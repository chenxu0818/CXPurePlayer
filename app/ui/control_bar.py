"""底部三段式控制栏：音量 / 播放控制 / 编码与播放列表开关。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QSizePolicy, QVBoxLayout, QWidget,
)

from ..core.i18n import source_text, tr
from ..core.theme import palette
from .icons import icon
from .widget_utils import mark_dynamic


def format_time(seconds: float, live: bool = False) -> str:
    if live:
        return "● LIVE"
    value = max(0, int(seconds or 0))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit()
        super().mousePressEvent(event)


class IconButton(QPushButton):
    def __init__(self, icon_name: str, tip: str = "", parent=None) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        # 保存源文案而非已翻译文案：切换语言时用源文案重新查字典，
        # 否则英文态下 tr("Mute") 找不到条目，会停留在英文。
        self._tip = source_text(tip)
        self.setObjectName("iconButton")
        self.setToolTip(tr(self._tip))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(False)
        self.refresh_icon()

    def refresh_icon(self) -> None:
        self.setIcon(icon(self._icon_name, palette().get("text_soft", "#aab6cb")))

    def retranslate(self) -> None:
        self.setToolTip(tr(self._tip))

    def set_active_icon(self, active: bool, checked_color: str = "#ffffff") -> None:
        color = checked_color if active else palette().get("text_soft", "#aab6cb")
        self.setIcon(icon(self._icon_name, color))


class ControlBar(QWidget):
    playPause = Signal()
    stop = Signal()
    rewind = Signal()
    forward = Signal()
    volumeChanged = Signal(int)
    muteToggled = Signal(bool)
    togglePlaylist = Signal(bool)

    def __init__(self, metrics, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("controlPanel")
        self.m = metrics
        self._muted = False
        self._live = False
        self._has_media = False
        self._video_codec = ""
        self._audio_codec = ""
        self._build()
        self.apply_scale()
        # 初始无媒体：播放/停止/快进/快退不可用，避免空点击报错。
        self.set_has_media(False)

    def apply_scale(self) -> None:
        """控制栏整体高度约为原基准的 70%（34px @ 100%）。"""
        m = self.m
        self.setFixedHeight(m.s(34))
        layout = self.layout()
        if layout is not None:
            layout.setContentsMargins(m.s(14), m.s(4), m.s(14), m.s(4))
            layout.setSpacing(m.s(10))

    def _build(self) -> None:
        m = self.m
        root = QHBoxLayout(self)
        root.setContentsMargins(m.s(14), m.s(4), m.s(14), m.s(4))
        root.setSpacing(m.s(10))

        # 左下：音量
        left = QHBoxLayout()
        left.setSpacing(m.s(6))
        self.mute_btn = IconButton("volume", tr("静音"))
        self.mute_btn.clicked.connect(self._on_mute_clicked)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("volumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.valueChanged.connect(self.volumeChanged.emit)
        self.volume_label = mark_dynamic(QLabel("100%"))
        self.volume_label.setObjectName("volumeValue")
        self.volume_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        left.addWidget(self.mute_btn)
        left.addWidget(self.volume_slider)
        left.addWidget(self.volume_label)

        # 中间：播放控制
        center = QHBoxLayout()
        center.setSpacing(m.s(4))
        self.rewind_btn = IconButton("rewind", tr("快退"))
        self.play_btn = IconButton("play", tr("播放 / 暂停"))
        self.stop_btn = IconButton("stop", tr("停止"))
        self.forward_btn = IconButton("forward", tr("快进"))
        for btn, slot in (
            (self.rewind_btn, self.rewind), (self.play_btn, self.playPause),
            (self.stop_btn, self.stop), (self.forward_btn, self.forward),
        ):
            btn.clicked.connect(slot.emit)
            center.addWidget(btn)

        self.time_label = mark_dynamic(QLabel("00:00 / 00:00"))
        self.time_label.setObjectName("time")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setMinimumWidth(m.s(140))
        center.addSpacing(m.s(8))
        center.addWidget(self.time_label)

        self.video_codec = ClickableLabel("视频：--")
        self.audio_codec = ClickableLabel("音频：--")
        for label in (self.video_codec, self.audio_codec):
            label.setObjectName("codec")
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            center.addWidget(label)
        center.addStretch(1)

        # 右下：列表开关
        self.list_btn = IconButton("list", tr("播放列表"))
        self.list_btn.setCheckable(True)
        self.list_btn.clicked.connect(lambda checked: self.togglePlaylist.emit(checked))
        self.effects_btn = IconButton("settings", "Tab OSD")
        self.effects_btn.setCheckable(True)

        root.addLayout(left, 1)
        root.addStretch(1)
        root.addLayout(center, 0)
        root.addStretch(1)
        tail = QHBoxLayout()
        tail.setSpacing(m.s(3))
        tail.addWidget(self.effects_btn)
        tail.addWidget(self.list_btn)
        root.addLayout(tail, 1)

    # --- 状态更新 ---
    def set_playing(self, playing: bool) -> None:
        name = "pause" if playing else "play"
        if self.play_btn._icon_name != name:
            self.play_btn._icon_name = name
            self.play_btn.refresh_icon()

    def set_has_media(self, has_media: bool) -> None:
        """无媒体时禁用播放/快进/快退/停止，避免空操作报错。

        直播时快进/快退仍禁用；有媒体后按当前直播状态恢复快进/快退。
        """
        self._has_media = has_media
        self.play_btn.setEnabled(has_media)
        self.stop_btn.setEnabled(has_media)
        self.rewind_btn.setEnabled(has_media and not self._live)
        self.forward_btn.setEnabled(has_media and not self._live)

    def set_volume(self, volume: int, muted: bool) -> None:
        self._muted = muted
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(max(0, min(100, int(volume))))
        self.volume_slider.blockSignals(False)
        self.volume_label.setText(f"{int(volume)}%")
        self.mute_btn._icon_name = "mute" if muted else "volume"
        self.mute_btn.refresh_icon()

    def _on_mute_clicked(self) -> None:
        self._muted = not self._muted
        self.muteToggled.emit(self._muted)

    def set_time(self, pos: float, duration: float, live: bool = False) -> None:
        self.time_label.setText(f"{format_time(pos, live)} / {format_time(duration)}")

    def set_codecs(self, video: str, audio: str) -> None:
        self._video_codec = video
        self._audio_codec = audio
        self.video_codec.setText(f"{tr('视频')}：{video or '--'}")
        self.audio_codec.setText(f"{tr('音频')}：{audio or '--'}")

    def retranslate(self) -> None:
        self.mute_btn.retranslate()
        self.rewind_btn.retranslate()
        self.play_btn.retranslate()
        self.stop_btn.retranslate()
        self.forward_btn.retranslate()
        self.list_btn.retranslate()
        self.effects_btn.retranslate()
        self.set_codecs(self._video_codec, self._audio_codec)

    def set_live(self, live: bool) -> None:
        self._live = live
        # 直播禁用快进/快退；无媒体时同步禁用，避免空操作。
        self.rewind_btn.setEnabled(self._has_media and not live)
        self.forward_btn.setEnabled(self._has_media and not live)
        if live:
            self.time_label.setText("● LIVE")

    def refresh_icons(self) -> None:
        for btn in (self.mute_btn, self.rewind_btn, self.play_btn, self.stop_btn,
                    self.forward_btn, self.list_btn, self.effects_btn):
            btn.refresh_icon()
