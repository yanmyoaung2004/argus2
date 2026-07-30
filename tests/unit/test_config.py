from argus.shared.config import Settings


class TestSettings:
    def test_default_values(self) -> None:
        s = Settings()
        assert s.app_host == "0.0.0.0"
        assert s.app_port == 8000
        assert s.redis_url == "redis://localhost:6379/0"
        assert s.budget_per_research == 0.50
        assert s.llm_cache_ttl == 86400
        assert s.source_cache_ttl == 604800
        assert s.circuit_breaker_fail_max == 5
        assert s.circuit_breaker_reset_timeout_seconds == 30
        assert s.redis_stream_maxlen == 10000
        assert s.sse_idle_timeout_seconds == 300

    def test_env_prefix(self) -> None:
        assert Settings.model_config["env_prefix"] == "ARGUS_"

    def test_agent_concurrency_default(self) -> None:
        s = Settings()
        assert s.agent_concurrency == 2

    def test_ollama_defaults(self) -> None:
        s = Settings()
        assert s.ollama_base_url == "http://localhost:11434"
        assert s.ollama_timeout_seconds == 120

    def test_budget_default(self) -> None:
        s = Settings()
        assert s.budget_per_research == 0.50

    def test_authoritative_domains(self) -> None:
        s = Settings()
        assert "wikipedia.org" in s.authoritative_domains
        assert "reuters.com" in s.authoritative_domains
