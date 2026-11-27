"""P1-1：agent 工具 osint_job_start / osint_job_result。"""

from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import osint_jobs  # noqa: E402
from trade.agent_context import bind_company, bind_tool_evidence  # noqa: E402
from trade.hermes_chat_memory_plugin import tools  # noqa: E402


@pytest.fixture
def companies(monkeypatch, tmp_path):
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
    return {
        "first": co.create(name="Tool Co", slug="tool-co")["id"],
        "second": co.create(name="Tool Other", slug="tool-other")["id"],
    }


@pytest.fixture
def fake_orchestrator(monkeypatch):
    async def _fake(target, budget=0, on_event=None, **_kw):
        if on_event:
            on_event({"event": "source_done", "source": "rdap", "status": "hit", "ms": 5})
        return {"target": target, "overall_rating": "low"}

    import trade.osint.orchestrator as orch

    monkeypatch.setattr(orch, "osint_full_check", _fake)


class TestHandlers:
    def test_start_and_read_result(self, companies, fake_orchestrator):
        with bind_company(companies["first"]):
            started = json.loads(tools.handle_osint_job_start({"target": "acme.com"}))
            assert started["job_id"] and started["status"] in ("queued", "running")

            deadline = time.time() + 5
            payload = {}
            while time.time() < deadline:
                payload = json.loads(tools.handle_osint_job_result({"job_id": started["job_id"]}))
                if payload["job"]["status"] == "done":
                    break
                time.sleep(0.02)

        assert payload["job"]["status"] == "done"
        assert payload["job"]["report"]["overall_rating"] == "low"
        assert any(event["type"] == "source_done" for event in payload["events"])

    def test_start_requires_bound_company(self, companies):
        result = json.loads(tools.handle_osint_job_start({"target": "acme.com"}))
        assert "error" in result

    def test_other_company_cannot_read(self, companies, fake_orchestrator):
        with bind_company(companies["first"]):
            started = json.loads(tools.handle_osint_job_start({"target": "acme.com"}))

        with bind_company(companies["second"]):
            result = json.loads(tools.handle_osint_job_result({"job_id": started["job_id"]}))
        assert "error" in result

        # 等任务收尾，避免线程活过本用例的临时库
        deadline = time.time() + 15
        while time.time() < deadline:
            if osint_jobs.get_job(companies["first"], started["job_id"])["status"] in osint_jobs.TERMINAL:
                break
            time.sleep(0.02)
        else:
            pytest.fail("后台任务 15s 内未到终态，后续用例可能抢锁（W15 O-27）")

    def test_missing_target(self, companies):
        with bind_company(companies["first"]):
            result = json.loads(tools.handle_osint_job_start({"target": " "}))
        assert "error" in result


class TestRegistrationGate:
    def test_tools_registered_only_in_trade_host(self, monkeypatch):
        plugin = importlib.import_module("trade.hermes_chat_memory_plugin")

        monkeypatch.setenv("TRADE_HOST", "1")
        importlib.reload(plugin)
        names = {name for name, *_ in plugin._TOOLS}
        assert {"osint_job_start", "osint_job_result"} <= names
        assert {"osint_fact_save", "osint_fact_list"} <= names

        monkeypatch.delenv("TRADE_HOST", raising=False)
        importlib.reload(plugin)
        names = {name for name, *_ in plugin._TOOLS}
        assert "osint_job_start" not in names
        assert "osint_fact_save" not in names


class TestFactTools:
    """事实库工具：查到就登记，下次同目标复用；不同值标冲突。"""

    def test_save_and_read_back(self, companies):
        with bind_company(companies["first"]), bind_tool_evidence(
            lambda: ("fetch https://example.com/x",),
        ):
            saved = json.loads(tools.handle_osint_fact_save({
                "target": "天津赛得进出口有限公司",
                "field": "注册资本",
                "value": "100万元人民币",
                "source_url": "https://example.com/x",
                "source_name": "企查查",
            }))
            assert saved["saved"] is True

            listed = json.loads(tools.handle_osint_fact_list({"target": "天津赛得进出口有限公司"}))
        assert listed["known_facts"]["注册资本"]["values"] == ["100万元人民币"]
        assert listed["known_facts"]["注册资本"]["conflict"] is False
        assert listed["conflicts"] == []

    def test_conflicting_values_are_flagged(self, companies):
        with bind_company(companies["first"]), bind_tool_evidence(
            lambda: ("https://a.example/company", "https://b.example/company"),
        ):
            tools.handle_osint_fact_save({
                "target": "acme.com", "field": "员工人数",
                "value": "8", "source_url": "https://a.example/company",
                "source_name": "平台A",
            })
            tools.handle_osint_fact_save({
                "target": "acme.com", "field": "员工人数",
                "value": "25", "source_url": "https://b.example/company",
                "source_name": "平台B",
            })
            listed = json.loads(tools.handle_osint_fact_list({"target": "acme.com"}))
        assert listed["known_facts"]["员工人数"]["conflict"] is True
        assert sorted(listed["known_facts"]["员工人数"]["values"]) == ["25", "8"]
        assert listed["conflicts"] == ["员工人数"]

    def test_known_facts_returned_by_job_start(self, companies, fake_orchestrator):
        """同目标第二次背调：osint_job_start 直接带回已知事实。"""
        with bind_company(companies["first"]), bind_tool_evidence(lambda: ()):
            # 无来源 URL：即使直接登记也属于「未核实」
            tools.handle_osint_fact_save({
                "target": "acme.com", "field": "法定代表人", "value": "张三",
            })
            started = json.loads(tools.handle_osint_job_start({"target": "acme.com"}))
            # 等任务结束再离开：后台线程继续跑会与下一个用例的 init_db 抢锁
            deadline = time.time() + 15
            while time.time() < deadline:
                payload = json.loads(tools.handle_osint_job_result(
                    {"job_id": started["job_id"]},
                ))
                if payload["job"]["status"] in ("done", "failed", "cancelled", "partial"):
                    break
                time.sleep(0.02)
            else:
                pytest.fail("后台任务 15s 内未结束，后续用例可能抢锁（W15 O-27）")
        assert started["known_facts"] == {}
        assert started["unverified_facts"]["法定代表人"]["values"] == ["张三"]
        assert started["unverified_facts"]["法定代表人"]["note"] == "上次未能核实"

    def test_verified_fact_is_reused(self, companies, fake_orchestrator):
        """来源 URL 在本轮工具证据里出现 → verified，下次直接复用。"""
        with bind_company(companies["first"]), bind_tool_evidence(
            lambda: ("fetch https://cr.example/acme",),
        ):
            tools.handle_osint_fact_save({
                "target": "acme.com", "field": "注册资本", "value": "100万",
                "source_url": "https://cr.example/acme",
            })
        with bind_company(companies["first"]), bind_tool_evidence(lambda: ()):
            started = json.loads(tools.handle_osint_job_start({"target": "acme.com"}))
        assert started["known_facts"]["注册资本"]["values"] == ["100万"]

        deadline = time.time() + 15
        while time.time() < deadline:
            if osint_jobs.get_job(companies["first"], started["job_id"])["status"] in osint_jobs.TERMINAL:
                break
            time.sleep(0.02)
        else:
            pytest.fail("后台任务 15s 内未到终态，后续用例可能抢锁（W15 O-27）")

    def test_facts_are_company_scoped(self, companies):
        with bind_company(companies["first"]):
            tools.handle_osint_fact_save({
                "target": "acme.com", "field": "注册资本", "value": "100万",
            })
        with bind_company(companies["second"]):
            listed = json.loads(tools.handle_osint_fact_list({"target": "acme.com"}))
        assert listed["known_facts"] == {}

    def test_save_requires_bound_company(self, companies):
        result = json.loads(tools.handle_osint_fact_save({
            "target": "acme.com", "field": "注册资本", "value": "100万",
        }))
        assert "error" in result

    def test_save_rejects_empty_fields(self, companies):
        with bind_company(companies["first"]):
            result = json.loads(tools.handle_osint_fact_save({
                "target": "acme.com", "field": "", "value": "x",
            }))
        assert "error" in result


def test_source_url_verified_is_exact_not_substring(monkeypatch):
    """W15 O-4：参数里嵌套的 URL 不能让子串匹配误判为已核实。"""
    import trade.agent_context as ac
    from trade.hermes_chat_memory_plugin import tools

    nested = "https://evil.test/?u=https://cr.example/acme"
    monkeypatch.setattr(ac, "current_tool_evidence", lambda: (nested,))
    assert tools._source_url_verified("https://cr.example/acme") is False
    assert tools._source_url_verified(nested) is True


class TestStartJobRealOrchestrator:
    """P0 回归：start_job 走真实 osint_full_check，不因 asyncio.wait 收协程而失败，且运行中同目标复用。"""

    def test_start_job_real_orchestrator_and_reuses_running_job(self, companies, monkeypatch):
        """真实 osint_full_check 跑通；仍在 running 时第二次同目标 start 返回 reused。"""
        import threading

        import trade.osint.orchestrator as orch

        monkeypatch.setenv("TRADE_OSINT_SOURCES", "off")
        gate = threading.Event()
        entered = threading.Event()

        def _slow_whois(domain):  # noqa: ARG001
            entered.set()
            gate.wait(timeout=5.0)
            return {
                "domain": "acme.com",
                "registered": True,
                "creation_date": "2015-01-01T00:00:00Z",
                "days_old": 4000,
                "age_category": "old",
                "error": None,
            }

        monkeypatch.setattr(orch, "domain_whois", _slow_whois)
        monkeypatch.setattr(
            orch,
            "detect_tech_stack",
            lambda url: {"technologies": ["nginx"], "is_free_platform": False, "is_enterprise": True, "error": None},
        )
        monkeypatch.setattr(
            orch,
            "check_sanctions",
            lambda name, country=None: {
                "is_sanctioned": False,
                "risk_level": "none",
                "hits": [],
                "coverage": {"degraded": False, "total_entries": 30000},
            },
        )
        monkeypatch.setattr(orch, "_resolve_entity_name", lambda domain, **kw: None)

        with bind_company(companies["first"]):
            first = json.loads(tools.handle_osint_job_start({"target": "acme.com"}))
            assert first["reused"] is False
            assert entered.wait(timeout=3.0), "后台任务未真正进入采集层（可能已提前崩溃）"

            second = json.loads(tools.handle_osint_job_start({"target": "acme.com"}))
            assert second["reused"] is True
            assert second["job_id"] == first["job_id"]

            gate.set()

            deadline = time.time() + 10
            payload = {}
            while time.time() < deadline:
                payload = json.loads(tools.handle_osint_job_result({"job_id": first["job_id"]}))
                if payload["job"]["status"] in osint_jobs.TERMINAL:
                    break
                time.sleep(0.02)

        assert payload["job"]["status"] in ("done", "partial"), payload
        assert not any(
            "Passing coroutines is forbidden" in json.dumps(ev, ensure_ascii=False)
            for ev in payload["events"]
        )

