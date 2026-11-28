"""RDAP 域名注册信息（工单 P2-2，替代脆弱的 43 端口 WHOIS）。

端点：https://rdap.org/domain/{domain}（IANA bootstrap 重定向到对应注册局）。
只取日期、注册商、NS —— GDPR 之后注册人信息普遍脱敏，不做无意义的猜测。
"""

from __future__ import annotations

from typing import Any

from trade.osint.sources.base import (
    Fetcher,
    SourceResult,
    TargetContext,
    error_result,
    fetch_json,
    skipped,
)

NAME = "rdap"
LABEL = "RDAP 域名注册"
URL = "https://rdap.org/domain/{domain}"


def _registrar(payload: dict[str, Any]) -> str:
    """从 RDAP entities 里取 registrar 的 fn 字段。"""
    for entity in payload.get("entities") or []:
        roles = entity.get("roles") or []
        if "registrar" not in roles:
            continue
        vcard = entity.get("vcardArray") or []
        if len(vcard) < 2 or not isinstance(vcard[1], list):
            continue
        for item in vcard[1]:
            if isinstance(item, list) and len(item) >= 4 and item[0] == "fn":
                return str(item[3] or "").strip()
    return ""


def run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult:
    """查询域名注册信息；无域名目标返回 skipped。"""
    if not ctx.domain:
        return skipped(NAME, "目标不含域名")

    url = URL.format(domain=ctx.domain)
    try:
        payload = fetch_json(url, fetch=fetch)
    except Exception as exc:  # noqa: BLE001 —— 单来源失败不影响其它来源
        return error_result(NAME, exc)
    if payload is None:
        return error_result(NAME, code="parse_error", detail="RDAP 无响应或返回非 JSON")
    if not isinstance(payload, dict):
        # 返回非 dict 说明响应结构异常，属于解析失败 error，不可误报 miss
        return error_result(NAME, code="parse_error", detail=f"unexpected type {type(payload).__name__}")

    events = {
        str(event.get("eventAction") or "").strip().lower(): event.get("eventDate")
        for event in payload.get("events") or []
        if isinstance(event, dict)
    }
    creation = events.get("registration")
    expiry = events.get("expiration")
    nameservers = [
        str(ns.get("ldhName") or "").strip()
        for ns in payload.get("nameservers") or []
        if isinstance(ns, dict) and ns.get("ldhName")
    ]
    registrar = _registrar(payload)

    if not creation and not expiry and not nameservers:
        return SourceResult(NAME, "miss", error="RDAP 未返回注册信息")

    facts: list[dict] = []
    if creation:
        facts.append({"text": f"注册时间：{creation}", "url": url})
    if expiry:
        facts.append({"text": f"到期时间：{expiry}", "url": url})
    if registrar:
        facts.append({"text": f"注册商：{registrar}", "url": url})
    if nameservers:
        facts.append({
            "text": "NS：" + "、".join(nameservers[:4]),
            "url": url,
        })

    return SourceResult(
        NAME,
        "hit",
        facts=facts,
        data={
            "creation_date": creation,
            "expiry_date": expiry,
            "registrar": registrar,
            "nameservers": nameservers,
        },
    )
