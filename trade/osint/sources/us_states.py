"""美国州公司登记（工单 P2-2）：纽约州 + 科罗拉多州官方开放数据。

其他州没有统一 API（多数只有验证码网页），只生成官方查询链接交给人工。
Socrata SoQL 用 `upper(name) like '%…%'` 精确过滤，避免把同名公司挂错。
"""

from __future__ import annotations

import urllib.parse

from trade.osint.sources.base import (
    Fetcher,
    SourceResult,
    TargetContext,
    fetch_json,
    skipped,
)

NAME = "us_states"
LABEL = "美国州公司登记"
NY_URL = "https://data.ny.gov/resource/n9v6-gdp6.json?$where={where}&$limit=5"
CO_URL = "https://data.colorado.gov/resource/4ykn-tg5h.json?$where={where}&$limit=5"
NY_PORTAL = "https://apps.dos.ny.gov/publicInquiry/"
CO_PORTAL = "https://www.coloradosos.gov/biz/BusinessEntityCriteriaExt.do"


def _hint(ctx: TargetContext) -> str:
    if ctx.company_name:
        return ctx.company_name
    if ctx.domain:
        return ctx.domain.split(".")[0]
    return ""


def _where(column: str, hint: str) -> str:
    """构造 SoQL 条件并编码（单引号转义）。"""
    escaped = hint.upper().replace("'", "''")
    return urllib.parse.quote(f"upper({column}) like '%{escaped}%'", safe="")


def _ny_rows(rows: list[dict], hint: str) -> list[dict]:
    return [row for row in rows
            if hint.lower() in str(row.get("current_entity_name") or "").lower()]


def _co_rows(rows: list[dict], hint: str) -> list[dict]:
    return [row for row in rows
            if hint.lower() in str(row.get("entityname") or "").lower()]


def run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult:
    """查 NY/CO 登记。"""
    hint = _hint(ctx).strip()
    if not hint or ctx.target_type == "person":
        return skipped(NAME, "没有可用于州登记的公司名")

    facts: list[dict] = []
    data: dict = {}
    errors: list[str] = []
    ny = None
    co = None

    ny_exc: BaseException | None = None
    co_exc: BaseException | None = None

    # 纽约州（含 DOS 流程地址：注册代理/邮寄地址，不是经营地证明）
    ny_url = NY_URL.format(where=_where("current_entity_name", hint))
    try:
        ny = fetch_json(ny_url, fetch=fetch)
    except Exception as exc:  # noqa: BLE001
        ny = None
        ny_exc = exc
        errors.append(f"NY {type(exc).__name__}")
    for row in (_ny_rows(ny or [], hint) if isinstance(ny, list) else [])[:3]:
        name = str(row.get("current_entity_name") or "")
        parts = [f"纽约州登记：{name}"]
        if row.get("dos_id"):
            parts.append(f"DOS ID {row['dos_id']}")
        if row.get("initial_dos_filing_date"):
            parts.append(f"成立 {str(row['initial_dos_filing_date'])[:10]}")
        if row.get("county"):
            parts.append(f"{row['county']} 县")
        addr = " ".join(str(row.get(key) or "").strip() for key in (
            "dos_process_address_1", "dos_process_city",
            "dos_process_state", "dos_process_zip",
        )).strip()
        if addr:
            parts.append(f"流程地址 {addr}（注册代理/邮寄地址，非经营地证明）")
        facts.append({"text": "，".join(parts), "url": NY_PORTAL})
    if ny:
        data["ny"] = _ny_rows(ny, hint)[:3]

    # 科罗拉多州
    co_url = CO_URL.format(where=_where("entityname", hint))
    try:
        co = fetch_json(co_url, fetch=fetch)
    except Exception as exc:  # noqa: BLE001
        co = None
        co_exc = exc
        errors.append(f"CO {type(exc).__name__}")
    for row in (_co_rows(co or [], hint) if isinstance(co, list) else [])[:3]:
        parts = [f"科罗拉多州登记：{row.get('entityname') or ''}"]
        if row.get("entityid"):
            parts.append(f"ID {row['entityid']}")
        if row.get("entityformdate"):
            parts.append(f"成立 {str(row['entityformdate'])[:10]}")
        if row.get("entitystatus"):
            parts.append(f"状态 {row['entitystatus']}")
        addr = " ".join(str(row.get(key) or "").strip() for key in (
            "principaladdress1", "principalcity", "principalstate",
        )).strip()
        if addr:
            parts.append(f"地址 {addr}（登记地址）")
        facts.append({"text": "，".join(parts), "url": CO_PORTAL})
    if co:
        data["co"] = _co_rows(co, hint)[:3]

    if facts:
        return SourceResult(NAME, "hit", facts=facts, data=data)
    if errors and ny is None and co is None:
        from trade.osint.sources.base import error_result

        return error_result(NAME, co_exc or ny_exc)
    return SourceResult(NAME, "miss", error="NY/CO 未查到匹配登记")
