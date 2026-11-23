"""统一对话框工具：统一按钮尺寸、文件对话框尺寸与文本输入对话框。

所有自定义对话框的“确定 / 取消 / 关闭”等按钮统一使用 26px 高、64px 宽
（由 QSS 的 compact 属性控制），并水平居中。文件对话框统一放大并加宽侧栏，
避免长路径、文件名和频道列表被截断。
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ..core.i18n import TRANSLATIONS, tr
from .widget_utils import set_window_icon, translate_standard_buttons

DIALOG_BUTTON_WIDTH = 64


def compact_button(button: QPushButton, metrics, width: int | None = DIALOG_BUTTON_WIDTH) -> QPushButton:
    """给按钮套用统一 compact 尺寸（高度由 QSS compact 规则控制）。

    width 为 None 时只统一高度、宽度随文字自适应，适合面板中长短不一的按钮。
    """
    button.setProperty("compact", True)
    if width is not None:
        button.setFixedWidth(metrics.s(width))
    return button


def localized_button_width(button: QPushButton, source: str, metrics, padding: int = 26) -> int:
    """按所有语言中最长的译文计算按钮宽度，保证切换语言时宽度不变且文字完整。"""
    font_metrics = button.fontMetrics()
    candidates = {source}
    for dictionary in TRANSLATIONS.values():
        candidates.add(dictionary.get(source, source))
    return max(font_metrics.horizontalAdvance(text) for text in candidates) + metrics.s(padding)


def centered_buttons(*buttons: QPushButton) -> QHBoxLayout:
    """把按钮放在一行正中间。"""
    row = QHBoxLayout()
    row.addStretch(1)
    for button in buttons:
        row.addWidget(button)
    row.addStretch(1)
    return row


def prepare_file_dialog(dialog: QFileDialog, metrics, width: int = 920, height: int = 620) -> QFileDialog:
    """放大非原生文件对话框，并给左侧导航栏足够的宽度。"""
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setViewMode(QFileDialog.ViewMode.Detail)
    # Qt 自带的 zh_CN 翻译对文件对话框标签覆盖不完整，显式同步这三处，
    # 避免出现「Look in / Files of type」与按钮中文混排。
    dialog.setLabelText(QFileDialog.DialogLabel.LookIn, tr("查找范围"))
    dialog.setLabelText(QFileDialog.DialogLabel.FileName, tr("文件名称"))
    dialog.setLabelText(QFileDialog.DialogLabel.FileType, tr("文件类型"))
    dialog.setMinimumSize(metrics.s(width), metrics.s(height))
    dialog.resize(metrics.s(width), metrics.s(height))
    splitter = dialog.findChild(QSplitter, "splitter")
    if splitter is not None:
        sidebar_width = metrics.s(190)
        QTimer.singleShot(
            0, lambda: splitter.setSizes([sidebar_width, max(metrics.s(400), dialog.width() - sidebar_width)])
        )
    return dialog


def get_open_files(
    parent: QWidget, title: str, directory: str = "", name_filter: str = "",
    metrics=None, selected_filter: str = "",
) -> Tuple[list[str], str]:
    dialog = QFileDialog(parent, title)
    if metrics is not None:
        prepare_file_dialog(dialog, metrics)
    else:
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
    if name_filter:
        dialog.setNameFilter(name_filter)
    if selected_filter:
        dialog.selectNameFilter(selected_filter)
    if directory:
        dialog.setDirectory(directory)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.selectedFiles(), dialog.selectedNameFilter()
    return [], ""


def get_save_file(
    parent: QWidget, title: str, directory: str = "", name_filter: str = "",
    metrics=None, selected_filter: str = "",
) -> Tuple[str, str]:
    dialog = QFileDialog(parent, title)
    if metrics is not None:
        prepare_file_dialog(dialog, metrics)
    else:
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setFileMode(QFileDialog.FileMode.AnyFile)
    if name_filter:
        dialog.setNameFilter(name_filter)
    if selected_filter:
        dialog.selectNameFilter(selected_filter)
    if directory:
        # directory 参数允许传入完整文件路径：拆分为目录 + 预选文件名，
        # 这样保存对话框会带出默认文件名，而不是空文件名。
        parent_dir, name = os.path.split(directory)
        if os.path.isdir(directory):
            dialog.setDirectory(directory)
        else:
            if parent_dir:
                dialog.setDirectory(parent_dir)
            if name:
                dialog.selectFile(name)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        files = dialog.selectedFiles()
        return (files[0] if files else ""), dialog.selectedNameFilter()
    return "", ""


def get_existing_directory(
    parent: QWidget, title: str, directory: str = "", metrics=None
) -> str:
    dialog = QFileDialog(parent, title)
    if metrics is not None:
        prepare_file_dialog(dialog, metrics)
    else:
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    if directory:
        dialog.setDirectory(directory)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        files = dialog.selectedFiles()
        return files[0] if files else ""
    return ""


class TextInputDialog(QDialog):
    """替代 QInputDialog：更宽的输入框 + 居中统一尺寸的确定/取消。"""

    def __init__(
        self, parent: QWidget, title: str, label: str, text: str = "",
        metrics=None, width: int = 560,
    ) -> None:
        super().__init__(parent)
        self.metrics = metrics
        self.setWindowTitle(title)
        set_window_icon(self)
        scale_width = metrics.s(width) if metrics is not None else width
        self.setMinimumWidth(scale_width)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.edit = QLineEdit(text)
        self.edit.setMinimumWidth(scale_width - metrics.s(120) if metrics is not None else scale_width - 120)
        form.addRow(QLabel(label), self.edit)
        layout.addLayout(form)

        self.ok_btn = compact_button(QPushButton(tr("确定")), metrics)
        self.ok_btn.setObjectName("primaryButton")
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn = compact_button(QPushButton(tr("取消")), metrics)
        self.cancel_btn.clicked.connect(self.reject)
        layout.addLayout(centered_buttons(self.ok_btn, self.cancel_btn))
        translate_standard_buttons(self)

    @classmethod
    def get_text(
        cls, parent: QWidget, title: str, label: str, text: str = "",
        metrics=None,
    ) -> Tuple[str, bool]:
        dialog = cls(parent, title, label, text, metrics)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.edit.text(), True
        return text, False
