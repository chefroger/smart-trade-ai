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
