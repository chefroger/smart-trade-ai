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


class TestCompanyScopeRequired:
    """P2-30：不传公司时不能裸 id 查/改/删（fail-closed）。"""

    def test_order_operations_fail_closed(self, db):
        from trade import order
        co = _mk_company("Co", "co")
        cust = _mk_customer(co["id"], "Cust")
        o = order.create(co["id"], cust["id"], "Widget")

        assert order.get(o["id"]) is None
        assert order.update(o["id"], notes="x") is None
        assert order.delete(o["id"]) is False
        assert order.list_by_customer(cust["id"]) == []
        assert order.link_library(o["id"], 1) is False
        assert order.unlink_library(o["id"], 1) is False

    def test_library_operations_fail_closed(self, db):
        from trade import library
        co = _mk_company("Co", "co")
        lib = library.create("Lib", "/tmp/lib-failclosed", company_id=co["id"])

        assert library.get(lib["id"]) is None
        assert library.update(lib["id"], name="X") is None
        assert library.delete(lib["id"]) is False


class TestConversationSaveScope:
    """P1-19 防御纵深：保存层也不能把别家客户/库写进本公司对话。"""

    def test_foreign_customer_and_library_are_dropped(self, db, tmp_path):
        from trade import chat_memory
        co1 = _mk_company("Co1", "co1")
        co2 = _mk_company("Co2", "co2")
        cust1 = _mk_customer(co1["id"], "Cust1")
        cust2 = _mk_customer(co2["id"], "Cust2")
        lib2 = _mk_library(co2["id"], "Lib2", str(tmp_path / "lib2"))

        row = chat_memory.save_with_context(
            company_id=co1["id"], query="hello", response="world",
            customer_id=cust2["id"], library_id=lib2["id"],
            retain_to_memory=False,
        )

        assert row["customer_id"] is None
        assert row["library_id"] is None
        # 合规的关联仍然保留
        ok = chat_memory.save_with_context(
            company_id=co1["id"], query="hello", response="world",
            customer_id=cust1["id"], retain_to_memory=False,
        )
        assert ok["customer_id"] == cust1["id"]


class TestReconcileAmounts:
    """P1-15：数量×单价 与 总金额 必须一致（总金额为空时自动算出）。"""

    def test_blank_total_is_computed(self):
        from trade import order
        qty, price, total = order.reconcile_amounts(10, 3.5, 0)
        assert (qty, price, total) == (10.0, 3.5, 35.0)

    def test_none_total_is_computed(self):
        from trade import order
        assert order.reconcile_amounts(3, 2, None)[2] == 6.0

    def test_consistent_triplet_passes(self):
        from trade import order
        assert order.reconcile_amounts(10, 3.5, 35.0) == (10.0, 3.5, 35.0)

    def test_cent_rounding_noise_tolerated(self):
        from trade import order
        # 0.01 以内视为舍入噪声，不拦
        assert order.reconcile_amounts(3, 3.333, 9.999)[2] == 9.999

    def test_contradiction_raises(self):
        from trade import order
        with pytest.raises(ValueError, match="不一致"):
            order.reconcile_amounts(10, 3.5, 999)

    def test_missing_price_keeps_total(self):
        from trade import order
        # 单价缺失时无法校验（例如只录了报价总额），原样放行
        assert order.reconcile_amounts(10, 0, 500)[2] == 500


class TestOrderStatusMachine:
    """P1-15：只允许 报价中→已下单→已出货→已完成；取消仅发货前；终态不可再变。"""

    def test_forward_chain_allowed(self):
        from trade import order
        assert order.can_transition_status("报价中", "已下单")
        assert order.can_transition_status("已下单", "已出货")
        assert order.can_transition_status("已出货", "已完成")

    def test_same_status_allowed(self):
        from trade import order
        for status in order.ORDER_STATUSES:
            assert order.can_transition_status(status, status)

    def test_backward_transitions_blocked(self):
        from trade import order
        assert not order.can_transition_status("已完成", "报价中")
        assert not order.can_transition_status("已出货", "已下单")
        assert not order.can_transition_status("已下单", "报价中")

    def test_cancel_only_before_shipping(self):
        from trade import order
        assert order.can_transition_status("报价中", "已取消")
        assert order.can_transition_status("已下单", "已取消")
        assert not order.can_transition_status("已出货", "已取消")

    def test_terminal_states_frozen(self):
        from trade import order
        for target in order.ORDER_STATUSES:
            if target == "已完成":
                continue
            assert not order.can_transition_status("已完成", target)
        assert not order.can_transition_status("已取消", "已出货")

    def test_unknown_legacy_status_is_not_trapped(self):
        from trade import order
        # 历史脏数据（空 / 未知值）不拦，否则用户无法修正旧记录
        assert order.can_transition_status("", "已下单")
        assert order.can_transition_status("已确认", "已出货")


class TestOrderApiValidation:
    """P1-15 端到端：API 层拦截矛盾金额与非法状态迁移。"""

    def _mk(self, db):
        co = _mk_company("Co", "co")
        cust = _mk_customer(co["id"], "Cust")
        return co, cust

    def _create(self, cid, cust_id, **kwargs):
        from trade.api.models import OrderCreate
        from trade.api.orders import create_order
        payload = OrderCreate(
            customer_id=cust_id, product_name="Widget", **kwargs,
        )
        return create_order(payload, cid=cid)

    def test_create_rejects_contradictory_total(self, db):
        from fastapi import HTTPException
        co, cust = self._mk(db)
        with pytest.raises(HTTPException) as exc:
            self._create(co["id"], cust["id"], quantity=10, unit_price=3.5, total_amount=999)
        assert exc.value.status_code == 400
        assert "不一致" in exc.value.detail

    def test_create_computes_blank_total(self, db):
        co, cust = self._mk(db)
        o = self._create(co["id"], cust["id"], quantity=10, unit_price=3.5)
        assert o["total_amount"] == 35.0

    def test_update_rejects_contradictory_amounts(self, db):
        from fastapi import HTTPException

        from trade.api.models import OrderUpdate
        from trade.api.orders import update_order
        co, cust = self._mk(db)
        o = self._create(co["id"], cust["id"], quantity=10, unit_price=3.5)
        with pytest.raises(HTTPException) as exc:
            update_order(o["id"], OrderUpdate(quantity=20), cid=co["id"])
        assert exc.value.status_code == 400
        assert "不一致" in exc.value.detail

    def test_update_blocks_invalid_transition(self, db):
        from fastapi import HTTPException

        from trade.api.models import OrderUpdate
        from trade.api.orders import update_order
        co, cust = self._mk(db)
        o = self._create(co["id"], cust["id"], status="已完成")
        with pytest.raises(HTTPException) as exc:
            update_order(o["id"], OrderUpdate(status="报价中"), cid=co["id"])
        assert exc.value.status_code == 400
        assert "已完成" in exc.value.detail

    def test_update_allows_forward_transition(self, db):
        from trade.api.models import OrderUpdate
        from trade.api.orders import update_order
        co, cust = self._mk(db)
        o = self._create(co["id"], cust["id"])
        updated = update_order(o["id"], OrderUpdate(status="已下单"), cid=co["id"])
        assert updated["status"] == "已下单"

    def test_update_can_clear_optional_fields(self, db):
        """显式传 null 表示清空；不传表示保持不变（审计 P2-28）。"""
        from trade.api.models import OrderUpdate
        from trade.api.orders import update_order
        co, cust = self._mk(db)
        o = self._create(co["id"], cust["id"], order_no="PO-1", notes="旧备注")

        cleared = update_order(
            o["id"], OrderUpdate(order_no=None, notes=None), cid=co["id"],
        )

        assert cleared["order_no"] is None
        assert cleared["notes"] is None

    def test_update_null_required_field_is_ignored(self, db):
        """非可清空字段（品名/数量）传 null 不能把数据写坏。"""
        from trade.api.models import OrderUpdate
        from trade.api.orders import update_order
        co, cust = self._mk(db)
        o = self._create(co["id"], cust["id"], quantity=10, unit_price=3.5)

        updated = update_order(
            o["id"], OrderUpdate(quantity=None, product_name=None), cid=co["id"],
        )

        assert updated["quantity"] == 10
        assert updated["product_name"] == "Widget"

    def test_negative_amount_returns_400(self, db):
        """负数不再静默归零，直接 400（审计 P2-25）。"""
        from fastapi import HTTPException

        from trade.api.models import OrderUpdate
        from trade.api.orders import update_order
        co, cust = self._mk(db)
        with pytest.raises(HTTPException) as exc:
            self._create(co["id"], cust["id"], quantity=-5)
        assert exc.value.status_code == 400
        assert "数量" in exc.value.detail

        o = self._create(co["id"], cust["id"], quantity=1)
        with pytest.raises(HTTPException) as exc2:
            update_order(o["id"], OrderUpdate(unit_price=-1), cid=co["id"])
        assert exc2.value.status_code == 400
        assert "单价" in exc2.value.detail

    def test_notes_edit_on_completed_order_still_works(self, db):
        from trade.api.models import OrderUpdate
        from trade.api.orders import update_order
        co, cust = self._mk(db)
        o = self._create(co["id"], cust["id"], status="已完成")
        updated = update_order(o["id"], OrderUpdate(notes="归档备注"), cid=co["id"])
        assert updated["notes"] == "归档备注"
