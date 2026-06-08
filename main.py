import os
import platform
import sys

if platform.system() == "Windows":
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

import argparse
import asyncio
import random
import threading
from pathlib import Path


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from ui import EmilyUI  # noqa: F401 — ui package (ui/app.py)
from core.engine import EmilyLive, _WAKE_GREETINGS


def main():
    parser = argparse.ArgumentParser(description="E.M.I.L.Y. desktop assistant")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Re-run terminal onboarding wizard",
    )
    args = parser.parse_args()

    from core.onboarding import ensure_onboarded
    ensure_onboarded(force=args.setup)

    ui = EmilyUI("face.png")

    def _play_wake_greeting(emily: EmilyLive) -> None:
        text = random.choice(_WAKE_GREETINGS)
        try:
            from core.voice.policy import speak_ui
            speak_ui(text, player=ui, live_session=emily._live_session, loop=emily._loop)
        except Exception as e:
            print(f"[Sleep] TTS failed ({e}); using speak().")
            emily.speak(text)

    def runner():
        emily = EmilyLive(ui)
        ui._win.set_wake_greeting_handler(lambda: _play_wake_greeting(emily))
        try:
            asyncio.run(emily.run())
        except KeyboardInterrupt:
            print("\nShutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()
