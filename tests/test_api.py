"""
API 层测试 — FastAPI 端点 + skill_router 匹配。

直接测试路由函数（不经过 HTTP），mock 外部 Hermes 依赖。
HTTP 层测试通过 run_server_smoke 验证即可。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def setup_mocks():
    """模块级 mock Hermes 依赖。"""
    with patch.dict(sys.modules, {
        "hermes_cli": MagicMock(),
        "hermes_cli.config": MagicMock(),
        "hermes_cli.auth": MagicMock(),
        "hermes_cli.env_loader": MagicMock(),
        "hermes_cli.models": MagicMock(),
        "hermes_constants": MagicMock(),
        "run_agent": MagicMock(),
    }):
        import hermes_cli
        hermes_cli.__version__ = "0.13.0"

        from hermes_cli import env_loader
        env_loader.load_hermes_dotenv = MagicMock()

        import hermes_constants
        hermes_constants.get_hermes_home = MagicMock(return_value=Path("/tmp/.hermes"))

        from hermes_cli import config
        config.load_config = MagicMock(return_value={
            "model": {"provider": "openai", "default": "gpt-4o"}
        })

        from hermes_cli import auth
        class MockProviderConfig:
            auth_type = "api_key"
            api_key_env_vars = ["OPENAI_API_KEY"]
            display_name = "OpenAI"
            base_url_env_var = ""

        auth.PROVIDER_REGISTRY = {"openai": MockProviderConfig()}
        yield


@pytest.fixture
def test_db(monkeypatch, tmp_path, setup_mocks):
    """创建临时测试数据库（mock 桌面工作目录到 tmp_path）。"""
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

    # 桌面工作目录重定向到 tmp_path
    import trade.company as _co
    def _mock_setup(company_name, slug, suggested_name=""):
        wd = tmp_path / (suggested_name or company_name)
        wd.mkdir(parents=True, exist_ok=True)
        for cat_name, _ in _co._WORK_DIR_CATEGORIES:
            (wd / cat_name).mkdir(parents=True, exist_ok=True)
        return wd, True
    monkeypatch.setattr(_co, "_setup_work_directory", _mock_setup)

    yield db_path

    _db._get_db_path = original_db


@pytest.fixture
def company_id(test_db):
    """创建测试公司并返回 ID。"""
    from trade import company
    c = company.create(name="API Test Company", slug="api-test-company")
    return c["id"]


# ── Deps 测试 ──────────────────────────────────────────────────────────────


class TestDeps:
    """测试 API 依赖函数。"""

    def test_require_company_valid(self, company_id, setup_mocks):
        """有效的 X-Company-ID 返回 company_id。"""
        from trade.api.deps import require_company
        # 直接调用函数（绕过 FastAPI Header 依赖注入）
        result = require_company(str(company_id))
        assert result == company_id

    def test_require_company_missing(self, setup_mocks):
        """缺失 header → 401。"""
        from fastapi import HTTPException

        from trade.api.deps import require_company
        with pytest.raises(HTTPException) as exc_info:
            require_company("")
        assert exc_info.value.status_code == 401

    def test_require_company_invalid(self, setup_mocks):
        """无效 header → 401。"""
        from fastapi import HTTPException

        from trade.api.deps import require_company
        with pytest.raises(HTTPException) as exc_info:
            require_company("not-an-int")
        assert exc_info.value.status_code == 401

    def test_opt_company_missing(self, setup_mocks):
        """缺失 header → None。"""
        from trade.api.deps import opt_company
        assert opt_company("") is None
        assert opt_company(None) is None


class TestCronIsMachineLevel:
    """cron 端点是**机器级**资源，没有公司维度。

    审查曾标记 get_today_cron(cid) / get_active_jobs(cid)「要求公司头却从不使用」。
    核实结论：Hermes 的 cron 产物（~/.hermes/cron/jobs.json 与 output/）里没有任何
    公司标识，按公司过滤在数据模型上不可能。因此把「机器级」语义固化成测试：
    不同 cid 必须返回完全相同的数据；若将来真要按公司隔离，这个测试会先失败，
    提醒改动者那是产品级变更（需要 Hermes 侧给 job 打公司标签）。
    """

    @pytest.fixture
    def cron_with_jobs(self, monkeypatch, tmp_path):
        """把 cron 数据源指向临时目录，避免读真实 ~/.hermes。"""
        import trade.api.cron as cron_mod

        monkeypatch.setattr(cron_mod, "_JOBS_FILE", tmp_path / "jobs.json")
        monkeypatch.setattr(cron_mod, "_CRON_OUTPUT", tmp_path / "output")
        cron_mod._JOBS_FILE.write_text(
            json.dumps({"jobs": [
                {"name": "早安简报", "schedule": {"display": "0 9 * * *"}},
                {"name": "每日工作总结", "schedule": {"display": "0 17 * * *"}},
            ]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return cron_mod

    def test_today_cron_identical_across_companies(self, cron_with_jobs):
        """不同公司的今日任务清单必须一致（cron 无公司维度）。"""
        # 位置传参：函数签名是 _cid（故意不使用），这里就是要证明它被忽略
        a = cron_with_jobs.get_today_cron(1)
        b = cron_with_jobs.get_today_cron(2)

        assert a == b, "cron 是机器级资源，不应随公司变化；若要按公司隔离需先改数据模型"

    def test_active_jobs_identical_across_companies(self, cron_with_jobs):
        """不同公司的活跃任务必须一致。"""
        a = cron_with_jobs.get_active_jobs(1)
        b = cron_with_jobs.get_active_jobs(999)

        assert a == b


class _FakeRequest:
    """只带 headers 的最小 Request 替身（require_session 只用到 request.headers）。"""

    def __init__(self, headers):
        self.headers = headers


class TestRequireSession:
    """require_session（session token 校验）的负向用例。

    此前这个依赖在全部测试里零覆盖：token 校验若被写反、或整段删掉，
    测试仍然全绿，而整站 API 会变成无鉴权。这里补上真实断言。
    """

    def test_rejects_wrong_token(self, setup_mocks):
        """token 不匹配 → 401。"""
        from fastapi import HTTPException

        from trade.api import deps

        deps.set_session_token("correct-token")
        with pytest.raises(HTTPException) as exc_info:
            deps.require_session(_FakeRequest({"X-Hermes-Session-Token": "wrong-token"}))
        assert exc_info.value.status_code == 401

    def test_rejects_missing_token(self, setup_mocks):
        """缺少 token header → 401。"""
        from fastapi import HTTPException

        from trade.api import deps

        deps.set_session_token("correct-token")
        with pytest.raises(HTTPException) as exc_info:
            deps.require_session(_FakeRequest({}))
        assert exc_info.value.status_code == 401

    def test_rejects_empty_token_when_server_token_empty(self, setup_mocks):
        """服务端 token 未初始化时不放行，返回 500（防御性：绝不能当成通过）。"""
        from fastapi import HTTPException

        from trade.api import deps

        deps.set_session_token("")
        with pytest.raises(HTTPException) as exc_info:
            deps.require_session(_FakeRequest({"X-Hermes-Session-Token": ""}))
        assert exc_info.value.status_code == 500

    def test_accepts_matching_token(self, setup_mocks):
        """token 匹配时放行（不抛异常）。"""
        from trade.api import deps

        deps.set_session_token("correct-token")
        deps.require_session(_FakeRequest({"X-Hermes-Session-Token": "correct-token"}))


# ── Router Assembly 测试 ────────────────────────────────────────────────────


class TestRouterAssembly:
    """测试路由组装和注册。"""

    @staticmethod
    def _flatten_routes(router):
        """递归展开嵌套的子路由。

        - fastapi <0.137: include_router 把子路由的每个 APIRoute 平铺到父 router.routes
        - fastapi >=0.137: 包成 _IncludedRouter，原始子 router 保留在 .original_router
        - Mount(子 app): 子 router 在 .routes 上
        """
        flat = []
        for r in router.routes:
            inner = getattr(r, "original_router", None) or (
                getattr(r, "routes", None) and r
            )
            if inner is not None and inner is not r:
                flat.extend(TestRouterAssembly._flatten_routes(inner))
            elif getattr(r, "routes", None):
                flat.extend(TestRouterAssembly._flatten_routes(r))
            else:
                flat.append(r)
        return flat

    def test_router_imports_and_registers(self, setup_mocks):
        """router 对象可正常导入且注册了所有端点类型。"""
        from trade.api import router
        assert router is not None

        all_routes = self._flatten_routes(router)

        # 应包含所有主要域
        key_routes = set()
        for route in all_routes:
            if hasattr(route, 'path'):
                p = route.path
                for keyword in ['companies', 'libraries', 'customers', 'conversations',
                                'chat', 'memory', 'onboarding', 'models']:
                    if keyword in p:
                        key_routes.add(keyword)

        assert 'companies' in key_routes
        assert 'libraries' in key_routes
        assert 'customers' in key_routes
        assert 'chat' in key_routes

    def test_all_endpoints_registered(self, setup_mocks):
        """所有 endpoint 数量符合预期（至少 25 个）。"""
        from trade.api import router
        # 收集所有 HTTP 路由路径（递归展开嵌套子路由）
        endpoints = []
        for route in self._flatten_routes(router):
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                for method in route.methods:
                    if method in ('GET', 'POST', 'PUT', 'DELETE'):
                        endpoints.append(f"{method} {route.path}")

        # 至少应有 25 个端点
        assert len(endpoints) >= 25, f"Expected >= 25 endpoints, got {len(endpoints)}"


# ── Skill Router Tests ──────────────────────────────────────────────────────


class TestSkillRouter:
    """测试 skill_router 匹配逻辑。"""

    def test_match_b2b_osint(self):
        from trade.skill_router import match_skill
        result = match_skill("帮我背调一下这家公司")
        assert result is not None
        assert result["name"] == "b2b-osint"

    def test_match_lead_generation(self):
        from trade.skill_router import match_skill
        # "写开发信" 属冷邮件撰写场景——b2b-cold-outreach 是专职写邮件的技能，
        # b2b-lead-generation 是"找客户"全链路（2026-09 触发词路由调优后归属调整）
        result = match_skill("帮我写一封开发信给欧洲客户")
        assert result is not None
        assert result["name"] == "b2b-cold-outreach"

    def test_match_document_analysis(self):
        from trade.skill_router import match_skill
        result = match_skill("分析这份产品报价单文档")
        assert result is not None
        assert result["name"] == "b2b-document"

    def test_match_platform_diagnosis(self):
        from trade.skill_router import match_skill
        result = match_skill("帮我优化阿里国际站的产品标题")
        assert result is not None
        assert result["name"] == "b2b-platform"

    def test_match_linkedin_marketing(self):
        from trade.skill_router import match_skill
        result = match_skill("帮我做一个LinkedIn营销方案")
        assert result is not None
        assert result["name"] == "b2b-linkedin-marketing"

    def test_match_social_media(self):
        from trade.skill_router import match_skill
        result = match_skill("帮我规划一周的Facebook发帖内容")
        assert result is not None
        assert result["name"] == "b2b-social-media"

    def test_match_customs_data(self):
        from trade.skill_router import match_skill
        result = match_skill("分析这批海关数据的采购商")
        assert result is not None
        assert result["name"] == "b2b-customs-data"

    def test_match_onboarding(self):
        from trade.skill_router import match_skill
        result = match_skill("我是新公司，怎么开始使用")
        assert result is not None
        assert result["name"] == "b2b-onboarding"

    def test_match_document_generation(self):
        from trade.skill_router import match_skill
        result = match_skill("帮我生成一份形式发票给客户")
        assert result is not None
        assert result["name"] == "b2b-doc-generation"

    def test_match_customer_management(self):
        from trade.skill_router import match_skill
        result = match_skill("查看我的客户列表")
        assert result is not None
        assert result["name"] == "b2b-customer-mgmt"

    def test_match_daily_automation(self):
        from trade.skill_router import match_skill
        result = match_skill("帮我设置早安简报自动发送")
        assert result is not None
        assert result["name"] == "b2b-daily-automation"

    def test_match_email_intel(self):
        from trade.skill_router import match_skill
        result = match_skill("查一下这个邮箱 john@test.com")
        assert result is not None
        assert result["name"] in ("b2b-email-intel", "b2b-osint")

    def test_explicit_skill_call(self):
        from trade.skill_router import match_skill
        result = match_skill("用 b2b-email-intel 查 john@test.com")
        assert result is not None
        assert result["name"] == "b2b-email-intel"

    def test_no_match_irrelevant(self):
        from trade.skill_router import match_skill
        assert match_skill("今天天气怎么样") is None

    def test_empty_query(self):
        from trade.skill_router import match_skill
        assert match_skill("") is None
        assert match_skill("   ") is None

    def test_augment_query_with_skill(self):
        from trade.skill_router import augment_query
        result = augment_query("帮我背调", skill_name="b2b-osint")
        assert "[SKILL AUGMENTATION]" in result
        assert "b2b-osint" in result
        assert "帮我背调" in result

    def test_augment_query_no_match(self):
        from trade.skill_router import augment_query
        original = "这是什么天气"
        assert augment_query(original) == original

    def test_skill_registry_count(self):
        """注册表应有 38 个 skill。"""
        from trade.skill_registry import _SKILLS
        assert len(_SKILLS) == 38

    def test_no_duplicate_triggers(self):
        """每个 skill 的触发词不应有重复。"""
        from trade.skill_registry import _SKILLS
        for s in _SKILLS:
            triggers = s["triggers"]
            duplicates = [t for t in triggers if triggers.count(t) > 1]
            assert not duplicates, f"{s['name']} has duplicate triggers: {duplicates}"

    def test_ambiguous_match_order(self):
        """'背景调查'同时命中 b2b-osint 和 b2b-email-intel 时，应返回 osint。"""
        from trade.skill_router import match_skill
        result = match_skill("背景调查")
        assert result is not None
        assert result["name"] == "b2b-osint"


# ── Company Endpoint Functions ──────────────────────────────────────────────


class TestCompanyEndpoints:
    """测试公司端点函数。"""

    def test_create_company(self, test_db, setup_mocks):
        from trade import company
        c = company.create(name="Endpoint Co", slug="endpoint-co")
        assert c["name"] == "Endpoint Co"
        assert c["slug"] == "endpoint-co"
        assert c["is_active"] is True

    def test_list_companies(self, test_db, company_id, setup_mocks):
        from trade import company
        companies = company.list_all()
        assert any(c["id"] == company_id for c in companies)

    def test_agent_identity(self, test_db, company_id, setup_mocks):
        from trade import company
        identity = company.get_agent_identity(company_id)
        assert isinstance(identity, str)  # may be empty, but should be a string

    def test_update_agent_identity(self, test_db, company_id, setup_mocks):
        from trade import company
        result = company.update_trade_company(company_id, agent_identity_md="Test identity")
        assert result["agent_identity_md"] == "Test identity"


# ── Library Endpoint Functions ──────────────────────────────────────────────


class TestLibraryEndpoints:
    """测试文档库端点函数。"""

    def test_create_and_list(self, test_db, company_id, setup_mocks):
        from trade import library
        Path("/tmp/eplib").mkdir(parents=True, exist_ok=True)
        lib = library.create("Endpoint Lib", "/tmp/eplib", company_id=company_id)
        assert lib["name"] == "Endpoint Lib"

        libs = library.list_by_company(company_id)
        assert any(l["id"] == lib["id"] for l in libs)

    def test_company_scoped_access(self, test_db, company_id, setup_mocks):
        from trade import company, library
        other = company.create(name="Other Co", slug="other-co-lib")
        Path("/tmp/mylib").mkdir(parents=True, exist_ok=True)
        lib = library.create("My Lib", "/tmp/mylib", company_id=company_id)

        # Other company shouldn't see this library
        assert library.get(lib["id"], company_id=other["id"]) is None


class TestWorkDirUpload:
    """测试拖拽文件上传到公司工作目录子目录。"""

    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    def test_upload_single_file(self, test_db, company_id, setup_mocks, monkeypatch):
        """上传单个文件到指定子目录"""
        import io
        import tempfile

        from fastapi import UploadFile

        work_dir = Path(tempfile.mkdtemp(prefix="trade-work-test-"))
        monkeypatch.setattr("trade.company._setup_work_directory",
                           lambda name, slug, suggested_name="": (work_dir, True))
        monkeypatch.setattr("trade.company.get",
                           lambda cid: {"name": "Test", "slug": "test"})
        # 上传端点会读 trade_companies.extra1 取已保存的工作目录
        monkeypatch.setattr("trade.company.get_trade_company",
                           lambda cid: {"extra1": None})
        monkeypatch.setattr("trade.company.update_trade_company",
                           lambda cid, **kw: None)

        from trade.api.libraries import upload_to_work_dir

        f = UploadFile(filename="test.txt", file=io.BytesIO(b"hello world"))
        result = self._run(upload_to_work_dir(
            subdir="合同", files=[f], x_company_id=company_id,
        ))
        assert result["uploaded"] == 1
        assert "test.txt" in result["files"][0]
        assert (work_dir / "合同" / "test.txt").read_text() == "hello world"

    def test_upload_preserves_subdirs(self, test_db, company_id, setup_mocks, monkeypatch):
        """上传带子路径结构的文件"""
        import io
        import tempfile

        from fastapi import UploadFile

        work_dir = Path(tempfile.mkdtemp(prefix="trade-work-test-"))
        monkeypatch.setattr("trade.company._setup_work_directory",
                           lambda name, slug, suggested_name="": (work_dir, True))
        monkeypatch.setattr("trade.company.get",
                           lambda cid: {"name": "Test", "slug": "test"})
        # 上传端点会读 trade_companies.extra1 取已保存的工作目录
        monkeypatch.setattr("trade.company.get_trade_company",
                           lambda cid: {"extra1": None})
        monkeypatch.setattr("trade.company.update_trade_company",
                           lambda cid, **kw: None)

        from trade.api.libraries import upload_to_work_dir

        f1 = UploadFile(filename="sub/a.txt", file=io.BytesIO(b"aaa"))
        f2 = UploadFile(filename="sub/deep/b.txt", file=io.BytesIO(b"bbb"))
        result = self._run(upload_to_work_dir(
            subdir="客户资料", files=[f1, f2], x_company_id=company_id,
        ))
        assert result["uploaded"] == 2
        # result["files"] 的路径是相对于 work_dir 的，包含子目录前缀
        assert (work_dir / "客户资料" / "sub" / "a.txt").read_text() == "aaa"
        assert (work_dir / "客户资料" / "sub" / "deep" / "b.txt").read_text() == "bbb"

    def test_invalid_subdir_rejected(self, test_db, company_id, setup_mocks):
        """非法的子目录名应返回 400"""
        import io

        from fastapi import UploadFile

        from trade.api.libraries import upload_to_work_dir

        f = UploadFile(filename="test.txt", file=io.BytesIO(b"test"))
        with pytest.raises(Exception) as exc:
            self._run(upload_to_work_dir(
                subdir="../../../etc", files=[f], x_company_id=company_id,
            ))
        assert "400" in str(exc.value) or "无效" in str(exc.value)

    def test_path_traversal_sanitized(self, test_db, company_id, setup_mocks, monkeypatch):
        """含 ../ 的文件名应被 sanitize"""
        import io
        import tempfile

        from fastapi import UploadFile

        work_dir = Path(tempfile.mkdtemp(prefix="trade-work-test-"))
        monkeypatch.setattr("trade.company._setup_work_directory",
                           lambda name, slug, suggested_name="": (work_dir, True))
        monkeypatch.setattr("trade.company.get",
                           lambda cid: {"name": "Test", "slug": "test"})
        # 上传端点会读 trade_companies.extra1 取已保存的工作目录
        monkeypatch.setattr("trade.company.get_trade_company",
                           lambda cid: {"extra1": None})
        monkeypatch.setattr("trade.company.update_trade_company",
                           lambda cid, **kw: None)

        from trade.api.libraries import upload_to_work_dir

        f = UploadFile(filename="../escape.txt", file=io.BytesIO(b"bad"))
        result = self._run(upload_to_work_dir(
            subdir="报价单", files=[f], x_company_id=company_id,
        ))
        assert result["uploaded"] == 1
        assert "escape.txt" in result["files"][0]
        written = work_dir / "报价单" / result["files"][0]
        assert written.resolve().is_relative_to(work_dir.resolve())


# ── Customer Endpoint Functions ─────────────────────────────────────────────


class TestCustomerEndpoints:
    """测试客户端点函数。"""

    def test_create_and_list(self, test_db, company_id, setup_mocks):
        from trade import customer
        cust = customer.create("Endpoint Customer", company_id=company_id)
        assert cust["name"] == "Endpoint Customer"

        custs = customer.list_by_company(company_id)
        assert any(c["id"] == cust["id"] for c in custs)


# ── Conversation Endpoint Functions ─────────────────────────────────────────


class TestConversationEndpoints:
    """测试对话端点函数。"""

    def test_save_conversation(self, test_db, company_id, setup_mocks):
        from trade import chat_memory
        conv = chat_memory.save(company_id, "Query", "Response",
                                 files_read=[{"file": "test.pdf", "pages": [1]}])
        assert conv["query"] == "Query"
        assert len(conv["files_read"]) == 1

    def test_list_conversations(self, test_db, company_id, setup_mocks):
        from trade import chat_memory
        chat_memory.save(company_id, "Q1", "A1")
        convs = chat_memory.list_by_company(company_id)
        assert len(convs) >= 1


# ── Onboarding Flow ─────────────────────────────────────────────────────────


class TestOnboardingFlow:
    """测试首次引导流程。"""

    def test_onboarding_status_new_db(self, test_db, setup_mocks):
        from trade import onboarding
        onboarding.reset_onboarding_flag()
        assert onboarding.is_onboarding_done() is False

    def test_create_first_company(self, test_db, setup_mocks):
        from trade import onboarding
        onboarding.reset_onboarding_flag()

        result = onboarding.create_first_company(
            company_name="Flow Test Co",
            contact_name="Alice",
            identity_data={
                "products": "Electronics",
                "differentiation": "OEM factory",
                "target_region": "Europe",
            },
        )
        assert result["company"]["name"] == "Flow Test Co"
        assert "Electronics" in result["trade_company"]["agent_identity_md"]
        assert onboarding.is_onboarding_done() is True

    def test_create_first_company_duplicate(self, test_db, company_id, setup_mocks):
        from trade import onboarding
        assert onboarding.is_onboarding_done() is True


class _FakeClient:
    """只带 client.host 的最小请求替身（回环判定只看它）。"""

    def __init__(self, host):
        self.client = type("C", (), {"host": host})()


class TestTradeUiTokenScope:
    """session token 只下发给本机回环客户端。

    token 是唯一凭据，而 /trade 页面本身无需鉴权即可获取 —— 一旦 --host 0.0.0.0，
    局域网内任意主机 fetch 该页就能拿到 token 并接管全部 API（含 /system/update）。
    """

    def test_loopback_clients_may_receive_token(self):
        from trade.app import _client_is_loopback

        for host in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            assert _client_is_loopback(_FakeClient(host)) is True, host

    def test_remote_clients_are_not_loopback(self):
        from trade.app import _client_is_loopback

        for host in ("192.168.1.5", "10.0.0.7", "203.0.113.9", ""):
            assert _client_is_loopback(_FakeClient(host)) is False, host

    def test_remote_client_blocked_by_default(self, monkeypatch):
        from trade import app as app_mod

        monkeypatch.delenv("TRADE_ALLOW_REMOTE_UI", raising=False)
        assert app_mod._client_may_receive_token(_FakeClient("192.168.1.5")) is False

    def test_remote_client_allowed_with_explicit_optin(self, monkeypatch):
        """显式开启后允许局域网使用（用户明确知道风险）。"""
        from trade import app as app_mod

        monkeypatch.setenv("TRADE_ALLOW_REMOTE_UI", "1")
        assert app_mod._client_may_receive_token(_FakeClient("192.168.1.5")) is True
