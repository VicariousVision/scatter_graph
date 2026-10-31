import re
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Convert Neo4j values (temporal types, spatial points, ...) into JSON-friendly values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if hasattr(value, "iso_format"):
        return value.iso_format()
    return str(value)


def public_properties(props: dict[str, Any] | None) -> dict[str, Any]:
    """Drop internal properties (``__tmp_internal_id``, embeddings, ...)."""
    return {
        k: to_jsonable(v)
        for k, v in (props or {}).items()
        if not k.startswith("__") and k != "embedding"
    }


_NON_WORD = re.compile(r"[^\w\s]+", re.UNICODE)


def to_fulltext_query(text: str) -> str:
    """Make free text safe for a Lucene fulltext query.

    Neo4j parses fulltext queries with Lucene syntax, so characters such as ``/ : ( " -``
    or a trailing ``NOT`` raise parse errors. Lower-cased plain words avoid that while
    keeping keyword matching intact.
    """
    words = _NON_WORD.sub(" ", text).lower().split()
    return " ".join(words) or "document"
