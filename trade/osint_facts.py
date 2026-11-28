"""背调事实库（2026-11-22）：把模型查到的关键事实结构化落盘，供下次复用。

## 为什么需要它

同一目标跑两次背调，结果会不一样 —— 差的不是机器判定层（它是确定性的），而是
**模型自由检索的那部分**：企查查/爱企查/天眼查全都有反爬，第一次撞开了、第二次被
挡，于是注册资本、法定代表人这类字段第二次就成了「暂未找到」。

模型查到的信息原本只存在聊天文本里，没有结构化落点，下次只能从零再赌一次反爬。
本模块把「字段 / 值 / 来源 URL / 查询时间」存下来：

- 查到就存一次（`save_fact`）→ 之后每次同目标都能复用
- 同一字段出现**不同值** → 标记为冲突（`known_facts` 里带 `conflict: true`），
  报告应并列写出两个值而不是挑一个

## 归属与隔离

所有读写都带 `company_id`：事实属于"本公司的背调档案"，跨公司不可见。
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta

from trade.database import get_connection

logger = logging.getLogger(__name__)

# 目标前缀（与 orchestrator 的白名单保持一致）
_PREFIX_RE = re.compile(
    r"^(?:person|company|domain|username|人名|公司|企业|域名|网址)\s*[:：]\s*",
    re.IGNORECASE,
)

# 单条事实的字段名白名单：只接受这些键，避免模型把整段话塞进 field
MAX_FIELD_LEN = 40
MAX_VALUE_LEN = 500
MAX_SOURCE_LEN = 300

# M8：合法事实状态与否定事实默认复用天数（默认 3 天，可通过环境变量调整）
VALID_FACT_STATUSES = frozenset({"found", "not_found", "failed"})
DEFAULT_NOT_FOUND_TTL_DAYS = 3


def not_found_ttl_days() -> int:
    """返回「已查询未检索到」事实的默认复用天数（环境变量 TRADE_OSINT_NOT_FOUND_TTL_DAYS，默认 3 天）。"""
    raw = os.environ.get("TRADE_OSINT_NOT_FOUND_TTL_DAYS", "").strip()
    if raw:
        try:
            val = int(raw)
            if val >= 0:
                return val
        except ValueError:
            pass
    return DEFAULT_NOT_FOUND_TTL_DAYS


def _ensure_status_column(conn) -> None:
    """幂等确保 osint_facts.status 列存在（兼容跳过 init_db 的老库测试）。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(osint_facts)")}
    if cols and "status" not in cols:
        conn.execute("ALTER TABLE osint_facts ADD COLUMN status TEXT NOT NULL DEFAULT 'found'")


def normalize_subject(target: str) -> str:
    """把目标归一成事实库的 subject 键。

    - 去掉类型前缀（`company:` / `公司:` / `domain:` …）
    - 域名统一小写并去 www.
    - 公司名去掉首尾空白与内部连续空格（大小写保留：中文公司名大小写无意义，
      英文公司名大小写有，混着归一会把同一家公司拆成两个 subject）
    """
    text = str(target or "").strip()
    text = _PREFIX_RE.sub("", text).strip()
    if not text:
        return ""
    if "." in text and " " not in text:
        return text.lower().removeprefix("www.")
    return re.sub(r"\s+", " ", text)


def save_fact(
    company_id: int,
    target: str,
    field: str,
    value: str = "",
    *,
    source_url: str = "",
    source_name: str = "",
    note: str = "",
    verified: bool = False,
    status: str = "found",
) -> dict | None:
    """登记一条事实（同公司 + 同 subject + 同字段 + 同值 + 同来源 → 覆盖更新）。

    Args:
        status: "found"（已检索到，默认，value 必填）| "not_found"（已查询未检索到，value 存空串）
                | "failed"（查询失败，value 存空串）

    verified=True 表示 source_url 在本轮已完成工具证据里出现过（P1-D）。
    未核实的事实仍保存，但 known_facts 不会返回它。

    Returns:
        {"id", "subject", "field", "value", "status", ...}；参数不合法或写入失败返回 None。
    """
    subject = normalize_subject(target)
    field = str(field or "").strip()[:MAX_FIELD_LEN]
    norm_status = str(status or "found").strip().lower()
    if norm_status not in VALID_FACT_STATUSES:
        norm_status = "found"  # 非法状态回退默认 found

    if norm_status == "found":
        value = str(value if value is not None else "").strip()[:MAX_VALUE_LEN]
        if not subject or not field or not value:
            return None
    else:
        # not_found / failed：value 统一存空字符串，避免与真实值混淆
        value = ""
        if not subject or not field:
            return None

    source_url = str(source_url or "").strip()[:MAX_SOURCE_LEN]
    source_name = str(source_name or "").strip()[:MAX_SOURCE_LEN]
    note = str(note or "").strip()[:MAX_VALUE_LEN]
    verified_flag = 1 if (verified and norm_status == "found") else 0

    conn = get_connection()
    try:
        _ensure_status_column(conn)
        conn.execute(
            "INSERT INTO osint_facts(company_id, subject, subject_raw, field, value,"
            " source_url, source_name, note, verified, status) VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(company_id, subject, field, value, source_url)"
            " DO UPDATE SET observed_at = datetime('now','localtime'),"
            " source_name = excluded.source_name, note = excluded.note,"
            " status = excluded.status,"
            # 一旦核实过就不降级：同一行后续用无证据的保存覆盖时保持 1
            " verified = CASE WHEN osint_facts.verified = 1 OR excluded.verified = 1"
            " THEN 1 ELSE 0 END",
            (company_id, subject, str(target or "").strip()[:200], field, value,
             source_url, source_name, note, verified_flag, norm_status),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, subject, field, value, source_url, source_name, note,"
            " verified, status, observed_at FROM osint_facts"
            " WHERE company_id=? AND subject=? AND field=? AND value=? AND source_url=?"
            " ORDER BY id DESC LIMIT 1",
            (company_id, subject, field, value, source_url),
        ).fetchone()
    except Exception as exc:  # noqa: BLE001 —— 事实库是增强项，失败不阻断背调
        logger.warning("osint_facts 写入失败：%s", exc)
        return None
    finally:
        conn.close()
    return dict(row) if row else None


def list_facts(
    company_id: int,
    target: str | None = None,
    *,
    limit: int = 200,
) -> list[dict]:
    """列出本公司的已知事实；给了 target 就只列该 subject 的。"""
    limit = max(1, min(int(limit), 1000))
    conn = get_connection()
    try:
        _ensure_status_column(conn)
        if target:
            subject = normalize_subject(target)
            rows = conn.execute(
                "SELECT id, subject, subject_raw, field, value, source_url, source_name,"
                " note, verified, status, observed_at FROM osint_facts"
                " WHERE company_id=? AND subject=? ORDER BY field, id DESC LIMIT ?",
                (company_id, subject, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, subject, subject_raw, field, value, source_url, source_name,"
                " note, verified, status, observed_at FROM osint_facts"
                " WHERE company_id=? ORDER BY subject, field, id DESC LIMIT ?",
                (company_id, limit),
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _group(rows: list[dict]) -> dict:
    """把事实行按字段汇总（known / unverified 共用）。"""
    grouped: dict[str, dict] = {}
    for row in rows:
        field = row["field"]
        bucket = grouped.setdefault(
            field, {"values": [], "conflict": False, "sources": [], "subjects": []})
        if row["value"] not in bucket["values"]:
            bucket["values"].append(row["value"])
        src = {"url": row.get("source_url") or "", "name": row.get("source_name") or "",
               "observed_at": row.get("observed_at") or ""}
        if src not in bucket["sources"]:
            bucket["sources"].append(src)
        if row.get("subject") and row["subject"] not in bucket["subjects"]:
            bucket["subjects"].append(row["subject"])
    for bucket in grouped.values():
        bucket["conflict"] = len(bucket["values"]) > 1
    return grouped


def known_facts(company_id: int, target: str | None = None) -> dict:
    """按字段汇总**已核实**的事实（仅 status='found' 且 verified=1）；同一字段多值标 `conflict: true`。

    2026-11-23 审计 P1-D：只返回 verified=1 —— 模型自报、来源 URL 没在
    本轮工具证据里出现过的事实不算「已核实」，不能下次直接复用。

    Returns:
        {field: {"values": [...], "conflict": bool, "sources": [...]}}
    """
    rows = [
        row for row in list_facts(company_id, target)
        if (row.get("status") or "found") == "found" and int(row.get("verified") or 0)
    ]
    return _group(rows)


def unverified_facts(company_id: int, target: str | None = None) -> dict:
    """未核实事实（仅 status='found' 且 verified=0，单独列出，报告应注明「已检索到（未核实）」）。"""
    rows = [
        row for row in list_facts(company_id, target)
        if (row.get("status") or "found") == "found" and not int(row.get("verified") or 0)
    ]
    grouped = _group(rows)
    for bucket in grouped.values():
        bucket["note"] = "上次未能核实"
    return grouped


def not_found_facts(
    company_id: int,
    target: str | None = None,
    *,
    max_age_days: int | None = None,
    now: datetime | None = None,
) -> dict:
    """返回 N 天内「已查询未检索到」（status='not_found'）的字段，供下次背调沿用或按需重查。

    规则：
      - 若同一字段已有 status='found' 的记录（无论是否已核实），则该字段不再出现在 not_found_facts
        中（报告优先显示 found，同时保留历史行）；
      - 超过 max_age_days（默认 3 天）的否定记录不再推荐沿用。
    """
    ttl = not_found_ttl_days() if max_age_days is None else max(0, int(max_age_days))
    ref_now = now or datetime.now()
    cutoff = ref_now - timedelta(days=ttl)

    all_rows = list_facts(company_id, target)
    found_fields = {
        row["field"]
        for row in all_rows
        if (row.get("status") or "found") == "found" and str(row.get("value") or "").strip()
    }

    grouped: dict[str, dict] = {}
    for row in all_rows:
        if (row.get("status") or "found") != "not_found":
            continue
        field = row["field"]
        # 同一字段已有 found 值时优先展示 found，历史 not_found 行仍留在表内
        if field in found_fields:
            continue
        obs_str = str(row.get("observed_at") or "").strip()
        if obs_str:
            try:
                obs_dt = datetime.fromisoformat(obs_str.replace("Z", "+00:00")).replace(tzinfo=None)
                if obs_dt < cutoff:
                    continue  # 超过 TTL 天数，不再作为近期未检索到提示
            except ValueError:
                pass
        bucket = grouped.setdefault(
            field,
            {
                "status": "not_found",
                "label": "已查询未检索到",
                "sources": [],
                "observed_at": obs_str,
                "note": row.get("note") or "",
                "hint": f"近 {ttl} 天内已查询未检索到；如需重查可以重查，否则直接沿用",
            },
        )
        src = {
            "url": row.get("source_url") or "",
            "name": row.get("source_name") or "",
            "observed_at": obs_str,
        }
        if src not in bucket["sources"]:
            bucket["sources"].append(src)
        if obs_str and (not bucket["observed_at"] or obs_str > bucket["observed_at"]):
            bucket["observed_at"] = obs_str
    return grouped


def conflict_fields(company_id: int, target: str | None = None) -> list[str]:
    """只返回有冲突的字段名（报告里应并列写出这些字段的多个值）。"""
    return [f for f, b in known_facts(company_id, target).items() if b.get("conflict")]


def delete_facts(company_id: int, target: str) -> int:
    """删除某目标的全部事实（目标查错了、或用户要求清掉重来）。"""
    subject = normalize_subject(target)
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM osint_facts WHERE company_id=? AND subject=?", (company_id, subject))
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()
