"""EU VIES 增值税号核验（工单 P2-2）。

只在目标文本里出现 VAT 号（如 `IE6388047V`）时才查；官方接口，无需 key。
"""

from __future__ import annotations

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

NAME = "vies"
LABEL = "EU VIES 增值税核验"
URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{cc}/vat/{num}"

# 2 位国别 + 2–12 位字母数字（各国长度不同，交给 VIES 判定）
_VAT_RE = re.compile(r"\b([A-Za-z]{2})([0-9A-Za-z]{2,12})\b")


def _extract_vat(target: str) -> tuple[str, str] | None:
    """从目标文本里提取 VAT 号；没有返回 None。"""
    for match in _VAT_RE.finditer(target.upper()):
        cc, num = match.group(1), match.group(2)
        # 国别码必须是真实 EU 成员（避免把 "HP123456" 之类当 VAT）
        if cc in _EU_COUNTRIES:
            return cc, num
    return None


_EU_COUNTRIES = frozenset({
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR",
    "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
    "SE", "SI", "SK", "XI",
})


def run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult:
    """核验 VAT；目标里没有 VAT 号返回 skipped。"""
    vat = _extract_vat(ctx.target)
    if not vat:
        return skipped(NAME, "目标中没有 EU VAT 号")

    cc, num = vat
    url = URL.format(cc=cc, num=quote(num))
    try:
        payload = fetch_json(url, fetch=fetch)
    except Exception as exc:  # noqa: BLE001
        return error_result(NAME, exc)
    if not isinstance(payload, dict):
        return error_result(NAME, code="parse_error", detail="VIES 无有效 JSON 响应")

    valid = bool(payload.get("isValid"))
    name = str(payload.get("name") or "").strip()
    address = " ".join(str(payload.get("address") or "").split())

    label = f"VAT {cc}{num}"
    if valid:
        detail = label + "：有效"
        if name:
            detail += f"；名称：{name}"
        if address:
            detail += f"；地址：{address}"
    else:
        detail = f"{label}：无效（{payload.get('userError') or 'VIES 判定无效'}）"

    return SourceResult(
        NAME,
        "hit",
        facts=[{
            "text": detail,
            "url": "https://ec.europa.eu/taxation_customs/vies/#/vat-validation",
        }],
        data={
            "vat": f"{cc}{num}",
            "valid": valid,
            "name": name,
            "address": address,
        },
    )
