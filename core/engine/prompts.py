"""Shared system prompt construction for all voice engines."""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

from memory.memory_manager import format_memory_for_prompt, load_memory

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


PROMPT_PATH = base_dir() / "core" / "prompt.txt"
USER_INFO_PATH = base_dir() / "core" / "user_info.txt"


def _read_prompt_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def load_user_info() -> str:
    return _read_prompt_file(USER_INFO_PATH)


def clean_transcript(text: str) -> str:
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


def plain_text_for_speech(text: str) -> str:
    """Convert markdown-heavy LLM output into natural spoken prose for TTS."""
    text = clean_transcript(text)
    if not text:
        return ""

    text = re.sub(r"```[\w-]*\n?", "", text)
    text = text.replace("```", "")
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)

    for pattern in (
        r"\*\*\*(.+?)\*\*\*",
        r"\*\*(.+?)\*\*",
        r"__(.+?)__",
        r"\*(.+?)\*",
        r"_(.+?)_",
    ):
        text = re.sub(pattern, r"\1", text, flags=re.DOTALL)

    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)

    text = text.replace("**", "").replace("__", "").replace("*", "").replace("_", "")
    text = re.sub(r"\n{2,}", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip()


def load_system_prompt() -> str:
    core = _read_prompt_file(PROMPT_PATH)
    if not core:
        core = (
            "You are Emily, The user's AI assistant. "
            "Be articulate, highly informative, and detailed when explaining data or reviews, "
            "while keeping tool execution transitions brief. "
            "Never simulate or guess results — always call the appropriate tool."
        )
    user_info = load_user_info()
    if user_info:
        return f"{core}\n\n{user_info}"
    return core


def build_system_message() -> str:
    now = datetime.now()
    time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
    mem_str = format_memory_for_prompt(load_memory())
    parts = [
        f"[CURRENT DATE & TIME]\nRight now it is: {time_str}\n"
        f"Use this to calculate exact times for reminders.\n",
    ]
    if mem_str:
        parts.append(mem_str)
    parts.append(load_system_prompt())
    return "\n".join(parts)
