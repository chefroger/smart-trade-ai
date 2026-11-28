"""
公司软删 → purge 全路径凭据擦除验收测试（M3 / W3）。

验收口径：
  建测试公司 → 填入可辨认的虚构假 Key 文件与假邮箱凭证 →
  1) 软删公司：凭据即刻擦除（保留期不留 Key），业务记忆仍保留，另一家活跃公司凭据不受影响；
  2) 执行 purge：全盘（TRADE_HOME 与临时库）搜索不到该假 Key 与假邮箱凭证的任何片段。
"""

from __future__ import annotations

from trade import company as company_mod
from trade import database as db_mod
from trade import mailbox_store


def test_soft_delete_erases_credentials_immediately_and_purge_leaves_zero_trace(
    tmp_path, monkeypatch
):
    """软删即擦凭据，purge 后全盘无任何假 Key 与假邮箱凭证残留，且不误伤其他活跃公司。"""
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

    # 建两家虚构测试公司（A 待删，B 保持活跃）
    co_a = company_mod.create(
        name="Fictional Alpha Co",
        slug="fictional-alpha",
        contact_email="alpha@fictional-alpha.invalid",
    )
    company_mod.create(
        name="Fictional Beta Co",
        slug="fictional-beta",
        contact_email="beta@fictional-beta.invalid",
    )

    # 构造可辨认的虚构假凭据（仅用于单元测试）
    fake_api_key = "FICTIONAL-TEST-KEY-ALPHA-99887766"
    fake_mail_secret_a = "FICTIONAL-IMAP-SECRET-ALPHA-554433"
    fake_mail_secret_b = "FICTIONAL-IMAP-SECRET-BETA-112233"

    # 在公司 A 数据目录写入凭据文件与正常业务记忆文件
    alpha_dir = trade_home / "fictional-alpha"
    alpha_dir.mkdir(parents=True, exist_ok=True)
    (alpha_dir / ".env").write_text(f"CUSTOM_KEY={fake_api_key}\n", encoding="utf-8")
    (alpha_dir / "MEMORY.md").write_text("# 正常业务记忆保留 30 天\n", encoding="utf-8")

    # 在 mailboxes + mailbox_secrets.json 写入公司 A 与公司 B 的绑定邮箱凭证
    conn = db_mod.get_connection()
    try:
        cur_a = conn.execute(
            "INSERT INTO mailboxes (preset, email_address, host, port, username) "
            "VALUES ('custom', 'alpha@fictional-alpha.invalid', 'imap.invalid', 993, 'alpha')"
        )
        mid_a = int(cur_a.lastrowid)
        cur_b = conn.execute(
            "INSERT INTO mailboxes (preset, email_address, host, port, username) "
            "VALUES ('custom', 'beta@fictional-beta.invalid', 'imap.invalid', 993, 'beta')"
        )
        mid_b = int(cur_b.lastrowid)
        conn.commit()
    finally:
        conn.close()

    mailbox_store.set_secret(mid_a, fake_mail_secret_a)
    mailbox_store.set_secret(mid_b, fake_mail_secret_b)

    # 1) 软删公司 A：凭据必须即刻擦除，业务记忆仍保留，公司 B 凭据不受影响
    assert company_mod.delete(int(co_a["id"])) is True
    assert not (alpha_dir / ".env").exists()
    assert (alpha_dir / "MEMORY.md").exists()
    assert mailbox_store.get_secret(mid_a) is None
    assert mailbox_store.get_secret(mid_b) == fake_mail_secret_b

    # 2) 执行 purge：全盘（整个 trade_home 下所有文件）grep 不到任何假 Key 与假邮箱凭证片段
    assert company_mod.purge(int(co_a["id"])) is True
    assert not alpha_dir.exists()
    for p in trade_home.rglob("*"):
        if not p.is_file():
            continue
        raw = p.read_bytes()
        assert fake_api_key.encode() not in raw, f"发现残留假 API Key：{p}"
        assert fake_mail_secret_a.encode() not in raw, f"发现残留假邮箱凭证：{p}"

    # 确认公司 B 的邮箱凭证依然完好
    assert mailbox_store.get_secret(mid_b) == fake_mail_secret_b
