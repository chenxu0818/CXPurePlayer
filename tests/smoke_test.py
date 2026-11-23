"""无界面冒烟测试：播放内核、ffprobe、M3U、录制命名、主题与缩放。"""

from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.i18n import init_i18n  # noqa: E402
from app.core.logger import init_loggers  # noqa: E402
from app.core.m3u_parser import parse_m3u  # noqa: E402
from app.core.media_info import build_info_from_mpv, codec_label  # noqa: E402
from app.core.mpv_player import MpvPlayer  # noqa: E402
from app.core.recorder import build_output_name  # noqa: E402
from app.core.settings import AppSettings  # noqa: E402
from app.core.theme import build_stylesheet  # noqa: E402
from app.core.ui_scale import Metrics, configure_high_dpi  # noqa: E402
from app.core.models import RecordTask  # noqa: E402

SAMPLE = r"C:\Users\57594\AppData\Local\Temp\cxvc_perf_test.mp4"


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS" if condition else "FAIL") + " | " + name + ((" | " + detail) if detail else ""))
    if not condition:
        raise SystemExit(1)


def main() -> None:
    configure_high_dpi()
    app = QApplication.instance() or QApplication(sys.argv)
    init_loggers()
    init_i18n("zh_CN")
    settings = AppSettings()
    metrics = Metrics(settings)

    check("主题样式表生成", "QPushButton" in build_stylesheet("default", metrics))
    check("缩放范围", 0.8 <= metrics.scale <= 2.0, f"scale={metrics.scale}")
    check("尺寸派生", metrics.s(100) >= 80, f"s(100)={metrics.s(100)}")

    # ffprobe
    if os.path.isfile(SAMPLE):
        # mpv 播放（无界面输出）
        player = MpvPlayer()
        errors = []
        player.errorOccurred.connect(errors.append)
        ok = player.init(0, vo="null")
        check("libmpv 初始化", ok, "; ".join(errors)[:200])
        if ok:
            player.open(SAMPLE)
            deadline = time.time() + 6
            while time.time() < deadline and float(player.property("time-pos", 0) or 0) <= 0.1:
                app.processEvents()
                time.sleep(0.1)
            pos = float(player.property("time-pos", 0) or 0)
            duration = float(player.property("duration", 0) or 0)
            check("播放推进", pos > 0.1, f"pos={pos:.2f}, duration={duration:.2f}")
            info = build_info_from_mpv(player, SAMPLE)
            check("媒体信息(libmpv)", len(info.streams) > 0,
                  f"streams={len(info.streams)}")
            if info.streams:
                print("      codec:", codec_label(info.streams[0].codec_name))
            player.set_speed(1.5)
            check("倍速设置", abs(float(player.property("speed", 1)) - 1.5) < 0.01)
            player.seek(1.0, absolute=True)
            check("定位seek", True)
            with tempfile.TemporaryDirectory() as tmp:
                shot = os.path.join(tmp, "shot.png")
                check("截图命令", player.screenshot(shot, True))
            player.shutdown()
    else:
        print("SKIP | 样例视频不存在:", SAMPLE)

    # M3U
    with tempfile.TemporaryDirectory() as tmp:
        m3u = os.path.join(tmp, "list.m3u8")
        with open(m3u, "w", encoding="utf-8") as fh:
            fh.write("#EXTM3U\n#EXTINF:-1 tvg-name=\"测试台\" group-title=\"央视\",测试台\n相对/stream.ts\n")
        result = parse_m3u(m3u)
        check("M3U 解析", len(result.channels) == 1, str(result.channels))
        check("相对URL补全", os.path.isabs(result.channels[0].url), result.channels[0].url)
        check("分组解析", result.channels[0].group == "央视", result.channels[0].group)

    # 录制命名
    task = RecordTask(
        id="x", channel="央视新闻", content="晚间新闻",
        start_time="2026-11-21 19:00", end_time="2026-11-21 19:30",
    )
    name = build_output_name(task, 1763710800, "ts")
    check("录制命名", name == "央视新闻-晚间新闻-202611211900-202611211930-1763710800.ts", name)

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
