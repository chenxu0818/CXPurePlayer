"""分辨率自适应：系统 DPI + 应用自动档 + 手动覆盖，统一 Metrics 尺寸源。"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication

# 界面自适应范围：最低 720p，最高 6K（按逻辑分辨率较短边计算）。
MIN_SUPPORTED_SHORT_SIDE = 720
MAX_SUPPORTED_SHORT_SIDE = 3456

# 自动档参考表：(逻辑分辨率较短边上限, scale)
_AUTO_TIERS = [
    (MIN_SUPPORTED_SHORT_SIDE, 1.0),
    (1080, 1.0),
    (1440, 1.25),
    (2160, 1.6),
    (2880, 1.8),
    (MAX_SUPPORTED_SHORT_SIDE, 2.0),
]


def detect_auto_scale() -> float:
    """按主屏“系统缩放后的逻辑分辨率”取自动档，避免重复放大。"""
    app = QGuiApplication.instance()
    if app is None or not app.screens():
        return 1.0
    screen = app.primaryScreen()
    if screen is None:
        return 1.0
    size = screen.size()
    short_side = min(size.width(), size.height())
    # 低于 720p 的逻辑分辨率（如系统高 DPI 缩放后的逻辑值）按 720p 档处理，不再继续缩小 UI。
    short_side = max(MIN_SUPPORTED_SHORT_SIDE, min(MAX_SUPPORTED_SHORT_SIDE, short_side))
    for limit, scale in _AUTO_TIERS:
        if short_side <= limit:
            return scale
    return 2.0


def configure_high_dpi() -> None:
    """必须在 QApplication 创建前调用。"""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    if not hasattr(QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"):
        return
    try:
        from PySide6.QtCore import Qt

        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass


class Metrics(QObject):
    """全局尺寸源：所有界面尺寸必须从此处派生，禁止裸写像素常量。"""

    scaleChanged = Signal(float)

    def __init__(self, settings) -> None:
        super().__init__()
        self._settings = settings
        self._scale = 1.0
        self.recompute()

    # --- 缩放计算 ---
    def recompute(self) -> float:
        if self._settings.ui_scale_mode == "manual":
            scale = self._settings.ui_scale / 100.0
        else:
            scale = detect_auto_scale()
        scale = max(0.8, min(2.0, float(scale)))
        if abs(scale - self._scale) > 1e-6:
            self._scale = scale
            self.scaleChanged.emit(scale)
        return self._scale

    @property
    def scale(self) -> float:
        return self._scale

    def mode_text(self) -> str:
        mode = "手动" if self._settings.ui_scale_mode == "manual" else "自动"
        return f"{mode} / {int(round(self._scale * 100))}%"

    # --- 尺寸派生 ---
    def s(self, px: float) -> int:
        return max(1, int(round(px * self._scale)))

    def font(self, pt: float) -> float:
        return max(8.0, round(pt * self._scale, 1))

    def icon(self, size: int) -> int:
        return self.s(size)

    def apply_font(self, app: QApplication) -> None:
        font = QFont("Microsoft YaHei")
        font.setPointSizeF(9 * self._scale)
        app.setFont(font)
