"""Always-on-top floating Emily orb (compact / Clippy-style mode)."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from core.config import get_float_orb_position, save_float_orb_position
from ui.orb_widget import EmilyOrbWidget

ORB_WINDOW_SIZE = 72
ORB_OPACITY = 0.7
ORB_MARGIN = 24


class FloatingOrbWindow(QWidget):
    """Frameless floating orb — drag to move, double-click to restore main HUD."""

    def __init__(
        self,
        face_path: str,
        *,
        on_restore: Callable[[], None] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._on_restore = on_restore
        self._drag_offset: QPoint | None = None
        self._dragging = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(ORB_WINDOW_SIZE, ORB_WINDOW_SIZE)
        self.setWindowOpacity(ORB_OPACITY)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._orb = EmilyOrbWidget(face_path, self)
        layout.addWidget(self._orb)

        self._place_initial()

    def _place_initial(self) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geom = screen.availableGeometry()
        saved = get_float_orb_position()
        if saved is not None:
            x, y = saved
            x = max(geom.left(), min(x, geom.right() - self.width()))
            y = max(geom.top(), min(y, geom.bottom() - self.height()))
            self.move(x, y)
            return
        x = geom.right() - self.width() - ORB_MARGIN
        y = geom.bottom() - self.height() - ORB_MARGIN
        self.move(x, y)

    def set_speaking(self, speaking: bool) -> None:
        self._orb.set_speaking(speaking)

    def set_muted(self, muted: bool) -> None:
        self._orb.set_muted(muted)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._drag_offset = None
            save_float_orb_position(self.x(), self.y())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._on_restore:
            self._on_restore()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)
