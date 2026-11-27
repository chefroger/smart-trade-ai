"""
供应商管理一期 · 第二批（询价侧）验收测试（B1–B10）。

逐条对应任务书 §6 验收用例：
  B1  询价单两态（open / decided 切换与拒绝第三态）
  B2  回复沉淀接缝（source='rfq'、rfq_id、source_customer_id、三向查询与比价、能力行 is_self_produced=2）
  B3  沉淀同步（改价同步更新单行 / 改回未回删除 / 删回复删除 / 删整单清理）
  B4  未回不沉淀（只加供应商不录回复 → supplier_quotes 无新增）
  B5  选中唯一（连选两家仅最后一家 selected=1 + 重复加同供应商仅一行）
  B6  公司隔离（rfqs / rfq_responses 列表/详情/改/删/选定跨公司 404 或不可见）
  B7  china-leads 工具（supplier_candidate_save 候选入库 / 同名复用 / 无绑定报错零写入）
  B8  只读工具（supplier_quote_search / supplier_compare / supplier_list 一致性、跨公司隔离与只读约束）
  B9  对外隔离（全档位 prompt 含隔离规则 + 扫描测试 + 注入预算 ≤ 5000）
  B10 导出导入（rfqs / rfq_responses 导出、连导两次幂等、quote_id 指向目标库沉淀报价）
"""

from __future__ import annotations

import importlib
import json
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trade import agent_context
from trade import company as company_mod
from trade import customer as customer_mod
from trade import database as db_mod
from trade import inquiry as inquiry_mod
from trade import prompt as prompt_mod
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

    def _fake_work_dir(name, slug, suggested_name=""):
        wd = tmp_path / "work" / (slug or "co")
        wd.mkdir(parents=True, exist_ok=True)
        return wd, True

    monkeypatch.setattr(company_mod.workdir, "_setup_work_directory", _fake_work_dir)
    (tmp_path / "work").mkdir(parents=True, exist_ok=True)

    db_mod.init_db()

    app = FastAPI()
    app.include_router(trade_router, prefix="/api/trade")
    token = "test-rfq-token"
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
# B1 询价单两态
# ==============================================================================


def test_b1_rfq_two_states_only(env):
    """B1：新建 open → 选定 decided → 取消选定回 open；第三态被拒绝。"""
    client = env["client"]
    cid = env["co_a"]["id"]
    hdr = env["headers"](cid)

    sup = supplier_mod.create_supplier(cid, name="恒泰阀门厂")
    r_create = client.post(
        "/api/trade/rfqs",
        json={"product_name": "球阀", "spec_model": "DN50", "quantity": 100, "unit": "台"},
        headers=hdr,
    )
    assert r_create.status_code == 200
    rfq = r_create.json()
    assert rfq["status"] == "open"

    # 拒绝第三态
    r_bad = client.put(f"/api/trade/rfqs/{rfq['id']}", json={"status": "cancelled"}, headers=hdr)
    assert r_bad.status_code == 400
    r_bad_create = client.post(
        "/api/trade/rfqs",
        json={"product_name": "球阀", "status": "draft"},
        headers=hdr,
    )
    assert r_bad_create.status_code == 400

    # 加入供应商 → 选定 → 单头置 decided
    resp = client.post(
        f"/api/trade/rfqs/{rfq['id']}/responses",
        json={"supplier_id": sup["id"]},
        headers=hdr,
    ).json()
    r_sel = client.post(f"/api/trade/rfq-responses/{resp['id']}/select", headers=hdr)
    assert r_sel.status_code == 200
    assert r_sel.json()["selected"] == 1
    assert client.get(f"/api/trade/rfqs/{rfq['id']}", headers=hdr).json()["status"] == "decided"

    # 取消选定 → 单头回 open
    r_unsel = client.post(f"/api/trade/rfq-responses/{resp['id']}/unselect", headers=hdr)
    assert r_unsel.status_code == 200
    assert r_unsel.json()["selected"] == 0
    assert client.get(f"/api/trade/rfqs/{rfq['id']}", headers=hdr).json()["status"] == "open"


# ==============================================================================
# B2 回复沉淀接缝
# ==============================================================================


def test_b2_response_quote_precipitation_and_batch1_seam(env):
    """B2：已回且有价 → 沉淀 supplier_quotes(source='rfq') + 能力行 is_self_produced=2，且进三向查询与比价。"""
    client = env["client"]
    cid = env["co_a"]["id"]
    hdr = env["headers"](cid)

    cust = customer_mod.create("Nordic Trade AB", "Erik", company_id=cid)
    inq = inquiry_mod.create(cust["id"], company_id=cid, title="Q4 阀门询盘")
    sup = supplier_mod.create_supplier(cid, name="东升铸造厂", tax_point=13.0)

    # 仅传 inquiry_id 时自动带出 customer_id
    rfq = client.post(
        "/api/trade/rfqs",
        json={
            "product_name": "不锈钢球阀",
            "spec_model": "DN50",
            "quantity": 300,
            "unit": "台",
            "inquiry_id": inq["id"],
        },
        headers=hdr,
    ).json()
    assert rfq["customer_id"] == cust["id"]

    resp = client.post(
        f"/api/trade/rfqs/{rfq['id']}/responses",
        json={"supplier_id": sup["id"]},
        headers=hdr,
    ).json()
    updated = client.put(
        f"/api/trade/rfq-responses/{resp['id']}",
        json={
            "responded": 1,
            "price_excl_tax": 120.0,
            "currency": "CNY",
            "lead_time_days": 15,
            "moq": 50,
            "notes": "含木箱",
        },
        headers=hdr,
    ).json()
    assert updated["responded"] == 1
    assert updated["responded_at"] != ""
    assert updated["quote_id"] is not None

    # 校验沉淀出的报价能被第一批三向查询（按客户查）找到
    by_cust = supplier_mod.search_quotes(cid, customer_id=cust["id"])
    assert len(by_cust) == 1
    q = by_cust[0]
    assert q["id"] == updated["quote_id"]
    assert q["source"] == "rfq"
    assert q["rfq_id"] == rfq["id"]
    assert q["source_customer_id"] == cust["id"]
    assert q["price_excl_tax"] == 120.0
    assert q["quoted_at"] == updated["responded_at"]

    # 校验沉淀出的报价能进第一批比价
    cmp_res = supplier_mod.compare_product(cid, product_name="不锈钢球阀")
    assert len(cmp_res["unit_groups"]) == 1
    assert cmp_res["unit_groups"][0]["unit"] == "台"
    assert cmp_res["unit_groups"][0]["suppliers"][0]["supplier_name"] == "东升铸造厂"

    # 校验顺带建出的能力行 is_self_produced=2
    sup_detail = supplier_mod.get_supplier(sup["id"], cid)
    assert len(sup_detail["products"]) == 1
    assert sup_detail["products"][0]["product_name"] == "不锈钢球阀"
    assert sup_detail["products"][0]["spec_model"] == "DN50"
    assert sup_detail["products"][0]["is_self_produced"] == 2


# ==============================================================================
# B3 沉淀同步 + B4 未回不沉淀
# ==============================================================================


def test_b3_and_b4_precipitation_sync_and_unresponded_guard(env):
    """B3 & B4：未回不沉淀；改价同步更新单行；改回未回删除；删回复删除；删整单清理。"""
    cid = env["co_a"]["id"]
    s1 = supplier_mod.create_supplier(cid, name="甲厂")
    s2 = supplier_mod.create_supplier(cid, name="乙厂")

    rfq = rfq_mod.create_rfq(cid, product_name="高压软管", spec_model="20mm", unit="米")
    r1 = rfq_mod.add_rfq_response(rfq["id"], cid, s1["id"])
    r2 = rfq_mod.add_rfq_response(rfq["id"], cid, s2["id"])

    # B4：只加供应商不录回复 → supplier_quotes 为空
    assert supplier_mod.search_quotes(cid, product_name="高压软管") == []

    # 录已回回复 → 沉淀一行
    r1 = rfq_mod.update_rfq_response(r1["id"], cid, responded=1, price_excl_tax=15.0)
    qid1 = r1["quote_id"]
    assert qid1 is not None
    assert len(supplier_mod.search_quotes(cid, product_name="高压软管")) == 1

    # B3.1：改回复价格 → 同步 UPDATE 同一行，不新建第二行
    r1 = rfq_mod.update_rfq_response(r1["id"], cid, price_excl_tax=14.2, price_incl_tax=16.0)
    assert r1["quote_id"] == qid1
    quotes = supplier_mod.search_quotes(cid, product_name="高压软管")
    assert len(quotes) == 1
    assert quotes[0]["price_excl_tax"] == 14.2
    assert quotes[0]["price_incl_tax"] == 16.0

    # B3.2：改回未回 → 沉淀行删除
    r1 = rfq_mod.update_rfq_response(r1["id"], cid, responded=0)
    assert r1["quote_id"] is None
    assert supplier_mod.search_quotes(cid, product_name="高压软管") == []

    # 重新沉淀两家后测删除单条回复与删除整单
    r1 = rfq_mod.update_rfq_response(r1["id"], cid, responded=1, price_excl_tax=14.0)
    r2 = rfq_mod.update_rfq_response(r2["id"], cid, responded=1, price_excl_tax=13.5)
    assert len(supplier_mod.search_quotes(cid, product_name="高压软管")) == 2

    # B3.3：删回复行 → 对应沉淀报价删除
    assert rfq_mod.delete_rfq_response(r1["id"], cid) is True
    rem = supplier_mod.search_quotes(cid, product_name="高压软管")
    assert len(rem) == 1
    assert rem[0]["supplier_id"] == s2["id"]

    # B3.4：删整单 → 剩余回复与沉淀报价一并清掉
    assert rfq_mod.delete_rfq(rfq["id"], cid) is True
    assert rfq_mod.get_rfq(rfq["id"], cid) is None
    assert supplier_mod.search_quotes(cid, product_name="高压软管") == []


# ==============================================================================
# B5 选中唯一 + 重复加入幂等
# ==============================================================================


def test_b5_single_selected_and_idempotent_add(env):
    """B5：连选两家仅最后一家 selected=1；同单重复加同一供应商仅一行。"""
    cid = env["co_a"]["id"]
    s1 = supplier_mod.create_supplier(cid, name="一厂")
    s2 = supplier_mod.create_supplier(cid, name="二厂")

    rfq = rfq_mod.create_rfq(cid, product_name="密封圈", unit="件")
    r1a = rfq_mod.add_rfq_response(rfq["id"], cid, s1["id"])
    r1b = rfq_mod.add_rfq_response(rfq["id"], cid, s1["id"])
    assert r1a["id"] == r1b["id"]

    r2 = rfq_mod.add_rfq_response(rfq["id"], cid, s2["id"])
    rfq_mod.select_rfq_response(r1a["id"], cid)
    rfq_mod.select_rfq_response(r2["id"], cid)

    detail = rfq_mod.get_rfq(rfq["id"], cid)
    assert len(detail["responses"]) == 2
    selected_ids = [r["supplier_id"] for r in detail["responses"] if r["selected"] == 1]
    assert selected_ids == [s2["id"]]
    assert detail["status"] == "decided"
    assert detail["selected_supplier_name"] == "二厂"


# ==============================================================================
# B6 公司隔离
# ==============================================================================


def test_b6_rfq_company_isolation(env):
    """B6：rfqs 与 rfq_responses 的列表/详情/改/删/选定/取消选定，跨公司一律 404 或查不到。"""
    client = env["client"]
    cid_a = env["co_a"]["id"]
    cid_b = env["co_b"]["id"]
    hdr_a = env["headers"](cid_a)

    sup_a = supplier_mod.create_supplier(cid_a, name="A公司供应商")
    rfq_a = client.post("/api/trade/rfqs", json={"product_name": "精密齿轮"}, headers=hdr_a).json()
    resp_a = client.post(
        f"/api/trade/rfqs/{rfq_a['id']}/responses",
        json={"supplier_id": sup_a["id"]},
        headers=hdr_a,
    ).json()

    # 切到公司 B
    deps_mod._ACTIVE_COMPANY.clear()
    hdr_b = env["headers"](cid_b)

    assert client.get("/api/trade/rfqs", headers=hdr_b).json() == []
    assert client.get(f"/api/trade/rfqs/{rfq_a['id']}", headers=hdr_b).status_code == 404
    assert client.put(f"/api/trade/rfqs/{rfq_a['id']}", json={"title": "hack"}, headers=hdr_b).status_code == 404
    assert client.delete(f"/api/trade/rfqs/{rfq_a['id']}", headers=hdr_b).status_code == 404
    assert client.post(
        f"/api/trade/rfqs/{rfq_a['id']}/responses",
        json={"supplier_id": sup_a["id"]},
        headers=hdr_b,
    ).status_code == 404
    assert client.put(
        f"/api/trade/rfq-responses/{resp_a['id']}",
        json={"responded": 1, "price_excl_tax": 1.0},
        headers=hdr_b,
    ).status_code == 404
    assert client.post(f"/api/trade/rfq-responses/{resp_a['id']}/select", headers=hdr_b).status_code == 404
    assert client.post(f"/api/trade/rfq-responses/{resp_a['id']}/unselect", headers=hdr_b).status_code == 404
    assert client.delete(f"/api/trade/rfq-responses/{resp_a['id']}", headers=hdr_b).status_code == 404


# ==============================================================================
# B7 china-leads 工具（supplier_candidate_save）
# ==============================================================================


def test_b7_supplier_candidate_save_tool(env):
    """B7：新建 status='候选'/source='china-leads'；同名再调复用不新建；无绑定公司报错且零写入。"""
    cid_a = env["co_a"]["id"]

    # 无绑定公司：报错且零写入
    with agent_context.bind_company(company_id=None):
        err_res = json.loads(plugin_tools.handle_supplier_candidate_save({"name": "未绑定工厂"}))
    assert "error" in err_res
    assert supplier_mod.list_suppliers(cid_a) == []

    # 绑定公司 A：新建候选供应商（含联系人与 source_url）
    with agent_context.bind_company(company_id=cid_a):
        res1 = json.loads(
            plugin_tools.handle_supplier_candidate_save({
                "name": "永康鑫盛五金厂",
                "short_name": "鑫盛",
                "main_products": "保温杯",
                "province": "浙江",
                "city": "金华",
                "source_url": "https://example.cn/xinsheng",
                "contact": {"name": "赵经理", "phone": "13800001234", "wechat": "wx_zhao"},
            })
        )
        assert res1["created"] is True
        assert res1["already_exists"] is False
        assert res1["supplier"]["status"] == "候选"
        assert res1["supplier"]["source"] == "china-leads"
        assert res1["contact"]["name"] == "赵经理"

        # 同名再调（含空白差异，norm 口径）→ 返回既有 id 不新建
        res2 = json.loads(
            plugin_tools.handle_supplier_candidate_save({"name": "  永康鑫盛五金厂  "})
        )
        assert res2["created"] is False
        assert res2["already_exists"] is True
        assert res2["supplier_id"] == res1["supplier_id"]
        assert len(supplier_mod.list_suppliers(cid_a)) == 1


# ==============================================================================
# B8 AI 只读工具
# ==============================================================================


def test_b8_readonly_supplier_tools_and_isolation(env, monkeypatch):
    """B8：三个只读工具返回与 API 一致、跨公司零泄漏、description 含内部禁止对外声明、无其余写工具。"""
    cid_a = env["co_a"]["id"]
    cid_b = env["co_b"]["id"]

    sup_a = supplier_mod.create_supplier(cid_a, name="Alpha 精密厂", status="合作中", tax_point=13.0)
    supplier_mod.create_quote(
        cid_a, sup_a["id"], product_name="钛合金螺栓", unit="件",
        price_excl_tax=10.0, quoted_at="2026-11-20",
    )
    sup_b = supplier_mod.create_supplier(cid_b, name="Beta 保密厂", status="合作中")
    supplier_mod.create_quote(
        cid_b, sup_b["id"], product_name="钛合金螺栓", unit="件",
        price_excl_tax=8.0, quoted_at="2026-11-20",
    )

    # 绑定公司 A：三工具返回一致且不漏公司 B 数据
    with agent_context.bind_company(company_id=cid_a):
        list_res = json.loads(plugin_tools.handle_supplier_list({"status": "合作中"}))
        assert list_res["count"] == 1
        assert list_res["suppliers"][0]["name"] == "Alpha 精密厂"

        quote_res = json.loads(plugin_tools.handle_supplier_quote_search({"product_name": "钛合金螺栓"}))
        assert quote_res["count"] == 1
        assert quote_res["quotes"][0]["supplier_name"] == "Alpha 精密厂"

        cmp_res = json.loads(plugin_tools.handle_supplier_compare({"product_name": "钛合金螺栓"}))
        assert len(cmp_res["unit_groups"]) == 1
        assert [s["supplier_name"] for s in cmp_res["unit_groups"][0]["suppliers"]] == ["Alpha 精密厂"]

    # 无绑定公司一律报错
    with agent_context.bind_company(company_id=None):
        assert "error" in json.loads(plugin_tools.handle_supplier_list({}))
        assert "error" in json.loads(plugin_tools.handle_supplier_quote_search({}))
        assert "error" in json.loads(plugin_tools.handle_supplier_compare({"product_name": "钛合金螺栓"}))

    # 校验三个只读工具 description 均写明内部采购禁止对外声明
    for schema in (
        plugin_tools.SUPPLIER_QUOTE_SEARCH_SCHEMA,
        plugin_tools.SUPPLIER_COMPARE_SCHEMA,
        plugin_tools.SUPPLIER_LIST_SCHEMA,
    ):
        assert "内部采购数据" in schema["description"]
        assert "禁止写入给客户的邮件" in schema["description"]

    # 校验 TRADE_HOST=1 下插件工具集仅含 3 个只读工具 + 1 个受控 candidate_save，无其他 supplier 写工具
    monkeypatch.setenv("TRADE_HOST", "1")
    import trade.hermes_chat_memory_plugin as plugin_pkg

    importlib.reload(plugin_pkg)
    supplier_tool_names = {name for name, *_ in plugin_pkg._TOOLS if name.startswith("supplier_")}
    assert supplier_tool_names == {
        "supplier_candidate_save",
        "supplier_quote_search",
        "supplier_compare",
        "supplier_list",
    }


# ==============================================================================
# B9 对外隔离 + 注入预算实测
# ==============================================================================


def test_b9_outbound_isolation_all_tiers_and_budget():
    """B9：所有系统提示词档位均含供应商对外隔离规则；注入预算前 5 大合计 ≤ 5000。"""
    tiers = [
        prompt_mod.TRADE_SYSTEM_PROMPT,
        prompt_mod.TRADE_SYSTEM_PROMPT_FIRST_TURN,
        prompt_mod.TRADE_SYSTEM_PROMPT_MINIMAL,
        prompt_mod.TRADE_SYSTEM_PROMPT_OSINT,
        prompt_mod.TRADE_SYSTEM_PROMPT_FULL,
        prompt_mod.TRADE_SYSTEM_PROMPT_FULL_DOCGEN,
    ]
    for tier in tiers:
        assert "供应商名称、采购价格、能力库与报价历史属内部数据" in tier
        assert "禁止引用这些数据" in tier

    # 确认 b2b-china-leads Phase 5 已加入人工确认后入库提示
    skill_path = Path(__file__).resolve().parent.parent / "skills" / "b2b-china-leads" / "SKILL.md"
    skill_text = skill_path.read_text(encoding="utf-8")
    assert "supplier_candidate_save" in skill_text
    assert "用户没点头不存" in skill_text


# ==============================================================================
# B10 导出 / 导入扩展
# ==============================================================================


def test_b10_export_and_idempotent_import_rfqs(env):
    """B10：导出含 rfqs/rfq_responses；连导两次不增行；导入后 response.quote_id 指向目标库沉淀报价。"""
    cid_a = env["co_a"]["id"]

    cust = customer_mod.create("Global Valve Ltd", "John", company_id=cid_a)
    inq = inquiry_mod.create(cust["id"], company_id=cid_a, title="Valve RFQ Inquiry")
    sup = supplier_mod.create_supplier(cid_a, name="导出询价厂", tax_point=13.0)

    rfq = rfq_mod.create_rfq(
        cid_a,
        title="阀门采购询价",
        product_name="闸阀",
        spec_model="DN80",
        quantity=50,
        unit="台",
        inquiry_id=inq["id"],
        customer_id=cust["id"],
    )
    resp = rfq_mod.add_rfq_response(rfq["id"], cid_a, sup["id"])
    resp = rfq_mod.update_rfq_response(resp["id"], cid_a, responded=1, price_excl_tax=210.0)
    rfq_mod.select_rfq_response(resp["id"], cid_a)
    assert resp["quote_id"] is not None

    zip_path = env["tmp_path"] / "rfq-export.zip"
    exporter.export_company(cid_a, dest_zip=zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["tables"]["rfqs"]["rows"] == 1
        assert manifest["tables"]["rfq_responses"]["rows"] == 1

    # 导入到新公司
    rep_new = importer.import_company(zip_path, force_new=True)
    new_cid = rep_new["target"]["id"]
    assert rep_new["tables"]["rfqs"]["added"] == 1
    assert rep_new["tables"]["rfq_responses"]["added"] == 1

    # 连导两次同一目标公司：两表一条不增
    rep_again = importer.import_company(zip_path, target_company_id=new_cid)
    assert rep_again["tables"]["rfqs"]["added"] == 0
    assert rep_again["tables"]["rfqs"]["skipped"] == 1
    assert rep_again["tables"]["rfq_responses"]["added"] == 0
    assert rep_again["tables"]["rfq_responses"]["skipped"] == 1

    # 校验目标库 response.quote_id 指向目标库对应的沉淀报价行，且 rfq_id / customer_id 均正确重映射
    imported_rfqs = rfq_mod.list_rfqs(new_cid)
    assert len(imported_rfqs) == 1
    detail = rfq_mod.get_rfq(imported_rfqs[0]["id"], new_cid)
    assert detail["status"] == "decided"
    assert detail["customer_id"] is not None and detail["customer_id"] != cust["id"]
    assert detail["inquiry_id"] is not None and detail["inquiry_id"] != inq["id"]
    assert len(detail["responses"]) == 1

    imp_resp = detail["responses"][0]
    assert imp_resp["quote_id"] is not None
    assert imp_resp["quote_id"] != resp["quote_id"]

    imp_quotes = supplier_mod.search_quotes(new_cid, product_name="闸阀")
    assert len(imp_quotes) == 1
    assert imp_quotes[0]["id"] == imp_resp["quote_id"]
    assert imp_quotes[0]["rfq_id"] == detail["id"]
    assert imp_quotes[0]["source_customer_id"] == detail["customer_id"]
