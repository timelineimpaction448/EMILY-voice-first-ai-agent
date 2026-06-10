"""Comms console widgets: log, neural trace, command input, file pod, controls."""

from __future__ import annotations

import math
import time
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QDragEnterEvent, QDropEvent, QFont, QPainter, QPen,
)
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLineEdit, QPushButton, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget,
)

from ui.theme import C, hud_font, qcol
from ui.widgets.base import anim_clock

_MAX_LOG_BLOCKS = 400
_MAX_TRACE_BLOCKS = 300


# ---------------- mission log ----------------

class LogConsole(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 9))
        self.document().setMaximumBlockCount(_MAX_LOG_BLOCKS)
        self.setStyleSheet(f"""
            QTextEdit {{
                background: rgba(2, 10, 18, 0.80); color: {C.TEXT};
                border: 1px solid {C.BORDER_A}; border-left: 2px solid {C.PRI};
                border-radius: 2px; padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{ background: transparent; width: 8px; border: none; }}
            QScrollBar::handle:vertical {{ background: {C.BORDER_B}; border-radius: 4px; min-height: 20px; }}
        """)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        tl = text.lower()
        if tl.startswith("you:"):
            col = qcol(C.WHITE)
        elif tl.startswith("emily:"):
            col = qcol(C.GLOW)
        elif tl.startswith("file:"):
            col = qcol(C.GREEN)
        elif "err" in tl:
            col = qcol(C.RED)
        else:
            col = qcol(C.ARC)
        cur = self.textCursor()
        ts_fmt = cur.charFormat()
        ts_fmt.setForeground(QBrush(qcol(C.TEXT_DIM)))
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(time.strftime("%H:%M:%S "), ts_fmt)
        fmt = cur.charFormat()
        fmt.setForeground(QBrush(col))
        cur.insertText(text + "\n", fmt)
        self.setTextCursor(cur)
        self.ensureCursorVisible()


# ---------------- neural trace ----------------

class NeuralTrace(QTextEdit):
    """Streaming model reasoning. Dims when idle; line count capped."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 7))
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setPlaceholderText("Neural trace idle…")
        self.document().setMaximumBlockCount(_MAX_TRACE_BLOCKS)
        self._last_activity = 0.0
        self._idle = True
        self.setStyleSheet(self._sheet(idle=True))
        anim_clock().tick.connect(self._idle_check)

    def _sheet(self, idle: bool) -> str:
        border = C.BORDER_A if idle else C.ARC
        color = C.TEXT_DIM if idle else C.TEXT
        return f"""
            QTextEdit {{
                background: rgba(2, 10, 18, 0.80); color: {color};
                border: 1px solid {C.BORDER_A}; border-left: 2px solid {border};
                border-radius: 2px; padding: 5px;
            }}
            QScrollBar:vertical {{ background: transparent; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: {C.BORDER_B}; border-radius: 3px; min-height: 16px; }}
        """

    def _touch(self):
        self._last_activity = time.monotonic()
        if self._idle:
            self._idle = False
            self.setStyleSheet(self._sheet(idle=False))

    def _idle_check(self):
        if not self._idle and (time.monotonic() - self._last_activity) > 6.0:
            self._idle = True
            self.setStyleSheet(self._sheet(idle=True))

    def append_chunk(self, text: str) -> None:
        if not text:
            return
        self._touch()
        cur = self.textCursor()
        fmt = cur.charFormat()
        fmt.setForeground(QBrush(qcol(C.GLOW)))
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(text, fmt)
        self.setTextCursor(cur)
        self.ensureCursorVisible()

    def append_system_line(self, text: str) -> None:
        if not text:
            return
        self._touch()
        cur = self.textCursor()
        fmt = cur.charFormat()
        fmt.setForeground(QBrush(qcol(C.TEXT_MED)))
        cur.movePosition(cur.MoveOperation.End)
        if self.toPlainText() and not self.toPlainText().endswith("\n"):
            cur.insertText("\n", fmt)
        cur.insertText(text.rstrip() + "\n", fmt)
        self.setTextCursor(cur)
        self.ensureCursorVisible()

    def end_turn(self) -> None:
        if not self.toPlainText().strip():
            return
        cur = self.textCursor()
        fmt = cur.charFormat()
        fmt.setForeground(QBrush(qcol(C.BORDER_B)))
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText("\n· · ·\n", fmt)
        self.setTextCursor(cur)
        self.ensureCursorVisible()

    def clear_stream(self) -> None:
        self.clear()


# ---------------- command input ----------------

class CommandInput(QWidget):
    submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: list[str] = []
        self._hist_idx = 0
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)

        self._input = QLineEdit()
        self._input.setPlaceholderText("⌁ command or question…")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.BAR_BG}; color: {C.WHITE};
                border: 1px solid {C.BORDER_A}; border-radius: 2px; padding: 3px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.GLOW}; }}
        """)
        self._input.returnPressed.connect(self._send)
        self._input.installEventFilter(self)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{ background: {C.PANEL}; color: {C.ARC};
                border: 1px solid {C.ARC}; border-radius: 2px; }}
            QPushButton:hover {{ background: {C.PRI_GHO}; color: {C.GLOW}; border: 1px solid {C.GLOW}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeyEvent
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Up:
                self._recall(-1)
                return True
            if key == Qt.Key.Key_Down:
                self._recall(1)
                return True
        return super().eventFilter(obj, event)

    def _recall(self, direction: int):
        if not self._history:
            return
        self._hist_idx = max(0, min(len(self._history), self._hist_idx + direction))
        if self._hist_idx >= len(self._history):
            self._input.clear()
        else:
            self._input.setText(self._history[self._hist_idx])
            self._input.end(False)

    def _send(self):
        txt = self._input.text().strip()
        if not txt:
            return
        self._input.clear()
        self._history.append(txt)
        self._history = self._history[-50:]
        self._hist_idx = len(self._history)
        self.submitted.emit(txt)


# ---------------- circular file drop pod ----------------

_EXT_TO_CAT = {
    **dict.fromkeys(["jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "svg", "ico"], "image"),
    **dict.fromkeys(["mp4", "avi", "mov", "mkv", "wmv", "flv", "webm", "m4v"], "video"),
    **dict.fromkeys(["mp3", "wav", "ogg", "m4a", "aac", "flac", "wma", "opus"], "audio"),
    **dict.fromkeys(["pdf"], "pdf"),
    **dict.fromkeys(["doc", "docx"], "word"),
    **dict.fromkeys(["xls", "xlsx", "ods"], "excel"),
    **dict.fromkeys(["ppt", "pptx"], "pptx"),
    **dict.fromkeys(["py", "js", "ts", "html", "css", "java", "c", "cpp", "go", "rs"], "code"),
    **dict.fromkeys(["zip", "rar", "tar", "gz", "7z"], "archive"),
    **dict.fromkeys(["txt", "md", "rst", "log"], "text"),
    **dict.fromkeys(["csv", "tsv", "json", "xml"], "data"),
}
_CAT_GLYPH = {
    "image": "🖼", "video": "🎬", "audio": "🎵", "pdf": "📄", "word": "📝",
    "excel": "📊", "pptx": "📊", "code": "💻", "archive": "📦", "text": "📃",
    "data": "🔧", "unknown": "📎",
}


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size/1024:.1f} KB"
    if size < 1024 ** 3:
        return f"{size/1024**2:.1f} MB"
    return f"{size/1024**3:.1f} GB"


class FileDropPod(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None, diameter: int = 120):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(diameter, diameter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._current: str | None = None
        self._cat = "unknown"
        self._name = ""
        self._size = ""
        self._drag = False
        anim_clock().tick.connect(self.update)

    def current_file(self) -> str | None:
        return self._current

    def clear_file(self):
        self._current = None
        self.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag = True

    def dragLeaveEvent(self, e):
        self._drag = False

    def dropEvent(self, e: QDropEvent):
        self._drag = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            path, _ = QFileDialog.getOpenFileName(self, "Select a file for Emily", str(Path.home()))
            if path:
                self._set_file(path)

    def _set_file(self, path: str):
        p = Path(path)
        self._current = path
        self._cat = _EXT_TO_CAT.get(p.suffix.lower().lstrip("."), "unknown")
        self._name = p.name
        try:
            self._size = _fmt_size(p.stat().st_size)
        except OSError:
            self._size = ""
        self.update()
        self.file_selected.emit(path)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        r = min(W, H) / 2 - 4
        frame_i = anim_clock().frame

        ring_col = C.GLOW if self._drag else (C.GREEN if self._current else C.PRI_DIM)
        # rotating dashed ring
        p.setPen(QPen(qcol(ring_col, 220), 1.6, Qt.PenStyle.DashLine))
        p.setBrush(QBrush(qcol(C.PANEL2, 180)))
        p.drawEllipse(QPointF(cx, cy), r, r)
        # spinner ticks
        p.setPen(QPen(qcol(ring_col, 150), 1))
        for k in range(12):
            a = math.radians(k * 30 + frame_i * (2 if self._drag else 0.6))
            p.drawLine(QPointF(cx + (r - 5) * math.cos(a), cy + (r - 5) * math.sin(a)),
                       QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))

        if self._current:
            p.setFont(hud_font(int(r * 0.5)))
            p.setPen(QPen(qcol(C.WHITE), 1))
            p.drawText(QRectF(cx - r, cy - r * 0.7, r * 2, r), Qt.AlignmentFlag.AlignCenter,
                       _CAT_GLYPH.get(self._cat, "📎"))
            p.setFont(hud_font(6, True))
            p.setPen(QPen(qcol(C.GREEN), 1))
            nm = self._name if len(self._name) <= 14 else self._name[:11] + "…"
            p.drawText(QRectF(cx - r, cy + r * 0.18, r * 2, 12), Qt.AlignmentFlag.AlignHCenter, nm)
            p.setPen(QPen(qcol(C.TEXT_DIM), 1))
            p.drawText(QRectF(cx - r, cy + r * 0.42, r * 2, 12), Qt.AlignmentFlag.AlignHCenter, self._size)
        else:
            p.setFont(hud_font(int(r * 0.45)))
            p.setPen(QPen(qcol(ring_col), 1))
            p.drawText(QRectF(cx - r, cy - r * 0.55, r * 2, r), Qt.AlignmentFlag.AlignCenter, "+")
            p.setFont(hud_font(6, True))
            p.setPen(QPen(qcol(C.TEXT_DIM), 1))
            p.drawText(QRectF(cx - r, cy + r * 0.3, r * 2, 12), Qt.AlignmentFlag.AlignHCenter,
                       "DROP" if self._drag else "PAYLOAD")


# ---------------- comms controls ----------------

class CommsControls(QWidget):
    """MUTE COMMS / ABORT / SETTINGS / FULLSCREEN / COMPACT."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        self.mute_btn = QPushButton("◉  COMMS ACTIVE")
        self.mute_btn.setFixedHeight(30)
        self.mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self.mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.mute_btn)
        self.set_muted(False)

        self.stop_btn = QPushButton("◼  ABORT")
        self.stop_btn.setFixedHeight(34)
        self.stop_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setStyleSheet(f"""
            QPushButton {{ background: #180008; color: {C.RED}; border: 2px solid {C.RED}; border-radius: 2px; }}
            QPushButton:hover {{ background: {C.RED}; color: {C.WHITE}; }}
        """)
        lay.addWidget(self.stop_btn)

        row = QHBoxLayout()
        row.setSpacing(5)
        self.settings_btn = self._mini("⚙", "Settings (Ctrl+,)")
        self.fs_btn = self._mini("⛶", "Fullscreen (F11)")
        self.compact_btn = self._mini("◳", "Compact (Ctrl+M)")
        for b in (self.settings_btn, self.fs_btn, self.compact_btn):
            row.addWidget(b)
        lay.addLayout(row)

    def _mini(self, text, tip):
        b = QPushButton(text)
        b.setFixedHeight(26)
        b.setToolTip(tip)
        b.setFont(QFont("Courier New", 10))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER_A}; border-radius: 2px; }}
            QPushButton:hover {{ color: {C.GLOW}; border: 1px solid {C.BORDER_B}; }}
        """)
        return b

    def set_muted(self, muted: bool):
        if muted:
            self.mute_btn.setText("⊘  COMMS OFF")
            self.mute_btn.setStyleSheet(
                f"QPushButton {{ background: #140006; color: {C.MUTED_C}; "
                f"border: 1px solid {C.MUTED_C}; border-radius: 2px; }}")
        else:
            self.mute_btn.setText("◉  COMMS ACTIVE")
            self.mute_btn.setStyleSheet(
                f"QPushButton {{ background: #141008; color: {C.ARC}; "
                f"border: 1px solid {C.ARC}; border-radius: 2px; }}"
                f"QPushButton:hover {{ background: #1a1808; color: {C.GLOW}; }}")


# ---------------- chevron page switcher ----------------

class ChevronBar(QWidget):
    """`<<<  PAGE  >>>` switcher for the right console stack."""

    page_changed = pyqtSignal(int)

    def __init__(self, pages: list[str], parent=None):
        super().__init__(parent)
        self._pages = pages
        self._idx = 0
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        anim_clock().tick.connect(self.update)

    @property
    def index(self) -> int:
        return self._idx

    def set_index(self, idx: int):
        self._idx = idx % len(self._pages)
        self.page_changed.emit(self._idx)
        self.update()

    def mousePressEvent(self, e):
        if e.position().x() < self.width() / 2:
            self.set_index(self._idx - 1)
        else:
            self.set_index(self._idx + 1)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        frame_i = anim_clock().frame
        pulse = int(120 + 100 * abs((frame_i % 30) / 30.0 - 0.5) * 2)
        p.setFont(hud_font(9, True))
        p.setPen(QPen(qcol(C.PRI, pulse), 1))
        p.drawText(QRectF(0, 0, 40, H), Qt.AlignmentFlag.AlignCenter, "‹‹‹")
        p.drawText(QRectF(W - 40, 0, 40, H), Qt.AlignmentFlag.AlignCenter, "›››")
        p.setFont(hud_font(8, True))
        p.setPen(QPen(qcol(C.GLOW), 1))
        p.drawText(QRectF(40, 0, W - 80, H), Qt.AlignmentFlag.AlignCenter, self._pages[self._idx])
