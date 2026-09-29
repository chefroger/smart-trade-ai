"""图片识别铁律测试 —— 图片必须走 `vision_analyze`，不得自建 OCR。

## 为什么需要这个文件（实测踩出来的）

2026-09-29 用户让 Trade 识别一张界面截图（会话 `20260929_084156_4120c8`）。
核对证据链后确认：**那次没有走 Hermes 视觉通道**，而是 agent 先拿
`browser_exec` 看本地文件（空等 420s 超时）、再自己写了个 Swift 脚本调 macOS
Apple Vision 框架 OCR，逐区域裁剪跑多轮。工具统计：

    7×terminal + 1×write_file + 1×browser_exec(超时 420s)，vision_analyze 0 次

而 Hermes 侧的门控实测是**开着的**：

    image_input_mode = native | native_fast_path = True
    check_vision_requirements() = True

也就是说 `vision_analyze` 当时可选、可用（另经实测：把同一张图直接发给
deepseek-flash，返回文字与原图逐字一致）。失败原因不在配置，在提示词层 ——
`trade/prompt.py` 里关于图片 / 截图 / 图像**一条规则都没有**，全项目唯一一句图片
指令是 `static/trade_chat.js:1884`，而它只挂在**拖拽导入**路径上。用户这次是在
聊天框里直接给的路径，那句提示压根没触发。

所以规则必须**常驻四档**：一条「有时在、有时不在」的提示不构成硬约束，
而这次的 bug 恰恰是它没送到。
"""

from __future__ import annotations

import pytest

# 铁律块的标题行 —— 用它判断「这一档里到底有没有这条规则」
IMAGE_BLOCK_HEADER = "# Image & Screenshot Handling"


class TestImageBlockContent:
    """铁律块本身的内容要求。"""

    def test_block_exists_and_nonempty(self):
        from trade.prompt import TRADE_IMAGE_BLOCK

        assert TRADE_IMAGE_BLOCK.strip(), "图片铁律块不能为空"

    def test_block_has_header(self):
        """块必须有可识别的标题行（测试和排查都靠它定位）。"""
        from trade.prompt import TRADE_IMAGE_BLOCK

        assert IMAGE_BLOCK_HEADER in TRADE_IMAGE_BLOCK

    def test_block_names_the_vision_tool(self):
        """必须点名 `vision_analyze` —— 只说「用视觉工具」模型可能不知道叫什么。"""
        from trade.prompt import TRADE_IMAGE_BLOCK

        assert "vision_analyze" in TRADE_IMAGE_BLOCK

    def test_block_forbids_self_written_ocr(self):
        """必须明文禁止自建 OCR（这次就是自写了 Swift 脚本）。"""
        from trade.prompt import TRADE_IMAGE_BLOCK

        assert "OCR" in TRADE_IMAGE_BLOCK or "ocr" in TRADE_IMAGE_BLOCK

    def test_block_forbids_browser_route_for_local_images(self):
        """必须禁止用浏览器路径去开本地图片（这次空等 browser_exec 420s）。"""
        from trade.prompt import TRADE_IMAGE_BLOCK

        assert "browser_exec" in TRADE_IMAGE_BLOCK

    def test_block_mentions_read_file_cannot_read_images(self):
        """必须说明 `read_file` 不支持图片，免得模型读完得出「无法读取」的结论。"""
        from trade.prompt import TRADE_IMAGE_BLOCK

        assert "read_file" in TRADE_IMAGE_BLOCK

    def test_block_is_compact(self):
        """常驻块要付每请求的成本，必须克制（这条规则值不了几千 token）。"""
        from trade.prompt import TRADE_IMAGE_BLOCK

        assert len(TRADE_IMAGE_BLOCK) < 900, (
            f"图片铁律块 {len(TRADE_IMAGE_BLOCK)} 字符，超出常驻预算（<900）"
        )


class TestImageBlockAlwaysPresent:
    """四档提示词都必须携带铁律 —— 少一档就等于那条路径上没规则。

    四档分别由 `trade/helpers.py:build_query()` 按场景选出：
    OSINT 背调 / 文档类 FULL / 非首轮 MINIMAL / 首轮 FIRST_TURN。
    """

    def _tiers(self):
        from trade.prompt import (
            TRADE_SYSTEM_PROMPT_FIRST_TURN,
            TRADE_SYSTEM_PROMPT_FULL,
            TRADE_SYSTEM_PROMPT_MINIMAL,
            TRADE_SYSTEM_PROMPT_OSINT,
        )

        return {
            "FIRST_TURN": TRADE_SYSTEM_PROMPT_FIRST_TURN,
            "MINIMAL": TRADE_SYSTEM_PROMPT_MINIMAL,
            "OSINT": TRADE_SYSTEM_PROMPT_OSINT,
            "FULL": TRADE_SYSTEM_PROMPT_FULL,
        }

    @pytest.mark.parametrize("tier", ["FIRST_TURN", "MINIMAL", "OSINT", "FULL"])
    def test_every_tier_carries_the_rule(self, tier):
        """每一档都必须含铁律块。"""
        text = self._tiers()[tier]

        assert IMAGE_BLOCK_HEADER in text, f"{tier} 档缺少图片铁律块"
        assert "vision_analyze" in text, f"{tier} 档缺少 vision_analyze 指令"

    def test_all_tiers_share_the_same_block(self):
        """四档共用同一个常量（单一事实来源），避免各写一份而慢慢漂移。"""
        from trade.prompt import TRADE_IMAGE_BLOCK

        for name, text in self._tiers().items():
            assert TRADE_IMAGE_BLOCK in text, f"{name} 档内嵌的块与 TRADE_IMAGE_BLOCK 不一致"


@pytest.fixture
def company_env(monkeypatch, tmp_path):
    """临时库 + 一家公司：只为跑真实 build_query 装配器。"""
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
    return co.create(name="Img Co", slug="img-co")


class TestImageRuleReachesModel:
    """走真实装配器 `build_query`，断言铁律真的进了最终发给模型的 prompt。

    读代码不足以判断这类改动是否生效 —— 本项目已多次出现「常量写了、档位也在、
    运行时没送到」。这里断言的是最终文本。
    """

    def _build(self, env, query, *, calls=1):
        import trade.helpers as helpers

        result = None
        for _ in range(calls):
            result = helpers.build_query(env["id"], None, query)
        return result

    def test_plain_chat_carrying_an_image_path_gets_the_rule(self, company_env):
        """复现 #83 的真实场景：聊天框里直接给图片路径（非拖拽导入）。"""
        prompt, _ = self._build(company_env, "识别图片 '/Users/rogerlau/Desktop/截屏2026-09-29 08.39.50.png'")

        assert IMAGE_BLOCK_HEADER in prompt
        assert "vision_analyze" in prompt

    def test_later_turns_still_get_the_rule(self, company_env):
        """非首轮（精简档）也必须带 —— 用户可能是第二句才贴图。"""
        prompt, _ = self._build(company_env, "再看这张图", calls=2)

        assert IMAGE_BLOCK_HEADER in prompt

    def test_rule_survives_identity_composition(self, company_env):
        """基础规则与公司身份是组合关系，铁律不能被身份文本顶掉。"""
        prompt, _ = self._build(company_env, "你好")

        assert "# Disclaimer" in prompt, "前置条件：基础块确实在"
        assert "当前工作公司" in prompt, "前置条件：身份文本确实在"
        assert IMAGE_BLOCK_HEADER in prompt, "身份文本不得顶替图片铁律"
