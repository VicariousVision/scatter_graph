from fastapi import APIRouter

from . import conversations, documents, graph, health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(documents.router)
api_router.include_router(graph.router)
api_router.include_router(conversations.router)
