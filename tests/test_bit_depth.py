"""属性信息 Bit depth 回归：绝不能把 mpv 的 average-bpp 当成位深。

历史 bug：8bit 的 yuv420p 视频（mpv video-params.average-bpp=12，即每像素
平均位数 8+2+2=12）被错误显示为 "12 bits"。位深只能从像素格式解析。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.info_format import _bit_depth, format_media_info  # noqa: E402
from app.core.models import MediaInfo, StreamInfo  # noqa: E402


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        raise AssertionError(name + (" - " + detail if detail else ""))


def test_bit_depth_parsing() -> None:
    cases = {
        "yuv420p": "8 bits",
        "yuvj420p": "8 bits",
        "nv12": "8 bits",
        "yuyv422": "8 bits",
        "yuv410p": "8 bits",
        "yuv420p10le": "10 bits",
        "yuv422p10le": "10 bits",
        "yuv444p10le": "10 bits",
        "yuv420p12le": "12 bits",
        "yuv420p14le": "14 bits",
        "yuv420p16le": "16 bits",
        "gbrp12le": "12 bits",
        "p010le": "10 bits",
        "p016le": "16 bits",
        "gray": "8 bits",
        "rgb24": "8 bits",
        "rgb48le": "16 bits",
        "": "",
        "unknown": "",
    }
    for pix, expected in cases.items():
        check(f"位深解析 {pix or '(空)'}", _bit_depth(pix) == expected,
              f"got={_bit_depth(pix)!r} exp={expected!r}")


def _video_text(pix_fmt: str, vparams: dict) -> str:
    info = MediaInfo(path="x.ts", name="x.ts", duration=600.0)
    info.streams.append(StreamInfo(
        index=0, codec_type="video", codec_name="h264",
        width=1920, height=1080, r_frame_rate="25/1",
        pix_fmt=pix_fmt, bit_rate="4000000",
        raw={"codec-profile": "High"},
    ))
    info.video_params = vparams
    return format_media_info(info)


def test_yuv420p_not_twelve() -> None:
    """核心回归：8bit yuv420p 即使 average-bpp=12 也显示 8 bits。"""
    text = _video_text("yuv420p", {"pixelformat": "yuv420p", "average-bpp": 12})
    check("8bit yuv420p 显示 8 bits", "Bit depth                         : 8 bits" in text)
    check("不出现 12 bits", "Bit depth                         : 12 bits" not in text)


def test_fallback_to_video_params() -> None:
    """pix_fmt 为空时从 video-params.pixelformat 取，仍不落入 average-bpp。"""
    text = _video_text("", {"pixelformat": "yuv420p", "average-bpp": 12})
    check("pix_fmt 空时回退 video-params 得 8 bits",
          "Bit depth                         : 8 bits" in text)
    check("pix_fmt 空也不显示 12 bits",
          "Bit depth                         : 12 bits" not in text)


def test_no_pixelformat_no_bogus_depth() -> None:
    """既无 pix_fmt 也无 pixelformat、只有 average-bpp 时，不显示伪造的位深。"""
    text = _video_text("", {"average-bpp": 12})
    check("无像素格式时不伪造位深", "Bit depth" not in text)


def test_high_bitdepth_formats() -> None:
    for pix, expected in (("yuv420p10le", "10 bits"), ("yuv420p16le", "16 bits")):
        text = _video_text(pix, {"pixelformat": pix, "average-bpp": 15})
        check(f"{pix} 显示 {expected}",
              f"Bit depth                         : {expected}" in text)


def main() -> None:
    test_bit_depth_parsing()
    test_yuv420p_not_twelve()
    test_fallback_to_video_params()
    test_no_pixelformat_no_bogus_depth()
    test_high_bitdepth_formats()
    print("ALL_BIT_DEPTH_TESTS_PASSED")


if __name__ == "__main__":
    main()
