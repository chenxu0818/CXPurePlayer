"""v1.0.3 跨平台支持专项回归：用户数据目录、字体、开机自启动降级。"""
from __future__ import annotations

import os
import sys

from app.core import autostart
from app.core import settings as settings_mod
from app.core import ui_scale as ui_scale_mod
from app.core.settings import user_data_root
from app.core.ui_scale import ui_font_family


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


def test_ui_font_family_switches_on_macos(monkeypatch) -> None:
    monkeypatch.setattr(ui_scale_mod.sys, "platform", "darwin")
    assert ui_font_family() == "PingFang SC"

    monkeypatch.setattr(ui_scale_mod.sys, "platform", "win32")
    assert ui_font_family() == "Microsoft YaHei"
