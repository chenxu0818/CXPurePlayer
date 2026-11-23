"""界面主题：7 套科技现代风格配色，统一生成全局样式表（支持 UI 缩放）。"""

from __future__ import annotations

import os
import tempfile
from typing import Dict, Optional

THEMES: Dict[str, dict] = {
    "default": {
        "name": "星夜蓝",
        "palette": {
            "bg": "#0e1118", "panel": "#161b26", "panel_alt": "#1d2432",
            "border": "#2a3446", "text": "#dbe3f0", "text_strong": "#f4f7ff",
            "text_soft": "#aab6cb", "muted": "#74829b",
            "accent": "#4c8dff", "accent_hover": "#69a2ff", "accent_text": "#ffffff",
            "accent2": "#8b5cff", "toolbar": "#121722", "menu": "#1a2130",
            "input": "#111722", "progress": "#4c8dff", "playhead": "#ff6b8a",
            "marker": "#3b485e", "success": "#37d39b", "warning": "#ffb454",
            "danger": "#ff5d73",
        },
    },
    "ocean": {
        "name": "深空蓝",
        "palette": {
            "bg": "#081322", "panel": "#0e1e33", "panel_alt": "#142943",
            "border": "#1e4065", "text": "#d5e9ff", "text_strong": "#f2f8ff",
            "text_soft": "#a6c7ea", "muted": "#6d90b8",
            "accent": "#00b4d8", "accent_hover": "#26cbea", "accent_text": "#03121c",
            "accent2": "#4361ee", "toolbar": "#0b1a2d", "menu": "#10223a",
            "input": "#0a192b", "progress": "#00b4d8", "playhead": "#ff5c7a",
            "marker": "#2b587f", "success": "#2dd4bf", "warning": "#fbbf24",
            "danger": "#fb7185",
        },
    },
    "nebula": {
        "name": "霓虹紫",
        "palette": {
            "bg": "#100b1d", "panel": "#19112e", "panel_alt": "#241940",
            "border": "#38285f", "text": "#e8ddff", "text_strong": "#f9f2ff",
            "text_soft": "#c6b0ec", "muted": "#8d77b9",
            "accent": "#b25cff", "accent_hover": "#ca7bff", "accent_text": "#ffffff",
            "accent2": "#ff5da8", "toolbar": "#150e27", "menu": "#1d1436",
            "input": "#130d24", "progress": "#b25cff", "playhead": "#ff5da8",
            "marker": "#57447f", "success": "#4ade80", "warning": "#fbbf24",
            "danger": "#fb6b8e",
        },
    },
    "aurora": {
        "name": "极光绿",
        "palette": {
            "bg": "#081713", "panel": "#0f211c", "panel_alt": "#17302a",
            "border": "#255044", "text": "#d6f5e8", "text_strong": "#f0fff8",
            "text_soft": "#a3d7c2", "muted": "#6c9f8c",
            "accent": "#00d68f", "accent_hover": "#26e7a6", "accent_text": "#04251a",
            "accent2": "#00b4d8", "toolbar": "#0b1b17", "menu": "#122620",
            "input": "#0a1a16", "progress": "#00d68f", "playhead": "#ff7b7b",
            "marker": "#2f6b59", "success": "#4ade80", "warning": "#facc15",
            "danger": "#fb7185",
        },
    },
    "ember": {
        "name": "赛博橙",
        "palette": {
            "bg": "#17100c", "panel": "#221710", "panel_alt": "#302015",
            "border": "#563824", "text": "#f6e7d9", "text_strong": "#fff6ee",
            "text_soft": "#d9bda6", "muted": "#a17d61",
            "accent": "#ff9430", "accent_hover": "#ffac55", "accent_text": "#1c0e04",
            "accent2": "#ff5d73", "toolbar": "#1e140e", "menu": "#271a12",
            "input": "#1a110c", "progress": "#ff9430", "playhead": "#ff5d73",
            "marker": "#7a5436", "success": "#4ade80", "warning": "#fbbf24",
            "danger": "#ff6b6b",
        },
    },
    "techblue": {
        "name": "科技蓝（浅色）",
        "palette": {
            "bg": "#eef3fa", "panel": "#ffffff", "panel_alt": "#f4f8ff",
            "border": "#d8e0ec", "text": "#303a4a", "text_strong": "#16233a",
            "text_soft": "#5d6b80", "muted": "#8b98aa",
            "accent": "#2f7cf6", "accent_hover": "#1f6ae0", "accent_text": "#ffffff",
            "accent2": "#7c5cff", "toolbar": "#ffffff", "menu": "#ffffff",
            "input": "#ffffff", "progress": "#2f7cf6", "playhead": "#f0566b",
            "marker": "#b9c5d6", "success": "#16a37a", "warning": "#d98a09",
            "danger": "#e14b60",
        },
    },
    "stellar": {
        "name": "星空科技",
        "starfield": True,
        "palette": {
            "bg": "#060a18", "panel": "#0c1228", "panel_alt": "#141c39",
            "border": "#273161", "text": "#dfe7ff", "text_strong": "#f7f9ff",
            "text_soft": "#adbaee", "muted": "#7889c2",
            "accent": "#5b8cff", "accent_hover": "#7ba7ff", "accent_text": "#ffffff",
            "accent2": "#a25cff", "toolbar": "#090f22", "menu": "#101838",
            "input": "#0a1128", "progress": "#5b8cff", "playhead": "#ff5d96",
            "marker": "#39477c", "success": "#3ddc97", "warning": "#ffc857",
            "danger": "#ff6b8a",
        },
    },
}

THEME_CHOICES = [(code, data["name"]) for code, data in THEMES.items()]
DEFAULT_THEME = "default"
_current = DEFAULT_THEME
_starfield_path = ""


def current_theme() -> str:
    return _current


def set_theme(code: str) -> None:
    global _current
    _current = code if code in THEMES else DEFAULT_THEME


def palette() -> dict:
    return THEMES[_current]["palette"]


def _starfield_image() -> str:
    global _starfield_path
    if _starfield_path and os.path.isfile(_starfield_path):
        return _starfield_path
    from PySide6.QtCore import QRandomGenerator, Qt
    from PySide6.QtGui import QColor, QImage, QPainter

    size = 512
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    rng = QRandomGenerator(20261121)
    for _ in range(160):
        x, y = int(rng.bounded(size)), int(rng.bounded(size))
        radius = 1 if rng.bounded(10) else 2
        painter.setBrush(QColor(205, 222, 255, 70 + rng.bounded(120)))
        painter.drawEllipse(x, y, radius, radius)
    painter.end()
    path = os.path.join(tempfile.gettempdir(), "cxp_starfield.png")
    image.save(path)
    _starfield_path = path
    return path


# 现代互联网风格样式模板；占位符由 build_stylesheet 替换
_CSS = """
QWidget {{
    background: @bg@; color: @text@;
    font-family: 'Microsoft YaHei', 'PingFang SC', 'Segoe UI', sans-serif;
    font-size: @fs@px;
}}
QWidget#root {{ background: @bg@; }}
QWidget#titleBar {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 @toolbar@,stop:0.55 @panel@,stop:1 @toolbar@);
    border-bottom: 1px solid @border@;
}}
QLabel#appLogo {{ background: transparent; border: none; }}
QLabel#titleText {{ color: @text_strong@; font-size: @fs2@px; font-weight: 600; }}
QLabel#versionText {{ color: @muted@; font-size: @fs0@px; }}
QLabel#mediaName {{
    color: @text_soft@; font-size: @fs@px;
    background: transparent; border: none; padding: 0px @pad@px;
}}
QLabel#statusToast {{
    color: @text_strong@; font-size: @fs@px; background: @panel@;
    border: 1px solid @border@; border-radius: @r8@px;
    padding: @pad0@px @pad@px;
}}
QLabel#scaleBadge {{
    color: @text_soft@; background: @panel_alt@; font-size: @fs0@px;
    border: 1px solid @border@; border-radius: @r10@px;
    padding: @pad0@px @pad@px;
}}
QPushButton#speedBadge {{
    color: @accent@; background: @panel_alt@; font-size: @fs0@px; font-weight: 600;
    border: 1px solid @border@; border-radius: @r10@px;
    padding: @pad0@px @pad@px; min-height: 0px; max-height: @btnsm@px;
}}
QPushButton#speedBadge:hover {{ background: @border@; border-color: @accent@; }}
QPushButton#speedBadge:pressed {{ background: @accent@; color: @accent_text@; }}
QToolBar#mainTool {{
    background: @toolbar@; border: none; border-bottom: 1px solid @border@;
    padding: @pad@px @pad2@px; spacing: @gap@px;
}}
QMenuBar {{ background: transparent; color: @text_soft@; border: none; }}
QMenuBar::item {{ padding: @pad0@px @pad@px; border-radius: @r6@px; }}
QMenuBar::item:selected {{ background: @panel_alt@; color: @accent@; }}
QMenu {{
    background: @menu@; border: 1px solid @border@; border-radius: @r10@px;
    padding: @pad0@px; color: @text@;
}}
QMenu::item {{ padding: @pad0@px @pad2@px; border-radius: @r6@px; }}
QMenu::item:selected {{ background: @accent@; color: @accent_text@; }}
QMenu::separator {{ height: 1px; background: @border@; margin: @pad0@px @pad@px; }}
QPushButton {{
    background: @panel_alt@; color: @text@; border: 1px solid @border@;
    border-radius: @r8@px; padding: @pad0@px @pad@px; min-height: @btn@px;
}}
QPushButton:hover {{ background: @border@; border-color: @accent@; color: @text_strong@; }}
QPushButton:pressed {{ background: @accent@; color: @accent_text@; }}
QPushButton:disabled {{ color: @muted@; background: @panel@; border-color: @border@; }}
QPushButton#primaryButton {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 @accent@,stop:1 @accent2@);
    color: @accent_text@; border: 1px solid @accent@; font-weight: 600;
    border-radius: @r8@px; padding: @pad0@px @pad2@px;
}}
QPushButton#primaryButton:hover {{ background: @accent_hover@; border-color: @accent_hover@; }}
QPushButton[compact="true"], QPushButton#primaryButton[compact="true"] {{
    min-height: @btnsm@px; max-height: @btnsm@px; padding: 0px @pad@px;
}}
QDialogButtonBox QPushButton {{
    min-height: @btnsm@px; max-height: @btnsm@px; padding: 0px @pad@px;
    min-width: @dlgbtnw@px; max-width: @dlgbtnw@px;
}}
QPushButton#iconButton {{
    background: transparent; border: none; border-radius: @r8@px; padding: 0px;
    min-width: @btnsm@px; max-width: @btnsm@px; min-height: @btnsm@px; max-height: @btnsm@px;
}}
QPushButton#iconButton:hover {{ background: @panel_alt@; }}
QPushButton#iconButton:checked, QPushButton#iconButtonActive {{
    background: @accent@; color: @accent_text@;
}}
QPushButton#winButton, QPushButton#winButtonClose {{
    background: transparent; border: none; border-radius: @r6@px; padding: 0px;
    min-width: @winbtn@px; max-width: @winbtn@px; min-height: @winh@px; max-height: @winh@px;
    color: @text_soft@;
}}
QPushButton#winButton:hover {{ background: @panel_alt@; color: @text_strong@; }}
QPushButton#winButtonClose:hover {{ background: @danger@; color: #ffffff; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit {{
    background: @input@; color: @text@; border: 1px solid @border@;
    border-radius: @r8@px; padding: 0px @pad@px;
    min-height: @inputh@px; max-height: @inputh@px;
    selection-background-color: @accent@;
}}
QTextEdit {{
    background: @input@; color: @text@; border: 1px solid @border@;
    border-radius: @r8@px; padding: @pad0@px @pad@px;
    selection-background-color: @accent@;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateTimeEdit:focus {{
    border: 1px solid @accent@;
}}
QComboBox::drop-down {{ border: none; width: @pad2@px; }}
QComboBox QAbstractItemView {{
    background: @menu@; color: @text@; border: 1px solid @border@;
    border-radius: @r8@px; padding: @pad0@px;
}}
QComboBox QAbstractItemView::item {{ min-height: @btn@px; padding: @pad0@px @pad@px; }}
QComboBox QAbstractItemView::item:selected {{ background: @accent@; color: @accent_text@; }}
QCheckBox, QRadioButton {{ color: @text@; spacing: @pad0@px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: @ind@px; height: @ind@px; border: 1px solid @border@;
    border-radius: @r4@px; background: @input@;
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: @accent@; border-color: @accent_hover@;
}}
QRadioButton::indicator {{ border-radius: @ind@px; }}
QSlider::groove:horizontal {{ background: @border@; height: @slider@px; border-radius: @slider@px; }}
QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 @accent@,stop:1 @accent2@); border-radius: @slider@px; }}
QSlider::add-page:horizontal {{ background: @border@; border-radius: @slider@px; }}
QSlider::handle:horizontal {{
    background: @text_strong@; width: @handle@px; height: @handle@px;
    margin: -@handlegap@px 0; border-radius: @handle@px; border: 1px solid @accent@;
}}
QSlider::handle:horizontal:hover {{ background: @accent@; }}
QSlider#volumeSlider {{ min-width: @volw@px; max-width: @volw@px; }}
QLabel#volumeValue {{ min-width: @voll@px; max-width: @voll@px; color: @muted@; font-size: @fs0@px; }}
QTreeWidget, QListWidget, QTableWidget {{
    background: @panel@; border: 1px solid @border@; border-radius: @r10@px;
    padding: @pad0@px;
}}
QTreeWidget::item, QListWidget::item {{ padding: @pad0@px @pad@px; border-radius: @r6@px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: @panel_alt@; }}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: @accent@; color: @accent_text@;
}}
QHeaderView::section {{
    background: @panel_alt@; color: @text_soft@; border: none;
    border-bottom: 1px solid @border@; padding: @pad0@px @pad@px; font-weight: 600;
}}
QProgressBar {{
    background: @input@; border: 1px solid @border@; border-radius: @r8@px;
    height: @progressh@px; text-align: center; color: @text@;
}}
QProgressBar::chunk {{ background: @accent@; border-radius: @r8@px; }}
QStatusBar {{ background: @toolbar@; color: @muted@; border-top: 1px solid @border@; }}
QToolTip {{
    background: @menu@; color: @text@; border: 1px solid @accent@;
    border-radius: @r6@px; padding: @pad0@px @pad@px;
}}
QScrollBar:vertical {{ background: transparent; width: @scroll@px; }}
QScrollBar::handle:vertical {{ background: @border@; border-radius: @scroll@px; min-height: @pad2@px; }}
QScrollBar::handle:vertical:hover {{ background: @accent@; }}
QScrollBar:horizontal {{ background: transparent; height: @scroll@px; }}
QScrollBar::handle:horizontal {{ background: @border@; border-radius: @scroll@px; min-width: @pad2@px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QFrame#separator {{ background: @border@; max-height: 1px; }}
QWidget#controlPanel {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 @panel@,stop:1 @toolbar@);
    border-top: 1px solid @border@;
}}
QWidget#videoArea {{ background: #000000; }}
QWidget#card {{
    background: @panel@; border: 1px solid @border@; border-radius: @r12@px;
}}
QLabel#hint {{ color: @muted@; font-size: @fs@px; padding: @pad2@px; }}
QLabel#small {{ color: @muted@; font-size: @fs0@px; }}
QLabel#sectionTitle {{ color: @text_strong@; font-size: @fs2@px; font-weight: 700; }}
QLabel#codec {{ color: @accent@; font-size: @fs0@px; font-weight: 600; }}
QLabel#time {{ color: @text_strong@; font-size: @fs2@px; font-family: 'Consolas', 'Segoe UI'; }}
QLabel#live {{ color: @danger@; font-size: @fs@px; font-weight: 700; }}
QDockWidget {{ background: @panel@; border: none; }}
QDockWidget::title {{
    background: @toolbar@; color: @text_soft@; padding: @pad0@px @pad@px;
    border-bottom: 1px solid @border@;
}}
QDockWidget::close-button {{ background: transparent; border: none; }}
QDockWidget::close-button:hover {{ background: @danger@; border-radius: @r4@px; }}
QTabWidget::pane {{ border: 1px solid @border@; border-radius: @r10@px; background: @panel@; }}
QTabBar::tab {{
    background: transparent; color: @muted@; padding: @pad0@px @pad2@px;
    border-bottom: 2px solid transparent; min-height: @btn@px;
}}
QTabBar::tab:selected {{ color: @accent@; border-bottom: 2px solid @accent@; font-weight: 600; }}
QTabBar::tab:hover {{ color: @text_strong@; }}
QGroupBox {{ border: 1px solid @border@; border-radius: @r10@px; margin-top: @pad@px; padding: @pad@px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: @pad@px; color: @accent@; font-weight: 600; }}
@star@
"""


def build_stylesheet(code: Optional[str] = None, metrics=None) -> str:
    """生成全局 QSS；metrics 提供 UI 缩放后的尺寸。"""
    key = code if code in THEMES else _current
    p = THEMES[key]["palette"]
    m = metrics
    scale = float(getattr(m, "scale", 1.0) or 1.0)

    def px(value: int) -> int:
        return max(1, int(round(value * scale)))

    star_css = ""
    if THEMES[key].get("starfield"):
        try:
            star_css = (
                f"QWidget#root {{ background-image: url('{_starfield_image().replace(chr(92), '/')}');"
                " background-repeat: repeat; }"
            )
        except Exception:
            star_css = ""

    replacements = {
        "bg": p["bg"], "panel": p["panel"], "panel_alt": p["panel_alt"],
        "border": p["border"], "text": p["text"], "text_strong": p["text_strong"],
        "text_soft": p["text_soft"], "muted": p["muted"],
        "accent": p["accent"], "accent_hover": p["accent_hover"],
        "accent_text": p["accent_text"], "accent2": p["accent2"],
        "toolbar": p["toolbar"], "menu": p["menu"], "input": p["input"],
        "progress": p["progress"], "playhead": p["playhead"],
        "marker": p["marker"], "success": p["success"], "warning": p["warning"],
        "danger": p["danger"],
        "fs": px(13), "fs0": px(11), "fs2": px(15), "logo": px(17),
        "pad0": px(4), "pad": px(9), "pad2": px(16),
        "gap": px(6), "btn": px(32), "btnsm": px(26), "inputh": px(26), "dlgbtnw": px(64),
        "winbtn": px(30), "winh": px(30),
        "r4": px(4), "r6": px(6), "r8": px(9), "r10": px(12), "r12": px(14),
        "ind": px(15), "slider": px(5), "handle": px(13), "handlegap": px(5),
        "volw": px(84), "voll": px(46), "progressh": px(16), "scroll": px(9),
        "star": star_css,
    }
    css = _CSS
    for name, value in replacements.items():
        css = css.replace("@" + name + "@", str(value))
    # 模板中的双花括号仅为避免编辑期歧义，输出时还原为合法 QSS
    css = css.replace("{{", "{").replace("}}", "}")
    return css


def apply_theme(app, code: str, metrics=None) -> None:
    set_theme(code)
    app.setStyleSheet(build_stylesheet(code, metrics))
