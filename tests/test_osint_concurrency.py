"""P0-4：CLI 并发、分层超时、全局预算、进度事件。

工单验收：
  - 注入一个慢 fake 层（sleep 300 秒）后，CLI 在 budget + 5 秒内返回，
    报告里该层标注 timeout；
  - 正常情况下各层并行，总耗时约等于最慢的一层。

测试里用 sleep 0.35~5 秒代替 300 秒（同样的机制，跑得快）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import trade.osint.orchestrator as orch  # noqa: E402
from trade.osint import cli  # noqa: E402


def _whois_ok(*_, **__):
    return {
        "domain": "acme.com",
        "registered": True,
        "creation_date": "2015-01-01T00:00:00Z",
        "days_old": 4000,
        "age_category": "old",
        "error": None,
    }


def _tech_ok(*_, **__):
    return {
        "technologies": ["nginx"],
        "is_free_platform": False,
        "is_enterprise": True,
        "error": None,
    }


def _sanctions_healthy(*_, **__):
    return {
        "is_sanctioned": False,
        "risk_level": "none",
        "hits": [],
        "coverage": {"degraded": False, "total_entries": 30000},
    }


class TestParallelExecution:
    @pytest.mark.asyncio
    async def test_independent_layers_run_concurrently(self, monkeypatch):
        """两层各睡 0.35s，并发总耗时 < 0.6s（串行则 ≥ 0.7s）。"""
        def _slow_whois(domain):
            time.sleep(0.35)
            return _whois_ok()

        def _slow_tech(url):
            time.sleep(0.35)
            return _tech_ok()

        monkeypatch.setattr(orch, "domain_whois", _slow_whois)
        monkeypatch.setattr(orch, "detect_tech_stack", _slow_tech)

        started = time.monotonic()
        report = await orch.osint_full_check(
            "acme.com",
            include_sanctions=False,
            include_tech_stack=True,
            include_linkedin=False,
        )
        elapsed = time.monotonic() - started

        assert elapsed < 0.6, f"各层没有并发（耗时 {elapsed:.2f}s）"
        assert report["layers"]["domain_intel"]["registered"] is True
        assert report["layers"]["tech_stack"]["technologies"] == ["nginx"]


class TestLayerTimeout:
    @pytest.mark.asyncio
    async def test_slow_layer_times_out_and_report_returns(self, monkeypatch):
        """慢层 5 秒、预算 1 秒 → 1 秒左右返回，该层标 timeout。"""
        def _very_slow(domain):
            time.sleep(5)
            return _whois_ok()

        monkeypatch.setattr(orch, "domain_whois", _very_slow)

        started = time.monotonic()
        report = await orch.osint_full_check(
            "acme.com",
            include_sanctions=False,
            include_tech_stack=False,
            include_linkedin=False,
            budget=1.0,
        )
        elapsed = time.monotonic() - started

        assert elapsed < 2.5, "超时后仍在等线程结束（守护线程没生效？）"
        di = report["layers"]["domain_intel"]
        assert di["timed_out"] is True
        assert "超时" in di["error"]
        # 关键层超时 → fail-closed 结论
        assert report["overall_rating"] == "incomplete"
        assert report["overall_score"] is None

    @pytest.mark.asyncio
    async def test_failed_layer_does_not_kill_other_layers(self, monkeypatch):
        """某层抛异常，其它层照常完成。"""
        def _boom(domain):
            raise RuntimeError("whois 炸了")

        monkeypatch.setattr(orch, "domain_whois", _boom)
        monkeypatch.setattr(orch, "detect_tech_stack", _tech_ok)

        report = await orch.osint_full_check(
            "acme.com",
            include_sanctions=False,
            include_tech_stack=True,
            include_linkedin=False,
        )

        assert report["layers"]["domain_intel"]["error"] == "whois 炸了"
        assert report["layers"]["tech_stack"]["technologies"] == ["nginx"]

    @pytest.mark.asyncio
    async def test_exhausted_budget_marks_layer_without_running(self):
        """预算为 0：不启动线程，直接标 timeout（预算耗尽）。"""
        result = await orch._run_layer("domain_intel", _whois_ok, "acme.com", timeout=0)
        assert result["timed_out"] is True
        assert "预算耗尽" in result["error"]


class TestProgressEvents:
    @pytest.mark.asyncio
    async def test_start_and_done_for_every_layer(self, monkeypatch):
        monkeypatch.setattr(orch, "domain_whois", _whois_ok)
        monkeypatch.setattr(orch, "detect_tech_stack", _tech_ok)
        monkeypatch.setattr(
            orch, "check_sanctions", lambda name, country=None: _sanctions_healthy()
        )
        monkeypatch.setattr(orch, "_resolve_entity_name", lambda domain, **kw: None)

        events: list[dict] = []
        report = await orch.osint_full_check(
            "acme.com",
            include_sanctions=True,
            include_tech_stack=True,
            include_linkedin=True,
            on_event=events.append,
        )

        started = {e["source"] for e in events if e["event"] == "source_start"}
        done = {e["source"]: e for e in events if e["event"] == "source_done"}
        assert started == {"domain_intel", "tech_stack", "sanctions", "linkedin"}
        assert set(done) == started
        for event in done.values():
            assert event["status"] in {"hit", "miss", "error", "skipped", "timeout"}
            assert isinstance(event["ms"], int)
        assert done["domain_intel"]["status"] == "hit"
        assert done["sanctions"]["status"] == "miss"
        assert done["linkedin"]["status"] == "skipped"
        assert report["layers"]["linkedin"] is not None

    @pytest.mark.asyncio
    async def test_timeout_status_reported(self, monkeypatch):
        monkeypatch.setattr(
            orch, "domain_whois", lambda domain: (time.sleep(5), _whois_ok())[1]
        )
        events: list[dict] = []
        await orch.osint_full_check(
            "acme.com",
            include_sanctions=False,
            include_tech_stack=False,
            include_linkedin=False,
            budget=0.3,
            on_event=events.append,
        )
        done = next(e for e in events if e["event"] == "source_done")
        assert done["source"] == "domain_intel"
        assert done["status"] == "timeout"


def _minimal_report() -> dict:
    return {
        "target": "acme.com",
        "target_type": "domain",
        "overall_score": 100,
        "overall_rating": "low",
        "flags": [],
        "layers": {},
        "recommendations": [],
    }


def _async(value):
    async def _coro():
        return value
    return _coro()


class TestCliOptions:
    def test_progress_goes_to_stderr_as_jsonl(self, monkeypatch, capsys):
        async def _fake(target, **kw):
            on_event = kw.get("on_event")
            assert on_event is not None, "--progress 必须把 on_event 传下去"
            on_event({"event": "source_start", "source": "domain_intel", "label": "WHOIS 域名情报"})
            on_event({"event": "source_done", "source": "domain_intel",
                      "status": "hit", "ms": 12})
            return _minimal_report()

        monkeypatch.setattr(cli, "osint_full_check", _fake)
        assert cli.main(["--progress", "acme.com"]) == 0

        captured = capsys.readouterr()
        events = [json.loads(line) for line in captured.err.strip().splitlines()]
        assert events[0]["event"] == "source_start"
        assert events[1]["status"] == "hit"
        # stdout 仍是人读报告，不混入 JSONL
        assert "综合评分" in captured.out
        assert '"event"' not in captured.out

    def test_no_progress_passes_none(self, monkeypatch):
        seen = {}

        async def _fake(target, **kw):
            seen.update(kw)
            return _minimal_report()

        monkeypatch.setattr(cli, "osint_full_check", _fake)
        cli.main(["acme.com"])
        assert seen["on_event"] is None

    def test_target_option_with_spaces(self, monkeypatch):
        seen = {}

        async def _fake(target, **kw):
            seen["target"] = target
            return _minimal_report()

        monkeypatch.setattr(cli, "osint_full_check", _fake)
        assert cli.main(["--target=Acme Corp"]) == 0
        assert seen["target"] == "Acme Corp"

    def test_target_option_conflicts_with_positional(self, capsys):
        assert cli.main(["--target=Acme", "other.com"]) == 2
        assert "不能同时使用" in capsys.readouterr().out

    def test_budget_option_is_forwarded(self, monkeypatch):
        seen = {}

        async def _fake(target, **kw):
            seen.update(kw)
            return _minimal_report()

        monkeypatch.setattr(cli, "osint_full_check", _fake)
        assert cli.main(["acme.com", "--budget=42"]) == 0
        assert seen["budget"] == 42.0

    def test_invalid_budget_rejected(self, capsys):
        assert cli.main(["acme.com", "--budget=abc"]) == 2
        assert "--budget 需要数字" in capsys.readouterr().out
        assert cli.main(["acme.com", "--budget=0"]) == 2
        assert "必须大于 0" in capsys.readouterr().out

    def test_cli_render_marks_timeout(self):
        report = _minimal_report()
        report["layers"] = {
            "domain_intel": {"timed_out": True, "error": "超时（20 秒）",
                             "registered": False, "domain": "acme.com"},
        }
        text = cli.format_report(report)
        assert "超时 —— 超时（20 秒）" in text


# 冒烟：守护线程的异常不会泄漏到事件循环
def test_spawn_blocking_propagates_exception():
    async def _run():
        with pytest.raises(ValueError):
            await orch._spawn_blocking(lambda: (_ for _ in ()).throw(ValueError("boom")))
    asyncio.run(_run())
