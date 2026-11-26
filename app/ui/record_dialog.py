"""新建 / 编辑 IPTV 录制任务对话框。"""

from __future__ import annotations

import os
import shutil
from datetime import date, datetime, time, timedelta
from typing import List

from PySide6.QtCore import Qt, QDate, QTime, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCalendarWidget, QCheckBox, QComboBox,
    QDateTimeEdit, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QTimeEdit, QVBoxLayout, QWidget,
)

from ..core.i18n import tr
from ..core.models import (
    Channel, FREQUENCIES, RecordTask, TaskStatus, frequency_label,
)
from ..core.recorder import active_occurrence
from ..core.settings import AppSettings
from .dialog_utils import (
    centered_buttons, compact_button, get_existing_directory,
    localized_button_width,
)
from .widget_utils import auto_retranslate, mark_dynamic, set_window_icon, translate_standard_buttons


class RecordDialog(QDialog):
    """新建 / 编辑录制任务：频率（单次/日/周/自定义）+ 分组二级频道选择。"""

    WEEKDAY_KEYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
    FREQ_LABELS = {
        "once": "单次", "daily": "每日", "weekly": "每周", "custom": "自定义",
    }
    MAX_CUSTOM_DATES = 5

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
        self.setMinimumWidth(metrics.s(520))
        self._build(channel)
        if task is not None:
            self._load(task)
        elif channel is not None:
            self._select_channel(channel)

    # ---------- 构建 ----------
    def _build(self, channel: Channel | None) -> None:
        m = self.metrics
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # 电视台：一级分组 + 二级频道，参考 IPTV 分组方式。
        self.group_combo = QComboBox()
        self.channel_combo = QComboBox()
        self.channel_combo.setEditable(False)
        groups: list[str] = []
        for item in self._channels:
            if item.group not in groups:
                groups.append(item.group)
        if not groups:
            groups = [tr("默认分组")]
        for group in groups:
            self.group_combo.addItem(group, group)
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        self._reload_channels(self.group_combo.currentData())
        form.addRow(tr("分组"), self.group_combo)
        form.addRow(tr("电视台"), self.channel_combo)

        self.content = QLineEdit()
        self.content.setText(tr("录制"))
        form.addRow(tr("录制内容"), self.content)

        # 频率选择
        self.freq_combo = QComboBox()
        for freq in FREQUENCIES:
            self.freq_combo.addItem(tr(self.FREQ_LABELS[freq]), freq)
        self.freq_combo.currentIndexChanged.connect(self._on_freq_changed)
        form.addRow(tr("录制频率"), self.freq_combo)

        # 单次：完整日期时间
        now = datetime.now().replace(second=0, microsecond=0)
        self.start = QDateTimeEdit(now)
        self.start.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.start.setCalendarPopup(True)
        self.end = QDateTimeEdit(now + timedelta(hours=1))
        self.end.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.end.setCalendarPopup(True)
        form.addRow(tr("开始时间"), self.start)
        form.addRow(tr("结束时间"), self.end)

        # 循环（日/周/自定义）：仅时分
        self.time_start = QTimeEdit(now.time())
        self.time_start.setDisplayFormat("HH:mm")
        self.time_end = QTimeEdit((now + timedelta(hours=1)).time())
        self.time_end.setDisplayFormat("HH:mm")
        form.addRow(tr("开始时刻"), self.time_start)
        form.addRow(tr("结束时刻"), self.time_end)

        # 周：星期多选
        self.weekday_row = QHBoxLayout()
        self.weekday_boxes: list[QCheckBox] = []
        for label in self.WEEKDAY_KEYS:
            box = mark_dynamic(QCheckBox(tr(label)))
            self.weekday_boxes.append(box)
            self.weekday_row.addWidget(box)
        self.weekday_widget = QWidget()
        self.weekday_widget.setLayout(self.weekday_row)
        form.addRow(tr("重复星期"), self.weekday_widget)

        # 自定义：日历多选（最多 5 天）。新建时不默认选中当天：QCalendarWidget
        # 无法清空选中日期，因此内部选中态放到最大日期（不在当前月），并用样式
        # 隐藏高亮；用户点击后才把日期加入 _custom_dates 并恢复高亮。
        today = QDate.currentDate()
        self.calendar = QCalendarWidget()
        self.calendar.setMinimumDate(today)
        self.calendar.setMaximumDate(today.addYears(2))
        self.calendar.setSelectedDate(today.addYears(2))
        self.calendar.setCurrentPage(today.year(), today.month())
        self.calendar.clicked.connect(self._on_calendar_clicked)
        self._custom_dates: list[QDate] = []
        self.date_hint = QLabel("")
        self.date_hint.setObjectName("small")
        custom_box = QVBoxLayout()
        custom_box.addWidget(self.calendar)
        custom_box.addWidget(self.date_hint)
        self.custom_widget = QWidget()
        self.custom_widget.setLayout(custom_box)
        form.addRow(tr("选择日期"), self.custom_widget)

        self.directory = QLineEdit(self.settings.record_dir)
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

        self._on_freq_changed()
        self._apply_calendar_selection_style()
        self._update_date_hint()
        self._update_hint()

    def _reload_channels(self, group: str | None) -> None:
        """按分组刷新二级频道下拉。"""
        self.channel_combo.clear()
        matched = [c for c in self._channels if c.group == group] if group else list(self._channels)
        for item in matched:
            self.channel_combo.addItem(item.name, item)
        if not matched:
            self.channel_combo.addItem(tr("请先添加 IPTV 频道"), None)

    def _on_group_changed(self) -> None:
        self._reload_channels(self.group_combo.currentData())

    def _select_channel(self, channel: Channel) -> None:
        """定位到指定频道所在分组并选中。"""
        group_index = self.group_combo.findData(channel.group)
        if group_index >= 0:
            self.group_combo.setCurrentIndex(group_index)
        else:
            # 频道分组不在列表中（异常情况）时补一个分组
            self.group_combo.addItem(channel.group, channel.group)
            self.group_combo.setCurrentIndex(self.group_combo.count() - 1)
        self._reload_channels(channel.group)
        index = self.channel_combo.findText(channel.name)
        if index >= 0:
            self.channel_combo.setCurrentIndex(index)

    # ---------- 频率联动 ----------
    def _on_freq_changed(self) -> None:
        freq = self.freq_combo.currentData()
        once = freq == "once"
        # 单次显示完整 datetime；循环显示时分。QFormLayout 的 label 随 field 一起隐藏。
        self._set_field_row(self.start, once)
        self._set_field_row(self.end, once)
        self._set_field_row(self.time_start, not once)
        self._set_field_row(self.time_end, not once)
        self._set_field_row(self.weekday_widget, freq == "weekly")
        self._set_field_row(self.custom_widget, freq == "custom")
        if freq == "custom":
            self._update_date_hint()
        self.adjustSize()

    def _set_field_row(self, field, visible: bool) -> None:
        """同步 QFormLayout 中某字段所在行的 label 与 field 可见性。"""
        field.setVisible(visible)
        form = self._form_layout()
        if form is None:
            return
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
            label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item is not None and item.widget() is field and label_item is not None:
                label = label_item.widget()
                if label is not None:
                    label.setVisible(visible)
                return

    def _form_layout(self):
        top = self.layout()
        if top is None:
            return None
        for i in range(top.count()):
            item = top.itemAt(i)
            candidate = item.layout() if hasattr(item, "layout") else None
            if candidate is not None and hasattr(candidate, "labelForField"):
                return candidate
        return None

    def _on_calendar_clicked(self, selected: QDate) -> None:
        """点击日历才真正选中日期；初始状态不把当天计入已选日期。"""
        if selected in self._custom_dates:
            # 已选日期：再次点击视为取消（保留至少一个）
            if len(self._custom_dates) > 1:
                self._custom_dates.remove(selected)
            else:
                return
        else:
            if len(self._custom_dates) >= self.MAX_CUSTOM_DATES:
                QMessageBox.warning(
                    self, tr("提示"),
                    tr("自定义最多选择5天"),
                )
                return
            self._custom_dates.append(selected)
        self._apply_calendar_selection_style()
        self._update_date_hint()

    def _apply_calendar_selection_style(self) -> None:
        """无已选日期时隐藏日历控件自带的选中高亮。"""
        if self._custom_dates:
            self.calendar.setStyleSheet("")
            return
        self.calendar.setStyleSheet(
            "QCalendarWidget QAbstractItemView:enabled {"
            "selection-background-color: transparent;"
            "selection-color: palette(window-text);}"
        )

    def _update_date_hint(self) -> None:
        dates = sorted(d.toString("yyyy-MM-dd") for d in self._custom_dates)
        self.date_hint.setText(
            f"{tr('已选日期')}: {len(dates)}/{self.MAX_CUSTOM_DATES}  " + ", ".join(dates)
        )

    # ---------- 通用 ----------
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
            free = shutil.disk_usage(directory).free / (1024 ** 3)
            self.hint.setText(f"{tr('磁盘空间')}: {free:.1f} GB")
        except OSError:
            self.hint.setText(tr("录制目录不可写"))

    def _load(self, task: RecordTask) -> None:
        # 频率
        index = next(
            (i for i in range(self.freq_combo.count())
             if self.freq_combo.itemData(i) == task.frequency), 0
        )
        self.freq_combo.setCurrentIndex(index)
        self._select_channel_for_name(task.channel)
        self.content.setText(task.content)
        # 单次时间
        try:
            self.start.setDateTime(datetime.strptime(task.start_time, "%Y-%m-%d %H:%M"))
            self.end.setDateTime(datetime.strptime(task.end_time, "%Y-%m-%d %H:%M"))
        except (ValueError, TypeError):
            pass
        # 循环时刻
        hs = parse_hhmm_safe(task.time_start)
        he = parse_hhmm_safe(task.time_end)
        if hs and he:
            self.time_start.setTime(QTime(hs[0], hs[1]))
            self.time_end.setTime(QTime(he[0], he[1]))
        # 星期
        if task.frequency == "weekly":
            wanted = {int(x) for x in task.weekdays.split(",") if x.strip()}
            for i, box in enumerate(self.weekday_boxes):
                box.setChecked(i in wanted)
        # 自定义日期
        if task.frequency == "custom":
            dates: list[QDate] = []
            for token in task.custom_dates.split(","):
                token = token.strip()
                if not token:
                    continue
                qd = QDate.fromString(token, "yyyy-MM-dd")
                if qd.isValid():
                    dates.append(qd)
            if dates:
                self._custom_dates = dates[: self.MAX_CUSTOM_DATES]
                self.calendar.setSelectedDate(self._custom_dates[0])
                self._apply_calendar_selection_style()
                self._update_date_hint()
        self.directory.setText(task.record_dir)
        index = next(
            (i for i in range(self.record_format.count())
             if self.record_format.itemData(i) == task.record_format), 0
        )
        self.record_format.setCurrentIndex(index)
        self._on_freq_changed()

    def _select_channel_for_name(self, name: str) -> None:
        """按频道名定位分组与频道；旧任务引用的频道已删除时补选项。"""
        found = next((c for c in self._channels if c.name == name), None)
        if found is not None:
            self._select_channel(found)
            return
        # 兼容已删除频道：在默认分组补一个占位项
        default_group = self.group_combo.itemData(0)
        self.group_combo.setCurrentIndex(0)
        self._reload_channels(default_group)
        self.channel_combo.addItem(name, None)
        self.channel_combo.setCurrentIndex(self.channel_combo.count() - 1)

    def _on_ok(self) -> None:
        freq = self.freq_combo.currentData()
        start_str: str
        end_str: str
        time_start = ""
        time_end = ""
        weekdays = ""
        custom_dates = ""
        if freq == "once":
            start = self.start.dateTime().toPython()
            end = self.end.dateTime().toPython()
            if end <= start:
                QMessageBox.warning(self, tr("提示"), tr("结束时间必须晚于开始时间"))
                return
            start_str = start.strftime("%Y-%m-%d %H:%M")
            end_str = end.strftime("%Y-%m-%d %H:%M")
        else:
            hs_qtime = self.time_start.time()
            he_qtime = self.time_end.time()
            hs = (hs_qtime.hour(), hs_qtime.minute())
            he = (he_qtime.hour(), he_qtime.minute())
            time_start = f"{hs[0]:02d}:{hs[1]:02d}"
            time_end = f"{he[0]:02d}:{he[1]:02d}"
            if time_end == time_start:
                QMessageBox.warning(self, tr("提示"), tr("结束时间必须晚于开始时间"))
                return
            now_dt = datetime.now()
            today = now_dt.date()
            if freq == "weekly":
                selected = [i for i, box in enumerate(self.weekday_boxes) if box.isChecked()]
                if not selected:
                    QMessageBox.warning(self, tr("提示"), tr("请至少选择一个星期几"))
                    return
                weekdays = ",".join(str(i) for i in selected)
            elif freq == "custom":
                if not self._custom_dates:
                    QMessageBox.warning(self, tr("提示"), tr("请至少选择一个日期"))
                    return
                custom_dates = ",".join(d.toString("yyyy-MM-dd") for d in sorted(self._custom_dates))
            # 当前时刻正落在规则窗口内（含跨午夜）时立即开录，结束仍是计划结束时刻。
            current = active_occurrence(
                freq, today, hs, he, weekdays, custom_dates, now=now_dt
            )
            if current is not None:
                start_dt, end_dt = current
            else:
                if freq == "weekly":
                    first_day = next_future_weekday(today, selected, hs, he)
                elif freq == "custom":
                    first_day = next_future_custom(today, self._custom_dates, hs, he)
                else:  # daily
                    first_day = today
                    if datetime.combine(first_day, time(hs[0], hs[1])) <= now_dt:
                        first_day += timedelta(days=1)
                start_dt = datetime.combine(first_day, time(hs[0], hs[1]))
                end_dt = datetime.combine(first_day, time(he[0], he[1]))
                if end_dt <= start_dt:
                    end_dt += timedelta(days=1)
            start_str = start_dt.strftime("%Y-%m-%d %H:%M")
            end_str = end_dt.strftime("%Y-%m-%d %H:%M")

        directory = self.directory.text().strip()
        if not directory:
            QMessageBox.warning(self, tr("提示"), tr("录制目录不可写"))
            return
        selected = self.channel_combo.currentData()
        if not isinstance(selected, Channel) or not selected.url.strip():
            QMessageBox.warning(self, tr("提示"), tr("请先添加 IPTV 频道"))
            return
        self.values = {
            "name": selected.name,
            "url": selected.url,
            "content": self.content.text().strip() or tr("录制"),
            "start_time": start_str,
            "end_time": end_str,
            "record_dir": directory,
            "record_format": self.record_format.currentData(),
            "frequency": freq,
            "weekdays": weekdays,
            "custom_dates": custom_dates,
            "time_start": time_start,
            "time_end": time_end,
        }
        self.accept()

    def retranslate(self) -> None:
        auto_retranslate(self)
        self.freq_combo.blockSignals(True)
        current = self.freq_combo.currentData()
        for i in range(self.freq_combo.count()):
            self.freq_combo.setItemText(i, tr(self.FREQ_LABELS.get(self.freq_combo.itemData(i), "单次")))
        self.freq_combo.blockSignals(False)
        for box, label in zip(self.weekday_boxes, self.WEEKDAY_KEYS):
            box.setText(tr(label))
        self._on_freq_changed()
        translate_standard_buttons(self)
        self._update_date_hint()
        self._update_hint()


def parse_hhmm_safe(value: str):
    """HH:mm -> (hour, minute)；无效返回 None。"""
    try:
        parts = str(value).split(":")
        h, m = int(parts[0]), int(parts[1])
        return (h, m) if 0 <= h <= 23 and 0 <= m <= 59 else None
    except (ValueError, IndexError, TypeError):
        return None


def _occurs_in_future(day: date, hs: tuple, he: tuple, now_dt: datetime) -> bool:
    """某天的录制窗口是否尚未开始（跨午夜结束视为次日）。"""
    start = datetime.combine(day, QTime(hs[0], hs[1]).toPython())
    return start > now_dt


def next_future_weekday(base: date, weekdays: list, hs: tuple, he: tuple) -> date:
    """从 base（含）起找到下一个尚未开始的选中星期几日期。"""
    now_dt = datetime.now()
    for offset in range(14):
        d = base + timedelta(days=offset)
        if d.weekday() in weekdays and _occurs_in_future(d, hs, he, now_dt):
            return d
    return base + timedelta(days=14)


def next_future_custom(base: date, dates: list, hs: tuple, he: tuple) -> date:
    """从自定义日期中找到下一个尚未开始的日期。"""
    now_dt = datetime.now()
    candidates = sorted(d.toPython() for d in dates)
    for d in candidates:
        if d >= base and _occurs_in_future(d, hs, he, now_dt):
            return d
    return candidates[0] if candidates else base


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

    # 表格列索引：选择 / 创建时间 / 状态 / 录制频率 / 电视台 / 录制内容 / 时间区间 / 输出文件
    (COL_SELECT, COL_CREATED, COL_STATUS, COL_FREQ, COL_CHANNEL,
     COL_CONTENT, COL_TIME, COL_OUTPUT) = range(8)

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

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(self._headers())
        header = self.table.horizontalHeader()
        for column, width in (
            (self.COL_SELECT, 52), (self.COL_CREATED, 164), (self.COL_STATUS, 86),
            (self.COL_FREQ, 80), (self.COL_CHANNEL, 140), (self.COL_CONTENT, 130),
            (self.COL_TIME, 220),
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
        # 点击数据行 = 切换该行勾选（与复选框一致），便于批量选择。
        self.table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        # 每个按钮的启用规则统一由 _update_action_buttons() 依据勾选的任务集合决定。
        for attr, label, handler in (
            ("stop_btn", "停止", lambda: self._emit_checked(self.taskStop)),
            ("cancel_btn", "取消", lambda: self._emit_checked(self.taskCancel)),
            ("edit_btn", "编辑", lambda: self._emit_single(self.taskEdit)),
            ("delete_btn", "删除", lambda: self._delete_selected()),
            ("open_file_btn", "打开文件", lambda: self._emit_checked(self.taskOpenFile)),
            ("open_dir_btn", "打开目录", lambda: self._open_dirs()),
        ):
            button = compact_button(QPushButton(tr(label)), m)
            button.clicked.connect(handler)
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
            "选择", "创建时间", "状态", "录制频率", "电视台", "录制内容", "时间区间", "输出文件"
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
                task.created_at or "--", tr(task.status),
                tr(frequency_label(task.frequency)), task.channel, task.content,
                f"{task.start_time}\n→ {task.end_time}", task.output or "--",
            ]
            for column, value in zip(
                (self.COL_CREATED, self.COL_STATUS, self.COL_FREQ, self.COL_CHANNEL,
                 self.COL_CONTENT, self.COL_TIME, self.COL_OUTPUT), values
            ):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.ItemDataRole.UserRole, task.id)
                if column == self.COL_STATUS:
                    cell.setForeground(QColor(color))
                if column in (self.COL_CONTENT, self.COL_TIME, self.COL_OUTPUT):
                    # 列宽不足或时间区间换行被截断时，悬浮展示完整文本。
                    cell.setToolTip(value)
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

    def _on_cell_clicked(self, row: int, column: int) -> None:
        """点击数据行等价于点击复选框：再次点击取消选择。

        点击复选框列本身交给 Qt 的 itemChanged 处理（避免双重翻转）；
        点击其它列时手动翻转勾选状态，并让 itemChanged 触发按钮刷新。
        """
        if column == self.COL_SELECT:
            return
        item = self.table.item(row, self.COL_SELECT)
        if item is None:
            return
        checked = item.checkState() == Qt.CheckState.Checked
        item.setCheckState(
            Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked
        )

    def _selected_tasks(self) -> list[RecordTask]:
        ids = set(self.selected_task_ids())
        return [task for task in self._tasks if task.id in ids]

    def _update_action_buttons(self) -> None:
        """按钮启用规则完全依据勾选集合，与当前焦点行无关。

        - 未勾选任何任务：停止/取消/编辑/删除/打开文件/打开目录 全部禁用；
        - 勾选多个任务：编辑禁用、打开目录仅在所有输出文件处于同一目录时可用；
        - 勾选单个任务：按任务状态与输出文件决定是否可用。
        """
        tasks = self._selected_tasks()
        count = len(tasks)
        recording = any(task.status == TaskStatus.RECORDING.value for task in tasks)
        dirs = {
            os.path.dirname(task.output)
            for task in tasks if task.output
        }
        self.stop_btn.setEnabled(count > 0 and recording)
        self.cancel_btn.setEnabled(count > 0)
        self.edit_btn.setEnabled(count == 1)
        self.delete_btn.setEnabled(count > 0)
        self.open_file_btn.setEnabled(count > 0)
        self.open_dir_btn.setEnabled(count > 0 and len(dirs) == 1)

    def _delete_selected(self) -> None:
        ids = self.selected_task_ids()
        if ids:
            self.taskDeleteSelected.emit(ids)

    def _emit_checked(self, signal: Signal) -> None:
        """对勾选的每个任务逐个发出信号（停止/取消/打开文件）。"""
        for task_id in self.selected_task_ids():
            signal.emit(task_id)

    def _emit_single(self, signal: Signal) -> None:
        """仅当恰好勾选一个任务时发出信号（编辑）。"""
        ids = self.selected_task_ids()
        if len(ids) == 1:
            signal.emit(ids[0])

    def _open_dirs(self) -> None:
        """打开目录：勾选任务输出文件同处一个目录时，打开该目录。"""
        tasks = self._selected_tasks()
        dirs = {os.path.dirname(task.output) for task in tasks if task.output}
        if len(dirs) != 1:
            return
        # 用任一任务 id 触发；主窗口按该任务 output 的目录打开。
        self.taskOpenDir.emit(tasks[0].id)
