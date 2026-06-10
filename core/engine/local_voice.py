"""Batch voice loop: VAD → STT → chat LLM → TTS (local Supertonic or Deepgram cloud)."""

from __future__ import annotations

import asyncio
import traceback
from datetime import datetime
from typing import TYPE_CHECKING

import sounddevice as sd

from core.engine.prompts import build_system_message, clean_transcript
from core.llm.factory import get_llm_provider
from core.mcp.registry import get_active_tool_declarations
from core.llm.types import Message
from core.tools.executor import ToolExecutor
from core.config import uses_deepgram_voice
from core.voice.stt import SAMPLE_RATE as STT_SAMPLE_RATE, get_stt_engine, preload_stt
from core.voice.tts import preload_tts, speak_sync, stop_speech
from core.voice.vad import VADSegmenter

if TYPE_CHECKING:
    from core.engine import EmilyLive

# Optional, Qt-free HUD audio-level store. Guarded so the engine still runs if
# the UI services package is unavailable (headless/tests).
try:
    from ui.services.audio_level import audio_level as _audio_level
except Exception:  # pragma: no cover
    _audio_level = None

CHANNELS = 1
CHUNK_SIZE = 1024
MAX_HISTORY_TURNS = 20


class LocalVoiceEngine:
    def __init__(self, host: EmilyLive):
        self._host = host
        self._executor = ToolExecutor(host)
        self._history: list[Message] = []
        self._system_message = build_system_message()
        self._last_user_text = ""
        self._tool_started_this_turn = False
        self._stt_ready = False
        self._tts_ready = False

    @property
    def ui(self):
        return self._host.ui

    def _build_messages(self) -> list[Message]:
        msgs = [Message(role="system", content=self._system_message)]
        msgs.extend(self._history[-MAX_HISTORY_TURNS * 2 :])
        return msgs

    def _trim_history(self) -> None:
        if len(self._history) > MAX_HISTORY_TURNS * 2:
            self._history = self._history[-MAX_HISTORY_TURNS * 2 :]

    async def bootstrap(self) -> None:
        if uses_deepgram_voice():
            print("[EMILY] Loading voice stack (Deepgram STT/TTS + local end-of-speech detection)...")
            self.ui.write_log("SYS: Loading voice stack (Deepgram)...")
        else:
            print("[EMILY] Loading voice stack...")
            self.ui.write_log("SYS: Loading voice stack (first run may download models)...")

        status = {"stt": False, "tts": False, "llm": False}

        def _warm_stt() -> None:
            print("[STT] Preloading speech-to-text...")
            self.ui.write_log("SYS: Loading speech-to-text...")
            try:
                preload_stt()
                status["stt"] = True
                print("[STT] Speech-to-text ready")
                self.ui.write_log("SYS: Speech-to-text ready")
            except Exception as exc:
                print(f"[STT] Preload failed: {exc}")
                self.ui.write_log(f"SYS: {exc}")

        def _warm_tts() -> None:
            print("[TTS] Preloading text-to-speech...")
            self.ui.write_log("SYS: Loading text-to-speech...")
            try:
                preload_tts()
                status["tts"] = True
                print("[TTS] Text-to-speech ready")
                self.ui.write_log("SYS: Text-to-speech ready")
            except Exception as exc:
                print(f"[TTS] Preload failed: {exc}")
                self.ui.write_log(f"SYS: {exc}")

        def _warm_llm() -> None:
            from core.llm.tools import to_openai_tools
            print("[LLM] Warming connection...")
            self.ui.write_log("SYS: Warming LLM connection...")
            provider = get_llm_provider()
            to_openai_tools()
            provider.warm_connection()
            status["llm"] = True

        await asyncio.gather(
            asyncio.to_thread(_warm_stt),
            asyncio.to_thread(_warm_tts),
            asyncio.to_thread(_warm_llm),
        )

        self._stt_ready = status["stt"]
        self._tts_ready = status["tts"]
        if not status["llm"]:
            raise RuntimeError("LLM connection failed — check LM Studio is running and reachable.")

    async def _maybe_fallback_search(self, emily_text: str) -> None:
        if self._tool_started_this_turn or self._host._tool_tasks:
            return
        user = self._last_user_text.lower()
        if not user:
            return
        wants_search = any(
            k in user
            for k in (
                "news", "briefing", "financial", "market", "earnings", "economy",
                "geopolitical", "fed ", "inflation", "sector", "granular", "headline",
                "trading", "stock market", "wall street", "crypto", "bitcoin",
            )
        )
        if not wants_search:
            return
        emily = emily_text.lower()
        short_reply = len(emily_text) < 280
        preamble = any(
            p in emily
            for p in (
                "stand by", "standby", "let's see", "let me", "one moment",
                "hold on", "searching", "looking", "pulling", "under the hood",
                "give you", "detail you want",
            )
        )
        if not (short_reply and (preamble or len(emily_text) < 120)):
            return
        query = self._last_user_text
        if any(k in user for k in ("financial", "market", "granular", "earnings", "sector")):
            query = f"detailed US financial markets news today: {query}"
        try:
            from actions.web_search import web_search as web_search_action
            from core.tools.executor import WEB_SEARCH_TIMEOUT_SEC
            result = await self._executor.run_blocking(
                lambda: web_search_action({"query": query}, player=self.ui),
                timeout=WEB_SEARCH_TIMEOUT_SEC,
            )
            followup = (
                "Web search results are ready. Summarize these for the user in detailed "
                f"plain spoken English with no markdown:\n\n{(result or '')[:6000]}"
            )
            await self._process_turn(followup, from_user=False)
        except Exception as e:
            print(f"[EMILY] Fallback search failed: {e}")

    async def _process_turn(self, user_text: str, *, from_user: bool = True) -> None:
        if self._host._tool_cancel.is_set():
            return
        user_text = clean_transcript(user_text)
        if not user_text:
            return

        if from_user:
            now = datetime.now().strftime("%A, %B %d, %Y — %I:%M:%S %p")
            enriched = f"[{now}] {user_text}"
            self._last_user_text = user_text
            self.ui.write_log(f"You: {user_text}")
            self._history.append(Message(role="user", content=enriched))
        else:
            self._history.append(Message(role="user", content=user_text))

        self._tool_started_this_turn = False
        self.ui.set_state("THINKING")
        provider = get_llm_provider()
        max_tool_rounds = 8

        for _ in range(max_tool_rounds):
            if self._host._tool_cancel.is_set():
                return
            response = await asyncio.to_thread(
                provider.chat,
                self._build_messages(),
                get_active_tool_declarations(),
            )

            if response.tool_calls:
                self._tool_started_this_turn = True
                self._history.append(
                    Message(role="assistant", content=response.text or "", tool_calls=response.tool_calls)
                )
                for tc in response.tool_calls:
                    if self._host._tool_cancel.is_set():
                        return
                    result, silent = await self._executor.execute(tc)
                    if silent:
                        continue
                    self._history.append(
                        Message(role="tool", content=result, tool_call_id=tc.id, name=tc.name)
                    )
                continue

            reply = clean_transcript(response.text or "")
            if reply:
                self._history.append(Message(role="assistant", content=reply))
                self._trim_history()
                self.ui.write_log(f"Emily: {reply}")
                self.ui.end_thinking_turn()
                await self._maybe_fallback_search(reply)
                if (
                    self._tts_ready
                    and not self._host._tool_cancel.is_set()
                    and not reply.startswith("Vision module")
                ):
                    await self._host._speak_local(reply)
            break

    async def _listen_and_transcribe(self) -> None:
        if uses_deepgram_voice():
            print("[EMILY] Mic started — VAD detects when you stop speaking, then sends audio to Deepgram STT")
        else:
            print("[EMILY] Mic + VAD started")
        loop = asyncio.get_event_loop()
        stt = get_stt_engine()
        mic_block_reason = ""

        def on_utterance(pcm: bytes) -> None:
            async def _transcribe():
                try:
                    text = await asyncio.to_thread(stt.transcribe_pcm, pcm)
                    text = clean_transcript(text)
                    if text and self._host._utterance_queue:
                        await self._host._utterance_queue.put(text)
                except Exception as e:
                    print(f"[EMILY] STT error: {e}")
                    import traceback
                    traceback.print_exc()
            asyncio.run_coroutine_threadsafe(_transcribe(), loop)

        vad = VADSegmenter(
            on_utterance=on_utterance,
            use_silero=not uses_deepgram_voice(),
        )

        def callback(indata, frames, time_info, status):
            nonlocal mic_block_reason
            with self._host._speaking_lock:
                speaking = self._host._is_speaking
            blocked = ""
            if speaking:
                blocked = "speaking"
            elif self.ui.muted:
                blocked = "muted"
            elif self.ui.sleep_mode:
                blocked = "sleep"
            if blocked:
                if blocked != mic_block_reason:
                    mic_block_reason = blocked
                    if blocked == "sleep":
                        print("[EMILY] Mic paused — sleep mode (show your face to the camera)")
                    elif blocked == "muted":
                        print("[EMILY] Mic paused — voice channel muted")
                return
            mic_block_reason = ""
            if _audio_level is not None:
                try:
                    import numpy as _np
                    rms = float(_np.sqrt(_np.mean(_np.square(indata.astype(_np.float32)))))
                    _audio_level().push_mic_rms(rms)
                except Exception:
                    pass
            vad.feed(indata.tobytes())

        from core.config import get_mic_device_index
        mic_device = get_mic_device_index()

        try:
            with sd.InputStream(
                samplerate=STT_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                device=mic_device,
                callback=callback,
            ):
                while self._host._session_stop and not self._host._session_stop.is_set():
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[EMILY] Mic error: {e}")
            raise

    async def _turn_processor(self) -> None:
        print("[EMILY] Turn processor started")
        while self._host._session_stop and not self._host._session_stop.is_set():
            text = None
            try:
                if self._host._text_queue:
                    try:
                        text = await asyncio.wait_for(self._host._text_queue.get(), timeout=0.2)
                    except asyncio.TimeoutError:
                        pass
                if not text and self._host._utterance_queue:
                    try:
                        text = await asyncio.wait_for(self._host._utterance_queue.get(), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue
                if text:
                    await self._process_turn(text)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[EMILY] Turn error: {e}")
                traceback.print_exc()

    async def run(self) -> None:
        self._system_message = build_system_message()
        await self.bootstrap()
        self.ui.set_voice_ready(enable_mic=self._stt_ready)

        tasks = [
            asyncio.create_task(self._turn_processor(), name="turns"),
        ]
        if self._stt_ready:
            tasks.append(asyncio.create_task(self._listen_and_transcribe(), name="mic"))
        else:
            print("[EMILY] Mic disabled — speech-to-text unavailable (text input still works)")
            self.ui.write_log("SYS: Mic disabled — type commands in the text box below.")
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            if not task.cancelled():
                exc = task.exception()
                if exc:
                    print(f"[EMILY] Task {task.get_name()} failed: {exc}")
