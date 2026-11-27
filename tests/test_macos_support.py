"""v1.0.3 跨平台支持专项回归：用户数据目录、字体、开机自启动降级。"""
from __future__ import annotations

import os
import sys

from app.core import autostart
from app.core import mpv_player as mpv_player_mod
from app.core import settings as settings_mod
from app.core import ui_scale as ui_scale_mod
from app.core.settings import subprocess_env, user_data_root
from app.core.ui_scale import ui_font_family
from app.ui.mpv_render_widget import MpvRenderWidget


def test_autostart_supported_only_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(autostart.os, "name", "nt")
    assert autostart.is_supported() is True

    monkeypatch.setattr(autostart.os, "name", "posix")
    assert autostart.is_supported() is False
    assert autostart.is_enabled() is False
    assert autostart.set_enabled(True) == "当前系统不支持开机自启动"


def test_user_data_root_windows_frozen_keeps_exe_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings_mod.sys, "platform", "win32")
    monkeypatch.setattr(settings_mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(settings_mod.sys, "executable", str(tmp_path / "CXPurePlayer.exe"))
    assert user_data_root() == str(tmp_path)


def test_user_data_root_macos_frozen_uses_application_support(monkeypatch, tmp_path) -> None:
    real_expanduser = settings_mod.os.path.expanduser
    monkeypatch.setattr(
        settings_mod.os.path,
        "expanduser",
        lambda path: str(tmp_path) if path == "~" else real_expanduser(path),
    )
    monkeypatch.setattr(settings_mod.sys, "platform", "darwin")
    monkeypatch.setattr(settings_mod.sys, "frozen", True, raising=False)

    expected = os.path.join(str(tmp_path), "Library", "Application Support", "CXPurePlayer")
    assert user_data_root() == expected
    assert os.path.isdir(expected)


def test_mpv_init_options_macos_does_not_pass_wid(monkeypatch) -> None:
    monkeypatch.setattr(mpv_player_mod.sys, "platform", "darwin")
    options = mpv_player_mod.mpv_init_options(12345, "gpu")
    assert "wid" not in options
    assert options["vo"] == "libmpv"


def test_mpv_init_options_windows_keeps_embedded_wid(monkeypatch) -> None:
    monkeypatch.setattr(mpv_player_mod.sys, "platform", "win32")
    options = mpv_player_mod.mpv_init_options(12345, "gpu")
    assert options["wid"] == "12345"
    assert options["vo"] == "gpu"


def test_ui_font_family_switches_on_macos(monkeypatch) -> None:
    monkeypatch.setattr(ui_scale_mod.sys, "platform", "darwin")
    assert ui_font_family() == "PingFang SC"

    monkeypatch.setattr(ui_scale_mod.sys, "platform", "win32")
    assert ui_font_family() == "Microsoft YaHei"


def test_subprocess_env_drops_injected_dyld_paths(monkeypatch) -> None:
    """外部 ffmpeg/ffprobe 不能继承随包 libav* 搜索路径。"""
    monkeypatch.setattr(settings_mod.sys, "platform", "darwin")
    monkeypatch.setattr(settings_mod.os.path, "sep", "/")
    monkeypatch.setattr(settings_mod.os, "pathsep", ":")
    monkeypatch.setattr(settings_mod, "bin_dirs", lambda: ["/Applications/CXPurePlayer.app/bin"])
    monkeypatch.setenv(
        "DYLD_LIBRARY_PATH",
        "/Applications/CXPurePlayer.app/bin:/usr/local/lib",
    )
    monkeypatch.setenv("DYLD_FALLBACK_LIBRARY_PATH", "/Applications/CXPurePlayer.app/bin")

    env = subprocess_env()
    assert "CXPurePlayer.app/bin" not in env.get("DYLD_LIBRARY_PATH", "")
    assert "/usr/local/lib" in env.get("DYLD_LIBRARY_PATH", "")
    assert "DYLD_FALLBACK_LIBRARY_PATH" not in env


def test_subprocess_env_unchanged_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(settings_mod.sys, "platform", "win32")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/somewhere")
    assert subprocess_env().get("DYLD_LIBRARY_PATH") == "/somewhere"


def test_render_context_retries_after_player_ready(app) -> None:
    """initializeGL 早于 mpv 就绪时不能把渲染上下文永久标记为 ready。"""

    class FakePlayer:
        available = False

        def __init__(self) -> None:
            self.created = 0
            self.callback = None

        def create_render_context(self, _get_proc_address) -> bool:
            self.created += 1
            return self.available

        def set_render_update_callback(self, callback) -> None:
            self.callback = callback

    player = FakePlayer()
    widget = MpvRenderWidget(object(), player)
    assert widget._setup_render_context() is False
    assert widget._render_ready is False

    player.available = True
    assert widget._setup_render_context() is True
    assert widget._render_ready is True
    assert player.created == 1
    assert player.callback is not None
    widget.deleteLater()
