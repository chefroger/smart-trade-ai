"""背调事实库（2026-11-22）：事实落盘、同目标复用、冲突并列。

为什么：模型查到的工商信息原先只存在聊天文本里，下次背调只能从零再赌一次反爬 ——
于是同一目标两次跑，第二次就变成「暂未找到」。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import osint_facts  # noqa: E402


@pytest.fixture
def company(monkeypatch, tmp_path):
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
    return co.create(name="Facts Co", slug="facts-co")["id"]


class TestNormalizeSubject:
    def test_prefix_is_stripped(self):
        assert osint_facts.normalize_subject("company:ACME") == "ACME"
        assert osint_facts.normalize_subject("公司:天津赛得进出口有限公司") == "天津赛得进出口有限公司"
        assert osint_facts.normalize_subject("domain:spiderimpex.com") == "spiderimpex.com"
        assert osint_facts.normalize_subject("公司：天津赛得进出口有限公司") == "天津赛得进出口有限公司"

    def test_domain_is_lowercased(self):
        assert osint_facts.normalize_subject("SpiderImpex.COM") == "spiderimpex.com"
        assert osint_facts.normalize_subject("www.spiderimpex.com") == "spiderimpex.com"

    def test_company_keeps_case_but_collapses_spaces(self):
        assert osint_facts.normalize_subject("  ACME   Trading  ") == "ACME Trading"

    def test_empty(self):
        assert osint_facts.normalize_subject("") == ""
        assert osint_facts.normalize_subject("   ") == ""


class TestSaveAndReuse:
    def test_save_then_known_facts(self, company):
        row = osint_facts.save_fact(
            company, "天津赛得进出口有限公司", "法定代表人", "迟国波",
            source_url="https://example.com/a", source_name="企查查")
        assert row is not None
        assert row["subject"] == "天津赛得进出口有限公司"

        known = osint_facts.known_facts(company, "天津赛得进出口有限公司")
        assert known["法定代表人"]["values"] == ["迟国波"]
        assert known["法定代表人"]["conflict"] is False

    def test_same_fact_updates_observed_at_only(self, company):
        for _ in range(3):
            osint_facts.save_fact(company, "acme.com", "注册资本", "100万",
                                  source_url="https://example.com/a")
        rows = osint_facts.list_facts(company, "acme.com")
        assert len(rows) == 1

    def test_different_source_keeps_both_rows(self, company):
        osint_facts.save_fact(company, "acme.com", "注册资本", "100万",
                              source_url="https://a.com")
        osint_facts.save_fact(company, "acme.com", "注册资本", "100万",
                              source_url="https://b.com")
        rows = osint_facts.list_facts(company, "acme.com")
        assert len(rows) == 2
        known = osint_facts.known_facts(company, "acme.com")
        assert known["注册资本"]["values"] == ["100万"]   # 同值不同源 → 不算冲突
        assert known["注册资本"]["conflict"] is False

    def test_conflicting_values_flagged(self, company):
        osint_facts.save_fact(company, "acme.com", "员工人数", "8", source_url="https://a.com")
        osint_facts.save_fact(company, "acme.com", "员工人数", "25", source_url="https://b.com")
        known = osint_facts.known_facts(company, "acme.com")
        assert known["员工人数"]["conflict"] is True
        assert sorted(known["员工人数"]["values"]) == ["25", "8"]
        assert osint_facts.conflict_fields(company, "acme.com") == ["员工人数"]

    def test_prefixed_target_matches_unprefixed(self, company):
        """第一次用 `company:天津赛得…` 登记，第二次用裸名查 —— 要能对上。"""
        osint_facts.save_fact(company, "company:天津赛得进出口有限公司", "注册资本", "100万")
        known = osint_facts.known_facts(company, "天津赛得进出口有限公司")
        assert known["注册资本"]["values"] == ["100万"]

    def test_other_company_cannot_see(self, company, monkeypatch, tmp_path):
        import trade.company as co

        def _setup(name, slug, suggested_name=""):
            wd = tmp_path / (suggested_name or name)
            wd.mkdir(parents=True, exist_ok=True)
            return wd, True

        monkeypatch.setattr(co, "_setup_work_directory", _setup)
        other = co.create(name="Other Co", slug="other-co")["id"]
        osint_facts.save_fact(company, "acme.com", "注册资本", "100万")
        assert osint_facts.known_facts(other, "acme.com") == {}

    def test_invalid_fact_rejected(self, company):
        assert osint_facts.save_fact(company, "", "注册资本", "100万") is None
        assert osint_facts.save_fact(company, "acme.com", "", "100万") is None
        assert osint_facts.save_fact(company, "acme.com", "注册资本", "  ") is None

    def test_delete_facts(self, company):
        osint_facts.save_fact(company, "acme.com", "注册资本", "100万")
        assert osint_facts.delete_facts(company, "acme.com") == 1
        assert osint_facts.list_facts(company, "acme.com") == []
