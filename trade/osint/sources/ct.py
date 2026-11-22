"""证书透明度日志（工单 P2-2）：子域名 + 首张证书时间。

主源 certspotter（免费、响应稳定）；crt.sh 作备用（实测对同一域名常返回 []，
只在前者失败/为空时尝试）。
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

NAME = "ct"
LABEL = "证书透明度（CT）"
CERTSPOTTER = (
    "https://api.certspotter.com/v1/issuances"
    "?domain={domain}&include_subdomains=true&expand=dns_names"
)
CRT_SH = "https://crt.sh/?q=%25.{domain}&output=json"


def _certspotter_headers() -> dict[str, str]:
    """certspotter 匿名有严格限流（实测 429）；配置 token 时带上。"""
    token = os.environ.get("CERTSPOTTER_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _clean_name(value: str) -> str:
    """小写并去掉通配符前缀。"""
    return str(value or "").strip().lower().lstrip("*.")


def run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult:
    """查询证书；无域名目标返回 skipped。"""
    if not ctx.domain:
        return skipped(NAME, "目标不含域名")

    domain = ctx.domain.lower()
    names: set[str] = set()
    earliest = ""
    count = 0

    primary_error = ""
    fallback_error = ""

    # 主源：certspotter（可配 CERTSPOTTER_TOKEN 提高配额）
    try:
        payload = fetch_json(
            CERTSPOTTER.format(domain=domain),
            fetch=fetch,
            headers=_certspotter_headers(),
        )
    except Exception as exc:  # noqa: BLE001 —— 主源失败走备用源
        payload = None
        primary_error = f"{type(exc).__name__}: {exc}"

    if isinstance(payload, list) and payload:
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            count += 1
            not_before = str(entry.get("not_before") or "")
            if not_before and (not earliest or not_before < earliest):
                earliest = not_before
            for raw in entry.get("dns_names") or []:
                name = _clean_name(raw)
                if name:
                    names.add(name)

    # 备用源：crt.sh
    if not names:
        try:
            fallback = fetch_json(CRT_SH.format(domain=quote(domain)), fetch=fetch)
        except Exception as exc:  # noqa: BLE001
            fallback = None
            fallback_error = f"{type(exc).__name__}: {exc}"
        if isinstance(fallback, list) and fallback:
            for entry in fallback:
                if not isinstance(entry, dict):
                    continue
                count += 1
                not_before = str(entry.get("not_before") or "")
                if not_before and (not earliest or not_before < earliest):
                    earliest = not_before
                for raw in str(entry.get("name_value") or "").splitlines():
                    name = _clean_name(raw)
                    if name:
                        names.add(name)

    if not names:
        if primary_error or fallback_error:
            detail = "；".join(filter(None, [
                f"certspotter {primary_error}" if primary_error else "",
                f"crt.sh {fallback_error}" if fallback_error else "",
            ]))
            return SourceResult(NAME, "error", error=f"CT 查询失败（{detail}）")
        return SourceResult(NAME, "miss", error="未查到证书记录")

    # 只保留本域的子域（crt.sh 会带回其它域的共享证书）
    bare_subdomains = sorted({
        name[: -len(domain) - 1]
        for name in names
        if name.endswith("." + domain)
    })

    facts = [{
        "text": (
            f"证书 {count} 张" + (f"，最早 {earliest}" if earliest else "")
            + (f"；子域名：{'、'.join(bare_subdomains[:8])}" if bare_subdomains else "")
        ),
        "url": f"https://crt.sh/?q={quote(domain)}",
    }]
    return SourceResult(
        NAME,
        "hit",
        facts=facts,
        data={
            "cert_count": count,
            "earliest": earliest or None,
            "subdomains": bare_subdomains,
            "dns_names": sorted(names),
        },
    )
