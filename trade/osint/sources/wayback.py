"""Wayback Machine 首次快照（工单 P2-2）：网站第一次被存档的时间。

CDX 返回的是 JSON 行的数组（首行是表头）；按时间戳取最早一条。
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

NAME = "wayback"
LABEL = "Wayback 首次快照"
CDX = "https://web.archive.org/cdx/search/cdx?url={domain}&output=json&limit=10"


def run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult:
    """查询首次快照；无域名目标返回 skipped。"""
    if not ctx.domain:
        return skipped(NAME, "目标不含域名")

    domain = ctx.domain.lower()
    try:
        payload = fetch_json(CDX.format(domain=quote(domain)), fetch=fetch)
    except Exception as exc:  # noqa: BLE001
        return error_result(NAME, exc)
    if payload is None:
        return error_result(NAME, code="parse_error", detail="Wayback 无响应或返回非 JSON")
    if not isinstance(payload, list):
        return error_result(NAME, code="parse_error", detail="Wayback 返回非列表结构")
    if len(payload) < 2:
        return SourceResult(NAME, "miss", error="Wayback 无快照")

    rows = [row for row in payload[1:] if isinstance(row, list) and len(row) >= 3]
    if not rows:
        return SourceResult(NAME, "miss", error="Wayback 无快照")

    first = min(rows, key=lambda row: str(row[1]))
    timestamp = str(first[1])
    original = str(first[2])
    snapshot = f"https://web.archive.org/web/{timestamp}/{original}"

    # 20261015081506 → 2026-10-15 08:15:06（UTC）
    readable = (
        f"{timestamp[0:4]}-{timestamp[4:6]}-{timestamp[6:8]}"
        f" {timestamp[8:10]}:{timestamp[10:12]}:{timestamp[12:14]}"
        if len(timestamp) >= 14 else timestamp
    )

    return SourceResult(
        NAME,
        "hit",
        facts=[{"text": f"首次快照：{readable}（UTC）", "url": snapshot}],
        data={
            "first_snapshot": timestamp,
            "first_url": original,
            "snapshot_url": snapshot,
            "snapshot_count": len(rows),
        },
    )
