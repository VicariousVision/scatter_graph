"""System status: Neo4j, APOC, indexes, Ollama and the two models."""

import logging
from typing import Any

import httpx
import neo4j

from .config import FULLTEXT_INDEX_NAME, VECTOR_INDEX_NAME, Settings
from .indexes import ensure_indexes, index_states

logger = logging.getLogger(__name__)


def _component(ok: bool, detail: str) -> dict[str, Any]:
    return {"ok": ok, "detail": detail}


def _model_present(wanted: str, available: set[str]) -> bool:
    name = wanted if ":" in wanted else f"{wanted}:latest"
    return name in available or wanted in available


def _single(driver: neo4j.Driver, s: Settings, query: str) -> neo4j.Record:
    # A plain session fails fast; execute_query would retry for up to 30s when Neo4j is down.
    with driver.session(database=s.neo4j_database) as session:
        record = session.run(query).single()
    if record is None:
        raise RuntimeError("empty result")
    return record


def check_neo4j(driver: neo4j.Driver, s: Settings) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        r = _single(
            driver, s, "CALL dbms.components() YIELD name, versions, edition RETURN name, versions[0] AS version, edition"
        )
        out["neo4j"] = _component(True, f"{r['name']} {r['version']} ({r['edition']}) at {s.neo4j_uri}")
    except neo4j.exceptions.AuthError:
        out["neo4j"] = _component(False, "Authentication failed: check NEO4J_USERNAME / NEO4J_PASSWORD in backend/.env")
        return out
    except Exception as exc:
        out["neo4j"] = _component(False, f"Cannot reach Neo4j at {s.neo4j_uri}: {type(exc).__name__}")
        return out

    try:
        out["apoc"] = _component(True, f"APOC {_single(driver, s, 'RETURN apoc.version() AS v')['v']}")
    except Exception:
        out["apoc"] = _component(False, "APOC plugin not installed (Neo4j Desktop: DBMS > Plugins > APOC)")

    try:
        states = index_states(driver, s)
        if len(states) < 2:
            ensure_indexes(driver, s)  # self-heal if Neo4j was down when the API started
            states = index_states(driver, s)
        missing = [n for n in (VECTOR_INDEX_NAME, FULLTEXT_INDEX_NAME) if states.get(n) != "ONLINE"]
        out["indexes"] = (
            _component(True, "Vector and fulltext indexes online")
            if not missing
            else _component(False, f"Not online yet: {', '.join(f'{n} ({states.get(n, 'missing')})' for n in missing)}")
        )
    except Exception as exc:
        out["indexes"] = _component(False, f"Could not check indexes: {exc}")
    return out


def check_ollama(s: Settings) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        with httpx.Client(base_url=s.ollama_host, timeout=3.0) as client:
            version = client.get("/api/version").json().get("version", "?")
            tags = client.get("/api/tags").json().get("models", [])
    except Exception as exc:
        out["ollama"] = _component(False, f"Cannot reach Ollama at {s.ollama_host}: {type(exc).__name__}")
        return out

    available = {m.get("name") for m in tags} | {m.get("model") for m in tags}
    out["ollama"] = _component(True, f"Ollama {version} at {s.ollama_host}")
    for key, model in (("llm", s.llm_model), ("embedder", s.embedding_model)):
        out[key] = (
            _component(True, f"{model} ready")
            if _model_present(model, available)
            else _component(False, f"{model} not pulled: run `ollama pull {model}`")
        )
    return out


def system_health(driver: neo4j.Driver, s: Settings) -> dict[str, Any]:
    components = {**check_neo4j(driver, s), **check_ollama(s)}
    for key in ("neo4j", "apoc", "indexes", "ollama", "llm", "embedder"):
        components.setdefault(key, _component(False, "Unavailable"))
    return {
        "ok": all(c["ok"] for c in components.values()),
        "components": components,
        "models": {"llm": s.llm_model, "embedder": s.embedding_model},
    }
