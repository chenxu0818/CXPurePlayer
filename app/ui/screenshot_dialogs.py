"""截图设置对话框：缩略图拼图与连续截图，每次操作只选一次保存位置。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
)


def centered_spinbox(spin: QSpinBox, metrics) -> QSpinBox:
    """数字居中显示，并统一数字输入框宽度。"""
    spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
    spin.setFixedWidth(metrics.s(84))
    return spin

from ..core.i18n import tr
from ..core.screenshot import (
    SnapshotWorker, _video_stem, build_thumbnail, continuous_snapshots,
)
from ..core.settings import user_data_root
from .dialog_utils import centered_buttons, compact_button, get_existing_directory, get_save_file
from .widget_utils import auto_retranslate, mark_dynamic, set_window_icon, translate_standard_buttons

class _BaseSnapshotDialog(QDialog):
    def __init__(self, metrics, player, parent=None) -> None:
        super().__init__(parent)
        self.m = metrics
        self.player = player
        self._cancelled = False
        self._worker = None
        set_window_icon(self)
        self._build_common()

    def _build_common(self) -> None:
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.run_btn = compact_button(QPushButton(tr("执行")), self.m)
        self.run_btn.setObjectName("primaryButton")
        self.run_btn.clicked.connect(self._on_run)
        self.cancel_btn = compact_button(QPushButton(tr("取消")), self.m)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.close_btn = compact_button(QPushButton(tr("关闭")), self.m)
        self.close_btn.clicked.connect(self.reject)
        self.bottom = centered_buttons(self.run_btn, self.cancel_btn, self.close_btn)

    def _on_cancel(self) -> None:
        self._cancelled = True
        self.cancel_btn.setEnabled(False)
        worker = getattr(self, "_worker", None)
        if worker is not None:
            worker.cancel()

    def _finish_ui(self, layout: QVBoxLayout) -> None:
        layout.addWidget(self.progress)
        layout.addLayout(self.bottom)

    def _progress_cb(self, current: int, total: int, message: str) -> None:
        self.progress.setValue(int(current * 100 / max(1, total)))
        self.progress.setFormat(f"{message}  {current}/{total}  %p%")

    def _begin(self, task) -> None:
        self._cancelled = False
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._worker = SnapshotWorker(task, self)
        self._worker.progress.connect(self._progress_cb)
        self._worker.finished.connect(self._on_task_finished)
        self._worker.start()

    def _end(self) -> None:
        self.progress.setVisible(False)
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._worker = None

    def _on_task_finished(self, ok: bool, message: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def _on_run(self) -> None:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def retranslate(self) -> None:
        auto_retranslate(self)
        translate_standard_buttons(self)
        self.setWindowTitle(tr("缩略图") if isinstance(self, ThumbnailDialog) else tr("连续截图"))
        if isinstance(self, ThumbnailDialog):
            self._update_total()


class ThumbnailDialog(_BaseSnapshotDialog):
    def __init__(self, metrics, player, parent=None) -> None:
        super().__init__(metrics, player, parent)
        self.setWindowTitle(tr("缩略图"))
        self.setMinimumWidth(metrics.s(420))
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.cols = centered_spinbox(QSpinBox(), metrics)
        self.cols.setRange(1, 20)
        self.cols.setValue(2)
        self.rows = centered_spinbox(QSpinBox(), metrics)
        self.rows.setRange(1, 20)
        self.rows.setValue(5)
        self.total_label = mark_dynamic(QLabel("10"))
        self.cols.valueChanged.connect(self._update_total)
        self.rows.valueChanged.connect(self._update_total)
        frame = QHBoxLayout()
        frame.setSpacing(metrics.s(6))
        frame.addWidget(self.cols)
        x_label = QLabel("×")
        x_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame.addWidget(x_label)
        frame.addWidget(self.rows)
        frame.addSpacing(metrics.s(6))
        frame.addWidget(self.total_label)
        frame.addStretch(1)
        form.addRow(tr("横向数量") + " / " + tr("纵向数量"), frame)

        self.sample = QComboBox()
        self.sample.addItem(tr("全片均匀"), "all")
        self.sample.addItem(tr("当前时间点前后"), "current")
        form.addRow(tr("取样范围"), self.sample)

        self.subtitles = QCheckBox(tr("包含字幕"))
        self.subtitles.setChecked(True)
        form.addRow("", self.subtitles)

        self.output_edit = QLineEdit()
        self.output_edit.setText(
            os.path.join(user_data_root(), f"{_video_stem(self.player)}_thumbnail.png")
        )
        pick = QPushButton(tr("浏览"))
        pick.clicked.connect(self._pick_output)
        path_row = QHBoxLayout()
        path_row.addWidget(self.output_edit, 1)
        path_row.addWidget(pick)
        form.addRow(tr("选择保存位置"), path_row)
        layout.addLayout(form)
        self._finish_ui(layout)
        self._update_total()

    def _update_total(self) -> None:
        self.total_label.setText(f"= {self.cols.value() * self.rows.value()} {tr('总帧数')}")

    def _pick_output(self) -> None:
        default = self.output_edit.text().strip() or os.path.join(
            user_data_root(), f"{_video_stem(self.player)}_thumbnail.png"
        )
        path, _ = get_save_file(
            self, tr("选择保存位置"), default, "PNG (*.png)", self.m
        )
        if path:
            self.output_edit.setText(path)

    def _on_run(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        output = self.output_edit.text().strip()
        if not output:
            QMessageBox.warning(self, tr("提示"), tr("请先选择保存位置"))
            return

        columns, rows = self.cols.value(), self.rows.value()
        sample_range = self.sample.currentData()
        include_subtitles = self.subtitles.isChecked()

        def task(progress, cancelled):
            return build_thumbnail(
                self.player, output, columns, rows,
                0, sample_range, "png",
                progress, cancelled, include_subtitles,
            )

        self._begin(task)

    def _on_task_finished(self, ok: bool, message: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        self._end()
        QMessageBox.information(self, tr("提示"), tr("完成") if ok else message)
        if ok:
            self.accept()


class ContinuousDialog(_BaseSnapshotDialog):
    def __init__(self, metrics, player, parent=None) -> None:
        super().__init__(metrics, player, parent)
        self.setWindowTitle(tr("连续截图"))
        self.setMinimumWidth(metrics.s(420))
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.start = QComboBox()
        self.start.addItem(tr("当前时间"), "current")
        self.start.addItem(tr("从头开始"), "begin")
        form.addRow(tr("起始位置"), self.start)

        self.interval_mode = QComboBox()
        self.interval_mode.addItem(tr("按时间"), "time")
        self.interval_mode.addItem(tr("按帧"), "frame")
        self.interval = centered_spinbox(QSpinBox(), metrics)
        self.interval.setRange(1, 600)
        self.interval.setValue(1)
        self.interval_unit = QLabel(tr("秒"))
        self.interval_unit.setObjectName("small")
        self.interval_mode.currentIndexChanged.connect(self._update_interval_unit)
        interval_row = QHBoxLayout()
        interval_row.setSpacing(metrics.s(6))
        interval_row.addWidget(self.interval_mode)
        interval_row.addWidget(self.interval)
        interval_row.addWidget(self.interval_unit)
        interval_row.addStretch(1)
        form.addRow(tr("间隔方式"), interval_row)

        self.count = centered_spinbox(QSpinBox(), metrics)
        self.count.setRange(1, 9999)
        self.count.setValue(5)
        form.addRow(tr("指定张数"), self.count)

        self.prefix = QLineEdit()
        self.prefix.setText(_video_stem(self.player) + "_snapshot")
        form.addRow(tr("文件名前缀"), self.prefix)

        self.dir_edit = QLineEdit(user_data_root())
        pick = QPushButton(tr("浏览"))
        pick.clicked.connect(self._pick_dir)
        path_row = QHBoxLayout()
        path_row.addWidget(self.dir_edit, 1)
        path_row.addWidget(pick)
        form.addRow(tr("选择文件夹"), path_row)
        layout.addLayout(form)
        self._finish_ui(layout)

    def _update_interval_unit(self) -> None:
        """按时间=秒，按帧=帧，明确显示单位。"""
        self.interval_unit.setText(tr("秒") if self.interval_mode.currentData() == "time" else tr("帧"))

    def retranslate(self) -> None:
        super().retranslate()
        self._update_interval_unit()

    def _pick_dir(self) -> None:
        directory = get_existing_directory(
            self, tr("选择文件夹"), self.dir_edit.text(), self.m
        )
        if directory:
            self.dir_edit.setText(directory)

    def _on_run(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        directory = self.dir_edit.text().strip()
        if not directory:
            QMessageBox.warning(self, tr("提示"), tr("请先选择保存位置"))
            return

        prefix = self.prefix.text().strip() or _video_stem(self.player)
        start_mode = self.start.currentData()
        interval_mode = self.interval_mode.currentData()
        interval = float(self.interval.value())
        count = self.count.value()
        done_text, fail_text = tr("完成"), tr("失败")
        log_hint = tr("失败原因已写入日志，可通过帮助页或 log 目录查看")

        def task(progress, cancelled):
            ok, failed = continuous_snapshots(
                self.player, directory, prefix,
                start_mode, interval_mode,
                interval, count, "png",
                progress, cancelled,
                False,
            )
            message = f"{done_text}: {ok}, {fail_text}: {failed}"
            if failed:
                message += f"\n{log_hint}"
            return ok, message

        self._begin(task)

    def _on_task_finished(self, ok: bool, message: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        self._end()
        QMessageBox.information(self, tr("提示"), message)
        if not self._cancelled:
            self.accept()
