"""文档完整读取门禁的端点行为测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def env(monkeypatch, tmp_path):
    """准备临时数据库、公司和文档库。"""
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
    company = co.create(name="Gate Co", slug="gate-co")

    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    # 纯文本：不依赖文档解析器，适合验证「agent 漏读」判定
    (lib_dir / "合同.txt").write_text("甲\n乙\n", encoding="utf-8")
    (lib_dir / "报价.xlsx").write_bytes(b"PK\x03\x04demo")
    (lib_dir / ".DS_Store").write_bytes(b"\x00\x01")

    import trade.library as lib
    library = lib.create("报价库", str(lib_dir), company_id=company["id"])
    return {"cid": company["id"], "library": library, "dir": lib_dir}


@pytest.fixture
def agent_stub():
    """返回固定回答的 Agent 替身。"""
    stub = MagicMock()
    stub.chat.return_value = "分析完成"
    stub.run_conversation.return_value = {"final_response": "分析完成"}
    return stub


async def _call_chat(env, agent_stub, query, evidence, saved):
    """调用同步聊天端点，返回结果或抛出的 HTTPException。"""
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    def _save(**kwargs):
        saved.append(kwargs)
        return {"id": 1}

    with patch.object(chat, "create_agent", return_value=agent_stub), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat, "snapshot_read_coverage", return_value=evidence), \
         patch("trade.license.check_license", return_value=(True, "")), \
         patch.object(chat.chat_memory, "save_with_context", side_effect=_save):
        payload = ChatRequest(query=query, library_id=env["library"]["id"])
        return await chat.trade_chat(payload, env["cid"])


STRICT_QUERY = "请完整读取这个目录的所有文件"


@pytest.mark.asyncio
async def test_hermes_without_evidence_api_degrades_instead_of_blocking(env, agent_stub):
    """Hermes 未提供读取证据接口时应正常回答，不能把功能整体拦死。"""
    saved = []
    result = await _call_chat(env, agent_stub, STRICT_QUERY, None, saved)

    assert result["response"] == "分析完成"
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_complete_evidence_returns_answer_and_audit(env, agent_stub):
    """可分析文件全部读完时返回答案，并记录读取清单与跳过文件。"""
    saved = []
    evidence = {
        str((env["dir"] / "合同.txt").resolve()): {"status": "complete", "complete": True},
        str((env["dir"] / "报价.xlsx").resolve()): {
            "status": "complete", "complete": True,
            "document_metadata": {"kind": "xlsx", "sheets": ["Sheet1"]},
        },
    }
    result = await _call_chat(env, agent_stub, STRICT_QUERY, evidence, saved)

    assert result["response"] == "分析完成"
    assert saved[0]["files_read"] == [
        {"file": "合同.txt", "status": "complete"},
        {"file": "报价.xlsx", "status": "complete"},
    ]
    assert result["analysis_skipped"] == [
        {"file": ".DS_Store", "reason": "hidden_file"}]


@pytest.mark.asyncio
async def test_incomplete_returns_reason_as_answer_and_keeps_question(env, agent_stub):
    """未读完时把原因作为回答返回，并保留用户提问的痕迹。"""
    saved = []
    evidence = {
        # 读了别的文件，但没有读资料库里的 xlsx
        str((env["dir"] / ".." / "other.txt").resolve()): {"complete": True},
    }
    result = await _call_chat(env, agent_stub, STRICT_QUERY, evidence, saved)

    assert "报价.xlsx" in result["response"]
    assert "未读完" in result["response"]
    assert result["analysis_incomplete"] is True
    assert len(saved) == 1
    assert saved[0]["query"] == STRICT_QUERY


@pytest.mark.asyncio
async def test_no_read_evidence_degrades_instead_of_failing(env, agent_stub):
    """完全没有读取证据时不判失败，避免把正常问答误拦。"""
    saved = []
    result = await _call_chat(env, agent_stub, STRICT_QUERY, {}, saved)

    assert result["response"] == "分析完成"
    assert "analysis_incomplete" not in result


@pytest.mark.asyncio
async def test_error_response_is_not_saved_as_complete_analysis(env, agent_stub):
    """Agent 失败/超时的文案不能被当成完整分析结论。"""
    agent_stub.chat.return_value = ""
    agent_stub.run_conversation.return_value = {"final_response": ""}
    saved = []
    evidence = {
        str((env["dir"] / "合同.txt").resolve()): {"status": "complete", "complete": True},
        str((env["dir"] / "报价.xlsx").resolve()): {
            "status": "complete", "complete": True,
            "document_metadata": {"kind": "xlsx", "sheets": ["Sheet1"]},
        },
    }
    result = await _call_chat(env, agent_stub, STRICT_QUERY, evidence, saved)

    assert "空响应" in result["response"]
    assert saved[0]["files_read"] is None


def _agent_reporting_reads(reads, captured):
    """替身 agent：运行期间通过回调上报指定的读取结果。"""
    import json

    class _Agent:
        def run_conversation(self, *_a, **_k):
            callback = captured.get("tool_complete_callback")
            for path, payload in reads:
                callback("1", "read_file", {"path": str(path)}, json.dumps(payload))
            return {"final_response": "分析完成"}

        def chat(self, *_a, **_k):
            return "分析完成"

    return _Agent()


@pytest.mark.asyncio
async def test_gate_falls_back_to_callbacks_without_hermes_api(env):
    """公开版 Hermes 没有读取快照接口时，用工具回调自收集的证据做门禁。"""
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    captured = {}
    saved = []
    reads = [
        (env["dir"] / "合同.txt", {"total_lines": 2, "truncated": False}),
        (env["dir"] / "报价.xlsx", {"total_lines": 5, "truncated": False,
                                    "extracted_document": True}),
    ]

    def _create(**kwargs):
        captured.update(kwargs)
        return _agent_reporting_reads(reads, captured)

    with patch.object(chat, "create_agent", side_effect=_create), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat, "snapshot_read_coverage", return_value=None), \
         patch("trade.license.check_license", return_value=(True, "")), \
         patch.object(chat.chat_memory, "save_with_context",
                      side_effect=lambda **k: saved.append(k) or {"id": 1}):
        payload = ChatRequest(query=STRICT_QUERY, library_id=env["library"]["id"])
        result = await chat.trade_chat(payload, env["cid"])

    assert result["response"] == "分析完成"
    assert set(saved[0]["files_read"] and [f["file"] for f in saved[0]["files_read"]]) == {
        "合同.txt", "报价.xlsx"}


@pytest.mark.asyncio
async def test_callback_gate_blocks_skipped_file(env):
    """回调路径同样能发现 agent 漏读：只读了其中一个文件就判不通过。"""
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    captured = {}
    saved = []
    reads = [(env["dir"] / "合同.txt", {"total_lines": 2, "truncated": False})]

    with patch.object(chat, "create_agent",
                      side_effect=lambda **kw: (captured.update(kw),
                                                _agent_reporting_reads(reads, captured))[1]), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat, "snapshot_read_coverage", return_value=None), \
         patch("trade.license.check_license", return_value=(True, "")), \
         patch.object(chat.chat_memory, "save_with_context",
                      side_effect=lambda **k: saved.append(k) or {"id": 1}):
        payload = ChatRequest(query=STRICT_QUERY, library_id=env["library"]["id"])
        result = await chat.trade_chat(payload, env["cid"])

    assert "报价.xlsx" in result["response"]
    assert result["analysis_incomplete"] is True


@pytest.mark.asyncio
async def test_hermes_snapshot_wins_over_callbacks(env):
    """Hermes 快照可用时优先用它（信息更全，含扫描页等结构化字段）。"""
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    captured = {}
    saved = []
    # 回调只上报读了合同.txt；快照里两个文件都读完 —— 应以快照为准
    reads = [(env["dir"] / "合同.txt", {"total_lines": 2, "truncated": False})]
    snapshot = {
        str((env["dir"] / "合同.txt").resolve()): {
            "status": "complete", "complete": True, "source": "hermes"},
        str((env["dir"] / "报价.xlsx").resolve()): {
            "status": "complete", "complete": True, "source": "hermes",
            "document_metadata": {"kind": "xlsx", "sheets": ["Sheet1"]}},
    }

    with patch.object(chat, "create_agent",
                      side_effect=lambda **kw: (captured.update(kw),
                                                _agent_reporting_reads(reads, captured))[1]), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat, "snapshot_read_coverage", return_value=snapshot), \
         patch("trade.license.check_license", return_value=(True, "")), \
         patch.object(chat.chat_memory, "save_with_context",
                      side_effect=lambda **k: saved.append(k) or {"id": 1}):
        payload = ChatRequest(query=STRICT_QUERY, library_id=env["library"]["id"])
        result = await chat.trade_chat(payload, env["cid"])

    assert result["response"] == "分析完成"
    assert "analysis_incomplete" not in result


@pytest.mark.asyncio
async def test_normal_chat_skips_gate(env, agent_stub):
    """普通提问不启用门禁，保持原有行为。"""
    saved = []
    result = await _call_chat(env, agent_stub, "逐个介绍一下你们的产品线", {}, saved)

    assert result["response"] == "分析完成"
    assert saved[0]["files_read"] is None


@pytest.mark.asyncio
async def test_gate_releases_hermes_task_record(env, agent_stub):
    """门禁结束后必须释放 Hermes 侧读取记录，避免长驻进程内累积。"""
    import trade.api.chat as chat

    released = []
    evidence = {
        str((env["dir"] / "合同.txt").resolve()): {"status": "complete", "complete": True},
        str((env["dir"] / "报价.xlsx").resolve()): {
            "status": "complete", "complete": True,
            "document_metadata": {"kind": "xlsx", "sheets": ["Sheet1"]},
        },
    }
    with patch.object(chat, "create_agent", return_value=agent_stub), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat, "snapshot_read_coverage", return_value=evidence), \
         patch.object(chat, "release_read_coverage", side_effect=released.append), \
         patch("trade.license.check_license", return_value=(True, "")), \
         patch.object(chat.chat_memory, "save_with_context", return_value={"id": 1}):
        from trade.api.models import ChatRequest
        payload = ChatRequest(query=STRICT_QUERY, library_id=env["library"]["id"])
        await chat.trade_chat(payload, env["cid"])

    assert released and released[0].startswith("trade-doc-")


async def _collect_stream(env, agent_stub, query, evidence):
    """消费 SSE 流，返回 (事件名, 数据) 列表。

    mock 必须覆盖整个消费过程：生成器在 StreamingResponse 返回之后才真正执行。
    """
    import trade.api.chat as chat
    from trade.api.models import ChatRequest

    events = []
    with patch.object(chat, "create_agent", return_value=agent_stub), \
         patch.object(chat, "build_query", return_value=("Q", "H")), \
         patch.object(chat, "snapshot_read_coverage", return_value=evidence), \
         patch.object(chat, "release_read_coverage"), \
         patch("trade.license.check_license", return_value=(True, "")), \
         patch.object(chat.chat_memory, "save_with_context", return_value={"id": 1}):
        payload = ChatRequest(query=query, library_id=env["library"]["id"])
        response = await chat.trade_chat_stream(payload, env["cid"])
        async for chunk in response.body_iterator:
            text = chunk.decode() if isinstance(chunk, bytes) else chunk
            for block in text.split("\n\n"):
                lines = [ln for ln in block.splitlines() if ln]
                if not lines:
                    continue
                name = next((ln[7:] for ln in lines if ln.startswith("event: ")), "")
                data = next((ln[6:] for ln in lines if ln.startswith("data: ")), "")
                if name:
                    events.append((name, data))
    return events


@pytest.mark.asyncio
async def test_stream_degrades_when_evidence_api_missing(env, agent_stub):
    """SSE 在 Hermes 缺证据接口时仍要给出回答，而不是只报错。"""
    events = await _collect_stream(env, agent_stub, STRICT_QUERY, None)
    names = [name for name, _ in events]

    assert "response" in names
    assert "error" not in names


@pytest.mark.asyncio
async def test_stream_incomplete_returns_reason_as_response(env, agent_stub):
    """SSE 未读完时把原因作为回答下发，不报错也不给分析结论。"""
    evidence = {
        str((env["dir"] / "报价.xlsx").resolve()): {
            "status": "complete", "complete": True,
            "document_metadata": {"kind": "xlsx", "sheets": ["Sheet1"]},
        },
    }
    events = await _collect_stream(env, agent_stub, STRICT_QUERY, evidence)
    names = [name for name, _ in events]
    payloads = dict(events)

    assert "analysis_gate" in names
    assert "response" in names
    assert "error" not in names
    assert "合同.txt" in payloads["response"]


@pytest.mark.asyncio
async def test_stream_complete_emits_gate_then_response(env, agent_stub):
    """SSE 读完时先通过门禁，再下发回答。"""
    evidence = {
        str((env["dir"] / "合同.txt").resolve()): {"status": "complete", "complete": True},
        str((env["dir"] / "报价.xlsx").resolve()): {
            "status": "complete", "complete": True,
            "document_metadata": {"kind": "xlsx", "sheets": ["Sheet1"]},
        },
    }
    events = await _collect_stream(env, agent_stub, STRICT_QUERY, evidence)
    names = [name for name, _ in events]

    assert "analysis_gate" in names
    assert "response" in names
    assert names.index("analysis_gate") < names.index("response")
