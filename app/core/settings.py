"""应用配置：ini 持久化、路径解析、录制目录回退。"""

from __future__ import annotations

import hashlib
import os
import sys
import time

from PySide6.QtCore import QSettings

from ..version import APP_NAME
from .theme import DEFAULT_THEME


def app_root() -> str:
    """源码模式返回项目根目录；打包模式返回 EXE 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resource_root() -> str:
    """只读资源目录：打包后位于 _MEIPASS。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", app_root())
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def ensure_bin_path() -> str:
    """把随包 bin 目录加入 PATH / DLL 搜索路径，使 python-mpv 能找到 libmpv-2.dll。

    Windows 上 Python 3.8+ 除 PATH 外还需 os.add_dll_directory()；
    打包模式下同时兼容 _MEIPASS（解压目录）与 EXE 同目录 bin。
    """
    primary = os.path.join(resource_root(), "bin")
    candidates = [primary]
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(app_root(), "bin"))
    current = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    for directory in candidates:
        if not os.path.isdir(directory):
            continue
        if os.path.normcase(directory) not in {os.path.normcase(p) for p in current}:
            os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
            current.append(directory)
        if os.name == "nt":
            try:
                os.add_dll_directory(directory)  # type: ignore[attr-defined]
            except Exception:
                pass
    return primary


def _writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


def default_record_dir() -> str:
    """录制默认目录：<APP_ROOT>/record；不可写时回退 LOCALAPPDATA。"""
    primary = os.path.join(app_root(), "record")
    if _writable(primary):
        return primary
    fallback = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_NAME, "record"
    )
    _writable(fallback)
    return fallback


class AppSettings:
    """QSettings(ini) 封装，全部键集中在此。"""

    DEFAULTS = {
        "language": "zh_CN",
        "theme": DEFAULT_THEME,
        "ui_scale_mode": "auto",
        "ui_scale": 100,
        "seek_step": 10,
        "volume": 100,
        "remember_position": False,
        "repeat_mode": "normal",
        "screenshot_format": "png",
        "subtitle_size": 20,
        "record_dir": "",
        "record_format": "source",
        "record_retry_interval": 30,
        "osd_auto_hide": False,
    }

    def __init__(self) -> None:
        self._q = QSettings(os.path.join(app_root(), "settings.ini"), QSettings.Format.IniFormat)

    def get(self, key: str, default=None):
        fallback = self.DEFAULTS.get(key, default) if default is None else default
        return self._q.value(key, fallback)

    def set(self, key: str, value) -> None:
        self._q.setValue(key, value)
        self._q.sync()

    # --- 常用属性 ---
    @property
    def language(self) -> str:
        return str(self.get("language", "zh_CN"))

    @language.setter
    def language(self, value: str) -> None:
        self.set("language", value)

    @property
    def theme(self) -> str:
        return str(self.get("theme", DEFAULT_THEME))

    @theme.setter
    def theme(self, value: str) -> None:
        self.set("theme", value)

    @property
    def ui_scale_mode(self) -> str:
        return str(self.get("ui_scale_mode", "auto"))

    @ui_scale_mode.setter
    def ui_scale_mode(self, value: str) -> None:
        self.set("ui_scale_mode", value)

    @property
    def ui_scale(self) -> int:
        try:
            return int(self.get("ui_scale", 100))
        except (TypeError, ValueError):
            return 100

    @ui_scale.setter
    def ui_scale(self, value: int) -> None:
        self.set("ui_scale", int(value))

    @property
    def seek_step(self) -> int:
        try:
            value = int(self.get("seek_step", 10))
        except (TypeError, ValueError):
            return 10
        return value if value in (5, 10, 30, 60) else 10

    @seek_step.setter
    def seek_step(self, value: int) -> None:
        self.set("seek_step", int(value))

    # --- 记忆播放位置（按文件分别记录，30 天未播放自动过期） ---
    _POSITION_GROUP = "playbackPositions"
    POSITION_EXPIRE_DAYS = 30
    _POSITION_EXPIRE_SECONDS = POSITION_EXPIRE_DAYS * 86400

    @staticmethod
    def _parse_position(raw) -> tuple[float, int]:
        """解析位置值，兼容旧版纯秒数格式（无时间戳视为不过期）。"""
        text = str(raw or "")
        if "|" in text:
            pos_text, _, ts_text = text.partition("|")
            try:
                return max(0.0, float(pos_text)), int(float(ts_text))
            except (TypeError, ValueError):
                return 0.0, 0
        try:
            return max(0.0, float(text)), 0
        except (TypeError, ValueError):
            return 0.0, 0

    @staticmethod
    def _position_key(path: str) -> str:
        """用规范化路径的哈希作 ini 键，避免路径中的特殊字符破坏 ini 结构。"""
        normalized = os.path.normcase(os.path.abspath(path))
        return hashlib.sha1(normalized.encode("utf-8", "surrogateescape")).hexdigest()

    @property
    def remember_position(self) -> bool:
        return bool(self.get("remember_position", False))

    @remember_position.setter
    def remember_position(self, value: bool) -> None:
        self.set("remember_position", bool(value))

    def get_playback_position(self, path: str) -> float:
        """返回该文件上次播放位置（秒）；无记录、异常或已过期时返回 0。"""
        if not path:
            return 0.0
        key = self._position_key(path)
        self._q.beginGroup(self._POSITION_GROUP)
        try:
            raw = self._q.value(key, 0.0)
        finally:
            self._q.endGroup()
        value, ts = self._parse_position(raw)
        if value <= 0:
            return 0.0
        if ts > 0 and time.time() - ts > self._POSITION_EXPIRE_SECONDS:
            self.clear_playback_position(path)
            return 0.0
        return value

    def set_playback_position(self, path: str, seconds: float) -> None:
        """记录播放位置与最后播放时间；不足 1 秒的位置不记录。"""
        if not path:
            return
        try:
            value = round(max(0.0, float(seconds)), 2)
        except (TypeError, ValueError):
            return
        if value < 1.0:
            return
        self._q.beginGroup(self._POSITION_GROUP)
        try:
            self._q.setValue(self._position_key(path), f"{value:.2f}|{int(time.time())}")
        finally:
            self._q.endGroup()
        self._q.sync()

    def clear_playback_position(self, path: str) -> None:
        """清除单个文件的播放位置（播完时调用，下次从头开始）。"""
        if not path:
            return
        self._q.beginGroup(self._POSITION_GROUP)
        try:
            self._q.remove(self._position_key(path))
        finally:
            self._q.endGroup()
        self._q.sync()

    def purge_expired_positions(self) -> int:
        """启动时清理超过 POSITION_EXPIRE_DAYS 天未再播放的记录，返回清除条数。

        不能只靠打开时惰性判断——用户再也不打开的文件会永远留在 ini 里。
        """
        now = time.time()
        expired: list[str] = []
        self._q.beginGroup(self._POSITION_GROUP)
        try:
            for key in self._q.allKeys():
                _, ts = self._parse_position(self._q.value(key, 0.0))
                if ts > 0 and now - ts > self._POSITION_EXPIRE_SECONDS:
                    expired.append(key)
            for key in expired:
                self._q.remove(key)
        finally:
            self._q.endGroup()
        if expired:
            self._q.sync()
        return len(expired)

    @property
    def volume(self) -> int:
        try:
            return max(0, min(100, int(self.get("volume", 100))))
        except (TypeError, ValueError):
            return 100

    @volume.setter
    def volume(self, value: int) -> None:
        self.set("volume", int(value))

    @property
    def screenshot_format(self) -> str:
        value = str(self.get("screenshot_format", "png")).lower()
        return value if value in ("png", "jpg", "webp", "bmp") else "png"

    @screenshot_format.setter
    def screenshot_format(self, value: str) -> None:
        self.set("screenshot_format", value)

    @property
    def record_format(self) -> str:
        value = str(self.get("record_format", "source")).lower()
        return value if value in ("source", "ts", "mp4", "mkv") else "source"

    @record_format.setter
    def record_format(self, value: str) -> None:
        self.set("record_format", value)

    @property
    def record_dir(self) -> str:
        custom = str(self.get("record_dir", "") or "")
        if custom and _writable(custom):
            return custom
        return default_record_dir()

    @record_dir.setter
    def record_dir(self, value: str) -> None:
        self.set("record_dir", value)

    @property
    def record_retry_interval(self) -> int:
        try:
            return max(5, int(self.get("record_retry_interval", 30)))
        except (TypeError, ValueError):
            return 30

    @record_retry_interval.setter
    def record_retry_interval(self, value: int) -> None:
        self.set("record_retry_interval", int(value))
