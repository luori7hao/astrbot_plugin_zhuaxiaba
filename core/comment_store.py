from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CommentedThreadStore:
    def __init__(self, file_path: str | None = None):
        if file_path:
            self.path = Path(file_path)
        else:
            self.path = Path(__file__).resolve().parent.parent / "data" / "commented_threads.json"

    def _ensure_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"读取评论标记文件失败：{exc}") from exc
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"评论标记文件不是合法 JSON：{self.path}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"评论标记文件格式错误：{self.path}")
        normalized: dict[str, dict[str, Any]] = {}
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            normalized[str(key)] = value
        return normalized

    def is_marked(self, thread_id: Any) -> bool:
        data = self.load()
        return str(thread_id) in data

    def mark(self, thread_id: Any, title: str = "") -> None:
        data = self.load()
        data[str(thread_id)] = {
            "commented_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "title": str(title or "").strip(),
        }
        self._save(data)

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self._ensure_parent()
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp_path.write_text(payload, encoding="utf-8")
            os.replace(tmp_path, self.path)
        except OSError as exc:
            raise RuntimeError(f"写入评论标记文件失败：{exc}") from exc
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
