"""Windows 开机自启动（HKCU Run 项）。非 Windows 平台为无操作。

通过注册表当前用户 Run 项实现，写入的是本程序可执行命令：
- 打包模式：直接写 EXE 绝对路径（带引号，兼容含空格路径）；
- 源码模式：写当前 Python 解释器 + main.py（便于开发调试）。
"""

from __future__ import annotations

import os
import sys

APP_NAME = "CXPurePlayer"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _exe_command() -> str:
    """生成开机自启动命令行。"""
    if getattr(sys, "frozen", False):
        return f'"{os.path.abspath(sys.executable)}"'
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main_py = os.path.join(root, "main.py")
    return f'"{sys.executable}" "{main_py}"'


def is_enabled() -> bool:
    """读取当前是否已设置开机自启动。"""
    if os.name != "nt":
        return False
    try:
        import winreg  # type: ignore[import-not-found]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except OSError:
        return False


def set_enabled(enabled: bool) -> str:
    """开启/关闭开机自启动；返回空串表示成功，否则返回错误描述。"""
    if os.name != "nt":
        return "当前系统不支持开机自启动"
    try:
        import winreg  # type: ignore[import-not-found]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_WRITE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _exe_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return ""
    except OSError as exc:
        return str(exc)
