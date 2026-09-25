"""
Trade AI Assistant — AI 聊天 API 路由。

端点：
  POST /chat         — 同步聊天（线程池 + 600s 超时）
  POST /chat/stream  — SSE 流式聊天（asyncio.Queue + 心跳 + 断连取消）
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from trade import chat_memory
from trade import library as library_module
from trade.api.deps import require_company
from trade.api.models import ChatRequest
from trade.document_task import (
    DocumentTask,
    format_incomplete_report,
    should_enforce_document_gate,
)
from trade.helpers import build_query, create_agent
from trade.hermes_compat import release_read_coverage, snapshot_read_coverage
from trade.read_evidence import ReadEvidenceCollector

_log = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# ── 简单内存限流（per-process，按公司隔离）──────────────────────────────────
# 每个公司 60 秒窗口内最多 20 次 chat 请求（含 sync + SSE）
_MAX_CHAT_PER_MINUTE = 20
_WINDOW_SECONDS = 60.0
_chat_timestamps: dict[int, list[float]] = {}  # company_id → [timestamps]
_rate_limit_lock = threading.Lock()

# 定期清理：每小时扫描一次，删除超过 1 小时无活跃时间戳的 company entry，
# 防止 _chat_timestamps 和 _last_skill_per_company 无界增长导致内存泄漏。
# 阈值 3600s 远大于限流窗口 60s，不会误清活跃公司。
_STALE_THRESHOLD = 3600.0

def _cleanup_rate_limit_dicts():
    while True:
        time.sleep(3600)
        now = time.time()
        with _rate_limit_lock:
            stale = [
                cid for cid, stamps in _chat_timestamps.items()
                if not stamps or all(now - t > _STALE_THRESHOLD for t in stamps)
            ]
            for cid in stale:
                del _chat_timestamps[cid]
        # 同时清理 skill 缓存中超过阈值的 company entry
        with _skill_cache_lock:
            # 只能清理在 _chat_timestamps 中也被清理的条目，
            # 确保活跃公司的 skill 缓存不会被误删
            for cid in stale:
                _last_skill_per_company.pop(cid, None)

# 进程内 skill 缓存：记录每个 company 上次使用的 skill 名称，用于跳过重复注入
_last_skill_per_company: dict[int, str] = {}
_skill_cache_lock = threading.Lock()

_cleanup_thread = threading.Thread(target=_cleanup_rate_limit_dicts, daemon=True)
_cleanup_thread.start()


def _check_chat_rate_limit(company_id: int) -> bool:
    """检查指定公司是否超过 chat 限流阈值。返回 True 表示允许继续。"""
    global _chat_timestamps
    now = time.time()
    with _rate_limit_lock:
        stamps = _chat_timestamps.get(company_id, [])
        stamps = [t for t in stamps if now - t < _WINDOW_SECONDS]
        if len(stamps) >= _MAX_CHAT_PER_MINUTE:
            _chat_timestamps[company_id] = stamps
            return False
        stamps.append(now)
        _chat_timestamps[company_id] = stamps
        return True


def _extract_and_cache_skill(cid: int, full_query: str, skill_hint: str | None) -> str | None:
    """从 build_query 输出中提取当前匹配的 skill 名称并缓存。

    同步和流式端点共享此逻辑，避免重复 ~10 行 regex 提取代码。
    OSINT 场景：skill_hint 中有 "## 当前技能：{name}"
    非 OSINT 场景：full_query 中有 "## 技能触发：{name}"
    """
    import re as _re
    _skill_match = (
        _re.search(r'##\s*当前技能[：:]\s*(\S+)', skill_hint or '') or
        _re.search(r'##\s*技能触发[：:]\s*(\S+)', full_query)
    )
    current_skill = _skill_match.group(1) if _skill_match else None
    with _skill_cache_lock:
        if current_skill:
            _last_skill_per_company[cid] = current_skill
    return current_skill

def _document_gate(document_task, request_task_id: str, collector):
    """取读取证据并判定完成度；两份来源都没有证据时返回 None（降级放行）。

    优先用 Hermes 的读取快照（含页数/Sheet/扫描页等结构化信息）。公开版
    Hermes 没有这个对外接口，回退到工具回调自收集的证据，这样不依赖
    Hermes 上游改动也能做完整性判定。
    """
    hermes_evidence = snapshot_read_coverage(request_task_id)
    if hermes_evidence:
        return document_task.evaluate(hermes_evidence)
    if collector is not None:
        collected = collector.snapshot()
        if collected:
            return document_task.evaluate(collected)
    _log.warning("No read evidence available; document gate skipped")
    return None


# ── 同步聊天 ──────────────────────────────────────────────────────────────

@router.post("/chat")
async def trade_chat(
    payload: ChatRequest,
    cid: int = Depends(require_company),
):
    """同步聊天。"""
    from trade.license import check_license
    lic_ok, lic_msg = check_license(cid)
    if not lic_ok:
        raise HTTPException(status_code=402, detail=lic_msg)

    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    if not _check_chat_rate_limit(cid):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试。")

    # 读取上次使用的 skill 名称（用于跳过重复注入）
    with _skill_cache_lock:
        last_skill = _last_skill_per_company.get(cid)

    full_query, skill_hint = build_query(
        cid, payload.library_id, query, customer_id=payload.customer_id,
        last_skill_name=last_skill, language=payload.language or "zh",
    )

    # 从 full_query 或 skill_hint 中提取当前匹配的 skill 名称并缓存
    current_skill = _extract_and_cache_skill(cid, full_query, skill_hint)
    document_task = None
    if payload.library_id and should_enforce_document_gate(query):
        library = library_module.get(payload.library_id, company_id=cid)
        if library:
            document_task = DocumentTask.from_root(library["root_path"])
            if document_task.truncated or not document_task.files:
                # 目录过大或没有可分析文件：无法可靠判定完整性，退回普通问答。
                _log.info("Document gate skipped (truncated=%s, files=%d)",
                          document_task.truncated, len(document_task.files))
                document_task = None

    _MAX_AGENT_RETRIES = 2  # 最多重试 2 次（共 3 次尝试），与 SSE 流式端点保持一致

    request_task_id = f"trade-doc-{cid}-{time.time_ns()}" if document_task else None
    # 回调收集的证据：公开版 Hermes 没有对外读取快照接口，靠这个兜底。
    evidence = ReadEvidenceCollector() if document_task else None

    def _call_agent() -> tuple[str, bool]:
        """返回 (回复文本, 是否成功)；失败文本不得用于门禁判定。"""
        last_error = ""
        for attempt in range(_MAX_AGENT_RETRIES + 1):
            try:
                agent = create_agent(
                    ephemeral_system_prompt=skill_hint,
                    skill_name=current_skill,
                    tool_start_callback=evidence.on_start if evidence else None,
                    tool_complete_callback=evidence.on_complete if evidence else None,
                )
                if document_task and request_task_id:
                    result = agent.run_conversation(full_query, task_id=request_task_id)["final_response"]
                else:
                    result = agent.chat(full_query)
                if result:
                    return result, True
                if attempt < _MAX_AGENT_RETRIES:
                    _log.warning("Agent returned empty, retry %d/%d", attempt + 1, _MAX_AGENT_RETRIES)
                    time.sleep(2 ** attempt)
                    continue
                return "Agent 返回了空响应。", False
            except ImportError:
                return "⚠️ AI Agent 模块未加载。", False
            except RuntimeError as e:
                last_error = str(e)
                if attempt < _MAX_AGENT_RETRIES:
                    _log.warning("Agent RuntimeError, retry %d/%d: %s", attempt + 1, _MAX_AGENT_RETRIES, e)
                    time.sleep(2 ** attempt)
                    continue
                return f"⚠️ {e}", False
            except Exception as e:
                last_error = str(e) or f"Agent call failed (attempt {attempt + 1})"
                _log.exception("Agent call failed (attempt %d/%d)", attempt + 1, _MAX_AGENT_RETRIES)
                if attempt < _MAX_AGENT_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
        fallback = f"⚠️ Agent 调用失败: {last_error}" if last_error else "⚠️ Agent 调用失败，请稍后重试。"
        return fallback, False

    loop = asyncio.get_running_loop()
    agent_ok = True
    try:
        response, agent_ok = await asyncio.wait_for(
            loop.run_in_executor(None, _call_agent),
            timeout=600,
        )
    except TimeoutError:
        response, agent_ok = "⏰ Agent 执行时间过长（超过 10 分钟），已自动中止。请简化问题后重试。", False

    gate_result = None
    incomplete = False
    if document_task and request_task_id:
        try:
            if agent_ok:
                gate_result = _document_gate(document_task, request_task_id, evidence)
                if gate_result is not None and gate_result.status == "incomplete":
                    # 不通过时把原因作为回答返回，既不丢用户提问也不给不完整结论。
                    incomplete = True
                    response = format_incomplete_report(gate_result)
        finally:
            # 释放 Hermes 侧该请求的读取记录，避免长驻进程内无限累积。
            release_read_coverage(request_task_id)

    lib_name = ""
    if payload.library_id:
        lib = library_module.get(payload.library_id, company_id=cid)
        if lib:
            lib_name = lib["name"]

    conv = chat_memory.save_with_context(
        company_id=cid, library_id=payload.library_id, query=query,
        response=response, library_name=lib_name,
        files_read=([{"file": path, "status": "complete"} for path in gate_result.complete]
                    if gate_result else None),
        context=payload.context or "",
        skill=current_skill or "",
    )
    payload_out = {"response": response, "conversation": conv}
    if gate_result is not None:
        payload_out["analysis_skipped"] = gate_result.skipped
        if incomplete:
            payload_out["analysis_incomplete"] = True
    return payload_out


# ── SSE 流式聊天 ──────────────────────────────────────────────────────────

@router.post("/chat/stream")
async def trade_chat_stream(
    payload: ChatRequest,
    cid: int = Depends(require_company),
):
    """SSE 流式聊天，实时推送 Agent 工具调用进度。

    使用 asyncio.Queue + call_soon_threadsafe 替代 queue.Queue + executor 轮询，
    每条 SSE 连接只占用 1 条线程。客户端断连时通过 CancelledError 取消 agent。
    """
    from trade.license import check_license
    lic_ok, lic_msg = check_license(cid)
    if not lic_ok:
        raise HTTPException(status_code=402, detail=lic_msg)

    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    if not _check_chat_rate_limit(cid):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试。")

    # 读取上次使用的 skill 名称（用于跳过重复注入）
    with _skill_cache_lock:
        last_skill = _last_skill_per_company.get(cid)

    full_query, skill_hint = build_query(
        cid, payload.library_id, query, customer_id=payload.customer_id,
        last_skill_name=last_skill, language=payload.language or "zh",
    )

    # 从 full_query 或 skill_hint 中提取当前匹配的 skill 名称并缓存
    current_skill = _extract_and_cache_skill(cid, full_query, skill_hint)
    document_task = None
    if payload.library_id and should_enforce_document_gate(query):
        library = library_module.get(payload.library_id, company_id=cid)
        if library:
            document_task = DocumentTask.from_root(library["root_path"])
            if document_task.truncated or not document_task.files:
                # 目录过大或没有可分析文件：无法可靠判定完整性，退回普通问答。
                _log.info("Document gate skipped (truncated=%s, files=%d)",
                          document_task.truncated, len(document_task.files))
                document_task = None
    request_task_id = f"trade-doc-{cid}-{time.time_ns()}" if document_task else None
    # 回调收集的证据：公开版 Hermes 没有对外读取快照接口，靠这个兜底。
    evidence = ReadEvidenceCollector() if document_task else None

    loop = asyncio.get_running_loop()
    event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    def _emit_threadsafe(event_type: str, data: dict | None = None):
        """工作线程通过 call_soon_threadsafe 投递到 asyncio queue。

        put_nowait 在队列满时抛出 QueueFull，用 call_soon_threadsafe 回调时不好捕获，
        改为 queue.put_nowait 包装在一次非阻塞 try 中，满则静默丢弃（优先保持 SSE 连接稳定）。
        """
        def _safe_put(ev_type, ev_data):
            try:
                event_queue.put_nowait((ev_type, ev_data))
            except asyncio.QueueFull:
                _log.warning("SSE event queue full, dropping event: %s", ev_type)

        loop.call_soon_threadsafe(_safe_put, event_type, data or {})

    def _tool_start(tc_id, name, args):
        if evidence is not None:
            evidence.on_start(tc_id, name, args)
        _emit_threadsafe("tool_start", {"tool_call_id": tc_id, "name": name, "args": args})

    def _tool_complete(tc_id, name, args, result):
        # 证据收集与 SSE 推送解耦：队列满丢事件不影响完整性判定。
        if evidence is not None:
            evidence.on_complete(tc_id, name, args, result)
        preview = ""
        if isinstance(result, str):
            preview = result[:300]
        elif isinstance(result, (list, dict)):
            preview = _json.dumps(result, ensure_ascii=False)[:300]
        _emit_threadsafe("tool_complete", {
            "tool_call_id": tc_id, "name": name, "result_preview": preview,
        })

    _MAX_AGENT_RETRIES = 2
    cancel_event = threading.Event()  # 客户端断连时置位，阻止重试继续浪费 token

    def _run_agent() -> str | None:
        last_error = ""
        for attempt in range(_MAX_AGENT_RETRIES + 1):
            # 客户端已断连，立即停止重试循环
            if cancel_event.is_set():
                _log.info("Agent cancelled by client disconnect, attempt %d", attempt + 1)
                return None
            try:
                if attempt == 0:
                    _emit_threadsafe("thinking", {"message": "正在分析问题..."})
                else:
                    _emit_threadsafe("thinking", {"message": f"正在重试（第 {attempt} 次）..."})
                agent = create_agent(
                    tool_start_callback=_tool_start,
                    tool_complete_callback=_tool_complete,
                    ephemeral_system_prompt=skill_hint,
                    skill_name=current_skill,
                )
                start = time.time()
                if document_task and request_task_id:
                    result = agent.run_conversation(full_query, task_id=request_task_id)["final_response"]
                else:
                    result = agent.chat(full_query)
                elapsed = time.time() - start

                if not result and attempt < _MAX_AGENT_RETRIES:
                    if cancel_event.is_set():
                        return None
                    _log.warning("Agent returned empty in stream, retry %d/%d", attempt + 1, _MAX_AGENT_RETRIES)
                    time.sleep(2 ** attempt)
                    continue

                gate_result = None
                if document_task and request_task_id and result:
                    try:
                        gate_result = _document_gate(document_task, request_task_id, evidence)
                        if gate_result is not None:
                            if gate_result.status == "incomplete":
                                # 不通过时把原因作为回答下发，不报错也不给不完整结论。
                                result = format_incomplete_report(gate_result)
                            _emit_threadsafe("analysis_gate", {
                                "status": gate_result.status,
                                "files": gate_result.complete,
                                "missing": gate_result.missing,
                                "errors": gate_result.errors,
                                "skipped": gate_result.skipped,
                            })
                    finally:
                        # 释放 Hermes 侧该请求的读取记录，避免长驻进程内无限累积。
                        release_read_coverage(request_task_id)

                lib_name = ""
                if payload.library_id:
                    lib = library_module.get(payload.library_id, company_id=cid)
                    if lib:
                        lib_name = lib["name"]

                # 先保存对话，再发送响应 —— 确保前端能拿到 conversation_id 做评分
                conv_id = None
                try:
                    conv = chat_memory.save_with_context(
                        company_id=cid, library_id=payload.library_id,
                        query=query, response=result or "",
                        library_name=lib_name,
                        files_read=([{"file": path, "status": "complete"} for path in gate_result.complete]
                                    if gate_result else None),
                        context=payload.context or "",
                        skill=current_skill or "",
                    )
                    if conv:
                        conv_id = conv.get("id")
                except Exception:
                    _log.exception("save_with_context failed in stream")

                _emit_threadsafe("response", {
                    "text": result or "Agent 返回了空响应。",
                    "elapsed_sec": round(elapsed, 1),
                    "conversation_id": conv_id,
                })
                return result
            except ImportError:
                _emit_threadsafe("error", {"message": "AI Agent 模块未加载。"})
                return None
            except RuntimeError as e:
                last_error = str(e)
                if attempt < _MAX_AGENT_RETRIES and not cancel_event.is_set():
                    _log.warning("Agent RuntimeError in stream, retry %d/%d: %s", attempt + 1, _MAX_AGENT_RETRIES, e)
                    time.sleep(2 ** attempt)
                    continue
                _emit_threadsafe("error", {"message": last_error})
                return None
            except Exception as e:
                last_error = str(e) or f"Agent stream failed (attempt {attempt + 1})"
                _log.exception("Agent stream failed (attempt %d/%d)", attempt + 1, _MAX_AGENT_RETRIES)
                if attempt < _MAX_AGENT_RETRIES and not cancel_event.is_set():
                    time.sleep(2 ** attempt)
                    continue
                _emit_threadsafe("error", {"message": f"⚠️ {last_error}"})
                return None
        _emit_threadsafe("error", {"message": "Agent 重试耗尽，请稍后重试。"})
        return None

    async def _event_stream():
        def _sse(ev_type: str, payload: dict) -> str:
            return f"event: {ev_type}\ndata: {_json.dumps(payload, ensure_ascii=False)}\n\n"

        agent_task = loop.run_in_executor(None, _run_agent)
        # 30 分钟 Agent 兜底超时 — 网站诊断等长任务也应在 30min 内完成
        # 超时后发 error 事件并取消 agent，防止永久挂起
        deadline = time.time() + 1800
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    _emit_threadsafe("error", {"message": "⏰ Agent 执行超过 30 分钟，已自动中止。请简化问题或联系支持。"})
                    break
                try:
                    # 取 15s 心跳与剩余 deadline 的较小值，确保 deadline 到期时能及时触发
                    wait_sec = min(15.0, remaining)
                    ev_type, ev_data = await asyncio.wait_for(event_queue.get(), timeout=wait_sec)
                except TimeoutError:
                    if agent_task.done():
                        break
                    yield ": ping\n\n"
                    continue

                yield _sse(ev_type, ev_data)
                if ev_type in ("response", "error"):
                    break
        finally:
            # 客户端断连或异常 → 先发取消信号让 Agent 线程尽快退出重试循环，
            # 减少 token 浪费。线程池中的 agent.chat() 无法被中断，
            # 但重试和后续 emit 会被跳过。
            cancel_event.set()
            if not agent_task.done():
                agent_task.cancel()
                try:
                    await agent_task
                except (asyncio.CancelledError, Exception):
                    pass
            yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )
