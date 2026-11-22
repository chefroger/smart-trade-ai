"""被动 DNS / 子域名（工单 P2-2）。

HackerTarget 免费接口（约 50 次/天），返回 `子域名,IP` 的纯文本。
只做公开 DNS 数据整理，不做端口扫描或任何主动探测。
"""

from __future__ import annotations

from trade.osint.sources.base import (
    Fetcher,
    SourceResult,
    TargetContext,
    fetch_text,
    quote,
    skipped,
)

NAME = "pdns"
LABEL = "被动 DNS 子域名"
URL = "https://api.hackertarget.com/hostsearch/?q={domain}"


def run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult:
    """查子域名；无域名目标返回 skipped。"""
    if not ctx.domain:
        return skipped(NAME, "目标不含域名")

    domain = ctx.domain.lower()
    url = URL.format(domain=quote(domain))
    try:
        text = fetch_text(url, fetch=fetch)
    except Exception as exc:  # noqa: BLE001
        return SourceResult(NAME, "error", error=f"被动 DNS 查询失败：{exc}")
    if text is None:
        return SourceResult(NAME, "error", error="被动 DNS 无响应")
    if not text.strip():
        return SourceResult(NAME, "miss", error="未查到子域名记录")

    lowered = text.strip().lower()
    if lowered.startswith("error") or lowered.startswith("api count exceeded"):
        # HackerTarget 的配额提示也走 200，必须显式识别
        return SourceResult(NAME, "miss", error=f"被动 DNS 不可用：{text.strip()[:120]}")

    subdomains: list[str] = []
    ips: list[str] = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2 or not parts[0]:
            continue
        subdomains.append(parts[0])
        if parts[1] and parts[1] not in ips:
            ips.append(parts[1])

    if not subdomains:
        return SourceResult(NAME, "miss", error="未查到子域名记录")

    return SourceResult(
        NAME,
        "hit",
        facts=[{
            "text": (
                f"子域名 {len(subdomains)} 个："
                + "、".join(subdomains[:10])
                + (f"；IP：{'、'.join(ips[:5])}" if ips else "")
            ),
            "url": url,
        }],
        data={"subdomains": subdomains[:50], "ips": ips[:20]},
    )
