"""渲染关键对话框预览，用于检查布局与多语言。"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from app.core import ui_scale
from app.core.i18n import init_i18n
from app.core.settings import AppSettings
from app.core.theme import apply_theme
from app.ui.main_window import MainWindow
from app.ui.properties_dialog import PropertiesDialog
from app.ui.settings_dialog import SettingsDialog

app = QApplication(sys.argv)
ui_scale.configure_high_dpi()
settings = AppSettings()
init_i18n(settings.language)
metrics = ui_scale.Metrics(settings)
apply_theme(app, settings.theme, metrics)
metrics.apply_font(app)
window = MainWindow()

props = PropertiesDialog(metrics, lambda: window.player.snapshot_state(),
                         lambda: None, window)
props.resize(760, 560)
props.tabs.setCurrentIndex(1)
props.show()
app.processEvents()
props.grab().save(r"D:/app/CXPurePlayer/docs/ui-properties.png")

settings_dialog = SettingsDialog(settings, metrics, window)
settings_dialog.show()
app.processEvents()
settings_dialog.grab().save(r"D:/app/CXPurePlayer/docs/ui-settings.png")

window.recorder.shutdown()
window.player.shutdown()
print("saved docs/ui-properties.png, docs/ui-settings.png")
