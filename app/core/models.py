"""数据模型：轨道、播放列表、媒体信息、IPTV 频道与录制任务。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


@dataclass
class TrackInfo:
    index: int
    track_type: str = "audio"  # audio / sub / video
    codec: str = ""
    language: str = ""
    title: str = ""
    external: bool = False
    path: str = ""

    def label(self) -> str:
        parts = [f"{self.index}"]
        if self.language:
            parts.append(self.language)
        if self.codec:
            parts.append(self.codec.upper())
        if self.title:
            parts.append(self.title)
        if self.external:
            parts.append("外部")
        return " - ".join(parts)


@dataclass
class PlaylistItem:
    path: str
    name: str = ""
    duration: float = 0.0
    missing: bool = False


@dataclass
class StreamInfo:
    index: int = 0
    codec_type: str = ""
    codec_name: str = ""
    codec_long_name: str = ""
    width: int = 0
    height: int = 0
    r_frame_rate: str = ""
    sample_rate: str = ""
    channels: int = 0
    bit_rate: str = ""
    pix_fmt: str = ""
    language: str = ""
    title: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StreamInfo":
        tags = data.get("tags") or {}
        return cls(
            index=int(data.get("index", 0)),
            codec_type=str(data.get("codec_type", "")),
            codec_name=str(data.get("codec_name", "")),
            codec_long_name=str(data.get("codec_long_name", "")),
            width=int(data.get("width", 0) or 0),
            height=int(data.get("height", 0) or 0),
            r_frame_rate=str(data.get("r_frame_rate", "")),
            sample_rate=str(data.get("sample_rate", "")),
            channels=int(data.get("channels", 0) or 0),
            bit_rate=str(data.get("bit_rate", "")),
            pix_fmt=str(data.get("pix_fmt", "")),
            language=str(tags.get("language", "")),
            title=str(tags.get("title", "")),
        )


@dataclass
class MediaInfo:
    path: str = ""
    name: str = ""
    size: int = 0
    format_name: str = ""
    duration: float = 0.0
    bit_rate: str = ""
    created: str = ""
    modified: str = ""
    streams: List[StreamInfo] = field(default_factory=list)
    chapters: List[Dict[str, Any]] = field(default_factory=list)
    live: bool = False
    limited: bool = False
    overall_bitrate: str = ""
    bitrate_mode: str = ""
    video_bitrate: str = ""
    frame_rate: str = ""
    # 视频扫描方式：逐行 / 隔行（上场优先 / 下场优先）
    scan_type: str = ""
    # libmpv 额外属性：容器元数据、解码视频参数与内嵌附件（封面图等）
    metadata: Dict[str, Any] = field(default_factory=dict)
    video_params: Dict[str, Any] = field(default_factory=dict)
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    raw_format: Dict[str, Any] = field(default_factory=dict)


class TaskStatus(str, Enum):
    WAITING = "等待中"
    RECORDING = "录制中"
    COMPLETED = "已完成"
    PARTIAL = "部分录制"
    CANCELLED = "已取消"
    FAILED = "失败"


# 录制频率取值（英文源文案，界面显示经 i18n 翻译）
FREQ_ONCE = "once"
FREQ_DAILY = "daily"
FREQ_WEEKLY = "weekly"
FREQ_CUSTOM = "custom"
FREQUENCIES = (FREQ_ONCE, FREQ_DAILY, FREQ_WEEKLY, FREQ_CUSTOM)


def frequency_label(freq: str) -> str:
    """频率英文 key -> 中文源文案（供记录与日志，界面用 tr 再翻译）。"""
    return {
        FREQ_ONCE: "单次",
        FREQ_DAILY: "每日",
        FREQ_WEEKLY: "每周",
        FREQ_CUSTOM: "自定义",
    }.get(freq, "单次")


@dataclass
class Channel:
    name: str
    url: str
    group: str = "默认分组"
    logo: str = ""
    note: str = ""
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Channel":
        return cls(
            name=str(data.get("name", "")),
            url=str(data.get("url", "")),
            group=str(data.get("group", "默认分组") or "默认分组"),
            logo=str(data.get("logo", "") or ""),
            note=str(data.get("note", "") or ""),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class RecordTask:
    id: str
    channel: str
    url: str = ""
    content: str = ""
    start_time: str = ""  # yyyy-MM-dd HH:mm（单次=计划时刻；循环=下次具体发生时点）
    end_time: str = ""
    created_at: str = ""  # yyyy-MM-dd HH:mm:ss 任务创建时刻
    record_dir: str = ""
    record_format: str = "source"
    status: str = TaskStatus.WAITING.value
    output: str = ""
    error: str = ""
    started_ts: int = 0
    stopped_ts: int = 0
    size: int = 0
    actual_start: str = ""
    # 录制频率：once=单次 / daily=每日 / weekly=每周 / custom=自定义日期
    frequency: str = "once"
    # 每周重复的星期，逗号分隔 0-6（0=周一 … 6=周日），如 "0,2,4"
    weekdays: str = ""
    # 自定义日期，逗号分隔 yyyy-MM-dd，最多 5 个
    custom_dates: str = ""
    # 循环任务的每日开始/结束时刻 HH:mm（start_time/end_time 保存下次具体日期时间）
    time_start: str = ""
    time_end: str = ""
    # 循环任务已执行的次数（用于生成不重复的输出文件名与进度展示）
    run_index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecordTask":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class MediaState:
    path: str = ""
    title: str = ""
    time_pos: float = 0.0
    duration: float = 0.0
    speed: float = 1.0
    volume: int = 100
    muted: bool = False
    paused: bool = True
    live: bool = False
    video_codec: str = ""
    audio_codec: str = ""
    vo: str = ""
    ao: str = ""
    hwdec: str = ""
    drop_frames: int = 0
    cache: str = ""


def format_speed(value: float) -> str:
    """按实际选择值显示播放速度，避免 0.75 被四舍五入成 0.8。

    规则：整数值保留一位小数（1.0x / 2.0x），其余按有效数字原样输出
    （0.5x / 0.75x / 0.9x / 1.1x / 1.25x / 1.5x），与速度菜单文本一致。
    对 mpv 回调带来的微小浮点误差做吸附，保证显示稳定。
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 1.0
    rounded = round(number)
    if abs(number - rounded) < 1e-6:
        return f"{rounded:.1f}x"
    return f"{number:g}x"
