"""回归：控制栏 tooltip 语言切换、主题名翻译、视频分辨率窗口适配、按钮风格与 dock 关闭按钮。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton, QApplication, QComboBox, QMenu, QPushButton, QSizePolicy,
)

from app.core.i18n import init_i18n, tr  # noqa: E402
from app.core.logger import init_loggers  # noqa: E402
from app.core.theme import THEME_CHOICES, palette  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.record_dialog import RecordDialog  # noqa: E402
from app.ui.settings_dialog import SettingsDialog  # noqa: E402


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS" if condition else "FAIL") + " | " + name + ((" | " + detail) if detail else ""))
    if not condition:
        raise SystemExit(1)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    init_loggers()
    init_i18n("zh_CN")
    w = MainWindow()
    w.apply_appearance()
    app.processEvents()

    # 1. 控制栏 tooltip 在语言切换后随语言更新（源文案保存正确）
    zh_tips = [b.toolTip() for b in (
        w.control.mute_btn, w.control.rewind_btn, w.control.play_btn,
        w.control.stop_btn, w.control.forward_btn, w.control.list_btn,
    )]
    check("中文态控制栏 tooltip 为中文", all(t for t in zh_tips)
          and any("\u4e00" <= ch <= "\u9fff" for t in zh_tips for ch in t), str(zh_tips))

    w.settings.language = "en"
    w._on_settings_applied()
    app.processEvents()
    en_tips = [b.toolTip() for b in (
        w.control.mute_btn, w.control.rewind_btn, w.control.play_btn,
        w.control.stop_btn, w.control.forward_btn, w.control.list_btn,
    )]
    check("英文态控制栏 tooltip 为英文", "Mute" in en_tips and "Rewind" in en_tips
          and "Play / Pause" in en_tips, str(en_tips))

    w.settings.language = "zh_TW"
    w._on_settings_applied()
    app.processEvents()
    tw_tips = [b.toolTip() for b in (
        w.control.mute_btn, w.control.rewind_btn, w.control.play_btn,
        w.control.stop_btn, w.control.forward_btn, w.control.list_btn,
    )]
    check("繁体态控制栏 tooltip 为繁体", "靜音" in tw_tips and "暫停" in " ".join(tw_tips),
          str(tw_tips))

    w.settings.language = "zh_CN"
    w._on_settings_applied()
    app.processEvents()
    back_tips = [b.toolTip() for b in (
        w.control.mute_btn, w.control.rewind_btn, w.control.play_btn,
        w.control.stop_btn, w.control.forward_btn, w.control.list_btn,
    )]
    check("回中文控制栏 tooltip 恢复", back_tips == zh_tips, f"{zh_tips} -> {back_tips}")

    # 2. 主题名随语言切换
    settings = SettingsDialog(w.settings, w.metrics, w)
    theme_combo: QComboBox = settings.theme
    zh_names = [theme_combo.itemText(i) for i in range(theme_combo.count())]
    check("中文态主题名为中文", "星夜蓝" in zh_names, str(zh_names))
    w.settings.language = "en"
    w._on_settings_applied()
    settings.retranslate()
    app.processEvents()
    en_names = [theme_combo.itemText(i) for i in range(theme_combo.count())]
    check("英文态主题名为英文", "Starry Night" in en_names and "Neon Purple" in en_names,
          str(en_names))
    w.settings.language = "zh_TW"
    w._on_settings_applied()
    settings.retranslate()
    app.processEvents()
    tw_names = [theme_combo.itemText(i) for i in range(theme_combo.count())]
    check("繁体态主题名为繁体", "星夜藍" in tw_names and "極光綠" in tw_names, str(tw_names))
    w.settings.language = "zh_CN"
    w._on_settings_applied()
    settings.retranslate()
    app.processEvents()
    back_names = [theme_combo.itemText(i) for i in range(theme_combo.count())]
    check("回中文主题名恢复", back_names == [name for _, name in THEME_CHOICES], str(back_names))

    # 3. 按视频真实分辨率调整窗口：小视频按分辨率设定，超大视频最大化
    screen = QApplication.primaryScreen()
    avail = screen.availableGeometry()
    # 小分辨率：窗口应接近 视频分辨率 + chrome，且不最大化
    # 临时降低最小尺寸，以便验证适配算法本身（正常运行时最小尺寸为 UI 保护下限）
    w.setMinimumSize(200, 150)
    w.showNormal()
    app.processEvents()
    w.fit_window_to_video(640, 360)
    app.processEvents()
    check("小视频不最大化", not w.isMaximized())
    check("小视频窗口按真实分辨率", abs(w.player_widget.width() - 640) <= 2
          and abs(w.player_widget.height() - 360) <= 2,
          f"video widget={w.player_widget.width()}x{w.player_widget.height()}")
    # 超大分辨率：应最大化
    w.fit_window_to_video(avail.width() * 2, avail.height() * 2)
    app.processEvents()
    check("超大视频最大化", w.isMaximized())
    w.showNormal()
    app.processEvents()

    # 4. 按钮风格统一：compact 属性一致（高度由 QSS 控制，不固定宽度）
    record = RecordDialog(w.settings, [], w.metrics, parent=w)
    browse_btns = [b for b in record.findChildren(QPushButton) if b.text() == tr("浏览")]
    check("录制弹窗浏览按钮存在", len(browse_btns) == 1, str(len(browse_btns)))
    check("录制弹窗浏览按钮 compact 属性", browse_btns[0].property("compact") is True)
    # 设置页浏览按钮同样为 compact，二者风格一致
    pick_btns = [b for b in settings.findChildren(QPushButton) if b.text() == tr("浏览")]
    check("设置页浏览按钮 compact 属性", pick_btns and pick_btns[0].property("compact") is True)
    for panel in (w.playlist_panel, w.iptv_panel):
        text_btns = [b for b in panel.findChildren(QPushButton)
                     if b.text() and not b.property("compact")]
        # 仅允许 iconButton（无文字）；有文字按钮应全部 compact
        check(f"{type(panel).__name__} 文字按钮全部 compact", not text_btns,
              str([b.text() for b in text_btns]))

    # 5. dock 关闭按钮使用纯白加粗自绘图标（深色标题栏上清晰可见）
    close_btn = w.dock.findChild(QAbstractButton, "qt_dockwidget_closebutton")
    check("dock 关闭按钮存在", close_btn is not None)
    if close_btn is not None:
        check("dock 关闭按钮设置了图标", not close_btn.icon().isNull())
        pm = close_btn.icon().pixmap(20, 20).toImage()
        brightest = max(
            (max(pm.pixelColor(x, y).red(), pm.pixelColor(x, y).green(),
                 pm.pixelColor(x, y).blue())
             for y in range(pm.height()) for x in range(pm.width())
             if pm.pixelColor(x, y).alpha() > 200),
            default=0,
        )
        check("dock 关闭按钮图标为纯白", brightest == 255, str(brightest))
        check("dock 关闭按钮图标放大到 18px", close_btn.iconSize().width() >= 18,
              str(close_btn.iconSize()))
        check("dock 关闭按钮 tooltip 为关闭", close_btn.toolTip() == tr("关闭"),
              close_btn.toolTip())

    # 6. 所有菜单 / 按钮名称不带省略号（简体 / 英文 / 繁体）
    for language in ("zh_CN", "en", "zh_TW"):
        w.settings.language = language
        w._on_settings_applied()
        app.processEvents()
        bad = []
        for menu in w._menubar.findChildren(QMenu):
            if "…" in menu.title() or "..." in menu.title():
                bad.append(menu.title())
            for action in menu.actions():
                text = action.text()
                if "…" in text or "..." in text:
                    bad.append(text)
        for btn in w.findChildren(QPushButton):
            text = btn.text()
            if "…" in text or "..." in text:
                bad.append(text)
        check(f"{language} 菜单与按钮无省略号", not bad, str(bad))
    w.settings.language = "zh_CN"
    w._on_settings_applied()
    app.processEvents()

    # 7. 语言切换不改播放列表宽度
    w._set_playlist_visible(True)
    app.processEvents()
    dock_width = w.dock.width()
    list_width = w.playlist_panel.list.width()
    hint_width = w.dock.sizeHint().width()
    for language in ("en", "zh_TW", "zh_CN", "en"):
        w.settings.language = language
        w._on_settings_applied()
        app.processEvents()
        check(f"{language} 播放列表抽屉宽度不变", w.dock.width() == dock_width,
              f"{dock_width} -> {w.dock.width()}")
        check(f"{language} 播放列表控件宽度不变", w.playlist_panel.list.width() == list_width,
              f"{list_width} -> {w.playlist_panel.list.width()}")
        check(f"{language} 抽屉尺寸提示与语言无关", w.dock.sizeHint().width() == hint_width,
              f"{hint_width} -> {w.dock.sizeHint().width()}")

    # 8. 2560x1440 / 125% 缩放下打开 1920x1080 视频不应最大化
    class _Fake1440pScreen:
        def geometry(self):
            return QRect(0, 0, 2048, 1152)

        def availableGeometry(self):
            return QRect(0, 0, 2048, 1112)

        def devicePixelRatio(self):
            return 1.25

    w.setMinimumSize(200, 150)
    w.showNormal()
    w.resize(1180, 720)
    app.processEvents()
    real_screen = w.screen
    w.screen = lambda: _Fake1440pScreen()
    try:
        w.fit_window_to_video(1920, 1080)
        app.processEvents()
        check("1440p@125% 下 1080p 视频不最大化", not w.isMaximized())
        check("1440p@125% 视频区按物理像素 1:1",
              abs(w.player_widget.width() - 1536) <= 2
              and abs(w.player_widget.height() - 864) <= 2,
              f"video widget={w.player_widget.width()}x{w.player_widget.height()}")
    finally:
        w.screen = real_screen
        w.setMinimumSize(w.metrics.s(880), w.metrics.s(560))

    print("\nALL UI POLISH CHECKS PASSED")


if __name__ == "__main__":
    main()
