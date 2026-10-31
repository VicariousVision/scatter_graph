from typing import Any, Optional

from fastapi import APIRouter, Query, Request

from ..graph import get_entity_types, get_graph

router = APIRouter(tags=["graph"])


@router.get("/graph")
def graph(
    request: Request,
    document_id: Optional[str] = None,
    types: Optional[str] = Query(None, description="Comma-separated entity labels"),
    limit: int = Query(500, ge=1, le=2000),
) -> dict[str, Any]:
    """Entity nodes (most connected first) and the relationships between them."""
    state = request.app.state
    type_list = [t.strip() for t in (types or "").split(",") if t.strip()]
    return get_graph(state.driver, state.settings, document_id or None, type_list, limit)


@router.get("/graph/meta")
def graph_meta(request: Request) -> dict[str, Any]:
    """Values for the graph filters."""
    state = request.app.state
    documents = [
        {"id": d["id"], "file_name": d["file_name"], "entities": d["entities"]}
        for d in state.ingestion.list_documents()
        if d.get("status") == "done"
    ]
    return {"entity_types": get_entity_types(state.driver, state.settings), "documents": documents}
