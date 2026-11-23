"""双日志：常规日志与录制日志按天分片，各自清理 30 天前文件。

常规日志：log/yyyy-MM-dd.log
录制日志：log/yyyy-MM-dd-record.log
录制相关模块只允许调用 record_logger，避免长时录制刷爆常规日志。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from .settings import app_root

_LOG_DIR = os.path.join(app_root(), "log")
_RETENTION_DAYS = 30


class _DailyFileHandler(logging.FileHandler):
    """按本地日期自动切换文件的处理器，文件名严格使用 yyyy-MM-dd[-record].log。"""

    def __init__(self, suffix: str) -> None:
        self._suffix = suffix
        self._day = datetime.now().date()
        filename = self._path_for(self._day)
        super().__init__(filename, encoding="utf-8", delay=False)
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        )

    def _path_for(self, day) -> str:
        return os.path.join(_LOG_DIR, f"{day:%Y-%m-%d}{self._suffix}.log")

    def emit(self, record: logging.LogRecord) -> None:
        today = datetime.now().date()
        if today != self._day:
            self.close()
            self._day = today
            self.baseFilename = self._path_for(today)
            self.stream = self._open()
        super().emit(record)


def _make_logger(name: str, suffix: str) -> logging.Logger:
    os.makedirs(_LOG_DIR, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        logger.addHandler(_DailyFileHandler(suffix))
    return logger


def _cleanup() -> None:
    cutoff = datetime.now() - timedelta(days=_RETENTION_DAYS)
    try:
        for name in os.listdir(_LOG_DIR):
            if not name.endswith(".log"):
                continue
            path = os.path.join(_LOG_DIR, name)
            try:
                if os.path.getmtime(path) < cutoff.timestamp():
                    os.remove(path)
            except OSError:
                pass
    except OSError:
        pass


app_logger = _make_logger("cxpureplayer.app", "")
record_logger = _make_logger("cxpureplayer.record", "-record")


def init_loggers() -> None:
    """启动时调用一次，清理过期日志。"""
    _cleanup()


def log_info(message: str, *, record: bool = False) -> None:
    (record_logger if record else app_logger).info(message)


def log_warning(message: str, *, record: bool = False) -> None:
    (record_logger if record else app_logger).warning(message)


def log_error(message: str, *, record: bool = False) -> None:
    (record_logger if record else app_logger).error(message)


def log_exception(message: str, *, record: bool = False) -> None:
    (record_logger if record else app_logger).exception(message)
