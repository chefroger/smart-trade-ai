"""背调后台任务 API（工单 P1-1）。

  POST /osint/jobs            立即返回 job_id（10 分钟内同目标复用）
  GET  /osint/jobs/{id}       状态 + 已有结构化结果
  GET  /osint/jobs/{id}/events SSE（支持 Last-Event-ID / ?after=seq，15s 心跳）
  POST /osint/jobs/{id}/cancel
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from trade import osint_jobs
from trade.api.deps import require_company

router = APIRouter(tags=["osint-jobs"])


class JobCreateRequest(BaseModel):
    target: str


class SourceRetryRequest(BaseModel):
    source: str


@router.post("/osint/jobs")
async def create_osint_job(
    payload: JobCreateRequest,
    cid: int = Depends(require_company),
):
    target = (payload.target or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="target is required")
    try:
        job, created = await asyncio.to_thread(osint_jobs.create_job, cid, target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if created:
        osint_jobs.start_job(job["id"], target)
    return {
        "job_id": job["id"],
        "status": job["status"],
        "reused": not created,
        "created_at": job.get("created_at"),
    }


@router.get("/osint/jobs")
async def list_osint_jobs(cid: int = Depends(require_company), limit: int = 20):
    return {"jobs": await asyncio.to_thread(osint_jobs.list_jobs, cid, limit)}


@router.get("/osint/jobs/{job_id}")
async def get_osint_job(job_id: int, cid: int = Depends(require_company)):
    job = await asyncio.to_thread(osint_jobs.get_job, cid, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post("/osint/jobs/{job_id}/cancel")
async def cancel_osint_job(job_id: int, cid: int = Depends(require_company)):
    job = await asyncio.to_thread(osint_jobs.cancel_job, cid, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"job_id": job_id, "status": job["status"]}


@router.post("/osint/jobs/{job_id}/retry-source")
async def retry_osint_job_source(
    job_id: int,
    payload: SourceRetryRequest,
    cid: int = Depends(require_company),
):
    """单独重试某个可重试的数据源/层（P2-4）。"""
    src = (payload.source or "").strip()
    if not src:
        raise HTTPException(status_code=400, detail="source is required")
    try:
        res = await asyncio.to_thread(osint_jobs.retry_job_source, cid, job_id, src)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if res is None:
        raise HTTPException(status_code=404, detail="job not found")
    return res


@router.get("/osint/jobs/{job_id}/events")
async def osint_job_events(
    request: Request,
    job_id: int,
    after: int = 0,
    cid: int = Depends(require_company),
):
    job = await asyncio.to_thread(osint_jobs.get_job, cid, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    header_last = request.headers.get("last-event-id", "").strip()
    cursor = max(after, int(header_last)) if header_last.isdigit() else max(0, after)

    async def _stream():
        nonlocal cursor
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            events = await asyncio.to_thread(osint_jobs.list_events, job_id, cursor)
            for event in events:
                cursor = event["seq"]
                idle = 0
                data = json.dumps(event["payload"], ensure_ascii=False)
                yield (
                    f"id: {event['seq']}\n"
                    f"event: {event['type']}\n"
                    f"data: {data}\n\n"
                )
            current = await asyncio.to_thread(osint_jobs.get_job, cid, job_id)
            if current and current["status"] in osint_jobs.TERMINAL:
                # 本轮没有新事件且任务已结束 → 收尾
                if not events:
                    yield "event: done\ndata: {}\n\n"
                    break
            if not events:
                idle += 1
                if idle % 15 == 0:
                    yield ": ping\n\n"
                await asyncio.sleep(1)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )
