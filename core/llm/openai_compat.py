from __future__ import annotations

from core.config import get_api_key_for_provider, get_base_url_for_provider, get_batch_llm_model
from core.llm.openai import OpenAIProvider


class OpenAICompatProvider(OpenAIProvider):
    """OpenAI-compatible API for Ollama and LM Studio."""

    def __init__(self, provider_name: str, model: str | None = None, base_url: str | None = None):
        self.name = provider_name
        from openai import OpenAI
        from core.llm.http_client import get_http_client
        self.model = model or get_batch_llm_model()
        url = base_url or get_base_url_for_provider(provider_name)
        api_key = get_api_key_for_provider(provider_name) or "not-needed"
        self._client = OpenAI(
            base_url=url,
            api_key=api_key,
            http_client=get_http_client(),
        )

    def warm_connection(self) -> None:
        try:
            self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            print(f"[LLM] {self.name} connection warm")
        except Exception as e:
            print(f"[LLM] {self.name} warm-up skipped: {e}")

    def supports_multimodal(self) -> bool:
        return False
