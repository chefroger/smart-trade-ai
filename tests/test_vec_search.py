"""trade.vec_search 模块测试。

- 降级路径（无 sqlite-vec）：纯标准库可跑；
- 向量路径：sqlite-vec 可用时才跑，否则 skip。
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trade import vec_search  # noqa: E402
from trade.embeddings import TfidfBackend  # noqa: E402

try:
    import sqlite_vec  # noqa: F401

    HAS_VEC = vec_search.vec_available()
except ImportError:
    HAS_VEC = False

needs_vec = pytest.mark.skipif(not HAS_VEC, reason="sqlite-vec 未安装")


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    yield c
    c.close()


@pytest.fixture()
def customer_conn():
    """带 customers 表的连接（降级路径用）。"""
    c = sqlite3.connect(":memory:")
    c.execute(
        """CREATE TABLE customers (
               id INTEGER PRIMARY KEY, company_id INTEGER,
               name TEXT, contact TEXT, note TEXT,
               extra1 TEXT DEFAULT '{}', extra2 TEXT DEFAULT '{}')"""
    )
    c.executemany(
        "INSERT INTO customers (company_id, name, contact, note) VALUES (?,?,?,?)",
        [
            (1, "Acme Lighting", "john@acme.com", "德国灯具采购商"),
            (1, "Beta Foods", "li@beta.com", "食品进口商"),
            (2, "Acme Lighting", "other@acme.com", "另一家公司的同名客户"),
        ],
    )
    c.commit()
    yield c
    c.close()


def test_keyword_fallback_search(customer_conn):
    hits = vec_search.keyword_search_customers(customer_conn, "灯具", 1)
    assert len(hits) == 1 and hits[0]["customer_id"] == 1
    # 多租户隔离：公司 2 查不到公司 1 的
    hits2 = vec_search.keyword_search_customers(customer_conn, "Acme", 2)
    assert [h["customer_id"] for h in hits2] == [3]


def test_keyword_fallback_empty_query(customer_conn):
    assert vec_search.keyword_search_customers(customer_conn, "", 1) == []


def test_search_customers_falls_back_without_vec(customer_conn, monkeypatch):
    monkeypatch.setattr(vec_search, "vec_available", lambda: False)
    hits = vec_search.search_customers(customer_conn, "灯具", 1)
    assert len(hits) == 1 and hits[0]["customer_id"] == 1


@needs_vec
def test_vec_rebuild_and_search():
    c = sqlite3.connect(":memory:")
    backend = TfidfBackend()
    rows = [
        (1, 1, "Acme Lighting 德国灯具采购商 john@acme.com"),
        (2, 1, "Beta Foods 食品进口商 li@beta.com"),
        (3, 1, "Gamma Tools 五金工具批发"),
    ]
    n = vec_search.rebuild_customer_index(c, rows, backend=backend)
    assert n == 3
    hits = vec_search.semantic_search_customers(c, "灯具采购", 1, backend=backend)
    assert hits, "应召回灯具客户"
    assert hits[0]["customer_id"] == 1
    c.close()


@needs_vec
def test_vec_company_isolation():
    c = sqlite3.connect(":memory:")
    backend = TfidfBackend()
    rows = [
        (1, 1, "Acme Lighting 灯具"),
        (2, 2, "Acme Lighting 灯具"),
    ]
    vec_search.rebuild_customer_index(c, rows, backend=backend)
    hits = vec_search.semantic_search_customers(c, "灯具", 1, backend=backend)
    assert all(h["customer_id"] == 1 for h in hits)
    c.close()


@needs_vec
def test_vec_dim_change_rebuilds():
    c = sqlite3.connect(":memory:")
    b1 = TfidfBackend(ngram_range=(2, 2), max_features=128)
    b2 = TfidfBackend(ngram_range=(2, 4), max_features=4096)
    rows = [(1, 1, "测试文本")]
    assert vec_search.rebuild_customer_index(c, rows, backend=b1) == 1
    # 换后端（维度变化）应自动重建而不报错
    assert vec_search.rebuild_customer_index(c, rows, backend=b2) == 1
    c.close()


# ── 跨进程持久化 / 默认阈值 / 增删改钩子（2026-10-13 集成时补）───────────────

@needs_vec
def test_state_persists_across_process_restart(conn):
    """fit 状态持久化后，新进程（新 backend 实例）仍能用同一向量空间检索。

    不持久化的话：服务一重启，查询向量与库里存的向量不可比 → 语义检索静默消失。
    """
    from trade.embeddings import reset_backend

    reset_backend()
    rows = [(1, 1, "深圳光明照明有限公司 灯具出口 德国汉堡"), (2, 1, "宁波五金制品厂 紧固件 美国")]
    assert vec_search.rebuild_customer_index(conn, rows, backend=TfidfBackend()) == 2
    reset_backend()  # 模拟进程重启：内存里的 fit 状态全没了

    hits = vec_search.semantic_search_customers(conn, "德国汉堡的灯具买家", company_id=1, min_score=0.0)
    assert hits and hits[0]["customer_id"] == 1, "重启后向量空间恢复失败（应能查到，且排第一）"


@needs_vec
def test_default_threshold_excludes_orthogonal_noise(conn):
    """默认阈值必须高于正交基线 —— 否则任何查询都会把全部客户当命中返回。

    score = 1/(1+distance)，无关向量（正交）距离恒为 √2 → score 恒 0.4142。
    出厂默认 0.35 低于该基线，实测会把 5 个客户全数返回。
    """
    from trade.embeddings import reset_backend

    reset_backend()
    rows = [
        (1, 1, "深圳光明照明有限公司 灯具出口 德国汉堡买家"),
        (2, 1, "宁波五金制品厂 紧固件 美国市场 家得宝供应商"),
        (3, 1, "青岛纺织品进出口 家纺毛巾 澳大利亚批发商"),
    ]
    assert vec_search.rebuild_customer_index(conn, rows, backend=TfidfBackend()) == 3

    hits = vec_search.semantic_search_customers(conn, "灯具", company_id=1)  # 用默认阈值
    ids = [h["customer_id"] for h in hits]
    assert ids == [1], f"无关客户也过了默认阈值：{ids}"


@needs_vec
def test_scores_expose_cosine_for_interpretable_tuning(conn):
    """返回值带 cosine，便于按可解释尺度调阈值（score 尺度有 0.4142 的隐形基线）。"""
    from trade.embeddings import reset_backend

    reset_backend()
    assert vec_search.rebuild_customer_index(
        conn, [(1, 1, "灯具 德国 汉堡")], backend=TfidfBackend()
    ) == 1
    hits = vec_search.semantic_search_customers(conn, "灯具", company_id=1, min_score=0.0)
    assert hits and "cosine" in hits[0]
    assert -1.0 <= hits[0]["cosine"] <= 1.0


@needs_vec
class TestCustomerIndexHooks:
    """客户增删改后索引同步 —— 防"刚建的客户搜不到、还不降级"。

    向量检索只在"命中为空"时才降级关键词，索引过期会让新客户彻底不可见：
    向量路径返回了旧数据（非空）→ 永远不走降级 → 用户搜不到刚建的人。
    """

    @pytest.fixture()
    def env(self, monkeypatch, tmp_path):
        """临时库（schema 就绪），不触碰真实数据。"""
        db_path = tmp_path / "trade.db"
        import trade.database as _db

        monkeypatch.setattr(_db, "_get_db_path", lambda: db_path)
        from trade.database import SCHEMA_SQL, _add_spare_columns

        c = sqlite3.connect(str(db_path))
        c.executescript(SCHEMA_SQL)
        _add_spare_columns(c)
        c.commit()
        c.close()
        from trade.embeddings import reset_backend

        reset_backend()  # 每个用例从干净的向量空间开始
        return db_path

    def test_new_customer_searchable_immediately_and_gone_after_delete(self, env):
        from trade import customer as cust_mod
        from trade.company import create as create_company
        from trade.database import get_connection

        company = create_company(name="钩子公司", slug="hook-co")
        cid = company["id"]
        created = cust_mod.create(
            "深圳光明照明有限公司", company_id=cid, country="德国", note="汉堡灯具买家"
        )

        conn = get_connection()
        try:
            # 该查询 LIKE 匹配不到任何字段 → 有结果就只可能来自向量路径
            hits = vec_search.search_customers(conn, "德国汉堡的灯具买家", company_id=cid)
            assert any(h["customer_id"] == created["id"] for h in hits), "刚建的客户搜不到（索引钩子没生效）"
        finally:
            conn.close()

        assert cust_mod.delete(created["id"], company_id=cid) is True
        conn = get_connection()
        try:
            hits = vec_search.search_customers(conn, "德国汉堡的灯具买家", company_id=cid)
            assert all(h["customer_id"] != created["id"] for h in hits), "删掉的客户仍能从索引搜出来"
        finally:
            conn.close()

    def test_index_failure_never_breaks_customer_write(self, env, monkeypatch):
        """索引写失败（如扩展坏掉）绝不能让建客户失败。"""
        from trade import customer as cust_mod
        from trade.company import create as create_company

        company = create_company(name="容错公司", slug="tolerant-co")

        def _boom(*a, **kw):
            raise RuntimeError("模拟索引写入崩溃")

        monkeypatch.setattr(vec_search, "upsert_customer_vector", _boom)
        monkeypatch.setattr(vec_search, "rebuild_all_customers", _boom)
        created = cust_mod.create("某客户", company_id=company["id"])
        assert created.get("id"), "索引失败把建客户也带崩了"


def test_search_endpoint_declared_before_dynamic_route():
    """`/customers/search` 必须声明在 `/customers/{customer_id}` 之前。

    否则 FastAPI 会把 "search" 拿去转 int → 422，端点等于不存在
    （项目里 `/customers/duplicates` 就是按这个顺序排的）。
    """
    import pathlib

    src = pathlib.Path("trade/api/customers.py").read_text(encoding="utf-8")
    assert src.index('"/customers/search"') < src.index('"/customers/{customer_id}"')


@needs_vec
def test_default_threshold_keeps_weak_but_real_matches(conn):
    """默认阈值的**召回侧**：弱相关但真实的命中不得被切掉（否则用户搜不到）。

    实测（3 条客户、查询「深圳的客户」）：正确客户 cos≈0.12 只拿到 0.4299 分。
    若阈值定在 0.43（cos≈0.12），这类命中全被切；而本功能的降级链是
    「向量为空 → 关键词 LIKE」，自然语言查询在 LIKE 下查不到东西 →
    用户得到空结果。搜索场景里弱结果优于空结果，故默认取 0.42（刚过正交基线）。
    正交噪声（0.4142）在 0.42 下仍被滤掉 —— 见 test_default_threshold_excludes_orthogonal_noise。
    """
    from trade.embeddings import reset_backend

    reset_backend()
    rows = [
        (1, 1, "深圳市光明照明有限公司 张伟 灯具出口 德国 汉堡地区买家"),
        (2, 1, "宁波五金制品厂 李娜 紧固件 美国市场 家得宝供应商"),
        (3, 1, "青岛纺织品进出口 刘洋 家纺 毛巾 澳大利亚 批发商"),
    ]
    assert vec_search.rebuild_customer_index(conn, rows, backend=TfidfBackend()) == 3

    hits = vec_search.semantic_search_customers(conn, "深圳的客户", company_id=1)  # 默认阈值
    ids = [h["customer_id"] for h in hits]
    assert 1 in ids, f"弱相关但正确的客户被默认阈值切掉了（recall 回归）：{ids}"
    # 纯噪声（无任何字符重叠）仍须被滤掉
    assert all(h["cosine"] > 0.0 for h in hits), f"正交噪声漏进来了：{hits}"
