"""Screen/camera vision via Gemini Live API (image + native audio out)."""

from __future__ import annotations

import asyncio
import base64
import re

from google import genai
from google.genai import types

from core.config import get_api_key_for_provider, get_live_model, get_live_voice
from core.engine.audio_output import AudioOutputPlayer

_player = AudioOutputPlayer()


def stop_audio() -> None:
    _player.clear()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


async def analyze_image(
    image_bytes: bytes,
    mime_type: str,
    user_text: str,
    *,
    system_prompt: str,
) -> str:
    """Send image+question on a dedicated Live session; play native audio; return transcript."""
    client = genai.Client(
        api_key=get_api_key_for_provider("gemini"),
        http_options={"api_version": "v1beta"},
    )
    voice = get_live_voice()
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice),
            ),
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=system_prompt,
    )
    model = get_live_model()
    prompt = f"User question: {user_text}"

    _player.start()
    transcript_parts: list[str] = []

    async with client.aio.live.connect(model=model, config=config) as session:
        await session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[
                    types.Part(inline_data=types.Blob(data=image_bytes, mime_type=mime_type)),
                    types.Part(text=prompt),
                ],
            ),
            turn_complete=True,
        )
        async for msg in session.receive():
            sc = msg.server_content
            if not sc:
                continue
            if sc.output_transcription and sc.output_transcription.text:
                transcript_parts.append(sc.output_transcription.text)
            if sc.model_turn and sc.model_turn.parts:
                for part in sc.model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        pcm = part.inline_data.data
                        if isinstance(pcm, str):
                            pcm = base64.b64decode(pcm)
                        _player.feed(pcm)
            if sc.turn_complete:
                break

    await _player.drain()
    return _clean("".join(transcript_parts))
