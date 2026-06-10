"""Dev harness — run the HUD with a mock engine (no voice stack, no LLM).

    python -m ui.preview            # full UI driven by scripted mock traffic
    python -m ui.preview --gallery  # widget gallery with live sliders
    python -m ui.preview --quiet    # full UI, no scripted traffic (manual poke)

This lets us iterate on the cockpit without loading Whisper/Supertonic/LLM,
which otherwise costs a full model load per UI tweak.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import threading
import time
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))


class MockEngine:
    """Mimics EmilyLive's side of the EmilyUI facade contract on a daemon thread."""

    def __init__(self, ui):
        self.ui = ui
        self.ui.on_text_command = self._on_text
        self.ui.on_stop = self._on_stop
        self._stop = threading.Event()
        self._speaking = False

    def _on_text(self, text: str) -> None:
        self.ui.write_log(f"You: {text}")
        time.sleep(0.4)
        self.ui.set_state("THINKING")
        self.ui.append_thinking_line(f"▸ parsing({text[:24]!r})")
        time.sleep(0.6)
        self.ui.append_thinking("Considering the request… ")
        time.sleep(0.5)
        self.ui.end_thinking_turn()
        self._say(f"Mock reply to: {text[:40]}")

    def _on_stop(self) -> None:
        self.ui.write_log("SYS: Stop requested (mock).")
        self.ui.clear_thinking()
        if not self.ui.muted:
            self.ui.set_state("LISTENING")

    def _say(self, text: str) -> None:
        self.ui.write_log(f"Emily: {text}")
        self.ui.start_speaking()
        self._speaking = True
        # Simulate TTS duration proportional to length.
        dur = min(4.0, 0.6 + len(text) * 0.03)
        end = time.time() + dur
        while time.time() < end and not self._stop.is_set():
            time.sleep(0.05)
        self._speaking = False
        self.ui.stop_speaking()

    def run_script(self) -> None:
        """A repeating storyline that exercises every facade path."""
        time.sleep(1.0)
        self.ui.set_voice_ready(enable_mic=True)
        self.ui.write_log("SYS: Mock engine online.")
        scenes = [
            ("LISTENING", "Awaiting input…", 2.5),
            ("THINKING", "Running diagnostics", 1.8),
            ("PROCESSING", "Executing tool: weather_report", 1.6),
            ("SPEAKING", "It is 22 degrees and clear, sir.", 2.4),
            ("LISTENING", "Standing by", 2.0),
        ]
        while not self._stop.is_set():
            for state, log, dwell in scenes:
                if self._stop.is_set():
                    break
                if state == "SPEAKING":
                    self._say(log)
                    continue
                self.ui.set_state(state)
                self.ui.write_log(f"SYS: {log}")
                if state == "THINKING":
                    for frag in ("analyse ", "plan ", "select tool "):
                        self.ui.append_thinking(frag)
                        time.sleep(0.25)
                    self.ui.end_thinking_turn()
                slept = 0.0
                while slept < dwell and not self._stop.is_set():
                    time.sleep(0.1)
                    slept += 0.1

    def start(self, script: bool = True) -> None:
        if script:
            threading.Thread(target=self.run_script, daemon=True, name="MockEngine").start()

    def stop(self) -> None:
        self._stop.set()


def run_full(script: bool = True) -> None:
    from ui import EmilyUI

    face = str(_BASE / "face.png")
    ui = EmilyUI(face)
    engine = MockEngine(ui)
    engine.start(script=script)
    try:
        ui.root.mainloop()
    finally:
        engine.stop()


def run_gallery() -> None:
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        from ui.widgets.gallery import GalleryWindow
    except Exception as e:
        print(f"[preview] Gallery unavailable yet: {e}")
        return
    win = GalleryWindow()
    win.show()
    app.exec()


def main() -> None:
    ap = argparse.ArgumentParser(description="Emily HUD preview harness")
    ap.add_argument("--gallery", action="store_true", help="Show the widget gallery")
    ap.add_argument("--quiet", action="store_true", help="No scripted mock traffic")
    args = ap.parse_args()
    if args.gallery:
        run_gallery()
    else:
        run_full(script=not args.quiet)


if __name__ == "__main__":
    main()
