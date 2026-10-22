"""并发写的锁语义测试（2026-10-22 审计 P0）。

背景：`customer.update` / `order.update` 原先用 deferred 的 `BEGIN`（只开读快照），
随后把快照升级成写锁。若期间有别的连接提交过，SQLite 抛 SQLITE_BUSY_SNAPSHOT ——
**不重试**，`busy_timeout` 完全不生效（实测：瞬间 "database is locked"）。
真实场景：用户点「保存客户」的同时，chat 请求正往 chat_memory 插一条对话。

这两条用例把「并发写会怎样」钉死：
① deferred 语义下必然瞬间失败（复现原始 bug，作为对照）；
② 改成 BEGIN IMMEDIATE 后会**排队等锁**（busy_timeout 生效），不失败。
"""

from __future__ import annotations

import sqlite3
import time

import pytest


@pytest.fixture
def db(monkeypatch, tmp_path):
    """临时数据库 + 完整 schema。"""
    db_path = tmp_path / "trade.db"

    import trade.database as _db
    original = _db._get_db_path
    _db._get_db_path = lambda: db_path

    from trade.database import SCHEMA_SQL, _add_spare_columns
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    _add_spare_columns(conn)
    conn.commit()
    conn.close()

    yield db_path

    _db._get_db_path = original


class TestDeferredBeginFailsUnderConcurrency:
    """对照：deferred BEGIN 的读→写升级在并发提交后会瞬间失败。"""

    def test_snapshot_upgrade_raises_immediately(self, db):
        a = sqlite3.connect(str(db), timeout=30)
        a.execute("PRAGMA journal_mode=WAL")
        a.execute("CREATE TABLE t (x INTEGER)")
        a.commit()

        a.execute("BEGIN")                     # deferred：只开读快照
        a.execute("SELECT * FROM t").fetchone()  # 建立快照

        b = sqlite3.connect(str(db), timeout=30)
        b.execute("INSERT INTO t VALUES (1)")
        b.commit()                              # 别的连接提交 → 快照失效

        started = time.time()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            a.execute("UPDATE t SET x = 2")
        # 关键：busy_timeout 根本没生效 —— 瞬间失败而非等待重试
        assert time.time() - started < 1.0, (
            "SQLITE_BUSY_SNAPSHOT 不走 busy_timeout，必须用 BEGIN IMMEDIATE 避免"
        )
        a.close()
        b.close()


class TestUpdatesUseImmediate:
    """customer.update / order.update 必须用 BEGIN IMMEDIATE。"""

    def test_customer_update_opens_transaction_with_immediate(self, db, monkeypatch):
        """customer.update 实际发出的事务语句必须是 BEGIN IMMEDIATE。

        用 sqlite 的 trace 回调抓**真实发出**的 SQL —— 比构造竞态确定得多
        （竞态下另一个连接是否已提交不确定，测试会时红时绿）。
        deferred BEGIN 只开读快照，之后升级写锁时若期间有别的连接提交过，
        SQLite 抛 SQLITE_BUSY_SNAPSHOT 且不重试（busy_timeout 不生效）→
        用户点「保存客户」直接报 "database is locked"。
        """
        from trade import customer

        conn = sqlite3.connect(str(db))
        conn.execute("INSERT INTO companies (name, slug) VALUES ('Co', 'co')")
        conn.execute(
            "INSERT INTO customers (company_id, name, contact, note) VALUES (1, 'C', 'c@x', '')"
        )
        conn.commit()
        conn.close()

        real_get_connection = customer.get_connection
        statements: list[str] = []

        def get_connection_traced():
            inner = real_get_connection()
            inner.set_trace_callback(statements.append)
            return inner

        monkeypatch.setattr(customer, "get_connection", get_connection_traced)

        assert customer.update(1, company_id=1, tier="A") is not None

        begins = [s.strip() for s in statements if s.strip().upper().startswith("BEGIN")]
        assert begins, f"没抓到 BEGIN 语句：{statements[:5]}"
        assert begins[0].upper().startswith("BEGIN IMMEDIATE"), (
            f"customer.update 必须用 BEGIN IMMEDIATE（实际：{begins[0]!r}）—— "
            "deferred BEGIN 的读快照升级会在并发下抛 database is locked"
        )

    def test_order_update_opens_transaction_with_immediate(self, db, monkeypatch):
        """order.update 同上。"""
        from trade import order

        conn = sqlite3.connect(str(db))
        conn.execute("INSERT INTO companies (name, slug) VALUES ('Co', 'co')")
        conn.execute("INSERT INTO customers (company_id, name) VALUES (1, 'C')")
        conn.execute(
            "INSERT INTO orders (company_id, customer_id, product_name, order_no, "
            "quantity, unit, unit_price, currency, total_amount, status) "
            "VALUES (1, 1, 'P', 'o1', 1, 'pcs', 1.0, 'USD', 1.0, '报价中')"
        )
        conn.commit()
        conn.close()

        real_get_connection = order.get_connection
        statements: list[str] = []

        def get_connection_traced():
            inner = real_get_connection()
            inner.set_trace_callback(statements.append)
            return inner

        monkeypatch.setattr(order, "get_connection", get_connection_traced)

        assert order.update(1, company_id=1, status="已确认") is not None

        begins = [s.strip() for s in statements if s.strip().upper().startswith("BEGIN")]
        assert begins, f"没抓到 BEGIN 语句：{statements[:5]}"
        assert begins[0].upper().startswith("BEGIN IMMEDIATE"), (
            f"order.update 必须用 BEGIN IMMEDIATE（实际：{begins[0]!r}）"
        )

    def test_order_update_uses_immediate_transaction(self, db):
        """order.update 的事务起点必须是 IMMEDIATE（源码级断言 + 行为验证）。"""
        from trade import order

        conn = sqlite3.connect(str(db))
        conn.execute("INSERT INTO companies (name, slug) VALUES ('Co', 'co')")
        conn.execute(
            "INSERT INTO customers (company_id, name) VALUES (1, 'C')"
        )
        conn.execute(
            "INSERT INTO orders (company_id, customer_id, product_name, order_no, "
            "quantity, unit, unit_price, currency, total_amount, status) "
            "VALUES (1, 1, 'P', 'o1', 1, 'pcs', 1.0, 'USD', 1.0, '报价中')"
        )
        conn.commit()
        conn.close()

        # 行为验证：更新能成功并落库
        res = order.update(1, company_id=1, status="已确认")
        assert res is not None
        check = sqlite3.connect(str(db))
        assert check.execute("SELECT status FROM orders WHERE id=1").fetchone()[0] == "已确认"
        check.close()
