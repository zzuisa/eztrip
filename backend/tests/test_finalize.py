"""最终化 + 审核闭环的回归测试（纯离线，不调用模型/网络）。
运行：python tests/test_finalize.py   （无需 pytest）

核心断言：审核员看到的永远是 settle 之后的最终行程；交付的行程指纹 == 审核指纹；用户编辑后指纹失配 → 需要重审。
"""
import asyncio
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agents import context as ctx_mod, final_review, refine, reviewer   # noqa: E402
from app.agents.context import PlanningContext                               # noqa: E402
from app.services import finalize                                            # noqa: E402

META = {
    "start_date": "2026-11-13", "transportation": "租车自驾",
    "origin": "Düsseldorf", "origin_lat": 51.242945, "origin_lng": 6.741256,
    "return_point": {"name": "Düsseldorf", "lat": 51.242945, "lng": 6.741256},
    "day_windows": [{"day": 1, "start": "09:00", "end": "18:00"}],
    "rental": {"name": "SIXT", "daily_eur": 55},
}


def act(name, time, lat=51.1997, lng=5.9888):
    return {"name": name, "time": time, "latitude": lat, "longitude": lng, "description": "", "route_desc": "", "estimated_cost": 0}


def meal(name, typ, time, lat=51.1887, lng=5.9803):
    return {"name": name, "type": typ, "time": time, "latitude": lat, "longitude": lng}


def make_plan():
    return {"location": "Roermond", "days": 1, "itinerary": [{
        "day": 1, "title": "t", "route_summary": "r",
        "activities": [act("Outlet", "12:00-18:15"), act("Maasplassen", "18:25-19:55")],
        "meals": [meal("Käfer", "breakfast", "08:00-08:45"), meal("Lunch", "lunch", "14:30-15:30"), meal("Dinner", "dinner", "20:00-21:00")],
    }]}


def test_settle_fits_window_and_return():
    plan = make_plan()
    info = finalize.settle(plan, META)
    day = plan["itinerary"][0]
    names = [a["name"] for a in day["activities"]] + [m["name"] for m in day["meals"]]
    assert "Maasplassen" not in names and "Dinner" not in names, names          # 超出可游览时间的被移除
    bf = next((m for m in day["meals"] if m["name"] == "Käfer"), None)           # 早餐不会早于抵达+缓冲
    assert bf is None or finalize.clock_minutes(bf["time"]) >= finalize.clock_minutes(day["transit_start"]["arrive"]) + 30, bf
    assert "取车" in day["transit_start"]["note"] and day["transit_start"]["minutes"] > 45   # 取车手续计入
    assert finalize.clock_minutes(day["transit_end"]["arrive"]) <= finalize.RETURN_LATEST
    assert info["checks"] == [], info["checks"]
    assert info["notes"], "自动调整应当留下说明"


def test_window_is_departure_to_return():
    meta = {**META, "destination_hint": "Roermond", "day_windows": [{"day": 1, "start": "11:00", "end": "19:00"}]}
    plan = {"location": "Roermond", "days": 1, "itinerary": [{
        "day": 1, "title": "t", "route_summary": "r",
        "activities": [act("Outlet", "11:35-16:00"), act("Maasplassen", "16:10-17:30")],
        "meals": [meal("Lunch", "lunch", "13:40-14:30")],
    }]}
    info = finalize.settle(plan, meta)
    day = plan["itinerary"][0]
    ts, te = day["transit_start"], day["transit_end"]
    dep, arr = finalize.clock_minutes(ts["depart"]), finalize.clock_minutes(ts["arrive"])
    assert dep >= 11 * 60, ts
    first = min(finalize.clock_minutes(x["time"]) for x in day["activities"] + day["meals"])
    assert first - arr <= 30 + 5, (ts, first)                       # 到达后不空等
    assert finalize.clock_minutes(te["arrive"]) <= 19 * 60, te       # 回到出发地(含还车)不晚于窗口结束
    assert info["checks"] == [], info["checks"]
    again = finalize.settle(plan, meta)
    assert again["notes"] == [] and again["fingerprint"] == info["fingerprint"]


def test_weather_zero_probability_no_umbrella():
    from app.services import weather
    row = {"weather_code": 51, "precipitation_probability": 0, "precipitation_mm": 0.3, "temp_min": 5, "temp_max": 10,
           "wind_kmh": 10, "gust_kmh": 20, "uv_index": 1}
    a = weather.advice(row)
    assert not any("降雨" in x for x in a["advice"]) and a["risk"] == "low", a
    assert row["weather_code"] == 3
    wet = {"weather_code": 61, "precipitation_probability": 70, "precipitation_mm": 4, "temp_min": 5, "temp_max": 10, "wind_kmh": 10, "gust_kmh": 20}
    assert any("降雨" in x for x in weather.advice(wet)["advice"]) and wet["weather_code"] == 61


def test_settle_is_idempotent():
    plan = make_plan()
    first = finalize.settle(plan, META)
    again = finalize.settle(plan, META)
    assert again["notes"] == [] and again["fingerprint"] == first["fingerprint"]


def test_fingerprint_detects_changes_but_not_cosmetics():
    plan = make_plan()
    finalize.settle(plan, META)
    fp = finalize.fingerprint(plan)
    plan["itinerary"][0]["activities"][0]["image_url"] = "http://x/y.jpg"     # 图片不影响
    plan["total_budget"] = {"total": 1}
    assert finalize.fingerprint(plan) == fp
    plan["itinerary"][0]["activities"][0]["time"] = "12:30-17:30"             # 时间变了就必须重审
    assert finalize.fingerprint(plan) != fp


def test_needs_review_after_edit():
    plan = make_plan()
    finalize.settle(plan, META)
    plan["review"] = {"status": "ok", "fingerprint": finalize.fingerprint(plan)}
    assert not final_review.needs_review(plan)
    plan["itinerary"][0]["activities"][0]["name"] = "Another"
    assert final_review.needs_review(plan)


def test_user_edit_is_not_rewritten():
    plan = make_plan()
    plan["itinerary"][0]["activities"].append(act("Late", "21:00-22:00"))
    before = [a["name"] for a in plan["itinerary"][0]["activities"]]
    finalize.settle(plan, META, fit=False)                                     # 用户编辑：只重建交通、不改行程
    assert [a["name"] for a in plan["itinerary"][0]["activities"]] == before
    assert plan["itinerary"][0]["transit_start"]


class FakeCtx(PlanningContext):
    pass


def run_loop(scores):
    """用桩审核员跑 refine_plan，记录每次审核时看到的行程是否已 settle。"""
    seen = []
    calls = {"n": 0}

    async def fake_review(**kw):
        it = kw["itinerary"]
        view = {"itinerary": it}
        seen.append({
            "has_transit": bool(it[0].get("transit_start")),
            "fingerprint": finalize.fingerprint(view),
            "names": [a["name"] for a in it[0]["activities"]],
            "meta": kw.get("meta"),
        })
        score = scores[min(calls["n"], len(scores) - 1)]
        calls["n"] += 1
        issues = [] if score >= 85 else [{"day": 1, "severity": "high", "type": "timing", "message": "问题", "fix": "改"}]
        return {"status": "ok", "model": "m", "score": score, "summary": "s", "verdict": "revise" if issues else "pass",
                "issues": issues, "revised_days": []}

    async def fake_recompose(ctx, day, feedback, avoid=(), sem=None):
        fake_recompose.feedback.append(feedback)
        d = copy.deepcopy(make_plan()["itinerary"][0])
        d["activities"] = [act("Outlet", "10:00-15:00"), act("Park", "15:30-17:00")]
        d["meals"] = [meal("Lunch", "lunch", "12:30-13:30")]
        return d
    fake_recompose.feedback = []

    reviewer.review_itinerary = fake_review
    refine.recompose_day = fake_recompose
    refine.get_llm_router = lambda: None
    refine.get_model = lambda *_: "m"
    ctx = PlanningContext(location="Roermond", days=1, preferences="", origin="Düsseldorf", emit=None,
                          start_date="2026-11-13", transportation="租车自驾")
    ctx.trip_meta = META
    ctx.assigned = {1: [act("Outlet", "10:00-15:00")]}
    ctx_mod.set_context(ctx)
    plan = make_plan()
    plan["attractions"] = []
    it = plan["itinerary"]
    out_it, geo, review = asyncio.run(refine.refine_plan(ctx, plan, it, [], None, "Roermond", 1, "", "Düsseldorf"))
    return seen, out_it, review, plan, fake_recompose.feedback


def test_review_always_sees_final_data_and_delivery_matches():
    seen, out_it, review, plan, feedback = run_loop([40, 90])
    assert len(seen) == 2, "重排后必须复审"
    assert all(s["has_transit"] for s in seen), "审核员必须看到 settle 之后的交通"
    assert all(s["meta"] is not None for s in seen)
    assert "Maasplassen" not in seen[0]["names"], "第一次审核前已经排除了放不下的活动"
    assert any("硬约束" in f for f in feedback), "重排要带上当天硬约束"
    assert review["fingerprint"] == finalize.fingerprint(plan), "交付 = 被审核过的那一份"
    assert review["score"] == 90


def test_worse_revision_reverts_to_reviewed_best():
    seen, out_it, review, plan, _ = run_loop([60, 30])
    assert review["score"] == 60
    assert review["fingerprint"] == finalize.fingerprint(plan)


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:                       # noqa: BLE001
                import traceback
                traceback.print_exc()
                print("FAIL", name, repr(e))
                fails += 1
    sys.exit(1 if fails else 0)

