"""SEC EDGAR 全文检索（工单 P2-2）：美国上市/申报主体的申报记录。

统一检索接口要求 UA 带联系邮箱；邮箱取自当前公司的 contact_email 或
`TRADE_CONTACT_EMAIL`（写在 `~/.hermes/.env`）。**不内置任何个人邮箱兜底**
（W15 O-8）：未配置或格式不合法时该层 skipped 并写明原因，不冒用他人身份
向 SEC 发请求。
"""

from __future__ import annotations

import os
import re

from trade.osint.sources.base import (
    Fetcher,
    SourceResult,
    TargetContext,
    error_result,
    fetch_json,
    quote,
    skipped,
)

NAME = "edgar"
LABEL = "SEC EDGAR 申报"
SEARCH = "https://efts.sec.gov/LATEST/search-index?q=%22{hint}%22"
# 简单格式校验（W15 O-16）：有 @、有域名点、无空白
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def _contact_email(ctx: TargetContext | None = None) -> str:
    """当前可用的联系邮箱（公司配置优先，其次环境变量）；无/非法返回空串。"""
    email = str(getattr(ctx, "contact_email", "") or "").strip()
    email = email or os.environ.get("TRADE_CONTACT_EMAIL", "").strip()
    return email if _EMAIL_RE.match(email) else ""


def _headers(ctx: TargetContext | None = None) -> dict[str, str]:
    """EDGAR 请求头；未配置合法联系邮箱时返回空 dict（调用方应 skipped）。"""
    email = _contact_email(ctx)
    if not email:
        return {}
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
    headers = _headers(ctx)
    if not headers:
        return skipped(
            NAME,
            "未配置合法的联系邮箱（TRADE_CONTACT_EMAIL），SEC 要求 UA 带联系邮箱",
        )

    url = SEARCH.format(hint=quote(hint))
    try:
        payload = fetch_json(url, fetch=fetch, headers=headers)
    except Exception as exc:  # noqa: BLE001
        return error_result(NAME, exc)
    if not isinstance(payload, dict):
        return error_result(NAME, code="parse_error", detail="EDGAR 无有效 JSON 响应")

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
