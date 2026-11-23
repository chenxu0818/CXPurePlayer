"""自绘图标：QPainter 生成多尺寸 QIcon，清晰且无需 QtSvg / 外部图片。"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

SIZE_STEPS = (16, 20, 24, 32, 48, 64)


def _draw(painter: QPainter, name: str, size: int, color: QColor) -> None:
    s = float(size)
    c = s / 2.0
    pen = QPen(color)
    pen.setWidthF(max(1.3, s / 16.0))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    def triangle(points, fill=True):
        path = QPainterPath()
        path.moveTo(QPointF(*points[0]))
        for point in points[1:]:
            path.lineTo(QPointF(*point))
        path.closeSubpath()
        if fill:
            painter.setBrush(QBrush(color))
        painter.drawPath(path)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == "play":
        triangle([(c - s * 0.16, c - s * 0.25), (c + s * 0.28, c), (c - s * 0.16, c + s * 0.25)])
    elif name == "pause":
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(c - s * 0.22, c - s * 0.26, s * 0.14, s * 0.52, s * 0.03, s * 0.03)
        painter.drawRoundedRect(c + s * 0.08, c - s * 0.26, s * 0.14, s * 0.52, s * 0.03, s * 0.03)
        painter.setBrush(Qt.BrushStyle.NoBrush)
    elif name == "stop":
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(c - s * 0.23, c - s * 0.23, s * 0.46, s * 0.46, s * 0.05, s * 0.05)
        painter.setBrush(Qt.BrushStyle.NoBrush)
    elif name in ("rewind", "forward"):
        sign = -1 if name == "rewind" else 1
        triangle([
            (c + sign * s * 0.06, c - s * 0.24),
            (c + sign * s * 0.32, c),
            (c + sign * s * 0.06, c + s * 0.24),
        ])
        triangle([
            (c - sign * s * 0.22, c - s * 0.24),
            (c + sign * s * 0.04, c),
            (c - sign * s * 0.22, c + s * 0.24),
        ])
    elif name == "step":
        triangle([(c - s * 0.16, c - s * 0.24), (c + s * 0.22, c), (c - s * 0.16, c + s * 0.24)])
        painter.drawLine(c + s * 0.27, c - s * 0.24, c + s * 0.27, c + s * 0.24)
    elif name == "volume":
        triangle([(c - s * 0.30, c - s * 0.10), (c - s * 0.14, c - s * 0.10), (c + s * 0.02, c - s * 0.26),
                  (c + s * 0.02, c + s * 0.26), (c - s * 0.14, c + s * 0.10), (c - s * 0.30, c + s * 0.10)])
        painter.drawArc(c - s * 0.02, c - s * 0.18, s * 0.34, s * 0.36, -70 * 16, 140 * 16)
        painter.drawArc(c - s * 0.02, c - s * 0.32, s * 0.52, s * 0.64, -65 * 16, 130 * 16)
    elif name == "mute":
        triangle([(c - s * 0.30, c - s * 0.10), (c - s * 0.14, c - s * 0.10), (c + s * 0.02, c - s * 0.26),
                  (c + s * 0.02, c + s * 0.26), (c - s * 0.14, c + s * 0.10), (c - s * 0.30, c + s * 0.10)])
        painter.drawLine(c + s * 0.12, c - s * 0.14, c + s * 0.36, c + s * 0.14)
        painter.drawLine(c + s * 0.36, c - s * 0.14, c + s * 0.12, c + s * 0.14)
    elif name == "list":
        for dy in (-0.22, 0, 0.22):
            painter.drawLine(c - s * 0.26, c + s * dy, c + s * 0.26, c + s * dy)
            painter.drawEllipse(c - s * 0.31, c + s * dy - s * 0.035, s * 0.07, s * 0.07)
    elif name == "fullscreen":
        painter.drawLine(c - s * 0.32, c - s * 0.10, c - s * 0.32, c - s * 0.32)
        painter.drawLine(c - s * 0.32, c - s * 0.32, c - s * 0.10, c - s * 0.32)
        painter.drawLine(c + s * 0.10, c - s * 0.32, c + s * 0.32, c - s * 0.32)
        painter.drawLine(c + s * 0.32, c - s * 0.32, c + s * 0.32, c - s * 0.10)
        painter.drawLine(c - s * 0.32, c + s * 0.10, c - s * 0.32, c + s * 0.32)
        painter.drawLine(c - s * 0.32, c + s * 0.32, c - s * 0.10, c + s * 0.32)
        painter.drawLine(c + s * 0.10, c + s * 0.32, c + s * 0.32, c + s * 0.32)
        painter.drawLine(c + s * 0.32, c + s * 0.32, c + s * 0.32, c + s * 0.10)
    elif name == "restore":
        painter.drawRect(c - s * 0.26, c - s * 0.14, s * 0.40, s * 0.40)
        painter.drawRect(c - s * 0.12, c - s * 0.28, s * 0.40, s * 0.40)
    elif name == "minimize":
        painter.drawLine(c - s * 0.24, c + s * 0.04, c + s * 0.24, c + s * 0.04)
    elif name in ("close", "close_bold"):
        if name == "close_bold":
            # 抽屉标题栏的关闭按钮：加粗描边，保证在深色工具栏上清晰可见
            pen.setWidthF(max(2.0, s / 10.0))
            painter.setPen(pen)
        r = s * (0.26 if name == "close_bold" else 0.22)
        painter.drawLine(c - r, c - r, c + r, c + r)
        painter.drawLine(c + r, c - r, c - r, c + r)
    elif name == "camera":
        painter.drawRoundedRect(c - s * 0.32, c - s * 0.22, s * 0.64, s * 0.44, s * 0.06, s * 0.06)
        painter.drawEllipse(c, c, s * 0.14, s * 0.14)
    elif name == "folder":
        path = QPainterPath()
        path.moveTo(c - s * 0.34, c - s * 0.20)
        path.lineTo(c - s * 0.06, c - s * 0.20)
        path.lineTo(c + s * 0.02, c - s * 0.10)
        path.lineTo(c + s * 0.34, c - s * 0.10)
        path.lineTo(c + s * 0.34, c + s * 0.26)
        path.lineTo(c - s * 0.34, c + s * 0.26)
        path.closeSubpath()
        painter.drawPath(path)
    elif name == "open":
        painter.drawRoundedRect(c - s * 0.34, c - s * 0.24, s * 0.68, s * 0.48, s * 0.06, s * 0.06)
        painter.drawLine(c - s * 0.34, c - s * 0.06, c + s * 0.34, c - s * 0.06)
        painter.drawLine(c - s * 0.10, c + s * 0.04, c + s * 0.10, c + s * 0.04)
    elif name == "export":
        # 托盘 + 向外箭头：导出频道列表
        painter.drawRoundedRect(c - s * 0.32, c + s * 0.02, s * 0.64, s * 0.28, s * 0.04, s * 0.04)
        painter.drawLine(c, c - s * 0.34, c, c + s * 0.10)
        painter.drawLine(c - s * 0.16, c - s * 0.18, c, c - s * 0.34)
        painter.drawLine(c, c - s * 0.34, c + s * 0.16, c - s * 0.18)
    elif name == "settings":
        painter.drawEllipse(c, c, s * 0.30, s * 0.30)
        for angle in range(0, 360, 45):
            rad = angle * 3.14159265 / 180
            x1, y1 = c + 0.30 * s * __import__("math").cos(rad), c + 0.30 * s * __import__("math").sin(rad)
            x2, y2 = c + 0.42 * s * __import__("math").cos(rad), c + 0.42 * s * __import__("math").sin(rad)
            painter.drawLine(x1, y1, x2, y2)
    elif name == "search":
        painter.drawEllipse(c - s * 0.05, c - s * 0.05, s * 0.42, s * 0.42)
        painter.drawLine(c + s * 0.25, c + s * 0.25, c + s * 0.40, c + s * 0.40)
    elif name == "plus":
        painter.drawLine(c - s * 0.26, c, c + s * 0.26, c)
        painter.drawLine(c, c - s * 0.26, c, c + s * 0.26)
    elif name == "edit":
        painter.drawLine(c - s * 0.30, c + s * 0.30, c - s * 0.06, c + s * 0.34)
        painter.drawLine(c - s * 0.06, c + s * 0.34, c + s * 0.34, c - s * 0.06)
        painter.drawLine(c + s * 0.34, c - s * 0.06, c + s * 0.14, c - s * 0.30)
        painter.drawLine(c + s * 0.14, c - s * 0.30, c - s * 0.30, c + s * 0.30)
    elif name == "trash":
        painter.drawLine(c - s * 0.30, c - s * 0.18, c + s * 0.30, c - s * 0.18)
        painter.drawLine(c - s * 0.18, c - s * 0.18, c - s * 0.12, c + s * 0.32)
        painter.drawLine(c + s * 0.18, c - s * 0.18, c + s * 0.12, c + s * 0.32)
        painter.drawLine(c - s * 0.12, c + s * 0.32, c + s * 0.12, c + s * 0.32)
    elif name == "record":
        painter.setBrush(QBrush(color))
        painter.drawEllipse(c, c, s * 0.28, s * 0.28)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(c, c, s * 0.40, s * 0.40)
    elif name == "tv":
        painter.drawRoundedRect(c - s * 0.34, c - s * 0.26, s * 0.68, s * 0.44, s * 0.05, s * 0.05)
        painter.drawLine(c - s * 0.12, c + s * 0.18, c - s * 0.12, c + s * 0.32)
        painter.drawLine(c + s * 0.12, c + s * 0.18, c + s * 0.12, c + s * 0.32)
        painter.drawLine(c - s * 0.24, c + s * 0.32, c + s * 0.24, c + s * 0.32)
    elif name == "info":
        painter.drawEllipse(c, c, s * 0.56, s * 0.56)
        painter.drawLine(c, c - s * 0.06, c, c + s * 0.26)
        painter.drawPoint(c, c - s * 0.22)
    elif name == "check":
        painter.drawLine(c - s * 0.28, c, c - s * 0.06, c + s * 0.22)
        painter.drawLine(c - s * 0.06, c + s * 0.22, c + s * 0.30, c - s * 0.24)
    elif name == "chevron":
        painter.drawLine(c - s * 0.14, c - s * 0.20, c + s * 0.14, c)
        painter.drawLine(c + s * 0.14, c, c - s * 0.14, c + s * 0.20)
    else:
        painter.drawEllipse(c, c, s * 0.36, s * 0.36)


@lru_cache(maxsize=256)
def make_icon(name: str, color_hex: str) -> QIcon:
    icon = QIcon()
    color = QColor(color_hex)
    for size in SIZE_STEPS:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        _draw(painter, name, size, color)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def icon(name: str, color: str = "#dbe3f0") -> QIcon:
    return make_icon(name, color)
