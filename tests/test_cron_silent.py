"""cron 静默产出不进入今日简报待看。

Hermes 判无新内容时写 `[SILENT]` 并跳过投递，但产出文件仍存。
Trade 的 `/cron/today` 不得把 silent 产出当成可展示气泡返回。
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def cron_env(monkeypatch, tmp_path):
    """把 cron 的 jobs.json / output 目录指到临时位置。"""
    import trade.api.cron as cron

    hermes = tmp_path / "hermes"
    output = hermes / "cron" / "output"
    output.mkdir(parents=True)
    monkeypatch.setattr(cron, "_HERMES_HOME", hermes)
    monkeypatch.setattr(cron, "_CRON_OUTPUT", output)
    monkeypatch.setattr(cron, "_JOBS_FILE", hermes / "cron" / "jobs.json")
    return cron


def _write_jobs(cron, jobs):
    cron._JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    cron._JOBS_FILE.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")


def _write_output(cron, job_id: str, today: str, content: str):
    d = cron._CRON_OUTPUT / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{today}_09-00-00.md").write_text(content, encoding="utf-8")


class TestIsSilentCronOutput:
    def test_silent_marker(self, cron_env):
        assert cron_env._is_silent_cron_output("[SILENT]")
        assert cron_env._is_silent_cron_output("  [SILENT]\n")
        assert cron_env._is_silent_cron_output("no_change")

    def test_normal_content_not_silent(self, cron_env):
        assert not cron_env._is_silent_cron_output("# 早安简报\n汇率上涨")
        # 正文里顺带提到也不算静默
        assert not cron_env._is_silent_cron_output("任务标记为 [SILENT] 仅供参考，以下是实质内容")


class TestSilentFilteredFromToday:
    def test_silent_output_not_shown_normal_is(self, cron_env):
        """构造一份 [SILENT] 与一份正常产出：前者无展示内容，后者正常出现。"""
        cron = cron_env
        today = date.today().isoformat()
        _write_jobs(cron, [
            {"id": "job-silent", "name": "静默任务", "schedule": {"display": "0 8 * * *"}},
            {"id": "job-normal", "name": "正常任务", "schedule": {"display": "0 9 * * *"}},
        ])
        _write_output(cron, "job-silent", today, "[SILENT]\n")
        _write_output(cron, "job-normal", today, "# 早安简报\n今日汇率稳定\n")

        result = cron.get_today_cron(1)
        by_name = {t["name"]: t for t in result["completed"]}

        silent = by_name["静默任务"]
        assert silent.get("silent") is True
        assert silent.get("has_output") is False
        assert silent.get("output") in (None, "")
        # 今日简报待看：不得带回 [SILENT] 正文
        assert "[SILENT]" not in (silent.get("output") or "")

        normal = by_name["正常任务"]
        assert normal.get("has_output") is True
        assert "早安简报" in (normal.get("output") or "")
        assert normal.get("silent") is not True
