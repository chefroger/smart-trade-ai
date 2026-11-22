"""SEC EDGAR 全文检索（工单 P2-2）：美国上市/申报主体的申报记录。

统一检索接口要求 UA 带联系邮箱；邮箱取自 `TRADE_CONTACT_EMAIL`，
未配置时用占位地址（SEC 可能拒绝，如实返回错误）。
"""

from __future__ import annotations

import os

from trade.osint.sources.base import (
    Fetcher,
    SourceResult,
    TargetContext,
    fetch_json,
    quote,
    skipped,
)

NAME = "edgar"
LABEL = "SEC EDGAR 申报"
SEARCH = "https://efts.sec.gov/LATEST/search-index?q=%22{hint}%22"


def _headers() -> dict[str, str]:
    email = os.environ.get("TRADE_CONTACT_EMAIL", "").strip() or "support@smart-trade-ai.example"
    return {
        "User-Agent": f"Trade-AI/1.0 ({email})",
        "Accept": "application/json",
    }


def _hint(ctx: TargetContext) -> str:
    if ctx.company_name:
        return ctx.company_name
    if ctx.domain:
        return ctx.domain.split(".")[0]
    return ""


def run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult:
    """查 SEC 申报；个人目标或无公司线索返回 skipped。"""
    hint = _hint(ctx).strip()
    if not hint or ctx.target_type == "person":
        return skipped(NAME, "没有可用于 EDGAR 的公司名")

    url = SEARCH.format(hint=quote(hint))
    try:
        payload = fetch_json(url, fetch=fetch, headers=_headers())
    except Exception as exc:  # noqa: BLE001
        return SourceResult(NAME, "error", error=f"EDGAR 查询失败：{exc}")
    if not isinstance(payload, dict):
        return SourceResult(NAME, "miss", error="EDGAR 无有效响应")

    hits = ((payload.get("hits") or {}).get("hits")) or []
    if not hits:
        return SourceResult(NAME, "miss", error="EDGAR 无申报记录")

    facts: list[dict] = []
    filings: list[dict] = []
    for hit in hits[:3]:
        source = hit.get("_source") or {}
        names = source.get("display_names") or []
        name = str(names[0]) if names else ""
        form = str(source.get("form") or "")
        filed = str(source.get("file_date") or "")
        fact_text = " ".join(part for part in (form, filed, name) if part)
        if fact_text:
            facts.append({"text": f"SEC 申报：{fact_text}", "url": url})
            filings.append({"form": form, "file_date": filed, "name": name})

    total = ((payload.get("hits") or {}).get("total") or {}).get("value")
    return SourceResult(
        NAME,
        "hit",
        facts=facts,
        data={"total": total, "filings": filings},
    )
