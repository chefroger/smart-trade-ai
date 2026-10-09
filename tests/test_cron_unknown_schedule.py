"""调度解析不出来的 cron 任务必须标「未知」，不能显示成「待执行」。

## 问题

`_cron_to_time` 只处理 "M H * * *" 形态；`*/5 * * * *`、`0 9 1 * *` 这类
返回空串。而 `get_today_cron` 里：

    task_time = task["time"].split("-")[0] ...
    is_past = bool(task_time) and task_time <= current_time   # 空串 → False

于是解析失败的任务**永远**落在 `pending` 且 `missed=False` —— 界面上看是
「还没到点」，而真相是「不知道它该几点跑」。一个从没执行过、或执行失败的任务，
用户会一直以为它只是还没到时间。

（这个 `bool(task_time)` 守卫本身是为了修另一个 bug：空串 <= "14:30" 恒为 True，
会把空任务永远标成 missed。修法不是把两者混为一谈，而是显式区分第三种状态。）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def cron_env(monkeypatch, tmp_path):
    """把 cron 的 jobs.json / output 目录指到临时位置。"""
    import trade.api.cron as cron

    hermes = tmp_path / "hermes"
    (hermes / "cron" / "output").mkdir(parents=True)
    monkeypatch.setattr(cron, "_HERMES_HOME", hermes)
    monkeypatch.setattr(cron, "_CRON_OUTPUT", hermes / "cron" / "output")
    monkeypatch.setattr(cron, "_JOBS_FILE", hermes / "cron" / "jobs.json")
    return cron


def _write_jobs(cron, jobs):
    cron._JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    cron._JOBS_FILE.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")


class TestUnknownScheduleFlagged:
    def test_complex_cron_expression_is_marked_unknown(self, cron_env):
        """`*/5 * * * *` 解析不出时刻 → 应标 unknown_schedule，而非"未到点"。"""
        cron = cron_env
        _write_jobs(cron, [{"id": "j1", "name": "每五分钟跑", "schedule": {"expr": "*/5 * * * *"}}])

        result = cron.get_today_cron(1)

        assert not result["completed"], "前置条件：没有输出 → 不在 completed"
        item = result["pending"][0]
        assert item.get("unknown_schedule") is True, (
            f"解析不出调度却当成「还没到点」：{item}"
        )
        assert item["missed"] is None, "未知调度的 missed 必须是 None（未知），不能是 False"

    def test_normal_time_is_not_marked_unknown(self, cron_env):
        """正常时刻仍按老逻辑判定 —— 别把好路径标成未知。"""
        cron = cron_env
        _write_jobs(cron, [{"id": "j2", "name": "每天九点", "schedule": {"display": "0 9 * * *"}}])

        item = cron.get_today_cron(1)["pending"][0]

        assert item.get("unknown_schedule") is not True
        assert item["missed"] in (True, False)
