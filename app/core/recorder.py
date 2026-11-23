"""IPTV 定时录制：多任务并发、无界面 libmpv stream-record、停止/取消/重试。"""

from __future__ import annotations

import os
import re
import shutil
import time
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Signal, QTimer

from .iptv_store import RecordStore, new_task_id
from .logger import log_error, log_info, record_logger
from .models import Channel, RecordTask, TaskStatus
from .settings import AppSettings, ensure_bin_path

_ILLEGAL = re.compile(r'[\\/:*?"<>|]')
_MIN_FREE_BYTES = 200 * 1024 * 1024


def sanitize(text: str) -> str:
    return _ILLEGAL.sub("_", (text or "").strip()).replace("\n", " ").replace("\r", " ")


def compact_time(value: str) -> str:
    """yyyy-MM-dd HH:mm -> yyyyMMddHHmm"""
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").strftime("%Y%m%d%H%M")
    except (TypeError, ValueError):
        return re.sub(r"\D", "", value or "")[:12].ljust(12, "0")


def parse_time(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def source_extension(url: str) -> str:
    path = urlparse(url or "").path.lower()
    if path.endswith((".m3u8", ".m3u")):
        return "ts"
    for ext in ("mp4", "ts", "mkv", "flv", "avi", "mov", "webm"):
        if path.endswith("." + ext):
            return ext
    return "ts"


def build_output_name(task: RecordTask, ts: int, ext: str) -> str:
    name = (
        f"{sanitize(task.channel)}-{sanitize(task.content)}-"
        f"{compact_time(task.start_time)}-{compact_time(task.end_time)}-{ts}.{ext}"
    )
    return name


class Recorder(QObject):
    taskChanged = Signal(str)
    tasksChanged = Signal()
    message = Signal(str)

    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._store = RecordStore()
        self._tasks: List[RecordTask] = self._store.load_tasks()
        self._instances: Dict[str, object] = {}
        self._retry_count: Dict[str, int] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._restore()

    # ---------- 查询 ----------
    @property
    def tasks(self) -> List[RecordTask]:
        return self._tasks

    def find(self, task_id: str) -> Optional[RecordTask]:
        return next((item for item in self._tasks if item.id == task_id), None)

    # ---------- 任务管理 ----------
    def add_task(
        self,
        channel: Channel,
        content: str,
        start_time: str,
        end_time: str,
        directory: str,
        record_format: str,
    ) -> tuple[Optional[RecordTask], str]:
        start = parse_time(start_time)
        end = parse_time(end_time)
        if start is None or end is None or end <= start:
            return None, "结束时间必须晚于开始时间"
        if not directory:
            directory = self._settings.record_dir
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            return None, f"录制目录不可写：{exc}"
        try:
            free = shutil.disk_usage(directory).free
            if free < _MIN_FREE_BYTES:
                return None, f"磁盘空间不足（剩余 {free // (1024 * 1024)} MB）"
        except OSError:
            pass
        task = RecordTask(
            id=new_task_id(), channel=channel.name, url=channel.url,
            content=sanitize(content) or "录制", start_time=start_time,
            end_time=end_time, created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            record_dir=directory,
            record_format=record_format or self._settings.record_format,
            status=TaskStatus.WAITING.value,
        )
        self._tasks.append(task)
        self._save()
        record_logger.info(
            f"创建任务 {task.id} | {task.channel} | {task.start_time} ~ {task.end_time} | {task.record_format}"
        )
        self.message.emit("录制任务已创建")
        return task, ""

    def update_task(self, task_id: str, **fields) -> str:
        task = self.find(task_id)
        if task is None:
            return "任务不存在"
        if task.status != TaskStatus.WAITING.value:
            return "只有等待中的任务可以编辑"
        for key in ("channel", "url", "content", "start_time", "end_time", "record_dir", "record_format"):
            if key in fields:
                setattr(task, key, fields[key])
        self._save()
        self.taskChanged.emit(task_id)
        return ""

    def remove_task(self, task_id: str) -> str:
        task = self.find(task_id)
        if task is None:
            return "任务不存在"
        if task.status == TaskStatus.RECORDING.value:
            return "录制中的任务请先停止或取消"
        self._tasks.remove(task)
        self._save()
        self.tasksChanged.emit()
        return ""

    def start_timer(self) -> None:
        self._timer.start()

    def stop_timer(self) -> None:
        self._timer.stop()

    # ---------- 调度 ----------
    def _restore(self) -> None:
        for task in self._tasks:
            if task.status == TaskStatus.RECORDING.value:
                task.status = TaskStatus.FAILED.value
                task.error = "程序中断"
                record_logger.warning(f"任务 {task.id} 因程序中断标记为失败")
        for task in self._tasks:
            end = parse_time(task.end_time)
            start = parse_time(task.start_time)
            now = datetime.now()
            if task.status == TaskStatus.WAITING.value and end and end <= now:
                task.status = TaskStatus.FAILED.value
                task.error = "任务已过期"
        self._save()

    def _tick(self) -> None:
        now = datetime.now()
        for task in list(self._tasks):
            start = parse_time(task.start_time)
            end = parse_time(task.end_time)
            if task.status == TaskStatus.WAITING.value and start and now >= start:
                if end and now >= end:
                    task.status = TaskStatus.FAILED.value
                    task.error = "任务已过期"
                    self._notify(task)
                    continue
                self._launch(task)
            elif task.status == TaskStatus.RECORDING.value and end and now >= end:
                self.stop_task(task.id, user=False)

    def _launch(self, task: RecordTask, retry: bool = False) -> None:
        if task.id in self._instances:
            return
        try:
            ensure_bin_path()
            import mpv  # type: ignore
        except Exception as exc:
            task.status = TaskStatus.FAILED.value
            task.error = f"缺少 libmpv-2.dll：{exc}"
            self._notify(task)
            return
        fmt = task.record_format
        ext = source_extension(task.url) if fmt == "source" else fmt
        stamp = int(time.time())
        name = build_output_name(task, stamp, ext)
        if retry:
            base, dot, extension = name.rpartition(".")
            name = f"{base}_retry.{extension}"
        path = os.path.join(task.record_dir, name)
        try:
            instance = mpv.MPV(
                vo="null", ao="null",
                input_default_bindings=False, input_vo_keyboard=False,
                terminal=False, msg_level="all=warn",
                stream_record=path,
            )
            instance.register_event_callback(lambda event, t=task: self._on_record_event(t, event))
            instance.play(task.url)
        except Exception as exc:
            task.status = TaskStatus.FAILED.value
            task.error = str(exc)
            record_logger.error(f"任务 {task.id} 开录失败：{exc}")
            self._notify(task)
            return
        self._instances[task.id] = instance
        task.status = TaskStatus.RECORDING.value
        task.output = path
        task.started_ts = stamp
        task.actual_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        task.error = ""
        record_logger.info(
            f"开录 {task.id} | {task.channel} | {task.url} | {path}"
        )
        self._notify(task)
        self.message.emit(f"开始录制：{task.channel}")

    def stop_task(self, task_id: str, *, user: bool = True) -> str:
        """正常收尾：先清空 stream-record 让 muxer 写尾，再终止实例。"""
        task = self.find(task_id)
        if task is None:
            return "任务不存在"
        instance = self._instances.pop(task_id, None)
        if instance is not None:
            try:
                instance.stream_record = ""
            except Exception as exc:
                record_logger.warning(f"任务 {task_id} 写尾失败：{exc}")
            try:
                instance.terminate()
            except Exception:
                pass
        task.status = TaskStatus.COMPLETED.value
        task.stopped_ts = int(time.time())
        if task.output and os.path.isfile(task.output):
            task.size = os.path.getsize(task.output)
        record_logger.info(
            f"停止录制 {task_id} | {task.channel} | {'用户操作' if user else '到点自动'} | "
            f"{task.output} | {task.size} bytes"
        )
        self._notify(task)
        return ""

    def cancel_task(self, task_id: str) -> str:
        task = self.find(task_id)
        if task is None:
            return "任务不存在"
        if task.status not in (TaskStatus.WAITING.value, TaskStatus.RECORDING.value):
            return "当前状态不可取消"
        instance = self._instances.pop(task_id, None)
        if instance is not None:
            try:
                instance.terminate()
            except Exception:
                pass
        task.status = TaskStatus.CANCELLED.value
        task.error = "用户取消"
        record_logger.warning(f"取消录制 {task_id} | {task.channel}")
        self._notify(task)
        return ""

    def _on_record_event(self, task: RecordTask, event) -> None:
        """录制实例收到 end-file：仅处理非主动停止造成的断流。"""
        # python-mpv 1.x 的 MpvEvent 是字典封装，event/reason 需从 as_dict() 取，
        # 直接 getattr 会永远为空，导致断流后不会重连。
        data = event.as_dict() if hasattr(event, "as_dict") else {}
        name = data.get("event") or getattr(event, "event", "")
        if name != "end-file":
            return
        if task.status != TaskStatus.RECORDING.value:
            return
        if self.find(task.id) is not task:
            return
        self._instances.pop(task.id, None)
        reason = data.get("reason") or getattr(event, "reason", "")
        record_logger.warning(f"任务 {task.id} 检测到断流：{reason}")
        self._retry_if_needed(task)

    def _retry_if_needed(self, task: RecordTask) -> None:
        """录制中实例意外退出且未到结束时间时重连续录。"""
        if task.id in self._instances:
            return
        end = parse_time(task.end_time)
        if end is None or datetime.now() >= end:
            return
        count = self._retry_count.get(task.id, 0) + 1
        self._retry_count[task.id] = count
        if count > 10:
            task.status = TaskStatus.PARTIAL.value
            task.error = "重试次数超限，保留已录制片段"
            record_logger.error(f"任务 {task.id} 重试超限")
            self._notify(task)
            return
        record_logger.warning(
            f"任务 {task.id} 流中断，{self._settings.record_retry_interval}s 后重连（第 {count} 次）"
        )
        QTimer.singleShot(
            self._settings.record_retry_interval * 1000,
            lambda: self._launch(task, retry=True) if self.find(task.id) is task else None,
        )

    def shutdown(self) -> None:
        self.stop_timer()
        for task_id in list(self._instances):
            self.stop_task(task_id, user=False)

    # ---------- 内部 ----------
    def _notify(self, task: RecordTask) -> None:
        self._save()
        self.taskChanged.emit(task.id)

    def _save(self) -> None:
        self._store.save_tasks(self._tasks)
        self.tasksChanged.emit()
