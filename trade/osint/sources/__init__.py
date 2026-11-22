"""公开来源层（工单 P2-2）。

每个来源是独立模块，统一接口：

    run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult

- 不抛异常：失败在 SourceResult.status/error 里如实返回
- 不下载大文件、不绕登录/验证码/付费墙
- `TRADE_OSINT_SOURCES=off` 可整体关闭（默认开启）

第一批：RDAP、证书透明度、Wayback、GitHub。
"""

from __future__ import annotations

import os

from trade.osint.sources import (
    ct,
    edgar,
    gdelt,
    github,
    gleif,
    pdns,
    rdap,
    us_states,
    vies,
    wayback,
)
from trade.osint.sources.base import Fetcher, SourceResult, TargetContext

SOURCES = (rdap, ct, wayback, pdns, github, gleif, vies, us_states, edgar, gdelt)
SOURCE_LABELS = {module.NAME: module.LABEL for module in SOURCES}


def sources_enabled() -> bool:
    """公开来源总开关（默认开）。"""
    return os.environ.get("TRADE_OSINT_SOURCES", "on").strip().casefold() not in (
        "off", "0", "false", "no",
    )


def source_applies(name: str, ctx: TargetContext) -> bool:
    """该来源是否适用于本次目标（避免报告里出现无意义的 skipped）。"""
    if name in {"rdap", "ct", "wayback", "pdns"}:
        return bool(ctx.domain)
    if name in {"gleif", "us_states", "edgar"}:
        # 法人登记类来源：个人目标不适用
        return ctx.target_type != "person" and bool(ctx.company_name or ctx.domain)
    if name == "vies":
        return vies._extract_vat(ctx.target) is not None
    if name == "github":
        return bool(
            ctx.github_username or ctx.person_name or ctx.company_name or ctx.domain
        )
    if name == "gdelt":
        return bool(ctx.person_name or ctx.company_name or ctx.domain)
    return True


__all__ = [
    "Fetcher",
    "SourceResult",
    "TargetContext",
    "SOURCES",
    "SOURCE_LABELS",
    "source_applies",
    "sources_enabled",
]
