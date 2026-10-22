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
    """「Agent 构造」检查：**只在大模型已配置时才真的去构造**。

    2026-10-15 起，「Agent 构造」前面多了一道 `check_provider()` 闸门：没配大模型时
    直接报 WARN（那是「还没配置」，不是安装问题），既不构造 agent、也就不会连带触发
    Hermes 的 pm 激活。所以这一组用例要先把闸门设成「已配置」，才测得到构造路径。
    """

    @pytest.fixture(autouse=True)
    def _provider_configured(self, monkeypatch):
        from trade import helpers

        monkeypatch.setattr(helpers, "check_provider", lambda: None)

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


class TestEstopCheck:
    """急停（ESTOP）检查：`hermes pause` 会让定时任务**静默**停跑。

    机制见 Hermes `agent/estop.py`：`hermes pause` 写 `$HERMES_HOME/ESTOP` 哨兵、
    `hermes resume` 删除；存在期间 cron/kanban/gateway 新回合一律跳过。Trade 界面
    完全不显示这个状态 —— 客户机上残留了就只会看到"定时任务不跑了"，所以必须
    能在自检里一眼看出来。
    """

    def test_no_sentinel_is_ok(self, tmp_path):
        from trade.doctor import STATUS_OK, check_estop

        results = check_estop(estop_path=tmp_path / "ESTOP")

        assert len(results) == 1 and results[0].status == STATUS_OK
        assert results[0].fatal is False

    def test_sentinel_is_warn_with_recovery_hint(self, tmp_path):
        """哨兵存在 → 降级（不是致命：Trade 还能用），且必须告诉用户怎么恢复。"""
        from trade.doctor import STATUS_WARN, check_estop

        p = tmp_path / "ESTOP"
        p.write_text('{"reason": "升级前暂停", "engaged_at": "2026-10-14"}', encoding="utf-8")

        results = check_estop(estop_path=p)

        assert results[0].status == STATUS_WARN
        detail = results[0].detail
        assert "定时任务" in detail and "hermes resume" in detail
        assert "升级前暂停" in detail, "哨兵里写了原因就带出来，便于定位"

    def test_corrupt_or_empty_sentinel_still_counts_as_engaged(self, tmp_path):
        """fail-safe：空文件/损坏内容同样是"已触发"（Hermes 就是这么判的），不是错误。"""
        from trade.doctor import STATUS_WARN, check_estop

        p = tmp_path / "ESTOP"
        p.write_text("", encoding="utf-8")
        assert check_estop(estop_path=p)[0].status == STATUS_WARN

        p.write_text("这不是 JSON{{{", encoding="utf-8")
        assert check_estop(estop_path=p)[0].status == STATUS_WARN

    def test_stat_error_is_not_a_false_ok(self, monkeypatch, tmp_path):
        """stat 出错时不能报 OK —— Hermes 自己是 fail-safe（出错也算已触发），
        而 `Path.exists()` 会吞掉 OSError 返回 False，用它就会给出假的"未急停"。"""
        import os as _os

        from trade.doctor import STATUS_OK, STATUS_WARN, check_estop

        def _boom(path, *a, **kw):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(_os, "stat", _boom)
        results = check_estop(estop_path=tmp_path / "ESTOP")

        assert results[0].status == STATUS_WARN, "stat 失败被误报成「未急停」"
        assert results[0].status != STATUS_OK
        assert "无法确认" in results[0].detail

    def test_included_in_run_doctor(self, monkeypatch):
        """run_doctor 的编排里必须带上这项检查（快检也要跑，零成本）。"""
        from trade import doctor

        seen = []
        monkeypatch.setattr(doctor, "check_estop", lambda: seen.append(True) or [])
        monkeypatch.setattr(doctor, "check_hermes_runtime", lambda: [])
        monkeypatch.setattr(doctor, "check_post_install", lambda: [])

        doctor.run_doctor(deep=False)

        assert seen, "run_doctor 没有调用 check_estop"


class TestUnconfiguredLlmIsNotFatal:
    """没配大模型 = 「还没配置」，不是「安装不完整」。

    2026-10-15 干净机器实测：安装脚本的快检走 `run_doctor(deep=False)`，其中
    「Agent 构造」是 fatal 项，而 `create_agent()` 在没配大模型时必然抛
    `RuntimeError("未配置 AI 模型…")` —— 于是新装机器**永远**卡在
    「安装不完整，请发给技术支持」，而用户照着做也没用：真正该做的是去配大模型。
    """

    @staticmethod
    def _stub_compat_ok(monkeypatch):
        """让 Hermes 版本那项直接通过，用例只聚焦「Agent 构造」。"""
        import trade.hermes_compat as compat

        monkeypatch.setattr(compat, "hermes_python_compat", lambda: {
            "verdict": "ok", "version": "0.22.0", "python": "3.14.7",
            "reason": "ok", "checkout": None,
        })

    def test_missing_provider_reports_warn_not_fatal(self, monkeypatch):
        from trade import helpers

        self._stub_compat_ok(monkeypatch)
        monkeypatch.setattr(
            helpers, "check_provider",
            lambda: "未配置 AI 模型。请先运行 hermes setup 选择模型。",
        )

        results = doctor.check_hermes_runtime(agent_factory=lambda: pytest.fail(
            "未配置大模型时不该去构造 agent（会连带触发 pm 激活）"
        ))

        agent = next(r for r in results if r.name == "Agent 构造")
        assert agent.status == doctor.STATUS_WARN
        assert agent.fatal is False
        assert "hermes setup" in agent.detail, "要告诉用户下一步是去配大模型"
        # 关键：安装脚本据此判定「能不能继续」，不能是致命
        assert doctor.has_fatal_failure(results) is False

    def test_real_construction_failure_still_fatal(self, monkeypatch):
        """大模型配好了、agent 却构造不出来 —— 这仍必须是致命项（别把真问题放过去）。"""
        from trade import helpers

        self._stub_compat_ok(monkeypatch)
        monkeypatch.setattr(helpers, "check_provider", lambda: None)

        def _boom():
            raise RuntimeError("No LLM provider configured")

        results = doctor.check_hermes_runtime(agent_factory=_boom)

        agent = next(r for r in results if r.name == "Agent 构造")
        assert agent.status == doctor.STATUS_FAIL
        assert agent.fatal is True
        assert doctor.has_fatal_failure(results) is True


class TestUpdateInterpreterGuard:
    """`trade update` 必须拒绝在非 Trade venv 的解释器下运行。

    为什么：升级过程中的全部 `pip install` 用 `sys.executable`。若被系统 python 调起
    （cron / launchd / 计划任务 / 手敲 python），依赖会装进**全局 site-packages** ——
    既污染用户系统，又因为启动器指向 Trade 自己的 venv 而下次启动仍缺依赖，白升一场。
    """

    @staticmethod
    def _stub(monkeypatch, tmp_path, *, prefix, base_prefix, trade_venv_exists):
        """把 sys.prefix 与两处 venv 探测路径都钉进临时目录。

        必须连 `Path.home()` 一起钉：开发机上**真的有** `~/.trade/venv`，
        不隔离的话判据会被真实环境干扰（第一版就是这么写的，测试结果不可信）。
        """
        from trade.post_install import update as upd

        home = tmp_path / "home"
        trade_home = tmp_path / "tradehome"
        home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(upd, "_get_trade_home", lambda: trade_home)
        monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: home))
        if trade_venv_exists:
            venv = trade_home / "venv"
            venv.mkdir(parents=True, exist_ok=True)
            (venv / "pyvenv.cfg").write_text("", encoding="utf-8")
        monkeypatch.setattr(sys, "prefix", prefix)
        monkeypatch.setattr(sys, "base_prefix", base_prefix)
        return upd, trade_home

    def test_refuses_outside_any_venv(self, monkeypatch, tmp_path):
        upd, _ = self._stub(monkeypatch, tmp_path, prefix="/usr", base_prefix="/usr",
                            trade_venv_exists=False)

        reason = upd._refuse_reason_for_interpreter()

        assert reason and "虚拟环境" in reason

    def test_refuses_inside_another_venv(self, monkeypatch, tmp_path):
        other = tmp_path / "othervenv"
        other.mkdir()
        upd, _ = self._stub(monkeypatch, tmp_path, prefix=str(other), base_prefix="/usr",
                            trade_venv_exists=True)

        reason = upd._refuse_reason_for_interpreter()

        assert reason and "不是 Trade 自己" in reason

    def test_allows_inside_trade_venv(self, monkeypatch, tmp_path):
        upd, trade_home = self._stub(monkeypatch, tmp_path,
                                     prefix=str(tmp_path / "tradehome" / "venv"),
                                     base_prefix="/usr", trade_venv_exists=True)

        assert upd._refuse_reason_for_interpreter() is None

    def test_allows_when_no_trade_venv_exists(self, monkeypatch, tmp_path):
        """开发机上从仓库直接跑（本机没有 trade venv）不能被拦。"""
        upd, _ = self._stub(monkeypatch, tmp_path, prefix=str(tmp_path), base_prefix="/usr",
                            trade_venv_exists=False)

        assert upd._refuse_reason_for_interpreter() is None

    def test_update_trade_refuses_early_when_guard_trips(self, monkeypatch, tmp_path):
        """守卫必须真的**接在 update_trade 的入口**上。

        只测 `_refuse_reason_for_interpreter()` 本身发现不了「漏接线」——
        变异检验时把调用点改成恒 None，上面 4 条用例全绿，就是这个缺口。
        """
        from trade.post_install import update as upd

        monkeypatch.setattr(upd, "_get_trade_home", lambda: tmp_path)
        monkeypatch.setattr(upd, "_refuse_reason_for_interpreter",
                            lambda: "当前解释器不在任何虚拟环境内。")
        # 架构检查排在守卫**之前**，而它在 Windows 上会走 platform.uname() →
        # platform._syscmd_ver → subprocess.check_output(['ver'])。不钉住它，
        # 下面的 subprocess 炸弹会先炸在 platform 上（CI 在 Windows 上就是这么炸的：
        # 报「守卫没接住」但其实根本没走到守卫）。钉住之后，炸弹只对
        # 「守卫被绕过」这一种情况生效。
        from trade import bootstrap

        monkeypatch.setattr(bootstrap, "check_native_architecture", lambda: True)

        # 守卫之后每一步都会碰网络/子进程：用会炸的替身，确保"越过守卫"会立刻暴露
        def _boom(*_a, **_k):
            raise AssertionError("守卫没接住，升级流程被放行了")

        monkeypatch.setattr(upd.subprocess, "run", _boom)
        monkeypatch.setattr(upd.subprocess, "Popen", _boom)

        result = upd.update_trade()

        assert result["ok"] is False
        assert "not_in_trade_venv" in result["errors"]


class TestSkillsConsistency:
    """技能一致性检查（2026-10-21 审计 P1）。

    升级时技能同步失败只记 warning，而 doctor 原先没有任何技能检查 ——
    结果 doctor 全绿、技能停在旧版，用户无从察觉。
    """

    def _tree(self, root, files):
        for name, content in files.items():
            d = root / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "SKILL.md").write_text(content, encoding="utf-8")

    def test_all_match_reports_ok(self, tmp_path):
        from trade.doctor import STATUS_OK, check_skills

        pkg, inst = tmp_path / "pkg", tmp_path / "inst"
        self._tree(pkg, {"b2b-a": "v1", "b2b-b": "v1"})
        self._tree(inst, {"b2b-a": "v1", "b2b-b": "v1"})

        result = check_skills(package_dir=pkg, installed_dir=inst)[0]
        assert result.status == STATUS_OK

    def test_missing_and_stale_are_warned(self, tmp_path):
        from trade.doctor import STATUS_WARN, check_skills

        pkg, inst = tmp_path / "pkg", tmp_path / "inst"
        self._tree(pkg, {"b2b-a": "v1", "b2b-b": "v1", "b2b-c": "v1"})
        self._tree(inst, {"b2b-a": "v1", "b2b-b": "v0"})  # b 旧版，c 缺失

        result = check_skills(package_dir=pkg, installed_dir=inst)[0]
        assert result.status == STATUS_WARN
        assert "缺失 1" in result.detail and "b2b-c" in result.detail
        assert "旧版本 1" in result.detail and "b2b-b" in result.detail

    def test_user_extra_skills_are_not_flagged(self, tmp_path):
        """用户自己加的技能不属于包内清单，不算问题。"""
        from trade.doctor import STATUS_OK, check_skills

        pkg, inst = tmp_path / "pkg", tmp_path / "inst"
        self._tree(pkg, {"b2b-a": "v1"})
        self._tree(inst, {"b2b-a": "v1", "my-custom": "whatever"})

        assert check_skills(package_dir=pkg, installed_dir=inst)[0].status == STATUS_OK

    def test_missing_package_dir_is_not_a_false_alarm(self, tmp_path):
        from trade.doctor import STATUS_WARN, check_skills

        result = check_skills(package_dir=tmp_path / "nope", installed_dir=tmp_path)[0]
        assert result.status == STATUS_WARN
        assert "找不到包内" in result.detail
