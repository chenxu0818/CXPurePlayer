"""pytest 公共夹具：为 UI 回归测试提供 QApplication 与 Metrics。"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.settings import AppSettings  # noqa: E402
from app.core.ui_scale import Metrics  # noqa: E402


@pytest.fixture(scope="session")
def app() -> QApplication:
    """整个测试会话复用一个 QApplication，避免重复创建。"""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def metrics(app: QApplication) -> Metrics:
    """每个测试使用独立 Metrics，避免缩放状态互相污染。"""
    return Metrics(AppSettings())
