"""对话记忆存储（SQLite）：按 user_key 隔离的会话与消息，支持历史查看、续聊、删除。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

MAX_CONV_PER_USER = 200
MAX_MSG_PER_CONV = 300
GUEST_RETENTION_DAYS = 90

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  user_key TEXT NOT NULL,
  result_id TEXT NOT NULL,
  place_day INTEGER NOT NULL DEFAULT 0,
  place_kind TEXT NOT NULL DEFAULT 'activity',
  place_name TEXT NOT NULL,
  location TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  msg_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_key, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_conv_place ON conversations(user_key, result_id, place_kind, place_name, updated_at DESC);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conv_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  model TEXT,
  ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conv_id, id);
"""


class ChatStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or Path(__file__).resolve().parents[2] / "storage" / "chat_memory.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)
            if "extra" not in {r["name"] for r in c.execute("PRAGMA table_info(messages)").fetchall()}:
                c.execute("ALTER TABLE messages ADD COLUMN extra TEXT")
        self._last_prune = 0.0

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------- 会话 ----------
    def create(self, user_key: str, result_id: str, day: int, kind: str, name: str, location: str = "") -> str:
        cid = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO conversations(id,user_key,result_id,place_day,place_kind,place_name,location,title,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (cid, user_key, result_id, day, kind, name, location, "", now, now),
            )
            self._prune(c, user_key, now)
        return cid

    def get(self, user_key: str, cid: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM conversations WHERE id=? AND user_key=?", (cid, user_key)).fetchone()
        return dict(row) if row else None

    def find_latest(self, user_key: str, result_id: str, kind: str, name: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM conversations WHERE user_key=? AND result_id=? AND place_kind=? AND place_name=? AND msg_count>0"
                " ORDER BY updated_at DESC LIMIT 1",
                (user_key, result_id, kind, name),
            ).fetchone()
        return dict(row) if row else None

    def add_message(self, user_key: str, cid: str, role: str, content: str, model: Optional[str] = None,
                    extra: Optional[Dict[str, Any]] = None) -> None:
        now = time.time()
        with self._lock, self._conn() as c:
            row = c.execute("SELECT msg_count,title FROM conversations WHERE id=? AND user_key=?", (cid, user_key)).fetchone()
            if not row:
                return
            c.execute("INSERT INTO messages(conv_id,role,content,model,ts,extra) VALUES(?,?,?,?,?,?)",
                      (cid, role, content, model, now, json.dumps(extra, ensure_ascii=False) if extra else None))
            title = row["title"] or (content.strip().replace("\n", " ")[:40] if role == "user" else "")
            c.execute(
                "UPDATE conversations SET msg_count=msg_count+1, updated_at=?, title=? WHERE id=?",
                (now, title, cid),
            )
            if row["msg_count"] + 1 > MAX_MSG_PER_CONV:
                c.execute(
                    "DELETE FROM messages WHERE id IN (SELECT id FROM messages WHERE conv_id=? ORDER BY id LIMIT ?)",
                    (cid, row["msg_count"] + 1 - MAX_MSG_PER_CONV),
                )
                c.execute("UPDATE conversations SET msg_count=? WHERE id=?", (MAX_MSG_PER_CONV, cid))

    def drop_last_user(self, user_key: str, cid: str) -> None:
        with self._lock, self._conn() as c:
            if not c.execute("SELECT 1 FROM conversations WHERE id=? AND user_key=?", (cid, user_key)).fetchone():
                return
            row = c.execute("SELECT id,role FROM messages WHERE conv_id=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
            if row and row["role"] == "user":
                c.execute("DELETE FROM messages WHERE id=?", (row["id"],))
                c.execute("UPDATE conversations SET msg_count=MAX(msg_count-1,0) WHERE id=?", (cid,))

    def messages(self, user_key: str, cid: str, limit: int = 200) -> List[Dict[str, Any]]:
        with self._conn() as c:
            own = c.execute("SELECT 1 FROM conversations WHERE id=? AND user_key=?", (cid, user_key)).fetchone()
            if not own:
                return []
            rows = c.execute(
                "SELECT role,content,model,ts,extra FROM (SELECT * FROM messages WHERE conv_id=? ORDER BY id DESC LIMIT ?) ORDER BY id",
                (cid, limit),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["extra"] = json.loads(d["extra"]) if d.get("extra") else None
            except Exception:  # noqa: BLE001
                d["extra"] = None
            out.append(d)
        return out

    def list(self, user_key: str, result_id: Optional[str] = None, kind: Optional[str] = None,
             name: Optional[str] = None, limit: int = 60) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM conversations WHERE user_key=? AND msg_count>0"
        args: List[Any] = [user_key]
        if result_id:
            sql += " AND result_id=?"
            args.append(result_id)
        if kind and name:
            sql += " AND place_kind=? AND place_name=?"
            args += [kind, name]
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(max(1, min(limit, 200)))
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(sql, args).fetchall()]
            for r in rows:
                last = c.execute("SELECT role,content FROM messages WHERE conv_id=? ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
                r["snippet"] = (last["content"].replace("\n", " ")[:80] if last else "")
        return rows

    def delete(self, user_key: str, cid: str) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM conversations WHERE id=? AND user_key=?", (cid, user_key))
            return cur.rowcount > 0

    def clear(self, user_key: str) -> int:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM conversations WHERE user_key=?", (user_key,)).rowcount

    # ---------- 记忆 ----------
    def recent_user_questions(self, user_key: str, result_id: str, exclude_cid: Optional[str], limit: int = 6) -> List[Dict[str, str]]:
        """同一行程里、用户在其它地点问过的问题（跨地点记忆）。"""
        with self._conn() as c:
            rows = c.execute(
                "SELECT m.content AS q, v.place_name AS place FROM messages m JOIN conversations v ON v.id=m.conv_id"
                " WHERE v.user_key=? AND v.result_id=? AND m.role='user' AND v.id != ?"
                " ORDER BY m.id DESC LIMIT ?",
                (user_key, result_id, exclude_cid or "", limit),
            ).fetchall()
        return [{"q": r["q"], "place": r["place"]} for r in rows]

    # ---------- 清理 ----------
    def _prune(self, c: sqlite3.Connection, user_key: str, now: float) -> None:
        c.execute(
            "DELETE FROM conversations WHERE id IN (SELECT id FROM conversations WHERE user_key=? ORDER BY updated_at DESC LIMIT -1 OFFSET ?)",
            (user_key, MAX_CONV_PER_USER),
        )
        if now - self._last_prune > 3600:
            self._last_prune = now
            c.execute(
                "DELETE FROM conversations WHERE user_key LIKE 'g:%' AND updated_at < ?",
                (now - GUEST_RETENTION_DAYS * 86400,),
            )
            c.execute("DELETE FROM conversations WHERE msg_count=0 AND created_at < ?", (now - 86400,))


_store: Optional[ChatStore] = None


def get_chat_store() -> ChatStore:
    global _store
    if _store is None:
        _store = ChatStore()
    return _store

