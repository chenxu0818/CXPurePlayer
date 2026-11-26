"""IPTV 定时录制：多任务并发、无界面 libmpv stream-record、停止/取消/重试。"""

from __future__ import annotations

import os
import re
import shutil
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Signal, QTimer

from . import ffmpeg_recorder
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


def parse_hhmm(value: str) -> Optional[Tuple[int, int]]:
    """HH:mm -> (hour, minute)。"""
    try:
        parts = str(value).split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
        return None
    except (ValueError, IndexError, TypeError):
        return None


def _at(day: date, hhmm: Tuple[int, int]) -> datetime:
    return datetime(day.year, day.month, day.day, hhmm[0], hhmm[1])


def _window(day: date, hs: Tuple[int, int], he: Tuple[int, int]) -> Tuple[datetime, datetime]:
    """某天的录制窗口；结束 <= 开始时视为跨午夜（次日结束）。"""
    start = _at(day, hs)
    end = _at(day, he)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _selected_day(
    frequency: str,
    day: date,
    base: date,
    weekdays: str,
    custom_dates: str,
) -> bool:
    """日期 day 是否匹配循环规则。base 是规则生效起始日。"""
    if frequency == "daily":
        # 允许 base 前一天：跨午夜窗口可能从前一天开始、今天结束。
        return day >= base - timedelta(days=1)
    if frequency == "weekly":
        try:
            wanted = {int(x) for x in str(weekdays).split(",") if x.strip() != ""}
        except ValueError:
            return False
        return day.weekday() in wanted
    if frequency == "custom":
        selected = set()
        for token in str(custom_dates).split(","):
            token = token.strip()
            if not token:
                continue
            parsed = parse_time(token + " 00:00")
            if parsed is not None:
                selected.add(parsed.date())
        return day in selected
    return False


def next_occurrence(
    frequency: str,
    day: date,
    hhmm_start: Tuple[int, int],
    hhmm_end: Tuple[int, int],
    weekdays: str = "",
    custom_dates: str = "",
    after: Optional[datetime] = None,
) -> Optional[Tuple[datetime, datetime]]:
    """计算 >= after 的下一次录制窗口（开始、结束 datetime）。

    - once：按 day 的 hhmm 生成一次；若已过 after 则返回 None（单次不重排）。
    - daily：从 day 起逐日尝试，找到开始时刻 >= after 的那天。
    - weekly：在 weekdays（0=周一..6=周日）中找 >= after 的最近一个匹配日。
    - custom：从 custom_dates 中找开始时刻 >= after 的最近一个日期。
    """
    reference = after or datetime.now()
    if frequency == "once":
        start, end = _window(day, hhmm_start, hhmm_end)
        return (start, end) if start >= reference else None

    if frequency in ("daily", "weekly", "custom"):
        # 通常最多向后看 366 天；weekly/custom 用有限集合避免无规则时死循环。
        limit = 366 if frequency == "daily" else (14 if frequency == "weekly" else 0)
        if frequency == "custom":
            candidates: List[date] = []
            for token in str(custom_dates).split(","):
                token = token.strip()
                parsed = parse_time(token + " 00:00") if token else None
                if parsed is not None:
                    candidates.append(parsed.date())
            days = sorted(d for d in set(candidates) if _selected_day(
                frequency, d, day, weekdays, custom_dates
            ))
        else:
            days = [day + timedelta(days=offset) for offset in range(limit)]
        for d in days:
            if not _selected_day(frequency, d, day, weekdays, custom_dates):
                continue
            start, end = _window(d, hhmm_start, hhmm_end)
            if start >= reference:
                return start, end
    return None


def active_occurrence(
    frequency: str,
    day: date,
    hhmm_start: Tuple[int, int],
    hhmm_end: Tuple[int, int],
    weekdays: str = "",
    custom_dates: str = "",
    now: Optional[datetime] = None,
) -> Optional[Tuple[datetime, datetime]]:
    """返回当前时刻正处于其中的录制窗口；用于新建任务立即开录。

    只处理 daily / weekly / custom；匹配规则要求当天（或跨午夜时起始日）
    确实在循环配置里。窗口开始时刻可以早于当前时刻，结束保持计划时刻。
    """
    if frequency not in ("daily", "weekly", "custom"):
        return None
    reference = now or datetime.now()
    candidates = [reference.date(), reference.date() - timedelta(days=1)]
    for d in dict.fromkeys(candidates):
        if not _selected_day(frequency, d, day, weekdays, custom_dates):
            continue
        start, end = _window(d, hhmm_start, hhmm_end)
        if start <= reference < end:
            return start, end
    return None


def format_dt(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


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
        self._backend: Dict[str, str] = {}
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
        frequency: str = "once",
        weekdays: str = "",
        custom_dates: str = "",
        time_start: str = "",
        time_end: str = "",
    ) -> tuple[Optional[RecordTask], str]:
        start = parse_time(start_time)
        end = parse_time(end_time)
        frequency = frequency or "once"
        if frequency == "once":
            if start is None or end is None or end <= start:
                return None, "结束时间必须晚于开始时间"
        else:
            # 循环任务：以 HH:mm 规则计算第一个具体窗口，start_time/end_time 由对话框
            # 已填好；这里再校验规则有效，确保持久化后仍可重排下一次。
            hs = parse_hhmm(time_start)
            he = parse_hhmm(time_end)
            if hs is None or he is None:
                return None, "循环任务需要有效的开始/结束时间（时分）"
            if start is None or end is None:
                return None, "时间格式无效"
            if frequency == "weekly" and not any(
                x.strip() for x in (weekdays or "").split(",")
            ):
                return None, "请至少选择一个星期几"
            if frequency == "custom" and not any(
                x.strip() for x in (custom_dates or "").split(",")
            ):
                return None, "请至少选择一个日期"
        if not directory:
            directory = self._settings.record_dir
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            return None, f"录制目录不可写：{exc}"
        try:
            free = shutil.disk_usage(directory).free
            if free < _MIN_FREE_BYTES:
                return None, f"磁盘空间不足（剩余 {free / (1024 ** 3):.1f} GB）"
        except OSError:
            pass
        task = RecordTask(
            id=new_task_id(), channel=channel.name, url=channel.url,
            content=sanitize(content) or "录制", start_time=start_time,
            end_time=end_time, created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            record_dir=directory,
            record_format=record_format or self._settings.record_format,
            status=TaskStatus.WAITING.value,
            frequency=frequency, weekdays=weekdays, custom_dates=custom_dates,
            time_start=time_start, time_end=time_end,
        )
        self._tasks.append(task)
        self._save()
        record_logger.info(
            f"创建任务 {task.id} | {task.channel} | 频率={frequency} | "
            f"{task.start_time} ~ {task.end_time} | {task.record_format}"
        )
        self.message.emit("录制任务已创建")
        return task, ""

    def _reschedule(self, task: RecordTask) -> bool:
        """循环任务在完成一次后计算下一次窗口；返回是否成功重排。

        单次任务返回 False（保持完成态）。周/自定义任务若已无后续日期，返回 False
        表示任务全部完成。重排后写入新的 start_time/end_time 并复位为等待中。
        """
        if task.frequency == "once":
            return False
        hs = parse_hhmm(task.time_start)
        he = parse_hhmm(task.time_end)
        start = parse_time(task.start_time)
        if hs is None or he is None or start is None:
            return False
        # 从当前窗口的下一天开始找，避免重复匹配同一天
        base = start.date() + timedelta(days=1)
        window = next_occurrence(
            task.frequency, base, hs, he, task.weekdays, task.custom_dates,
            after=datetime.now(),
        )
        if window is None:
            return False
        task.start_time = format_dt(window[0])
        task.end_time = format_dt(window[1])
        task.status = TaskStatus.WAITING.value
        task.output = ""
        task.started_ts = 0
        task.stopped_ts = 0
        task.size = 0
        task.error = ""
        task.run_index = int(task.run_index or 0) + 1
        return True

    def _spawn_next_task(self, task: RecordTask, now: datetime) -> Optional[RecordTask]:
        """为错过的循环任务生成下一次等待任务；原任务保留为失败记录。"""
        hs = parse_hhmm(task.time_start)
        he = parse_hhmm(task.time_end)
        start = parse_time(task.start_time)
        if hs is None or he is None or start is None:
            return None
        window = next_occurrence(
            task.frequency, start.date() + timedelta(days=1), hs, he,
            task.weekdays, task.custom_dates, after=now,
        )
        if window is None:
            return None
        follow = RecordTask(
            id=new_task_id(), channel=task.channel, url=task.url,
            content=task.content, start_time=format_dt(window[0]),
            end_time=format_dt(window[1]),
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            record_dir=task.record_dir, record_format=task.record_format,
            status=TaskStatus.WAITING.value, frequency=task.frequency,
            weekdays=task.weekdays, custom_dates=task.custom_dates,
            time_start=task.time_start, time_end=task.time_end,
            run_index=int(task.run_index or 0) + 1,
        )
        self._tasks.append(follow)
        return follow

    def _expire_waiting(self, task: RecordTask, now: datetime, reason: str = "任务已过期") -> None:
        """等待任务已错过整个窗口：本次标记失败，循环任务续接下一次。"""
        task.status = TaskStatus.FAILED.value
        task.error = reason
        task.output = ""
        follow = None
        if task.frequency != "once":
            follow = self._spawn_next_task(task, now)
        if follow is not None:
            task.error = f"{reason}，已顺延至新任务"
            record_logger.info(
                f"任务 {task.id} 已过期，下一次 {follow.start_time} 由新任务 {follow.id} 承接"
            )
        else:
            record_logger.warning(f"任务 {task.id} 已过期：{reason}")
        self._notify(task)

    def update_task(self, task_id: str, **fields) -> str:
        task = self.find(task_id)
        if task is None:
            return "任务不存在"
        if task.status != TaskStatus.WAITING.value:
            return "只有等待中的任务可以编辑"
        for key in (
            "channel", "url", "content", "start_time", "end_time", "record_dir",
            "record_format", "frequency", "weekdays", "custom_dates", "time_start", "time_end",
        ):
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
        # 启动时立即检查一次：恢复出来的任务若仍在录制时段内，立刻开录，
        # 不必等第一个 1 秒 tick。
        self._tick()
        self._timer.start()

    def stop_timer(self) -> None:
        self._timer.stop()

    # ---------- 调度 ----------
    def _restore(self) -> None:
        for task in list(self._tasks):
            if task.status == TaskStatus.RECORDING.value:
                task.status = TaskStatus.FAILED.value
                task.error = "程序中断"
                record_logger.warning(f"任务 {task.id} 因程序中断标记为失败")
        now = datetime.now()
        for task in list(self._tasks):
            if task.status != TaskStatus.WAITING.value:
                continue
            start = parse_time(task.start_time)
            end = parse_time(task.end_time)
            if start is None or end is None:
                if start is not None and start <= now:
                    self._expire_waiting(task, now, "任务时间无效")
                continue
            if end <= now:
                # 本次窗口已完整错过：标记失败，循环任务续接新的等待任务。
                self._expire_waiting(task, now)
            # start <= now < end 的任务保持等待，start_timer() 会立即开录。
        self._save()

    def _tick(self) -> None:
        now = datetime.now()
        for task in list(self._tasks):
            start = parse_time(task.start_time)
            end = parse_time(task.end_time)
            if task.status == TaskStatus.WAITING.value and start and now >= start:
                if end is None:
                    self._expire_waiting(task, now, "任务时间无效")
                    continue
                if now >= end:
                    # 本次窗口已完整错过：失败记录 + 循环任务续接新任务。
                    self._expire_waiting(task, now)
                    continue
                self._launch(task)
            elif task.status == TaskStatus.RECORDING.value and end and now >= end:
                self.stop_task(task.id, user=False)

    def _launch(self, task: RecordTask, retry: bool = False) -> None:
        if task.id in self._instances:
            return
        fmt = task.record_format
        ext = source_extension(task.url) if fmt == "source" else fmt
        stamp = int(time.time())
        name = build_output_name(task, stamp, ext)
        if retry:
            base, dot, extension = name.rpartition(".")
            name = f"{base}_retry.{extension}"
        path = os.path.join(task.record_dir, name)

        # 首选 ffmpeg 整流复制：-map 0 保留全部音轨（解决双音轨只录一个的问题）。
        # 仅当系统没有 ffmpeg 时才回退到 libmpv stream-record（只录选中音轨）。
        use_ffmpeg = ffmpeg_recorder.has_ffmpeg()
        instance = None
        if use_ffmpeg:
            instance = ffmpeg_recorder.spawn(task.url, path)
        if instance is None:
            # 回退：libmpv stream-record
            use_ffmpeg = False
            try:
                ensure_bin_path()
                import mpv  # type: ignore
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
        # 记录使用的录制后端，供停止/断流判定使用
        self._backend[task.id] = "ffmpeg" if use_ffmpeg else "mpv"
        task.status = TaskStatus.RECORDING.value
        task.output = path
        task.started_ts = stamp
        task.actual_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        task.error = ""
        record_logger.info(
            f"开录 {task.id} | {task.channel} | 后端={'ffmpeg(全音轨)' if use_ffmpeg else 'libmpv'} | "
            f"{task.url} | {path}"
        )
        if use_ffmpeg:
            # ffmpeg 无事件回调，用定时器监控进程意外退出（断流重连）
            QTimer.singleShot(2000, lambda: self._monitor_ffmpeg(task))
        self._notify(task)
        self.message.emit(f"开始录制：{task.channel}")

    def _monitor_ffmpeg(self, task: RecordTask) -> None:
        """ffmpeg 后端：进程意外退出且未到结束时间时重连；到点由 _tick 收尾。"""
        instance = self._instances.get(task.id)
        if instance is None or self._backend.get(task.id) != "ffmpeg":
            return
        if task.status != TaskStatus.RECORDING.value:
            return
        exit_code = getattr(instance, "poll", lambda: None)()
        if exit_code is None:
            # 仍在录制，2 秒后再查
            QTimer.singleShot(2000, lambda: self._monitor_ffmpeg(task))
            return
        # 进程已退出：若非主动停止（主动 stopping 会先 pop 实例），视为断流
        end = parse_time(task.end_time)
        if end is None or datetime.now() >= end:
            return
        record_logger.warning(f"任务 {task.id} ffmpeg 进程退出(code={exit_code})，触发断流重连")
        self._instances.pop(task.id, None)
        self._retry_if_needed(task)

    def stop_task(self, task_id: str, *, user: bool = True) -> str:
        """正常收尾：先清空 stream-record 让 muxer 写尾，再终止实例。"""
        task = self.find(task_id)
        if task is None:
            return "任务不存在"
        instance = self._instances.pop(task_id, None)
        if instance is not None:
            if self._backend.get(task_id) == "ffmpeg":
                ffmpeg_recorder.stop(instance)
            else:
                try:
                    instance.stream_record = ""
                except Exception as exc:
                    record_logger.warning(f"任务 {task_id} 写尾失败：{exc}")
                try:
                    instance.terminate()
                except Exception:
                    pass
        self._backend.pop(task_id, None)
        task.status = TaskStatus.COMPLETED.value
        task.stopped_ts = int(time.time())
        if task.output and os.path.isfile(task.output):
            task.size = os.path.getsize(task.output)
        record_logger.info(
            f"停止录制 {task_id} | {task.channel} | {'用户操作' if user else '到点自动'} | "
            f"{task.output} | {task.size} bytes"
        )
        # 循环任务完成本次后自动顺延到下一次；单次任务保持已完成。
        if self._reschedule(task):
            record_logger.info(
                f"任务 {task_id} 为循环任务，已重排下一次至 {task.start_time}"
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
            if self._backend.get(task_id) == "ffmpeg":
                ffmpeg_recorder.stop(instance)
            else:
                try:
                    instance.terminate()
                except Exception:
                    pass
        self._backend.pop(task_id, None)
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
