from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[2]

# Data folder location (moved under api/ for Azure Functions deployment)
DATA_ROOT = API_ROOT / "data"


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_env_files() -> None:
    # api/.env is highest priority (loaded first; subsequent files skip already-set keys)
    candidates = [
        API_ROOT / ".env",
        PROJECT_ROOT / ".env",
        Path.cwd() / ".env",
    ]
    for candidate in candidates:
        _load_env_file(candidate)


def _get_str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    trimmed = value.strip()
    return trimmed if trimmed != "" else default


def _get_int(name: str, default: int) -> int:
    raw = _get_str(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = _get_str(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = _get_str(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    env: str

    openai_api_key: str | None
    azure_openai_api_key: str | None
    azure_openai_endpoint: str | None
    azure_openai_api_version: str
    azure_openai_deployment: str | None
    azure_openai_embedding_deployment: str | None
    llm_provider: str
    model_name: str
    fallback_model_name: str
    temperature: float
    max_tokens: int

    embedding_model: str
    embedding_dimension: int

    qdrant_url: str | None
    qdrant_api_key: str | None
    qdrant_collection: str
    vector_backend: str
    supabase_vector_table: str
    supabase_vector_rpc: str
    supabase_vector_scan_limit: int

    retrieval_k: int
    retrieval_score_threshold: float
    retrieval_max_context_chars: int
    source_snippet_chars: int

    allowed_origins: str

    ingest_shared_secret: str | None
    ingest_max_file_bytes: int
    ingest_allowed_extensions: str

    rate_limit_enabled: bool
    rate_limit_window_seconds: int
    rate_limit_requests_per_window: int

    llm_timeout_seconds: int
    llm_circuit_fail_threshold: int
    llm_circuit_reset_seconds: int

    allow_mock_provider: bool
    use_inmemory_vector_store: bool
    session_ttl_minutes: int
    session_max_messages: int

    ingest_chunk_size: int
    ingest_chunk_overlap: int

    chat_events_enabled: bool
    chat_event_queue_file: str
    chat_event_reminder_delay_minutes: int
    chat_reminder_state_file: str
    chat_reminder_batch_size: int
    chat_webhook_url: str | None
    contact_webhook_url: str | None
    make_webhook_chat_url: str | None
    make_webhook_calendar_url: str | None

    durable_store_enabled: bool
    durable_sqlite_path: str
    durable_careers_sqlite_path: str

    langfuse_enabled: bool
    langfuse_public_key: str | None
    langfuse_secret_key: str | None
    langfuse_host: str

    gemini_api_key: str | None
    gemini_model: str


def _runtime_base() -> Path:
    """Returns a writable runtime directory.
    Azure Functions (Linux) only allows writes in /tmp.
    Detected by WEBSITE_INSTANCE_ID being set in Azure-hosted environments.
    """
    import os as _os
    if _os.environ.get("WEBSITE_INSTANCE_ID") or _os.environ.get("FUNCTIONS_EXTENSION_VERSION"):
        base = Path("/tmp/ofstride-runtime")
    else:
        base = API_ROOT / ".runtime"
    return base


def _build_settings() -> Settings:
    _load_env_files()

    return Settings(
        env=_get_str("ENV", "dev") or "dev",
        openai_api_key=_get_str("OPENAI_API_KEY"),
        azure_openai_api_key=_get_str("AZURE_OPENAI_API_KEY"),
        azure_openai_endpoint=_get_str("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_version=_get_str("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
        or "2024-12-01-preview",
        azure_openai_deployment=_get_str("AZURE_OPENAI_DEPLOYMENT"),
        azure_openai_embedding_deployment=_get_str("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
        llm_provider=_get_str("LLM_PROVIDER", "openai") or "openai",
        model_name=_get_str("MODEL_NAME", "gpt-4o-mini") or "gpt-4o-mini",
        fallback_model_name=_get_str("FALLBACK_MODEL_NAME", "gpt-4o-mini") or "gpt-4o-mini",
        temperature=_get_float("LLM_TEMPERATURE", 0.2),
        max_tokens=_get_int("LLM_MAX_TOKENS", 700),
        embedding_model=_get_str("EMBEDDING_MODEL", "text-embedding-3-small")
        or "text-embedding-3-small",
        embedding_dimension=_get_int("EMBEDDING_DIMENSION", 1536),
        qdrant_url=_get_str("QDRANT_URL"),
        qdrant_api_key=_get_str("QDRANT_API_KEY"),
        qdrant_collection=_get_str("QDRANT_COLLECTION", "ofstride_consultants")
        or "ofstride_consultants",
        vector_backend=_get_str("VECTOR_BACKEND", "auto") or "auto",
        supabase_vector_table=_get_str("SUPABASE_VECTOR_TABLE", "rag_documents")
        or "rag_documents",
        supabase_vector_rpc=_get_str("SUPABASE_VECTOR_RPC", "match_rag_documents")
        or "match_rag_documents",
        supabase_vector_scan_limit=_get_int("SUPABASE_VECTOR_SCAN_LIMIT", 2000),
        retrieval_k=_get_int("RETRIEVAL_K", 6),
        retrieval_score_threshold=_get_float("RETRIEVAL_SCORE_THRESHOLD", 0.40),
        retrieval_max_context_chars=_get_int("RETRIEVAL_MAX_CONTEXT_CHARS", 7000),
        source_snippet_chars=_get_int("SOURCE_SNIPPET_CHARS", 420),
        allowed_origins=_get_str("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:4280")
        or "http://localhost:5173,http://localhost:4280",
        ingest_shared_secret=_get_str("INGEST_SHARED_SECRET"),
        ingest_max_file_bytes=_get_int("INGEST_MAX_FILE_BYTES", 5 * 1024 * 1024),
        ingest_allowed_extensions=_get_str(
            "INGEST_ALLOWED_EXTENSIONS",
            ".txt,.md,.csv",
        )
        or ".txt,.md,.csv",
        rate_limit_enabled=_get_bool("RATE_LIMIT_ENABLED", True),
        rate_limit_window_seconds=_get_int("RATE_LIMIT_WINDOW_SECONDS", 60),
        rate_limit_requests_per_window=_get_int("RATE_LIMIT_REQUESTS_PER_WINDOW", 30),
        llm_timeout_seconds=_get_int("LLM_TIMEOUT_SECONDS", 30),
        llm_circuit_fail_threshold=_get_int("LLM_CIRCUIT_FAIL_THRESHOLD", 3),
        llm_circuit_reset_seconds=_get_int("LLM_CIRCUIT_RESET_SECONDS", 90),
        allow_mock_provider=_get_bool("ALLOW_MOCK_PROVIDER", True),
        use_inmemory_vector_store=_get_bool("USE_INMEMORY_VECTOR_STORE", True),
        session_ttl_minutes=_get_int("SESSION_TTL_MINUTES", 30),
        session_max_messages=_get_int("SESSION_MAX_MESSAGES", 16),
        ingest_chunk_size=_get_int("INGEST_CHUNK_SIZE", 1400),
        ingest_chunk_overlap=_get_int("INGEST_CHUNK_OVERLAP", 200),
        chat_events_enabled=_get_bool("CHAT_EVENTS_ENABLED", True),
        chat_event_queue_file=_get_str(
            "CHAT_EVENT_QUEUE_FILE",
            str(_runtime_base() / "chat_events.ndjson"),
        )
        or str(_runtime_base() / "chat_events.ndjson"),
        chat_event_reminder_delay_minutes=_get_int("CHAT_EVENT_REMINDER_DELAY_MINUTES", 1440),
        chat_reminder_state_file=_get_str(
            "CHAT_REMINDER_STATE_FILE",
            str(_runtime_base() / "chat_reminder_state.json"),
        )
        or str(_runtime_base() / "chat_reminder_state.json"),
        chat_reminder_batch_size=_get_int("CHAT_REMINDER_BATCH_SIZE", 20),
        chat_webhook_url=_get_str("CHAT_WEBHOOK_URL"),
        contact_webhook_url=_get_str("CONTACT_WEBHOOK_URL"),
        make_webhook_chat_url=_get_str("MAKE_WEBHOOK_CHAT_URL"),
        make_webhook_calendar_url=_get_str("MAKE_WEBHOOK_CALENDAR_URL"),
        durable_store_enabled=_get_bool("DURABLE_STORE_ENABLED", True),
        durable_sqlite_path=_get_str(
            "DURABLE_SQLITE_PATH",
            str(_runtime_base() / "chat_state.db"),
        )
        or str(_runtime_base() / "chat_state.db"),
        durable_careers_sqlite_path=_get_str(
            "DURABLE_CAREERS_SQLITE_PATH",
            str(_runtime_base() / "careers_state.db"),
        )
        or str(_runtime_base() / "careers_state.db"),
        langfuse_enabled=_get_bool("LANGFUSE_ENABLED", True),
        langfuse_public_key=_get_str("LANGFUSE_PUBLIC_KEY"),
        langfuse_secret_key=_get_str("LANGFUSE_SECRET_KEY"),
        langfuse_host=_get_str("LANGFUSE_HOST", "https://cloud.langfuse.com") or "https://cloud.langfuse.com",
        gemini_api_key=_get_str("GEMINI_API_KEY"),
        gemini_model=_get_str("GEMINI_MODEL", "gemini-1.5-flash") or "gemini-1.5-flash",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _build_settings()
