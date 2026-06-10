"""One-shot verification for the HUD 2.0 rewrite.

    python scripts/verify_hud.py

Runs: byte-compile of the whole tree, import smoke test of every new module
(offscreen Qt), and the offline service unit tests. Exits non-zero on any failure.
GUI-launch checks (`python -m ui.preview`) still require a real display.
"""

from __future__ import annotations

import compileall
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# Run Qt offscreen so imports/instantiation work headless.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAIL = 0


def step(name: str, fn):
    global FAIL
    print(f"\n=== {name} ===")
    try:
        ok = fn()
        if ok is False:
            FAIL += 1
            print(f"  FAILED: {name}")
        else:
            print(f"  OK: {name}")
    except Exception as e:
        import traceback
        FAIL += 1
        print(f"  ERROR: {name}: {e}")
        traceback.print_exc()


def compile_tree():
    ok_ui = compileall.compile_dir(str(BASE / "ui"), quiet=1, maxlevels=5)
    ok_core = compileall.compile_file(str(BASE / "core" / "engine" / "local_voice.py"), quiet=1)
    ok_cfg = compileall.compile_file(str(BASE / "core" / "config.py"), quiet=1)
    ok_act = compileall.compile_file(str(BASE / "actions" / "weather_report.py"), quiet=1)
    return bool(ok_ui and ok_core and ok_cfg and ok_act)


def import_modules():
    mods = [
        "ui.theme", "ui.layout",
        "ui.widgets.base", "ui.widgets.gauges", "ui.widgets.dials",
        "ui.widgets.audio", "ui.widgets.camera_ring", "ui.widgets.reactor",
        "ui.widgets.system", "ui.widgets.weather", "ui.widgets.chrome",
        "ui.widgets.tracking", "ui.widgets.comms", "ui.widgets.gallery",
        "ui.widgets.backdrop", "ui.widgets.fx",
        "ui.services.base", "ui.services.cache", "ui.services.http",
        "ui.services.system_metrics", "ui.services.network", "ui.services.weather",
        "ui.services.trackers", "ui.services.audio_level", "ui.services.hub",
    ]
    import importlib
    for m in mods:
        importlib.import_module(m)
    return True


def build_cockpit_headless():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from ui.app import MainWindow
    win = MainWindow(str(BASE / "face.png"))
    # exercise the facade-critical paths
    win._apply_state("LISTENING")
    win._apply_state("SPEAKING")
    win._apply_state("THINKING")
    assert win.drop is not None
    assert hasattr(win.camera, "get_snapshot_jpeg")
    win.hub.stop()
    win.close()
    return True


def service_tests():
    from ui.services.tests import main as tests_main
    return tests_main() == 0


if __name__ == "__main__":
    step("byte-compile tree", compile_tree)
    step("import all HUD modules", import_modules)
    step("build cockpit (offscreen)", build_cockpit_headless)
    step("offline service tests", service_tests)
    print(f"\n{'='*44}")
    print("VERIFY OK" if FAIL == 0 else f"VERIFY FAILED ({FAIL} step(s))")
    sys.exit(1 if FAIL else 0)
