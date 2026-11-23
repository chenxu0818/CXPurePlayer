"""验证语言切换时一/二/三级菜单与弹窗文案完整同步（含往返切换）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QMenu  # noqa: E402

from app.core.i18n import init_i18n, source_text, tr  # noqa: E402
from app.core.logger import init_loggers  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.properties_dialog import PropertiesDialog  # noqa: E402
from app.ui.settings_dialog import SettingsDialog  # noqa: E402


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS" if condition else "FAIL") + " | " + name + ((" | " + detail) if detail else ""))
    if not condition:
        raise SystemExit(1)


def has_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def all_menu_texts(window: MainWindow) -> list[str]:
    texts: list[str] = []
    for menu in window._menubar.findChildren(QMenu):
        if menu.title():
            texts.append(menu.title())
        for action in menu.actions():
            if action.isSeparator():
                continue
            texts.append(action.text())  # 含子菜单入口 action（其 text 即子菜单标题）
    return texts


def dialog_texts(dialog) -> list[str]:
    out = [dialog.windowTitle()]
    out.extend(w.text() for w in dialog.findChildren(QLabel) if w.text())
    return out


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    init_loggers()
    init_i18n("zh_CN")
    w = MainWindow()
    w.apply_appearance()
    app.processEvents()

    # source_text 必须能从任意语言译文反查源文案（en → zh 关键）
    check("source_text 反查英文译文", source_text("Settings") == "设置",
          source_text("Settings"))
    check("source_text 反查繁体译文", source_text("檔案(&F)") == "文件(&F)",
          source_text("檔案(&F)"))

    # 中文态创建弹窗，验证往返切换
    settings = SettingsDialog(w.settings, w.metrics, w)
    props = PropertiesDialog(w.metrics, lambda: None, lambda: None, w)

    zh_menu = all_menu_texts(w)
    zh_settings = dialog_texts(settings)
    check("中文菜单含中文", any(has_chinese(t) for t in zh_menu))

    # 切英文
    w.settings.language = "en"
    w._on_settings_applied()
    app.processEvents()
    en_menu = all_menu_texts(w)
    static_zh = [t for t in en_menu if has_chinese(t)]
    # 数字倍速档位、IPTV 等无中文属正常；这里要求所有静态文案均已英文化
    check("英文态菜单无中文残留", not static_zh, str(static_zh))
    check("英文态含 Open File", "Open File" in en_menu)
    check("英文态含二级 Disable Audio", "Disable Audio" in en_menu)
    check("英文态含三级 Add External Subtitle", "Add External Subtitle" in en_menu)
    check("英文态设置弹窗标题", settings.windowTitle() == "Settings", settings.windowTitle())
    check("英文态设置弹窗标签", "Language" in dialog_texts(settings))
    check("英文态属性弹窗标题", props.windowTitle() == "Properties", props.windowTitle())

    # 切回中文
    w.settings.language = "zh_CN"
    w._on_settings_applied()
    app.processEvents()
    back_menu = all_menu_texts(w)
    back_settings = dialog_texts(settings)
    check("回中文菜单无英文文案残留",
          not any(t in back_menu for t in ("Open File", "Disable Audio", "Play / Pause")),
          str([t for t in back_menu if t in ("Open File", "Disable Audio", "Play / Pause")]))
    check("回中文含打开文件", "打开文件" in back_menu)
    check("回中文含二级禁用音频", "禁用音频" in back_menu)
    check("回中文设置弹窗标签恢复", back_settings == zh_settings,
          f"{zh_settings[:6]} -> {back_settings[:6]}")
    check("回中文属性弹窗标题", props.windowTitle() == "属性信息", props.windowTitle())

    print("\nALL LANGUAGE SWITCH CHECKS PASSED")


if __name__ == "__main__":
    main()
