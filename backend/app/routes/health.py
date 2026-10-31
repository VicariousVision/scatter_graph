from typing import Any

from fastapi import APIRouter, Request

from ..health import system_health

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    state = request.app.state
    return {**system_health(state.driver, state.settings), "ingestion": state.ingestion.summary()}
