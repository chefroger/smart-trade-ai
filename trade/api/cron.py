"""
Trade AI Assistant — Cron 任务 API。

读取 Hermes cron 输出和 jobs.json，返回今日任务清单及已激活任务列表。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from trade.api.deps import require_company

router = APIRouter(tags=["cron"])

_hermes_val = os.environ.get("HERMES_HOME", "").strip()
if _hermes_val:
    _HERMES_HOME = Path(_hermes_val)
elif os.name == "nt":
    _local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    _HERMES_HOME = Path(_local) / "hermes"
else:
    _HERMES_HOME = Path.home() / ".hermes"
_CRON_OUTPUT = _HERMES_HOME / "cron" / "output"
_JOBS_FILE = _HERMES_HOME / "cron" / "jobs.json"


@router.get("/cron/today")
def get_today_cron(cid: int = Depends(require_company)):
    """返回今日 cron 任务清单（已执行 + 待执行）。

    任务来源: jobs.json 中已激活的定时任务。如果 jobs.json 不存在或为空，
    回退到内置标准任务列表。要求公司上下文（require_company）。
    """
    today = date.today().isoformat()
    now = datetime.now()
    current_time = now.strftime("%H:%M")

    # 从 jobs.json 读取实际激活的任务
    active_jobs = _load_active_jobs()
    if active_jobs:
        tasks = active_jobs
    else:
        # 回退到内置标准任务列表
        tasks = [
            {"name": "早安简报", "time": "09:00"},
            {"name": "邮件处理与跟进", "time": "09:00-10:30"},
            {"name": "精准加人 (LinkedIn)", "time": "10:00-11:30"},
            {"name": "评论互动与私信致谢", "time": "11:30-12:00"},
            {"name": "LinkedIn 内容发布", "time": "15:30"},
            {"name": "B2B 平台检查", "time": "15:30-17:00"},
            {"name": "客户开发", "time": "13:30-15:30"},
            {"name": "每日工作总结", "time": "17:00"},
        ]

    completed = []
    pending = []

    for task in tasks:
        task_name = task["name"]
        task_time = task["time"].split("-")[0] if "-" in task["time"] else task["time"]
        # task_time 为空字符串时按"未到点"处理，避免 "" <= "14:30" 永远 True 导致空任务被永远标记 missed
        is_past = bool(task_time) and task_time <= current_time
        output = _find_cron_output(task_name, today)

        if output:
            completed.append({
                "name": task_name, "time": task["time"],
                "output": output, "has_output": True,
            })
        elif is_past:
            pending.append({
                "name": task_name, "time": task["time"],
                "scheduled": task_time, "missed": True,
            })
        else:
            pending.append({
                "name": task_name, "time": task["time"],
                "scheduled": task_time, "missed": False,
            })

    return {"today": today, "current_time": current_time, "completed": completed, "pending": pending}


def _load_active_jobs():
    """从 jobs.json 读取已激活的定时任务，提取 name 和 time。"""
    if not _JOBS_FILE.is_file():
        return []
    try:
        with open(_JOBS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    tasks = []
    job_list = data.get("jobs", [])
    if isinstance(job_list, list):
        for job in job_list:
            if not isinstance(job, dict):
                continue
            name = job.get("name", job.get("task_name", ""))
            # 从 cron 或调度信息中提取人类可读的时间
            schedule_display = _extract_time_display(job)
            if name:
                tasks.append({"name": name, "time": schedule_display, "job_id": job.get("id", "")})
    elif isinstance(job_list, dict):
        for job_id, job in job_list.items():
            if not isinstance(job, dict):
                continue
            name = job.get("task_name", job.get("name", ""))
            schedule_display = _extract_time_display(job)
            if name:
                tasks.append({"name": name, "time": schedule_display, "job_id": job_id})
    return tasks


def _extract_time_display(job: dict) -> str:
    """从 cron job 中提取人类可读的时间显示。

    优先级: schedule.display → schedule_display → 从 next_run_at 提取时分 → 空串
    将 cron 表达式 "0 9 * * 1-5" 转换为 "09:00"。
    """
    # 尝试从 schedule.dict 或 schedule_display 中获取
    sched = job.get("schedule", {})
    if isinstance(sched, dict):
        display = sched.get("display", "")
        if display:
            time_str = _cron_to_time(display)
            if time_str:
                return time_str
    sched_display = job.get("schedule_display", "")
    if sched_display:
        time_str = _cron_to_time(sched_display)
        if time_str:
            return time_str
    # 从 next_run_at 提取时分
    next_run = job.get("next_run_at", "")
    if next_run:
        try:
            # 格式: "2026-05-22T09:00:00+08:00"
            return next_run[11:16]
        except Exception:
            pass
    return ""


def _cron_to_time(expr: str) -> str:
    """将 5 段 cron 表达式转换为 "HH:MM" 显示。

    只处理简单的 "M H * * *" 或 "M H * * D" 格式。
    其他格式返回空串。
    """
    import re
    parts = expr.strip().split()
    if len(parts) >= 2:
        m, h = parts[0], parts[1]
        # 验证小时和分钟是数字
        if re.match(r'^\d+$', h) and re.match(r'^\d+$', m):
            return f"{int(h):02d}:{int(m):02d}"
    return ""


@router.get("/cron/jobs")
def get_active_jobs(cid: int = Depends(require_company)):
    """返回 Hermes cron 中已激活的定时任务列表。

    从 ~/.hermes/cron/jobs.json 读取，返回任务名称、调度时间、下次执行时间。
    要求公司上下文（require_company）。
    """
    if not _JOBS_FILE.is_file():
        return []

    try:
        with open(_JOBS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    jobs = []
    # Hermes cron jobs.json 格式: {"jobs": [...], "updated_at": "..."}
    job_list = data.get("jobs", [])
    if isinstance(job_list, list):
        for job in job_list:
            if not isinstance(job, dict):
                continue
            jobs.append({
                "id": job.get("id", ""),
                "name": job.get("name", job.get("task_name", "")),
                "schedule": job.get("schedule", {}).get("display", job.get("schedule_display", "")),
                "next_run": job.get("next_run_at", ""),
                "enabled": job.get("enabled", True),
                "deliver": job.get("deliver", "local"),
            })
    else:
        # 兼容旧格式: {job_id: job_dict, ...}
        for job_id, job in job_list.items() if isinstance(job_list, dict) else []:
            if not isinstance(job, dict):
                continue
            jobs.append({
                "id": job_id,
                "name": job.get("task_name", job.get("name", job_id)),
                "schedule": job.get("schedule", {}).get("display", "") if isinstance(job.get("schedule"), dict) else job.get("schedule", ""),
                "next_run": job.get("next_run_at", ""),
                "enabled": job.get("enabled", True),
                "deliver": job.get("deliver", "local"),
            })

    return jobs


_capture_lock = threading.Lock()


def _capture_output(func, *args, **kwargs) -> dict:
    """在内存中捕获函数的 print 输出（含 stdout 和 stderr），返回 {"ok": True, "output": str}。

    线程安全：全局锁防止并发请求时 sys.stdout/stderr 重定向互相污染。
    subprocess 的 stderr 也会被捕获，不会再静默丢失。
    """
    with _capture_lock:
        try:
            import io
            _buf_stdout = io.StringIO()
            _buf_stderr = io.StringIO()
            _orig_stdout = sys.stdout
            _orig_stderr = sys.stderr
            sys.stdout = _buf_stdout
            sys.stderr = _buf_stderr
            try:
                result = func(*args, **kwargs)
            finally:
                sys.stdout = _orig_stdout
                sys.stderr = _orig_stderr
            output = _buf_stdout.getvalue()
            errors = _buf_stderr.getvalue()
            if errors:
                output += "\n[stderr]\n" + errors
            resp = {"ok": True, "output": output}
            if isinstance(result, str) and result:
                resp["file"] = result
            return resp
        except SystemExit as e:
            return {"ok": False, "error": f"Process exited with code {e.code}", "output": getattr(sys, 'stdout', None) and ''}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ── Skills update 限流（5 req/min per token） ────────────────────────────

_skills_rate_lock = threading.Lock()
_skills_rate_map: dict[str, list[float]] = {}
_SKILLS_RATE_WINDOW = 60
_SKILLS_RATE_MAX = 5


def _check_skills_rate_limit(key: str) -> bool:
    """Skills 更新限流。"""
    now = time.time()
    with _skills_rate_lock:
        stamps = _skills_rate_map.get(key, [])
        stamps = [t for t in stamps if now - t < _SKILLS_RATE_WINDOW]
        if len(stamps) >= _SKILLS_RATE_MAX:
            _skills_rate_map[key] = stamps
            return False
        stamps.append(now)
        _skills_rate_map[key] = stamps
        return True


@router.post("/skills/update")
def api_update_skills(request: Request):
    """从 GitHub 拉取最新 B2B skill 定义。"""
    _tk = request.headers.get("X-Hermes-Session-Token", "")
    if _tk and not _check_skills_rate_limit(_tk[:16]):
        raise HTTPException(status_code=429, detail="Skills 更新请求过于频繁，请稍后重试。")

    from trade.post_install import update_skills as _do_update
    return _capture_output(_do_update)


@router.get("/cron/health")
def get_customer_health_audit(cid: int = Depends(require_company)):
    """客户健康审计：检测僵尸客户、高价值未转化、数据不完整等维度。

    可由 b2b-daily-automation 技能在定时任务中调用，生成早安简报中的客户健康概览。
    """
    from trade import customer as customer_module
    return customer_module.health_audit(cid)


def _find_cron_output(task_name: str, today: str) -> str | None:
    if not _CRON_OUTPUT.is_dir():
        return None
    for job_dir in sorted(_CRON_OUTPUT.iterdir(), reverse=True):
        if not job_dir.is_dir():
            continue
        for output_file in sorted(job_dir.glob("*.md"), reverse=True):
            try:
                content = output_file.read_text(encoding="utf-8")
                if task_name in content and today in output_file.stem[:10]:
                    return content
            except Exception:
                continue
    return None
