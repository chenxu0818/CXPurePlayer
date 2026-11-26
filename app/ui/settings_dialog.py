"""设置对话框：语言、主题、UI 缩放、快进步长、录制目录与封装。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from ..core import autostart
from ..core.i18n import LANGUAGES, tr
from ..core.settings import default_record_dir
from ..core.theme import THEME_CHOICES
from ..core.ui_scale import detect_auto_scale
from .dialog_utils import centered_buttons, compact_button, get_existing_directory
from .widget_utils import auto_retranslate, set_window_icon, translate_standard_buttons


class SettingsDialog(QDialog):
    applied = Signal()

    def __init__(self, settings, metrics, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.metrics = metrics
        self.setWindowTitle(tr("设置"))
        set_window_icon(self)
        self.setMinimumWidth(metrics.s(460))
        self._build()

    def _build(self) -> None:
        m = self.metrics
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.language = QComboBox()
        for code, name in LANGUAGES:
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, [c for c, _ in LANGUAGES].index(self.settings.language)))
        form.addRow(tr("界面语言"), self.language)

        self.theme = QComboBox()
        # 主题名经 tr() 显示，切换语言时 auto_retranslate 会按 item_source 反查源文案同步
        for code, name in THEME_CHOICES:
            self.theme.addItem(tr(name), code)
        for index, (code, name) in enumerate(THEME_CHOICES):
            self.theme.setProperty(f"item_source_{index}", name)
        index = next((i for i, (c, _) in enumerate(THEME_CHOICES) if c == self.settings.theme), 0)
        self.theme.setCurrentIndex(index)
        form.addRow(tr("主题"), self.theme)

        self.scale_mode = QComboBox()
        self.scale_mode.addItem(tr("自动"), "auto")
        self.scale_mode.addItem(tr("手动"), "manual")
        self.scale_mode.setCurrentIndex(0 if self.settings.ui_scale_mode == "auto" else 1)
        self.scale_mode.setFixedWidth(m.s(72))
        self.scale_value = QSpinBox()
        self.scale_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scale_value.setRange(80, 200)
        self.scale_value.setSingleStep(10)
        self.scale_value.setValue(self.settings.ui_scale)
        self.scale_value.setFixedWidth(m.s(66))
        self.scale_value.setEnabled(self.settings.ui_scale_mode == "manual")
        self.scale_mode.currentIndexChanged.connect(
            lambda: self.scale_value.setEnabled(self.scale_mode.currentData() == "manual")
        )
        self.refit_btn = compact_button(QPushButton(tr("适配当前屏幕")), m, width=118)
        self.refit_btn.clicked.connect(self._on_refit)
        percent = QLabel("%")
        percent.setFixedWidth(m.s(14))
        scale_row = QHBoxLayout()
        scale_row.setContentsMargins(0, 0, 0, 0)
        scale_row.addWidget(self.scale_mode)
        scale_row.addWidget(self.scale_value)
        scale_row.addWidget(percent)
        scale_row.addWidget(self.refit_btn)
        scale_row.addStretch(1)
        form.addRow(tr("缩放比例"), scale_row)

        self.seek_step = QComboBox()
        for value in (5, 10, 30, 60):
            self.seek_step.addItem(tr(f"{value} 秒"), value)
        self.seek_step.setCurrentIndex(
            [5, 10, 30, 60].index(self.settings.seek_step)
        )
        form.addRow(tr("快进步长"), self.seek_step)

        self.screenshot_format = QComboBox()
        self.screenshot_format.addItems(["png", "jpg", "webp", "bmp"])
        self.screenshot_format.setCurrentText(self.settings.screenshot_format)
        form.addRow(tr("截图格式"), self.screenshot_format)

        self.record_dir = QLineEdit(self.settings.record_dir)
        pick = compact_button(QPushButton(tr("浏览")), m)
        pick.clicked.connect(self._pick_record_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.record_dir, 1)
        dir_row.addWidget(pick)
        form.addRow(tr("录制目录"), dir_row)

        self.record_format = QComboBox()
        for value, label in (
            ("source", tr("同源")), ("ts", "TS"), ("mp4", "MP4"),
            ("mkv", "MKV"),
        ):
            self.record_format.addItem(label, value)
        index = next(
            (i for i in range(self.record_format.count()) if self.record_format.itemData(i) == self.settings.record_format),
            0,
        )
        self.record_format.setCurrentIndex(index)
        form.addRow(tr("封装格式"), self.record_format)

        self.retry = QSpinBox()
        self.retry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.retry.setRange(5, 300)
        self.retry.setValue(self.settings.record_retry_interval)
        form.addRow(tr("重试间隔"), self.retry)

        self.remember = QCheckBox(tr("记住播放位置"))
        self.remember.setChecked(bool(self.settings.get("remember_position", False)))
        form.addRow("", self.remember)

        self.autostart = QCheckBox(tr("开机自启动"))
        self.autostart.setChecked(autostart.is_enabled())
        form.addRow("", self.autostart)

        layout.addLayout(form)
        self.ok_btn = compact_button(QPushButton(tr("确定")), m)
        self.ok_btn.setObjectName("primaryButton")
        self.ok_btn.clicked.connect(self._on_ok)
        self.cancel_btn = compact_button(QPushButton(tr("取消")), m)
        self.cancel_btn.clicked.connect(self.reject)
        self.reset_btn = compact_button(QPushButton(tr("恢复默认")), m, width=80)
        self.reset_btn.clicked.connect(self._on_reset)
        layout.addLayout(centered_buttons(self.ok_btn, self.cancel_btn, self.reset_btn))

    def _pick_record_dir(self) -> None:
        path = get_existing_directory(
            self, tr("录制目录"), self.record_dir.text(), self.metrics
        )
        if path:
            self.record_dir.setText(path)

    def _on_refit(self) -> None:
        self.scale_value.setValue(int(round(detect_auto_scale() * 100)))

    def _on_reset(self) -> None:
        """把当前对话框里的所有设置恢复为出厂默认值（需点确定生效）。"""
        defaults = self.settings.DEFAULTS
        self.language.setCurrentIndex(max(0, [c for c, _ in LANGUAGES].index(defaults["language"])))
        self.theme.setCurrentIndex(
            max(0, next((i for i, (c, _) in enumerate(THEME_CHOICES) if c == defaults["theme"]), 0))
        )
        self.scale_mode.setCurrentIndex(0 if defaults["ui_scale_mode"] == "auto" else 1)
        self.scale_value.setValue(int(defaults["ui_scale"]))
        self.scale_value.setEnabled(self.scale_mode.currentData() == "manual")
        self.seek_step.setCurrentIndex([5, 10, 30, 60].index(int(defaults["seek_step"])))
        self.screenshot_format.setCurrentText(defaults["screenshot_format"])
        # 录制目录恢复为实际默认目录（<APP_ROOT>/record），而非空字符串。
        self.record_dir.setText(default_record_dir())
        self.record_format.setCurrentIndex(0)
        for i in range(self.record_format.count()):
            if self.record_format.itemData(i) == defaults["record_format"]:
                self.record_format.setCurrentIndex(i)
                break
        self.retry.setValue(int(defaults["record_retry_interval"]))
        self.remember.setChecked(bool(defaults["remember_position"]))
        self.autostart.setChecked(False)

    def _on_ok(self) -> None:
        self.settings.language = self.language.currentData()
        self.settings.theme = self.theme.currentData()
        self.settings.ui_scale_mode = self.scale_mode.currentData()
        self.settings.ui_scale = self.scale_value.value()
        self.settings.seek_step = int(self.seek_step.currentData())
        self.settings.screenshot_format = self.screenshot_format.currentText()
        self.settings.record_dir = self.record_dir.text().strip() or self.settings.record_dir
        self.settings.record_format = self.record_format.currentData()
        self.settings.record_retry_interval = self.retry.value()
        self.settings.set("remember_position", self.remember.isChecked())
        error = autostart.set_enabled(self.autostart.isChecked())
        if error:
            QMessageBox.warning(self, tr("提示"), f"{tr('设置开机自启动失败')}：{error}")
        self.applied.emit()
        self.accept()

    def retranslate(self) -> None:
        auto_retranslate(self)
        translate_standard_buttons(self)
