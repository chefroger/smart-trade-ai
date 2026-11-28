"""
OSINT 编排层与作业层保留示例/测试域名拦截测试（工单 #6）。

覆盖：
  - RFC 2606 / RFC 6761 保留域名与 example.<cc> 识别（正例）
  - 仅包含 example/test 子串的真实域名不误判（反例）
  - osint_full_check 命中保留域名时直接返回示例域名提示，不发起任何公网检索
  - osint_jobs 作业层命中保留域名时立即结束且不触发模型/外部调用
  - skills/b2b-osint/SKILL.md 含通用实体不一致防护规则
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trade import database as db_mod
from trade import osint_jobs
from trade.osint import orchestrator


@pytest.mark.parametrize(
    "raw_target,expected_domain",
    [
        # 虚构示例域名（正例）
        ("foo.example.sa", "foo.example.sa"),
        ("bar.example.com", "bar.example.com"),
        ("example.net", "example.net"),
        ("sub.example.org", "sub.example.org"),
        ("demo.example", "demo.example"),
        ("x.test", "x.test"),
        ("bad.invalid", "bad.invalid"),
        ("dev.localhost", "dev.localhost"),
        ("localhost", "localhost"),
        ("contact@foo.example.sa", "foo.example.sa"),
        ("https://bar.example.com/about", "bar.example.com"),
        ("Fictional Contracting Co. (foo.example.sa)", "foo.example.sa"),
        ("domain:foo.example.sa", "foo.example.sa"),
    ],
)
def test_reserved_domain_positive_cases(raw_target, expected_domain):
    """RFC 2606 / RFC 6761 与 example.<cc> 保留域名均被准确识别。"""
    assert orchestrator.detect_reserved_domain(raw_target) == expected_domain


@pytest.mark.parametrize(
    "real_target",
    [
        "example-trading.com",
        "myexample.sa",
        "acme-corp.com",
        "test-machinery.co.uk",
        "Global Example Parts Ltd.",
    ],
)
def test_reserved_domain_negative_cases(real_target):
    """真实域名/公司名仅含 example/test 字样时不得误判。"""
    assert orchestrator.detect_reserved_domain(real_target) is None


@pytest.mark.asyncio
async def test_osint_full_check_blocks_reserved_domain_with_zero_fetches():
    """命中保留域名时编排层直接返回示例域名提示，source_fetcher 零调用。"""
    calls = 0

    def _fail_if_called(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("保留域名不得发起公网检索")

    report = await orchestrator.osint_full_check(
        "Fictional Demo Co. (foo.example.sa)",
        source_fetcher=_fail_if_called,
    )
    assert calls == 0
    assert report["reserved_domain"] == "foo.example.sa"
    assert report["overall_rating"] == "incomplete"
    assert "示例或测试域名" in report["blocked_reason"]
    assert report["layers"] == {}
    assert report["sources"] == {}


def test_osint_job_reserved_domain_finishes_without_external_calls(tmp_path, monkeypatch):
    """作业层处理保留域名时立即以示例域名提示结束，不触发任何外部/模型调用。"""
    db_path = tmp_path / "osint_reserved.db"
    monkeypatch.setattr(db_mod, "_get_db_path", lambda: db_path)
    db_mod.init_db()
    conn = db_mod.get_connection()
    try:
        conn.execute(
            "INSERT INTO companies (id, name, slug) VALUES (1, 'Fictional Test Co', 'fictional-test')"
        )
        conn.commit()
    finally:
        conn.close()

    job, created = osint_jobs.create_job(1, "x.test")
    assert created is True

    osint_jobs._run_job(int(job["id"]), "x.test", 30.0)
    done_job = osint_jobs.get_job(1, int(job["id"]))
    assert done_job is not None
    assert done_job["status"] == "done"
    assert done_job["report"]["reserved_domain"] == "x.test"
    assert "示例或测试域名" in done_job["report"]["blocked_reason"]


def test_b2b_osint_skill_has_generic_entity_mismatch_rule():
    """b2b-osint 技能包含实体不一致时不借用第三方人名写开发信的通用规则。"""
    skill_path = Path(__file__).resolve().parent.parent / "skills" / "b2b-osint" / "SKILL.md"
    content = skill_path.read_text(encoding="utf-8")
    assert "实体不一致" in content
    assert "占位符" in content
