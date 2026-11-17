"""
Trade AI Assistant — 邮箱 IMAP 绑定与拉取 API。

端点仅依赖父路由的 session 鉴权，不按公司隔离。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from trade import mailbox_store
from trade.api.models import MailboxCreateRequest, MailboxSecretUpdate, MailboxTestRequest
from trade.mailbox import PRESETS, MailboxError, test_connection

router = APIRouter(tags=["mailboxes"])

_DUP_BIND_MSG = "该邮箱已经绑定过了，先解绑再绑"


def _resolve_imap(payload: MailboxTestRequest) -> tuple[str, int, str]:
    """按预设解析 host/port；username 默认 email_address。"""
    if payload.preset in PRESETS:
        default_host, default_port = PRESETS[payload.preset]
        host = payload.host or default_host
        port = payload.port if payload.port is not None else default_port
    else:
        # 自定义预设必须提供 host
        if not payload.host:
            raise HTTPException(status_code=400, detail="自定义邮箱必须填写 IMAP 服务器地址")
        host = payload.host.strip()
        port = payload.port if payload.port is not None else 993
    username = (payload.username or payload.email_address).strip()
    return host, int(port), username


@router.post("/mailboxes/test")
def api_mailbox_test(payload: MailboxTestRequest):
    """仅测通，不落库。"""
    host, port, username = _resolve_imap(payload)
    try:
        test_connection(host, port, username, payload.secret)
    except MailboxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/mailboxes", status_code=201)
def api_mailbox_create(payload: MailboxCreateRequest):
    """创建绑定（store 内测通一次，不在此重复测通）；重复地址返回 409。"""
    host, port, username = _resolve_imap(payload)
    try:
        return mailbox_store.create_mailbox(
            payload.preset,
            payload.email_address,
            payload.secret,
            display_name=payload.display_name or "",
            host=host,
            port=port,
            username=username,
        )
    except MailboxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        # 唯一约束：与前端约定 409 文案
        if "已绑定" in msg:
            raise HTTPException(status_code=409, detail=_DUP_BIND_MSG) from exc
        raise HTTPException(status_code=400, detail=msg) from exc


@router.put("/mailboxes/{mailbox_id}/secret")
def api_mailbox_secret_update(mailbox_id: int, payload: MailboxSecretUpdate):
    """更新授权码：测通失败则保留旧码。"""
    try:
        mailbox_store.update_secret(mailbox_id, payload.secret)
    except ValueError as exc:
        if "不存在" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MailboxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/mailboxes")
def api_mailbox_list():
    """列表含同步状态与邮件数；不返回 secret。"""
    return mailbox_store.list_mailboxes()


@router.delete("/mailboxes/{mailbox_id}")
def api_mailbox_delete(mailbox_id: int):
    """解绑：删除邮箱、邮件、匹配与凭证。"""
    mailbox_store.delete_mailbox(mailbox_id)
    return {"ok": True}


@router.post("/mailboxes/{mailbox_id}/pull")
def api_mailbox_pull(mailbox_id: int):
    """手动拉取单个邮箱。"""
    return mailbox_store.pull_one(mailbox_id)


@router.post("/mailboxes/pull-all")
def api_mailbox_pull_all():
    """串行拉取全部已绑定邮箱。"""
    return mailbox_store.pull_all()
