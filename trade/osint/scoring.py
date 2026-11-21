"""
Trade AI Assistant — OSINT 模块：风险评分与建议生成。

根据各层检测结果计算综合风险评分（0-100），并生成针对性的行动建议。
"""

from __future__ import annotations


def _deductions() -> dict[str, int]:
    """红旗 → 扣分权重表。

    提为函数是为了可测（测试要断言「不同红旗的扣分轻重关系合理」）。
    """
    return {
        "personal_email_domain": 30,     # 个人邮箱 → 严重减分
        "no_mx_record": 15,              # 域名无 MX 记录：假域名信号，但证据强度
                                         # 低于"个人邮箱"，故扣分更轻
        "email_domain_mismatch": 15,     # 邮箱域名与网站域名不一致
        "domain_age_new": 20,            # 新注册域名 → 中等减分
        "free_platform": 15,             # 免费建站 → 轻微减分
        "no_linkedin": 10,               # 无 LinkedIn → 轻微减分
        "linkedin_domain_mismatch": 15,  # LinkedIn 域名不匹配 → 中等减分
        "sanctioned": 50,                # 命中制裁名单 → 直接死刑
        "domain_age_old": 0,             # 老域名 → 不扣分（加分项在建议中体现）
    }


def compute_risk_score(flags: list[str]) -> tuple[int, str]:
    """根据红旗列表计算综合风险评分（0-100）和评级。

    每个红旗对应不同的扣分权重，敏感维度（制裁名单）扣分最多。

    **注意**：本函数只看「查出来的问题」，不知道哪一层没查成。对外结论必须走
    `compute_verdict()` —— 关键层未核验时它会把评级改成 "incomplete"，避免
    「什么都没查到」被当成「低风险」。

    Args:
        flags: 红旗标记列表（如 "personal_email_domain", "sanctioned" 等）

    Returns:
        (score, rating) 其中 rating 为 "low" | "medium" | "high"
    """
    score = 100

    deductions = _deductions()

    for flag in flags:
        score -= deductions.get(flag, 10)  # 未知红旗默认扣 10 分

    score = max(0, min(100, score))  # 限制在 [0, 100] 区间

    if score >= 80:
        # 评分 >= 80：低风险
        rating = "low"
    elif score >= 50:
        # 评分 50-79：中等风险
        rating = "medium"
    else:
        # 评分 < 50：高风险
        rating = "high"

    return score, rating


# 未核验层的可读名称（报告/CLI 直接展示，不暴露内部键名）
_LAYER_LABELS = {
    "sanctions": "制裁名单筛查",
    "domain_intel": "WHOIS 域名情报",
    "email_registration": "邮箱注册检测",
    "tech_stack": "技术栈检测",
    "linkedin": "LinkedIn 核查",
}


def _unverified_entry(layer: str, reason: str, *, required: bool,
                      status: str = "unverified") -> dict:
    """构造一条「未核验」记录。required=关键层（缺失即不能下结论）。"""
    return {
        "layer": layer,
        "label": _LAYER_LABELS.get(layer, layer),
        "status": status,       # unverified | skipped | not_applicable
        "reason": reason,
        "required": required,
    }


def assess_verification(
    layers: dict,
    *,
    has_domain: bool,
    sanctions_requested: bool = True,
) -> list[dict]:
    """列出本次没查成的层（2026-11-21 工单 P0-2，fail-closed）。

    背景：制裁名单可能从未成功下载（本地库为空），WHOIS 的 43 端口在国内
    常被拦 —— 旧逻辑照常给"没查到红旗"的报告打 low/100，用户会拿这条绿色
    结论去谈生意。这里把「查过且正常」与「没查成/没查」显式分开。

    关键层（对应工单）：制裁、域名。
      - 制裁名单从未成功下载（coverage.degraded）→ required（"没查到"不代表"没有"）
      - 有域名但 WHOIS 失败 → required
      - 用户主动关闭制裁 → 只披露（skipped，不算未完成）
      - 公司名目标没有域名 → not_applicable（需先发现官网，属正常缺省）
    其余层（holehe / 技术栈）失败只披露，不改变结论。

    Args:
        layers: report["layers"]
        has_domain: 目标是否解析出了可查询域名
        sanctions_requested: 用户是否开启制裁筛查

    Returns:
        [{layer, label, status, reason, required}, ...]
    """
    out: list[dict] = []

    # ── 制裁名单（关键）──
    sa = layers.get("sanctions")
    if not sanctions_requested:
        # 用户主动关闭：披露，但不判「未完成」——这是明确的范围排除
        out.append(_unverified_entry(
            "sanctions", "本次已关闭制裁筛查", required=False, status="skipped"))
    elif not sa:
        # 说好要查却没返回任何结果：不能当"干净"
        out.append(_unverified_entry(
            "sanctions", "制裁名单筛查未返回结果", required=True))
    else:
        # coverage 缺失按降级处理（旧版/外部构造的报告同样保守兜底）
        coverage = sa.get("coverage") or {}
        if coverage.get("degraded", True):
            total = coverage.get("total_entries", 0)
            out.append(_unverified_entry(
                "sanctions",
                f"名单尚未成功下载（本地可用 {total} 条）",
                required=True,
            ))

    # ── 域名情报（关键，前提是目标里有域名）──
    di = layers.get("domain_intel")
    if not has_domain:
        out.append(_unverified_entry(
            "domain_intel",
            "目标不含可查询域名（公司名需先发现官网）",
            required=False,
            status="not_applicable",
        ))
    elif not di:
        out.append(_unverified_entry(
            "domain_intel", "域名情报未执行", required=True))
    elif di.get("skipped"):
        # 编排器在无域名时才写 skipped；走到这里说明状态与 has_domain 矛盾，
        # 处置为「不适用」但不静默（保留披露）
        out.append(_unverified_entry(
            "domain_intel",
            f"域名情报跳过：{di.get('reason', '')}",
            required=False,
            status="not_applicable",
        ))
    elif di.get("error"):
        out.append(_unverified_entry(
            "domain_intel", f"WHOIS 查询失败：{di['error']}", required=True))

    # ── 非关键层：失败也如实披露（不改变评级）──
    er = layers.get("email_registration")
    if er and er.get("error"):
        out.append(_unverified_entry(
            "email_registration", f"holehe 未执行或失败：{er['error']}", required=False))
    ts = layers.get("tech_stack")
    if ts and ts.get("error"):
        out.append(_unverified_entry(
            "tech_stack", f"网站抓取失败：{ts['error']}", required=False))

    return out


def compute_verdict(
    flags: list[str],
    unverified: list[dict],
) -> tuple[int | None, str, int]:
    """fail-closed 汇总：关键层没查成时不给数字结论。

    Returns:
        (overall_score, rating, provisional_score)

        关键层未核验 → overall_score 为 None（报告显示"—"），rating 为
        "incomplete"，同时保留 provisional_score 供日志/诊断参考。
        已确认命中制裁 → 直接 high（结论已成立，不被「未完成」掩盖）。
    """
    score, rating = compute_risk_score(flags)

    # 明确的制裁命中是确定结论：即使其它层降级，也不能弱化成「未完成」
    if "sanctioned" in flags:
        return score, "high", score

    if any(u.get("required") for u in unverified):
        # 不输出数字：未核验时任何分数都会被读成「结论」
        return None, "incomplete", score

    return score, rating, score


def generate_recommendations(report: dict) -> list[str]:
    """根据各层检测结果生成结构化的行动建议。

    每个 layer 的结果独立评估，生成一条具体的、可执行的建议。

    Args:
        report: osint_full_check 的完整报告 dict，包含 "layers" 字段

    Returns:
        建议字符串列表（带 emoji 前缀指示严重程度）
    """
    recs: list[str] = []
    layers = report.get("layers", {})

    # ── 核验完整性（fail-closed，P0-2）──
    # 只在 orchestrator 生成的报告里有 unverified 字段；外部构造的报告不受影响。
    # 各层原因由下面各自的建议分支展开，这里只给结论性的「未完成」。
    unverified = report.get("unverified") or []
    blocking = [u for u in unverified if u.get("required")]
    if blocking:
        names = "、".join(u.get("label", u.get("layer", "")) for u in blocking)
        recs.append(
            f"🚫 本次背调未完成核验（{names}），结论为「未完成」，"
            "**不代表低风险**；原因与补齐方式见下方各层说明"
        )
    for u in unverified:
        # 用户主动关闭的渠道：明确写出「未查」，不能当成「无风险」
        if u.get("status") == "skipped":
            recs.append(
                f"ℹ️ {u.get('label', u.get('layer', ''))}本次未查（{u.get('reason', '')}），"
                "不能作为「无风险」的依据"
            )

    # ── 邮箱注册检测层（holehe）──
    # 这一层在全新安装的机器上从不执行（holehe 未被任何安装路径声明），
    # 代码内是懒加载 + 错误字典。报告若一字不提，用户会以为 120+ 平台的
    # 注册检测已经跑过 —— 属于"静默少一层"，必须披露。
    er = layers.get("email_registration")
    if er and er.get("error"):
        recs.append(
            f"⚠️ 邮箱注册检测未执行（{er['error']}）——"
            "本项缺失 120+ 平台的注册记录核查，如需该能力请联系支持安装 holehe"
        )

    # ── 邮箱验证建议 ──
    ev = layers.get("email_verification")
    if ev:
        # 根据邮箱验证结果生成建议
        if ev.get("risk_flag"):
            # 邮箱有红旗标记（个人邮箱）
            recs.append(
                f"⚠️ 对方使用个人邮箱（{ev.get('domain', '')}），"
                "建议要求对方提供企业邮箱后再深入谈判"
            )
        elif ev.get("is_corporate"):
            # 企业邮箱验证通过
            recs.append(
                f"✅ 企业邮箱验证通过（{ev.get('domain', '')}），域名匹配且 MX 记录正常"
            )

    # ── 域名建议 ──
    di = layers.get("domain_intel")
    if di:
        age_cat = di.get("age_category")
        days = di.get("days_old")
        if di.get("error"):
            # 查询失败的**必须说出来**：什么都不写会让读者以为域名已核验通过
            # （WHOIS 的 43 端口常被 ISP/防火墙拦截，国内尤其常见）。
            recs.append(
                f"⚠️ WHOIS 域名信息未能核验（{di.get('error')}），域名注册时间/持有者未知"
            )
        if age_cat == "new":
            # 域名为新注册（不足 1 年），提示风险
            recs.append(
                f"⚠️ 域名注册仅 {days} 天，属于新注册域名，配套信息待验证"
            )
        elif age_cat == "old" and days:
            # 域名注册超过 3 年，长期运营可信度高
            recs.append(
                f"✅ 域名注册已 {days} 天，长期运营可信度高"
            )

    # ── 技术栈建议 ──
    ts = layers.get("tech_stack")
    if ts:
        # 根据技术栈检测结果生成建议
        if ts.get("is_free_platform"):
            # 使用免费建站平台，公司规模可能较小
            platforms = ", ".join(ts.get("platforms", []))
            recs.append(
                f"⚠️ 网站使用免费建站平台（{platforms}），可能代表公司规模较小"
            )
        elif ts.get("error"):
            # 抓取失败时**不能**当成"技术栈没问题"：什么都不说会让读者以为
            # 这一层核验通过了。如实披露未验证。
            recs.append(
                f"⚠️ 网站无法访问或抓取失败（{ts.get('error')}），技术栈未能验证"
            )
        elif ts.get("is_enterprise"):
            # 使用企业级技术栈，可信度加分
            recs.append("✅ 网站使用企业级技术栈，可信度 +1")

    # ── 制裁名单建议 ──
    sa = layers.get("sanctions")
    if sa:
        # 根据制裁名单检测结果生成建议
        if sa.get("is_sanctioned"):
            # 明确命中制裁名单，最高风险等级
            recs.append("🚨 命中制裁名单，建议拒绝交易或咨询法律部门")
        elif sa.get("risk_level") == "medium":
            # 疑似匹配但不确定，需要人工核查
            recs.append("⚠️ 发现疑似制裁匹配，建议进一步人工核查")
        elif not sa.get("hits"):
            # 只有数据源健康时才敢下「未发现匹配」的结论。下载失败时会退化成
            # 几条内置样本，此时"没查到"完全是另一回事 —— 报告必须如实说明，
            # 否则用户会拿一条绿色的"已核查"去谈生意。
            # coverage 缺失（旧版报告/外部构造）按降级处理：保守优先。
            coverage = sa.get("coverage") or {}
            if coverage.get("degraded", True):
                total = coverage.get("total_entries", 0)
                recs.append(
                    f"⚠️ 制裁名单尚未成功下载（本地可用 {total} 条），"
                    "不构成「无制裁记录」的结论，请通过 OFAC/UN/EU/UK 官网人工复核"
                )
            else:
                recs.append("✅ 未在任何制裁名单中发现匹配项")

    # ── LinkedIn 建议（需 Agent 通过 browser_navigate 实际执行后补充）───
    li = layers.get("linkedin")
    if li and li.get("method") == "browser_navigate":
        # LinkedIn 验证尚未实际执行，提示 agent 使用浏览器工具完成
        recs.append(
            "🔍 LinkedIn 验证需要通过浏览器访问 LinkedIn 完成。"
            "请使用 browser_navigate 工具按 linkedin 层的 steps 指令执行验证。"
        )

    return recs
