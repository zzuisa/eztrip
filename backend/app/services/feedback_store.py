"""用户反馈存储（SQLite）：对整份行程或某个地点点赞 / 点踩 + 原因标签 + 备注。

按 user_key 隔离（站长 "owner"，游客 "g:<ez_uid>"）；同一人对同一对象只保留最新一条（再点一次同样的评价 = 取消）。
目的：把主观感受和 trip_quality 的客观问题放在一起看，找到规划逻辑里最该修的地方。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

TAGS = ("route", "timing", "place", "closed", "info", "image", "other")
MAX_PER_USER = 500
GUEST_RETENTION_DAYS = 180

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_key TEXT NOT NULL,
  result_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  day INTEGER NOT NULL DEFAULT 0,
  place TEXT NOT NULL DEFAULT '',
  rating INTEGER NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  note TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(user_key, result_id, scope, day, place)
);
CREATE INDEX IF NOT EXISTS idx_fb_result ON feedback(result_id);
CREATE INDEX IF NOT EXISTS idx_fb_time ON feedback(updated_at DESC);
"""


def clean_tags(tags: Any) -> List[str]:
    return [t for t in dict.fromkeys(str(x) for x in (tags or [])) if t in TAGS][:len(TAGS)]


class FeedbackStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or Path(__file__).resolve().parents[2] / "storage" / "feedback.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def set(self, user_key: str, result_id: str, scope: str, day: int, place: str, rating: int,
            tags: Any = None, note: str = "") -> Optional[Dict[str, Any]]:
        """rating = 0 → 取消；返回保存后的记录（取消返回 None）。"""
        place = (place or "").strip()[:120]
        day = max(0, int(day or 0))
        now = time.time()
        with self._lock, self._conn() as c:
            if rating == 0:
                c.execute("DELETE FROM feedback WHERE user_key=? AND result_id=? AND scope=? AND day=? AND place=?",
                          (user_key, result_id, scope, day, place))
                return None
            tag_list = clean_tags(tags) if rating < 0 else []        # 原因标签只在“不满意”时有意义
            c.execute(
                "INSERT INTO feedback(user_key,result_id,scope,day,place,rating,tags,note,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(user_key,result_id,scope,day,place) DO UPDATE SET rating=excluded.rating,tags=excluded.tags,note=excluded.note,updated_at=excluded.updated_at",
                (user_key, result_id, scope, day, place, rating, json.dumps(tag_list), (note or "").strip()[:500], now, now))
            self._prune(c, user_key, now)
            row = c.execute("SELECT * FROM feedback WHERE user_key=? AND result_id=? AND scope=? AND day=? AND place=?",
                            (user_key, result_id, scope, day, place)).fetchone()
            return self._row(row)

    def mine(self, user_key: str, result_id: str) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM feedback WHERE user_key=? AND result_id=? ORDER BY updated_at DESC", (user_key, result_id)).fetchall()
        return [self._row(r) for r in rows]

    def delete_result(self, result_id: str) -> int:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM feedback WHERE result_id=?", (result_id,)).rowcount

    def all_rows(self, limit: int = 2000) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM feedback ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r, with_user=True) for r in rows]

    def _prune(self, c: sqlite3.Connection, user_key: str, now: float) -> None:
        c.execute("DELETE FROM feedback WHERE id IN (SELECT id FROM feedback WHERE user_key=? ORDER BY updated_at DESC LIMIT -1 OFFSET ?)", (user_key, MAX_PER_USER))
        c.execute("DELETE FROM feedback WHERE user_key LIKE 'g:%' AND updated_at < ?", (now - GUEST_RETENTION_DAYS * 86400,))

    @staticmethod
    def _row(r: sqlite3.Row, with_user: bool = False) -> Dict[str, Any]:
        out = {"id": r["id"], "result_id": r["result_id"], "scope": r["scope"], "day": r["day"], "place": r["place"],
               "rating": r["rating"], "tags": json.loads(r["tags"] or "[]"), "note": r["note"], "updated_at": r["updated_at"]}
        if with_user:
            out["user"] = "owner" if r["user_key"] == "owner" else "guest"
        return out


_store: Optional[FeedbackStore] = None


def get_feedback_store() -> FeedbackStore:
    global _store
    if _store is None:
        _store = FeedbackStore()
    return _store

