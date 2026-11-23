"""无界面验证：语言切换后各层级页面文案是否同步。"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QFileDialog

from app.core import ui_scale
from app.core.i18n import init_i18n
from app.core.settings import AppSettings
from app.core.theme import apply_theme
from app.ui.main_window import MainWindow
from app.ui.record_dialog import RecordDialog
from app.ui.screenshot_dialogs import ContinuousDialog, ThumbnailDialog
from app.ui.settings_dialog import SettingsDialog

app = QApplication(sys.argv)
ui_scale.configure_high_dpi()
settings = AppSettings()
i18n = init_i18n(settings.language)
metrics = ui_scale.Metrics(settings)
apply_theme(app, settings.theme, metrics)
metrics.apply_font(app)

window = MainWindow()
dialogs = [
    SettingsDialog(settings, metrics, window),
    RecordDialog(settings, [], metrics, parent=window),
    ThumbnailDialog(metrics, window.player, window),
    ContinuousDialog(metrics, window.player, window),
]

def snapshot() -> dict:
    from PySide6.QtWidgets import QDialogButtonBox

    dialog = QFileDialog(window)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    box = dialog.findChild(QDialogButtonBox)
    labels = {}
    if box:
        open_button = box.button(QDialogButtonBox.StandardButton.Open)
        cancel_button = box.button(QDialogButtonBox.StandardButton.Cancel)
        labels["file_open"] = open_button.text() if open_button else ""
        labels["file_cancel"] = cancel_button.text() if cancel_button else ""
    dialog.deleteLater()
    return {
        "menu": window._menubar.actions()[0].text(),
        "dock": window.dock.windowTitle(),
        "scale_tip": window.title_bar.scale_label.toolTip(),
        "settings_title": dialogs[0].windowTitle(),
        "settings_ok": dialogs[0].ok_btn.text(),
        "settings_language": dialogs[0].language.itemText(2),
        "record_title": dialogs[1].windowTitle(),
        "record_ok": dialogs[1].ok_btn.text(),
        "thumb_title": dialogs[2].windowTitle(),
        "thumb_run": dialogs[2].run_btn.text(),
        "continuous_title": dialogs[3].windowTitle(),
        **labels,
    }


for language in ("zh_CN", "en", "zh_TW", "zh_CN"):
    settings.language = language
    i18n.set_language(language)
    window.apply_appearance()
    for dialog in dialogs:
        if hasattr(dialog, "retranslate"):
            dialog.retranslate()
    print(language, snapshot())

window.recorder.shutdown()
window.player.shutdown()
