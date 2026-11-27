"""CXPurePlayer 入口：高 DPI 配置、全局外观、主窗口。"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

from app.core import ui_scale
from app.core.i18n import init_i18n
from app.core.logger import log_info
from app.core.qt_translator import install_qt_translator
from app.core.settings import AppSettings
from app.ui.widget_utils import app_icon, set_window_icon
from app.version import APP_DISPLAY, APP_VERSION


def main() -> int:
    ui_scale.configure_high_dpi()
    # macOS 默认把 QMenuBar 放到屏幕顶部；必须在 QApplication 创建前声明，
    # 否则无边框窗口内的菜单栏会被 Qt 当作原生菜单隐藏。
    QCoreApplication.setAttribute(
        Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True
    )
    app = QApplication(sys.argv)
    app.setApplicationName("CXPurePlayer")
    app.setApplicationVersion(APP_VERSION)

    settings = AppSettings()
    init_i18n(settings.language)
    install_qt_translator(app, settings.language)
    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    metrics = ui_scale.Metrics(settings)
    from app.core.theme import apply_theme
    apply_theme(app, settings.theme, metrics)
    metrics.apply_font(app)

    from app.ui.main_window import MainWindow

    window = MainWindow()
    set_window_icon(window)
    window.show()
    # 文件关联 / 右键「打开方式」：把命令行传入的文件路径交给主窗口播放。
    # 记录原始 argv 便于排查文件关联问题；过滤掉选项与非文件路径。
    log_info(f"[启动] 原始命令行 argv[1:] = {sys.argv[1:]!r}")
    launch_files = [
        arg for arg in sys.argv[1:]
        if not arg.startswith("-") and os.path.isfile(arg)
    ]
    if launch_files:
        # 内核在事件循环首轮才初始化，走入队逻辑等 readyChanged 后再播放。
        window.queue_launch_files(launch_files)
    else:
        log_info("[启动] 命令行未发现有效媒体文件（普通启动）")
    log_info(f"{APP_DISPLAY} {APP_VERSION} 启动")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
