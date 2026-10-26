"""Cron 任务按公司隔离（审计 P1-17）。

Hermes 的 jobs.json 没有公司字段；Trade 用插件钩子记录 job_id→公司，
cron 端点据此过滤，并按 job_id 精确读取输出目录（不再按任务名子串匹配）。
"""

from __future__ import annotations

import json
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
    a = co.create(name="公司A", slug="co-a")
    b = co.create(name="公司B", slug="co-b")

    import trade.api.cron as cron

    jobs_file = tmp_path / "jobs.json"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    jobs_file.write_text(json.dumps({"jobs": [
        {"id": "job-a", "name": "A 的任务", "schedule": {"display": "0 9 * * *"}},
        {"id": "job-b", "name": "B 的任务", "schedule": {"display": "0 10 * * *"}},
        {"id": "job-legacy", "name": "旧任务", "schedule": {"display": "0 11 * * *"}},
    ]}), encoding="utf-8")
    monkeypatch.setattr(cron, "_JOBS_FILE", jobs_file)
    monkeypatch.setattr(cron, "_CRON_OUTPUT", output_dir)

    return {"a": a, "b": b, "cron": cron, "output_dir": output_dir, "jobs_file": jobs_file}


class TestBinding:
    def test_bind_lookup_unbind(self, env):
        import trade.cron_binding as cb

        cb.bind_job("job-a", env["a"]["id"])
        assert cb.job_company("job-a") == env["a"]["id"]

        cb.bind_job("job-a", env["b"]["id"])
        assert cb.job_company("job-a") == env["b"]["id"]

        cb.unbind_job("job-a")
        assert cb.job_company("job-a") is None

    def test_visible_rules(self, env):
        import trade.cron_binding as cb

        cb.bind_job("job-a", env["a"]["id"])
        assert cb.visible_for_company("job-a", env["a"]["id"], company_count=2)
        assert not cb.visible_for_company("job-a", env["b"]["id"], company_count=2)
        # 未绑定：多公司隐藏，单公司展示
        assert not cb.visible_for_company("job-legacy", env["a"]["id"], company_count=2)
        assert cb.visible_for_company("job-legacy", env["a"]["id"], company_count=1)


class TestCronApiFiltering:
    def test_each_company_sees_only_its_jobs(self, env):
        import trade.cron_binding as cb

        cb.bind_job("job-a", env["a"]["id"])
        cb.bind_job("job-b", env["b"]["id"])

        names_a = [j["name"] for j in env["cron"].get_active_jobs(env["a"]["id"])]
        names_b = [j["name"] for j in env["cron"].get_active_jobs(env["b"]["id"])]

        assert names_a == ["A 的任务"]
        assert names_b == ["B 的任务"]

    def test_legacy_job_hidden_when_multiple_companies(self, env):
        import trade.cron_binding as cb

        cb.bind_job("job-a", env["a"]["id"])
        cb.bind_job("job-b", env["b"]["id"])

        names = [j["name"] for j in env["cron"].get_active_jobs(env["a"]["id"])]
        assert "旧任务" not in names


class TestOutputByJobId:
    def test_reads_only_that_jobs_directory(self, env):
        today = "2026-10-26"
        for job_id, content in (("job-a", "A 输出"), ("job-b", "B 输出")):
            d = env["output_dir"] / job_id
            d.mkdir()
            (d / f"{today}_09-00-00.md").write_text(content, encoding="utf-8")

        # 两个输出里都提到任务名，旧实现会串；按 job_id 只读自己那一份
        got = env["cron"]._find_cron_output("A 的任务", today, job_id="job-a")
        assert got == "A 输出"

    def test_missing_job_dir_returns_none(self, env):
        assert env["cron"]._find_cron_output("X", "2026-10-26", job_id="nope") is None


class TestHooks:
    def test_create_binds_job_to_current_company(self, env, monkeypatch):
        import trade.cron_binding as cb
        from trade.agent_context import bind_company

        monkeypatch.setattr(cb, "_current_company_id", lambda: env["a"]["id"])
        result = json.dumps({"success": True, "job_id": "job-new", "name": "新任务"})

        with bind_company(env["a"]["id"]):
            cb.on_post_tool_call(
                tool_name="cronjob_manage",
                args={"action": "create", "schedule": "0 9 * * *"},
                result=result,
            )

        assert cb.job_company("job-new") == env["a"]["id"]

    def test_cross_company_update_blocked(self, env, monkeypatch):
        import trade.cron_binding as cb

        cb.bind_job("job-a", env["a"]["id"])
        monkeypatch.setattr(cb, "_current_company_id", lambda: env["b"]["id"])
        verdict = cb.on_pre_tool_call(
            "cronjob_manage", {"action": "remove", "job_id": "job-a"},
        )
        assert verdict and verdict["action"] == "block"

    def test_same_company_or_unbound_allowed(self, env, monkeypatch):
        import trade.cron_binding as cb

        cb.bind_job("job-a", env["a"]["id"])
        monkeypatch.setattr(cb, "_current_company_id", lambda: env["a"]["id"])
        assert cb.on_pre_tool_call(
            "cronjob_manage", {"action": "run", "job_id": "job-a"},
        ) is None
        assert cb.on_pre_tool_call(
            "cronjob_manage", {"action": "run", "job_id": "job-unbound"},
        ) is None

    def test_remove_unbinds(self, env, monkeypatch):
        import trade.cron_binding as cb

        cb.bind_job("job-a", env["a"]["id"])
        monkeypatch.setattr(cb, "_current_company_id", lambda: env["a"]["id"])
        cb.on_post_tool_call(
            tool_name="cronjob_manage",
            args={"action": "remove", "job_id": "job-a"},
            result="{}",
        )
        assert cb.job_company("job-a") is None
