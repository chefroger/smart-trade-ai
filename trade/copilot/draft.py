"""draft —— 生成回复草稿（平台无关）。

## 铁律 3：数字只从库里取

草稿里的价格、MOQ、规格、交期**必须**来自产品库检索结果并标注出处；检索不到的
数字**不许出现**，相应位置写"（待确认）"。

两道防线：
    ① 提示词侧：明确告诉模型"只能用给定条目里的数字，查不到就写（待确认）"
    ② 组装侧：把草稿里出现的数字与产品条目做核对，**库里没有的数字直接剔除**
       （宁可删掉一个数字，也不让它带着假出处留在草稿里）

## 复用哪条执行路径

复用 `trade/api/chat.py` 的会话执行路径（`build_query` → `create_agent` →
`agent.chat`），公司绑定沿用既有机制，**不新造隔离**。

## 输出格式

严格 JSON（与 extract 同一套 json_object 范式）：
    {"draft": "回复正文（与客户同语种）", "summary_zh": "一行中文大意",
     "sources": [{"label": "出处", "value": "数字"}]}
"""

from __future__ import annotations

import logging
import re
import threading
import time

from trade.copilot.numbers import NUMBER_RE, extract_numbers, number_key
from trade.copilot.types import (
    DEFAULT_TIMEOUT,
    CustomerContext,
    DraftResult,
    SourceRef,
)

_log = logging.getLogger(__name__)

# 失败重试次数（总尝试 = 1 + 1）。与 api/chat.py 的重试思路一致，
# 但受总截止时间约束：超时用掉全部预算时不会再重试。
_DRAFT_ATTEMPTS = 2

# 这些 key 只是检索元数据，里面的数字（如文件名里的年份）不是产品数据，
# 不许计入"有出处的数字"。
_NON_DATA_KEYS = frozenset({
    "label", "source_file", "library_id", "root_path", "matched_terms",
})

# 模板占位符：只认 "{单词}"，不会误伤提示词里的 JSON 示例（{"draft": ...}）。
_SLOT_RE = re.compile(r"\{(\w+)\}")

# 草稿生成提示词
_DRAFT_PROMPT = """\
你是 B2B 外贸销售助理。根据下面给定的材料，写一版**可以直接发给客户**的回复草稿。

## 硬性要求

1. **只用给定材料里的事实**。产品库条目里没有的数字（价格、MOQ、规格、交期、认证），
   一律写"（待确认）"，**绝对不许自己填一个看起来合理的数字**。
2. **语种与客户一致**：客户用什么语言写，就用什么语言回（英文客户 → 英文草稿）。
3. **一版就够**，不要给多个方案、不要罗列一堆选项。
4. 语气专业、简短、像真人写的：先回应客户关心的问题，再给下一步动作。
5. 不要写"根据我的知识库""根据产品库"这类内部话术。
6. 如果材料不足以回答，直接说需要向客户确认什么，不要编。

## 输出格式

严格输出这个 JSON（不要任何解释文字、不要 markdown 代码块）：
{"draft": "回复正文", "summary_zh": "一行中文大意（不超过 40 字）",
 "sources": [{"label": "出处（文档名或字段名）", "value": "该出处支撑的数字"}]}

sources 只列草稿里**实际用到**的数字出处；没有用到数字就给空数组。

## 客户最新消息

{customer_message}

## 该客户的历史（可能为空）

{history}

## 产品库条目（数字只能来自这里）

{products}

## 客户档案

{profile}
"""

# 兼容旧测试/旧调用：数字识别的实现已统一到 trade.copilot.numbers。
_NUMBER_RE = NUMBER_RE
_extract_numbers = extract_numbers


def _allowed_numbers(ctx: CustomerContext) -> set[str]:
    """产品条目里出现过的数字（= 允许出现在草稿里的数字）。

    只认数据字段（正文摘录、价格、MOQ 等）与 facts.value；文件名/库路径里的
    数字不算 —— 否则 "报价2026.pdf" 会让草稿里的 2026 被误判成有出处。
    """
    allowed: set[str] = set()
    for entry in ctx.product_entries or []:
        for key, value in entry.items():
            if key in _NON_DATA_KEYS:
                continue
            if isinstance(value, str):
                allowed |= extract_numbers(value)
    for fact in ctx.facts or []:
        allowed |= extract_numbers(fact.value)
    return allowed


def strip_unbacked_numbers(draft: str, ctx: CustomerContext) -> tuple[str, bool]:
    """剔除草稿里**产品库没有**支撑的数字。

    Returns:
        (清理后的草稿, 是否动过)。剔除时把该数字替换成"（待确认）" ——
        宁可留个占位，也不让一个没有出处的数字发出去（铁律 3）。
    """
    allowed = _allowed_numbers(ctx)
    if not allowed:
        # 产品库一条都没有 → 任何数字都不许出现在草稿里
        if not _extract_numbers(draft):
            return draft, False
        return _NUMBER_RE.sub("（待确认）", draft), True

    changed = False

    def _replace(match: re.Match) -> str:
        nonlocal changed
        raw = match.group(0)
        # 比对用归一 key：库里 "USD 3.50" 与草稿 "$3.50" 必须算同一个数字。
        key = number_key(raw)
        if key is not None and key in allowed:
            return raw
        changed = True
        return "（待确认）"

    return NUMBER_RE.sub(_replace, draft), changed


def build_prompt(
    customer_message: str,
    ctx: CustomerContext,
    *,
    customer_name: str = "",
) -> str:
    """组装草稿提示词（各段落来自既有上下文，不另写一套约束）。"""
    history_lines = ctx.history or []
    history = "\n".join(f"- {h}" for h in history_lines) if history_lines else "（无）"

    products = "（产品库没有可用条目 —— 草稿里不许出现任何数字，未知处写「（待确认）」）"
    if ctx.product_entries:
        lines = []
        for entry in ctx.product_entries:
            label = str(entry.get("label") or "")
            body = "；".join(
                f"{k}={v}" for k, v in entry.items()
                if k not in ("label", "root_path", "library_id") and v
            )
            lines.append(f"- [{label}] {body or '（该文档未解析出结构化字段）'}")
        products = "\n".join(lines)

    profile = "（未识别客户）"
    if ctx.matched and ctx.customer_name:
        profile = f"客户名：{ctx.customer_name}（客户档案 id={ctx.customer_id}）"

    # 提示词里含 JSON 示例（带花括号），不能用 str.format。
    # 必须是**单遍**替换：客户消息里如果恰好写了 "{history}"，链式 replace 会把它
    # 也换成历史段（注入 + 内容错位）。单遍替换只扫模板，不扫插入的值。
    slots = {
        "customer_message": customer_message or "（无）",
        "history": history,
        "products": products,
        "profile": profile,
    }
    return _SLOT_RE.sub(lambda m: slots.get(m.group(1), m.group(0)), _DRAFT_PROMPT)


def parse_draft(raw: str) -> DraftResult:
    """解析草稿 JSON。解析失败 → 带 error 的结果（不返回空草稿）。"""
    from trade.copilot.extract import _parse_json_object

    obj = _parse_json_object(raw)
    if obj is None:
        return DraftResult(error="草稿生成结果不是有效 JSON，请重试")
    draft = str(obj.get("draft") or "").strip()
    if not draft:
        return DraftResult(error="草稿为空，请重试")
    sources = []
    for item in obj.get("sources") or []:
        if isinstance(item, dict):
            sources.append(SourceRef(
                label=str(item.get("label") or ""),
                value=str(item.get("value") or ""),
            ))
    return DraftResult(
        draft=draft,
        summary_zh=str(obj.get("summary_zh") or "").strip(),
        sources=sources,
    )


def generate_draft(
    customer_message: str,
    ctx: CustomerContext,
    *,
    company_id: int,
    timeout: float = DEFAULT_TIMEOUT,
) -> DraftResult:
    """生成一版草稿。

    走 `trade.api.chat` 的会话执行路径（公司绑定沿用既有机制）。

    失败**一律**转成 `DraftResult.error`（复审 P1-4）：Hermes 的异常里有继承
    `SystemExit` 的 `RelaunchExit`，只捕 `Exception` 会一路穿出去把调用方带崩。
    超时是**真**的截止时间（后台线程 + 事件等待），不是摆设。
    """
    # 到期软着陆：试用/许可证结束后不能再出**新**草稿（已生成的草稿仍可查看）。
    # 许可证是整机一份，company_id 仅用于兼容签名。
    try:
        from trade.license import check_license

        lic_ok, lic_msg = check_license(company_id)
    except Exception:
        lic_ok, lic_msg = True, ""  # 许可证模块异常不阻断（缺省可用，与主聊天一致）
    if not lic_ok:
        return DraftResult(
            error=f"许可证已到期，暂时不能生成新草稿。{lic_msg}".strip()
        )

    prompt = build_prompt(customer_message, ctx)

    try:
        raw = _run_with_retries(prompt, company_id=company_id, timeout=timeout)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 —— 见上：必须连 SystemExit 一起兜住
        _log.error("副驾草稿生成失败：%s", exc, exc_info=True)
        return DraftResult(error=f"草稿生成失败：{type(exc).__name__}: {exc}")

    if not raw:
        return DraftResult(error="草稿生成无输出，请重试")

    result = parse_draft(raw)
    if not result.ok:
        return result

    # 铁律 3 的第二道防线：剔除没有出处的数字
    cleaned, changed = strip_unbacked_numbers(result.draft, ctx)
    result.draft = cleaned
    result.has_placeholder = changed or ("（待确认）" in cleaned)
    if changed:
        # 数字被剔掉后，原来声称支撑它的出处也不能再留着（复审 P2）——
        # 否则 UI 会展示"出处：报价单 $3.50"，而草稿里那个 $3.50 已变成占位符。
        result.sources = _reconcile_sources(result.sources, cleaned)
        _log.info("副驾草稿剔除了没有出处的数字（剩余出处 %d 条）", len(result.sources))

    # 试用期价值小结：只有真正产出一版草稿才计数
    try:
        from trade.trial_usage import KIND_DRAFT, record_event

        record_event(KIND_DRAFT, company_id)
    except Exception:
        pass
    return result


def _reconcile_sources(sources: list[SourceRef], draft: str) -> list[SourceRef]:
    """只保留其数字仍在草稿里的出处；非数字出处（如"客户档案"）保留。"""
    draft_numbers = extract_numbers(draft)
    kept: list[SourceRef] = []
    for source in sources:
        numbers = extract_numbers(source.value)
        if not numbers or (numbers & draft_numbers):
            kept.append(source)
    return kept


def _run_with_retries(prompt: str, *, company_id: int, timeout: float) -> str:
    """在总截止时间内最多尝试 `_DRAFT_ATTEMPTS` 次，返回模型原文。"""
    deadline = time.monotonic() + max(0.1, timeout)
    last_error: BaseException | None = None

    for attempt in range(_DRAFT_ATTEMPTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            raw = _call_with_deadline(
                lambda: _run_once(prompt, company_id=company_id),
                remaining,
            )
            if raw:
                return raw
            _log.warning("副驾草稿返回空文本（attempt %d/%d）", attempt + 1, _DRAFT_ATTEMPTS)
        except (Exception, SystemExit) as exc:
            last_error = exc
            _log.warning("副驾草稿调用失败（attempt %d/%d）：%s", attempt + 1, _DRAFT_ATTEMPTS, exc)

        if attempt + 1 < _DRAFT_ATTEMPTS:
            # 重试前留 0.5s 给截止时间收尾；剩余不到 1s 就不睡（避免把预算睡光）
            pause = min(1.0, max(0.0, deadline - time.monotonic() - 0.5))
            if pause > 0:
                time.sleep(pause)

    if last_error is not None:
        raise last_error
    raise TimeoutError(f"草稿生成超时（{timeout:.0f}s）")


def _call_with_deadline(fn, timeout: float):
    """在 daemon 线程里跑 fn，最多等 timeout 秒。

    用 daemon 线程而不是 ThreadPoolExecutor：后者在解释器退出时会 join 工作线程，
    一旦 agent 卡死会把整个进程的退出也拖住。
    """
    box: dict[str, object] = {}
    done = threading.Event()

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 —— 原样带回调用方再分类
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=_target, name="copilot-draft", daemon=True).start()
    if not done.wait(timeout):
        raise TimeoutError(f"草稿生成超时（{timeout:.0f}s）")
    error = box.get("error")
    if error is not None:
        raise error  # type: ignore[misc]
    value = box.get("value")
    return value if isinstance(value, str) else ""


def _run_once(prompt: str, *, company_id: int) -> str:
    """跑一次草稿请求（既有会话路径）。

    曾经预留过 `trade.api.chat.run_draft_session` 分支，但该函数从来没存在过：
    每次调用都要 import 一次 2 秒级的 `trade.api.chat`，然后必然走 ImportError。
    删掉分支后省下这次 import，语义不变。
    """
    return _run_via_existing_chat(prompt, company_id=company_id)


def _run_via_existing_chat(prompt: str, *, company_id: int) -> str:
    """跑一次草稿请求：**无工具**、只带公司身份的最小路径。

    为什么不再走 `build_query` + 默认 agent（2026-10-23 审计 P0）：
      - 客户消息和产品库摘录都是不可信文本，默认 agent 带 file/terminal/
        code_execution 且全局 YOLO —— 文档里一句「读取 ~/.trade/...」就能
        把本机文件带进草稿；
      - build_query 还会把全公司最近 20 条对话和 20 笔订单无差别塞进 prompt，
        直接违反副驾铁律 4（不许把别家客户上下文带进来）。
    草稿需要的事实已经在 prompt 里（产品条目/命中客户历史），不需要工具。
    """
    from trade.company import get_trade_company, slug_from_id
    from trade.helpers import create_agent
    from trade.prompts import resolve_system_prompt

    slug = None
    db_identity = ""
    try:
        slug = slug_from_id(company_id)
        db_identity = (get_trade_company(company_id) or {}).get(
            "agent_identity_md", ""
        ) or ""
    except Exception:
        pass

    system_prompt = resolve_system_prompt(
        company_slug=slug, db_identity=db_identity,
    )
    agent = create_agent(
        ephemeral_system_prompt=system_prompt,
        skill_name=None,
        enabled_toolsets=[],
    )
    result = agent.chat(prompt)
    return result if isinstance(result, str) else ""
