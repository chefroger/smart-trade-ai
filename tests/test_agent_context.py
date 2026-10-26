"""审计 P0-2：chat-memory 工具的公司身份必须以服务端绑定为准。

模型可以生成任意 company_id；工具必须校验它与本次 agent 调用绑定的公司一致，
未绑定时 fail-closed。
"""

from __future__ import annotations

import json

from trade.agent_context import bind_company, current_company_id
from trade.hermes_chat_memory_plugin.tools import handle_chat_memory_list


class TestAgentContext:
    def test_bind_and_reset(self):
        assert current_company_id() is None
        with bind_company(7):
            assert current_company_id() == 7
        assert current_company_id() is None

    def test_nested_bind_restores_previous(self):
        with bind_company(7):
            with bind_company(9):
                assert current_company_id() == 9
            assert current_company_id() == 7


class TestChatMemoryToolBinding:
    def test_unbound_tool_refuses(self):
        result = handle_chat_memory_list({"company_id": 1})
        assert "not bound" in result
        assert "Refusing" in result

    def test_mismatched_company_id_refuses(self):
        with bind_company(1):
            result = handle_chat_memory_list({"company_id": 2})
        assert "does not match" in result

    def test_bound_company_and_customer_are_used(self, monkeypatch):
        calls: list[tuple] = []

        def fake_search_history(company_id, time_range="all", limit=20, **kw):
            calls.append((company_id, kw.get("customer_id"), kw.get("unattributed_only")))
            return [{"id": 1, "query": "q", "response": "r"}]

        monkeypatch.setattr("trade.chat_memory.search_history", fake_search_history)

        with bind_company(1, 7):
            result = handle_chat_memory_list({"company_id": 1, "limit": 5})

        payload = json.loads(result)
        assert payload["company_id"] == 1
        assert payload["count"] == 1
        assert calls == [(1, 7, False)]

    def test_no_customer_falls_back_to_unattributed_only(self, monkeypatch):
        calls: list[tuple] = []

        def fake_search_history(company_id, time_range="all", limit=20, **kw):
            calls.append((company_id, kw.get("customer_id"), kw.get("unattributed_only")))
            return []

        monkeypatch.setattr("trade.chat_memory.search_history", fake_search_history)

        with bind_company(1):
            handle_chat_memory_list({"company_id": 1})

        assert calls == [(1, None, True)]

    def test_invalid_claim_still_refused(self):
        with bind_company(1):
            result = handle_chat_memory_list({"company_id": "1"})
        assert "positive integer" in result
