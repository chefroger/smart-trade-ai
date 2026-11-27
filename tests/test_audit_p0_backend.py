"""2026-11-26 全项目审计 P0 后端回归测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def test_old_emails_table_without_company_id_upgrades_cleanly(monkeypatch, tmp_path):
    """老库 emails 表缺 company_id/customer_id 时，init_db 不得在建索引阶段崩溃。"""
    import trade.database as _db

    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE emails (id INTEGER PRIMARY KEY, mailbox_id INTEGER NOT NULL, "
        "message_id TEXT NOT NULL, received_at TEXT)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    monkeypatch.setattr(_db, "_get_db_path", lambda: db_file)
    _db.init_db()

    conn = sqlite3.connect(str(db_file))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(emails)").fetchall()}
        assert {"company_id", "customer_id"} <= cols
    finally:
        conn.close()


def test_guardrails_blocks_brand_safety_and_memory_md_writes(tmp_path):
    """strict 模式下必须禁止写入 brand_safety.md 与 memories/MEMORY.md。"""
    from trade.hermes_chat_memory_plugin import guardrails

    root = tmp_path / "co_a"
    brand = root / "companies" / "co_a" / "brand_safety.md"
    mem = root / "memories" / "MEMORY.md"
    normal = root / "notes" / "draft.md"

    assert guardrails._is_sensitive_write_target(brand, [root]) is True
    assert guardrails._is_sensitive_write_target(mem, [root]) is True
    assert guardrails._is_sensitive_write_target(normal, [root]) is False


def test_classify_user_paths_blocks_other_company_workdir_and_hermes_env(monkeypatch, tmp_path):
    """对话显式路径放行必须拦截其他公司桌面工作目录与 ~/.hermes/.env 等敏感文件。"""
    trade_home = tmp_path / "trade_home"
    trade_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TRADE_HOME", str(trade_home))
    import trade.database as _db

    monkeypatch.setattr(_db, "_get_db_path", lambda: trade_home / "trade.db")
    _db.init_db()

    import trade.company as co
    from trade.api.chat import _classify_user_paths

    def _setup(name, slug, suggested_name=""):
        wd = tmp_path / "desktop" / (suggested_name or slug)
        wd.mkdir(parents=True, exist_ok=True)
        for cat, _ in co._WORK_DIR_CATEGORIES:
            (wd / cat).mkdir(parents=True, exist_ok=True)
        return wd, True

    monkeypatch.setattr(co, "_setup_work_directory", _setup)
    c1 = co.create(name="CoOne", slug="co-one")
    c2 = co.create(name="CoTwo", slug="co-two")

    own_file = Path(c1["work_dir"]) / "报价单" / "a.pdf"
    other_file = Path(c2["work_dir"]) / "报价单" / "b.pdf"
    own_file.parent.mkdir(parents=True, exist_ok=True)
    other_file.parent.mkdir(parents=True, exist_ok=True)
    own_file.write_text("ok", encoding="utf-8")
    other_file.write_text("secret", encoding="utf-8")
    hermes_env = Path.home() / ".hermes" / ".env"

    query = f"请帮我看 {own_file} 和 {other_file} 以及 {hermes_env}"
    allowed = _classify_user_paths(query, c1["id"])
    assert str(own_file) in allowed
    assert str(other_file) not in allowed
    assert str(hermes_env) not in allowed
