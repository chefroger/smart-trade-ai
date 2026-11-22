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

from trade.osint.sources import ct, github, rdap, wayback
from trade.osint.sources.base import Fetcher, SourceResult, TargetContext

SOURCES = (rdap, ct, wayback, github)
SOURCE_LABELS = {module.NAME: module.LABEL for module in SOURCES}


def sources_enabled() -> bool:
    """公开来源总开关（默认开）。"""
    return os.environ.get("TRADE_OSINT_SOURCES", "on").strip().casefold() not in (
        "off", "0", "false", "no",
    )


__all__ = [
    "Fetcher",
    "SourceResult",
    "TargetContext",
    "SOURCES",
    "SOURCE_LABELS",
    "sources_enabled",
]
