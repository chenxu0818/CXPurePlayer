"""渲染主窗口预览图（用于检查科技现代风格 UI）。"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import ui_scale  # noqa: E402
from app.core.i18n import init_i18n  # noqa: E402
from app.core.settings import AppSettings  # noqa: E402
from app.core.theme import apply_theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

SAMPLE = r"C:\Users\57594\AppData\Local\Temp\cxvc_perf_test.mp4"
OUTPUT = r"D:\app\CXPurePlayer\docs\ui-preview.png"


def main() -> None:
    ui_scale.configure_high_dpi()
    app = QApplication(sys.argv)
    settings = AppSettings()
    init_i18n(settings.language)
    metrics = ui_scale.Metrics(settings)
    apply_theme(app, settings.theme, metrics)
    metrics.apply_font(app)
    window = MainWindow()
    window.show()
    window.resize(metrics.s(1280), metrics.s(760))
    if os.path.isfile(SAMPLE):
        QTimer.singleShot(300, lambda: window._open_paths([SAMPLE]))
    QTimer.singleShot(1400, lambda: window.osd.toggle())
    QTimer.singleShot(2200, lambda: (
        window.grab().save(OUTPUT),
        app.quit(),
    ))
    app.exec()
    print("saved", OUTPUT)


if __name__ == "__main__":
    main()
