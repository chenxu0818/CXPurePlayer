"""v1.0.2 回归：录制频率、二级频道选择、GB、无媒体按钮、全音轨录制。
运行：python tests/test_v102_features.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil  # noqa: E402
from datetime import date, datetime, timedelta  # noqa: E402
from PySide6.QtCore import QDate, QTime  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

QMessageBox.warning = lambda *a, **k: QMessageBox.StandardButton.Ok

from app.core import ffmpeg_recorder  # noqa: E402
from app.core.i18n import init_i18n, tr  # noqa: E402
from app.core.models import Channel, RecordTask, TaskStatus  # noqa: E402
from app.core.recorder import (  # noqa: E402
    Recorder, active_occurrence, next_occurrence, parse_hhmm, parse_time,
)
from app.core.settings import AppSettings  # noqa: E402
from app.core.ui_scale import Metrics  # noqa: E402
from app.ui.control_bar import ControlBar  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.record_dialog import (  # noqa: E402
    RecordDialog, RecordTasksDialog, next_future_custom, next_future_weekday,
)

app = QApplication.instance() or QApplication([])
init_i18n("zh_CN")
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"PASS {name}")
    else:
        FAILED.append(name)
        print(f"FAIL {name} {detail}")


def metrics() -> Metrics:
    return Metrics(AppSettings())


CHANNELS = [
    Channel("新闻台", "http://a", "新闻"),
    Channel("财经台", "http://b", "新闻"),
    Channel("体育台", "http://c", "体育"),
]


# ---------- 需求1：频率 ----------
def test_frequency_ui() -> None:
    d = RecordDialog(AppSettings(), CHANNELS, metrics())
    check("频率四选项", [d.freq_combo.itemData(i) for i in range(d.freq_combo.count())]
          == ["once", "daily", "weekly", "custom"])
    d.show()
    d.freq_combo.setCurrentIndex(d.freq_combo.findData("once"))
    check("单次显示日期时间", not d.start.isHidden() and d.time_start.isHidden())
    d.freq_combo.setCurrentIndex(d.freq_combo.findData("daily"))
    check("每日显示时分", d.start.isHidden() and not d.time_start.isHidden() and d.weekday_widget.isHidden())
    d.freq_combo.setCurrentIndex(d.freq_combo.findData("weekly"))
    check("每周显示星期", not d.weekday_widget.isHidden() and d.custom_widget.isHidden())
    d.freq_combo.setCurrentIndex(d.freq_combo.findData("custom"))
    check("自定义显示日历", d.custom_widget.isHidden() is False)


def test_custom_no_default_today() -> None:
    d = RecordDialog(AppSettings(), CHANNELS, metrics())
    d.freq_combo.setCurrentIndex(d.freq_combo.findData("custom"))
    check("自定义初始无已选日期", d._custom_dates == [], str(d._custom_dates))
    check("自定义初始提示0/5",
          d.date_hint.text().startswith(f"{tr('已选日期')}: 0/5"), d.date_hint.text())
    check("自定义初始不高亮当天",
          "transparent" in d.calendar.styleSheet()
          and d.calendar.selectedDate() != QDate.currentDate(),
          f"{d.calendar.styleSheet()}/{d.calendar.selectedDate()}")
    chosen = QDate.currentDate().addDays(2)
    d.calendar.clicked.emit(chosen)
    check("点击后才选中日期",
          d._custom_dates == [chosen] and "1/5" in d.date_hint.text(), d.date_hint.text())
    check("选中后恢复日历高亮", d.calendar.styleSheet() == "")
    task = RecordTask(
        id="c", channel="新闻台", frequency="custom",
        start_time="2026-12-01 09:00", end_time="2026-12-01 10:00",
        custom_dates=chosen.toString("yyyy-MM-dd"),
    )
    d2 = RecordDialog(AppSettings(), CHANNELS, metrics(), task=task)
    check("编辑自定义任务回填日期",
          d2._custom_dates == [chosen] and d2.calendar.selectedDate() == chosen,
          f"{d2._custom_dates}/{d2.calendar.selectedDate()}")


def test_frequency_values() -> None:
    d = RecordDialog(AppSettings(), CHANNELS, metrics())
    # 单次
    d.freq_combo.setCurrentIndex(0)
    d._on_ok()
    check("单次值", d.values["frequency"] == "once")
    # 每日（时刻已过则顺延到明天）
    d.freq_combo.setCurrentIndex(d.freq_combo.findData("daily"))
    d.time_start.setTime(QTime(9, 30))
    d.time_end.setTime(QTime(10, 0))
    d._on_ok()
    check("每日值", d.values["time_start"] == "09:30" and d.values["frequency"] == "daily")
    st = datetime.strptime(d.values["start_time"], "%Y-%m-%d %H:%M")
    et = datetime.strptime(d.values["end_time"], "%Y-%m-%d %H:%M")
    check("每日窗口尚未结束（可能在当前时段内立即开录）", et > datetime.now(), str(st))
    # 每周多选
    d.freq_combo.setCurrentIndex(d.freq_combo.findData("weekly"))
    for i in range(7):
        d.weekday_boxes[i].setChecked(i in (0, 2, 4))
    d._on_ok()
    check("每周多选值", d.values["weekdays"] == "0,2,4" and d.values["frequency"] == "weekly")
    # 自定义（最多5天）
    d.freq_combo.setCurrentIndex(d.freq_combo.findData("custom"))
    d._custom_dates = [QDate.currentDate().addDays(2), QDate.currentDate().addDays(4)]
    d._on_ok()
    check("自定义日期值", len(d.values["custom_dates"].split(",")) == 2)
    check("自定义最多5天上限", RecordDialog.MAX_CUSTOM_DATES == 5)


def test_next_occurrence() -> None:
    hs, he = parse_hhmm("09:30"), parse_hhmm("10:00")
    ref = datetime(2026, 11, 26, 18, 0)  # 当日 18:00，09:30 已过
    check("单次已过不重排", next_occurrence("once", date(2026, 11, 26), hs, he, after=ref) is None)
    nxt = next_occurrence("daily", date(2026, 11, 26), hs, he, after=ref)
    check("每日顺延到次日", nxt is not None and nxt[0].date() == date(2026, 11, 27))
    nxt = next_occurrence("weekly", date(2026, 11, 27), hs, he, "0,2", after=ref)
    check("每周匹配星期", nxt is not None and nxt[0].date() == date(2026, 11, 30))  # 周一
    nxt = next_occurrence("custom", date(2026, 11, 27), hs, he,
                          custom_dates="2026-11-25,2026-11-28", after=ref)
    check("自定义最近日期", nxt is not None and nxt[0].date() == date(2026, 11, 28))
    # 跨午夜
    nxt = next_occurrence("once", date(2026, 11, 26), (23, 30), (0, 30), after=datetime(2026, 11, 26, 23, 0))
    check("跨午夜结束为次日", nxt is not None and nxt[1].date() == date(2026, 11, 27))


def test_active_occurrence() -> None:
    now = datetime(2026, 11, 26, 9, 30)
    day = now.date()
    expected = (datetime(2026, 11, 26, 9, 0), datetime(2026, 11, 26, 10, 0))
    check("每日时段内立即开录", active_occurrence("daily", day, (9, 0), (10, 0), now=now) == expected)
    check("每周当天时段内立即开录",
          active_occurrence("weekly", day, (9, 0), (10, 0),
                            weekdays=str(day.weekday()), now=now) == expected)
    check("自定义当天时段内立即开录",
          active_occurrence("custom", day, (9, 0), (10, 0),
                            custom_dates="2026-11-26", now=now) == expected)
    check("时段外不立即开录",
          active_occurrence("daily", day, (9, 0), (10, 0),
                            now=datetime(2026, 11, 26, 11, 0)) is None)
    cross = active_occurrence(
        "daily", date(2026, 11, 27), (23, 0), (1, 0),
        now=datetime(2026, 11, 27, 0, 30),
    )
    check("跨午夜时段内立即开录",
          cross == (datetime(2026, 11, 26, 23, 0), datetime(2026, 11, 27, 1, 0)), str(cross))


def test_dialog_immediate_recording() -> None:
    d = RecordDialog(AppSettings(), CHANNELS, metrics())
    now = datetime.now().replace(second=0, microsecond=0)
    start_dt = now - timedelta(minutes=10)
    if start_dt.date() != now.date():
        start_dt = now.replace(minute=0)
    end_dt = (now + timedelta(minutes=50)).replace(second=0, microsecond=0)
    d.time_start.setTime(QTime(start_dt.hour, start_dt.minute))
    d.time_end.setTime(QTime(end_dt.hour, end_dt.minute))
    d.freq_combo.setCurrentIndex(d.freq_combo.findData("daily"))
    d._on_ok()
    expected_start = start_dt.strftime("%Y-%m-%d %H:%M")
    expected_end = end_dt.strftime("%Y-%m-%d %H:%M")
    check("每日时段内新建即开录",
          d.values["start_time"] == expected_start and d.values["end_time"] == expected_end,
          f"{d.values['start_time']}~{d.values['end_time']} != {expected_start}~{expected_end}")


def test_expired_waiting_restore() -> None:
    r = Recorder(AppSettings())
    r._save = lambda: None  # type: ignore[method-assign]
    now = datetime.now()
    past_start = (now - timedelta(hours=3)).replace(second=0, microsecond=0)
    past_end = (now - timedelta(hours=2)).replace(second=0, microsecond=0)
    weekly = RecordTask(
        id="old_w", channel="测试台", status=TaskStatus.WAITING.value,
        frequency="weekly", weekdays="0,1,2,3,4,5,6",
        time_start="09:00", time_end="10:00",
        start_time=past_start.strftime("%Y-%m-%d %H:%M"),
        end_time=past_end.strftime("%Y-%m-%d %H:%M"),
    )
    once = RecordTask(
        id="old_o", channel="测试台", status=TaskStatus.WAITING.value,
        frequency="once",
        start_time=past_start.strftime("%Y-%m-%d %H:%M"),
        end_time=past_end.strftime("%Y-%m-%d %H:%M"),
    )
    r._tasks = [weekly, once]
    r._restore()
    check("过期循环任务标记失败",
          weekly.status == TaskStatus.FAILED.value and "过期" in weekly.error,
          f"{weekly.status}/{weekly.error}")
    created = [t for t in r._tasks if t.id not in ("old_w", "old_o")]
    nxt = created[0] if len(created) == 1 else None
    check("循环任务续接新等待任务",
          nxt is not None and nxt.status == TaskStatus.WAITING.value
          and nxt.run_index == 1 and parse_time(nxt.start_time) > now,
          f"{[(t.id, t.status, t.start_time) for t in created]}")
    check("过期单次任务标记失败",
          once.status == TaskStatus.FAILED.value and "过期" in once.error,
          f"{once.status}/{once.error}")


def test_startup_active_task_launches() -> None:
    r = Recorder(AppSettings())
    r._save = lambda: None  # type: ignore[method-assign]
    now = datetime.now()
    start = (now - timedelta(minutes=10)).replace(second=0, microsecond=0)
    end = (now + timedelta(minutes=50)).replace(second=0, microsecond=0)
    task = RecordTask(
        id="active", channel="测试台", status=TaskStatus.WAITING.value,
        frequency="daily", time_start=start.strftime("%H:%M"),
        time_end=end.strftime("%H:%M"),
        start_time=start.strftime("%Y-%m-%d %H:%M"),
        end_time=end.strftime("%Y-%m-%d %H:%M"),
    )
    launched: list[str] = []
    r._launch = lambda t, retry=False: launched.append(t.id)  # type: ignore[method-assign]
    r._tasks = [task]
    r.start_timer()
    r.stop_timer()
    check("启动时立即开录时段内任务", launched == ["active"], str(launched))


def test_reschedule() -> None:
    r = Recorder(AppSettings())
    t = RecordTask(id="x", channel="c", frequency="daily", time_start="09:30", time_end="10:00",
                   start_time="2026-11-26 09:30", end_time="2026-11-26 10:00")
    ok = r._reschedule(t)
    check("循环重排成功", ok and t.start_time == "2026-11-27 09:30" and t.run_index == 1)
    check("重排后等待中", t.status == TaskStatus.WAITING.value)
    once = RecordTask(id="y", channel="c", frequency="once")
    check("单次不重排", r._reschedule(once) is False)


# ---------- 需求2：二级频道选择 ----------
def test_two_level_channel() -> None:
    d = RecordDialog(AppSettings(), CHANNELS, metrics())
    groups = [d.group_combo.itemText(i) for i in range(d.group_combo.count())]
    check("一级分组", groups == ["新闻", "体育"], f"{groups}")
    check("默认二级频道", [d.channel_combo.itemText(i) for i in range(d.channel_combo.count())]
          == ["新闻台", "财经台"])
    d.group_combo.setCurrentIndex(1)
    check("切分组刷新频道", [d.channel_combo.itemText(i) for i in range(d.channel_combo.count())]
          == ["体育台"])
    # 编辑时定位分组
    t = RecordTask(id="e", channel="财经台", url="http://b", frequency="once",
                   start_time="2026-12-01 10:00", end_time="2026-12-01 11:00")
    d2 = RecordDialog(AppSettings(), CHANNELS, metrics(), task=t)
    check("编辑定位频道", d2.channel_combo.currentText() == "财经台")


# ---------- 需求3：GB ----------
def test_gb_unit() -> None:
    d = RecordDialog(AppSettings(), CHANNELS, metrics())
    d.directory.setText(os.getcwd())
    d._update_hint()
    free_gb = shutil.disk_usage(os.getcwd()).free / (1024 ** 3)
    expected = f"{tr('磁盘空间')}: {free_gb:.1f} GB"
    check("磁盘空间按GB精确显示", d.hint.text() == expected, f"{d.hint.text()} != {expected}")
    check("磁盘空间不出现MB", "MB" not in d.hint.text(), d.hint.text())


# ---------- 新增：任务列表展示录制频率 ----------
def test_frequency_column() -> None:
    dlg = RecordTasksDialog(metrics())
    headers = [dlg.table.horizontalHeaderItem(i).text()
               for i in range(dlg.table.columnCount())]
    check("任务列表8列含录制频率", dlg.table.columnCount() == 8
          and headers[dlg.COL_FREQ] == tr("录制频率"), str(headers))
    tasks = [
        RecordTask(id="a", channel="甲", frequency="once", start_time="2026-12-01 09:00",
                   end_time="2026-12-01 10:00"),
        RecordTask(id="b", channel="乙", frequency="daily", start_time="2026-12-02 09:00",
                   end_time="2026-12-02 10:00"),
        RecordTask(id="c", channel="丙", frequency="weekly", start_time="2026-12-03 09:00",
                   end_time="2026-12-03 10:00"),
        RecordTask(id="d", channel="丁", frequency="custom", start_time="2026-12-04 09:00",
                   end_time="2026-12-04 10:00"),
        RecordTask(id="e", channel="戊", start_time="2026-12-05 09:00",
                   end_time="2026-12-05 10:00"),
    ]
    dlg.set_tasks(tasks)
    shown = [dlg.table.item(row, dlg.COL_FREQ).text()
             for row in range(dlg.table.rowCount())]
    check("频率列渲染四种类型及旧任务默认单次",
          shown == [tr("单次"), tr("每日"), tr("每周"), tr("自定义"), tr("单次")], str(shown))
    # 语言切换后表头与单元格同步刷新
    init_i18n("en")
    dlg.retranslate()
    en_headers = [dlg.table.horizontalHeaderItem(i).text()
                  for i in range(dlg.table.columnCount())]
    en_shown = [dlg.table.item(row, dlg.COL_FREQ).text()
                for row in range(dlg.table.rowCount())]
    check("频率列随语言切换",
          en_headers[dlg.COL_FREQ] == "Frequency"
          and en_shown[:4] == ["Once", "Daily", "Weekly", "Custom"],
          f"{en_headers[dlg.COL_FREQ]}/{en_shown}")
    init_i18n("zh_CN")
    dlg.retranslate()


# ---------- 新增：任务列表长文本悬浮提示 ----------
def test_task_table_tooltips() -> None:
    dlg = RecordTasksDialog(metrics())
    content = "超长录制内容" * 30
    output = "D:/record/" + "very-long-file-name-" * 20 + ".ts"
    task = RecordTask(
        id="tip", channel="测试台", content=content,
        start_time="2026-12-01 09:00", end_time="2026-12-01 10:00",
        output=output,
    )
    dlg.set_tasks([task])
    expected = {
        "录制内容": (dlg.COL_CONTENT, content),
        "时间区间": (dlg.COL_TIME, f"{task.start_time}\n→ {task.end_time}"),
        "输出文件": (dlg.COL_OUTPUT, output),
    }
    for name, (column, text) in expected.items():
        item = dlg.table.item(0, column)
        check(f"{name}悬浮显示全文", item is not None and item.toolTip() == text,
              item.toolTip() if item else "no item")


# ---------- 需求4：无媒体禁用按钮 ----------
def test_no_media_buttons() -> None:
    bar = ControlBar(metrics())
    check("初始播放按钮禁用", not bar.play_btn.isEnabled())
    check("初始快进按钮禁用", not bar.forward_btn.isEnabled())
    check("初始快退按钮禁用", not bar.rewind_btn.isEnabled())
    bar.set_has_media(True)
    check("有媒体恢复按钮", bar.play_btn.isEnabled() and bar.forward_btn.isEnabled())
    bar.set_live(True)
    check("直播禁用快进快退", not bar.forward_btn.isEnabled() and not bar.rewind_btn.isEnabled())
    bar.set_live(False)
    bar.set_has_media(False)
    check("停止后再次禁用", not bar.play_btn.isEnabled() and not bar.forward_btn.isEnabled())
    # 主窗口守卫
    win = MainWindow()
    win._toggle_play()  # 无媒体时应直接返回不报错
    win._forward()
    win._rewind()
    check("主窗口无媒体空操作不报错", True)
    win.recorder.shutdown()
    win.player.shutdown()
    win.close()


# ---------- 需求5：全音轨录制 ----------
def test_ffmpeg_all_tracks() -> None:
    cmd = ffmpeg_recorder.build_ffmpeg_cmd("http://x/live.m3u8", "D:/tmp/rec.ts")
    check("ffmpeg映射全部流", "-map" in cmd and "0" in cmd and "copy" in cmd)
    check("有可用ffmpeg", ffmpeg_recorder.has_ffmpeg())


def main() -> None:
    for fn in (
        test_frequency_ui, test_custom_no_default_today, test_frequency_values, test_next_occurrence,
        test_active_occurrence, test_dialog_immediate_recording,
        test_expired_waiting_restore, test_startup_active_task_launches,
        test_reschedule, test_two_level_channel, test_gb_unit, test_frequency_column,
        test_task_table_tooltips, test_no_media_buttons, test_ffmpeg_all_tracks,
    ):
        print(f"\n===== {fn.__name__} =====")
        fn()
    print("\n===== SUMMARY =====")
    if FAILED:
        print("FAILED:", ", ".join(FAILED))
        sys.exit(1)
    print("ALL_PASSED")


if __name__ == "__main__":
    main()
