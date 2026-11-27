"""基于系统 ffmpeg 的流录制：整流 stream copy，保留全部音轨。

libmpv 的 ``stream-record`` 只写入"被选中"的轨道，遇到双音轨（如 mp2 + ac3）
IPTV 时只会录下其中一个。ffmpeg 的 ``-map 0 -c copy`` 会映射并复制 demuxer
中的全部流，完整保留双音轨。ffmpeg 作为可选外部工具（从 bin/ 或系统 PATH
查找，不随包），不可用时调用方回退到 libmpv。
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from .logger import log_error, log_info
from .settings import resource_root, subprocess_env

FFMPEG_CANDIDATES = [
    os.path.join(resource_root(), "bin", "ffmpeg.exe"),
    os.path.join(resource_root(), "bin", "ffmpeg"),
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "ffmpeg",
]


def ffmpeg_path() -> str:
    """返回可用的 ffmpeg 路径；仅系统 PATH 时返回 'ffmpeg' 供 Popen 解析。"""
    for candidate in FFMPEG_CANDIDATES:
        if candidate == "ffmpeg":
            return candidate  # 交给 Popen 在 PATH 中查找，找不到会抛 FileNotFoundError
        if os.path.isfile(candidate):
            return candidate
    return ""


def has_ffmpeg() -> bool:
    """探测系统是否可用 ffmpeg（真正执行一次 -version）。"""
    binary = ffmpeg_path()
    if not binary:
        return False
    try:
        result = subprocess.run(
            [binary, "-version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5,
            env=subprocess_env(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def build_ffmpeg_cmd(url: str, output: str, fmt: str = "source") -> list[str]:
    """构造整流复制命令：-map 0 保留全部音视频轨道，不做重编码。

    fmt='source' 时由输出扩展名决定封装（调用方已按源类型选好 .ts/.mp4 等）；
    其余格式同样交给扩展名，保证与 libmpv 回退路径行为一致。
    """
    return [
        ffmpeg_path() or "ffmpeg",
        "-hide_banner", "-loglevel", "warning",
        "-rw_timeout", "15000000",  # 网络读超时 15s（微秒），避免卡死
        "-i", url,
        "-map", "0",                # 关键：映射全部流（含所有音轨）
        "-c", "copy",               # 不重编码，仅换封装/透传
        "-f", "mpegts" if output.lower().endswith(".ts") else _guess_format(output),
        "-y", output,
    ]


def _guess_format(output: str) -> str:
    ext = os.path.splitext(output)[1].lower().lstrip(".")
    return {"mp4": "mp4", "mkv": "matroska", "flv": "flv", "avi": "avi", "webm": "webm"}.get(ext, "mpegts")


def spawn(url: str, output: str) -> Optional[subprocess.Popen]:
    """启动 ffmpeg 录制进程；失败返回 None 并写日志。"""
    cmd = build_ffmpeg_cmd(url, output)
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=subprocess_env(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log_info(f"[录制] ffmpeg 整流录制启动：{output}（保留全部音轨）")
        return proc
    except (OSError, subprocess.SubprocessError) as exc:
        log_error(f"[录制] ffmpeg 启动失败，将回退 libmpv：{exc}")
        return None


def stop(proc: subprocess.Popen, timeout: float = 8.0) -> None:
    """优雅停止：向 stdin 发 q 让 ffmpeg 写完 muxer 尾，超时再强杀。"""
    if proc.poll() is not None:
        return
    try:
        if proc.stdin is not None:
            proc.stdin.write(b"q\n")
            proc.stdin.flush()
            try:
                proc.wait(timeout=timeout)
                return
            except subprocess.TimeoutExpired:
                pass
    except (OSError, ValueError):
        pass
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
    except Exception:
        pass
