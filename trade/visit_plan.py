"""验厂计划（s5–s7）：一份来访计划 = 元信息 + payload(JSON)。

所有明细字段（行程/日程/人员/清单/风险…）放在 payload，避免每加一个字段就
migration；列表/打印/长图共用同一条记录。
"""

from __future__ import annotations

import json
from typing import Any

from trade.database import begin_immediate, get_connection


class VisitPlanError(Exception):
    """验厂计划写入被拒（客户不属于本公司等）。"""


def _as_days(value: Any) -> int:
    """天数解析：非法或非正一律按 1 天，避免 int() 抛 ValueError 变 500。"""
    try:
        n = int(value or 1)
    except (TypeError, ValueError):
        return 1
    return n if n > 0 else 1


def _assert_customer_in_company(conn, customer_id: int | None, company_id: int) -> None:
    """校验客户属于本公司；不属于就拒写。

    此前 customer_id 原样入库，可以挂别家客户的 id（2026-11-20 审计 P2-8）。
    customer_id 为空是合法用法（不关联客户的计划），直接放行。
    """
    # 不关联客户是合法用法：空 id 直接放行，不做归属校验
    if not customer_id:
        return
    row = conn.execute(
        "SELECT 1 FROM customers WHERE id = ? AND company_id = ?",
        (customer_id, company_id),
    ).fetchone()
    # 查不到 = 不存在或属于别家，一律拒绝，避免泄露"这个 id 存不存在"
    if not row:
        raise VisitPlanError("客户不属于本公司")


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        payload = json.loads(d.get("payload") or "{}")
    except (TypeError, ValueError):
        payload = {}
    d["payload"] = payload if isinstance(payload, dict) else {}
    return d


def list_plans(company_id: int) -> list[dict]:
    """按公司列出验厂计划（最近更新在前）。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM visit_plans WHERE company_id = ? AND status <> 'deleted' "
            "ORDER BY updated_at DESC, id DESC",
            (company_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception:
        # 升级未重启时表可能还不存在：降级为空列表，不阻断页面
        return []
    finally:
        conn.close()


def get_plan(plan_id: int, *, company_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM visit_plans WHERE id = ? AND company_id = ? AND status <> 'deleted'",
            (plan_id, company_id),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def create_plan(
    company_id: int,
    *,
    customer_id: int | None = None,
    title: str = "",
    visit_date: str = "",
    days: Any = 1,
    location: str = "",
    payload: dict | None = None,
) -> int:
    conn = get_connection()
    try:
        begin_immediate(conn)
        _assert_customer_in_company(conn, customer_id, company_id)
        cur = conn.execute(
            "INSERT INTO visit_plans "
            "(company_id, customer_id, title, visit_date, days, location, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                customer_id,
                str(title or ""),
                str(visit_date or ""),
                _as_days(days),
                str(location or ""),
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_plan(plan_id: int, *, company_id: int, **fields) -> dict | None:
    """部分更新；payload 传 dict 时整体替换。"""
    allowed = {"customer_id", "title", "visit_date", "days", "location", "payload", "status"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_plan(plan_id, company_id=company_id)
    if "payload" in updates:
        updates["payload"] = json.dumps(updates["payload"] or {}, ensure_ascii=False)
    if "days" in updates:
        updates["days"] = _as_days(updates["days"])
    cols = ", ".join(f"{k} = ?" for k in updates)
    conn = get_connection()
    try:
        begin_immediate(conn)
        # 改挂客户时同样校验归属，不能把计划挪到别家客户身上
        if "customer_id" in updates and updates["customer_id"]:
            _assert_customer_in_company(conn, updates["customer_id"], company_id)
        cur = conn.execute(
            f"UPDATE visit_plans SET {cols}, updated_at = datetime('now','localtime') "
            "WHERE id = ? AND company_id = ?",
            (*updates.values(), plan_id, company_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_plan(plan_id, company_id=company_id)


def delete_plan(plan_id: int, *, company_id: int) -> bool:
    """软删除，保留审计痕迹。"""
    conn = get_connection()
    try:
        begin_immediate(conn)
        cur = conn.execute(
            "UPDATE visit_plans SET status = 'deleted', updated_at = datetime('now','localtime') "
            "WHERE id = ? AND company_id = ?",
            (plan_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── 验厂建议生成（本地规则：通用清单 + 按国家礼仪/禁忌）──
_GENERIC_TIPS = [
    "守时，提前 10 分钟到达；正式称呼对方并准备名片",
    "不主动谈政治、宗教、收入等敏感话题",
    "尊重饮食禁忌（宗教/素食/酒精），点餐前先问一句",
    "拍照、录像、参观产线前先征得同意",
    "礼品合规：不送现金/贵重物品；客户索要一律拒绝并上报",
]

_COUNTRY_TIPS = {
    "德国": ["守时极重要，迟到需提前说明", "称呼 Herr/Frau + 姓氏，初次见面握手", "周日商店大多关门，约会避开周日",
             "避免纳粹/二战相关玩笑", "商务着装正式，名片简洁"],
    "美国": ["守时、直接表达，握手有力", "避免宗教、政治、个人隐私话题", "小费文化常见（餐饮 15–20%）"],
    "英国": ["守时，幽默含蓄", "避免脱欧、北爱尔兰等敏感话题", "正式称呼 Mr/Ms + 姓氏"],
    "法国": ["进门先说 Bonjour，离开说 Au revoir", "名片可备法文一面", "商务午餐较正式，避免过早谈钱"],
    "意大利": ["注重着装与家庭话题", "商务节奏较慢，关系先行", "避免拿意大利行政效率开玩笑"],
    "西班牙": ["午休文化，晚餐通常较晚", "商务关系需寒暄，勿急于进入正题"],
    "俄罗斯": ["正式、守时，握手要用力", "避免政治与乌克兰话题", "送礼避免偶数与黄色花"],
    "日本": ["名片双手递接并稍作阅读", "极度守时，鞠躬问候", "送礼讲究包装，避免 4/9 数字"],
    "韩国": ["双手接物，长辈/职位高者优先", "酒桌礼仪：侧身饮酒", "避免用红笔写名字"],
    "印度": ["右手递物/握手，避免左手", "尊重宗教与素食习惯，忌牛肉话题", "时间观念相对弹性，行程留余量"],
    "巴西": ["关系导向，寒暄与肢体距离较近", "守时相对弹性，正式场合仍需准时", "避免谈论阿根廷与政治"],
    "澳大利亚": ["风格直接随意，守时", "避免拿土著/移民话题开玩笑"],
    "加拿大": ["守时、礼貌，英法双语区注意语言", "避免把加拿大与美国混为一谈"],
    "荷兰": ["沟通直接，守时", "避免拿邻国与宗教开玩笑"],
    "波兰": ["正式握手，初次见面用头衔", "避免二战与邻国政治话题"],
    "土耳其": ["先茶后事，关系导向", "尊重宗教节日与祈祷时间", "避免亚美尼亚/库尔德等敏感话题"],
    "越南": ["双手递名片，尊重长辈", "避免摸头、用脚指物", "佛教场所着装保守"],
    "泰国": ["头部神圣、脚不洁，勿触碰他人头部", "进入寺庙着装保守", "对王室保持尊重"],
    "墨西哥": ["关系导向，寒暄充分", "守时弹性，正式会议仍需准时", "避免移民与治安话题"],
    "阿联酋": ["右手递物，避免左手", "斋月白天不在公共场合饮食", "避免酒精与亲密举止，尊重女性礼仪"],
    "沙特": ["右手递物，避免左手", "斋月遵守禁食规定", "避免宗教与政治话题，着装保守"],
    "新加坡": ["守时、高效", "多元宗教，避免种族与宗教玩笑", "公共场所禁口香糖"],
}


_COUNTRY_ALIASES = {
    "germany": "德国", "usa": "美国", "united states": "美国", "uk": "英国",
    "united kingdom": "英国", "france": "法国", "italy": "意大利", "spain": "西班牙",
    "russia": "俄罗斯", "japan": "日本", "korea": "韩国", "india": "印度",
    "brazil": "巴西", "australia": "澳大利亚", "canada": "加拿大", "netherlands": "荷兰",
    "poland": "波兰", "turkey": "土耳其", "vietnam": "越南", "thailand": "泰国",
    "mexico": "墨西哥", "uae": "阿联酋", "saudi": "沙特", "singapore": "新加坡",
}


def _match_country_tips(country: str) -> list[str]:
    """根据国家名称匹配商务礼仪提示，英文别名按词边界匹配以防缩写子串误判。"""
    import re as _re

    s = str(country or "")
    lower = s.lower()
    normalized = s
    # 长别名优先匹配，且要求前后非英文字母（防止 "uk" 误命中 "Ukraine"）
    for en, zh in sorted(_COUNTRY_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True):
        if _re.search(rf"(?<![a-z]){_re.escape(en)}(?![a-z])", lower):
            normalized = zh
            break
    for key, tips in _COUNTRY_TIPS.items():
        # 命中已知中文国家名则返回对应礼仪清单
        if key in normalized:
            return tips
    return _GENERIC_TIPS


def suggest_draft(company_id: int, customer_id: int | None = None) -> dict:
    """生成验厂计划建议（通用现场准备 + 国家礼仪/禁忌 + 出发前事项）。

    纯本地规则，不调用模型、不写库；前端填空用。
    """
    from trade import customer as customer_module

    name = ""
    country = ""
    if customer_id:
        cust = customer_module.get(customer_id, company_id=company_id)
        if cust:
            name = cust.get("name") or ""
            try:
                e1 = json.loads(cust.get("extra1") or "{}")
            except (TypeError, ValueError):
                e1 = {}
            country = (e1.get("country") or "").strip()

    checklist = (
        "【出发前】\n"
        "- 与客户书面确认来访日期、人数、航班/车次与接机安排\n"
        "- 确认酒店、行程表与陪同人员，发送确认邮件\n"
        "- 护照/签证/邀请函/名片/保险/常用药\n"
        "- 样品、报价单、认证与图纸齐套，标签朝外、可快速取用\n"
        "- 与客户确认是否可拍照/录像、是否携带设备\n\n"
        "【现场准备 · 卫生与安全】\n"
        "- 车间/仓库 5S：地面无油污、通道畅通、物料定置\n"
        "- 访客安全：安全帽/护目镜/反光背心、逃生路线、急救箱\n"
        "- 卫生间、茶水间、会议室清洁，异味与杂物清理\n"
        "- 涉密区域遮挡或绕行；拍照先征得同意\n"
        "- 样品台与演示流程预演，设备提前通电测试"
    )

    tips = _match_country_tips(country)
    risk_lines = ["【礼仪与禁忌 · " + (country or "客户所在国") + "】"]
    risk_lines += ["- " + t for t in tips]
    risk_lines += [
        "",
        "【现场风险】",
        "- 未经确认不得拍摄产线/客户资料",
        "- 不现场承诺交期与价格，统一由业务确认后回复",
        "- 礼品合规：不送现金与贵重物品；客户索要一律拒绝并上报",
    ]

    # 客户画像带入内部提醒：只带非敏感类（家庭/礼物往来绝对不进打印件与长图）
    # 敏感类只报数量、不写原文（2026-11-20 审计 P0-1）
    profile_notes: list[str] = []
    sensitive_count = 0
    if customer_id:
        try:
            from trade import profile as profile_mod

            # 默认取「待确认 + 已确认」：用户刚添加的画像条目还没确认，也必须带出来
            for f in profile_mod.list_facts(customer_id, company_id=company_id):
                cat = str(f.get("category") or "").strip()
                subject = str(f.get("subject") or "").strip()
                content = str(f.get("content") or "").strip()
                # 敏感类（家庭/礼物往来）只计数，原文一律丢弃；
                # 其他分类里写了家庭称谓（如「重要日期：太太生日」）同样过滤
                if (cat in profile_mod.SENSITIVE_CATEGORIES
                        or profile_mod.contains_family_terms(subject + " " + content)):
                    sensitive_count += 1
                    continue
                # 对象和内容都为空：没有可展示信息，跳过
                if not content and not subject:
                    continue
                # 待确认条目在分类后追加标记，提醒现场核实
                if str(f.get("status") or "") == "待确认":
                    cat = (cat + " · 待确认") if cat else "待确认"
                # 对象和内容都要带上：对象是谁、具体是什么事
                body = (subject + "：" + content) if (subject and content) else (subject or content)
                profile_notes.append(("- [" + cat + "] " if cat else "- ") + body)
        except Exception:
            # 画像表不存在 / 老库未升级：静默跳过，不影响基础建议
            profile_notes = []
    # 有非敏感条目或有敏感计数时都要出标题：计数行本身就是提醒
    if profile_notes or sensitive_count:
        risk_lines += ["", "【客户档案提醒 · 内部】"]
        risk_lines += profile_notes
        # 只报数量，不给原文，避免随打印件/长图外流
        if sensitive_count:
            risk_lines.append(
                f"- 该客户有 {sensitive_count} 条私密档案，未在此显示；需要时单独查阅备忘录"
            )
    summary = (
        "感谢来访。我们将安排车间参观、样品演示与商务沟通；"
        "如需拍摄或进入特定区域，请提前告知，我们会做好安排。"
    )
    return {
        "checklist": checklist,
        "risks": "\n".join(risk_lines),
        # 单独返回，前端可只把这些追加到已有风险里，不覆盖用户改过的内容
        "profile_notes": profile_notes,
        "summary": summary,
        "country": country,
        "customer": name,
    }
