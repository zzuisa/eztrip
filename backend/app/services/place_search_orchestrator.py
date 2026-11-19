"""Google Places 检索并发编排。

把同步、阻塞的检索调用移出事件循环（``asyncio.to_thread``），并以有界并发
（``asyncio.Semaphore``）批量执行；同一批内相同 key 的调用只发一次（请求内去重）。
单个调用异常被隔离为空结果，不影响整批。

不重写 ``GooglePlacesService``：仅编排其现有同步方法（含磁盘缓存/归一化/日志）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List

DEFAULT_CONCURRENCY = 6

Thunk = Callable[[], List[Dict[str, Any]]]


async def gather_calls(
    calls: Dict[str, Thunk],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> Dict[str, List[Dict[str, Any]]]:
    """并发执行 ``{key: thunk}``，返回 ``{key: result}``。

    - key 天然去重：dict 相同 key 只保留一个 thunk，故同一批内相同查询只发一次。
    - 每个 thunk 经 ``asyncio.to_thread`` 在线程池执行，避免阻塞事件循环。
    - ``concurrency`` 通过信号量限制同时在途的外部请求数（防 429）。
    - 单个 thunk 抛异常时返回 ``[]``，不影响其余调用。
    """
    if not calls:
        return {}
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _run_one(thunk: Thunk) -> List[Dict[str, Any]]:
        async with sem:
            try:
                result = await asyncio.to_thread(thunk)
            except Exception:
                return []
        return result if isinstance(result, list) else []

    keys = list(calls.keys())
    results = await asyncio.gather(*(_run_one(calls[k]) for k in keys))
    return dict(zip(keys, results))


def text_key(query: str, limit: int) -> str:
    """文本检索的去重 key。"""
    return f"text::{str(query).strip().lower()}::{int(limit)}"


def near_key(query: str, anchor_lat: float, anchor_lng: float, limit: int, radius_meters: int) -> str:
    """就近检索的去重 key（含锚点/半径/limit，避免误合并）。"""
    return (
        f"near::{str(query).strip().lower()}::{round(float(anchor_lat), 4)}::"
        f"{round(float(anchor_lng), 4)}::{int(limit)}::{int(radius_meters)}"
    )


async def search_texts(
    service: Any,
    queries: List[str],
    *,
    limit: int,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> Dict[str, List[Dict[str, Any]]]:
    """并发执行一批文本检索，返回 ``{原始query: items}``（跳过空 query）。"""
    calls: Dict[str, Thunk] = {}
    key_to_query: Dict[str, str] = {}
    for raw in queries:
        q = str(raw).strip()
        if not q:
            continue
        key = text_key(q, limit)
        key_to_query.setdefault(key, q)
        if key not in calls:
            calls[key] = (lambda q=q: service.search_places(q, limit=limit))
    raw_results = await gather_calls(calls, concurrency=concurrency)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for key, items in raw_results.items():
        out[key_to_query[key]] = items
    return out
