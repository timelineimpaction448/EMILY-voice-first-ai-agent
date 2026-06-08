"""Emily conversation engine facade — local or native realtime voice."""

from __future__ import annotations

import asyncio
import random
import threading
import traceback

from core.config import get_llm_provider_name, get_pipeline_label
from core.engine.prompts import build_system_message
from core.voice.policy import set_live_session, speak_ui
from core.voice.tts import speak_sync, stop_speech

_WAKE_GREETINGS = ("Hello.", "Hi.", "Hi there.")


class EmilyLive:
    def __init__(self, ui):
        self.ui = ui
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session_stop: asyncio.Event | None = None
        self._utterance_queue: asyncio.Queue[str] | None = None
        self._text_queue: asyncio.Queue[str] | None = None
        self._is_speaking = False
        self._speaking_lock = threading.Lock()
        self._tool_cancel = threading.Event()
        self._tool_tasks: set[asyncio.Task] = set()
        self._engine = None
        self._live_session = None
        self.ui.on_text_command = self._on_text_command
        self.ui.on_stop = self.stop_current_action

    def _drain_queue(self, q: asyncio.Queue | None) -> None:
        if not q:
            return
        while True:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break

    def stop_current_action(self) -> None:
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(self._stop_current_action_async(), self._loop)

    async def _stop_current_action_async(self) -> None:
        print("[EMILY] Stop requested")
        self._tool_cancel.set()
        stop_speech()
        if self._live_session and hasattr(self._live_session, "_player"):
            self._live_session._player.clear()
        try:
            from actions.screen_processor import stop_vision_audio
            stop_vision_audio()
        except Exception:
            pass
        self._drain_queue(self._utterance_queue)
        self._drain_queue(self._text_queue)
        self.set_speaking(False)
        for task in list(self._tool_tasks):
            task.cancel()
        self._tool_tasks.clear()
        try:
            from agent.task_queue import get_queue
            get_queue().cancel_all_active()
        except Exception:
            pass
        self.ui.clear_thinking()
        if not self.ui.muted and not self.ui.sleep_mode:
            self.ui.set_state("LISTENING")

    def _on_text_command(self, text: str) -> None:
        self._tool_cancel.clear()
        if not self._loop or not self._text_queue:
            return
        asyncio.run_coroutine_threadsafe(self._text_queue.put(text), self._loop)

    def speak(self, text: str) -> None:
        if self._tool_cancel.is_set() or not text:
            return
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._speak_async(text), self._loop)

    async def _speak_async(self, text: str) -> None:
        if self._live_session:
            speak_ui(text, player=self.ui, live_session=self._live_session, loop=self._loop)
            return
        await self._speak_local(text)

    async def _speak_local(self, text: str) -> None:
        self.set_speaking(True)
        try:
            await asyncio.to_thread(speak_sync, text)
        finally:
            self.set_speaking(False)

    def speak_error(self, tool_name: str, error: str) -> None:
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def set_speaking(self, value: bool) -> None:
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def _create_engine(self):
        from core.voice.policy import uses_native_voice
        if uses_native_voice():
            provider = get_llm_provider_name()
            if provider == "openai":
                from core.engine.openai_realtime import OpenAIRealtimeEngine
                return OpenAIRealtimeEngine(self)
            from core.engine.gemini_live import GeminiLiveEngine
            return GeminiLiveEngine(self)
        from core.engine.local_voice import LocalVoiceEngine
        return LocalVoiceEngine(self)

    async def run(self) -> None:
        while True:
            try:
                self._session_stop = asyncio.Event()
                self._loop = asyncio.get_event_loop()
                self._utterance_queue = asyncio.Queue()
                self._text_queue = asyncio.Queue()
                self._tool_cancel.clear()
                build_system_message()

                pipeline = get_pipeline_label()
                self.ui.write_log(f"SYS: Voice pipeline: {pipeline}")
                print(f"[EMILY] Voice pipeline: {pipeline}")

                self._engine = self._create_engine()
                if hasattr(self._engine, "can_speak"):
                    self._live_session = self._engine
                    set_live_session(self._engine)
                else:
                    self._live_session = None
                    set_live_session(None)

                await self._engine.run()
            except Exception as e:
                print(f"[EMILY] Engine error: {e}")
                traceback.print_exc()
                self.ui.write_log(f"SYS: Engine error — {e}")
            finally:
                set_live_session(None)
                self._live_session = None
                self.set_speaking(False)
                self.ui.set_state("THINKING")

            print("[EMILY] Restarting in 3s...")
            await asyncio.sleep(3)


__all__ = ["EmilyLive", "_WAKE_GREETINGS"]
