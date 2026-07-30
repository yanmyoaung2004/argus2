from __future__ import annotations

from argus.llm.provider_config import ProviderEntry, KNOWN_MODELS, DEFAULT_LLM_DEFS, SEARCH_PROVIDER_DEFS


class TestProviderEntry:
    def test_defaults(self) -> None:
        entry = ProviderEntry(
            provider_type="ollama",
            display_name="Ollama",
            category="llm",
            enabled=True,
        )
        assert entry.provider_type == "ollama"
        assert entry.base_url == ""
        assert entry.api_key == ""
        assert entry.selected_model == ""
        assert entry.priority == 99
        assert entry.cost_per_million_input == 0.0

    def test_with_all_fields(self) -> None:
        entry = ProviderEntry(
            provider_type="groq",
            display_name="Groq",
            category="llm",
            enabled=True,
            base_url="https://api.groq.com",
            api_key="sk-test",
            selected_model="llama-3.1-8b",
            priority=10,
            cost_per_million_input=1.0,
            cost_per_million_output=2.0,
        )
        assert entry.base_url == "https://api.groq.com"
        assert entry.api_key == "sk-test"
        assert entry.selected_model == "llama-3.1-8b"
        assert entry.priority == 10
        assert entry.cost_per_million_output == 2.0


class TestKnownModels:
    def test_ollama_has_models_key(self) -> None:
        assert "ollama" in KNOWN_MODELS

    def test_groq_has_models(self) -> None:
        assert "groq" in KNOWN_MODELS
        assert len(KNOWN_MODELS["groq"]) > 0

    def test_openai_has_models(self) -> None:
        assert "openai" in KNOWN_MODELS


class TestDefaultLLMDefs:
    def test_ollama_defined(self) -> None:
        defn = next((d for d in DEFAULT_LLM_DEFS if d["provider_type"] == "ollama"), None)
        assert defn is not None
        assert defn["display_name"] == "Ollama"
        assert "default_base_url" in defn

    def test_groq_defined(self) -> None:
        defn = next((d for d in DEFAULT_LLM_DEFS if d["provider_type"] == "groq"), None)
        assert defn is not None
        assert "default_model" in defn

    def test_all_providers_have_default_model(self) -> None:
        for defn in DEFAULT_LLM_DEFS:
            assert "default_model" in defn, f"{defn['provider_type']} missing default_model"

    def test_all_providers_have_base_url(self) -> None:
        for defn in DEFAULT_LLM_DEFS:
            assert "default_base_url" in defn, f"{defn['provider_type']} missing default_base_url"


class TestSearchProviderDefs:
    def test_duckduckgo_defined(self) -> None:
        defn = next((d for d in SEARCH_PROVIDER_DEFS if d["provider_type"] == "duckduckgo"), None)
        assert defn is not None
        assert "default_base_url" in defn

    def test_serpapi_defined(self) -> None:
        defn = next((d for d in SEARCH_PROVIDER_DEFS if d["provider_type"] == "serpapi"), None)
        assert defn is not None

    def test_all_search_providers_have_default_base_url(self) -> None:
        for defn in SEARCH_PROVIDER_DEFS:
            assert "default_base_url" in defn, f"{defn['provider_type']} missing default_base_url"
