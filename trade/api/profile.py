"""客户画像 API：facts + gifts。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from trade import profile as profile_mod
from trade.api.deps import require_company

router = APIRouter(tags=["profile"])


class LooseBody(BaseModel):
    """宽松请求体：类型校验一律在路由/存取层转 400。"""

    category: Any = None
    subject: Any = None
    content: Any = None
    attach_to: Any = None
    contact_id: Any = None
    ai_visible: Any = None
    direction: Any = None
    item: Any = None
    approx_value: Any = None
    currency: Any = None
    gift_date: Any = None
    occasion: Any = None
    note: Any = None
    source: Any = None
    limit: Any = None


def _map_err(exc: Exception) -> None:
    """把存取层异常映射成 HTTP。"""
    if isinstance(exc, profile_mod.ProfileNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc) or "不存在") from exc
    if isinstance(exc, profile_mod.ProfileConflictError):
        raise HTTPException(status_code=409, detail=str(exc) or "冲突") from exc
    if isinstance(exc, profile_mod.ProfileError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, RuntimeError) and "表不存在" in str(exc):
        raise HTTPException(
            status_code=503,
            detail="客户画像功能需要重启 Trade 后才能使用",
        ) from exc
    if isinstance(exc, RuntimeError) and str(exc).startswith("提取失败"):
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    raise exc


def _ensure_customer(customer_id: int, company_id: int) -> None:
    """客户归属校验。"""
    try:
        profile_mod._require_customer(customer_id, company_id)
    except profile_mod.ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="客户不存在") from exc


# ── Facts ───────────────────────────────────────────────────────────────────


@router.get("/customers/{customer_id}/facts")
def get_facts(
    customer_id: int,
    status: str | None = None,
    cid: int = Depends(require_company),
):
    """列出客户事实。"""
    _ensure_customer(customer_id, cid)
    if not profile_mod.facts_available():
        return {"available": False, "items": []}
    try:
        items = profile_mod.list_facts(
            customer_id, company_id=cid, status=status,
        )
    except Exception as exc:
        _map_err(exc)
        raise
    return {"available": True, "items": items}


@router.post("/customers/{customer_id}/facts")
def post_fact(
    customer_id: int,
    body: LooseBody,
    cid: int = Depends(require_company),
):
    """手工新建事实。"""
    _ensure_customer(customer_id, cid)
    if not profile_mod.facts_available():
        raise HTTPException(
            status_code=503,
            detail="客户画像功能需要重启 Trade 后才能使用",
        )
    try:
        result = profile_mod.create_fact_manual(
            customer_id,
            company_id=cid,
            category=body.category,
            content=body.content,
            subject=body.subject or "",
            attach_to=body.attach_to or "none",
            contact_id=body.contact_id,
        )
    except Exception as exc:
        _map_err(exc)
        raise
    # W13/W14：内容像家庭成员信息 → 提示改「家庭」类；
    # 像「客户索要」→ 提示改记礼物表（都只提示，不阻断写入）
    from trade.privacy_terms import contains_family_terms

    text = f"{body.subject or ''} {body.content or ''}"
    hints = []
    if (body.category or "") != "家庭" and contains_family_terms(text):
        hints.append("内容包含家庭成员信息，建议把分类改为「家庭」")
    if (body.category or "") != "礼物往来" and profile_mod.looks_like_gift(text):
        hints.append("内容像客户索要/送礼，建议改记到「礼物往来」表")
    if hints and isinstance(result, dict):
        result = {**result, "hint": "；".join(hints)}
    return result


@router.put("/customers/{customer_id}/facts/{fact_id}")
def put_fact(
    customer_id: int,
    fact_id: int,
    body: LooseBody,
    cid: int = Depends(require_company),
):
    """更新事实。"""
    _ensure_customer(customer_id, cid)
    if not profile_mod.facts_available():
        raise HTTPException(
            status_code=503,
            detail="客户画像功能需要重启 Trade 后才能使用",
        )
    updates = body.model_dump(exclude_unset=True)
    try:
        return profile_mod.update_fact(
            fact_id, customer_id=customer_id, company_id=cid, updates=updates,
        )
    except Exception as exc:
        _map_err(exc)
        raise


@router.post("/customers/{customer_id}/facts/{fact_id}/confirm")
def confirm_fact(
    customer_id: int, fact_id: int, cid: int = Depends(require_company),
):
    """确认事实。"""
    _ensure_customer(customer_id, cid)
    if not profile_mod.facts_available():
        raise HTTPException(
            status_code=503,
            detail="客户画像功能需要重启 Trade 后才能使用",
        )
    try:
        return profile_mod.confirm_fact(
            fact_id, customer_id=customer_id, company_id=cid,
        )
    except Exception as exc:
        _map_err(exc)
        raise


@router.post("/customers/{customer_id}/facts/{fact_id}/void")
def void_fact(
    customer_id: int, fact_id: int, cid: int = Depends(require_company),
):
    """作废事实。"""
    _ensure_customer(customer_id, cid)
    if not profile_mod.facts_available():
        raise HTTPException(
            status_code=503,
            detail="客户画像功能需要重启 Trade 后才能使用",
        )
    try:
        return profile_mod.void_fact(
            fact_id, customer_id=customer_id, company_id=cid,
        )
    except Exception as exc:
        _map_err(exc)
        raise


@router.delete("/customers/{customer_id}/facts/{fact_id}")
def delete_fact(
    customer_id: int, fact_id: int, cid: int = Depends(require_company),
):
    """删除手工事实。"""
    _ensure_customer(customer_id, cid)
    if not profile_mod.facts_available():
        raise HTTPException(
            status_code=503,
            detail="客户画像功能需要重启 Trade 后才能使用",
        )
    try:
        profile_mod.delete_fact(
            fact_id, customer_id=customer_id, company_id=cid,
        )
    except Exception as exc:
        _map_err(exc)
        raise
    return {"ok": True}


@router.post("/customers/{customer_id}/facts/extract")
def extract_facts(
    customer_id: int,
    body: LooseBody,
    cid: int = Depends(require_company),
):
    """从聊天/邮件手动提取。"""
    _ensure_customer(customer_id, cid)
    if not profile_mod.facts_available() or not profile_mod.gifts_available():
        raise HTTPException(
            status_code=503,
            detail="客户画像功能需要重启 Trade 后才能使用",
        )
    try:
        return profile_mod.extract_from_sources(
            customer_id,
            company_id=cid,
            source=body.source,
            limit=body.limit if body.limit is not None else 20,
        )
    except Exception as exc:
        _map_err(exc)
        raise


# ── Gifts ───────────────────────────────────────────────────────────────────


@router.get("/customers/{customer_id}/gifts")
def get_gifts(
    customer_id: int,
    status: str | None = None,
    cid: int = Depends(require_company),
):
    """列出礼物。"""
    _ensure_customer(customer_id, cid)
    if not profile_mod.gifts_available():
        return {"available": False, "items": []}
    try:
        items = profile_mod.list_gifts(
            customer_id, company_id=cid, status=status,
        )
    except Exception as exc:
        _map_err(exc)
        raise
    return {"available": True, "items": items}


@router.post("/customers/{customer_id}/gifts")
def post_gift(
    customer_id: int,
    body: LooseBody,
    cid: int = Depends(require_company),
):
    """手工新建礼物。"""
    _ensure_customer(customer_id, cid)
    if not profile_mod.gifts_available():
        raise HTTPException(
            status_code=503,
            detail="客户画像功能需要重启 Trade 后才能使用",
        )
    try:
        return profile_mod.create_gift_manual(
            customer_id,
            company_id=cid,
            direction=body.direction,
            item=body.item,
            approx_value=body.approx_value,
            currency=body.currency or "",
            gift_date=body.gift_date or "",
            occasion=body.occasion or "",
            note=body.note or "",
            attach_to=body.attach_to or "none",
            contact_id=body.contact_id,
        )
    except Exception as exc:
        _map_err(exc)
        raise


@router.put("/customers/{customer_id}/gifts/{gift_id}")
def put_gift(
    customer_id: int,
    gift_id: int,
    body: LooseBody,
    cid: int = Depends(require_company),
):
    """更新礼物。"""
    _ensure_customer(customer_id, cid)
    if not profile_mod.gifts_available():
        raise HTTPException(
            status_code=503,
            detail="客户画像功能需要重启 Trade 后才能使用",
        )
    updates = body.model_dump(exclude_unset=True)
    try:
        return profile_mod.update_gift(
            gift_id, customer_id=customer_id, company_id=cid, updates=updates,
        )
    except Exception as exc:
        _map_err(exc)
        raise


@router.post("/customers/{customer_id}/gifts/{gift_id}/confirm")
def confirm_gift(
    customer_id: int, gift_id: int, cid: int = Depends(require_company),
):
    """确认礼物。"""
    _ensure_customer(customer_id, cid)
    if not profile_mod.gifts_available():
        raise HTTPException(
            status_code=503,
            detail="客户画像功能需要重启 Trade 后才能使用",
        )
    try:
        return profile_mod.confirm_gift(
            gift_id, customer_id=customer_id, company_id=cid,
        )
    except Exception as exc:
        _map_err(exc)
        raise


@router.post("/customers/{customer_id}/gifts/{gift_id}/void")
def void_gift(
    customer_id: int, gift_id: int, cid: int = Depends(require_company),
):
    """作废礼物。"""
    _ensure_customer(customer_id, cid)
    if not profile_mod.gifts_available():
        raise HTTPException(
            status_code=503,
            detail="客户画像功能需要重启 Trade 后才能使用",
        )
    try:
        return profile_mod.void_gift(
            gift_id, customer_id=customer_id, company_id=cid,
        )
    except Exception as exc:
        _map_err(exc)
        raise


@router.delete("/customers/{customer_id}/gifts/{gift_id}")
def delete_gift(
    customer_id: int, gift_id: int, cid: int = Depends(require_company),
):
    """删除手工礼物。"""
    _ensure_customer(customer_id, cid)
    if not profile_mod.gifts_available():
        raise HTTPException(
            status_code=503,
            detail="客户画像功能需要重启 Trade 后才能使用",
        )
    try:
        profile_mod.delete_gift(
            gift_id, customer_id=customer_id, company_id=cid,
        )
    except Exception as exc:
        _map_err(exc)
        raise
    return {"ok": True}


# ── 私密备忘录（审计 P1-F）────────────────────────────────────────────────
# 家庭类 facts 与「客户索要」礼物不进 AI / 打印 / 长图 / 导出，只能在本机
# 输入固定密语后单独查看。默认每次进入都要输入（不缓存会话）。

class MemoPassBody(BaseModel):
    passphrase: str = ""


class MemoPrefsBody(BaseModel):
    unlock_mode: str = "always"


@router.get("/profile/memo/status")
def memo_status(cid: int = Depends(require_company)):
    """密语是否已设置（不返回任何哈希/盐）；附带解锁策略。"""
    from trade import memo as memo_mod

    return {
        "configured": memo_mod.is_configured(),
        "unlock_mode": memo_mod.unlock_mode(),
    }


@router.post("/profile/memo/prefs")
def memo_prefs(body: MemoPrefsBody, cid: int = Depends(require_company)):
    """设置密语策略：每次输入 / 本会话内有效（W13）。"""
    from trade import memo as memo_mod

    try:
        mode = memo_mod.set_unlock_mode(body.unlock_mode)
    except memo_mod.MemoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"unlock_mode": mode}


@router.get("/profile/privacy-terms")
def privacy_terms(cid: int = Depends(require_company)):
    """家庭/私密称谓词表（前端打印、长图使用同一份，W13）。"""
    from trade.privacy_terms import family_terms_payload

    return family_terms_payload()


@router.post("/profile/memo/passphrase")
def memo_configure(body: MemoPassBody, cid: int = Depends(require_company)):
    """首次设置密语；已设置时只做校验（不允许静默覆盖）。"""
    from trade import memo as memo_mod

    if not memo_mod.is_configured():
        try:
            memo_mod.configure(body.passphrase)
        except memo_mod.MemoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"configured": True, "created": True}
    remaining = memo_mod.lock_remaining(cid)
    if remaining:
        raise HTTPException(
            status_code=429, detail=f"密语已锁定，请 {remaining} 秒后重试",
        )
    if not memo_mod.verify(body.passphrase):
        memo_mod.register_failure(cid)
        raise HTTPException(status_code=403, detail="密语不正确")
    memo_mod.register_success(cid)
    return {"configured": True, "created": False}


@router.post("/customers/{customer_id}/memo")
def customer_memo(
    customer_id: int, body: MemoPassBody, cid: int = Depends(require_company),
):
    """校验密语后返回该客户的家庭 facts + 客户索要。"""
    from trade import memo as memo_mod

    _ensure_customer(customer_id, cid)
    if not memo_mod.is_configured():
        raise HTTPException(status_code=409, detail="尚未设置密语")
    # O-新6：后端节流，刷新页面不能绕过前端锁定
    # O-新28：按公司分桶 —— A 公司锁住不影响 B 公司
    remaining = memo_mod.lock_remaining(cid)
    if remaining:
        raise HTTPException(
            status_code=429, detail=f"密语已锁定，请 {remaining} 秒后重试",
        )
    if not memo_mod.verify(body.passphrase):
        memo_mod.register_failure(cid)
        raise HTTPException(status_code=403, detail="密语不正确")
    memo_mod.register_success(cid)
    return memo_mod.memo_items(cid, customer_id)
