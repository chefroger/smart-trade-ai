"""订单明细行（一单多商品）— 表结构、迁移回填、摘要口径、API 与上下文。

设计口径：
- order_items 是商品行的事实来源；orders 上的五列是自动同步的摘要，
  供客户简报 / 搜索 / 列表 / 旧 UI 读取。
- 单行时摘要 = 该行；多行时数量只在单位一致且都有数量时求和，
  总额只在**所有行都有总额**时求和（任一行待谈 → NULL，不展示部分合计）。
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def db(monkeypatch, tmp_path):
    """临时库：直接跑 SCHEMA_SQL（与 test_order.py 同一建库方式）。"""
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


def _mk(db):
    from trade import company, customer
    co = company.create(name="C", slug="c1")
    cust = customer.create("K", company_id=co["id"])
    return co, cust


class TestOrderItemsTable:
    def test_table_and_index_exist(self, db):
        conn = sqlite3.connect(str(db))
        try:
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            indexes = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
        finally:
            conn.close()
        assert "order_items" in tables
        assert "idx_order_items_order" in indexes

    def test_cascade_delete_removes_items(self, db):
        from trade import order

        co, cust = _mk(db)
        o = order.create(
            company_id=co["id"], customer_id=cust["id"], product_name="A",
            quantity=1, unit_price=10,
        )
        assert order.get(o["id"], company_id=co["id"])["items"]

        order.delete(o["id"], company_id=co["id"])

        conn = sqlite3.connect(str(db))
        try:
            left = conn.execute(
                "SELECT COUNT(*) FROM order_items WHERE order_id = ?", (o["id"],),
            ).fetchone()[0]
        finally:
            conn.close()
        assert left == 0


class TestMigrationBackfill:
    def test_backfill_runs_once_and_is_idempotent(self, monkeypatch, tmp_path):
        """迁移只回填一次：用户删光明细后重启不会被复活。"""
        import trade.database as dbm

        db_path = tmp_path / "trade.db"
        monkeypatch.setattr(dbm, "_get_db_path", lambda: db_path)
        monkeypatch.setattr(dbm, "_backup_db", lambda p: None)

        dbm.init_db()  # 全新库

        conn = dbm.get_connection()
        try:
            conn.execute(
                "INSERT INTO companies (name, slug) VALUES ('C', 'c1')"
            )
            company_id = conn.execute("SELECT id FROM companies").fetchone()[0]
            conn.execute(
                "INSERT INTO customers (company_id, name) VALUES (?, 'K')",
                (company_id,),
            )
            customer_id = conn.execute("SELECT id FROM customers").fetchone()[0]
            # 模拟迁移前的历史订单：只有头字段，没有明细
            conn.execute(
                "INSERT INTO orders (company_id, customer_id, product_name, "
                "quantity, unit_price, currency, total_amount) "
                "VALUES (?, ?, 'Legacy', 2, 3, 'USD', 6)",
                (company_id, customer_id),
            )
            order_id = conn.execute("SELECT id FROM orders").fetchone()[0]
            conn.execute("DELETE FROM schema_migrations WHERE version = 1")
            conn.commit()
        finally:
            conn.close()

        dbm.init_db()  # 第二次：执行迁移回填

        conn = dbm.get_connection()
        try:
            rows = conn.execute(
                "SELECT product_name, quantity, unit_price, total_amount "
                "FROM order_items WHERE order_id = ?", (order_id,),
            ).fetchall()
        finally:
            conn.close()
        assert len(rows) == 1
        assert rows[0][0] == "Legacy"
        assert rows[0][3] == 6

        # 用户主动删光明细 → 再启动不能被复活
        conn = dbm.get_connection()
        try:
            conn.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
            conn.commit()
        finally:
            conn.close()

        dbm.init_db()

        conn = dbm.get_connection()
        try:
            left = conn.execute(
                "SELECT COUNT(*) FROM order_items WHERE order_id = ?", (order_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        assert left == 0, "迁移已记账，不得每次启动都重新回填"


class TestMultiItemCreate:
    def test_three_items_summary(self, db):
        from trade import order

        co, cust = _mk(db)
        o = order.create(
            company_id=co["id"], customer_id=cust["id"], order_no="PO-1",
            items=[
                {"product_name": "面膜", "quantity": 1000, "unit": "盒",
                 "unit_price": 3.5},
                {"product_name": "精华", "quantity": 500, "unit": "盒",
                 "unit_price": 12},
                {"product_name": "唇膏", "quantity": 200, "unit": "支",
                 "unit_price": 6},
            ],
        )

        assert len(o["items"]) == 3
        # 单位不一致（盒 vs 支）→ 头数量不求和
        assert o["quantity"] is None
        assert o["unit"] == ""
        # 三行都有总额 → 合计
        assert o["total_amount"] == pytest.approx(3500 + 6000 + 1200)
        assert o["unit_price"] is None, "多行时头单价无意义"
        assert o["product_name"] == "面膜 / 精华 / 唇膏", "3 项以内全列出"

    def test_single_item_summary_matches_flat(self, db):
        from trade import order

        co, cust = _mk(db)
        o = order.create(
            company_id=co["id"], customer_id=cust["id"],
            items=[{"product_name": "面膜", "quantity": 10, "unit": "盒",
                    "unit_price": 2}],
        )

        assert o["product_name"] == "面膜"
        assert o["quantity"] == 10
        assert o["unit_price"] == 2
        assert o["total_amount"] == 20

    def test_any_pending_line_makes_total_null(self, db):
        """任一行单价待谈 → 头合计 NULL（不展示部分合计）。"""
        from trade import order

        co, cust = _mk(db)
        o = order.create(
            company_id=co["id"], customer_id=cust["id"],
            items=[
                {"product_name": "A", "quantity": 10, "unit_price": 5},
                {"product_name": "B", "quantity": 20,
                 "unit_price": None, "total_amount": None},
            ],
        )

        assert o["total_amount"] is None
        assert o["items"][1]["unit_price"] is None

    def test_uniform_units_sum_quantity(self, db):
        from trade import order

        co, cust = _mk(db)
        o = order.create(
            company_id=co["id"], customer_id=cust["id"],
            items=[
                {"product_name": "A", "quantity": 10, "unit": "盒",
                 "unit_price": 5},
                {"product_name": "B", "quantity": 20, "unit": "盒",
                 "unit_price": 2},
            ],
        )

        assert o["quantity"] == 30
        assert o["unit"] == "盒"

    def test_missing_product_name_rejected(self, db):
        from trade import order

        co, cust = _mk(db)
        with pytest.raises(ValueError, match="品名"):
            order.create(
                company_id=co["id"], customer_id=cust["id"],
                items=[{"product_name": "  ", "quantity": 1}],
            )

    def test_empty_items_rejected(self, db):
        from trade import order

        co, cust = _mk(db)
        with pytest.raises(ValueError):
            order.create(company_id=co["id"], customer_id=cust["id"], items=[])

    def test_legacy_flat_create_equals_single_item(self, db):
        from trade import order

        co, cust = _mk(db)
        o = order.create(
            company_id=co["id"], customer_id=cust["id"], product_name="Widget",
            quantity=2, unit_price=3,
        )

        assert len(o["items"]) == 1
        assert o["items"][0]["product_name"] == "Widget"
        assert o["total_amount"] == 6


class TestUpdateItems:
    def test_replace_items_and_resummarize(self, db):
        from trade import order

        co, cust = _mk(db)
        o = order.create(
            company_id=co["id"], customer_id=cust["id"], product_name="A",
            quantity=1, unit_price=10,
        )

        updated = order.update(
            o["id"], company_id=co["id"],
            items=[
                {"product_name": "A", "quantity": 2, "unit_price": 10},
                {"product_name": "B", "quantity": 3, "unit_price": 4},
            ],
        )

        assert len(updated["items"]) == 2
        assert updated["total_amount"] == pytest.approx(32)
        assert "等2项" in updated["product_name"] or "A / B" in updated["product_name"]

    def test_flat_amounts_apply_to_single_item(self, db):
        """旧 UI 全量 PUT：平铺金额落到唯一明细行。"""
        from trade import order

        co, cust = _mk(db)
        o = order.create(
            company_id=co["id"], customer_id=cust["id"], product_name="A",
            quantity=1, unit_price=10,
        )

        updated = order.update(o["id"], company_id=co["id"], quantity=5)

        assert updated["items"][0]["quantity"] == 5
        assert updated["quantity"] == 5

    def test_flat_amounts_on_multi_item_consistent_are_ignored(self, db):
        """多行订单：平铺字段与摘要一致（旧 UI 全量 body）→ 允许改状态。"""
        from trade import order

        co, cust = _mk(db)
        o = order.create(
            company_id=co["id"], customer_id=cust["id"],
            items=[
                {"product_name": "A", "quantity": 2, "unit": "盒", "unit_price": 10},
                {"product_name": "B", "quantity": 3, "unit": "盒", "unit_price": 4},
            ],
        )

        updated = order.update(
            o["id"], company_id=co["id"],
            quantity=o["quantity"], total_amount=o["total_amount"],
            status="已下单",
        )

        assert updated["status"] == "已下单"
        assert len(updated["items"]) == 2

    def test_flat_amounts_on_multi_item_conflict_rejected(self, db):
        from trade import order

        co, cust = _mk(db)
        o = order.create(
            company_id=co["id"], customer_id=cust["id"],
            items=[
                {"product_name": "A", "quantity": 2, "unit": "盒", "unit_price": 10},
                {"product_name": "B", "quantity": 3, "unit": "盒", "unit_price": 4},
            ],
        )

        with pytest.raises(ValueError, match="按行"):
            order.update(o["id"], company_id=co["id"], total_amount=999)

    def test_zero_items_lazily_materializes(self, db):
        """迁移前直插的订单（无明细）：平铺更新时惰性补一行。"""
        from trade import order

        co, cust = _mk(db)
        conn = sqlite3.connect(str(db))
        try:
            cur = conn.execute(
                "INSERT INTO orders (company_id, customer_id, product_name, "
                "quantity, unit_price, currency, total_amount) "
                "VALUES (?, ?, 'Old', 1, 2, 'USD', 2)",
                (co["id"], cust["id"]),
            )
            order_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        updated = order.update(order_id, company_id=co["id"], quantity=3)

        assert len(updated["items"]) == 1
        assert updated["items"][0]["quantity"] == 3


class TestItemsApi:
    def _mk(self, db):
        return _mk(db)

    def test_create_with_items(self, db):
        from trade.api.models import OrderCreate, OrderItemIn
        from trade.api.orders import create_order

        co, cust = self._mk(db)
        payload = OrderCreate(
            customer_id=cust["id"],
            currency="USD",
            items=[
                OrderItemIn(product_name="A", quantity=2, unit_price=10),
                OrderItemIn(product_name="B", quantity=3, unit_price=4),
            ],
        )

        o = create_order(payload, cid=co["id"])

        assert len(o["items"]) == 2
        assert o["total_amount"] == pytest.approx(32)

    def test_create_without_name_or_items_rejected(self, db):
        from fastapi import HTTPException

        from trade.api.models import OrderCreate
        from trade.api.orders import create_order

        co, cust = self._mk(db)
        with pytest.raises(HTTPException) as exc:
            create_order(OrderCreate(customer_id=cust["id"]), cid=co["id"])

        assert exc.value.status_code == 400

    def test_empty_items_rejected(self, db):
        from fastapi import HTTPException

        from trade.api.models import OrderCreate
        from trade.api.orders import create_order

        co, cust = self._mk(db)
        with pytest.raises(HTTPException) as exc:
            create_order(
                OrderCreate(customer_id=cust["id"], items=[]), cid=co["id"],
            )

        assert exc.value.status_code == 400

    def test_negative_item_line_rejected(self, db):
        from fastapi import HTTPException

        from trade.api.models import OrderCreate, OrderItemIn
        from trade.api.orders import create_order

        co, cust = self._mk(db)
        with pytest.raises(HTTPException) as exc:
            create_order(
                OrderCreate(
                    customer_id=cust["id"],
                    items=[
                        OrderItemIn(product_name="A", quantity=1, unit_price=1),
                        OrderItemIn(product_name="B", quantity=-1, unit_price=1),
                    ],
                ),
                cid=co["id"],
            )

        assert exc.value.status_code == 400
        assert "第 2 行" in exc.value.detail

    def test_update_replaces_items(self, db):
        from trade.api.models import OrderCreate, OrderItemIn, OrderUpdate
        from trade.api.orders import create_order, update_order

        co, cust = self._mk(db)
        o = create_order(
            OrderCreate(customer_id=cust["id"], product_name="A",
                        quantity=1, unit_price=10),
            cid=co["id"],
        )

        updated = update_order(
            o["id"],
            OrderUpdate(items=[
                OrderItemIn(product_name="A", quantity=2, unit_price=10),
                OrderItemIn(product_name="C", quantity=1, unit_price=7),
            ]),
            cid=co["id"],
        )

        assert [i["product_name"] for i in updated["items"]] == ["A", "C"]
        assert updated["total_amount"] == pytest.approx(27)

    def test_cross_company_get_fails_closed(self, db):
        from trade import company as company_module
        from trade import order

        co, cust = _mk(db)
        other = company_module.create(name="Other", slug="other")
        o = order.create(
            company_id=co["id"], customer_id=cust["id"], product_name="A",
            quantity=1, unit_price=1,
        )

        assert order.get(o["id"], company_id=other["id"]) is None
        assert order.list_by_company(other["id"]) == []


class TestContextFormatting:
    def test_multi_item_lines_listed(self, db):
        from trade import order

        co, cust = _mk(db)
        order.create(
            company_id=co["id"], customer_id=cust["id"],
            items=[
                {"product_name": "面膜", "quantity": 1000, "unit": "盒",
                 "unit_price": 3.5},
                {"product_name": "精华", "quantity": 500, "unit": "盒",
                 "unit_price": None, "total_amount": None},
            ],
        )
        rows = order.list_by_customer(cust["id"], company_id=co["id"])

        text = order._format_order_context(rows, {"name": "K", "contact": "Li"})

        assert "2 项商品" in text
        assert "面膜" in text and "精华" in text
        assert "单价待谈" in text
        assert "合计：待谈" in text

    def test_search_matches_any_item_name(self, db):
        from trade import order

        co, cust = _mk(db)
        order.create(
            company_id=co["id"], customer_id=cust["id"],
            items=[
                {"product_name": "AAA", "quantity": 1, "unit_price": 1},
                {"product_name": "ZZZ", "quantity": 1, "unit_price": 1},
                {"product_name": "YYY", "quantity": 1, "unit_price": 1},
                {"product_name": "隐藏品", "quantity": 1, "unit_price": 1},
            ],
        )

        # 第 4 项不在摘要（只拼前 3 项）里，必须靠明细匹配找到
        rows = order._search_by_customer_and_product(cust["id"], "隐藏")

        assert len(rows) == 1
        assert len(rows[0]["items"]) == 4

        summary = order.list_by_customer(cust["id"], company_id=co["id"])[0]
        assert "等4项" in summary["product_name"], "超过 3 项时摘要带数量提示"
