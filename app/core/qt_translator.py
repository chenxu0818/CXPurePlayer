"""Qt 内置组件（文件对话框 / 输入框 / 消息框）的标准按钮与标签翻译。"""

from __future__ import annotations

import os

import PySide6
from PySide6.QtCore import QTranslator

from .settings import resource_root

_SUPPORTED = {"zh_CN", "zh_TW", "en"}
_INSTALLED: list[QTranslator] = []


def install_qt_translator(app, language: str) -> None:
    """随界面语言切换 Qt 自带翻译；找不到文件时保留 Qt 默认英文。"""
    for translator in _INSTALLED:
        app.removeTranslator(translator)
    _INSTALLED.clear()

    code = language if language in _SUPPORTED else "zh_CN"
    name = f"qtbase_{code}.qm"
    candidates = [
        os.path.join(resource_root(), "translations", name),
        os.path.join(os.path.dirname(PySide6.__file__), "translations", name),
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        translator = QTranslator(app)
        if translator.load(path):
            app.installTranslator(translator)
            _INSTALLED.append(translator)
            return
