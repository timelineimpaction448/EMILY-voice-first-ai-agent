"""Shared LLM helpers for action modules."""

from __future__ import annotations

import io
from typing import Any

from core.llm.factory import get_llm_provider, run_completion, run_completion_with_search, run_multimodal

__all__ = [
    "get_llm_provider",
    "llm_complete",
    "llm_complete_with_search",
    "llm_multimodal",
    "LegacyLLMModel",
]


def llm_complete(prompt: str, system: str | None = None) -> str:
    return run_completion(prompt, system=system)


def llm_complete_with_search(query: str) -> str:
    return run_completion_with_search(query)


def llm_multimodal(text: str, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    return run_multimodal(text, image_bytes, mime_type=mime_type)


class _GenContentResponse:
    def __init__(self, text: str):
        self.text = text


class LegacyLLMModel:
    """Drop-in replacement for google.generativeai.GenerativeModel."""

    def __init__(self, system: str | None = None):
        self.system = system

    def generate_content(self, content: str | list[Any]) -> _GenContentResponse:
        provider = get_llm_provider()

        if isinstance(content, str):
            return _GenContentResponse(provider.complete(content, system=self.system))

        text_parts: list[str] = []
        image_bytes: bytes | None = None
        blob: dict | None = None

        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            else:
                try:
                    from PIL import Image
                    if isinstance(item, Image.Image):
                        buf = io.BytesIO()
                        item.convert("RGB").save(buf, format="JPEG")
                        image_bytes = buf.getvalue()
                        continue
                except Exception:
                    pass
                if isinstance(item, dict) and item.get("data"):
                    blob = item

        prompt = "\n".join(text_parts).strip()

        if blob:
            mime = blob.get("mime_type", "application/octet-stream")
            data = blob["data"]
            if provider.name == "gemini":
                from google import genai
                from google.genai import types
                from core.config import get_api_key_for_provider, get_llm_model
                client = genai.Client(api_key=get_api_key_for_provider("gemini"))
                response = client.models.generate_content(
                    model=get_llm_model(),
                    contents=[
                        types.Content(
                            role="user",
                            parts=[
                                types.Part(inline_data=types.Blob(data=data, mime_type=mime)),
                                types.Part(text=prompt or "Analyze this file."),
                            ],
                        )
                    ],
                )
                out = ""
                if response.candidates:
                    for part in response.candidates[0].content.parts or []:
                        if hasattr(part, "text") and part.text:
                            out += part.text
                return _GenContentResponse(out.strip())
            return _GenContentResponse(
                f"Multimodal blob ({mime}) requires Gemini provider. Current: {provider.name}."
            )

        if image_bytes:
            if not provider.supports_multimodal():
                return _GenContentResponse("Vision requires a multimodal-capable LLM provider.")
            return _GenContentResponse(
                provider.complete_multimodal(prompt or "Describe this image.", image_bytes)
            )

        return _GenContentResponse(provider.complete(prompt, system=self.system))
