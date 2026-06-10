"""Central configuration for Emily — user prefs in config.json, secrets in api_keys.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROVIDERS = ("gemini", "openai", "anthropic", "ollama", "lmstudio")
VOICE_MODES = ("local", "native", "deepgram")
REALTIME_PROVIDERS = ("gemini", "openai")
STT_MODELS = ("tiny", "base", "small", "medium", "large-v3")
TTS_VOICES = ("M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5")
DEEPGRAM_STT_MODELS = ("nova-3", "nova-2")
DEEPGRAM_TTS_VOICES = (
    "aura-2-asteria-en",
    "aura-2-apollo-en",
    "aura-2-thalia-en",
    "aura-2-arcas-en",
    "aura-2-helena-en",
    "aura-2-andromeda-en",
    "aura-2-athena-en",
    "aura-2-aries-en",
    "aura-2-luna-en",
    "aura-2-stella-en",
    "aura-2-orion-en",
    "aura-2-perseus-en",
    "aura-2-janus-en",
    "aura-2-juno-en",
    "aura-2-hera-en",
    "aura-2-harmonia-en"
)

REALTIME_MODELS: dict[str, tuple[str, ...]] = {
    "gemini": (
        "gemini-3.1-flash-live-preview",
        "gemini-3.1-flash-lite",
        "gemini-3.1-flash",
        "gemini-2.5-flash-native-audio-latest",
        "gemini-2.5-flash-native-audio-preview-12-2025",
        "gemini-2.5-flash-native-audio-preview-09-2025",
    ),
    "openai": (
        "gpt-realtime-mini",
        "gpt-realtime-1.5",
        "gpt-realtime-2"
    ),
}

REALTIME_VOICES: dict[str, tuple[str, ...]] = {
    "gemini": ("Aoede", "Charon", "Fenrir", "Kore", "Puck"),
    "openai": ("alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"),
}

DEFAULT_VOICE_MODE = "local"
DEFAULT_LIVE_MODELS = {
    "gemini": "gemini-3.1-flash-live-preview",
    "openai": "gpt-realtime-mini",
}
DEFAULT_LIVE_VOICES = {
    "gemini": "Aoede",
    "openai": "alloy",
}

PROVIDER_LABELS = {
    "gemini": "Gemini (Google AI Studio)",
    "openai": "OpenAI ChatGPT",
    "anthropic": "Anthropic Claude",
    "ollama": "Ollama (local)",
    "lmstudio": "LM Studio (local)",
}

CREDENTIAL_FIELDS = {
    "gemini": "gemini_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "ollama": "ollama_base_url",
    "lmstudio": "lmstudio_base_url",
}

LOCAL_API_KEY_FIELDS = {
    "ollama": "ollama_api_key",
    "lmstudio": "lmstudio_api_key",
}

DEFAULT_CREDENTIALS = {
    "ollama_base_url": "http://localhost:11434/v1",
    "lmstudio_base_url": "http://localhost:1234/v1",
}

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-20250514",
    "ollama": "llama3.2",
    "lmstudio": "",
}

DEFAULT_STT_MODEL = "base"
DEFAULT_TTS_VOICE = "M1"
SUPERTONIC_ACCEL_MODES = ("auto", "cpu", "cuda", "webgpu", "directml")
DEFAULT_SUPERTONIC_ACCEL = "auto"
DEFAULT_DEEPGRAM_STT_MODEL = "nova-3"
DEFAULT_DEEPGRAM_TTS_VOICE = "aura-2-asteria-en"
DEFAULT_CAMERA_INDEX = 0

_LEGACY_USER_PREF_KEYS = frozenset({
    "camera_cv_detect",
    "sleep_mode_enabled",
    "sleep_face_timeout_sec",
    "camera_index",
})

_user_prefs_migrated = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
USER_CONFIG_FILE = CONFIG_DIR / "config.json"
SECRETS_FILE = CONFIG_DIR / "api_keys.json"
MCP_FILE = CONFIG_DIR / "mcp.json"

# Back-compat alias used by a few modules
CONFIG_FILE = SECRETS_FILE


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[Config] Failed to load {path.name}: {e}")
        return {}


def load_user_config() -> dict[str, Any]:
    return _read_json(USER_CONFIG_FILE)


def save_user_config(updates: dict[str, Any]) -> None:
    ensure_config_dir()
    data = load_user_config()
    data.update(updates)
    USER_CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def load_secrets() -> dict[str, Any]:
    return _read_json(SECRETS_FILE)


def save_secrets(updates: dict[str, Any]) -> None:
    ensure_config_dir()
    data = load_secrets()
    data.update(updates)
    SECRETS_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def load_mcp_config() -> dict[str, Any]:
    return _read_json(MCP_FILE)


def save_mcp_config(updates: dict[str, Any]) -> None:
    ensure_config_dir()
    data = load_mcp_config()
    data.update(updates)
    MCP_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def _migrate_mcp_from_secrets() -> dict[str, Any]:
    """One-time move of mcpServers from api_keys.json into mcp.json."""
    secrets = load_secrets()
    servers = secrets.get("mcpServers")
    if not servers:
        return {}
    save_mcp_config({"mcpServers": servers})
    cleaned = {k: v for k, v in secrets.items() if k != "mcpServers"}
    SECRETS_FILE.write_text(json.dumps(cleaned, indent=4), encoding="utf-8")
    print("[Config] Migrated mcpServers from api_keys.json to mcp.json")
    return servers


def get_mcp_servers() -> dict[str, Any]:
    """MCP server definitions keyed by server name (e.g. massive)."""
    data = load_mcp_config()
    servers = data.get("mcpServers")
    if servers:
        return servers
    return _migrate_mcp_from_secrets()


def load_config() -> dict[str, Any]:
    """Merged view: user prefs + secrets + MCP (user prefs override secrets)."""
    merged = load_secrets().copy()
    merged.update(load_user_config())
    servers = get_mcp_servers()
    if servers:
        merged["mcpServers"] = servers
    return merged


def save_config(updates: dict[str, Any]) -> None:
    """Legacy helper — routes fields to api_keys.json, mcp.json, or config.json."""
    mcp_keys = {"mcpServers"}
    secret_keys = {
        "gemini_api_key", "openai_api_key", "anthropic_api_key",
        "ollama_base_url", "lmstudio_base_url",
        "ollama_api_key", "lmstudio_api_key",
    }
    mcp = {k: v for k, v in updates.items() if k in mcp_keys}
    secrets = {k: v for k, v in updates.items() if k in secret_keys}
    user = {
        k: v for k, v in updates.items()
        if k not in secret_keys and k not in mcp_keys
    }
    if mcp:
        save_mcp_config(mcp)
    if secrets:
        save_secrets(secrets)
    if user:
        save_user_config(user)


def onboarding_complete() -> bool:
    return bool(load_user_config().get("onboarding_complete"))


def get_llm_provider_name() -> str:
    cfg = load_user_config()
    provider = str(cfg.get("llm_provider", "gemini")).lower().strip()
    return provider if provider in PROVIDERS else "gemini"


def get_voice_mode() -> str:
    cfg = load_user_config()
    mode = str(cfg.get("voice_mode", DEFAULT_VOICE_MODE)).lower().strip()
    return mode if mode in VOICE_MODES else DEFAULT_VOICE_MODE


def get_realtime_models(provider: str | None = None) -> tuple[str, ...]:
    provider = (provider or get_llm_provider_name()).lower()
    if provider == "gemini":
        from core.llm.gemini_live_models import fetch_gemini_live_models
        return fetch_gemini_live_models(api_key=get_api_key_for_provider("gemini"))
    return REALTIME_MODELS.get(provider, ())


def resolve_live_model(provider: str, model: str) -> str:
    allowed = get_realtime_models(provider)
    if not allowed:
        return DEFAULT_LIVE_MODELS.get(provider, "")
    if model in allowed:
        return model
    default = DEFAULT_LIVE_MODELS.get(provider, allowed[0])
    if model:
        print(f"[Config] live_model '{model}' is unavailable; using '{default}'")
    return default


def get_live_model() -> str:
    cfg = load_user_config()
    provider = get_llm_provider_name()
    model = str(cfg.get("live_model", "")).strip()
    default = DEFAULT_LIVE_MODELS.get(provider, DEFAULT_LIVE_MODELS["gemini"])
    resolved = resolve_live_model(provider, model) if model else default
    if model and resolved != model:
        save_user_config({"live_model": resolved})
    return resolved


def get_live_voice() -> str:
    cfg = load_user_config()
    provider = get_llm_provider_name()
    voice = str(cfg.get("live_voice", "")).strip()
    if voice:
        return voice
    return DEFAULT_LIVE_VOICES.get(provider, DEFAULT_LIVE_VOICES["gemini"])


def uses_native_voice() -> bool:
    return get_voice_mode() == "native" and get_llm_provider_name() in REALTIME_PROVIDERS


def uses_deepgram_voice() -> bool:
    return get_voice_mode() == "deepgram"


def _strip_live_suffix(model: str) -> str:
    for suffix in (
        "-native-audio-preview-12-2025",
        "-native-audio-preview-09-2025",
        "-native-audio-latest",
        "-native-audio-preview",
        "-live-preview",
        "-live-001",
        "-live",
    ):
        if model.endswith(suffix):
            return model[: -len(suffix)]
    if "native-audio" in model:
        return model.split("-native-audio")[0]
    if "live" in model:
        return model.replace("-live", "").replace("live-", "")
    return model


def _model_matches_provider(provider: str, model: str) -> bool:
    m = model.lower().strip()
    if not m:
        return False
    if provider == "gemini":
        return m.startswith("gemini")
    if provider == "openai":
        return m.startswith(("gpt-", "o1", "o3", "o4", "chatgpt"))
    if provider == "anthropic":
        return m.startswith("claude")
    return True


def is_live_only_model(model: str, provider: str | None = None) -> bool:
    """True if the model only supports realtime/bidi APIs, not batch generateContent."""
    provider = (provider or get_llm_provider_name()).lower()
    m = model.lower().strip()
    if not m:
        return False
    if provider == "gemini":
        if m in get_realtime_models("gemini"):
            return True
        return any(
            marker in m
            for marker in ("-live-preview", "-live-001", "-native-audio", "native-audio")
        )
    if provider == "openai":
        return "realtime" in m
    return False


def get_vision_model() -> str:
    """Model used for vision — Live model in native Gemini mode, else batch multimodal."""
    if get_llm_provider_name() == "gemini" and uses_native_voice():
        return get_live_model()
    return get_batch_llm_model()


def get_llm_model() -> str:
    cfg = load_user_config()
    provider = get_llm_provider_name()
    model = str(cfg.get("llm_model", "")).strip()
    if model and _model_matches_provider(provider, model) and not is_live_only_model(model, provider):
        return model
    return DEFAULT_MODELS.get(provider, DEFAULT_MODELS["gemini"])


def get_batch_llm_model() -> str:
    cfg = load_user_config()
    provider = get_llm_provider_name()
    model = str(cfg.get("llm_model", "")).strip()
    default = DEFAULT_MODELS.get(provider, DEFAULT_MODELS["gemini"])

    if model and _model_matches_provider(provider, model) and not is_live_only_model(model, provider):
        return model

    if model and is_live_only_model(model, provider):
        print(f"[Config] llm_model '{model}' is Live-only; using batch model '{default}'")

    if uses_native_voice():
        live = str(cfg.get("live_model", "")).strip() or get_live_model()
        stripped = _strip_live_suffix(live)
        if (
            stripped
            and _model_matches_provider(provider, stripped)
            and not is_live_only_model(stripped, provider)
        ):
            resolved = stripped
            if model and is_live_only_model(model, provider):
                save_user_config({"llm_model": resolved})
            return resolved

    if model and is_live_only_model(model, provider):
        save_user_config({"llm_model": default})
    return default


def resolve_onboarding_model_default(provider: str, current: str) -> str:
    """Pick a sensible LLM model default for setup prompts."""
    provider = provider.lower().strip()
    model = str(current or "").strip()
    if model:
        for check in (provider, "gemini", "openai"):
            if is_live_only_model(model, check):
                model = ""
                break
    if model and _model_matches_provider(provider, model):
        return model
    return DEFAULT_MODELS.get(provider, "")


def validate_voice_config(
    user: dict[str, Any] | None = None,
    secrets: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    user = user if user is not None else load_user_config()
    secrets = secrets if secrets is not None else load_secrets()
    mode = str(user.get("voice_mode", DEFAULT_VOICE_MODE)).lower().strip()
    if mode not in VOICE_MODES:
        return False, f"Invalid voice_mode: {mode}"
    provider = str(user.get("llm_provider", get_llm_provider_name())).lower()
    if mode == "native":
        if provider not in REALTIME_PROVIDERS:
            return False, f"Native voice requires gemini or openai (got {provider})"
        live_model = str(user.get("live_model", "")).strip() or DEFAULT_LIVE_MODELS.get(provider, "")
        allowed = get_realtime_models(provider)
        if live_model not in allowed:
            return False, f"Invalid live_model for {provider}: {live_model}"
        live_voice = str(user.get("live_voice", "")).strip() or DEFAULT_LIVE_VOICES.get(provider, "")
        allowed_voices = REALTIME_VOICES.get(provider, ())
        if live_voice not in allowed_voices:
            return False, f"Invalid live_voice for {provider}: {live_voice}"
    elif mode == "deepgram":
        key = str(secrets.get("deepgram_api_key", "")).strip()
        if not key or len(key) < 8:
            return False, "Deepgram API key is required for deepgram voice mode"
        stt = str(user.get("stt_model", "")).strip() or DEFAULT_DEEPGRAM_STT_MODEL
        if stt not in DEEPGRAM_STT_MODELS:
            return False, f"Invalid Deepgram STT model: {stt}"
        tts = str(user.get("tts_voice", "")).strip() or DEFAULT_DEEPGRAM_TTS_VOICE
        if tts not in DEEPGRAM_TTS_VOICES:
            return False, f"Invalid Deepgram TTS voice: {tts}"
    return True, ""


def get_pipeline_label() -> str:
    if uses_native_voice():
        provider = get_llm_provider_name()
        return f"native ({provider}-live)"
    if uses_deepgram_voice():
        return "deepgram"
    return "local"


def get_api_key_for_provider(provider: str | None = None) -> str:
    cfg = load_secrets()
    provider = (provider or get_llm_provider_name()).lower()
    if provider in LOCAL_API_KEY_FIELDS:
        return str(cfg.get(LOCAL_API_KEY_FIELDS[provider], "")).strip()
    field = CREDENTIAL_FIELDS.get(provider)
    if not field or field.endswith("_url"):
        return ""
    return str(cfg.get(field, "")).strip()


def get_base_url_for_provider(provider: str | None = None) -> str:
    cfg = load_secrets()
    provider = (provider or get_llm_provider_name()).lower()
    if provider == "ollama":
        return str(cfg.get("ollama_base_url", DEFAULT_CREDENTIALS["ollama_base_url"])).strip()
    if provider == "lmstudio":
        return str(cfg.get("lmstudio_base_url", DEFAULT_CREDENTIALS["lmstudio_base_url"])).strip()
    return ""


def get_deepgram_api_key() -> str:
    return str(load_secrets().get("deepgram_api_key", "")).strip()


def get_stt_model() -> str:
    cfg = load_user_config()
    if uses_deepgram_voice():
        model = str(cfg.get("stt_model", DEFAULT_DEEPGRAM_STT_MODEL)).strip()
        return model if model in DEEPGRAM_STT_MODELS else DEFAULT_DEEPGRAM_STT_MODEL
    model = str(cfg.get("stt_model", DEFAULT_STT_MODEL)).strip()
    return model if model in STT_MODELS else DEFAULT_STT_MODEL


def get_tts_voice() -> str:
    cfg = load_user_config()
    if uses_deepgram_voice():
        voice = str(cfg.get("tts_voice", DEFAULT_DEEPGRAM_TTS_VOICE)).strip()
        return voice if voice in DEEPGRAM_TTS_VOICES else DEFAULT_DEEPGRAM_TTS_VOICE
    voice = str(cfg.get("tts_voice", DEFAULT_TTS_VOICE)).strip()
    return voice if voice else DEFAULT_TTS_VOICE


def get_os() -> str:
    return str(load_user_config().get("os_system", "windows")).lower()


# --- HUD 2.0 cockpit preferences ---

HUD_VERSIONS = (1, 2)
RADAR_MODES = ("iss", "quakes")
WEATHER_UNITS = ("metric", "imperial")


def get_hud_version() -> int:
    """2 = new cockpit (default), 1 = legacy panel HUD (escape hatch)."""
    try:
        v = int(load_user_config().get("hud_version", 2))
    except (TypeError, ValueError):
        return 2
    return v if v in HUD_VERSIONS else 2


def get_weather_location() -> str:
    return str(load_user_config().get("weather_location", "auto") or "auto").strip()


def weather_location_configured() -> bool:
    """True once the user has set (or explicitly skipped to 'auto') their location."""
    return "weather_location" in load_user_config()


def get_weather_units() -> str:
    u = str(load_user_config().get("weather_units", "metric")).lower().strip()
    return u if u in WEATHER_UNITS else "metric"


def get_radar_mode() -> str:
    m = str(load_user_config().get("radar_mode", "iss")).lower().strip()
    return m if m in RADAR_MODES else "iss"


def get_hud_reduced_motion() -> bool:
    return bool(load_user_config().get("hud_reduced_motion", False))


HUD_FX_MODES = ("full", "reduced", "off")


def get_hud_fx() -> str:
    """Cockpit FX level: 'full' (all effects), 'reduced' (no decorative motion),
    'off' (flat 2.0 look — no backdrop/overlay/shimmer). `hud_reduced_motion`
    forces at least 'reduced'."""
    fx = str(load_user_config().get("hud_fx", "full")).lower().strip()
    if fx not in HUD_FX_MODES:
        fx = "full"
    if fx == "full" and get_hud_reduced_motion():
        return "reduced"
    return fx


def get_hud_widgets() -> dict:
    """Per-widget enable map (empty = all on)."""
    w = load_user_config().get("hud_widgets", {})
    return w if isinstance(w, dict) else {}


def get_supertonic_accel() -> str:
    cfg = load_user_config()
    mode = str(cfg.get("supertonic_accel", DEFAULT_SUPERTONIC_ACCEL)).lower().strip()
    return mode if mode in SUPERTONIC_ACCEL_MODES else DEFAULT_SUPERTONIC_ACCEL


def _ensure_user_prefs_migrated() -> None:
    """Move device/sleep prefs from api_keys.json into config.json (one-time)."""
    global _user_prefs_migrated
    if _user_prefs_migrated:
        return
    _user_prefs_migrated = True

    secrets = load_secrets()
    if not any(k in secrets for k in _LEGACY_USER_PREF_KEYS):
        return

    user = load_user_config()
    updates = {k: secrets[k] for k in _LEGACY_USER_PREF_KEYS if k in secrets and k not in user}
    if updates:
        save_user_config(updates)

    cleaned = {k: v for k, v in secrets.items() if k not in _LEGACY_USER_PREF_KEYS}
    if len(cleaned) != len(secrets):
        SECRETS_FILE.write_text(json.dumps(cleaned, indent=4), encoding="utf-8")
        if updates:
            print("[Config] Migrated user preferences from api_keys.json to config.json")


def get_float_orb_position() -> tuple[int, int] | None:
    cfg = load_user_config()
    if "float_orb_x" not in cfg or "float_orb_y" not in cfg:
        return None
    try:
        return int(cfg["float_orb_x"]), int(cfg["float_orb_y"])
    except (TypeError, ValueError):
        return None


def save_float_orb_position(x: int, y: int) -> None:
    save_user_config({"float_orb_x": int(x), "float_orb_y": int(y)})


def get_mic_device_index() -> int | None:
    cfg = load_user_config()
    if "mic_device_index" not in cfg:
        return None
    try:
        return int(cfg["mic_device_index"])
    except (TypeError, ValueError):
        return None


def get_camera_index() -> int:
    _ensure_user_prefs_migrated()
    cfg = load_user_config()
    if "camera_index" in cfg:
        try:
            return int(cfg["camera_index"])
        except (TypeError, ValueError):
            pass
    return DEFAULT_CAMERA_INDEX


def get_camera_cv_enabled() -> bool:
    _ensure_user_prefs_migrated()
    cfg = load_user_config()
    if "camera_cv_detect" in cfg:
        return bool(cfg["camera_cv_detect"])
    return True


def get_sleep_mode_enabled() -> bool:
    _ensure_user_prefs_migrated()
    cfg = load_user_config()
    if "sleep_mode_enabled" in cfg:
        return bool(cfg["sleep_mode_enabled"])
    return True


def get_sleep_face_timeout_sec(default: int = 300) -> int:
    _ensure_user_prefs_migrated()
    cfg = load_user_config()
    raw = cfg.get("sleep_face_timeout_sec")
    if raw is None:
        return default
    try:
        return max(60, int(raw))
    except (TypeError, ValueError):
        return default


def validate_provider_config(
    provider: str,
    secrets: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    secrets = secrets if secrets is not None else load_secrets()
    provider = provider.lower()
    if provider not in PROVIDERS:
        return False, f"Unknown provider: {provider}"
    if provider in ("ollama", "lmstudio"):
        field = CREDENTIAL_FIELDS[provider]
        if not str(secrets.get(field, "")).strip():
            return False, f"{provider} base URL is required"
        return True, ""
    field = CREDENTIAL_FIELDS[provider]
    key = str(secrets.get(field, "")).strip()
    if not key or len(key) < 8:
        return False, f"{provider} API key is required"
    return True, ""


def is_configured() -> bool:
    if not onboarding_complete():
        return False
    user = load_user_config()
    if not user.get("os_system"):
        return False
    ok, _ = validate_provider_config(get_llm_provider_name())
    if not ok:
        return False
    ok, _ = validate_voice_config(user)
    return ok
