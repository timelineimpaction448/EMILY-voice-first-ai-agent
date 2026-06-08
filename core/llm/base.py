from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.llm.types import CompletionResponse, Message


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> CompletionResponse:
        ...

    def complete(self, prompt: str, system: str | None = None) -> str:
        msgs = []
        if system:
            msgs.append(Message(role="system", content=system))
        msgs.append(Message(role="user", content=prompt))
        resp = self.chat(msgs)
        return (resp.text or "").strip()

    def complete_with_search(self, query: str) -> str:
        return self.complete(query)

    def complete_multimodal(
        self,
        text: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> str:
        raise NotImplementedError(f"{self.name} does not support multimodal completion")

    def supports_tools(self) -> bool:
        return True

    def supports_search(self) -> bool:
        return False

    def supports_multimodal(self) -> bool:
        return False

    def warm_connection(self) -> None:
        """Optional startup hook to establish a pooled HTTP connection."""
