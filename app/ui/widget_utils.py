"""UI 公共工具：应用图标、Logo、控件级多语言同步。

所有顶层窗口统一使用同一个 Logo；静态文案控件通过 source_text 反查源文案，
切换语言时无需逐个硬编码即可同步。
"""

from __future__ import annotations

import os
import sys
from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QGroupBox,
    QLabel, QLineEdit, QPushButton, QTabWidget, QTableWidget, QWidget,
)

from ..core.i18n import source_text, tr
from ..core.settings import resource_root

_ICON: QIcon | None = None
_PIXMAP: QPixmap | None = None


def _resource(relative: str) -> str:
    return os.path.join(resource_root(), "app", "resources", relative)


def app_icon() -> QIcon:
    global _ICON
    if _ICON is None:
        name = "icon.icns" if sys.platform == "darwin" else "icon.ico"
        path = _resource(name)
        _ICON = QIcon(path) if os.path.isfile(path) else QIcon()
    return _ICON


def app_pixmap(size: int = 24) -> QPixmap:
    global _PIXMAP
    if _PIXMAP is None or _PIXMAP.isNull():
        path = _resource("logo.png")
        _PIXMAP = QPixmap(path) if os.path.isfile(path) else QPixmap()
    if _PIXMAP.isNull():
        return QPixmap()
    return _PIXMAP.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)


def set_window_icon(widget: QWidget) -> None:
    """为任意顶层窗口设置统一 Logo。"""
    icon = app_icon()
    if not icon.isNull():
        widget.setWindowIcon(icon)


def mark_dynamic(widget: QWidget) -> QWidget:
    """标记数值/时间等动态文案，语言切换时不参与反查。"""
    widget.setProperty("no_i18n", True)
    return widget


def _set_text(widget: QWidget, source: str) -> None:
    widget.setProperty("source_text", source)
    translated = tr(source)
    if isinstance(widget, (QLabel, QPushButton, QCheckBox, QGroupBox)):
        widget.setText(translated)


def auto_retranslate(root: QWidget) -> None:
    """递归同步 root 及所有子控件的静态文案。"""
    widgets: Iterable[QWidget] = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        if widget.property("no_i18n"):
            continue

        if isinstance(widget, (QDockWidget, QDialog)):
            stored = widget.property("source_text")
            source = str(stored) if stored else source_text(widget.windowTitle())
            widget.setProperty("source_text", source)
            widget.setWindowTitle(tr(source))

        if isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                key = f"tab_source_{index}"
                stored = widget.property(key)
                source = str(stored) if stored else widget.tabText(index)
                widget.setProperty(key, source)
                widget.setTabText(index, tr(source))

        if isinstance(widget, QTableWidget):
            for index in range(widget.columnCount()):
                key = f"header_source_{index}"
                stored = widget.property(key)
                item = widget.horizontalHeaderItem(index)
                source = str(stored) if stored else (item.text() if item else "")
                if source:
                    widget.setProperty(key, source)
                    if item is not None:
                        item.setText(tr(source))

        if isinstance(widget, QComboBox):
            current = widget.currentIndex()
            for index in range(widget.count()):
                key = f"item_source_{index}"
                stored = widget.property(key)
                source = str(stored) if stored else source_text(widget.itemText(index))
                widget.setProperty(key, source)
                widget.setItemText(index, tr(source))
            widget.setCurrentIndex(current)

        if isinstance(widget, (QLabel, QPushButton, QCheckBox, QGroupBox)):
            if isinstance(widget, QLabel) and widget.objectName() in ("time", "codec"):
                continue
            current = widget.text()
            if not current:
                continue
            stored = widget.property("source_text")
            source = str(stored) if stored else source_text(current)
            _set_text(widget, source)


def translate_standard_buttons(dialog: QWidget) -> None:
    """把 QDialogButtonBox 的标准按钮文本交给当前语言字典。"""
    for box in dialog.findChildren(QDialogButtonBox):
        for role, text in (
            (QDialogButtonBox.StandardButton.Ok, "确定"),
            (QDialogButtonBox.StandardButton.Cancel, "取消"),
            (QDialogButtonBox.StandardButton.Yes, "是"),
            (QDialogButtonBox.StandardButton.No, "否"),
            (QDialogButtonBox.StandardButton.Close, "关闭"),
        ):
            button = box.button(role)
            if button is not None:
                button.setText(tr(text))
