"""OpenAI Realtime WebSocket session with tool support."""

from __future__ import annotations

import asyncio
import base64
import json
import traceback
from typing import TYPE_CHECKING

import sounddevice as sd
from openai import AsyncOpenAI

from core.config import get_api_key_for_provider, get_live_model, get_live_voice
from core.engine.audio_output import AudioOutputPlayer, OUTPUT_SAMPLE_RATE
from core.engine.prompts import build_system_message, clean_transcript
from core.llm.http_client import get_http_client
from core.llm.tools import parse_tool_arguments, to_openai_tools
from core.mcp.registry import get_active_tool_declarations
from core.llm.types import ToolCall
from core.tools.executor import ToolExecutor
from core.voice.stt import SAMPLE_RATE as MIC_SAMPLE_RATE

if TYPE_CHECKING:
    from core.engine import EmilyLive

CHANNELS = 1
CHUNK_SIZE = 1024


class OpenAIRealtimeEngine:
    def __init__(self, host: EmilyLive):
        self._host = host
        self._executor = ToolExecutor(host)
        self._player = AudioOutputPlayer(sample_rate=OUTPUT_SAMPLE_RATE)
        self._connection = None
        self._is_speaking = False
        self._pending_fn_args: dict[str, str] = {}
        self._session_configured = False

    @property
    def ui(self):
        return self._host.ui

    @property
    def can_speak(self) -> bool:
        return (
            self._connection is not None
            and not self._host._tool_cancel.is_set()
            and not self.ui.muted
            and not self._is_speaking
        )

    async def speak_text(self, text: str) -> None:
        if not self._connection or not text:
            return
        self._connection.conversation.item.create(
            item={
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        )
        self._connection.response.create()

    def _session_config(self) -> dict:
        return {
            "type": "realtime",
            "model": get_live_model(),
            "instructions": build_system_message(),
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": MIC_SAMPLE_RATE},
                    "turn_detection": {"type": "server_vad"},
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": OUTPUT_SAMPLE_RATE},
                    "voice": get_live_voice(),
                },
            },
            "tools": to_openai_tools(get_active_tool_declarations()),
        }

    async def bootstrap(self) -> None:
        print("[EMILY] Connecting OpenAI Realtime session...")
        self._client = AsyncOpenAI(
            api_key=get_api_key_for_provider("openai"),
            http_client=get_http_client(),
        )
        self._player.start()
        print(f"[EMILY] OpenAI Realtime ready ({get_live_model()}, voice={get_live_voice()})")

    async def _handle_function_call(self, event) -> None:
        name = getattr(event, "name", "") or ""
        call_id = getattr(event, "call_id", "") or ""
        raw_args = getattr(event, "arguments", "") or self._pending_fn_args.pop(call_id, "")
        args = parse_tool_arguments(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
        tc = ToolCall(id=call_id, name=name, arguments=args)
        result, _silent = await self._executor.execute(tc)
        self._connection.conversation.item.create(
            item={
                "type": "function_call_output",
                "call_id": call_id,
                "output": result,
            },
        )
        self._connection.response.create()

    async def _event_loop(self) -> None:
        assert self._connection is not None
        async for event in self._connection:
            if self._host._tool_cancel.is_set():
                continue
            etype = getattr(event, "type", "")
            if etype == "session.created" and not self._session_configured:
                self._connection.session.update(session=self._session_config())
                self._session_configured = True
                self.ui.set_voice_ready()
                continue
            if etype == "response.output_audio.delta":
                delta = getattr(event, "delta", "")
                if delta:
                    self._set_speaking(True)
                    self._player.feed(base64.b64decode(delta))
            elif etype == "response.done":
                self._set_speaking(False)
                self.ui.end_thinking_turn()
            elif etype == "response.function_call_arguments.delta":
                call_id = getattr(event, "call_id", "")
                delta = getattr(event, "delta", "")
                self._pending_fn_args[call_id] = self._pending_fn_args.get(call_id, "") + delta
            elif etype == "response.function_call_arguments.done":
                await self._handle_function_call(event)
            elif etype == "conversation.item.input_audio_transcription.completed":
                text = clean_transcript(getattr(event, "transcript", "") or "")
                if text:
                    self.ui.write_log(f"You: {text}")
            elif etype == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if delta:
                    self.ui.append_thinking(delta)
            elif etype == "error":
                msg = getattr(event, "message", str(event))
                print(f"[EMILY] OpenAI Realtime error: {msg}")

    def _set_speaking(self, value: bool) -> None:
        self._is_speaking = value
        self._host.set_speaking(value)

    async def _mic_loop(self) -> None:
        loop = asyncio.get_event_loop()
        send_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)

        async def _sender() -> None:
            while self._host._session_stop and not self._host._session_stop.is_set():
                try:
                    chunk = await asyncio.wait_for(send_queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                if self._connection and not self.ui.muted and not self.ui.sleep_mode:
                    with self._host._speaking_lock:
                        if self._host._is_speaking:
                            continue
                    try:
                        self._connection.input_audio_buffer.append(
                            audio=base64.b64encode(chunk).decode("ascii"),
                        )
                    except Exception as e:
                        print(f"[EMILY] OpenAI audio send error: {e}")

        sender_task = asyncio.create_task(_sender(), name="openai-sender")

        def callback(indata, frames, time_info, status):
            with self._host._speaking_lock:
                if self._host._is_speaking or self.ui.muted or self.ui.sleep_mode:
                    return
            try:
                loop.call_soon_threadsafe(send_queue.put_nowait, indata.tobytes())
            except asyncio.QueueFull:
                pass

        from core.config import get_mic_device_index
        mic_device = get_mic_device_index()

        try:
            with sd.InputStream(
                samplerate=MIC_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                device=mic_device,
                callback=callback,
            ):
                while self._host._session_stop and not self._host._session_stop.is_set():
                    await asyncio.sleep(0.1)
        finally:
            sender_task.cancel()
            await asyncio.gather(sender_task, return_exceptions=True)

    async def _text_loop(self) -> None:
        while self._host._session_stop and not self._host._session_stop.is_set():
            try:
                if not self._host._text_queue:
                    await asyncio.sleep(0.1)
                    continue
                text = await asyncio.wait_for(self._host._text_queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            if text and self._connection:
                self.ui.write_log(f"You: {text}")
                self._connection.conversation.item.create(
                    item={
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": text}],
                    },
                )
                self._connection.response.create()

    async def run(self) -> None:
        await self.bootstrap()
        try:
            async with self._client.realtime.connect(model=get_live_model()) as connection:
                self._connection = connection
                self._session_configured = False
                tasks = [
                    asyncio.create_task(self._event_loop(), name="openai-events"),
                    asyncio.create_task(self._mic_loop(), name="openai-mic"),
                    asyncio.create_task(self._text_loop(), name="openai-text"),
                ]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    if not task.cancelled():
                        exc = task.exception()
                        if exc:
                            print(f"[EMILY] Task {task.get_name()} failed: {exc}")
                            traceback.print_exc()
        finally:
            self._connection = None
            self._player.stop()
