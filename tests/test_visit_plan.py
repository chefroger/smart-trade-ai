"""验厂计划：CRUD / 软删除 / 跨公司隔离 / 建议生成 / days 校验。

对应审计 O-2/O-3：此前 279 行后端 + 85 行 API 零测试。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def test_db(monkeypatch, tmp_path):
    """临时库 + 隔离桌面工作目录（与 test_business 同一套做法）。"""
    db_path = tmp_path / "trade.db"

    import trade.database as _db
    original_db = _db._get_db_path
    _db._get_db_path = lambda: db_path

    from trade.database import SCHEMA_SQL, _add_spare_columns
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    _add_spare_columns(conn)
    conn.commit()
    conn.close()

    import trade.company as _co

    def _mock_work_dir(company_name, slug, suggested_name=""):
        work_dir = tmp_path / (suggested_name or company_name)
        work_dir.mkdir(parents=True, exist_ok=True)
        for cat_name, _ in _co._WORK_DIR_CATEGORIES:
            (work_dir / cat_name).mkdir(parents=True, exist_ok=True)
        return work_dir, True

    monkeypatch.setattr(_co, "_setup_work_directory", _mock_work_dir)

    yield db_path

    _db._get_db_path = original_db


@pytest.fixture
def company_id(test_db):
    from trade import company
    return company.create(name="Visit Co", slug="visit-co")["id"]


@pytest.fixture
def customer_id(company_id):
    from trade import customer
    return customer.create("ACME", company_id=company_id)["id"]


class TestVisitPlanCrud:
    def test_create_get_update_soft_delete(self, company_id, customer_id):
        from trade import visit_plan as vp

        pid = vp.create_plan(
            company_id,
            customer_id=customer_id,
            title="来访计划",
            days="不是数字",
            payload={"risks": "内部风险"},
        )
        p = vp.get_plan(pid, company_id=company_id)
        assert p["title"] == "来访计划"
        assert p["days"] == 1  # 非法天数回落 1
        assert p["payload"] == {"risks": "内部风险"}

        p2 = vp.update_plan(pid, company_id=company_id, title="改标题", days="abc")
        assert p2["title"] == "改标题"
        assert p2["days"] == 1

        assert vp.delete_plan(pid, company_id=company_id) is True
        assert vp.get_plan(pid, company_id=company_id) is None
        assert all(x["id"] != pid for x in vp.list_plans(company_id))

    def test_cross_company_isolation(self, company_id, customer_id):
        from trade import company
        from trade import visit_plan as vp

        pid = vp.create_plan(company_id, title="A 公司计划")
        other = company.create(name="Other Co", slug="other-co")["id"]

        assert vp.get_plan(pid, company_id=other) is None
        assert vp.update_plan(pid, company_id=other, title="偷偷改") is None
        assert vp.delete_plan(pid, company_id=other) is False
        # 原公司仍能读到
        assert vp.get_plan(pid, company_id=company_id)["title"] == "A 公司计划"


class TestSuggestDraft:
    def _set_country(self, db_path, customer_id, country):
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE customers SET extra1=? WHERE id=?",
            (json.dumps({"country": country}, ensure_ascii=False), customer_id),
        )
        conn.commit()
        conn.close()

    def test_country_tips(self, test_db, company_id, customer_id):
        from trade import visit_plan as vp

        self._set_country(test_db, customer_id, "Italy")
        d = vp.suggest_draft(company_id, customer_id)
        assert d["country"] == "Italy"
        assert "【礼仪与禁忌 · Italy】" in d["risks"]
        assert "注重着装" in d["risks"]
        assert d["checklist"].strip()
        assert d["summary"].strip()

    def test_ukraine_does_not_mis_match_uk(self, test_db, company_id, customer_id):
        """Ukraine 含子串 uk，不得误命中英国礼仪（如北爱尔兰禁忌）。"""
        from trade import visit_plan as vp

        self._set_country(test_db, customer_id, "Ukraine")
        d = vp.suggest_draft(company_id, customer_id)
        assert "北爱尔兰" not in d["risks"]

    def test_profile_notes_keep_subject_and_pending(self, test_db, company_id, customer_id):
        from trade import visit_plan as vp

        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO customer_facts (company_id, customer_id, category, subject, "
            "content, source_type, status, ai_visible, fingerprint) VALUES (?,?,?,?,?,?,?,?,?)",
            (company_id, customer_id, "禁忌", "圣诞停工", "12.22–01.06 不能安排到货",
             "chat", "待确认", 0, "fp-visit-1"),
        )
        conn.execute(
            "INSERT INTO customer_facts (company_id, customer_id, category, subject, "
            "content, source_type, status, ai_visible, fingerprint) VALUES (?,?,?,?,?,?,?,?,?)",
            (company_id, customer_id, "喜好", "德英对照单据", "箱单用德英双语",
             "chat", "已确认", 1, "fp-visit-2"),
        )
        conn.commit()
        conn.close()

        d = vp.suggest_draft(company_id, customer_id)
        notes = d["profile_notes"]
        assert any("圣诞停工" in x and "12.22" in x and "待确认" in x for x in notes)
        assert any("德英对照单据" in x and "箱单用德英双语" in x for x in notes)
        # 提醒同时写进内部风险段
        assert "【客户档案提醒 · 内部】" in d["risks"]
        assert "圣诞停工" in d["risks"]


class TestDaysValidation:
    def test_as_days_falls_back(self):
        from trade.visit_plan import _as_days

        assert _as_days("abc") == 1
        assert _as_days(None) == 1
        assert _as_days(0) == 1
        assert _as_days("3") == 3

    def test_api_rejects_non_numeric_days(self):
        from fastapi import HTTPException

        from trade.api.visit_plans import _days_or_400

        assert _days_or_400(None) is None
        assert _days_or_400("2") == 2
        with pytest.raises(HTTPException) as ei:
            _days_or_400("abc")
        assert ei.value.status_code == 400
        with pytest.raises(HTTPException):
            _days_or_400(0)


class TestSensitiveProfileNotLeaked:
    def test_family_fact_never_in_suggest(self, test_db, company_id, customer_id):
        """「家庭」类原文不得出现在验厂建议的任何字段里（2026-11-20 审计 P0-1）。"""
        from trade import visit_plan as vp

        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO customer_facts (company_id, customer_id, category, subject, "
            "content, source_type, status, ai_visible, fingerprint) VALUES (?,?,?,?,?,?,?,?,?)",
            (company_id, customer_id, "家庭", "采购经理女儿",
             "女儿 Anna 明年考大学", "chat", "已确认", 0, "fp-family-1"),
        )
        conn.execute(
            "INSERT INTO customer_facts (company_id, customer_id, category, subject, "
            "content, source_type, status, ai_visible, fingerprint) VALUES (?,?,?,?,?,?,?,?,?)",
            (company_id, customer_id, "喜好", "德英对照单据", "箱单用德英双语",
             "chat", "已确认", 1, "fp-like-1"),
        )
        conn.commit()
        conn.close()

        d = vp.suggest_draft(company_id, customer_id)

        blob = json.dumps(d, ensure_ascii=False)
        assert "Anna" not in blob, "家庭类原文泄漏进了验厂建议"
        assert "女儿" not in blob
        assert "采购经理女儿" not in blob
        # 非敏感类照常带出
        assert any("德英对照单据" in x for x in d["profile_notes"])
        # 只留计数，不留原文
        assert "1 条私密档案" in d["risks"]

    def test_sensitive_note_absent_from_profile_notes(self, test_db, company_id, customer_id):
        from trade import visit_plan as vp

        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO customer_facts (company_id, customer_id, category, subject, "
            "content, source_type, status, ai_visible, fingerprint) VALUES (?,?,?,?,?,?,?,?,?)",
            (company_id, customer_id, "礼物往来", "客户送礼", "一箱红酒",
             "chat", "已确认", 0, "fp-gift-1"),
        )
        conn.commit()
        conn.close()

        d = vp.suggest_draft(company_id, customer_id)
        assert not any("红酒" in x for x in d["profile_notes"])
        assert "红酒" not in d["risks"]


class TestCustomerOwnership:
    def test_create_rejects_foreign_customer(self, company_id, customer_id):
        """customer_id 必须属于本公司（2026-11-20 审计 P2-8）。"""
        from trade import company, customer
        from trade import visit_plan as vp

        other = company.create(name="Other Owner Co", slug="other-owner-co")["id"]
        other_cust = customer.create("别的公司客户", company_id=other)["id"]

        with pytest.raises(vp.VisitPlanError):
            vp.create_plan(company_id, customer_id=other_cust, title="挂别人客户")

    def test_update_rejects_foreign_customer(self, company_id, customer_id):
        from trade import company, customer
        from trade import visit_plan as vp

        other = company.create(name="Other Owner Co 2", slug="other-owner-co-2")["id"]
        other_cust = customer.create("别的公司客户2", company_id=other)["id"]
        pid = vp.create_plan(company_id, customer_id=customer_id, title="自己的")

        with pytest.raises(vp.VisitPlanError):
            vp.update_plan(pid, company_id=company_id, customer_id=other_cust)

    def test_own_customer_ok(self, company_id, customer_id):
        from trade import visit_plan as vp

        pid = vp.create_plan(company_id, customer_id=customer_id, title="自己的客户")
        assert vp.get_plan(pid, company_id=company_id)["customer_id"] == customer_id

    def test_none_customer_still_allowed(self, company_id):
        """不关联客户的计划（customer_id 为空）必须仍能创建 —— 那是合法用法。"""
        from trade import visit_plan as vp

        pid = vp.create_plan(company_id, title="不关联客户")
        assert vp.get_plan(pid, company_id=company_id)["customer_id"] is None
