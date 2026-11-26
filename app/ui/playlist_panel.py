"""播放列表抽屉页：文件列表、右键菜单、双击播放。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QVBoxLayout, QWidget,
)

from ..core.i18n import tr
from ..core.models import PlaylistItem
from .dialog_utils import compact_button
from .icons import icon


class PlaylistPanel(QWidget):
    playRequested = Signal(str)
    removeRequested = Signal(str)
    propertiesRequested = Signal(str)
    openFolderRequested = Signal(str)
    filesAdded = Signal(list)

    def __init__(self, metrics, parent=None) -> None:
        super().__init__(parent)
        self.m = metrics
        self._items: list[PlaylistItem] = []
        self._build()
        self.retranslate()

    def _build(self) -> None:
        m = self.m
        layout = QVBoxLayout(self)
        layout.setContentsMargins(m.s(8), m.s(8), m.s(8), m.s(8))
        layout.setSpacing(m.s(6))

        tools = QHBoxLayout()
        # 与对话框按钮统一 compact 高度，宽度随文字自适应
        self.add_btn = compact_button(QPushButton(tr("添加文件")), m, width=None)
        self.add_btn.setIcon(icon("plus", "#4c8dff"))
        self.add_btn.clicked.connect(self._on_add)
        self.clear_btn = compact_button(QPushButton(tr("清空列表")), m, width=None)
        self.clear_btn.setIcon(icon("trash", "#ff6b8a"))
        self.clear_btn.clicked.connect(self.clear)
        tools.addWidget(self.add_btn)
        tools.addWidget(self.clear_btn)
        layout.addLayout(tools)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(self._on_double_click)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list)

    def retranslate(self) -> None:
        self.add_btn.setText(tr("添加文件"))
        self.clear_btn.setText(tr("清空列表"))

    def _on_add(self) -> None:
        from .dialog_utils import get_open_files

        paths, _ = get_open_files(
            self, tr("选择视频文件"), "",
            tr("媒体文件 (*.mp4 *.mkv *.mov *.avi *.ts *.flv *.webm *.m4v *.wmv *.m2ts *.mpg *.3gp "
            "*.aac *.mp3 *.flac *.wav);;所有文件 (*.*)"),
            self.m,
        )
        if paths:
            self.filesAdded.emit(paths)

    def add_paths(self, paths: list[str]) -> None:
        # 规范化 key 去重：正斜杠 / 与反斜杠 \、大小写差异视为同一文件，
        # 避免当前播放视频以两种路径形式被重复加入列表。
        def key(p: str) -> str:
            return os.path.normcase(os.path.abspath(p))
        existing = {key(item.path) for item in self._items}
        for path in paths:
            k = key(path)
            if k in existing:
                continue
            existing.add(k)
            item = PlaylistItem(path=path, name=os.path.basename(path),
                                missing=not os.path.isfile(path))
            self._items.append(item)
            row = QListWidgetItem(("⚠ " if item.missing else "") + item.name)
            row.setToolTip(path)
            if item.missing:
                row.setForeground(QColor("#74829b"))
            self.list.addItem(row)

    def clear(self) -> None:
        self._items.clear()
        self.list.clear()

    def _on_double_click(self, item: QListWidgetItem) -> None:
        row = self.list.row(item)
        if 0 <= row < len(self._items):
            self.playRequested.emit(self._items[row].path)

    def _on_context_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        row = self.list.row(item)
        path = self._items[row].path if 0 <= row < len(self._items) else ""
        menu = QMenu(self)
        actions = [
            (tr("播放"), lambda: self.playRequested.emit(path)),
            (tr("属性信息"), lambda: self.propertiesRequested.emit(path)),
            (tr("打开目录"), lambda: self.openFolderRequested.emit(path)),
            (tr("删除"), lambda: self.removeAt(row)),
        ]
        for text, slot in actions:
            action = menu.addAction(text)
            action.triggered.connect(slot)
        menu.exec(self.list.mapToGlobal(pos))

    def removeAt(self, row: int) -> None:
        if 0 <= row < len(self._items):
            removed = self._items.pop(row)
            self.list.takeItem(row)
            self.removeRequested.emit(removed.path)

    def highlight(self, path: str) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            if 0 <= index < len(self._items) and self._items[index].path == path:
                self.list.setCurrentItem(item)
                break

    @property
    def paths(self) -> list[str]:
        return [item.path for item in self._items]
