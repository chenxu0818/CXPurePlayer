"""分节式文件信息格式化：General / Video / Audio / Text / Chapters 分节输出。

所有字段来自 libmpv 提供的 MediaInfo，不依赖任何 GPL 工具。
"""

from __future__ import annotations

from math import gcd
from typing import Dict, List

from .models import MediaInfo, StreamInfo

_KEY_WIDTH = 34  # 左对齐字段宽度


def _line(key: str, value) -> str:
    if value in (None, "", "--"):
        return ""
    return f"{key:<{_KEY_WIDTH}}: {value}"


def _space_thousands(text: str) -> str:
    """把数字每三位用空格分隔（分节式）。"""
    if not text:
        return ""
    try:
        return f"{int(text):,}".replace(",", " ")
    except (TypeError, ValueError):
        return text


def _human_size(size: int) -> str:
    value = float(size or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return ""


def _duration(seconds) -> str:
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        return ""
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    if h and m:
        return f"{h} h {m} min"
    if h:
        return f"{h} h {m:02d} min"
    if m and s:
        return f"{m} min {s:02d} s"
    if m:
        return f"{m} min"
    return f"{s} s"


def _kbps(bits: str) -> str:
    try:
        value = float(bits)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    return f"{_space_thousands(str(int(round(value / 1000))))} kb/s"


def _mhz(samplerate: str) -> str:
    try:
        value = float(samplerate)
    except (TypeError, ValueError):
        return samplerate or ""
    if value <= 0:
        return ""
    return f"{value / 1000:.1f} kHz"


def _format_name(info: MediaInfo) -> str:
    mapping = {
        "mpegts": "MPEG-TS", "matroska": "Matroska", "webm": "WebM",
        "avi": "AVI", "mov": "QuickTime / MOV", "mp4": "MPEG-4",
        "flv": "Flash Video", "mp3": "MPEG Audio", "ogg": "OGG",
        "wav": "WAVE",
    }
    raw = (info.format_name or "").lower()
    for key in mapping:
        if key in raw:
            return mapping[key]
    return mapping.get(raw, raw.upper() if raw else "")


def _codec_format(stream: StreamInfo) -> tuple[str, str]:
    codec = (stream.codec_name or "").lower()
    mapping = {
        "h264": ("AVC", "Advanced Video Codec"),
        "hevc": ("HEVC", "High Efficiency Video Coding"),
        "av1": ("AV1", "AOMedia Video 1"),
        "vp9": ("VP9", "Google VP9"),
        "mpeg4": ("MPEG-4 Visual", "MPEG-4 Visual"),
        "mpeg2video": ("MPEG Video", "MPEG Video version 2"),
        "aac": ("AAC", "Advanced Audio Codec"),
        "mp2": ("MPEG Audio", "MPEG Audio version 1"),
        "mp3": ("MPEG Audio", "MPEG Audio version 1"),
        "ac3": ("AC-3", "Audio Coding 3"),
        "eac3": ("E-AC-3", "Enhanced AC-3"),
        "dts": ("DTS", "DTS"),
        "flac": ("FLAC", "Free Lossless Audio Codec"),
        "subrip": ("SRT", "SubRip"),
        "ass": ("ASS", "Advanced SubStation Alpha"),
        "ssa": ("SSA", "SubStation Alpha"),
        "webvtt": ("WebVTT", "Web Video Text Tracks"),
        "dvb_subtitle": ("DVB", "DVB Subtitle"),
        "dvd_subtitle": ("DVD", "DVD Subtitle"),
        "hdmv_pgs_subtitle": ("PGS", "Blu-ray Presentation Graphics"),
        "pgssub": ("PGS", "Blu-ray Presentation Graphics"),
    }
    return mapping.get(codec, (stream.codec_name.upper() if stream.codec_name else "--",
                               stream.codec_long_name or ""))


def _hex_id(value) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value or "")
    return f"{number} (0x{number:X})"


# MPEG-TS 等容器常见的 MediaInfo 风格 Codec ID（十进制）
_CODEC_IDS = {
    "h264": 27, "avc1": 27, "hevc": 173, "h265": 173, "mpeg4": 32,
    "mpeg2video": 2, "mp2": 3, "mp3": 3, "aac": 15, "ac3": 129,
    "eac3": 135, "dts": 132, "flac": 175, "subrip": 32, "ass": 33,
    "ssa": 34, "webvtt": 36, "hdmv_pgs_subtitle": 144, "dvb_subtitle": 130,
}


def _codec_id(stream: StreamInfo) -> str:
    codec = (stream.codec_name or "").lower()
    value = _CODEC_IDS.get(codec)
    if value:
        return str(value)
    return codec.upper() if codec else ""


def _pixel_format_of(stream: StreamInfo, info: MediaInfo) -> str:
    """统一取像素格式：优先解码后的 video-params，其次轨道的 pixelformat。

    libmpv 的 track-list 里视频轨常常没有 pixelformat，而 video-params 里有；
    两条探测路径（mpv / ffprobe）都要兼容，避免位深回退到错误的 average-bpp。
    """
    vp = info.video_params or {}
    return str(vp.get("pixelformat") or stream.pix_fmt or "").lower()


def _bit_depth(pix: str) -> str:
    """从像素格式字符串解析位深，返回 ``"N bits"``；无法判断时返回空串。

    只根据像素格式本身判断，绝不使用 mpv 的 ``average-bpp``——那是「每像素
    平均位数」（如 8bit yuv420p 为 8+2+2=12），不是位深，曾导致 8bit 被显示成
    12 bits。解析规则覆盖 FFmpeg 常见命名：

    - ``yuv420p`` / ``nv12`` / ``yuyv422`` → 8 bits（无显式位深后缀）
    - ``yuv420p10le`` / ``yuv422p12le`` / ``gbrp16le`` → 后缀数字即位深
    - ``p010le`` / ``p016le`` / ``yuv420p10`` → 10 / 16 bits
    - ``rgb24`` → 8 bits；``rgb48le`` → 16 bits
    """
    pix = (pix or "").lower()
    if not pix:
        return ""
    # 形如 yuv420p / yuv420p10le / gbrp16le / rgb48le 的末尾位深数字：
    # 紧跟在 'p' 之后、可选的 le/be 之前（如 p10、p12、p16），或 rgb24/rgb48。
    import re
    m = re.search(r"p(\d{1,2})(?:le|be)?$", pix)
    if m:
        depth = int(m.group(1))
        if depth in (8, 9, 10, 12, 14, 16):
            return f"{depth} bits"
    # rgb24/rgb48 表示整帧每像素位数（3 通道），需除以通道数换成单通道位深
    m = re.match(r"^(?:rgb|bgr)(\d{1,2})(?:le|be)?$", pix)
    if m:
        total = int(m.group(1))
        per_channel = total // 3
        if per_channel in (8, 10, 12, 14, 16):
            return f"{per_channel} bits"
    # p010 / p016 系列（ planes 命名，如 p010le）
    m = re.match(r"^p0?(\d{1,2})(?:le|be)?$", pix)
    if m:
        depth = int(m.group(1))
        if depth in (8, 10, 12, 14, 16):
            return f"{depth} bits"
    # 其余常见 8bit 像素格式：yuv420p 已在上面 p(\d) 不匹配，落到默认 8。
    if pix.startswith(("yuv", "rgb", "bgr", "nv", "gray", "gbr", "uyvy", "yuyv")):
        return "8 bits"
    return ""


def _bits_per_pixel_frame(stream: StreamInfo, bitrate: str) -> str:
    try:
        bits = float(bitrate or 0)
        w, h = int(stream.width), int(stream.height)
        fps = float(str(stream.r_frame_rate).split("/")[0] or 0)
        if "/" in str(stream.r_frame_rate):
            den = float(str(stream.r_frame_rate).split("/")[1] or 1)
            fps = fps / den if den else 0
        if bits and w and h and fps:
            return f"{bits / (w * h * fps):.3f}"
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return ""


def _fps_lines(stream: StreamInfo, info: MediaInfo, add) -> None:
    fps = str(stream.r_frame_rate or info.frame_rate or "")
    if not fps:
        return
    try:
        f = float(fps.split("/")[0])
        if "/" in fps:
            den = float(fps.split("/")[1] or 1)
            f = f / den if den else 0
        if f:
            add("Frame rate", f"{f:.3f} FPS")
            add("Frame rate mode", "Constant")
    except (ValueError, ZeroDivisionError):
        add("Frame rate", fps)


def _flags(raw: Dict, add) -> None:
    """轨道默认/强制/外部标记。"""
    if raw.get("default"):
        add("Default", "Yes")
    if raw.get("forced"):
        add("Forced", "Yes")
    if raw.get("external"):
        add("External", "Yes")


def _section_video(stream: StreamInfo, info: MediaInfo) -> List[str]:
    raw = stream.raw or {}
    fmt, fmt_info = _codec_format(stream)
    lines = ["Video"]
    add = lambda k, v: lines.append(_line(k, v))  # noqa: E731
    add("ID", _hex_id(raw.get("src-id", stream.index)))
    if raw.get("program-id"):
        add("Menu ID", _hex_id(raw.get("program-id")))
    add("Format", fmt)
    add("Format/Info", fmt_info)
    if raw.get("codec-profile"):
        add("Format profile", raw.get("codec-profile"))
    add("Codec ID", _codec_id(stream))
    add("Duration", _duration(raw.get("demux-duration") or info.duration))
    bitrate = stream.bit_rate or raw.get("demux-bitrate") or ""
    add("Bit rate", _kbps(bitrate))
    add("Width", f"{_space_thousands(str(stream.width))} pixels" if stream.width else "")
    add("Height", f"{_space_thousands(str(stream.height))} pixels" if stream.height else "")
    if stream.width and stream.height:
        g = gcd(stream.width, stream.height)
        if g and stream.width // g <= 40 and stream.height // g <= 40:
            add("Display aspect ratio", f"{stream.width // g}:{stream.height // g}")
    par = raw.get("demux-par") or info.video_params.get("par")
    if par:
        try:
            add("Sample aspect ratio", f"{float(par):.3f}")
        except (TypeError, ValueError):
            pass
    _fps_lines(stream, info, add)
    if info.scan_type:
        add("Scan type", info.scan_type)
    # 色彩相关：优先取解码后 video-params，其次取像素格式推断
    vp = info.video_params or {}
    colormatrix = vp.get("colormatrix") or ""
    color_map = {"bt.709": "ITU-R BT.709", "bt.601": "ITU-R BT.601",
                 "bt.2020": "ITU-R BT.2020", "rgb": "RGB"}
    if colormatrix:
        add("Matrix coefficients", color_map.get(str(colormatrix).lower(), str(colormatrix).upper()))
    if vp.get("primaries"):
        add("Color primaries", str(vp["primaries"]).upper())
    if vp.get("gamma"):
        add("Transfer characteristics", str(vp["gamma"]).upper())
    if vp.get("chroma-location"):
        add("Chroma location", str(vp["chroma-location"]))
    if vp.get("colorlevels"):
        add("Color range", "Full" if "full" in str(vp["colorlevels"]).lower() else "Limited")
    pix = _pixel_format_of(stream, info)
    if pix.startswith(("yuv", "nv", "gbr", "uyvy", "yuyv")):
        add("Color space", "YUV")
        for token, label in (("420", "4:2:0"), ("422", "4:2:2"), ("444", "4:4:4"), ("410", "4:1:0"), ("411", "4:1:1")):
            if token in pix:
                add("Chroma subsampling", label)
                break
    elif pix.startswith(("rgb", "bgr")):
        add("Color space", "RGB")
    depth = _bit_depth(pix)
    if depth:
        add("Bit depth", depth)
    add("Bits/(Pixel*Frame)", _bits_per_pixel_frame(stream, bitrate))
    try:
        stream_size = float(bitrate or 0) * float(raw.get("demux-duration") or info.duration) / 8
        if stream_size and info.size:
            pct = stream_size / info.size * 100
            add("Stream size", f"{_human_size(int(stream_size))} ({pct:.0f}%)")
        elif stream_size:
            add("Stream size", _human_size(int(stream_size)))
    except (TypeError, ValueError):
        pass
    if stream.language:
        add("Language", stream.language)
    if stream.title:
        add("Title", stream.title)
    _flags(raw, add)
    if info.metadata.get("encoder"):
        add("Encoded application", info.metadata["encoder"])
    return [ln for ln in lines if ln == "Video" or ln]


def _section_audio(stream: StreamInfo, info: MediaInfo) -> List[str]:
    raw = stream.raw or {}
    fmt, fmt_info = _codec_format(stream)
    lines = ["Audio"]
    add = lambda k, v: lines.append(_line(k, v))  # noqa: E731
    add("ID", _hex_id(raw.get("src-id", stream.index)))
    if raw.get("program-id"):
        add("Menu ID", _hex_id(raw.get("program-id")))
    add("Format", fmt)
    add("Format/Info", fmt_info)
    if stream.codec_name.lower() in ("mp2", "mp3"):
        add("Format version", "Version 1")
        if stream.codec_name.lower() == "mp2":
            add("Format profile", "Layer 2")
    add("Codec ID", _codec_id(stream))
    add("Duration", _duration(raw.get("demux-duration") or info.duration))
    bitrate = stream.bit_rate or raw.get("demux-bitrate") or ""
    if bitrate:
        add("Bit rate mode", "Constant")
    add("Bit rate", _kbps(bitrate))
    if stream.channels:
        names = {1: "Mono", 2: "Stereo", 6: "5.1"}
        ch = names.get(stream.channels, f"{stream.channels} channels")
        add("Channel(s)", f"{stream.channels} channels" if stream.channels > 2 else ch)
    aparams = raw.get("audio-params") or {}
    layout = aparams.get("channel-layout") or aparams.get("hr-channels") or ""
    if layout:
        add("Channel layout", str(layout))
    add("Sampling rate", _mhz(stream.sample_rate))
    if aparams.get("format"):
        add("Format", f"{fmt} / {aparams['format']}")
    add("Compression mode", "Lossy")
    try:
        stream_size = float(bitrate or 0) * float(raw.get("demux-duration") or info.duration) / 8
        if stream_size and info.size:
            pct = stream_size / info.size * 100
            add("Stream size", f"{_human_size(int(stream_size))} ({pct:.0f}%)")
        elif stream_size:
            add("Stream size", _human_size(int(stream_size)))
    except (TypeError, ValueError):
        pass
    if stream.language:
        add("Language", stream.language)
    if stream.title:
        add("Title", stream.title)
    _flags(raw, add)
    return [ln for ln in lines if ln == "Audio" or ln]


def _section_text(stream: StreamInfo, info: MediaInfo) -> List[str]:
    raw = stream.raw or {}
    fmt, fmt_info = _codec_format(stream)
    lines = ["Text"]
    add = lambda k, v: lines.append(_line(k, v))  # noqa: E731
    add("ID", _hex_id(raw.get("src-id", stream.index)))
    add("Format", fmt)
    add("Format/Info", fmt_info)
    add("Codec ID", _codec_id(stream))
    add("Duration", _duration(raw.get("demux-duration") or info.duration))
    if stream.language:
        add("Language", stream.language)
    if stream.title:
        add("Title", stream.title)
    _flags(raw, add)
    return [ln for ln in lines if ln == "Text" or ln]


def format_media_info(info: MediaInfo) -> str:
    """生成 分节式完整文件信息文本。"""
    if info is None:
        return ""
    # 每个元素为一个信息块，块之间输出空行分割
    blocks: List[List[str]] = []
    total_bytes = int(info.size or 0)
    overall = float(info.overall_bitrate or 0) or (total_bytes * 8 / info.duration if info.duration else 0)

    # General
    general = ["General"]
    general.append(_line("ID", "1 (0x1)"))
    general.append(_line("Complete name", info.path))
    general.append(_line("Format", _format_name(info)))
    if info.size:
        general.append(_line("File size", _human_size(info.size)))
    if info.duration:
        general.append(_line("Duration", _duration(info.duration)))
    if info.bitrate_mode:
        general.append(_line("Overall bit rate mode", "Variable" if info.bitrate_mode.upper() == "VBR" else "Variable"))
    if overall:
        general.append(_line("Overall bit rate", _kbps(str(int(overall)))))
    if info.frame_rate:
        general.append(_line("Frame rate", f"{float(info.frame_rate):.3f} FPS" if _is_number(info.frame_rate) else info.frame_rate))
    if info.metadata.get("encoder"):
        general.append(_line("Encoded application", info.metadata["encoder"]))
    if info.created:
        general.append(_line("Written date", info.created))
    if info.modified:
        general.append(_line("File modified date", _local_date(info.modified)))
    for attachment in info.attachments:
        codec = str(attachment.get("codec", "")).upper()
        label = f"{attachment.get('name', 'cover')} ({codec} image)"
        general.append(_line("Attachment", label))
    blocks.append([ln for ln in general if ln == "General" or ln])

    for stream in info.streams:
        if stream.codec_type == "video":
            blocks.append(_section_video(stream, info))
        elif stream.codec_type == "audio":
            blocks.append(_section_audio(stream, info))
        elif stream.codec_type == "sub":
            blocks.append(_section_text(stream, info))

    if info.chapters:
        chapters = ["Chapters"]
        for chapter in info.chapters:
            title = chapter.get("title") or f"Chapter {chapter.get('index', 0) + 1}"
            chapters.append(_line(_duration(chapter.get("start", 0)), title))
        blocks.append(chapters)

    # 信息块之间用一个空行分割（分节式）
    return "\n\n".join("\n".join(block) for block in blocks if block)


def _is_number(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _local_date(value: str) -> str:
    """modified 存的是 Unix 秒，格式化为本地时间。"""
    try:
        from datetime import datetime
        return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return value
