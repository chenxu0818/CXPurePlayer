"""macOS 视频显示区：QOpenGLWidget + libmpv 渲染上下文。

macOS 上直接把 NSView 句柄作为 wid 传给 libmpv，会在创建视频输出时崩溃。
这里改用 vo=libmpv，由本控件提供 OpenGL 上下文并逐帧渲染，播放仍然嵌入主窗口。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QObject, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QMouseEvent, QOpenGLContext, QPainter, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from ..core.i18n import tr
from ..core.theme import palette


class _RenderUpdateBridge(QObject):
    """把 libmpv 线程的更新请求安全地转到 Qt 主线程。"""
    updateRequested = Signal()


class MpvRenderWidget(QOpenGLWidget):
    filesDropped = Signal(list)
    doubleClicked = Signal()
    wheelVolume = Signal(int)
    renderReady = Signal()

    VIDEO_EXTS = {
        ".mp4", ".mkv", ".mov", ".avi", ".ts", ".flv", ".webm", ".m4v",
        ".wmv", ".m2ts", ".mpg", ".mpeg", ".3gp", ".aac", ".mp3", ".flac", ".wav",
    }

    def __init__(self, metrics, player, parent=None) -> None:
        super().__init__(parent)
        self.m = metrics
        self._player = player
        self._has_media = False
        self._render_ready = False
        self._bridge = _RenderUpdateBridge(self)
        self._bridge.updateRequested.connect(self.update)
        self.setAcceptDrops(True)
        self.setObjectName("videoArea")
        self.setUpdateBehavior(QOpenGLWidget.UpdateBehavior.PartialUpdate)

    # ---------- libmpv 渲染 ----------
    def _get_proc_address(self, _ctx, name) -> int:
        glctx = QOpenGLContext.currentContext()
        if glctx is None or not name:
            return 0
        return int(glctx.getProcAddress(QByteArray(name)))

    def initializeGL(self) -> None:
        ok = self._player.create_render_context(self._get_proc_address)
        if ok:
            self._player.set_render_update_callback(self._bridge.updateRequested.emit)
            self._render_ready = True
        self.renderReady.emit()
        self.update()

    def paintGL(self) -> None:
        self._player.render_frame(self.width(), self.height(), self.defaultFramebufferObject())
        if self._has_media:
            return
        painter = QPainter(self)
        painter.setPen(QColor(palette()["text_soft"]))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("拖入视频文件打开"))
        painter.end()

    # ---------- 与 PlayerWidget 一致的操作接口 ----------
    def native_id(self) -> int:
        # macOS 使用 libmpv 渲染上下文，不需要原生窗口句柄。
        return 0

    def set_has_media(self, value: bool) -> None:
        self._has_media = bool(value)
        self.update()

    def retranslate(self) -> None:
        self.update()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths: list[str] = []
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

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
            super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            self.wheelVolume.emit(5 if delta > 0 else -5)
            event.accept()
        else:
            super().wheelEvent(event)
