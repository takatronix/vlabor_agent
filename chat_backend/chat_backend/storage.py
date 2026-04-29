"""Conversation persistence — JSON-on-disk, one file per chat.

Layout::

    ~/.vlabor/agent/conversations/
        <conversation_id>.json   # full transcript + metadata

Each file looks like::

    {
      "id": "01h2…",
      "title": "first 60 chars of the first user message",
      "created_at": "2026-04-28T12:34:56Z",
      "updated_at": "2026-04-28T12:38:11Z",
      "messages": [{"role": "user", "content": [...]}, ...]
    }

Phase 0 picks files on purpose: zero infra setup, the operator can
``cat`` / ``grep`` / back up the directory with normal tools. We'll
move to SQLite if the listing endpoint starts feeling slow at >1k
conversations or replay / search demands more structure (see the
top-level design doc).
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _default_dir() -> Path:
    return Path(os.path.expanduser("~/.vlabor/agent/conversations"))


def _safe_id(value: str | None) -> str:
    """Reject ``..``/slashes so a malicious WS payload can't write
    outside the conversations dir."""
    if not value or not isinstance(value, str):
        return ""
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value):
        return ""
    return value


@dataclass
class ConversationSummary:
    id: str
    title: str
    updated_at: str
    message_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "updated_at": self.updated_at,
            "message_count": self.message_count,
        }


class ConversationStore:
    """Owns the on-disk conversations dir."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _default_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    # --- read --------------------------------------------------------

    def list(self) -> list[ConversationSummary]:
        rows: list[ConversationSummary] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            rows.append(
                ConversationSummary(
                    id=str(data.get("id") or path.stem),
                    title=str(data.get("title") or "(untitled)"),
                    updated_at=str(data.get("updated_at") or ""),
                    message_count=len(data.get("messages") or []),
                )
            )
        # Newest first.
        rows.sort(key=lambda r: r.updated_at, reverse=True)
        return rows

    def load(self, conversation_id: str) -> dict[str, Any] | None:
        cid = _safe_id(conversation_id)
        if not cid:
            return None
        path = self.root / f"{cid}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    # --- write -------------------------------------------------------

    def create(self) -> str:
        # uuid4 hex — same shape as the worker session ids elsewhere.
        cid = uuid.uuid4().hex
        path = self.root / f"{cid}.json"
        now = _now_iso()
        payload = {
            "id": cid,
            "title": "(new chat)",
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return cid

    def save(self, conversation_id: str, messages: list[dict[str, Any]]) -> bool:
        cid = _safe_id(conversation_id)
        if not cid:
            return False
        path = self.root / f"{cid}.json"
        existing = self.load(cid) or {
            "id": cid,
            "title": "(new chat)",
            "created_at": _now_iso(),
        }
        existing["messages"] = messages
        existing["updated_at"] = _now_iso()
        # Auto-title from the first user text turn if we don't have one yet.
        if existing.get("title") in (None, "", "(new chat)", "(untitled)"):
            existing["title"] = _derive_title(messages)
        try:
            path.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except OSError:
            return False

    def set_meta(self, conversation_id: str, **fields: Any) -> bool:
        """Merge top-level fields into the conversation file. Used for
        marking auto-generated diagnostic sessions (``origin="auto"``)
        and stamping the trigger payload (``trigger_components``)."""
        cid = _safe_id(conversation_id)
        if not cid:
            return False
        existing = self.load(cid)
        if existing is None:
            return False
        existing.update({k: v for k, v in fields.items() if v is not None})
        existing["updated_at"] = _now_iso()
        try:
            (self.root / f"{cid}.json").write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except OSError:
            return False

    def delete(self, conversation_id: str) -> bool:
        cid = _safe_id(conversation_id)
        if not cid:
            return False
        path = self.root / f"{cid}.json"
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return False


def _derive_title(messages: list[dict[str, Any]]) -> str:
    """First user message, first 60 chars. Anthropic content blocks
    are a list of ``{type, text}`` so we walk them carefully."""
    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    t = block.get("text")
                    if isinstance(t, str):
                        parts.append(t)
            text = " ".join(parts)
        else:
            continue
        text = text.strip()
        if text:
            return text[:60] + ("…" if len(text) > 60 else "")
    return "(untitled)"


__all__ = ["ConversationStore", "ConversationSummary"]
