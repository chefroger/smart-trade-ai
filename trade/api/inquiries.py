"""询盘实体 API（挂在 /customers/{id}/inquiries 与 /inquiries/{id}）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from trade import inquiry as inquiry_module
from trade.api.deps import require_company

router = APIRouter(tags=["inquiries"])


class InquiryCreate(BaseModel):
    """新建询盘。"""

    title: str = Field("", description="询盘标题")
    stage: str = Field("询盘", description="询盘阶段（询盘/报价/样品/订单）")


class InquiryUpdate(BaseModel):
    """修改询盘；字段可选。"""

    title: str | None = Field(None, description="询盘标题")
    stage: str | None = Field(None, description="询盘阶段")


@router.get("/customers/{customer_id}/inquiries")
def list_inquiries(customer_id: int, cid: int = Depends(require_company)):
    """列出该客户询盘；跨公司查不到 → 404。"""
    rows = inquiry_module.list_for_customer(customer_id, company_id=cid)
    if rows is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return rows


@router.post("/customers/{customer_id}/inquiries", status_code=201)
def create_inquiry(
    customer_id: int,
    payload: InquiryCreate,
    cid: int = Depends(require_company),
):
    """手工新建询盘并重算客户阶段。"""
    result = inquiry_module.create(
        customer_id,
        company_id=cid,
        title=payload.title or "",
        stage=payload.stage or "询盘",
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return result


@router.put("/inquiries/{inquiry_id}")
def update_inquiry(
    inquiry_id: int,
    payload: InquiryUpdate,
    cid: int = Depends(require_company),
):
    """改 title/stage；跨公司 404。"""
    data: dict[str, Any] = payload.model_dump(exclude_none=True)
    if not data:
        existing = inquiry_module.get(inquiry_id, company_id=cid)
        if existing is None:
            raise HTTPException(status_code=404, detail="Inquiry not found")
        return existing
    result = inquiry_module.update(
        inquiry_id,
        company_id=cid,
        title=data.get("title"),
        stage=data.get("stage"),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    return result


@router.delete("/inquiries/{inquiry_id}")
def delete_inquiry(inquiry_id: int, cid: int = Depends(require_company)):
    """删除询盘（幂等 ok）并重算。"""
    inquiry_module.delete(inquiry_id, company_id=cid)
    return {"ok": True}
