"""今日简报聚合（屏 1 KPI + 早安摘要）。"""

from __future__ import annotations

from datetime import date


def get_today_brief(company_id: int) -> dict:
    """聚合今日简报：新询盘 / 逾期跟进 / 待出货 / 早安摘要。

    new_inquiries = 本公司 inquiries 中 created_at 为今天（本地时区）的行数，
    不限阶段。不用邮件数顶替；inquiries 表不存在（极旧库）时返回 None，
    前端继续显示「—」。
    """
    today = date.today().isoformat()
    from trade.customer import get_company_summary
    from trade.database import get_connection

    # 逾期口径与 /customers/summary 一致：next_follow_up_date < 今天
    overdue = int(get_company_summary(company_id).get("overdue") or 0)

    conn = get_connection()
    try:
        pending = int(conn.execute(
            "SELECT COUNT(*) AS c FROM orders "
            "WHERE company_id = ? AND status = ?",
            (company_id, "已下单"),
        ).fetchone()["c"])
        has_inquiries = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='inquiries'"
        ).fetchone() is not None
        if has_inquiries:
            # created_at 默认 datetime('now','localtime')，与 today 同一时区
            new_inquiries = int(conn.execute(
                "SELECT COUNT(*) AS c FROM inquiries "
                "WHERE company_id = ? AND date(created_at) = ?",
                (company_id, today),
            ).fetchone()["c"])
        else:
            # 极旧库没有 inquiries 表：不猜数，返回 None 让前端显示「—」
            new_inquiries = None
    finally:
        conn.close()

    return {
        "date": today,
        "new_inquiries": new_inquiries,
        "overdue_followups": overdue,
        "pending_shipments": pending,
        "summary": _morning_brief_summary(company_id, today),
    }


def _morning_brief_summary(company_id: int, today: str) -> dict | None:
    """读 cron「早安简报」今天的产出；没有或静默则返回 null。"""
    try:
        from trade.api import cron as cron_api
    except Exception:
        return None

    jobs = []
    try:
        jobs = cron_api._load_active_jobs(company_id) or []
    except Exception:
        jobs = []

    # 无激活 job 时仍按标准名试一次（无 job_id 时 _find_cron_output 会返回 None）
    candidates = [j for j in jobs if _is_morning_brief_name(j.get("name") or "")]
    if not candidates:
        candidates = [{"name": "早安简报", "job_id": ""}]

    for job in candidates:
        name = job.get("name") or "早安简报"
        job_id = str(job.get("job_id") or "")
        try:
            output = cron_api._find_cron_output(name, today, job_id=job_id)
        except Exception:
            output = None
        if not output:
            continue
        try:
            if cron_api._is_silent_cron_output(output):
                continue
        except Exception:
            pass
        text = (output or "").strip()
        if not text:
            continue
        # 摘要行取前 400 字，避免把整篇 cron 产出塞进右栏
        preview = text if len(text) <= 400 else (text[:397] + "…")
        return {
            "text": preview,
            "source": "cron:早安简报",
            "generated_at": today,
        }
    return None


def _is_morning_brief_name(name: str) -> bool:
    """判断任务名是否早安简报（兼容 emoji / 英文别名）。"""
    n = (name or "").strip().lower()
    if "早安简报" in name:
        return True
    if "morning" in n and "brief" in n:
        return True
    return False
