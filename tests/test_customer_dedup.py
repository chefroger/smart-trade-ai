"""客户去重 + 数据完整度评分 + 简报 + 健康审计 测试。

使用临时数据库，不触碰真实用户数据。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def test_db(monkeypatch, tmp_path):
    """创建临时数据库并初始化 schema，mock 掉 _get_db_path 和桌面工作目录。"""
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
    """在临时数据库中创建一个测试公司，返回公司 ID。"""
    from trade import company
    c = company.create("Test Company")
    return c["id"]


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestComputeDataCompleteness:
    """测试 compute_data_completeness() — 数据完整度评分。"""

    def test_empty_customer(self):
        """空客户数据应返回 score 0。"""
        from trade.customer import compute_data_completeness
        result = compute_data_completeness({})
        assert result["score"] == 0
        assert result["filled_count"] == 0
        assert len(result["missing_fields"]) == result["total_fields"]

    def test_full_customer(self):
        """完整客户数据应返回 score 100。"""
        from trade.customer import compute_data_completeness
        cust = {
            "extra1": json.dumps({
                "country": "US", "tier": "A", "linkedin_url": "https://linkedin.com/in/example",
                "company_website": "https://example.com", "social_media": {"twitter": "@ex"},
                "buyer_type": "品牌商", "main_category": "电力金具", "match_score": 4,
            }),
            "extra2": json.dumps({
                "title": "CEO", "email": "ceo@example.com", "backup_email": "backup@ex.com",
                "phone": "+1-555-1234", "whatsapp": "+1-555-1234", "wechat": "wxid123",
                "source": "展会", "follow_up_note": "下周跟进",
            }),
        }
        result = compute_data_completeness(cust)
        assert result["score"] == 100, (
            f"Expected 100, got {result['score']}, missing: {result['missing_fields']}"
        )
        assert result["filled_count"] == result["total_fields"]

    def test_partial_customer(self):
        """部分字段应有合理的中间分数。"""
        from trade.customer import compute_data_completeness
        cust = {
            "extra1": json.dumps({"country": "US", "company_website": "https://example.com"}),
            "extra2": json.dumps({"email": "ceo@example.com"}),
        }
        result = compute_data_completeness(cust)
        assert 0 < result["score"] < 100
        assert result["filled_count"] < result["total_fields"]


class TestFindDuplicates:
    """测试 find_duplicates() — 重复客户检测。"""

    def test_no_duplicates(self, test_db, company_id):
        """不同客户应返回空列表。"""
        from trade.customer import create, find_duplicates
        create("A Corp", email="a@x.com", company_website="a.com", company_id=company_id)
        create("B Ltd", email="b@x.com", company_website="b.com", company_id=company_id)
        result = find_duplicates(company_id)
        assert result == []

    def test_email_match(self, test_db, company_id):
        """相同 email 应被检测为重复。"""
        from trade.customer import create, find_duplicates
        create("A Corp", email="same@x.com", company_website="a.com", company_id=company_id)
        create("B Ltd", email="same@x.com", company_website="b.com", company_id=company_id)
        result = find_duplicates(company_id)
        assert len(result) == 1
        assert result[0]["reason"] == "email_match"
        assert result[0]["detail"] == "same@x.com"
        assert len(result[0]["customers"]) == 2

    def test_website_match(self, test_db, company_id):
        """相同 website（标准化后）应被检测为重复。"""
        from trade.customer import create, find_duplicates
        create("A Corp", email="a@x.com", company_website="https://www.example.com/", company_id=company_id)
        create("B Ltd", email="b@x.com", company_website="http://example.com", company_id=company_id)
        result = find_duplicates(company_id)
        assert len(result) == 1
        assert result[0]["reason"] == "website_match"
        assert len(result[0]["customers"]) == 2


class TestBulkSaveDedup:
    """测试 bulk_save() email/website 去重。"""

    def test_skips_email_duplicate(self, test_db, company_id):
        """bulk_save 应跳过 email 相同的客户。"""
        from trade.customer import bulk_save, create
        create("Existing", email="dup@x.com", company_id=company_id)
        result = bulk_save(company_id, [
            {"name": "New One", "email": "dup@x.com"},
        ])
        assert result["skipped"] == 1
        assert result["created"] == 0

    def test_skips_website_duplicate(self, test_db, company_id):
        """bulk_save 应跳过 website 相同的客户（精确匹配）。"""
        from trade.customer import bulk_save, create
        create("Existing", company_website="dup.com", company_id=company_id)
        result = bulk_save(company_id, [
            {"name": "New One", "company_website": "dup.com"},
        ])
        assert result["skipped"] == 1
        assert result["created"] == 0


class TestCreateDedupWarning:
    """测试 create() 软去重警告。"""

    def test_warns_on_email_duplicate(self, test_db, company_id):
        """相同 email 创建第二个客户时应返回 duplicate_warning。"""
        from trade.customer import create
        create("First", email="dup@x.com", company_id=company_id)
        result = create("Second", email="dup@x.com", company_id=company_id)
        assert result.get("duplicate_warning") == "email_already_exists"

    def test_warns_on_website_duplicate(self, test_db, company_id):
        """相同 website（含协议/www 差异）创建第二个客户时应返回 duplicate_warning。"""
        from trade.customer import create
        create("First", company_website="https://www.dup.com/", company_id=company_id)
        result = create("Second", company_website="http://dup.com", company_id=company_id)
        assert result.get("duplicate_warning") == "website_already_exists"

    def test_no_warning_unique(self, test_db, company_id):
        """唯一客户不应有警告。"""
        from trade.customer import create
        result = create("Unique", email="u@x.com", company_id=company_id)
        assert "duplicate_warning" not in result


class TestBuildBriefing:
    """测试 build_briefing() — AI 客户简报。"""

    def test_empty_customer(self, test_db, company_id):
        """不存在客户返回空字符串。"""
        from trade.customer import build_briefing
        result = build_briefing(99999, company_id=company_id)
        assert result == ""

    def test_includes_identity_and_contact(self, test_db, company_id):
        """简报应包含身份和联系方式。"""
        from trade.customer import build_briefing, create
        cust = create(
            "Test Corp", contact="John", company_id=company_id,
            country="US", tier="A", title="CEO", buyer_type="品牌商",
            email="john@test.com", phone="+1-555-0001",
        )
        result = build_briefing(cust["id"], company_id=company_id)
        assert "Test Corp" in result
        assert "john@test.com" in result
        assert "品牌商" in result

    def test_shows_identity_section(self, test_db, company_id):
        """简报应有身份段标题。"""
        from trade.customer import build_briefing, create
        cust = create("Sparse Co", company_id=company_id)
        result = build_briefing(cust["id"], company_id=company_id)
        assert "## 客户简报" in result


class TestHealthAudit:
    """测试 health_audit() — 客户健康审计。"""

    def test_empty_company(self, test_db, company_id):
        """空公司应返回空列表和零计数。"""
        from trade.customer import health_audit
        result = health_audit(company_id)
        assert result["summary"]["total_customers"] == 0
        assert result["summary"]["stale_count"] == 0

    def test_detects_incomplete_customer(self, test_db, company_id):
        """数据极少的客户应出现在 incomplete_data 中。"""
        from trade.customer import create, health_audit
        create("Sparse", company_id=company_id)  # 只有 name，完整度极低
        result = health_audit(company_id)
        assert result["summary"]["incomplete_count"] >= 1

    def test_detects_high_value_unconverted(self, test_db, company_id):
        """A 级客户无订单应在 high_value_unconverted 中。"""
        from trade.customer import create, health_audit
        create("VIP", tier="A", country="US", company_id=company_id)
        result = health_audit(company_id)
        assert result["summary"]["high_value_unconverted_count"] >= 1

    def test_recent_conversation_prevents_stale_false_positive(self, test_db, company_id):
        """老客户只要近期有对话/邮件沟通，不应被误判为 90 天僵尸客户。"""
        from trade import chat_memory
        from trade.customer import create, health_audit

        cust = create("Active Old Co", company_id=company_id)
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "UPDATE customers SET updated_at = '2020-01-01 00:00:00' WHERE id = ?",
            (cust["id"],),
        )
        conn.commit()
        conn.close()
        chat_memory.save_with_context(
            company_id=company_id,
            query="最新报价咨询",
            response="已回复",
            customer_id=cust["id"],
            retain_to_memory=False,
        )
        result = health_audit(company_id)
        stale_ids = [c["id"] for c in result["stale_customers"]]
        assert cust["id"] not in stale_ids
