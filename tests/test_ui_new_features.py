"""验证右上倍速徽标与视频区/工具栏拖拽移动窗口。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDateTime, QEventLoop, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QDialog, QMenu, QMessageBox, QPushButton,
)

from app.core.i18n import init_i18n, tr  # noqa: E402
from app.core.logger import init_loggers  # noqa: E402
from app.core.models import Channel, TaskStatus, format_speed  # noqa: E402
from app.core.settings import AppSettings  # noqa: E402
from app.core import ui_scale  # noqa: E402
from app.core.theme import apply_theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.record_dialog import RecordDialog  # noqa: E402


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS" if condition else "FAIL") + " | " + name + ((" | " + detail) if detail else ""))
    if not condition:
        raise SystemExit(1)


def mouse_seq(widget, event_type, pos, global_pos, button, buttons):
    event = QMouseEvent(event_type, pos, global_pos, button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


def drag(widget, start_local, delta):
    win = widget.window()
    start_global = widget.mapToGlobal(start_local)
    mouse_seq(widget, QEvent.Type.MouseButtonPress, start_local, start_global,
              Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    for step in range(1, 6):
        frac = step / 5.0
        local = start_local + delta * frac
        global_pos = start_global + delta * frac
        mouse_seq(widget, QEvent.Type.MouseMove, local, global_pos,
                  Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    end_local = start_local + delta
    end_global = start_global + delta
    mouse_seq(widget, QEvent.Type.MouseButtonRelease, end_local, end_global,
              Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)


from PySide6.QtCore import QEvent  # noqa: E402


def check_record_tasks(app) -> None:
    """IPTV 录制入口迁移、电视台下拉选择与到点开录端到端回归。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    store_path = os.path.join(root, "recordings.json")
    backup = open(store_path, "rb").read() if os.path.isfile(store_path) else None
    tmp = tempfile.mkdtemp(prefix="cx_record_test_")
    video = os.path.join(tmp, "channel.mp4")
    warnings = []
    original_warning = QMessageBox.warning
    original_exec = RecordDialog.exec
    try:
        ffmpeg = shutil.which("ffmpeg")
        check("本机 ffmpeg 可用", bool(ffmpeg), str(ffmpeg))
        subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
             "-i", "testsrc=size=320x240:rate=15", "-t", "3",
             "-pix_fmt", "yuv420p", video],
            check=True,
        )
        window = MainWindow()
        window.apply_appearance()
        app.processEvents()

        # 1. IPTV 抽屉页不再有录制任务区与新建按钮
        check("IPTV 页移除录制任务表格", not hasattr(window.iptv_panel, "table"))
        check("IPTV 页移除新建录制任务按钮",
              not hasattr(window.iptv_panel, "record_btn")
              and all(b.text() != tr("新建录制任务")
                      for b in window.iptv_panel.findChildren(QPushButton)))

        # 2. 新建/显示录制任务直接作为 IPTV 下的二级菜单项，无中间子菜单
        iptv_menu = next(
            (m for m in window._menubar.findChildren(QMenu) if m.title() == "IPTV"), None
        )
        check("IPTV 菜单存在", iptv_menu is not None)
        if iptv_menu is None:
            return
        iptv_texts = [a.text() for a in iptv_menu.actions()]
        check("IPTV 直接包含新建与显示录制任务",
              tr("新建录制任务") in iptv_texts
              and tr("显示录制任务") in iptv_texts, str(iptv_texts))
        check("IPTV 下无录制任务中间子菜单",
              all(a.menu() is None or a.text() != tr("录制任务")
                  for a in iptv_menu.actions()))

        # 2b. IPTV 页导出为图标按钮（悬浮文字），编辑/删除按钮宽度跨语言一致
        panel = window.iptv_panel
        check("导出按钮为图标按钮", panel.export_btn.objectName() == "iconButton"
              and not panel.export_btn.text()
              and panel.export_btn.toolTip() == tr("导出"))
        edit_width, delete_width = panel.edit_btn.width(), panel.delete_btn.width()
        check("编辑/删除按钮初始有固定宽度", edit_width > 0 and delete_width > 0,
              f"{edit_width}/{delete_width}")
        for lang in ("en", "zh_TW", "zh_CN"):
            window.settings.language = lang
            window._on_settings_applied()
            app.processEvents()
            check(f"{lang}: 按钮宽度不变",
                  (panel.edit_btn.width(), panel.delete_btn.width()) == (edit_width, delete_width),
                  f"{panel.edit_btn.width()}/{panel.delete_btn.width()}")
            check(f"{lang}: 按钮文字显示完整",
                  panel.edit_btn.fontMetrics().horizontalAdvance(panel.edit_btn.text())
                  < panel.edit_btn.width()
                  and panel.delete_btn.fontMetrics().horizontalAdvance(panel.delete_btn.text())
                  < panel.delete_btn.width())

        # 2c. 录制任务窗口：三个长文案按钮三语等宽且文字完整；8 列含选择/创建时间/录制频率、无操作列
        dlg = window.tasks_dialog
        headers = [dlg.table.horizontalHeaderItem(i).text()
                   for i in range(dlg.table.columnCount())]
        check("录制任务表新增选择、创建时间与录制频率列、去掉操作列",
              dlg.table.columnCount() == 8
              and tr("选择") in headers and tr("创建时间") in headers
              and tr("录制频率") in headers
              and tr("操作") not in headers, str(headers))
        check("录制任务窗口已加宽", dlg.width() >= 1100 and dlg.minimumWidth() >= 970,
              f"{dlg.width()}/{dlg.minimumWidth()}")
        long_buttons = (("new_btn", "新建录制任务"),
                        ("open_file_btn", "打开文件"),
                        ("open_dir_btn", "打开目录"))
        widths_before = {attr: getattr(dlg, attr).width() for attr, _ in long_buttons}
        for lang in ("en", "zh_TW", "zh_CN"):
            window.settings.language = lang
            window._on_settings_applied()
            app.processEvents()
            for attr, source in long_buttons:
                button = getattr(dlg, attr)
                check(f"{lang}: {source} 宽度不变",
                      button.width() == widths_before[attr],
                      f"{button.width()} vs {widths_before[attr]}")
                check(f"{lang}: {source} 文字显示完整",
                      button.fontMetrics().horizontalAdvance(button.text()) < button.width(),
                      f"text={button.text()} width={button.width()}")

        # 3. 电视台改为不可编辑下拉，且只能选已导入频道
        channels = [Channel(name="测试台", url=video, group="测试")]
        window.iptv_panel.set_channels(channels)
        dialog = RecordDialog(window.settings, channels, window.metrics, parent=window)
        check("电视台下拉不可编辑", not dialog.channel_combo.isEditable())
        check("分组下拉包含测试分组",
              "测试" in [dialog.group_combo.itemText(i) for i in range(dialog.group_combo.count())])
        check("电视台选项来自频道列表",
              dialog.channel_combo.count() == 1
              and isinstance(dialog.channel_combo.itemData(0), Channel)
              and dialog.channel_combo.itemData(0).url == video)
        QMessageBox.warning = lambda *args, **kwargs: warnings.append(args) or QMessageBox.StandardButton.Ok
        empty = RecordDialog(window.settings, [], window.metrics, parent=window)
        empty._on_ok()
        check("无频道时拒绝创建任务", not hasattr(empty, "values") and len(warnings) == 1,
              str(warnings))
        now = datetime.now()
        dialog.start.setDateTime(QDateTime.fromString(
            (now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M"), "yyyy-MM-dd HH:mm"))
        dialog.end.setDateTime(QDateTime.fromString(
            (now + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M"), "yyyy-MM-dd HH:mm"))
        dialog.directory.setText(os.path.join(tmp, "out"))
        dialog._on_ok()
        check("选定频道带出真实 URL",
              getattr(dialog, "values", {}).get("url") == video,
              str(getattr(dialog, "values", {})))
        QMessageBox.warning = original_warning

        # 4. 菜单新建任务真正写入列表（原 dialog.Accepted 会抛 AttributeError）
        def fake_exec(self):
            self.channel_combo.setCurrentIndex(0)
            self.start.setDateTime(QDateTime.currentDateTime().addSecs(-60))
            self.end.setDateTime(QDateTime.currentDateTime().addSecs(120))
            self.directory.setText(os.path.join(tmp, "out"))
            self._on_ok()
            return QDialog.DialogCode.Accepted

        RecordDialog.exec = fake_exec
        try:
            window._new_task()
        finally:
            RecordDialog.exec = original_exec
        # 先停表，避免到点任务在断言前就自动开录，便于验证等待中状态。
        window.recorder.stop_timer()
        app.processEvents()
        check("新建任务加入录制列表", len(window.recorder.tasks) == 1,
              str([t.channel for t in window.recorder.tasks]))
        check("独立任务窗口同步显示", window.tasks_dialog.table.rowCount() == 1,
              str(window.tasks_dialog.table.rowCount()))
        if not window.recorder.tasks:
            return
        task = window.recorder.tasks[-1]
        check("任务记录含创建时间（yyyy-MM-dd HH:mm:ss）",
              len(task.created_at) == 19 and task.created_at[4] == "-"
              and task.created_at[13] == ":", task.created_at)
        dlg = window.tasks_dialog
        dlg.table.selectRow(0)
        app.processEvents()
        check("未勾选任务-停止按钮禁用", not dlg.stop_btn.isEnabled(),
              f"status={task.status}")

        # 5. 到点真正开录并生成文件
        window.recorder.start_timer()
        loop = QEventLoop()
        QTimer.singleShot(4000, loop.quit)
        loop.exec()
        check("到点进入录制中", task.status == TaskStatus.RECORDING.value,
              f"status={task.status} error={task.error}")
        check("录制输出文件已生成",
              bool(task.output) and os.path.isfile(task.output)
              and os.path.getsize(task.output) > 0, str(task.output))
        dlg.set_tasks(list(window.recorder.tasks))
        dlg.table.selectRow(0)
        # 新规则：停止按钮依据勾选集合（点击数据行=勾选）
        dlg.table.cellClicked.emit(0, dlg.COL_CHANNEL)
        app.processEvents()
        check("勾选录制中任务-停止按钮可用", dlg.stop_btn.isEnabled())
        window.recorder.stop_task(task.id)
        app.processEvents()

        # 6. 列表全选 + 批量删除
        window.recorder.stop_timer()
        dlg.set_tasks(list(window.recorder.tasks))
        app.processEvents()
        before_delete = len(window.recorder.tasks)
        dlg.select_all_cb.setCheckState(Qt.CheckState.Checked)
        app.processEvents()
        check("全选勾选所有行",
              len(dlg.selected_task_ids()) == dlg.table.rowCount() == before_delete,
              f"{len(dlg.selected_task_ids())}/{dlg.table.rowCount()}/{before_delete}")
        dlg._delete_selected()
        app.processEvents()
        check("全选批量删除生效", len(window.recorder.tasks) == 0,
              str([t.channel for t in window.recorder.tasks]))
    finally:
        QMessageBox.warning = original_warning
        RecordDialog.exec = original_exec
        if "window" in locals():
            window.recorder.shutdown()
        if backup is None:
            if os.path.isfile(store_path):
                os.remove(store_path)
        else:
            with open(store_path, "wb") as fh:
                fh.write(backup)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    ui_scale.configure_high_dpi()
    app = QApplication.instance() or QApplication(sys.argv)
    init_loggers()
    init_i18n("zh_CN")
    settings = AppSettings()
    metrics = ui_scale.Metrics(settings)
    apply_theme(app, settings.theme, metrics)
    metrics.apply_font(app)
    window = MainWindow()
    window.show()
    app.processEvents()

    # 1. 倍速徽标存在且初始文本为 1.0x
    badge = window.title_bar.speed_btn
    check("倍速徽标存在", badge is not None)
    check("倍速徽标初始文本", badge.text() == "1.0x", badge.text())
    check("浮点噪声吸附", format_speed(0.7500000001) == "0.75x", format_speed(0.7500000001))
    check("整数速度保留一位小数", format_speed(2.0) == "2.0x", format_speed(2.0))

    # 徽标位于比例徽标左侧：两者同一布局中，索引顺序正确
    layout = window.title_bar.layout()
    idx_speed = layout.indexOf(badge)
    idx_scale = layout.indexOf(window.title_bar.scale_label)
    check("倍速徽标位于比例徽标左侧", 0 <= idx_speed < idx_scale,
          f"speed={idx_speed}, scale={idx_scale}")

    # 2. 速度变化同步徽标（不弹 toast），且选择多少就展示多少
    # 先清除启动时"未打开视频"提示，确保只观察速度变化是否弹提示
    window.status_toast.hide()
    # 直连槽为同步调用，emit 后即刻断言；避免 processEvents 触发 mpv 异步回调覆盖
    for value, expected in (
        (0.5, "0.5x"), (0.75, "0.75x"), (0.9, "0.9x"),
        (1.1, "1.1x"), (1.25, "1.25x"), (1.5, "1.5x"), (2.0, "2.0x"),
    ):
        window.player.speedChanged.emit(value)
        check(f"速度 {value} 按实际值展示", badge.text() == expected, badge.text())
        action = window.speed_actions.get(value)
        check(f"速度 {value} 菜单文本与徽标一致",
              action is not None and action.text() == expected,
              action.text() if action else "无菜单项")
    check("速度变化不再显示下方提示", not window.status_toast.isVisible())

    # 恢复默认速度供后续验证
    window.player.speedChanged.emit(1.0)
    check("默认速度徽标", badge.text() == "1.0x", badge.text())

    # 3. 拖拽视频区移动窗口
    window.raise_()
    before = window.pos()
    video = window.player_widget
    center = QPoint(video.width() // 2, video.height() // 2)
    drag(video, center, QPoint(60, 40))
    after = window.pos()
    check("视频区拖拽移动窗口", after - before == QPoint(60, 40),
          f"before={before}, after={after}")

    # 4. 拖拽底部控制栏移动窗口（非交互空白区域）
    before = window.pos()
    control = window.control
    blank = QPoint(control.width() // 2, control.height() // 2)
    # 寻找非按钮/非滑块的子控件点：直接用控制栏本身中间位置
    drag(control, blank, QPoint(-40, 30))
    after = window.pos()
    check("控制栏拖拽移动窗口", after - before == QPoint(-40, 30),
          f"before={before}, after={after}")

    # 5. 缩放边缘仍优先于移动（左边缘拖拽改尺寸而非移动）
    before_pos = window.pos()
    before_size = window.size()
    edge_local = QPoint(2, window.height() // 2)
    drag(window, edge_local, QPoint(30, 0))
    check("边缘缩放优先", window.size().width() != before_size.width()
          or window.pos() != before_pos,
          f"size {before_size}->{window.size()}, pos {before_pos}->{window.pos()}")

    # 6. 底部控制栏高度为原基准的 70%（34px @ 100%）
    expected_h = window.metrics.s(34)
    check("底部控制栏高度 70%", window.control.height() == expected_h,
          f"height={window.control.height()}, expected={expected_h}")

    # 7. 全屏浮层与退出行为
    window.showMaximized()
    app.processEvents()
    max_size = window.size()
    window._toggle_fullscreen()
    app.processEvents()
    check("进入全屏", window._fullscreen and window.isFullScreen())
    check("全屏标题栏默认隐藏", not window.title_bar.isVisible())
    check("全屏控制栏默认隐藏", not window.control.isVisible())
    video_h = window.player_widget.height()
    check("全屏视频区铺满", video_h >= window.centralWidget().height() - 1,
          f"video={video_h}, central={window.centralWidget().height()}")

    top_pos = QPoint(window.width() // 2, 2)
    mouse_seq(window, QEvent.Type.MouseMove, top_pos, window.mapToGlobal(top_pos),
              Qt.MouseButton.NoButton, Qt.MouseButton.NoButton)
    app.processEvents()
    check("鼠标到顶部标题栏滑入", window._fs_top_visible)
    mid_pos = QPoint(window.width() // 2, window.height() // 2)
    mouse_seq(window, QEvent.Type.MouseMove, mid_pos, window.mapToGlobal(mid_pos),
              Qt.MouseButton.NoButton, Qt.MouseButton.NoButton)
    app.processEvents()
    check("鼠标离开顶部标题栏隐藏", not window._fs_top_visible)

    bottom_pos = QPoint(window.width() // 2, window.height() - 2)
    mouse_seq(window, QEvent.Type.MouseMove, bottom_pos, window.mapToGlobal(bottom_pos),
              Qt.MouseButton.NoButton, Qt.MouseButton.NoButton)
    app.processEvents()
    check("鼠标到底部控制栏滑入", window._fs_bottom_visible)
    check("浮层不影响视频尺寸", window.player_widget.height() == video_h,
          f"before={video_h}, after={window.player_widget.height()}")

    calls = {"n": 0}
    # v1.0.2：无媒体时播放/暂停被守卫拦截，测试需先置位媒体状态。
    window._current_path = "dummy-media"
    original_toggle = window.player.play_pause
    window.player.play_pause = lambda: calls.__setitem__("n", calls["n"] + 1)
    QTest.keyClick(window, Qt.Key.Key_Space)
    app.processEvents()
    check("全屏 Space 播放/暂停", calls["n"] == 1, str(calls["n"]))
    window.player.play_pause = original_toggle
    # 保留媒体状态，供后续左右键快进快退快捷键测试使用。

    QTest.keyClick(window, Qt.Key.Key_Return)
    app.processEvents()
    check("Enter 退出全屏", not window._fullscreen and not window.isFullScreen())
    check("Enter 恢复最大化尺寸", window.isMaximized()
          and abs(window.width() - max_size.width()) <= 2
          and abs(window.height() - max_size.height()) <= 2,
          f"now={window.size()}, before={max_size}")
    # 回归：退出全屏后控制栏/进度条必须插回视频区下方，不能跑到上方
    layout = window.centralWidget().layout()
    order = [layout.itemAt(i).widget() for i in range(layout.count())]
    expected_order = [window.title_bar, window._menubar, window.player_widget,
                      window.progress, window.control]
    check("退出全屏布局顺序正确", order == expected_order,
          str([getattr(w, "objectName", lambda: "?")() for w in order]))
    check("退出全屏控制栏在视频区下方",
          window.control.y() >= window.player_widget.y() + window.player_widget.height() - 2,
          f"control.y={window.control.y()}, player.bottom={window.player_widget.y() + window.player_widget.height()}")

    window._toggle_fullscreen()
    app.processEvents()
    QTest.keyClick(window, Qt.Key.Key_Escape)
    app.processEvents()
    check("Esc 退出全屏", not window._fullscreen and not window.isFullScreen())
    check("Esc 恢复最大化尺寸", window.isMaximized())

    window._toggle_fullscreen()
    app.processEvents()
    window.title_bar.window_buttons["restore"][0].click()
    app.processEvents()
    check("全屏最大化按钮退出全屏", not window._fullscreen and not window.isFullScreen())
    check("全屏最大化按钮恢复最大化尺寸", window.isMaximized())

    # 8. 全屏播放列表浮层：不得遮挡底部控制栏列表按钮，可再次点击收缩
    window._toggle_fullscreen()
    app.processEvents()
    check("全屏播放列表 dock 从停靠布局移出", window.dock.parent() is window.centralWidget())
    window._set_playlist_visible(True)
    app.processEvents()
    check("全屏中列表可显示", window.dock.isVisible())
    check("全屏列表浮层不覆盖进度条",
          window.dock.y() + window.dock.height() <= window.progress.y() + 1,
          f"dock.bottom={window.dock.y() + window.dock.height()}, progress.y={window.progress.y()}")
    check("全屏列表浮层不覆盖控制栏",
          window.dock.y() + window.dock.height() <= window.control.y() + 1,
          f"dock.bottom={window.dock.y() + window.dock.height()}, control.y={window.control.y()}")
    # 模拟再次点击列表按钮收缩
    window._toggle_playlist_dock()
    app.processEvents()
    check("全屏中列表可再次收缩", not window.dock.isVisible())
    window._exit_fullscreen()
    app.processEvents()
    check("退出全屏列表恢复停靠", window.dock.parent() is window)

    # 9. 全屏左右键快进/快退（独立 QShortcut，隐藏菜单栏后仍生效）
    window.showMaximized()
    app.processEvents()
    window._toggle_fullscreen()
    app.processEvents()
    seek_calls = []
    original_seek = window.player.seek
    window.player.seek = lambda value, absolute=False: seek_calls.append((value, absolute))
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Right)
    app.processEvents()
    window.player.seek = original_seek
    step = window.settings.seek_step
    check("全屏左右键快进快退触发", seek_calls == [(-step, False), (step, False)],
          str(seek_calls))
    window._exit_fullscreen()
    app.processEvents()

    check_record_tasks(app)

    print("\nALL UI FEATURE CHECKS PASSED")


if __name__ == "__main__":
    main()
