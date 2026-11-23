"""属性信息对话框：仅显示分节式文件信息 + 复制。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout,
)

from ..core.i18n import tr
from ..core.info_format import format_media_info
from ..core.media_info import MediaInfo
from .dialog_utils import centered_buttons, compact_button
from .widget_utils import auto_retranslate, set_window_icon, translate_standard_buttons


class PropertiesDialog(QDialog):
    def __init__(self, metrics, state_provider, info_provider, parent=None) -> None:
        super().__init__(parent)
        self.m = metrics
        self._state_provider = state_provider
        self._info_provider = info_provider
        self.setWindowTitle(tr("属性信息"))
        set_window_icon(self)
        self._last_info = None
        self.setMinimumSize(metrics.s(720), metrics.s(560))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(metrics.s(12), metrics.s(12), metrics.s(12), metrics.s(12))

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.text.setPlainText("")
        font = self.text.font()
        font.setFamily("Consolas")
        font.setPointSizeF(metrics.font(9))
        self.text.setFont(font)
        layout.addWidget(self.text, 1)

        # 与“关闭”按钮使用完全相同的 compact 样式，避免专属 objectName 的
        # min-height 规则覆盖紧凑尺寸导致按钮变形。
        self.copy_btn = compact_button(QPushButton(tr("复制")), metrics)
        self.copy_btn.clicked.connect(self.copy_all)
        self.close_btn = compact_button(QPushButton(tr("关闭")), metrics)
        self.close_btn.clicked.connect(self.reject)
        layout.addLayout(centered_buttons(self.copy_btn, self.close_btn))

    def set_info(self, info: MediaInfo) -> None:
        if info is None:
            return
        self._last_info = info
        self.text.setPlainText(format_media_info(info))

    def copy_all(self) -> None:
        from PySide6.QtWidgets import QApplication, QMessageBox

        content = self.text.toPlainText()
        if content:
            QApplication.clipboard().setText(content)
        QMessageBox.information(self, tr("提示"), tr("已复制到剪贴板"))

    def retranslate(self) -> None:
        auto_retranslate(self)
        translate_standard_buttons(self)
        if self._last_info is not None:
            self.set_info(self._last_info)
