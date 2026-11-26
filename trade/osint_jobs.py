"""背调后台任务（工单 P1-1）。

把 6 层 + 公开来源的确定性采集放进后台线程：切换公司、刷新页面、SSE 断线
都不会杀任务；事件按 seq 持久化，前端用 `Last-Event-ID` / `?after=` 续传。

状态机：queued → running → done | failed | partial | cancelled
  - 服务重启时，遗留的 running/queued 统一标 partial（已有事件仍可读）
  - cancel 标记状态并停止后续事件落库；O-22 起会把 should_cancel 传进
    编排器，取消未完成的层并立即收尾（已在跑的 HTTP 线程无法强杀，结果丢弃）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta

from trade.database import begin_immediate, get_connection

logger = logging.getLogger(__name__)

TERMINAL = frozenset({"done", "failed", "partial", "cancelled"})
_REUSE_WINDOW_SECONDS = 600
_MAX_CONCURRENT = 2
_DEFAULT_BUDGET = float(os.environ.get("TRADE_OSINT_JOB_BUDGET", "300"))

_semaphore = threading.Semaphore(_MAX_CONCURRENT)
_cancel_lock = threading.Lock()
_cancelled: set[int] = set()
# 本进程内已启动的任务：只有它们才需要"取消标记"。
# 未启动就取消的任务（比如排队中被取消）不能留标记 —— job id 在不同数据库里会
# 从 1 重新开始（测试就是独立的临时库），残留标记会让新任务误判为已取消。
_active: set[int] = set()


# ── 读取 ────────────────────────────────────────────────────────────────────


def _row_to_job(row) -> dict:
    job = dict(row)
    report = job.pop("report_json", "") or ""
    try:
        job["report"] = json.loads(report) if report else None
    except ValueError:
        job["report"] = None
    return job


def get_job(company_id: int, job_id: int) -> dict | None:
    """按公司取任务（跨公司不可见）。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM osint_jobs WHERE id = ? AND company_id = ?",
            (job_id, company_id),
        ).fetchone()
    finally:
        conn.close()
    return _row_to_job(row) if row else None


def list_jobs(company_id: int, limit: int = 20) -> list[dict]:
    """该公司最近的任务（不含 report，避免列表接口过大）。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, company_id, target, target_type, status, created_at, updated_at "
            "FROM osint_jobs WHERE company_id = ? ORDER BY id DESC LIMIT ?",
            (company_id, max(1, min(int(limit), 100))),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def list_events(job_id: int, after_seq: int = 0, limit: int = 500) -> list[dict]:
    """返回 seq > after_seq 的事件（升序），供 SSE 续传。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT seq, ts, type, payload_json FROM osint_job_events "
            "WHERE job_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (job_id, max(0, int(after_seq)), max(1, min(limit, 1000))),
        ).fetchall()
    finally:
        conn.close()
    events = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except ValueError:
            payload = {}
        events.append({
            "seq": int(row["seq"]),
            "ts": row["ts"],
            "type": row["type"],
            "payload": payload,
        })
    return events


def append_event(job_id: int, event_type: str, payload: dict | None = None) -> int:
    """追加一条事件，返回新 seq（写事务串行化，防止工作线程与取消线程并发撞键）。"""
    conn = get_connection()
    try:
        # BEGIN IMMEDIATE 保证并发追加事件时 MAX(seq)+1 分配互斥
        begin_immediate(conn)
        try:
            cur = conn.execute(
                "INSERT INTO osint_job_events(job_id, seq, type, payload_json) "
                "SELECT ?, COALESCE(MAX(seq), 0) + 1, ?, ? "
                "FROM osint_job_events WHERE job_id = ?",
                (job_id, event_type, json.dumps(payload or {}, ensure_ascii=False), job_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT seq FROM osint_job_events WHERE rowid = ?", (cur.lastrowid,)
            ).fetchone()
            return int(row["seq"]) if row else 0
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


# ── 创建 / 取消 ─────────────────────────────────────────────────────────────


def create_job(company_id: int, target: str) -> tuple[dict, bool]:
    """创建任务；10 分钟内同公司同目标复用已有任务。

    Returns:
        (job, created)；created=False 表示复用。
    """
    target = (target or "").strip()
    if not target:
        raise ValueError("target is required")
    cutoff = (datetime.now() - timedelta(seconds=_REUSE_WINDOW_SECONDS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn = get_connection()
    try:
        # check-then-insert 必须串行化（2026-11-22 审计 P2-1）：两个并发请求同时
        # SELECT 看不到对方、再各自 INSERT，10 分钟去重就被击穿，整条背调重复外部采集。
        # BEGIN IMMEDIATE 拿写锁（busy_timeout=30s），跨进程也成立。
        begin_immediate(conn)
        try:
            # 只复用**还在排队/运行**的任务。复用已完成任务会让用户以为“又背调了一次”，
            # 实际看到的是几分钟前的旧结果，且大动画不会出现（界面按设计跳过已完成任务）。
            # 2026-11-22 实机：同目标连点两次，第二次静默复用 done 任务 → 只见报告、无动画。
            row = conn.execute(
                "SELECT * FROM osint_jobs WHERE company_id = ? AND lower(target) = lower(?) "
                "AND created_at >= ? AND status IN ('queued', 'running') "
                "ORDER BY id DESC LIMIT 1",
                (company_id, target, cutoff),
            ).fetchone()
            if row:
                conn.commit()
                return _row_to_job(row), False

            cur = conn.execute(
                "INSERT INTO osint_jobs(company_id, target, target_type, status) "
                "VALUES (?, ?, '', 'queued')",
                (company_id, target),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM osint_jobs WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return _row_to_job(row), True
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def cancel_job(company_id: int, job_id: int) -> dict | None:
    """取消任务（幂等）；任务不存在或不属于该公司返回 None。"""
    job = get_job(company_id, job_id)
    if job is None:
        return None
    if job["status"] in TERMINAL:
        return job  # 已结束：取消是幂等的，不再追加事件
    with _cancel_lock:
        if job_id in _active:
            _cancelled.add(job_id)
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE osint_jobs SET status = 'cancelled', updated_at = datetime('now','localtime') "
            "WHERE id = ? AND status NOT IN ('done','failed','partial','cancelled')",
            (job_id,),
        )
        conn.commit()
    finally:
        conn.close()
    append_event(job_id, "cancelled", {"message": "用户取消"})
    return get_job(company_id, job_id)


def _is_cancelled(job_id: int) -> bool:
    with _cancel_lock:
        return job_id in _cancelled


def recover_stale_jobs() -> int:
    """服务启动时把遗留的 running/queued 标成 partial（事件仍可读）。"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE osint_jobs SET status = 'partial', updated_at = datetime('now','localtime') "
            "WHERE status IN ('queued', 'running')"
        )
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()


# ── 执行 ────────────────────────────────────────────────────────────────────


def _current_status(job_id: int) -> str:
    """读任务状态（不带公司过滤；调用方已持有 job_id）。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT status FROM osint_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    finally:
        conn.close()
    return str(row["status"]) if row else ""


def start_job(job_id: int, target: str, budget: float | None = None) -> None:
    """后台线程执行；并发上限 2，排队任务保持 queued。

    2026-11-22 审计 P2-2：create → cancel → start 的间隙里任务已被取消，
    旧实现仍会跑完整条外部采集（事件再落到已取消任务上）。这里启动前重读状态：
    - 先登记 active 再把取消标记复位（并发 cancel 会看到 active 并置标记）
    - 重读状态，非 queued/running 直接退出
    - cancel 发生在重读之后、线程启动之前：cancel 会看到 active 置标记，
      `_run_job` 拿到信号量后会再次检查并退出
    """
    with _cancel_lock:
        _active.add(job_id)
        _cancelled.discard(job_id)
    if _current_status(job_id) not in ("queued", "running"):
        with _cancel_lock:
            _active.discard(job_id)
            _cancelled.discard(job_id)
        return
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, target, budget if budget is not None else _DEFAULT_BUDGET),
        daemon=True,
        name=f"osint-job-{job_id}",
    )
    thread.start()


def _update_status(job_id: int, status: str, report: dict | None = None) -> None:
    conn = get_connection()
    try:
        if report is None:
            conn.execute(
                "UPDATE osint_jobs SET status = ?, updated_at = datetime('now','localtime') "
                "WHERE id = ? AND status NOT IN ('cancelled')",
                (status, job_id),
            )
        else:
            conn.execute(
                "UPDATE osint_jobs SET status = ?, report_json = ?, "
                "updated_at = datetime('now','localtime') "
                "WHERE id = ? AND status NOT IN ('cancelled')",
                (status, json.dumps(report, ensure_ascii=False, default=str), job_id),
            )
        conn.commit()
    finally:
        conn.close()


def _run_job(job_id: int, target: str, budget: float) -> None:
    acquired = _semaphore.acquire()
    try:
        if not acquired or _is_cancelled(job_id):
            return
        _update_status(job_id, "running")
        append_event(job_id, "job_start", {"target": target, "budget": budget})

        def _on_event(event: dict) -> None:
            if _is_cancelled(job_id):
                return
            append_event(job_id, str(event.get("event") or "event"), event)

        from trade.osint.orchestrator import osint_full_check

        # 绑定公司上下文：EDGAR 等官方接口要取当前公司的 contact_email
        # （2026-11-23 审计 P2-3）。后台线程不会继承请求线程的 ContextVar。
        company_id = None
        try:
            from trade.database import get_connection

            conn = get_connection()
            try:
                row = conn.execute(
                    "SELECT company_id FROM osint_jobs WHERE id = ?", (job_id,)
                ).fetchone()
                company_id = int(row[0]) if row else None
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 —— 取不到就退回环境变量
            company_id = None

        from contextlib import nullcontext

        from trade.agent_context import bind_company

        started = time.time()
        with (bind_company(company_id) if company_id is not None else nullcontext()):
            report = asyncio.run(
                osint_full_check(
                    target, budget=budget, on_event=_on_event,
                    # W15 O-22：取消后立即收尾，不再等整条采集跑完
                    should_cancel=lambda: _is_cancelled(job_id),
                )
            )
        if _is_cancelled(job_id):
            return
        append_event(job_id, "verdict", {
            "rating": report.get("overall_rating"),
            "unverified": report.get("unverified") or [],
            "ms": int((time.time() - started) * 1000),
        })
        _update_status(job_id, "done", report)
    except Exception as exc:  # noqa: BLE001 —— 单任务失败不影响服务
        logger.exception("OSINT job %s failed", job_id)
        if not _is_cancelled(job_id):
            append_event(job_id, "error", {"message": f"{type(exc).__name__}: {exc}"})
            _update_status(job_id, "failed")
    finally:
        if acquired:
            _semaphore.release()
        with _cancel_lock:
            _cancelled.discard(job_id)
            _active.discard(job_id)
