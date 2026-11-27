"""
供应商管理一期 · 第三批（履约侧，一期收官批）验收测试（C1–C11）。

逐条对应任务书 §9 验收用例：
  C1  采购单与单号（CRUD、po_no 手填原样/空生成 PO{id}/改单不可改、五态限制）
  C2  单号对应（按客户 order_no 搜采购单、详情显示号空号 SO{id}+客户名、order_id 过滤）
  C3  从询价单生成（decided+选中行正确生成、amount=选中价×数量、open/无选中行报错、缺价缺量留空）
  C4  提醒口径（逾期与临期今天+3含边界、已出货/完成/无交期不命中、逾期优先、固定日期夹具）
  C5  简报联动（get_today_brief 含 delivery_alerts/count 与 alerts 同口径、无提醒空表、既有四项不变）
  C6  催货话术（upcoming/overdue/cutoff 含事实、cutoff 未入柜或无截关日报错、零副作用）
  C7  拼柜（柜 CRUD 与 code 生成 CG{id}、明细重复加入仅一行、删柜不删采购单、待拼池口径）
  C8  倒计时（days_to_cutoff 正/零/负/null 四种情况，固定日期夹具）
  C9  公司隔离（采购单、拼柜、明细、提醒跨公司一律 404 或查不到）
  C10 导出导入（三表导出、连导两次不增行、items 双外键与 order_id/rfq_id 映射正确）
  C11 AI 工具（supplier_delivery_alerts 与 API 同结果、跨公司零泄漏、只读与内部声明）
"""

from __future__ import annotations

import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trade import agent_context
from trade import brief as brief_mod
from trade import company as company_mod
from trade import customer as customer_mod
from trade import database as db_mod
from trade import license as license_mod
from trade import order as order_mod
from trade import purchase as purchase_mod
from trade import rfq as rfq_mod
from trade import supplier as supplier_mod
from trade.api import deps as deps_mod
from trade.api import router as trade_router
from trade.company.transfer import exporter, importer
from trade.hermes_chat_memory_plugin import tools as plugin_tools


@pytest.fixture
def env(monkeypatch, tmp_path):
    """隔离临时数据库、工作目录与 FastAPI 测试客户端。"""
    trade_home = tmp_path / "trade_home"
    trade_home.mkdir(parents=True, exist_ok=True)
    db_path = trade_home / "data" / "trade.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("TRADE_HOME", str(trade_home))
    monkeypatch.setattr(db_mod, "_get_db_path", lambda: db_path)
    monkeypatch.setattr(company_mod.crud, "TRADE_HOME", trade_home)
    # 供应商模块为付费能力：既有第三批功能验收在已激活（active）状态下运行
    monkeypatch.setattr(license_mod, "license_state", lambda: ("active", ""))

    def _fake_work_dir(name, slug, suggested_name=""):
        wd = tmp_path / "work" / (slug or "co")
        wd.mkdir(parents=True, exist_ok=True)
        return wd, True

    monkeypatch.setattr(company_mod.workdir, "_setup_work_directory", _fake_work_dir)
    (tmp_path / "work").mkdir(parents=True, exist_ok=True)

    db_mod.init_db()

    app = FastAPI()
    app.include_router(trade_router, prefix="/api/trade")
    token = "test-purchase-token"
    deps_mod.set_session_token(token)
    deps_mod._ACTIVE_COMPANY.clear()
    client = TestClient(app)

    co_a = company_mod.create(name="Company Alpha", slug="alpha")
    co_b = company_mod.create(name="Company Beta", slug="beta")

    def headers(cid: int) -> dict[str, str]:
        return {
            "X-Hermes-Session-Token": token,
            "X-Company-ID": str(cid),
        }

    return {
        "client": client,
        "db_path": db_path,
        "tmp_path": tmp_path,
        "co_a": co_a,
        "co_b": co_b,
        "headers": headers,
    }


# ==============================================================================
# C1 采购单与单号
# ==============================================================================


def test_c1_po_crud_number_rules_and_five_states(env):
    """C1：CRUD 正常；手填 po_no 用原样、空生成 PO{id}、改单不可改号；仅允许五态。"""
    client = env["client"]
    cid = env["co_a"]["id"]
    hdr = env["headers"](cid)
    sup = supplier_mod.create_supplier(cid, name="恒信铸造厂")

    # 1) 空 po_no → 自动生成 PO{id}
    r1 = client.post(
        "/api/trade/purchase-orders",
        json={"supplier_id": sup["id"], "product_name": "铸铁阀体", "quantity": 100, "unit": "件"},
        headers=hdr,
    )
    assert r1.status_code == 200
    po1 = r1.json()
    assert po1["po_no"] == f"PO{po1['id']}"
    assert po1["status"] == "已下单"
    assert po1["ordered_at"] != ""

    # 2) 手填 po_no → 保留原样
    r2 = client.post(
        "/api/trade/purchase-orders",
        json={"supplier_id": sup["id"], "product_name": "不锈钢法兰", "po_no": "CG-2026-008"},
        headers=hdr,
    )
    assert r2.status_code == 200
    po2 = r2.json()
    assert po2["po_no"] == "CG-2026-008"

    # 3) 改单不许改 po_no（传不同号返回 400；传其他字段正常更新）
    r_bad_no = client.put(
        f"/api/trade/purchase-orders/{po1['id']}",
        json={"po_no": "HACK-999"},
        headers=hdr,
    )
    assert r_bad_no.status_code == 400
    assert client.get(f"/api/trade/purchase-orders/{po1['id']}", headers=hdr).json()["po_no"] == f"PO{po1['id']}"

    # 4) 状态仅允许五态
    for st in ("生产中", "待出货", "已出货", "完成"):
        r_st = client.put(f"/api/trade/purchase-orders/{po1['id']}", json={"status": st}, headers=hdr)
        assert r_st.status_code == 200
        assert r_st.json()["status"] == st
    assert client.put(
        f"/api/trade/purchase-orders/{po1['id']}",
        json={"status": "已取消"},
        headers=hdr,
    ).status_code == 400

    # 5) 删除正常
    assert client.delete(f"/api/trade/purchase-orders/{po2['id']}", headers=hdr).status_code == 200
    assert client.get(f"/api/trade/purchase-orders/{po2['id']}", headers=hdr).status_code == 404


# ==============================================================================
# C2 单号对应（客户订单 order_no ↔ 采购单）
# ==============================================================================


def test_c2_order_number_mapping_and_search(env):
    """C2：按客户 order_no 搜到关联采购单；空 order_no 显示 SO{id}；order_id 过滤正确。"""
    client = env["client"]
    cid = env["co_a"]["id"]
    hdr = env["headers"](cid)

    cust = customer_mod.create("Hamburg Industrial GmbH", "Klaus", company_id=cid)
    sup = supplier_mod.create_supplier(cid, name="精工阀门厂")

    # 订单 1：有手填 order_no
    ord_named = order_mod.create(
        cid, cust["id"], product_name="球阀", order_no="PI-2026-099", quantity=50, unit="台",
    )
    # 订单 2：空 order_no
    ord_blank = order_mod.create(
        cid, cust["id"], product_name="止回阀", order_no="", quantity=30, unit="台",
    )

    po_a = purchase_mod.create_purchase_order(
        cid, supplier_id=sup["id"], order_id=ord_named["id"], product_name="球阀",
    )
    po_b = purchase_mod.create_purchase_order(
        cid, supplier_id=sup["id"], order_id=ord_blank["id"], product_name="止回阀",
    )

    # 用客户订单号 PI-2026-099 作为 q 搜索采购单
    found = client.get("/api/trade/purchase-orders?q=PI-2026-099", headers=hdr).json()
    assert len(found) == 1
    assert found[0]["id"] == po_a["id"]
    assert found[0]["order_display_no"] == "PI-2026-099"
    assert found[0]["customer_name"] == "Hamburg Industrial GmbH"

    # 空 order_no 的订单在详情与列表中显示 SO{order_id}
    detail_b = client.get(f"/api/trade/purchase-orders/{po_b['id']}", headers=hdr).json()
    assert detail_b["order_display_no"] == f"SO{ord_blank['id']}"
    assert detail_b["customer_name"] == "Hamburg Industrial GmbH"

    # 客户订单详情侧关联采购单查询接口（order_id 过滤）
    by_ord = client.get(f"/api/trade/purchase-orders?order_id={ord_named['id']}", headers=hdr).json()
    assert [p["id"] for p in by_ord] == [po_a["id"]]


# ==============================================================================
# C3 从询价单生成采购单
# ==============================================================================


def test_c3_create_po_from_rfq(env):
    """C3：decided+选中行正确生成；open 或无选中行报错；缺价缺量 amount 留空。"""
    client = env["client"]
    cid = env["co_a"]["id"]
    hdr = env["headers"](cid)

    sup = supplier_mod.create_supplier(cid, name="华东机电厂")

    # 1) open 状态的询价单 → 报错不建单
    rfq_open = rfq_mod.create_rfq(cid, product_name="步进电机", quantity=20, unit="台")
    assert client.post(
        "/api/trade/purchase-orders/from-rfq",
        json={"rfq_id": rfq_open["id"]},
        headers=hdr,
    ).status_code == 400
    assert purchase_mod.list_purchase_orders(cid) == []

    # 2) decided 但无选中行 → 报错不建单
    rfq_no_sel = rfq_mod.create_rfq(cid, product_name="减速机", quantity=10, unit="台", status="decided")
    assert client.post(
        "/api/trade/purchase-orders/from-rfq",
        json={"rfq_id": rfq_no_sel["id"]},
        headers=hdr,
    ).status_code == 400

    # 3) decided + 有选中行且有价有量 → 正确计算 amount = 单价×数量
    rfq_ok = rfq_mod.create_rfq(cid, product_name="步进电机", spec_model="NEMA23", quantity=25, unit="台")
    resp = rfq_mod.add_rfq_response(rfq_ok["id"], cid, sup["id"])
    rfq_mod.update_rfq_response(resp["id"], cid, responded=1, price_excl_tax=80.0, price_incl_tax=90.4)
    rfq_mod.select_rfq_response(resp["id"], cid)

    r_po = client.post(
        "/api/trade/purchase-orders/from-rfq",
        json={"rfq_id": rfq_ok["id"]},
        headers=hdr,
    )
    assert r_po.status_code == 200
    po = r_po.json()
    assert po["supplier_id"] == sup["id"]
    assert po["rfq_id"] == rfq_ok["id"]
    assert po["product_name"] == "步进电机"
    assert po["spec_model"] == "NEMA23"
    assert po["quantity"] == 25.0
    assert po["amount"] == 2000.0  # 优先不含税价 80 * 25
    assert po["promised_date"] == ""

    # 4) 价格或数量缺失 → amount 留空（绝不编造）
    rfq_noprice = rfq_mod.create_rfq(cid, product_name="定制支架", quantity=50, unit="套")
    resp_np = rfq_mod.add_rfq_response(rfq_noprice["id"], cid, sup["id"])
    rfq_mod.select_rfq_response(resp_np["id"], cid)
    po_np = purchase_mod.create_purchase_order_from_rfq(cid, rfq_noprice["id"])
    assert po_np["amount"] is None


# ==============================================================================
# C4 提醒口径（固定日期夹具）
# ==============================================================================


def test_c4_delivery_alerts_rules_and_sorting(env):
    """C4：逾期与临期(+3天含边界)命中；已出货/完成/无交期不命中；逾期优先；天数准确。"""
    cid = env["co_a"]["id"]
    sup = supplier_mod.create_supplier(cid, name="交期测试厂")
    fixed_today = "2026-11-27"

    # 逾期 5 天
    po_over5 = purchase_mod.create_purchase_order(
        cid, supplier_id=sup["id"], product_name="逾期5天货", promised_date="2026-11-22", status="生产中",
    )
    # 逾期 1 天
    po_over1 = purchase_mod.create_purchase_order(
        cid, supplier_id=sup["id"], product_name="逾期1天货", promised_date="2026-11-26", status="已下单",
    )
    # 今天到期（剩余 0 天）
    po_today = purchase_mod.create_purchase_order(
        cid, supplier_id=sup["id"], product_name="今天到期货", promised_date="2026-11-27", status="待出货",
    )
    # 边界：今天 + 3 天（2026-11-30）→ 命中
    po_edge3 = purchase_mod.create_purchase_order(
        cid, supplier_id=sup["id"], product_name="边界3天货", promised_date="2026-11-30", status="生产中",
    )
    # 今天 + 4 天（2026-12-01）→ 不命中
    purchase_mod.create_purchase_order(
        cid, supplier_id=sup["id"], product_name="4天后货", promised_date="2026-12-01", status="生产中",
    )
    # 已出货 / 完成 / 无交期 → 均不命中
    purchase_mod.create_purchase_order(
        cid, supplier_id=sup["id"], product_name="已出货逾期", promised_date="2026-11-20", status="已出货",
    )
    purchase_mod.create_purchase_order(
        cid, supplier_id=sup["id"], product_name="已完成逾期", promised_date="2026-11-20", status="完成",
    )
    purchase_mod.create_purchase_order(
        cid, supplier_id=sup["id"], product_name="无交期货", promised_date="", status="已下单",
    )

    alerts = purchase_mod.get_delivery_alerts(cid, today_str=fixed_today)
    assert [a["id"] for a in alerts] == [po_over5["id"], po_over1["id"], po_today["id"], po_edge3["id"]]
    assert alerts[0]["is_overdue"] is True and alerts[0]["days_overdue"] == 5 and alerts[0]["days_left"] == 0
    assert alerts[1]["is_overdue"] is True and alerts[1]["days_overdue"] == 1 and alerts[1]["days_left"] == 0
    assert alerts[2]["is_overdue"] is False and alerts[2]["days_overdue"] == 0 and alerts[2]["days_left"] == 0
    assert alerts[3]["is_overdue"] is False and alerts[3]["days_overdue"] == 0 and alerts[3]["days_left"] == 3


# ==============================================================================
# C5 简报联动
# ==============================================================================


def test_c5_today_brief_delivery_alerts_linkage(env):
    """C5：get_today_brief 含 delivery_alerts 与 count 且与 alerts 同口径；既有四项不变。"""
    cid = env["co_a"]["id"]

    # 无提醒时为空列表、既有四项正常
    brief_empty = brief_mod.get_today_brief(cid)
    assert brief_empty["delivery_alerts"] == []
    assert brief_empty["delivery_alert_count"] == 0
    assert brief_empty["overdue_followups"] == 0
    assert brief_empty["pending_shipments"] == 0

    # 新增客户待出货订单 + 一条逾期采购单
    cust = customer_mod.create("Brief Cust", "Li", company_id=cid)
    order_mod.create(cid, cust["id"], product_name="泵体", status="已下单")
    sup = supplier_mod.create_supplier(cid, name="简报测试厂")
    purchase_mod.create_purchase_order(
        cid, supplier_id=sup["id"], product_name="泵体铸件", promised_date="2020-01-01", status="生产中",
    )

    brief = brief_mod.get_today_brief(cid)
    direct = purchase_mod.get_delivery_alerts(cid)
    assert brief["pending_shipments"] == 1
    assert brief["delivery_alert_count"] == len(direct) == 1
    assert [a["id"] for a in brief["delivery_alerts"]] == [a["id"] for a in direct]


# ==============================================================================
# C6 催货话术（零写库副作用）
# ==============================================================================


def test_c6_followup_draft_templates_and_zero_side_effects(env):
    """C6：三 variant 文本含准确事实；cutoff 未入柜/无截关日报错；调用前后库行数无变化。"""
    client = env["client"]
    cid = env["co_a"]["id"]
    hdr = env["headers"](cid)

    sup = supplier_mod.create_supplier(cid, name="信达五金厂")
    supplier_mod.create_contact(cid, sup["id"], name="王总", phone="13800138000", is_primary=1)
    po = purchase_mod.create_purchase_order(
        cid,
        supplier_id=sup["id"],
        po_no="PO-8801",
        product_name="不锈钢合页",
        promised_date="2026-11-29",
        status="生产中",
    )

    # 未入柜时 cutoff 必须报错
    assert client.post(
        f"/api/trade/purchase-orders/{po['id']}/followup-draft",
        json={"variant": "cutoff"},
        headers=hdr,
    ).status_code == 400

    # 加入无截关日的拼柜 → cutoff 仍报错
    cons_nocut = purchase_mod.create_consolidation(cid, code="CG-NOCUT", cutoff_date="", status="组货中")
    purchase_mod.add_consolidation_item(cons_nocut["id"], cid, po["id"])
    assert client.post(
        f"/api/trade/purchase-orders/{po['id']}/followup-draft",
        json={"variant": "cutoff"},
        headers=hdr,
    ).status_code == 400

    # 加入有截关日的「组货中」拼柜
    cons = purchase_mod.create_consolidation(cid, code="CG-99", cutoff_date="2026-12-05", status="组货中")
    purchase_mod.add_consolidation_item(cons["id"], cid, po["id"])

    def _snapshot_counts():
        conn = db_mod.get_connection()
        try:
            tables = ("purchase_orders", "consolidations", "consolidation_items", "todos", "conversations")
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        finally:
            conn.close()

    before = _snapshot_counts()

    d_up = purchase_mod.build_followup_draft(po["id"], cid, "upcoming", today_str="2026-11-27")
    assert "王总您好" in d_up["text"]
    assert "PO-8801" in d_up["text"]
    assert "不锈钢合页" in d_up["text"]
    assert "2026-11-29" in d_up["text"]
    assert "2 天" in d_up["text"]

    d_ov = purchase_mod.build_followup_draft(po["id"], cid, "overdue", today_str="2026-12-02")
    assert "王总您好" in d_ov["text"]
    assert "PO-8801" in d_ov["text"]
    assert "3 天" in d_ov["text"]

    d_cu = purchase_mod.build_followup_draft(po["id"], cid, "cutoff", today_str="2026-11-27")
    assert "CG-99" in d_cu["text"]
    assert "2026-12-05" in d_cu["text"]
    assert "PO-8801" in d_cu["text"]

    # 零写库副作用断言
    assert _snapshot_counts() == before


# ==============================================================================
# C7 拼柜与待拼池 + C8 截关倒计时
# ==============================================================================


def test_c7_and_c8_consolidations_pool_and_cutoff_countdown(env):
    """C7 & C8：柜 CRUD 与 CG{id}；重复加入仅一行；删柜不删采购单；待拼池口径；倒计时四态。"""
    cid = env["co_a"]["id"]
    sup = supplier_mod.create_supplier(cid, name="拼柜测试厂")

    po1 = purchase_mod.create_purchase_order(cid, supplier_id=sup["id"], product_name="货A", status="生产中")
    purchase_mod.create_purchase_order(cid, supplier_id=sup["id"], product_name="货B", status="已出货")

    # 初始待拼池：仅含未出货的 po1（不含已出货的 po2）
    assert [p["id"] for p in purchase_mod.list_consolidation_pool(cid)] == [po1["id"]]

    # C7：空 code 生成 CG{id}
    c1 = purchase_mod.create_consolidation(cid, destination_port="汉堡", cutoff_date="2026-12-01")
    assert c1["code"] == f"CG{c1['id']}"

    # 重复加入同一采购单 → 返回既有行、只有一行
    it1 = purchase_mod.add_consolidation_item(c1["id"], cid, po1["id"])
    it2 = purchase_mod.add_consolidation_item(c1["id"], cid, po1["id"])
    assert it1["item_id"] == it2["item_id"]
    assert len(purchase_mod.get_consolidation(c1["id"], cid)["items"]) == 1

    # 入柜即离待拼池
    assert purchase_mod.list_consolidation_pool(cid) == []

    # 移出即回待拼池
    assert purchase_mod.remove_consolidation_item(c1["id"], it1["item_id"], cid) is True
    assert [p["id"] for p in purchase_mod.list_consolidation_pool(cid)] == [po1["id"]]

    # 再入柜后删柜 → 采购单本身保留并回到待拼池
    purchase_mod.add_consolidation_item(c1["id"], cid, po1["id"])
    assert purchase_mod.delete_consolidation(c1["id"], cid) is True
    assert purchase_mod.get_purchase_order(po1["id"], cid) is not None
    assert [p["id"] for p in purchase_mod.list_consolidation_pool(cid)] == [po1["id"]]

    # C8：days_to_cutoff 正 / 零 / 负 / null 四种情况（固定日期 2026-11-27）
    fixed_today = "2026-11-27"
    c_pos = purchase_mod.create_consolidation(cid, code="CG-POS", cutoff_date="2026-11-30")
    c_zero = purchase_mod.create_consolidation(cid, code="CG-ZERO", cutoff_date="2026-11-27")
    c_neg = purchase_mod.create_consolidation(cid, code="CG-NEG", cutoff_date="2026-11-25")
    c_null = purchase_mod.create_consolidation(cid, code="CG-NULL", cutoff_date="")

    assert purchase_mod.get_consolidation(c_pos["id"], cid, today_str=fixed_today)["days_to_cutoff"] == 3
    assert purchase_mod.get_consolidation(c_zero["id"], cid, today_str=fixed_today)["days_to_cutoff"] == 0
    assert purchase_mod.get_consolidation(c_neg["id"], cid, today_str=fixed_today)["days_to_cutoff"] == -2
    assert purchase_mod.get_consolidation(c_null["id"], cid, today_str=fixed_today)["days_to_cutoff"] is None


# ==============================================================================
# C9 公司隔离
# ==============================================================================


def test_c9_purchase_and_consolidation_company_isolation(env):
    """C9：采购单、拼柜、明细、提醒，跨公司一律 404 或查不到。"""
    client = env["client"]
    cid_a = env["co_a"]["id"]
    cid_b = env["co_b"]["id"]
    hdr_a = env["headers"](cid_a)

    sup_a = supplier_mod.create_supplier(cid_a, name="A公司工厂")
    po_a = client.post(
        "/api/trade/purchase-orders",
        json={"supplier_id": sup_a["id"], "product_name": "机密组件", "promised_date": "2020-01-01"},
        headers=hdr_a,
    ).json()
    cons_a = client.post(
        "/api/trade/consolidations",
        json={"code": "CG-A1", "cutoff_date": "2026-12-01"},
        headers=hdr_a,
    ).json()
    item_a = client.post(
        f"/api/trade/consolidations/{cons_a['id']}/items",
        json={"purchase_order_id": po_a["id"]},
        headers=hdr_a,
    ).json()

    # 切换 session 绑定至公司 B
    deps_mod._ACTIVE_COMPANY.clear()
    hdr_b = env["headers"](cid_b)

    assert client.get("/api/trade/purchase-orders", headers=hdr_b).json() == []
    assert client.get("/api/trade/purchase-orders/alerts", headers=hdr_b).json() == []
    assert client.get("/api/trade/consolidations", headers=hdr_b).json() == []
    assert client.get("/api/trade/consolidations/pool", headers=hdr_b).json() == []

    assert client.get(f"/api/trade/purchase-orders/{po_a['id']}", headers=hdr_b).status_code == 404
    assert client.put(f"/api/trade/purchase-orders/{po_a['id']}", json={"note": "x"}, headers=hdr_b).status_code == 404
    assert client.delete(f"/api/trade/purchase-orders/{po_a['id']}", headers=hdr_b).status_code == 404
    assert client.post(
        f"/api/trade/purchase-orders/{po_a['id']}/followup-draft",
        json={"variant": "upcoming"},
        headers=hdr_b,
    ).status_code == 404
    assert client.get(f"/api/trade/consolidations/{cons_a['id']}", headers=hdr_b).status_code == 404
    assert client.put(f"/api/trade/consolidations/{cons_a['id']}", json={"note": "x"}, headers=hdr_b).status_code == 404
    assert client.delete(f"/api/trade/consolidations/{cons_a['id']}", headers=hdr_b).status_code == 404
    assert client.delete(
        f"/api/trade/consolidations/{cons_a['id']}/items/{item_a['item_id']}",
        headers=hdr_b,
    ).status_code == 404


# ==============================================================================
# C10 导出 / 导入扩展
# ==============================================================================


def test_c10_export_and_idempotent_import_purchase_tables(env):
    """C10：三表导出、连导两次不增行、外键（order_id/rfq_id/items）正确重映射。"""
    cid_a = env["co_a"]["id"]
    cust = customer_mod.create("Export Buyer", "Tom", company_id=cid_a)
    ord_a = order_mod.create(cid_a, cust["id"], product_name="叶轮", order_no="ORD-88")
    sup = supplier_mod.create_supplier(cid_a, name="导出采购厂")
    rfq = rfq_mod.create_rfq(cid_a, product_name="叶轮", customer_id=cust["id"])

    po = purchase_mod.create_purchase_order(
        cid_a,
        supplier_id=sup["id"],
        order_id=ord_a["id"],
        rfq_id=rfq["id"],
        po_no="PO-EXP-1",
        product_name="叶轮",
        quantity=40,
        unit="套",
        amount=8000.0,
    )
    cons = purchase_mod.create_consolidation(cid_a, code="CG-EXP-1", cutoff_date="2026-12-10", destination_port="鹿特丹")
    purchase_mod.add_consolidation_item(cons["id"], cid_a, po["id"])

    zip_path = env["tmp_path"] / "purchase-export.zip"
    exporter.export_company(cid_a, dest_zip=zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        for tbl in ("purchase_orders", "consolidations", "consolidation_items"):
            assert manifest["tables"][tbl]["rows"] == 1

    rep_new = importer.import_company(zip_path, force_new=True)
    new_cid = rep_new["target"]["id"]
    assert rep_new["tables"]["purchase_orders"]["added"] == 1
    assert rep_new["tables"]["consolidations"]["added"] == 1
    assert rep_new["tables"]["consolidation_items"]["added"] == 1

    # 连导两次同一公司：三表一条不增
    rep_again = importer.import_company(zip_path, target_company_id=new_cid)
    for tbl in ("purchase_orders", "consolidations", "consolidation_items"):
        assert rep_again["tables"][tbl]["added"] == 0
        assert rep_again["tables"][tbl]["skipped"] == 1

    # 校验目标库外键重映射正确
    new_pos = purchase_mod.list_purchase_orders(new_cid)
    assert len(new_pos) == 1
    new_po = new_pos[0]
    assert new_po["po_no"] == "PO-EXP-1"
    assert new_po["order_id"] is not None and new_po["order_id"] != ord_a["id"]
    assert new_po["rfq_id"] is not None and new_po["rfq_id"] != rfq["id"]
    assert new_po["order_display_no"] == "ORD-88"

    new_cons = purchase_mod.list_consolidations(new_cid)
    assert len(new_cons) == 1
    assert len(new_cons[0]["items"]) == 1
    assert new_cons[0]["items"][0]["purchase_order_id"] == new_po["id"]


# ==============================================================================
# C11 AI 只读提醒工具
# ==============================================================================


def test_c11_supplier_delivery_alerts_ai_tool(env):
    """C11：supplier_delivery_alerts 与 API 同结果；跨公司不出现；无绑定报错；带内部声明。"""
    cid_a = env["co_a"]["id"]
    cid_b = env["co_b"]["id"]

    sup_a = supplier_mod.create_supplier(cid_a, name="A提醒厂")
    sup_b = supplier_mod.create_supplier(cid_b, name="B保密厂")
    purchase_mod.create_purchase_order(
        cid_a, supplier_id=sup_a["id"], product_name="A逾期件", promised_date="2020-01-01", status="生产中",
    )
    purchase_mod.create_purchase_order(
        cid_b, supplier_id=sup_b["id"], product_name="B逾期件", promised_date="2020-01-01", status="生产中",
    )

    with agent_context.bind_company(company_id=cid_a):
        res = json.loads(plugin_tools.handle_supplier_delivery_alerts({}))
        api_alerts = purchase_mod.get_delivery_alerts(cid_a)
        assert res["count"] == len(api_alerts) == 1
        assert [a["product_name"] for a in res["alerts"]] == ["A逾期件"]

    with agent_context.bind_company(company_id=None):
        err = json.loads(plugin_tools.handle_supplier_delivery_alerts({}))
        assert "error" in err

    desc = plugin_tools.SUPPLIER_DELIVERY_ALERTS_SCHEMA["description"]
    assert "内部采购数据" in desc
    assert "禁止写入给客户的邮件" in desc
