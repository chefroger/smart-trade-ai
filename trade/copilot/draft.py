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

from trade.copilot.types import CustomerContext, DraftResult, SourceRef

_log = logging.getLogger(__name__)

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

# 数字的判定：金额 / 尺寸 / 数量 / 规格
_NUMBER_RE = re.compile(
    # 顺序要紧：带单位/词的那种要排在纯数字前面，否则 "30 天" 里的 30 会被
    # 金额或裸数字分支先吃掉、丢掉"天"这个语义。
    r"(?:\bMOQ\s*[:：]?\s*\d[\d,]*)"                        # MOQ 500
    r"|(?:[$€£¥￥]\s?\d[\d,]*(?:\.\d+)?)"                    # 金额 $3.50
    r"|(?:\b\d[\d,]*(?:\.\d+)?\s?(?:mm|cm|m|kg|g|pcs|units|ton|kW|V|W|kV|mA|Hz|°C|℃|%)\b)"
    r"|(?:\d+\s*(?:个工作日|天|日|weeks?))"                    # 交期 30 天（中文无 \b 边界）
    r"|(?:\b\d+(?:\.\d+)?\s?kV\b)",                         # 33kV（上面那条不含 kV 变体）
    re.IGNORECASE,
)


def _extract_numbers(text: str) -> set[str]:
    """抽出文本里的数字（归一：去千分位与空格，便于比对）。"""
    if not text:
        return set()
    out: set[str] = set()
    for match in _NUMBER_RE.finditer(text):
        raw = match.group(0).strip()
        normalized = re.sub(r"[\s,]", "", raw)
        if normalized:
            out.add(normalized)
    return out


def _allowed_numbers(ctx: CustomerContext) -> set[str]:
    """产品条目里出现过的数字（= 允许出现在草稿里的数字）。"""
    allowed: set[str] = set()
    for entry in ctx.product_entries or []:
        for value in entry.values():
            if isinstance(value, str):
                allowed |= _extract_numbers(value)
    for fact in ctx.facts or []:
        allowed |= _extract_numbers(fact.value)
        allowed |= _extract_numbers(fact.label)
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
        normalized = re.sub(r"[\s,]", "", raw.strip())
        if normalized in allowed:
            return raw
        changed = True
        return "（待确认）"

    return _NUMBER_RE.sub(_replace, draft), changed


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

    # 提示词里含 JSON 示例（带花括号），不能用 str.format —— 改用显式占位替换
    out = _DRAFT_PROMPT
    out = out.replace("{customer_message}", customer_message or "（无）")
    out = out.replace("{history}", history)
    out = out.replace("{products}", products)
    out = out.replace("{profile}", profile)
    return out


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
    timeout: float = 60.0,
) -> DraftResult:
    """生成一版草稿。

    走 `trade.api.chat` 的会话执行路径（公司绑定沿用既有机制）。
    """
    prompt = build_prompt(customer_message, ctx)

    try:
        from trade.api.chat import run_draft_session  # type: ignore
    except ImportError:
        run_draft_session = None

    raw = ""
    if run_draft_session is not None:
        try:
            raw = run_draft_session(
                prompt, company_id=company_id, timeout=timeout
            )
        except Exception as exc:
            _log.warning("副驾草稿生成失败：%s", exc)
            return DraftResult(error=f"草稿生成失败：{type(exc).__name__}: {exc}")
    else:
        # chat.py 还没有专用的草稿入口时，走既有的 chat 端点内部函数
        raw = _run_via_existing_chat(prompt, company_id=company_id, timeout=timeout)

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
        _log.info("副驾草稿剔除了 %s 个没有出处的数字", "若干")
    return result


def _run_via_existing_chat(prompt: str, *, company_id: int, timeout: float) -> str:
    """经 trade 现有的会话执行路径跑一次请求，返回模型文本。

    刻意**不**新造隔离：走 `build_query` + `create_agent`，公司身份与技能注入
    都由 trade 既有机制决定。
    """
    from trade.helpers import build_query, create_agent

    full_query, skill_hint = build_query(
        company_id, None, prompt, customer_id=None,
        last_skill_name=None, language="zh",
    )
    agent = create_agent(ephemeral_system_prompt=skill_hint, skill_name=None)
    result = agent.chat(full_query)
    return result if isinstance(result, str) else ""
