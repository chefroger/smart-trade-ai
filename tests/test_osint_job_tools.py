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
from trade.agent_context import bind_company  # noqa: E402
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
        deadline = time.time() + 5
        while time.time() < deadline:
            if osint_jobs.get_job(companies["first"], started["job_id"])["status"] in osint_jobs.TERMINAL:
                break
            time.sleep(0.02)

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

        monkeypatch.delenv("TRADE_HOST", raising=False)
        importlib.reload(plugin)
        names = {name for name, *_ in plugin._TOOLS}
        assert "osint_job_start" not in names
