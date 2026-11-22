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
import re

from trade.database import get_connection

logger = logging.getLogger(__name__)

# 目标前缀（与 orchestrator 的白名单保持一致）
_PREFIX_RE = re.compile(
    r"^(?:person|company|domain|username|人名|公司|企业|域名|网址)\s*:\s*",
    re.IGNORECASE,
)

# 单条事实的字段名白名单：只接受这些键，避免模型把整段话塞进 field
MAX_FIELD_LEN = 40
MAX_VALUE_LEN = 500
MAX_SOURCE_LEN = 300


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
    value: str,
    *,
    source_url: str = "",
    source_name: str = "",
    note: str = "",
) -> dict | None:
    """登记一条事实（同公司 + 同 subject + 同字段 + 同来源 → 覆盖更新）。

    Returns:
        {"id", "subject", "field", "value", ...}；参数不合法或写入失败返回 None。
    """
    subject = normalize_subject(target)
    field = str(field or "").strip()[:MAX_FIELD_LEN]
    value = str(value if value is not None else "").strip()[:MAX_VALUE_LEN]
    if not subject or not field or not value:
        return None
    source_url = str(source_url or "").strip()[:MAX_SOURCE_LEN]
    source_name = str(source_name or "").strip()[:MAX_SOURCE_LEN]
    note = str(note or "").strip()[:MAX_VALUE_LEN]

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO osint_facts(company_id, subject, subject_raw, field, value,"
            " source_url, source_name, note) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(company_id, subject, field, value, source_url)"
            " DO UPDATE SET observed_at = datetime('now','localtime'),"
            " source_name = excluded.source_name, note = excluded.note",
            (company_id, subject, str(target or "").strip()[:200], field, value,
             source_url, source_name, note),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, subject, field, value, source_url, source_name, note,"
            " observed_at FROM osint_facts"
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
        if target:
            subject = normalize_subject(target)
            rows = conn.execute(
                "SELECT id, subject, subject_raw, field, value, source_url, source_name,"
                " note, observed_at FROM osint_facts"
                " WHERE company_id=? AND subject=? ORDER BY field, id DESC LIMIT ?",
                (company_id, subject, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, subject, subject_raw, field, value, source_url, source_name,"
                " note, observed_at FROM osint_facts"
                " WHERE company_id=? ORDER BY subject, field, id DESC LIMIT ?",
                (company_id, limit),
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def known_facts(company_id: int, target: str | None = None) -> dict:
    """按字段汇总已知事实；同一字段有多个不同值时标 `conflict: true`。

    Returns:
        {field: {"values": [...], "conflict": bool, "sources": [...]}}
    """
    rows = list_facts(company_id, target)
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
