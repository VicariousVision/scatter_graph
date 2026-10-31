"""Read-only graph queries for the UI. Only entity nodes are shown, not chunks or documents."""

from typing import Any, Optional

import neo4j

from .config import Settings
from .utils import public_properties

# Filters shared by the count and the node queries.
_ENTITY_FILTER = """
MATCH (n:__Entity__)
WHERE ($documentId IS NULL OR EXISTS {
        MATCH (n)-[:FROM_CHUNK]->(:Chunk)-[:FROM_DOCUMENT]->(d:Document)
        WHERE d.documentId = $documentId })
  AND (size($types) = 0 OR any(l IN labels(n) WHERE l IN $types))
"""

_COUNT = _ENTITY_FILTER + "RETURN count(n) AS total"

_NODES = (
    _ENTITY_FILTER
    + """
WITH n, COUNT { (n)--(:__Entity__) } AS degree
ORDER BY degree DESC, elementId(n)
LIMIT $limit
RETURN elementId(n) AS id, n.name AS name,
       head([l IN labels(n) WHERE NOT l STARTS WITH '__']) AS label,
       properties(n) AS properties, degree,
       COLLECT {
         MATCH (n)-[:FROM_CHUNK]->(:Chunk)-[:FROM_DOCUMENT]->(d:Document)
         RETURN DISTINCT d.documentId
       } AS documents
"""
)

_LINKS = """
MATCH (a:__Entity__)-[r]->(b:__Entity__)
WHERE elementId(a) IN $ids AND elementId(b) IN $ids
RETURN elementId(r) AS id, type(r) AS type, elementId(a) AS source, elementId(b) AS target,
       properties(r) AS properties
"""

_ENTITY_TYPES = """
MATCH (n:__Entity__)
UNWIND [l IN labels(n) WHERE NOT l STARTS WITH '__'] AS label
RETURN label, count(*) AS count
ORDER BY count DESC, label
"""


def get_graph(
    driver: neo4j.Driver,
    s: Settings,
    document_id: Optional[str] = None,
    types: Optional[list[str]] = None,
    limit: int = 500,
) -> dict[str, Any]:
    params = {"documentId": document_id, "types": types or [], "limit": limit}
    db = s.neo4j_database
    total = driver.execute_query(_COUNT, params, database_=db).records[0]["total"]
    node_records = driver.execute_query(_NODES, params, database_=db).records
    nodes = [
        {
            "id": r["id"],
            "name": r["name"] or "(unnamed)",
            "label": r["label"] or "Entity",
            "properties": public_properties(r["properties"]),
            "degree": r["degree"],
            "documents": r["documents"],
        }
        for r in node_records
    ]
    ids = [n["id"] for n in nodes]
    links = (
        [
            {
                "id": r["id"],
                "type": r["type"],
                "source": r["source"],
                "target": r["target"],
                "properties": public_properties(r["properties"]),
            }
            for r in driver.execute_query(_LINKS, {"ids": ids}, database_=db).records
        ]
        if ids
        else []
    )
    return {"nodes": nodes, "links": links, "total_nodes": total, "truncated": total > len(nodes)}


def get_entity_types(driver: neo4j.Driver, s: Settings) -> list[dict[str, Any]]:
    records = driver.execute_query(_ENTITY_TYPES, database_=s.neo4j_database).records
    return [{"label": r["label"], "count": r["count"]} for r in records]
