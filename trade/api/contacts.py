"""附加联系人 API（挂在 /customers/{id}/contacts）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from trade import contacts as contacts_module
from trade.api.deps import require_company
from trade.contacts import ContactValidationError, ContactsUnavailable

router = APIRouter(tags=["contacts"])


class ContactWrite(BaseModel):
    """附加联系人写入体；function 用 str 以便存取层归一脏值。"""

    name: str | None = None
    function: str | None = None
    title: str | None = None
    responsibility: str | None = None
    is_primary: int | bool | None = None
    email: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    wechat: str | None = None
    note: str | None = None


def _http_from_store(exc: Exception) -> HTTPException:
    """把存取层异常映射为 HTTP。"""
    if isinstance(exc, ContactsUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ContactValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail="Customer not found")
    raise exc


@router.get("/customers/{customer_id}/contacts")
def list_contacts(customer_id: int, cid: int = Depends(require_company)):
    """主联系人（拼装）+ 附加联系人列表。"""
    bundle = contacts_module.get_bundle(customer_id, company_id=cid)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return bundle


@router.post("/customers/{customer_id}/contacts", status_code=201)
def create_contact(
    customer_id: int,
    payload: ContactWrite,
    cid: int = Depends(require_company),
):
    """新建附加联系人。"""
    data: dict[str, Any] = payload.model_dump(exclude_none=False)
    # POST 必须带 name；其余缺省当空串
    if payload.name is None:
        data["name"] = ""
    try:
        return contacts_module.create(customer_id, company_id=cid, data=data)
    except (ContactsUnavailable, ContactValidationError, LookupError) as exc:
        raise _http_from_store(exc) from exc


@router.put("/customers/{customer_id}/contacts/{contact_id}")
def update_contact(
    customer_id: int,
    contact_id: int,
    payload: ContactWrite,
    cid: int = Depends(require_company),
):
    """修改附加联系人。"""
    # 只传客户端显式给出的字段（exclude_none），避免把未填项清空
    data = payload.model_dump(exclude_none=True)
    try:
        result = contacts_module.update(
            customer_id, contact_id, company_id=cid, data=data
        )
    except (ContactsUnavailable, ContactValidationError, LookupError) as exc:
        raise _http_from_store(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return result


@router.delete("/customers/{customer_id}/contacts/{contact_id}")
def delete_contact(
    customer_id: int,
    contact_id: int,
    cid: int = Depends(require_company),
):
    """删除附加联系人。"""
    try:
        ok = contacts_module.delete(customer_id, contact_id, company_id=cid)
    except (ContactsUnavailable, ContactValidationError, LookupError) as exc:
        raise _http_from_store(exc) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"ok": True}
