"""Factories for the Neo4j driver, the Gemma LLM and the embedding model (all via Ollama)."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from functools import lru_cache
from typing import Any, Optional

import neo4j
from neo4j_graphrag.embeddings.ollama import OllamaEmbeddings
from neo4j_graphrag.llm.ollama_llm import OllamaLLM
from neo4j_graphrag.llm.types import LLMResponse

from .config import Settings, get_settings

logger = logging.getLogger(__name__)

# Gemma 4 may emit an empty thought block ("<|channel>thought\n<channel|>") before the
# answer even with thinking disabled. Ollama normally strips it; this is a safety net.
_THOUGHT_BLOCK = re.compile(r"^\s*<\|channel>\s*thought.*?<channel\|>\s*", re.DOTALL)


class GemmaOllamaLLM(OllamaLLM):
    """OllamaLLM with two fixes for local use.

    1. neo4j-graphrag 1.23's async path sends the whole ``model_params`` dict as Ollama
       ``options``, so ``format``/``think``/``num_ctx`` are silently ignored. SimpleKGPipeline
       only calls ``ainvoke``, so we route it through the (correct) sync path in a thread.
    2. An optional cap on concurrent calls, so extraction doesn't flood a laptop GPU.
    """

    def __init__(self, *args: Any, max_concurrency: Optional[int] = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._slots = threading.BoundedSemaphore(max_concurrency) if max_concurrency else None

    def invoke(  # type: ignore[override]
        self,
        input: Any,
        message_history: Any = None,
        system_instruction: Optional[str] = None,
        response_format: Any = None,
        **kwargs: Any,
    ) -> LLMResponse:
        if self._slots is None:
            response = super().invoke(input, message_history, system_instruction, response_format, **kwargs)
        else:
            with self._slots:
                response = super().invoke(input, message_history, system_instruction, response_format, **kwargs)
        cleaned = _THOUGHT_BLOCK.sub("", response.content or "", count=1)
        return LLMResponse(content=cleaned, usage=response.usage)

    async def ainvoke(  # type: ignore[override]
        self,
        input: Any,
        message_history: Any = None,
        system_instruction: Optional[str] = None,
        response_format: Any = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return await asyncio.to_thread(
            self.invoke, input, message_history, system_instruction, response_format, **kwargs
        )


class PrefixedOllamaEmbeddings(OllamaEmbeddings):
    """OllamaEmbeddings that prepends embeddinggemma's task prefix to every text."""

    def __init__(self, model: str, prefix: str = "", **kwargs: Any) -> None:
        super().__init__(model=model, **kwargs)
        self.prefix = prefix

    def embed_query(self, text: str, **kwargs: Any) -> list[float]:
        return super().embed_query(self.prefix + text, **kwargs)

    async def async_embed_query(self, text: str, **kwargs: Any) -> list[float]:
        return await super().async_embed_query(self.prefix + text, **kwargs)


@lru_cache
def get_driver() -> neo4j.Driver:
    s = get_settings()
    return neo4j.GraphDatabase.driver(
        s.neo4j_uri,
        auth=(s.neo4j_username, s.neo4j_password),
        connection_timeout=5.0,
    )


def _model_params(s: Settings, temperature: float, json_output: bool) -> dict[str, Any]:
    params: dict[str, Any] = {
        "options": {"temperature": temperature, "num_ctx": s.ollama_num_ctx},
        "keep_alive": s.ollama_keep_alive,
        "think": s.ollama_think,
    }
    if json_output:
        params["format"] = "json"
    return params


def make_extraction_llm(s: Settings | None = None) -> GemmaOllamaLLM:
    """Deterministic, JSON-constrained LLM for schema and entity/relation extraction."""
    s = s or get_settings()
    return GemmaOllamaLLM(
        model_name=s.llm_model,
        model_params=_model_params(s, temperature=0.0, json_output=True),
        max_concurrency=s.extraction_concurrency,
        host=s.ollama_host,
        timeout=s.ollama_timeout_seconds,
    )


def make_chat_llm(s: Settings | None = None) -> GemmaOllamaLLM:
    """LLM used by GraphRAG for answers and for summarising the chat history."""
    s = s or get_settings()
    return GemmaOllamaLLM(
        model_name=s.llm_model,
        model_params=_model_params(s, temperature=s.chat_temperature, json_output=False),
        host=s.ollama_host,
        timeout=s.ollama_timeout_seconds,
    )


def make_document_embedder(s: Settings | None = None) -> PrefixedOllamaEmbeddings:
    s = s or get_settings()
    return PrefixedOllamaEmbeddings(
        model=s.embedding_model, prefix=s.embedding_document_prefix, host=s.ollama_host
    )


def make_query_embedder(s: Settings | None = None) -> PrefixedOllamaEmbeddings:
    s = s or get_settings()
    return PrefixedOllamaEmbeddings(
        model=s.embedding_model, prefix=s.embedding_query_prefix, host=s.ollama_host
    )
