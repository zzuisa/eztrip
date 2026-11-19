"""旅行规划后台任务：生成与 HTTP 连接解耦，断线后可按序号续看或取回结果。

事件以原始 SSE 文本缓存在内存里（容器重启会丢失运行中的任务；已完成的结果
由 TravelPlanStore 持久化，可按 result_id 取回）。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator, Dict, List, Optional
from uuid import uuid4

JOB_TTL_SECONDS = 3600
MAX_JOBS = 60
KEEPALIVE_SECONDS = 12.0


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class Job:
    def __init__(self, owner_ip: str, counted_guest: bool) -> None:
        self.id = uuid4().hex
        self.owner_ip = owner_ip
        self.counted_guest = counted_guest
        self.created = time.time()
        self.finished: Optional[float] = None
        self.events: List[str] = [_sse("job", {"job_id": self.id})]
        self.status = "running"  # running | done | error | cancelled
        self.percent = 0
        self.message = ""
        self.result_id: Optional[str] = None
        self.error: Optional[str] = None
        self.task: Optional[asyncio.Task] = None
        self._cond = asyncio.Condition()

    def snapshot(self) -> dict:
        return {
            "job_id": self.id,
            "status": self.status,
            "percent": self.percent,
            "message": self.message,
            "result_id": self.result_id,
            "error": self.error,
            "events": len(self.events),
        }

    async def _push(self, chunk: str) -> None:
        if chunk.startswith(":"):
            return  # 保活注释不缓存
        async with self._cond:
            self.events.append(chunk)
            self._track(chunk)
            self._cond.notify_all()

    def _track(self, chunk: str) -> None:
        try:
            head, _, body = chunk.partition("\n")
            event = head.removeprefix("event:").strip()
            data = json.loads(body.removeprefix("data:").strip())
        except Exception:
            return
        if event == "progress":
            self.percent = int(data.get("percent") or self.percent)
            self.message = str(data.get("status") or self.message)
        elif event == "done":
            self.status = "done"
            self.percent = 100
            self.result_id = data.get("result_id")
        elif event == "error":
            self.status = "error"
            self.error = str(data.get("message") or "生成失败")

    async def _finish(self, status: Optional[str] = None) -> None:
        async with self._cond:
            if status:
                self.status = status
            elif self.status == "running":
                self.status = "error"
                self.error = self.error or "生成意外中断"
            self.finished = time.time()
            self._cond.notify_all()

    async def follow(self, start: int = 0) -> AsyncIterator[str]:
        """从第 start 个事件开始回放并持续跟随，直到任务结束。"""
        index = max(0, start)
        while True:
            async with self._cond:
                if index >= len(self.events) and self.status == "running":
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=KEEPALIVE_SECONDS)
                    except asyncio.TimeoutError:
                        pass
                batch = self.events[index:]
                running = self.status == "running"
            if batch:
                for chunk in batch:
                    yield chunk
                index += len(batch)
            elif running:
                yield ": keepalive\n\n"
            if not running and index >= len(self.events):
                return


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}

    def _gc(self) -> None:
        now = time.time()
        for job_id, job in list(self._jobs.items()):
            if job.finished and now - job.finished > JOB_TTL_SECONDS:
                self._jobs.pop(job_id, None)
        if len(self._jobs) > MAX_JOBS:
            for job_id, job in sorted(self._jobs.items(), key=lambda kv: kv[1].created):
                if job.finished:
                    self._jobs.pop(job_id, None)
                if len(self._jobs) <= MAX_JOBS:
                    break

    def running_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status == "running")

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def start(self, generator: AsyncIterator[str], owner_ip: str, counted_guest: bool, on_guest_failure=None) -> Job:
        self._gc()
        job = Job(owner_ip, counted_guest)
        self._jobs[job.id] = job

        async def pump() -> None:
            try:
                async for chunk in generator:
                    await job._push(chunk)
                await job._finish()
            except asyncio.CancelledError:
                await job._finish("cancelled")
                raise
            except Exception as exc:  # 生成器已自行捕获业务异常，这里兜底
                job.error = str(exc)
                await job._finish("error")
            finally:
                try:
                    await generator.aclose()  # 触发生成器内的 finally（取消子任务）
                except Exception:
                    pass
                if job.status != "done" and counted_guest and on_guest_failure:
                    on_guest_failure()  # 失败/取消不占用游客额度

        job.task = asyncio.create_task(pump())
        return job

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status != "running" or not job.task:
            return False
        job.task.cancel()
        return True


_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager

