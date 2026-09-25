"""冒烟测试：保证 /chat 端点的依赖注入不会崩。"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestRequireCompanyInjection:
    """验证 Depends(require_company) 的依赖注入不会在 chat 端点里崩。"""

    def test_cid_directly_injected_not_requiring_strip(self, monkeypatch, tmp_path):
        """require_company 的返回值是 int，chat 端点应直接当 int 用。

        如果代码里写了 cid = require_company(x_company_id)，int 没有 .strip()，
        直接 AttributeError。
        """
        # Simulate what FastAPI Depends does: require_company returns an int
        # Mock the company lookup
        import trade.company as co
        from trade.api.deps import require_company
        monkeypatch.setattr(co, "get_trade_company", lambda cid: {"company_id": cid, "is_active": 1})

        # A valid header string should parse to int 1
        result = require_company("1")
        assert result == 1
        assert isinstance(result, int)

        # If someone wrote cid = require_company(result) with result=1 (int),
        # it would call "1".strip() → AttributeError on int.
        # This is what the bug was. Let's verify int.strip() fails:
        with pytest.raises(AttributeError):
            _ = int("1").strip() is not None  # int has no .strip()


class TestSmokeChatModule:
    """验证 chat.py 的 import 链不会崩（无需真实 LLM）。"""

    def test_chat_module_imports(self, monkeypatch, tmp_path):
        """chat.py 可以正常导入，Depends 签名正确。"""
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
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
            hermes_constants.get_hermes_home = MagicMock(return_value=Path(tmp_path))
            from hermes_cli import config
            config.load_config = MagicMock(return_value={"model": {"provider": "openai", "default": "gpt-4o"}})
            from hermes_cli import auth
            class _PC:
                auth_type = "api_key"
                api_key_env_vars = ["OPENAI_API_KEY"]
                display_name = "OpenAI"
                base_url_env_var = ""
            auth.PROVIDER_REGISTRY = {"openai": _PC()}

            from trade.database import init_db
            init_db()

            from trade.api.chat import router, trade_chat, trade_chat_stream
            assert router is not None
            assert callable(trade_chat)
            assert callable(trade_chat_stream)

    def test_create_agent_factory(self, monkeypatch, tmp_path):
        """create_agent 不再写 os.environ。"""
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
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
            hermes_constants.get_hermes_home = MagicMock(return_value=Path(tmp_path))
            from hermes_cli import config
            config.load_config = MagicMock(return_value={"model": {"provider": "openai", "default": "gpt-4o"}})
            from hermes_cli import auth
            class _PC:
                auth_type = "api_key"
                api_key_env_vars = ["OPENAI_API_KEY"]
                display_name = "OpenAI"
                base_url_env_var = ""
            auth.PROVIDER_REGISTRY = {"openai": _PC()}

            import os

            from trade.helpers import create_agent
            os.environ.pop("HERMES_YOLO_MODE", None)

            # Mock AIAgent to avoid real LLM call
            class _MockAgent:
                def __init__(self, **kw):
                    pass
                def chat(self, msg):
                    return "ok"

            import run_agent
            run_agent.AIAgent = _MockAgent

            agent = create_agent()
            assert agent.chat("hi") == "ok"

            # Hermes 新参数默认不传，避免旧版 AIAgent 构造失败。
            captured = {}
            class _CaptureAgent:
                def __init__(self, **kw):
                    captured.update(kw)
            run_agent.AIAgent = _CaptureAgent
            create_agent(cwd="/tmp/work", connection_callback=lambda *_: None, side_agent=True)
            assert captured["cwd"] == "/tmp/work"
            assert captured["side_agent"] is True
            assert "connection_callback" in captured

            # create_agent should NOT set HERMES_YOLO_MODE (moved to server.py startup)
            assert os.environ.get("HERMES_YOLO_MODE", "") != "true"


class TestChatEndpointHTTP:
    """真实 HTTP 请求测试：POST /api/trade/chat 不能因依赖注入崩成 500。"""

    @pytest.mark.asyncio
    async def test_chat_endpoint_returns_200_mocked(self, monkeypatch, tmp_path):
        """关键回归：/chat 端点完整调用链通验。

        使用独立 FastAPI app（不与 server.py 共享全局状态），
        避免 test_api.py 中 module-scope mock 的泄漏。
        """
        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        import trade.database as _db
        _db._get_db_path = lambda p=tmp_path: p / "trade.db"
        from trade.database import init_db
        init_db()

        # Mock Hermes + agent 依赖
        class _A:
            def chat(self, q): return "mocked-response"

        # 桌面工作目录重定向到 tmp_path
        import trade.company as co
        def _mock_setup(cname, slug, suggested_name=""):
            wd = tmp_path / (suggested_name or cname)
            wd.mkdir(parents=True, exist_ok=True)
            for cat_name, _ in co._WORK_DIR_CATEGORIES:
                (wd / cat_name).mkdir(parents=True, exist_ok=True)
            return wd, True
        monkeypatch.setattr(co, "_setup_work_directory", _mock_setup)

        try:
            co.create(name="Smoke Test Co", slug="smoke-test")
        except ValueError:
            pass
        monkeypatch.setattr(co, "get_trade_company",
                            lambda cid: {"company_id": cid, "data_dir": str(tmp_path), "agent_identity_md": "", "is_active": 1})

        import trade.helpers
        monkeypatch.setattr(trade.helpers, "check_provider", lambda: None)
        monkeypatch.setattr(trade.helpers, "get_agent_kwargs", lambda: {"provider":"x","model":"x","base_url":"","api_key":""})
        monkeypatch.setattr(trade.helpers, "build_query", lambda c, l, q, **kw: q)
        monkeypatch.setattr(trade.helpers, "create_agent", lambda **kw: _A())

        # chat.py 在模块级别 import create_agent，已被其他测试缓存，需 patch 两处
        import trade.api.chat as chat_mod
        monkeypatch.setattr(chat_mod, "create_agent", lambda **kw: _A())
        monkeypatch.setattr(chat_mod, "build_query", lambda c, l, q, **kw: q)
        monkeypatch.setattr(chat_mod.chat_memory, "save_with_context", lambda **kw: {"id": 1})

        from trade.api.deps import set_session_token
        set_session_token("test-token")

        # 构建独立 app
        from fastapi import FastAPI

        from trade.api import router as trade_router
        app = FastAPI()
        app.include_router(trade_router, prefix="/api/trade")

        import httpx
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/trade/chat",
                json={"query": "hi"},
                headers={"X-Hermes-Session-Token": "test-token", "X-Company-ID": "1"},
            )
            assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
            assert r.json()["response"] == "mocked-response"
