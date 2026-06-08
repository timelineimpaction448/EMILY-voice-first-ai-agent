# config/__init__.py
from pathlib import Path

from core.config import (
    get_mcp_servers,
    get_os,
    get_sleep_face_timeout_sec,
    get_sleep_mode_enabled,
    get_tts_voice,
    load_mcp_config,
    load_secrets,
    load_user_config,
)

_CONFIG_DIR = Path(__file__).parent


def get_config() -> dict:
    merged = load_secrets().copy()
    merged.update(load_user_config())
    servers = get_mcp_servers()
    if servers:
        merged["mcpServers"] = servers
    return merged


def is_windows() -> bool:
    return get_os() == "windows"


def is_mac() -> bool:
    return get_os() == "mac"


def is_linux() -> bool:
    return get_os() == "linux"
