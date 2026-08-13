"""测试 _BLOCKED_SKILLS 过滤逻辑。

验证 auto-smtp-email 在任何匹配路径下都不会被触发。
"""


class TestBlockedSkills:
    """测试被禁用的 skill 不会被系统匹配。"""

    def test_auto_smtp_email_not_scored(self):
        """auto-smtp-email 不应出现在评分结果中。"""
        from trade.skill_router import _score_skills

        # 直接使用其触发词
        results = _score_skills("发邮件")
        names = [r["skill_name"] for r in results]
        assert "auto-smtp-email" not in names, (
            f"auto-smtp-email 不应出现在结果中，但得到: {names}"
        )

    def test_auto_smtp_email_not_matched_by_match_skill(self):
        """match_skill 不应返回 auto-smtp-email。"""
        from trade.skill_router import match_skill

        result = match_skill("帮我发邮件")
        assert result is None or result["name"] != "auto-smtp-email"

    def test_auto_smtp_email_not_matched_by_match_skills(self):
        """match_skills 不应包含 auto-smtp-email。"""
        from trade.skill_router import match_skills

        results = match_skills("群发邮件")
        names = [r["skill_name"] for r in results]
        assert "auto-smtp-email" not in names

    def test_blocked_skill_name_in_registry(self):
        """auto-smtp-email 应在注册表中被标记为禁用。"""
        from trade.skill_registry import _BLOCKED_SKILLS

        assert "auto-smtp-email" in _BLOCKED_SKILLS

    def test_other_email_skills_not_blocked(self):
        """b2b-email-intel 和 b2b-email-imitation 不应被禁用。"""
        from trade.skill_registry import _BLOCKED_SKILLS

        assert "b2b-email-intel" not in _BLOCKED_SKILLS
        assert "b2b-email-imitation" not in _BLOCKED_SKILLS


class TestSkillCount:
    """测试技能注册表的数量。"""

    def test_all_skills_registered(self):
        """skill_registry 应有 38 个条目。"""
        from trade.skill_registry import _SKILLS

        assert len(_SKILLS) == 38

    def test_all_skill_names_unique(self):
        """所有 skill 名称不能重复。"""
        from trade.skill_registry import _SKILLS

        names = [s["name"] for s in _SKILLS]
        assert len(names) == len(set(names)), (
            f"重复的 skill 名称: {[n for n in names if names.count(n) > 1]}"
        )

    def test_new_skills_present(self):
        """新增的 7 个技能应存在于注册表中。"""
        from trade.skill_registry import skill_names

        names = set(skill_names())
        for expected in (
            "b2b-kol-imitation", "b2b-reddit-engagement", "b2b-seo-aeo",
            "b2b-short-video", "b2b-exhibition", "b2b-product-description",
            "b2b-six-thinking-hats", "b2b-inquiry-training",
        ):
            assert expected in names, f"缺少技能: {expected}"


class TestQAPairs:
    """测试 QA 对加载、解析、评分和注入。"""

    def test_parse_qa_pairs(self):
        """解析标准格式的 QA 对。"""
        from trade.skill_router import _parse_qa_pairs

        content = """## Q1: 如何做客户背调？
**答案**: 核心目标是转化为发球权。
**标签**: 背调原则, 客户筛选
**场景**: 任何客户背调
**关键词**: 背调, 发球权, 信息不对称

## Q2: 如何写开发信？
**答案**: 高回复率公式 = 初步调查 + 避开SPAM。
**标签**: 开发信公式
**场景**: 写开发信前
**关键词**: 高回复率, SPAM, 标题
"""
        pairs = _parse_qa_pairs(content)
        assert len(pairs) == 2
        assert pairs[0]["q"] == "如何做客户背调？"
        assert pairs[0]["tags"] == ["背调原则", "客户筛选"]
        assert pairs[0]["keywords"] == ["背调", "发球权", "信息不对称"]
        assert pairs[1]["q"] == "如何写开发信？"
        assert "高回复率" in pairs[1]["a"]

    def test_parse_qa_pairs_empty(self):
        """空内容返回空列表。"""
        from trade.skill_router import _parse_qa_pairs

        assert _parse_qa_pairs("") == []
        assert _parse_qa_pairs("只是一些文字没有QA格式") == []

    def test_load_qa_pairs_real_skill(self):
        """加载真实 skill 的 QA 对（b2b-osint 应有 15 条）。"""
        from trade.skill_router import _load_qa_pairs

        pairs = _load_qa_pairs("b2b-osint")
        assert len(pairs) == 15
        # 验证结构完整性
        for p in pairs:
            assert p["q"], "QA pair missing question"
            assert p["a"], "QA pair missing answer"
            assert isinstance(p["tags"], list)
            assert isinstance(p["keywords"], list)

    def test_load_qa_pairs_nonexistent(self):
        """不存在的 skill 或没有 QA 文件的 skill 返回空。"""
        from trade.skill_router import _load_qa_pairs

        assert _load_qa_pairs("nonexistent-skill") == []
        # b2b-document 没有 qa_pairs.md
        assert _load_qa_pairs("b2b-document") == []

    def test_score_qa_relevance_chinese(self):
        """中文查询匹配中文 QA 对。"""
        from trade.skill_router import _load_qa_pairs, _score_qa_relevance

        pairs = _load_qa_pairs("b2b-osint")
        relevant = _score_qa_relevance("帮我背调一下这个客户", pairs)
        assert len(relevant) > 0, "Should find relevant QA pairs for 背调 query"
        assert len(relevant) <= 5, "Should return at most 5 pairs"
        # 最高分的应该是背调相关的
        assert any("背调" in r["q"] or "背调" in r["a"] for r in relevant)

    def test_score_qa_relevance_english(self):
        """英文查询匹配英文 QA 对。"""
        from trade.skill_router import _load_qa_pairs, _score_qa_relevance

        pairs = _load_qa_pairs("b2b-cold-outreach")
        relevant = _score_qa_relevance("write a cold email to US client", pairs)
        assert len(relevant) > 0

    def test_score_qa_relevance_no_match(self):
        """完全不相关的查询返回空。"""
        from trade.skill_router import _load_qa_pairs, _score_qa_relevance

        pairs = _load_qa_pairs("b2b-osint")
        relevant = _score_qa_relevance("今天天气真好", pairs)
        assert len(relevant) == 0

    def test_augment_query_includes_qa(self):
        """augment_query 匹配到有 QA 对的 skill 时应注入相关知识块。"""
        from trade.skill_router import augment_query

        result = augment_query("帮我背调一下")
        assert "相关知识（精准匹配）" in result, "Should inject QA section"
        assert "发球权" in result or "背调" in result

    def test_augment_query_no_qa_for_skill_without_pairs(self):
        """没有 QA 文件的 skill 不注入 QA 块。"""
        from trade.skill_router import augment_query

        # b2b-document 没有 qa_pairs.md
        result = augment_query("读报价单")
        # 可能匹配到 skill 但不应该有 QA 注入
        assert "相关知识（精准匹配）" not in result or "b2b-document" not in result
