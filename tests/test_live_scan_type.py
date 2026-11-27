"""直播流扫描方式回归：ffprobe field_order、异步探测竞态、真实 HTTP 流端到端。"""

import functools
import http.server
import os
import shutil
import socketserver
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.i18n import init_i18n  # noqa: E402
from app.core.media_info import (  # noqa: E402
    MediaInfoCache, parse_probe, scan_type_from_field_order,
)
from app.core.models import Channel  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        raise AssertionError(name + (" - " + detail if detail else ""))


def test_field_order_mapping() -> None:
    check("ffprobe progressive 映射",
          scan_type_from_field_order("progressive") == "Progressive")
    check("ffprobe tt 映射上场优先",
          scan_type_from_field_order("tt") == "Interlaced (top field first)")
    check("ffprobe bb 映射下场优先",
          scan_type_from_field_order("bb") == "Interlaced (bottom field first)")


def test_parse_probe_scan_type() -> None:
    data = {
        "format": {"duration": "2", "format_name": "mpegts"},
        "streams": [
            {"codec_type": "video", "width": 320, "height": 240,
             "field_order": "tt", "r_frame_rate": "25/1"},
            {"codec_type": "audio", "codec_name": "mp2", "channels": 2,
             "sample_rate": "48000"},
        ],
    }
    info = parse_probe(data, "http://live/test.ts", live=True)
    check("ffprobe 回退路径解析扫描方式",
          info.scan_type == "Interlaced (top field first)", str(info.scan_type))


class _FakeWorker:
    def __init__(self) -> None:
        self.cancelled = False
        self.waited: list[int] = []

    def isRunning(self) -> bool:
        return True

    def cancel(self) -> None:
        self.cancelled = True

    def wait(self, ms: int) -> None:
        self.waited.append(ms)


class _FakePlayer:
    def property(self, name: str, default=None):
        if name == "track-list":
            return [{"id": 1, "type": "video", "codec": "h264",
                     "demux-w": 320, "demux-h": 240}]
        if name == "duration":
            return 2.0
        if name == "video-frame-info":
            return {"interlaced": False}
        return default


def test_cancel_stale_worker() -> None:
    cache = MediaInfoCache()
    stale = _FakeWorker()
    cache._worker = stale
    cache.probe_with_player("http://live/test.ts", _FakePlayer(), live=True)
    check("新探测取消旧 ffprobe 探测", stale.cancelled and stale.waited == [500])
    check("取消后清空旧 worker 引用", cache._worker is None)


def test_live_stream_ui(app) -> None:
    if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
        print("SKIP: offscreen 无界面环境无法嵌入 libmpv 原生窗口，跳过真实直播流测试")
        return
    if not shutil.which("ffmpeg"):
        print("SKIP: 未找到 ffmpeg，跳过真实直播流测试")
        return
    video = os.path.abspath(os.path.join(os.path.dirname(__file__), "_scan_live.ts"))
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=size=320x240:rate=25", "-t", "12",
         "-pix_fmt", "yuv420p", video],
        check=True,
    )
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=os.path.dirname(video),
    )
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/" + os.path.basename(video)

    init_i18n("zh_CN")
    window = MainWindow()
    window.apply_appearance()
    window.show()
    app.processEvents()
    window._play_channel(Channel(name="测试直播", url=url))

    def verify() -> None:
        try:
            scan = window._osd_details.get("scan", "")
            check("直播 Tab OSD 显示扫描方式",
                  scan not in ("", "--"), str(scan))
            osd_lines = [text for text, _ in window.osd._lines() if "扫描方式" in text]
            check("Tab OSD 文本包含扫描方式", bool(osd_lines), str(osd_lines))
            window._show_properties()
            app.processEvents()
            prop_text = window._properties_dialog.text.toPlainText()
            check("属性窗口包含 Scan type",
                  any(line.lstrip().startswith("Scan type")
                      for line in prop_text.splitlines()))
        finally:
            app.quit()

    QTimer.singleShot(3200, verify)
    app.exec()
    window.player.shutdown()
    httpd.shutdown()
    if os.path.exists(video):
        os.remove(video)


def main() -> None:
    test_field_order_mapping()
    test_parse_probe_scan_type()
    test_cancel_stale_worker()
    app = QApplication.instance() or QApplication(sys.argv)
    test_live_stream_ui(app)
    print("\nALL LIVE SCAN TYPE CHECKS PASSED")


if __name__ == "__main__":
    main()
