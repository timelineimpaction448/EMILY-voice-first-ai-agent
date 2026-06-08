"""Tool declarations and schema converters for multi-provider LLM APIs."""

from __future__ import annotations

import json
from typing import Any

from core.llm.tool_declarations import TOOL_DECLARATIONS
from core.mcp.registry import get_active_tool_declarations


_GEMINI_TO_JSON = {
    "OBJECT": "object",
    "STRING": "string",
    "INTEGER": "integer",
    "NUMBER": "number",
    "BOOLEAN": "boolean",
    "ARRAY": "array",
}


def _convert_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    if not schema:
        return {"type": "object", "properties": {}}
    out: dict[str, Any] = {}
    for key, val in schema.items():
        if key == "type" and isinstance(val, str):
            out[key] = _GEMINI_TO_JSON.get(val.upper(), val.lower())
        elif key == "properties" and isinstance(val, dict):
            out[key] = {k: _convert_schema(v) if isinstance(v, dict) else v for k, v in val.items()}
        elif key == "items" and isinstance(val, dict):
            out[key] = _convert_schema(val)
        else:
            out[key] = val
    if out.get("type") == "object" and "properties" not in out:
        out["properties"] = {}
    return out


_OPENAI_TOOLS_CACHE: list[dict] | None = None


def to_openai_tools(declarations: list[dict] | None = None) -> list[dict]:
    global _OPENAI_TOOLS_CACHE
    if declarations is None and _OPENAI_TOOLS_CACHE is not None:
        return _OPENAI_TOOLS_CACHE

    decls = declarations or get_active_tool_declarations()
    tools = []
    for decl in decls:
        tools.append({
            "type": "function",
            "function": {
                "name": decl["name"],
                "description": decl.get("description", ""),
                "parameters": _convert_schema(decl.get("parameters")),
            },
        })
    if declarations is None:
        _OPENAI_TOOLS_CACHE = tools
    return tools


def to_anthropic_tools(declarations: list[dict] | None = None) -> list[dict]:
    decls = declarations or get_active_tool_declarations()
    tools = []
    for decl in decls:
        tools.append({
            "name": decl["name"],
            "description": decl.get("description", ""),
            "input_schema": _convert_schema(decl.get("parameters")),
        })
    return tools


def to_gemini_declarations(declarations: list[dict] | None = None) -> list:
    try:
        from google.genai import types
    except ImportError as exc:
        raise ImportError("google-genai is required for Gemini provider.") from exc

    decls = declarations or get_active_tool_declarations()
    return [
        types.FunctionDeclaration(
            name=decl["name"],
            description=decl.get("description", ""),
            parameters=decl.get("parameters"),
        )
        for decl in decls
    ]


def parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}
