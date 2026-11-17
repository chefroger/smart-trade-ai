"""doc_skip 旁路回归：不再只拦 read_file，按路径扫描所有工具参数。

复现清单（2026-11-13，trade 修前实测）：
- read_file：对照组，必须拦
- terminal：`cat <path>`，修前拦住失败
- execute_code：`open(<path>).read()`，修前拦住失败
- search_files：`path=<path>` 内容搜索，修前拦住失败
- delegate_task：嵌套任务 goal/context 含路径，修前拦住失败
"""

from __future__ import annotations

import pytest

from trade.hermes_chat_memory_plugin import doc_skip


@pytest.fixture(autouse=True)
def _trade_host(monkeypatch):
    """沿用 test_doc_gate_cache.py 的做法：钩子只在 TRADE_HOST=1 时生效。"""
    monkeypatch.setenv("TRADE_HOST", "1")
    doc_skip._skips.clear()
    yield
    doc_skip._skips.clear()


@pytest.fixture
def target(tmp_path):
    path = tmp_path / "repro.txt"
    path.write_text("REPRO_MARKER\n", encoding="utf-8")
    doc_skip.register("task-1", [str(path)])
    return path


def _blocked(tool: str, args, task_id: str = "task-1") -> bool:
    result = doc_skip.on_pre_tool_call(tool, args, task_id=task_id)
    return bool(result and result.get("action") == "block")


def test_read_file_still_blocked(target):
    assert _blocked("read_file", {"path": str(target)})


def test_terminal_command_blocked(target):
    assert _blocked("terminal", {"command": f"cat {target}"})


def test_execute_code_blocked(target):
    code = f"print(open({str(target)!r}).read())"
    assert _blocked("execute_code", {"code": code})


def test_search_files_path_blocked(target):
    assert _blocked("search_files", {
        "pattern": "REPRO_MARKER", "target": "content", "path": str(target),
    })


def test_delegate_task_nested_args_blocked(target):
    args = {
        "tasks": [{
            "goal": "读取这个文件并回报第一行",
            "context": f"文件路径：{target}",
        }],
    }
    assert _blocked("delegate_task", args)


def test_unrelated_file_not_blocked(target, tmp_path):
    other = tmp_path / "other.txt"
    other.write_text("OTHER\n", encoding="utf-8")
    assert not _blocked("terminal", {"command": f"cat {other}"})


def test_tool_without_skipped_path_not_blocked(target):
    assert not _blocked("terminal", {"command": "ls -la /tmp"})
    assert not _blocked("terminal", {})
    assert not _blocked("write_file", {"path": "/tmp/unrelated.txt", "content": "x"})


def test_release_stops_blocking(target):
    doc_skip.release("task-1")
    assert not _blocked("terminal", {"command": f"cat {target}"})


def test_fail_open_on_unexpected_args():
    assert doc_skip.on_pre_tool_call("terminal", object(), task_id="task-1") is None


def test_inactive_outside_trade_host(target, monkeypatch):
    """TRADE_HOST 未设时钩子直接放行（不影响用户自己的 Hermes）。"""
    monkeypatch.delenv("TRADE_HOST", raising=False)
    assert not _blocked("read_file", {"path": str(target)})
    assert not _blocked("terminal", {"command": f"cat {target}"})


# ── 路径写法归一（agentbase Windows CI 真实失败过的用例）──────────────────
# Windows 下 repr() 会把反斜杠写成两个（'C:\\Users\\x'），needle 与 haystack
# 若不归一就永远匹配不上；命令里混用正斜杠同理。

_WIN_PATH = r"C:\Users\runneradmin\AppData\Local\Temp\repro.txt"


def test_windows_path_blocked_even_when_repr_escapes_backslashes():
    doc_skip.register("task-win", [_WIN_PATH])
    code = f"print(open({_WIN_PATH!r}).read())"
    assert _blocked("execute_code", {"code": code}, task_id="task-win")


def test_windows_path_blocked_when_written_with_forward_slashes():
    doc_skip.register("task-win2", [_WIN_PATH])
    forward = _WIN_PATH.replace("\\", "/")
    assert _blocked("terminal", {"command": f"cat {forward}"}, task_id="task-win2")


def test_separator_spelling_variant_blocked(target):
    """同一文件用反斜杠写（Windows 风格）也要拦。"""
    doc_skip.register("task-sep", [str(target).replace("/", "\\")])
    assert _blocked("terminal", {"command": f"cat {target}"}, task_id="task-sep")


def test_unrelated_windows_path_not_blocked():
    doc_skip.register("task-win3", [_WIN_PATH])
    other = r"C:\Users\runneradmin\AppData\Local\Temp\other.txt"
    assert not _blocked("terminal", {"command": f"cat {other}"}, task_id="task-win3")
