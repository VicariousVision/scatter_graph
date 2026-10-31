"""Vector and fulltext indexes on the Chunk nodes that SimpleKGPipeline writes."""

import neo4j
from neo4j_graphrag.indexes import create_fulltext_index, create_vector_index

from .config import FULLTEXT_INDEX_NAME, VECTOR_INDEX_NAME, Settings


def ensure_indexes(driver: neo4j.Driver, s: Settings) -> None:
    """Create both indexes if missing (idempotent: uses IF NOT EXISTS)."""
    create_vector_index(
        driver,
        VECTOR_INDEX_NAME,
        label="Chunk",
        embedding_property="embedding",
        dimensions=s.embedding_dimensions,
        similarity_fn="cosine",
        neo4j_database=s.neo4j_database,
    )
    create_fulltext_index(
        driver,
        FULLTEXT_INDEX_NAME,
        label="Chunk",
        node_properties=["text"],
        neo4j_database=s.neo4j_database,
    )


def index_states(driver: neo4j.Driver, s: Settings) -> dict[str, str]:
    """Return {index name: state} for the two indexes the app needs."""
    records, _, _ = driver.execute_query(
        "SHOW INDEXES YIELD name, state WHERE name IN $names RETURN name, state",
        names=[VECTOR_INDEX_NAME, FULLTEXT_INDEX_NAME],
        database_=s.neo4j_database,
    )
    return {r["name"]: r["state"] for r in records}
