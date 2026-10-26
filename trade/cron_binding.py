"""Hermes cron job 的公司归属（审计 P1-17）。

Hermes 的 jobs.json 是机器级、没有公司字段；Trade 不改 Hermes，而是：

1. 插件 `post_tool_call` 在 `cronjob_manage` 创建成功后拿到返回里的 job_id，
   把 job_id → 当前绑定公司写入 Trade 的 SQLite（`cron_job_companies`）；
2. 插件 `pre_tool_call` 挡住跨公司对已绑定 job 的 update/pause/resume/remove/run；
3. Trade 的 cron API 按映射过滤 job 列表，并按 job_id 读取输出目录。

未绑定的历史 job（Trade 之外创建的）没有归属信息：当公司数 >1 时不向任何
公司展示（避免把 A 的任务名/输出给 B），单公司时照常展示以保持兼容。
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

TOOL_NAME = "cronjob_manage"
_OWNED_ACTIONS = frozenset({"update", "pause", "resume", "remove", "run"})


def _conn():
    from trade.database import get_connection

    return get_connection()


def bind_job(job_id: str, company_id: int) -> None:
    """记录 job 归属；失败只记日志（不能影响 agent 的工具调用）。"""
    if not job_id or not company_id:
        return
    try:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO cron_job_companies (job_id, company_id) VALUES (?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET company_id = excluded.company_id",
                (str(job_id), int(company_id)),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("cron job 归属记录失败（不影响任务）: %s", e)


def unbind_job(job_id: str) -> None:
    if not job_id:
        return
    try:
        conn = _conn()
        try:
            conn.execute("DELETE FROM cron_job_companies WHERE job_id = ?", (str(job_id),))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("cron job 归属清理失败: %s", e)


def job_company(job_id: str) -> int | None:
    """job 归属的公司；未绑定/读取失败返回 None。"""
    if not job_id:
        return None
    try:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT company_id FROM cron_job_companies WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
            return int(row[0]) if row else None
        finally:
            conn.close()
    except Exception:
        return None


def visible_for_company(job_id: str, company_id: int, *, company_count: int) -> bool:
    """该 job 是否向 company_id 展示。

    - 已绑定：只给所属公司看；
    - 未绑定（Trade 之外创建的历史任务）：单公司时展示，多公司时隐藏，
      避免任务名/输出跨公司泄露。
    """
    owner = job_company(job_id)
    if owner is not None:
        return owner == company_id
    return company_count <= 1


def _current_company_id() -> int | None:
    try:
        from trade.agent_context import current_company_id

        return current_company_id()
    except Exception:
        return None


def on_pre_tool_call(tool_name: str = "", args=None, **_kw):
    """阻止跨公司操作已绑定的 cron job。"""
    if tool_name != TOOL_NAME or not isinstance(args, dict):
        return None
    action = str(args.get("action") or "").strip().lower()
    if action not in _OWNED_ACTIONS:
        return None
    job_id = str(args.get("job_id") or "").strip()
    owner = job_company(job_id)
    cid = _current_company_id()
    if owner is not None and cid is not None and owner != cid:
        return {
            "action": "block",
            "message": "trade 守卫：该定时任务属于其他公司，当前会话不能修改/运行它。",
        }
    return None


def on_post_tool_call(tool_name: str = "", args=None, result=None, **_kw) -> None:
    """创建/删除 cron job 后维护归属映射。永不抛异常。"""
    if tool_name != TOOL_NAME or not isinstance(args, dict):
        return
    action = str(args.get("action") or "").strip().lower()
    cid = _current_company_id()
    if action == "create":
        job_id = None
        if isinstance(result, str):
            try:
                data = json.loads(result)
                job_id = data.get("job_id") or (data.get("job") or {}).get("id")
            except (ValueError, TypeError):
                job_id = None
        if job_id and cid:
            bind_job(str(job_id), cid)
    elif action == "remove":
        job_id = args.get("job_id")
        if job_id:
            unbind_job(str(job_id))
