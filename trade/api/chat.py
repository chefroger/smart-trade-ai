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
import re
import sqlite3
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse

from trade import chat_memory, doc_cache
from trade import library as library_module
from trade import usage as usage_module
from trade.agent_context import bind_company, bind_tool_evidence, extract_user_paths
from trade.api.deps import require_company
from trade.api.models import ChatRequest
from trade.chat_blocks import parse_trade_json_blocks
from trade.database import get_connection
from trade.doc_extract import resolve_extraction_model, warm_cache
from trade.doc_scope import (
    SCOPE_LOCATE,
    SCOPE_SUMMARY,
    detect_request_scope,
    scope_allows_cache,
)
from trade.document_task import (
    DocumentTask,
    format_incomplete_report,
    should_enforce_document_gate,
)
from trade.helpers import build_query, configured_run_budget_seconds, create_agent
from trade.hermes_chat_memory_plugin.doc_skip import register as register_doc_skip
from trade.hermes_chat_memory_plugin.doc_skip import release as release_doc_skip
from trade.hermes_compat import release_read_coverage, snapshot_read_coverage
from trade.partial_report import (
    CompletedToolTracker,
    build_partial_report,
    build_summary_prompt,
)
from trade.prompt import detect_reply_language
from trade.read_evidence import ReadEvidenceCollector

_log = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# SSE 流的 agent 兜底超时（秒）。网站诊断等长任务也应在该时限内完成；
# 超时后必须下发 error 事件并中止 agent，不能让流无声结束。
# 提为模块常量是为了可测 —— 超时路径以前没有测试覆盖（它的 error 事件曾被丢弃）。
_STREAM_DEADLINE_SECONDS = 1800.0

# 同步聊天的 Agent 兜底超时（秒）。提为模块常量以便测试缩短。
_SYNC_TIMEOUT_SECONDS = 600.0
# 给「总结/收尾」留出的余量：预算必须小于外层超时，否则 Hermes 按 1500s
# 计划收尾，外层 600s 先到 → 用户只拿到超时中止（审计 P2-5）。
_SYNC_BUDGET_MARGIN_SECONDS = 60


def _sync_run_budget() -> int | None:
    """同步端点的单轮预算 = min(配置值, 外层超时 - 余量)。

    用户显式调低预算时尊重更小的值；关闭预算（0/负数）时返回 None 不传。
    下限 30s：测试会把超时缩到亚秒级，不能算出 0/负数。
    """
    budget = configured_run_budget_seconds()
    if budget is None:
        return None
    cap = int(_SYNC_TIMEOUT_SECONDS - _SYNC_BUDGET_MARGIN_SECONDS)
    return max(30, min(budget, cap))


def _external_paths_hint(paths: list[str]) -> str:
    """用户本轮贴出外部文件时追加的提示：只读授权 + 敏感信息不复述。"""
    listed = "\n".join(f"- {p}" for p in paths)
    return (
        "## 本轮用户显式贴出的文件\n"
        "用户已在消息里亲手给出下列文件路径，本轮可只读访问这些精确文件：\n"
        f"{listed}\n"
        "只能读这些文件本身，不能据此访问目录、其它文件或执行它们。\n"
        "回答或写草稿时不要复述密码、密钥、token 原文；需要提及时打码或只讲结论。"
    )


# ── OSINT 交付兜底（2026-11-23 工单 P0-C）──────────────────────────────────
_OSINT_SKILL = "b2b-osint"
# 算「成功跑过制裁筛查」的工具：后台任务启动即可（它自带制裁层），
# 或 terminal 里显式跑 trade.osint。
_OSINT_TOOL_NAMES = frozenset({"osint_job_start", "osint_job_result"})
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_DOMAIN_RE = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.IGNORECASE)


def _osint_target_from_query(query: str) -> str | None:
    """从用户问题里取制裁筛查对象（显式前缀 > 邮箱 > 人名 > 域名 > 短问题）。

    取不到就返回 None —— 宁可如实写「未执行」，也不要拿整句话去比对名单。
    """
    text = " ".join(str(query or "").split())
    if not text:
        return None
    try:
        from trade.osint.orchestrator import _split_type_prefix, _split_username_prefix
        from trade.skill_router import extract_osint_name

        target, forced = _split_type_prefix(text)
        target, _ = _split_username_prefix(target)
        name = extract_osint_name(target)
        if forced and target:
            # 显式前缀后可能还跟着问句（company:Acme Trading 有没有被制裁）：
            # 能从剩余文本里取出名字就用名字，否则整段就是目标。
            return name or target
        match = _EMAIL_RE.search(text)
        if match:
            return match.group(0)
        if name:
            return name
        match = _DOMAIN_RE.search(text)
        if match:
            return match.group(0)
        # 很短的问题本身就是目标（如「天津赛得」）
        if len(text) <= 30:
            return text
    except Exception:
        _log.exception("提取 OSINT 目标失败")
    return None


def _osint_sanctions_used(tools: CompletedToolTracker) -> bool:
    """本轮是否成功调用过 OSINT 工具（后台任务或 terminal 跑 trade.osint）。"""
    for item in tools.snapshot():
        name = str(item.get("name") or "")
        if name in _OSINT_TOOL_NAMES:
            return True
        if name in ("terminal", "bash", "execute_code"):
            detail = str(item.get("detail") or "")
            if "trade.osint" in detail or "osint_job" in detail:
                return True
    return False


def _sanctions_fallback_text(query: str) -> str:
    """用本地制裁库补一段结论（<1 秒，无网络下载）。"""
    target = _osint_target_from_query(query)
    if not target:
        return "制裁名单筛查：未执行（无法从问题中确定筛查对象）"
    try:
        from trade.osint.sanctions import check_sanctions

        result = check_sanctions(target)
    except Exception as exc:  # noqa: BLE001 —— 兜底失败不能影响主回答
        _log.exception("交付前制裁兜底失败")
        return f"制裁名单筛查：未执行（{type(exc).__name__}: {exc}）"

    coverage = result.get("coverage") or {}
    if coverage.get("degraded", True):
        return "制裁名单筛查：未执行（本地名单未就绪，不构成「无制裁记录」的结论）"
    lists = coverage.get("lists") or {}
    total = int(coverage.get("total_entries") or 0)
    stale = [
        f"{info.get('label', code)} 过期 {float(info.get('stale_hours') or 0):.0f} 小时"
        for code, info in lists.items()
        if info.get("stale")
    ]
    stale_note = ("；" + "、".join(stale[:3])) if stale else ""
    hits = result.get("hits") or []
    if result.get("is_sanctioned"):
        top = "、".join(
            f"{hit.get('list_label') or hit.get('list')}: {hit.get('matched_value')}"
            for hit in hits[:3]
        )
        return f"制裁名单筛查：⚠️ 命中（{top}）。强烈建议拒绝交易或咨询法律部门。"
    if hits:
        return f"制裁名单筛查：发现 {len(hits)} 条疑似匹配（非精确），需人工核查。"
    return (
        f"制裁名单筛查：未命中（已比对 {len(lists)} 份名单、本地 {total} 条"
        f"{stale_note}）。"
    )


def _ensure_sanctions_section(
    *, query: str, response: str, skill: str, tools: CompletedToolTracker,
) -> str:
    """命中 b2b-osint 但没跑过 OSINT 工具、或缺制裁段落时，补一段本地结论。

    条件（工单 P0-C）：本轮命中 OSINT，且
      - 没有成功调用过 osint_job_start / trade.osint，或
      - 回答里没有「制裁」段落。
    两个条件都满足（工具跑过且回答已写制裁）才跳过。
    """
    if skill != _OSINT_SKILL or not response:
        return response
    if _osint_sanctions_used(tools) and "制裁" in response:
        return response
    return f"{response}\n\n【制裁名单筛查】\n{_sanctions_fallback_text(query)}"


def _path_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _classify_user_paths(query: str, cid: int) -> list[str]:
    """用户本轮亲手贴出、且允许 AI 只读访问的文件清单。

    2026-10-29 起不再有「待确认」往返：用户贴出路径本身就是授权
    （自己电脑上的自己的文件，不需要再打一句「确认读取」）。
    仍保留一条：~/.trade 下但不是本公司目录（其它公司/全局数据）不进清单 ——
    多公司隔离是产品口径，不因放宽守卫而放开。
    """
    from trade.helpers import _allowed_path_roots
    from trade.post_install.skills import _get_trade_home

    paths = extract_user_paths(query)
    if not paths:
        return []

    roots: list[Path] = []
    try:
        for root in _allowed_path_roots(cid):
            try:
                roots.append(Path(root).resolve())
            except OSError:
                continue
    except Exception:
        roots = []
    try:
        trade_home = Path(_get_trade_home()).resolve()
    except Exception:
        trade_home = None

    allowed: list[str] = []
    for raw in paths:
        path = Path(raw)
        # ~/.trade 下、但不是本公司目录：其它公司数据 / 全局数据，硬拦
        if trade_home is not None and _path_under(path, trade_home) and not any(
            _path_under(path, root) for root in roots
        ):
            continue
        allowed.append(raw)
    return allowed


def _abort_running_agent(agent) -> None:
    """超时 / 客户端放弃后，尽力让仍在跑的 agent 停下来（审计 P1-21）。

    只 set 一个取消标记是不够的：`run_in_executor` 的 Future 取消**停不掉线程**，
    `agent.chat()` 里正在执行的工具调用会继续跑、继续烧 token。Hermes 提供了
    跨线程的 `interrupt()` / `hard_interrupt()`（工具侧按线程检查中断位），
    这是唯一真正能让工具停下的手段。

    但它们是上游内部 API：新旧版本可能没有。拿不到就只靠调用方的取消标记
    挡住重试与落库 —— 中断失败绝不能让超时响应变成 500。
    """
    if agent is None:
        return
    for attempt in (
        lambda: agent.hard_interrupt("trade: request timed out"),
        lambda: agent.interrupt("trade: request timed out", hard_cancel=True),
        lambda: agent.interrupt("trade: request timed out"),
    ):
        try:
            attempt()
            return
        except (AttributeError, TypeError):
            continue  # 该版本没有这个方法/签名，换下一种
        except Exception:
            _log.warning("Failed to interrupt timed-out agent", exc_info=True)
            return

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

def _validate_scope(payload, cid: int) -> None:
    """校验 payload 里的 customer_id / library_id 属于当前公司。

    不校验会在切公司后产生"公司 B + 客户 A"的错标行，之后按客户过滤时
    反而把它当作 A 的历史读出（2026-10-25 审计 P1-19）。
    """
    if payload.customer_id is not None:
        from trade import customer as customer_module

        if not customer_module.get(payload.customer_id, company_id=cid):
            raise HTTPException(
                status_code=400,
                detail="customer_id does not belong to the current company.",
            )
    if payload.library_id is not None:
        if not library_module.get(payload.library_id, company_id=cid):
            raise HTTPException(
                status_code=400,
                detail="library_id does not belong to the current company.",
            )


def _parse_osint_job_attachment(result) -> dict | None:
    """从 osint_job_start 的返回值里取出 {job_id,target}（只认插件自己的 JSON 结构）。

    工具返回值经 SSE 的 result_preview 截断到 300 字符，前端解析不可靠，
    所以由后端在 tool_complete 之后补发一条 job_attached。
    """
    data = result
    if isinstance(data, str):
        try:
            data = _json.loads(data)
        except ValueError:
            return None
    if not isinstance(data, dict):
        return None
    job_id = data.get("job_id")
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        return None
    return {
        "job_id": job_id,
        "target": str(data.get("target") or "")[:200],
        # 复用 10 分钟内的已完成任务时，前端不该挂一个永远不动的 task 面板
        "status": str(data.get("status") or "")[:20],
    }


def _document_gate(
    document_task,
    request_task_id: str,
    collector,
    *,
    request_scope: str = "full_read",
    cache_evidence: dict | None = None,
):
    """取读取证据并判定完成度；两份来源都没有证据时返回 None（降级放行）。

    优先用 Hermes 的读取快照（含页数/Sheet/扫描页等结构化信息）。公开版
    Hermes 没有这个对外接口，回退到工具回调自收集的证据，这样不依赖
    Hermes 上游改动也能做完整性判定。

    `cache_evidence` 只覆盖本次跳过的文件；同一文件若本次真的读了，
    全文证据覆盖缓存证据（缓存不得冒充全文已读）。
    """
    evidence: dict = dict(cache_evidence or {})
    hermes_evidence = snapshot_read_coverage(request_task_id)
    if hermes_evidence:
        evidence.update(hermes_evidence)
    elif collector is not None:
        collected = collector.snapshot()
        if collected:
            evidence.update(collected)
    if not evidence:
        _log.warning("No read evidence available; document gate skipped")
        return None
    return document_task.evaluate(evidence, request_scope=request_scope)


_MAX_CACHE_PROMPT_FILES = 30
_MAX_CACHE_SUMMARY_CHARS = 300


def _load_cache_hits(document_task, tenant_id: int, request_scope: str):
    """查本租户缓存，返回 (cache_evidence, skip_paths, prompt_block)。

    只有 summary/locate 才查缓存；每个文件按当前字节哈希精确匹配，
    内容一变旧行自然不命中。缓存不可用时静默返回空（本次照常全文读）。
    """
    if (document_task is None or not doc_cache.cache_enabled()
            or not scope_allows_cache(request_scope)):
        return {}, set(), ""
    resolved = resolve_extraction_model()
    if resolved is None:
        return {}, set(), ""
    model_key = resolved[2]

    hits: list[tuple[object, object, str]] = []
    conn = None
    try:
        conn = get_connection()
        for item in document_task.files:
            try:
                digest = doc_cache.file_sha256(item.path)
            except OSError:
                continue
            entry = doc_cache.get(
                conn, tenant_id=tenant_id, sha256=digest, model=model_key
            )
            if entry is not None and entry.cacheable_info:
                hits.append((item, entry, digest))
    except (sqlite3.Error, OSError, ValueError) as exc:
        _log.warning("读取文档缓存失败，按未命中处理：%s", exc)
        return {}, set(), ""
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    if not hits:
        return {}, set(), ""

    evidence: dict[str, dict] = {}
    skip_paths: set[str] = set()
    lines: list[str] = [
        "[文档缓存（仅用于概览/定位）]",
        "以下是已有提取摘要的文件；具体数字/条款/原文仍须本次全文核对，"
        "不得用缓存回答具体事实：",
    ]
    shown = 0
    for item, entry, digest in hits:
        summary = (entry.summary_text or "").strip()[:_MAX_CACHE_SUMMARY_CHARS]
        if not summary:
            # 没有摘要就没有可注入的内容：不拦读取，让模型自己去读。
            continue
        if shown >= _MAX_CACHE_PROMPT_FILES:
            break
        path_key = str(item.path)
        lines.append(f"- {item.relative_path}：{summary}")
        shown += 1
        # 只有真正写进提示的文件才登记跳过/证据（审计 P1-3）。
        skip_paths.add(path_key)
        evidence[path_key] = {
            "source": "cache",
            "cache_complete": True,
            "doc_kind": entry.doc_kind,
            "allowed_scope": [SCOPE_SUMMARY, SCOPE_LOCATE],
            "tenant_id": str(tenant_id),
            "sha256": digest,
            "model": entry.model,
            "extractor_version": entry.extractor_version,
            "extracted_at": entry.extracted_at,
        }
    if not shown:
        return {}, set(), ""
    return evidence, skip_paths, "\n".join(lines)


def _warm_cache_paths(paths, tenant_id: int) -> None:
    """后台预热给定文件；绝不阻塞响应，失败静默。"""
    if not doc_cache.cache_enabled() or not paths:
        return
    # 没有配置对话模型就不必起线程（也让测试环境保持安静）。
    if resolve_extraction_model() is None:
        return
    try:
        threading.Thread(
            target=lambda: warm_cache(list(paths), tenant_id=tenant_id), daemon=True
        ).start()
    except Exception as exc:
        _log.debug("启动缓存预热线程失败：%s", exc)


def _warm_after_read(request_task_id, collector, tenant_id: int) -> None:
    """按本次真实读取证据预热（不依赖门禁是否通过）。

    门禁只负责"是否给出结论"；读到哪些文件就预热哪些，否则概览/定位
    永远等不到缓存（2026-11-09 基准：缓存收益为 0 的直接原因）。
    """
    paths: set[str] = set()
    if request_task_id:
        snapshot = snapshot_read_coverage(request_task_id)
        for path, record in (snapshot or {}).items():
            if isinstance(record, dict) and record.get("complete") is True:
                paths.add(str(path))
    if collector is not None:
        for path, record in (collector.snapshot() or {}).items():
            if isinstance(record, dict) and record.get("complete") is True:
                paths.add(str(path))
    if paths:
        _warm_cache_paths(paths, tenant_id)


@router.get("/usage/today")
def usage_today(response: Response, cid: int = Depends(require_company)):
    """今日 token 用量（仅提示，不拦截聊天）。

    上限只影响界面配色与文案（超过后标红），聊天照常执行 —— 用户 2026-10-26
    明确要求「提示但不拦」。

    必须是 no-store：额度每天在变、后台代码升级后阈值也会变，浏览器拿旧响应
    会一直显示旧值（实测升级后仍显示 2,000,000）。
    """
    response.headers["Cache-Control"] = "no-store"
    used, limit = usage_module.daily_budget_state(cid)
    return {
        "used": used,
        "limit": limit,  # 0 = 不限
        "exceeded": bool(limit and used >= limit),
    }


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
    _validate_scope(payload, cid)

    # 读取上次使用的 skill 名称（用于跳过重复注入）
    with _skill_cache_lock:
        last_skill = _last_skill_per_company.get(cid)

    full_query, skill_hint = build_query(
        cid, payload.library_id, query, customer_id=payload.customer_id,
        last_skill_name=last_skill,
        # 回复语言跟随**用户这句话**：中文回中文、英文回英文；
        # 界面语言只作「判不出来时」的兜底（2026-11-02 口径）。
        language=detect_reply_language(query, payload.language or "zh"),
    )
    # 用户本轮亲手贴出的文件 → 直接只读放行（贴出来即授权，不再二次确认）
    user_paths = _classify_user_paths(query, cid)
    if user_paths:
        skill_hint = (skill_hint or "") + "\n\n" + _external_paths_hint(user_paths)

    # 从 full_query 或 skill_hint 中提取当前匹配的 skill 名称并缓存
    current_skill = _extract_and_cache_skill(cid, full_query, skill_hint)
    request_scope = detect_request_scope(query)
    gate_required = bool(payload.library_id and should_enforce_document_gate(query))
    # 概览/定位只把缓存摘要当上下文，不参与门禁（2026-11-09 审计 P1-1）。
    cache_context = bool(
        payload.library_id and not gate_required
        and doc_cache.cache_enabled() and scope_allows_cache(request_scope)
    )
    document_task = None
    if gate_required or cache_context:
        library = library_module.get(payload.library_id, company_id=cid)
        if library:
            document_task = DocumentTask.from_root(library["root_path"])
            if document_task.truncated or not document_task.files:
                # 目录过大或没有可分析文件：无法可靠判定完整性，退回普通问答。
                _log.info("Document plan skipped (truncated=%s, files=%d)",
                          document_task.truncated, len(document_task.files))
                document_task = None

    cache_evidence: dict = {}
    skip_paths: set[str] = set()
    cache_block = ""
    if document_task is not None and cache_context:
        # 哈希/查库是阻塞 I/O：放进线程，避免卡住事件循环。
        cache_evidence, skip_paths, cache_block = await asyncio.to_thread(
            _load_cache_hits, document_task, cid, request_scope
        )
        if cache_block:
            full_query = full_query + "\n\n" + cache_block
        # 只有概览才硬跳过；定位要自己判断关键词，不能拦读取。
        if request_scope != SCOPE_SUMMARY:
            skip_paths = set()

    _MAX_AGENT_RETRIES = 2  # 最多重试 2 次（共 3 次尝试），与 SSE 流式端点保持一致

    request_task_id = f"trade-doc-{cid}-{time.time_ns()}" if document_task else None
    if document_task and request_task_id and skip_paths:
        register_doc_skip(request_task_id, skip_paths)
    # 回调收集的证据：公开版 Hermes 没有对外读取快照接口，靠这个兜底。
    # 即使没有文档计划也收集（用于"读到哪些就预热哪些"）。
    evidence = ReadEvidenceCollector()
    # 所有工具调用的完成记录：任务中止时写「已查渠道」，以及只基于已有结果总结
    tools = CompletedToolTracker()

    def _sync_tool_start(tc_id, name, args):
        tools.on_start(name, args)
        evidence.on_start(tc_id, name, args)

    def _sync_tool_complete(tc_id, name, args, result):
        tools.on_complete(name, args, result)
        evidence.on_complete(tc_id, name, args, result)

    # 超时后主线程要靠它中断仍在跑的 agent；列表用于跨线程传引用
    agent_holder: list = []
    cancelled = threading.Event()

    def _summarize_after_tools(reason: str) -> tuple[str, str]:
        """工具已跑过：只基于已有结果做**一次**总结调用，不再整轮重跑。

        enabled_toolsets=[] 禁用工具 —— 总结不应该再执行任何工具（否则就是
        换一种方式重跑）。总结失败时退回本地生成的未完成报告，绝不丢证据。

        总结成功也标 **partial**（审计 P2-3）：本轮 Agent 并没有产出最终回答，
        这只是凭部分工具结果整理的半成品 —— 必须跳过长期记忆，否则以后会把
        它当成正式结论注入后续对话。
        """
        try:
            agent = create_agent(
                ephemeral_system_prompt=skill_hint,
                skill_name=current_skill,
                enabled_toolsets=[],
                run_budget_seconds=_sync_run_budget(),
            )
            agent_holder.clear()
            agent_holder.append(agent)
            if cancelled.is_set():
                return "", "failed"
            text = agent.chat(build_summary_prompt(query, tools))
            usage_module.record_agent_usage(
                agent, company_id=cid, skill=current_skill or "",
            )
            if text and not cancelled.is_set():
                return text, "partial"
        except Exception:
            _log.exception("总结调用失败（已有工具结果）")
        return build_partial_report(reason, tools, evidence), "partial"

    def _call_agent() -> tuple[str, str]:
        """返回 (回复文本, 状态)；状态 = ok | partial | failed。

        partial = 任务中止时生成的「未完成报告」：有已完成的工具结果，
        但没有最终回答。failed = 连工具都没跑成的失败兜底文案。
        """
        last_error = ""
        for attempt in range(_MAX_AGENT_RETRIES + 1):
            # 已超时：不再发起新尝试（用户早已拿到"已中止"）
            if cancelled.is_set():
                return "", "failed"
            try:
                agent = create_agent(
                    ephemeral_system_prompt=skill_hint,
                    skill_name=current_skill,
                    tool_start_callback=_sync_tool_start,
                    tool_complete_callback=_sync_tool_complete,
                    run_budget_seconds=_sync_run_budget(),
                )
                agent_holder.clear()
                agent_holder.append(agent)
                # 守卫不可用时不允许跑工具（agent 已构造，插件钩子能力此刻已知）
                from trade.bootstrap import tool_guard_chat_block_reason

                block_reason = tool_guard_chat_block_reason()
                if block_reason:
                    return block_reason, "failed"
                # 构造期间已超时：别再启动这一轮（主线程的 abort 会正好错过它）
                if cancelled.is_set():
                    return "", "failed"
                # 绑定公司身份：chat-memory 等插件工具只认服务端绑定，
                # 不再信任模型自填的 company_id（审计 P0-2）。
                try:
                    with bind_company(
                        cid, payload.customer_id,
                        user_paths=user_paths,
                    ), bind_tool_evidence(
                        # 动态供应：osint_fact_save 在 agent 运行中调用，要看到
                        # 此刻已完成工具的参数/结果（P1-D 来源核验）
                        lambda: [
                            f"{item.get('detail', '')} {item.get('preview', '')}"
                            for item in tools.snapshot()
                        ],
                    ):
                        if document_task and request_task_id:
                            result = agent.run_conversation(full_query, task_id=request_task_id)["final_response"]
                        else:
                            result = agent.chat(full_query)
                finally:
                    # 不论成功/失败（含被中断）都把这次尝试的 token 记账：
                    # 失败的重试同样烧钱，漏记会让额度形同虚设（审计 P1-16）。
                    usage_module.record_agent_usage(
                        agent, company_id=cid, skill=current_skill or "",
                    )
                if cancelled.is_set():
                    # 超时后迟到的结果：用户已收到中止提示，不能再当成功回复
                    return "", "failed"
                if result:
                    return result, "ok"
                # 空响应：本轮已经跑过工具 → 不再整轮重跑（会重复执行工具），
                # 改为「只基于已有结果出总结」的一次调用。
                if tools.has_completed():
                    return _summarize_after_tools("Agent 返回空响应")
                if attempt < _MAX_AGENT_RETRIES:
                    _log.warning("Agent returned empty, retry %d/%d", attempt + 1, _MAX_AGENT_RETRIES)
                    time.sleep(2 ** attempt)
                    continue
                return "Agent 返回了空响应。", "failed"
            except ImportError:
                return "⚠️ AI Agent 模块未加载。", "failed"
            except RuntimeError as e:
                last_error = str(e)
                # 已经跑过工具：重跑整轮会重复执行工具，只做一次总结
                if tools.has_completed():
                    return _summarize_after_tools(f"Agent 报错：{e}")
                if attempt < _MAX_AGENT_RETRIES:
                    _log.warning("Agent RuntimeError, retry %d/%d: %s", attempt + 1, _MAX_AGENT_RETRIES, e)
                    time.sleep(2 ** attempt)
                    continue
                return f"⚠️ {e}", "failed"
            except Exception as e:
                last_error = str(e) or f"Agent call failed (attempt {attempt + 1})"
                _log.exception("Agent call failed (attempt %d/%d)", attempt + 1, _MAX_AGENT_RETRIES)
                if tools.has_completed():
                    return _summarize_after_tools(f"Agent 异常：{e}")
                if attempt < _MAX_AGENT_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
            except BaseException as e:
                # 与 _run_agent（stream）对称：Hermes 可能以 BaseException 结束，例如
                # hermes_bootstrap 的 RelaunchExit 继承 SystemExit。它穿过
                # asyncio.wait_for 后，uvicorn 的 ExceptionMiddleware 同样只捕
                # Exception → 会一路穿透到 ASGI 栈，最坏情况整个服务进程退出。
                # 同步端点没有"稍后重试"的余地，如实上报即可。
                _log.error(
                    "Agent terminated with %s: %s", type(e).__name__, e, exc_info=True
                )
                return f"⚠️ Agent 异常终止（{type(e).__name__}）：{e}", "failed"
        fallback = f"⚠️ Agent 调用失败: {last_error}" if last_error else "⚠️ Agent 调用失败，请稍后重试。"
        return fallback, "failed"

    loop = asyncio.get_running_loop()
    try:
        response, status = await asyncio.wait_for(
            loop.run_in_executor(None, _call_agent),
            timeout=_SYNC_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        # Future 取消停不掉线程：先置取消标记（挡住重试与落库），
        # 再尽力中断 agent，让正在跑的工具调用停下来（审计 P1-21）。
        cancelled.set()
        _abort_running_agent(agent_holder[0] if agent_holder else None)
        if tools.has_completed():
            # 已经跑过工具：留下「未完成报告」（partial=true），别让证据消失
            response = build_partial_report("超过 10 分钟自动中止", tools, evidence)
            status = "partial"
        else:
            response = "⏰ Agent 执行时间过长（超过 10 分钟），已自动中止。请简化问题后重试。"
            status = "failed"

    agent_ok = status == "ok"
    partial = status == "partial"

    gate_result = None
    incomplete = False
    if gate_required and document_task and request_task_id:
        try:
            if agent_ok:
                gate_result = _document_gate(
                    document_task, request_task_id, evidence,
                    request_scope=request_scope, cache_evidence=cache_evidence,
                )
                if gate_result is not None and gate_result.status == "incomplete":
                    # 不通过时把原因作为回答返回，既不丢用户提问也不给不完整结论。
                    incomplete = True
                    response = format_incomplete_report(gate_result)
        finally:
            # 读到哪些就预热哪些（不依赖门禁是否通过），再释放读记录。
            _warm_after_read(request_task_id, evidence, cid)
            release_read_coverage(request_task_id)
            release_doc_skip(request_task_id)

    if not gate_required:
        # 没有门禁的普通请求：回调证据同样可以预热（有 task_id 时也读快照）。
        _warm_after_read(request_task_id, evidence, cid)

    if cache_block and not gate_required and agent_ok:
        response += (
            f"\n\n（本次参考了 {len(cache_evidence)} 个文件的缓存摘要；"
            "具体事实请以本次读取为准。）"
        )

    # 交付前制裁兜底（工单 P0-C）：路由命中 OSINT 却没有跑过工具/没写制裁段落。
    if agent_ok or partial:
        response = _ensure_sanctions_section(
            query=query, response=response,
            skill=current_skill or "", tools=tools,
        )

    lib_name = ""
    if payload.library_id:
        lib = library_module.get(payload.library_id, company_id=cid)
        if lib:
            lib_name = lib["name"]

    # 失败兜底文案（超时 / 模块未加载 / Agent 异常）不写入历史：
    # 它们不是对用户的回答，存档后会被后续轮次当作上下文注入（审计 P1-21）。
    # W10：剥除 trade-json 围栏后再入库/回传，避免气泡里露出原始 JSON。
    response_blocks = None
    if response and (agent_ok or partial):
        # 总结成功也走 partial：它的文本同样可能带 trade-json 围栏，
        # 不入库剥离就会在气泡/历史里露出原始 JSON。
        response, response_blocks = parse_trade_json_blocks(response)
    conv = None
    if agent_ok or partial:
        conv = chat_memory.save_with_context(
            company_id=cid, library_id=payload.library_id, query=query,
            response=response, library_name=lib_name,
            customer_id=payload.customer_id,
            files_read=([{"file": path, "status": "complete"} for path in gate_result.complete]
                        if gate_result else None),
            context=payload.context or "",
            skill=current_skill or "",
            blocks=response_blocks,
            partial=partial,
            retain_to_memory=not partial,
        )
    payload_out = {"response": response, "conversation": conv}
    if response_blocks:
        payload_out["blocks"] = response_blocks
    if partial:
        # 前端可据此区分「最终回答」与「任务中止时的未完成报告」
        payload_out["partial"] = True
    if cache_evidence and not gate_required:
        # 概览/定位用了哪些文件的缓存摘要（不是“已读”，只是上下文来源）
        payload_out["analysis_cache_context"] = sorted(
            Path(path).name for path in cache_evidence
        )
    if gate_result is not None:
        payload_out["analysis_skipped"] = gate_result.skipped
        if gate_result.coverage_note:
            # 能力边界如实披露（原版 Hermes 无结构化读取快照时）
            payload_out["analysis_note"] = gate_result.coverage_note
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
    _validate_scope(payload, cid)

    # 读取上次使用的 skill 名称（用于跳过重复注入）
    with _skill_cache_lock:
        last_skill = _last_skill_per_company.get(cid)

    full_query, skill_hint = build_query(
        cid, payload.library_id, query, customer_id=payload.customer_id,
        last_skill_name=last_skill,
        # 回复语言跟随**用户这句话**：中文回中文、英文回英文；
        # 界面语言只作「判不出来时」的兜底（2026-11-02 口径）。
        language=detect_reply_language(query, payload.language or "zh"),
    )
    # 用户本轮亲手贴出的文件 → 直接只读放行（贴出来即授权，不再二次确认）
    user_paths = _classify_user_paths(query, cid)
    if user_paths:
        skill_hint = (skill_hint or "") + "\n\n" + _external_paths_hint(user_paths)

    # 从 full_query 或 skill_hint 中提取当前匹配的 skill 名称并缓存
    current_skill = _extract_and_cache_skill(cid, full_query, skill_hint)
    request_scope = detect_request_scope(query)
    gate_required = bool(payload.library_id and should_enforce_document_gate(query))
    # 概览/定位只把缓存摘要当上下文，不参与门禁（2026-11-09 审计 P1-1）。
    cache_context = bool(
        payload.library_id and not gate_required
        and doc_cache.cache_enabled() and scope_allows_cache(request_scope)
    )
    document_task = None
    if gate_required or cache_context:
        library = library_module.get(payload.library_id, company_id=cid)
        if library:
            document_task = DocumentTask.from_root(library["root_path"])
            if document_task.truncated or not document_task.files:
                # 目录过大或没有可分析文件：无法可靠判定完整性，退回普通问答。
                _log.info("Document plan skipped (truncated=%s, files=%d)",
                          document_task.truncated, len(document_task.files))
                document_task = None

    cache_evidence: dict = {}
    skip_paths: set[str] = set()
    cache_block = ""
    if document_task is not None and cache_context:
        # 哈希/查库是阻塞 I/O：放进线程，避免卡住 SSE 事件循环。
        cache_evidence, skip_paths, cache_block = await asyncio.to_thread(
            _load_cache_hits, document_task, cid, request_scope
        )
        if cache_block:
            full_query = full_query + "\n\n" + cache_block
        # 只有概览才硬跳过；定位要自己判断关键词，不能拦读取。
        if request_scope != SCOPE_SUMMARY:
            skip_paths = set()

    request_task_id = f"trade-doc-{cid}-{time.time_ns()}" if document_task else None
    if document_task and request_task_id and skip_paths:
        register_doc_skip(request_task_id, skip_paths)
    # 回调收集的证据：公开版 Hermes 没有对外读取快照接口，靠这个兜底。
    # 即使没有文档计划也收集（用于"读到哪些就预热哪些"）。
    evidence = ReadEvidenceCollector()
    # 所有工具调用的完成记录：任务中止时写「已查渠道」，以及只基于已有结果总结
    tools = CompletedToolTracker()

    loop = asyncio.get_running_loop()
    event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    async def _put_critical(item) -> None:
        """终态事件背压入队，但最多等 30 秒。

        客户端断连后队列没人消费，无超时的 put 会留下永不完成的 task。
        """
        try:
            await asyncio.wait_for(event_queue.put(item), timeout=30)
        except TimeoutError:
            _log.warning("SSE critical event dropped after 30s: %s", item[0])

    def _emit_threadsafe(event_type: str, data: dict | None = None):
        """工作线程通过 call_soon_threadsafe 投递到 asyncio queue。

        进度类事件（tool_* / thinking）队列满可丢，保证 SSE 不堵死。
        response / error / done / analysis_gate 是终态或门禁结论，改走
        create_task(put) 背压等待，避免用户只看到「工具跑完了却没有回复」。
        """
        critical = event_type in ("response", "error", "done", "analysis_gate")

        def _safe_put(ev_type, ev_data):
            if critical:
                # 终态事件必须送达；队列满时等待空位，但必须有上限
                asyncio.create_task(_put_critical((ev_type, ev_data)))
                return
            try:
                event_queue.put_nowait((ev_type, ev_data))
            except asyncio.QueueFull:
                _log.warning("SSE event queue full, dropping event: %s", ev_type)

        loop.call_soon_threadsafe(_safe_put, event_type, data or {})

    def _tool_start(tc_id, name, args):
        tools.on_start(name, args)
        if evidence is not None:
            evidence.on_start(tc_id, name, args)
        _emit_threadsafe("tool_start", {"tool_call_id": tc_id, "name": name, "args": args})

    def _tool_complete(tc_id, name, args, result):
        # 证据收集与 SSE 推送解耦：队列满丢事件不影响完整性判定。
        tools.on_complete(name, args, result)
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
        # 后台背调刚启动：补一条 job_attached，前端据此把 task 面板挂进当前气泡，
        # 不必解析被截断的 result_preview（工单 §4-B1）。
        if name == "osint_job_start":
            attached = _parse_osint_job_attachment(result)
            if attached:
                _emit_threadsafe("job_attached", attached)

    _MAX_AGENT_RETRIES = 2
    cancel_event = threading.Event()  # 客户端断连时置位，阻止重试继续浪费 token
    agent_holder: list = []  # 断连/超时时靠它中断仍在跑的 agent（见 _abort_running_agent）

    # ── 未完成报告（P0-5）───────────────────────────────────────────────
    partial_lock = threading.Lock()
    partial_state = {"saved": False}   # 只写一次（超时分支与 finally 都会尝试）
    delivered = {"ok": False}          # 正常回答是否已落库并下发

    def _save_partial(reason: str) -> tuple[str | None, int | None]:
        """把「未完成报告」写进历史（幂等）。没有完成的工具调用则不写。"""
        if not tools.has_completed():
            return None, None
        with partial_lock:
            # 正常回答已经交付：不能再补写一条「未完成报告」（审计 P1-1）。
            # 事件循环可能先取到 response 再进入 finally，必须在这里兜一层。
            if delivered["ok"] or partial_state["saved"]:
                return None, None
            partial_state["saved"] = True
        text = build_partial_report(reason, tools, evidence)
        conv_id = None
        try:
            conv = chat_memory.save_with_context(
                company_id=cid, library_id=payload.library_id, query=query,
                response=text, customer_id=payload.customer_id,
                context=payload.context or "", skill=current_skill or "",
                partial=True, retain_to_memory=False,
            )
            if conv:
                conv_id = conv.get("id")
        except Exception:
            _log.exception("save partial report failed")
        return text, conv_id

    def _emit_partial_response(text: str | None, conv_id: int | None) -> None:
        """把未完成报告作为 response 事件下发（前端据此显示半成品）。"""
        if not text:
            _emit_threadsafe("error", {"message": "Agent 未能产出结果，请稍后重试。"})
            return
        _emit_threadsafe("response", {
            "text": text,
            "elapsed_sec": 0.0,
            "conversation_id": conv_id,
            "partial": True,
        })

    def _summarize_after_tools(reason: str) -> str | None:
        """工具已跑过：只基于已有结果做**一次**总结（工具禁用，不重跑）。"""
        _emit_threadsafe("thinking", {"message": "正在根据已完成的工具结果整理答复..."})
        try:
            agent = create_agent(
                ephemeral_system_prompt=skill_hint,
                skill_name=current_skill,
                enabled_toolsets=[],
            )
            agent_holder.clear()
            agent_holder.append(agent)
            if cancel_event.is_set():
                return None
            text = agent.chat(build_summary_prompt(query, tools))
            usage_module.record_agent_usage(
                agent, company_id=cid, skill=current_skill or "",
            )
            if text and not cancel_event.is_set():
                return text
        except Exception:
            _log.exception("总结调用失败（已有工具结果）")
        return None

    def _finish_after_tools(reason: str) -> str | None:
        """工具已跑过时的收尾：先试一次总结，不行就落未完成报告。

        总结成功也按 partial 落库/下发（审计 P2-3）：它是凭部分工具结果整理的
        半成品，不是本轮 Agent 的最终回答，不能进长期记忆。
        """
        summary = _summarize_after_tools(reason)
        if summary:
            return _finalize(summary, 0.0, partial=True)
        text, conv_id = _save_partial(reason)
        _emit_partial_response(text, conv_id)
        return None

    def _finalize(result: str, elapsed: float, *, partial: bool = False) -> str | None:
        """收尾：门禁判定 → 保存历史 → 下发 response 事件。

        partial=True 表示 result 是「凭已完成的工具结果整理的半成品」，
        保存时标 partial 并跳过长期记忆，下发时带 partial 标记（审计 P2-3）。
        """
        gate_result = None
        if document_task and request_task_id:
            try:
                if gate_required and result:
                    gate_result = _document_gate(
                        document_task, request_task_id, evidence,
                        request_scope=request_scope,
                        cache_evidence=cache_evidence,
                    )
                    if gate_result is not None:
                        if gate_result.status == "incomplete":
                            # 不通过时把原因作为回答下发，不报错也不给不完整结论。
                            result = format_incomplete_report(gate_result)
                        _emit_threadsafe("analysis_gate", {
                            "status": gate_result.status,
                            "files": gate_result.complete,
                            "cache_files": gate_result.cache_complete,
                            "missing": gate_result.missing,
                            "errors": gate_result.errors,
                            "skipped": gate_result.skipped,
                            "coverage_note": gate_result.coverage_note,
                        })
                elif result and cache_block and not gate_required:
                    result += (
                        f"\n\n（本次参考了 {len(cache_evidence)} 个文件的缓存摘要；"
                        "具体事实请以本次读取为准。）"
                    )
            finally:
                # 读到哪些就预热哪些（不依赖门禁是否通过），再释放读记录。
                _warm_after_read(request_task_id, evidence, cid)
                release_read_coverage(request_task_id)
                release_doc_skip(request_task_id)
        elif not gate_required:
            # 没有门禁的普通请求：回调证据同样可以预热（有 task_id 时也读快照）。
            _warm_after_read(request_task_id, evidence, cid)

        lib_name = ""
        if payload.library_id:
            lib = library_module.get(payload.library_id, company_id=cid)
            if lib:
                lib_name = lib["name"]

        # 客户端已断连/已超时：迟到的回答不能再写进历史 —— 用户已经收到
        # 中止提示，存档后会被下一轮当上下文注入（复审 P1-21 残口）。
        if cancel_event.is_set():
            return None

        # 交付前制裁兜底（工单 P0-C）：与同步端点同一规则。
        if result:
            result = _ensure_sanctions_section(
                query=query, response=result,
                skill=current_skill or "", tools=tools,
            )

        # W10：先剥 trade-json 围栏，再入库并推 SSE（失败静默为纯文本）
        reply_text = result or "Agent 返回了空响应。"
        reply_blocks = None
        try:
            reply_text, reply_blocks = parse_trade_json_blocks(reply_text)
        except Exception:
            reply_blocks = None

        # 先保存对话，再发送响应 —— 确保前端能拿到 conversation_id 做评分
        conv_id = None
        try:
            conv = chat_memory.save_with_context(
                company_id=cid, library_id=payload.library_id,
                query=query, response=reply_text,
                library_name=lib_name,
                customer_id=payload.customer_id,
                files_read=([{"file": path, "status": "complete"} for path in gate_result.complete]
                            if gate_result else None),
                context=payload.context or "",
                skill=current_skill or "",
                blocks=reply_blocks,
                partial=partial,
                retain_to_memory=not partial,
            )
            if conv:
                conv_id = conv.get("id")
        except Exception as exc:
            _log.exception("save_with_context failed in stream")
            # 不能静默：回答能显示但 conversation_id 为空，评分/引用链路
            # 会断，用户却不知道（审计 P2-33）。发一条警告事件让前端提示。
            _emit_threadsafe("warning", {
                "message": f"对话已回复，但保存到历史失败（{type(exc).__name__}），"
                           "本轮无法评分或后续引用。",
            })

        resp_payload = {
            "text": reply_text,
            "elapsed_sec": round(elapsed, 1),
            "conversation_id": conv_id,
        }
        if reply_blocks:
            resp_payload["blocks"] = reply_blocks
        if partial:
            resp_payload["partial"] = True
        # 先置 delivered 再发 response（审计 P1-1）：反过来的话，事件循环
        # 可能先取到 response、break 进 finally，此时 delivered 仍为 False，
        # finally 会再写一条「客户端断开」的未完成报告。
        delivered["ok"] = True
        _emit_threadsafe("response", resp_payload)
        return result

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
                agent_holder.clear()
                agent_holder.append(agent)
                # 守卫不可用时不允许跑工具（与同步端点一致）
                from trade.bootstrap import tool_guard_chat_block_reason

                block_reason = tool_guard_chat_block_reason()
                if block_reason:
                    _emit_threadsafe("error", {"message": block_reason})
                    return None
                # 断连/超时发生在构造期间：别再启动这一轮
                if cancel_event.is_set():
                    return None
                start = time.time()
                # 同同步端点：把公司身份绑进本次 agent 调用的上下文。
                try:
                    with bind_company(
                        cid, payload.customer_id,
                        user_paths=user_paths,
                    ), bind_tool_evidence(
                        # 动态供应：osint_fact_save 在 agent 运行中调用，要看到
                        # 此刻已完成工具的参数/结果（P1-D 来源核验）
                        lambda: [
                            f"{item.get('detail', '')} {item.get('preview', '')}"
                            for item in tools.snapshot()
                        ],
                    ):
                        if document_task and request_task_id:
                            result = agent.run_conversation(full_query, task_id=request_task_id)["final_response"]
                        else:
                            result = agent.chat(full_query)
                finally:
                    # 断连/失败同样记账：本次尝试的 token 已经花掉了（审计 P1-16）
                    usage_module.record_agent_usage(
                        agent, company_id=cid, skill=current_skill or "",
                    )
                elapsed = time.time() - start

                if not result:
                    # 空响应：本轮已经跑过工具 → 不再整轮重跑（会重复执行工具），
                    # 只基于已有结果做一次总结；总结也失败则落未完成报告。
                    if tools.has_completed():
                        return _finish_after_tools("Agent 返回空响应")
                    if attempt < _MAX_AGENT_RETRIES:
                        if cancel_event.is_set():
                            return None
                        _log.warning("Agent returned empty in stream, retry %d/%d", attempt + 1, _MAX_AGENT_RETRIES)
                        time.sleep(2 ** attempt)
                        continue

                return _finalize(result, elapsed)
            except ImportError:
                _emit_threadsafe("error", {"message": "AI Agent 模块未加载。"})
                return None
            except RuntimeError as e:
                last_error = str(e)
                # 已经跑过工具：重跑整轮会重复执行工具，只做一次总结
                if tools.has_completed():
                    return _finish_after_tools(f"Agent 报错：{e}")
                if attempt < _MAX_AGENT_RETRIES and not cancel_event.is_set():
                    _log.warning("Agent RuntimeError in stream, retry %d/%d: %s", attempt + 1, _MAX_AGENT_RETRIES, e)
                    time.sleep(2 ** attempt)
                    continue
                _emit_threadsafe("error", {"message": last_error})
                return None
            except Exception as e:
                last_error = str(e) or f"Agent stream failed (attempt {attempt + 1})"
                _log.exception("Agent stream failed (attempt %d/%d)", attempt + 1, _MAX_AGENT_RETRIES)
                if tools.has_completed():
                    return _finish_after_tools(f"Agent 异常：{e}")
                if attempt < _MAX_AGENT_RETRIES and not cancel_event.is_set():
                    time.sleep(2 ** attempt)
                    continue
                _emit_threadsafe("error", {"message": f"⚠️ {last_error}"})
                return None
            except BaseException as e:
                # Hermes 可能以 BaseException 结束 —— 例如 hermes_bootstrap 的
                # RelaunchExit 继承 SystemExit（它会把 server.py 重新 exec 到 Hermes
                # 自带的 store python，而那里没有 trade 包）。`except Exception` 抓不到
                # 这类异常，agent 线程会静默死亡：前端既收不到 response 也收不到 error，
                # 只能落兜底文案「Agent 未返回有效回复」（客户机实测，2026-10-08）。
                # 它也不是瞬时故障，重试无意义，如实上报即可。
                _log.error(
                    "Agent terminated with %s: %s", type(e).__name__, e, exc_info=True
                )
                _emit_threadsafe(
                    "error",
                    {"message": f"⚠️ Agent 异常终止（{type(e).__name__}）：{e}"},
                )
                return None
        _emit_threadsafe("error", {"message": "Agent 重试耗尽，请稍后重试。"})
        return None

    async def _event_stream():
        def _sse(ev_type: str, payload: dict) -> str:
            return f"event: {ev_type}\ndata: {_json.dumps(payload, ensure_ascii=False)}\n\n"

        agent_task = loop.run_in_executor(None, _run_agent)
        # 30 分钟 Agent 兜底超时 — 网站诊断等长任务也应在 30min 内完成
        # 超时后发 error 事件并取消 agent，防止永久挂起
        deadline = time.time() + _STREAM_DEADLINE_SECONDS
        timed_out = {"value": False}
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    # 直接 yield，不能走 _emit_threadsafe：那条路径要等下一轮事件循环
                    # 才往队列里 put，而这里紧接着就 break，队列里的 error 永远不会被
                    # 取到（历史 bug —— 超时后用户只看到「未返回有效回复」，既不知道
                    # 是超时、也不知道任务已被中止）。
                    _log.error("Agent stream exceeded %.0fs deadline; aborting", _STREAM_DEADLINE_SECONDS)
                    timed_out["value"] = True
                    # 已跑过工具 → 留下未完成报告（partial=true），别让证据消失。
                    # SQLite 写入放到线程里，别在 async 生成器里同步阻塞事件循环。
                    partial_text, _conv_id = await asyncio.to_thread(
                        _save_partial, "超过 30 分钟自动中止",
                    )
                    message = "⏰ Agent 执行超过 30 分钟，已自动中止。请简化问题或联系支持。"
                    if partial_text:
                        message = f"{message}\n\n{partial_text}"
                    yield _sse("error", {"message": message})
                    break
                try:
                    # 取 15s 心跳与剩余 deadline 的较小值，确保 deadline 到期时能及时触发
                    wait_sec = min(15.0, remaining)
                    ev_type, ev_data = await asyncio.wait_for(event_queue.get(), timeout=wait_sec)
                except TimeoutError:
                    if agent_task.done():
                        # 任务已结束、队列里却没有终止事件 —— 说明它是异常收场的。
                        # 不取 exception() 会让失败彻底静默（还会打出
                        # "Future exception was never retrieved" 警告），
                        # 前端只能落到兜底文案。取出来即当作 error 下发。
                        if not agent_task.cancelled():
                            exc = agent_task.exception()
                            if exc is not None:
                                _log.error("Agent task died without emitting: %r", exc)
                                yield _sse("error", {
                                    "message": f"⚠️ Agent 失败（{type(exc).__name__}）：{exc}"
                                })
                        break
                    yield ": ping\n\n"
                    continue

                yield _sse(ev_type, ev_data)
                if ev_type in ("response", "error"):
                    break
        finally:
            # 客户端断连 / 超时 / 异常 → 先发取消信号让 Agent 线程退出重试循环，
            # 再尽力中断它：Future.cancel() 停不掉线程里正在跑的工具调用，
            # 只有 Hermes 的 interrupt() 能让工具侧看到中断位（审计 P1-21）。
            cancel_event.set()
            if not agent_task.done():
                _abort_running_agent(agent_holder[0] if agent_holder else None)
                agent_task.cancel()
                try:
                    await agent_task
                except (asyncio.CancelledError, Exception):
                    pass
            # 线程里的 release 可能赶在 error 事件之后才执行；这里兜底一次，
            # 保证流结束（异常/断连/超时）时跳过集合一定被释放。
            if document_task and request_task_id:
                try:
                    release_read_coverage(request_task_id)
                    release_doc_skip(request_task_id)
                except Exception:
                    _log.exception("release read coverage / doc skip failed")
            # 没有正常下发回答（超时 / 断连 / 用户停止 / Agent 报错）但已有
            # 工具结果 → 补一份未完成报告进历史（幂等：超时分支可能已写过）。
            if not delivered["ok"]:
                reason = (
                    "超过 30 分钟自动中止"
                    if timed_out["value"]
                    else "客户端断开或用户停止"
                )
                await asyncio.to_thread(_save_partial, reason)
            yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )
