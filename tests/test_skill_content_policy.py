"""技能内容合规与一致性回归（2026-11-04）。

审计发现：无出处成功率、未授权课程署名、响应时效互相矛盾、客户分级口径冲突、
写死的金额/行业示例。这里逐条钉住，防止回潮。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"


def _all_skill_texts() -> list[tuple[str, str]]:
    rows = []
    for p in SKILLS.rglob("*.md"):
        if p.name == "STANDARDS.md":
            continue
        rows.append((str(p.relative_to(ROOT)), p.read_text(encoding="utf-8")))
    return rows


def _text(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


class TestNoFabricatedClaims:
    FORBIDDEN = (
        "成功率预估",
        "Holly",
        "外贸连环跟进108招",
        "108招",
        "80%成交",
        "80% of customers are closed",
        "佣金折扣",
    )

    def test_forbidden_claims_absent(self):
        hits = []
        for path, text in _all_skill_texts():
            for token in self.FORBIDDEN:
                if token in text:
                    hits.append((path, token))
        assert not hits, f"技能里仍有高风险表述：{hits}"


class TestResponseSla:
    def test_single_sla_source_of_truth(self):
        text = _text("b2b-inquiry-training")
        assert "响应时效口径（全站统一）" in text
        assert "工作时间内首响 ≤30 分钟" in text
        assert "5 分钟是理想值" in text
        assert "2 小时内给出报价/方案等实质进展" in text

    def test_other_skills_do_not_contradict(self):
        assert "≤30 分钟（工作时间）" in _text("b2b-sales-playbook")
        assert "工作时间内 30 分钟内回复" in _text("b2b-lead-generation")


class TestCustomerGrading:
    def test_customer_grade_has_one_owner(self):
        assert "客户档案等级的唯一口径" in _text("b2b-customer-mgmt")

    def test_pipeline_uses_temperature_not_grade(self):
        text = _text("b2b-sales-pipeline")
        assert "商机温度（Hot/Warm/Cold" in text
        assert "A 级（Hot）" not in text

    def test_linkedin_labels_priority(self):
        assert "开发优先级，不是客户档案等级" in _text("b2b-linkedin-marketing")

    def test_exhibition_uses_intent_levels(self):
        text = _text("b2b-exhibition")
        assert "展会意向分级" in text and "高 / 中 / 低" in text


class TestNoUnauthorizedNames:
    """外贸业务文档均未取得授权，技能里不得出现文档中的公司名与人名。"""

    TEACHERS = (
        "王辛",
        "太阳老师",
        "沈腾",
        "刘沅臻",
        "Holly",
        "跨境侠客",
        "合君",
        "福友",
        "fuyoutools",
        "Sammy",
        "智囊团",
        "老师",
    )
    CASES = (
        "Walmart",
        "Bunnings",
        "Lowe's",
        "EuroPack",
        "ABC GmbH",
        "XYZ Hydraulics",
        "John",
        "Smith",
    )

    def test_no_teacher_or_course_names(self):
        hits = []
        for path, text in _all_skill_texts():
            for token in self.TEACHERS:
                if token in text:
                    hits.append((path, token))
        assert not hits, f"技能里仍有未获授权的讲师/课程名：{hits}"

    def test_no_case_company_or_person_names(self):
        hits = []
        for path, text in _all_skill_texts():
            for token in self.CASES:
                if token in text:
                    hits.append((path, token))
        assert not hits, f"技能里仍有示例公司/人名：{hits}"


class TestNoHardcodedNumbers:
    def test_pipeline_has_no_fixed_amounts_or_stats(self):
        text = _text("b2b-sales-pipeline") + (SKILLS / "b2b-sales-pipeline" / "references" / "qa_pairs.md").read_text(encoding="utf-8")
        for token in ("$15", "$14.5", "电视外框", "25-40%"):
            assert token not in text, f"b2b-sales-pipeline 仍有写死内容：{token}"

    def test_course_attribution_is_neutral(self):
        text = _text("b2b-sales-playbook")
        assert "来源未核实" in text
        assert "Holly" not in text
