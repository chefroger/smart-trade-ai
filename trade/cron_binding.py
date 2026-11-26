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
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

TOOL_NAME = "cronjob_manage"
_OWNED_ACTIONS = frozenset({"update", "pause", "resume", "remove", "run"})
_PROMPT_COMPANY_ID_RE = re.compile(r"\bcompany_id\s*[:=]\s*(\d+)\b")
_PROMPT_COMPANY_NAME_RE = re.compile(r"当前公司[：:]\s*([^\n（(。]+)")


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


def infer_job_company(job: dict) -> int | None:
    """从 Hermes job 字典推断所属公司并在确认唯一归属时回填映射表。

    用于兼容插件钩子上线前已创建的任务，或模型在 Prompt / workdir 中写入了
    明确公司标识但未经过钩子落表的任务。未命中或存在歧义时返回 None。
    """
    # 非字典输入直接放弃推断，避免异常数据污染归属表
    if not isinstance(job, dict):
        return None

    job_id = str(job.get("id") or "").strip()
    # 若映射表已有显式归属记录，优先以映射表为准
    if job_id:
        existing = job_company(job_id)
        if existing is not None:
            return existing

    try:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT c.id, c.name, c.extra1, tc.data_dir "
                "FROM companies c "
                "LEFT JOIN trade_companies tc ON tc.company_id = c.id "
                "WHERE c.is_active = 1"
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return None

    # 没有任何激活公司时无法归属
    if not rows:
        return None

    active_by_id = {int(r["id"]): r for r in rows}
    prompt = str(job.get("prompt") or "")
    workdir = str(job.get("workdir") or "").strip()
    matched_cid: int | None = None

    # 1. 优先匹配 Prompt 中显式注入的 company_id=<N>（无歧义且属于当前激活公司）
    id_hits = {
        int(m.group(1))
        for m in _PROMPT_COMPANY_ID_RE.finditer(prompt)
        if int(m.group(1)) in active_by_id
    }
    if len(id_hits) == 1:
        matched_cid = next(iter(id_hits))

    # 2. 其次匹配 job.workdir 是否落在唯一激活公司的工作目录或数据目录内
    if matched_cid is None and workdir:
        try:
            target_wd = Path(os.path.expanduser(workdir)).resolve()
            wd_hits: set[int] = set()
            for cid, row in active_by_id.items():
                cand_dirs: list[str] = []
                if row["data_dir"]:
                    cand_dirs.append(str(row["data_dir"]))
                try:
                    ex1 = json.loads(row["extra1"] or "{}")
                    if isinstance(ex1, dict) and ex1.get("work_dir"):
                        cand_dirs.append(str(ex1["work_dir"]))
                except (ValueError, TypeError):
                    pass
                for raw_wd in cand_dirs:
                    raw_wd = raw_wd.strip()
                    # 跳过空目录配置
                    if not raw_wd:
                        continue
                    co_wd = Path(os.path.expanduser(raw_wd)).resolve()
                    # 任务目录等于公司目录或位于其子目录内，视为归属该公司
                    if target_wd == co_wd or co_wd in target_wd.parents:
                        wd_hits.add(cid)
                        break
            if len(wd_hits) == 1:
                matched_cid = next(iter(wd_hits))
        except (OSError, ValueError):
            pass

    # 3. 最后尝试匹配「当前公司：<名称>」头部声明的唯一激活公司名
    if matched_cid is None and prompt:
        m = _PROMPT_COMPANY_NAME_RE.search(prompt)
        if m:
            declared_name = m.group(1).strip().lower()
            name_hits = {
                cid
                for cid, row in active_by_id.items()
                if str(row["name"] or "").strip().lower() == declared_name
            }
            if len(name_hits) == 1:
                matched_cid = next(iter(name_hits))

    # 确认唯一归属后回填数据库，避免后续每次轮询重复解析
    if matched_cid is not None and job_id:
        bind_job(job_id, matched_cid)
    return matched_cid


def visible_for_company(
    job_id: str,
    company_id: int,
    *,
    company_count: int,
    job: dict | None = None,
) -> bool:
    """该 job 是否向 company_id 展示。

    - 已绑定（或可从 job 元信息唯一推断归属）：只给所属公司看；
    - 未绑定（Trade 之外创建的历史任务）：单公司时展示，多公司时隐藏，
      避免任务名/输出跨公司泄露。
    """
    owner = job_company(job_id)
    # 映射表未命中但传入了完整 job 字典时，尝试按 Prompt/workdir 推断归属
    if owner is None and isinstance(job, dict):
        owner = infer_job_company(job)
    # 有明确归属公司时严格按公司匹配
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
        job_id = None
        # Hermes 支持按任务名删除并在返回 JSON 的 removed_job.id 中给出真实 ID
        if isinstance(result, str):
            try:
                data = json.loads(result)
                job_id = (data.get("removed_job") or {}).get("id")
            except (ValueError, TypeError):
                job_id = None
        # 返回体未带真实 ID 时回退使用调用参数中的 job_id
        if not job_id:
            job_id = args.get("job_id")
        if job_id:
            unbind_job(str(job_id))
