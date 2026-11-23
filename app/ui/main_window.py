"""主窗口：自定义科技风标题栏、菜单、播放区、进度条、控制栏、右侧抽屉与全局同步。"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from typing import List, Optional

from PySide6.QtCore import (
    Qt, QTimer, Signal, QPoint, QEvent, QRect, QSize, QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QCursor, QKeySequence, QMouseEvent,
    QShortcut, QPainter, QPen,
)
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSlider, QAbstractSpinBox, QApplication, QComboBox,
    QDialog, QDockWidget, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QPushButton, QSizePolicy, QScrollBar, QSlider,
    QStyle, QStyleOptionSlider, QTabWidget, QVBoxLayout, QWidget, QMenuBar,
)

from ..core.i18n import i18n, init_i18n, tr
from ..core.logger import init_loggers, log_error, log_info
from ..core.qt_translator import install_qt_translator
from ..core.media_info import MediaInfoCache, codec_label
from ..core.models import Channel, MediaInfo, RecordTask, TaskStatus, format_speed
from ..core.m3u_parser import export_m3u, parse_m3u
from ..core.mpv_player import MpvPlayer
from ..core.recorder import Recorder
from ..core.settings import AppSettings, app_root
from ..core.theme import apply_theme, palette
from ..core import ui_scale as uiscale
from ..version import APP_VERSION
from .control_bar import ControlBar
from .dialog_utils import (
    TextInputDialog, centered_buttons, compact_button, get_existing_directory,
    get_open_files, get_save_file,
)
from .icons import icon
from .iptv_panel import IptvPanel
from .osd_overlay import OsdOverlay
from .player_widget import PlayerWidget
from .playlist_panel import PlaylistPanel
from .properties_dialog import PropertiesDialog
from .record_dialog import RecordDialog, RecordTasksDialog
from .screenshot_dialogs import ContinuousDialog, ThumbnailDialog
from .settings_dialog import SettingsDialog
from .widget_utils import app_pixmap, auto_retranslate, mark_dynamic, set_window_icon, translate_standard_buttons

# Windows 原生无边框窗口缩放：靠 WM_NCHITTEST 让系统识别四边/四角并给出 resize 光标，
# WM_SIZING 中按视频宽高比约束矩形。比自绘透明拖拽条更稳，且与自定义标题栏拖动共存。
WM_NCHITTEST = 0x0084
WM_SIZING = 0x0214
HTCLIENT = 1
HTCAPTION = 2
HTLEFT, HTRIGHT = 10, 11
HTTOP, HTTOPLEFT, HTTOPRIGHT = 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
WMSZ_LEFT, WMSZ_RIGHT = 1, 2
WMSZ_TOP, WMSZ_TOPLEFT, WMSZ_TOPRIGHT = 3, 4, 5
WMSZ_BOTTOM, WMSZ_BOTTOMLEFT, WMSZ_BOTTOMRIGHT = 6, 7, 8


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG), ("top", wintypes.LONG),
        ("right", wintypes.LONG), ("bottom", wintypes.LONG),
    ]


class SeekSlider(QSlider):
    """进度条：点击任意位置直接跳转，拖拽同样按绝对位置定位。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._dragging = False
        # 保存章节时间点（秒）；进度条 range 会随 duration 动态变化，
        # 因此绘制时按 start/duration 比例计算像素位置。
        self._chapter_starts: list[float] = []
        self._chapter_duration = 0.0

    def set_chapters(self, chapters: list, duration: float) -> None:
        """设置章节时间点，换片时传空列表清除。"""
        starts: list[float] = []
        if chapters and duration and duration > 0:
            for chapter in chapters:
                try:
                    start = float(chapter.get("start", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if 0 < start < duration and start not in starts:
                    starts.append(start)
        if starts != self._chapter_starts or duration != self._chapter_duration:
            self._chapter_starts = starts
            self._chapter_duration = float(duration or 0)
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._chapter_starts or self._chapter_duration <= 0 or self.maximum() <= self.minimum():
            return
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self
        )
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self
        )
        span = groove.width() - handle.width()
        if span <= 0:
            return
        p = palette()
        painter = QPainter(self)
        pen = QPen(QColor(p["accent"]), 2)
        painter.setPen(pen)
        x0 = groove.left() + handle.width() // 2
        y = groove.center().y()
        height = max(6, groove.height() // 2)
        for start in self._chapter_starts:
            ratio = max(0.0, min(1.0, start / self._chapter_duration))
            x = x0 + int(round(span * ratio))
            painter.drawLine(x, y - height // 2, x, y + height // 2)
        painter.end()

    def _value_from_x(self, x: float) -> int:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self
        )
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self
        )
        span = groove.width() - handle.width()
        if span <= 0:
            return self.value()
        pos = int(x) - groove.left() - handle.width() // 2
        ratio = max(0, min(span, pos)) / span
        return self.minimum() + round(ratio * (self.maximum() - self.minimum()))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            self._dragging = True
            self.setValue(self._value_from_x(event.position().x()))
            self.sliderPressed.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging and self.maximum() > self.minimum():
            self.setValue(self._value_from_x(event.position().x()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging:
            self._dragging = False
            self.sliderReleased.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class TitleBar(QWidget):
    def __init__(self, main_window, metrics, parent=None) -> None:
        super().__init__(parent)
        self.main_window = main_window
        self.m = metrics
        self.setObjectName("titleBar")
        self.setFixedHeight(metrics.s(32))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(metrics.s(10), 0, metrics.s(4), 0)
        layout.setSpacing(metrics.s(5))

        self.window_buttons = {}
        logo_size = metrics.s(18)
        self.logo_label = QLabel()
        self.logo_label.setObjectName("appLogo")
        self.logo_label.setPixmap(app_pixmap(logo_size))
        self.logo_label.setFixedSize(logo_size, logo_size)
        self.logo_label.setScaledContents(True)
        self.logo_label.setToolTip(tr("应用名称"))
        self.title_label = QLabel(tr("应用名称"))
        self.title_label.setObjectName("titleText")
        self.title_label.setProperty("source_text", "应用名称")
        version = QLabel(APP_VERSION)
        version.setObjectName("versionText")
        mark_dynamic(version)
        layout.addWidget(self.logo_label)
        layout.addWidget(self.title_label)
        layout.addWidget(version)
        layout.addStretch(1)

        # 标题栏正中显示当前媒体文件名
        self.media_name = QLabel("")
        self.media_name.setObjectName("mediaName")
        self.media_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.media_name.setSizePolicy(
            self.media_name.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Ignored
        )
        mark_dynamic(self.media_name)
        layout.addWidget(self.media_name, 1)
        layout.addStretch(1)

        # 右上角倍速徽标：位于比例（UI 缩放）徽标左侧，点击直接选择倍速
        self.speed_btn = QPushButton("1.0x")
        self.speed_btn.setObjectName("speedBadge")
        self.speed_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.speed_btn.setToolTip(tr("点击切换播放速度"))
        mark_dynamic(self.speed_btn)
        self.speed_btn.clicked.connect(self.main_window._show_speed_menu)
        layout.addWidget(self.speed_btn)

        self.scale_label = QLabel("")
        self.scale_label.setObjectName("scaleBadge")
        mark_dynamic(self.scale_label)
        layout.addWidget(self.scale_label)

        for name, tip, slot in (
            ("minimize", "最小化", self.main_window.showMinimized),
            ("restore", "最大化/还原", self.main_window._toggle_maximize),
            ("close", "退出", self.main_window.close),
        ):
            button = QPushButton()
            button.setObjectName("winButton" + ("Close" if name == "close" else ""))
            button.setIcon(icon(name, "#aab6cb"))
            button.setToolTip(tr(tip))
            button.setFixedSize(metrics.s(30), metrics.s(30))
            button.clicked.connect(slot)
            layout.addWidget(button)
            self.window_buttons[name] = (button, tip)

        self._drag_pos = None

    def apply_scale(self) -> None:
        """缩放变化时重建固定尺寸，避免标题栏停留在创建时的比例。"""
        m = self.m
        self.setFixedHeight(m.s(32))
        logo_size = m.s(18)
        self.logo_label.setFixedSize(logo_size, logo_size)
        self.logo_label.setPixmap(app_pixmap(logo_size))
        for button, _ in self.window_buttons.values():
            button.setFixedSize(m.s(30), m.s(30))

    def retranslate(self) -> None:
        name = tr("应用名称")
        self.title_label.setText(name)
        self.logo_label.setToolTip(name)
        self.speed_btn.setToolTip(tr("点击切换播放速度"))
        for button, tip in self.window_buttons.values():
            button.setToolTip(tr(tip))

    def set_speed(self, value: float) -> None:
        """更新右上角倍速徽标文本，按实际选择值显示（如 0.75x / 1.0x）。"""
        self.speed_btn.setText(format_speed(value))

    def set_media_name(self, name: str) -> None:
        """标题栏中间显示当前媒体文件名。"""
        self.media_name.setText(name or "")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.main_window._fullscreen:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.main_window.pos()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self.main_window.isMaximized():
                self.main_window.showNormal()
            self.main_window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.main_window._toggle_maximize()


class PlaylistDock(QDockWidget):
    """右侧抽屉：宽度只由 UI 缩放决定，不随中英文文案长短而变化。"""

    def __init__(self, title: str, width: int, parent=None) -> None:
        super().__init__(title, parent)
        self._hint_width = max(1, int(width))

    def set_stable_width(self, width: int) -> None:
        self._hint_width = max(1, int(width))

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        hint.setWidth(self._hint_width)
        return hint

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        hint.setWidth(self._hint_width)
        return hint


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        init_loggers()
        self.settings = AppSettings()
        expired = self.settings.purge_expired_positions()
        if expired:
            log_info(f"[记忆位置] 清理 {expired} 条超过 "
                     f"{self.settings.POSITION_EXPIRE_DAYS} 天未播放的记录")
        self.metrics = uiscale.Metrics(self.settings)
        self.i18n = i18n()
        self.player = MpvPlayer(self)
        self.info_cache = MediaInfoCache(self)
        self.recorder = Recorder(self.settings, self)
        self.playlist: list[str] = []
        self._current_path = ""
        self._live = False
        self._position_observed = False  # 本次打开文件是否真正播放过（>1s）
        # 记忆播放位置：定时保存，避免播放中直接退出丢失进度
        self._position_timer = QTimer(self)
        self._position_timer.setInterval(5000)
        self._position_timer.timeout.connect(self._save_playback_position)
        self._position_timer.start()
        self._last_media_info: Optional[MediaInfo] = None
        # 命令行/文件关联传入的待播文件：mpv 内核延迟到事件循环首轮初始化，
        # 故先入队，等 readyChanged(True) 后再真正打开，避免竞态导致有标题无画面。
        self._pending_launch_files: list[str] = []
        self._fullscreen = False
        self._normal_geometry = None
        self._was_maximized_before_fullscreen = False
        self._dock_visible_before_fullscreen = False
        self._full_overlay_widgets: list[tuple[QWidget, int]] = []
        self._fs_top_visible = False
        self._fs_bottom_visible = False
        self._fs_top_h = 0
        self._fs_bottom_h = 0
        self._scrubbing_active = False
        self.speed_actions: dict[float, QAction] = {}
        # 无边框窗口：按视频分辨率比例锁定缩放。打开视频前不锁定，自由缩放。
        self._video_aspect = 16.0 / 9.0
        self._aspect_locked = False
        self._resize_margin = self.metrics.s(8)
        # 四边/四角拖拽缩放状态（Qt 事件过滤器方案，兼容高 DPI）。
        self._resize_edge = ""              # 方向：l/r/t/b 及其组合
        self._resize_origin: QRect | None = None
        self._resize_global = QPoint()
        self._resize_chrome_h = 0
        # 视频区/下方工具栏拖拽移动窗口状态（不与边缘缩放冲突）
        self._move_dragging = False
        self._move_active = False
        self._move_origin = QPoint()
        self._move_global = QPoint()

        self.setWindowTitle(tr("应用名称"))
        set_window_icon(self)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMinimumSize(self.metrics.s(880), self.metrics.s(560))
        self.resize(self.metrics.s(1180), self.metrics.s(720))

        self._build_ui()
        self._build_menus()
        self._build_shortcuts()
        self._connect_signals()
        self._style_dock_close_button()
        self.apply_appearance()
        self.recorder.start_timer()
        # 全局事件过滤器：无边框窗口四边/四角悬停光标与拖拽缩放。
        # 原生 WM_NCHITTEST 命中虽正确，但 Qt 无边框窗口不会进入系统缩放循环，
        # 因此用 Qt 鼠标事件自行实现，行为可控且不受高 DPI 影响。
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        QTimer.singleShot(0, self._init_player)

    # ---------- 构建 UI ----------
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title_bar = TitleBar(self, self.metrics)
        outer.addWidget(self.title_bar)
        self._menubar = QMenuBar()
        outer.addWidget(self._menubar)

        self.player_widget = PlayerWidget(self.metrics)
        outer.addWidget(self.player_widget, 1)

        self.osd = OsdOverlay(self.metrics, self.player_widget)
        self.osd.setGeometry(self.metrics.s(14), self.metrics.s(14),
                             self.metrics.s(360), self.metrics.s(210))
        self.osd.raise_()

        self.progress = SeekSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setToolTip(tr("进度"))
        outer.addWidget(self.progress)

        self.control = ControlBar(self.metrics)
        outer.addWidget(self.control)

        # 右侧抽屉：宽度固定由 UI 缩放决定，切语言不跟随按钮文案伸缩
        self.dock = PlaylistDock(tr("播放列表"), self.metrics.s(380), self)
        self.dock.setObjectName("sideDock")
        self.dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.dock_contents = QTabWidget()
        self.playlist_panel = PlaylistPanel(self.metrics)
        self.iptv_panel = IptvPanel(self.metrics)
        self.dock_contents.addTab(self.playlist_panel, tr("播放列表"))
        self.dock_contents.addTab(self.iptv_panel, "IPTV")
        self.dock.setWidget(self.dock_contents)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        # 固定初始宽度；尺寸提示由 PlaylistDock 给出，用户仍可在停靠后拖宽。
        self.dock.resize(self.metrics.s(380), self.dock.height())
        self.dock.hide()
        self.control.list_btn.setChecked(False)

        # 录制任务列表独立窗口（从 IPTV 抽屉页移出，菜单 IPTV → 显示录制任务 打开）
        self.tasks_dialog = RecordTasksDialog(self.metrics, self)

        # 底部状态栏已移除：状态提示改为视频区下方的短暂浮层
        self.status_toast = QLabel(self.player_widget)
        self.status_toast.setObjectName("statusToast")
        self.status_toast.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
        )
        self.status_toast.setWordWrap(True)
        self.status_toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.status_toast.hide)

    def _menu(self, parent, text: str):
        menu = parent.addMenu(tr(text))
        menu.setProperty("source_title", text)
        return menu

    def _action(self, text: str, slot, shortcut: str = "", checkable: bool = False) -> QAction:
        action = QAction(tr(text), self)
        action.setProperty("source_text", text)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setCheckable(checkable)
        return action

    def _build_menus(self) -> None:
        menubar = self._menubar
        self.actions = {}

        menu = self._menu(menubar, "文件(&F)")
        menu.addAction(self._action("打开文件", self._open_files, "Ctrl+O"))
        menu.addAction(self._action("打开文件夹", self._open_folder))
        menu.addSeparator()
        menu.addAction(self._action("导入频道列表", self._import_channels))
        menu.addAction(self._action("导出频道列表", self._export_channels))
        menu.addSeparator()
        menu.addAction(self._action("退出", self.close, "Ctrl+Q"))

        menu = self._menu(menubar, "播放(&P)")
        # Space 由独立 QShortcut 注册：全屏时菜单栏隐藏，菜单 Action 的快捷键可能失效。
        self.actions["play"] = menu.addAction(self._action("播放 / 暂停", self._toggle_play))
        menu.addAction(self._action("停止", self._stop, "S"))
        # 快进/快退由独立 QShortcut 注册（见 _build_shortcuts）：
        # 全屏隐藏菜单栏后，菜单 Action 的快捷键会失效，与 Space 同理。
        self.actions["rewind"] = menu.addAction(self._action("快退", self._rewind))
        self.actions["forward"] = menu.addAction(self._action("快进", self._forward))
        menu.addSeparator()
        speed_menu = self._menu(menu, "播放速度")
        speed_group = QActionGroup(self)
        speed_group.setExclusive(True)
        for value in (0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0):
            action = self._action(
                f"{value}x", lambda checked=False, v=value: self._choose_speed(v),
                checkable=True,
            )
            speed_group.addAction(action)
            action.setChecked(value == 1.0)
            self.speed_actions[value] = action
            speed_menu.addAction(action)
        menu.addSeparator()
        menu.addAction(self._action("全屏", self._toggle_fullscreen, "F11"))

        menu = self._menu(menubar, "轨道(&T)")
        self.audio_menu = self._menu(menu, "音轨")
        self.audio_menu.addAction(self._action("添加外部音轨", self._add_audio))
        self.sub_menu = self._menu(menu, "字幕")
        self.sub_menu.addAction(self._action("添加外部字幕", self._add_subtitle))
        self.sub_menu.addAction(self._action("关闭字幕", lambda checked=False: self.player.set_subtitle_track(-1)))

        menu = self._menu(menubar, "截图(&S)")
        menu.addAction(self._action("单张截图", self._single_snapshot, "Alt+S"))
        menu.addAction(self._action("缩略图", self._thumbnail, "Alt+T"))
        menu.addAction(self._action("连续截图", self._continuous, "Alt+C"))

        menu = menubar.addMenu("IPTV")
        menu.addAction(self._action("打开 IPTV URL", self._open_iptv_url, "Ctrl+U"))
        menu.addAction(self._action("导入频道列表", self._import_channels))
        # 录制任务两个入口直接挂在 IPTV 下，与「打开 IPTV URL」同为二级菜单项。
        menu.addAction(self._action("新建录制任务", self._new_task))
        menu.addAction(self._action("显示录制任务", self._show_record_tasks))
        menu.addAction(self._action("显示频道面板", self._show_iptv_panel, "F7"))

        menu = self._menu(menubar, "视图(&I)")
        menu.addAction(self._action("播放列表", self._toggle_playlist_dock, "Ctrl+L"))
        menu.addAction(self._action("属性信息", self._show_properties, "Ctrl+I"))

        menu = self._menu(menubar, "设置(&S)")
        menu.addAction(self._action("设置", self._show_settings, "Ctrl+,"))

        menu = self._menu(menubar, "帮助(&H)")
        menu.addAction(self._action("关于", self._about))

    def _build_shortcuts(self) -> None:
        bindings = [
            ("Tab", self._toggle_osd),
            ("Esc", self._escape),
            ("Return", self._toggle_fullscreen),
            ("Up", lambda: self.player.set_volume(self.player.state.volume + 5)),
            ("Down", lambda: self.player.set_volume(self.player.state.volume - 5)),
            ("M", self._toggle_mute),
            ("F6", self._toggle_playlist_dock),
            ("Space", self._toggle_play),
            ("Left", self._rewind),
            ("Right", self._forward),
        ]
        for key, slot in bindings:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(slot)

    def _connect_signals(self) -> None:
        self.player.timeChanged.connect(self._on_time)
        self.player.pauseChanged.connect(lambda paused: self.control.set_playing(not paused))
        self.player.speedChanged.connect(self.title_bar.set_speed)
        self.player.speedChanged.connect(self._sync_speed_action)
        self.player.volumeChanged.connect(self.control.set_volume)
        self.player.tracksChanged.connect(self._update_track_menus)
        self.player.tracksChanged.connect(self._reprobe_current_info)
        self.audio_menu.aboutToShow.connect(self._refresh_track_checks)
        self.sub_menu.aboutToShow.connect(self._refresh_track_checks)
        self.player.videoSizeChanged.connect(self._on_video_size)
        self.player.fileLoaded.connect(self._on_file_loaded)
        self.player.playbackRestarted.connect(self._on_playback_restarted)
        self.player.endReached.connect(self._on_end)
        self.player.errorOccurred.connect(self._on_error)
        self.player.readyChanged.connect(self._on_ready)
        self.player.stateChanged.connect(self._on_state)
        self.info_cache.infoReady.connect(self._on_info_ready)

        self.control.playPause.connect(self._toggle_play)
        self.control.stop.connect(self._stop)
        self.control.rewind.connect(self._rewind)
        self.control.forward.connect(self._forward)
        self.control.volumeChanged.connect(self.player.set_volume)
        self.control.muteToggled.connect(self.player.set_mute)
        self.control.togglePlaylist.connect(self._set_playlist_visible)
        self.control.video_codec.clicked.connect(self._show_properties)
        self.control.audio_codec.clicked.connect(self._show_properties)
        self.control.effects_btn.clicked.connect(self._toggle_osd)

        self.player_widget.filesDropped.connect(self._open_paths)
        self.player_widget.doubleClicked.connect(self._toggle_fullscreen)
        self.player_widget.wheelVolume.connect(
            lambda delta: self.player.set_volume(self.player.state.volume + delta)
        )
        self.progress.sliderPressed.connect(self._on_scrub_started)
        self.progress.sliderReleased.connect(self._on_scrub_finished)

        self.playlist_panel.playRequested.connect(self._play_path)
        # 播放列表「添加文件」：有片子播放时只入列、不打断；空闲时自动播放第一个。
        self.playlist_panel.filesAdded.connect(lambda paths: self._open_paths(paths, play=None))
        self.playlist_panel.propertiesRequested.connect(self._show_properties_for)
        self.playlist_panel.openFolderRequested.connect(self._open_folder_of)

        self.iptv_panel.playChannel.connect(self._play_channel)
        self.iptv_panel.channelsChanged.connect(self._save_channels)
        self.iptv_panel.importRequested.connect(self._import_paths)
        self.iptv_panel.exportRequested.connect(self._export_channels_to)
        self.iptv_panel.editChannel.connect(self._edit_channel)
        self.iptv_panel.newTask.connect(self._new_task)
        self.tasks_dialog.newTask.connect(self._new_task)
        self.tasks_dialog.taskStop.connect(self._task_stop)
        self.tasks_dialog.taskCancel.connect(self._task_cancel)
        self.tasks_dialog.taskEdit.connect(self._task_edit)
        self.tasks_dialog.taskDelete.connect(self._task_delete)
        self.tasks_dialog.taskDeleteSelected.connect(self._task_delete_selected)
        self.tasks_dialog.taskOpenFile.connect(self._task_open_file)
        self.tasks_dialog.taskOpenDir.connect(self._task_open_dir)

        self.recorder.taskChanged.connect(self._on_task_changed)
        self.recorder.tasksChanged.connect(self._refresh_tasks)
        self.recorder.message.connect(lambda text: self._update_status(text))
        self.dock.visibilityChanged.connect(self.control.list_btn.setChecked)

        self.i18n.languageChanged.connect(lambda _: self.apply_appearance())
        self.metrics.scaleChanged.connect(lambda _: self.apply_appearance())

        self._load_channels()
        self._refresh_tasks()

    def _init_player(self) -> None:
        log_info(f"[启动] _init_player 执行，native_id={self.player_widget.native_id()}")
        ok = self.player.init(self.player_widget.native_id())
        if not ok:
            self._update_status(tr("播放内核未就绪") + ": libmpv-2.dll")
            log_error("[启动] _init_player 失败，libmpv 不可用")
        else:
            self.player.set_volume(self.settings.volume)
            self._update_status(tr("未打开视频"))
            log_info("[启动] _init_player 成功")

    # ---------- 外观与同步 ----------
    def apply_appearance(self) -> None:
        # 语言切换只改文案，不应改动用户当前看到的播放列表宽度。
        # 只在语言真的变化时记录宽度；切换 UI 缩放时则允许抽屉跟随缩放重排。
        language_changed = getattr(self, "_applied_language", None) != self.settings.language
        self._applied_language = self.settings.language
        dock_width = (
            self.dock.width()
            if language_changed and self.dock.isVisible() and not self._fullscreen
            else None
        )
        app = QApplication.instance()
        apply_theme(app, self.settings.theme, self.metrics)
        self.metrics.apply_font(app)
        self.dock.set_stable_width(self.metrics.s(380))
        install_qt_translator(app, self.settings.language)
        self.setWindowTitle(tr("应用名称"))
        self.title_bar.apply_scale()
        self.control.apply_scale()
        self.title_bar.scale_label.setText(f"UI {self._scale_text()}")
        self.title_bar.scale_label.setToolTip(tr("缩放状态提示"))
        self.progress.setToolTip(tr("进度"))
        auto_retranslate(self)
        self._walk_retranslate(self)
        self._retranslate_menus()
        self.control.refresh_icons()
        self.osd.refresh_geometry()
        self.osd.update()
        self.control.effects_btn.setChecked(self.osd.isVisible())
        self._style_dock_close_button()
        if dock_width is not None:
            self._restore_dock_width(dock_width)
            # 布局可能在事件循环下一轮才按新 sizeHint 重排，再恢复一次保证宽度不变。
            QTimer.singleShot(0, lambda width=dock_width: self._restore_dock_width(width))

    def _restore_dock_width(self, width: int) -> None:
        """语言切换后恢复播放列表抽屉宽度（保留用户手动拖出的宽度）。"""
        if (width <= 0 or not self.dock.isVisible() or self._fullscreen
                or self.dock.width() == width):
            return
        self.dock.resize(width, self.dock.height())

    def _style_dock_close_button(self) -> None:
        """抽屉关闭按钮用纯白加粗 X（原生/普通亮色图标在深色标题栏上仍偏灰）。"""
        button = self.dock.findChild(QAbstractButton, "qt_dockwidget_closebutton")
        if button is None:
            return
        white = icon("close_bold", "#ffffff")
        button.setIcon(white)
        button.setIconSize(QSize(18, 18))
        # 明确各状态的图标，避免样式把 Normal 态图标置灰
        button.setToolTip(tr("关闭"))

    def _position_status_toast(self) -> None:
        """把状态浮层放在视频区下方居中。"""
        toast = getattr(self, "status_toast", None)
        if toast is None or not self.player_widget:
            return
        m = self.metrics
        w = self.player_widget.width()
        h = self.player_widget.height()
        if w <= 0 or h <= 0:
            return
        toast_w = min(w - m.s(24), m.s(560))
        toast_h = m.s(44)
        toast.setGeometry((w - toast_w) // 2, h - toast_h - m.s(12), toast_w, toast_h)

    def _scale_text(self) -> str:
        mode = tr("手动") if self.settings.ui_scale_mode == "manual" else tr("自动")
        return f"{mode} / {int(round(self.metrics.scale * 100))}%"

    def _retranslate_menus(self) -> None:
        # `_action()` 创建的 QAction parent 是主窗口，而非菜单栏 / 菜单，
        # 因此不能用 `_menubar.findChildren(QAction)`——那样只会命中菜单栏直属的
        # 菜单标题动作，所有一/二/三级菜单项都不会更新。改为遍历每个菜单的 actions()，
        # 递归覆盖子菜单，并用 source_text 属性取回源文案重新翻译。
        menus = [self._menubar, *self._menubar.findChildren(QMenu)]
        for menu in menus:
            source = menu.property("source_title")
            if source:
                menu.setTitle(tr(str(source)))
            for action in menu.actions():
                a_source = action.property("source_text")
                # 子菜单的入口 action 由 menu.setTitle 负责，此处跳过带子菜单的项
                if a_source and action.menu() is None:
                    action.setText(tr(str(a_source)))

    def _walk_retranslate(self, widget: QWidget) -> None:
        retranslate = getattr(widget, "retranslate", None)
        if callable(retranslate):
            try:
                retranslate()
            except Exception as exc:
                log_error(f"retranslate failed: {exc}")
        for child in widget.findChildren(QWidget):
            method = getattr(child, "retranslate", None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass

    # ---------- 播放 ----------
    def _open_files(self) -> None:
        paths, _ = get_open_files(
            self, tr("选择视频文件"), "",
            tr("媒体文件 (*.mp4 *.mkv *.mov *.avi *.ts *.flv *.webm *.m4v *.wmv *.m2ts *.mpg *.3gp "
            "*.aac *.mp3 *.flac *.wav);;所有文件 (*.*)"),
            self.metrics,
        )
        if paths:
            self._open_paths(paths)

    def _open_folder(self) -> None:
        path = get_existing_directory(self, tr("选择文件夹"), metrics=self.metrics)
        if path:
            self._open_paths([
                os.path.join(path, name) for name in sorted(os.listdir(path))
                if os.path.splitext(name)[1].lower() in PlayerWidget.VIDEO_EXTS
            ])

    def queue_launch_files(self, paths: list[str]) -> None:
        """文件关联/命令行传入的文件先入队；内核就绪后再播放。

        libmpv 通过 QTimer.singleShot(0) 在事件循环首轮才初始化，若在主窗口
        show() 后立即 open()，内核尚未就绪会被直接忽略，只剩标题栏被设置。
        """
        log_info(f"[启动] 收到命令行文件 {len(paths)} 个，内核就绪={self.player.available}: {paths}")
        if self.player.available:
            log_info("[启动] 内核已就绪，立即打开")
            self._open_paths(paths)
        else:
            self._pending_launch_files.extend(paths)
            log_info(f"[启动] 内核未就绪，已入队等待 readyChanged: {self._pending_launch_files}")

    def _flush_pending_launch(self) -> None:
        paths = list(self._pending_launch_files)
        self._pending_launch_files.clear()
        if paths:
            log_info(f"[启动] readyChanged 后播放排队文件 {len(paths)} 个: {paths}")
            self._open_paths(paths)

    def _open_paths(self, paths: list[str], play: bool | None = True) -> None:
        if not paths:
            return
        had_media = bool(getattr(self, "_current_path", ""))
        self.playlist_panel.add_paths(paths)
        self.playlist = self.playlist_panel.paths
        # play=True（打开/拖放）：无论当前是否已有视频都立即切换；
        # play=None（加入播放列表）：已有视频时只入列，空闲时才自动播放。
        if play is True or (play is None and not had_media):
            self._play_path(paths[0])

    def _save_playback_position(self) -> None:
        """保存当前本地文件的播放位置；仅在开启设置且确实播放过时写入。"""
        if not self.settings.remember_position or not self._position_observed:
            return
        path = getattr(self, "_current_path", "")
        if not path or getattr(self, "_live", False) or not os.path.isfile(path):
            return
        state = self.player.state
        pos = max(0.0, float(state.time_pos or 0.0))
        duration = max(0.0, float(state.duration or 0.0))
        if duration > 0 and duration - pos <= 3.0:
            self.settings.clear_playback_position(path)
            log_info(f"[记忆位置] 已播完，清除记录: {os.path.basename(path)}")
            return
        if pos < 1.0:
            # 用户拖回开头后切换，视为从头开始，清掉旧记录
            self.settings.clear_playback_position(path)
            return
        self.settings.set_playback_position(path, pos)

    def _clear_playback_position(self) -> None:
        """播放自然结束时清除记录，使下次从头开始。"""
        path = getattr(self, "_current_path", "")
        if path and not getattr(self, "_live", False):
            self.settings.clear_playback_position(path)
            log_info(f"[记忆位置] 播放结束，清除记录: {os.path.basename(path)}")

    def _play_path(self, path: str) -> None:
        log_info(f"[打开] _play_path: {path}，内核就绪={self.player.available}")
        if not os.path.isfile(path):
            self._update_status(tr("文件不存在"))
            log_error(f"[打开] 文件不存在: {path}")
            return
        # 切换文件前先保存上一个文件的进度（此时 _current_path 仍是旧文件）
        self._save_playback_position()
        start_pos = 0.0
        if self.settings.remember_position:
            start_pos = self.settings.get_playback_position(path)
            if start_pos > 0:
                log_info(f"[记忆位置] 恢复 {os.path.basename(path)} 到 {start_pos:.1f}s")
        self._position_observed = False
        self._live = False
        self._current_path = path
        self.player_widget.set_has_media(True)
        self.player.open(path, start_pos=start_pos)
        self.playlist_panel.highlight(path)
        self.info_cache.probe_with_player(path, self.player)
        self.control.set_live(False)
        self.title_bar.set_media_name(os.path.basename(path))

    def _play_channel(self, channel: Channel) -> None:
        if not channel.enabled:
            return
        self._save_playback_position()
        self._position_observed = False
        self._live = True
        self._current_path = channel.url
        self.player_widget.set_has_media(True)
        self.player.open(channel.url, live=True)
        self.control.set_live(True)
        self.osd.set_info(self.player.state, channel.name, {})
        self.info_cache.probe_with_player(channel.url, self.player, live=True)
        self.title_bar.set_media_name(f"{tr('直播')} · {channel.name}")

    def _toggle_play(self) -> None:
        self.player.play_pause()

    def _stop(self) -> None:
        self._save_playback_position()
        self.player.stop()
        self.control.set_time(0, 0)
        self.title_bar.set_media_name("")
        self.progress.blockSignals(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.blockSignals(False)
        self._update_status(tr("停止"))

    def _rewind(self) -> None:
        self.player.seek(-self.settings.seek_step, absolute=False)

    def _forward(self) -> None:
        self.player.seek(self.settings.seek_step, absolute=False)

    def _toggle_mute(self) -> None:
        self.player.set_mute(not self.player.state.muted)

    def _on_time(self, pos: float, duration: float) -> None:
        if pos >= 1.0:
            self._position_observed = True
        self.control.set_time(pos, duration, self._live)
        if self._live:
            # 直播无固定时长，进度条保持在起点
            if not self._scrubbing_active:
                self.progress.blockSignals(True)
                self.progress.setRange(0, 1)
                self.progress.setValue(0)
                self.progress.blockSignals(False)
            return
        if not self._scrubbing_active:
            # 以 0.1 秒为刻度，进度条范围与时长严格对应
            maximum = max(1, int(round(duration * 10))) if duration > 0 else 1
            self.progress.blockSignals(True)
            self.progress.setRange(0, maximum)
            self.progress.setValue(min(maximum, max(0, int(round(pos * 10)))))
            self.progress.blockSignals(False)

    def _on_scrub_started(self) -> None:
        self._scrubbing_active = True

    def _on_scrub_finished(self) -> None:
        self._scrubbing_active = False
        if self._live:
            self.progress.setValue(0)
            return
        value = self.progress.value() / 10.0
        self.player.seek(value, absolute=True)

    def _choose_speed(self, value: float) -> None:
        self.player.set_speed(value)
        action = self.speed_actions.get(value)
        if action is not None and not action.isChecked():
            action.setChecked(True)

    def _show_speed_menu(self) -> None:
        """右上角倍速徽标：就地弹出速度菜单，选中即生效。"""
        menu = QMenu(self)
        for action in self.speed_actions.values():
            menu.addAction(action)
        button = self.title_bar.speed_btn
        menu.exec(button.mapToGlobal(QPoint(0, button.height())))

    def _sync_speed_action(self, value: float) -> None:
        for speed, action in self.speed_actions.items():
            if abs(speed - value) < 1e-3:
                if not action.isChecked():
                    action.setChecked(True)
                return

    def _rescale_window(self, old_scale: float, new_scale: float) -> None:
        """UI 缩放变化时按比例调整窗口尺寸，视频/截图/录制输出不受影响。"""
        if abs(new_scale - old_scale) < 1e-6 or old_scale <= 0:
            return
        if self.isMaximized() or self._fullscreen:
            return
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        ratio = new_scale / old_scale
        width = int(round(self.width() * ratio))
        height = int(round(self.height() * ratio))
        width = max(self.minimumWidth(), width)
        height = max(self.minimumHeight(), height)
        if available is not None:
            width = min(width, available.width())
            height = min(height, available.height())
        self.resize(width, height)

    def _toggle_osd(self) -> None:
        """Tab 快捷键 / 右下角按钮统一入口，保持按钮选中态与浮层一致。"""
        self.osd.toggle()
        self.control.effects_btn.setChecked(self.osd.isVisible())

    def _on_playback_restarted(self) -> None:
        """mpv 重建视频表面后重新置顶 OSD，避免浮层被视频覆盖。"""
        if self.osd.isVisible():
            self.osd.raise_()
            self.osd.update()
        # 直播流首帧前轨道为空，首次探测会退到 ffprobe；首帧后 video-frame-info
        # 与 track-list 已就绪，重取一次让 Tab OSD / 属性窗口显示扫描方式。
        if getattr(self, "_live", False):
            self._reprobe_current_info()

    def _on_file_loaded(self, path: str) -> None:
        self.progress.set_chapters([], 0)
        if path and not self._live:
            self._current_path = path
            self.title_bar.set_media_name(os.path.basename(path))
        self.osd.set_info(self.player.state, os.path.basename(path), {})

    def _on_end(self) -> None:
        self.control.set_playing(False)
        self._clear_playback_position()
        self._update_status(tr("播放结束"))

    def _on_error(self, message: str) -> None:
        self._update_status(message[:120])
        log_error(message)

    def _on_ready(self, ready: bool) -> None:
        if ready:
            self._update_status(tr("libmpv 就绪"))
            log_info("[启动] libmpv readyChanged(True)")
            self._flush_pending_launch()

    def _on_state(self, state) -> None:
        details = getattr(self, "_osd_details", {})
        self.osd.set_info(state, os.path.basename(self._current_path), details)

    def _reprobe_current_info(self) -> None:
        """轨道/字幕就绪后再刷新一次，避免首次 open 时 track-list 为空导致字幕缺失。

        用单次定时器做防抖：视频/音频/字幕轨道会先后到达，取最后一次为准。
        """
        path = getattr(self, "_current_path", "")
        if not path:
            return
        timer = getattr(self, "_info_reprobe_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._do_reprobe)
            self._info_reprobe_timer = timer
        # 等 mpv 把 track-list / chapter-list 全部填充完成
        timer.start(150)

    def _do_reprobe(self) -> None:
        path = getattr(self, "_current_path", "")
        if not path:
            return
        self.info_cache.invalidate(path)
        self.info_cache.probe_with_player(path, self.player, live=self._live)

    def _on_info_ready(self, info: MediaInfo) -> None:
        self._last_media_info = info
        self.progress.set_chapters(info.chapters, info.duration)
        videos = [s for s in info.streams if s.codec_type == "video"]
        audios = [s for s in info.streams if s.codec_type == "audio"]
        vcodec = codec_label(videos[0].codec_name) if videos else "--"
        acodec = codec_label(audios[0].codec_name) if audios else "--"
        self.control.set_codecs(vcodec, acodec)
        from ..core.media_info import format_size

        def _pretty_fps(value: str) -> str:
            try:
                if "/" in value:
                    num, den = value.split("/", 1)
                    fps = float(num) / float(den)
                else:
                    fps = float(value)
                return f"{fps:.3f}" if fps else value
            except (TypeError, ValueError, ZeroDivisionError):
                return value or "--"

        video = videos[0] if videos else None
        audio = audios[0] if audios else None
        vp = info.video_params or {}
        vraw = (video.raw if video else {}) or {}
        araw = (audio.raw if audio else {}) or {}
        vbitrate = str(getattr(video, "bit_rate", "") or vraw.get("demux-bitrate", ""))
        abitrate = str(getattr(audio, "bit_rate", "") or araw.get("demux-bitrate", ""))
        def _kbps(value: str) -> str:
            try:
                return f"{int(float(value) / 1000)} kb/s" if float(value) else "--"
            except (TypeError, ValueError):
                return "--"

        details = {
            "video_codec": vcodec,
            "audio_codec": acodec,
            "resolution": f"{video.width}x{video.height}" if video and video.width else "--",
            "fps": _pretty_fps(video.r_frame_rate if video else ""),
            "pix_fmt": video.pix_fmt if video else "--",
            "sample_rate": audio.sample_rate if audio else "--",
            "channels": str(audio.channels) if audio else "--",
            "format": info.format_name or "--",
            "size": format_size(info.size),
            "duration": info.duration,
            "overall_bitrate": _kbps(info.overall_bitrate),
            "video_bitrate": _kbps(vbitrate),
            "audio_bitrate": _kbps(abitrate),
            "scan": getattr(info, "scan_type", "") or "--",
            "aspect": vp.get("aspect-name", "") or "--",
            "colormatrix": str(vp.get("colormatrix", "") or "").upper() or "--",
            "sub_count": str(len([s for s in info.streams if s.codec_type == "sub"])),
            "chapter_count": str(len(info.chapters)),
        }
        self._osd_details = details
        self.osd.set_info(self.player.state, info.name, details)
        properties = getattr(self, "_properties_dialog", None)
        if properties is not None and properties.isVisible():
            properties.set_info(info)

    def _update_track_menus(self, tracks: dict) -> None:
        # QAction.triggered 会透传一个 checked 布尔参数，所有回调都保留该形参，
        # 否则 PySide 因签名不匹配而不调用（曾导致音轨/字幕选择点击无反应）。
        self.audio_menu.clear()
        audio_group = QActionGroup(self.audio_menu)
        audio_group.setExclusive(True)
        disable_audio = self._action(
            "禁用音频", lambda checked=False: self.player.set_audio_track(0), checkable=True
        )
        disable_audio.setProperty("track_id", 0)
        audio_group.addAction(disable_audio)
        self.audio_menu.addAction(disable_audio)
        for track in tracks.get("audio", []):
            act = self._action(
                track.label(),
                lambda checked=False, index=track.index: self.player.set_audio_track(index),
                checkable=True,
            )
            act.setProperty("track_id", track.index)
            audio_group.addAction(act)
            self.audio_menu.addAction(act)
        self.audio_menu.addSeparator()
        self.audio_menu.addAction(self._action("添加外部音轨", lambda checked=False: self._add_audio()))

        self.sub_menu.clear()
        sub_group = QActionGroup(self.sub_menu)
        sub_group.setExclusive(True)
        disable_sub = self._action(
            "关闭字幕", lambda checked=False: self.player.set_subtitle_track(0), checkable=True
        )
        disable_sub.setProperty("track_id", 0)
        sub_group.addAction(disable_sub)
        self.sub_menu.addAction(disable_sub)
        for track in tracks.get("sub", []):
            act = self._action(
                track.label(),
                lambda checked=False, index=track.index: self.player.set_subtitle_track(index),
                checkable=True,
            )
            act.setProperty("track_id", track.index)
            sub_group.addAction(act)
            self.sub_menu.addAction(act)
        self.sub_menu.addSeparator()
        self.sub_menu.addAction(self._action("添加外部字幕", lambda checked=False: self._add_subtitle()))
        # 立即刷新选中态；菜单展开时再刷新一次以反映播放器内部切换。
        self._refresh_track_checks()

    def _refresh_track_checks(self) -> None:
        """按 mpv 当前 aid/sid 勾选对应音轨/字幕项，禁用项在 id=0 时勾选。"""
        cur_audio = self.player.current_audio_track()
        found_audio = False
        for act in self.audio_menu.actions():
            if not act.isCheckable():
                continue
            track_id = int(act.property("track_id") or 0)
            checked = track_id == cur_audio
            if checked:
                found_audio = True
            act.setChecked(checked)
        if not found_audio:
            # 当前 id 不在列表中（如切换文件瞬间）：勾选“禁用音频”
            for act in self.audio_menu.actions():
                if act.isCheckable() and int(act.property("track_id") or 0) == 0:
                    act.setChecked(True)
                    break

        cur_sub = self.player.current_subtitle_track()
        found_sub = False
        for act in self.sub_menu.actions():
            if not act.isCheckable():
                continue
            track_id = int(act.property("track_id") or 0)
            checked = track_id == cur_sub
            if checked:
                found_sub = True
            act.setChecked(checked)
        if not found_sub:
            for act in self.sub_menu.actions():
                if act.isCheckable() and int(act.property("track_id") or 0) == 0:
                    act.setChecked(True)
                    break

    # ---------- 轨道 / 截图 ----------
    def _add_audio(self) -> None:
        paths, _ = get_open_files(
            self, tr("添加外部音轨"), "",
            tr("音频 (*.aac *.mp3 *.m4a *.flac *.wav *.ogg *.opus *.wma);;所有文件 (*.*)"),
            self.metrics,
        )
        path = paths[0] if paths else ""
        if path:
            self.player.add_external_audio(path)

    def _add_subtitle(self) -> None:
        paths, _ = get_open_files(
            self, tr("添加外部字幕"), "",
            tr("字幕 (*.srt *.ass *.ssa *.vtt);;所有文件 (*.*)"),
            self.metrics,
        )
        path = paths[0] if paths else ""
        if path:
            self.player.add_external_subtitle(path)

    def _single_snapshot(self) -> None:
        from ..core.screenshot import _stamp, single_snapshot

        name = os.path.splitext(os.path.basename(self._current_path))[0] or "snapshot"
        name = "".join(c for c in name if c not in '\\/:*?"<>|')
        # 默认文件名带视频名前缀与截图时间戳；核心检测到时间戳后不会重复添加
        default = f"{name}_snapshot_{_stamp()}.png"
        path, _ = get_save_file(
            self, tr("选择保存位置"), os.path.join(app_root(), default),
            tr("图片 (*.png)"), self.metrics,
        )
        if path:
            saved = single_snapshot(self.player, path, True)
            if saved:
                self._update_status(f"{tr('完成')}: {saved}")
            else:
                self._update_status(tr("保存失败"))

    def _thumbnail(self) -> None:
        if not self.player.available:
            self._on_error(tr("播放内核未就绪"))
            return
        dialog = ThumbnailDialog(self.metrics, self.player, self)
        dialog.exec()

    def _continuous(self) -> None:
        if not self.player.available:
            self._on_error(tr("播放内核未就绪"))
            return
        dialog = ContinuousDialog(self.metrics, self.player, self)
        dialog.exec()

    # ---------- IPTV ----------
    def _load_channels(self) -> None:
        from ..core.iptv_store import ChannelStore

        channels = ChannelStore().load_channels()
        self.iptv_panel.set_channels(channels)

    def _save_channels(self, channels: list[Channel]) -> None:
        from ..core.iptv_store import ChannelStore

        ChannelStore().save_channels(channels)
        self._update_status(f"{tr('频道名称')}: {len(channels)}")

    def _open_iptv_url(self) -> None:
        url, ok = TextInputDialog.get_text(
            self, "IPTV", "URL", metrics=self.metrics
        )
        if ok and url.strip():
            self._play_channel(Channel(name=url.strip(), url=url.strip()))

    def _import_channels(self) -> None:
        paths, _ = get_open_files(
            self, tr("导入频道列表"), "", tr("M3U (*.m3u *.m3u8);;所有文件 (*.*)"),
            self.metrics,
        )
        if paths:
            self._import_paths(paths)

    def _import_paths(self, paths: list[str]) -> None:
        from ..core.iptv_store import ChannelStore

        channels = list(self.iptv_panel._channels)
        imported, skipped = 0, 0
        for path in paths:
            result = parse_m3u(path)
            channels.extend(result.channels)
            imported += len(result.channels)
            skipped += len(result.skipped)
        ChannelStore().save_channels(channels)
        self.iptv_panel.set_channels(channels)
        QMessageBox.information(
            self, tr("提示"), f"{tr('成功')}: {imported} {tr('条')}, {tr('跳过')}: {skipped} {tr('条')}"
        )

    def _export_channels_to(self, path: str) -> None:
        ok = export_m3u(path, self.iptv_panel._channels)
        QMessageBox.information(
            self, tr("提示"), tr("完成") if ok else tr("保存失败")
        )

    def _export_channels(self) -> None:
        path, _ = get_save_file(
            self, tr("导出频道列表"), os.path.join(app_root(), "channels.m3u"),
            tr("M3U (*.m3u)"), self.metrics,
        )
        if path:
            self._export_channels_to(path)

    def _edit_channel(self, channel: Channel) -> None:
        name, ok = TextInputDialog.get_text(
            self, tr("编辑频道"), tr("频道名称"), channel.name, self.metrics
        )
        if not ok or not name.strip():
            return
        url, ok = TextInputDialog.get_text(
            self, tr("编辑频道"), "URL", channel.url, self.metrics
        )
        if not ok or not url.strip():
            return
        group, ok = TextInputDialog.get_text(
            self, tr("编辑频道"), tr("分组"), channel.group, self.metrics
        )
        if not ok:
            return
        updated = Channel(name=name.strip(), url=url.strip(), group=group.strip() or "默认分组",
                          logo=channel.logo, note=channel.note, enabled=channel.enabled)
        self.iptv_panel.apply_channel_edit(channel, updated)

    def _new_task(self, channel: Optional[Channel] = None) -> None:
        if not isinstance(channel, Channel):
            channel = None  # 兼容 QAction 传参
        dialog = RecordDialog(self.settings, self.iptv_panel._channels,
                              self.metrics, channel=channel, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values
        selected = next(
            (c for c in self.iptv_panel._channels if c.name == values["name"]), None
        )
        if selected is None:
            selected = Channel(name=values["name"], url=values["url"])
        task, error = self.recorder.add_task(
            selected, values["content"], values["start_time"], values["end_time"],
            values["record_dir"], values["record_format"],
        )
        if error:
            QMessageBox.warning(self, tr("错误"), error)
        else:
            self._refresh_tasks()

    def _task_stop(self, task_id: str) -> None:
        task = self.recorder.find(task_id)
        if task is None:
            return
        if task.status != TaskStatus.RECORDING.value:
            QMessageBox.warning(self, tr("提示"), tr("只有录制中的任务才能停止"))
            return
        error = self.recorder.stop_task(task_id)
        if error:
            QMessageBox.warning(self, tr("提示"), error)

    def _task_cancel(self, task_id: str) -> None:
        error = self.recorder.cancel_task(task_id)
        if error:
            QMessageBox.warning(self, tr("提示"), error)

    def _task_edit(self, task_id: str) -> None:
        task = self.recorder.find(task_id)
        if task is None:
            return
        dialog = RecordDialog(self.settings, self.iptv_panel._channels,
                              self.metrics, task=task, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        error = self.recorder.update_task(task_id, **dialog.values)
        if error:
            QMessageBox.warning(self, tr("提示"), error)

    def _task_delete(self, task_id: str) -> None:
        error = self.recorder.remove_task(task_id)
        if error:
            QMessageBox.warning(self, tr("提示"), error)

    def _task_delete_selected(self, task_ids: list[str]) -> None:
        """批量删除勾选任务；录制中的任务由内核拒绝，跳过并提示。"""
        skipped: list[str] = []
        errors: list[str] = []
        for task_id in task_ids:
            task = self.recorder.find(task_id)
            if task is None:
                continue
            if task.status == TaskStatus.RECORDING.value:
                skipped.append(task.channel)
                continue
            error = self.recorder.remove_task(task_id)
            if error:
                errors.append(error)
        if skipped:
            QMessageBox.warning(
                self, tr("提示"),
                f"{tr('录制中的任务已跳过')}：{', '.join(skipped)}",
            )
        elif errors:
            QMessageBox.warning(self, tr("提示"), errors[0])

    def _task_open_file(self, task_id: str) -> None:
        task = self.recorder.find(task_id)
        if task and task.output and os.path.isfile(task.output):
            self._open_folder_of(task.output, open_file=True)

    def _task_open_dir(self, task_id: str) -> None:
        task = self.recorder.find(task_id)
        if task and task.output and os.path.isfile(task.output):
            self._open_folder_of(task.output)

    def _open_folder_of(self, path: str, open_file: bool = False) -> None:
        if not os.path.exists(path):
            self._update_status(tr("文件不存在"))
            return
        target = path if open_file else os.path.dirname(path)
        if sys.platform.startswith("win"):
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", target])

    def _refresh_tasks(self) -> None:
        self.tasks_dialog.set_tasks(list(self.recorder.tasks))

    def _show_record_tasks(self) -> None:
        """IPTV → 显示录制任务：打开独立任务列表窗口。"""
        self._refresh_tasks()
        self.tasks_dialog.exec()

    def _on_task_changed(self, task_id: str) -> None:
        self._refresh_tasks()

    # ---------- 对话框 ----------
    def _show_properties(self) -> None:
        self._show_properties_for(self._current_path)

    def _show_properties_for(self, path: str) -> None:
        dialog = getattr(self, "_properties_dialog", None)
        if dialog is None or not dialog.isVisible():
            dialog = PropertiesDialog(
                self.metrics, lambda: self.player.snapshot_state(),
                lambda: self._last_media_info, self
            )
            self._properties_dialog = dialog
        dialog.show()
        dialog.raise_()
        info = self.info_cache.get(path)
        if info:
            dialog.set_info(info)
        else:
            self.info_cache.probe_with_player(path, self.player, live=self._live)

    def _show_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.metrics, self)
        dialog.applied.connect(self._on_settings_applied)
        dialog.exec()

    def _on_settings_applied(self) -> None:
        """设置确认后：切换全局语言并重算缩放，同步主题、图标等全部界面。"""
        init_i18n(self.settings.language)
        self.i18n = i18n()
        old_scale = self.metrics.scale
        self.metrics.recompute()
        self.apply_appearance()
        self._rescale_window(old_scale, self.metrics.scale)
        self._position_status_toast()

    def _about(self) -> None:
        from PySide6.QtWidgets import QDialog

        dialog = QDialog(self)
        set_window_icon(dialog)
        dialog.setWindowTitle(tr("关于"))
        dialog.setMinimumWidth(self.metrics.s(400))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(self.metrics.s(24), self.metrics.s(20),
                                  self.metrics.s(24), self.metrics.s(18))
        layout.setSpacing(self.metrics.s(8))

        logo = QLabel()
        logo.setPixmap(app_pixmap(self.metrics.s(64)))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name = QLabel(tr("应用名称"))
        name.setObjectName("titleText")
        name.setProperty("source_text", "应用名称")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version = QLabel(APP_VERSION)
        version.setObjectName("versionText")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark_dynamic(version)
        text = QLabel(tr("关于文本").format(version=APP_VERSION)
                      + "\n\nPySide6 · libmpv · FFmpeg\nLGPL")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        ok = compact_button(QPushButton(tr("确定")), self.metrics)
        ok.setObjectName("primaryButton")
        ok.clicked.connect(dialog.accept)
        buttons = centered_buttons(ok)

        layout.addWidget(logo)
        layout.addWidget(name)
        layout.addWidget(version)
        layout.addWidget(text)
        layout.addLayout(buttons)
        dialog.exec()

    # ---------- 窗口与快捷键 ----------
    def _on_video_size(self, width: int, height: int) -> None:
        """视频分辨率就绪：锁定宽高比，并按真实分辨率调整窗口（超屏则最大化）。

        本地文件、在线播放与 IPTV 频道最终都经 mpv 的 video-params 触发此回调，
        因此三类播放共用同一套窗口适配逻辑。
        """
        if width <= 0 or height <= 0:
            return
        aspect = width / float(height)
        self._video_aspect = aspect
        self._aspect_locked = True
        log_info(f"[窗口] 视频显示尺寸 {width}x{height} 比例 {aspect:.4f}")
        if self._fullscreen:
            return
        self.fit_window_to_video(width, height)

    def fit_window_to_video(self, width: int, height: int) -> None:
        """按视频真实分辨率设置窗口，物理像素先按屏幕 DPI 换算后比较可用区。

        mpv 报告的 dw/dh 是视频的物理像素；Qt 的窗口几何是设备无关的逻辑像素。
        在 2560x1440 / 125% 缩放下，逻辑可用区只有 2048x1112，若直接拿 1920x1080
        与逻辑区比较会误判为“超屏”而最大化。除以 devicePixelRatio 后，视频区按
        1:1 物理像素显示，1920x1080 视频在 1440p 屏幕上就能正常开窗。
        """
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        dpr = float(screen.devicePixelRatio() or 1.0)
        if dpr <= 0:
            dpr = 1.0
        # 视频区之外的固定尺寸：标题栏 + 菜单栏 + 进度条 + 控制栏（右侧抽屉如显示也计入）
        chrome_h = max(0, self.height() - self.player_widget.height())
        chrome_w = max(0, self.width() - self.centralWidget().width())
        video_w = max(1, int(round(width / dpr)))
        video_h = max(1, int(round(height / dpr)))
        win_w = video_w + chrome_w
        win_h = video_h + chrome_h
        # 换算后的视频真实尺寸（含界面 chrome）仍超出屏幕可用区域时才最大化
        if win_w > avail.width() or win_h > avail.height():
            if not self.isMaximized():
                self.showMaximized()
                log_info(f"[窗口] 视频 {width}x{height} 超出屏幕可用区，最大化")
            return
        if self.isMaximized():
            self.showNormal()
        win_w = max(self.minimumWidth(), win_w)
        win_h = max(self.minimumHeight(), win_h)
        # 以原窗口中心为锚点重设位置
        center = self.geometry().center()
        x = center.x() - win_w // 2
        y = center.y() - win_h // 2
        x = max(avail.left(), min(x, avail.right() - win_w))
        y = max(avail.top(), min(y, avail.bottom() - win_h))
        self.setGeometry(x, y, win_w, win_h)
        log_info(f"[窗口] 按视频真实分辨率重排: {win_w}x{win_h} "
                 f"video={video_w}x{video_h}/{width}x{height} dpr={dpr:.2f}")

    # ---------- 无边框窗口缩放/移动（Qt 事件过滤器） ----------
    def eventFilter(self, obj, event):  # noqa: N802
        """四边/四角拖拽缩放，以及视频区/下方工具栏拖拽移动窗口。

        只处理鼠标指针落在主窗口范围内的事件；子控件事件向上传播时同样可见。
        最小化/最大化/全屏时禁用，避免与系统窗口管理冲突。
        """
        if self._fullscreen:
            if event.type() == QEvent.Type.MouseMove:
                self._update_fullscreen_overlays(event.globalPosition().toPoint())
            return False
        if self.isMaximized() or self.isMinimized():
            return False
        etype = event.type()
        # 缩放拖拽中：鼠标可能移出窗口，先于归属过滤处理，避免中断
        if etype == QEvent.Type.MouseMove and self._resize_edge:
            self._resize_by_drag(event.globalPosition().toPoint())
            return True
        if etype == QEvent.Type.MouseButtonRelease and self._resize_edge:
            self._resize_edge = ""
            self._resize_origin = None
            self.unsetCursor()
            return True
        # 移动拖拽中：同样先处理，保证鼠标移出窗口后仍能跟随。
        # 但弹出菜单等窗口不属于本窗口，其鼠标事件不能吞掉，否则菜单无法交互。
        if (etype == QEvent.Type.MouseMove and self._move_dragging
                and (obj is self or (isinstance(obj, QWidget) and self.isAncestorOf(obj)))):
            pos = event.globalPosition().toPoint()
            dx = pos.x() - self._move_global.x()
            dy = pos.y() - self._move_global.y()
            if not self._move_active and abs(dx) + abs(dy) > self.metrics.s(4):
                self._move_active = True
            if self._move_active:
                if not (event.buttons() & Qt.MouseButton.LeftButton):
                    self._move_dragging = False
                    self._move_active = False
                    return False
                self.move(self._move_origin + QPoint(dx, dy))
                return True
        if etype == QEvent.Type.MouseButtonRelease and self._move_dragging:
            self._move_dragging = False
            self._move_active = False
            # 不吞掉 release，保留子控件正常的点击/双击行为
        # 全局过滤器会收到所有窗口/弹窗的事件，只处理本窗口及其子控件。
        if obj is not self and not (isinstance(obj, QWidget) and self.isAncestorOf(obj)):
            return False
        if etype == QEvent.Type.MouseMove:
            self._update_resize_cursor(event.globalPosition().toPoint())
        elif etype == QEvent.Type.MouseButtonPress:
            # 按钮不触发缩放/移动（右上角窗口按钮、倍速徽标等）
            if isinstance(obj, QPushButton):
                return False
            pos = event.globalPosition().toPoint()
            if event.button() == Qt.MouseButton.LeftButton:
                edge = self._edge_at(pos)
                if edge:
                    self._resize_edge = edge
                    self._resize_origin = QRect(self.geometry())
                    self._resize_global = QPoint(pos)
                    # 按下时固定非视频区高度，避免拖动中布局实时变化导致比例累积误差
                    self._resize_chrome_h = max(0, self.height() - self.player_widget.height())
                    return True
                if self._move_drag_source(obj):
                    self._move_dragging = True
                    self._move_active = False
                    self._move_origin = self.pos()
                    self._move_global = QPoint(pos)
        return False

    def _move_drag_source(self, obj) -> bool:
        """判断控件是否属于可拖拽移动窗口的区域（视频区/菜单栏/下方工具栏）。"""
        if not isinstance(obj, QWidget):
            return False
        # 交互控件保持自身行为（按钮、滑块、输入框、下拉框、滚动条）
        if isinstance(obj, (QAbstractButton, QAbstractSlider, QAbstractSpinBox,
                            QComboBox, QLineEdit, QScrollBar)):
            return False
        # OSD 浮层、状态提示、右侧抽屉不参与窗口移动
        if obj is self.osd or self.osd.isAncestorOf(obj):
            return False
        if obj is self.status_toast:
            return False
        if obj is self.dock or self.dock.isAncestorOf(obj):
            return False
        # 编解码标签保留点击查看属性的行为
        if obj.objectName() == "codec":
            return False
        for host in (self.player_widget, self.control):
            if obj is host or host.isAncestorOf(obj):
                return True
        return False

    def _edge_at(self, global_pos: QPoint) -> str:
        """把全局坐标映射到窗口边缘，返回 l/r/t/b 及两字母角落组合。"""
        p = self.mapFromGlobal(global_pos)
        m = self._resize_margin
        w, h = self.width(), self.height()
        left = p.x() <= m
        right = p.x() >= w - m
        top = p.y() <= m
        bottom = p.y() >= h - m
        if top and left:
            return "tl"
        if top and right:
            return "tr"
        if bottom and left:
            return "bl"
        if bottom and right:
            return "br"
        if left:
            return "l"
        if right:
            return "r"
        if top:
            return "t"
        if bottom:
            return "b"
        return ""

    def _update_resize_cursor(self, global_pos: QPoint) -> None:
        """根据命中边缘设置方向光标；非边缘恢复默认光标。"""
        edge = self._edge_at(global_pos)
        cursors = {
            "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
            "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
            "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
            "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
        }
        if edge:
            self.setCursor(QCursor(cursors[edge]))
        elif self.cursor().shape() != Qt.CursorShape.ArrowCursor:
            self.unsetCursor()

    def _resize_by_drag(self, global_pos: QPoint) -> None:
        """按鼠标位移调整窗口；打开视频后锁定视频显示区宽高比。"""
        if self._resize_origin is None:
            return
        dx = global_pos.x() - self._resize_global.x()
        dy = global_pos.y() - self._resize_global.y()
        origin = self._resize_origin
        left, top = origin.left(), origin.top()
        right, bottom = origin.right(), origin.bottom()
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        edge = self._resize_edge

        if "l" in edge:
            left = min(right - min_w, left + dx)
        if "r" in edge:
            right = max(left + min_w, right + dx)
        if "t" in edge:
            top = min(bottom - min_h, top + dy)
        if "b" in edge:
            bottom = max(top + min_h, bottom + dy)

        # 锁定视频区比例（保持视频无黑边填充）：
        # 拖左右边/四角以宽度为基准反算高度；只拖上下边时以高度为基准反算宽度，
        # 否则上下边拖动会因宽度未变而无法改变窗口尺寸。
        if self._aspect_locked:
            chrome_h = getattr(self, "_resize_chrome_h", 0)
            horiz = "l" in edge or "r" in edge
            if horiz:
                new_w = max(min_w, right - left)
                video_h = int(round(new_w / self._video_aspect))
                target_h = max(min_h, video_h + chrome_h)
                if "t" in edge:
                    top = bottom - target_h
                else:
                    bottom = top + target_h
            else:
                new_h = max(min_h, bottom - top)
                video_h = max(1, new_h - chrome_h)
                target_w = max(min_w, int(round(video_h * self._video_aspect)))
                if "l" in edge:
                    left = right - target_w
                else:
                    right = left + target_w

        new_w = max(min_w, right - left)
        new_h = max(min_h, bottom - top)
        self.setGeometry(left, top, new_w, new_h)

    def _toggle_maximize(self) -> None:
        # 全屏时右上角按钮作为“退出全屏并恢复原窗口状态”使用。
        if self._fullscreen:
            self._toggle_fullscreen()
            return
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _toggle_fullscreen(self) -> None:
        if self._fullscreen:
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self) -> None:
        """全屏：把标题栏/进度条/控制栏从布局中取出，作为不影响视频尺寸的浮层。"""
        central = self.centralWidget()
        layout = central.layout()
        self._was_maximized_before_fullscreen = self.isMaximized()
        self._dock_visible_before_fullscreen = self.dock.isVisible()
        self._normal_geometry = self.saveGeometry()
        # 全屏时把播放列表从 QMainWindow 停靠布局移出，作为 central 的浮层子控件：
        # 停靠部件会覆盖视频区右侧整列并压住底部控制栏的列表按钮，导致无法再次收缩。
        self.removeDockWidget(self.dock)
        self.dock.setParent(central)
        self.dock.hide()

        # 记录移除前的真实索引，退出时按原顺序插回。
        # 不能硬编码：player_widget 占据索引 2，进度条/控制栏在其后（3、4），
        # 写错会让底部控制栏退出全屏后跑到视频区上方。
        overlay_widgets = [self.title_bar, self._menubar, self.progress, self.control]
        self._full_overlay_widgets = [(w, layout.indexOf(w)) for w in overlay_widgets]
        for widget, _index in self._full_overlay_widgets:
            layout.removeWidget(widget)
            widget.setParent(central)
            widget.hide()

        self._fs_top_visible = False
        self._fs_bottom_visible = False
        self._fullscreen = True
        self.showFullScreen()
        QApplication.processEvents()
        self._layout_fullscreen_overlays()

    def _layout_fullscreen_overlays(self) -> None:
        """按当前窗口尺寸重算浮层位置；隐藏时停在屏幕外，动画只改位置不改布局。"""
        if not self._fullscreen:
            return
        central = self.centralWidget()
        width, height = central.width(), central.height()
        top_h = self.title_bar.height()
        progress_h = self.progress.height()
        control_h = self.control.height()
        if progress_h <= 1:
            progress_h = self.metrics.s(16)
        if control_h <= 1:
            control_h = self.metrics.s(34)
        self._fs_top_h = top_h
        self._fs_bottom_h = progress_h + control_h

        top_y = 0 if self._fs_top_visible else -top_h
        progress_y = (height - self._fs_bottom_h) if self._fs_bottom_visible else height
        control_y = (height - control_h) if self._fs_bottom_visible else height
        self.title_bar.setGeometry(0, top_y, width, top_h)
        self.progress.setGeometry(0, progress_y, width, progress_h)
        self.control.setGeometry(0, control_y, width, control_h)
        # 全屏播放列表浮层：停靠右侧，底边止于进度条上方，绝不覆盖底部控制栏，
        # 因此列表按钮始终可见可点，可再次点击收缩。
        if self._fullscreen:
            dock_w = max(self.dock.minimumSizeHint().width(),
                         min(self.metrics.s(360), max(self.metrics.s(260), width // 3)))
            dock_h = max(self.metrics.s(160), height - self._fs_bottom_h)
            self.dock.setGeometry(width - dock_w, 0, dock_w, dock_h)
            self.dock.raise_()
        if self._fs_top_visible:
            self.title_bar.raise_()
        if self._fs_bottom_visible:
            self.progress.raise_()
            self.control.raise_()

    def _slide_widget(self, widget: QWidget, visible: bool, shown_y: int, hidden_y: int) -> None:
        """用位置动画滑入/滑出浮层，不触碰布局，视频区尺寸保持不变。"""
        anim = getattr(widget, "_fs_anim", None)
        if anim is not None:
            anim.stop()
        if visible:
            widget.show()
            widget.raise_()
        animation = QPropertyAnimation(widget, b"pos")
        animation.setDuration(180)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(QPoint(widget.x(), widget.y()))
        animation.setEndValue(QPoint(widget.x(), shown_y if visible else hidden_y))
        if not visible:
            animation.finished.connect(lambda target=widget: target.hide())
        animation.start()
        widget._fs_anim = animation

    def _show_fullscreen_top(self) -> None:
        if self._fs_top_visible:
            return
        self._fs_top_visible = True
        self._slide_widget(self.title_bar, True, 0, -self._fs_top_h)

    def _hide_fullscreen_top(self) -> None:
        if not self._fs_top_visible:
            return
        self._fs_top_visible = False
        self._slide_widget(self.title_bar, False, 0, -self._fs_top_h)

    def _show_fullscreen_bottom(self) -> None:
        if self._fs_bottom_visible:
            return
        self._fs_bottom_visible = True
        height = self.centralWidget().height()
        self._slide_widget(
            self.progress, True, height - self._fs_bottom_h, height
        )
        self._slide_widget(
            self.control, True, height - self.control.height(), height
        )

    def _hide_fullscreen_bottom(self) -> None:
        if not self._fs_bottom_visible:
            return
        self._fs_bottom_visible = False
        height = self.centralWidget().height()
        self._slide_widget(
            self.progress, False, height - self._fs_bottom_h, height
        )
        self._slide_widget(
            self.control, False, height - self.control.height(), height
        )

    def _update_fullscreen_overlays(self, global_pos: QPoint) -> None:
        rect = self.geometry()
        if not rect.contains(global_pos):
            self._hide_fullscreen_top()
            self._hide_fullscreen_bottom()
            return
        top_zone = max(self._fs_top_h, self.metrics.s(48))
        bottom_zone = max(self._fs_bottom_h, self.metrics.s(56))
        if global_pos.y() <= rect.top() + top_zone:
            self._show_fullscreen_top()
        else:
            self._hide_fullscreen_top()
        if global_pos.y() >= rect.bottom() - bottom_zone:
            self._show_fullscreen_bottom()
        else:
            self._hide_fullscreen_bottom()

    def _exit_fullscreen(self) -> None:
        """退出全屏并恢复进入前的最大化/普通窗口状态。"""
        for widget, _index in self._full_overlay_widgets:
            anim = getattr(widget, "_fs_anim", None)
            if anim is not None:
                anim.stop()
        self._fs_top_visible = False
        self._fs_bottom_visible = False
        self._fullscreen = False

        self.showNormal()
        if self._was_maximized_before_fullscreen:
            self.showMaximized()
        elif self._normal_geometry:
            self.restoreGeometry(self._normal_geometry)

        central = self.centralWidget()
        layout = central.layout()
        # 按原始索引从小到大插回，保证视频区仍在进度条/控制栏之上方，
        # 退出全屏后恢复 title → menubar → 视频 → 进度 → 控制栏的顺序。
        for widget, index in sorted(self._full_overlay_widgets, key=lambda item: item[1]):
            widget.setParent(central)
            layout.insertWidget(index, widget)
            widget.show()
        self._full_overlay_widgets = []

        # 退出全屏：把浮层形态的播放列表重新停靠回右侧，并恢复进入前的可见性
        self.dock.setParent(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        if self._dock_visible_before_fullscreen:
            self.dock.show()
        self._position_status_toast()
        if self.osd.isVisible():
            self.osd.refresh_geometry()
            self.osd.raise_()

    def _escape(self) -> None:
        if self._fullscreen:
            self._toggle_fullscreen()
        elif self.osd.isVisible():
            self.osd.hide_osd()
            self.control.effects_btn.setChecked(False)

    def _toggle_playlist_dock(self) -> None:
        self._set_playlist_visible(not self.dock.isVisible())

    def _set_playlist_visible(self, visible: bool) -> None:
        if visible:
            self.dock.show()
            self.dock.raise_()
            if self._fullscreen:
                # 重新定位浮层并让底部控制栏保持在最上层，列表按钮不被遮挡
                self._layout_fullscreen_overlays()
                self.progress.raise_()
                self.control.raise_()
        else:
            self.dock.hide()
        self.control.list_btn.setChecked(visible)

    def _show_iptv_panel(self) -> None:
        self.dock.show()
        self.dock_contents.setCurrentIndex(1)

    def _update_status(self, message: str) -> None:
        toast = getattr(self, "status_toast", None)
        if toast is None:
            return
        toast.setText(message[:160])
        self._position_status_toast()
        toast.raise_()
        toast.show()
        self._toast_timer.start(2600)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_status_toast()
        if self._fullscreen:
            self._layout_fullscreen_overlays()
        # 窗口尺寸变化（最大化/拉伸）后重算 Tab OSD 几何，避免信息行被裁切。
        if self.osd.isVisible():
            self.osd.refresh_geometry()
            self.osd.raise_()

    def closeEvent(self, event) -> None:  # noqa: N802
        active = [task for task in self.recorder.tasks if task.status == TaskStatus.RECORDING.value]
        if active:
            answer = QMessageBox.question(
                self, tr("提示"),
                f"{len(active)} {tr('录制中')}，是否停止录制并保存？\n"
                f"{tr('是')} = 停止并保存；{tr('否')} = 保持当前任务（进程退出后视为中断）",
            )
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        self._save_playback_position()
        self.recorder.shutdown()
        self.player.shutdown()
        event.accept()
