"""交通查询API路由"""

import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from ...models.schemas import (
    DbNlqRequest,
    DbNlqResponse,
    DbTripQueryRequest,
)
from ...services.guest_guard import client_ip, get_quota, guest_quota_dependency, is_owner
from ...services.deutsche_bahn_service import get_deutsche_bahn_service
from ...tools.db.nlq_parser import now_berlin, parse_plan
from ...tools.db.searcher import DbUnavailable, OutOfWindow, StationNotFound
from ...tools.db.debug import db_log, DbTimer

router = APIRouter(prefix="/transport", tags=["交通服务"])

POLICY_VERSION = "2.0.0"


def _run_nlq(req: DbNlqRequest, request_id: str) -> DbNlqResponse:
    plan = parse_plan(req.query, request_id=request_id)
    db_log(request_id, "nlq_parsed_obj", plan.__dict__)
    miss = [n for n, v in (("出发地", plan.origin), ("目的地", plan.destination)) if not v.strip()]
    if miss:
        return DbNlqResponse(
            success=False,
            code="clarify",
            message=f"请补充{'、'.join(miss)}，例如：'明天 9 点 Frankfurt Hbf 到 Berlin Hbf' 或 '现在 杜塞到杜堡'",
            data=[],
            policy_version=POLICY_VERSION,
        )

    now = now_berlin()
    if plan.time_mode == "scheduled" and plan.date and plan.hour:
        start = datetime.strptime(f"{plan.date}{plan.hour}{plan.minute or '00'}", "%y%m%d%H%M")
    else:
        start = now
    regional = req.regional_only if req.regional_only is not None else (plan.regional_only if plan.regional_only is not None else True)

    service = get_deutsche_bahn_service()
    try:
        res = service.search_trips(
            origin=plan.origin, destination=plan.destination, start=start, limit=plan.limit, regional_only=regional,
            auto_widen=(req.regional_only is None and plan.regional_only is None),
        )
    except StationNotFound as e:
        return DbNlqResponse(success=False, code="no_station", message=f"{e}。请换个写法，例如带上 Hbf 或使用德文站名。", data=[], policy_version=POLICY_VERSION)
    except OutOfWindow as e:
        return DbNlqResponse(success=False, code="out_of_window", message=f"{e}。请改查近期车次，更远的日期请到 DB Navigator 确认。", data=[], policy_version=POLICY_VERSION)

    parsed = DbTripQueryRequest(
        origin=res.origin.name if res.origin else plan.origin,
        destination=res.destination.name if res.destination else plan.destination,
        date=start.strftime("%y%m%d"),
        hour=start.strftime("%H"),
        minute=start.strftime("%M"),
        time_mode=plan.time_mode or "now",
        language="de",
    )
    stations = None
    if res.origin and res.destination:
        stations = {
            "origin": {"name": res.origin.name, "eva": res.origin.evas[0]},
            "destination": {"name": res.destination.name, "eva": res.destination.evas[0]},
        }
    return DbNlqResponse(
        success=True,
        code="ok",
        message="查询成功" if res.trips else "没有找到车次",
        parsed=parsed,
        data=res.trips,
        policy_version=POLICY_VERSION,
        notes=res.notes,
        filtered_out=res.filtered_out,
        regional_only=res.regional_only,
        stations=stations,
    )


@router.post(
    "/db/nlq",
    dependencies=[Depends(guest_quota_dependency("nlq"))],
    response_model=DbNlqResponse,
    summary="自然语言查询德铁车次",
    response_description="返回解析结果与车次列表，或返回澄清信息",
    description=(
        "用户以自然语言提问，服务端使用 LLM 抽取结构化参数后调用德铁能力查询车次。\n\n"
        "示例：`帮我查 2026-04-02 14点 Frankfurt Hbf 到 Berlin Hbf 的车次`"
    ),
    responses={
        200: {
            "description": "查询成功或需要澄清",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "查询成功",
                            "value": {
                                "success": True,
                                "message": "查询成功",
                                "parsed": {
                                    "origin": "Frankfurt Hbf",
                                    "destination": "Berlin Hbf",
                                    "date": "260402",
                                    "hour": "14",
                                    "language": "de",
                                },
                                "data": [
                                    {
                                        "train_name": "ICE 123",
                                        "origin": "Frankfurt Hbf",
                                        "destination": "Berlin Hbf",
                                        "departure_time": "14:08",
                                        "arrival_time": "18:02",
                                        "platform": "7",
                                        "status": "on time",
                                    }
                                ],
                                "policy_version": "v1",
                            },
                        },
                        "clarification": {
                            "summary": "信息不足需澄清",
                            "value": {
                                "success": False,
                                "message": "请补充出发地和目的地",
                                "parsed": None,
                                "data": [],
                                "policy_version": "v1",
                            },
                        },
                    }
                }
            },
        },
        500: {"description": "自然语言查询失败"},
    },
)
async def nlq_db_trips(req: DbNlqRequest, request: Request):
    request_id = uuid.uuid4().hex[:8]
    db_log(request_id, "nlq_request", {"query": req.query})
    owner = is_owner(request)
    ip = client_ip(request)

    def refund():
        if not owner:
            get_quota().refund("nlq", ip)

    try:
        out = await asyncio.to_thread(_run_nlq, req, request_id)
        if not out.success:
            refund()  # 没有真正查询的澄清/无站点不扣游客额度
        return out
    except DbUnavailable as e:
        refund()
        db_log(request_id, "nlq_error", str(e))
        raise HTTPException(status_code=503, detail=f"德铁数据源暂时不可用，请稍后再试（{e}）")
    except Exception as e:
        refund()
        db_log(request_id, "nlq_error", str(e))
        print(f"[db-nlq] error {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"自然语言查询失败: {type(e).__name__}")


@router.get(
    "/health",
    summary="交通服务健康检查",
    description="检查交通服务是否可用",
)
async def transport_health():
    try:
        _ = get_deutsche_bahn_service()
        return {"status": "healthy", "service": "transport-service"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"服务不可用: {str(e)}")


