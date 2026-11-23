"""libmpv 播放内核封装：属性观察、Qt 信号桥接、轨道与截图控制。"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from .logger import log_error, log_info
from .models import MediaState, TrackInfo
from .settings import ensure_bin_path, resource_root

# 必须先让 python-mpv 能找到 libmpv-2.dll
_BIN_DIR = ensure_bin_path()


class MpvPlayer(QObject):
    """所有 mpv 调用集中在此；mpv 线程回调通过 Qt Signal 切回 GUI 线程。"""

    stateChanged = Signal(object)      # MediaState
    timeChanged = Signal(float, float)  # pos, duration
    pauseChanged = Signal(bool)
    speedChanged = Signal(float)
    volumeChanged = Signal(int, bool)   # volume, muted
    tracksChanged = Signal(object)      # Dict[str, List[TrackInfo]]
    videoSizeChanged = Signal(int, int)  # 视频显示宽高（dw/dh），供窗口按分辨率比例填充
    fileLoaded = Signal(str)
    playbackRestarted = Signal()
    endReached = Signal()
    errorOccurred = Signal(str)
    readyChanged = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mpv = None
        self._available = False
        self._wid: Optional[int] = None
        self._state = MediaState()
        self._external_audio: List[TrackInfo] = []
        self._external_sub: List[TrackInfo] = []
        self._external_audio_index = 0
        self._external_sub_index = 0

    # ---------- 生命周期 ----------
    @property
    def available(self) -> bool:
        return self._available

    @property
    def state(self) -> MediaState:
        return self._state

    def init(self, wid: int, vo: str = "gpu") -> bool:
        """创建 libmpv 实例并嵌入原生窗口；vo='null' 可用于无界面测试。"""
        if self._mpv is not None:
            return True
        self._wid = wid
        try:
            import mpv  # type: ignore
        except Exception as exc:
            self.errorOccurred.emit(
                f"未找到 libmpv-2.dll。已将路径加入搜索：{_BIN_DIR}\n"
                f"请把 LGPL 构建的 libmpv-2.dll 放入该目录（源码模式为项目 bin 目录）。\n{exc}"
            )
            self.readyChanged.emit(False)
            return False
        try:
            self._mpv = mpv.MPV(
                wid=str(int(wid)),
                vo=vo,
                hwdec="auto-safe",
                input_default_bindings=False,
                input_vo_keyboard=False,
                input_cursor=False,
                osc=False,
                osd_level=0,
                keep_open="no",
                force_window="no",
                terminal=False,
                msg_level="all=warn",
            )
            self._mpv.observe_property("time-pos", self._on_time_pos)
            self._mpv.observe_property("duration", self._on_duration)
            self._mpv.observe_property("pause", self._on_pause)
            self._mpv.observe_property("speed", self._on_speed)
            self._mpv.observe_property("volume", self._on_volume)
            self._mpv.observe_property("mute", self._on_mute)
            self._mpv.observe_property("track-list", self._on_track_list)
            self._mpv.observe_property("video-params", self._on_video_params)
            self._mpv.observe_property("audio-params", self._on_audio_params)
            self._mpv.observe_property("video-out-params", self._on_vo_params)
            self._mpv.register_event_callback(self._on_event)
            self._available = True
            self.readyChanged.emit(True)
            log_info("libmpv 初始化成功")
            return True
        except Exception as exc:
            self._mpv = None
            self.errorOccurred.emit(f"libmpv 初始化失败：{exc}")
            log_error(f"libmpv init failed: {exc}")
            self.readyChanged.emit(False)
            return False

    def shutdown(self) -> None:
        if self._mpv is not None:
            try:
                self._mpv.terminate()
            except Exception:
                pass
            self._mpv = None
        self._available = False

    # ---------- mpv 回调 ----------
    def _on_time_pos(self, name, value):
        try:
            pos = float(value or 0.0)
        except (TypeError, ValueError):
            pos = 0.0
        self._state.time_pos = pos
        self.timeChanged.emit(pos, self._state.duration)
        self.stateChanged.emit(self._state)

    def _on_duration(self, name, value):
        try:
            self._state.duration = float(value or 0.0)
        except (TypeError, ValueError):
            self._state.duration = 0.0
        self.timeChanged.emit(self._state.time_pos, self._state.duration)

    def _on_pause(self, name, value):
        self._state.paused = bool(value)
        self.pauseChanged.emit(self._state.paused)

    def _on_speed(self, name, value):
        try:
            self._state.speed = float(value or 1.0)
        except (TypeError, ValueError):
            self._state.speed = 1.0
        self.speedChanged.emit(self._state.speed)

    def _on_volume(self, name, value):
        try:
            self._state.volume = int(value or 0)
        except (TypeError, ValueError):
            self._state.volume = 100
        self.volumeChanged.emit(self._state.volume, self._state.muted)

    def _on_mute(self, name, value):
        self._state.muted = bool(value)
        self.volumeChanged.emit(self._state.volume, self._state.muted)

    def _on_track_list(self, name, value):
        tracks: Dict[str, List[TrackInfo]] = {"audio": [], "sub": [], "video": []}
        for item in value or []:
            try:
                kind = str(item.get("type", ""))
                if kind not in tracks:
                    continue
                tracks[kind].append(
                    TrackInfo(
                        index=int(item.get("id", 0)),
                        track_type=kind,
                        codec=str(item.get("codec", "")),
                        language=str(item.get("lang", "")),
                        title=str(item.get("title", "")),
                    )
                )
            except Exception:
                continue
        # 外部轨道由 mpv 通过 audio-add/sub-add 自动加入 track-list（external=True），
        # 上面的循环已经包含它们；不要再手动追加，否则菜单出现重复项且 id 对不上。
        self.tracksChanged.emit(tracks)

    def _on_video_params(self, name, value):
        if not value:
            return
        self._state.video_codec = str(value.get("codec", "") or "")
        self.stateChanged.emit(self._state)
        # dw/dh 是考虑采样宽高比后的显示尺寸；用它定义视频区比例，保证画面完整填充。
        try:
            dw = int(value.get("dw") or value.get("w") or 0)
            dh = int(value.get("dh") or value.get("h") or 0)
            if dw > 0 and dh > 0:
                self.videoSizeChanged.emit(dw, dh)
        except (TypeError, ValueError):
            pass

    def _on_audio_params(self, name, value):
        if not value:
            return
        self._state.audio_codec = str(value.get("codec", "") or "")
        self.stateChanged.emit(self._state)

    def _on_vo_params(self, name, value):
        if value:
            self._state.vo = str(value.get("backend", "") or "")
        self.stateChanged.emit(self._state)

    def _on_event(self, event):
        # python-mpv 1.x 的 MpvEvent 不再暴露 .event/.reason 属性，事件数据
        # 在 as_dict() 中且值为 bytes；旧版仍走属性读取兜底。
        try:
            raw = event.as_dict()
            name = raw.get("event", b"")
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            name = str(name or "")
            reason = raw.get("reason", b"")
            if isinstance(reason, bytes):
                reason = reason.decode("utf-8", "replace")
            reason = str(reason or "")
        except Exception:
            name = str(getattr(event, "event", "") or "")
            reason = str(getattr(event, "reason", "") or "")
        if name == "end-file":
            log_info(f"[mpv事件] end-file reason={reason}")
            # 只有自然播完才视为结束；切换文件(redirect)/停止(stop)/退出(quit)
            # 不应触发"播放结束"，否则会误清掉刚记录的播放位置。
            if reason == "eof":
                self.endReached.emit()
        elif name == "playback-restart":
            log_info("[mpv事件] playback-restart（首帧已渲染）")
            self.playbackRestarted.emit()
        elif name == "file-loaded":
            path = ""
            try:
                path = str(self.property("path", "") or "")
            except Exception:
                pass
            log_info(f"[mpv事件] file-loaded: {path}")
            self.fileLoaded.emit(path)
        elif name in ("error", "start-file"):
            log_info(f"[mpv事件] {name}")

    # ---------- 播放控制 ----------
    def open(self, path: str, *, live: bool = False, start_pos: float = 0.0) -> None:
        """打开媒体；start_pos>0 时用 loadfile 的 start 选项从指定秒数续播。"""
        if not self._available or self._mpv is None:
            log_error(f"[内核] open 时内核未就绪（available={self._available}, mpv={self._mpv is not None}），忽略: {path}")
            self.errorOccurred.emit("播放内核未就绪")
            return
        self._external_audio.clear()
        self._external_sub.clear()
        self._state = MediaState(path=path, title=os.path.basename(path), live=live)
        try:
            # mpv 0.42 的 loadfile 命令不再接受 options 参数（python-mpv 抛
            # Invalid value for mpv parameter），改用 start 属性在加载前指定起点。
            # 每次打开都显式重置，避免上一个文件的续播位置影响下一个文件。
            try:
                self._mpv.start = float(start_pos) if start_pos > 0 else 0.0
            except Exception:
                pass
            self._mpv.play(path)
            if start_pos > 0:
                log_info(f"[内核] 从 {start_pos:.1f}s 续播: {path}")
            else:
                log_info(f"[内核] 已调用 mpv.play: {path}")
        except Exception as exc:
            self.errorOccurred.emit(f"打开失败：{exc}")
            log_error(f"[内核] mpv.play 异常: {exc}")

    def play_pause(self) -> None:
        if self._available and self._mpv is not None:
            try:
                self._mpv.pause = not bool(self._mpv.pause)
            except Exception as exc:
                self.errorOccurred.emit(str(exc))

    def pause(self, value: bool) -> None:
        if self._available and self._mpv is not None:
            self._mpv.pause = bool(value)

    def stop(self) -> None:
        if self._available and self._mpv is not None:
            try:
                self._mpv.command("stop")
                self._state.time_pos = 0.0
                self.timeChanged.emit(0.0, 0.0)
            except Exception as exc:
                self.errorOccurred.emit(str(exc))

    def seek(self, seconds: float, absolute: bool = True) -> None:
        if self._available and self._mpv is not None:
            try:
                mode = "absolute" if absolute else "relative"
                self._mpv.command("seek", float(seconds), mode, "exact")
            except Exception as exc:
                self.errorOccurred.emit(str(exc))

    def set_speed(self, speed: float) -> None:
        if self._available and self._mpv is not None:
            self._mpv.speed = float(speed)

    def set_volume(self, volume: int) -> None:
        value = max(0, min(100, int(volume)))
        self._state.volume = value
        if self._available and self._mpv is not None:
            self._mpv.volume = value
        self.volumeChanged.emit(value, self._state.muted)

    def set_mute(self, muted: bool) -> None:
        self._state.muted = bool(muted)
        if self._available and self._mpv is not None:
            self._mpv.mute = bool(muted)
        self.volumeChanged.emit(self._state.volume, self._state.muted)

    # ---------- 轨道 ----------
    @staticmethod
    def _track_value(track_id: int) -> str:
        """把轨道 id 转成 mpv command 需要的字符串值；<=0 表示禁用。

        注意：不能用 `mpv.aid = int` 赋值，python-mpv 对整数会抛
        "wrong format" TypeError，导致选择/禁用完全失效；必须用 command set
        并传字符串。mpv 中 "no" 表示禁用该轨道。
        """
        return "no" if track_id is None or int(track_id) <= 0 else str(int(track_id))

    def set_audio_track(self, track_id: int) -> None:
        if self._available and self._mpv is not None:
            value = self._track_value(track_id)
            try:
                self._mpv.command("set", "aid", value)
                log_info(f"[轨道] 设置音轨: {track_id} -> aid={value} (当前 aid={self._mpv.aid})")
            except Exception as exc:
                log_error(f"[轨道] 设置音轨失败 aid={value}: {exc}")

    def set_subtitle_track(self, track_id: int) -> None:
        if self._available and self._mpv is not None:
            value = self._track_value(track_id)
            try:
                self._mpv.command("set", "sid", value)
                log_info(f"[轨道] 设置字幕: {track_id} -> sid={value} (当前 sid={self._mpv.sid})")
            except Exception as exc:
                log_error(f"[轨道] 设置字幕失败 sid={value}: {exc}")

    @staticmethod
    def _normalize_track_id(value) -> int:
        """把 mpv 的 aid/sid 原始值归一化为菜单可用的轨道 id；禁用返回 0。"""
        if value is None or value is False:
            return 0
        if isinstance(value, str):
            if value.lower() in ("no", "", "false"):
                return 0
            try:
                return int(value)
            except ValueError:
                return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def current_audio_track(self) -> int:
        """当前选中的音轨 id，0 表示禁用。"""
        if self._available and self._mpv is not None:
            try:
                return self._normalize_track_id(self._mpv.aid)
            except Exception:
                return 0
        return 0

    def current_subtitle_track(self) -> int:
        """当前选中的字幕 id，0 表示关闭。"""
        if self._available and self._mpv is not None:
            try:
                return self._normalize_track_id(self._mpv.sid)
            except Exception:
                return 0
        return 0

    def add_external_audio(self, path: str) -> None:
        if self._available and self._mpv is not None:
            info = TrackInfo(
                index=self._external_audio_index, track_type="audio",
                codec=os.path.splitext(path)[1].lstrip(".").lower(),
                title=os.path.basename(path), external=True, path=path,
            )
            self._external_audio.append(info)
            self._mpv.command("audio-add", path, "auto", os.path.basename(path))
            self._external_audio_index += 1
            log_info(f"添加外部音轨：{path}")

    def add_external_subtitle(self, path: str, encoding: str = "auto") -> None:
        if self._available and self._mpv is not None:
            info = TrackInfo(
                index=self._external_sub_index, track_type="sub",
                codec=os.path.splitext(path)[1].lstrip(".").lower(),
                title=os.path.basename(path), external=True, path=path,
            )
            self._external_sub.append(info)
            if encoding and encoding != "auto":
                self._mpv.command("sub-add", path, "auto", os.path.basename(path), encoding)
            else:
                self._mpv.command("sub-add", path, "auto", os.path.basename(path))
            self._external_sub_index += 1
            log_info(f"添加外部字幕：{path}")

    def remove_external(self, info: TrackInfo) -> None:
        if self._available and self._mpv is not None:
            try:
                self._mpv.command("track-remove", info.index)
                if info in self._external_audio:
                    self._external_audio.remove(info)
                if info in self._external_sub:
                    self._external_sub.remove(info)
            except Exception as exc:
                self.errorOccurred.emit(str(exc))

    # ---------- 截图 / 属性 ----------
    def screenshot(self, path: str, subtitles: bool = True) -> bool:
        if not self._available or self._mpv is None:
            return False
        try:
            self._mpv.command("screenshot-to-file", path, "subtitles" if subtitles else "video")
            return True
        except Exception as exc:
            self.errorOccurred.emit(f"截图失败：{exc}")
            log_error(f"screenshot failed: {exc}")
            return False

    def property(self, name: str, default=None):
        """python-mpv 通过属性访问读取 mpv 属性（time-pos -> time_pos）。"""
        if not self._available or self._mpv is None:
            return default
        try:
            return getattr(self._mpv, name.replace("-", "_"), default)
        except Exception:
            return default

    def snapshot_state(self) -> MediaState:
        """供属性面板 / Tab OSD 使用的属性快照。"""
        s = self._state
        for key, attr in (
            ("time-pos", "time_pos"), ("duration", "duration"), ("speed", "speed"),
            ("volume", "volume"), ("vo-configured", "vo"), ("hwdec-current", "hwdec"),
            ("frame-drop-count", "drop_frames"),
        ):
            try:
                value = self.property(key)
                if value is not None:
                    setattr(s, attr, value)
            except Exception:
                continue
        return s

    def set_option(self, key: str, value) -> None:
        if self._available and self._mpv is not None:
            try:
                setattr(self._mpv, key.replace("-", "_"), value)
            except Exception as exc:
                log_error(f"set option {key}: {exc}")
