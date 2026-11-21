"""用户待办 API（P2-12）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from trade import todo as todo_mod
from trade.api.deps import require_company

router = APIRouter(tags=["todos"])


class TodoBody(BaseModel):
    title: Any = None
    due_date: Any = None
    customer_id: Any = None
    done: Any = None


def _int_or_none(v):
    """把可选客户 id 转成 int；空值保持 None，非法值交给业务层拒绝。"""
    # 空值表示「不关联客户」
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        # 非数字原样返回，让 todo 模块统一抛 TodoError → 400
        return v


@router.get("/todos")
def list_todos(cid: int = Depends(require_company)):
    return todo_mod.list_todos(cid)


@router.post("/todos")
def create_todo(body: TodoBody, cid: int = Depends(require_company)):
    try:
        return todo_mod.create_todo(
            cid,
            title=body.title,
            due_date=body.due_date if body.due_date is not None else "",
            customer_id=_int_or_none(body.customer_id),
        )
    # 标题/日期/客户归属校验失败：转 400，而不是冒成 500
    except todo_mod.TodoError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/todos/{todo_id}")
def update_todo(todo_id: int, body: TodoBody, cid: int = Depends(require_company)):
    fields = {}
    # None 表示「本次未提供」，逐字段收集真正要改的值
    if body.title is not None:
        fields["title"] = body.title
    if body.due_date is not None:
        fields["due_date"] = body.due_date
    if body.done is not None:
        fields["done"] = body.done
    if body.customer_id is not None:
        fields["customer_id"] = _int_or_none(body.customer_id)
    try:
        row = todo_mod.update_todo(todo_id, company_id=cid, **fields)
    # 改挂别家客户 / 非法标题日期：转 400
    except todo_mod.TodoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # 目标不存在或属于别家公司：404
    if not row:
        raise HTTPException(status_code=404, detail="待办不存在")
    return row


@router.delete("/todos/{todo_id}")
def delete_todo(todo_id: int, cid: int = Depends(require_company)):
    # 没删到行 = 不存在或属于别家公司
    if not todo_mod.delete_todo(todo_id, company_id=cid):
        raise HTTPException(status_code=404, detail="待办不存在")
    return {"ok": True}
