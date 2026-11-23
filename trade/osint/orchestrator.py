"""
Trade AI Assistant — OSINT 编排器：完整尽职调查流程。

osint_full_check() 是 OSINT 模块的统一入口，接收邮箱/域名/公司名，
自动识别类型后并发执行各层检测，最终输出综合风险评分报告。

并发与超时（2026-11-21 工单 P0-4）：
  - 各层互不依赖（都只依赖 target / 已解析的域名），用 asyncio.gather 并发；
  - 每层独立超时，另有全局预算 budget（默认 150 秒）；
  - 阻塞层跑在**守护线程**里 —— run_in_executor 的线程是非守护的，超时后
    仍在跑、解释器退出时要 join，一层卡 300 秒 CLI 就得陪 300 秒。
"""

from __future__ import annotations

import asyncio
import functools
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from trade import email_intel
from trade.osint.email_verify import verify_corporate_email
from trade.osint.linkedin_verify import linkedin_company_verify
from trade.osint.sanctions import check_sanctions
from trade.osint.scoring import (
    _LAYER_LABELS,
    assess_verification,
    compute_verdict,
    generate_recommendations,
)
from trade.osint.sources import (
    SOURCE_LABELS,
    TargetContext,
    source_applies,
    sources_enabled,
)
from trade.osint.sources import (
    SOURCES as PUBLIC_SOURCES,
)
from trade.osint.tech_stack import detect_tech_stack
from trade.osint.whois import domain_whois

# 单层超时（秒）。全局预算另由 osint_full_check(budget=...) 限制。
# sanctions 给 60 秒：首次运行要下载名单文件（下载本身在 check_sanctions 内部）；
# 工单 P0-1 改成后台每日刷新后，这里可以降到 20 秒左右。
_LAYER_TIMEOUTS: dict[str, float] = {
    "email_registration": 90.0,  # holehe 要探测 120+ 站点
    "domain_intel": 20.0,
    "email_verification": 20.0,
    "tech_stack": 20.0,
    "sanctions": 60.0,
    "linkedin": 10.0,
    # 公开来源（P2-2）：单源 15 秒（GDELT 偏慢，给 20 秒）
    "rdap": 15.0,
    "ct": 15.0,
    "wayback": 15.0,
    "pdns": 15.0,
    "github": 15.0,
    "gleif": 15.0,
    "vies": 15.0,
    "us_states": 15.0,
    "edgar": 15.0,
    "gdelt": 20.0,
    "gravatar": 15.0,
    "usernames": 25.0,
    "registries_misc": 15.0,
}

# 进度事件用的完整标签表（6 层 + 公开来源）
_PROGRESS_LABELS = {**_LAYER_LABELS, **SOURCE_LABELS}

# 进度事件回调类型：CLI --progress 用它往 stderr 写 JSONL
EventCallback = Callable[[dict], None]


async def osint_full_check(
    target: str,
    *,
    include_sanctions: bool = True,
    include_tech_stack: bool = True,
    include_linkedin: bool = True,
    budget: float = 150.0,
    on_event: EventCallback | None = None,
    source_fetcher=None,
) -> dict:
    """完整 OSINT 尽职调查（异步并发编排，LLM 友好）。

    接收邮箱 / 域名 / 公司名 / 人名，自动识别类型，**并发**执行各层检测，
    最终输出综合风险评分报告。人名可加显式前缀 `person:`，公司名可加
    `company:` 覆盖自动识别。

    各层互不依赖，并发执行；单层超时 + 全局预算两层保护。任一层的失败、
    超时、缺依赖都只影响该层自身（标 error/timeout），不会拖垮整份报告。

    Args:
        target: 邮箱 / 域名 / 公司名 / 人名（支持 `person:` / `company:` 前缀）
        include_sanctions: 是否包含制裁名单筛查（默认 True）
        include_tech_stack: 是否包含技术栈检测（默认 True）
        include_linkedin: 是否包含 LinkedIn 验证（默认 True）
        budget: 全局时间预算（秒），默认 150；预算耗尽时未完成的层标 timeout
        on_event: 可选进度回调，收到 source_start / source_done 事件 dict
        source_fetcher: 测试注入的公开来源取数函数（默认走真实 HTTP）

    Returns:
        完整报告 dict，结构见需求文档 3.11.8 节：
        {
            "target": str,
            "target_type": str,       # email | domain | url | company | person
            "overall_rating": str,    # "low" | "medium" | "high" | "incomplete"
            "overall_score": int | None,   # 0-100；None = 关键层未核验
            "provisional_score": int,      # 诊断用分数，非对外结论
            "unverified": list[dict],      # 未核验/未查的层及原因
            "flags": list[str],       # 红旗标记列表
            "layers": {               # 6 层检测结果
                "email_registration": dict | None,
                "domain_intel": dict,
                "email_verification": dict | None,
                "tech_stack": dict | None,
                "sanctions": dict | None,
                "linkedin": dict | None,
            },
            "sources": {              # 公开来源（P2-2）
                "rdap": dict, "ct": dict, "wayback": dict, "github": dict,
            },
            "recommendations": list[str],  # 行动建议
        }
    """
    target, forced_type = _split_type_prefix(target)
    target, forced_username = _split_username_prefix(target)
    target_type = forced_type or _detect_target_type(target)
    username_hint = forced_username or _extract_username(target, target_type)

    report: dict = {
        "target": target,
        "target_type": target_type,
        "overall_rating": "unknown",
        "overall_score": 0,
        "flags": [],
        "layers": {},
        "sources": {},
        "recommendations": [],
    }

    # ── 确定用于域名查询的目标 ──
    if target_type == "email":
        # 从邮箱提取域名，用于后续各层检测
        domain_from_email = target.split("@", 1)[1]
    else:
        # 非邮箱目标，无需从邮箱提取域名
        domain_from_email = None

    lookup_domain = _extract_lookup_domain(target, target_type, domain_from_email)

    # ── 规划各层：互不依赖，全部并发 ────────────────────────────────────
    # 每项: (阻塞函数, 位置参数)。真正的执行统一走 _run_layer（超时 + 进度）。
    planned: dict[str, tuple[Callable, tuple]] = {}

    if target_type == "email":
        # Layer 1: holehe 邮箱注册检测
        planned["email_registration"] = (email_intel.email_background_check, (target,))
        # Layer 3: 企业邮箱验证（DNS MX）
        planned["email_verification"] = (verify_corporate_email, (target,))

    if lookup_domain:
        # Layer 2: WHOIS 域名情报
        planned["domain_intel"] = (domain_whois, (lookup_domain,))

        if include_tech_stack:
            # Layer 4: 技术栈检测（依赖域名，不依赖 WHOIS 结果）
            planned["tech_stack"] = (detect_tech_stack, (f"https://{lookup_domain}",))

    if include_sanctions:
        # Layer 5: 制裁筛查。公司名解析（抓官网 title）与名单比对合成一个
        # 阻塞任务，整体受本层超时约束。
        planned["sanctions"] = (
            _sanctions_and_screen,
            (lookup_domain, domain_from_email or target),
        )

    # ── 公开来源（P2-2）：RDAP / CT / Wayback / GitHub ─────────────────
    # 与 6 层并发；RDAP/CT/Wayback 必须有域名，GitHub 按域名/人名/公司名搜索。
    public_planned: dict[str, Callable] = {}
    if sources_enabled():
        # EDGAR 等官方接口要求真实联系邮箱：优先当前公司的 contact_email，
        # 没有才回退环境变量/维护者地址（审计 P2-3）
        contact_email = ""
        try:
            from trade.agent_context import current_company_id

            _cid = current_company_id()
            if _cid:
                from trade.company import crud as _company_crud

                _row = _company_crud.get(_cid)
                contact_email = str((_row or {}).get("contact_email") or "").strip()
        except Exception:
            contact_email = ""
        ctx = TargetContext(
            target=target,
            target_type=target_type,
            domain=lookup_domain,
            email=target if target_type == "email" else None,
            person_name=target if target_type == "person" else None,
            company_name=target if target_type == "company" else None,
            username=username_hint,
            contact_email=contact_email,
        )
        for module in PUBLIC_SOURCES:
            if not source_applies(module.NAME, ctx):
                continue
            public_planned[module.NAME] = functools.partial(
                _run_public_source, module, ctx, source_fetcher,
            )

    deadline = time.monotonic() + max(0.0, budget)
    tasks = {
        source: _run_layer(
            source,
            fn,
            *args,
            timeout=min(_LAYER_TIMEOUTS[source], max(0.0, deadline - time.monotonic())),
            on_event=on_event,
        )
        for source, (fn, args) in planned.items()
    }
    for name, fn in public_planned.items():
        tasks[name] = _run_layer(
            name,
            fn,
            timeout=min(
                _LAYER_TIMEOUTS.get(name, 15.0),
                max(0.0, deadline - time.monotonic()),
            ),
            on_event=on_event,
        )
    results = dict(zip(tasks, await asyncio.gather(*tasks.values()), strict=True))
    report["sources"] = {name: results[name] for name in public_planned}

    # ── 落报告：未规划的层写 None / skipped ─────────────────────────────
    report["layers"]["email_registration"] = (
        results.get("email_registration") if target_type == "email" else None
    )
    if lookup_domain:
        report["layers"]["domain_intel"] = results["domain_intel"]
    else:
        # 人名/公司名无法直接提取域名（需先用搜索发现官网）
        report["layers"]["domain_intel"] = {
            "skipped": True,
            "reason": "目标名不含域名（人名/公司名需先发现官网）",
        }
    report["layers"]["email_verification"] = (
        results.get("email_verification") if target_type == "email" else None
    )
    report["layers"]["tech_stack"] = results.get("tech_stack")
    report["layers"]["sanctions"] = results.get("sanctions")

    # RDAP 补位：WHOIS 失败/无日期时用 RDAP 注册信息（P2-2）
    _apply_rdap_fallback(report)

    # ── 红旗映射（只认已核验的数据）────────────────────────────────────
    di = report["layers"]["domain_intel"]
    if di and not di.get("error") and not di.get("skipped"):
        if di.get("age_category") == "new":
            report["flags"].append("domain_age_new")
        if di.get("days_old") and di["days_old"] > 3650:
            report["flags"].append("domain_age_old")

    ev = report["layers"]["email_verification"]
    if ev:
        # 按**具体红旗**映射到评分用的标记名。
        # 历史上这里把任何 risk_flag 一律写成 "personal_email_domain" ——
        # 于是"域名没有 MX 记录"也被标成"个人邮箱"，扣分理由与事实不符。
        report["flags"].extend(_map_email_flags(ev.get("risk_flags") or []))

    ts = report["layers"]["tech_stack"]
    if ts and ts.get("is_free_platform"):
        # 网站使用免费建站工具（如 Wix/Shopify），可能为低预算公司
        report["flags"].append("free_platform")

    sa = report["layers"]["sanctions"]
    if sa and sa.get("is_sanctioned"):
        # 目标出现在制裁名单中，标记为严重风险
        report["flags"].append("sanctioned")

    # ── Layer 6: LinkedIn 验证（纯本地生成 browser_navigate 指令）──────
    if include_linkedin and lookup_domain:
        # 当 target 不是公司名时（如 email），用域名作为公司名线索
        _company_hint = target if target_type == "company" else lookup_domain
        if on_event:
            on_event({
                "event": "source_start",
                "source": "linkedin",
                "label": _LAYER_LABELS.get("linkedin", "linkedin"),
            })
        started = time.monotonic()
        report["layers"]["linkedin"] = linkedin_company_verify(lookup_domain, _company_hint)
        if on_event:
            on_event({
                "event": "source_done",
                "source": "linkedin",
                "status": "skipped",  # 只生成指令，需人工/浏览器实际执行
                "ms": int((time.monotonic() - started) * 1000),
            })
    else:
        # 用户关闭 LinkedIn 验证或缺少域名，跳过此层
        report["layers"]["linkedin"] = None

    # ── 核验完整性 + 综合评分（fail-closed，工单 P0-2）────────────────
    # 先列出哪些关键层没查成：制裁数据源降级、有域名但 WHOIS 失败。
    # 这些情况下 compute_verdict 会把评级改为 "incomplete"、分数置 None，
    # 避免「没查成」被当成「没风险」。
    report["unverified"] = assess_verification(
        report["layers"],
        has_domain=bool(lookup_domain),
        sanctions_requested=include_sanctions,
    )
    # 公开来源 status=hit 的数量（candidate 在未来版本里也不算命中。
    # 审计 P0-B：人名/公司名没有域名、公开来源也零命中时，本轮实际上只跑了
    # 制裁筛查，不能给 low/100。
    public_hits = sum(
        1 for item in report["sources"].values()
        if isinstance(item, dict) and item.get("status") == "hit"
    )
    score, rating, provisional = compute_verdict(
        report["flags"],
        report["unverified"],
        target_type=target_type,
        has_domain=bool(lookup_domain),
        public_hits=public_hits,
    )
    report["overall_score"] = score          # None = 未完成核验/仅完成制裁筛查
    report["overall_rating"] = rating
    report["provisional_score"] = provisional  # 仅供诊断，不是对外结论
    if rating == "limited":
        report["rating_note"] = (
            "仅完成制裁筛查：目标没有可查询域名，公开来源也没有命中；"
            "这不是低风险结论。补到官网或公司注册信息后请重新背调。"
        )

    # ── 生成建议 ───────────────────────────────────────────────────────
    report["recommendations"] = generate_recommendations(report)

    return report


# ─────────────────────────────────────────────────────────────────────────────
# 并发执行器：守护线程 + 单层超时 + 进度事件
# ─────────────────────────────────────────────────────────────────────────────


def _spawn_blocking(fn: Callable, *args) -> asyncio.Future:
    """在守护线程里执行阻塞函数，返回可 await 的 Future。

    为什么不用 loop.run_in_executor：默认 ThreadPoolExecutor 的线程是
    **非守护**的，超时后任务仍在跑，解释器退出时会 join 它们 —— 一层卡
    300 秒，CLI 就得陪 300 秒（验收要求 budget+5 秒内返回）。守护线程
    超时后直接遗弃，进程可以按时退出。

    结果交付前检查 future 是否已结束（超时会被 wait_for 取消），
    事件循环已关闭时也不抛错。
    """
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    def _deliver(setter: Callable, value) -> None:
        if fut.done():
            return  # 已超时取消：结果没人要了
        setter(value)

    def _work() -> None:
        try:
            value = fn(*args)
        except Exception as exc:  # noqa: BLE001 —— 统一转交给事件循环处理
            outcome: tuple[bool, object] = (False, exc)
        else:
            outcome = (True, value)

        ok, payload = outcome

        def _apply() -> None:
            if ok:
                _deliver(fut.set_result, payload)
            else:
                _deliver(fut.set_exception, payload)

        try:
            loop.call_soon_threadsafe(_apply)
        except RuntimeError:
            # 事件循环已关闭（CLI 提前退出 / 宿主卸载）：忽略迟到结果
            pass

    threading.Thread(
        target=_work,
        daemon=True,
        name=f"osint-{getattr(fn, '__name__', 'layer')}",
    ).start()
    return fut


async def _run_layer(
    source: str,
    fn: Callable,
    *args,
    timeout: float,
    on_event: EventCallback | None = None,
) -> dict:
    """执行一层：超时保护 + 异常兜底 + 进度事件。

    Returns:
        该层结果 dict。失败/超时时返回带 ``error``（及 ``timed_out``）的桩，
        形状与该层正常返回一致，调用方无需特判。
    """
    label = _PROGRESS_LABELS.get(source, source)
    if on_event:
        on_event({"event": "source_start", "source": source, "label": label})

    started = time.monotonic()
    if timeout <= 0:
        # 全局预算已耗尽：不启动线程，直接标 timeout
        result = _failure_layer(source, "budget")
        status = "timeout"
    else:
        try:
            result = await asyncio.wait_for(_spawn_blocking(fn, *args), timeout=timeout)
            status = _status_for(source, result)
        except TimeoutError:
            result = _failure_layer(source, "timeout", timeout)
            status = "timeout"
        except Exception as exc:  # noqa: BLE001 —— 单层失败不拖垮整份报告
            result = _failure_layer(source, "error", detail=str(exc))
            status = "error"

    if on_event:
        on_event({
            "event": "source_done",
            "source": source,
            "status": status,
            "ms": int((time.monotonic() - started) * 1000),
        })
    return result


def _status_for(source: str, layer: dict) -> str:
    """把某层结果映射成进度事件状态：hit | miss | error | skipped | timeout。"""
    if not layer:
        return "skipped"
    if source in SOURCE_LABELS:
        # 公开来源自带 status（hit/miss/error/skipped）
        return layer.get("status") or "miss"
    if layer.get("timed_out"):
        return "timeout"
    if layer.get("error"):
        return "error"
    if source == "email_registration":
        return "hit" if layer.get("found_count") else "miss"
    if source == "domain_intel":
        # registered=False 且无错误：域名不存在（属查到的结论，不是 miss 的网络含义）
        return "hit" if layer.get("registered") else "miss"
    if source == "email_verification":
        return "hit" if layer.get("risk_flags") else "miss"
    if source == "tech_stack":
        return "hit" if layer.get("technologies") else "miss"
    if source == "sanctions":
        if layer.get("is_sanctioned") or layer.get("hits"):
            return "hit"
        # 数据源降级时「没查到」不构成结论，按 error 上报
        coverage = layer.get("coverage") or {}
        return "error" if coverage.get("degraded", True) else "miss"
    return "miss"


def _failure_layer(source: str, kind: str, timeout: float = 0.0, *, detail: str = "") -> dict:
    """构造失败层的返回桩（形状与正常结果一致）。"""
    if kind == "timeout":
        reason = f"超时（{timeout:.0f} 秒）"
    elif kind == "budget":
        reason = "预算耗尽，未执行"
    else:
        reason = detail or "未知错误"

    stub: dict = {"error": reason, "timed_out": kind in ("timeout", "budget")}
    if source in SOURCE_LABELS:
        # 公开来源桩：字段与 SourceResult.to_dict() 对齐
        stub.update({
            "status": "timeout" if kind in ("timeout", "budget") else "error",
            "facts": [],
            "data": {},
        })
        return stub
    if source == "sanctions":
        # 关键：不能因为超时就让调用方以为「已查且无命中」
        stub.update({
            "hits": [],
            "is_sanctioned": False,
            "risk_level": "none",
            "coverage": {"degraded": True, "total_entries": 0, "lists": {}},
            "suggestion": f"制裁名单筛查未完成（{reason}），不构成「无制裁记录」的结论。",
        })
    elif source == "email_registration":
        stub.update({"checked_count": 0, "found_count": 0, "results": []})
    elif source == "email_verification":
        stub.update({
            "risk_flags": [],
            "mx_error": reason,
            "mx_found": None,
            "is_personal": None,
            "is_corporate": None,
        })
    elif source == "domain_intel":
        stub.update({"domain": "", "registered": False})
    elif source == "tech_stack":
        stub.update({"technologies": []})
    return stub


def _sanctions_and_screen(domain: str | None, fallback_name: str) -> dict:
    """制裁层：域名 → 公司名（官网 title）→ 名单比对，合成一个阻塞任务。"""
    resolved = _resolve_entity_name(domain)
    return check_sanctions(resolved or fallback_name)


def _run_public_source(module, ctx: TargetContext, fetcher) -> dict:
    """跑一个公开来源模块，统一转成 dict（供 _run_layer 处理）。"""
    return module.run(ctx, fetch=fetcher).to_dict()


# 显式类型前缀（大小写不敏感）。中文前缀一并支持：模型实际会写 `公司:…`。
_TYPE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("person:", "person"), ("人名:", "person"),
    ("company:", "company"), ("公司:", "company"), ("企业:", "company"),
    ("domain:", "domain"), ("域名:", "domain"), ("网址:", "domain"),
)


def _split_type_prefix(target: str) -> tuple[str, str | None]:
    """剥离显式类型前缀：`person:` / `company:` / `domain:`（大小写不敏感）。

    2026-11-22 修两处：
    1. 补 `domain:` —— 模型用它指定域名目标，但此前不在白名单里，于是
       `domain:spiderimpex.com` 被当成**公司名**：域名层静默跳过，报告还写
       “目标不含域名”，看起来查过了其实跑空（两次背调覆盖范围因此不同）。
    2. 补中文前缀（`公司:` 等）—— 此前 `公司:天津赛得进出口有限公司` 的前缀
       没被剥掉，目标串带着前缀去查制裁名单，查询串被污染。
    """
    text = str(target or "").strip()
    lowered = text.casefold()
    for prefix, kind in _TYPE_PREFIXES:
        # 全角冒号也认（模型会写 `公司：天津…`），否则前缀整段进查询串
        for sep in (":", "："):
            p = prefix[:-1] + sep
            if lowered.startswith(p):
                return text.split(sep, 1)[1].strip(), kind
    return text, None


def _split_username_prefix(target: str) -> tuple[str, str | None]:
    """剥离显式用户名前缀：`username:foo`。"""
    text = str(target or "").strip()
    lowered = text.casefold()
    for sep in (":", "："):
        if lowered.startswith("username" + sep):
            value = text.split(sep, 1)[1].strip()
            return value, value
    return text, None


# 可以从 URL 提取用户名的公开主页站点
_SOCIAL_HOSTS = frozenset({
    "github.com", "x.com", "twitter.com", "linkedin.com",
    "instagram.com", "tiktok.com", "youtube.com",
})


def _extract_username(target: str, target_type: str) -> str | None:
    """邮箱取本地部分；社交主页 URL 取路径里的 handle。"""
    if target_type == "email" and "@" in target:
        local = target.split("@", 1)[0].strip()
        # 公共邮箱前缀（info@/sales@…）不是个人用户名，查 50 个站点只会制造噪音
        if local.casefold() in {
            "info", "sales", "support", "contact", "admin", "hello",
            "office", "service", "help", "marketing",
        }:
            return None
        if len(local) >= 3 and re.fullmatch(r"[A-Za-z0-9._-]+", local):
            return local
        return None
    if target_type == "url":
        from urllib.parse import urlsplit

        parsed = urlsplit(target)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if host not in _SOCIAL_HOSTS:
            return None
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            return None
        if host == "linkedin.com" and len(parts) >= 2 and parts[0] == "in":
            return parts[1].lstrip("@")
        return parts[0].lstrip("@")
    return None


# 出现这些词基本可判定为公司（用于人名启发式，避免把 "ACME Trading" 判成人）
_COMPANY_WORDS = frozenset({
    "ltd", "limited", "llc", "llp", "inc", "incorporated", "corp", "corporation",
    "co", "gmbh", "ag", "sa", "sas", "srl", "spa", "bv", "nv", "plc", "pte",
    "pty", "wll", "group", "holdings", "holding", "trading", "traders", "company",
    "enterprise", "enterprises", "industries", "industry", "international",
    "import", "exports", "export", "imports", "contracting", "construction",
    "manufacturing", "logistics", "technology", "technologies", "tech",
    "solutions", "systems", "services", "partners", "associates", "consulting",
    "ventures", "capital", "labs", "supply", "supplies", "studio", "studios",
})


def _looks_like_person(value: str) -> bool:
    """启发式判断人名（个人背调用；公司名仍走 company）。

    - 中文：2–4 个汉字，且不含「公司/集团/厂/店/有限/股份」
    - 英文：2–4 个字母词，且不含 Ltd/LLC/Group 这类公司后缀
    """
    text = value.strip()
    if not text or "@" in text:
        return False

    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", text):
        return not re.search(r"公司|集团|工厂|贸易|有限|股份", text)

    if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", text):
        return False
    tokens = re.findall(r"[A-Za-z][A-Za-z.'-]*", text)
    if not 2 <= len(tokens) <= 4:
        return False
    normalized = [token.casefold().strip(".'-") for token in tokens]
    if any(token in _COMPANY_WORDS for token in normalized):
        return False
    return any(len(token) >= 3 for token in normalized)


def _apply_rdap_fallback(report: dict) -> None:
    """WHOIS 失败/缺日期时，用 RDAP 的注册信息补位（P2-2）。

    RDAP 已经是域名注册的首选来源；这里只在 WHOIS 没给出日期（或整层失败）
    时填充，避免覆盖 WHOIS 已成功解析的数据。
    """
    rdap = (report.get("sources") or {}).get("rdap") or {}
    if rdap.get("status") != "hit":
        return
    data = rdap.get("data") or {}
    creation = data.get("creation_date")
    if not creation:
        return

    di = report["layers"].get("domain_intel") or {}
    if not (di.get("error") or di.get("skipped") or not di.get("creation_date")):
        return

    days_old = None
    category = None
    try:
        created = datetime.fromisoformat(str(creation).replace("Z", "+00:00"))
        days_old = (datetime.now(UTC) - created).days
        category = "new" if days_old < 365 else "medium" if days_old < 1095 else "old"
    except (ValueError, TypeError):
        pass

    report["layers"]["domain_intel"] = {
        "domain": di.get("domain") or "",
        "registered": True,
        "registrar": di.get("registrar") or data.get("registrar") or None,
        "creation_date": creation,
        "expiry_date": di.get("expiry_date") or data.get("expiry_date"),
        "days_old": days_old,
        "age_category": category,
        "dns_servers": di.get("dns_servers") or data.get("nameservers") or [],
        "registrant_name": None,
        "whois_server": "rdap",
        "status": di.get("status"),
        "error": None,
        "via": "rdap",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 内部 helpers
# ─────────────────────────────────────────────────────────────────────────────

# 邮箱验证的中文红旗 → 评分用的标记名。
# 必须逐条对应：不同红旗的证据强度不同、扣分也不同（见 scoring._deductions）。
_EMAIL_FLAG_MAP = {
    "使用个人邮箱域名": "personal_email_domain",
    "域名未检测到 MX 记录（可能是假域名）": "no_mx_record",
    "邮箱域名与网站域名不一致": "email_domain_mismatch",
}


def _map_email_flags(risk_flags: list[str]) -> list[str]:
    """把邮箱验证层的中文红旗翻译成评分层的标记名。

    未识别的红旗不丢弃：转成 ``email_<hash>`` 会污染评分表，改为忽略并
    依赖该层自己的 suggestion 字段披露（scoring 是白名单制，未知标记本就扣默认分，
    这里选择不臆造语义）。
    """
    return [_EMAIL_FLAG_MAP[f] for f in risk_flags if f in _EMAIL_FLAG_MAP]


def _extract_lookup_domain(target: str, target_type: str, domain_from_email: str | None) -> str | None:
    """从目标中提取用于 WHOIS / 技术栈检测的域名。

    公司名无法直接提取域名（需先搜索发现官网），返回 None。
    URL 使用 urllib.parse 精确解析，避免路径参数残留。
    """
    if domain_from_email:
        return domain_from_email

    if target_type == "url":
        from urllib.parse import urlparse
        parsed = urlparse(target)
        netloc = parsed.netloc.lower().removeprefix("www.")
        return netloc or None

    if target_type == "domain":
        # 未知前缀的情形（如 `foo:example.com`）：去掉前缀再取域名
        if ":" in target or "：" in target:
            target = re.split(r"[:：]", target)[-1].strip()
        return target.lower().removeprefix("www.")

    # company / unknown — 无法直接提取域名
    return None


def _looks_like_domain(text: str) -> bool:
    """是否符合域名格式（含 . 和合法 TLD，支持 IDN punycode）。"""
    try:
        ascii_text = text.encode("idna").decode("ascii")
    except Exception:
        ascii_text = text
    # TLD 既可能是纯字母（com/de/io），也可能是 **punycode**（中文域名的顶级域，
    # 如 中国 → xn--fiqs8s）—— 后者含数字和连字符，只写 [a-z]{2,} 会漏判 IDN 域名。
    return bool(re.match(r"^[a-z0-9]([a-z0-9-]+\.)+([a-z]{2,}|xn--[a-z0-9]+)$", ascii_text.lower()))


def _detect_target_type(target: str) -> str:
    """自动识别目标类型：email / domain / url / company。

    识别规则：
      - 含 @ → email
      - 含 http(s):// → url
      - 符合域名格式 (含 . 和合法 TLD) → domain
      - `未知前缀:域名` → domain（冒号后是域名就按域名查）
      - 否则 → company
    """
    target = target.strip()
    if "@" in target and "." in target.split("@", 1)[1]:
        # 含 @ 且 @ 后有 . → 视为邮箱地址
        return "email"
    if target.startswith(("http://", "https://")):
        # 以 http(s):// 开头 → 视为 URL
        return "url"
    if _looks_like_domain(target):
        # 符合标准域名格式（如 example.com / 例子.中国）→ 视为域名
        return "domain"
    # 未知前缀 + 域名（`domain:example.com` / `foo:example.com`）：
    # 冒号后是域名就按域名查，不静默降级成公司名（2026-11-22 修：
    # 之前 domain: 前缀不被识别，域名层被静默跳过，报告还写“目标不含域名”）。
    if ":" in target or "：" in target:
        suffix = re.split(r"[:：]", target)[-1].strip()
        if suffix and _looks_like_domain(suffix):
            return "domain"
    # 人名启发式（2–4 个词且不含公司后缀）→ person；
    # 个人背调与公司背调的可用来源不同，类型判错会整层走错。
    if _looks_like_person(target):
        return "person"
    # 以上都不匹配 → 视为公司名称
    return "company"


def _resolve_entity_name(domain: str | None, *, fetcher=None) -> str | None:
    """域名 → 公司名（供制裁名单筛查用）。

    用官网 `<title>` 取主标题（分隔符前的部分）。

    **为什么不用 WHOIS 注册人**：本项目的 whois 层不提取注册人信息
    （`registrant_name` 字段恒为 None —— GDPR 后绝大多数 TLD 已脱敏，
    解析出来的也多为隐私代理名）。曾经想复用它省一次请求，但那是一条
    永远走不到的死路；这里如实去掉，只留真正有信号的一条。

    Args:
        fetcher: 可选注入的取页面函数（测试用；默认 http_get，自带 SSRF 防护）。

    解析失败返回 None，调用方回退用域名原文（保持原行为）。
    """
    if not domain:
        return None

    # 官网 <title>
    try:
        from trade.osint.constants import http_get  # 懒加载，避免循环导入

        fetch = fetcher or http_get
        html = fetch(f"https://{domain}", timeout=15)
        if html:
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            if m:
                title = re.sub(r"\s+", " ", m.group(1)).strip()
                # 去掉分隔符后的后缀："ACME Corp | Official Site" -> "ACME Corp"；
                # 半角连字符只在两侧都有空格时切（Coca-Cola / Rolls-Royce 是
                # 公司名的一部分）；| – — : 保持原规则（2026-11-23 审计 P2-1）。
                title = re.split(r"(?:\s*[|–—:]\s*)|(?:\s+-\s+)", title)[0].strip()
                if len(title) >= 3:
                    return title
    except Exception:
        pass
    return None
