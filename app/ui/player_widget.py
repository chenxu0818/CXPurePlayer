"""视频显示区：原生窗口容器、拖放打开、双击全屏、滚轮音量。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QWheelEvent
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ..core.i18n import tr


class PlayerWidget(QFrame):
    filesDropped = Signal(list)
    doubleClicked = Signal()
    wheelVolume = Signal(int)

    VIDEO_EXTS = {
        ".mp4", ".mkv", ".mov", ".avi", ".ts", ".flv", ".webm", ".m4v",
        ".wmv", ".m2ts", ".mpg", ".mpeg", ".3gp", ".aac", ".mp3", ".flac", ".wav",
    }

    def __init__(self, metrics, parent=None) -> None:
        super().__init__(parent)
        self.m = metrics
        self.setObjectName("videoArea")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.hint = QLabel(tr("拖入视频文件打开"))
        self.hint.setObjectName("hint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hint)

    def native_id(self) -> int:
        return int(self.winId())

    def set_has_media(self, value: bool) -> None:
        self.hint.setVisible(not value)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = []
        for url in event.mimeData().urls() or []:
            path = url.toLocalFile()
            if not path:
                continue
            if os.path.isdir(path):
                for name in sorted(os.listdir(path)):
                    full = os.path.join(path, name)
                    if os.path.isfile(full) and os.path.splitext(name)[1].lower() in self.VIDEO_EXTS:
                        paths.append(full)
            elif os.path.isfile(path):
                paths.append(path)
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            self.wheelVolume.emit(5 if delta > 0 else -5)
            event.accept()
        else:
            super().wheelEvent(event)

    def retranslate(self) -> None:
        self.hint.setText(tr("拖入视频文件打开"))
