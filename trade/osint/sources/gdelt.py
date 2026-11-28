"""GDELT 新闻检索（工单 P2-2）：公开新闻标题、来源与日期。

接口偏慢且会限流（实测 429），超时 20 秒；失败如实标注，不影响其它来源。
"""

from __future__ import annotations

from trade.osint.sources.base import (
    Fetcher,
    SourceResult,
    TargetContext,
    error_result,
    fetch_json,
    quote,
    skipped,
)

NAME = "gdelt"
LABEL = "GDELT 新闻"
URL = (
    "https://api.gdeltproject.org/api/v2/doc/doc"
    "?query=%22{hint}%22&mode=artlist&format=json&maxrecords=8&timespan=1y"
)


def _hint(ctx: TargetContext) -> str:
    if ctx.company_name:
        return ctx.company_name
    if ctx.person_name:
        return ctx.person_name
    if ctx.domain:
        return ctx.domain.split(".")[0]
    return ""


def run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult:
    """查新闻；无线索返回 skipped。"""
    hint = _hint(ctx).strip()
    if not hint:
        return skipped(NAME, "没有可检索的名称")

    url = URL.format(hint=quote(hint))
    try:
        payload = fetch_json(url, fetch=fetch, timeout=20)
    except Exception as exc:  # noqa: BLE001
        return error_result(NAME, exc)
    if not isinstance(payload, dict):
        return error_result(NAME, code="parse_error", detail="GDELT 无有效 JSON 响应")

    articles = payload.get("articles") or []
    if not articles:
        return SourceResult(NAME, "miss", error="GDELT 无相关新闻")

    facts: list[dict] = []
    items: list[dict] = []
    for article in articles[:5]:
        title = str(article.get("title") or "").strip()
        domain = str(article.get("domain") or "").strip()
        seen = str(article.get("seendate") or "")[:8]
        link = str(article.get("url") or "")
        if not title:
            continue
        meta = "、".join(part for part in (domain, seen) if part)
        facts.append({"text": f"新闻：{title}（{meta}）", "url": link})
        items.append({"title": title, "domain": domain, "seendate": seen, "url": link})

    return SourceResult(NAME, "hit", facts=facts, data={"articles": items})
