"""新建 / 编辑 IPTV 录制任务对话框。"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..core.i18n import tr
from ..core.models import Channel, RecordTask, TaskStatus
from ..core.settings import AppSettings
from .dialog_utils import (
    centered_buttons, compact_button, get_existing_directory,
    localized_button_width,
)
from .widget_utils import auto_retranslate, mark_dynamic, set_window_icon, translate_standard_buttons


class RecordDialog(QDialog):
    def __init__(self, settings: AppSettings, channels: List[Channel], metrics,
                 task: RecordTask | None = None, channel: Channel | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.metrics = metrics
        self._channels = channels
        self._task = task
        self.setWindowTitle(tr("新建录制任务") if task is None else tr("编辑"))
        set_window_icon(self)
        self.setMinimumWidth(metrics.s(480))
        self._build(channel)
        if task is not None:
            self._load(task)
        elif channel is not None:
            self.channel.setCurrentText(channel.name)

    def _build(self, channel: Channel | None) -> None:
        m = self.metrics
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # 电视台只能从已导入频道中选择，避免手输名称导致 URL 为空、任务无法开录。
        self.channel = mark_dynamic(QComboBox())
        self.channel.setEditable(False)
        for item in self._channels:
            self.channel.addItem(item.name, item)
        if not self._channels:
            self.channel.addItem(tr("请先添加 IPTV 频道"), None)
        form.addRow(tr("电视台"), self.channel)

        self.content = QLineEdit()
        self.content.setText(tr("录制"))
        form.addRow(tr("录制内容"), self.content)

        now = datetime.now().replace(second=0, microsecond=0)
        self.start = QDateTimeEdit(now)
        self.start.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.start.setCalendarPopup(True)
        self.end = QDateTimeEdit(now + timedelta(hours=1))
        self.end.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.end.setCalendarPopup(True)
        form.addRow(tr("开始时间"), self.start)
        form.addRow(tr("结束时间"), self.end)

        self.directory = QLineEdit(self.settings.record_dir)
        # 与设置页“浏览”按钮统一尺寸（compact：26px 高、64px 宽）
        browse = compact_button(QPushButton(tr("浏览")), self.metrics)
        browse.clicked.connect(self._pick_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.directory, 1)
        dir_row.addWidget(browse)
        form.addRow(tr("保存目录"), dir_row)

        self.record_format = QComboBox()
        for value, label in (
            ("source", tr("同源")), ("ts", "TS"), ("mp4", "MP4"),
            ("mkv", "MKV"),
        ):
            self.record_format.addItem(label, value)
        index = next(
            (i for i in range(self.record_format.count())
             if self.record_format.itemData(i) == self.settings.record_format), 0
        )
        self.record_format.setCurrentIndex(index)
        form.addRow(tr("封装格式"), self.record_format)

        self.hint = mark_dynamic(QLabel(""))
        self.hint.setObjectName("small")
        self.hint.setWordWrap(True)
        form.addRow("", self.hint)

        layout.addLayout(form)
        notice = QLabel(tr("请遵守当地法律与频道版权"))
        notice.setObjectName("small")
        layout.addWidget(notice)

        self.ok_btn = compact_button(QPushButton(tr("确定")), self.metrics)
        self.ok_btn.setObjectName("primaryButton")
        self.ok_btn.clicked.connect(self._on_ok)
        self.cancel_btn = compact_button(QPushButton(tr("取消")), self.metrics)
        self.cancel_btn.clicked.connect(self.reject)
        layout.addLayout(centered_buttons(self.ok_btn, self.cancel_btn))
        self.start.dateTimeChanged.connect(self._update_hint)
        self._update_hint()

    def _pick_dir(self) -> None:
        path = get_existing_directory(
            self, tr("保存目录"), self.directory.text(), self.metrics
        )
        if path:
            self.directory.setText(path)
            self._update_hint()

    def _update_hint(self) -> None:
        directory = self.directory.text().strip()
        if not directory:
            self.hint.setText("")
            return
        try:
            free = shutil.disk_usage(directory).free // (1024 * 1024)
            self.hint.setText(f"{tr('磁盘空间')}: {free} MB")
        except OSError:
            self.hint.setText(tr("录制目录不可写"))

    def _load(self, task: RecordTask) -> None:
        index = self.channel.findText(task.channel)
        if index < 0:
            # 旧任务引用的频道可能已被删除，补一个可选项以便继续编辑。
            self.channel.addItem(task.channel, None)
            index = self.channel.count() - 1
        self.channel.setCurrentIndex(index)
        self.content.setText(task.content)
        self.start.setDateTime(datetime.strptime(task.start_time, "%Y-%m-%d %H:%M"))
        self.end.setDateTime(datetime.strptime(task.end_time, "%Y-%m-%d %H:%M"))
        self.directory.setText(task.record_dir)
        index = next(
            (i for i in range(self.record_format.count())
             if self.record_format.itemData(i) == task.record_format), 0
        )
        self.record_format.setCurrentIndex(index)

    def _on_ok(self) -> None:
        start = self.start.dateTime().toPython()
        end = self.end.dateTime().toPython()
        if end <= start:
            QMessageBox.warning(self, tr("提示"), tr("结束时间必须晚于开始时间"))
            return
        directory = self.directory.text().strip()
        if not directory:
            QMessageBox.warning(self, tr("提示"), tr("录制目录不可写"))
            return
        selected = self.channel.currentData()
        if not isinstance(selected, Channel) or not selected.url.strip():
            QMessageBox.warning(self, tr("提示"), tr("请先添加 IPTV 频道"))
            return
        self.values = {
            "name": selected.name,
            "url": selected.url,
            "content": self.content.text().strip() or tr("录制"),
            "start_time": start.strftime("%Y-%m-%d %H:%M"),
            "end_time": end.strftime("%Y-%m-%d %H:%M"),
            "record_dir": directory,
            "record_format": self.record_format.currentData(),
        }
        self.accept()

    def retranslate(self) -> None:
        auto_retranslate(self)
        if not self._channels and self.channel.count():
            self.channel.setItemText(0, tr("请先添加 IPTV 频道"))
        translate_standard_buttons(self)
        self._update_hint()


class RecordTasksDialog(QDialog):
    """独立的录制任务列表窗口：任务管理从 IPTV 抽屉页移入 IPTV 菜单。"""

    newTask = Signal()
    taskStop = Signal(str)
    taskCancel = Signal(str)
    taskEdit = Signal(str)
    taskDelete = Signal(str)
    taskDeleteSelected = Signal(list)
    taskOpenFile = Signal(str)
    taskOpenDir = Signal(str)

    # 表格列索引：选择 / 创建时间 / 状态 / 电视台 / 录制内容 / 时间区间 / 输出文件
    COL_SELECT, COL_CREATED, COL_STATUS, COL_CHANNEL, COL_CONTENT, COL_TIME, COL_OUTPUT = range(7)

    def __init__(self, metrics, parent=None) -> None:
        super().__init__(parent)
        self.metrics = metrics
        self._tasks: list[RecordTask] = []
        self.setWindowTitle(tr("录制任务"))
        set_window_icon(self)
        # 新增创建时间列后加宽窗口，保证各列文字不挤叠。
        self.setMinimumSize(metrics.s(980), metrics.s(440))
        self.resize(metrics.s(1120), metrics.s(480))
        self._build()
        self.retranslate()

    def _build(self) -> None:
        m = self.metrics
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.select_all_cb = QCheckBox(tr("全选"))
        self.select_all_cb.setTristate(True)
        self.select_all_cb.stateChanged.connect(self._on_select_all)
        top.addWidget(self.select_all_cb)
        top.addStretch(1)
        self.new_btn = compact_button(QPushButton(tr("新建录制任务")), m)
        self.new_btn.setObjectName("primaryButton")
        self.new_btn.clicked.connect(lambda _checked=False: self.newTask.emit())
        top.addWidget(self.new_btn)
        layout.addLayout(top)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(self._headers())
        header = self.table.horizontalHeader()
        for column, width in (
            (self.COL_SELECT, 52), (self.COL_CREATED, 164), (self.COL_STATUS, 86),
            (self.COL_CHANNEL, 140), (self.COL_CONTENT, 130), (self.COL_TIME, 220),
        ):
            self.table.setColumnWidth(column, m.s(width))
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_OUTPUT, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # 主题为深色，Qt 默认交替行浅色底会让浅色文字看不清，统一使用主题底色。
        self.table.setAlternatingRowColors(False)
        self.table.itemSelectionChanged.connect(self._update_action_buttons)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        for attr, label, signal in (
            ("stop_btn", "停止", self.taskStop),
            ("cancel_btn", "取消", self.taskCancel),
            ("edit_btn", "编辑", self.taskEdit),
            ("delete_btn", "删除", None),
            ("open_file_btn", "打开文件", self.taskOpenFile),
            ("open_dir_btn", "打开目录", self.taskOpenDir),
        ):
            button = compact_button(QPushButton(tr(label)), m)
            if signal is None:
                button.clicked.connect(lambda _checked=False: self._delete_selected())
            else:
                button.clicked.connect(
                    lambda _checked=False, target=signal: self._emit_selected(target)
                )
            setattr(self, attr, button)
            actions.addWidget(button)
        self.close_btn = compact_button(QPushButton(tr("关闭")), m)
        self.close_btn.clicked.connect(self.reject)
        actions.addStretch(1)
        actions.addWidget(self.close_btn)
        layout.addLayout(actions)
        self._apply_button_widths()

    def _apply_button_widths(self) -> None:
        """三个长文案按钮按三语最长译文定宽，切换语言时宽度不变且文字不截断。"""
        m = self.metrics
        for button, source in (
            (self.new_btn, "新建录制任务"),
            (self.open_file_btn, "打开文件"),
            (self.open_dir_btn, "打开目录"),
        ):
            button.setFixedWidth(localized_button_width(button, source, m))

    def _headers(self) -> list[str]:
        return [tr(key) for key in (
            "选择", "创建时间", "状态", "电视台", "录制内容", "时间区间", "输出文件"
        )]

    def retranslate(self) -> None:
        self.setWindowTitle(tr("录制任务"))
        self.select_all_cb.setText(tr("全选"))
        self.new_btn.setText(tr("新建录制任务"))
        for attr, label in (
            ("stop_btn", "停止"), ("cancel_btn", "取消"), ("edit_btn", "编辑"),
            ("delete_btn", "删除"), ("open_file_btn", "打开文件"),
            ("open_dir_btn", "打开目录"), ("close_btn", "关闭"),
        ):
            getattr(self, attr).setText(tr(label))
        self._apply_button_widths()
        self.table.setHorizontalHeaderLabels(self._headers())
        self._render()

    def set_tasks(self, tasks: list[RecordTask]) -> None:
        self._tasks = list(tasks)
        self._render()

    def _render(self) -> None:
        # 任务状态刷新会频繁重建表格，先记住勾选的任务，渲染后恢复。
        checked = set(self.selected_task_ids())
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for task in self._tasks:
            row = self.table.rowCount()
            self.table.insertRow(row)
            select = QTableWidgetItem()
            select.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            select.setCheckState(
                Qt.CheckState.Checked if task.id in checked else Qt.CheckState.Unchecked
            )
            select.setData(Qt.ItemDataRole.UserRole, task.id)
            self.table.setItem(row, self.COL_SELECT, select)
            color = {
                TaskStatus.RECORDING.value: "#ff5d73",
                TaskStatus.COMPLETED.value: "#37d39b",
                TaskStatus.WAITING.value: "#ffb454",
            }.get(task.status, "#8d97a5")
            values = [
                task.created_at or "--", tr(task.status), task.channel, task.content,
                f"{task.start_time}\n→ {task.end_time}", task.output or "--",
            ]
            for column, value in zip(
                (self.COL_CREATED, self.COL_STATUS, self.COL_CHANNEL,
                 self.COL_CONTENT, self.COL_TIME, self.COL_OUTPUT), values
            ):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.ItemDataRole.UserRole, task.id)
                if column == self.COL_STATUS:
                    cell.setForeground(QColor(color))
                self.table.setItem(row, column, cell)
        self.table.blockSignals(False)
        self._sync_select_all()
        self._update_action_buttons()

    def selected_task_ids(self) -> list[str]:
        ids: list[str] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_SELECT)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                ids.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return ids

    def _current_task_id(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, self.COL_STATUS)
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    def _sync_select_all(self) -> None:
        total = self.table.rowCount()
        checked = len(self.selected_task_ids())
        if total == 0 or checked == 0:
            state = Qt.CheckState.Unchecked
        elif checked == total:
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        self.select_all_cb.blockSignals(True)
        self.select_all_cb.setCheckState(state)
        self.select_all_cb.blockSignals(False)

    def _on_select_all(self, state: int) -> None:
        checked = Qt.CheckState.Checked if state == Qt.CheckState.Checked.value else Qt.CheckState.Unchecked
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_SELECT)
            if item is not None:
                item.setCheckState(checked)
        self.table.blockSignals(False)
        self._update_action_buttons()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != self.COL_SELECT:
            return
        self._sync_select_all()
        self._update_action_buttons()

    def _update_action_buttons(self) -> None:
        """停止按钮只对录制中任务可用；其余操作沿用内核状态校验。"""
        task_id = self._current_task_id()
        task = next((item for item in self._tasks if item.id == task_id), None)
        self.stop_btn.setEnabled(
            task is not None and task.status == TaskStatus.RECORDING.value
        )

    def _delete_selected(self) -> None:
        ids = self.selected_task_ids()
        if not ids:
            current = self._current_task_id()
            ids = [current] if current else []
        if ids:
            self.taskDeleteSelected.emit(ids)

    def _emit_selected(self, signal: Signal) -> None:
        task_id = self._current_task_id()
        if task_id:
            signal.emit(task_id)
