"""2026-10-25 审计 P2 低风险批次回归。

覆盖：
- P2-2：备份还原不再回退到裸 extractall（路径穿越防护不能降级）
- P2-4：启动日志不打印 session token 片段
- P2-15：Win32 DPI 上下文按指针宽度声明（见 test_copilot_win32 的签名断言）
- P2-19：买家类型 option 的 value 固定中文（见 tests_js）
- P2-26：对话 limit 夹在 1～200；CSV 读完后再校验实际大小
- P2-1：插件工具错误不把 traceback 返回给 LLM
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read_source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class TestRestoreNoUnsafeFallback:
    def test_extractall_always_uses_data_filter(self):
        src = _read_source("trade/post_install/backup.py")
        extract_at = src.index("tar.extractall")
        around = src[max(0, extract_at - 600): extract_at + 200]
        assert 'filter="data"' in around
        # 不许再有 `except TypeError: tar.extractall(...)` 这种降级
        assert "except TypeError" not in around
        # 全文件只应有一处 extractall 调用
        assert src.count("tar.extractall") == 1


class TestTokenNotLogged:
    def test_startup_log_has_no_token_fragment(self):
        src = _read_source("trade/app.py")
        assert "_SESSION_TOKEN[:8]" not in src
        assert "Session token 已生成" in src


class TestConversationLimitClamp:
    @pytest.mark.parametrize("raw,expected", [(-1, 1), (0, 1), (99999, 200), (50, 50)])
    def test_limit_is_clamped(self, raw, expected):
        import trade.api.conversations as conv_api

        seen = []
        with patch.object(
            conv_api.chat_memory, "list_by_company",
            side_effect=lambda cid, limit: seen.append(limit) or [],
        ):
            conv_api.list_conversations(limit=raw, x_company_id=1)

        assert seen == [expected]


class TestPromptUsesRealToolNames:
    def test_no_list_files_in_prompts(self):
        """Hermes 没有 list_files 工具；旧提示词让模型调一个不存在的工具。"""
        src = _read_source("trade/helpers.py")
        assert "list_files" not in src
        assert "search_files" in src


class TestUpdateNeedsConfirmHeader:
    def test_backend_rejects_update_without_confirm_header(self):
        """前端 confirm() 只是浏览器层，后端必须再挡一道（审计 P1-10）。"""
        src = _read_source("trade/app.py")
        assert "X-Confirm-Update" in src
        assert 'request.headers.get("X-Confirm-Update"' in src

    def test_update_does_not_auto_restart(self):
        """更新只拉取+装依赖，不自动重启（P1-10 的安全替代方案）。"""
        src = _read_source("trade/app.py")
        assert "background_tasks.add_task(_perform_restart)" not in src
        assert 'result["restart_scheduled"] = False' in src


class TestConversationSaveScope:
    def test_foreign_library_is_rejected(self):
        """与 /chat 的 _validate_scope 对齐：库里没有这个库就不能按它存行。"""
        import trade.api.conversations as conv_api
        from trade.api.models import ConversationSave

        with patch.object(conv_api.library_module, "get", return_value=None):
            with pytest.raises(HTTPException) as exc:
                conv_api.save_conversation(
                    ConversationSave(query="q", response="r", library_id=99),
                    x_company_id=1,
                )

        assert exc.value.status_code == 400
        assert "Library" in exc.value.detail


class TestCsvSizeAfterRead:
    @pytest.mark.asyncio
    async def test_chunked_upload_over_limit_rejected(self):
        """file.size 为 None（分块上传）时，读完必须按实际字节数拒绝。"""
        from starlette.datastructures import UploadFile

        import trade.api.customers as cust_api

        payload = b"name\n" + b"x" * (10 * 1024 * 1024 + 1)
        upload = UploadFile(file=io.BytesIO(payload), filename="big.csv")
        assert getattr(upload, "size", None) is None

        with pytest.raises(HTTPException) as exc:
            await cust_api.bulk_import_customers(upload, cid=1)

        assert exc.value.status_code == 413


class TestPluginDoesNotLeakTraceback:
    def test_error_returns_exception_type_only(self):
        import trade.chat_memory as chat_memory
        import trade.hermes_chat_memory_plugin.tools as tools
        from trade.agent_context import bind_company

        def boom(**_kw):
            raise RuntimeError("db exploded at /Users/secret/trade.db")

        with bind_company(1, None), patch.object(chat_memory, "search_history", boom):
            result = tools.handle_chat_memory_list(
                {"company_id": 1, "time_range": "all"}
            )

        text = str(result)
        assert "RuntimeError" in text, "应保留异常类型，便于 LLM 向用户解释"
        assert "/Users/secret" not in text, "内部路径不得返回给 LLM"
        assert "Traceback" not in text
