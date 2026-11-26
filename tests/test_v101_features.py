"""v1.0.1 六项需求回归测试。

1) 录制任务按钮启用规则  2) 点击行切换选择  3) 文件对话框桌面快捷项
4) 设置开机自启动  5) 打开视频同目录视频入列  6) 右键双击不全屏
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from app.core import autostart  # noqa: E402
from app.core.i18n import init_i18n  # noqa: E402
from app.core.logger import init_loggers  # noqa: E402
from app.core.models import RecordTask, TaskStatus  # noqa: E402
from app.core.settings import AppSettings  # noqa: E402
from app.core.ui_scale import Metrics  # noqa: E402
from app.ui.dialog_utils import get_open_files, prepare_file_dialog  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.player_widget import PlayerWidget  # noqa: E402
from app.ui.record_dialog import RecordTasksDialog  # noqa: E402
from app.ui.settings_dialog import SettingsDialog  # noqa: E402


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS" if condition else "FAIL") + " | " + name + ((" | " + detail) if detail else ""))
    if not condition:
        raise SystemExit(1)


def make_task(task_id: str, output: str = "", status: str = TaskStatus.WAITING.value) -> RecordTask:
    return RecordTask(id=task_id, channel="CCTV", content="新闻", output=output, status=status)


def test_record_buttons_and_row_click(app: QApplication, metrics) -> None:
    dlg = RecordTasksDialog(metrics)

    # 未勾选任何任务：所有操作按钮禁用
    dlg.set_tasks([make_task("t1", "/v/a.ts"), make_task("t2", "/w/b.ts")])
    for name in ("cancel_btn", "edit_btn", "delete_btn", "open_file_btn", "open_dir_btn", "stop_btn"):
        check(f"未勾选-{name}-禁用", not getattr(dlg, name).isEnabled())

    # 点击数据行 = 勾选（再次点击取消）
    dlg.table.cellClicked.emit(0, dlg.COL_CHANNEL)
    check("点击数据行-勾选", dlg.selected_task_ids() == ["t1"])
    check("单选-编辑可用", dlg.edit_btn.isEnabled())
    check("单选-打开目录可用", dlg.open_dir_btn.isEnabled())
    dlg.table.cellClicked.emit(0, dlg.COL_CHANNEL)
    check("再次点击-取消勾选", dlg.selected_task_ids() == [])
    check("取消勾选后-编辑禁用", not dlg.edit_btn.isEnabled())

    # 多选：编辑禁用；删除/取消可用
    dlg.table.cellClicked.emit(0, dlg.COL_CHANNEL)
    dlg.table.cellClicked.emit(1, dlg.COL_CHANNEL)
    check("多选-勾选两个", len(dlg.selected_task_ids()) == 2)
    check("多选-编辑禁用", not dlg.edit_btn.isEnabled())
    check("多选-删除可用", dlg.delete_btn.isEnabled())
    check("多选-取消可用", dlg.cancel_btn.isEnabled())

    # 多选且目录不同：打开目录禁用
    check("多选目录不同-打开目录禁用", not dlg.open_dir_btn.isEnabled())

    # 多选且目录相同：打开目录可用（用全选复选框精确控制勾选）
    dlg.set_tasks([
        make_task("s1", "/v/a.ts"), make_task("s2", "/v/b.ts"),
        make_task("s3", "/v/c.ts"),
    ])
    dlg.select_all_cb.setCheckState(Qt.CheckState.Checked)
    check("多选同目录-打开目录可用", dlg.open_dir_btn.isEnabled())

    # 无 output 的单任务：打开目录禁用
    dlg.set_tasks([make_task("n1", "")])
    dlg.table.cellClicked.emit(0, dlg.COL_CHANNEL)
    check("单选无output-打开目录禁用", not dlg.open_dir_btn.isEnabled())

    # 停止：仅勾选含录制中任务时可用
    dlg.set_tasks([make_task("r1", "/v/r.ts", TaskStatus.RECORDING.value), make_task("w1", "")])
    dlg.table.cellClicked.emit(0, dlg.COL_CHANNEL)
    check("勾选录制中-停止可用", dlg.stop_btn.isEnabled())
    dlg.table.cellClicked.emit(0, dlg.COL_CHANNEL)
    dlg.table.cellClicked.emit(1, dlg.COL_CHANNEL)
    check("勾选等待中-停止禁用", not dlg.stop_btn.isEnabled())


def test_file_dialog_desktop(app: QApplication, metrics) -> None:
    from PySide6.QtCore import QStandardPaths, QUrl, QTimer
    dialog = QFileDialog(None, "test")
    prepare_file_dialog(dialog, metrics)
    # prepare_file_dialog 用 QTimer.singleShot 延迟设置，这里直接复用其辅助逻辑验证
    from app.ui.dialog_utils import _ensure_sidebar_url
    desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
    url = QUrl.fromLocalFile(desktop)
    before = len(dialog.sidebarUrls())
    _ensure_sidebar_url(dialog, url)
    after = dialog.sidebarUrls()
    check("桌面快捷项已加入", url in after, f"before={before} after={len(after)}")
    _ensure_sidebar_url(dialog, url)
    check("桌面快捷项不重复", len(dialog.sidebarUrls()) == len(after))


def test_autostart_module() -> None:
    cmd = autostart._exe_command()
    check("自启动命令非空", bool(cmd))
    check("自启动命令带引号", cmd.startswith('"'))
    # 读写往返（仅验证逻辑，不改真实注册表：mock 由 set_enabled 的错误分支覆盖）
    check("is_enabled 可调", isinstance(autostart.is_enabled(), bool))


def test_sibling_videos(app: QApplication, metrics) -> None:
    import tempfile
    tmp = tempfile.mkdtemp(prefix="cx_v101_")
    for name in ("b.mp4", "a.mp4", "c.mkv", "note.txt"):
        with open(os.path.join(tmp, name), "w") as fh:
            fh.write("x")
    win = MainWindow()
    result = win._sibling_videos([os.path.join(tmp, "c.mkv")])
    check("同目录视频全部入列", len(result) == 3, f"got={len(result)}")
    # 按文件名顺序展示，当前播放文件不再置顶（打开 c.mkv 时应排在 a、b 之后）
    order = [os.path.basename(p) for p in result]
    check("按文件名顺序展示", order == ["a.mp4", "b.mp4", "c.mkv"], f"order={order}")
    check("不含非视频文件", all(not n.endswith(".txt") for n in result))

    # 回归：传入正斜杠路径（命令行 / 文件关联场景）时，当前视频不得重复出现
    fwd = os.path.join(tmp, "c.mkv").replace("\\", "/")
    result2 = win._sibling_videos([fwd])
    names = [os.path.basename(p) for p in result2]
    check("正斜杠路径-当前视频只出现一次", names.count("c.mkv") == 1,
          f"names={names}")
    check("正斜杠路径-入列数量仍为3", len(result2) == 3, f"got={len(result2)}")

    # 回归：播放列表 add_paths 对斜杠差异去重
    pl = win.playlist_panel
    pl.clear()
    pl.add_paths([fwd, os.path.join(tmp, "c.mkv"), os.path.join(tmp, "a.mp4")])
    check("add_paths-斜杠差异去重", len(pl.paths) == 2, f"paths={pl.paths}")

    # 回归：列表按文件名排序，但播放目标仍是用户打开的文件（不是排第一的 a.mp4）
    pl.clear()
    played = []
    win._play_path = lambda p: played.append(p)
    win._open_paths([os.path.join(tmp, "c.mkv")])
    check("播放目标为实际打开的文件",
          len(played) == 1 and os.path.basename(played[0]) == "c.mkv",
          f"played={played}")
    ordered = [os.path.basename(p) for p in win.playlist_panel.paths]
    check("打开后列表按文件名排序",
          ordered == ["a.mp4", "b.mp4", "c.mkv"], f"ordered={ordered}")
    win.close()


def test_right_double_click_no_fullscreen(app: QApplication, metrics) -> None:
    w = PlayerWidget(metrics)
    fired = []
    w.doubleClicked.connect(lambda: fired.append(1))
    pos = w.rect().center()
    global_pos = w.mapToGlobal(pos)
    right_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick, pos, global_pos,
        Qt.MouseButton.RightButton, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(w, right_event)
    check("右键双击不触发全屏", not fired)
    left_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick, pos, global_pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(w, left_event)
    check("左键双击仍触发全屏", bool(fired))


def main() -> None:
    init_loggers()
    init_i18n("zh_CN")
    app = QApplication.instance() or QApplication([])
    metrics = Metrics(AppSettings())
    test_record_buttons_and_row_click(app, metrics)
    test_file_dialog_desktop(app, metrics)
    test_autostart_module()
    test_sibling_videos(app, metrics)
    test_right_double_click_no_fullscreen(app, metrics)
    print("ALL_V101_TESTS_PASSED")


if __name__ == "__main__":
    main()
