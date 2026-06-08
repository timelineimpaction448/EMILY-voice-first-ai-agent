from __future__ import annotations

import json
import uuid

from core.config import get_api_key_for_provider, get_batch_llm_model
from core.llm.base import LLMProvider
from core.llm.tools import parse_tool_arguments, to_openai_tools
from core.llm.types import CompletionResponse, Message, ToolCall


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        from openai import OpenAI
        from core.llm.http_client import get_http_client
        self.model = model or get_batch_llm_model()
        self._client = OpenAI(
            api_key=api_key or get_api_key_for_provider("openai"),
            http_client=get_http_client(),
        )

    def warm_connection(self) -> None:
        try:
            self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            print("[LLM] Connection warm")
        except Exception as e:
            print(f"[LLM] Warm-up skipped: {e}")

    def supports_multimodal(self) -> bool:
        return True

    def _to_openai_messages(self, messages: list[Message]) -> list[dict]:
        out: list[dict] = []
        for msg in messages:
            if msg.role == "system":
                out.append({"role": "system", "content": msg.content})
            elif msg.role == "user":
                out.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                entry: dict = {"role": "assistant", "content": msg.content or ""}
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                out.append(entry)
            elif msg.role == "tool":
                out.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id or "",
                    "content": msg.content,
                })
        return out

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> CompletionResponse:
        kwargs: dict = {
            "model": self.model,
            "messages": self._to_openai_messages(messages),
        }
        if tools is not None:
            kwargs["tools"] = to_openai_tools(tools)

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0].message
        tool_calls: list[ToolCall] = []
        if choice.tool_calls:
            for tc in choice.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id or str(uuid.uuid4()),
                        name=tc.function.name,
                        arguments=parse_tool_arguments(tc.function.arguments),
                    )
                )
        return CompletionResponse(
            text=(choice.content or "").strip() or None,
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
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                        },
                        {"type": "text", "text": text},
                    ],
                }
            ],
        )
        return (response.choices[0].message.content or "").strip()
