"""截图执行器：单张、源图 NxM 缩略图、连续截图。不记忆保存目录。

全部截图均使用 mpv 输出的**源分辨率**画面，不做缩放或压缩；
内部统一以 PNG（无损）落地，输出文件也保持源图像素。
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from .logger import log_error, log_info, log_warning

ProgressFn = Callable[[int, int, str], None]
CancelFn = Callable[[], bool]


def _video_stem(player) -> str:
    """当前媒体的文件名（不含扩展名），用于截图命名前缀。"""
    path = str(player.property("path", "") or "")
    stem = os.path.splitext(os.path.basename(path))[0]
    return "".join(c for c in stem if c not in '\\/:*?"<>|').strip() or "video"


def _with_video_prefix(output: str, player) -> str:
    """确保输出文件名以视频名为前缀。"""
    directory, base = os.path.split(output)
    stem = _video_stem(player)
    if not base.startswith(stem + "_"):
        base = f"{stem}_{base}"
    return os.path.join(directory, base) if directory else base


_TIMESTAMP_RE = re.compile(r"^\d{8}-\d{6}$")
_STAMP_FMT = "%Y%m%d-%H%M%S"


def _stamp() -> str:
    """截图时间戳（截图执行时刻），统一格式 YYYYMMDD-HHMMSS。"""
    return datetime.now().strftime(_STAMP_FMT)


def _with_timestamp(prefix: str) -> str:
    """在文件名前缀末尾加入时间戳；若已含时间戳则不重复添加。"""
    tail = prefix.rsplit("_", 1)[-1]
    if _TIMESTAMP_RE.match(tail):
        return prefix
    return f"{prefix}_{_stamp()}"


def _fmt_path(directory: str, prefix: str, index: int, fmt: str) -> str:
    ext = fmt.lower()
    stem = f"{prefix}_{index:04d}"
    base = os.path.join(directory, f"{stem}.{ext}")
    if not os.path.exists(base):
        return base
    n = 1
    while True:
        candidate = os.path.join(directory, f"{stem}_{n}.{ext}")
        if not os.path.exists(candidate):
            return candidate
        n += 1


def _pump(ms: int = 10) -> None:
    """让出执行权。后台线程里只 sleep，不触碰 GUI 事件循环。"""
    app = QApplication.instance()
    if app is not None and QThread.currentThread() == app.thread():
        app.processEvents()
    time.sleep(ms / 1000.0)


def _wait_seek(player, target: float, timeout: float = 2.0) -> float:
    """等待 seek 生效，避免截到旧帧。返回稳定后的实际时间位置。"""
    start = time.monotonic()
    actual = 0.0
    while time.monotonic() - start < timeout:
        _pump(10)
        try:
            actual = float(player.property("time-pos", 0) or 0)
        except Exception:
            actual = 0.0
        if abs(actual - target) <= 0.35:
            return actual
    _pump(30)
    log_warning(f"seek 未在 {timeout:.1f}s 内到位：目标 {target:.2f}s，实际 {actual:.2f}s")
    return actual


def _current_frame_interval(duration: float) -> float:
    """“当前时间点前后”取样时，按视频总时长决定相邻帧间隔（秒）。

    长片间隔大、短片间隔小：
      总时长 > 1h        -> 60s
      30min ~ 1h         -> 30s
      10min ~ 30min      -> 10s
      5min  ~ 10min      -> 5s
      < 5min             -> 1s
    """
    if duration > 3600:
        return 60.0
    if duration >= 1800:
        return 30.0
    if duration >= 600:
        return 10.0
    if duration >= 300:
        return 5.0
    return 1.0


def _frame_positions(
    duration: float, current: float, total: int, start_mode: str, window: float = 0.0
) -> List[float]:
    """参考缩略图找图逻辑：在取样范围内均匀取 total 个时间点。"""
    if duration <= 0:
        return [max(0.0, current)] * total
    if start_mode == "current":
        span = window if window > 0 else float(total)
        start = max(0.0, current - span)
        end = min(duration, current + span)
        if end - start < 1e-3:
            start, end = max(0.0, current - total), min(duration, current + total)
    else:  # all / begin：全片均匀
        start, end = 0.0, duration
    if end <= start:
        return [start] * total
    return [start + (end - start) * ((i + 0.5) / total) for i in range(total)]


def _capture_source_frame(player, path: str, include_subtitles: bool) -> bool:
    """以源分辨率、PNG 无损截取一帧。

    mpv 的 screenshot-to-file 是异步落盘的：命令返回时文件可能尚未出现，
    因此这里轮询等待文件生成并写入完成，避免连续截图误判为失败。
    """
    # 先清理可能存在的旧/残留文件，避免误判上一次的落盘结果
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    mode = "subtitles" if include_subtitles else "video"
    accepted = player.screenshot(path, include_subtitles)
    if not accepted:
        log_error(f"截图命令被拒绝：mode={mode} path={path}")
        return False
    deadline = time.monotonic() + 5.0
    last_size = -1
    stable = 0
    while time.monotonic() < deadline:
        _pump(20)
        try:
            if os.path.isfile(path):
                size = os.path.getsize(path)
                if size > 0 and size == last_size:
                    stable += 1
                    if stable >= 2:
                        return True
                else:
                    stable = 0
                last_size = size
        except OSError:
            pass
    return False


def _insert_timestamp(path: str) -> str:
    """在文件名（扩展名前）加入截图时间戳，已含则不重复。"""
    directory, base = os.path.split(path)
    stem, ext = os.path.splitext(base)
    if not _TIMESTAMP_RE.match(stem.rsplit("_", 1)[-1]):
        stem = f"{stem}_{_stamp()}"
    candidate = os.path.join(directory, stem + (ext or ".png"))
    # 避免覆盖同名文件
    if not os.path.exists(candidate):
        return candidate
    n = 1
    while True:
        alt = os.path.join(directory, f"{stem}_{n}{ext or '.png'}")
        if not os.path.exists(alt):
            return alt
        n += 1


def single_snapshot(player, path: str, include_subtitles: bool = True) -> str:
    """单张源图截图，成功时返回实际保存路径（含时间戳），失败返回空串。"""
    if not path:
        return ""
    # 强制 PNG 无损、源分辨率，并在文件名中加入截图时间戳
    path = _insert_timestamp(path)
    root, ext = os.path.splitext(path)
    path = root + ".png" if ext.lower() != ".png" else path
    ok = player.screenshot(path, include_subtitles)
    if ok:
        log_info(f"单张截图（源图）：{path}")
        return path
    return ""


def build_thumbnail(
    player,
    output: str,
    columns: int,
    rows: int,
    frame_width: int,
    sample_range: str,
    fmt: str,
    progress: ProgressFn,
    cancelled: CancelFn,
    include_subtitles: bool = True,
) -> Tuple[bool, str]:
    """用源分辨率画面拼成 NxM 缩略图；输出文件名自动加视频名前缀。"""
    total = max(1, columns) * max(1, rows)
    duration = float(player.property("duration", 0) or 0)
    current = float(player.property("time-pos", 0) or 0)
    if duration <= 0:
        return False, "媒体时长未知，无法生成缩略图"

    output = _with_video_prefix(output, player)
    # 文件名统一加截图时间戳（若用户已填则保持）
    out_dir, out_base = os.path.split(output)
    out_stem, out_ext = os.path.splitext(out_base)
    output = os.path.join(out_dir, _with_timestamp(out_stem) + (out_ext or ".png"))
    # “当前时间点前后”：相邻帧间隔按视频总时长分档，长片间隔大、短片间隔小，
    # 既避免取样点挤在一起，也保证短视频仍有足够取样范围。
    window = 0.0
    if sample_range == "current":
        interval = _current_frame_interval(duration)
        window = min(float(total) * interval / 2.0, duration)
    positions = _frame_positions(duration, current, total, sample_range, window)

    was_paused = bool(player.property("pause", True))
    player.pause(True)
    frames: List[Tuple[str, float]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="cxp_thumb_") as tmp:
            for i, target in enumerate(positions):
                if cancelled():
                    return False, "已取消"
                player.seek(target, absolute=True)
                _wait_seek(player, target)
                frame_path = os.path.join(tmp, f"f{i:04d}.png")
                if _capture_source_frame(player, frame_path, include_subtitles):
                    frames.append((frame_path, target))
                progress(i + 1, total, "正在截取源图")
            if not frames:
                return False, "没有成功截取任何帧"

            sample = QImage(frames[0][0])
            if sample.isNull():
                return False, "读取源图失败"
            # 使用源图原始分辨率作为单元格，不做任何缩放
            fw, fh = sample.width(), sample.height()
            sheet = QImage(fw * columns, fh * rows, QImage.Format.Format_RGB32)
            sheet.fill(QColor("#000000"))
            painter = QPainter(sheet)
            font = QFont("Microsoft YaHei", max(12, int(fh * 0.05)))
            painter.setFont(font)
            label_h = max(26, int(fh * 0.09))
            for index, (frame_path, stamp) in enumerate(frames):
                col, row = index % columns, index // columns
                x, y = col * fw, row * fh
                frame = QImage(frame_path)
                if not frame.isNull():
                    if frame.width() == fw and frame.height() == fh:
                        painter.drawImage(x, y, frame)
                    else:
                        scaled = frame.scaled(fw, fh, Qt.AspectRatioMode.IgnoreAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation)
                        painter.drawImage(x, y, scaled)
                # 时间标签叠加在单元底部，不缩放源图
                stamp_i = int(stamp)
                text = f"{stamp_i // 3600:02d}:{(stamp_i % 3600) // 60:02d}:{stamp_i % 60:02d}"
                painter.fillRect(x, y + fh - label_h, fw, label_h, QColor(0, 0, 0, 150))
                painter.setPen(QColor("#dbeafe"))
                painter.drawText(x, y + fh - label_h, fw, label_h,
                                 Qt.AlignmentFlag.AlignCenter, text)
            painter.end()
            parent = os.path.dirname(output)
            if parent:
                os.makedirs(parent, exist_ok=True)
            # PNG 无损输出；即便用户选了 jpg/webp 也改用 PNG，保证不压缩
            output = os.path.splitext(output)[0] + ".png"
            if not sheet.save(output, "PNG"):
                return False, "保存缩略图失败"
            log_info(f"源图缩略图：{output}（{columns}x{rows}，{fw}x{fh}/格）")
            return True, output
    except Exception as exc:
        log_error(f"thumbnail failed: {exc}")
        return False, str(exc)
    finally:
        if not was_paused:
            player.pause(False)


def continuous_snapshots(
    player,
    directory: str,
    prefix: str,
    start_mode: str,
    interval_mode: str,
    interval: float,
    limit_count: int,
    fmt: str,
    progress: ProgressFn,
    cancelled: CancelFn,
    include_subtitles: bool = True,
) -> Tuple[int, int]:
    """连续源图截图：找图逻辑与缩略图一致（均匀取样 + 等待 seek）。

    返回 (成功数, 失败数)。每次操作只选择一次目录；文件名以视频名开头。
    """
    os.makedirs(directory, exist_ok=True)
    duration = float(player.property("duration", 0) or 0)
    current = float(player.property("time-pos", 0) or 0)
    maximum = max(1, int(limit_count)) if limit_count > 0 else 9999

    # 视频名前缀 + 用户自定义前缀
    video = _video_stem(player)
    prefix = f"{video}_{prefix}" if prefix and not prefix.startswith(video + "_") else (prefix or video)
    # 每批连续截图带同一个截图时间戳，避免与其它批次重名
    prefix = _with_timestamp(prefix)

    # 与缩略图一致的均匀取样；begin=全片，current=当前时间点前后
    window = max(0.0, float(interval)) * maximum if interval_mode == "time" else 0.0
    positions = _frame_positions(duration, current, maximum, start_mode, window)

    log_info(f"连续截图开始：{maximum} 张 -> {directory}")

    was_paused = bool(player.property("pause", True))
    player.pause(True)
    ok_count, fail_count, taken = 0, 0, 0
    try:
        with tempfile.TemporaryDirectory(prefix="cxp_cont_") as tmp:
            for target in positions:
                if cancelled() or taken >= maximum:
                    break
                player.seek(target, absolute=True)
                _wait_seek(player, target)
                source = os.path.join(tmp, f"f{taken:04d}.png")
                if not _capture_source_frame(player, source, include_subtitles):
                    fail_count += 1
                    taken += 1
                    progress(taken, maximum, "正在截取源图")
                    continue
                final = _fmt_path(directory, prefix, taken + 1, "png")
                # 临时目录通常在 C: 用户目录，导出目录可能在 D:/U 盘等其它卷，
                # os.replace 跨卷会抛 OSError，必须先复制到目标卷再重命名。
                try:
                    shutil.copyfile(source, final + ".part")
                    os.replace(final + ".part", final)
                    ok_count += 1
                except OSError as exc:
                    fail_count += 1
                    log_error(f"连续截图保存失败：{final} 错误={exc}")
                    try:
                        if os.path.exists(final + ".part"):
                            os.remove(final + ".part")
                    except OSError:
                        pass
                taken += 1
                progress(taken, maximum, "正在截取源图")
        log_info(f"连续截图完成：成功 {ok_count} / 失败 {fail_count}")
        return ok_count, fail_count
    except Exception as exc:
        log_error(f"连续截图异常：{exc}")
        return ok_count, fail_count + 1
    finally:
        if not was_paused:
            player.pause(False)


class SnapshotWorker(QThread):
    """把截图任务放到后台线程，UI 只通过信号更新进度，避免拼接时卡顿。

    task 是一个可调用对象，签名为 task(progress_fn, cancelled_fn) -> (ok, message)。
    libmpv 的 command / 属性读取均为线程安全；此线程不触碰任何 QWidget。
    """

    progress = Signal(int, int, str)
    finished = Signal(bool, str)

    def __init__(self, task, parent=None) -> None:
        super().__init__(parent)
        self._task = task
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # noqa: N802
        def _progress(current: int, total: int, message: str) -> None:
            self.progress.emit(current, total, message)

        try:
            ok, message = self._task(_progress, lambda: self._cancelled)
        except Exception as exc:  # noqa: BLE001
            log_error(f"snapshot worker failed: {exc}")
            ok, message = False, str(exc)
        self.finished.emit(bool(ok), str(message or ""))
