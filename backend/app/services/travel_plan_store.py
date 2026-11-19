"""旅行规划结果持久化存储（文件型）"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID, uuid4


class TravelPlanStore:
    """基于本地 JSON 文件的结果存储。"""

    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parents[2] / "storage" / "travel_plans"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, result_id: str) -> Path:
        # 仅接受 UUID，杜绝路径拼接
        try:
            safe = str(UUID(str(result_id)))
        except ValueError:
            safe = "invalid-id"
        return self.base_dir / f"{safe}.json"

    def save(self, payload: Dict[str, Any]) -> str:
        result_id = str(uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        record = {
            "id": result_id,
            "created_at": now_iso,
            "updated_at": now_iso,
            "payload": payload,
        }
        self._file_path(result_id).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return result_id

    def get(self, result_id: str) -> Dict[str, Any] | None:
        path = self._file_path(result_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    _write_lock = threading.Lock()

    def update_payload(self, result_id: str, mutator) -> bool:
        """在锁内读-改-写 payload（mutator(payload) 原地修改，返回 False 则不写回）。"""
        with self._write_lock:
            record = self.get(result_id)
            if not record:
                return False
            payload = record.get("payload") or {}
            if mutator(payload) is False:
                return False
            record["payload"] = payload
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._file_path(result_id).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            return True

    def update_record(self, result_id: str, mutator) -> bool:
        """在锁内读-改-写整条记录（含 payload 之外的 editor / rev / history 等字段）。mutator 返回 False 则不写回。"""
        with self._write_lock:
            record = self.get(result_id)
            if not record:
                return False
            if mutator(record) is False:
                return False
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            tmp = self._file_path(result_id).with_suffix(".tmp")
            tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._file_path(result_id))
            return True

    def merge_payload(self, result_id: str, extra: Dict[str, Any]) -> bool:
        """向已保存结果的 payload 合并额外字段（如 trip_meta）。"""
        record = self.get(result_id)
        if not record:
            return False
        payload = record.get("payload") or {}
        payload.update(extra)
        record["payload"] = payload
        self._file_path(result_id).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return True

    def list(self, limit: int = 100, editor: str | None = None) -> List[Dict[str, Any]]:
        """editor=None 返回全部（站长）；否则只返回该生成者（匿名 uid）名下的行程。"""
        records: List[Dict[str, Any]] = []
        files = sorted(self.base_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files:
            if len(records) >= max(limit, 1):
                break
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if editor is not None and raw.get("editor") != editor:
                    continue
                payload = raw.get("payload") or {}
                records.append(
                    {
                        "id": raw.get("id"),
                        "created_at": raw.get("created_at"),
                        "updated_at": raw.get("updated_at"),
                        "location": payload.get("location"),
                        "days": payload.get("days"),
                        "warnings_count": len(payload.get("warnings") or []),
                        "cities": [s.get("city") for s in (payload.get("segments") or []) if isinstance(s, dict) and s.get("city")],
                        "mine": bool(raw.get("editor")),
                        "highlights": [
                            str(a.get("name"))
                            for a in (payload.get("attractions") or [])[:3]
                            if isinstance(a, dict) and a.get("name")
                        ],
                    }
                )
            except Exception:
                continue
        return records

    def delete(self, result_id: str) -> bool:
        path = self._file_path(result_id)
        if not path.exists():
            return False
        path.unlink()
        return True


_travel_plan_store: TravelPlanStore | None = None


def get_travel_plan_store() -> TravelPlanStore:
    global _travel_plan_store
    if _travel_plan_store is None:
        _travel_plan_store = TravelPlanStore()
    return _travel_plan_store

