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

    @staticmethod
    def _log_dll_diagnostics(exc: Exception) -> None:
        """DLL 加载失败时记录完整异常链、原生 WinError 与依赖逐个加载结果，定位根因。"""
        import platform
        import traceback
        import ctypes
        log_error("[DLL诊断] ===== libmpv 加载失败诊断开始 =====")
        log_error(f"[DLL诊断] 系统: {platform.platform()} | {platform.machine()} | Python {platform.python_version()}")
        log_error(f"[DLL诊断] 冻结打包: {getattr(sys, 'frozen', False)} | _MEIPASS={getattr(sys, '_MEIPASS', '')}")
        log_error(f"[DLL诊断] DLL 搜索目录: {_BIN_DIR}")
        log_error(f"[DLL诊断] 外层异常: {type(exc).__name__}: {exc}")
        # 挖完整异常链（PyInstaller hook 会包一层 PyInstallerImportError，原生
        # FileNotFoundError / WinError 藏在 __cause__ 里，深挖才能拿到真实错误码）
        seen: set = set()
        cur = exc
        depth = 0
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            log_error(
                f"[DLL诊断] 异常链[{depth}] {type(cur).__name__}: "
                f"winerror={getattr(cur, 'winerror', None)} errno={getattr(cur, 'errno', None)} :: {str(cur)[:260]}"
            )
            cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
            depth += 1
        log_error(f"[DLL诊断] 完整 traceback:\n{traceback.format_exc()}")

        dll_path = os.path.join(_BIN_DIR, "libmpv-2.dll")
        exists = os.path.isfile(dll_path)
        try:
            size = os.path.getsize(dll_path) if exists else -1
        except Exception:
            size = -2
        log_error(f"[DLL诊断] DLL 存在={exists} 大小={size} 路径={dll_path}")
        log_error(f"[DLL诊断] 路径纯ASCII={all(ord(c) < 128 for c in dll_path)}")

        # 用原始 kernel32.LoadLibraryExW 绕过 PyInstaller 的 CDLL hook，拿真实错误码。
        # 同时对 libmpv 的关键依赖逐个加载，直接定位缺失/损坏的那一个。
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
            k32.LoadLibraryExW.restype = ctypes.c_void_p
            k32.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
            k32.FreeLibrary.argtypes = [ctypes.c_void_p]
            k32.FreeLibrary.restype = ctypes.c_int
            flag_sets = [
                ("PLAIN", 0),
                ("ALTERED_SEARCH", 0x00000008),
                ("MPV_FLAGS", 0x00001000 | 0x00000100),
            ]
            for label, flags in flag_sets:
                ctypes.set_last_error(0)
                handle = k32.LoadLibraryExW(dll_path, None, flags)
                err = ctypes.get_last_error()
                log_error(f"[DLL诊断] LoadLibraryExW[{label}] handle={handle} GetLastError={err}")
                if handle:
                    k32.FreeLibrary(handle)

            # libmpv-2.dll 的实际依赖（pefile 从随包 DLL 导入表提取）
            deps = (
                "GDI32.dll ole32.dll USER32.dll VERSION.dll vulkan-1.dll ADVAPI32.dll "
                "KERNEL32.dll OLEAUT32.dll api-ms-win-core-winrt-l1-1-0.dll AVRT.dll "
                "dwmapi.dll IMM32.dll api-ms-win-core-path-l1-1-0.dll SHCORE.dll "
                "UxTheme.dll WINMM.dll api-ms-win-core-winrt-error-l1-1-1.dll SHELL32.dll "
                "OPENGL32.dll api-ms-win-crt-stdio-l1-1-0.dll api-ms-win-crt-runtime-l1-1-0.dll "
                "bcrypt.dll SHLWAPI.dll WS2_32.dll DWrite.dll Secur32.dll IPHLPAPI.DLL "
                "WLDAP32.dll CRYPT32.dll api-ms-win-core-synch-l1-2-0.dll ntdll.dll "
                "bcryptprimitives.dll AVICAP32.dll SETUPAPI.dll Normaliz.dll d2d1.dll"
            ).split()
            failed_deps = []
            for dep in deps:
                ctypes.set_last_error(0)
                hdep = k32.LoadLibraryExW(dep, None, 0)
                if not hdep:
                    failed_deps.append(f"{dep}(err={ctypes.get_last_error()})")
                else:
                    k32.FreeLibrary(hdep)
            log_error(f"[DLL诊断] 依赖加载失败: {failed_deps if failed_deps else 'NONE'}")
        except Exception as de:
            log_error(f"[DLL诊断] Win32 API 诊断出错: {type(de).__name__}: {de}")

        # 测试把 DLL 复制到纯 ASCII 短路径后能否加载（区分杀软拦截 Temp/中文路径 vs 依赖缺失）
        try:
            import shutil
            # 选一个人人可写、纯 ASCII 的目录（Public 优先，回退系统 Temp）
            public = os.environ.get("PUBLIC", "C:\\Users\\Public")
            ascii_dir = os.path.join(public, "cxmpvdiag")
            if not os.access(public, os.W_OK):
                ascii_dir = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Temp", "cxmpvdiag")
            os.makedirs(ascii_dir, exist_ok=True)
            ascii_dll = os.path.join(ascii_dir, "libmpv-2.dll")
            shutil.copyfile(dll_path, ascii_dll)
            k32b = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
            k32b.LoadLibraryExW.restype = ctypes.c_void_p
            k32b.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
            ctypes.set_last_error(0)
            h_ascii = k32b.LoadLibraryExW(ascii_dll, None, 0x00000008)
            log_error(
                f"[DLL诊断] ASCII短路径加载: path={ascii_dll} handle={h_ascii} "
                f"GetLastError={ctypes.get_last_error()}"
            )
        except Exception as de:
            log_error(f"[DLL诊断] ASCII短路径测试出错: {type(de).__name__}: {de}")

        log_error("[DLL诊断] ===== 诊断结束 =====")

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
            self._log_dll_diagnostics(exc)
            self.errorOccurred.emit(
                f"libmpv 内核加载失败（详见 log 目录日志）。\n{exc}"
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
