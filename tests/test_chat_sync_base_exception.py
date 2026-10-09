"""同步 `/chat` 也必须兜住 BaseException —— 与 stream 侧对称。

## 背景

2026-10-08 客户机事故：Hermes 的 `hermes_bootstrap.py` 把 server.py 重新 exec 到
它自带的 store python（无 trade 包），子进程 ModuleNotFoundError 退出，父进程
`raise RelaunchExit(1)` —— 它继承 **SystemExit**（BaseException）。

`/chat/stream` 已补 `except BaseException`（`trade/api/chat.py:450`），但同步
`_call_agent()` 只有 ImportError/RuntimeError/Exception 三个分支，仍然抓不到。

后果比 stream 更重：异常从 executor 线程穿过 `asyncio.wait_for`，uvicorn 的
`ExceptionMiddleware` 同样只捕 `Exception` → SystemExit 会穿透到 ASGI 栈，
最坏情况**整个服务进程退出**（不是单个请求失败）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _AgentRaising:
    """agent 一被调用就抛 BaseException（复现 RelaunchExit 的形状）。"""

    def __init__(self, exc: BaseException):
        self._exc = exc

    def chat(self, query):  # noqa: ARG002
        raise self._exc

    def run_conversation(self, query, task_id=None):  # noqa: ARG002
        raise self._exc


@pytest.fixture
def company(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    import trade.database as _db

    monkeypatch.setattr(_db, "_get_db_path", lambda: tmp_path / "trade.db")
    from trade.database import init_db

    init_db()

    import trade.company as co

    def _setup(name, slug, suggested_name=""):
        wd = tmp_path / (suggested_name or name)
        wd.mkdir(parents=True, exist_ok=True)
        for cat, _ in co._WORK_DIR_CATEGORIES:
            (wd / cat).mkdir(parents=True, exist_ok=True)
        return wd, True

    monkeypatch.setattr(co, "_setup_work_directory", _setup)
    return co.create(name="Sync Co", slug="sync-co")


async def _call_sync(company: dict, exc: BaseException):
    """驱动真实的 trade_chat（同步端点）。"""
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    with patch.object(chat, "create_agent", return_value=_AgentRaising(exc)), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat.chat_memory, "save_with_context", return_value={"id": 1}), \
         patch("trade.license.check_license", return_value=(True, "")):
        return await chat.trade_chat(
            ChatRequest(query="你好"), company["id"]
        )


class TestSyncChatSurvivesBaseException:
    """SystemExit 之类的 BaseException 必须被兜住并转成可见回复。"""

    async def test_does_not_propagate(self, company):
        """异常不得穿透出端点 —— 否则可能掀掉整个服务进程。"""
        result = await _call_sync(company, SystemExit(1))

        assert result is not None, "SystemExit 穿透了同步端点（服务进程可能被带崩）"

    async def test_response_mentions_exception_type(self, company):
        """回复要写明异常类型，便于定位（学 stream 侧的措辞）。"""
        result = await _call_sync(company, SystemExit(1))
        text = result["response"] if isinstance(result, dict) else str(result)

        assert "SystemExit" in text, f"回复未标明异常类型：{text!r}"

    async def test_not_retried(self, company):
        """BaseException 不是瞬时故障，不该重试（重试只会拖时间）。"""
        import time

        start = time.time()
        await _call_sync(company, SystemExit(1))
        elapsed = time.time() - start

        assert elapsed < 1.5, f"疑似进入重试循环（耗时 {elapsed:.1f}s）"
