"""ffprobe 异步调用与媒体信息解析（直播 URL 10 秒超时）。"""

from __future__ import annotations

import json
import os
import subprocess
from typing import List, Optional

from PySide6.QtCore import QObject, QThread, Signal

from .logger import log_error, log_info
from .models import MediaInfo, StreamInfo
from .settings import resource_root, subprocess_env

FFPROBE_CANDIDATES = [
    os.path.join(resource_root(), "bin", "ffprobe.exe"),
    os.path.join(resource_root(), "bin", "ffprobe"),
    "/opt/homebrew/bin/ffprobe",
    "/usr/local/bin/ffprobe",
    "ffprobe",
]


def ffprobe_path() -> str:
    for candidate in FFPROBE_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
        if candidate == "ffprobe":
            return candidate
    return ""


def scan_type_from_field_order(value) -> str:
    """把 ffprobe 的 field_order 统一映射为扫描方式文案（与 libmpv 分支一致）。"""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text == "progressive":
        return "Progressive"
    if text.startswith("t"):
        return "Interlaced (top field first)"
    if text.startswith("b"):
        return "Interlaced (bottom field first)"
    return ""


class ProbeWorker(QThread):
    finishedInfo = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, live: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.path = path
        self.live = live
        self._stop = False

    def run(self) -> None:
        binary = ffprobe_path()
        if not binary:
            self.failed.emit("未找到 ffprobe")
            return
        command = [
            binary, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", "-show_chapters",
        ]
        if self.live:
            command += ["-rw_timeout", "10000000"]
        command.append(self.path)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20 if self.live else 60,
                env=subprocess_env(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if self._stop:
                return
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip()[:300] or "ffprobe 返回错误")
            data = json.loads(result.stdout or "{}")
            info = parse_probe(data, self.path, self.live)
            self.finishedInfo.emit(info)
        except subprocess.TimeoutExpired:
            info = MediaInfo(path=self.path, name=os.path.basename(self.path), live=True, limited=True)
            self.finishedInfo.emit(info)
        except Exception as exc:
            log_error(f"ffprobe failed for {self.path}: {exc}")
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        self._stop = True


def parse_probe(data: dict, path: str, live: bool = False) -> MediaInfo:
    fmt = data.get("format") or {}
    streams: List[StreamInfo] = [
        StreamInfo.from_dict(item) for item in (data.get("streams") or [])
    ]
    # 直播流常走 ffprobe 回退路径，field_order 是那里唯一可得的扫描方式信息。
    scan_type = ""
    for item in data.get("streams") or []:
        if str(item.get("codec_type", "")) != "video":
            continue
        scan_type = scan_type_from_field_order(item.get("field_order"))
        if scan_type:
            break
    try:
        duration = float(fmt.get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0
    chapters = []
    for chapter in data.get("chapters") or []:
        tags = chapter.get("tags") or {}
        chapters.append(
            {
                "index": int(chapter.get("id", 0) or 0),
                "start": float(chapter.get("start_time", 0) or 0),
                "title": str(tags.get("title", "")),
            }
        )
    try:
        size = int(fmt.get("size", 0) or 0)
    except (TypeError, ValueError):
        size = 0
    return MediaInfo(
        path=path,
        name=os.path.basename(path),
        size=size,
        format_name=str(fmt.get("format_name", "")),
        duration=duration,
        bit_rate=str(fmt.get("bit_rate", "")),
        created=str(fmt.get("creation_time", "")),
        modified=str(fmt.get("mtime", "")),
        streams=streams,
        chapters=chapters,
        live=live,
        scan_type=scan_type,
    )


def build_info_from_mpv(player, path: str, live: bool = False) -> MediaInfo:
    """不依赖 ffprobe：直接用 libmpv 属性构造媒体信息（LGPL 组合更干净）。"""
    info = MediaInfo(path=path, name=os.path.basename(path), live=live)
    if not live and os.path.isfile(path):
        try:
            info.size = os.path.getsize(path)
            info.modified = str(int(os.path.getmtime(path)))
        except OSError:
            pass
    info.format_name = str(player.property("file-format", "") or "")
    try:
        info.duration = float(player.property("duration", 0) or 0)
    except (TypeError, ValueError):
        info.duration = 0.0

    # 容器元数据（encoder / creation_time / title 等）与解码后的视频参数，
    # 用于补齐分节式文件信息中原本缺失的字段。
    meta = player.property("metadata", {}) or {}
    info.metadata = {str(k): str(v) for k, v in dict(meta).items()} if isinstance(meta, dict) else {}
    vparams = player.property("video-params", {}) or {}
    info.video_params = dict(vparams) if isinstance(vparams, dict) else {}
    if info.metadata.get("creation_time"):
        info.created = info.metadata["creation_time"]

    # 扫描方式：libmpv 的 video-frame-info/interlaced + tff 能区分逐行/隔行，
    # 从而让用户分辨 1080p（逐行）与 1080i（隔行）。按原始信息展示，不做中文翻译。
    try:
        frame_info = player.property("video-frame-info", {}) or {}
        if isinstance(frame_info, dict):
            if frame_info.get("interlaced"):
                field = "top field first" if frame_info.get("tff") else "bottom field first"
                info.scan_type = f"Interlaced ({field})"
            else:
                info.scan_type = "Progressive"
    except Exception:
        pass

    # 视频/音频裸码率与容器帧率，用于文件信息摘要
    for attr, key in (
        ("video_bitrate", "video-bitrate"), ("audio_bitrate", "audio-bitrate"),
        ("frame_rate", "container-fps"),
    ):
        try:
            value = float(player.property(key, 0) or 0)
        except (TypeError, ValueError):
            value = 0.0
        setattr(info, attr, str(value) if value else "")
    if info.size and info.duration:
        info.overall_bitrate = str(int(info.size * 8 / info.duration))
        info.bitrate_mode = "CBR"

    # 章节（libmpv chapter-list）
    for chapter in player.property("chapter-list", []) or []:
        if not isinstance(chapter, dict):
            continue
        info.chapters.append({
            "index": int(chapter.get("id", len(info.chapters)) or len(info.chapters)),
            "start": float(chapter.get("time", 0) or 0),
            "title": str(chapter.get("title", "") or ""),
        })

    tracks = player.property("track-list", []) or []
    aparams_global = player.property("audio-params", {}) or {}
    if not isinstance(aparams_global, dict):
        aparams_global = {}
    for track in tracks:
        if not isinstance(track, dict):
            continue
        kind = str(track.get("type", ""))
        if kind not in ("video", "audio", "sub"):
            continue
        # 内嵌封面图（albumart / image）在 mpv 中同为 video 类型，
        # 但不属于视频流：作为附件展示在 General 段。
        if track.get("image") or track.get("albumart") or track.get("attached-picture"):
            info.attachments.append({
                "name": str(track.get("title", "") or track.get("filename", "") or "cover"),
                "codec": str(track.get("codec", "")),
                "type": "image",
            })
            continue
        params = track.get("audio-params") or {}
        if not isinstance(params, dict):
            params = {}
        demux = track.get("demux-format") or ""
        try:
            width = int(track.get("demux-w", 0) or 0)
            height = int(track.get("demux-h", 0) or 0)
        except (TypeError, ValueError):
            width = height = 0
        if kind == "video":
            width = width or int(vparams.get("w", 0) or 0)
            height = height or int(vparams.get("h", 0) or 0)
        rate = track.get("demux-bitrate") or track.get("bitrate") or ""
        if not rate:
            if kind == "video" and info.video_bitrate:
                rate = info.video_bitrate
            elif kind == "audio" and info.audio_bitrate:
                rate = info.audio_bitrate
        sample_rate = str(params.get("samplerate", "") or track.get("demux-samplerate", ""))
        channels = int(params.get("channel-count", 0) or track.get("demux-channel-count", 0) or 0)
        if kind == "audio" and not sample_rate:
            sample_rate = str(aparams_global.get("samplerate", ""))
        if kind == "audio" and not channels:
            channels = int(aparams_global.get("channel-count", 0) or 0)
        raw = dict(track)
        if kind == "audio" and params:
            raw["audio-params"] = params
        if kind == "video" and vparams:
            raw["video-params"] = vparams
        info.streams.append(
            StreamInfo(
                index=int(track.get("id", 0) or 0),
                codec_type=kind,
                codec_name=str(track.get("codec", "")),
                codec_long_name=str(track.get("codec-desc", "") or demux),
                width=width,
                height=height,
                r_frame_rate=str(track.get("demux-fps", "") or info.frame_rate),
                sample_rate=sample_rate,
                channels=channels,
                bit_rate=str(rate),
                # libmpv 视频轨的像素格式字段是 format-name（并非 pixelformat），
                # video-params 未就绪时它是唯一可靠来源，缺失会让 Bit depth 消失。
                pix_fmt=str(track.get("pixelformat", "") or track.get("format-name", "")
                            or vparams.get("pixelformat", "")),
                language=str(track.get("lang", "") or (track.get("metadata") or {}).get("language", "")),
                title=str(track.get("title", "")),
                raw=raw,
            )
        )
    # 用音频流码率判断恒定/可变（简单启发：单音频流且位率有值视为 CBR）
    audios = [s for s in info.streams if s.codec_type == "audio"]
    if len(audios) == 1 and audios[0].bit_rate:
        info.bitrate_mode = "CBR"

    # 视频码率：mpv 的 video-bitrate 常为不稳定估算，改用 总码率 - 音频码率 还原，
    # 更接近 MediaInfo 的显示值。
    videos = [s for s in info.streams if s.codec_type == "video"]
    if videos and info.size and info.duration:
        def _to_int(value) -> int:
            try:
                return int(float(value or 0))
            except (TypeError, ValueError):
                return 0

        audio_total = sum(_to_int(a.bit_rate) for a in audios)
        video_rate = _to_int(info.overall_bitrate) - audio_total
        if video_rate > 0:
            info.video_bitrate = str(video_rate)
            for video in videos:
                video.bit_rate = str(video_rate)
    return info


class MediaInfoCache(QObject):
    """异步探测 + 缓存，切换轨道不重复探测。"""

    infoReady = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cache: dict[str, MediaInfo] = {}
        self._worker: Optional[ProbeWorker] = None

    def probe_with_player(self, path: str, player, live: bool = False) -> None:
        """优先用 libmpv 属性，避免依赖任何 GPL 工具。"""
        if not path:
            return
        # 直播流首帧前轨道为空会先启动一次 ffprobe；随后 mpv 轨道就绪再次探测时，
        # 必须取消那次异步探测，否则它的空结果会覆盖已经拿到的扫描方式等信息。
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(500)
            self._worker = None
        cached = self._cache.get(path)
        if cached is not None:
            self.infoReady.emit(cached)
            return
        info = build_info_from_mpv(player, path, live)
        if not info.streams and not info.duration:
            self.probe(path, live)
            return
        self._on_finished(info)

    def probe(self, path: str, live: bool = False) -> None:
        if not path:
            return
        cached = self._cache.get(path)
        if cached is not None:
            self.infoReady.emit(cached)
            return
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(500)
        worker = ProbeWorker(path, live, self)
        worker.finishedInfo.connect(self._on_finished)
        worker.failed.connect(lambda msg: log_error(f"probe: {msg}"))
        self._worker = worker
        worker.start()

    def _on_finished(self, info: MediaInfo) -> None:
        self._cache[info.path] = info
        self.infoReady.emit(info)

    def get(self, path: str) -> Optional[MediaInfo]:
        return self._cache.get(path)

    def invalidate(self, path: str) -> None:
        """轨道/字幕后加载或变更时丢弃旧快照，下次重新读取完整信息。"""
        self._cache.pop(path, None)

    def clear(self) -> None:
        self._cache.clear()


def format_size(size: int) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return ""


def codec_label(name: str) -> str:
    mapping = {
        "h264": "H.264", "hevc": "H.265/HEVC", "av1": "AV1", "vp9": "VP9",
        "mpeg4": "MPEG-4", "mpeg2video": "MPEG-2", "aac": "AAC", "mp3": "MP3",
        "flac": "FLAC", "opus": "Opus", "vorbis": "Vorbis", "ac3": "AC3",
        "eac3": "E-AC3", "dts": "DTS", "truehd": "TrueHD",
        "subrip": "SRT", "ass": "ASS", "ssa": "SSA", "webvtt": "WebVTT",
    }
    return mapping.get((name or "").lower(), (name or "--").upper())
