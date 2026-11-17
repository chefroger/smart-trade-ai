"""今日简报 API（W9）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from trade.api.deps import require_company
from trade.brief import get_today_brief

router = APIRouter(tags=["brief"])


@router.get("/brief/today")
def brief_today(cid: int = Depends(require_company)):
    """返回今日简报 KPI 与早安摘要。"""
    return get_today_brief(cid)
