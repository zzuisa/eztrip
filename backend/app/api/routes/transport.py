"""交通查询API路由"""

import uuid

from fastapi import APIRouter, HTTPException

from ...models.schemas import (
    DbNlqRequest,
    DbNlqResponse,
)
from ...services.deutsche_bahn_service import get_deutsche_bahn_service
from ...agents.db_nlq import parse_nlq_to_trip_query_with_time_filter
from ...tools.db.debug import db_log, DbTimer

router = APIRouter(prefix="/transport", tags=["交通服务"])


@router.post(
    "/db/nlq",
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
async def nlq_db_trips(req: DbNlqRequest):
    request_id = uuid.uuid4().hex[:8]
    timer = DbTimer(request_id)
    db_log(request_id, "nlq_request", {"query": req.query})
    try:
        parsed, min_departure_time, timetable_tool_override, limit, month_ticket_only, clarification, policy_version = (
            parse_nlq_to_trip_query_with_time_filter(req.query)
        )
        if clarification:
            return DbNlqResponse(
                success=False,
                message=clarification,
                parsed=None,
                data=[],
                policy_version=policy_version,
            )
        timer.mark("nlq_parsed")
        db_log(request_id, "nlq_parsed_obj", parsed.model_dump())
        service = get_deutsche_bahn_service()
        trips = service.query_trips(
            origin=parsed.origin,
            destination=parsed.destination,
            date=parsed.date,
            hour=parsed.hour,
            language=parsed.language,
            min_departure_time=min_departure_time,
            timetable_tool_override=timetable_tool_override,
            limit=limit,
            month_ticket_only=month_ticket_only,
        )
        timer.mark("nlq_trips_done")
        db_log(request_id, "nlq_trips_count", {"count": len(trips)})
        return DbNlqResponse(success=True, message="查询成功", parsed=parsed, data=trips, policy_version=policy_version)
    except Exception as e:
        db_log(request_id, "nlq_error", str(e))
        raise HTTPException(status_code=500, detail=f"自然语言查询失败: {str(e)}")


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

