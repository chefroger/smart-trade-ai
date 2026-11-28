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
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from trade import email_intel
from trade.osint.domain_class import (
    PLATFORM_SKIP_DOMAIN_CATEGORIES,
    classify_domain_or_url,
)
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

# 登记类来源（W3）：只证明登记存在，不构成经营/身份核验
_REGISTRY_SOURCES = frozenset({"us_states", "gleif", "vies", "registries_misc"})
# 仅对「目标自有域名」有意义的公开来源（公共平台域名需跳过并标 not_applicable）
_DOMAIN_ONLY_PUBLIC_SOURCES = ("rdap", "ct", "wayback", "pdns")


def _public_hit_counts(sources: dict) -> tuple[int, int]:
    """返回 (实质核验 hit 数, 登记类 hit 数)。candidate 不算命中。"""
    substantive = 0
    registry = 0
    for name, item in (sources or {}).items():
        if not isinstance(item, dict) or item.get("status") != "hit":
            continue
        if name in _REGISTRY_SOURCES:
            registry += 1
        else:
            substantive += 1
    return substantive, registry


def _registry_formation_dates(sources: dict) -> list[str]:
    """从登记类事实里抽取成立日期（报告要写出，W3）。"""
    import re as _re

    dates: list[str] = []
    for name in _REGISTRY_SOURCES:
        item = (sources or {}).get(name)
        if not isinstance(item, dict):
            continue
        for fact in item.get("facts") or []:
            match = _re.search(r"成立\s*(\d{4}-\d{2}-\d{2})", str(fact.get("text") or ""))
            if match and match.group(1) not in dates:
                dates.append(match.group(1))
    return dates


def _registry_jurisdictions(sources: dict) -> list[str]:
    """从登记类事实里抽取州/国（S9：报告写「已查到公司登记（州/国）」）。"""
    import re as _re

    places: list[str] = []

    def _add(value: object) -> None:
        text = str(value or "").strip()
        if text and text not in places:
            places.append(text)

    for name in _REGISTRY_SOURCES:
        item = (sources or {}).get(name)
        if not isinstance(item, dict) or item.get("status") != "hit":
            continue
        # GLEIF 等提供结构化国家代码
        _add((item.get("data") or {}).get("country"))
        for fact in item.get("facts") or []:
            text = str(fact.get("text") or "")
            # 「纽约州登记」「法国登记」「注册地：US」
            match = _re.search(r"([\u4e00-\u9fff]{2,8}州)登记", text)
            if not match:
                match = _re.search(r"([\u4e00-\u9fff]{2,8})登记[：:]", text)
            if match:
                _add(match.group(1))
                continue
            match = _re.search(r"注册地[：:]\s*([A-Z]{2})", text)
            if match:
                _add(match.group(1))
    return places


# 单层超时（秒）。全局预算另由 osint_full_check(budget=...) 限制。
# 名单已改为后台每日刷新（check_sanctions 只读本地库），制裁层不再需要
# 下载时间，20 秒足够（2026-11-23 审计 P2-3）。
_LAYER_TIMEOUTS: dict[str, float] = {
    "email_registration": 90.0,  # holehe 要探测 120+ 站点
    "domain_intel": 20.0,
    "email_verification": 20.0,
    "tech_stack": 20.0,
    "sanctions": 20.0,
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


# RFC 2606 / RFC 6761 保留示例与测试域名（不可用于真实背调）
_RESERVED_TLDS = frozenset({"example", "test", "invalid", "localhost"})
_RESERVED_SECOND_LEVEL_EXACT = frozenset({"example.com", "example.net", "example.org"})
# 从自由文本（含公司名+括号域名、URL、邮箱）中抽取候选域名 token
_DOMAIN_TOKEN_RE = re.compile(
    r"(?:https?://)?(?:[a-z0-9._%+-]+@)?([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+)",
    re.IGNORECASE,
)


def is_reserved_domain(domain: str) -> bool:
    """判断单个域名是否属于 RFC 2606 / RFC 6761 保留示例或测试域名。

    命中规则：
      - 裸 `localhost` 或任意 `.example` / `.test` / `.invalid` / `.localhost` 后缀；
      - `example.com` / `example.net` / `example.org` 及其任意子域名；
      - `example.<2字母国家码>`（如 `example.sa`、`foo.example.sa`）及其子域名。

    不会误判 `example-trading.com`、`myexample.sa` 等仅含 example 子串的真实域名。
    """
    raw = (domain or "").strip().lower().rstrip(".")
    if not raw:
        return False
    if raw == "localhost":
        return True
    labels = [lb for lb in raw.split(".") if lb]
    if len(labels) < 2:
        return False
    tld = labels[-1]
    # RFC 2606 / 6761 保留顶级域
    if tld in _RESERVED_TLDS:
        return True
    base2 = f"{labels[-2]}.{tld}"
    # RFC 2606 保留二级域名及其任意子域
    if base2 in _RESERVED_SECOND_LEVEL_EXACT:
        return True
    # 国家码下的 example.<cc>（如 foo.example.sa / example.cn）
    if labels[-2] == "example" and len(tld) == 2 and tld.isalpha():
        return True
    return False


def detect_reserved_domain(target: str) -> str | None:
    """从背调目标文本中检测是否包含保留示例/测试域名，命中返回该域名，否则 None。"""
    text = (target or "").strip()
    if not text:
        return None
    # 裸 localhost（不带点）
    if text.lower() == "localhost":
        return "localhost"
    for match in _DOMAIN_TOKEN_RE.finditer(text):
        cand = match.group(1).lower().rstrip(".")
        if is_reserved_domain(cand):
            return cand
    return None


def _build_reserved_domain_report(target: str, target_type: str, reserved_domain: str) -> dict:
    """构造命中保留示例/测试域名时的确定性背调报告（零公网检索、零模型调用）。"""
    reason = f"目标包含保留示例或测试域名（{reserved_domain}），这是示例或测试域名，无法背调。"
    return {
        "target": target,
        "target_type": target_type,
        "overall_rating": "incomplete",
        "overall_score": None,
        "reserved_domain": reserved_domain,
        "blocked_reason": reason,
        "flags": [reason],
        "unverified": [],
        "layers": {},
        "sources": {},
        "recommendations": [
            "这是示例或测试域名，无法背调。请核对并输入真实的客户官网域名或公司名称后再试。"
        ],
    }


async def osint_full_check(
    target: str,
    *,
    include_sanctions: bool = True,
    include_tech_stack: bool = True,
    include_linkedin: bool = True,
    budget: float = 150.0,
    on_event: EventCallback | None = None,
    source_fetcher=None,
    should_cancel: Callable[[], bool] | None = None,
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
        should_cancel: 可选取消判定（W15 O-22）；命中后取消未完成的层并返回

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

    # 工单 #6：编排层确定性拦截 RFC 2606 / 6761 保留示例或测试域名，绝不进入公网检索与实体匹配
    reserved_dom = detect_reserved_domain(target)
    if reserved_dom is not None:
        return _build_reserved_domain_report(target, target_type, reserved_dom)

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

    # ── M1：公共平台域名分类（公共邮箱/B2B 平台/建站子域/社媒平台不查自有域名专属层）──
    domain_class: dict[str, Any] | None = None
    is_platform_domain = False
    platform_reason = ""
    inferred_store_name: str | None = None
    if lookup_domain:
        # 网址目标传完整 target（保留路径，如 linkedin.com/company/x 视为企业主页）
        classify_input = target if target_type == "url" else lookup_domain
        domain_class = classify_domain_or_url(classify_input)
        if domain_class["category"] in PLATFORM_SKIP_DOMAIN_CATEGORIES:
            is_platform_domain = True
            platform_reason = domain_class["reason"]
            inferred_store_name = domain_class.get("inferred_store_name")
            report["domain_classification"] = domain_class
            report["platform_domain_notice"] = f"目标使用公共平台域名：{platform_reason}"
            if inferred_store_name:
                # 平台店铺 URL 推断出的候选公司名，标明来源并交给公司名类公开来源
                report["inferred_store_name"] = inferred_store_name
                report["inferred_store_note"] = f"推断店铺名 {inferred_store_name}（推断自店铺地址）"

    effective_domain = None if is_platform_domain else lookup_domain

    # ── 规划各层：互不依赖，全部并发 ────────────────────────────────────
    # 每项: (阻塞函数, 位置参数)。真正的执行统一走 _run_layer（超时 + 进度）。
    planned: dict[str, tuple[Callable, tuple]] = {}

    if target_type == "email":
        # Layer 1: holehe 邮箱注册检测
        planned["email_registration"] = (email_intel.email_background_check, (target,))
        # Layer 3: 企业邮箱验证（DNS MX）
        planned["email_verification"] = (verify_corporate_email, (target,))

    if effective_domain:
        # Layer 2: WHOIS 域名情报（仅目标自有域名执行）
        planned["domain_intel"] = (domain_whois, (effective_domain,))

        if include_tech_stack:
            # Layer 4: 技术栈检测（依赖自有域名，不依赖 WHOIS 结果）
            planned["tech_stack"] = (detect_tech_stack, (f"https://{effective_domain}",))

    if include_sanctions:
        # Layer 5: 制裁筛查。公司名解析（抓官网 title）与名单比对合成一个
        # 阻塞任务，整体受本层超时约束。公共平台域名不抓平台官网 title。
        sanctions_fallback = (
            inferred_store_name
            if (is_platform_domain and inferred_store_name)
            else (target if is_platform_domain else (domain_from_email or target))
        )
        planned["sanctions"] = (
            _sanctions_and_screen,
            (effective_domain, sanctions_fallback),
        )

    # ── 公开来源（P2-2）：RDAP / CT / Wayback / GitHub ─────────────────
    # 与 6 层并发；RDAP/CT/Wayback/pDNS 必须有目标自有域名，GitHub 等按公司名/人名搜索。
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
            domain=effective_domain,
            email=target if target_type == "email" else None,
            person_name=target if target_type == "person" else None,
            company_name=target if target_type == "company" else inferred_store_name,
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
    tasks: dict[str, asyncio.Task[dict]] = {
        source: asyncio.create_task(
            _run_layer(
                source,
                fn,
                *args,
                timeout=min(_LAYER_TIMEOUTS[source], max(0.0, deadline - time.monotonic())),
                on_event=on_event,
            )
        )
        for source, (fn, args) in planned.items()
    }
    for name, fn in public_planned.items():
        tasks[name] = asyncio.create_task(
            _run_layer(
                name,
                fn,
                timeout=min(
                    _LAYER_TIMEOUTS.get(name, 15.0),
                    max(0.0, deadline - time.monotonic()),
                ),
                on_event=on_event,
            )
        )
    results = await _await_layers(tasks, should_cancel)
    report["sources"] = {name: results[name] for name in public_planned}
    if is_platform_domain and sources_enabled():
        # 公共平台域名跳过自有域名专属公开来源，显式标 not_applicable 并写明原因
        for src_name in _DOMAIN_ONLY_PUBLIC_SOURCES:
            report["sources"][src_name] = {
                "status": "not_applicable",
                "reason": platform_reason,
                "facts": [],
                "data": {},
                "error": None,
            }

    # ── 落报告：未规划的层写 None / skipped / not_applicable ─────────────
    report["layers"]["email_registration"] = (
        results.get("email_registration") if target_type == "email" else None
    )
    if effective_domain:
        report["layers"]["domain_intel"] = results["domain_intel"]
    elif is_platform_domain:
        # 公共平台域名：WHOIS 不代表目标公司，标 not_applicable
        report["layers"]["domain_intel"] = {
            "status": "not_applicable",
            "not_applicable": True,
            "skipped": True,
            "reason": platform_reason,
        }
    else:
        # 人名/公司名无法直接提取域名（需先用搜索发现官网）
        report["layers"]["domain_intel"] = {
            "skipped": True,
            "reason": "目标名不含域名（人名/公司名需先发现官网）",
        }
    report["layers"]["email_verification"] = (
        results.get("email_verification") if target_type == "email" else None
    )
    if is_platform_domain and include_tech_stack:
        # 公共平台域名：技术栈检测不适用，显式标 not_applicable
        report["layers"]["tech_stack"] = {
            "status": "not_applicable",
            "not_applicable": True,
            "skipped": True,
            "reason": platform_reason,
        }
    else:
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
    if include_linkedin and effective_domain:
        # 当 target 不是公司名时（如 email），用自有域名作为公司名线索
        _company_hint = target if target_type == "company" else effective_domain
        if on_event:
            on_event({
                "event": "source_start",
                "source": "linkedin",
                "label": _LAYER_LABELS.get("linkedin", "linkedin"),
            })
        started = time.monotonic()
        report["layers"]["linkedin"] = linkedin_company_verify(effective_domain, _company_hint)
        if on_event:
            on_event({
                "event": "source_done",
                "source": "linkedin",
                "status": "skipped",  # 只生成指令，需人工/浏览器实际执行
                "ms": int((time.monotonic() - started) * 1000),
            })
    else:
        # 用户关闭 LinkedIn 验证、缺少域名或属于公共平台域名，跳过此层
        report["layers"]["linkedin"] = None

    # ── 核验完整性 + 综合评分（fail-closed，工单 P0-2）────────────────
    # 先列出哪些关键层没查成：制裁数据源降级、有域名但 WHOIS 失败。
    # 这些情况下 compute_verdict 会把评级改为 "incomplete"、分数置 None，
    # 避免「没查成」被当成「没风险」。
    report["unverified"] = assess_verification(
        report["layers"],
        has_domain=bool(effective_domain),
        sanctions_requested=include_sanctions,
    )
    # 公开来源按「登记类 / 实质核验」分开计数（W3）：
    # us_states/GLEIF/VIES 只证明“注册过”，壳公司也能拿 low/100。
    public_hits, registry_hits = _public_hit_counts(report["sources"])
    score, rating, provisional = compute_verdict(
        report["flags"],
        report["unverified"],
        target_type=target_type,
        has_domain=bool(effective_domain),
        public_hits=public_hits,
    )
    report["overall_score"] = score          # None = 未完成核验/仅完成制裁筛查
    report["overall_rating"] = rating
    report["provisional_score"] = provisional  # 仅供诊断，不是对外结论
    if rating == "limited":
        dates = _registry_formation_dates(report["sources"])
        if registry_hits:
            # S9：有登记类命中时如实写「已查到公司登记」，不再说「没有实质
            # 核验命中」——登记本身就是命中，只是不足以证明经营真实性。
            places = _registry_jurisdictions(report["sources"])
            where = "、".join(places[:2]) or "公开登记库"
            if dates:
                basis = f"{where}，成立于 {'、'.join(dates[:2])}"
            else:
                basis = f"{where}，成立日期未提供"
            report["rating_note"] = (
                f"已查到公司登记（{basis}）；登记只证明主体存在，"
                "不证明经营真实性。补充官网、域名或其它核验来源后再评级。"
            )
        else:
            report["rating_note"] = (
                "仅完成制裁筛查：目标没有可查询域名，公开来源也没有实质核验命中；"
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


async def _await_layers(
    tasks: dict[str, asyncio.Task[dict] | Coroutine[Any, Any, dict]],
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, dict]:
    """等待各层完成；提供 should_cancel 时每 0.5s 检查并取消未完成的层。

    W15 O-22：取消后不再等所有层跑完（in-flight 的 HTTP 线程无法强杀，
    但其结果会被丢弃，任务立即收尾）。
    """
    if should_cancel is None:
        # 未提供取消检查时直接 gather（兼容 Task 与协程）
        values = await asyncio.gather(*tasks.values())
        return dict(zip(tasks, values, strict=True))

    # Python 3.11+ 的 asyncio.wait 禁止传入裸协程；统一归一化为 Task，
    # 已是 Task 的对象保持原样，避免重复包装。
    normalized: dict[str, asyncio.Task[dict]] = {
        name: (t if isinstance(t, asyncio.Task) else asyncio.create_task(t))
        for name, t in tasks.items()
    }
    finished: dict[asyncio.Task[dict], object] = {}
    pending: set[asyncio.Task[dict]] = set(normalized.values())
    try:
        while pending:
            if should_cancel():
                # 命中取消信号：取消并收割未完成 Task，避免留下未 await 协程告警
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                pending.clear()
                break
            done, pending = await asyncio.wait(
                pending, timeout=0.5, return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                if task.cancelled():
                    continue
                exc = task.exception()
                finished[task] = exc if exc is not None else task.result()
    except BaseException:
        # 中途抛错或外层取消时，收割所有仍在运行的子任务，避免孤儿任务/告警
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        raise

    results: dict[str, dict] = {}
    for name, task in normalized.items():
        if task in finished:
            value = finished[task]
            if isinstance(value, BaseException):
                results[name] = _failure_layer(name, "error", detail=str(value))
            else:
                results[name] = value
        else:
            results[name] = _failure_layer(name, "cancelled")
    return results


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
    elif kind == "cancelled":
        reason = "已取消（用户中止）"
    else:
        reason = detail or "未知错误"

    stub: dict = {"error": reason, "timed_out": kind in ("timeout", "budget", "cancelled")}
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
    2. 补中文前缀（`公司:` 等）—— 此前 `公司:某某进出口有限公司` 的前缀
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
