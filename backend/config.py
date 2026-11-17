from pathlib import Path
import os

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import Optional

# Resolve configuration from backend/ even when starting from the repository root.
_BACKEND_DIR = Path(__file__).resolve().parent
_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    # "openai" | "anthropic" | "lmstudio" (local) | "openai_compat" (third-party OpenAI-compatible gateway) | "dashscope"
    llm_provider: str = "openai"

    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"

    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-3-5-haiku-20241022"

    lmstudio_base_url: str = "http://localhost:1234/v1"
    lmstudio_model: str = "local-model"
    lmstudio_api_key: str = "lm-studio"

    # Third-party OpenAI-compatible HTTP API, e.g. https://llm.ichonhui.com/.../v1
    openai_compat_base_url: str = ""
    openai_compat_model: str = ""
    openai_compat_api_key: str = ""

    # Alibaba Cloud DashScope (OpenAI-compatible)
    dashscope_api_key: Optional[str] = None
    dashscope_model: str = "qwen3.5-flash"  # qwen3.5-flash (recommended) | qwen3.5-plus | qwen-turbo | qwen-max
    # Mainland China: https://dashscope.aliyuncs.com/compatible-mode/v1
    # International:   https://dashscope-intl.aliyuncs.com/compatible-mode/v1
    dashscope_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

    tavily_api_key: Optional[str] = None
    newsapi_key: Optional[str] = None
    event_registry_api_key: Optional[str] = None

    global_rss_feeds: str = ""

    tavily_exclude_domains: str = "wikipedia.org,baike.baidu.com,baidu.com,wikiwand.com,britannica.com,zhihu.com"

    monitor_keywords: str = "artificial intelligence,machine learning"
    fetch_interval_minutes: int = 15
    max_results_per_keyword: int = 15

    event_cluster_threshold: float = 0.38
    scoring_weights: str = "authority=0.35,coverage=0.25,rank_proxy=0.20,freshness=0.10,originality=0.10"

    database_path: str = "./data/monitor.db"
    chroma_persist_dir: str = "./data/chroma"

    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"
    # Event adapter. Public deployments explicitly allow their own hostname.
    event_memory_enabled: bool = False
    event_memory_database_path: str = "data/eventkb.sqlite3"
    event_memory_hosts: str = Field(default_factory=lambda: ",".join(filter(None, [
        "localhost", "127.0.0.1", "backend", "testserver", os.getenv("RENDER_EXTERNAL_HOSTNAME")
    ])))
    scheduler_enabled: bool = False
    external_calls_enabled: bool = True

    @field_validator("database_path", "chroma_persist_dir", "event_memory_database_path")
    @classmethod
    def resolve_storage(cls, value):
        path = Path(value).expanduser()
        return str(path if path.is_absolute() else _ROOT / path)

    model_config = SettingsConfigDict(
        env_file=os.environ.get("DOMAIN_MONITOR_ENV_FILE", str(_BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()
