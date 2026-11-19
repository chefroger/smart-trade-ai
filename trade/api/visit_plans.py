"""验厂计划 API（s5–s7）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from trade import visit_plan as visit_mod
from trade.api.deps import require_company

router = APIRouter(tags=["visit-plans"])


class VisitPlanBody(BaseModel):
    customer_id: Any = None
    title: Any = None
    visit_date: Any = None
    days: Any = None
    location: Any = None
    payload: Any = None


def _int_or_none(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _days_or_400(v):
    """天数必须是整数；非法值返回 400，而不是让 int() 抛成 500。"""
    if v in (None, ""):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="天数必须是整数")
    if n < 1:
        raise HTTPException(status_code=400, detail="天数至少为 1")
    return n


@router.get("/visit-plans")
def list_visit_plans(cid: int = Depends(require_company)):
    return visit_mod.list_plans(cid)


@router.get("/visit-plans/suggest")
def suggest_visit_draft(customer_id: int | None = None, cid: int = Depends(require_company)):
    """按客户国家生成验厂建议（出发前/现场卫生安全/礼仪禁忌），不写库。"""
    return visit_mod.suggest_draft(cid, customer_id)


@router.post("/visit-plans")
def create_visit_plan(body: VisitPlanBody, cid: int = Depends(require_company)):
    payload = body.payload if isinstance(body.payload, dict) else {}
    plan_id = visit_mod.create_plan(
        cid,
        customer_id=_int_or_none(body.customer_id),
        title=str(body.title or ""),
        visit_date=str(body.visit_date or ""),
        days=_days_or_400(body.days) or 1,
        location=str(body.location or ""),
        payload=payload,
    )
    return visit_mod.get_plan(plan_id, company_id=cid)


@router.get("/visit-plans/{plan_id}")
def get_visit_plan(plan_id: int, cid: int = Depends(require_company)):
    plan = visit_mod.get_plan(plan_id, company_id=cid)
    if not plan:
        raise HTTPException(status_code=404, detail="验厂计划不存在")
    return plan


@router.put("/visit-plans/{plan_id}")
def update_visit_plan(plan_id: int, body: VisitPlanBody, cid: int = Depends(require_company)):
    fields = {}
    if body.customer_id is not None:
        fields["customer_id"] = _int_or_none(body.customer_id)
    for key in ("title", "visit_date", "days", "location", "payload"):
        val = getattr(body, key)
        if val is None:
            continue
        if key == "days":
            parsed = _days_or_400(val)
            if parsed is None:
                continue
            fields[key] = parsed
        else:
            fields[key] = val if key != "payload" or isinstance(val, dict) else {}
    plan = visit_mod.update_plan(plan_id, company_id=cid, **fields)
    if not plan:
        raise HTTPException(status_code=404, detail="验厂计划不存在")
    return plan


@router.delete("/visit-plans/{plan_id}")
def delete_visit_plan(plan_id: int, cid: int = Depends(require_company)):
    if not visit_mod.delete_plan(plan_id, company_id=cid):
        raise HTTPException(status_code=404, detail="验厂计划不存在")
    return {"ok": True}
