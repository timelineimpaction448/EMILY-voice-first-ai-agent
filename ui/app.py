"""Emily HUD 2.0 — starship cockpit window.

`EmilyUI` keeps the exact facade the engine depends on (set_state, write_log,
append_thinking*, set_voice_ready, muted, sleep_mode, current_file,
on_text_command, on_stop, get_camera_detections, start/stop_speaking, root).
The MainWindow composes the cockpit from ui/layout.py and ui/widgets/*.
"""

from __future__ import annotations

import os
import platform
import random
import sys
import threading
import time
from pathlib import Path

if platform.system() == "Windows":
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QVBoxLayout, QWidget,
)

from ui.theme import C, hud_font
from ui.floating_orb import FloatingOrbWindow
from ui.widgets.base import anim_clock

_WAKE_GREETINGS = ("Hello.", "Hi.", "Hi there.")
_DEFAULT_SLEEP_FACE_TIMEOUT_SEC = 300
_OS = platform.system()

_DEFAULT_W, _DEFAULT_H = 1280, 800
_MIN_W, _MIN_H = 1000, 680


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _sleep_mode_enabled() -> bool:
    from core.config import get_sleep_mode_enabled
    return get_sleep_mode_enabled()


def _sleep_face_timeout_sec() -> int:
    from core.config import get_sleep_face_timeout_sec
    return get_sleep_face_timeout_sec(_DEFAULT_SLEEP_FACE_TIMEOUT_SEC)


class MainWindow(QMainWindow):
    _log_sig = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _voice_ready_sig = pyqtSignal(bool)
    _think_append_sig = pyqtSignal(str)
    _think_line_sig = pyqtSignal(str)
    _think_end_sig = pyqtSignal()
    _think_clear_sig = pyqtSignal()

    def __init__(self, face_path: str):
        super().__init__()
        self._face_path = face_path
        self.setWindowTitle("E.M.I.L.Y. — Cockpit HUD")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move((screen.width() - _DEFAULT_W) // 2, (screen.height() - _DEFAULT_H) // 2)

        self.on_text_command = None
        self.on_stop = None
        self._wake_greeting_handler = None
        self._muted = True
        self._voice_ready = False
        self._mic_available = False
        self._muted_for_sleep = False
        self._sleep_mode = False
        self._compact_mode = False
        self._frame = 0

        self._floating = FloatingOrbWindow(face_path, on_restore=self._exit_compact_mode)
        self._floating.hide()

        # first-run: ask for the user's location so live weather/sun/moon work
        self._maybe_prompt_location()

        # services + cockpit
        from ui.services.hub import ServiceHub
        from ui.layout import build_cockpit, apply_breakpoints
        self.hub = ServiceHub()
        central = build_cockpit(self, self.hub)
        self.setCentralWidget(central)
        self.hub.start()

        # visual FX level (full / reduced / off)
        from core.config import get_hud_fx
        self._fx = get_hud_fx()
        self._apply_fx(self._fx)

        # pipeline label
        try:
            from core.config import get_pipeline_label
            self.header.set_pipeline(get_pipeline_label())
        except Exception:
            pass

        # signal wiring (engine thread -> widgets)
        self._log_sig.connect(self.log.append_log)
        self._state_sig.connect(self._apply_state)
        self._voice_ready_sig.connect(self.set_voice_ready)
        self._think_append_sig.connect(self.trace.append_chunk)
        self._think_line_sig.connect(self.trace.append_system_line)
        self._think_end_sig.connect(self.trace.end_turn)
        self._think_clear_sig.connect(self.trace.clear_stream)

        # widget callbacks
        self.cmd.submitted.connect(self._send)
        self.drop.file_selected.connect(self._on_file_selected)
        self.controls.mute_btn.clicked.connect(self._toggle_mute)
        self.controls.stop_btn.clicked.connect(self._on_stop)
        self.controls.settings_btn.clicked.connect(self._open_settings)
        self.controls.fs_btn.clicked.connect(self._toggle_fullscreen)
        self.controls.compact_btn.clicked.connect(self._enter_compact_mode)
        self.radar.blip_info.connect(lambda m: self.log.append_log(f"SYS: {m}"))

        self._apply_state("INITIALISING")
        self.log.append_log("SYS: Cockpit online. Loading voice stack...")

        # single Qt timer is AnimClock; we ride it for sleep checks + breakpoints
        anim_clock().tick.connect(self._on_frame)
        apply_breakpoints(self, self.width())

        # shortcuts
        for keys, slot in (
            ("Ctrl+,", self._open_settings),
            ("F4", self._toggle_mute),
            ("F11", self._toggle_fullscreen),
            ("Ctrl+M", self._enter_compact_mode),
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.activated.connect(slot)

    # ----- frame tick: sleep check + camera countdown -----
    def _on_frame(self):
        self._frame += 1
        if self._frame % 90 == 0:  # ~3s at 30fps
            self._check_sleep_mode()

    def resizeEvent(self, event):
        from ui.layout import apply_breakpoints
        apply_breakpoints(self, self.width())
        super().resizeEvent(event)

    # ----- visual FX level -----
    def _fx_targets(self):
        """Widgets that honor set_reduced_motion()."""
        names = ("_central", "scanlines", "reactor", "radar", "ticker",
                 "gauge_trio", "core_grid", "net_spark", "disk", "power",
                 "weather", "wind", "link", "header", "spectrum")
        for n in names:
            w = getattr(self, n, None)
            if w is not None and hasattr(w, "set_reduced_motion"):
                yield w

    def _apply_fx(self, mode: str):
        reduced = mode in ("reduced", "off")
        anim_clock().set_reduced_motion(reduced)
        for w in self._fx_targets():
            try:
                w.set_reduced_motion(reduced)
            except Exception:
                pass
        if mode == "off":
            self._central.set_disabled(True)
            if hasattr(self, "scanlines"):
                self.scanlines.hide()
        elif mode == "full":
            self._start_boot()

    def _start_boot(self):
        from ui.widgets.fx import BootOverlay
        self.boot = BootOverlay(self._central, readiness=self._boot_readiness)
        self.boot.show()
        self.boot.cover()

    def _boot_readiness(self) -> dict:
        return {
            "bus": True,
            "metrics": getattr(self.hub.metrics, "last_good", None) is not None,
            "weather": getattr(self.hub.weather, "last_good", None) is not None,
            "camera": getattr(self.camera, "_status", "") == "live",
            "voice": self._voice_ready,
        }

    # ----- compact mode -----
    def _enter_compact_mode(self):
        if self._compact_mode:
            return
        self._compact_mode = True
        if self.isMinimized():
            self.showNormal()
        self.hide()
        self._floating.set_muted(self._muted)
        self._floating.set_speaking(self.reactor.speaking)
        self._floating.show()
        self._floating.raise_()

    def _exit_compact_mode(self):
        if not self._compact_mode:
            return
        self._compact_mode = False
        self._floating.hide()
        self.show()
        self.raise_()
        self.activateWindow()

    def changeEvent(self, event):
        if (event.type() == QEvent.Type.WindowStateChange
                and self.isMinimized() and not self._compact_mode):
            QTimer.singleShot(0, self._enter_compact_mode)
        super().changeEvent(event)

    def _toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def closeEvent(self, event):
        try:
            self.camera.stop()
        except Exception:
            pass
        try:
            self.hub.stop()
        except Exception:
            pass
        try:
            self._floating.close()
        except Exception:
            pass
        super().closeEvent(event)

    # ----- comms -----
    def _on_stop(self):
        self.log.append_log("SYS: Stop requested.")
        if self.on_stop:
            try:
                self.on_stop()
            except Exception as e:
                self.log.append_log(f"SYS: Stop failed — {e}")

    def _send(self, txt: str):
        txt = (txt or "").strip()
        if not txt:
            return
        self.log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _on_file_selected(self, path: str):
        p = Path(path)
        try:
            size = p.stat().st_size
            size_s = f"{size/1024:.1f} KB" if size < 1024**2 else f"{size/1024**2:.1f} MB"
        except OSError:
            size_s = "?"
        self.log.append_log(f"FILE: {p.name} ({size_s}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size_s} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size_s}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    # ----- mute / voice ready -----
    def _toggle_mute(self):
        if not self._voice_ready:
            self.log.append_log("SYS: Voice stack still loading...")
            return
        if not self._mic_available:
            self.log.append_log(
                "SYS: Mic unavailable — connect to the internet and restart to download voice models.")
            return
        if self._sleep_mode:
            self.log.append_log("SYS: Sleep mode — show your face to the camera to wake.")
            return
        self._apply_mute(not self._muted, user_initiated=True)

    def _apply_mute(self, muted: bool, *, user_initiated: bool = False):
        if self._muted == muted:
            return
        self._muted = muted
        self.reactor.set_muted(muted)
        self.spectrum.set_muted(muted)
        self.controls.set_muted(muted)
        self._floating.set_muted(muted)
        if user_initiated and muted:
            self._muted_for_sleep = False
        if self._sleep_mode and not muted:
            return
        if muted and not self._sleep_mode:
            self._apply_state("MUTED" if self._voice_ready else "INITIALISING")
            if user_initiated:
                self.log.append_log("SYS: Microphone muted.")
        elif not self._sleep_mode and self._voice_ready:
            self._apply_state("LISTENING")
            if user_initiated:
                self.log.append_log("SYS: Microphone active.")

    def set_voice_ready(self, enable_mic: bool = True):
        self._voice_ready = True
        self._mic_available = enable_mic
        if self._sleep_mode:
            return
        if enable_mic:
            self._apply_mute(False)
            self._apply_state("LISTENING")
            self.log.append_log("SYS: E.M.I.L.Y. online.")
        else:
            self._apply_state("THINKING")
            self.log.append_log("SYS: E.M.I.L.Y. online (text-only — mic needs internet for Whisper).")

    # ----- sleep mode -----
    def _check_sleep_mode(self):
        if not _sleep_mode_enabled() or not getattr(self.camera, "_detector", None):
            self.camera.set_countdown(None)
            return
        if self.camera.is_face_visible():
            self.camera.set_countdown(None)
            if self._sleep_mode:
                self._wake_from_sleep()
            return
        timeout = _sleep_face_timeout_sec()
        without = self.camera.get_seconds_without_face()
        if not self._sleep_mode:
            remaining = max(0.0, 1.0 - without / max(1, timeout))
            self.camera.set_countdown(remaining)
            if without >= timeout:
                self._enter_sleep_mode()

    def _enter_sleep_mode(self):
        if self._sleep_mode:
            return
        self._sleep_mode = True
        mins = max(1, _sleep_face_timeout_sec() // 60)
        self.log.append_log(f"SYS: Sleep mode — no face for ~{mins} min. Mic muted.")
        if not self._muted:
            self._muted_for_sleep = True
            self._apply_mute(True)
        self._apply_state("SLEEP")
        self.reactor.set_muted(True)
        self.controls.set_muted(True)
        self.camera.set_countdown(None)

    def set_wake_greeting_handler(self, handler):
        self._wake_greeting_handler = handler

    def _wake_from_sleep(self):
        if not self._sleep_mode:
            return
        self._sleep_mode = False
        self.log.append_log("SYS: Face detected — waking up.")
        unmute_after = self._muted_for_sleep
        self._muted_for_sleep = False
        self._apply_state("LISTENING")
        threading.Thread(target=self._run_wake_greeting, args=(unmute_after,),
                         daemon=True, name="WakeGreeting").start()

    def _run_wake_greeting(self, unmute_after: bool):
        try:
            if self._wake_greeting_handler:
                self._wake_greeting_handler()
            else:
                self._play_wake_greeting_edge()
            self._log_sig.emit("SYS: Wake greeting played.")
        except Exception as e:
            self._log_sig.emit(f"SYS: Wake greeting failed — {e}")
        finally:
            if unmute_after:
                QTimer.singleShot(0, self._finish_wake_unmute)

    def _finish_wake_unmute(self):
        if not self._sleep_mode:
            self._apply_mute(False)

    @staticmethod
    def _play_wake_greeting_edge():
        from core.tts import speak_sync
        speak_sync(random.choice(_WAKE_GREETINGS))

    # ----- state -----
    def _apply_state(self, state: str):
        if self._sleep_mode and state not in ("SLEEP", "SPEAKING"):
            state = "SLEEP"
        speaking = state == "SPEAKING"
        self.reactor.set_state(state)
        self.header.set_state(state)
        self.spectrum.set_speaking(speaking)
        self.spectrum.set_muted(self._muted)
        self._floating.set_speaking(speaking)
        self._floating.set_muted(self._muted)

    # ----- first-run location -----
    def _maybe_prompt_location(self):
        from core.config import weather_location_configured, save_user_config
        if weather_location_configured():
            return
        # never block a headless / offscreen run (verify script, CI) on a modal dialog
        if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
            return
        try:
            dlg = LocationDialog(self)
            if dlg.exec():
                save_user_config({"weather_location": dlg.value() or "auto"})
            else:
                # skipped — fall back to IP geolocation, don't nag again
                save_user_config({"weather_location": "auto"})
        except Exception as e:
            print(f"[UI] Location prompt failed ({e}); using auto.")
            save_user_config({"weather_location": "auto"})

    # ----- settings -----
    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            dlg.apply(self)
            self.log.append_log("SYS: Settings updated.")


class LocationDialog(QDialog):
    """First-run prompt for the user's city / state / country (saved to config)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("E.M.I.L.Y — Set Your Location")
        self.setStyleSheet(f"background: {C.PANEL}; color: {C.TEXT};")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        intro = QLabel(
            "Welcome. Enter your location so I can pull live weather, "
            "sunrise/sunset and other local data. You can change this later in Settings."
        )
        intro.setFont(hud_font(8))
        intro.setStyleSheet(f"color: {C.TEXT_MED};")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        field_css = (f"QLineEdit {{ background: {C.BAR_BG}; color: {C.WHITE}; "
                     f"border: 1px solid {C.BORDER_A}; padding: 5px; }}"
                     f"QLineEdit:focus {{ border: 1px solid {C.GLOW}; }}")

        def _lbl(t):
            l = QLabel(t)
            l.setFont(hud_font(7, True))
            l.setStyleSheet(f"color: {C.GLOW};")
            return l

        lay.addWidget(_lbl("CITY  *"))
        self.city = QLineEdit()
        self.city.setPlaceholderText("e.g. London")
        self.city.setStyleSheet(field_css)
        lay.addWidget(self.city)

        lay.addWidget(_lbl("STATE / REGION  (optional)"))
        self.state = QLineEdit()
        self.state.setPlaceholderText("e.g. England")
        self.state.setStyleSheet(field_css)
        lay.addWidget(self.state)

        lay.addWidget(_lbl("COUNTRY  (optional, e.g. GB)"))
        self.country = QLineEdit()
        self.country.setPlaceholderText("e.g. GB")
        self.country.setStyleSheet(field_css)
        lay.addWidget(self.country)

        btns = QDialogButtonBox()
        save = btns.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        skip = btns.addButton("Skip (use IP location)", QDialogButtonBox.ButtonRole.RejectRole)
        save.clicked.connect(self._on_save)
        skip.clicked.connect(self.reject)
        lay.addWidget(btns)

    def _on_save(self):
        if not self.city.text().strip():
            self.city.setStyleSheet(self.city.styleSheet() + f"QLineEdit {{ border: 1px solid {C.RED}; }}")
            self.city.setFocus()
            return
        self.accept()

    def value(self) -> str:
        parts = [self.city.text().strip(), self.state.text().strip(), self.country.text().strip()]
        return ", ".join([p for p in parts if p])


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cockpit Settings")
        self.setStyleSheet(f"background: {C.PANEL}; color: {C.TEXT};")
        self.setMinimumWidth(360)
        from core.config import (
            get_weather_location, get_weather_units, get_radar_mode, get_hud_reduced_motion,
            get_hud_fx,
        )
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        lay.addWidget(self._label("VISUAL FX"))
        self.fx = QComboBox()
        self.fx.addItems(["full", "reduced", "off"])
        _fx = str(parent._fx) if parent and hasattr(parent, "_fx") else get_hud_fx()
        self.fx.setCurrentText(_fx if _fx in ("full", "reduced", "off") else "full")
        lay.addWidget(self.fx)

        lay.addWidget(self._label("WEATHER LOCATION  (\"auto\" or \"City, CC\")"))
        self.loc = QLineEdit(get_weather_location())
        self.loc.setStyleSheet(self._field())
        lay.addWidget(self.loc)

        lay.addWidget(self._label("UNITS"))
        self.units = QComboBox()
        self.units.addItems(["metric", "imperial"])
        self.units.setCurrentText(get_weather_units())
        lay.addWidget(self.units)

        lay.addWidget(self._label("RADAR MODE"))
        self.radar = QComboBox()
        self.radar.addItems(["iss", "quakes"])
        self.radar.setCurrentText(get_radar_mode())
        lay.addWidget(self.radar)

        self.reduced = QCheckBox("Reduced motion (low-power machines)")
        self.reduced.setChecked(get_hud_reduced_motion())
        lay.addWidget(self.reduced)

        note = QLabel("LLM provider / voice / devices: run  python main.py --setup")
        note.setFont(hud_font(7))
        note.setStyleSheet(f"color: {C.TEXT_DIM};")
        note.setWordWrap(True)
        lay.addWidget(note)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _label(self, text):
        lbl = QLabel(text)
        lbl.setFont(hud_font(7, True))
        lbl.setStyleSheet(f"color: {C.GLOW};")
        return lbl

    def _field(self):
        return (f"QLineEdit {{ background: {C.BAR_BG}; color: {C.WHITE}; "
                f"border: 1px solid {C.BORDER_A}; padding: 4px; }}")

    def apply(self, win):
        from core.config import save_user_config
        loc = self.loc.text().strip() or "auto"
        units = self.units.currentText()
        radar = self.radar.currentText()
        reduced = self.reduced.isChecked()
        fx = self.fx.currentText()
        save_user_config({
            "weather_location": loc,
            "weather_units": units,
            "radar_mode": radar,
            "hud_reduced_motion": reduced,
            "hud_fx": fx,
        })
        # apply live
        try:
            win.hub.weather.set_options(units=units, location=loc)
        except Exception:
            pass
        try:
            win.radar.set_mode(radar)
        except Exception:
            pass
        # FX: apply reduced/off live (switching back to 'full' boot needs restart)
        live_mode = "off" if fx == "off" else ("reduced" if (reduced or fx == "reduced") else "full")
        win._fx = live_mode
        reduced_now = live_mode in ("reduced", "off")
        anim_clock().set_reduced_motion(reduced_now)
        for w in win._fx_targets():
            try:
                w.set_reduced_motion(reduced_now)
            except Exception:
                pass
        try:
            win._central.set_disabled(live_mode == "off")
            if hasattr(win, "scanlines"):
                win.scanlines.setVisible(live_mode != "off")
        except Exception:
            pass


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()

    def protocol(self, *_):
        pass


class EmilyUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        try:
            from core.config import get_hud_version
            if get_hud_version() == 1:
                print("[UI] hud_version=1 (legacy panel HUD) was retired; using cockpit v2.")
        except Exception:
            pass
        self._win = MainWindow(face_path)
        self._win.show()
        self.root = _RootShim(self._app)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if self._win._sleep_mode and v is False:
            return
        if v != self._win._muted:
            self._win._apply_mute(bool(v), user_initiated=True)

    @property
    def current_file(self) -> str | None:
        return self._win.drop.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_stop(self):
        return self._win.on_stop

    @on_stop.setter
    def on_stop(self, cb):
        self._win.on_stop = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def set_voice_ready(self, enable_mic: bool = True):
        self._win._voice_ready_sig.emit(enable_mic)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def append_thinking(self, text: str):
        self._win._think_append_sig.emit(text)

    def append_thinking_line(self, text: str):
        self._win._think_line_sig.emit(text)

    def end_thinking_turn(self):
        self._win._think_end_sig.emit()

    def clear_thinking(self):
        self._win._think_clear_sig.emit()

    def get_camera_detections(self) -> list[dict]:
        if hasattr(self._win, "camera"):
            return self._win.camera.get_detections()
        return []

    @property
    def sleep_mode(self) -> bool:
        return self._win._sleep_mode

    def wait_for_api_key(self):
        pass

    def wait_for_config(self):
        pass

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
