"""Graph-grounded question answering (HybridCypherRetriever + GraphRAG) and conversations."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from typing import Any, Optional

import neo4j
from neo4j_graphrag.generation import GraphRAG
from neo4j_graphrag.message_history import Neo4jMessageHistory
from neo4j_graphrag.retrievers import HybridCypherRetriever
from neo4j_graphrag.types import LLMMessage, RawSearchResult, RetrieverResult, RetrieverResultItem

from .clients import make_chat_llm, make_query_embedder
from .config import FULLTEXT_INDEX_NAME, VECTOR_INDEX_NAME, Settings
from .prompts import LEGAL_RAG_TEMPLATE, NO_ANSWER
from .utils import public_properties, to_fulltext_query, to_jsonable

logger = logging.getLogger(__name__)

# Appended by HybridCypherRetriever after the hybrid (vector + fulltext) search over Chunk
# nodes; `node` is the matched chunk and `score` its hybrid score. For each chunk we pull
# its source document, the entities extracted from it, and their relationships (both
# inside the chunk and to entities found in other chunks or documents).
RETRIEVAL_QUERY = """
WITH node AS chunk, score
MATCH (chunk)-[:FROM_DOCUMENT]->(doc:Document)
WITH chunk, score, doc,
     COLLECT {
       MATCH (chunk)<-[:FROM_CHUNK]-(e:__Entity__)
       RETURN DISTINCT e LIMIT 25
     } AS entities
WITH chunk, score, doc, entities,
     COLLECT {
       UNWIND entities AS e
       MATCH (e)-[r]-(other:__Entity__)
       WITH DISTINCT r, other IN entities AS local
       ORDER BY local DESC
       RETURN r LIMIT 40
     } AS rels
RETURN
  chunk.text AS text,
  chunk.index AS chunkIndex,
  elementId(chunk) AS chunkId,
  score,
  doc.documentId AS documentId,
  coalesce(doc.fileName, doc.path) AS fileName,
  [e IN entities | {
     id: elementId(e), name: e.name,
     label: head([l IN labels(e) WHERE NOT l STARTS WITH '__']),
     properties: properties(e)
  }] AS entities,
  [r IN rels | {
     id: elementId(r), type: type(r), properties: properties(r),
     source: elementId(startNode(r)), sourceName: startNode(r).name,
     sourceLabel: head([l IN labels(startNode(r)) WHERE NOT l STARTS WITH '__']),
     target: elementId(endNode(r)), targetName: endNode(r).name,
     targetLabel: head([l IN labels(endNode(r)) WHERE NOT l STARTS WITH '__'])
  }] AS relationships
"""


def _props_text(props: dict[str, Any]) -> str:
    items = [f"{k}: {v}" for k, v in public_properties(props).items() if k != "name" and v not in (None, "")]
    return "; ".join(items)


def format_record(record: neo4j.Record) -> RetrieverResultItem:
    """Turn one retrieved chunk into LLM context text plus metadata for the UI."""
    file_name = record["fileName"] or "unknown document"
    lines = [f"--- Source: [{file_name}] (excerpt {int(record['chunkIndex'] or 0) + 1}) ---", record["text"] or ""]

    rels = record["relationships"] or []
    if rels:
        lines.append("Knowledge graph facts:")
        for r in rels:
            detail = _props_text(r["properties"])
            lines.append(
                f"- {r['sourceName']} ({r['sourceLabel']}) -[{r['type']}]-> {r['targetName']} ({r['targetLabel']})"
                + (f" [{detail}]" if detail else "")
            )
    details = [(e, _props_text(e["properties"])) for e in record["entities"] or []]
    details = [(e, d) for e, d in details if d]
    if details:
        lines.append("Entity details:")
        lines.extend(f"- {e['name']} ({e['label']}): {d}" for e, d in details)

    return RetrieverResultItem(
        content="\n".join(lines) + "\n",
        metadata={
            "document_id": record["documentId"],
            "file_name": file_name,
            "chunk_id": record["chunkId"],
            "chunk_index": record["chunkIndex"],
            "score": record["score"],
            "text": record["text"],
            "entities": record["entities"],
            "relationships": rels,
        },
    )


class LegalHybridRetriever(HybridCypherRetriever):
    """HybridCypherRetriever whose fulltext half receives a Lucene-safe query.

    The vector half still embeds the original question text.
    """

    def get_search_results(self, query_text: str, query_vector: Optional[list[float]] = None, **kwargs: Any) -> RawSearchResult:  # type: ignore[override]
        if query_vector is None and self.embedder is not None:
            query_vector = self.embedder.embed_query(query_text)
        return super().get_search_results(
            query_text=to_fulltext_query(query_text), query_vector=query_vector, **kwargs
        )


def summarize_context(result: Optional[RetrieverResult]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Sources (one per retrieved chunk) and the retrieved subgraph for the UI."""
    sources: list[dict[str, Any]] = []
    nodes: dict[str, dict[str, Any]] = {}
    links: dict[str, dict[str, Any]] = {}
    for item in result.items if result else []:
        md = item.metadata or {}
        text = md.get("text") or ""
        sources.append(
            {
                "document_id": md.get("document_id"),
                "file_name": md.get("file_name"),
                "chunk_index": md.get("chunk_index"),
                "score": round(float(md.get("score") or 0), 4),
                "snippet": text[:400] + ("…" if len(text) > 400 else ""),
            }
        )
        for e in md.get("entities") or []:
            nodes[e["id"]] = {"id": e["id"], "name": e["name"], "label": e["label"], "properties": public_properties(e["properties"])}
        for r in md.get("relationships") or []:
            nodes.setdefault(r["source"], {"id": r["source"], "name": r["sourceName"], "label": r["sourceLabel"], "properties": {}})
            nodes.setdefault(r["target"], {"id": r["target"], "name": r["targetName"], "label": r["targetLabel"], "properties": {}})
            links[r["id"]] = {
                "id": r["id"],
                "type": r["type"],
                "source": r["source"],
                "target": r["target"],
                "properties": public_properties(r["properties"]),
            }
    return sources, {"nodes": list(nodes.values()), "links": list(links.values())}


_CONVERSATION_EXISTS = "MATCH (s:Session {id: $id}) WHERE NOT s:__Entity__ RETURN s.title AS title"

_SET_TITLE = "MATCH (s:Session {id: $id}) WHERE NOT s:__Entity__ SET s.title = $title"

_LIST_CONVERSATIONS = """
MATCH (s:Session)
WHERE NOT s:__Entity__
OPTIONAL MATCH (s)-[:LAST_MESSAGE]->(newest:Message)
RETURN s.id AS id, coalesce(s.title, 'New conversation') AS title,
       s.createdAt AS createdAt, coalesce(newest.createdAt, s.createdAt) AS updatedAt
ORDER BY updatedAt DESC
"""

# Neo4jMessageHistory keeps messages as a linked list: (Session)-[:LAST_MESSAGE]->(Message)
# and (older)-[:NEXT]->(newer).
_MESSAGES = """
MATCH (s:Session {id: $id})-[:LAST_MESSAGE]->(newest:Message)
MATCH p = (oldest:Message)-[:NEXT*0..]->(newest)
WHERE NOT EXISTS { (:Message)-[:NEXT]->(oldest) }
UNWIND nodes(p) AS m
RETURN elementId(m) AS id, m.role AS role, m.content AS content, m.createdAt AS createdAt,
       m.sources AS sources, m.graph AS graph
"""

_ANNOTATE_LAST = """
MATCH (s:Session {id: $id})-[:LAST_MESSAGE]->(m:Message)
SET m.sources = $sources, m.graph = $graph
RETURN elementId(m) AS id, m.createdAt AS createdAt
"""


class ChatService:
    def __init__(self, settings: Settings, driver: neo4j.Driver) -> None:
        self._s = settings
        self._driver = driver
        self._rag: Optional[GraphRAG] = None
        self._lock = threading.Lock()

    def _get_rag(self) -> GraphRAG:
        # Built lazily: the retriever reads the vector index definition when created.
        with self._lock:
            if self._rag is None:
                retriever = LegalHybridRetriever(
                    driver=self._driver,
                    vector_index_name=VECTOR_INDEX_NAME,
                    fulltext_index_name=FULLTEXT_INDEX_NAME,
                    retrieval_query=RETRIEVAL_QUERY,
                    embedder=make_query_embedder(self._s),
                    result_formatter=format_record,
                    neo4j_database=self._s.neo4j_database,
                )
                self._rag = GraphRAG(retriever=retriever, llm=make_chat_llm(self._s), prompt_template=LEGAL_RAG_TEMPLATE)
            return self._rag

    def _history(self, conversation_id: str, window: Optional[int] = None) -> Neo4jMessageHistory:
        return Neo4jMessageHistory(
            session_id=conversation_id, driver=self._driver, window=window, database=self._s.neo4j_database
        )

    # ---- conversations ----------------------------------------------------------------

    def create_conversation(self, title: Optional[str] = None) -> dict[str, Any]:
        conversation_id = uuid.uuid4().hex
        self._history(conversation_id)  # creates the Session node
        if title:
            self._run(_SET_TITLE, id=conversation_id, title=title)
        return self.get_conversation(conversation_id) or {}

    def list_conversations(self) -> list[dict[str, Any]]:
        return [
            {"id": r["id"], "title": r["title"], "created_at": to_jsonable(r["createdAt"]), "updated_at": to_jsonable(r["updatedAt"])}
            for r in self._run(_LIST_CONVERSATIONS)
        ]

    def get_conversation(self, conversation_id: str) -> Optional[dict[str, Any]]:
        found = self._run(_CONVERSATION_EXISTS, id=conversation_id)
        if not found:
            return None
        messages = [
            {
                "id": r["id"],
                "role": r["role"],
                "content": r["content"],
                "created_at": to_jsonable(r["createdAt"]),
                "sources": json.loads(r["sources"]) if r["sources"] else [],
                "graph": json.loads(r["graph"]) if r["graph"] else None,
            }
            for r in self._run(_MESSAGES, id=conversation_id)
        ]
        return {"id": conversation_id, "title": found[0]["title"] or "New conversation", "messages": messages}

    # ---- question answering -----------------------------------------------------------

    def ask(self, conversation_id: str, question: str) -> Optional[dict[str, Any]]:
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            return None

        history = self._history(conversation_id, window=self._s.history_window)
        result = self._get_rag().search(
            query_text=question,
            message_history=history,
            retriever_config={"top_k": self._s.retrieval_top_k},
            return_context=True,
            response_fallback=NO_ANSWER,
        )
        answer = (result.answer or "").strip() or NO_ANSWER
        sources, graph = summarize_context(result.retriever_result)

        history.add_messages(
            [LLMMessage(role="user", content=question), LLMMessage(role="assistant", content=answer)]
        )
        saved = self._run(_ANNOTATE_LAST, id=conversation_id, sources=json.dumps(sources), graph=json.dumps(graph))
        if not conversation["messages"] and conversation["title"] == "New conversation":
            self._run(_SET_TITLE, id=conversation_id, title=_title_from(question))

        return {
            "id": saved[0]["id"] if saved else uuid.uuid4().hex,
            "role": "assistant",
            "content": answer,
            "created_at": to_jsonable(saved[0]["createdAt"]) if saved else None,
            "sources": sources,
            "graph": graph,
        }

    def _run(self, query: str, **params: Any) -> list[neo4j.Record]:
        records, _, _ = self._driver.execute_query(query, params, database_=self._s.neo4j_database)
        return records


def _title_from(question: str) -> str:
    title = " ".join(question.split())
    return title if len(title) <= 60 else title[:57].rstrip() + "..."
