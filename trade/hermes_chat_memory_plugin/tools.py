"""chat-memory 插件的工具实现。

为何需要把 search_history 薄封装一次，而不是让 LLM 直接调 trade.chat_memory：
- 该模块期望在**trade 进程内**被 import（从 trade.chat_memory 路径）—— 在 Hermes 进程里
  import 是 Hermes 自己的 trade 安装副本（如果有），未必一致。
- 通过插件 __init__.py 把 trade 注入到 Hermes 进程的 sys.path 后再 import；这里是**接缝**。
"""

from __future__ import annotations

import logging
import re as _re
from typing import Any

_log = logging.getLogger(__name__)


def _str(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """与 google_meet 同型的 schema 构造（plugins/AGENTS.md 约定的格式）。"""
    params: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        params["required"] = required
    return {"name": name, "description": description, "parameters": params}


# 枚举值与 trade.chat_memory.search_history 的 _BOUNDARY_COMPUTERS 一一对应。
# 增删时**两边同步**（测试钉住）。
_TIME_RANGES_DESCRIPTION = """\
时间范围枚举：
- today / this_week / this_month / this_year 含"现在"（含端点 start，不含结束）；
- yesterday / last_week / last_month / last_year 不含"现在"（前一周期完整窗口）；
- all 不限。
未知值服务端按 all 兜底（fail-safe —— 与 search_history 的旧行为一致）。
"""

_RECENT_DAYS_DESCRIPTION = (
    "可选。过去 N 天（含今天）的窗口，start = (now - (N-1) 天) 的 00:00。"
    "注意 N=1 等价于 'today'（今天 00:00 起），**不是** 'yesterday' —— "
    "要昨天的数据请用 time_range='yesterday'。"
    "用于表达枚举表里没有的相对区间（如 '上上周三' = 14）。"
    "**与 time_range 互斥**：若都给了本参数优先；建议在 augment_prompt 里告诉 LLM 不要同时给。"
)

_RECENT_MONTHS_DESCRIPTION = (
    "可选。过去 N 个月（含本月）。逐月回退，遇 1 月走 12/去年。用于 '前几个月' 这类模糊词。"
    "**与 time_range 互斥**。"
)


CHAT_MEMORY_LIST_SCHEMA = _schema(
    "chat_memory_list",
    "查 trade 用户的对话历史（SQLite，按 company_id 严格隔离）。"
    "**company_id 必填**——必须传用户在 system prompt 的 Trade Context 段里写明的那个数字，"
    "**不能**从用户消息推断，传错会读到其他公司的数据。"
    "时间范围默认 'all'；给具体枚举值能精确窗口；recent_days/recent_months 用来表达枚举外的相对区间。",
    {
        "company_id": {
            "type": "integer",
            "description": (
                "当前会话的公司 ID。从 system prompt 的 'Trade Context' 段读取；"
                "**不要**让用户输入这个值。服务端会校验它与当前会话绑定一致，"
                "不一致直接拒绝。"
            ),
        },
        "time_range": {
            "type": "string",
            "enum": [
                "today", "yesterday",
                "this_week", "last_week",
                "this_month", "last_month",
                "this_year", "last_year",
                "all",
            ],
            "description": _TIME_RANGES_DESCRIPTION,
        },
        "recent_days": {
            "type": "integer",
            "minimum": 1,
            "description": _RECENT_DAYS_DESCRIPTION,
        },
        "recent_months": {
            "type": "integer",
            "minimum": 1,
            "description": _RECENT_MONTHS_DESCRIPTION,
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "default": 20,
            "description": "最大返回条数。默认 20。",
        },
    },
    required=["company_id"],
)


def handle_chat_memory_list(args: dict[str, Any], **_kw) -> str:
    """插件 handler 签名：handle(args, **_kw)。

    **_kw 来自 dispatcher 注入**（task_id/session_id 等），signatures 已被 Hermes
    用 inspect 过滤（plugins/AGENTS.md），所以"宽收"是安全的。
    """
    # 公司身份以**服务端绑定**为准（2026-10-23 审计 P0-2）：
    # 工具参数是模型生成的不可信输入，注入一句"传 company_id=2"就能读别家历史。
    # 绑定由 Trade 在 agent.chat() 外层通过 ContextVar 设置，Hermes 的工具
    # 执行器会随线程复制上下文。
    try:
        from trade.agent_context import current_company_id, current_customer_id

        bound_company = current_company_id()
        bound_customer = current_customer_id()
    except ImportError as exc:
        return _err(f"trade agent context unavailable: {exc}")

    if bound_company is None:
        return _err(
            "chat_memory_list is only available inside a Trade chat session "
            "(company context is not bound). Refusing to read history."
        )

    # 模型仍然会按 schema 传 company_id；只做一致性校验，绝不采用它的值
    claimed = args.get("company_id")
    if not isinstance(claimed, int) or claimed <= 0:
        return _err(
            "company_id is required and must be a positive integer — "
            "read it from the system prompt's 'Trade Context' section."
        )
    if claimed != bound_company:
        return _err(
            f"company_id {claimed} does not match the active Trade session; "
            "refusing to read another company's history."
        )
    company_id = bound_company

    time_range = args.get("time_range") or "all"
    if not isinstance(time_range, str):
        return _err(f"time_range must be a string (got {type(time_range).__name__})")
    recent_days = args.get("recent_days")
    recent_months = args.get("recent_months")
    if recent_days is not None and not isinstance(recent_days, int):
        return _err(f"recent_days must be an integer or omitted (got {type(recent_days).__name__})")
    if recent_months is not None and not isinstance(recent_months, int):
        return _err(f"recent_months must be an integer or omitted (got {type(recent_months).__name__})")
    if recent_days is not None and recent_days <= 0:
        return _err("recent_days must be positive")
    if recent_months is not None and recent_months <= 0:
        return _err("recent_months must be positive")
    # recent_days 与 recent_months 互斥（schema 允许但只能用一个）
    if recent_days is not None and recent_months is not None:
        return _err("recent_days and recent_months are mutually exclusive — pass only one")

    try:
        limit = int(args.get("limit") or 20)
    except (TypeError, ValueError):
        return _err("limit must be an integer")
    if limit < 1 or limit > 100:
        return _err("limit must be between 1 and 100")

    try:
        from trade.chat_memory import search_history
    except ImportError as exc:
        return _err(
            f"trade package not importable from Hermes process: {exc}. "
            "This usually means the chat-memory plugin was loaded outside a Trade context — "
            "check that trade-bootstrap adds Trade to sys.path before Hermes loads plugins."
        )

    try:
        rows = search_history(
            company_id=company_id,
            time_range=time_range,
            limit=limit,
            recent_days=recent_days,
            recent_months=recent_months,
            # 选中客户时只查该客户；未选客户时只返回未归属对话，
            # 避免工具层绕过 prompt 层的客户隔离（审计 P1-2）
            customer_id=bound_customer,
            unattributed_only=bound_customer is None,
        )
    except Exception as exc:
        # 异常不外抛（plugins/AGENTS.md: handler 失败返回 tool_error）。
        # traceback 只进本机日志：返回给 LLM 等于把 trade 内部路径/帧信息写进
        # 提示词（审计 P2-1）。
        _log.exception("search_history failed")
        return _err(f"search_history failed: {type(exc).__name__}")

    return _json({
        "company_id": company_id,
        "time_range": time_range,
        "recent_days": recent_days,
        "recent_months": recent_months,
        "count": len(rows),
        "rows": rows,
    })


OSINT_JOB_START_SCHEMA = _schema(
    "osint_job_start",
    "启动一个**后台**背调任务（6 层 + 公开来源），立即返回 job_id，不阻塞聊天。"
    "**一次用户请求只启动一个后台任务**：不要把同一家公司的公司名和官网域名拆成两个 job，"
    "直接传官网域名（若已知）或公司名即可，编排器会自动解析并并行跑各层。"
    "仅在需要消歧时加前缀（如人名 person:、用户名 username:）。"
    "10 分钟内同公司同目标（忽略前缀/大小写差异）的**排队/运行中**任务会自动复用；已完成的任务会重新跑。"
    "启动后用 osint_job_result 读取进度与结果。"
    "返回里带 known_facts：此前已核实过的事实（同目标），先看它，别重复查。",
    {
        "target": _str("背调目标（单次只传一个主目标，如 acme.com 或 \"Acme Corp\" 或 person:\"Jane Doe\"）"),
    },
    ["target"],
)

OSINT_FACT_SAVE_SCHEMA = _schema(
    "osint_fact_save",
    "登记一条背调事实（字段 / 值 / 来源），存进本公司的背调事实库。"
    "**查到就登记**：下次同目标背调会直接复用，不必再赌一次反爬。"
    "同一字段查到不同值时照实再登记一次，系统会标为冲突（报告要并列写出，不要挑一个）。"
    "只登记有来源的事实；没有来源的推测不要登记。",
    {
        "target": _str("这条事实属于哪个目标（公司名 / 域名 / 人名）"),
        "field": _str("字段名，如「注册资本」「法定代表人」「统一社会信用代码」「员工人数」"),
        "value": _str("字段值，照抄来源原文"),
        "source_url": _str("来源 URL（有就填，没有留空）"),
        "source_name": _str("来源站点名，如「企查查」「阿里巴巴」"),
    },
    ["target", "field", "value"],
)

OSINT_FACT_LIST_SCHEMA = _schema(
    "osint_fact_list",
    "读取本公司的背调事实库（此前已核实的字段 / 值 / 来源）。"
    "给了 target 就只读该目标；不填就列出全部。"
    "conflict=true 的字段说明两次查到了不同值 —— 报告里要并列写出两个值并标注来源。",
    {
        "target": _str("目标（公司名 / 域名 / 人名）；不填则列出全部已登记事实"),
    },
    [],
)

OSINT_JOB_RESULT_SCHEMA = _schema(
    "osint_job_result",
    "读取后台背调任务的当前状态与结果（不阻塞）。status 为 done 时 report 是完整结构化报告；"
    "running 时 events 是到目前为止的逐来源进度；cancelled/partial/failed 表示任务未完成。",
    {
        "job_id": {"type": "integer", "description": "osint_job_start 返回的 job_id"},
        "after_seq": {
            "type": "integer",
            "description": "只看 seq 之后的增量事件（默认 0 = 最近 50 条）",
        },
    },
    ["job_id"],
)


def _bound_company():
    """当前 agent 调用绑定的公司 id（未绑定返回 None）。"""
    try:
        from trade.agent_context import current_company_id

        return current_company_id()
    except ImportError:
        return None


_URL_IN_TEXT_RE = _re.compile(r"https?://[^\s<>\"'`）)】]+", _re.IGNORECASE)


def _source_url_verified(source_url: str) -> bool:
    """来源 URL 是否出现在本轮已完成工具的证据里（P1-D / W15 O-4）。

    必须做**完整 URL 相等**比较，不能用子串：`https://evil/?u=https://good`
    这类参数里嵌套的地址会让子串匹配误判为「已核实」。
    没有证据（Hermes 独立运行、或模型自己编的 URL）一律不算核实。
    """
    url = str(source_url or "").strip().lower().rstrip("/")
    if not url:
        return False
    try:
        from trade.agent_context import current_tool_evidence

        for text in current_tool_evidence():
            for candidate in _URL_IN_TEXT_RE.findall(str(text)):
                if candidate.strip().lower().rstrip("/.,;)") == url:
                    return True
        return False
    except Exception:
        return False


def handle_osint_job_start(args: dict[str, Any], **_kw) -> str:
    """创建并启动后台背调任务。"""
    target = str(args.get("target") or "").strip()
    if not target:
        return _err("target is required")
    company_id = _bound_company()
    if company_id is None:
        return _err("没有公司上下文，拒绝创建背调任务")

    try:
        from trade import osint_jobs

        job, created = osint_jobs.create_job(company_id, target)
        if created:
            osint_jobs.start_job(job["id"], target)
    except Exception as exc:  # noqa: BLE001
        return _err(f"创建背调任务失败：{exc}")

    # 同目标此前核实过的事实：让模型先看它，别重复查（也不必再赌一次反爬）
    known: dict = {}
    unverified: dict = {}
    try:
        from trade import osint_facts

        known = osint_facts.known_facts(company_id, target)
        unverified = osint_facts.unverified_facts(company_id, target)
    except Exception:  # noqa: BLE001 —— 事实库是增强项，读不到不影响背调
        known = {}

    return _json({
        "job_id": job["id"],
        "status": job["status"],
        "reused": not created,
        "target": target,
        "known_facts": known,
        # 上次未能核实的事实：可以重新查，但不能当结论直接引用
        "unverified_facts": unverified,
    })


def handle_osint_fact_save(args: dict[str, Any], **_kw) -> str:
    """登记一条背调事实（供下次复用）。"""
    target = str(args.get("target") or "").strip()
    field = str(args.get("field") or "").strip()
    value = str(args.get("value") or "").strip()
    if not target or not field or not value:
        return _err("target / field / value 都是必填")
    company_id = _bound_company()
    if company_id is None:
        return _err("没有公司上下文，拒绝登记事实")

    try:
        from trade import osint_facts

        source_url = str(args.get("source_url") or "")
        row = osint_facts.save_fact(
            company_id, target, field, value,
            source_url=source_url,
            source_name=str(args.get("source_name") or ""),
            # 来源必须在本轮已完成工具结果里出现过才算核实（P1-D）
            verified=_source_url_verified(source_url),
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"登记事实失败：{exc}")

    if row is None:
        return _err("事实内容为空或过长，未登记")
    return _json({"saved": True, "fact": row})


def handle_osint_fact_list(args: dict[str, Any], **_kw) -> str:
    """读取本公司的背调事实库。"""
    company_id = _bound_company()
    if company_id is None:
        return _err("没有公司上下文，拒绝读取事实库")
    target = str(args.get("target") or "").strip() or None
    try:
        from trade import osint_facts

        known = osint_facts.known_facts(company_id, target)
        unverified = osint_facts.unverified_facts(company_id, target)
        rows = osint_facts.list_facts(company_id, target)
    except Exception as exc:  # noqa: BLE001
        return _err(f"读取事实库失败：{exc}")
    return _json({
        "known_facts": known,
        # 未核实：可以重新查，但不能当结论直接引用
        "unverified_facts": unverified,
        "conflicts": [f for f, b in known.items() if b.get("conflict")],
        "facts": rows,
    })


def handle_osint_job_result(args: dict[str, Any], **_kw) -> str:
    """读取后台背调任务状态与（增量）事件。"""
    try:
        job_id = int(args.get("job_id"))
    except (TypeError, ValueError):
        return _err("job_id must be an integer")
    after_seq = args.get("after_seq", 0)
    try:
        after_seq = max(0, int(after_seq or 0))
    except (TypeError, ValueError):
        after_seq = 0

    company_id = _bound_company()
    if company_id is None:
        return _err("没有公司上下文，拒绝读取背调任务")

    try:
        from trade import osint_jobs

        job = osint_jobs.get_job(company_id, job_id)
        if job is None:
            return _err("job not found")
        events = osint_jobs.list_events(job_id, after_seq=after_seq, limit=50)
    except Exception as exc:  # noqa: BLE001
        return _err(f"读取背调任务失败：{exc}")

    # 已核实过的事实：报告写作时用（复用 + 冲突并列）；未核实单独列出
    known: dict = {}
    unverified: dict = {}
    try:
        from trade import osint_facts

        known = osint_facts.known_facts(company_id, job.get("target"))
        unverified = osint_facts.unverified_facts(company_id, job.get("target"))
    except Exception:  # noqa: BLE001
        known = {}

    return _json({
        "job": {
            "id": job["id"],
            "target": job["target"],
            "status": job["status"],
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
            "report": job.get("report"),
        },
        "events": events,
        "known_facts": known,
        "unverified_facts": unverified,
        "conflicts": [f for f, b in known.items() if b.get("conflict")],
        "next_after_seq": events[-1]["seq"] if events else after_seq,
    })


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, default=str)


def _err(msg: str) -> str:
    return _json({"error": msg})


# ==============================================================================
# 供应商管理一期 · 第二批工具（受控写入候选供应商 + 3 个内部只读查询工具）
# ==============================================================================

_SUPPLIER_INTERNAL_NOTICE = (
    "内部采购数据，仅供内部查询，禁止写入给客户的邮件、报价单等对外文案。"
)

SUPPLIER_CANDIDATE_SAVE_SCHEMA = _schema(
    "supplier_candidate_save",
    "将 b2b-china-leads 找到的国内厂家线索保存为本公司供应商库中的「候选」供应商"
    "（status='候选'，source='china-leads'）。"
    "入库前必须先将候选名单给用户确认，用户未明确同意前不得调用。"
    "同公司已有同名供应商时不重复新建，直接返回既有 supplier_id。"
    + _SUPPLIER_INTERNAL_NOTICE,
    {
        "name": _str("供应商全称（必填）"),
        "short_name": _str("简称（可选）"),
        "main_products": _str("主营产品/品类（可选）"),
        "province": _str("所在省份（可选）"),
        "city": _str("所在城市（可选）"),
        "source_url": _str("线索来源 URL（可选）"),
        "note": _str("备注信息（可选）"),
        "contact": {
            "type": "object",
            "description": "可选联系人信息（name/phone/wechat）",
            "properties": {
                "name": _str("联系人姓名"),
                "phone": _str("联系电话"),
                "wechat": _str("微信号"),
            },
            "additionalProperties": False,
        },
        "contact_name": _str("联系人姓名（可选，与 contact.name 等效）"),
        "contact_phone": _str("联系电话（可选，与 contact.phone 等效）"),
        "contact_wechat": _str("微信号（可选，与 contact.wechat 等效）"),
    },
    ["name"],
)

SUPPLIER_QUOTE_SEARCH_SCHEMA = _schema(
    "supplier_quote_search",
    "按产品名、供应商 ID 或来源客户 ID 查询本公司历史采购报价（只读）。"
    + _SUPPLIER_INTERNAL_NOTICE,
    {
        "product_name": _str("产品名称关键词（模糊匹配，可选）"),
        "supplier_id": {"type": "integer", "description": "供应商 ID（可选）"},
        "customer_id": {"type": "integer", "description": "来源客户 ID（可选）"},
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 200,
            "default": 50,
            "description": "最大返回条数（默认 50，上限 200）",
        },
    },
    [],
)

SUPPLIER_COMPARE_SCHEMA = _schema(
    "supplier_compare",
    "按产品名（及可选规格型号）对本公司多家供应商做比价聚合（只读，按单位分组返回）。"
    + _SUPPLIER_INTERNAL_NOTICE,
    {
        "product_name": _str("要对比的产品名称（必填，模糊匹配）"),
        "spec_model": _str("规格型号关键词（可选，模糊匹配）"),
    },
    ["product_name"],
)

SUPPLIER_LIST_SCHEMA = _schema(
    "supplier_list",
    "按关键词或合作状态查询本公司供应商名录（只读）。"
    + _SUPPLIER_INTERNAL_NOTICE,
    {
        "q": _str("搜索关键词：匹配名称、简称或主营品类（可选）"),
        "status": _str("状态筛选：候选/洽谈中/合作中/暂停/黑名单（可选）"),
        "supplier_type": _str("供应商类型筛选（可选）"),
        "is_starred": {"type": "integer", "description": "星标筛选：1 仅星标（可选）"},
    },
    [],
)

SUPPLIER_DELIVERY_ALERTS_SCHEMA = _schema(
    "supplier_delivery_alerts",
    "查询本公司采购单的交期提醒（已逾期或未来 3 天内到期的未出货采购单，只读）。"
    + _SUPPLIER_INTERNAL_NOTICE,
    {},
    [],
)


def handle_supplier_candidate_save(args: dict[str, Any], **_kw) -> str:
    """受控写入：将国内找厂线索保存为候选供应商（同公司同名不新建）。"""
    company_id = _bound_company()
    # 无绑定公司上下文时拒绝任何写入
    if company_id is None:
        return _err("没有公司上下文，拒绝写入候选供应商")

    name = str(args.get("name") or "").strip()
    # 名称必填
    if not name:
        return _err("name is required")

    try:
        from trade import supplier as supplier_mod
        from trade.company.transfer import merge as merge_mod

        target_key = merge_mod.norm_name(name)
        existing_list = supplier_mod.list_suppliers(company_id)
        matched = next(
            (s for s in existing_list if merge_mod.norm_name(s.get("name")) == target_key),
            None,
        )
        # 同公司已有同名供应商（norm 口径）：不新建，返回既有 id 并注明已存在
        if matched is not None:
            return _json({
                "created": False,
                "already_exists": True,
                "supplier_id": matched["id"],
                "supplier": matched,
                "message": f"本公司已存在同名供应商「{matched['name']}」（ID #{matched['id']}），未重复新建",
            })

        source_url = str(args.get("source_url") or "").strip()
        extra1 = {"source_url": source_url} if source_url else {}
        note_text = str(args.get("note") or "").strip()
        # 有来源 URL 时同步记入备注方便界面查看
        if source_url and source_url not in note_text:
            note_text = f"{note_text}\n来源：{source_url}".strip() if note_text else f"来源：{source_url}"

        created = supplier_mod.create_supplier(
            company_id,
            name=name,
            short_name=str(args.get("short_name") or "").strip(),
            main_products=str(args.get("main_products") or "").strip(),
            province=str(args.get("province") or "").strip(),
            city=str(args.get("city") or "").strip(),
            status="候选",
            source="china-leads",
            note=note_text,
            extra1=extra1,
        )

        # 可选联系人（支持 contact 嵌套对象或扁平字段）
        contact_obj = args.get("contact") if isinstance(args.get("contact"), dict) else {}
        c_name = str(contact_obj.get("name") or args.get("contact_name") or "").strip()
        c_phone = str(contact_obj.get("phone") or args.get("contact_phone") or "").strip()
        c_wechat = str(contact_obj.get("wechat") or args.get("contact_wechat") or "").strip()
        created_contact = None
        if c_name:
            created_contact = supplier_mod.create_contact(
                company_id,
                int(created["id"]),
                name=c_name,
                phone=c_phone,
                wechat=c_wechat,
                is_primary=1,
            )

        return _json({
            "created": True,
            "already_exists": False,
            "supplier_id": created["id"],
            "supplier": created,
            "contact": created_contact,
        })
    except Exception as exc:  # noqa: BLE001
        _log.exception("handle_supplier_candidate_save failed")
        return _err(f"保存候选供应商失败：{exc}")


def handle_supplier_quote_search(args: dict[str, Any], **_kw) -> str:
    """内部只读查询：按产品/供应商/客户查询本公司历史采购报价。"""
    company_id = _bound_company()
    # 无绑定公司上下文时拒绝读取
    if company_id is None:
        return _err("没有公司上下文，拒绝查询供应商报价")

    try:
        from trade import supplier as supplier_mod

        sup_id = args.get("supplier_id")
        cust_id = args.get("customer_id")
        limit = int(args.get("limit") or 50)
        limit = max(1, min(limit, 200))
        rows = supplier_mod.search_quotes(
            company_id,
            product_name=str(args.get("product_name") or "").strip(),
            supplier_id=int(sup_id) if sup_id is not None else None,
            customer_id=int(cust_id) if cust_id is not None else None,
            limit=limit,
        )
        return _json({"count": len(rows), "quotes": rows})
    except Exception as exc:  # noqa: BLE001
        _log.exception("handle_supplier_quote_search failed")
        return _err(f"查询供应商报价失败：{exc}")


def handle_supplier_compare(args: dict[str, Any], **_kw) -> str:
    """内部只读查询：按产品名与规格比价。"""
    company_id = _bound_company()
    # 无绑定公司上下文时拒绝读取
    if company_id is None:
        return _err("没有公司上下文，拒绝执行产品比价")

    product_name = str(args.get("product_name") or "").strip()
    # 产品名称必填
    if not product_name:
        return _err("product_name is required")

    try:
        from trade import supplier as supplier_mod

        res = supplier_mod.compare_product(
            company_id,
            product_name=product_name,
            spec_model=str(args.get("spec_model") or "").strip(),
        )
        return _json(res)
    except Exception as exc:  # noqa: BLE001
        _log.exception("handle_supplier_compare failed")
        return _err(f"产品比价失败：{exc}")


def handle_supplier_list(args: dict[str, Any], **_kw) -> str:
    """内部只读查询：按关键词/状态查询本公司供应商名录。"""
    company_id = _bound_company()
    # 无绑定公司上下文时拒绝读取
    if company_id is None:
        return _err("没有公司上下文，拒绝查询供应商名录")

    try:
        from trade import supplier as supplier_mod

        starred = args.get("is_starred")
        rows = supplier_mod.list_suppliers(
            company_id,
            q=str(args.get("q") or "").strip(),
            status=str(args.get("status") or "").strip(),
            supplier_type=str(args.get("supplier_type") or "").strip(),
            is_starred=int(starred) if starred is not None else None,
        )
        return _json({"count": len(rows), "suppliers": rows})
    except Exception as exc:  # noqa: BLE001
        _log.exception("handle_supplier_list failed")
        return _err(f"查询供应商名录失败：{exc}")


def handle_supplier_delivery_alerts(args: dict[str, Any], **_kw) -> str:
    """内部只读查询：获取本公司采购单交期提醒（逾期与 3 天内临期）。"""
    company_id = _bound_company()
    # 无绑定公司上下文时拒绝读取
    if company_id is None:
        return _err("没有公司上下文，拒绝查询采购交期提醒")

    try:
        from trade import purchase as purchase_mod

        rows = purchase_mod.get_delivery_alerts(company_id)
        return _json({"count": len(rows), "alerts": rows})
    except Exception as exc:  # noqa: BLE001
        _log.exception("handle_supplier_delivery_alerts failed")
        return _err(f"查询采购交期提醒失败：{exc}")
