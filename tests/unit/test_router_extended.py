from __future__ import annotations

from argus.llm.router import CostAwareRouter
from argus.shared.models import LLMProviderType


class TestRouterExtended:
    def test_routing_table_contains_all_task_types(self) -> None:
        expected = {"planning", "scout", "deep_dive", "verification", "synthesis", "conflict_resolution"}
        assert expected.issubset(CostAwareRouter.ROUTING_TABLE.keys())

    def test_is_provider_enabled_ollama(self) -> None:
        router = CostAwareRouter()
        assert router._is_provider_enabled(LLMProviderType.OLLAMA) is True

    def test_get_provider_ollama(self) -> None:
        router = CostAwareRouter()
        provider = router._get_provider(LLMProviderType.OLLAMA)
        assert provider is not None

    def test_get_provider_groq(self) -> None:
        router = CostAwareRouter()
        provider = router._get_provider(LLMProviderType.GROQ)
        assert provider is not None

    def test_get_provider_openrouter(self) -> None:
        router = CostAwareRouter()
        provider = router._get_provider(LLMProviderType.OPENROUTER)
        assert provider is not None

    def test_get_provider_openai(self) -> None:
        router = CostAwareRouter()
        provider = router._get_provider(LLMProviderType.OPENAI)
        assert provider is not None

    def test_get_provider_anthropic(self) -> None:
        router = CostAwareRouter()
        provider = router._get_provider(LLMProviderType.ANTHROPIC)
        assert provider is not None

    def test_get_provider_google(self) -> None:
        router = CostAwareRouter()
        provider = router._get_provider(LLMProviderType.GOOGLE_AI_STUDIO)
        assert provider is not None

    def test_get_provider_deepseek(self) -> None:
        router = CostAwareRouter()
        provider = router._get_provider(LLMProviderType.DEEPSEEK)
        assert provider is not None

    def test_get_provider_together(self) -> None:
        router = CostAwareRouter()
        provider = router._get_provider(LLMProviderType.TOGETHER_AI)
        assert provider is not None

    def test_get_provider_litellm(self) -> None:
        router = CostAwareRouter()
        provider = router._get_provider(LLMProviderType.LITELLM)
        assert provider is not None

    def test_get_provider_nvidia(self) -> None:
        router = CostAwareRouter()
        provider = router._get_provider(LLMProviderType.NVIDIA)
        assert provider is not None

    def test_get_provider_custom_openai(self) -> None:
        router = CostAwareRouter()
        provider = router._get_provider(LLMProviderType.CUSTOM_OPENAI)
        assert provider is not None

    def test_get_provider_openai_compatible(self) -> None:
        router = CostAwareRouter()
        provider = router._get_provider(LLMProviderType.OPENAI_COMPATIBLE)
        assert provider is not None

    def test_get_provider_caches_instances(self) -> None:
        router = CostAwareRouter()
        p1 = router._get_provider(LLMProviderType.OLLAMA)
        p2 = router._get_provider(LLMProviderType.OLLAMA)
        assert p1 is p2
