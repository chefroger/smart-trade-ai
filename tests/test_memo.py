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

    def test_five_failures_lock_then_expire(self, monkeypatch):
        from trade import memo

        memo.reset_throttle()
        base = memo.time.monotonic()
        for _ in range(memo.MAX_FAILURES):
            memo.register_failure()
        assert memo.lock_remaining() > 0
        # O-新28：运行中的锁走 monotonic —— 墙钟怎么跳都不影响；过 61 秒后解锁
        monkeypatch.setattr(memo.time, "monotonic", lambda: base + memo.LOCK_SECONDS + 1)
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

    def test_wall_clock_jump_does_not_change_lock(self, monkeypatch):
        """O-新28：锁定期内墙钟前拨/回拨，剩余秒数按 monotonic 走。"""
        from trade import memo

        memo.reset_throttle()
        for _ in range(memo.MAX_FAILURES):
            memo.register_failure()
        before = memo.lock_remaining()

        real_time = memo.time.time
        monkeypatch.setattr(memo.time, "time", lambda: real_time() + 3600)
        assert memo.lock_remaining() == before
        monkeypatch.setattr(memo.time, "time", lambda: real_time() - 3600)
        assert memo.lock_remaining() == before
        memo.reset_throttle()

    def test_lock_is_per_company(self):
        """O-新28：A 公司锁住不影响 B 公司。"""
        from trade import memo

        memo.reset_throttle()
        for _ in range(memo.MAX_FAILURES):
            memo.register_failure(company_id=1)
        assert memo.lock_remaining(1) > 0
        assert memo.lock_remaining(2) == 0
        memo.reset_throttle()

    def test_throttle_survives_restart(self, monkeypatch, tmp_path):
        """S8/O-新28：状态写进 memo_throttle.json，重启不清零。"""
        import importlib
        import json

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        from trade import memo

        memo.reset_throttle()
        for _ in range(memo.MAX_FAILURES):
            memo.register_failure()
        assert memo.lock_remaining() > 0

        data = json.loads(memo.throttle_path().read_text(encoding="utf-8"))
        assert data["global"]["until"] > 0
        assert "failures" in data["global"]

        # 模拟应用重启：重新加载模块，状态只能来自磁盘。
        # 其他测试可能把 trade.memo 从 sys.modules 里移除过（test_isolation），
        # reload 前先确保它已注册。
        import sys

        monkeypatch.setitem(sys.modules, "trade.memo", memo)
        reloaded = importlib.reload(memo)
        assert reloaded.lock_remaining() > 0
        # 重启水合把剩余夹到 ≤ LOCK_SECONDS（时钟回拨不会锁一年）
        assert reloaded.lock_remaining() <= reloaded.LOCK_SECONDS
        reloaded.reset_throttle()


class TestLegacyMemoThrottleMigration:
    """O-新30：旧版 memo.json 中的 throttle_failures / throttle_until 迁移到 memo_throttle.json。"""

    def test_legacy_active_lock_migrates_to_global_bucket_and_cleans_memo_json(
        self, monkeypatch, tmp_path
    ):
        import json
        import time

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        from trade import memo

        memo.configure("pass1234")
        cfg = json.loads(memo.memo_config_path().read_text(encoding="utf-8"))
        cfg["throttle_failures"] = 0
        cfg["throttle_until"] = time.time() + 45
        memo.memo_config_path().write_text(json.dumps(cfg), encoding="utf-8")

        # 升级后首次查询锁定状态：有效锁不静默清零（含带 company_id 的端点调用）
        rem_global = memo.lock_remaining()
        assert 0 < rem_global <= memo.LOCK_SECONDS
        assert memo.lock_remaining(company_id=7) > 0

        # 旧字段已搬入 memo_throttle.json 的 global 桶
        throttle_data = json.loads(memo.throttle_path().read_text(encoding="utf-8"))
        assert throttle_data["global"]["until"] > time.time()

        # memo.json 不再残留死字段，原有密语配置完整保留
        cleaned = json.loads(memo.memo_config_path().read_text(encoding="utf-8"))
        assert "throttle_failures" not in cleaned
        assert "throttle_until" not in cleaned
        assert cleaned["salt"] == cfg["salt"]
        assert cleaned["hash"] == cfg["hash"]
        assert memo.verify("pass1234") is True
        memo.reset_throttle()

    def test_legacy_failure_count_migrates_and_continues_counting(
        self, monkeypatch, tmp_path
    ):
        import json

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        from trade import memo

        memo.configure("pass1234")
        cfg = json.loads(memo.memo_config_path().read_text(encoding="utf-8"))
        cfg["throttle_failures"] = memo.MAX_FAILURES - 1
        cfg["throttle_until"] = 0
        memo.memo_config_path().write_text(json.dumps(cfg), encoding="utf-8")

        # 再错 1 次即达到 MAX_FAILURES 并触发锁定
        memo.register_failure()
        assert memo.lock_remaining() > 0

        cleaned = json.loads(memo.memo_config_path().read_text(encoding="utf-8"))
        assert "throttle_failures" not in cleaned
        assert "throttle_until" not in cleaned
        memo.reset_throttle()

    def test_legacy_expired_lock_is_cleaned_without_locking(self, monkeypatch, tmp_path):
        import json
        import time

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        from trade import memo

        memo.configure("pass1234")
        cfg = json.loads(memo.memo_config_path().read_text(encoding="utf-8"))
        cfg["throttle_failures"] = 0
        cfg["throttle_until"] = time.time() - 120
        memo.memo_config_path().write_text(json.dumps(cfg), encoding="utf-8")

        assert memo.lock_remaining() == 0
        cleaned = json.loads(memo.memo_config_path().read_text(encoding="utf-8"))
        assert "throttle_failures" not in cleaned
        assert "throttle_until" not in cleaned
        memo.reset_throttle()

    def test_legacy_far_future_lock_is_clamped_to_lock_seconds(self, monkeypatch, tmp_path):
        import json
        import time

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        from trade import memo

        memo.configure("pass1234")
        cfg = json.loads(memo.memo_config_path().read_text(encoding="utf-8"))
        cfg["throttle_failures"] = 0
        cfg["throttle_until"] = time.time() + 999_999
        memo.memo_config_path().write_text(json.dumps(cfg), encoding="utf-8")

        rem = memo.lock_remaining()
        assert 0 < rem <= memo.LOCK_SECONDS
        memo.reset_throttle()

    def test_set_unlock_mode_also_cleans_legacy_throttle_keys(self, monkeypatch, tmp_path):
        import json
        import time

        monkeypatch.setenv("TRADE_HOME", str(tmp_path))
        from trade import memo

        memo.configure("pass1234")
        cfg = json.loads(memo.memo_config_path().read_text(encoding="utf-8"))
        cfg["throttle_failures"] = 2
        cfg["throttle_until"] = time.time() + 30
        memo.memo_config_path().write_text(json.dumps(cfg), encoding="utf-8")

        assert memo.set_unlock_mode("session") == "session"
        cleaned = json.loads(memo.memo_config_path().read_text(encoding="utf-8"))
        assert cleaned["unlock_mode"] == "session"
        assert "throttle_failures" not in cleaned
        assert "throttle_until" not in cleaned
        assert memo.lock_remaining() > 0
        memo.reset_throttle()
