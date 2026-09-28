"""Prompt 解析链与品牌安全护栏测试。

验证 resolve_system_prompt 的优先级链（文件 > DB > 全局 > 代码兜底），
以及 get_brand_safety 的兜底逻辑。
"""

from __future__ import annotations

import pytest


@pytest.fixture
def trade_home(tmp_path, monkeypatch):
    """将 TRADE_HOME 指向临时目录，并清空 mtime 缓存。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    from trade import prompts
    prompts.invalidate_cache()
    yield tmp_path
    prompts.invalidate_cache()


class TestResolveSystemPrompt:
    """resolve_system_prompt 是「基础规则 + 用户自定义」的组合，不是二选一。

    历史 bug：它是一条二选一的优先级链（文件 → DB → 全局 → 代码），而 onboarding
    必然写入身份文本，于是身份把基础规则**整体顶替**。实测（本文件对应的回归测试）：
    返回长度恰好等于身份文本长度，而 Disclaimer / Role / Language Policy /
    Data Isolation / 准确规则一个都不在 —— 这些规则从未到达过模型。
    """

    # 基础规则块的首行标记（Disclaimer 块开头）
    BASE_MARKER = "# Disclaimer — READ BEFORE ANSWERING ANY QUESTION"

    def _assert_composed(self, result: str, base: str, custom: str) -> None:
        """断言 result == 基础块 + 自定义块，且顺序为基础在前。"""
        assert self.BASE_MARKER in result, "基础规则块必须常驻，不能被自定义文本顶替"
        assert base in result
        assert custom in result
        assert result.index(base) < result.index(custom), "基础规则必须在自定义文本之前"

    def test_no_custom_returns_base_only(self, trade_home):
        """没有任何自定义内容时，返回的就是默认基础规则块本身。"""
        from trade import prompts
        from trade.prompt import TRADE_SYSTEM_PROMPT_FIRST_TURN

        assert prompts.resolve_system_prompt() == TRADE_SYSTEM_PROMPT_FIRST_TURN

    def test_custom_base_param_used_as_base(self, trade_home):
        """code_fallback 指定的是**基础块**（如 OSINT/MINIMAL 档），仍会与自定义组合。"""
        from trade import prompts

        result = prompts.resolve_system_prompt(code_fallback="CUSTOM_BASE")

        assert result == "CUSTOM_BASE"

    def test_db_identity_is_appended_to_base(self, trade_home):
        """DB 身份必须追加在基础规则之后，而不是替换基础规则。"""
        from trade import prompts
        from trade.prompt import TRADE_SYSTEM_PROMPT

        result = prompts.resolve_system_prompt(db_identity="DB_IDENTITY")

        self._assert_composed(result, TRADE_SYSTEM_PROMPT, "DB_IDENTITY")

    def test_company_file_appended_and_wins_over_db(self, trade_home):
        """公司身份文件优先于 DB，且追加在基础规则之后。

        通过生产的写入 API 落文件，不手写路径 —— 手写路径会跟着实现一起错，
        于是「文件优先」明明是死的、测试却一直绿（之前正是如此）。
        """
        from trade import prompts
        from trade.prompt import TRADE_SYSTEM_PROMPT

        prompts.write_agent_identity("acme", "FILE_IDENTITY")

        result = prompts.resolve_system_prompt(company_slug="acme", db_identity="DB_IDENTITY")

        self._assert_composed(result, TRADE_SYSTEM_PROMPT, "FILE_IDENTITY")
        assert "DB_IDENTITY" not in result, "有公司文件时不应再拼 DB 身份"

    def test_global_system_md_appended_to_base(self, trade_home):
        """全局 system.md 也是自定义层，追加在基础规则之后。"""
        from trade import prompts
        from trade.prompt import TRADE_SYSTEM_PROMPT

        sys_path = trade_home / "prompts" / "system.md"
        sys_path.parent.mkdir(parents=True, exist_ok=True)
        sys_path.write_text("GLOBAL_SYSTEM", encoding="utf-8")

        result = prompts.resolve_system_prompt()

        self._assert_composed(result, TRADE_SYSTEM_PROMPT, "GLOBAL_SYSTEM")


class TestAccuracyRulesAlwaysPresent:
    """准确规则（逐个文件扫描 / List Integrity）必须在首轮与后续轮次都在。

    历史 bug：这两块只写在 MINIMAL 里，而 MINIMAL 是「非首轮」档 ——
    首轮反而拿不到「逐个文件完整扫描」这条最关键的规则。
    """

    def test_first_turn_base_contains_accuracy_rules(self):
        """首轮使用的基础块必须含准确规则。"""
        from trade.prompt import TRADE_SYSTEM_PROMPT_FIRST_TURN

        assert "逐个文件扫描" in TRADE_SYSTEM_PROMPT_FIRST_TURN
        assert "List Integrity" in TRADE_SYSTEM_PROMPT_FIRST_TURN

    def test_minimal_still_contains_accuracy_rules(self):
        """后续轮次的精简档也必须保留准确规则。"""
        from trade.prompt import TRADE_SYSTEM_PROMPT_MINIMAL

        assert "逐个文件扫描" in TRADE_SYSTEM_PROMPT_MINIMAL
        assert "List Integrity" in TRADE_SYSTEM_PROMPT_MINIMAL

    def test_first_turn_base_is_not_smaller_than_minimal(self):
        """首轮基础块应比后续轮次的精简档更完整（否则档位是反的）。"""
        from trade.prompt import TRADE_SYSTEM_PROMPT_FIRST_TURN, TRADE_SYSTEM_PROMPT_MINIMAL

        assert len(TRADE_SYSTEM_PROMPT_FIRST_TURN) >= len(TRADE_SYSTEM_PROMPT_MINIMAL)


class TestNeedsFullPrompt:
    """FULL 提示词（22674 字符 ≈ 5700 token）只在文档处理类任务上按需注入。"""

    def test_document_library_selected(self):
        from trade.prompts import needs_full_prompt

        assert needs_full_prompt(library_id=3) is True

    def test_explicit_file_paths_mentioned(self):
        from trade.prompts import needs_full_prompt

        assert needs_full_prompt(explicit_paths=["/tmp/quote.xlsx"]) is True

    def test_document_skill_matched(self):
        from trade.prompts import needs_full_prompt

        assert needs_full_prompt(matched_name="b2b-document") is True

    def test_plain_chat_does_not_need_full(self):
        """普通闲聊不应背上 5700 token 的文档指南。"""
        from trade.prompts import needs_full_prompt

        assert needs_full_prompt(matched_name="b2b-market-analysis") is False
        assert needs_full_prompt() is False


class TestBrandSafety:
    def test_default_when_no_slug(self, trade_home):
        """无公司 slug 时返回内置 BRAND_SAFETY_BLOCK。"""
        from trade import prompts
        from trade.prompt import BRAND_SAFETY_BLOCK
        assert prompts.get_brand_safety() == BRAND_SAFETY_BLOCK

    def test_default_when_file_missing(self, trade_home):
        """有 slug 但文件不存在时返回内置默认。"""
        from trade import prompts
        from trade.prompt import BRAND_SAFETY_BLOCK
        assert prompts.get_brand_safety("nonexistent") == BRAND_SAFETY_BLOCK

    def test_custom_file(self, trade_home):
        """有 slug 且文件存在时返回文件内容。

        路径取生产实现，不手写 —— 手写会跟着实现的路径 bug 一起错，测试照样绿。
        """
        from trade import prompts

        path = prompts._brand_safety_path("acme")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("CUSTOM_BRAND_SAFETY", encoding="utf-8")

        assert prompts.get_brand_safety("acme") == "CUSTOM_BRAND_SAFETY"


class TestBrandSafetyBlock:
    def test_block_nonempty(self):
        """内置 BRAND_SAFETY_BLOCK 非空且含关键护栏词。"""
        from trade.prompt import BRAND_SAFETY_BLOCK
        assert BRAND_SAFETY_BLOCK.strip()
        # 护栏应包含禁止编造/贬损等核心约束
        assert "NEVER" in BRAND_SAFETY_BLOCK or "禁止" in BRAND_SAFETY_BLOCK
