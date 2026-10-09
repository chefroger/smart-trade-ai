"""`trade doctor` —— 安装后端到端自检。

## 设计要点

- **端到端验活**：能发真实请求就发真实请求。特别是 vision 必须让配置好的模型
  真读一张图 —— 历史上"工具不在场"和"模型看不见"两个洞各踩过一次，
  只有真读图能同时覆盖。
- **分级阻断**：只有"Trade 根本用不了"的项标 fatal（agent 构造不出来、
  数据库不可写、对话空回复）。搜索/记忆这类降级项不阻断。
- **捕 BaseException**：客户机事故的异常是 RelaunchExit(SystemExit)，
  `except Exception` 抓不到，自检本身必须避免重蹈。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import doctor


@pytest.fixture
def trade_home(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    return tmp_path


class TestHermesRuntimeCheck:
    def test_success(self):
        class _FakeAgent:
            pass

        results = doctor.check_hermes_runtime(agent_factory=lambda: _FakeAgent())

        assert any(r.name == "Agent 构造" and r.status == doctor.STATUS_OK for r in results)

    def test_base_exception_is_caught(self):
        """RelaunchExit 继承 SystemExit —— 自检必须能报出它，而不是自己崩掉。"""
        def boom():
            raise SystemExit(1)

        results = doctor.check_hermes_runtime(agent_factory=boom)

        item = next(r for r in results if r.name == "Agent 构造")
        assert item.status == doctor.STATUS_FAIL
        assert "SystemExit" in item.detail
        assert item.fatal is True, "agent 构造不出来 = Trade 根本用不了，必须致命"

    def test_ordinary_exception_is_caught(self):
        def boom():
            raise RuntimeError("provider 未配置")

        results = doctor.check_hermes_runtime(agent_factory=boom)

        item = next(r for r in results if r.name == "Agent 构造")
        assert item.status == doctor.STATUS_FAIL
        assert "provider 未配置" in item.detail


class TestVisionCheck:
    def test_missing_tool_is_fatal_and_names_the_cause(self):
        results = doctor.check_vision(
            tool_list_provider=lambda: ["read_file", "terminal"],
            vision_prober=lambda _t: (True, "unused"),
        )

        item = next(r for r in results if r.name == "vision 工具在场")
        assert item.status == doctor.STATUS_FAIL
        assert item.fatal is True, "没有看图工具时图片需求全废"
        assert "DEFAULT_ENABLED_TOOLSETS" in item.detail, "要指向真正该改的地方"

    def test_tool_present_but_model_blind_is_reported(self):
        """工具在场 ≠ 模型能看 —— 两件事分开报。"""
        results = doctor.check_vision(
            tool_list_provider=lambda: ["vision_analyze"],
            vision_prober=lambda _t: (False, "模型未读出探测文字"),
        )

        assert next(r for r in results if r.name == "vision 工具在场").status == doctor.STATUS_OK
        blind = next(r for r in results if r.name == "vision 读图")
        assert blind.status == doctor.STATUS_FAIL
        assert blind.fatal is False, "读不了图仍能用纯文字，属降级而非致命"

    def test_probe_text_is_passed_to_prober(self):
        seen = []

        doctor.check_vision(
            tool_list_provider=lambda: ["vision_analyze"],
            vision_prober=lambda t: (seen.append(t), (True, "ok"))[1],
        )

        assert seen and seen[0].startswith("VISION-OK-"), (
            "探测文字必须是本次生成的随机 token —— 固定文字可能被模型猜中"
        )

    def test_probe_failure_does_not_crash(self):
        def boom(_t):
            raise OSError("provider 不通")

        results = doctor.check_vision(
            tool_list_provider=lambda: ["vision_analyze"], vision_prober=boom
        )

        assert any(r.name == "vision 读图" for r in results)


class TestTavilyCheck:
    def test_missing_key_is_degraded_not_fatal(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)

        results = doctor.check_tavily()

        assert results[0].status == doctor.STATUS_WARN
        assert results[0].fatal is False, "没配搜索仍能用 Trade，不该阻断"

    def test_live_search_success(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

        results = doctor.check_tavily(searcher=lambda _k: (True, "搜索可用"))

        assert results[0].status == doctor.STATUS_OK

    def test_ssl_failure_is_reported_not_swallowed(self, monkeypatch):
        """本机实测过 SSL 被拦时搜索静默失败 —— 自检必须把它显形。"""
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

        def ssl_boom(_k):
            raise OSError("SSL: UNEXPECTED_EOF_WHILE_READING")

        results = doctor.check_tavily(searcher=ssl_boom)

        assert results[0].status == doctor.STATUS_WARN
        assert "SSL" in results[0].detail


class TestTradeCheck:
    def test_empty_chat_reply_is_fatal(self):
        """空回复正是客户机上「Agent 未返回有效回复」的表现 —— 必须致命。"""
        results = doctor.check_trade(
            db_prober=lambda: (True, "可读写"),
            chat_prober=lambda: (False, "agent 返回空回复"),
        )

        item = next(r for r in results if r.name == "对话回合")
        assert item.status == doctor.STATUS_FAIL
        assert item.fatal is True

    def test_chat_raising_systemexit_is_fatal_not_crash(self):
        def boom():
            raise SystemExit(1)

        results = doctor.check_trade(db_prober=lambda: (True, "ok"), chat_prober=boom)

        item = next(r for r in results if r.name == "对话回合")
        assert item.status == doctor.STATUS_FAIL and item.fatal is True

    def test_db_failure_is_fatal(self):
        results = doctor.check_trade(
            db_prober=lambda: (False, "磁盘只读"),
            chat_prober=lambda: (True, "ok"),
        )

        item = next(r for r in results if r.name == "数据库")
        assert item.fatal is True


class TestFatalAggregation:
    def test_fatal_failure_detected(self):
        results = [
            doctor.CheckResult("a", doctor.STATUS_OK, ""),
            doctor.CheckResult("b", doctor.STATUS_FAIL, "", fatal=True),
        ]
        assert doctor.has_fatal_failure(results) is True

    def test_warn_failure_does_not_block(self):
        results = [
            doctor.CheckResult("search", doctor.STATUS_WARN, "没配 key"),
            doctor.CheckResult("a", doctor.STATUS_OK, ""),
        ]
        assert doctor.has_fatal_failure(results) is False

    def test_non_fatal_fail_does_not_block(self):
        results = [doctor.CheckResult("vision", doctor.STATUS_FAIL, "", fatal=False)]
        assert doctor.has_fatal_failure(results) is False


class TestReport:
    def test_report_lists_every_check(self):
        results = [
            doctor.CheckResult("Hermes 版本", doctor.STATUS_OK, "0.21.4"),
            doctor.CheckResult("Tavily 搜索", doctor.STATUS_WARN, "未配置"),
        ]

        text = doctor.format_report(results)

        assert "Hermes 版本" in text and "Tavily 搜索" in text
        assert "降级" in text

    def test_report_says_all_passed(self):
        text = doctor.format_report([doctor.CheckResult("a", doctor.STATUS_OK, "x")])
        assert "全部通过" in text

    def test_report_surfaces_fatal_loudly(self):
        text = doctor.format_report(
            [doctor.CheckResult("对话回合", doctor.STATUS_FAIL, "空回复", fatal=True)]
        )
        assert "无法正常使用" in text


class TestShouldRunPolicy:
    """首次跑；未过则每次启动重试；配置变了重跑。"""

    def test_runs_when_no_record(self, trade_home):
        assert doctor.should_run_doctor() is True

    def test_skips_when_passed_and_config_unchanged(self, trade_home, monkeypatch):
        monkeypatch.setattr(doctor, "_fingerprint", lambda: "p|m|0.6.8")
        doctor.save_doctor_result([doctor.CheckResult("a", doctor.STATUS_OK, "x")])

        assert doctor.should_run_doctor() is False

    def test_retries_when_last_run_failed(self, trade_home, monkeypatch):
        monkeypatch.setattr(doctor, "_fingerprint", lambda: "p|m|0.6.8")
        doctor.save_doctor_result(
            [doctor.CheckResult("对话回合", doctor.STATUS_FAIL, "空回复", fatal=True)]
        )

        assert doctor.should_run_doctor() is True, "未过时必须每次启动重试 —— 客户修好配置重启就恢复"

    def test_retries_when_config_changed(self, trade_home, monkeypatch):
        monkeypatch.setattr(doctor, "_fingerprint", lambda: "p|m|0.6.8")
        doctor.save_doctor_result([doctor.CheckResult("a", doctor.STATUS_OK, "x")])
        monkeypatch.setattr(doctor, "_fingerprint", lambda: "other|model|0.6.8")

        assert doctor.should_run_doctor() is True

    def test_corrupt_state_file_reruns(self, trade_home):
        path = doctor._state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json", encoding="utf-8")

        assert doctor.should_run_doctor() is True

    def test_saved_report_is_readable(self, trade_home, monkeypatch):
        monkeypatch.setattr(doctor, "_fingerprint", lambda: "fp")
        doctor.save_doctor_result([doctor.CheckResult("a", doctor.STATUS_OK, "x")])

        data = doctor.load_doctor_result()

        assert data["passed"] is True and data["results"][0]["name"] == "a"
        assert json.dumps(data)  # 可序列化


class TestVisionResponseJudgement:
    """真机跑出来的两个坑,都钉在 `_judge_vision_response` 上。"""

    def test_reads_expected_text(self):
        ok, detail = doctor._judge_vision_response("VISION-OK-1234", "VISION-OK-1234", "stop")

        assert ok is True and "读出" in detail

    def test_empty_content_with_length_finish_is_budget_not_blindness(self):
        """真机实测：deepseek-flash 是推理模型，max_tokens 太小时推理占满预算、
        正文为空（finish_reason=length）。这**不是**"模型看不见"，
        报错措辞必须区分开 —— 否则会误导排查方向。"""
        ok, detail = doctor._judge_vision_response("VISION-OK-1234", "", "length")

        assert ok is False
        assert "推理" in detail or "预算" in detail, "要点出真实原因（预算被推理占满）"
        # 不能落到"未读出探测文字"那句 —— 那是"模型试过但没读对"的措辞，
        # 会把排查引向模型能力，而真因是探测参数
        assert "未读出探测文字" not in detail

    def test_wrong_text_is_reported_with_actual_output(self):
        ok, detail = doctor._judge_vision_response("VISION-OK-1234", "我看不清", "stop")

        assert ok is False
        assert "我看不清" in detail, "要把模型实际返回的内容带出来，便于判断"


class TestReportCountsEveryFailure:
    """真机跑出来的 bug：出现 ✗ 却仍打印「全部通过」。

    `format_report` 原先只统计 fatal 与 warn —— 非致命的 FAIL 两边都不算，
    于是落到 else 分支说"全部通过"。这正是本项目一直在修的那类
    「把失败说成通过」。
    """

    def test_non_fatal_failure_is_not_reported_as_all_passed(self):
        text = doctor.format_report([
            doctor.CheckResult("Agent 构造", doctor.STATUS_OK, "ok"),
            doctor.CheckResult("vision 读图", doctor.STATUS_FAIL, "没读出来", fatal=False),
        ])

        assert "全部通过" not in text, "有 ✗ 却说全部通过"
        assert "vision 读图" in text

    def test_failure_wording_differs_from_degradation(self):
        """失败与降级要分开说 —— 两者的用户动作不同（一个要修，一个可忽略）。"""
        failed = doctor.format_report(
            [doctor.CheckResult("vision 读图", doctor.STATUS_FAIL, "x", fatal=False)]
        )
        warned = doctor.format_report(
            [doctor.CheckResult("Tavily 搜索", doctor.STATUS_WARN, "x")]
        )

        assert "降级" not in failed, "失败不该被降级措辞掩盖"
        assert "降级" in warned


class TestQuickMode:
    def test_quick_skips_live_requests(self, monkeypatch):
        """快检绝不发真实请求（安装时可安全调用，零 token）。"""
        called = []
        monkeypatch.setattr(doctor, "_probe_vision_live", lambda _t: called.append("vision"))
        monkeypatch.setattr(doctor, "_probe_chat_live", lambda: called.append("chat"))
        monkeypatch.setattr(doctor, "_probe_tavily_live", lambda _k: called.append("tavily"))
        monkeypatch.setattr(doctor, "_agent_tool_names", lambda: ["vision_analyze"])

        doctor.run_doctor(deep=False)

        assert called == [], f"快检不应发真实请求，却调用了：{called}"

    def test_quick_still_reports_missing_vision_tool(self, monkeypatch):
        monkeypatch.setattr(doctor, "_agent_tool_names", lambda: ["read_file"])

        results = doctor.run_doctor(deep=False)

        assert any(r.name == "vision 工具在场" and r.status == doctor.STATUS_FAIL for r in results)
