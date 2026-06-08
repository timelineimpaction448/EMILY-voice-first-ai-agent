from __future__ import annotations

from core.config import get_llm_provider_name
from core.llm.anthropic import AnthropicProvider
from core.llm.base import LLMProvider
from core.llm.gemini import GeminiProvider
from core.llm.openai import OpenAIProvider
from core.llm.openai_compat import OpenAICompatProvider

_provider_cache: LLMProvider | None = None


def get_llm_provider(force_refresh: bool = False) -> LLMProvider:
    global _provider_cache
    if force_refresh:
        _provider_cache = None
    if _provider_cache is not None:
        return _provider_cache
    provider = get_llm_provider_name()
    if provider == "openai":
        _provider_cache = OpenAIProvider()
    elif provider == "anthropic":
        _provider_cache = AnthropicProvider()
    elif provider == "ollama":
        _provider_cache = OpenAICompatProvider("ollama")
    elif provider == "lmstudio":
        _provider_cache = OpenAICompatProvider("lmstudio")
    else:
        _provider_cache = GeminiProvider()
    return _provider_cache


def run_completion(prompt: str, system: str | None = None) -> str:
    return get_llm_provider().complete(prompt, system=system)


def run_completion_with_search(query: str) -> str:
    provider = get_llm_provider()
    if provider.supports_search():
        return provider.complete_with_search(query)
    return provider.complete(query)


def run_multimodal(text: str, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    provider = get_llm_provider()
    if not provider.supports_multimodal():
        raise RuntimeError(f"Provider {provider.name} does not support vision.")
    return provider.complete_multimodal(text, image_bytes, mime_type=mime_type)
