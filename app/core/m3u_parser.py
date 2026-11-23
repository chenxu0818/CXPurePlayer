"""本地 M3U / M3U8 频道列表解析与导出（不联网拉取）。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Tuple
from urllib.parse import urljoin

from .models import Channel

_ATTR = re.compile(r'([\w-]+)="([^"]*)"')


@dataclass
class ParseResult:
    channels: List[Channel] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    source: str = ""

    @property
    def total(self) -> int:
        return len(self.channels) + len(self.skipped)


def _absolute_url(url: str, base_dir: str) -> str:
    url = (url or "").strip()
    if not url:
        return url
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        return url
    if url.startswith(("/", "\\")):
        return os.path.abspath(url)
    return os.path.abspath(os.path.join(base_dir, url))


def parse_m3u(path: str) -> ParseResult:
    """解析本地 m3u/m3u8，相对 URL 按列表所在目录补全。"""
    result = ParseResult(source=path)
    base_dir = os.path.dirname(os.path.abspath(path)) or os.getcwd()
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        result.skipped.append(f"读取失败：{exc}")
        return result

    pending_name = ""
    pending_attrs: dict = {}
    pending_group = ""

    def flush(url: str) -> None:
        nonlocal pending_name, pending_attrs, pending_group
        if not url:
            return
        name = (
            pending_attrs.get("tvg-name")
            or pending_name
            or os.path.splitext(os.path.basename(url))[0]
        ).strip()
        if not name:
            result.skipped.append(url)
        else:
            result.channels.append(
                Channel(
                    name=name,
                    url=_absolute_url(url, base_dir),
                    group=(pending_attrs.get("group-title") or pending_group or "默认分组").strip(),
                    logo=_absolute_url(pending_attrs.get("tvg-logo", ""), base_dir)
                    if pending_attrs.get("tvg-logo") else "",
                    note=" ".join(
                        v for k, v in pending_attrs.items() if k.startswith("tvg-") and k not in ("tvg-name", "tvg-logo")
                    ),
                )
            )
        pending_name, pending_attrs, pending_group = "", {}, ""

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            payload = line.split(":", 1)[1]
            if "," in payload:
                attrs_part, name_part = payload.rsplit(",", 1)
                pending_name = name_part.strip()
            else:
                attrs_part = payload
                pending_name = ""
            pending_attrs = {key: value for key, value in _ATTR.findall(attrs_part)}
            continue
        if line.startswith("#EXTGRP:"):
            pending_group = line.split(":", 1)[1].strip()
            continue
        if line.startswith("#"):
            continue
        flush(line)

    flush("")
    # 去重（名称 + URL）
    seen, unique = set(), []
    for channel in result.channels:
        key = (channel.name, channel.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(channel)
    result.channels = unique
    return result


def export_m3u(path: str, channels: List[Channel]) -> bool:
    lines = ["#EXTM3U"]
    for channel in channels:
        if not channel.enabled:
            continue
        attrs = [f'tvg-name="{channel.name}"', f'group-title="{channel.group}"']
        if channel.logo:
            attrs.append(f'tvg-logo="{channel.logo}"')
        lines.append(f"#EXTINF:-1 {' '.join(attrs)},{channel.name}")
        lines.append(channel.url)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return True
    except OSError:
        return False
