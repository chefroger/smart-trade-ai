"""GLEIF LEI 登记（工单 P2-2）：法人实体标识、法定名称、注册地。

仅适用于公司/法人；个人目标返回 skipped。公开数据（CC0），无需 key。
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

NAME = "gleif"
LABEL = "GLEIF LEI 登记"
URL = "https://api.gleif.org/api/v1/lei-records?filter%5Bentity.legalName%5D={name}&page%5Bsize%5D=5"


def _hint(ctx: TargetContext) -> str:
    """公司名优先；域名目标用域名主干。"""
    if ctx.company_name:
        return ctx.company_name
    if ctx.domain:
        return ctx.domain.split(".")[0]
    return ""


def run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult:
    """查 LEI 记录。"""
    hint = _hint(ctx).strip()
    if not hint or ctx.target_type == "person":
        return skipped(NAME, "没有可用于 GLEIF 的公司名")

    url = URL.format(name=quote(hint))
    try:
        payload = fetch_json(url, fetch=fetch)
    except Exception as exc:  # noqa: BLE001
        return error_result(NAME, exc)
    if payload is None or not isinstance(payload, dict):
        return error_result(NAME, code="parse_error", detail="GLEIF 无有效 JSON 响应")
    records = payload.get("data")
    if not records:
        return SourceResult(NAME, "miss", error="GLEIF 无匹配记录")

    # 过滤接口是模糊匹配：优先取名称里真的包含查询词的那条
    hint_lower = hint.lower()
    chosen = None
    for record in records:
        attrs = (record or {}).get("attributes") or {}
        name = ((attrs.get("entity") or {}).get("legalName") or {}).get("name") or ""
        if hint_lower in name.lower():
            chosen = record
            break
    if chosen is None:
        return SourceResult(NAME, "miss", error="GLEIF 结果与目标名称不吻合，未采用")

    attrs = chosen.get("attributes") or {}
    entity = attrs.get("entity") or {}
    name = (entity.get("legalName") or {}).get("name") or ""
    lei = chosen.get("id") or ""
    country = (entity.get("legalAddress") or {}).get("country") or ""
    status = (attrs.get("registration") or {}).get("status") or ""
    record_url = f"https://search.gleif.org/#/record/{lei}" if lei else url

    parts = [f"法定名称：{name}"]
    if lei:
        parts.append(f"LEI：{lei}")
    if country:
        parts.append(f"注册地：{country}")
    if status:
        parts.append(f"状态：{status}")
    return SourceResult(
        NAME,
        "hit",
        facts=[{"text": "，".join(parts), "url": record_url}],
        data={"lei": lei, "legal_name": name, "country": country, "status": status},
    )
