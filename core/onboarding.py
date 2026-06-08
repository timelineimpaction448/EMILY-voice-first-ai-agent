"""Terminal onboarding wizard — runs before the PyQt UI starts."""

from __future__ import annotations

import platform
import sys

from core.config import (
    CREDENTIAL_FIELDS,
    LOCAL_API_KEY_FIELDS,
    DEFAULT_CREDENTIALS,
    DEFAULT_DEEPGRAM_STT_MODEL,
    DEFAULT_DEEPGRAM_TTS_VOICE,
    DEFAULT_LIVE_MODELS,
    DEFAULT_LIVE_VOICES,
    DEFAULT_MODELS,
    DEFAULT_STT_MODEL,
    DEFAULT_TTS_VOICE,
    DEFAULT_VOICE_MODE,
    DEEPGRAM_STT_MODELS,
    DEEPGRAM_TTS_VOICES,
    PROVIDER_LABELS,
    PROVIDERS,
    REALTIME_MODELS,
    REALTIME_PROVIDERS,
    REALTIME_VOICES,
    STT_MODELS,
    TTS_VOICES,
    VOICE_MODES,
    get_api_key_for_provider,
    get_llm_provider_name,
    get_realtime_models,
    is_configured,
    resolve_live_model,
    load_config,
    load_secrets,
    onboarding_complete,
    save_secrets,
    save_user_config,
    validate_provider_config,
    resolve_onboarding_model_default,
    validate_voice_config,
    is_live_only_model,
)
from core.devices import list_cameras, list_microphones


def _clear_screen() -> None:
    if sys.platform == "win32":
        import os
        os.system("cls")
    else:
        print("\033[2J\033[H", end="")


def _prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{text}{suffix}: ").strip()
    return value if value else default


def _choose_index(options: list[tuple], label: str, default_index: int = 0) -> int:
    if not options:
        print(f"  No {label} found — using default index 0.")
        return 0
    if len(options) == 1:
        idx, name = options[0]
        print(f"  Only one {label}: {name} (index {idx})")
        return idx
    print(f"\nSelect {label}:")
    for n, (idx, name) in enumerate(options, 1):
        print(f"  {n}. [{idx}] {name}")
    while True:
        raw = input(f"Choice [1-{len(options)}] (default 1): ").strip()
        if not raw:
            return options[0][0]
        try:
            choice = int(raw)
            if 1 <= choice <= len(options):
                return options[choice - 1][0]
        except ValueError:
            pass
        print("  Invalid choice — try again.")


def _detect_os() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "mac"
    if system == "windows":
        return "windows"
    return "linux"


def _collect_os(current: str) -> str:
    detected = _detect_os()
    print(f"\nOperating system (detected: {detected})")
    print("  1. Windows  2. macOS  3. Linux")
    raw = input(f"Choice [1-3] (default auto): ").strip()
    mapping = {"1": "windows", "2": "mac", "3": "linux"}
    if raw in mapping:
        return mapping[raw]
    return current or detected


def _collect_provider(current: str) -> str:
    print("\nLLM provider:")
    for n, p in enumerate(PROVIDERS, 1):
        mark = " *" if p == current else ""
        print(f"  {n}. {PROVIDER_LABELS[p]}{mark}")
    while True:
        raw = input(f"Choice [1-{len(PROVIDERS)}] (default 1): ").strip()
        if not raw:
            return current if current in PROVIDERS else "gemini"
        try:
            choice = int(raw)
            if 1 <= choice <= len(PROVIDERS):
                return PROVIDERS[choice - 1]
        except ValueError:
            pass
        print("  Invalid choice — try again.")


def _collect_credential(provider: str, secrets: dict) -> dict:
    field = CREDENTIAL_FIELDS[provider]
    existing = str(secrets.get(field, "")).strip()
    if provider in ("ollama", "lmstudio"):
        default = existing or DEFAULT_CREDENTIALS[field]
        print(f"\n{PROVIDER_LABELS[provider]} base URL")
        updates = {field: _prompt("Base URL", default)}
        key_field = LOCAL_API_KEY_FIELDS[provider]
        existing_key = str(secrets.get(key_field, "")).strip()
        print("API key (optional — for authenticated remote or proxied endpoints)")
        if existing_key:
            key_value = _prompt("API key (Enter to keep, type 'none' to clear)", existing_key)
        else:
            key_value = _prompt("API key (Enter to skip)")
        if key_value.lower() == "none":
            updates[key_field] = ""
        elif key_value:
            updates[key_field] = key_value
        return updates
    print(f"\n{PROVIDER_LABELS[provider]} API key")
    if existing:
        value = _prompt("API key (Enter to keep existing)", existing)
    else:
        value = _prompt("API key")
    return {field: value}


def _collect_voice_mode(provider: str, current: str) -> str:
    cur = current if current in VOICE_MODES else DEFAULT_VOICE_MODE
    print("\nVoice pipeline:")
    if provider in REALTIME_PROVIDERS:
        print("  1. Native realtime — provider handles STT+TTS (lower latency)")
        print("  2. Local voice stack — faster-whisper + Supertonic")
        print("  3. Deepgram cloud — Deepgram STT + Deepgram TTS")
        default_choice = {"native": "1", "local": "2", "deepgram": "3"}.get(cur, "2")
        raw = input(f"Choice [1-3] (default {default_choice}): ").strip()
        if not raw:
            return cur
        if raw == "1":
            return "native"
        if raw == "2":
            return "local"
        if raw == "3":
            return "deepgram"
        return cur
    print("  1. Local voice stack — faster-whisper + Supertonic")
    print("  2. Deepgram cloud — Deepgram STT + Deepgram TTS")
    default_choice = "2" if cur == "deepgram" else "1"
    raw = input(f"Choice [1-2] (default {default_choice}): ").strip()
    if not raw:
        return cur if cur in ("local", "deepgram") else "local"
    if raw == "1":
        return "local"
    if raw == "2":
        return "deepgram"
    return cur if cur in ("local", "deepgram") else "local"


def _collect_deepgram_credential(secrets: dict) -> dict:
    existing = str(secrets.get("deepgram_api_key", "")).strip()
    print("\nDeepgram API key")
    if existing:
        value = _prompt("API key (Enter to keep existing)", existing)
    else:
        value = _prompt("API key")
    return {"deepgram_api_key": value}


def _collect_live_model(provider: str, current: str, secrets: dict | None = None) -> str:
    if provider == "gemini":
        from core.llm.gemini_live_models import fetch_gemini_live_models, invalidate_cache
        invalidate_cache()
        key = str((secrets or {}).get("gemini_api_key", "")).strip() or get_api_key_for_provider("gemini")
        models = list(fetch_gemini_live_models(api_key=key, force_refresh=True))
        print("  (fetched from Gemini API — bidiGenerateContent models)")
    else:
        models = list(get_realtime_models(provider))
    default = resolve_live_model(provider, current) if current else DEFAULT_LIVE_MODELS.get(provider, models[0] if models else "")
    if default not in models and models:
        default = models[0]
    print(f"\nRealtime model ({provider}):")
    for n, m in enumerate(models, 1):
        mark = " *" if m == default else ""
        print(f"  {n}. {m}{mark}")
    raw = input(f"Choice [1-{len(models)}] (default 1): ").strip()
    if not raw:
        return default
    try:
        choice = int(raw)
        if 1 <= choice <= len(models):
            return models[choice - 1]
    except ValueError:
        pass
    return default


def _collect_live_voice(provider: str, current: str) -> str:
    voices = REALTIME_VOICES.get(provider, ())
    default = current or DEFAULT_LIVE_VOICES.get(provider, voices[0] if voices else "")
    print(f"\nRealtime voice ({provider}):")
    for n, v in enumerate(voices, 1):
        mark = " *" if v == default else ""
        print(f"  {n}. {v}{mark}")
    raw = input(f"Choice [1-{len(voices)}] (default 1): ").strip()
    if not raw:
        return default
    try:
        choice = int(raw)
        if 1 <= choice <= len(voices):
            return voices[choice - 1]
    except ValueError:
        pass
    return default


def _collect_model(provider: str, current: str, *, label: str = "Model") -> str:
    default = resolve_onboarding_model_default(provider, current)
    print(f"\n{label} (blank = {default or 'provider default'})")
    return _prompt(label, default)


def _collect_stt(current: str) -> str:
    print("\nSpeech-to-text model (faster-whisper):")
    for n, m in enumerate(STT_MODELS, 1):
        mark = " *" if m == (current or DEFAULT_STT_MODEL) else ""
        print(f"  {n}. {m}{mark}")
    raw = input(f"Choice [1-{len(STT_MODELS)}] (default {DEFAULT_STT_MODEL}): ").strip()
    if not raw:
        return current or DEFAULT_STT_MODEL
    try:
        choice = int(raw)
        if 1 <= choice <= len(STT_MODELS):
            return STT_MODELS[choice - 1]
    except ValueError:
        pass
    return current or DEFAULT_STT_MODEL


def _collect_tts(current: str) -> str:
    print("\nTTS voice (Supertonic 3):")
    for n, v in enumerate(TTS_VOICES, 1):
        mark = " *" if v == (current or DEFAULT_TTS_VOICE) else ""
        print(f"  {n}. {v}{mark}")
    raw = input(f"Choice [1-{len(TTS_VOICES)}] (default {DEFAULT_TTS_VOICE}): ").strip()
    if not raw:
        return current or DEFAULT_TTS_VOICE
    try:
        choice = int(raw)
        if 1 <= choice <= len(TTS_VOICES):
            return TTS_VOICES[choice - 1]
    except ValueError:
        pass
    return current or DEFAULT_TTS_VOICE


def _collect_deepgram_stt(current: str) -> str:
    print("\nSpeech-to-text model (Deepgram):")
    for n, m in enumerate(DEEPGRAM_STT_MODELS, 1):
        mark = " *" if m == (current or DEFAULT_DEEPGRAM_STT_MODEL) else ""
        print(f"  {n}. {m}{mark}")
    raw = input(f"Choice [1-{len(DEEPGRAM_STT_MODELS)}] (default {DEFAULT_DEEPGRAM_STT_MODEL}): ").strip()
    if not raw:
        return current or DEFAULT_DEEPGRAM_STT_MODEL
    try:
        choice = int(raw)
        if 1 <= choice <= len(DEEPGRAM_STT_MODELS):
            return DEEPGRAM_STT_MODELS[choice - 1]
    except ValueError:
        pass
    return current or DEFAULT_DEEPGRAM_STT_MODEL


def _collect_deepgram_tts(current: str) -> str:
    print("\nTTS voice (Deepgram Aura):")
    for n, v in enumerate(DEEPGRAM_TTS_VOICES, 1):
        mark = " *" if v == (current or DEFAULT_DEEPGRAM_TTS_VOICE) else ""
        print(f"  {n}. {v}{mark}")
    raw = input(f"Choice [1-{len(DEEPGRAM_TTS_VOICES)}] (default {DEFAULT_DEEPGRAM_TTS_VOICE}): ").strip()
    if not raw:
        return current or DEFAULT_DEEPGRAM_TTS_VOICE
    try:
        choice = int(raw)
        if 1 <= choice <= len(DEEPGRAM_TTS_VOICES):
            return DEEPGRAM_TTS_VOICES[choice - 1]
    except ValueError:
        pass
    return current or DEFAULT_DEEPGRAM_TTS_VOICE


def _print_summary(user: dict, provider: str) -> None:
    print("\n" + "=" * 52)
    print("  Configuration summary")
    print("=" * 52)
    print(f"  OS:           {user.get('os_system')}")
    print(f"  LLM:          {PROVIDER_LABELS.get(provider, provider)}")
    voice_mode = user.get("voice_mode", DEFAULT_VOICE_MODE)
    print(f"  Voice mode:   {voice_mode}")
    if voice_mode == "native":
        print(f"  Live model:   {user.get('live_model')}")
        print(f"  Live voice:   {user.get('live_voice')}")
        print(f"  Batch model:  {user.get('llm_model') or '(auto from live model)'}")
    elif voice_mode == "deepgram":
        print(f"  Model:        {user.get('llm_model') or DEFAULT_MODELS.get(provider, '')}")
        print(f"  STT:          {user.get('stt_model')} (Deepgram)")
        print(f"  TTS voice:    {user.get('tts_voice')} (Deepgram)")
    else:
        print(f"  Model:        {user.get('llm_model') or DEFAULT_MODELS.get(provider, '')}")
        print(f"  STT:          {user.get('stt_model')}")
        print(f"  TTS voice:    {user.get('tts_voice')}")
    print(f"  Microphone:   index {user.get('mic_device_index')}")
    print(f"  Camera:       index {user.get('camera_index')}")
    print("=" * 52)


def run_onboarding() -> None:
    _clear_screen()
    print("=" * 52)
    print("  E.M.I.L.Y. — First-time setup")
    print("=" * 52)
    print("Configure your LLM, voice, microphone, and camera.")
    print("Secrets are stored in config/api_keys.json;")
    print("preferences in config/config.json.")
    print("(Voice models may download on first use.)\n")

    existing_user = load_config()
    secrets = load_secrets()

    provider = _collect_provider(existing_user.get("llm_provider", get_llm_provider_name()))
    cred_updates = _collect_credential(provider, secrets)
    merged_secrets = {**secrets, **cred_updates}
    ok, err = validate_provider_config(provider, merged_secrets)
    while not ok:
        print(f"  Error: {err}")
        cred_updates = _collect_credential(provider, merged_secrets)
        merged_secrets = {**secrets, **cred_updates}
        ok, err = validate_provider_config(provider, merged_secrets)

    batch_model_default = existing_user.get("llm_model", "")
    llm_model = ""
    if provider not in REALTIME_PROVIDERS:
        llm_model = _collect_model(provider, batch_model_default)

    voice_mode = _collect_voice_mode(provider, existing_user.get("voice_mode", DEFAULT_VOICE_MODE))
    live_model = ""
    live_voice = ""
    stt_model = existing_user.get("stt_model", DEFAULT_STT_MODEL)
    tts_voice = existing_user.get("tts_voice", DEFAULT_TTS_VOICE)

    if voice_mode == "native":
        live_model = _collect_live_model(provider, existing_user.get("live_model", ""), merged_secrets)
        live_voice = _collect_live_voice(provider, existing_user.get("live_voice", ""))
        batch_default = existing_user.get("llm_model", "")
        if batch_default and is_live_only_model(batch_default, provider):
            batch_default = ""
        llm_model = _collect_model(
            provider,
            batch_default,
            label="Batch model (vision/agent — NOT the live voice model; blank = auto)",
        )
        if llm_model and is_live_only_model(llm_model, provider):
            llm_model = ""
    elif voice_mode == "deepgram":
        dg_updates = _collect_deepgram_credential(merged_secrets)
        merged_secrets = {**merged_secrets, **dg_updates}
        stt_model = _collect_deepgram_stt(existing_user.get("stt_model", DEFAULT_DEEPGRAM_STT_MODEL))
        tts_voice = _collect_deepgram_tts(existing_user.get("tts_voice", DEFAULT_DEEPGRAM_TTS_VOICE))
        if not llm_model:
            llm_model = _collect_model(provider, batch_model_default)
    else:
        if not llm_model:
            llm_model = _collect_model(provider, batch_model_default)
        stt_model = _collect_stt(existing_user.get("stt_model", DEFAULT_STT_MODEL))
        tts_voice = _collect_tts(existing_user.get("tts_voice", DEFAULT_TTS_VOICE))

    os_name = _collect_os(existing_user.get("os_system", ""))

    print("\nScanning audio input devices...")
    mics = list_microphones()
    mic_index = _choose_index(mics, "microphone", existing_user.get("mic_device_index", 0))

    print("\nScanning cameras...")
    cameras = list_cameras()
    camera_index = _choose_index(cameras, "camera", existing_user.get("camera_index", 0))

    user_cfg = {
        "onboarding_complete": True,
        "llm_provider": provider,
        "voice_mode": voice_mode,
        "llm_model": llm_model,
        "stt_model": stt_model,
        "tts_voice": tts_voice,
        "mic_device_index": mic_index,
        "camera_index": camera_index,
        "os_system": os_name,
    }
    if voice_mode == "native":
        user_cfg["live_model"] = live_model
        user_cfg["live_voice"] = live_voice
    else:
        user_cfg.pop("live_model", None)
        user_cfg.pop("live_voice", None)

    ok, err = validate_voice_config(user_cfg, merged_secrets)
    while not ok:
        print(f"  Error: {err}")
        if voice_mode == "native" and provider in REALTIME_PROVIDERS:
            live_model = _collect_live_model(provider, live_model, merged_secrets)
            live_voice = _collect_live_voice(provider, live_voice)
            user_cfg["live_model"] = live_model
            user_cfg["live_voice"] = live_voice
        elif voice_mode == "deepgram":
            dg_updates = _collect_deepgram_credential(merged_secrets)
            merged_secrets = {**merged_secrets, **dg_updates}
            stt_model = _collect_deepgram_stt(stt_model)
            tts_voice = _collect_deepgram_tts(tts_voice)
            user_cfg["stt_model"] = stt_model
            user_cfg["tts_voice"] = tts_voice
        else:
            voice_mode = "local"
            user_cfg["voice_mode"] = "local"
        ok, err = validate_voice_config(user_cfg, merged_secrets)

    _print_summary(user_cfg, provider)
    confirm = input("\nSave and continue? [Y/n]: ").strip().lower()
    if confirm in ("n", "no"):
        print("Restarting setup...\n")
        return run_onboarding()

    save_user_config(user_cfg)
    all_secret_updates = {**cred_updates}
    if voice_mode == "deepgram":
        all_secret_updates.update(
            {k: v for k, v in merged_secrets.items() if k == "deepgram_api_key"}
        )
    save_secrets(all_secret_updates)

    if voice_mode == "deepgram":
        from core.voice.deepgram_client import reset_deepgram_client
        reset_deepgram_client()

    from core.llm.factory import get_llm_provider
    get_llm_provider(force_refresh=True)

    if voice_mode in ("local", "deepgram"):
        print("\n[Setup] Preloading voice models (first run may take several minutes)...")
        try:
            from core.voice.stt import preload_stt
            from core.voice.tts import preload_tts
            preload_stt()
            preload_tts()
            print("[Setup] Voice models ready.")
        except Exception as exc:
            from core.voice.errors import format_voice_model_error
            print(f"[Setup] Voice preload warning: {format_voice_model_error('Voice models', exc)}")
            print("[Setup] Connect to the internet and restart Emily to enable voice.")

    print("\nSetup complete. Starting E.M.I.L.Y...\n")


def ensure_onboarded(*, force: bool = False) -> None:
    if force or not is_configured():
        if not force and onboarding_complete():
            ok, err = validate_provider_config(get_llm_provider_name())
            if ok:
                return
            print(f"[Setup] Config incomplete: {err}")
        run_onboarding()


if __name__ == "__main__":
    ensure_onboarded(force="--setup" in sys.argv or "-f" in sys.argv)
