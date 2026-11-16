"""邮箱绑定存储：凭证文件、mailbox CRUD、匹配入库、拉取编排（分步实现）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from trade.database import _get_db_path


def secrets_path() -> Path:
    """凭证文件与 trade.db 同目录。"""
    return _get_db_path().parent / "mailbox_secrets.json"


def _load_secrets() -> dict[str, str]:
    """从磁盘读取凭证映射；缺失或空文件返回空 dict。"""
    p = secrets_path()
    # 文件不存在时无需创建，调用方按空映射处理
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def _save_secrets(data: dict[str, str]) -> None:
    """写入凭证 JSON，非 Windows 上限制为仅属主读写。"""
    p = secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Windows 不支持可靠 chmod，跳过
    if os.name != "nt":
        os.chmod(p, 0o600)


def get_secret(mailbox_id: int) -> str | None:
    """读取指定 mailbox 的授权码/凭证；无则 None。"""
    return _load_secrets().get(str(mailbox_id))


def set_secret(mailbox_id: int, secret: str) -> None:
    """保存指定 mailbox 的凭证（不落库、不写日志）。"""
    data = _load_secrets()
    data[str(mailbox_id)] = secret
    _save_secrets(data)


def delete_secret(mailbox_id: int) -> None:
    """删除指定 mailbox 的凭证项。"""
    data = _load_secrets()
    data.pop(str(mailbox_id), None)
    _save_secrets(data)
