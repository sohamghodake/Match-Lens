"""Application settings, read from environment variables (and `.env` when present).

Switching LLM provider means changing LLM_BASE_URL, LLM_API_KEY and LLM_MODEL only;
see `.env.example` at the repo root for the three supported setups.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Every vector column is this wide. bge-small-en-v1.5 is natively 384-d and
# text-embedding-3-small is asked for 384 dimensions, so switching providers never
# changes the schema (it does mean re-embedding, since the vector spaces differ).
EMBED_DIM = 384

DEFAULT_EMBED_MODELS = {
    "local": "BAAI/bge-small-en-v1.5",
    "openai": "text-embedding-3-small",
}

# The repo-root .env, shared with docker compose. Real environment variables win.
# (Inside the backend container this resolves to /.env, which doesn't exist; compose
# passes the variables in directly.)
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # Postgres. Plain `postgresql://...?sslmode=require` URLs (as Neon gives them)
    # are accepted and converted for asyncpg.
    database_url: str = "postgresql+asyncpg://matchlens:matchlens@localhost:5440/matchlens"

    # Comma-separated list of origins allowed to call the API from a browser.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3100"]

    # LLM: any OpenAI-compatible endpoint (OpenAI, local Ollama, Ollama cloud).
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: SecretStr = SecretStr("ollama")
    llm_model: str = "qwen2.5:3b"
    # Cheaper model for bulk calls such as skill extraction; falls back to llm_model.
    llm_model_fast: str | None = None
    llm_timeout_seconds: float = 120.0
    # SDK-level retries for connection errors, 429s and 5xx responses.
    llm_max_retries: int = 2

    # Embeddings.
    embed_provider: Literal["local", "openai"] = "local"
    embed_model: str | None = None  # defaults per provider, see DEFAULT_EMBED_MODELS
    embed_base_url: str = "https://api.openai.com/v1"
    embed_api_key: SecretStr | None = None  # required when embed_provider=openai
    embed_cache_dir: str | None = None  # where fastembed keeps downloaded models

    # Job ingestion. Skills always come from the free dictionary scan; the LLM pass is
    # an optional extra, capped per run (meant for a local model; see ingestion/).
    ingest_llm_skills: bool = False
    ingest_llm_max_jobs: int = 25

    # Matching. Re-ranking sends the top candidates to the LLM in one compact call.
    match_candidates: int = 100  # stage 1: nearest jobs by vector similarity
    match_rerank_top: int = 20  # stage 3: how many the LLM scores (and the API returns)
    match_cache_hours: float = 12
    # "low" keeps gpt-oss's hidden reasoning small (it counts against tokens/minute).
    # Leave empty for models that don't accept the parameter.
    match_reasoning_effort: str | None = "low"
    match_rerank_fast: bool = False  # use LLM_MODEL_FAST for re-ranking

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, value: str) -> str:
        return to_asyncpg_url(value)

    @field_validator("llm_model_fast", "embed_model", "match_reasoning_effort", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _fill_defaults(self) -> "Settings":
        if self.embed_model is None:
            self.embed_model = DEFAULT_EMBED_MODELS[self.embed_provider]
        if self.llm_model_fast is None:
            self.llm_model_fast = self.llm_model
        return self


def to_asyncpg_url(url: str) -> str:
    """Rewrite a libpq-style Postgres URL into one SQLAlchemy's asyncpg driver accepts.

    asyncpg rejects libpq-only query parameters (`sslmode`, `channel_binding`), which
    Neon includes in its connection strings, so `sslmode` becomes `ssl` and the rest go.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql", "postgresql+psycopg", "postgresql+psycopg2"):
        scheme = "postgresql+asyncpg"
    query = []
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        if key == "sslmode":
            query.append(("ssl", val))
        elif key != "channel_binding":
            query.append((key, val))
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@lru_cache
def get_settings() -> Settings:
    return Settings()
