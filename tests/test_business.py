"""
业务层测试 — company / library / customer / chat_memory CRUD。

所有测试使用独立临时数据库，不影响实际数据。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def test_db(monkeypatch, tmp_path):
    """创建临时数据库并初始化 schema，mock 掉 _get_db_path 和桌面工作目录。"""
    db_path = tmp_path / "trade.db"

    import trade.database as _db
    original_db = _db._get_db_path
    _db._get_db_path = lambda: db_path

    from trade.database import SCHEMA_SQL, _add_spare_columns
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    _add_spare_columns(conn)
    conn.commit()
    conn.close()

    # 把桌面工作目录重定向到 tmp_path，避免污染真实桌面
    import trade.company as _co

    def _mock_work_dir(company_name, slug, suggested_name=""):
        work_dir = tmp_path / (suggested_name or company_name)
        work_dir.mkdir(parents=True, exist_ok=True)
        for cat_name, _ in _co._WORK_DIR_CATEGORIES:
            (work_dir / cat_name).mkdir(parents=True, exist_ok=True)
        return work_dir, True

    monkeypatch.setattr(_co, "_setup_work_directory", _mock_work_dir)

    yield db_path

    _db._get_db_path = original_db


@pytest.fixture
def company_id(test_db):
    """创建一个测试公司并返回其 ID。"""
    from trade import company
    c = company.create(name="Test Company", slug="test-company")
    return c["id"]


# ── Company CRUD ────────────────────────────────────────────────────────────


class TestCompanyCRUD:
    """测试公司实体的增删改查。"""

    def test_create_company(self, test_db):
        """创建公司：返回字典含 id/name/slug。"""
        from trade import company
        c = company.create(name="ACME Corp")
        assert c["id"] > 0
        assert c["name"] == "ACME Corp"
        assert c["slug"] == "acme-corp"
        assert c["is_active"] is True

    def test_create_duplicate_slug(self, test_db):
        """重复 slug 应自动递增后缀。"""
        from trade import company
        company.create(name="First", slug="same-slug")
        c2 = company.create(name="Second", slug="same-slug")
        assert c2["slug"] == "same-slug-2"

    def test_list_all(self, test_db):
        """list_all 返回激活和未激活的公司。"""
        from trade import company
        company.create(name="Active Co")
        company.create(name="Inactive Co")
        all_companies = company.list_all()
        assert len(all_companies) >= 2

    def test_get_by_id(self, test_db, company_id):
        """get 返回正确的公司。"""
        from trade import company
        c = company.get(company_id)
        assert c["name"] == "Test Company"
        assert c["slug"] == "test-company"

    def test_get_nonexistent(self, test_db):
        """不存在的 ID 返回 None。"""
        from trade import company
        assert company.get(99999) is None

    def test_update_company(self, test_db, company_id):
        """更新公司字段：只更新传入的字段。"""
        from trade import company
        result = company.update(company_id, name="Updated Name", website="https://example.com")
        assert result is not None
        assert result["name"] == "Updated Name"
        assert result["website"] == "https://example.com"
        # slug 不应被修改
        assert result["slug"] == "test-company"

    def test_update_nonexistent(self, test_db):
        """更新不存在的公司返回 None。"""
        from trade import company
        assert company.update(99999, name="X") is None

    def test_deactivate_company(self, test_db, company_id):
        """可以将公司设为不活跃。"""
        from trade import company
        result = company.update(company_id, is_active=False)
        assert result["is_active"] is False

    def test_delete_company_cascade(self, test_db, company_id):
        """软删除：delete 设置 is_active=0，数据保留。purge 才物理删除。"""
        from trade import chat_memory, company, customer, library

        lib = library.create("Test Lib", "/tmp/test", company_id=company_id)
        cust = customer.create("Test Cust", company_id=company_id)
        conv = chat_memory.save(company_id, "test query", "test response",
                                 library_id=lib["id"])

        # 软删除 — 数据仍存在
        assert company.delete(company_id)
        c = company.get(company_id)
        assert c is not None
        assert c["is_active"] is False

        # 物理删除 — 级联清除
        company.purge(company_id)
        assert library.get(lib["id"]) is None
        assert customer.admin_get(cust["id"]) is None
        assert chat_memory.get(company_id, conv["id"]) is None

    def test_create_empty_name(self, test_db):
        """空公司名应抛出 ValueError。"""
        from trade import company
        with pytest.raises(ValueError, match="empty"):
            company.create(name="")
        with pytest.raises(ValueError, match="empty"):
            company.create(name="   ")


class TestTradeCompany:
    """测试 trade_companies 配置表。"""

    def test_trade_company_created_with_company(self, test_db):
        """创建公司时自动创建 trade_companies 记录。"""
        from trade import company
        c = company.create(name="New Co")
        tc = company.get_trade_company(c["id"])
        assert tc is not None
        assert tc["company_id"] == c["id"]
        assert tc["is_active"] == 1
        assert tc["agent_identity_md"] == ""

    def test_update_agent_identity(self, test_db, company_id):
        """更新公司的 agent_identity_md。"""
        from trade import company
        identity = "## 公司身份\n测试身份文本"
        result = company.update_trade_company(company_id, agent_identity_md=identity)
        assert result["agent_identity_md"] == identity

    def test_get_agent_identity_from_db(self, test_db, company_id):
        """get_agent_identity 优先读 DB。"""
        from trade import company
        identity = "DB identity"
        company.update_trade_company(company_id, agent_identity_md=identity)
        assert company.get_agent_identity(company_id) == identity


# ── Library CRUD ────────────────────────────────────────────────────────────


class TestLibraryCRUD:
    """测试文档库实体的增删改查。"""

    def test_create_library(self, test_db, company_id):
        """创建文档库：返回字典含 name/root_path。"""
        from trade import library
        lib = library.create("Product Docs", "/tmp/products", "产品文档",
                             company_id=company_id)
        assert lib["id"] > 0
        assert lib["name"] == "Product Docs"
        assert lib["company_id"] == company_id

    def test_list_by_company(self, test_db, company_id):
        """列出特定公司的文档库（含自动创建的工作目录库）。"""
        from trade import library
        # company.create() 自动创建了 8 个工作子目录库
        auto_libs = library.list_by_company(company_id)
        auto_count = len(auto_libs)

        library.create("Lib A", "/tmp/a", company_id=company_id)
        library.create("Lib B", "/tmp/b", company_id=company_id)

        libs = library.list_by_company(company_id)
        assert len(libs) == auto_count + 2
        assert {"Lib A", "Lib B"}.issubset({l["name"] for l in libs})

    def test_data_isolation(self, test_db):
        """不同公司的文档库应隔离。"""
        from trade import company, library
        c1 = company.create(name="Company 1", slug="co1")
        c2 = company.create(name="Company 2", slug="co2")

        library.create("C1 Lib", "/tmp/c1", company_id=c1["id"])
        library.create("C2 Lib", "/tmp/c2", company_id=c2["id"])

        c1_libs = library.list_by_company(c1["id"])
        c2_libs = library.list_by_company(c2["id"])
        # 各有自动创建的 8 个工作目录库 + 1 个手动库
        assert len(c1_libs) >= 1
        assert len(c2_libs) >= 1
        # C2 看不到 C1 的库
        c1_lib_names = {l["name"] for l in c1_libs}
        assert "C2 Lib" not in c1_lib_names

    def test_get_with_company_scope(self, test_db, company_id):
        """跨公司查询应返回 None。"""
        from trade import company, library
        c2 = company.create(name="Other Co", slug="other-co")
        lib = library.create("My Lib", "/tmp/mine", company_id=company_id)

        # 同一公司 → 可以获取
        assert library.get(lib["id"], company_id=company_id) is not None
        # 不同公司 → None
        assert library.get(lib["id"], company_id=c2["id"]) is None

    def test_update_library(self, test_db, company_id):
        """更新文档库字段。"""
        from trade import library
        lib = library.create("Old Name", "/tmp/old", company_id=company_id)
        result = library.update(lib["id"], company_id=company_id, name="New Name")
        assert result["name"] == "New Name"

    def test_delete_library(self, test_db, company_id):
        """删除文档库后 get 返回 None。"""
        from trade import library
        lib = library.create("To Delete", "/tmp/del", company_id=company_id)
        library.delete(lib["id"], company_id=company_id)
        assert library.get(lib["id"]) is None


# ── Customer CRUD ───────────────────────────────────────────────────────────


class TestCustomerCRUD:
    """测试客户实体的增删改查。"""

    def test_create_customer(self, test_db, company_id):
        """创建客户：返回字典含 name/contact。"""
        from trade import customer
        cust = customer.create("ACME Buyer", "buyer@acme.com",
                               "重要客户", company_id=company_id)
        assert cust["id"] > 0
        assert cust["name"] == "ACME Buyer"
        assert cust["company_id"] == company_id

    def test_list_by_company(self, test_db, company_id):
        """列出特定公司的所有客户。"""
        from trade import customer
        customer.create("Cust A", company_id=company_id)
        customer.create("Cust B", company_id=company_id)

        custs = customer.list_by_company(company_id)
        assert len(custs) == 2

    def test_link_library_to_customer(self, test_db, company_id):
        """关联文档库到客户。"""
        from trade import customer, library
        cust = customer.create("Test Cust", company_id=company_id)
        lib = library.create("Test Lib", "/tmp/testlib", company_id=company_id)

        customer.link_library(cust["id"], lib["id"], company_id=company_id)
        linked = customer.get_libraries(cust["id"], company_id=company_id)
        assert len(linked) == 1
        assert linked[0]["id"] == lib["id"]

    def test_unlink_library(self, test_db, company_id):
        """取消关联。"""
        from trade import customer, library
        cust = customer.create("Test Cust", company_id=company_id)
        lib = library.create("Test Lib", "/tmp/testlib", company_id=company_id)

        customer.link_library(cust["id"], lib["id"], company_id=company_id)
        customer.unlink_library(cust["id"], lib["id"], company_id=company_id)
        assert customer.get_libraries(cust["id"], company_id=company_id) == []

    def test_customer_data_isolation(self, test_db):
        """不同公司的客户应隔离。"""
        from trade import company, customer
        c1 = company.create(name="C1", slug="co1")
        c2 = company.create(name="C2", slug="co2")

        c1_cust = customer.create("C1 Customer", company_id=c1["id"])
        customer.create("C2 Customer", company_id=c2["id"])

        # C1 看不到 C2 的客户
        assert customer.get(c1_cust["id"], company_id=c2["id"]) is None


# ── Chat Memory CRUD ────────────────────────────────────────────────────────


class TestChatMemory:
    """测试对话记录存储。"""

    def test_save_and_retrieve(self, test_db, company_id):
        """保存对话后可以检索。"""
        from trade import chat_memory
        conv = chat_memory.save(company_id, "What is MOQ?",
                                "MOQ is Minimum Order Quantity",
                                files_read=[{"file": "catalog.pdf", "pages": [1, 2]}])
        assert conv["id"] > 0
        assert conv["query"] == "What is MOQ?"
        assert len(conv["files_read"]) == 1

    def test_list_recent(self, test_db, company_id):
        """list_by_company 按时间倒序返回。"""
        from trade import chat_memory
        chat_memory.save(company_id, "Q1", "A1")
        chat_memory.save(company_id, "Q2", "A2")

        recent = chat_memory.list_by_company(company_id, limit=5)
        assert len(recent) == 2
        # 最新在前
        assert recent[0]["query"] == "Q2"

    def test_conversation_isolation(self, test_db):
        """不同公司的对话应隔离。"""
        from trade import chat_memory, company
        c1 = company.create(name="C1", slug="co1")
        c2 = company.create(name="C2", slug="co2")

        chat_memory.save(c1["id"], "C1 secret", "A1")
        chat_memory.save(c2["id"], "C2 secret", "A2")

        c1_convs = chat_memory.list_by_company(c1["id"])
        assert len(c1_convs) == 1
        assert c1_convs[0]["query"] == "C1 secret"

    def test_update_response(self, test_db, company_id):
        """更新对话回复。"""
        from trade import chat_memory
        conv = chat_memory.save(company_id, "Q", "Old response")
        result = chat_memory.update_response(company_id, conv["id"], "New response")
        assert result["response"] == "New response"

    def test_delete_conversation(self, test_db, company_id):
        """删除对话。"""
        from trade import chat_memory
        conv = chat_memory.save(company_id, "Q", "A")
        assert chat_memory.delete(company_id, conv["id"]) is True
        assert chat_memory.get(company_id, conv["id"]) is None

    def test_get_recent_chronological(self, test_db, company_id):
        """get_recent 应按时间正序返回（用于上下文注入）。"""
        from trade import chat_memory
        chat_memory.save(company_id, "First")
        chat_memory.save(company_id, "Second")
        chat_memory.save(company_id, "Third")

        recent = chat_memory.get_recent(company_id, limit=20)
        # get_recent 内部做了 reverse，应返回正序
        queries = [r["query"] for r in recent]
        assert queries == ["First", "Second", "Third"]


# ── Onboarding ──────────────────────────────────────────────────────────────


class TestOnboarding:
    """测试首次运行引导。"""

    def test_is_onboarding_done_empty_db(self, test_db):
        """空数据库应返回 False。"""
        from trade import onboarding
        # 重置进程级标志（因为模块在被其他测试 import 后可能已设为 True）
        onboarding._onboarding_done = False
        assert onboarding.is_onboarding_done() is False

    def test_create_first_company(self, test_db):
        """首次创建公司应成功。"""
        from trade import onboarding
        # 重置标志
        onboarding.reset_onboarding_flag()

        result = onboarding.create_first_company(
            company_name="My Trade Co",
            contact_name="John",
            contact_email="john@tradeco.com",
            identity_data={
                "products": "LED lights",
                "differentiation": "Factory direct",
                "target_region": "Europe",
            },
        )
        assert result["company"]["name"] == "My Trade Co"
        assert result["trade_company"]["agent_identity_md"] is not None
        assert "LED lights" in result["trade_company"]["agent_identity_md"]

        # 引导完成后应返回 True
        assert onboarding.is_onboarding_done() is True

    def test_create_first_company_after_done(self, test_db, company_id):
        """已有公司后 onboarding flag 应为 True。"""
        from trade import onboarding
        # company_id fixture 已创建了公司，所以 onboarding 标志应为 True
        assert onboarding.is_onboarding_done() is True


class TestRootPathValidation:
    """测试文档库 root_path 校验逻辑（P0-1 回归测试）。"""

    def test_forbidden_dirs_rejected(self):
        """敏感数据目录必须被拒绝（跨平台：家目录下的敏感子目录 + 家目录本身 + 根目录）。"""
        from pathlib import Path

        from trade.library import _validate_root_path

        home = Path.home()
        forbidden = [
            str(home / ".ssh"),
            str(home / ".ssh" / "known_hosts"),
            str(home / ".hermes"),
            str(home / ".trade"),
            str(home),          # 家目录本身
            str(Path(home.anchor).resolve()),  # 根目录（跨平台）
        ]
        for p in forbidden:
            with pytest.raises(ValueError, match="敏感|根目录|家目录"):
                _validate_root_path(p)

    def test_legal_dirs_allowed(self, tmp_path):
        """合法目录必须放行（跨平台：家目录下的普通子目录 + pytest 临时目录）。"""
        from pathlib import Path

        from trade.library import _validate_root_path

        home = Path.home()
        legal = [
            str(home / "Documents" / "client-files"),
            str(tmp_path / "subdir"),
        ]
        for p in legal:
            result = _validate_root_path(p)
            assert Path(result).is_absolute()
