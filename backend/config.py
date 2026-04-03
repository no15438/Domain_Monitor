from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # "openai" | "anthropic" | "lmstudio" (本机) | "openai_compat" (第三方 OpenAI 兼容网关，如 ichonhui) | "dashscope"
    llm_provider: str = "openai"

    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"

    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-3-5-haiku-20241022"

    lmstudio_base_url: str = "http://localhost:1234/v1"
    lmstudio_model: str = "local-model"
    lmstudio_api_key: str = "lm-studio"

    # 第三方 OpenAI 兼容 HTTP API（非 LM Studio）：如 https://llm.ichonhui.com/.../v1
    openai_compat_base_url: str = ""
    openai_compat_model: str = ""
    openai_compat_api_key: str = ""

    # Alibaba Cloud DashScope (OpenAI-compatible)
    dashscope_api_key: Optional[str] = None
    dashscope_model: str = "qwen3.5-flash"  # qwen3.5-flash (推荐) | qwen3.5-plus | qwen-turbo | qwen-max
    # 中国大陆: https://dashscope.aliyuncs.com/compatible-mode/v1
    # 国际区:   https://dashscope-intl.aliyuncs.com/compatible-mode/v1
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

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
