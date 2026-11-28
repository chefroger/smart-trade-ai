"""
供应商管理一期 · 第一批（数据底座）验收测试（A1–A12）。

逐条对应任务书 §7 验收用例：
  A1  旧库升级（建五表 + 既有表行数与内容不变 + 重复启动幂等）
  A2  公司隔离（列表/search/compare/详情隔离 + 跨公司直调 GET/PUT/DELETE 一律 404）
  A3  能力唯一（同供应商同产品同规格 upsert 仅一行 + is_self_produced 三态）
  A4  报价只追加（连报三次返回三行按日期倒序 + valid_until 过期标记）
  A5  三向查询（产品名 / 供应商 ID / 来源客户 ID）
  A6  比价口径（有 tax_point 换算标 converted=True / 无 tax_point 不编造 / 不同单位分组）
  A7  导出完整（四张正式表完整导出 + manifest excluded 含 supplier_quote_drafts）
  A8  导入合并（同一包导入两次幂等、报价一条不增、能力行不重复、跨公司不串）
  A9  模板导入（模板下载 + 混入坏行时好行全入库、同名合并、坏行逐行报错）
  A10 抽取确认区（mock 模型 → 只落草稿 → 批准入库 source='ai-extract' / 驳回留痕）
  A11 抽取不编造（mock 无价格文档 → 草稿价格全空；批准后能力行 is_self_produced=2）
  A12 无对外泄漏面（chat / copilot / 品牌安全路径不得引用供应商或报价表）
"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trade import company as company_mod
from trade import customer as customer_mod
from trade import database as db_mod
from trade import doc_extract
from trade import license as license_mod
from trade import supplier as supplier_mod
from trade.api import deps as deps_mod
from trade.api import router as trade_router
from trade.company.transfer import exporter, importer


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
    # 供应商模块为付费能力：既有第一批功能验收在已激活（active）状态下运行
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
    token = "test-supplier-token"
    deps_mod.set_session_token(token)
    client = TestClient(app)

    co_a = company_mod.create(name="Company Alpha", slug="alpha")
    co_b = company_mod.create(name="Company Beta", slug="beta")

    def headers(cid: int, tok: str | None = None) -> dict[str, str]:
        return {
            "X-Hermes-Session-Token": tok or token,
            "X-Company-ID": str(cid),
        }

    return {
        "client": client,
        "db_path": db_path,
        "trade_home": trade_home,
        "tmp_path": tmp_path,
        "co_a": co_a,
        "co_b": co_b,
        "headers": headers,
        "token": token,
    }


# ==============================================================================
# A1 旧库升级
# ==============================================================================


def test_a1_legacy_db_upgrade(monkeypatch, tmp_path):
    """A1：基线旧库启动新代码后五张新表建成，既有表行数与内容不变，重复启动不报错。"""
    db_path = tmp_path / "legacy.db"
    monkeypatch.setattr(db_mod, "_get_db_path", lambda: db_path)

    # 先初始化一次再手动删掉五张供应商表，模拟 411471b 基线旧库
    db_mod.init_db()
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = OFF")
    for tbl in (
        "supplier_quote_drafts",
        "supplier_quotes",
        "supplier_products",
        "supplier_contacts",
        "suppliers",
    ):
        conn.execute(f"DROP TABLE IF EXISTS {tbl}")
    conn.execute("PRAGMA foreign_keys = ON")

    # 往既有表插入基线数据
    conn.execute("INSERT INTO companies (id, name, slug) VALUES (1, 'Legacy Co', 'legacy-co')")
    conn.execute("INSERT INTO customers (id, company_id, name, contact) VALUES (10, 1, 'Acme Buyer', 'Bob')")
    conn.execute(
        "INSERT INTO orders (id, company_id, customer_id, product_name, quantity) "
        "VALUES (20, 1, 10, 'Steel Pipe', 100)"
    )
    conn.execute(
        "INSERT INTO inquiries (id, company_id, customer_id, title) "
        "VALUES (30, 1, 10, 'Q4 Pipe Inquiry')"
    )
    conn.commit()

    before_customers = conn.execute("SELECT id, name, contact FROM customers").fetchall()
    before_orders = conn.execute("SELECT id, product_name, quantity FROM orders").fetchall()
    before_inquiries = conn.execute("SELECT id, title FROM inquiries").fetchall()
    conn.close()

    # 升级启动两次，验证建表与幂等性
    db_mod.init_db()
    db_mod.init_db()

    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for tbl in (
        "suppliers",
        "supplier_contacts",
        "supplier_products",
        "supplier_quotes",
        "supplier_quote_drafts",
    ):
        assert tbl in tables, f"升级后缺少新表：{tbl}"

    assert conn.execute("SELECT id, name, contact FROM customers").fetchall() == before_customers
    assert conn.execute("SELECT id, product_name, quantity FROM orders").fetchall() == before_orders
    assert conn.execute("SELECT id, title FROM inquiries").fetchall() == before_inquiries
    conn.close()


# ==============================================================================
# A2 公司隔离
# ==============================================================================


def test_a2_company_isolation(env):
    """A2：跨公司不可见、不可改；公司 B 直调公司 A 的资源 ID 一律返回 404。"""
    client = env["client"]
    cid_a = env["co_a"]["id"]
    cid_b = env["co_b"]["id"]
    hdr_a = env["headers"](cid_a)

    # 公司 A 建完整数据
    r = client.post(
        "/api/trade/suppliers",
        json={"name": "顺达陶瓷厂", "tax_point": 8.0, "status": "合作中"},
        headers=hdr_a,
    )
    assert r.status_code == 200
    sup_id = r.json()["id"]

    r_c = client.post(
        f"/api/trade/suppliers/{sup_id}/contacts",
        json={"name": "陈经理", "phone": "13800138000", "is_primary": 1},
        headers=hdr_a,
    )
    assert r_c.status_code == 200
    contact_id = r_c.json()["id"]

    r_p = client.post(
        f"/api/trade/suppliers/{sup_id}/products",
        json={"product_name": "马克杯", "spec_model": "350ml", "unit": "件", "is_self_produced": 1},
        headers=hdr_a,
    )
    assert r_p.status_code == 200
    prod_id = r_p.json()["id"]

    r_q = client.post(
        f"/api/trade/suppliers/{sup_id}/quotes",
        json={"product_name": "马克杯", "spec_model": "350ml", "unit": "件", "price_excl_tax": 4.5},
        headers=hdr_a,
    )
    assert r_q.status_code == 200
    quote_id = r_q.json()["id"]

    # 切换 session 绑定到公司 B
    deps_mod._ACTIVE_COMPANY.clear()
    hdr_b = env["headers"](cid_b)

    assert client.get("/api/trade/suppliers", headers=hdr_b).json() == []
    assert client.get("/api/trade/supplier-quotes/search?product_name=马克杯", headers=hdr_b).json() == []
    cmp_b = client.get("/api/trade/supplier-compare?product_name=马克杯", headers=hdr_b).json()
    assert cmp_b["unit_groups"] == [] and cmp_b["no_quote_suppliers"] == []

    # 跨公司直调 GET / PUT / DELETE 一律 404
    assert client.get(f"/api/trade/suppliers/{sup_id}", headers=hdr_b).status_code == 404
    assert client.put(f"/api/trade/suppliers/{sup_id}", json={"note": "hack"}, headers=hdr_b).status_code == 404
    assert client.delete(f"/api/trade/suppliers/{sup_id}", headers=hdr_b).status_code == 404
    assert client.put(f"/api/trade/suppliers/contacts/{contact_id}", json={"name": "hack"}, headers=hdr_b).status_code == 404
    assert client.delete(f"/api/trade/suppliers/contacts/{contact_id}", headers=hdr_b).status_code == 404
    assert client.put(f"/api/trade/supplier-products/{prod_id}", json={"unit": "箱"}, headers=hdr_b).status_code == 404
    assert client.delete(f"/api/trade/supplier-products/{prod_id}", headers=hdr_b).status_code == 404
    assert client.put(f"/api/trade/supplier-quotes/{quote_id}", json={"notes": "hack"}, headers=hdr_b).status_code == 404
    assert client.delete(f"/api/trade/supplier-quotes/{quote_id}", headers=hdr_b).status_code == 404


# ==============================================================================
# A3 能力唯一与三态自产
# ==============================================================================


def test_a3_product_capability_unique_and_tristate(env):
    """A3：同供应商同产品同规格保存两次仅一行，字段为第二次的值；is_self_produced 三态可存可查。"""
    cid = env["co_a"]["id"]
    sup = supplier_mod.create_supplier(cid, name="华强五金厂")

    first = supplier_mod.upsert_product(
        cid, sup["id"], product_name="不锈钢螺丝", spec_model="M6x20",
        unit="千件", is_self_produced=2, quality_note="初样", moq=50,
    )
    second = supplier_mod.upsert_product(
        cid, sup["id"], product_name="不锈钢螺丝", spec_model="M6x20",
        unit="千件", is_self_produced=1, quality_note="304 材质稳定", moq=100,
    )
    assert first["id"] == second["id"]
    assert second["is_self_produced"] == 1
    assert second["quality_note"] == "304 材质稳定"
    assert second["moq"] == 100

    # 验证其余两态（0 和 2）也可存可查
    p0 = supplier_mod.upsert_product(cid, sup["id"], product_name="外协垫片", spec_model="M6", is_self_produced=0)
    p2 = supplier_mod.upsert_product(cid, sup["id"], product_name="待定螺母", spec_model="M6", is_self_produced=2)
    detail = supplier_mod.get_supplier(sup["id"], cid)
    by_name = {p["product_name"]: p["is_self_produced"] for p in detail["products"]}
    assert by_name == {"不锈钢螺丝": 1, "外协垫片": 0, "待定螺母": 2}
    assert p0["is_self_produced"] == 0 and p2["is_self_produced"] == 2


# ==============================================================================
# A4 报价只追加 + 过期标记
# ==============================================================================


def test_a4_quotes_append_only_and_expired_flag(env):
    """A4：同产品连报三次价 → search 返回三行按日期倒序；过期带 expired=True。"""
    cid = env["co_a"]["id"]
    sup = supplier_mod.create_supplier(cid, name="恒通线缆厂")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    next_month = (date.today() + timedelta(days=30)).isoformat()

    supplier_mod.create_quote(
        cid, sup["id"], product_name="ADSS 光缆", spec_model="24芯", unit="米",
        price_excl_tax=3.2, quoted_at="2026-09-01", valid_until=yesterday,
    )
    supplier_mod.create_quote(
        cid, sup["id"], product_name="ADSS 光缆", spec_model="24芯", unit="米",
        price_excl_tax=3.4, quoted_at="2026-10-15", valid_until=next_month,
    )
    supplier_mod.create_quote(
        cid, sup["id"], product_name="ADSS 光缆", spec_model="24芯", unit="米",
        price_excl_tax=3.1, quoted_at="2026-11-20", valid_until=next_month,
    )

    rows = supplier_mod.search_quotes(cid, product_name="ADSS")
    assert len(rows) == 3
    assert [r["quoted_at"] for r in rows] == ["2026-11-20", "2026-10-15", "2026-09-01"]
    assert rows[0]["expired"] is False
    assert rows[2]["expired"] is True


# ==============================================================================
# A5 三向查询
# ==============================================================================


def test_a5_three_way_quote_search(env):
    """A5：按产品查多家、按供应商查全部报价、按 source_customer_id 查给该客户的历史报价。"""
    cid = env["co_a"]["id"]
    cust = customer_mod.create("Euro Buyer GmbH", "Hans", company_id=cid)
    s1 = supplier_mod.create_supplier(cid, name="甲厂")
    s2 = supplier_mod.create_supplier(cid, name="乙厂")

    supplier_mod.create_quote(
        cid, s1["id"], product_name="硅胶密封圈", unit="件",
        price_excl_tax=0.5, quoted_at="2026-11-01", source_customer_id=cust["id"],
    )
    supplier_mod.create_quote(
        cid, s1["id"], product_name="橡胶垫片", unit="件",
        price_excl_tax=0.3, quoted_at="2026-11-02",
    )
    supplier_mod.create_quote(
        cid, s2["id"], product_name="硅胶密封圈", unit="件",
        price_excl_tax=0.48, quoted_at="2026-11-03",
    )

    # 1) 按产品查到多家
    by_prod = supplier_mod.search_quotes(cid, product_name="硅胶密封圈")
    assert {r["supplier_id"] for r in by_prod} == {s1["id"], s2["id"]}
    # 2) 按供应商查全部报价
    by_sup = supplier_mod.search_quotes(cid, supplier_id=s1["id"])
    assert len(by_sup) == 2
    # 3) 按客户查给该客户的报价
    by_cust = supplier_mod.search_quotes(cid, customer_id=cust["id"])
    assert len(by_cust) == 1
    assert by_cust[0]["product_name"] == "硅胶密封圈"


# ==============================================================================
# A6 比价口径（含税换算 + 单位分组）
# ==============================================================================


def test_a6_compare_tax_conversion_and_unit_grouping(env):
    """A6：有 tax_point 换算标 converted=True；无 tax_point 不编造；不同单位不混排最低价。"""
    cid = env["co_a"]["id"]
    future = (date.today() + timedelta(days=30)).isoformat()

    # 甲：有 tax_point=8，仅报不含税价 100（单位：件）
    s_a = supplier_mod.create_supplier(cid, name="甲供应商", tax_point=8.0, can_issue_vat=1)
    supplier_mod.create_quote(
        cid, s_a["id"], product_name="铝型材接头", unit="件",
        price_excl_tax=100.0, quoted_at="2026-11-20", valid_until=future,
    )

    # 乙：无 tax_point，仅报不含税价 90（单位：件）
    s_b = supplier_mod.create_supplier(cid, name="乙供应商", tax_point=None, can_issue_vat=2)
    supplier_mod.create_quote(
        cid, s_b["id"], product_name="铝型材接头", unit="件",
        price_excl_tax=90.0, quoted_at="2026-11-20", valid_until=future,
    )

    # 丙：按 kg 报价 25（不同单位）
    s_c = supplier_mod.create_supplier(cid, name="丙供应商", tax_point=13.0, can_issue_vat=1)
    supplier_mod.create_quote(
        cid, s_c["id"], product_name="铝型材接头", unit="kg",
        price_excl_tax=25.0, quoted_at="2026-11-20", valid_until=future,
    )

    res = supplier_mod.compare_product(cid, product_name="铝型材接头")
    groups = {g["unit"]: g for g in res["unit_groups"]}
    assert set(groups.keys()) == {"件", "kg"}

    # 单位「件」组内最低价为 90，绝不被 kg 组的 25 污染
    assert groups["件"]["lowest_excl_tax"] == 90.0
    assert groups["kg"]["lowest_excl_tax"] == 25.0

    rows_piece = {r["supplier_name"]: r["latest_quote"] for r in groups["件"]["suppliers"]}
    rows_piece_full = {r["supplier_name"]: r for r in groups["件"]["suppliers"]}
    # 甲：换算含税价 108.0，标记 converted=True；O-供2：含税区间不纳入换算值
    assert rows_piece["甲供应商"]["price_incl_tax"] == 108.0
    assert rows_piece["甲供应商"]["converted"] is True
    assert rows_piece["甲供应商"]["price_incl_tax_converted"] is True
    assert rows_piece_full["甲供应商"]["price_excl_range"] == [100.0, 100.0]
    assert rows_piece_full["甲供应商"]["price_incl_range"] is None
    # 乙：无 tax_point，严禁编造含税价
    assert rows_piece["乙供应商"]["price_incl_tax"] is None
    assert rows_piece["乙供应商"]["converted"] is False
    # O-供1：有含税价（含换算）的甲排在无含税价的乙前面
    assert [r["supplier_name"] for r in groups["件"]["suppliers"]] == ["甲供应商", "乙供应商"]


# ==============================================================================
# A7 导出完整 + A8 导入合并幂等
# ==============================================================================


def test_a7_and_a8_export_and_idempotent_import(env):
    """A7 & A8：导出含四张正式表且 excluded 含草稿表；连续导入两次不重复且跨公司隔离。"""
    cid_a = env["co_a"]["id"]
    cid_b = env["co_b"]["id"]

    sup = supplier_mod.create_supplier(cid_a, name="导出测试工厂", short_name="导测", tax_point=13.0)
    supplier_mod.create_contact(cid_a, sup["id"], name="王工", phone="13900001111", is_primary=1)
    prod = supplier_mod.upsert_product(
        cid_a, sup["id"], product_name="定制电机", spec_model="24V-50W", unit="台", is_self_produced=1,
    )
    supplier_mod.create_quote(
        cid_a, sup["id"], product_name="定制电机", spec_model="24V-50W", unit="台",
        price_excl_tax=120.0, quoted_at="2026-11-25", supplier_product_id=prod["id"],
    )
    # 写入一条未确认草稿，验证不进导出包
    conn = db_mod.get_connection()
    conn.execute(
        "INSERT INTO supplier_quote_drafts (company_id, supplier_name_raw, product_name, source_file) "
        "VALUES (?, '未确认厂', '草稿品', '/tmp/draft.pdf')",
        (cid_a,),
    )
    conn.commit()
    conn.close()

    zip_path = env["tmp_path"] / "alpha-export.zip"
    exporter.export_company(cid_a, dest_zip=zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        # A7：四张表全在 tables 里，且草稿表在 excluded 里写明原因
        for tbl in ("suppliers", "supplier_contacts", "supplier_products", "supplier_quotes"):
            assert tbl in manifest["tables"]
            assert manifest["tables"][tbl]["rows"] == 1
        assert "supplier_quote_drafts" not in manifest["tables"]
        assert any("supplier_quote_drafts" in item for item in manifest["excluded"])

    # A8：连续两次导入同一公司，验证幂等合并
    rep1 = importer.import_company(zip_path, target_company_id=cid_a)
    rep2 = importer.import_company(zip_path, target_company_id=cid_a)

    assert rep1["tables"]["suppliers"]["added"] == 0
    assert rep1["tables"]["supplier_quotes"]["added"] == 0
    assert rep2["tables"]["suppliers"]["added"] == 0
    assert rep2["tables"]["supplier_contacts"]["added"] == 0
    assert rep2["tables"]["supplier_products"]["added"] == 0
    assert rep2["tables"]["supplier_quotes"]["added"] == 0
    assert rep2["tables"]["supplier_quotes"]["skipped"] == 1

    # 验证新建公司导入一次再合并导入一次：第一次全新增，第二次全跳过，且不影响公司 B
    rep_new = importer.import_company(zip_path, force_new=True)
    new_cid = rep_new["target"]["id"]
    assert rep_new["tables"]["suppliers"]["added"] == 1
    assert rep_new["tables"]["supplier_contacts"]["added"] == 1
    assert rep_new["tables"]["supplier_products"]["added"] == 1
    assert rep_new["tables"]["supplier_quotes"]["added"] == 1

    rep_again = importer.import_company(zip_path, target_company_id=new_cid)
    assert rep_again["tables"]["suppliers"]["added"] == 0
    assert rep_again["tables"]["supplier_products"]["added"] == 0
    assert rep_again["tables"]["supplier_quotes"]["added"] == 0
    assert len(supplier_mod.list_suppliers(new_cid)) == 1
    assert len(supplier_mod.search_quotes(new_cid)) == 1
    # 跨公司不串
    assert supplier_mod.list_suppliers(cid_b) == []


# ==============================================================================
# A9 模板导入
# ==============================================================================


def test_a9_csv_template_download_and_bulk_import(env):
    """A9：模板可下载；好行一次落齐四表且同名合并，坏行逐行报错不阻塞好行。"""
    client = env["client"]
    cid = env["co_a"]["id"]
    hdr = env["headers"](cid)

    # 下载 CSV 模板（必须带 UTF-8 BOM，避免 macOS/Windows Excel 打开中文乱码）
    r_tpl = client.get("/api/trade/suppliers/template", headers=hdr)
    assert r_tpl.status_code == 200
    assert r_tpl.content.startswith(b"\xef\xbb\xbf")
    assert "供应商名称*" in r_tpl.text

    csv_body = (
        "供应商名称*,简称,类型,主营品类,省,市,状态,可开专票,开票加点,结算方式,"
        "联系人姓名,联系人角色,联系电话,微信,产品名,规格,单位,是否自产（是/否/待确认）,"
        "不含税价,含税价,MOQ,报价日期,报价有效期\n"
        "顺达陶瓷,顺达,工厂,马克杯,广东,佛山,合作中,是,8,30%定金,陈明,业务报价,138001,wx1,马克杯,350ml,件,是,4.5,,1000,2026-11-20,2026-12-31\n"
        "顺达陶瓷,顺达,工厂,马克杯,广东,佛山,合作中,是,8,30%定金,李华,跟单生产,138002,wx2,咖啡杯,250ml,件,否,3.8,,500,2026-11-21,2026-12-31\n"
        ",缺名行,工厂,马克杯,广东,佛山,候选,是,8,,张三,业务,139,,马克杯,350ml,件,是,4.0,,100,2026-11-20,\n"
        "坏价厂,坏价,贸易商,包装,浙江,义乌,候选,是,abc,,赵六,业务,137,,纸箱,大号,个,是,not_num,,100,2026-11-20,\n"
    ).encode()

    r_bulk = client.post(
        "/api/trade/suppliers/bulk",
        files={"file": ("suppliers.csv", csv_body, "text/csv")},
        headers=hdr,
    )
    assert r_bulk.status_code == 200
    res = r_bulk.json()
    assert res["ok_rows"] == 2
    assert res["error_count"] == 2
    assert [e["row"] for e in res["errors"]] == [4, 5]
    # 同名供应商合并为一家
    assert res["created_suppliers"] == 1
    assert res["reused_suppliers"] == 1
    assert res["created_contacts"] == 2
    assert res["upserted_products"] == 2
    assert res["created_quotes"] == 2


# ==============================================================================
# A10 抽取确认区 + A11 抽取不编造
# ==============================================================================


@pytest.mark.asyncio
async def test_a10_ai_extract_drafts_approve_and_reject(env, tmp_path):
    """A10：抽取只落草稿（带 source_file/raw_excerpt），批准后入正式表，驳回后留痕。"""
    cid = env["co_a"]["id"]
    doc_file = tmp_path / "quote_shunda.txt"
    doc_file.write_text("佛山顺达陶瓷 350ml 马克杯 不含税 4.2 元/件 报价日 2026-11-22", encoding="utf-8")

    mock_json = json.dumps({
        "quotes": [
            {
                "supplier_name": "佛山顺达陶瓷",
                "product_name": "陶瓷马克杯",
                "spec_model": "350ml",
                "unit": "件",
                "price_excl_tax": 4.2,
                "price_incl_tax": None,
                "currency": "CNY",
                "quoted_at": "2026-11-22",
                "valid_until": "2026-12-22",
                "raw_excerpt": "佛山顺达陶瓷 350ml 马克杯 不含税 4.2 元/件",
            },
            {
                "supplier_name": "待驳回厂",
                "product_name": "测试品",
                "spec_model": "",
                "unit": "件",
                "price_excl_tax": 9.9,
                "price_incl_tax": None,
                "currency": "CNY",
                "quoted_at": "2026-11-22",
                "valid_until": "",
                "raw_excerpt": "测试摘录",
            },
        ]
    }, ensure_ascii=False)

    with patch.object(doc_extract, "resolve_extraction_model", return_value=("openai", "gpt-4o", "openai:gpt-4o")), \
         patch.object(doc_extract, "_call_model", new=AsyncMock(return_value=mock_json)):
        ext = await supplier_mod.extract_files_to_drafts(cid, [str(doc_file)])

    assert ext["drafts_created"] == 2
    assert ext["failed"] == []
    # 正式表此时应为 0（未批准绝不写正式表）
    assert supplier_mod.list_suppliers(cid) == []
    assert supplier_mod.search_quotes(cid) == []

    drafts = supplier_mod.list_drafts(cid, status="pending")
    assert len(drafts) == 2
    assert all(d["source_file"] == str(doc_file) and d["raw_excerpt"] for d in drafts)

    # 批准第一条（佛山顺达陶瓷）
    d_approve = next(d for d in drafts if d["supplier_name_raw"] == "佛山顺达陶瓷")
    approved = supplier_mod.approve_draft(d_approve["id"], cid)
    assert approved["quote"]["source"] == "ai-extract"
    assert approved["quote"]["source_ref"] == str(doc_file)
    assert approved["supplier_created"] is True

    # 驳回第二条（留痕不删，不入正式库）
    d_reject = next(d for d in drafts if d["supplier_name_raw"] == "待驳回厂")
    rejected = supplier_mod.reject_draft(d_reject["id"], cid)
    assert rejected["status"] == "rejected"
    assert len(supplier_mod.list_drafts(cid, status="rejected")) == 1
    assert len(supplier_mod.search_quotes(cid)) == 1


@pytest.mark.asyncio
async def test_a11_ai_extract_no_fabrication_and_tristate_default(env, tmp_path):
    """A11：文档无价格 → 草稿价格全空不编造；批准后能力行 is_self_produced=2（待确认）。"""
    cid = env["co_a"]["id"]
    doc_file = tmp_path / "catalog_no_price.txt"
    doc_file.write_text("星光灯具厂 供应 LED 投光灯 100W，价格面议。", encoding="utf-8")

    mock_json = json.dumps({
        "quotes": [
            {
                "supplier_name": "星光灯具厂",
                "product_name": "LED 投光灯",
                "spec_model": "100W",
                "unit": "台",
                "price_excl_tax": None,
                "price_incl_tax": None,
                "currency": "CNY",
                "quoted_at": "",
                "valid_until": "",
                "raw_excerpt": "星光灯具厂 供应 LED 投光灯 100W，价格面议。",
            }
        ]
    }, ensure_ascii=False)

    with patch.object(doc_extract, "resolve_extraction_model", return_value=("openai", "gpt-4o", "openai:gpt-4o")), \
         patch.object(doc_extract, "_call_model", new=AsyncMock(return_value=mock_json)):
        ext = await supplier_mod.extract_files_to_drafts(cid, [str(doc_file)])

    assert ext["drafts_created"] == 1
    draft = ext["drafts"][0]
    assert draft["price_excl_tax"] is None
    assert draft["price_incl_tax"] is None

    approved = supplier_mod.approve_draft(draft["id"], cid)
    detail = supplier_mod.get_supplier(approved["supplier_id"], cid)
    assert len(detail["products"]) == 1
    assert detail["products"][0]["is_self_produced"] == 2
    assert approved["quote"]["price_excl_tax"] is None
    assert approved["quote"]["price_incl_tax"] is None
    # O-供3：草稿无报价日期时留空，不兜底填批准当天
    assert approved["quote"]["quoted_at"] == ""


# ==============================================================================
# A12 无对外泄漏面
# ==============================================================================


def test_a12_no_supplier_leak_into_chat_copilot_or_brand_safety():
    """A12（第二批扩展）：对外路径（chat / copilot / draft / helpers / prompt / brand safety）不得引用供应商或采购询价模块。"""
    root = Path(__file__).resolve().parent.parent
    protected_files = [
        root / "trade" / "api" / "chat.py",
        root / "trade" / "helpers.py",
        root / "trade" / "prompt.py",
        root / "trade" / "prompts.py",
        root / "trade" / "api" / "copilot.py",
        root / "trade" / "copilot" / "draft.py",
        root / "trade" / "copilot" / "context.py",
        root / "trade" / "copilot" / "service.py",
        root / "trade" / "opener.py",
    ]
    forbidden_tokens = (
        "supplier_quotes",
        "supplier_products",
        "supplier_quote_drafts",
        "trade.supplier",
        "trade.rfq",
        "rfq_responses",
        "trade.purchase",
        "purchase_orders",
        "handle_supplier_quote_search",
        "handle_supplier_compare",
        "handle_supplier_list",
        "handle_supplier_delivery_alerts",
    )
    for path in protected_files:
        if not path.is_file():
            continue
        src = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in src, f"{path.name} 不得引用 {token}（A12/B9 对外隔离约束）"


# ==============================================================================
# B11 第一批 O-供1 / O-供2 / O-供3 修补回归
# ==============================================================================


def test_b11_o_fixes_compare_sort_range_and_draft_date(env):
    """B11：验证 O-供1 排序统一含税口径、O-供2 区间仅统计原值、O-供3 草稿空日期留空。"""
    cid = env["co_a"]["id"]
    future = (date.today() + timedelta(days=30)).isoformat()
    past = (date.today() - timedelta(days=3)).isoformat()

    # O-供1：原值含税 108 vs 换算含税 108 vs 换算含税 107.35 vs 无价 vs 过期低价
    s_orig = supplier_mod.create_supplier(cid, name="原值含税厂", tax_point=13.0)
    supplier_mod.create_quote(
        cid, s_orig["id"], product_name="工业阀门", unit="台",
        price_incl_tax=108.0, quoted_at="2026-11-20", valid_until=future,
    )
    s_conv_tie = supplier_mod.create_supplier(cid, name="换算同价厂", tax_point=8.0)
    supplier_mod.create_quote(
        cid, s_conv_tie["id"], product_name="工业阀门", unit="台",
        price_excl_tax=100.0, quoted_at="2026-11-20", valid_until=future,
    )
    # 给换算同价厂再加一条历史不含税价，顺便测 O-供2 区间排除换算值
    supplier_mod.create_quote(
        cid, s_conv_tie["id"], product_name="工业阀门", unit="台",
        price_excl_tax=110.0, quoted_at="2026-11-10", valid_until=future,
    )
    s_conv_low = supplier_mod.create_supplier(cid, name="换算更低厂", tax_point=13.0)
    supplier_mod.create_quote(
        cid, s_conv_low["id"], product_name="工业阀门", unit="台",
        price_excl_tax=95.0, quoted_at="2026-11-20", valid_until=future,
    )
    s_noprice = supplier_mod.create_supplier(cid, name="无价厂")
    supplier_mod.create_quote(
        cid, s_noprice["id"], product_name="工业阀门", unit="台",
        quoted_at="2026-11-20", valid_until=future,
    )
    s_expired = supplier_mod.create_supplier(cid, name="过期低价厂")
    supplier_mod.create_quote(
        cid, s_expired["id"], product_name="工业阀门", unit="台",
        price_incl_tax=50.0, quoted_at="2026-08-01", valid_until=past,
    )

    cmp_res = supplier_mod.compare_product(cid, product_name="工业阀门")
    grp = cmp_res["unit_groups"][0]
    names = [r["supplier_name"] for r in grp["suppliers"]]
    # 顺序：换算更低(107.35) → 原值含税(108) → 换算同价(108) → 无价 → 过期沉底
    assert names == ["换算更低厂", "原值含税厂", "换算同价厂", "无价厂", "过期低价厂"]

    # O-供2：换算同价厂只报了不含税价(100/110)，含税区间必须为 None（排除换算值）
    tie_row = next(r for r in grp["suppliers"] if r["supplier_name"] == "换算同价厂")
    assert tie_row["price_excl_range"] == [100.0, 110.0]
    assert tie_row["price_incl_range"] is None
    assert tie_row["latest_quote"]["converted"] is True

    # O-供3：草稿无 quoted_at 时批准后仍留空串，不填批准当天
    conn = db_mod.get_connection()
    cur = conn.execute(
        "INSERT INTO supplier_quote_drafts "
        "(company_id, supplier_name_raw, product_name, unit, price_excl_tax, quoted_at, source_file, status) "
        "VALUES (?, '空日期测试厂', '工业阀门', '台', 88.0, '', '/tmp/q.pdf', 'pending')",
        (cid,),
    )
    draft_id = cur.lastrowid
    conn.commit()
    conn.close()

    approved = supplier_mod.approve_draft(draft_id, cid)
    assert approved["quote"]["quoted_at"] == ""


# ==============================================================================
# 工单 #3：供应商 AI 抽取 token 记账
# ==============================================================================


@pytest.mark.asyncio
async def test_extract_records_usage_ledger(env, monkeypatch, tmp_path):
    """给 async_call_llm 打桩返回带 usage 对象，断言账本出现 skill='supplier-extract' 行。"""
    import sys as _sys
    import types as _types
    from types import SimpleNamespace

    from trade import usage as usage_mod

    cid = env["co_a"]["id"]
    # 虚构测试报价单文件（仅用于单元测试）
    sample = tmp_path / "fictional_quote.txt"
    sample.write_text("虚构测试厂\n测试件A 单价 12 元/件\n", encoding="utf-8")

    fake_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "quotes": [
                                {
                                    "supplier_name": "虚构测试厂",
                                    "product_name": "测试件A",
                                    "unit": "件",
                                    "price_excl_tax": 12.0,
                                    "price_incl_tax": None,
                                    "currency": "CNY",
                                    "raw_excerpt": "测试件A 单价 12 元/件",
                                }
                            ]
                        },
                        ensure_ascii=False,
                    )
                )
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=1500,
            completion_tokens=200,
            prompt_cache_hit_tokens=1200,
            prompt_cache_miss_tokens=300,
        ),
    )

    async def _fake_async_call_llm(**_kwargs):
        return fake_response

    fake_agent_pkg = _types.ModuleType("agent")
    fake_aux_mod = _types.ModuleType("agent.auxiliary_client")
    fake_aux_mod.async_call_llm = _fake_async_call_llm
    monkeypatch.setitem(_sys.modules, "agent", fake_agent_pkg)
    monkeypatch.setitem(_sys.modules, "agent.auxiliary_client", fake_aux_mod)
    monkeypatch.setattr(
        doc_extract, "resolve_extraction_model", lambda: ("deepseek", "deepseek-flash", "k")
    )

    res = await supplier_mod.extract_files_to_drafts(cid, [str(sample)])
    assert res["drafts_created"] == 1

    conn = db_mod.get_connection()
    try:
        assert usage_mod.tokens_today(conn, cid) == 1700
        row = conn.execute(
            "SELECT skill, provider, model, prompt_tokens, completion_tokens, "
            "cache_hit_tokens, cache_miss_tokens FROM usage_ledger WHERE company_id = ?",
            (cid,),
        ).fetchone()
        assert tuple(row) == ("supplier-extract", "deepseek", "deepseek-flash", 1500, 200, 1200, 300)
    finally:
        conn.close()


# ==============================================================================
# 工单 #2：按文件夹抽取时不支持文件不静默跳过，系统隐藏文件安静忽略
# ==============================================================================


@pytest.mark.asyncio
async def test_extract_folder_reports_unsupported_and_ignores_system_files(env, monkeypatch, tmp_path):
    """混合目录（txt + jpg + .DS_Store + ~$temp.xlsx）：jpg 进 failed，系统/临时文件不出现。"""
    cid = env["co_a"]["id"]
    folder = tmp_path / "fictional_mixed_dir"
    folder.mkdir()
    # 虚构测试报价与占位图片
    (folder / "quote.txt").write_text("虚构工厂\n测试件B 10元/个\n", encoding="utf-8")
    jpg_file = folder / "scan_quote.jpg"
    jpg_file.write_bytes(b"\xff\xd8\xff\xe0fakejpg")
    (folder / ".DS_Store").write_bytes(b"macos-meta")
    (folder / "Thumbs.db").write_bytes(b"win-meta")
    (folder / "~$quote.xlsx").write_bytes(b"office-lock")

    monkeypatch.setattr(
        doc_extract, "resolve_extraction_model", lambda: ("deepseek", "deepseek-flash", "k")
    )
    monkeypatch.setattr(
        doc_extract,
        "_call_model",
        AsyncMock(
            return_value=json.dumps(
                {
                    "quotes": [
                        {
                            "supplier_name": "虚构工厂",
                            "product_name": "测试件B",
                            "unit": "个",
                            "price_excl_tax": 10.0,
                            "moq": None,
                            "raw_excerpt": "测试件B 10元/个",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        ),
    )

    dir_res = await supplier_mod.extract_files_to_drafts(cid, [str(folder)])
    assert dir_res["files_processed"] == 1
    assert dir_res["drafts_created"] == 1
    assert len(dir_res["failed"]) == 1
    assert dir_res["failed"][0]["file"].endswith("scan_quote.jpg")
    assert dir_res["failed"][0]["error"] == "unsupported_type"

    # 单文件路径与文件夹路径对同一种文件给出同样的错误码
    single_res = await supplier_mod.extract_files_to_drafts(cid, [str(jpg_file)])
    assert len(single_res["failed"]) == 1
    assert single_res["failed"][0]["error"] == dir_res["failed"][0]["error"] == "unsupported_type"


# ==============================================================================
# 工单 #4：确认区草稿 MOQ 字段（迁移 + 抽取 → 编辑 → 批准全链路）
# ==============================================================================


def test_draft_moq_migration_preserves_old_drafts(tmp_path):
    """老库升级：给旧结构 supplier_quote_drafts 补 moq 列，旧草稿数据不丢且 moq 为 NULL。"""
    db_path = tmp_path / "legacy_drafts.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE supplier_quote_drafts (
            id                INTEGER PRIMARY KEY,
            company_id        INTEGER NOT NULL,
            supplier_id       INTEGER,
            supplier_name_raw TEXT DEFAULT '',
            product_name      TEXT DEFAULT '',
            spec_model        TEXT DEFAULT '',
            unit              TEXT DEFAULT '',
            price_excl_tax    REAL,
            price_incl_tax    REAL,
            currency          TEXT DEFAULT 'CNY',
            quoted_at         TEXT DEFAULT '',
            valid_until       TEXT DEFAULT '',
            source_file       TEXT NOT NULL,
            raw_excerpt       TEXT DEFAULT '',
            status            TEXT DEFAULT 'pending'
        );
        """
    )
    conn.execute(
        "INSERT INTO supplier_quote_drafts (company_id, supplier_name_raw, product_name, source_file) "
        "VALUES (1, '旧厂', '旧件', '/tmp/old.txt')"
    )
    conn.commit()

    db_mod._migrate_supplier_drafts_moq_v7(conn)
    conn.commit()

    cols = {r[1] for r in conn.execute("PRAGMA table_info(supplier_quote_drafts)").fetchall()}
    assert "moq" in cols
    row = conn.execute("SELECT product_name, moq FROM supplier_quote_drafts").fetchone()
    assert row == ("旧件", None)
    conn.close()


@pytest.mark.asyncio
async def test_extract_draft_edit_and_approve_preserves_moq(env, monkeypatch, tmp_path):
    """含 MOQ 的虚构样例走完抽取→编辑→批准，正式报价 MOQ 正确；无 MOQ 为 None。"""
    cid = env["co_a"]["id"]
    client = env["client"]
    headers = env["headers"](cid)

    sample = tmp_path / "fictional_moq.txt"
    sample.write_text("虚构MOQ厂\n件X MOQ 500 个 8元\n件Y 无起订 9元\n", encoding="utf-8")

    monkeypatch.setattr(
        doc_extract, "resolve_extraction_model", lambda: ("deepseek", "deepseek-flash", "k")
    )
    monkeypatch.setattr(
        doc_extract,
        "_call_model",
        AsyncMock(
            return_value=json.dumps(
                {
                    "quotes": [
                        {
                            "supplier_name": "虚构MOQ厂",
                            "product_name": "件X",
                            "unit": "个",
                            "price_excl_tax": 8.0,
                            "moq": 500,
                            "raw_excerpt": "件X MOQ 500 个 8元",
                        },
                        {
                            "supplier_name": "虚构MOQ厂",
                            "product_name": "件Y",
                            "unit": "个",
                            "price_excl_tax": 9.0,
                            "moq": None,
                            "raw_excerpt": "件Y 无起订 9元",
                        },
                    ]
                },
                ensure_ascii=False,
            )
        ),
    )

    ext = await supplier_mod.extract_files_to_drafts(cid, [str(sample)])
    assert ext["drafts_created"] == 2
    d_x = next(d for d in ext["drafts"] if d["product_name"] == "件X")
    d_y = next(d for d in ext["drafts"] if d["product_name"] == "件Y")
    assert d_x["moq"] == 500.0
    assert d_y["moq"] is None

    # 通过编辑接口修改 MOQ 为 800
    upd = client.put(
        f"/api/trade/supplier-quote-drafts/{d_x['id']}",
        headers=headers,
        json={"moq": 800},
    )
    assert upd.status_code == 200
    assert upd.json()["moq"] == 800.0

    # 批准入正式库后 MOQ 正确保留
    app_x = supplier_mod.approve_draft(d_x["id"], cid)
    app_y = supplier_mod.approve_draft(d_y["id"], cid)
    assert app_x["quote"]["moq"] == 800.0
    assert app_y["quote"]["moq"] is None


# ==============================================================================
# 工单 #5：AI 抽取后台作业接口（真实逐文件进度 + 取消 + 公司隔离）
# ==============================================================================


def test_extract_background_job_progress_and_isolation(env, monkeypatch, tmp_path):
    """后台抽取 5 个虚构文件：轮询可见真实进度事件，完成后产出结果，跨公司查询 404。"""
    import time as _time

    cid_a = env["co_a"]["id"]
    cid_b = env["co_b"]["id"]
    client = env["client"]

    folder = tmp_path / "fictional_batch5"
    folder.mkdir()
    for i in range(1, 6):
        (folder / f"quote_{i}.txt").write_text(f"虚构厂{i}\n件{i} 1{i}元/个\n", encoding="utf-8")

    monkeypatch.setattr(
        doc_extract, "resolve_extraction_model", lambda: ("deepseek", "deepseek-flash", "k")
    )

    async def _fake_model(messages, **_kw):
        return json.dumps(
            {
                "quotes": [
                    {
                        "supplier_name": "虚构批量厂",
                        "product_name": "批量测试件",
                        "unit": "个",
                        "price_excl_tax": 10.0,
                        "moq": 100,
                        "raw_excerpt": "批量测试件 10元/个",
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(doc_extract, "_call_model", _fake_model)

    start_resp = client.post(
        "/api/trade/suppliers/extract/jobs",
        headers=env["headers"](cid_a),
        json={"paths": [str(folder)]},
    )
    assert start_resp.status_code == 200
    job_id = start_resp.json()["job_id"]

    # 跨公司查作业必须 404（先解除会话公司绑定再以公司 B 身份请求）
    deps_mod._ACTIVE_COMPANY.clear()
    cross = client.get(
        f"/api/trade/suppliers/extract/jobs/{job_id}",
        headers=env["headers"](cid_b),
    )
    assert cross.status_code == 404
    deps_mod._ACTIVE_COMPANY.clear()

    # 轮询直到完成
    final_job = None
    deadline = _time.time() + 10.0
    while _time.time() < deadline:
        st = client.get(
            f"/api/trade/suppliers/extract/jobs/{job_id}",
            headers=env["headers"](cid_a),
        )
        assert st.status_code == 200
        data = st.json()
        if data["status"] in ("done", "failed", "cancelled"):
            final_job = data
            break
        _time.sleep(0.05)

    assert final_job is not None
    assert final_job["status"] == "done"
    assert final_job["total"] == 5
    assert final_job["done"] == 5
    assert final_job["result"]["drafts_created"] == 5
    ev_types = [e["type"] for e in final_job["events"]]
    assert ev_types.count("file_start") == 5
    assert ev_types.count("file_done") == 5
