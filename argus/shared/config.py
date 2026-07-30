from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "ARGUS_", "env_file": ".env", "env_file_encoding": "utf-8"}

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False
    app_log_level: str = "info"
    cors_origins: str = "*"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # SQLite
    sqlite_path: str = str(Path.home() / ".argus" / "knowledge.db")
    sqlite_wal_mode: bool = True
    sqlite_cache_size: int = -64000  # 64MB

    # LLM providers
    llm_default_model: str = "llama3.2:3b"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_timeout_seconds: int = 120

    # Groq
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout_seconds: int = 60

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_model: str = "mistralai/mixtral-8x7b-instruct"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: int = 60

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: int = 60

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_timeout_seconds: int = 120

    # Google AI Studio
    google_ai_studio_api_key: str = ""
    google_ai_studio_model: str = "gemini-2.0-flash"
    google_ai_studio_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    google_ai_studio_timeout_seconds: int = 60

    # LiteLLM
    litellm_api_key: str = ""
    litellm_model: str = "gpt-4o-mini"
    litellm_base_url: str = "http://localhost:4000"
    litellm_timeout_seconds: int = 60

    # Together AI
    together_ai_api_key: str = ""
    together_ai_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    together_ai_base_url: str = "https://api.together.xyz/v1"
    together_ai_timeout_seconds: int = 60

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_timeout_seconds: int = 60

    # NVIDIA (OpenAI-compatible)
    nvidia_api_key: str = ""
    nvidia_model: str = "meta/llama-3.1-8b-instruct"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_timeout_seconds: int = 60

    # Custom OpenAI-compatible endpoint
    custom_openai_api_key: str = ""
    custom_openai_model: str = ""
    custom_openai_base_url: str = ""
    custom_openai_timeout_seconds: int = 60

    # OpenAI-compatible endpoint
    openai_compatible_api_key: str = ""
    openai_compatible_model: str = "gpt-4o-mini"
    openai_compatible_base_url: str = ""
    openai_compatible_timeout_seconds: int = 60

    # Budget
    budget_per_research: float = 0.50

    # Cache TTLs (seconds)
    llm_cache_ttl: int = 86400  # 24 hours
    source_cache_ttl: int = 604800  # 7 days
    search_cache_ttl: int = 3600  # 1 hour

    # Vector
    vector_embedding_model: str = "all-MiniLM-L6-v2"  # sqlite-vec built-in or custom
    vector_hnsw_ef_construction: int = 200
    vector_hnsw_m: int = 16

    # Agent concurrency
    agent_concurrency: int = 2
    agent_heartbeat_ttl: int = 30
    agent_shutdown_timeout_seconds: int = 30

    # Redis stream config
    redis_stream_maxlen: int = 10000
    redis_consumer_group: str = "argus-workers"

    # Research timeouts
    research_max_duration_minutes: int = 360
    research_idle_timeout_minutes: int = 30

    # LLM retry
    llm_retry_max_attempts: int = 3
    llm_retry_min_wait_seconds: float = 1.0
    llm_retry_max_wait_seconds: float = 10.0

    # Circuit breaker
    circuit_breaker_fail_max: int = 5
    circuit_breaker_reset_timeout_seconds: int = 30

    # SerpAPI (paid search fallback)
    serpapi_api_key: str = ""

    # Firecrawl (web scraping / search fallback)
    firecrawl_api_key: str = ""
    firecrawl_base_url: str = "https://api.firecrawl.dev"

    # Tavily (AI-optimized search API)
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"

    # DuckDuckGo rate limiting
    ddg_rate_limit_per_second: float = 1.0

    # SSE
    sse_idle_timeout_seconds: int = 300

    # API auth (empty = no auth required)
    api_token: str = ""

    # Credibility
    authoritative_domains: str = (
        "wikipedia.org,britannica.com,reuters.com,ap.org,"
        "bbc.com,bbc.co.uk,nature.com,science.org,"
        "nih.gov,who.int,un.org,worldbank.org,"
        "scholar.google.com,arxiv.org,ieee.org,acm.org"
    )

    # Agent timeouts and batch sizes
    agent_wait_seconds: int = 135
    deep_dive_batch_size: int = 5
    deep_dive_max_content_chars: int = 8000
    scout_max_results: int = 10
    synthesis_max_entities: int = 20
    synthesis_max_claims: int = 30

    # Entity matching thresholds
    merge_threshold: float = 0.85
    llm_merge_threshold: float = 0.70
    edge_cooccur_threshold: int = 2

    # Agent types by task
    agent_for_task: dict[str, str] = {
        "discover": "scout",
        "extract": "deep_dive",
        "verify": "verification",
        "synthesize": "synthesis",
    }

    # Task type by agent
    task_types_for_agent: dict[str, list[str]] = {
        "scout": ["discover"],
        "deep_dive": ["extract"],
        "verification": ["verify"],
        "synthesis": ["synthesize"],
    }


settings = Settings()
