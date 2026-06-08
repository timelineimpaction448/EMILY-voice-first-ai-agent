import sys
from pathlib import Path

from core.config import (
    SECRETS_FILE,
    USER_CONFIG_FILE,
    ensure_config_dir,
    is_configured,
    load_secrets,
    load_user_config,
    save_secrets,
    save_user_config,
    validate_provider_config,
)


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"


def user_config_exists() -> bool:
    return USER_CONFIG_FILE.exists()


def secrets_exist() -> bool:
    return SECRETS_FILE.exists()


def config_exists() -> bool:
    return user_config_exists()


def save_api_keys(gemini_api_key: str) -> None:
    save_secrets({"gemini_api_key": gemini_api_key.strip()})


def load_api_keys() -> dict:
    return load_secrets()


def get_gemini_key() -> str | None:
    key = load_secrets().get("gemini_api_key")
    return str(key).strip() if key else None


def save_setup_config(updates: dict) -> None:
    from core.config import save_config
    save_config(updates)


__all__ = [
    "config_exists",
    "user_config_exists",
    "secrets_exist",
    "save_api_keys",
    "load_api_keys",
    "get_gemini_key",
    "is_configured",
    "save_setup_config",
    "save_user_config",
    "save_secrets",
    "load_user_config",
    "load_secrets",
    "validate_provider_config",
]
