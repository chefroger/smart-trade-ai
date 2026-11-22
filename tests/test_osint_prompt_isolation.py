"""背调（OSINT）不加载当前公司的业务上下文（2026-11-22 记忆改造第一步）。

实测事故：查外部个人时报告里出现「他与化妆品 OEM、外贸供应链的任何业务交集」
—— 那是当前公司 henfon 的业务范围，被当作背调对象的背景写了进去。

规则：OSINT 请求只保留基础规则 + 公司 ID（工具隔离需要），不注入
agent identity、公司名/slug、品牌护栏、客户简报到与订单上下文。
非 OSINT 请求行为不变。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SECRET = "本公司专注化妆品 OEM 与外贸供应链，品牌 Henfon"


@pytest.fixture
def henfon(monkeypatch, tmp_path):
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
    company = co.create(name="Henfon", slug="henfon")

    from trade import prompts

    prompts.write_agent_identity("henfon", SECRET)
    return company


def _build(company: dict, query: str) -> tuple[str, str | None]:
    from trade import helpers

    return helpers.build_query(company["id"], None, query)


class TestOsintPromptIsolation:
    def test_person_backcheck_does_not_load_company_identity(self, henfon):
        prompt, skill_hint = _build(henfon, "帮我查一下这个人 John Smith 的背景")

        assert skill_hint is not None, "背调技能应被注入"
        assert SECRET not in prompt, "公司业务范围混入了外部背调"
        assert "Henfon" not in prompt, "公司名混入了外部背调"
        # 公司 ID 仍要保留（公司隔离工具靠它）
        assert f"公司 ID：{henfon['id']}" in prompt
        assert "当前会话归属" in prompt

    def test_brand_safety_not_injected_for_osint(self, henfon):
        from trade.prompt import BRAND_SAFETY_BLOCK

        prompt, _ = _build(henfon, "帮我查一下这个人 John Smith 的背景")
        # 取品牌块里一段有辨识度的文字
        marker = BRAND_SAFETY_BLOCK.strip().splitlines()[0][:24]
        assert marker not in prompt

    def test_non_osint_still_has_company_context(self, henfon):
        prompt, _ = _build(henfon, "帮我写一封开发信给这个客户")

        assert SECRET in prompt
        assert "Henfon" in prompt


class TestResolveSystemPromptFlag:
    def test_include_custom_false_returns_base_only(self, henfon):
        from trade import prompts

        base = "BASE-RULES"
        assert prompts.resolve_system_prompt(
            company_slug="henfon", code_fallback=base, include_custom=False
        ) == base

        with_custom = prompts.resolve_system_prompt(
            company_slug="henfon", code_fallback=base,
        )
        assert SECRET in with_custom
