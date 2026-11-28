"""
公司软删 → purge 全路径凭据擦除与全局邮箱保护验收测试（PR #32 修正口径 A1–A5）。

验收口径：
  - A1 软删后：mailbox_secrets.json 中全部邮箱授权码保持不变（含 contact_email 命中、
       含邮件仅关联该公司的邮箱），mailboxes 表行数不变；
  - A2 purge 后：同 A1；公司自有凭据文件零残留；
  - A3 进程内活跃 session 解绑行为不变；
  - A4 软删审计日志文案不再声称擦除邮箱凭据；
  - A5 名为 token-payment-terms.pdf 的业务文件不被误删；api_key.txt / .env / secret-notes.txt 仍被擦除。
"""

from __future__ import annotations

import json

from trade import company as company_mod
from trade import database as db_mod
from trade import mailbox_store
from trade.api import deps as deps_mod


def test_soft_delete_and_purge_preserve_global_mailboxes_and_erase_company_secrets(
    tmp_path, monkeypatch
):
    """覆盖 A1–A5：全局邮箱不动、公司凭据即擦、token 业务文件不误删、session 解绑、审计文案准确。"""
    trade_home = tmp_path / "trade_home"
    trade_home.mkdir(parents=True, exist_ok=True)
    db_path = trade_home / "data" / "trade.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("TRADE_HOME", str(trade_home))
    monkeypatch.setattr(db_mod, "_get_db_path", lambda: db_path)
    monkeypatch.setattr(company_mod.crud, "TRADE_HOME", trade_home)

    def _fake_work_dir(name, slug, suggested_name=""):
        wd = tmp_path / "work" / (slug or "co")
        wd.mkdir(parents=True, exist_ok=True)
        return wd, True

    monkeypatch.setattr(company_mod.workdir, "_setup_work_directory", _fake_work_dir)
    db_mod.init_db()

    co_a = company_mod.create(
        name="Fictional Alpha Co",
        slug="fictional-alpha",
        contact_email="boss@fictional-alpha.invalid",
    )
    cid_a = int(co_a["id"])

    # 构造可辨认的虚构公司凭据与全局邮箱授权码（仅用于单元测试）
    fake_env_key = "FICTIONAL-ENV-KEY-ALPHA-99887766"
    fake_api_key = "FICTIONAL-API-KEY-ALPHA-11223344"
    fake_secret_note = "FICTIONAL-SECRET-NOTE-ALPHA-55667788"
    fake_mail_secret_contact = "FICTIONAL-IMAP-SECRET-CONTACT-111111"
    fake_mail_secret_linked = "FICTIONAL-IMAP-SECRET-LINKED-222222"

    alpha_dir = trade_home / "fictional-alpha"
    alpha_dir.mkdir(parents=True, exist_ok=True)
    # 应被擦除的公司凭据文件（根目录下的精确凭据文件 + PEM 格式 .key）
    (alpha_dir / ".env").write_text(f"CUSTOM_KEY={fake_env_key}\n", encoding="utf-8")
    (alpha_dir / "api_key.txt").write_text(fake_api_key, encoding="utf-8")
    (alpha_dir / "secrets.json").write_text(
        json.dumps({"secret": fake_secret_note}), encoding="utf-8"
    )
    (alpha_dir / "deploy.key").write_text(
        "-----BEGIN " + "FICTIONAL TEST KEY-----\nDUMMY-TEST-BODY\n",
        encoding="utf-8",
    )
    # 不应被误删的正常业务文件（含 token / credential / secret / Keynote .key 及业务子目录）
    (alpha_dir / "token-payment-terms.pdf").write_bytes(b"%PDF-1.4 fictional payment terms")
    (alpha_dir / "Company Credentials 2026.pptx").write_bytes(b"PK\x03\x04 fake pptx")
    (alpha_dir / "Annual Pitch.key").write_bytes(b"PK\x03\x04 fake keynote deck")
    (alpha_dir / "Secretary_List.xlsx").write_bytes(b"PK\x03\x04 fake xlsx")
    (alpha_dir / "secret-recipe-NDA.docx").write_bytes(b"PK\x03\x04 fake docx")
    (alpha_dir / "Confidential Supplier Credential Letter.pdf").write_bytes(b"%PDF-1.4")
    (alpha_dir / "MEMORY.md").write_text("# 正常业务记忆保留 30 天\n", encoding="utf-8")
    # libraries/ 与 clients/ 业务子目录内的任何文件绝不被凭据扫描触碰
    (alpha_dir / "libraries" / "docs").mkdir(parents=True, exist_ok=True)
    (alpha_dir / "libraries" / "docs" / ".env").write_text("SAMPLE=1\n", encoding="utf-8")
    (alpha_dir / "clients" / "acme").mkdir(parents=True, exist_ok=True)
    (alpha_dir / "clients" / "acme" / "api_key.txt").write_text("client-doc", encoding="utf-8")

    # 写入两个全局邮箱：一个匹配公司 A 的 contact_email，一个仅有归属公司 A 的邮件行
    conn = db_mod.get_connection()
    try:
        cur1 = conn.execute(
            "INSERT INTO mailboxes (preset, email_address, host, port, username) "
            "VALUES ('custom', 'boss@fictional-alpha.invalid', 'imap.invalid', 993, 'boss')"
        )
        mid1 = int(cur1.lastrowid)
        cur2 = conn.execute(
            "INSERT INTO mailboxes (preset, email_address, host, port, username) "
            "VALUES ('custom', 'sales@fictional-other.invalid', 'imap.invalid', 993, 'sales')"
        )
        mid2 = int(cur2.lastrowid)
        conn.execute(
            "INSERT INTO emails (mailbox_id, message_id, company_id, subject) "
            "VALUES (?, '<msg-1@invalid>', ?, 'Test')",
            (mid2, cid_a),
        )
        conn.commit()
    finally:
        conn.close()

    mailbox_store.set_secret(mid1, fake_mail_secret_contact)
    mailbox_store.set_secret(mid2, fake_mail_secret_linked)

    # A3：预先绑定活跃 session 到公司 A
    deps_mod.set_active_company("tok-session-a", cid_a)
    assert deps_mod._ACTIVE_COMPANY.get("tok-session-a") == cid_a

    # ── 1) 软删公司 A ──
    assert company_mod.delete(cid_a) is True

    # A1：全局邮箱凭据与 mailboxes 表行数丝毫未动
    assert mailbox_store.get_secret(mid1) == fake_mail_secret_contact
    assert mailbox_store.get_secret(mid2) == fake_mail_secret_linked
    conn = db_mod.get_connection()
    try:
        mb_count = conn.execute("SELECT COUNT(*) FROM mailboxes").fetchone()[0]
        assert mb_count == 2
    finally:
        conn.close()

    # A4：软删审计日志（JSONL）不再声称擦除邮箱凭据
    audit_files = sorted((trade_home / "audit").glob("*.jsonl"))
    assert audit_files, "软删后应写入审计日志 JSONL 文件"
    audit_entries = [
        json.loads(line)
        for f in audit_files
        for line in f.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    soft_del_entries = [
        e for e in audit_entries
        if e.get("company_id") == cid_a and e.get("action") == "soft_delete"
    ]
    assert soft_del_entries, "审计日志中应包含该公司 soft_delete 记录"
    detail = str(soft_del_entries[-1].get("detail", ""))
    assert "邮箱凭据" not in detail
    assert "凭据文件 4 个" in detail
    assert "fictional-alpha/.env" in detail
    assert "fictional-alpha/deploy.key" in detail

    # A3：活跃 session 已解绑
    assert deps_mod._ACTIVE_COMPANY.get("tok-session-a") is None

    # A5：精确凭据文件已擦除；外贸业务文件、Keynote .key、业务子目录内文件全部完好保留
    assert not (alpha_dir / ".env").exists()
    assert not (alpha_dir / "api_key.txt").exists()
    assert not (alpha_dir / "secrets.json").exists()
    assert not (alpha_dir / "deploy.key").exists()
    assert (alpha_dir / "token-payment-terms.pdf").exists()
    assert (alpha_dir / "Company Credentials 2026.pptx").exists()
    assert (alpha_dir / "Annual Pitch.key").exists()
    assert (alpha_dir / "Secretary_List.xlsx").exists()
    assert (alpha_dir / "secret-recipe-NDA.docx").exists()
    assert (alpha_dir / "Confidential Supplier Credential Letter.pdf").exists()
    assert (alpha_dir / "MEMORY.md").exists()
    assert (alpha_dir / "libraries" / "docs" / ".env").exists()
    assert (alpha_dir / "clients" / "acme" / "api_key.txt").exists()

    # ── 2) purge 公司 A ──
    assert company_mod.purge(cid_a) is True
    assert not alpha_dir.exists()

    # A2：全局邮箱凭据与 mailboxes 表行数仍保持不变
    assert mailbox_store.get_secret(mid1) == fake_mail_secret_contact
    assert mailbox_store.get_secret(mid2) == fake_mail_secret_linked
    conn = db_mod.get_connection()
    try:
        mb_count_after = conn.execute("SELECT COUNT(*) FROM mailboxes").fetchone()[0]
        assert mb_count_after == 2
    finally:
        conn.close()

    # A2：全盘搜索不到任何公司自有假 Key 残留
    for p in trade_home.rglob("*"):
        if not p.is_file():
            continue
        raw = p.read_bytes()
        for leaked in (fake_env_key, fake_api_key, fake_secret_note):
            assert leaked.encode() not in raw, f"发现残留公司凭据：{p}"
