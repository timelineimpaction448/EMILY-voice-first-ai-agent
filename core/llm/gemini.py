from __future__ import annotations

import json
import uuid
from typing import Any

from core.config import get_api_key_for_provider, get_batch_llm_model
from core.llm.base import LLMProvider
from core.llm.tools import parse_tool_arguments, to_gemini_declarations
from core.llm.types import CompletionResponse, Message, ToolCall


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        from google import genai
        self._genai = genai
        self.model = model or get_batch_llm_model()
        self._client = genai.Client(
            api_key=api_key or get_api_key_for_provider("gemini"),
            http_options={"api_version": "v1beta"},
        )

    def supports_search(self) -> bool:
        return True

    def supports_multimodal(self) -> bool:
        return True

    def _to_gemini_contents(self, messages: list[Message]) -> list:
        from google.genai import types
        contents = []
        for msg in messages:
            if msg.role == "system":
                continue
            if msg.role == "tool":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    id=msg.tool_call_id or str(uuid.uuid4()),
                                    name=msg.name or "tool",
                                    response={"result": msg.content},
                                )
                            )
                        ],
                    )
                )
                continue
            if msg.role == "assistant" and msg.tool_calls:
                parts = []
                if msg.content:
                    parts.append(types.Part(text=msg.content))
                for tc in msg.tool_calls:
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                id=tc.id,
                                name=tc.name,
                                args=tc.arguments,
                            )
                        )
                    )
                contents.append(types.Content(role="model", parts=parts))
                continue
            role = "user" if msg.role == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=msg.content)]))
        return contents

    def _system_instruction(self, messages: list[Message]) -> str | None:
        for msg in messages:
            if msg.role == "system" and msg.content:
                return msg.content
        return None

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> CompletionResponse:
        from google.genai import types
        config_kwargs: dict[str, Any] = {}
        sys_inst = self._system_instruction(messages)
        if sys_inst:
            config_kwargs["system_instruction"] = sys_inst
        if tools is not None:
            config_kwargs["tools"] = [
                types.Tool(function_declarations=to_gemini_declarations(tools))
            ]

        response = self._client.models.generate_content(
            model=self.model,
            contents=self._to_gemini_contents(messages),
            config=types.GenerateContentConfig(**config_kwargs) if config_kwargs else None,
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        candidate = response.candidates[0] if response.candidates else None
        if not candidate or not candidate.content:
            return CompletionResponse(text=None, tool_calls=[])

        for part in candidate.content.parts or []:
            if getattr(part, "text", None):
                text_parts.append(part.text)
            fc = getattr(part, "function_call", None)
            if fc:
                tool_calls.append(
                    ToolCall(
                        id=getattr(fc, "id", None) or str(uuid.uuid4()),
                        name=fc.name,
                        arguments=parse_tool_arguments(getattr(fc, "args", None)),
                    )
                )

        return CompletionResponse(
            text="".join(text_parts).strip() or None,
            tool_calls=tool_calls,
        )

    def complete_with_search(self, query: str) -> str:
        response = self._client.models.generate_content(
            model=self.model,
            contents=query,
            config={"tools": [{"google_search": {}}]},
        )
        text = ""
        if response.candidates:
            for part in response.candidates[0].content.parts or []:
                if hasattr(part, "text") and part.text:
                    text += part.text
        text = text.strip()
        if not text:
            raise ValueError("Gemini returned an empty response.")
        return text

    def complete_multimodal(
        self,
        text: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> str:
        from google.genai import types
        response = self._client.models.generate_content(
            model=self.model,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            inline_data=types.Blob(data=image_bytes, mime_type=mime_type)
                        ),
                        types.Part(text=text),
                    ],
                )
            ],
        )
        out = ""
        if response.candidates:
            for part in response.candidates[0].content.parts or []:
                if hasattr(part, "text") and part.text:
                    out += part.text
        return out.strip()
