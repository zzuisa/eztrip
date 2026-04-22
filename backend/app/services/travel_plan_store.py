"""旅行规划结果持久化存储（文件型）"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4


class TravelPlanStore:
    """基于本地 JSON 文件的结果存储。"""

    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parents[2] / "storage" / "travel_plans"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, result_id: str) -> Path:
        return self.base_dir / f"{result_id}.json"

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

    def list(self, limit: int = 100) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        files = sorted(self.base_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[: max(limit, 1)]:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                payload = raw.get("payload") or {}
                records.append(
                    {
                        "id": raw.get("id"),
                        "created_at": raw.get("created_at"),
                        "updated_at": raw.get("updated_at"),
                        "location": payload.get("location"),
                        "days": payload.get("days"),
                        "warnings_count": len(payload.get("warnings") or []),
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

