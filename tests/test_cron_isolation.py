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

    def test_wrong_date_returns_none(self, env):
        today = "2026-10-26"
        d = env["output_dir"] / "job-a"
        d.mkdir()
        (d / "2020-01-01_09-00-00.md").write_text("A 输出", encoding="utf-8")

        assert env["cron"]._find_cron_output("A 的任务", today, job_id="job-a") is None

    def test_decoy_without_job_id_returns_none(self, env):
        """没有 job_id（内置任务）时不许按正文子串猜完成。"""
        today = "2026-10-26"
        d = env["output_dir"] / "job-b"
        d.mkdir()
        (d / f"{today}_09-00-00.md").write_text(
            "B 输出提到 A 的任务", encoding="utf-8"
        )

        assert env["cron"]._find_cron_output("A 的任务", today) is None
        assert env["cron"]._find_cron_output("A 的任务", today, job_id="job-a") is None


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

    def test_remove_by_name_unbinds_via_result_id(self, env, monkeypatch):
        """按任务名删除时从返回 JSON 的 removed_job.id 解绑真实 ID。"""
        import trade.cron_binding as cb

        cb.bind_job("job-a", env["a"]["id"])
        monkeypatch.setattr(cb, "_current_company_id", lambda: env["a"]["id"])
        cb.on_post_tool_call(
            tool_name="cronjob_manage",
            args={"action": "remove", "job_id": "A 的任务"},
            result=json.dumps({"success": True, "removed_job": {"id": "job-a"}}),
        )
        assert cb.job_company("job-a") is None


class TestHermesCronOutputAndInference:
    """验证 Prompt 归属推断、已启用过滤、Hermes 包装头剥离及历史产出回显。"""

    def test_infer_company_from_prompt_and_filter_disabled(self, env):
        import trade.cron_binding as cb

        cid_a = env["a"]["id"]
        cid_b = env["b"]["id"]
        env["jobs_file"].write_text(json.dumps({"jobs": [
            {
                "id": "job-morning",
                "name": "🌅 早安简报",
                "enabled": True,
                "schedule": {"expr": "0 9 * * 1-5", "display": "0 9 * * 1-5"},
                "prompt": f"当前公司：公司A（company_id={cid_a}）。生成今日简报。",
            },
            {
                "id": "job-linkedin",
                "name": "🔍 精准加人",
                "enabled": True,
                "schedule": {"expr": "0 10 * * 1-5", "display": "0 10 * * 1-5"},
                "prompt": f"当前公司：公司A（company_id={cid_a}）。生成加人计划。",
            },
            {
                "id": "job-paused",
                "name": "📋 每周复盘",
                "enabled": False,
                "schedule": {"expr": "30 17 * * 5", "display": "30 17 * * 5"},
                "prompt": f"当前公司：公司A（company_id={cid_a}）。生成周报。",
            },
        ]}, ensure_ascii=False), encoding="utf-8")

        from datetime import date

        today = date.today().isoformat()
        # job-morning 今日已产出（带 Hermes 标准包装头）
        d1 = env["output_dir"] / "job-morning"
        d1.mkdir()
        (d1 / f"{today}_09-04-14.md").write_text(
            "# Cron Job: 🌅 早安简报\n\n"
            "**Job ID:** job-morning\n"
            f"**Run Time:** {today} 09:04:13\n\n"
            "**Prompt Characters:** 120\n"
            "## Prompt\n\n[IMPORTANT: system header]\n\n"
            "**Response Characters:** 42\n"
            "## Response\n\n"
            "# 🌅 早安简报\n\n美元 USD **6.7088**\n",
            encoding="utf-8",
        )
        # job-linkedin 只有历史产出，今日尚未到点
        d2 = env["output_dir"] / "job-linkedin"
        d2.mkdir()
        (d2 / "2026-11-25_10-07-03.md").write_text(
            "# Cron Job: 🔍 精准加人\n\n**Job ID:** job-linkedin\n\n"
            "## Prompt\n\nprompt body\n\n## Response\n\nLinkedIn 今日搜索方案\n",
            encoding="utf-8",
        )

        # 公司 A 能看到自己激活的 2 个任务（已暂停的不进入 active_items）
        res_a = env["cron"].get_today_cron(cid_a)
        active_a = res_a["active_items"]
        assert [x["job_id"] for x in active_a] == ["job-morning", "job-linkedin"]
        assert active_a[0]["is_today"] is True
        assert "美元 USD" in active_a[0]["output"]
        assert "[IMPORTANT:" not in active_a[0]["output"]
        assert active_a[1]["is_today"] is False
        assert active_a[1]["run_at"] == "2026-11-25 10:07"
        assert "LinkedIn 今日搜索方案" in active_a[1]["output"]

        # 归属已自动回填至 cron_job_companies，公司 B 看不到公司 A 的任务和产出
        assert cb.job_company("job-morning") == cid_a
        res_b = env["cron"].get_today_cron(cid_b)
        assert res_b["active_items"] == []

        # 单任务输出详情端点：公司 A 可读，公司 B 返回 404
        detail = env["cron"].get_cron_job_output("job-linkedin", cid_a)
        assert detail["output"] == "LinkedIn 今日搜索方案"
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            env["cron"].get_cron_job_output("job-linkedin", cid_b)
        assert exc.value.status_code == 404
