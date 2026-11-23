"""Tab 播放信息 OSD：视频区左上角半透明浮层，单页集中展示全部信息，支持滚动。"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QScrollBar, QWidget

from ..core.i18n import tr
from ..core.models import MediaState, format_speed
from ..core.theme import palette


class OsdOverlay(QWidget):
    """把所有播放/视频/音频信息合并到一块浮层，Tab 或右下角按钮显示/隐藏。

    面板按正常字号排版，长行按真实字体度量自动折行；空间不足时显示内嵌
    垂直滚动条，可拖动或滚轮查看所有字段，绝不压缩字号、绝不裁切信息。
    """

    PAGES = 1

    def __init__(self, metrics, parent=None) -> None:
        super().__init__(parent)
        self.m = metrics
        self._page = 0
        self._state = MediaState()
        self._media_name = ""
        self._details: dict = {}
        self._line_h = self.m.s(22)
        self._font_pt = max(9, int(self.m.font(10)))
        self._rows: list[tuple[str, bool]] = []
        # libmpv 以 wid 嵌入视频时直接绘制在父窗口的原生表面上，普通子控件会被
        # 视频层遮挡。将 OSD 提升为原生子窗口并置顶，保证 Tab 信息浮层可见。
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        # 全局 QSS 的 `QWidget { background: ... }` 会在自绘之后再次填充窗口，
        # 关闭样式表背景，只保留自绘，保证整块浮层背景色完全一致。
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        # 面板视觉尺寸即原生窗口尺寸；整块窗口只画一个圆角背景。
        self._panel_w = self.m.s(360)
        self._panel_h = self.m.s(210)
        # 不再设置 WA_TransparentForMouseEvents：该属性会连同子控件一起屏蔽
        # 鼠标事件，滚动条将无法拖动/滚轮。浮层只在 Tab 打开期间接收鼠标。
        self._scroll = QScrollBar(Qt.Orientation.Vertical, self)
        self._scroll.setObjectName("osdScrollBar")
        self._scroll.setSingleStep(1)
        self._scroll.valueChanged.connect(self.update)
        self._scroll.hide()
        self.setVisible(False)

    def _apply_scroll_style(self) -> None:
        """滚动条跟随当前主题配色与 UI 缩放。"""
        p = palette()
        accent = QColor(p["accent"])
        w = self.m.s(8)
        self._scroll.setStyleSheet(
            f"QScrollBar#osdScrollBar:vertical {{"
            f"background: transparent; width: {w}px; margin: 0px; border: none; }}"
            f"QScrollBar#osdScrollBar::groove:vertical {{ background: transparent; }}"
            f"QScrollBar#osdScrollBar::handle:vertical {{"
            f"background: rgba({accent.red()},{accent.green()},{accent.blue()},150);"
            f"border-radius: {max(2, w // 2)}px; min-height: {self.m.s(24)}px; }}"
            f"QScrollBar#osdScrollBar::handle:vertical:hover {{"
            f"background: rgba({accent.red()},{accent.green()},{accent.blue()},225); }}"
            f"QScrollBar#osdScrollBar::add-line:vertical, "
            f"QScrollBar#osdScrollBar::sub-line:vertical {{ height: 0px; }}"
        )

    def toggle(self) -> None:
        """Tab 快捷键 / 右下角按钮：显示/隐藏同一块合并信息。"""
        show = not self.isVisible()
        self._page = 0
        if show:
            # 必须先按真实内容重算几何再显示：原生子窗口首次显示时会立刻
            # 按构造时的 360x210 画一帧，之后 resize 不会擦掉旧帧，会留下
            # 重叠的残影（duplicate text / 内部蓝线）。
            self.refresh_geometry()
            self.setVisible(True)
            self.raise_()
        else:
            self.setVisible(False)
        self.update()

    def hide_osd(self) -> None:
        self.setVisible(False)
        self.update()

    def _font(self, bold: bool = False, pt: int | None = None) -> QFont:
        font = QFont("Microsoft YaHei", pt or self._font_pt)
        font.setBold(bold)
        return font

    def _wrap_rows(self, lines: list[tuple[str, bool]], max_width: int) -> list[tuple[str, bool]]:
        """按真实字体度量把过长的信息行折成多行，避免右侧文字被裁切。"""
        rows: list[tuple[str, bool]] = []
        fm = QFontMetrics(self._font(False))
        for text, header in lines:
            if header or not text or fm.horizontalAdvance(text) <= max_width:
                rows.append((text, header))
                continue
            current = ""
            for ch in text:
                if current and fm.horizontalAdvance(current + ch) > max_width:
                    rows.append((current, False))
                    current = "  " + ("" if ch == " " else ch)
                else:
                    current += ch
            if current:
                rows.append((current, False))
        return rows

    def refresh_geometry(self) -> None:
        """按当前信息行重算几何：固定可读字号，超出可用高度时启用滚动条。"""
        top = self.parent()
        if top is None:
            return
        pad = self.m.s(12)
        line_h = self.m.s(22)
        font_pt = max(9, int(self.m.font(10)))
        self._line_h = line_h
        self._font_pt = font_pt
        self._apply_scroll_style()

        avail_w = max(self.m.s(280), top.width() - self.m.s(28))
        avail_h = max(self.m.s(200), top.height() - self.m.s(28))
        scroll_reserve = self.m.s(12)

        lines = self._lines()
        max_w = 0
        for text, header in lines:
            max_w = max(max_w, QFontMetrics(self._font(header, font_pt)).horizontalAdvance(text))
        # 面板宽度在按文字度量的基础上再加宽 20%（仍受视频区可用宽度约束）。
        base_w = max(self.m.s(300), max_w + pad * 2 + scroll_reserve)
        width = min(int(base_w * 1.2), avail_w)
        text_w = max(self.m.s(160), width - pad * 2 - scroll_reserve)
        self._rows = self._wrap_rows(lines, text_w)

        # 面板高度按 20 行布局，实际只有 16 行内容，底部自然留出约 4 行空白；
        # 空间不足时面板收缩，滚动范围只按真实内容行计算，避免滚出空白区域。
        panel_h = pad * 2 + line_h * max(20, len(self._rows))
        height = min(panel_h, avail_h)
        real_h = pad * 2 + line_h * max(1, len(self._rows))
        self._panel_w, self._panel_h = width, height
        # 窗口尺寸等于面板尺寸；背景铺满窗口，整块浮层统一底色。
        self.setGeometry(self.m.s(14), self.m.s(14), width, height)

        bar_w = self.m.s(8)
        self._scroll.setGeometry(width - pad - bar_w, pad,
                                 bar_w, max(0, height - pad * 2))
        self._scroll.setRange(0, max(0, real_h - height))
        self._scroll.setPageStep(max(1, (height - pad * 2) // max(1, line_h)))
        need_scroll = real_h > height
        self._scroll.setVisible(need_scroll)
        if not need_scroll:
            self._scroll.setValue(0)
        self._scroll.raise_()
        self.raise_()

    def set_info(self, state: MediaState, name: str, details: dict | None = None) -> None:
        self._state = state
        self._media_name = name or state.title
        if details:
            self._details = details
        if self.isVisible():
            self.refresh_geometry()
            self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if not self._scroll.isVisible():
            event.ignore()
            return
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        direction = 1 if delta > 0 else -1
        self._scroll.setValue(self._scroll.value() - direction * max(1, self._line_h // 2))
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self.isVisible() or self._page >= self.PAGES:
            return
        p = palette()
        m = self.m
        pad = m.s(12)
        line_h = self._line_h
        pw, ph = self._panel_w, self._panel_h
        rows = self._rows or self._wrap_rows(self._lines(), max(self.m.s(160), pw - pad * 3))
        # 直接在本窗口上绘制，不经过离屏 QPixmap 中转：高 DPI 屏幕上离屏画布
        # 用逻辑像素尺寸，drawPixmap 贴回原生窗口时会被二次缩放，导致文字发虚。
        # 直接在窗口 painter 上绘制，字体按设备像素渲染，清晰锐利。
        painter = QPainter(self)
        # 原生窗口不会自动擦除背景（WA_NoSystemBackground），窗口放大后上一帧
        # 的旧内容会残留；先用 Clear 模式清空整窗，再绘制当前面板，避免残影。
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        panel_rect = QRect(0, 0, pw, ph)
        radius = m.s(10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p["panel_alt"]))
        painter.drawRoundedRect(panel_rect, radius, radius)
        text_right = pw - pad
        if self._scroll.isVisible():
            text_right -= self._scroll.width() + m.s(4)
        text_right = max(pad + 1, text_right)
        painter.setClipRect(pad, pad, text_right - pad, max(1, ph - pad * 2))
        offset = self._scroll.value() if self._scroll.isVisible() else 0
        font = self._font()
        for index, (text, header) in enumerate(rows):
            y = pad + line_h * index - offset
            if y + line_h <= pad:
                continue
            if y >= ph - pad:
                break
            if header:
                f = QFont(font)
                f.setBold(True)
                painter.setFont(f)
                painter.setPen(QColor(p["accent"]))
            else:
                painter.setFont(font)
                painter.setPen(QColor(p["text"]))
            painter.drawText(pad, y, text_right - pad, line_h,
                             Qt.AlignmentFlag.AlignVCenter, text)
        painter.end()

    def _lines(self) -> list[tuple[str, bool]]:
        """返回 (文本, 是否分节标题) 列表，三块信息合并为同一页（16 行）。"""
        s = self._state
        d = self._details
        duration = "● LIVE" if s.live else self._fmt(s.duration)
        lines: list[tuple[str, bool]] = []
        lines.append((tr("播放信息"), True))
        lines.append((f"  {tr('文件名')}: {self._media_name or '--'}", False))
        lines.append((f"  {tr('当前时间')}: {self._fmt(s.time_pos)} / {duration}", False))
        lines.append((f"  {tr('播放速度')}: {format_speed(s.speed)}   {tr('音量')}: {s.volume}%"
                      f"  ({tr('静音') if s.muted else 'ON'})", False))
        lines.append(("", False))
        lines.append((tr("视频"), True))
        lines.append((f"  {tr('视频编码')}: {d.get('video_codec') or s.video_codec or '--'}"
                      f"   {tr('格式')}: {d.get('format') or '--'}", False))
        lines.append((f"  {tr('分辨率')}: {d.get('resolution') or '--'}"
                      f"   {tr('宽高比')}: {d.get('aspect') or '--'}"
                      f"   {tr('扫描方式')}: {d.get('scan') or '--'}", False))
        lines.append((f"  {tr('帧率')}: {d.get('fps') or '--'} fps"
                      f"   {tr('像素格式')}: {d.get('pix_fmt') or '--'}", False))
        lines.append((f"  {tr('视频码率')}: {d.get('video_bitrate') or '--'}"
                      f"   {tr('矩阵系数')}: {d.get('colormatrix') or '--'}", False))
        lines.append((f"  {tr('视频输出')}: {s.vo or '--'}"
                      f"   {tr('硬解状态')}: {s.hwdec or '--'}"
                      f"   {tr('丢帧数')}: {int(s.drop_frames or 0)}", False))
        lines.append(("", False))
        lines.append((tr("音频"), True))
        lines.append((f"  {tr('音频编码')}: {d.get('audio_codec') or s.audio_codec or '--'}"
                      f"   {tr('音频码率')}: {d.get('audio_bitrate') or '--'}", False))
        lines.append((f"  {tr('采样率')}: {d.get('sample_rate') or '--'}"
                      f"   {tr('声道数')}: {d.get('channels') or '--'}"
                      f"   AO: {s.ao or '--'}", False))
        lines.append((f"  {tr('文件大小')}: {d.get('size') or '--'}"
                      f"   {tr('总码率')}: {d.get('overall_bitrate') or '--'}"
                      f"   {tr('字幕轨')}: {d.get('sub_count', '--')}"
                      f"   {tr('章节')}: {d.get('chapter_count', '--')}", False))
        return lines

    @staticmethod
    def _fmt(value: float) -> str:
        seconds = max(0, int(value or 0))
        h, rest = divmod(seconds, 3600)
        minute, sec = divmod(rest, 60)
        return f"{h:02d}:{minute:02d}:{sec:02d}" if h else f"{minute:02d}:{sec:02d}"
