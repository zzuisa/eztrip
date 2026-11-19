"""出口守卫测试：旧流水线 / 多城市合并的结果在 done 之前也要 settle，并且必须在最终数据之后审核。离线运行：python tests/test_attach.py"""
import asyncio
import json
import os
import sys
import tempfile

os.environ.setdefault("EZTRIP_TEST", "1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agents import final_review                                   # noqa: E402
from app.api.routes import travel_plan as tpr                         # noqa: E402
from app.models.schemas import TravelPlanRequest                      # noqa: E402
from app.services import finalize, travel_plan_store                  # noqa: E402
from tests.test_finalize import make_plan                             # noqa: E402


def sse(event, data):
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False))


async def run():
    tmp = tempfile.mkdtemp()
    from pathlib import Path
    store = travel_plan_store.TravelPlanStore.__new__(travel_plan_store.TravelPlanStore)
    store.base_dir = Path(tmp)
    import threading
    store._write_lock = threading.Lock()
    travel_plan_store._travel_plan_store = store
    plan = make_plan()
    plan.update({"attractions": [], "total_budget": {"transport": 0, "tickets": 0, "food": 0, "total": 0, "currency": "EUR"}, "tips": [], "warnings": []})
    rid = store.save(plan)

    seen = {}

    async def fake_review(payload, meta, source="final"):
        seen["fingerprint"] = finalize.fingerprint(payload)
        seen["has_transit"] = bool(payload["itinerary"][0].get("transit_start"))
        seen["names"] = [a["name"] for a in payload["itinerary"][0]["activities"]]
        return {"status": "ok", "model": "m", "score": 80, "summary": "s", "verdict": "pass", "issues": [],
                "revised_days": [], "fingerprint": seen["fingerprint"], "source": source}

    final_review.review_payload = fake_review

    async def gen():
        yield sse("done", {"success": True, "data": {**plan, "result_id": rid}, "result_id": rid})

    req = TravelPlanRequest(location="Roermond", days=1, start_date="2026-11-13", transportation="租车自驾",
                            origin="Düsseldorf", origin_lat=51.242945, origin_lng=6.741256,
                            day_windows=[{"day": 1, "start": "09:00", "end": "18:00"}])
    out = []
    async for chunk in tpr._attach_trip_meta(gen(), req, ""):
        out.append(chunk)
    done = [c for c in out if c.startswith("event: done")][-1]
    body = json.loads(done.partition("data:")[2])
    data = body["data"]
    assert seen["has_transit"], "审核必须发生在 settle 之后"
    assert "Maasplassen" not in seen["names"], seen
    assert data["settled"] and data["review"]["fingerprint"] == finalize.fingerprint(data), "交付 = 被审核过的"
    assert not any("review" in w for w in data["warnings"])
    saved = store.get(rid)["payload"]
    assert saved["review"]["fingerprint"] == finalize.fingerprint(saved), "落库的也一致"
    print("PASS attach guard", data["tips"][:1])


asyncio.run(run())

