"""PPT 差距项 B4→B1→B2→B3 的静态与路由回归（2026-11-09）。

背景：Roger 用《智贸新动能 V3》PPT 做了差距分析并逐条核实，确认 PPT 里的
若干数字/说法不实或口径被改。本文件钉住四件事：

1. 新增的事实/推断标注只在 prompt.py 里有一个来源，且四个档位都带上；
2. 背调/画像 skill 固定五节 + 「暂未找到」+ 已查渠道；
3. 知识库地图用正确路径（~/.trade/{slug}/companies/{slug}/），初始化不覆盖；
4. 报价 BOM 与卡点诊断的护栏（缺数据先问、认证只看资质夹、只起草不发送），
   以及 PPT 里的不实数字/说法不许回潮。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"


def _text(name: str) -> str:
    """读取指定 skill 的 SKILL.md 全文。"""
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def _load_prompt_module():
    """直接按文件加载 trade/prompt.py，避免触发 trade 包的其它依赖。"""
    spec = importlib.util.spec_from_file_location("trade_prompt_ppt_gap", ROOT / "trade" / "prompt.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _section(text: str, start_marker: str, end_marker: str) -> str:
    """截取两个标记之间的文本；缺标记时断言失败，避免静默跳过。"""
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


MODIFIED_SKILLS = (
    "b2b-osint",
    "b2b-customer-intel",
    "b2b-data-directory",
    "b2b-onboarding",
    "b2b-doc-generation",
    "b2b-sales-playbook",
)

# 经核实不实、口径被改或无出处的 PPT 表述（只列能精确匹配、不会误伤的）
FORBIDDEN_PPT_CLAIMS = (
    "1600 万",
    "1600万",
    "71%",
    "77%",
    "72%",
    "930 万美元",
    "930万美元",
    "240 句",
    "80,000 积分",
    "¥4,500",
    "¥8,000",
    "FDA 认证",
    "FDA approved",
    "清关零风险",
    "保证清关",
    "ZetaAPI",
)

# 只允许出现在「禁止/不得」语境里的输出用语
SEND_TOKENS = ("已发送", "可直接发送", "可直接发")
NEGATION_MARKERS = ("不", "禁", "未", "除非", "勿")


class TestEvidenceDisciplineBlock:
    """B4：事实/推断标注必须有唯一来源，且四个档位都带。"""

    def test_block_is_short_and_has_required_tags(self):
        prompt = _load_prompt_module()
        block = prompt.TRADE_EVIDENCE_BLOCK.strip()
        non_empty = [line for line in block.splitlines() if line.strip()]

        assert len(non_empty) <= 15, "prompt.py 新增块超过 15 行"
        for token in ("[事实]", "[推断]", "[待核实]", "暂未找到", "已查渠道"):
            assert token in block, f"新增块缺少 {token}"

    def test_all_tiers_carry_the_block(self):
        prompt = _load_prompt_module()
        for tier in (
            "TRADE_SYSTEM_PROMPT_FIRST_TURN",
            "TRADE_SYSTEM_PROMPT_MINIMAL",
            "TRADE_SYSTEM_PROMPT_OSINT",
            "TRADE_SYSTEM_PROMPT_FULL",
        ):
            assert "[待核实]" in getattr(prompt, tier), f"{tier} 未携带事实/推断块"

    def test_osint_and_customer_intel_have_five_sections(self):
        for skill in ("b2b-osint", "b2b-customer-intel"):
            text = _text(skill)
            for section in ("它是谁", "买什么", "找谁", "风险在哪", "从哪切入"):
                assert section in text, f"{skill} 缺少五节之一：{section}"
            assert "暂未找到" in text, f"{skill} 缺少「暂未找到」"
            assert "已查渠道" in text, f"{skill} 缺少「已查渠道」"


class TestOutboundActionBan:
    """Trade 不代发、不写发件箱；四个档位都必须常驻。"""

    def test_all_tiers_forbid_sending_and_outbox(self):
        prompt = _load_prompt_module()
        for tier in (
            "TRADE_SYSTEM_PROMPT_FIRST_TURN",
            "TRADE_SYSTEM_PROMPT_MINIMAL",
            "TRADE_SYSTEM_PROMPT_OSINT",
            "TRADE_SYSTEM_PROMPT_FULL",
        ):
            text = getattr(prompt, tier)
            for token in ("发件箱", "smtplib", "帮我发出去", "存到邮箱", "草稿，需你手动发送"):
                assert token in text, f"{tier} 缺少对外动作禁令：{token}"

    def test_block_stays_short(self):
        prompt = _load_prompt_module()
        lines = [l for l in prompt.TRADE_OUTBOUND_ACTION_BLOCK.strip().splitlines() if l.strip()]
        assert len(lines) <= 6


class TestKnowledgeMap:
    """B1：路径必须与 data_dir 层级一致；初始化不覆盖；检查不联网。"""

    def test_data_directory_uses_real_path(self):
        text = _text("b2b-data-directory")
        assert "~/.trade/{slug}/companies/{slug}/" in text
        assert "00-index.md" in text
        assert "初始化知识库" in text
        assert "检查知识库" in text
        assert "不覆盖" in text
        assert "不联网" in text

    def test_template_index_exists_and_is_navigation_only(self):
        template = ROOT / ".trade-template" / "companies" / "company-slug" / "00-index.md"
        assert template.is_file(), "缺少 00-index.md 模板"
        text = template.read_text(encoding="utf-8")
        assert "| 编号夹 |" in text
        # 模板只能是表头/导航，不能带真实数据
        for token in ("USD", "$", "证书编号"):
            assert token not in text

    def test_onboarding_mentions_knowledge_check(self):
        assert "检查知识库" in _text("b2b-onboarding")


class TestValueBom:
    """B2：进入条件、缺数据先问、内外两份、认证护栏、固定结尾。"""

    def test_required_rules_present(self):
        text = _text("b2b-doc-generation")
        for token in (
            "价值 BOM",
            "Incoterms 2020",
            "数量或数量阶梯",
            "对外英文草稿",
            "对内中文说明",
            "不出现成本、利润、利润率",
            "07 资质夹",
            "待填",
            "草稿，需人工确认价格、利润和认证后才能发给客户",
        ):
            assert token in text, f"b2b-doc-generation 缺少：{token}"

    def test_new_section_is_generic(self):
        text = _text("b2b-doc-generation")
        section = _section(text, "价值 BOM 报价草稿（可选步骤）", "交付前自检")
        for token in ("中国", "德国", "美国", "上海", "宁波", "Hamburg", "Shanghai"):
            assert token not in section, f"价值 BOM 段落出现具体国家/城市：{token}"

    def test_external_cost_words_outside_prohibition_absent(self):
        """P2-4 / P2-B：价值 BOM 全段（含散文，不只代码块）不得出现英文成本词。

        禁令句本身允许出现这些词；除禁令行外，任何一行出现即失败。
        """
        import re

        section = _section(_text("b2b-doc-generation"), "价值 BOM 报价草稿（可选步骤）", "交付前自检")
        offenders = []
        for line in section.splitlines():
            for word in ("cost", "profit", "margin", "markup"):
                if not re.search(rf"\b{word}s?\b", line, re.IGNORECASE):
                    continue
                # 只允许出现在「不得 / 不出现 / 禁止」这类禁令语境里
                if not any(marker in line for marker in ("不", "禁", "勿", "免")):
                    offenders.append((word, line.strip()))
        assert not offenders, f"对外说明出现未加禁令的成本词：{offenders}"
        # 禁令本身必须写清楚英文词，不能只有中文「成本」
        assert "cost / costs / profit / margin / markup" in section


class TestStallDiagnosis:
    """B3：原话→卡点→草稿；不确定要给候选；聊天短句也要标草稿。"""

    def test_required_rules_present(self):
        text = _text("b2b-sales-playbook")
        for token in (
            "先引用原话",
            "询盘澄清",
            "价格异议",
            "付款与账期",
            "不确定",
            "两个候选",
            "草稿，需你手动发送",
            "待填",
        ):
            assert token in text, f"b2b-sales-playbook 缺少：{token}"

    def test_registry_has_new_triggers(self):
        registry = (ROOT / "trade" / "skill_registry.py").read_text(encoding="utf-8")
        for trigger in ("客户这样回", "这封怎么回", "卡在哪一步"):
            assert trigger in registry, f"skill_registry 缺少触发词：{trigger}"

    def test_whatsapp_send_reminder_is_mandatory(self):
        """WhatsApp 草稿必须固定附发送提醒；微信草稿不套 WhatsApp 提醒。

        B 口径：提醒留在注入里。这里直接解析仓库 frontmatter，不调用
        load_injection_prompt —— 后者会优先读用户机上的 ~/.hermes/skills，
        本地与 CI 可能测到不同文件。
        """
        import re

        import yaml

        text = _text("b2b-sales-playbook")
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
        assert match, "SKILL.md 缺 frontmatter"
        frontmatter = yaml.safe_load(match.group(1)) or {}
        injection = frontmatter.get("injection_prompt") or ""
        body = text[match.end():]

        for token in ("WhatsApp 发送提醒", "群发", "非官方客户端", "opt-in", "stop"):
            assert token in text, f"b2b-sales-playbook 缺少发送提醒内容：{token}"
        assert "WhatsApp 发送提醒" in injection, "注入里缺 WhatsApp 发送提醒"
        assert "WhatsApp 发送提醒" in body, "正文里缺 WhatsApp 发送提醒"
        assert "每次输出 WhatsApp 聊天草稿" in injection, "注入未限定 WhatsApp 草稿"
        assert "微信草稿只需标" in body, "微信草稿不应附 WhatsApp 提醒"


class TestRouting:
    def test_stall_queries_route_to_sales_playbook(self):
        from trade.skill_router import match_skill

        for query in (
            "客户这样回：We found cheaper elsewhere",
            "这封怎么回：We found cheaper elsewhere",
            "这单卡在哪一步了",
        ):
            result = match_skill(query)
            assert result is not None, f"{query} 无路由"
            assert result["name"] == "b2b-sales-playbook", f"{query} 路由到了 {result['name']}"

    def test_find_customers_still_routes_to_lead_generation(self):
        from trade.skill_router import match_skill

        result = match_skill("帮我找德国的客户")
        assert result is not None
        assert result["name"] == "b2b-lead-generation"

    def test_bom_intent_beats_incoterm_mention(self):
        """P2-3：只有带 BOM/价值报价意图时才压过 CIF，纯术语问句仍走合规。"""
        from trade.skill_router import match_skill

        result = match_skill("按 CIF 重做价值 BOM")
        assert result is not None
        assert result["name"] == "b2b-doc-generation"

        result = match_skill("CIF 和 FOB 风险怎么划分")
        assert result is not None
        assert result["name"] == "b2b-trade-compliance"

        result = match_skill("CIF 报价要不要含保险")
        assert result is None or result["name"] != "b2b-doc-generation"

    def test_english_rewrites_route_to_the_right_skill(self):
        from trade.skill_router import match_skill

        cases = {
            "is this company legit?": "b2b-osint",
            "check the knowledge base": "b2b-data-directory",
            "value bom for this quote": "b2b-doc-generation",
            "how should i reply to this customer": "b2b-sales-playbook",
        }
        for query, expected in cases.items():
            result = match_skill(query)
            assert result is not None, f"{query} 无路由"
            assert result["name"] == expected, f"{query} 路由到了 {result['name']}"

    def test_short_triggers_do_not_hijack_unrelated_queries(self):
        """2026-11-10 审计 P2-1：短词子串不能把无关问句带进逼单/跟进 skill。"""
        from trade.skill_router import match_skill

        for query in (
            "客户回款了，怎么记账",
            "客户回国了",
            "直接发过去报价单",
            "the shipment is not responding",
            "customer replied to the newsletter",
            "how to reply to this inquiry",
        ):
            result = match_skill(query)
            assert result is None or result["name"] != "b2b-sales-playbook", (
                f"{query} 被过宽触发词带进了 b2b-sales-playbook"
            )

    def test_contextual_reply_queries_still_route_to_sales_playbook(self):
        """收窄后，带宾语/语境的说法仍应进入 playbook（防收窄过头）。"""
        from trade.skill_router import match_skill

        for query in (
            "客户回了一句太贵了",
            "客户说太贵了怎么办",
            "这封怎么回，客户压价",
            "卡在哪一步了，客户已读不回",
            # 2026-11-10 审计 P2-A：补回完整说法，不加回短词
            "客户回：OK noted.",
            "咋整，这个客户一直不回",
            "给我一段 WhatsApp 直接发过去",
        ):
            result = match_skill(query)
            assert result is not None, f"{query} 无路由"
            assert result["name"] == "b2b-sales-playbook", (
                f"{query} 路由到了 {result['name']}"
            )


class TestSocialMediaCaution:
    def test_facebook_usage_reminder_present(self):
        """输出 Facebook 内容时必须附带使用提醒（账号/主页/BM 限制风险）。"""
        text = _text("b2b-social-media")
        for token in ("Facebook 使用提醒", "公共主页", "Business Manager", "群组", "双因素"):
            assert token in text, f"b2b-social-media 缺少 Facebook 使用提醒：{token}"
        registry = (ROOT / "trade" / "skill_registry.py").read_text(encoding="utf-8")
        assert "Facebook 使用提醒" in registry, "注入用的 augment_prompt 没有带上提醒"


class TestContentHygiene:
    def test_forbidden_ppt_claims_absent(self):
        hits = []
        for skill in MODIFIED_SKILLS:
            text = _text(skill)
            for token in FORBIDDEN_PPT_CLAIMS:
                if token in text:
                    hits.append((skill, token))
        prompt_text = (ROOT / "trade" / "prompt.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_PPT_CLAIMS:
            if token in prompt_text:
                hits.append(("trade/prompt.py", token))
        assert not hits, f"出现已核实不实/无出处的表述：{hits}"

    def test_no_affirmative_send_claims(self):
        """「已发送」「可直接发送」只能出现在禁止语境里，不能当输出示例。"""
        hits = []
        for skill in MODIFIED_SKILLS:
            for lineno, line in enumerate(_text(skill).splitlines(), 1):
                for token in SEND_TOKENS:
                    if token in line and not any(marker in line for marker in NEGATION_MARKERS):
                        hits.append((skill, lineno, token))
        assert not hits, f"出现可直接发送/已发送的输出示例：{hits}"

    def test_new_blocks_have_no_forbidden_send_tokens_outside_negation(self):
        prompt_text = (ROOT / "trade" / "prompt.py").read_text(encoding="utf-8")
        for marker in ("已发送", "可直接发送"):
            for line in prompt_text.splitlines():
                if marker in line:
                    assert any(m in line for m in NEGATION_MARKERS), f"prompt.py 出现非禁止语境的 {marker}"


class TestInvariants:
    def test_auto_smtp_email_still_blocked(self):
        from trade.skill_registry import _BLOCKED_SKILLS

        assert "auto-smtp-email" in _BLOCKED_SKILLS

    def test_skill_count_unchanged(self):
        dirs = [p for p in SKILLS.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()]
        assert len(dirs) == 45, f"skill 目录数量变为 {len(dirs)}，应为 45"
