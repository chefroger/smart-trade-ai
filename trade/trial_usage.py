"""试用期价值小结的事件台账。

只记录**真实发生**的三类事件，不做事后估算（口径见
`trade-试用期方案-20261026.md` §B）：

- `draft`          生成了一版副驾草稿
- `inquiry`        保存了一轮对话（处理询盘/问答）
- `product_lookup` 真的检索到了产品库条目

事件写入失败只记日志，绝不影响主流程。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

KIND_DRAFT = "draft"
KIND_INQUIRY = "inquiry"
KIND_PRODUCT_LOOKUP = "product_lookup"


def record_event(kind: str, company_id: int | None) -> None:
    """记一条试用期事件；失败静默（旁路统计不能拖垮业务）。"""
    if not company_id:
        return
    try:
        from trade.database import get_connection

        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO trial_events (ts, company_id, kind) VALUES (?, ?, ?)",
                (time.time(), int(company_id), str(kind)),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.debug("试用期事件记录失败（不影响业务）: %s", e)


def summary(company_id: int | None, first_launch_at: str | None) -> dict | None:
    """统计试用起点以来的三类事件数；时间解析不了返回 None。"""
    if not first_launch_at:
        return None
    try:
        since = datetime.fromisoformat(first_launch_at).timestamp()
    except (TypeError, ValueError):
        return None
    try:
        from trade.database import get_connection

        conn = get_connection()
        try:
            if company_id:
                rows = conn.execute(
                    "SELECT kind, COUNT(*) FROM trial_events "
                    "WHERE company_id = ? AND ts >= ? GROUP BY kind",
                    (int(company_id), since),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT kind, COUNT(*) FROM trial_events "
                    "WHERE ts >= ? GROUP BY kind",
                    (since,),
                ).fetchall()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("试用期价值小结读取失败: %s", e)
        return None

    counts = {kind: int(n) for kind, n in rows}
    return {
        "drafts": counts.get(KIND_DRAFT, 0),
        "inquiries": counts.get(KIND_INQUIRY, 0),
        "product_lookups": counts.get(KIND_PRODUCT_LOOKUP, 0),
        "since": first_launch_at[:10],
    }
