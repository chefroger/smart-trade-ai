"""
Trade AI Assistant — Cron 任务 API。

读取 Hermes cron 输出和 jobs.json，返回今日任务清单及已激活任务列表。
"""

from __future__ import annotations

import json
import os
import re
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
    回退到内置标准任务列表。

    公司隔离（审计 P1-17）：jobs.json 本身没有公司字段，Trade 用
    `trade.cron_binding` 里维护的 job_id→公司映射过滤；未绑定的历史任务在
    多公司机器上不展示（避免把 A 的任务名/输出给 B）。
    """
    today = date.today().isoformat()
    now = datetime.now()
    current_time = now.strftime("%H:%M")

    # 从 jobs.json 读取实际已启用（enabled=True）的任务
    active_jobs = _load_active_jobs(cid)
    # 汇总用户已设置并激活的 Hermes cron 任务及其最新产出，供前端右栏直接渲染
    active_items = _build_active_cron_items(active_jobs, today)
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
        # `"09:00-10:30"` 是**执行窗口**：起点决定"scheduled"（几点开始），
        # 终点决定"missed"（到什么时候为止还算没跑）。原先只取起点判 missed，
        # 09:30 时一个窗口到 10:30 的任务会被误标"已过时"（2026-10-21 审计 P2）。
        parts = task["time"].split("-", 1)
        task_time = parts[0]
        task_window_end = parts[1] if len(parts) > 1 else parts[0]
        output = _find_cron_output(task_name, today, job_id=task.get("job_id", ""))

        if output:
            # Hermes 判无新内容时写 [SILENT] 并跳过投递；产出文件仍在。
            # Trade 今日简报不展示气泡、不计入「已完成待看」——只在有实质
            # 完成 / 失败 / 需用户动作时显示。
            if _is_silent_cron_output(output):
                completed.append({
                    "name": task_name, "time": task["time"],
                    "job_id": task.get("job_id", ""),
                    "output": None, "has_output": False, "silent": True,
                })
            else:
                completed.append({
                    "name": task_name, "time": task["time"],
                    "job_id": task.get("job_id", ""),
                    "output": output, "has_output": True,
                })
            continue

        # 第三态：调度解析不出来。`_cron_to_time` 只处理 "M H * * *"，
        # `*/5 * * * *`、`0 9 1 * *` 这类返回空串。此前用 bool(task_time) 把它
        # 归进"未到点"，于是界面显示「待执行」—— 真相是"不知道几点跑"，
        # 一个从没执行过的任务会被用户一直当成还没到时间。
        # （bool 守卫本身是为了修 "空串 <= '14:30' 那个 bug，不能退回去。）
        if not task_time:
            pending.append({
                "name": task_name, "time": task["time"],
                "scheduled": None, "missed": None, "unknown_schedule": True,
            })
            continue

        # 过了窗口终点才算 missed；窗口内（current <= end）仍是"待执行"
        if task_window_end < current_time:
            pending.append({
                "name": task_name, "time": task["time"],
                "scheduled": task_time, "missed": True,
            })
        else:
            pending.append({
                "name": task_name, "time": task["time"],
                "scheduled": task_time, "missed": False,
            })

    return {
        "today": today,
        "current_time": current_time,
        "completed": completed,
        "pending": pending,
        "active_items": active_items,
    }


def _company_count() -> int:
    """当前激活公司数（决定未绑定历史 job 是否可展示）。"""
    try:
        from trade.database import get_connection

        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM companies WHERE is_active = 1"
            ).fetchone()
            return int(row[0] or 0) if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


def _extract_schedule_raw(job: dict) -> str:
    """提取任务原始 cron 表达式或可读调度串。"""
    sched = job.get("schedule", {})
    # 新版 Hermes schedule 为字典，优先读 display，回退 expr
    if isinstance(sched, dict):
        return str(sched.get("display") or sched.get("expr") or job.get("schedule_display") or "")
    # 旧格式中 schedule 直接是字符串
    if isinstance(sched, str) and sched:
        return sched
    return str(job.get("schedule_display") or "")


def _load_active_jobs(company_id: int | None = None):
    """从 jobs.json 读取已启用（enabled=True）的定时任务，按公司过滤后提取元信息。"""
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
            # 已暂停（enabled=False）的任务不计入已激活列表
            if not job.get("enabled", True):
                continue
            name = job.get("name", job.get("task_name", ""))
            job_id = str(job.get("id", "") or "")
            schedule_display = _extract_time_display(job)
            if name and _job_visible(job_id, company_id, job=job):
                tasks.append({
                    "name": name,
                    "time": schedule_display,
                    "job_id": job_id,
                    "schedule": _extract_schedule_raw(job),
                    "next_run": str(job.get("next_run_at") or ""),
                    "last_run": str(job.get("last_run_at") or ""),
                })
    elif isinstance(job_list, dict):
        for job_id, job in job_list.items():
            if not isinstance(job, dict):
                continue
            # 已暂停（enabled=False）的任务不计入已激活列表
            if not job.get("enabled", True):
                continue
            name = job.get("task_name", job.get("name", ""))
            schedule_display = _extract_time_display(job)
            jid = str(job_id)
            if name and _job_visible(jid, company_id, job={**job, "id": jid}):
                tasks.append({
                    "name": name,
                    "time": schedule_display,
                    "job_id": jid,
                    "schedule": _extract_schedule_raw(job),
                    "next_run": str(job.get("next_run_at") or ""),
                    "last_run": str(job.get("last_run_at") or ""),
                })
    return tasks


def _build_active_cron_items(active_jobs: list[dict], today: str) -> list[dict]:
    """为当前公司所有已启用定时任务组装最新 Hermes cron 输出摘要。"""
    items: list[dict] = []
    for task in active_jobs:
        job_id = str(task.get("job_id") or "")
        output, run_at, is_silent = _find_latest_cron_output(job_id)
        is_today = bool(run_at and run_at[:10] == today)
        items.append({
            "job_id": job_id,
            "name": task.get("name") or "",
            "time": task.get("time") or task.get("schedule") or "",
            "schedule": task.get("schedule") or "",
            "next_run": task.get("next_run") or "",
            "output": output,
            "has_output": bool(output),
            "run_at": run_at,
            "is_today": is_today,
            "silent": is_silent,
        })
    return items


def _extract_time_display(job: dict) -> str:
    """从 cron job 中提取人类可读的时间显示。

    优先级: schedule.display/expr → schedule_display → 从 next_run_at 提取时分 → 空串
    将 cron 表达式 "0 9 * * 1-5" 转换为 "09:00"。
    """
    # 尝试从 schedule 字典（display 或 expr）中获取
    sched = job.get("schedule", {})
    if isinstance(sched, dict):
        display = sched.get("display") or sched.get("expr") or ""
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
    parts = expr.strip().split()
    if len(parts) >= 2:
        m, h = parts[0], parts[1]
        # 验证小时和分钟是数字
        if re.match(r"^\d+$", h) and re.match(r"^\d+$", m):
            return f"{int(h):02d}:{int(m):02d}"
    return ""


@router.get("/cron/jobs")
def get_active_jobs(cid: int = Depends(require_company)):
    """返回当前公司可见的 Hermes cron 定时任务（审计 P1-17）。

    映射由 trade.cron_binding 维护；未绑定的历史任务只在单公司机器上展示。
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
            job_id = str(job.get("id", "") or "")
            if not _job_visible(job_id, cid, job=job):
                continue
            latest_out, run_at, _silent = _find_latest_cron_output(job_id)
            jobs.append({
                "id": job_id,
                "name": job.get("name", job.get("task_name", "")),
                "schedule": _extract_schedule_raw(job),
                "next_run": job.get("next_run_at", ""),
                "last_run": job.get("last_run_at", ""),
                "run_at": run_at,
                "has_output": bool(latest_out),
                "enabled": job.get("enabled", True),
                "deliver": job.get("deliver", "local"),
            })
    else:
        # 兼容旧格式: {job_id: job_dict, ...}
        for job_id, job in job_list.items() if isinstance(job_list, dict) else []:
            if not isinstance(job, dict):
                continue
            jid = str(job_id)
            if not _job_visible(jid, cid, job={**job, "id": jid}):
                continue
            latest_out, run_at, _silent = _find_latest_cron_output(jid)
            jobs.append({
                "id": job_id,
                "name": job.get("task_name", job.get("name", job_id)),
                "schedule": _extract_schedule_raw(job),
                "next_run": job.get("next_run_at", ""),
                "last_run": job.get("last_run_at", ""),
                "run_at": run_at,
                "has_output": bool(latest_out),
                "enabled": job.get("enabled", True),
                "deliver": job.get("deliver", "local"),
            })

    return jobs


@router.get("/cron/jobs/{job_id}/output")
def get_cron_job_output(job_id: str, cid: int = Depends(require_company)):
    """返回指定 Hermes cron 任务最近一次执行的完整输出正文。"""
    # 校验 job_id 格式，禁止路径穿越字符
    clean_id = (job_id or "").strip()
    if not clean_id or "/" in clean_id or "\\" in clean_id or ".." in clean_id:
        raise HTTPException(status_code=400, detail="非法任务 ID")

    matched_job: dict | None = None
    if _JOBS_FILE.is_file():
        try:
            with open(_JOBS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            job_list = data.get("jobs", [])
            if isinstance(job_list, list):
                for j in job_list:
                    if isinstance(j, dict) and str(j.get("id") or "") == clean_id:
                        matched_job = j
                        break
            elif isinstance(job_list, dict) and isinstance(job_list.get(clean_id), dict):
                matched_job = {**job_list[clean_id], "id": clean_id}
        except Exception:
            matched_job = None

    # 任务不存在或不属于当前公司时统一返回 404，避免探测其它公司任务
    if matched_job is None or not _job_visible(clean_id, cid, job=matched_job):
        raise HTTPException(status_code=404, detail="未找到该定时任务")

    output, run_at, is_silent = _find_latest_cron_output(clean_id)
    today = date.today().isoformat()
    return {
        "job_id": clean_id,
        "name": matched_job.get("name", matched_job.get("task_name", clean_id)),
        "schedule": _extract_schedule_raw(matched_job),
        "run_at": run_at,
        "is_today": bool(run_at and run_at[:10] == today),
        "output": output,
        "has_output": bool(output),
        "silent": is_silent,
    }


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


def _job_visible(
    job_id: str,
    company_id: int | None,
    *,
    job: dict | None = None,
) -> bool:
    """按公司过滤 job；无约定公司上下文时不过滤（internal 调用兼容）。"""
    if not company_id:
        return True
    try:
        from trade.cron_binding import visible_for_company

        return visible_for_company(
            job_id,
            company_id,
            company_count=_company_count(),
            job=job,
        )
    except Exception:
        return False


_HERMES_RESPONSE_SPLIT_RE = re.compile(
    r"(?:^|\n)(?:\*\*Response Characters:\*\*\s*\d+\s*\n)?## Response\s*\n"
)
_OUTPUT_STEM_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})(?:-(\d{2}))?")


def _extract_cron_response(raw: str) -> str:
    """剥离 Hermes 落盘包装头（# Cron Job / ## Prompt），只提取真实 ## Response 正文。

    若文件不含 Hermes 标准包装头（如手工写入或单元测试样本），原样返回。
    """
    if not raw:
        return ""
    stripped = raw.lstrip()
    # 仅在文件具备 Hermes Cron 包装头特征时才切分 ## Response，避免误切普通 Markdown
    if stripped.startswith("# Cron Job:") or "**Job ID:**" in stripped[:400]:
        m = _HERMES_RESPONSE_SPLIT_RE.search(raw)
        if m:
            return raw[m.end():].strip()
    return raw


def _parse_output_run_at(stem: str) -> str:
    """从产出文件名（如 2026-11-26_09-04-14）提取可读执行时间 'YYYY-MM-DD HH:MM'。"""
    m = _OUTPUT_STEM_TS_RE.match(stem or "")
    # 标准文件名提取到分钟级时间戳
    if m:
        return f"{m.group(1)} {m.group(2)}:{m.group(3)}"
    # 非标准文件名仅在具备日期前缀时回退返回日期
    if len(stem or "") >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}$", stem[:10]):
        return stem[:10]
    return ""


def _is_silent_cron_output(text: str) -> bool:
    """判断 cron 产出是否为 Hermes 静默 / 无变化标记。

    Hermes 无新内容时输出 `[SILENT]`（或等价 no_change 标记）。只认「全文
    实质等于该标记」——正文里顺带提到 SILENT 的正常产出不算静默。
    """
    if not text:
        return False
    cleaned = _extract_cron_response(text)
    # 去掉空白后只剩标记本身
    compact = "".join(cleaned.split()).upper()
    return compact in {"[SILENT]", "SILENT", "[NO_CHANGE]", "NO_CHANGE"}


def _find_cron_output(task_name: str, today: str, job_id: str = "") -> str | None:
    """只读任务自己的今日产出：cron/output/<job_id>/<YYYY-MM-DD_HH-MM-SS>.md。

    任务身份用 job 目录（job_id）精确判定，日期取文件名前 10 位并精确相等。
    旧实现按「任务名出现在正文里」匹配 —— 别家任务的输出提到这个名字就会
    串回来（审计 P1-17）。没有 job_id 时不猜：宁可显示待执行，也不做正文
    子串匹配。
    """
    if not job_id or not _CRON_OUTPUT.is_dir():
        return None
    job_dir = _CRON_OUTPUT / job_id
    if not job_dir.is_dir():
        return None
    for output_file in sorted(job_dir.glob("*.md"), reverse=True):
        if output_file.stem[:10] != today:
            continue
        try:
            raw = output_file.read_text(encoding="utf-8")
            return _extract_cron_response(raw)
        except Exception:
            continue
    return None


def _find_latest_cron_output(job_id: str) -> tuple[str | None, str | None, bool]:
    """读取指定任务最近一次执行的产出，返回 (正文或None, 运行时刻, 是否静默)。"""
    if not job_id or not _CRON_OUTPUT.is_dir():
        return None, None, False
    job_dir = _CRON_OUTPUT / job_id
    if not job_dir.is_dir():
        return None, None, False
    for output_file in sorted(job_dir.glob("*.md"), reverse=True):
        try:
            raw = output_file.read_text(encoding="utf-8")
        except Exception:
            continue
        run_at = _parse_output_run_at(output_file.stem)
        resp = _extract_cron_response(raw)
        # 空文件继续向前找或视作无产出
        if not resp or not resp.strip():
            continue
        # 最近一次为静默标记时，不返回 [SILENT] 文本，仅标记 silent=True
        if _is_silent_cron_output(resp):
            return None, run_at or None, True
        return resp, run_at or None, False
    return None, None, False
