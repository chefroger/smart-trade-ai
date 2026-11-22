"""P1-1：背调后台任务（创建/去重/事件/取消/重启恢复）。"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import osint_jobs  # noqa: E402


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
    first = co.create(name="Job Co", slug="job-co")
    second = co.create(name="Other Co", slug="other-co")
    return {"first": first["id"], "second": second["id"]}


@pytest.fixture
def fake_orchestrator(monkeypatch):
    """替换确定性管线：快速发两条事件并返回报告。"""

    async def _fake(target, budget=0, on_event=None, **_kw):
        if on_event:
            on_event({"event": "source_start", "source": "rdap", "label": "RDAP"})
            await asyncio.sleep(0.02)
            on_event({"event": "source_done", "source": "rdap", "status": "hit", "ms": 20})
        return {
            "target": target,
            "overall_rating": "low",
            "overall_score": 80,
            "unverified": [],
        }

    import trade.osint.orchestrator as orch

    monkeypatch.setattr(orch, "osint_full_check", _fake)
    return _fake


def _wait(company_id: int, job_id: int, statuses: set[str], timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = osint_jobs.get_job(company_id, job_id)
        if job and job["status"] in statuses:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach {statuses}: {osint_jobs.get_job(company_id, job_id)}")


class TestCreateAndDedupe:
    def test_create_is_isolated_by_company(self, companies):
        job, created = osint_jobs.create_job(companies["first"], "acme.com")
        assert created is True
        assert osint_jobs.get_job(companies["second"], job["id"]) is None

    def test_same_target_reuses_job_within_window(self, companies):
        job, created = osint_jobs.create_job(companies["first"], "acme.com")
        again, created_again = osint_jobs.create_job(companies["first"], "ACME.com")
        assert created_again is False
        assert again["id"] == job["id"]

    def test_done_job_is_not_reused(self, companies):
        """2026-11-22：已完成任务不再被复用。

        复用 done 任务会让用户以为“又背调了一次”，实际看到的是旧结果，
        大动画也不会出现（界面跳过已完成任务）。只有排队/运行中的任务才复用。
        """
        from trade.database import get_connection

        job, _ = osint_jobs.create_job(companies["first"], "acme.com")
        conn = get_connection()
        try:
            conn.execute("UPDATE osint_jobs SET status='done' WHERE id=?", (job["id"],))
            conn.commit()
        finally:
            conn.close()

        again, created_again = osint_jobs.create_job(companies["first"], "ACME.com")
        assert created_again is True
        assert again["id"] != job["id"]

    def test_list_jobs_is_company_scoped(self, companies):
        job, _ = osint_jobs.create_job(companies["first"], "acme.com")
        mine = osint_jobs.list_jobs(companies["first"])
        assert [item["id"] for item in mine] == [job["id"]]
        assert osint_jobs.list_jobs(companies["second"]) == []
        assert "report" not in mine[0]


class TestRunner:
    def test_job_runs_to_done_with_events(self, companies, fake_orchestrator):
        job, _ = osint_jobs.create_job(companies["first"], "acme.com")
        osint_jobs.start_job(job["id"], "acme.com")

        finished = _wait(companies["first"], job["id"], {"done"})
        assert finished["report"]["overall_rating"] == "low"

        events = osint_jobs.list_events(job["id"])
        types = [event["type"] for event in events]
        assert "job_start" in types
        assert "source_start" in types and "source_done" in types
        assert "verdict" in types
        seqs = [event["seq"] for event in events]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

        # 续传：after 只拿后面的
        tail = osint_jobs.list_events(job["id"], after_seq=seqs[0])
        assert [event["seq"] for event in tail] == seqs[1:]

    def test_cancel_stops_status_from_being_overwritten(self, companies, monkeypatch):
        async def _slow(target, budget=0, on_event=None, **_kw):
            await asyncio.sleep(0.4)
            return {"target": target, "overall_rating": "low"}

        import trade.osint.orchestrator as orch

        monkeypatch.setattr(orch, "osint_full_check", _slow)

        job, _ = osint_jobs.create_job(companies["first"], "slow.example")
        osint_jobs.start_job(job["id"], "slow.example")
        cancelled = osint_jobs.cancel_job(companies["first"], job["id"])
        assert cancelled["status"] == "cancelled"

        time.sleep(0.6)
        assert osint_jobs.get_job(companies["first"], job["id"])["status"] == "cancelled"

    def test_cancel_is_idempotent(self, companies, fake_orchestrator):
        job, _ = osint_jobs.create_job(companies["first"], "idem.example")
        osint_jobs.cancel_job(companies["first"], job["id"])
        again = osint_jobs.cancel_job(companies["first"], job["id"])
        assert again["status"] == "cancelled"


class TestRecovery:
    def test_running_jobs_become_partial_on_restart(self, companies):
        from trade.database import get_connection

        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO osint_jobs(company_id, target, status) VALUES (?, ?, 'running')",
                (companies["first"], "restart.example"),
            )
            conn.commit()
            job_id = cur.lastrowid
        finally:
            conn.close()

        recovered = osint_jobs.recover_stale_jobs()
        assert recovered >= 1
        job = osint_jobs.get_job(companies["first"], job_id)
        assert job["status"] == "partial"
