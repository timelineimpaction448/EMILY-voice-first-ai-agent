"""Gemini Live WebSocket session: 16 kHz mic in, 24 kHz audio out, tools."""

from __future__ import annotations

import asyncio
import json
import traceback
from typing import TYPE_CHECKING

import sounddevice as sd
from google import genai
from google.genai import types

from core.config import get_api_key_for_provider, get_live_model, get_live_voice, get_realtime_models
from core.engine.audio_output import AudioOutputPlayer
from core.engine.prompts import build_system_message, clean_transcript
from core.llm.tools import parse_tool_arguments, to_gemini_declarations
from core.mcp.registry import get_active_tool_declarations
from core.llm.types import ToolCall
from core.tools.executor import ToolExecutor
from core.voice.stt import SAMPLE_RATE as MIC_SAMPLE_RATE

if TYPE_CHECKING:
    from core.engine import EmilyLive

CHANNELS = 1
CHUNK_SIZE = 1024


class GeminiLiveEngine:
    def __init__(self, host: EmilyLive):
        self._host = host
        self._executor = ToolExecutor(host)
        self._player = AudioOutputPlayer()
        self._session = None
        self._is_speaking = False
        self._tool_tasks: set[asyncio.Task] = set()

    @property
    def ui(self):
        return self._host.ui

    @property
    def can_speak(self) -> bool:
        return (
            self._session is not None
            and not self._host._tool_cancel.is_set()
            and not self.ui.muted
            and not self._is_speaking
        )

    async def speak_text(self, text: str) -> None:
        if not self._session or not text:
            return
        await self._session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=text)]),
            turn_complete=True,
        )

    def _build_connect_config(self, voice: str) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice),
                ),
            ),
            system_instruction=build_system_message(),
            tools=[types.Tool(function_declarations=to_gemini_declarations(get_active_tool_declarations()))],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def bootstrap(self) -> None:
        print("[EMILY] Connecting Gemini Live session...")
        api_key = get_api_key_for_provider("gemini")
        self._client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1beta"},
        )
        self._model = get_live_model()
        self._voice = get_live_voice()
        self._config = self._build_connect_config(self._voice)
        self._player.start()
        available = ", ".join(get_realtime_models("gemini")[:4])
        print(f"[EMILY] Gemini Live ready ({self._model}, voice={self._voice})")
        print(f"[EMILY] Live models available: {available}")

    async def _handle_tool_call(self, tool_call) -> None:
        if not tool_call or not tool_call.function_calls or not self._session:
            return
        responses: list[types.FunctionResponse] = []
        for fc in tool_call.function_calls:
            if self._host._tool_cancel.is_set():
                return
            args = {}
            if fc.args:
                if isinstance(fc.args, dict):
                    args = fc.args
                elif isinstance(fc.args, str):
                    try:
                        args = json.loads(fc.args)
                    except json.JSONDecodeError:
                        args = parse_tool_arguments(fc.args)
            tc = ToolCall(id=fc.id or "", name=fc.name or "", arguments=args)
            try:
                result, _silent = await self._executor.execute(tc)
            except Exception as e:
                print(f"[EMILY] Tool {fc.name} failed: {e}")
                traceback.print_exc()
                result = f"Tool '{fc.name}' failed: {e}"
            responses.append(
                types.FunctionResponse(
                    id=fc.id,
                    name=fc.name,
                    response={"result": result},
                ),
            )
        try:
            await self._session.send_tool_response(function_responses=responses)
        except Exception as e:
            print(f"[EMILY] send_tool_response failed: {e}")
            traceback.print_exc()

    def _process_server_message(self, msg) -> None:
        if self._host._tool_cancel.is_set():
            return
        if msg.tool_call:
            task = asyncio.create_task(self._handle_tool_call(msg.tool_call))
            self._tool_tasks.add(task)
            task.add_done_callback(self._tool_tasks.discard)
            return
        if not msg.server_content:
            return
        sc = msg.server_content
        if sc.interrupted:
            self._player.clear()
            self._set_speaking(False)
            self.ui.clear_thinking()
            return
        if sc.model_turn and sc.model_turn.parts:
            for part in sc.model_turn.parts:
                if getattr(part, "thought", False) and part.text:
                    self.ui.append_thinking(part.text)
                elif part.inline_data and part.inline_data.data:
                    pcm = part.inline_data.data
                    if isinstance(pcm, str):
                        import base64
                        pcm = base64.b64decode(pcm)
                    self._set_speaking(True)
                    self._player.feed(pcm)
                elif part.text and not getattr(part, "thought", False):
                    text = clean_transcript(part.text)
                    if text:
                        self.ui.write_log(f"Emily: {text}")
        if sc.input_transcription and sc.input_transcription.text:
            text = clean_transcript(sc.input_transcription.text)
            if text:
                self.ui.write_log(f"You: {text}")
        if sc.turn_complete:
            self._set_speaking(False)
            self.ui.end_thinking_turn()

    async def _receive_loop(self) -> None:
        assert self._session is not None
        # session.receive() yields one model turn then stops; loop until session ends.
        while self._host._session_stop and not self._host._session_stop.is_set():
            try:
                async for msg in self._session.receive():
                    self._process_server_message(msg)
            except Exception as e:
                if self._host._session_stop and self._host._session_stop.is_set():
                    break
                print(f"[EMILY] Gemini receive error: {e}")
                traceback.print_exc()
                raise

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
                if self._session and not self.ui.muted and not self.ui.sleep_mode:
                    with self._host._speaking_lock:
                        if self._host._is_speaking:
                            continue
                    try:
                        await self._session.send_realtime_input(
                            audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000"),
                        )
                    except Exception as e:
                        print(f"[EMILY] Gemini audio send error: {e}")

        sender_task = asyncio.create_task(_sender(), name="gemini-sender")

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
            if text and self._session:
                self.ui.write_log(f"You: {text}")
                await self._session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text=text)]),
                    turn_complete=True,
                )

    async def run(self) -> None:
        await self.bootstrap()
        try:
            async with self._client.aio.live.connect(model=self._model, config=self._config) as session:
                self._session = session
                self.ui.set_voice_ready()
                tasks = [
                    asyncio.create_task(self._receive_loop(), name="gemini-recv"),
                    asyncio.create_task(self._mic_loop(), name="gemini-mic"),
                    asyncio.create_task(self._text_loop(), name="gemini-text"),
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
            self._session = None
            self._player.stop()
