from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

# Names of the indexes the retriever searches. Both index the lexical-graph Chunk nodes
# written by SimpleKGPipeline (label "Chunk", properties "embedding" and "text").
VECTOR_INDEX_NAME = "chunk_embeddings"
FULLTEXT_INDEX_NAME = "chunk_fulltext"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    neo4j_uri: str = "neo4j://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"

    ollama_host: str = "http://localhost:11434"
    llm_model: str = "gemma4:12b"
    embedding_model: str = "embeddinggemma:300m"
    embedding_dimensions: int = 768
    # embeddinggemma is trained with task prefixes; they improve retrieval quality.
    embedding_query_prefix: str = "task: search result | query: "
    embedding_document_prefix: str = "title: none | text: "
    ollama_num_ctx: int = 16384
    ollama_think: bool = False
    ollama_keep_alive: str = "30m"
    ollama_timeout_seconds: float = 900

    chunk_size: int = 1200
    chunk_overlap: int = 150
    extraction_concurrency: int = 2
    schema_sample_chars: int = 12000
    max_upload_mb: int = 50

    retrieval_top_k: int = 6
    chat_temperature: float = 0.2
    history_window: int = 10

    cors_origins: list[str] = ["http://localhost:5173"]

    @property
    def upload_dir(self) -> Path:
        return BACKEND_DIR / "data" / "uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
