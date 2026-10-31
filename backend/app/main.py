"""FastAPI entry point: REST API under /api, plus the built React UI at / (if built)."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import neo4j
import ollama
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from neo4j_graphrag.exceptions import EmbeddingsGenerationError, LLMGenerationError

from .chat import ChatService
from .clients import get_driver
from .config import PROJECT_DIR, get_settings
from .indexes import ensure_indexes
from .ingest import IngestionService
from .routes import api_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)  # e.g. "unknown label" on an empty DB
logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per Ollama request otherwise
logger = logging.getLogger("app")

FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    driver = get_driver()
    app.state.settings = settings
    app.state.driver = driver
    app.state.ingestion = IngestionService(settings, driver)
    app.state.chat = ChatService(settings, driver)
    try:
        ensure_indexes(driver, settings)
    except Exception as exc:  # Neo4j may start after the API; /api/health retries
        logger.warning("Could not create indexes yet (%s). Check Neo4j and backend/.env.", exc)
    await app.state.ingestion.start()
    logger.info("Legal GraphRAG ready: LLM=%s, embeddings=%s", settings.llm_model, settings.embedding_model)
    yield
    await app.state.ingestion.stop()
    driver.close()


app = FastAPI(title="Legal GraphRAG", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


@app.exception_handler(neo4j.exceptions.AuthError)
async def _neo4j_auth(_: Request, exc: Exception) -> JSONResponse:
    return _error(503, "Neo4j authentication failed. Check NEO4J_USERNAME and NEO4J_PASSWORD in backend/.env.")


@app.exception_handler(neo4j.exceptions.ServiceUnavailable)
async def _neo4j_down(_: Request, exc: Exception) -> JSONResponse:
    return _error(503, f"Neo4j is not reachable at {get_settings().neo4j_uri}. Is the DBMS started?")


@app.exception_handler(ConnectionError)
async def _ollama_down(_: Request, exc: Exception) -> JSONResponse:
    return _error(503, f"Ollama is not reachable at {get_settings().ollama_host}. Is Ollama running?")


@app.exception_handler(httpx.TimeoutException)
async def _llm_timeout(_: Request, exc: Exception) -> JSONResponse:
    return _error(504, "The language model took too long to respond. Try again, or raise OLLAMA_TIMEOUT_SECONDS.")


@app.exception_handler(ollama.ResponseError)
@app.exception_handler(LLMGenerationError)
@app.exception_handler(EmbeddingsGenerationError)
async def _llm_error(_: Request, exc: Exception) -> JSONResponse:
    return _error(502, f"The model request failed: {exc}")


@app.exception_handler(Exception)
async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error")
    return _error(500, f"{type(exc).__name__}: {exc}")


if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")
else:

    @app.get("/", include_in_schema=False)
    def _ui_not_built() -> HTMLResponse:
        return HTMLResponse(
            "<h3>The UI has not been built.</h3><p>Run <code>bash setup.sh</code>, or start the dev UI with "
            "<code>bash start.sh --dev</code> and open http://localhost:5173.</p><p>API docs: <a href='/docs'>/docs</a></p>"
        )
