"""邮箱 IMAP 绑定：凭证文件 mailbox_secrets.json 读写与权限。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_secrets_roundtrip_and_chmod(tmp_path, monkeypatch):
    """凭证与 trade.db 同目录；读写删除；非 Windows 上文件权限 0o600。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    from trade import database as db

    db.init_db()
    from trade import mailbox_store as ms

    path = ms.secrets_path()
    assert path.parent == db._get_db_path().parent

    ms.set_secret(1, "auth-code-16chars")
    assert ms.get_secret(1) == "auth-code-16chars"

    if os.name == "nt":
        # Windows 上 chmod 不可靠，只验证文件存在且可读
        assert path.is_file()
        path.read_text(encoding="utf-8")
    else:
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
        assert path.stat().st_mode & 0o077 == 0

    ms.delete_secret(1)
    assert ms.get_secret(1) is None
