"""订单模块测试 — 覆盖 CRUD、客户归属校验、文档库关联隔离（含 P2-2 回归）。"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def db(monkeypatch, tmp_path):
    """创建临时数据库并初始化 schema。"""
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


def _mk_company(name, slug):
    from trade import company
    return company.create(name=name, slug=slug)


def _mk_customer(company_id, name):
    from trade import customer
    return customer.create(name, company_id=company_id)


def _mk_library(company_id, name, root):
    from trade import library
    return library.create(name, root, company_id=company_id)


class TestOrderCRUD:
    def test_create_order(self, db, tmp_path):
        from trade import order
        co = _mk_company("Co", "co")
        cust = _mk_customer(co["id"], "Cust")
        o = order.create(co["id"], cust["id"], "Widget", quantity=10, unit_price=5.0)
        assert o["id"] > 0
        assert o["product_name"] == "Widget"
        assert o["quantity"] == 10

    def test_create_order_customer_not_in_company(self, db):
        import pytest as _pytest

        from trade import order
        co1 = _mk_company("Co1", "co1")
        co2 = _mk_company("Co2", "co2")
        cust2 = _mk_customer(co2["id"], "Cust2")
        # 客户属于 co2，但用 co1 创建订单 → 应拒绝
        with _pytest.raises(ValueError, match="does not belong"):
            order.create(co1["id"], cust2["id"], "Widget")

    def test_get_and_update(self, db, tmp_path):
        from trade import order
        co = _mk_company("Co", "co")
        cust = _mk_customer(co["id"], "Cust")
        o = order.create(co["id"], cust["id"], "Widget")
        updated = order.update(o["id"], company_id=co["id"], product_name="Gadget", quantity=99)
        assert updated["product_name"] == "Gadget"
        assert updated["quantity"] == 99

    def test_delete(self, db, tmp_path):
        from trade import order
        co = _mk_company("Co", "co")
        cust = _mk_customer(co["id"], "Cust")
        o = order.create(co["id"], cust["id"], "Widget")
        assert order.delete(o["id"], company_id=co["id"]) is True
        assert order.get(o["id"], company_id=co["id"]) is None

    def test_get_company_scoped(self, db, tmp_path):
        from trade import order
        co1 = _mk_company("Co1", "co1")
        co2 = _mk_company("Co2", "co2")
        cust1 = _mk_customer(co1["id"], "Cust1")
        o = order.create(co1["id"], cust1["id"], "Widget")
        # co2 无法读到 co1 的订单
        assert order.get(o["id"], company_id=co2["id"]) is None


class TestOrderLibraryIsolation:
    """P2-2 回归：unlink_library 必须校验库归属公司。"""

    def test_link_and_unlink(self, db, tmp_path):
        from trade import order
        co = _mk_company("Co", "co")
        cust = _mk_customer(co["id"], "Cust")
        lib = _mk_library(co["id"], "Lib", str(tmp_path / "lib"))
        o = order.create(co["id"], cust["id"], "Widget")
        assert order.link_library(o["id"], lib["id"], company_id=co["id"]) is True
        assert order.unlink_library(o["id"], lib["id"], company_id=co["id"]) is True

    def test_unlink_cross_company_blocked(self, db, tmp_path):
        """解绑他公司的库应被拒绝（返回 False）。"""
        from trade import order
        co1 = _mk_company("Co1", "co1")
        co2 = _mk_company("Co2", "co2")
        cust1 = _mk_customer(co1["id"], "Cust1")
        lib2 = _mk_library(co2["id"], "Lib2", str(tmp_path / "lib2"))
        o = order.create(co1["id"], cust1["id"], "Widget")
        # 用 co1 的身份解绑 co2 的库 → 应返回 False（库不归属 co1）
        assert order.unlink_library(o["id"], lib2["id"], company_id=co1["id"]) is False

    def test_unlink_order_not_in_company(self, db, tmp_path):
        from trade import order
        co1 = _mk_company("Co1", "co1")
        co2 = _mk_company("Co2", "co2")
        cust1 = _mk_customer(co1["id"], "Cust1")
        lib1 = _mk_library(co1["id"], "Lib1", str(tmp_path / "lib1"))
        o = order.create(co1["id"], cust1["id"], "Widget")
        # 用 co2 的身份解绑 co1 的订单 → 订单不归属 co2，应返回 False
        assert order.unlink_library(o["id"], lib1["id"], company_id=co2["id"]) is False
