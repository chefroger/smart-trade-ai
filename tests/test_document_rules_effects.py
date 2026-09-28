"""
文档读取规则的**端到端实测**：真实 /chat 端点 + 真实门禁 + 真实证据收集器。

为什么需要这个文件：这一轮改动同时触及「提示词里的规则」和「机械门禁」两层，
而两层是否真的生效，读代码不足以判断（本项目已多次出现「文档写着、代码也在、
运行时不生效」）。这里用脚本化的假 Agent 驱动真实的 trade_chat()，
把各种读取剧本各跑一遍，断言**实际结果**。

运行条件刻意设为「客户机形态」：Hermes 不提供结构化读取快照
（snapshot_read_coverage 返回 None），证据只能来自工具回调 ——
也就是客户机上真实会发生的那条路径。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STRICT_QUERY = "请完整读取这个目录的所有文件"
CHAT_QUERY = "介绍一下你们公司"  # 非文档类提问


def _ok_result(total_lines: int = 5) -> str:
    """一次读到底的 read_file 结果。"""
    return json.dumps({"total_lines": total_lines, "truncated": False})


def _partial_result(total_lines: int = 10, next_offset: int = 3) -> str:
    """被截断且没有续读的结果（覆盖 1..next_offset-1）。"""
    return json.dumps({"total_lines": total_lines, "truncated": True, "next_offset": next_offset})


def _error_result(reason: str = "binary_content") -> str:
    return json.dumps({"error": reason})


class ScriptedAgent:
    """按剧本触发工具回调的假 Agent —— 回调就是生产代码接的那两个。"""

    def __init__(self, script):
        self.script = script  # [(name, args, result), ...]
        self.answer = "分析完成"
        self.tool_start_callback = None
        self.tool_complete_callback = None

    def run_conversation(self, query, task_id=None):  # noqa: ARG002
        for i, (name, args, result) in enumerate(self.script):
            call_id = f"call-{i}"
            if self.tool_start_callback:
                self.tool_start_callback(call_id, name, args)
            if self.tool_complete_callback:
                self.tool_complete_callback(call_id, name, args, result)
        return {"final_response": self.answer}

    def chat(self, query):  # noqa: ARG002
        return self.answer


@pytest.fixture
def env(monkeypatch, tmp_path):
    """临时库 + 公司；库内含 1 个文本文件与 1 个 xlsx（都需完整读取）。"""
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
    company = co.create(name="Rules Co", slug="rules-co")

    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    (lib_dir / "合同.txt").write_text("甲\n乙\n丙\n", encoding="utf-8")
    (lib_dir / "报价.xlsx").write_bytes(b"PK\x03\x04demo")

    import trade.library as lib
    library = lib.create("规则库", str(lib_dir), company_id=company["id"])
    return {"cid": company["id"], "library": library, "dir": lib_dir}


async def _run_chat(env, script, *, query=STRICT_QUERY, saved=None, library_id=True):
    """跑一次真实 trade_chat()，返回响应体。"""
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    saved = saved if saved is not None else []
    scripted = ScriptedAgent(script)

    def _create_agent(**kwargs):
        scripted.tool_start_callback = kwargs.get("tool_start_callback")
        scripted.tool_complete_callback = kwargs.get("tool_complete_callback")
        return scripted

    def _save(**kwargs):
        saved.append(kwargs)
        return {"id": 1}

    with patch.object(chat, "create_agent", side_effect=_create_agent), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat, "snapshot_read_coverage", return_value=None), \
         patch("trade.license.check_license", return_value=(True, "")), \
         patch.object(chat.chat_memory, "save_with_context", side_effect=_save):
        payload = ChatRequest(
            query=query,
            library_id=(env["library"]["id"] if library_id else None),
        )
        return await chat.trade_chat(payload, env["cid"])


# ── 通过路径 ────────────────────────────────────────────────────────────────


async def test_all_files_read_completely_passes(env):
    """规则：可分析文件全部读完 → 放行，并如实披露无法逐 Sheet/逐页核验。"""
    script = [
        ("read_file", {"path": str(env["dir"] / "合同.txt")}, _ok_result(3)),
        ("read_file", {"path": str(env["dir"] / "报价.xlsx")}, _ok_result(2)),
    ]

    result = await _run_chat(env, script)

    assert result["response"] == "分析完成", result["response"]
    assert "analysis_incomplete" not in result
    assert result.get("analysis_note"), "客户机形态必须披露能力边界"


async def test_all_files_read_via_terminal_passes_with_disclosure(env):
    """规则（本轮新增）：全程用 terminal 读 → 不误杀，但披露无法核验读全。"""
    script = [
        ("terminal", {"command": f"cat {env['dir']}/合同.txt"}, "甲\n乙\n丙"),
        ("terminal", {"command": f"pdftotext {env['dir']}/报价.xlsx -"}, "…"),
    ]

    result = await _run_chat(env, script)

    assert result["response"] == "分析完成", "terminal 读过不该被误判为漏读"
    assert result.get("analysis_note")


async def test_mixed_read_file_and_terminal_passes(env):
    """规则（本轮新增）：read_file 读 A + terminal 读 B → 不被整体误杀。"""
    script = [
        ("read_file", {"path": str(env["dir"] / "合同.txt")}, _ok_result(3)),
        ("terminal", {"command": f"cat {env['dir']}/报价.xlsx"}, "…"),
    ]

    result = await _run_chat(env, script)

    assert result["response"] == "分析完成", result["response"]


# ── 拦截路径 ────────────────────────────────────────────────────────────────


async def test_skipping_one_file_blocks_and_names_it(env):
    """规则：漏读任一可分析文件 → 拦截，且报告点名该文件。"""
    script = [("read_file", {"path": str(env["dir"] / "合同.txt")}, _ok_result(3))]

    result = await _run_chat(env, script)

    assert result["analysis_incomplete"] is True
    assert "报价.xlsx" in result["response"], "必须点名漏读的文件"
    assert "分析完成" not in result["response"], "不得把不完整结论当答案给出"


async def test_partial_read_blocks(env):
    """规则：截断后未续读（覆盖率不足）→ 拦截。"""
    script = [
        ("read_file", {"path": str(env["dir"] / "合同.txt")}, _partial_result(10, 3)),
        ("read_file", {"path": str(env["dir"] / "报价.xlsx")}, _ok_result(2)),
    ]

    result = await _run_chat(env, script)

    assert result["analysis_incomplete"] is True
    assert "合同.txt" in result["response"]


async def test_resumed_read_after_truncation_passes(env):
    """规则：截断后按 next_offset 续读到尾 → 覆盖率补齐 → 放行。"""
    script = [
        ("read_file", {"path": str(env["dir"] / "合同.txt")},
         json.dumps({"total_lines": 4, "truncated": True, "next_offset": 3})),
        ("read_file", {"path": str(env["dir"] / "合同.txt"), "offset": 3},
         json.dumps({"total_lines": 4, "truncated": False})),
        ("read_file", {"path": str(env["dir"] / "报价.xlsx")}, _ok_result(2)),
    ]

    result = await _run_chat(env, script)

    assert result["response"] == "分析完成", result["response"]


async def test_changed_file_during_analysis_blocks(env):
    """规则：分析期间源文件被改 → 拦截（结论不再可信）。"""
    target = env["dir"] / "合同.txt"
    script = [
        ("read_file", {"path": str(target)}, _ok_result(3)),
        ("read_file", {"path": str(env["dir"] / "报价.xlsx")}, _ok_result(2)),
    ]

    # 在第 2 个工具调用前改文件：用回调顺序无法插桩，改用「先改文件再跑」+
    # 让清单在校验时看到不同指纹 —— 这里直接走真实路径：先跑一次读，
    # 再在 evaluate 前改文件不可行，故用 monkeypatch 模拟指纹变化。
    import trade.document_task as dt
    original = dt.DocumentTask._fingerprint_changed
    calls = {"n": 0}

    def _flaky(self, item):
        calls["n"] += 1
        return calls["n"] == 1  # 第一个文件报「已变化」

    with patch.object(dt.DocumentTask, "_fingerprint_changed", _flaky):
        result = await _run_chat(env, script)

    assert original is not None  # 保持引用，说明走的是真实方法的替换
    assert result["analysis_incomplete"] is True
    assert "changed_during_analysis" in result["response"] or "被修改" in result["response"]


# ── 不拦截的边界 ────────────────────────────────────────────────────────────


async def test_no_tool_calls_at_all_degrades_instead_of_blocking(env):
    """规则：完全没有读取证据 → 放行（无法区分「没读」与「用别的方式读了」）。"""
    result = await _run_chat(env, [])

    assert result["response"] == "分析完成"
    assert "analysis_incomplete" not in result


async def test_unreadable_file_is_disclosed_not_blocking(env):
    """规则：文件本身读不出来（损坏/二进制）→ 披露，但不拦。"""
    script = [
        ("read_file", {"path": str(env["dir"] / "合同.txt")}, _ok_result(3)),
        ("read_file", {"path": str(env["dir"] / "报价.xlsx")}, _error_result("unreadable_binary")),
    ]

    result = await _run_chat(env, script)

    assert result["response"] == "分析完成", "文件读不出来不是 agent 的疏漏"
    skipped = result.get("analysis_skipped") or []
    assert any("报价.xlsx" in str(item) for item in skipped) or "报价.xlsx" in result["response"]


async def test_gate_not_enforced_for_normal_chat(env):
    """规则：非「全量读取」意图的提问不启用门禁（普通问答不受影响）。"""
    result = await _run_chat(env, [], query=CHAT_QUERY)

    assert result["response"] == "分析完成"
    assert "analysis_incomplete" not in result
    assert "analysis_note" not in result, "门禁没启用时不应附加任何门禁说明"


async def test_gate_not_enforced_without_library(env):
    """规则：没选文档库 → 门禁不介入。"""
    result = await _run_chat(env, [], library_id=False)

    assert result["response"] == "分析完成"
    assert "analysis_incomplete" not in result


# ── 提示词层：规则是否真的进入最终 prompt ────────────────────────────────────
# 这里直接调生产的 build_query（真实装配器），断言最终发给模型的文本内容。


class TestPromptRulesReachModel:
    """「逐个文件完整扫描」等规则必须真的出现在最终 prompt 里。"""

    def _build(self, env, query, *, library_id=None, calls=1):
        """连续调用 build_query（第 2 次起走「非首轮」档），返回最后一次结果。"""
        import trade.helpers as helpers

        result = None
        for _ in range(calls):
            result = helpers.build_query(
                env["cid"], library_id, query,
            )
        return result

    def test_scan_rule_present_on_first_turn(self, env):
        """首轮就要含「逐个文件扫描」铁律（历史上只在非首轮档里）。"""
        prompt, _ = self._build(env, "分析一下这个目录")

        assert "逐个文件扫描" in prompt
        assert "List Integrity" in prompt

    def test_scan_rule_still_present_on_later_turns(self, env):
        """非首轮（精简档）也必须保留准确规则。"""
        prompt, _ = self._build(env, "继续分析", calls=2)

        assert "逐个文件扫描" in prompt

    def test_base_rules_always_present_alongside_identity(self, env):
        """基础规则块必须与公司身份同时存在（组合式，不是二选一）。"""
        prompt, _ = self._build(env, "你好")

        assert "# Disclaimer" in prompt
        assert "# Language Policy" in prompt
        assert "当前工作公司" in prompt, "公司身份/公司信息必须一起注入"

    def test_document_task_gets_full_guide(self, env):
        """文档类任务才注入 FULL（含文档生成指南）。"""
        prompt, _ = self._build(env, "请帮我生成一份报价单文档")

        assert "Document Generation Guidelines" in prompt

    def test_plain_chat_does_not_get_full_guide(self, env):
        """普通问答不背 FULL 的 5700 token。"""
        prompt, _ = self._build(env, "你好")

        assert "Document Generation Guidelines" not in prompt

    def test_library_context_forces_full_scan(self, env):
        """选了文档库时，必须注入「强制扫描此目录所有文件」的上下文指令。"""
        prompt, _ = self._build(env, "看看这批文件", library_id=env["library"]["id"])

        assert "强制扫描" in prompt
        assert "不允许跳过任何文件" in prompt

    def test_explicit_path_forces_read(self, env):
        """问题里点名了具体文件时，注入最高优先级的强制读取指令。"""
        target = env["dir"] / "合同.txt"
        prompt, _ = self._build(env, f"请读一下 {target}")

        assert "用户指定文件（强制读取" in prompt
        assert "禁止跳过任何一个" in prompt
