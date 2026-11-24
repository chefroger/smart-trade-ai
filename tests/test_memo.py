"""P1-F：私密备忘录（家庭 facts + 客户索要，密语保护）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def env(monkeypatch, tmp_path):
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
    company = co.create(name="Memo Co", slug="memo-co")
    from trade import customer

    cust = customer.create(company_id=company["id"], name="Acme")
    return company["id"], cust["id"]


class TestPassphrase:
    def test_configure_and_verify(self, env, monkeypatch, tmp_path):
        from trade import memo

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        assert memo.is_configured() is False
        memo.configure("open sesame")
        assert memo.is_configured() is True
        assert memo.verify("open sesame") is True
        assert memo.verify("wrong") is False

    def test_min_length_and_no_silent_overwrite(self, env, monkeypatch, tmp_path):
        from trade import memo

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        with pytest.raises(memo.MemoError):
            memo.configure("123")
        memo.configure("first-pass")
        with pytest.raises(memo.MemoError):
            memo.configure("second-pass")
        assert memo.verify("first-pass") is True

    def test_corrupt_config_fails_closed(self, env, monkeypatch, tmp_path):
        from trade import memo

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        path = memo.memo_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")
        assert memo.verify("anything") is False


class TestUnlockMode:
    """W13：密语策略（每次输入 / 本会话内有效），默认每次输入。"""

    def test_default_is_always(self, env, monkeypatch, tmp_path):
        from trade import memo

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        assert memo.unlock_mode() == "always"

    def test_set_session_persists_and_survives_reconfigure(self, env, monkeypatch, tmp_path):
        from trade import memo

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        assert memo.set_unlock_mode("session") == "session"
        assert memo.unlock_mode() == "session"
        memo.configure("open sesame")
        assert memo.unlock_mode() == "session", "配置密语不能重置策略"
        assert memo.verify("open sesame") is True

    def test_rejects_unknown_mode(self, env, monkeypatch, tmp_path):
        from trade import memo

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        with pytest.raises(memo.MemoError):
            memo.set_unlock_mode("forever")


class TestMemoItems:
    def _add_fact(self, company_id, customer_id, category, subject, content):
        from trade import profile

        return profile.create_fact_manual(
            customer_id, company_id=company_id, category=category,
            subject=subject, content=content,
        )

    def test_includes_family_and_mislabeled_family_terms(self, env):
        from trade import memo

        company_id, customer_id = env
        self._add_fact(company_id, customer_id, "家庭", "太太", "Maria")
        # 分类写成「重要日期」但含家庭称谓：也必须进备忘录
        self._add_fact(company_id, customer_id, "重要日期", "太太生日", "3 月 8 日")
        self._add_fact(company_id, customer_id, "喜好", "咖啡", "美式")

        items = memo.memo_items(company_id, customer_id)

        texts = " ".join((f.get("subject") or "") + (f.get("content") or "") for f in items["facts"])
        assert "Maria" in texts and "3 月 8 日" in texts
        assert "咖啡" not in texts

    def test_includes_gift_requests_only(self, env):
        from trade import memo, profile

        company_id, customer_id = env
        profile.create_gift_manual(
            customer_id, company_id=company_id, direction="客户索要", item="两瓶茅台",
        )
        profile.create_gift_manual(
            customer_id, company_id=company_id, direction="我方赠送", item="茶叶",
        )
        items = memo.memo_items(company_id, customer_id)
        joined = " ".join(g["item"] for g in items["gift_requests"])
        assert "茅台" in joined and "茶叶" not in joined

    def test_company_isolation(self, env, monkeypatch, tmp_path):
        from trade import memo

        company_id, customer_id = env
        self._add_fact(company_id, customer_id, "家庭", "太太", "Maria")
        assert memo.memo_items(company_id + 999, customer_id)["facts"] == []

    def test_briefing_excludes_family_terms_even_if_mislabeled(self, env):
        from trade import profile

        company_id, customer_id = env
        self._add_fact(company_id, customer_id, "重要日期", "太太生日", "3 月 8 日")
        self._add_fact(company_id, customer_id, "喜好", "咖啡", "美式")

        text = profile.briefing_profile_section(customer_id, company_id=company_id)

        assert "太太" not in text and "3 月 8 日" not in text
        assert "咖啡" in text

    def test_visit_suggest_hides_but_counts(self, env):
        from trade import visit_plan

        company_id, customer_id = env
        self._add_fact(company_id, customer_id, "重要日期", "太太生日", "3 月 8 日")
        draft = visit_plan.suggest_draft(company_id, customer_id)
        assert "太太" not in draft["risks"]
        assert "3 月 8 日" not in draft["risks"]
        assert "1 条私密档案" in draft["risks"]

    def test_export_package_excludes_mislabeled_family(self, env, tmp_path):
        import json
        import zipfile

        from trade.company.transfer.exporter import export_company

        company_id, customer_id = env
        self._add_fact(company_id, customer_id, "重要日期", "太太生日", "3 月 8 日")
        self._add_fact(company_id, customer_id, "喜好", "咖啡", "美式")
        package = tmp_path / "export.zip"

        export_company(company_id, package)

        with zipfile.ZipFile(package) as zf:
            rows = json.loads(zf.read("db/customer_facts.json").decode("utf-8"))
        joined = " ".join((r.get("subject") or "") + (r.get("content") or "") for r in rows)
        assert "太太" not in joined and "3 月 8 日" not in joined
        assert "咖啡" in joined


def test_config_write_is_atomic(env, monkeypatch, tmp_path):
    """W15 O-19：写 memo.json 用临时文件 + os.replace，不留 .tmp 半成品。"""
    import json

    from trade import memo

    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    memo.configure("open sesame")
    path = memo.memo_config_path()
    assert path.is_file()
    assert not path.with_name(path.name + ".tmp").exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["salt"] and data["hash"]


class TestBackendThrottle:
    """O-新6：后端锁定，刷新前端页面不能绕过。"""

    def test_five_failures_lock_then_expire(self):
        from trade import memo

        memo.reset_throttle()
        for _ in range(memo.MAX_FAILURES):
            memo.register_failure()
        assert memo.lock_remaining() > 0
        # 模拟时间过去：把 lock_until 拨到过去，剩余应为 0
        memo._lock_until = 0.0
        assert memo.lock_remaining() == 0
        memo.reset_throttle()

    def test_success_resets_failure_count(self):
        from trade import memo

        memo.reset_throttle()
        for _ in range(memo.MAX_FAILURES - 1):
            memo.register_failure()
        memo.register_success()
        memo.register_failure()  # 计数已清零，不会立即锁
        assert memo.lock_remaining() == 0
        memo.reset_throttle()
