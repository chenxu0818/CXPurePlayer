"""验证「记住播放位置」：持久化、续播参数、结束清除。"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import settings as settings_mod  # noqa: E402
from app.core import ui_scale  # noqa: E402
from app.core.i18n import init_i18n  # noqa: E402
from app.core.logger import init_loggers  # noqa: E402
from app.core.mpv_player import MpvPlayer  # noqa: E402
from app.core.settings import AppSettings  # noqa: E402
from app.core.theme import apply_theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS" if condition else "FAIL") + " | " + name + ((" | " + detail) if detail else ""))
    if not condition:
        raise SystemExit(1)


def main() -> None:
    init_loggers()
    tmp = tempfile.mkdtemp(prefix="cx_remember_")
    original_app_root = settings_mod.app_root
    settings_mod.app_root = lambda: tmp
    try:
        # 1. 配置层：按文件持久化、隔离、路径规范化、清除、不足 1 秒不记录
        settings = AppSettings()
        settings.remember_position = True
        check("设置项可持久化", AppSettings().remember_position is True)
        p1 = os.path.join(tmp, "video A.mp4")
        p2 = os.path.join(tmp, "video B.mp4")
        Path(p1).write_bytes(b"")
        Path(p2).write_bytes(b"")
        settings.set_playback_position(p1, 42.37)
        check("位置写入并读回", abs(settings.get_playback_position(p1) - 42.37) < 0.01,
              str(settings.get_playback_position(p1)))
        check("不同文件互相隔离", settings.get_playback_position(p2) == 0.0)
        check("路径写法不同仍命中", settings.get_playback_position(p1.replace(os.sep, "/")) > 0)
        settings.set_playback_position(p2, 0.5)
        check("不足 1 秒不记录", settings.get_playback_position(p2) == 0.0)
        settings.clear_playback_position(p1)
        check("清除记录", settings.get_playback_position(p1) == 0.0)

        # 2. 内核层：start_pos>0 走 loadfile start 参数；否则普通 play
        player = MpvPlayer()

        class FakeMpv:
            def __init__(self) -> None:
                self.commands: list[tuple] = []
                self.played: list[str] = []

            def command(self, *args) -> None:
                self.commands.append(args)

            def play(self, path: str) -> None:
                self.played.append(path)

        fake = FakeMpv()
        player._available = True
        player._mpv = fake
        player.open(p1, start_pos=12.5)
        check("续播设置 mpv start 属性", abs(fake.start - 12.5) < 1e-6, str(fake.start))
        check("续播仍走正常加载", p1 in fake.played, str(fake.played))
        player.open(p2)
        check("打开新文件时重置 start", fake.start == 0.0, str(fake.start))
        check("无位置记录时正常播放", p2 in fake.played, str(fake.played))

        # 3. 主窗口层：切换前保存、打开时恢复、播完清除
        app = QApplication.instance() or QApplication(sys.argv)
        init_i18n("zh_CN")
        cfg = AppSettings()
        cfg.remember_position = True
        metrics = ui_scale.Metrics(cfg)
        apply_theme(app, cfg.theme, metrics)
        metrics.apply_font(app)
        window = MainWindow()
        window.show()
        app.processEvents()

        window._current_path = p1
        window._live = False
        window._position_observed = True
        window.player._state.time_pos = 33.0
        window.player._state.duration = 100.0
        window._save_playback_position()
        check("主窗口保存当前位置", abs(window.settings.get_playback_position(p1) - 33.0) < 0.01,
              str(window.settings.get_playback_position(p1)))

        seen: dict = {}
        window.player.open = lambda path, **kw: seen.update(path=path, **kw)
        window.info_cache.probe_with_player = lambda *a, **k: None
        window._play_path(p1)
        check("重新打开时恢复位置", abs(seen.get("start_pos", 0.0) - 33.0) < 0.01, str(seen))

        window._clear_playback_position()
        check("播放结束清除记录", window.settings.get_playback_position(p1) == 0.0)

        # 4. 过期策略：超过 30 天未播放的记录在读取与启动时清除
        old = os.path.join(tmp, "old.mp4")
        fresh = os.path.join(tmp, "fresh.mp4")
        Path(old).write_bytes(b"")
        Path(fresh).write_bytes(b"")
        settings.set_playback_position(old, 15.0)
        settings.set_playback_position(fresh, 25.0)
        old_key = settings._position_key(old)
        settings._q.beginGroup(settings._POSITION_GROUP)
        settings._q.setValue(old_key, f"15.00|{int(time.time()) - 31 * 86400}")
        settings._q.endGroup()
        settings._q.sync()
        check("过期记录读取即失效", settings.get_playback_position(old) == 0.0)
        settings._q.beginGroup(settings._POSITION_GROUP)
        remained = list(settings._q.allKeys())
        settings._q.endGroup()
        check("过期读取时同步删除", old_key not in remained, str(remained))

        # 启动时批量清理：一条过期 + 一条新鲜
        settings.set_playback_position(old, 15.0)
        settings._q.beginGroup(settings._POSITION_GROUP)
        settings._q.setValue(old_key, f"15.00|{int(time.time()) - 31 * 86400}")
        settings._q.endGroup()
        settings._q.sync()
        check("启动清理条数", settings.purge_expired_positions() == 1)
        check("未过期记录保留", abs(settings.get_playback_position(fresh) - 25.0) < 0.01,
              str(settings.get_playback_position(fresh)))

        # 旧版纯秒数格式兼容，且不被误判过期
        settings._q.beginGroup(settings._POSITION_GROUP)
        settings._q.setValue(settings._position_key(fresh), "8.5")
        settings._q.endGroup()
        settings._q.sync()
        check("旧格式记录兼容", abs(settings.get_playback_position(fresh) - 8.5) < 0.01,
              str(settings.get_playback_position(fresh)))

        window.close()
        print("\nALL REMEMBER-POSITION CHECKS PASSED")
    finally:
        settings_mod.app_root = original_app_root


if __name__ == "__main__":
    main()
