from __future__ import annotations

import uuid

from core.config import get_api_key_for_provider, get_batch_llm_model
from core.llm.base import LLMProvider
from core.llm.tools import parse_tool_arguments, to_anthropic_tools
from core.llm.types import CompletionResponse, Message, ToolCall


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        import anthropic
        self.model = model or get_batch_llm_model()
        self._client = anthropic.Anthropic(api_key=api_key or get_api_key_for_provider("anthropic"))

    def supports_multimodal(self) -> bool:
        return True

    def _split_system(self, messages: list[Message]) -> tuple[str | None, list[Message]]:
        system = None
        rest = []
        for msg in messages:
            if msg.role == "system" and system is None:
                system = msg.content
            else:
                rest.append(msg)
        return system, rest

    def _to_anthropic_messages(self, messages: list[Message]) -> list[dict]:
        out: list[dict] = []
        for msg in messages:
            if msg.role == "user":
                out.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                if msg.tool_calls:
                    blocks = []
                    if msg.content:
                        blocks.append({"type": "text", "text": msg.content})
                    for tc in msg.tool_calls:
                        blocks.append({
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        })
                    out.append({"role": "assistant", "content": blocks})
                else:
                    out.append({"role": "assistant", "content": msg.content})
            elif msg.role == "tool":
                out.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id or "",
                        "content": msg.content,
                    }],
                })
        return out

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> CompletionResponse:
        system, msgs = self._split_system(messages)
        kwargs: dict = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": self._to_anthropic_messages(msgs),
        }
        if system:
            kwargs["system"] = system
        if tools is not None:
            kwargs["tools"] = to_anthropic_tools(tools)

        response = self._client.messages.create(**kwargs)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id or str(uuid.uuid4()),
                        name=block.name,
                        arguments=dict(block.input) if block.input else {},
                    )
                )

        return CompletionResponse(
            text="".join(text_parts).strip() or None,
            tool_calls=tool_calls,
        )

    def complete_multimodal(
        self,
        text: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> str:
        import base64

        b64 = base64.b64encode(image_bytes).decode("ascii")
        response = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": text},
                ],
            }],
        )
        parts = [b.text for b in response.content if b.type == "text"]
        return "".join(parts).strip()
