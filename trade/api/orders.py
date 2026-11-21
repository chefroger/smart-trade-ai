"""订单 API 路由。"""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from trade import order as order_module
from trade.api.deps import require_company
from trade.api.models import OrderCreate, OrderUpdate

router = APIRouter(tags=["orders"])

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _clean_currency(value) -> str | None:
    """币种只收 3 位大写字母；HTTP 400（不是 422），并转大写。"""
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    if not _CURRENCY_RE.fullmatch(s):
        raise HTTPException(status_code=400, detail="币种必须是 3 位大写字母（如 USD/EUR）。")
    return s


def _clean_shipped_at(value) -> str | None:
    """出货日只收 YYYY-MM 或 YYYY-MM-DD；None 原样返回（可清空），脏值 400。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return ""
    fmt = "%Y-%m" if len(s) == 7 else "%Y-%m-%d"
    try:
        datetime.strptime(s, fmt)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="出货日必须是 YYYY-MM 或 YYYY-MM-DD。",
        ) from None
    if len(s) not in (7, 10):
        raise HTTPException(
            status_code=400,
            detail="出货日必须是 YYYY-MM 或 YYYY-MM-DD。",
        )
    return s


def _clean_item_currencies(items: list[dict]) -> None:
    for item in items:
        if "currency" in item:
            item["currency"] = _clean_currency(item.get("currency")) or ""


_NUMERIC_LABELS = {
    "quantity": "数量",
    "unit_price": "单价",
    "total_amount": "总金额",
}


def _amount_key(value) -> float | None:
    """0 与 None 在"是否改过"判断里等价：旧数据两者混用，不该因此拦编辑。"""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return None if number == 0 else number


def _amounts_unchanged(old: tuple, new: tuple) -> bool:
    """合并后的金额与库里一致 → 只改了非金额字段，跳过金额校验。"""
    for a, b in zip(old, new, strict=True):
        va, vb = _amount_key(a), _amount_key(b)
        if va is None or vb is None:
            if va is not None or vb is not None:
                return False
            continue
        if abs(float(va) - float(vb)) > 1e-6:
            return False
    return True


def _reject_negatives(values: dict) -> None:
    """负数直接 400，不再静默归零（审计 P2-25）。

    静默归零会把用户输入的负值悄悄改成 0 —— 订单金额被改掉而用户毫无察觉。
    """
    bad = [
        _NUMERIC_LABELS[key]
        for key in _NUMERIC_LABELS
        if isinstance(values.get(key), (int, float)) and values[key] < 0
    ]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"{'、'.join(bad)}不能为负数，请修正后重试。",
        )


def _reject_negative_items(items: list[dict]) -> None:
    """明细行逐行拒负数，报错指名第几行，方便用户定位。"""
    for idx, item in enumerate(items, start=1):
        for key, label in _NUMERIC_LABELS.items():
            value = item.get(key)
            if isinstance(value, (int, float)) and value < 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"第 {idx} 行{label}不能为负数，请修正后重试。",
                )


@router.get("/orders")
def list_orders(
    cid: int = Depends(require_company),
    status: str | None = Query(None, description="按状态过滤"),
    limit: int = Query(200, description="条数上限，默认 200（1–500）"),
):
    """列出当前公司的订单（可按 status 过滤）。"""
    # 走 400 而不是 FastAPI 的 422：前端 toast 只认 detail 字符串
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit 必须在 1–500 之间。")
    return order_module.list_by_company(cid, limit=limit, status=status)


@router.get("/customers/{customer_id}/orders")
def list_customer_orders(customer_id: int, cid: int = Depends(require_company)):
    """列出指定客户的所有订单。"""
    from trade import customer as cust_module
    c = cust_module.get(customer_id, company_id=cid)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    return order_module.list_by_customer(customer_id, company_id=cid)


@router.post("/orders")
def create_order(payload: OrderCreate, cid: int = Depends(require_company)):
    """创建订单。校验客户归属 + 金额一致性（总金额为空时自动算出）。

    多商品用 items；只发平铺字段 = 单商品订单（兼容旧前端）。
    """
    from trade import customer as cust_module
    c = cust_module.get(payload.customer_id, company_id=cid)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    # 新建不得直接是终态：已完成 / 已取消只能由状态机走到，否则等于绕过流水
    if (payload.status or "") in {"已完成", "已取消"}:
        raise HTTPException(
            status_code=400,
            detail="新建订单不能直接设置为已完成或已取消，请先按正常流程创建。",
        )

    items = (
        [item.model_dump() for item in payload.items]
        if payload.items is not None else None
    )
    if items is not None:
        if not items:
            raise HTTPException(status_code=400, detail="订单至少需要一行商品。")
        _reject_negative_items(items)
        _clean_item_currencies(items)
        return order_module.create(
            company_id=cid,
            customer_id=payload.customer_id,
            order_no=payload.order_no or "",
            currency=_clean_currency(payload.currency) or "USD",
            status=payload.status or "报价中",
            delivery_date=payload.delivery_date or "",
            payment_terms=payload.payment_terms or "",
            notes=payload.notes or "",
            incoterm=payload.incoterm or "",
            port_of_loading=payload.port_of_loading or "",
            container=payload.container or "",
            lead_time_text=payload.lead_time_text or "",
            shipped_at=_clean_shipped_at(payload.shipped_at) or "",
            items=items,
        )

    if not (payload.product_name or "").strip():
        raise HTTPException(status_code=400, detail="请填写品名，或至少添加一行商品。")
    _reject_negatives({
        "quantity": payload.quantity,
        "unit_price": payload.unit_price,
        "total_amount": payload.total_amount,
    })
    try:
        quantity, unit_price, total_amount = order_module.reconcile_amounts(
            payload.quantity, payload.unit_price, payload.total_amount,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return order_module.create(
        company_id=cid,
        customer_id=payload.customer_id,
        product_name=payload.product_name,
        order_no=payload.order_no or "",
        quantity=quantity,
        unit=payload.unit or "",
        unit_price=unit_price,
        # 单商品平铺路径同样要过币种校验：非法值 400，小写规范化为大写
        currency=_clean_currency(payload.currency) or "USD",
        total_amount=total_amount,
        status=payload.status or "报价中",
        delivery_date=payload.delivery_date or "",
        payment_terms=payload.payment_terms or "",
        notes=payload.notes or "",
        incoterm=payload.incoterm or "",
        port_of_loading=payload.port_of_loading or "",
        container=payload.container or "",
        lead_time_text=payload.lead_time_text or "",
        shipped_at=_clean_shipped_at(payload.shipped_at) or "",
    )


@router.get("/orders/{order_id}")
def get_order(order_id: int, cid: int = Depends(require_company)):
    """获取订单详情。"""
    o = order_module.get(order_id, company_id=cid)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    return o


@router.put("/orders/{order_id}")
def update_order(order_id: int, payload: OrderUpdate, cid: int = Depends(require_company)):
    """更新订单。校验状态迁移与金额一致性（都以库里的当前值为基准）。

    `exclude_unset` 而非 `exclude_none`：显式传 null 表示「清空该字段」
    （只对可清空字段生效），不能和不传混为一谈（审计 P2-28）。
    """
    changes = payload.model_dump(exclude_unset=True)
    existing = order_module.get(order_id, company_id=cid)
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")

    # items 显式传列表 = 整单替换明细；传 null / 不传 = 走平铺字段兼容路径
    items = changes.pop("items", None)

    # 非可清空字段传 null = 未提供，直接丢掉（避免把 product_name 写成 NULL）。
    # 金额字段在 CLEARABLE_FIELDS 里：显式 null 表示"清空 / 待谈"，必须保留。
    for key in list(changes):
        if changes[key] is None and key not in order_module.CLEARABLE_FIELDS:
            changes.pop(key)
    if "currency" in changes:
        changes["currency"] = _clean_currency(changes.get("currency")) or ""
    if "shipped_at" in changes:
        changes["shipped_at"] = _clean_shipped_at(changes.get("shipped_at"))
    _reject_negatives(changes)
    if items is not None:
        if not items:
            raise HTTPException(status_code=400, detail="订单至少需要一行商品。")
        _reject_negative_items(items)
        _clean_item_currencies(items)

    new_status = changes.get("status")
    if new_status and not order_module.can_transition_status(existing.get("status") or "", new_status):
        raise HTTPException(
            status_code=400,
            detail=f"订单状态不能从「{existing.get('status') or '未知'}」变为「{new_status}」。",
        )

    # 只有真的改了金额才校验：旧记录本就可能不一致，改备注不该被它挡住。
    # 前端 PUT 会发全量 body，所以必须按"合并后 vs 库内"判断，不能只看字段是否出现。
    # 传了 items 时金额由 order.py 逐行校验，这里不再按头级合并。
    if items is None and {"quantity", "unit_price", "total_amount"} & changes.keys():
        merged = (
            changes.get("quantity", existing.get("quantity")),
            changes.get("unit_price", existing.get("unit_price")),
            changes.get("total_amount", existing.get("total_amount")),
        )
        current = (
            existing.get("quantity"),
            existing.get("unit_price"),
            existing.get("total_amount"),
        )
        if _amounts_unchanged(current, merged):
            # 金额没动：不要回写。前端会发全量 body，回写会把库里的 NULL
            # 悄悄换成 0（_amount_key 视二者等价），前端就显示成"0"而不是"待谈"。
            for key in ("quantity", "unit_price", "total_amount"):
                changes.pop(key, None)
        else:
            try:
                qty, price, total = order_module.reconcile_amounts(*merged)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            changes.update(quantity=qty, unit_price=price, total_amount=total)

    try:
        result = order_module.update(
            order_id, company_id=cid, items=items, **changes,
        )
    except ValueError as exc:
        # 明细行校验（品名缺失 / 多商品单改头级金额）→ 400，不是 500
        raise HTTPException(status_code=400, detail=str(exc))
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    return result


@router.delete("/orders/{order_id}")
def delete_order(order_id: int, cid: int = Depends(require_company)):
    """删除订单。"""
    if not order_module.delete(order_id, company_id=cid):
        raise HTTPException(status_code=404, detail="Order not found")
    return {"ok": True}


@router.post("/orders/{order_id}/libraries/{library_id}")
def link_order_library(order_id: int, library_id: int, cid: int = Depends(require_company)):
    """关联文档库到订单。"""
    if not order_module.link_library(order_id, library_id, company_id=cid):
        raise HTTPException(status_code=404, detail="Order or library not found")
    return {"ok": True}


@router.delete("/orders/{order_id}/libraries/{library_id}")
def unlink_order_library(order_id: int, library_id: int, cid: int = Depends(require_company)):
    """取消订单的文档库关联。"""
    if not order_module.unlink_library(order_id, library_id, company_id=cid):
        raise HTTPException(status_code=404, detail="Association not found")
    return {"ok": True}
