"""技能路由的自然语言回归测试。"""

import pytest


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("帮我查一下公司", "b2b-osint"),
        ("帮我查一下邮箱", "b2b-email-intel"),
        ("查一下公司的背景", "b2b-osint"),
        ("帮我写一封冷邮件", "b2b-cold-outreach"),
        ("write an outreach email", "b2b-cold-outreach"),
        ("Check whether this email is real", "b2b-email-intel"),
        ("Analyze this quotation document", "b2b-document"),
        ("Practice replying to a difficult inquiry", "b2b-inquiry-training"),
        ("分析这份报价单", "b2b-document"),
        ("分析一下买家画像", "b2b-buyer-persona"),
        ("设置每日简报", "b2b-daily-automation"),
        ("分析一个市场", "b2b-market-analysis"),
        ("做一个skill", "b2b-skill-generator"),
        ("帮我查客户资料", "b2b-customer-mgmt"),
        ("分析这家公司的市场", "b2b-market-analysis"),
        ("做一个商业提案", "b2b-guarantee-proposal"),
        ("buyer persona", "b2b-buyer-persona"),
        ("LinkedIn", "b2b-linkedin-marketing"),
        ("领英", "b2b-linkedin-marketing"),
        ("客户分析", "b2b-customer-intel"),
        ("客户跟进", "b2b-sales-pipeline"),
        ("市场调研", "b2b-market-analysis"),
        ("竞争对手分析", "b2b-market-analysis"),
        ("展会邀约", "b2b-exhibition"),
        ("follow-up email", "b2b-cold-outreach"),
        ("商业提案", "b2b-guarantee-proposal"),
        ("客户档案", "b2b-customer-mgmt"),
        ("customer profile", "b2b-customer-mgmt"),
        ("产品介绍", "b2b-product-description"),
        ("展会邀请", "b2b-exhibition"),
        ("市场调研", "b2b-market-analysis"),
        ("竞争对手分析", "b2b-market-analysis"),
        ("end to end lead generation", "auto-trade-customer-development"),
    ],
)
def test_natural_language_routes_to_specialized_skill(query, expected):
    """自然语言查询应命中最具体的业务技能，而不是泛技能或无匹配。"""
    from trade.skill_router import match_skill

    result = match_skill(query)

    assert result is not None
    assert result["name"] == expected


def test_specialized_outreach_beats_generic_lead_generation():
    """开发信写作应由专职冷 outreach 技能处理，而非客户开发总技能。"""
    from trade.skill_router import match_skill

    result = match_skill("写一封开发信给德国客户")

    assert result is not None
    assert result["name"] == "b2b-cold-outreach"


def test_alias_name_explicit_call_resolves_to_registered_skill():
    """显式使用注册表 alias 时，应解析到对应的实际 skill。"""
    from trade.skill_router import match_skill

    result = match_skill("用 memory")

    assert result is not None
    assert result["name"] == "chat-memory"


def test_alias_name_explicit_augmentation_uses_registered_skill():
    """通过 alias 显式注入时，也应加载对应 skill 的规则。"""
    from trade.skill_router import augment_query

    result = augment_query("查询上次讨论", skill_name="memory")

    assert "chat-memory" in result
    assert "SKILL AUGMENTATION" in result


def test_blocked_alias_does_not_resolve_to_another_skill():
    """被禁用的 auto-smtp-email alias 不能绕过封禁解析到自动开发流水线。"""
    from trade.skill_router import match_skill

    assert match_skill("用 auto-smtp-email") is None


def test_document_skill_does_not_include_generation_instructions():
    """文档分析 skill 不应包含与其职责冲突的文档生成指令。"""
    from pathlib import Path

    text = Path("skills/b2b-document/SKILL.md").read_text(encoding="utf-8")

    assert "## Document Generation" not in text
    assert "When the user asks you to create a business document" not in text


def test_qa_cache_reloads_when_reference_file_changes(monkeypatch, tmp_path):
    """QA 文件更新后，mtime 缓存不能继续返回旧内容。"""
    import os
    import time

    import trade.skill_router as router

    skill_dir = tmp_path / "skill"
    qa_path = skill_dir / "references" / "qa_pairs.md"
    qa_path.parent.mkdir(parents=True)
    monkeypatch.setattr(router, "_get_skill_dir", lambda _name: skill_dir)
    router._QA_CACHE.clear()

    qa_path.write_text("## Q1: 旧问题？\n**答案**: 旧答案。\n", encoding="utf-8")
    first = router._load_qa_pairs("test-skill")
    assert first[0]["a"] == "旧答案。"

    qa_path.write_text("## Q1: 新问题？\n**答案**: 新答案。\n", encoding="utf-8")
    future = time.time() + 2
    os.utime(qa_path, (future, future))
    second = router._load_qa_pairs("test-skill")

    assert second[0]["a"] == "新答案。"


class TestChinaLeadsRouting:
    """新技能 b2b-china-leads 的路由：该命中的命中，**别抢别人的活**。

    实测踩过三处（都写进断言了）：
    ① 只写「找厂家/找供应商」这类触发词时，"帮我找浙江的五金厂"**匹配不到任何技能**
       —— 中文没有词边界，口语说法和触发词很难字面重合；
    ② 补触发词时加了"工厂"，结果与 b2b-* 的"工厂视频"**双命中（2 > 1）**，
       把"工厂视频怎么拍"抢了过来 —— 去掉"工厂"、只留单字"厂"后与它打平，
       靠列表顺序让原技能胜出；
    ③ v2.0.0 加"找货源/挖竞品"触发词时，裸"OEM"因 **ASCII 词边界命中得 3 分**，
       把"OEM 合同怎么签""写一封 OEM 合作邮件"这类邻近语义全抢过来；
       裸"贴牌"同理（"贴牌生产的合规要求"开头即词边界）。改成复合词
       （"OEM 厂家"/"贴牌厂家"/"找OEM"…）后只在货源语境命中。
    """

    @pytest.mark.parametrize("query", [
        # 模式③ / 通用
        "帮我找国内做注塑模具的厂家",
        "帮我找浙江的五金厂",
        "找东莞的模具厂",
        "开发国内客户",
        "国内获客",
        "1688 上找供应商",
        "帮我找国内的供应商",
        # 模式① 找货源（v2.0.0）
        "帮我找货源",
        "这批货想找代工厂",
        "找源头厂家",
        "国内代工",
        "想找 OEM 工厂",
        "找OEM供应商",
        "有没有贴牌厂家",
        "找能做贴牌的厂",
        # 模式② 挖竞品国内厂家（v2.0.0）
        "帮我找竞品厂家",
        "国内做同类产品的厂家",
        "同行厂家有哪些",
        "竞争对手厂家名单",
        "竞品工厂分布在哪些地区",
        "找同类厂商",
    ])
    def test_domestic_queries_hit_the_new_skill(self, query):
        from trade.skill_router import match_skill

        matched = match_skill(query)
        assert matched is not None, f"{query!r} 没匹配到任何技能"
        assert matched["name"] == "b2b-china-leads", (
            f"{query!r} 命中了 {matched['name']}，应为 b2b-china-leads"
        )

    @pytest.mark.parametrize("query,expected", [
        ("工厂视频怎么拍", "b2b-short-video"),      # 曾被我方"工厂"双命中抢走
        ("帮我写验厂邀请", "b2b-trade-ops"),
        ("供应商分析怎么做", "b2b-customs-data"),
        ("帮我找德国的客户", "b2b-lead-generation"),  # 海外开发不该被国内技能截胡
        ("帮我做竞品分析", "b2b-market-analysis"),    # 竞品"分析"归 market-analysis，我方只管"找厂家"
        ("竞品分析怎么写", "b2b-market-analysis"),
    ])
    def test_does_not_steal_neighbouring_skills(self, query, expected):
        from trade.skill_router import match_skill

        matched = match_skill(query)
        assert matched is not None and matched["name"] == expected, (
            f"{query!r} 被 {matched and matched['name']} 抢走了，应为 {expected}"
        )

    @pytest.mark.parametrize("query", [
        # 裸"OEM"/"贴牌"曾把这些全抢走（词边界 3 分）——回归防线
        "写一封 OEM 合作邮件",
        "贴牌生产的合规要求",
        "OEM 合同怎么签",
        "外贸 OEM 和 ODM 的区别",
        "贴牌产品怎么写描述",
    ])
    def test_neighbouring_semantics_not_stolen_by_bare_oem_tiezi(self, query):
        """OEM/贴牌 邻近语义（合同/合规/翻译/产品描述）不许被本技能吸走。

        这些语句可能归别的技能、也可能无人认领（None）——两种都行，
        唯一不许的就是落到 b2b-china-leads（它的注入提示词会跑错工作流）。
        """
        from trade.skill_router import match_skill

        matched = match_skill(query)
        assert matched is None or matched["name"] != "b2b-china-leads", (
            f"{query!r} 被抢到了 b2b-china-leads（应为 None 或原技能）"
        )


class TestTriggerMutualExclusivity:
    """跨技能触发词互斥性审计（2026-10-20，意图路由加固第一项）。

    关键词路由的准度完全取决于触发词的互斥性：两个 skill 拥有同一个词时，结果由
    打分/注册顺序决定，等于"谁先注册谁赢"，而赢家未必是对的。审计时实测 15/1074
    条被抢，典型误路由："market research"→customs-data（应 market-analysis）、
    "一键开发客户"→向导（应全自动流水线）、"催单"→lead-generation（应 sales-pipeline）。

    两条不变量（新增 skill / 触发词时若打破，先做归属决策，再改测试）：
    ① 同一触发词（大小写不敏感）只能属于一个 skill；
    ② 每条触发词单独作为查询时，必须路由回它自己的 skill。
    """

    @staticmethod
    def _active_skills():
        from trade.skill_registry import _BLOCKED_SKILLS, _SKILLS

        return [s for s in _SKILLS if s["name"] not in _BLOCKED_SKILLS]

    def test_no_cross_skill_duplicate_triggers(self):
        owners: dict[str, list[str]] = {}
        for skill in self._active_skills():
            # 路由匹配不区分大小写，这里也必须不区分（"Incoterms"/"incoterms" 曾是漏网之鱼）
            for trigger in skill.get("triggers", []):
                owners.setdefault(trigger.lower(), []).append(skill["name"])
        dupes = {t: ns for t, ns in owners.items() if len(ns) > 1}
        assert not dupes, (
            "触发词跨技能重复 —— 路由结果将取决于打分/注册顺序，而不是语义：\n"
            + "\n".join(f"  {t!r} → {ns}" for t, ns in sorted(dupes.items()))
        )

    def test_every_trigger_routes_to_its_owner(self):
        from trade.skill_router import match_skill

        stolen = []
        for skill in self._active_skills():
            for trigger in skill.get("triggers", []):
                matched = match_skill(trigger)
                if matched is None or matched["name"] != skill["name"]:
                    stolen.append((trigger, skill["name"], matched and matched["name"]))
        assert not stolen, (
            "以下触发词单独查询时没有路由回自己的技能（被抢或无命中）：\n"
            + "\n".join(f"  {t!r} 属于 {owner}，实际 → {got}" for t, owner, got in stolen)
        )


class TestPlatformSpecificInjectionIsSelfDetected:
    """平台专属规则必须**由 agent 自己识别**触发，不能要求用户指明。

    背景（2026-10-22）：b2b-platform 的阿里国际站专属规则（约 900 token）原先
    放在 injection_prompt 里 —— 94% 的用户不是阿里站，却每次对话都付这份钱。
    移到正文后，如果写成「仅当用户是阿里国际站」，等于把判断责任推给用户：
    真实提问常常只写「帮我优化下产品页」，不会说自己用的是阿里站。
    正确做法是给 agent **可判定的信号**（URL 域名 / 提到的后台模块名 / 页面特有字段），
    让它自己识别后用 skill_view 加载。
    """

    def _skill_text(self, name="b2b-platform"):
        from pathlib import Path

        return (Path(__file__).resolve().parent.parent
                / "skills" / name / "SKILL.md").read_text(encoding="utf-8")

    def test_injection_does_not_demand_user_confirmation(self):
        """注入里不能出现「仅当用户是阿里站」这类要用户指明的措辞。"""
        import re

        import yaml

        text = self._skill_text()
        fm = yaml.safe_load(re.match(r"^---\n(.*?)\n---\n", text, re.S).group(1))
        ip = fm["injection_prompt"]

        for bad in ("仅当用户是阿里", "只有用户是阿里", "如果用户是阿里国际站",
                    "若用户是阿里国际站", "请用户确认是否阿里"):
            assert bad not in ip, f"注入里出现要用户指明的措辞：{bad!r}"

    def test_injection_carries_detectable_signals(self):
        """注入必须给出可判定的识别信号，让 agent 能自己判断。"""
        import re

        import yaml

        text = self._skill_text()
        fm = yaml.safe_load(re.match(r"^---\n(.*?)\n---\n", text, re.S).group(1))
        ip = fm["injection_prompt"]

        assert "alibaba.com" in ip, "注入里要给出可判定的 URL 域名信号"
        assert "不要问用户" in ip, "注入里要明确「自己判断，不要问用户」"
        assert "skill_view" in ip, "注入里要写清命中后怎么加载（skill_view）"

    def test_body_keeps_the_full_rules(self):
        """下沉到正文的规则必须完整保留（不能为了省 token 丢约束）。"""
        body = self._skill_text().split("---\n", 2)[2]
        for kw in ("P4P 词效分层", "数据参谋", "旺铺", "问鼎", "商家星等级"):
            assert kw in body, f"正文的阿里专属规则丢了：{kw}"
