"""外部内容纪律测试 —— 文件/邮件/网页里的话当资料，不当指令。

常驻块必须挂进全部六档：SYSTEM / FIRST_TURN / MINIMAL / OSINT / FULL /
FULL_DOCGEN。少一档就等于那条路径上没规则；块为空即失败。
"""

from __future__ import annotations

import pytest

# 纪律块的标题行 —— 用它判断「这一档里到底有没有这条规则」
EXTERNAL_CONTENT_HEADER = "# External Content Discipline"


class TestExternalContentBlockContent:
    """纪律块本身的内容要求。"""

    def test_block_exists_and_nonempty(self):
        from trade.prompt import TRADE_EXTERNAL_CONTENT_BLOCK

        assert TRADE_EXTERNAL_CONTENT_BLOCK.strip(), "外部内容纪律块不能为空"

    def test_block_has_header(self):
        from trade.prompt import TRADE_EXTERNAL_CONTENT_BLOCK

        assert EXTERNAL_CONTENT_HEADER in TRADE_EXTERNAL_CONTENT_BLOCK

    def test_block_treats_external_as_data_not_instructions(self):
        from trade.prompt import TRADE_EXTERNAL_CONTENT_BLOCK

        text = TRADE_EXTERNAL_CONTENT_BLOCK
        assert "资料" in text
        assert "指令" in text

    def test_block_requires_ask_user_on_suspicious_directives(self):
        from trade.prompt import TRADE_EXTERNAL_CONTENT_BLOCK

        text = TRADE_EXTERNAL_CONTENT_BLOCK
        assert "问用户" in text
        assert "老板已授权" in text or "授权" in text

    def test_block_caps_retry_and_forbids_unknown_downloads(self):
        from trade.prompt import TRADE_EXTERNAL_CONTENT_BLOCK

        text = TRADE_EXTERNAL_CONTENT_BLOCK
        assert "失败两次" in text
        assert "来源不明" in text

    def test_block_is_compact(self):
        """常驻块要付每请求成本；任务书要求 ≤6 行实质内容。"""
        from trade.prompt import TRADE_EXTERNAL_CONTENT_BLOCK

        # 去掉标题行后的非空行数 ≤6
        body_lines = [
            ln for ln in TRADE_EXTERNAL_CONTENT_BLOCK.strip().splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assert len(body_lines) <= 6, (
            f"外部内容纪律块实质行数 {len(body_lines)}，超出 ≤6 行预算"
        )


class TestExternalContentBlockAlwaysPresent:
    """六档提示词都必须携带纪律块 —— 单一常量、全档挂载。"""

    def _tiers(self):
        from trade.prompt import (
            TRADE_SYSTEM_PROMPT,
            TRADE_SYSTEM_PROMPT_FIRST_TURN,
            TRADE_SYSTEM_PROMPT_FULL,
            TRADE_SYSTEM_PROMPT_FULL_DOCGEN,
            TRADE_SYSTEM_PROMPT_MINIMAL,
            TRADE_SYSTEM_PROMPT_OSINT,
        )

        return {
            "SYSTEM": TRADE_SYSTEM_PROMPT,
            "FIRST_TURN": TRADE_SYSTEM_PROMPT_FIRST_TURN,
            "MINIMAL": TRADE_SYSTEM_PROMPT_MINIMAL,
            "OSINT": TRADE_SYSTEM_PROMPT_OSINT,
            "FULL": TRADE_SYSTEM_PROMPT_FULL,
            "FULL_DOCGEN": TRADE_SYSTEM_PROMPT_FULL_DOCGEN,
        }

    @pytest.mark.parametrize(
        "tier",
        ["SYSTEM", "FIRST_TURN", "MINIMAL", "OSINT", "FULL", "FULL_DOCGEN"],
    )
    def test_every_tier_carries_the_rule(self, tier):
        text = self._tiers()[tier]

        assert EXTERNAL_CONTENT_HEADER in text, f"{tier} 档缺少外部内容纪律块"
        assert "资料" in text and "指令" in text, f"{tier} 档缺少资料/指令表述"

    def test_all_tiers_share_the_same_block(self):
        from trade.prompt import TRADE_EXTERNAL_CONTENT_BLOCK

        for name, text in self._tiers().items():
            assert TRADE_EXTERNAL_CONTENT_BLOCK in text, (
                f"{name} 档内嵌的块与 TRADE_EXTERNAL_CONTENT_BLOCK 不一致"
            )
