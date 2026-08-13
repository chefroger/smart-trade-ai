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
    def test_default_fallback(self, trade_home):
        """无任何自定义时返回代码默认 prompt。"""
        from trade import prompts
        from trade.prompt import TRADE_SYSTEM_PROMPT
        result = prompts.resolve_system_prompt()
        assert result == TRADE_SYSTEM_PROMPT

    def test_code_fallback_param(self, trade_home):
        """code_fallback 参数优先于默认。"""
        from trade import prompts
        result = prompts.resolve_system_prompt(code_fallback="CUSTOM_OSINT_PROMPT")
        assert result == "CUSTOM_OSINT_PROMPT"

    def test_db_identity_fallback(self, trade_home):
        """db_identity 参数在无文件时兜底。"""
        from trade import prompts
        result = prompts.resolve_system_prompt(db_identity="DB_IDENTITY")
        assert result == "DB_IDENTITY"

    def test_company_file_highest_priority(self, trade_home):
        """公司 identity 文件优先级最高。"""
        from trade import prompts
        identity_path = trade_home / "companies" / "acme" / "agent_identity.md"
        identity_path.parent.mkdir(parents=True, exist_ok=True)
        identity_path.write_text("FILE_IDENTITY", encoding="utf-8")

        result = prompts.resolve_system_prompt(company_slug="acme", db_identity="DB_IDENTITY")
        assert result == "FILE_IDENTITY"

    def test_global_system_md(self, trade_home):
        """全局 system.md 在无公司文件无 db 时兜底。"""
        from trade import prompts
        sys_path = trade_home / "prompts" / "system.md"
        sys_path.parent.mkdir(parents=True, exist_ok=True)
        sys_path.write_text("GLOBAL_SYSTEM", encoding="utf-8")

        result = prompts.resolve_system_prompt()
        assert result == "GLOBAL_SYSTEM"


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
        """有 slug 且文件存在时返回文件内容。"""
        from trade import prompts
        path = trade_home / "companies" / "acme" / "brand_safety.md"
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
