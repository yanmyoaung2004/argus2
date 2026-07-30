from __future__ import annotations

import pytest

from argus.llm.providers import (
    AnthropicProvider,
    DeepSeekProvider,
    GoogleAIStudioProvider,
    GroqProvider,
    LiteLLMProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    OpenRouterProvider,
    TogetherAIProvider,
)
from argus.shared.models import LLMProviderType


class TestLLMProviderBase:
    def test_entry_or_settings_uses_entry_first(self) -> None:
        from argus.llm.provider_config import ProviderEntry

        entry = ProviderEntry(
            provider_type="ollama",
            display_name="Ollama",
            category="llm",
            enabled=True,
            base_url="http://custom:11434",
            api_key="custom-key",
        )
        provider = OllamaProvider(entry=entry)
        assert provider._entry_or_settings("base_url") == "http://custom:11434"
        assert provider._entry_or_settings("api_key") == "custom-key"

    def test_entry_or_settings_falls_back_to_settings(self) -> None:
        provider = OllamaProvider()
        assert provider._entry_or_settings("base_url") == "http://localhost:11434"


class TestOllamaProvider:
    def test_provider_type(self) -> None:
        p = OllamaProvider()
        assert p.provider_type == LLMProviderType.OLLAMA

    def test_get_model_name_default(self) -> None:
        p = OllamaProvider()
        name = p._get_model_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_estimate_cost_free(self) -> None:
        p = OllamaProvider()
        assert p._estimate_cost(1000, 500) == 0.0


class TestGroqProvider:
    def test_provider_type(self) -> None:
        p = GroqProvider()
        assert p.provider_type == LLMProviderType.GROQ

    def test_get_model_name_default(self) -> None:
        p = GroqProvider()
        name = p._get_model_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_estimate_cost_free(self) -> None:
        p = GroqProvider()
        assert p._estimate_cost(1000, 500) == 0.0


class TestOpenRouterProvider:
    def test_provider_type(self) -> None:
        p = OpenRouterProvider()
        assert p.provider_type == LLMProviderType.OPENROUTER

    def test_estimate_cost_pricing(self) -> None:
        p = OpenRouterProvider()
        cost = p._estimate_cost(1_000_000, 0)
        assert cost == pytest.approx(0.27, rel=1e-3)

    def test_estimate_cost_output_pricing(self) -> None:
        p = OpenRouterProvider()
        cost = p._estimate_cost(0, 1_000_000)
        assert cost == pytest.approx(0.27, rel=1e-3)


class TestOpenAIProvider:
    def test_provider_type(self) -> None:
        p = OpenAIProvider()
        assert p.provider_type == LLMProviderType.OPENAI

    def test_estimate_cost_pricing(self) -> None:
        p = OpenAIProvider()
        cost = p._estimate_cost(1_000_000, 0)
        assert cost == pytest.approx(2.50, rel=1e-3)

    def test_estimate_cost_output_pricing(self) -> None:
        p = OpenAIProvider()
        cost = p._estimate_cost(0, 1_000_000)
        assert cost == pytest.approx(10.00, rel=1e-3)


class TestAnthropicProvider:
    def test_provider_type(self) -> None:
        p = AnthropicProvider()
        assert p.provider_type == LLMProviderType.ANTHROPIC

    def test_estimate_cost_pricing(self) -> None:
        p = AnthropicProvider()
        cost = p._estimate_cost(1_000_000, 0)
        assert cost == pytest.approx(3.00, rel=1e-3)

    def test_create_client_returns_empty_dict(self) -> None:
        p = AnthropicProvider()
        assert p._create_client() == {}


class TestGoogleAIStudioProvider:
    def test_provider_type(self) -> None:
        p = GoogleAIStudioProvider()
        assert p.provider_type == LLMProviderType.GOOGLE_AI_STUDIO

    def test_estimate_cost_pricing(self) -> None:
        p = GoogleAIStudioProvider()
        cost = p._estimate_cost(1_000_000, 0)
        assert cost == pytest.approx(0.10, rel=1e-3)

    def test_create_client_returns_empty_dict(self) -> None:
        p = GoogleAIStudioProvider()
        assert p._create_client() == {}


class TestLiteLLMProvider:
    def test_provider_type(self) -> None:
        p = LiteLLMProvider()
        assert p.provider_type == LLMProviderType.LITELLM

    def test_estimate_cost_free(self) -> None:
        p = LiteLLMProvider()
        assert p._estimate_cost(1000, 500) == 0.0


class TestTogetherAIProvider:
    def test_provider_type(self) -> None:
        p = TogetherAIProvider()
        assert p.provider_type == LLMProviderType.TOGETHER_AI

    def test_estimate_cost(self) -> None:
        p = TogetherAIProvider()
        cost = p._estimate_cost(1_000_000, 0)
        assert cost == pytest.approx(0.88, rel=1e-3)


class TestDeepSeekProvider:
    def test_provider_type(self) -> None:
        p = DeepSeekProvider()
        assert p.provider_type == LLMProviderType.DEEPSEEK

    def test_estimate_cost_input(self) -> None:
        p = DeepSeekProvider()
        cost = p._estimate_cost(1_000_000, 0)
        assert cost == pytest.approx(0.27, rel=1e-3)

    def test_estimate_cost_output(self) -> None:
        p = DeepSeekProvider()
        cost = p._estimate_cost(0, 1_000_000)
        assert cost == pytest.approx(1.10, rel=1e-3)


class TestOpenAICompatibleProvider:
    def test_provider_type(self) -> None:
        p = OpenAICompatibleProvider()
        assert p.provider_type == LLMProviderType.OPENAI_COMPATIBLE

    def test_estimate_cost(self) -> None:
        p = OpenAICompatibleProvider()
        cost = p._estimate_cost(1_000_000, 1_000_000)
        assert cost == pytest.approx(0.75, rel=1e-3)


class TestLazyClient:
    def test_client_is_lazily_created(self) -> None:
        p = OllamaProvider()
        assert p._client is None
        # Don't call _get_client() since it would try to connect
        # Just verify the lazy-initialization pattern
        assert p._client is None
