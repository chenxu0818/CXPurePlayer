"""IPTV 抽屉页：频道树（增删改/导入导出）与录制任务列表（停止/取消等）。"""

from __future__ import annotations

import os
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core.i18n import tr
from ..core.models import Channel
from .dialog_utils import (
    TextInputDialog, compact_button, get_open_files, get_save_file,
    localized_button_width,
)
from .icons import icon
from .widget_utils import auto_retranslate


class IptvPanel(QWidget):
    playChannel = Signal(object)
    editChannel = Signal(object)
    newTask = Signal(object)
    channelsChanged = Signal(list)

    def __init__(self, metrics, parent=None) -> None:
        super().__init__(parent)
        self.m = metrics
        self._channels: List[Channel] = []
        self._build()
        self.retranslate()

    def _build(self) -> None:
        m = self.m
        layout = QVBoxLayout(self)
        layout.setContentsMargins(m.s(8), m.s(8), m.s(8), m.s(8))
        layout.setSpacing(m.s(6))

        # 频道区
        layout.addWidget(self._section_label(tr("电视台")))
        tool = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("搜索"))
        self.search.textChanged.connect(lambda: self._render_channels())
        self.add_btn = QPushButton(icon("plus", "#4c8dff"), "")
        self.add_btn.setObjectName("iconButton")
        self.add_btn.clicked.connect(self._on_add_channel)
        self.import_btn = QPushButton(icon("open", "#4c8dff"), "")
        self.import_btn.setObjectName("iconButton")
        self.import_btn.setToolTip(tr("导入"))
        self.import_btn.clicked.connect(self._on_import)
        self.export_btn = QPushButton(icon("export", "#4c8dff"), "")
        self.export_btn.setObjectName("iconButton")
        self.export_btn.setToolTip(tr("导出"))
        self.export_btn.clicked.connect(self._on_export)
        tool.addWidget(self.search, 1)
        tool.addWidget(self.add_btn)
        tool.addWidget(self.import_btn)
        tool.addWidget(self.export_btn)
        layout.addLayout(tool)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(self._on_channel_double_click)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_channel_menu)
        layout.addWidget(self.tree, 2)

        row = QHBoxLayout()
        self.edit_btn = QPushButton(tr("编辑"))
        self.edit_btn.clicked.connect(self._on_edit_channel)
        self.delete_btn = QPushButton(tr("删除"))
        self.delete_btn.clicked.connect(self._on_delete_channel)
        row.addWidget(self.edit_btn)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        layout.addLayout(row)

        # 页面内文字按钮统一 compact 高度；add/import/export 为图标按钮不在此列。
        for btn in (self.edit_btn, self.delete_btn):
            compact_button(btn, m, width=None)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    def retranslate(self) -> None:
        self.search.setPlaceholderText(tr("搜索"))
        self.add_btn.setToolTip(tr("新增频道"))
        self.import_btn.setToolTip(tr("导入"))
        self.export_btn.setToolTip(tr("导出"))
        self.edit_btn.setText(tr("编辑"))
        self.delete_btn.setText(tr("删除"))
        # 按三语最长译文固定宽度：中/英切换时按钮不变宽，且英文全称不截断。
        self.edit_btn.setFixedWidth(localized_button_width(self.edit_btn, "编辑", self.m))
        self.delete_btn.setFixedWidth(localized_button_width(self.delete_btn, "删除", self.m))
        self._render_channels()

    # ---------- 频道 ----------
    def set_channels(self, channels: List[Channel]) -> None:
        self._channels = channels
        self._render_channels()

    def _render_channels(self) -> None:
        keyword = self.search.text().strip().lower() if hasattr(self, "search") else ""
        self.tree.clear()
        groups: dict[str, list[Channel]] = {}
        for channel in self._channels:
            if keyword and keyword not in channel.name.lower() and keyword not in channel.group.lower():
                continue
            groups.setdefault(channel.group, []).append(channel)
        for group_name, items in groups.items():
            parent = QTreeWidgetItem([f"📁 {group_name}  ({len(items)})"])
            parent.setData(0, Qt.ItemDataRole.UserRole, None)
            for channel in items:
                child = QTreeWidgetItem([("○ " if not channel.enabled else "") + channel.name])
                child.setData(0, Qt.ItemDataRole.UserRole, channel)
                child.setToolTip(0, channel.url)
                if not channel.enabled:
                    child.setForeground(0, QColor("#74829b"))
                parent.addChild(child)
            self.tree.addTopLevelItem(parent)
            parent.setExpanded(True)

    def _selected_channel(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def _on_channel_double_click(self, item: QTreeWidgetItem, column: int) -> None:
        channel = item.data(0, Qt.ItemDataRole.UserRole)
        if channel and channel.enabled:
            self.playChannel.emit(channel)

    def _on_channel_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        channel = item.data(0, Qt.ItemDataRole.UserRole)
        if channel is None:
            return
        menu = QMenu(self)
        menu.addAction(tr("播放"), lambda: self.playChannel.emit(channel))
        menu.addAction(tr("编辑"), lambda: self.editChannel.emit(channel))
        menu.addAction(tr("新建录制任务"), lambda: self.newTask.emit(channel))
        menu.addAction(tr("删除"), self._on_delete_channel)
        menu.exec(self.tree.mapToGlobal(pos))

    def _on_add_channel(self) -> None:
        name, ok = TextInputDialog.get_text(
            self, tr("新增频道"), tr("频道名称"), metrics=self.m
        )
        if not ok or not name.strip():
            return
        url, ok = TextInputDialog.get_text(self, tr("新增频道"), "URL", metrics=self.m)
        if not ok or not url.strip():
            return
        group, ok = TextInputDialog.get_text(
            self, tr("新增频道"), tr("分组"), "默认分组", self.m
        )
        channel = Channel(name=name.strip(), url=url.strip(), group=group.strip() or "默认分组")
        self._channels.append(channel)
        self._emit_channels()

    def _on_edit_channel(self) -> None:
        channel = self._selected_channel()
        if channel:
            self.editChannel.emit(channel)

    def apply_channel_edit(self, old: Channel, new: Channel) -> None:
        for index, item in enumerate(self._channels):
            if item is old:
                self._channels[index] = new
                break
        self._emit_channels()

    def _on_delete_channel(self) -> None:
        channel = self._selected_channel()
        if channel is None:
            return
        if QMessageBox.question(self, tr("提示"), f"{tr('删除')} {channel.name}?") != QMessageBox.StandardButton.Yes:
            return
        self._channels = [item for item in self._channels if item is not channel]
        self._emit_channels()

    def _emit_channels(self) -> None:
        self._render_channels()
        self.channelsChanged.emit(self._channels)

    def _on_import(self) -> None:
        paths, _ = get_open_files(
            self, tr("导入频道列表"), "", tr("M3U 列表 (*.m3u *.m3u8);;所有文件 (*.*)"),
            self.m,
        )
        if paths:
            self.importRequested.emit(paths)

    importRequested = Signal(list)
    exportRequested = Signal(str)

    def _on_export(self) -> None:
        path, _ = get_save_file(
            self, tr("导出频道列表"), "channels.m3u", tr("M3U (*.m3u)"), self.m
        )
        if path:
            self.exportRequested.emit(path)

