"""频道与录制任务的 JSON 持久化（临时文件 + 原子替换）。"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from typing import List

from .logger import log_error
from .models import Channel, RecordTask
from .settings import app_root


class JsonStore:
    def __init__(self, filename: str) -> None:
        self.path = os.path.join(app_root(), filename)

    def load(self) -> list:
        if not os.path.isfile(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except Exception as exc:
            log_error(f"读取 {self.path} 失败：{exc}")
            return []

    def save(self, items: list) -> bool:
        try:
            directory = os.path.dirname(self.path) or "."
            os.makedirs(directory, exist_ok=True)
            fd, temp = tempfile.mkstemp(prefix=".cxp_", dir=directory)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(items, fh, ensure_ascii=False, indent=2)
            os.replace(temp, self.path)
            return True
        except Exception as exc:
            log_error(f"写入 {self.path} 失败：{exc}")
            return False


class ChannelStore(JsonStore):
    def __init__(self) -> None:
        super().__init__("channels.json")

    def load_channels(self) -> List[Channel]:
        return [Channel.from_dict(item) for item in self.load() if isinstance(item, dict)]

    def save_channels(self, channels: List[Channel]) -> bool:
        return self.save([item.to_dict() for item in channels])


class RecordStore(JsonStore):
    def __init__(self) -> None:
        super().__init__("recordings.json")

    def load_tasks(self) -> List[RecordTask]:
        return [RecordTask.from_dict(item) for item in self.load() if isinstance(item, dict)]

    def save_tasks(self, tasks: List[RecordTask]) -> bool:
        return self.save([item.to_dict() for item in tasks])


def new_task_id() -> str:
    return uuid.uuid4().hex[:12]
