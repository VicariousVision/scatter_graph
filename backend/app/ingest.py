"""PDF ingestion: legal schema extraction, then SimpleKGPipeline, one document at a time."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Union

import neo4j
from neo4j_graphrag.components.data_loader import PdfLoader
from neo4j_graphrag.components.schema import GraphSchema, SchemaFromTextExtractor
from neo4j_graphrag.components.text_splitters.fixed_size_splitter import FixedSizeSplitter
from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline
from neo4j_graphrag.experimental.pipeline.notification import Event, EventType
from neo4j_graphrag.llm import LLMInterface

from .clients import make_document_embedder, make_extraction_llm
from .config import Settings
from .prompts import RESERVED_LABELS, LegalERExtractionTemplate, LegalSchemaExtractionTemplate

logger = logging.getLogger(__name__)

# Human-readable stage for each SimpleKGPipeline component.
PIPELINE_STAGES = {
    "file_loader": "Reading PDF",
    "splitter": "Splitting into chunks",
    "chunk_embedder": "Embedding chunks",
    "schema": "Applying schema",
    "extractor": "Extracting entities and relationships",
    "pruner": "Cleaning extracted graph",
    "writer": "Writing to Neo4j",
    "resolver": "Merging duplicate entities",
}


class IngestionError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    file_name: str
    file_path: Path
    file_hash: str
    file_size: int
    uploaded_at: str = field(default_factory=_now)
    status: str = "queued"  # queued | processing | done | failed
    stage: str = "Waiting in queue"
    error: Optional[str] = None
    finished_at: Optional[str] = None

    def metadata(self) -> dict[str, str]:
        """Properties stored on the Document node (PdfLoader expects string values)."""
        return {
            "documentId": self.id,
            "fileName": self.file_name,
            "fileHash": self.file_hash,
            "fileSize": str(self.file_size),
            "uploadedAt": self.uploaded_at,
        }

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("file_path")
        d.pop("file_hash")
        return d


# --------------------------------------------------------------------------------------
# Schema extraction
# --------------------------------------------------------------------------------------

_EXISTING_LABELS = """
MATCH (n:__Entity__)
UNWIND [l IN labels(n) WHERE NOT l STARTS WITH '__'] AS label
RETURN label, count(*) AS c ORDER BY c DESC LIMIT 30
"""

_EXISTING_REL_TYPES = """
MATCH (:__Entity__)-[r]->(:__Entity__)
RETURN type(r) AS type, count(*) AS c ORDER BY c DESC LIMIT 30
"""


def existing_schema_hint(driver: neo4j.Driver, s: Settings) -> str:
    """Describe the types already in the graph so new documents reuse the same labels."""
    labels, _, _ = driver.execute_query(_EXISTING_LABELS, database_=s.neo4j_database)
    rels, _, _ = driver.execute_query(_EXISTING_REL_TYPES, database_=s.neo4j_database)
    if not labels and not rels:
        return ""
    return (
        "Types that already exist in the knowledge graph (reuse these exact labels when they fit):\n"
        f"Node types: {', '.join(r['label'] for r in labels) or 'none'}\n"
        f"Relationship types: {', '.join(r['type'] for r in rels) or 'none'}"
    )


def sample_text(text: str, limit: int) -> str:
    """Start, middle and end of the document, so the schema sees more than the preamble."""
    if len(text) <= limit:
        return text
    part = limit // 3
    middle = len(text) // 2 - part // 2
    return "\n[...]\n".join([text[:part], text[middle : middle + part], text[-part:]])


def tidy_schema(schema: GraphSchema) -> GraphSchema:
    """Make an LLM-proposed schema safe and forgiving for a small local model.

    - drops reserved labels (Document, Chunk, Session, Message)
    - guarantees a ``name`` property (used for display and entity resolution)
    - allows extra properties and unlisted patterns, so valid facts aren't pruned
    - drops constraints, so a missing property never deletes an entity
    """
    node_types = []
    for nt in schema.node_types:
        if nt.label in RESERVED_LABELS:
            continue
        props = [{"name": p.name, "type": p.type, "description": p.description} for p in nt.properties]
        if not any(p["name"] == "name" for p in props):
            props.insert(0, {"name": "name", "type": "STRING", "description": ""})
        node_types.append(
            {"label": nt.label, "description": nt.description, "properties": props, "additional_properties": True}
        )
    labels = {nt["label"] for nt in node_types}
    relationship_types = [
        {
            "label": rt.label,
            "description": rt.description,
            "properties": [{"name": p.name, "type": p.type, "description": p.description} for p in rt.properties],
            "additional_properties": True,
        }
        for rt in schema.relationship_types
    ]
    patterns = [
        {"source": p.source, "relationship": p.relationship, "target": p.target}
        for p in schema.patterns
        if p.source in labels and p.target in labels
    ]
    return GraphSchema.model_validate(
        {
            "node_types": node_types,
            "relationship_types": relationship_types,
            "patterns": patterns,
            "additional_node_types": False,
            "additional_relationship_types": False,
            "additional_patterns": True,
        }
    )


async def extract_schema(
    llm: LLMInterface, driver: neo4j.Driver, s: Settings, text: str
) -> Union[GraphSchema, str]:
    """Automatic schema extraction on a sample of the document.

    SimpleKGPipeline's built-in ``schema="EXTRACTED"`` mode sends the *whole* document in
    one prompt, which overflows a local model's context window. We run the same library
    component on a sample instead, add legal guidance, and tell it which types the graph
    already has, so every new document fits the existing graph.
    """
    extractor = SchemaFromTextExtractor(llm=llm, prompt_template=LegalSchemaExtractionTemplate())
    try:
        hint = await asyncio.to_thread(existing_schema_hint, driver, s)
        schema = await extractor.run(text=sample_text(text, s.schema_sample_chars), examples=hint)
        schema = tidy_schema(schema)
    except Exception as exc:  # malformed JSON from the model, validation errors, ...
        logger.warning("Schema extraction failed (%s); continuing with schema-free extraction", exc)
        return "FREE"
    if not schema.node_types:
        return "FREE"
    logger.info(
        "Schema: nodes=%s relationships=%s",
        [n.label for n in schema.node_types],
        [r.label for r in schema.relationship_types],
    )
    return schema


# --------------------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------------------

_DOCUMENT_COUNTS = """
MATCH (d:Document {documentId: $id})
OPTIONAL MATCH (d)<-[:FROM_DOCUMENT]-(c:Chunk)
OPTIONAL MATCH (c)<-[:FROM_CHUNK]-(e:__Entity__)
RETURN count(DISTINCT c) AS chunks, count(DISTINCT e) AS entities
"""


async def ingest_pdf(
    path: Path,
    metadata: dict[str, str],
    s: Settings,
    driver: neo4j.Driver,
    on_stage: Callable[[str], None] = lambda _stage: None,
) -> dict[str, int]:
    """Parse one PDF and merge its entities and relationships into the graph."""
    on_stage("Reading PDF")
    loaded = await PdfLoader().run(filepath=str(path))
    if not loaded.text.strip():
        raise IngestionError("No text found in the PDF. Scanned (image-only) PDFs need OCR first.")

    llm = make_extraction_llm(s)
    on_stage("Extracting schema")
    schema = await extract_schema(llm, driver, s, loaded.text)

    kg_builder = SimpleKGPipeline(
        llm=llm,
        driver=driver,
        embedder=make_document_embedder(s),
        schema=schema,
        from_file=True,
        text_splitter=FixedSizeSplitter(chunk_size=s.chunk_size, chunk_overlap=s.chunk_overlap),
        prompt_template=LegalERExtractionTemplate(),
        perform_entity_resolution=True,
        on_error="IGNORE",  # a chunk with unparseable output is skipped, not fatal
        neo4j_database=s.neo4j_database,
    )

    async def report(event: Event) -> None:
        task = getattr(event, "task_name", None)
        if event.event_type == EventType.TASK_STARTED and task in PIPELINE_STAGES:
            on_stage(PIPELINE_STAGES[task])

    try:
        kg_builder.runner.pipeline.event_notifier.add_callback(report)
    except AttributeError:  # progress reporting is optional
        pass

    await kg_builder.run_async(file_path=str(path), document_metadata=metadata)

    records, _, _ = driver.execute_query(
        _DOCUMENT_COUNTS, id=metadata["documentId"], database_=s.neo4j_database
    )
    counts = {"chunks": records[0]["chunks"], "entities": records[0]["entities"]} if records else {}
    if not counts.get("chunks"):
        raise IngestionError("The pipeline finished but no chunks were written to Neo4j.")
    return counts


# --------------------------------------------------------------------------------------
# Background queue
# --------------------------------------------------------------------------------------

_DOCUMENTS = """
MATCH (d:Document)
WHERE d.documentId IS NOT NULL AND NOT d:__Entity__
OPTIONAL MATCH (d)<-[:FROM_DOCUMENT]-(c:Chunk)
OPTIONAL MATCH (c)<-[:FROM_CHUNK]-(e:__Entity__)
RETURN d.documentId AS id, d.fileName AS fileName, d.uploadedAt AS uploadedAt,
       d.fileSize AS fileSize, count(DISTINCT c) AS chunks, count(DISTINCT e) AS entities
"""

_FIND_BY_HASH = """
MATCH (d:Document {fileHash: $hash})
WHERE NOT d:__Entity__
RETURN d.fileName AS fileName LIMIT 1
"""


class IngestionService:
    """Queues uploaded PDFs and ingests them one at a time.

    One at a time keeps the local GPU from being overloaded and avoids two entity
    resolution passes merging the same nodes concurrently. Each job runs in a worker
    thread with its own event loop, because the pipeline makes blocking driver calls.
    """

    def __init__(self, settings: Settings, driver: neo4j.Driver) -> None:
        self._s = settings
        self._driver = driver
        self._jobs: dict[str, Job] = {}
        self._queue: Optional[asyncio.Queue[str]] = None
        self._worker: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        self._s.upload_dir.mkdir(parents=True, exist_ok=True)
        self._queue = asyncio.Queue()
        self._worker = asyncio.create_task(self._run_worker())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()

    # ---- submission -------------------------------------------------------------------

    def find_duplicate(self, file_hash: str) -> Optional[str]:
        for job in self._jobs.values():
            if job.file_hash == file_hash and job.status != "failed":
                return job.file_name
        records, _, _ = self._driver.execute_query(
            _FIND_BY_HASH, hash=file_hash, database_=self._s.neo4j_database
        )
        return records[0]["fileName"] if records else None

    def submit(self, file_name: str, data: bytes, file_hash: str) -> Job:
        assert self._queue is not None, "IngestionService.start() was not called"
        doc_id = uuid.uuid4().hex
        path = self._s.upload_dir / f"{doc_id}.pdf"
        path.write_bytes(data)
        job = Job(id=doc_id, file_name=file_name, file_path=path, file_hash=file_hash, file_size=len(data))
        self._jobs[doc_id] = job
        self._queue.put_nowait(doc_id)
        return job

    # ---- status -----------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        jobs = list(self._jobs.values())
        current = next((j for j in jobs if j.status == "processing"), None)
        return {
            "queued": sum(j.status == "queued" for j in jobs),
            "processing": sum(j.status == "processing" for j in jobs),
            "current": {"file_name": current.file_name, "stage": current.stage} if current else None,
        }

    def list_documents(self) -> list[dict[str, Any]]:
        """Documents stored in Neo4j merged with in-memory job state."""
        records, _, _ = self._driver.execute_query(_DOCUMENTS, database_=self._s.neo4j_database)
        docs: dict[str, dict[str, Any]] = {
            r["id"]: {
                "id": r["id"],
                "file_name": r["fileName"],
                "file_size": int(r["fileSize"] or 0),
                "uploaded_at": r["uploadedAt"],
                "status": "done",
                "stage": None,
                "error": None,
                "chunks": r["chunks"],
                "entities": r["entities"],
            }
            for r in records
        }
        for job in self._jobs.values():
            entry = docs.setdefault(job.id, {"chunks": 0, "entities": 0})
            entry.update(job.to_dict())
            if job.status == "done":
                entry["stage"] = None
        return sorted(docs.values(), key=lambda d: d.get("uploaded_at") or "", reverse=True)

    # ---- worker -----------------------------------------------------------------------

    async def _run_worker(self) -> None:
        assert self._queue is not None
        while True:
            doc_id = await self._queue.get()
            try:
                await asyncio.to_thread(self._process, self._jobs[doc_id])
            finally:
                self._queue.task_done()

    def _process(self, job: Job) -> None:
        job.status = "processing"

        def set_stage(stage: str) -> None:
            job.stage = stage

        logger.info("Ingesting %s (%s)", job.file_name, job.id)
        try:
            counts = asyncio.run(ingest_pdf(job.file_path, job.metadata(), self._s, self._driver, set_stage))
        except Exception as exc:
            logger.exception("Ingestion failed for %s", job.file_name)
            job.status, job.stage, job.error = "failed", None, f"{type(exc).__name__}: {exc}"
        else:
            logger.info("Ingested %s: %s", job.file_name, counts)
            job.status, job.stage = "done", None
        job.finished_at = _now()
