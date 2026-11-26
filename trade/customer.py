"""
Trade AI Assistant — 客户管理模块。

B2B 客户 CRUD，支持可选的文档库关联。
所有操作均受 company_id 作用域限制，实现多租户隔离。
"""

import json
import os
import re

from trade.database import begin_immediate, get_connection

# CRM 商机阶段白名单（与前端 _CRM_STAGES / API Literal 对齐）
CRM_STAGES = frozenset({"询盘", "报价", "样品", "订单"})


def _ts_key(value) -> float:
    """把对话/邮件两种时间格式统一成可比较的 epoch 秒。"""
    s = str(value or "").strip()
    if not s:
        return float("-inf")
    try:
        from datetime import datetime
        return datetime.fromisoformat(s.replace(" ", "T")).timestamp()
    except (TypeError, ValueError):
        return float("-inf")


def _normalize_crm_stage(stage: str | None, *, default: str = "询盘") -> str:
    """非法阶段回落到 default，避免脏值进库。"""
    s = (stage or "").strip()
    return s if s in CRM_STAGES else default


def _normalize_website(url: str | None) -> str:
    """标准化公司官网用于查重：转小写并剥离协议头、www 前缀与尾部斜杠。"""
    s = (url or "").strip().lower()
    # 空串直接返回，避免无意义正则处理
    if not s:
        return ""
    return re.sub(r"^https?://(www\.)?", "", s).rstrip("/")


def _normalize_is_starred(v) -> int:
    """只认 0/1；其它值视为 0。"""
    try:
        return 1 if int(v) == 1 else 0
    except (TypeError, ValueError):
        return 0


def create(
    name: str,
    contact: str = "",
    note: str = "",
    *,
    company_id: int,
    country: str = "",
    city: str = "",
    tier: str = "",
    linkedin_url: str = "",
    company_website: str = "",
    social_media: dict | None = None,
    title: str = "",
    email: str = "",
    backup_email: str = "",
    phone: str = "",
    whatsapp: str = "",
    wechat: str = "",
    source: str = "",
    buyer_type: str = "",
    follow_up_note: str = "",
    main_category: str = "",
    match_score: int = 0,
    function: str = "",
    responsibility: str = "",
    stage: str = "询盘",
    next_follow_up_date: str = "",
    is_starred: int = 0,
    _skip_dedup: bool = False,
) -> dict:
    """创建一条归属于指定公司的客户记录。返回新行的字典表示。

    _skip_dedup 内部参数：bulk_save() 等调用方已在外部做过去重时传入 True，
    跳过本函数内的 O(n) 软去重扫描，避免 N+1 性能退化。
    """
    from trade.contacts import _normalize_function

    stage = _normalize_crm_stage(stage)
    is_starred = _normalize_is_starred(is_starred)
    next_follow_up_date = (next_follow_up_date or "").strip()
    # 主联系人职能白名单归一；城市进 extra1
    function = _normalize_function(function)
    responsibility = (responsibility or "").strip()
    city = (city or "").strip()
    extra1 = json.dumps({
        "country": country,
        "city": city,
        "tier": tier,
        "linkedin_url": linkedin_url,
        "company_website": company_website,
        "social_media": social_media or {},
        "buyer_type": buyer_type,
        "main_category": main_category,
        "match_score": match_score,
    }, ensure_ascii=False)
    extra2 = json.dumps({
        "title": title,
        "email": email,
        "backup_email": backup_email,
        "phone": phone,
        "whatsapp": whatsapp,
        "wechat": wechat,
        "source": source,
        "follow_up_note": follow_up_note,
        "function": function,
        "responsibility": responsibility,
    }, ensure_ascii=False)

    conn = get_connection()
    try:
        # 软去重检查：在同一连接内用 SQL json_extract 做原子查询，
        # 消除之前 list_by_company() 跨连接的 TOCTOU 竞态窗口
        _warn = None
        _dup_id = None
        # 去重策略（优化路线 P1-5）：warn=只警告仍写入（默认，保持兼容）；
        # block=命中重复时拒绝写入；suggest=警告并返回候选 id 供上层合并。
        dedup_mode = os.environ.get("TRADE_DEDUP_MODE", "warn").strip().lower()
        if not _skip_dedup and (email or company_website):
            _email_check = (email or "").strip().lower()
            _site_check = _normalize_website(company_website)
            if _email_check:
                dup = conn.execute(
                    "SELECT id FROM customers WHERE company_id = ? "
                    "AND LOWER(COALESCE(json_extract(extra2, '$.email'), '')) = ? "
                    "LIMIT 1",
                    (company_id, _email_check),
                ).fetchone()
                if dup:
                    _warn = "email_already_exists"
                    _dup_id = dup[0]
            if not _warn and _site_check:
                # 与 bulk_save / find_duplicates 共用同一域名归一化口径
                for srow in conn.execute(
                    "SELECT id, json_extract(extra1, '$.company_website') AS ws "
                    "FROM customers WHERE company_id = ?",
                    (company_id,),
                ).fetchall():
                    if _normalize_website(srow["ws"]) == _site_check:
                        _warn = "website_already_exists"
                        _dup_id = srow["id"]
                        break

        if _warn and dedup_mode == "block":
            # 拒绝写入：返回错误结构而非抛异常，保持返回 dict 的契约
            return {
                "error": "duplicate",
                "duplicate_warning": _warn,
                "duplicate_customer_id": _dup_id,
                "company_id": company_id,
            }

        # 默认「询盘」→ override NULL（自动推导）；非默认 → 同步锁定 override
        stage_override = None if stage == "询盘" else stage
        cur = conn.execute(
            "INSERT INTO customers "
            "(company_id, name, contact, note, stage, stage_override, "
            "next_follow_up_date, is_starred, extra1, extra2) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id, name, contact, note,
                stage, stage_override, next_follow_up_date, is_starred,
                extra1, extra2,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM customers WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        result = _row_to_dict(row)
        if _warn:
            result["duplicate_warning"] = _warn
            if dedup_mode == "suggest" and _dup_id is not None:
                result["duplicate_customer_id"] = _dup_id
        # 语义索引：best-effort，立即写入，避免"刚建的客户搜不到"
        _index_customer_best_effort(conn, result)
        return result
    finally:
        conn.close()


def list_by_company(
    company_id: int,
    *,
    page: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """返回指定公司的客户，按最新创建排在前面。

    每条附上列表用聚合字段（前端筛选/排序用，不再另打订单/对话接口）：
    - order_count / order_total_amount
    - last_talk_at / last_email_at / last_contact_at（两者取较新）
    - extra_contacts: [{id, name, email}]

    page 为 None 时返回全量（兼容现有前端）；传了 page（1 起）才切页。
    需要 total 时用 list_by_company_page。
    """
    items, _total = list_by_company_page(company_id, page=page, limit=limit)
    return items


def list_by_company_page(
    company_id: int,
    *,
    page: int | None = None,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """同 list_by_company，额外返回 total_count（供 X-Total-Count）。"""
    lim = max(1, min(int(limit or 50), 200))
    conn = get_connection()
    try:
        total = int(conn.execute(
            "SELECT COUNT(*) AS c FROM customers WHERE company_id = ?",
            (company_id,),
        ).fetchone()["c"])
        if page is None:
            # 未传 page：全量返回，保持旧行为
            rows = conn.execute(
                "SELECT * FROM customers WHERE company_id = ? ORDER BY id DESC",
                (company_id,),
            ).fetchall()
        else:
            # 传了 page 才 LIMIT/OFFSET
            p = max(1, int(page))
            offset = (p - 1) * lim
            rows = conn.execute(
                "SELECT * FROM customers WHERE company_id = ? "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (company_id, lim, offset),
            ).fetchall()
        customers = [_row_to_dict(r) for r in rows]
        _attach_list_aggregates(conn, company_id, customers)
        return customers, total
    finally:
        conn.close()


def get_company_summary(company_id: int) -> dict:
    """公司级客户列表顶栏汇总（不折算多币种）。

    follow_up_pending = next_follow_up_date 非空且 ≥ 今天（逾期不计入）。
    """
    from datetime import date

    today = date.today().isoformat()
    conn = get_connection()
    try:
        total = int(conn.execute(
            "SELECT COUNT(*) AS c FROM customers WHERE company_id = ?",
            (company_id,),
        ).fetchone()["c"])
        follow_up_pending = int(conn.execute(
            "SELECT COUNT(*) AS c FROM customers WHERE company_id = ? "
            "AND TRIM(COALESCE(next_follow_up_date, '')) != '' "
            "AND next_follow_up_date >= ?",
            (company_id, today),
        ).fetchone()["c"])
        overdue = int(conn.execute(
            "SELECT COUNT(*) AS c FROM customers WHERE company_id = ? "
            "AND TRIM(COALESCE(next_follow_up_date, '')) != '' "
            "AND next_follow_up_date < ?",
            (company_id, today),
        ).fetchone()["c"])

        stage_counts = {"询盘": 0, "报价": 0, "样品": 0, "订单": 0}
        for r in conn.execute(
            "SELECT COALESCE(NULLIF(TRIM(stage), ''), '询盘') AS stage, COUNT(*) AS c "
            "FROM customers WHERE company_id = ? GROUP BY stage",
            (company_id,),
        ).fetchall():
            key = r["stage"] if r["stage"] in stage_counts else "询盘"
            stage_counts[key] = stage_counts.get(key, 0) + int(r["c"])

        tier_counts = {"A": 0, "B": 0, "C": 0, "未分级": 0}
        for r in conn.execute(
            "SELECT COALESCE(NULLIF(TRIM(json_extract(extra1, '$.tier')), ''), '') AS tier, "
            "COUNT(*) AS c FROM customers WHERE company_id = ? GROUP BY tier",
            (company_id,),
        ).fetchall():
            t = (r["tier"] or "").strip().upper()
            if t in ("A", "B", "C"):
                tier_counts[t] += int(r["c"])
            else:
                tier_counts["未分级"] += int(r["c"])

        order_totals_by_currency: dict[str, float] = {}
        for r in conn.execute(
            "SELECT COALESCE(NULLIF(TRIM(currency), ''), 'USD') AS currency, "
            "SUM(total_amount) AS total "
            "FROM orders WHERE company_id = ? AND total_amount IS NOT NULL "
            "GROUP BY currency",
            (company_id,),
        ).fetchall():
            order_totals_by_currency[r["currency"]] = float(r["total"] or 0)

        # 公司级最近联系：对话与邮件取较新
        last_talk = conn.execute(
            "SELECT MAX(created_at) AS t FROM conversations "
            "WHERE company_id = ? AND customer_id IS NOT NULL",
            (company_id,),
        ).fetchone()["t"]
        last_email = None
        try:
            last_email = conn.execute(
                "SELECT MAX(received_at) AS t FROM emails "
                "WHERE company_id = ? AND customer_id IS NOT NULL",
                (company_id,),
            ).fetchone()["t"]
        except Exception:
            last_email = None
        if last_talk and last_email:
            # ISO(T) 与空格格式不可直接比字符串；统一走 _ts_key
            last_contact_at = (
                last_talk if _ts_key(last_talk) >= _ts_key(last_email) else last_email
            )
        else:
            last_contact_at = last_talk or last_email

        return {
            "total": total,
            "follow_up_pending": follow_up_pending,
            "overdue": overdue,
            "stage_counts": stage_counts,
            "tier_counts": tier_counts,
            "order_totals_by_currency": order_totals_by_currency,
            "last_contact_at": last_contact_at,
        }
    finally:
        conn.close()


def _totals_from_currency_rows(rows) -> tuple[int, float | None, str | None, dict[str, float]]:
    """把按币种聚合的行收成 (count, single_total|None, single_currency|None, by_currency)。

    多币种时不把金额硬加在一起（审计 P2：混币种 SUM 会错），
    order_total_amount 只在单一币种时有值；仅含「单价待谈」(total_amount IS NULL)
    的币种行只计入总单数 count，不生成 0.0 币种桶（与 get_overview 口径一致）。
    """
    by_currency: dict[str, float] = {}
    count = 0
    for r in rows:
        count += int(r["order_count"] or 0)
        keys = r.keys() if hasattr(r, "keys") else ()
        priced = (
            int(r["priced_count"] or 0)
            if "priced_count" in keys
            else int(r["order_count"] or 0)
        )
        # 该币种全部为待谈（total_amount IS NULL）时不污染已定价币种桶
        if priced <= 0:
            continue
        cur = (r["currency"] or "USD").strip() or "USD"
        by_currency[cur] = by_currency.get(cur, 0.0) + float(r["order_total_amount"] or 0)
    if len(by_currency) == 1:
        currency, total = next(iter(by_currency.items()))
        return count, total, currency, by_currency
    if not by_currency:
        # 无任何订单保持 (0, 0.0, None, {})；仅有待谈订单则总额为 None
        return (0, 0.0, None, {}) if count == 0 else (count, None, None, {})
    return count, None, None, by_currency


def _attach_list_aggregates(
    conn, company_id: int, customers: list[dict]
) -> None:
    """就地给客户列表挂上订单数/总额/最近联系时间/附加联系人。

    订单按 (customer_id, currency) 分组，避免跨币种直接相加。
    last_contact_at = max(last_talk_at, last_email_at)；同时返回拆分字段。
    """
    if not customers:
        return
    # customer_id -> list of currency rows（同时统计总单数与已定价单数）
    order_rows: dict[int, list] = {}
    for r in conn.execute(
        "SELECT customer_id, COALESCE(NULLIF(TRIM(currency), ''), 'USD') AS currency, "
        "COUNT(*) AS order_count, "
        "COUNT(total_amount) AS priced_count, "
        "COALESCE(SUM(total_amount), 0) AS order_total_amount "
        "FROM orders WHERE company_id = ? GROUP BY customer_id, currency",
        (company_id,),
    ).fetchall():
        order_rows.setdefault(int(r["customer_id"]), []).append(r)

    last_talk = {
        int(r["customer_id"]): r["last_talk_at"]
        for r in conn.execute(
            "SELECT customer_id, MAX(created_at) AS last_talk_at "
            "FROM conversations WHERE company_id = ? AND customer_id IS NOT NULL "
            "GROUP BY customer_id",
            (company_id,),
        ).fetchall()
    }
    # emails 表可能尚未建好（升级后未重启）——缺表时邮件最近联系视为空
    last_email: dict[int, str] = {}
    try:
        for r in conn.execute(
            "SELECT customer_id, MAX(received_at) AS last_email_at "
            "FROM emails WHERE company_id = ? AND customer_id IS NOT NULL "
            "GROUP BY customer_id",
            (company_id,),
        ).fetchall():
            last_email[int(r["customer_id"])] = r["last_email_at"]
    except Exception:
        last_email = {}

    # 附加联系人一次 IN 查询，不做 N+1；contacts 缺表时降级为空
    extra_by_cust: dict[int, list[dict]] = {int(c["id"]): [] for c in customers}
    try:
        ids = list(extra_by_cust.keys())
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            placeholders = ",".join("?" * len(chunk))
            for r in conn.execute(
                f"SELECT id, customer_id, name, email FROM contacts "
                f"WHERE company_id = ? AND customer_id IN ({placeholders})",
                (company_id, *chunk),
            ).fetchall():
                cid = int(r["customer_id"])
                extra_by_cust.setdefault(cid, []).append({
                    "id": int(r["id"]),
                    "name": r["name"] or "",
                    "email": r["email"] or "",
                })
    except Exception:
        # contacts 表缺失时列表仍可用
        pass

    # 关联文档库一次 JOIN 批量查询，消除前端客户列表 N+1 串行请求
    libs_by_cust: dict[int, list[dict]] = {int(c["id"]): [] for c in customers}
    try:
        ids = list(libs_by_cust.keys())
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            placeholders = ",".join("?" * len(chunk))
            for r in conn.execute(
                f"SELECT cl.customer_id, l.* FROM customer_libraries cl "
                f"JOIN libraries l ON l.id = cl.library_id "
                f"WHERE l.company_id = ? AND cl.customer_id IN ({placeholders}) "
                f"ORDER BY l.id DESC",
                (company_id, *chunk),
            ).fetchall():
                cid = int(r["customer_id"])
                libs_by_cust.setdefault(cid, []).append(_library_row_to_dict(r))
    except Exception:
        # customer_libraries / libraries 缺表时列表仍可用
        pass

    for c in customers:
        cid = int(c["id"])
        count, total, currency, by_cur = _totals_from_currency_rows(
            order_rows.get(cid, [])
        )
        talk_at = last_talk.get(cid)
        email_at = last_email.get(cid)
        # 取两者中较新的作为「最近联系」
        if talk_at and email_at:
            contact_at = talk_at if _ts_key(talk_at) >= _ts_key(email_at) else email_at
        else:
            contact_at = talk_at or email_at
        c["order_count"] = count
        c["order_total_amount"] = total
        c["order_total_currency"] = currency
        c["order_totals_by_currency"] = by_cur
        c["last_talk_at"] = talk_at
        c["last_email_at"] = email_at
        c["last_contact_at"] = contact_at
        c["extra_contacts"] = extra_by_cust.get(cid, [])
        c["libraries"] = libs_by_cust.get(cid, [])


def get_overview(customer_id: int, *, company_id: int) -> dict | None:
    """CRM 卡片墙聚合：统计 + 人物/订单/邮件/重要对话 + 时间线（limit 50）。

    一次返回，前端点客户名只调本接口。人物 v1 = extra2 联系字段；
    邮件 v1 = 邮箱地址 + 空态，不编造邮件记录。
    """
    cust = get(customer_id, company_id=company_id)
    if not cust:
        return None

    from trade import chat_memory
    from trade import order as order_module

    try:
        e2 = json.loads(cust.get("extra2") or "{}")
    except (json.JSONDecodeError, TypeError):
        e2 = {}
    if not isinstance(e2, dict):
        e2 = {}

    # 主联系人真源 = contact + extra2；附加联系人来自 contacts 表（缺表降级为空）
    from trade import contacts as contacts_module

    primary = contacts_module.build_primary_person(cust)
    extras = contacts_module.list_additional(customer_id, company_id=company_id)
    people: list[dict] = []
    if primary is not None:
        # overview 不暴露 backup_email
        people.append({k: v for k, v in primary.items() if k != "backup_email"})
    people.extend(extras)
    email_details = contacts_module.collect_email_details(cust, extras)
    emails = [d["address"] for d in email_details]

    orders = order_module.list_by_customer(customer_id, company_id=company_id)
    # 按币种汇总，禁止跨币种硬加（审计 P2）
    by_currency: dict[str, float] = {}
    quote_count = 0
    for o in orders:
        if (o.get("status") or "") == "报价中":
            quote_count += 1
        if o.get("total_amount") is None or o.get("total_amount") == "":
            continue
        cur = (o.get("currency") or "USD").strip() or "USD"
        by_currency[cur] = by_currency.get(cur, 0.0) + float(o["total_amount"] or 0)
    if len(by_currency) == 1:
        order_currency, order_total = next(iter(by_currency.items()))
    elif not by_currency:
        order_currency, order_total = None, None
    else:
        order_currency, order_total = None, None

    chats = chat_memory.list_by_company(
        company_id, limit=50, customer_id=customer_id
    )
    important = [c for c in chats if c.get("is_important")]
    # 无标记时用最近 5 条兜底；前端靠 is_important_fallback 改标题
    is_important_fallback = not bool(important)
    key_talks_raw = important if important else chats[:5]
    key_talks: list[dict] = []
    for conv in key_talks_raw:
        item = dict(conv)
        # title/summary 存 conversations.extra3；缺省空串
        e3 = conv.get("extra3") if isinstance(conv.get("extra3"), dict) else {}
        item["title"] = str((e3 or {}).get("title") or "")
        item["summary"] = str((e3 or {}).get("summary") or "")
        item["is_important_fallback"] = is_important_fallback
        key_talks.append(item)

    # emails 表行数（邮件条数，不是地址数）；缺表降级 0
    email_count = 0
    try:
        from trade.database import get_connection as _gc

        _conn = _gc()
        try:
            email_count = int(_conn.execute(
                "SELECT COUNT(*) AS c FROM emails "
                "WHERE company_id = ? AND customer_id = ?",
                (company_id, customer_id),
            ).fetchone()["c"])
        finally:
            _conn.close()
    except Exception:
        email_count = 0

    timeline: list[dict] = []
    for o in orders:
        timeline.append({
            "at": (o.get("created_at") or "")[:16],
            "kind": "order",
            "text": f"订单 {o.get('order_no') or ('#' + str(o.get('id')))} · {o.get('status') or ''}",
        })
    for conv in chats:
        timeline.append({
            "at": (conv.get("created_at") or "")[:16],
            "kind": "talk",
            "text": (conv.get("query") or "")[:120],
        })
    timeline.sort(key=lambda x: x.get("at") or "", reverse=True)
    timeline = timeline[:50]

    return {
        "customer": cust,
        "stats": {
            "people_count": len(people),
            "order_count": len(orders),
            "order_total_amount": order_total,
            "order_total_currency": order_currency,
            "order_totals_by_currency": by_currency,
            "mail_and_talk_count": len(emails) + len(key_talks),
            "email_count": email_count,
            "key_talk_count": len(key_talks),
            "quote_count": quote_count,
        },
        "people": people,
        "orders": orders,
        "emails": emails,
        "email_details": email_details,
        "key_talks": key_talks,
        "timeline": timeline,
    }


def record_follow_up(
    customer_id: int,
    *,
    company_id: int,
    next_follow_up_date: str | None = None,
    note: str = "",
    resolved: bool = False,
) -> dict | None:
    """逾期跟进处理：更新下次跟进日（或清空=不再跟进），并追加一条跟进事件。

    「逾期已解决」的信号 = 该客户 next_follow_up_date 不再早于今天
    （改为未来日期，或清空表示不再跟进）。事件写入 extra3.follow_events
    （无 migration），由 get_timeline 聚合为 follow_up_done 展示。
    """
    from datetime import date, datetime

    today = date.today().isoformat()
    nxt = (next_follow_up_date or "").strip()
    if not resolved:
        if not nxt:
            raise ValueError("需要新的下次跟进日，或标记「不再跟进」")
        if nxt < today:
            raise ValueError("下次跟进日不能早于今天")
    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = get_connection()
    try:
        # 与其他写路径一致：IMMEDIATE 先拿写锁，避免 SNAPSHOT 升级失败
        begin_immediate(conn)
        row = conn.execute(
            "SELECT extra2, extra3 FROM customers WHERE id = ? AND company_id = ?",
            (customer_id, company_id),
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        try:
            e2 = json.loads(row["extra2"]) if row["extra2"] else {}
        except Exception:
            e2 = {}
        try:
            e3 = json.loads(row["extra3"]) if row["extra3"] else {}
        except Exception:
            e3 = {}
        note_txt = (note or "").strip()
        if note_txt:
            e2["follow_up_note"] = note_txt
        events = e3.get("follow_events")
        if not isinstance(events, list):
            events = []
        events.append({"at": at, "note": note_txt, "next": "" if resolved else nxt})
        e3["follow_events"] = events[-50:]
        conn.execute(
            "UPDATE customers SET next_follow_up_date = ?, extra2 = ?, extra3 = ?, "
            "updated_at = datetime('now','localtime') WHERE id = ? AND company_id = ?",
            ("" if resolved else nxt,
             json.dumps(e2, ensure_ascii=False),
             json.dumps(e3, ensure_ascii=False),
             customer_id, company_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get(customer_id, company_id=company_id)


def get_timeline(
    customer_id: int, *, company_id: int, days: int = 60,
) -> list[dict] | None:
    """客户互动时间线（W8）：订单创建/状态、邮件、对话、今日应回复。

    返回 [{at, kind, title, detail, ref_type, ref_id}]，按 at 倒序。
    客户不存在返回 None；days 夹在 1–365。
    """
    from datetime import date, timedelta

    cust = get(customer_id, company_id=company_id)
    if not cust:
        return None

    window = max(1, min(int(days or 60), 365))
    cutoff = (date.today() - timedelta(days=max(0, window - 1))).isoformat()
    today = date.today().isoformat()
    events: list[dict] = []
    conn = get_connection()
    try:
        # 订单创建（SELECT * 兼容未迁移旧库缺物流列）
        for r in conn.execute(
            "SELECT * FROM orders "
            "WHERE company_id = ? AND customer_id = ? AND created_at >= ?",
            (company_id, customer_id, cutoff),
        ).fetchall():
            ono = r["order_no"] or f"#{r['id']}"
            events.append({
                "at": (r["created_at"] or "")[:16],
                "kind": "order_created",
                "title": f"{ono} 创建",
                "detail": "",
                "ref_type": "order",
                "ref_id": r["id"],
            })

        # 状态变更（含出货）
        try:
            for r in conn.execute(
                "SELECT e.id, e.order_id, e.from_status, e.to_status, e.at, e.note, "
                "o.order_no, o.container, o.port_of_loading "
                "FROM order_events e "
                "JOIN orders o ON o.id = e.order_id "
                "WHERE e.company_id = ? AND o.customer_id = ? AND e.at >= ?",
                (company_id, customer_id, cutoff),
            ).fetchall():
                ono = r["order_no"] or f"#{r['order_id']}"
                to_st = r["to_status"] or ""
                title = f"{ono} {to_st}" if to_st else f"{ono} 状态变更"
                detail = r["note"] or ""
                if to_st == "已出货":
                    bits = [x for x in (r["container"], r["port_of_loading"]) if x]
                    detail = (" ".join(bits) + "开船") if bits else (detail or "出货")
                    title = f"{ono} 出货"
                events.append({
                    "at": (r["at"] or "")[:16],
                    "kind": "order_status",
                    "title": title,
                    "detail": detail,
                    "ref_type": "order",
                    "ref_id": r["order_id"],
                })
        except Exception:
            pass  # order_events 缺表时跳过

        # 邮件 in/out：客户的全部地址（主/备用/附加联系人），不只主邮箱
        try:
            from trade import contacts as contacts_module
            extras = contacts_module.list_additional(customer_id, company_id=company_id)
            try:
                e2_all = json.loads(cust.get("extra2") or "{}")
            except (json.JSONDecodeError, TypeError):
                e2_all = {}
            if not isinstance(e2_all, dict):
                e2_all = {}
            addr_set = {
                str(e2_all.get(k) or "").strip().lower()
                for k in ("email", "backup_email")
            }
            contact_raw = str(cust.get("contact") or "").strip()
            if "@" in contact_raw:
                addr_set.add(contact_raw.lower())
            for p in extras:
                addr_set.add((p.get("email") or "").strip().lower())
            addr_set.discard("")
        except Exception:
            addr_set = set()
        try:
            for r in conn.execute(
                "SELECT id, subject, from_addr, to_addrs, received_at "
                "FROM emails WHERE company_id = ? AND customer_id = ? "
                "AND received_at >= ?",
                (company_id, customer_id, cutoff),
            ).fetchall():
                subj = (r["subject"] or "").strip() or "（无主题）"
                # 按客户全部地址判收发：命中任一地址 → email_in，否则 email_out
                from_addr = (r["from_addr"] or "").lower()
                kind = "email_in" if any(a in from_addr for a in addr_set) else "email_out"
                events.append({
                    "at": (r["received_at"] or "")[:16],
                    "kind": kind,
                    "title": subj[:80],
                    "detail": (r["from_addr"] or "")[:80],
                    "ref_type": "email",
                    "ref_id": r["id"],
                })
        except Exception:
            pass

        # 对话
        for r in conn.execute(
            "SELECT id, query, response, created_at, extra3 FROM conversations "
            "WHERE company_id = ? AND customer_id = ? AND created_at >= ?",
            (company_id, customer_id, cutoff),
        ).fetchall():
            try:
                e3 = json.loads(r["extra3"] or "{}")
            except (json.JSONDecodeError, TypeError):
                e3 = {}
            title = (e3.get("title") or "").strip() or (r["query"] or "")[:60]
            detail = (e3.get("summary") or "").strip() or (r["response"] or "")[:80]
            events.append({
                "at": (r["created_at"] or "")[:16],
                "kind": "talk",
                "title": title,
                "detail": detail,
                "ref_type": "conversation",
                "ref_id": r["id"],
            })
    finally:
        conn.close()

    # 今天应回复
    follow = (cust.get("next_follow_up_date") or "").strip()
    if follow == today:
        events.append({
            "at": today,
            "kind": "follow_up_due",
            "title": "今天 · 应回复",
            "detail": "",
            "ref_type": "customer",
            "ref_id": customer_id,
        })

    # 跟进处理事件（extra3.follow_events；复用时间线，无独立表）
    try:
        _e3 = json.loads(cust.get("extra3") or "{}")
    except Exception:
        _e3 = {}
    for fe in (_e3.get("follow_events") or []):
        atv = str(fe.get("at") or "")
        if not atv or atv[:10] < cutoff:
            continue
        fe_note = str(fe.get("note") or "").strip()
        fe_next = str(fe.get("next") or "").strip()
        tail = ("下次跟进 " + fe_next) if fe_next else "不再跟进"
        fe_detail = (fe_note + " · " + tail) if fe_note else tail
        events.append({
            "at": atv,
            "kind": "follow_up_done",
            "title": "跟进已处理",
            "detail": fe_detail,
            "ref_type": "customer",
            "ref_id": customer_id,
        })

    # 对话空格格式 vs 邮件 ISO 带 T：必须用 _ts_key，否则同日邮件永远排前
    events.sort(key=lambda x: _ts_key(x.get("at")), reverse=True)
    return events


def get(customer_id: int, *, company_id: int) -> dict | None:
    """根据 ID 获取单个客户，必须按公司作用域限制。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM customers WHERE id = ? AND company_id = ?",
            (customer_id, company_id),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def get_by_ids(customer_ids: list[int], *, company_id: int) -> dict[int, dict]:
    """一次取回多个客户，返回 {id: 客户dict}；按公司作用域过滤。

    为什么需要：语义搜索端点原先对每个命中调 `get()` —— 每命中一个新连接
    一次 SELECT（top_k 上限 100 → 最多 101 个连接），在 SQLite 上是明显的
    连接风暴，也放大写锁竞争（2026-10-22 审计 P2）。
    """
    if not customer_ids:
        return {}
    conn = get_connection()
    try:
        # SQLite 的 IN 参数上限是 999，这里按批处理避免超限
        out: dict[int, dict] = {}
        ids = [int(i) for i in customer_ids]
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT * FROM customers WHERE company_id = ? AND id IN ({placeholders})",
                (company_id, *chunk),
            ).fetchall()
            for r in rows:
                d = _row_to_dict(r)
                out[d["id"]] = d
        return out
    finally:
        conn.close()


def update(
    customer_id: int,
    *,
    company_id: int,
    **kwargs,
) -> dict | None:
    """更新客户字段（单事务，部分失败统一回滚）。

    基础字段: name, contact, note, stage, next_follow_up_date, is_starred
    extra1 字段: country, city, tier, linkedin_url, company_website, social_media, buyer_type, main_category, match_score
    extra2 字段: title, email, backup_email, phone, whatsapp, wechat, source, last_contact_at, follow_up_note, function, responsibility
    extra3 字段: tags（列表标签；阶段/跟进日已迁实列，不再写 extra3）
    """
    from trade.contacts import _normalize_function

    extra1_keys = {"country", "city", "tier", "linkedin_url", "company_website", "social_media", "buyer_type", "main_category", "match_score"}
    extra2_keys = {"title", "email", "backup_email", "phone", "whatsapp", "wechat", "source", "last_contact_at", "follow_up_note", "function", "responsibility"}
    extra3_keys = {"tags"}
    basic_allowed = {
        "name", "contact", "note",
        "stage", "next_follow_up_date", "is_starred",
    }

    extra1_updates = {k: v for k, v in kwargs.items() if k in extra1_keys and v is not None}
    extra2_updates = {k: v for k, v in kwargs.items() if k in extra2_keys and v is not None}
    # tags：显式传入才更新；None=本次不动
    extra3_updates = {k: v for k, v in kwargs.items() if k in extra3_keys and v is not None}
    basic_updates = {k: v for k, v in kwargs.items() if k in basic_allowed and v is not None}
    # stage 新语义：走 override，不直接当普通列写；先取出原始值
    stage_raw = basic_updates.pop("stage", None)
    if "is_starred" in basic_updates:
        basic_updates["is_starred"] = _normalize_is_starred(basic_updates["is_starred"])
    if "next_follow_up_date" in basic_updates and basic_updates["next_follow_up_date"] is not None:
        basic_updates["next_follow_up_date"] = str(basic_updates["next_follow_up_date"]).strip()
    # 主联系人职能脏值归一「其他」；职责 trim
    if "function" in extra2_updates:
        extra2_updates["function"] = _normalize_function(extra2_updates["function"])
    if "responsibility" in extra2_updates and extra2_updates["responsibility"] is not None:
        extra2_updates["responsibility"] = str(extra2_updates["responsibility"]).strip()
    if "city" in extra1_updates and extra1_updates["city"] is not None:
        extra1_updates["city"] = str(extra1_updates["city"]).strip()

    if not (
        extra1_updates or extra2_updates or extra3_updates
        or basic_updates or stage_raw is not None
    ):
        return get(customer_id, company_id=company_id)

    conn = get_connection()
    try:
        # 必须 BEGIN IMMEDIATE（直接拿写锁），不能是 deferred 的 BEGIN：
        # deferred 只开**读快照**，随后要把快照升级成写锁时，若期间有别的连接
        # 提交过，SQLite 直接抛 SQLITE_BUSY_SNAPSHOT —— **不重试**，
        # busy_timeout 完全不生效（2026-10-21 实测：瞬间 "database is locked"）。
        # 场景：用户点「保存客户」的同时，chat 请求正往 chat_memory 插一条对话
        # → 保存直接失败。IMMEDIATE 从一开始就排队拿写锁，busy_timeout 生效。
        begin_immediate(conn)

        # 读取当前 JSON 用于合并（company_id 贯穿所有写操作）
        row = conn.execute(
            "SELECT extra1, extra2, extra3 FROM customers WHERE id = ? AND company_id = ?",
            (customer_id, company_id),
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        current_extra1 = json.loads(row["extra1"]) if row["extra1"] else {}
        current_extra2 = json.loads(row["extra2"]) if row["extra2"] else {}
        current_extra3 = json.loads(row["extra3"]) if row["extra3"] else {}

        # 合并 extra1
        if extra1_updates:
            current_extra1.update(extra1_updates)
            conn.execute(
                "UPDATE customers SET extra1 = ?, updated_at = datetime('now','localtime') WHERE id = ? AND company_id = ?",
                (json.dumps(current_extra1, ensure_ascii=False), customer_id, company_id),
            )

        # 合并 extra2
        if extra2_updates:
            current_extra2.update(extra2_updates)
            conn.execute(
                "UPDATE customers SET extra2 = ?, updated_at = datetime('now','localtime') WHERE id = ? AND company_id = ?",
                (json.dumps(current_extra2, ensure_ascii=False), customer_id, company_id),
            )

        # 合并 extra3（仅 tags）
        if extra3_updates:
            current_extra3.update(extra3_updates)
            conn.execute(
                "UPDATE customers SET extra3 = ?, updated_at = datetime('now','localtime') WHERE id = ? AND company_id = ?",
                (json.dumps(current_extra3, ensure_ascii=False), customer_id, company_id),
            )

        # 基础字段（跟进日 / 标星等；stage 不在此列）
        if basic_updates:
            set_clause = ", ".join(f"{k} = ?" for k in basic_updates)
            values = list(basic_updates.values()) + [customer_id, company_id]
            sql = f"UPDATE customers SET {set_clause}, updated_at = datetime('now','localtime') WHERE id = ? AND company_id = ?"
            n = conn.execute(sql, values).rowcount
            if n == 0:
                conn.rollback()
                return None

        # N4：stage → override；「自动」清 override 并按询盘重算
        if stage_raw is not None:
            from trade.inquiry import STAGE_AUTO, recompute_customer_stage

            s = str(stage_raw).strip()
            if s == STAGE_AUTO:
                conn.execute(
                    "UPDATE customers SET stage_override=NULL, "
                    "updated_at=datetime('now','localtime') "
                    "WHERE id=? AND company_id=?",
                    (customer_id, company_id),
                )
                recompute_customer_stage(conn, customer_id, company_id)
            else:
                norm = _normalize_crm_stage(s)
                conn.execute(
                    "UPDATE customers SET stage_override=?, stage=?, "
                    "updated_at=datetime('now','localtime') "
                    "WHERE id=? AND company_id=?",
                    (norm, norm, customer_id, company_id),
                )

        conn.commit()
        result = get(customer_id, company_id=company_id)
        # 语义索引：改过的客户（改名/备注/邮箱）要立刻重算向量
        if result:
            _index_customer_best_effort(conn, result)
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete(customer_id: int, *, company_id: int) -> bool:
    """按公司作用域删除客户。如果删除了行则返回 True。"""
    conn = get_connection()
    try:
        begin_immediate(conn)
        # 双保险：显式清 contacts / inquiries（外键 CASCADE 也会清；缺表静默）
        from trade.contacts import delete_for_customer
        from trade.inquiry import delete_for_customer as delete_inquiries_for_customer

        delete_for_customer(conn, customer_id, company_id)
        delete_inquiries_for_customer(conn, customer_id, company_id)
        cur = conn.execute(
            "DELETE FROM customers WHERE id = ? AND company_id = ?",
            (customer_id, company_id),
        )
        conn.commit()
        deleted = cur.rowcount > 0
        if deleted:
            # 语义索引：同步移除，避免删掉的客户仍被搜出来
            _delete_customer_index_best_effort(conn, customer_id)
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── 语义索引钩子（best-effort，任何失败都不影响客户主流程）──────────────────

def _index_customer_best_effort(conn, cust: dict) -> None:
    """把客户写进语义索引。没装 sqlite-vec / 索引未建时静默跳过。

    为什么放在这里（而不是等 Phase 2）：向量检索只在"命中为空"时才降级关键词，
    索引过期会让**刚建的客户搜不到、还不降级** —— 这是用户最先撞上的问题。
    """
    try:
        from trade.vec_search import index_customer

        index_customer(conn, cust)
    except Exception:
        pass  # 索引是增强能力，坏了不能拖垮建客户


def _delete_customer_index_best_effort(conn, customer_id: int) -> None:
    """从语义索引移除客户（best-effort）。"""
    try:
        from trade.vec_search import delete_customer_vector

        delete_customer_vector(conn, customer_id)
    except Exception:
        pass


# ── Library associations ─────────────────────────────────────────────────────
# Security: all library associations are verified through company_id scoping
# to prevent cross-company linking.


def link_library(
    customer_id: int,
    library_id: int,
    company_id: int,
) -> bool:
    """将文档库关联到客户（两者必须属于同一公司）。

    成功返回 True；如果客户或文档库在给定公司下不存在，则抛出 ValueError。
    """
    # Verify both belong to the company
    cust = get(customer_id, company_id=company_id)
    if not cust:
        # 客户在指定公司下不存在，拒绝关联以防止跨公司操作
        raise ValueError(f"Customer {customer_id} not found under company {company_id}")

    from trade.library import get as get_library

    lib = get_library(library_id, company_id)
    if not lib:
        # 文档库在指定公司下不存在，拒绝关联
        raise ValueError(f"Library {library_id} not found under company {company_id}")

    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO customer_libraries (customer_id, library_id) VALUES (?, ?)",
            (customer_id, library_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def unlink_library(
    customer_id: int,
    library_id: int,
    company_id: int,
) -> bool:
    """按公司作用域移除客户与文档库的关联关系。

    Raises:
        ValueError: 客户在指定公司下不存在（区别于关联不存在的场景）
    """
    conn = get_connection()
    try:
        # Verify ownership before unlinking
        cust = get(customer_id, company_id=company_id)
        if not cust:
            # 客户在指定公司下不存在，抛异常以便调用方区分错误类型
            raise ValueError(f"Customer {customer_id} not found under company {company_id}")
        cur = conn.execute(
            "DELETE FROM customer_libraries WHERE customer_id = ? AND library_id = ?",
            (customer_id, library_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_libraries(customer_id: int, company_id: int) -> list[dict]:
    """返回与客户关联的所有文档库，按公司作用域限制。"""
    # Verify customer belongs to company
    cust = get(customer_id, company_id=company_id)
    if not cust:
        # 客户不属于该公司，返回空列表而非报错，保证调用方流程不受阻
        return []

    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT l.* FROM libraries l
               JOIN customer_libraries cl ON cl.library_id = l.id
               WHERE cl.customer_id = ? AND l.company_id = ?
               ORDER BY l.name""",
            (customer_id, company_id),
        ).fetchall()
        return [_library_row_to_dict(r) for r in rows]
    finally:
        conn.close()


# ── 管理查询（绕过 company_id 隔离，仅用于内部场景如级联删除验证）───────


def admin_get(customer_id: int) -> dict | None:
    """管理员查询——不限制 company_id。**仅用于测试验证物理删除**。

    ⚠️ 生产代码禁止调用：此函数绕过租户隔离，是潜在越权入口。
    测试用它验证 purge 后客户行确实被物理删除（而非因 company 过滤查不到）。
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


# ── helpers ──────────────────────────────────────────────────────────────────

def _json_load(raw):
    """安全解析 JSON 字符串，失败时返回空 dict。"""
    if not raw or not isinstance(raw, str):
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}

def _row_to_dict(row) -> dict:
    keys = row.keys()
    result = {
        "id": row["id"],
        "company_id": row["company_id"],
        "name": row["name"],
        "contact": row["contact"],
        "note": row["note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        # CRM 实列：缺列（未迁移）时给默认值，避免前端崩
        "stage": row["stage"] if "stage" in keys and row["stage"] is not None else "询盘",
        "next_follow_up_date": (
            row["next_follow_up_date"]
            if "next_follow_up_date" in keys and row["next_follow_up_date"] is not None
            else ""
        ),
        "is_starred": int(row["is_starred"] or 0) if "is_starred" in keys else 0,
    }
    # N4：有效阶段 + 是否自动推导（读路径一律不返回原始列裸值以外的歧义）
    from trade.inquiry import effective_stage_fields

    result.update(effective_stage_fields(row))
    # 扩展字段（JSON 列）：前端依赖 extra1/extra2/extra3 展示额外信息
    try:
        result["extra1"] = row["extra1"] or "{}"
    except Exception:
        result["extra1"] = "{}"
    try:
        result["extra2"] = row["extra2"] or "{}"
    except Exception:
        result["extra2"] = "{}"
    try:
        result["extra3"] = row["extra3"] or "{}"
    except Exception:
        result["extra3"] = "{}"
    return result


def _library_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "company_id": row["company_id"],
        "name": row["name"],
        "root_path": row["root_path"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ── 批量保存客户（Agent 可调用）────────────────────────────────────────────────

def bulk_save(
    company_id: int,
    customers: list[dict],
    *,
    library_id: int | None = None,
) -> dict:
    """批量导入客户列表，自动跳过已存在的同名客户。

    Agent 从对话或文档中提取客户信息后，可调用此函数批量写入数据库。

    Args:
        company_id: 公司 ID
        customers: 客户字典列表，每个可含:
            name (必填), contact, note, country, city, tier, linkedin_url,
            company_website, social_media (dict), email, backup_email,
            phone, whatsapp, wechat, source, buyer_type, follow_up_note,
            main_category, match_score, function, responsibility
        library_id: 如果从文档库扫描提取，自动关联此文档库

    Returns:
        {"created": N, "skipped": N, "total": N}
    """
    created = 0
    skipped = 0

    # 预加载已有客户的三维去重集合：名称 / email / website
    all_existing = list_by_company(company_id)
    existing_names = {c["name"].lower() for c in all_existing}
    existing_emails: set[str] = set()
    existing_websites: set[str] = set()
    for c in all_existing:
        ex1 = _json_load(c.get("extra1", "{}"))
        ex2 = _json_load(c.get("extra2", "{}"))
        em = (ex2.get("email", "") or "").strip().lower()
        ws = _normalize_website(ex1.get("company_website", ""))
        if em:
            existing_emails.add(em)
        if ws:
            existing_websites.add(ws)

    for cust in customers:
        name = (cust.get("name") or "").strip()
        if not name:
            # 客户名称为空，跳过此条记录
            skipped += 1
            continue

        if name.lower() in existing_names:
            # 同名客户已存在，跳过以避免重复
            skipped += 1
            continue

        # email-based 去重
        cust_email = (cust.get("email") or "").strip().lower()
        if cust_email and cust_email in existing_emails:
            skipped += 1
            continue
        # website-based 去重（按标准化域名比对）
        cust_website = _normalize_website(cust.get("company_website"))
        if cust_website and cust_website in existing_websites:
            skipped += 1
            continue

        result = create(
            name=name,
            contact=cust.get("contact", ""),
            note=cust.get("note", ""),
            company_id=company_id,
            country=cust.get("country", ""),
            city=cust.get("city", ""),
            tier=cust.get("tier", ""),
            linkedin_url=cust.get("linkedin_url", ""),
            company_website=cust.get("company_website", ""),
            social_media=cust.get("social_media"),
            title=cust.get("title", ""),
            email=cust.get("email", ""),
            backup_email=cust.get("backup_email", ""),
            phone=cust.get("phone", ""),
            whatsapp=cust.get("whatsapp", ""),
            wechat=cust.get("wechat", ""),
            source=cust.get("source", "agent"),
            buyer_type=cust.get("buyer_type", ""),
            follow_up_note=cust.get("follow_up_note", ""),
            main_category=cust.get("main_category", ""),
            match_score=cust.get("match_score", 0),
            function=cust.get("function", ""),
            responsibility=cust.get("responsibility", ""),
            _skip_dedup=True,
        )

        # 如果指定了文档库，自动关联
        if library_id:
            try:
                link_library(result["id"], library_id, company_id)
            except ValueError:
                # 关联失败（如文档库不存在）时静默跳过，不影响其他客户的导入
                pass

        existing_names.add(name.lower())
        if cust_email:
            existing_emails.add(cust_email)
        if cust_website:
            existing_websites.add(cust_website)
        created += 1

    return {"created": created, "skipped": skipped, "total": created + skipped}


# ── 数据完整度评分 ────────────────────────────────────────────────────────────

def compute_data_completeness(cust: dict, *, _extra1: dict | None = None, _extra2: dict | None = None) -> dict:
    """计算客户数据完整度评分。

    基于 extra1 + extra2 中 16 个字段的加权计算：
    - 高权重 (3)：email, phone, company_website — 核心联系方式
    - 中权重 (2)：linkedin_url, whatsapp, buyer_type — 重要辅助信息
    - 低权重 (1)：其余字段

    _extra1 / _extra2 可选预解析参数：调用方如 health_audit() 已解析过 JSON 时传入，
    避免重复 json.loads 开销。未传入时从 cust dict 中按需解析。

    Returns:
        {"score": int (0-100), "missing_fields": [str], "filled_count": int, "total_fields": int}
    """
    if _extra1 is not None and _extra2 is not None:
        # 调用方已预解析，直接使用，跳过 JSON 解析开销
        extra1 = _extra1
        extra2 = _extra2
    else:
        raw_extra1 = cust.get("extra1", "{}")
        raw_extra2 = cust.get("extra2", "{}")
        try:
            extra1 = json.loads(raw_extra1) if isinstance(raw_extra1, str) else (raw_extra1 or {})
        except (json.JSONDecodeError, TypeError):
            extra1 = {}
        try:
            extra2 = json.loads(raw_extra2) if isinstance(raw_extra2, str) else (raw_extra2 or {})
        except (json.JSONDecodeError, TypeError):
            extra2 = {}

    # 字段权重：关键联系信息权重更高
    field_weights = {
        "country": 1, "tier": 1, "linkedin_url": 2, "company_website": 3,
        "social_media": 1, "buyer_type": 2, "main_category": 1, "match_score": 1,
        "title": 1, "email": 3, "backup_email": 1, "phone": 3,
        "whatsapp": 2, "wechat": 1, "source": 1, "follow_up_note": 1,
    }

    total_weight = sum(field_weights.values())
    filled_weight = 0
    missing_fields = []

    for field, weight in field_weights.items():
        value = extra1.get(field) if field in extra1 else extra2.get(field)
        # match_score 默认值 0 表示「未评分」，等同于未填写
        if field == "match_score" and isinstance(value, (int, float)) and value == 0:
            missing_fields.append(field)
            continue
        if value is not None and value != "" and (isinstance(value, (str, int, float)) or isinstance(value, dict)):
            if isinstance(value, str) and not value.strip():
                missing_fields.append(field)
                continue
            if isinstance(value, dict) and not value:
                missing_fields.append(field)
                continue
            filled_weight += weight
        else:
            missing_fields.append(field)

    score = int((filled_weight / total_weight) * 100) if total_weight > 0 else 0
    return {
        "score": score,
        "missing_fields": missing_fields,
        "filled_count": len(field_weights) - len(missing_fields),
        "total_fields": len(field_weights),
    }


# ── 重复客户检测 ──────────────────────────────────────────────────────────────

def find_duplicates(company_id: int) -> list[dict]:
    """查找指定公司内可能的重复客户。

    匹配规则（按优先级）：
      1. 相同 email — extra2.email 精确匹配（忽略大小写）
      2. 相同 company_website — extra1.company_website 标准化域名匹配
         （去除协议、www 前缀、尾部斜杠后比较）

    Returns:
        重复组列表 [{reason, detail, customers:[{id,name,contact,extra1,extra2}]}, ...]
    """
    all_custs = list_by_company(company_id)
    if len(all_custs) < 2:
        return []

    groups = []

    # Rule 1: 相同 email
    email_map: dict[str, list[int]] = {}
    for c in all_custs:
        extra2 = _json_load(c.get("extra2", "{}"))
        email = (extra2.get("email", "") or "").strip().lower()
        if email:
            email_map.setdefault(email, []).append(c["id"])

    for email, ids in email_map.items():
        if len(ids) > 1:
            group = [c for c in all_custs if c["id"] in ids]
            groups.append({
                "reason": "email_match",
                "detail": email,
                "customers": group,
            })

    # Rule 2: 相同 company_website（标准化域名）
    # 独立于 email 匹配，不共享 used_ids — 同一客户可能同时匹配 email 和 website，
    # 这是正确的多重证据，不应丢失任一维度的重复检测信息
    site_map: dict[str, list[int]] = {}
    for c in all_custs:
        extra1 = _json_load(c.get("extra1", "{}"))
        site = _normalize_website(extra1.get("company_website", ""))
        if site:
            site_map.setdefault(site, []).append(c["id"])

    for site, ids in site_map.items():
        if len(ids) > 1:
            group = [c for c in all_custs if c["id"] in ids]
            groups.append({
                "reason": "website_match",
                "detail": site,
                "customers": group,
            })

    return groups


# ── 客户健康审计 ──────────────────────────────────────────────────────────────

def health_audit(company_id: int) -> dict:
    """客户健康审计：检测需要关注的客户。

    检查维度：
      1. 僵尸客户：90 天以上无联系且无活跃订单
      2. 高价值未转化：A 级客户但无订单
      3. 数据不完整：完整度 < 40%
      4. 需跟进：30 天以上未联系

    Returns:
        {summary, stale_customers, high_value_unconverted, incomplete_data, need_followup}
    """
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    all_custs = list_by_company(company_id)
    now = _dt.now()
    ninety_days_ago_dt = now - _td(days=90)
    thirty_days_ago_dt = now - _td(days=30)

    # 批量加载所有客户的订单，避免 N+1 查询
    cust_ids = [c["id"] for c in all_custs]
    orders_by_customer: dict[int, list[dict]] = {cid: [] for cid in cust_ids}
    if cust_ids:
        placeholders = ",".join("?" for _ in cust_ids)
        conn = get_connection()
        try:
            rows = conn.execute(
                f"SELECT * FROM orders WHERE customer_id IN ({placeholders}) "
                "AND company_id = ? ORDER BY created_at DESC",
                (*cust_ids, company_id),
            ).fetchall()
            from trade.order import _row_to_dict as _order_row
            for row in rows:
                o = _order_row(row)
                orders_by_customer.setdefault(o["customer_id"], []).append(o)
        finally:
            conn.close()

    stale_customers = []
    high_value_unconverted = []
    incomplete_data = []
    need_followup = []

    for cust in all_custs:
        extra1 = _json_load(cust.get("extra1", "{}"))
        extra2 = _json_load(cust.get("extra2", "{}"))

        agg_contact = (cust.get("last_contact_at") or "").strip()
        manual_contact = (extra2.get("last_contact_at") or "").strip()
        # 综合对话/邮件沟通时间与手填联系时间，取较新者；均为空时才回退 updated_at
        if agg_contact and manual_contact:
            last_contact = (
                agg_contact
                if _ts_key(agg_contact) >= _ts_key(manual_contact)
                else manual_contact
            )
        else:
            last_contact = agg_contact or manual_contact or (cust.get("updated_at") or "").strip()

        # 解析 last_contact 为 datetime 对象（前10位为 YYYY-MM-DD）
        last_contact_dt = None
        days_since = None
        if last_contact:
            try:
                last_contact_dt = _dt.strptime(last_contact[:10], "%Y-%m-%d")
                days_since = (now - last_contact_dt).days
            except (ValueError, IndexError):
                last_contact_dt = None

        # 从批量结果取订单
        orders = orders_by_customer.get(cust["id"], [])

        # 1. 僵尸客户：90 天以上无联系且无活跃订单（报价中/已下单/已出货）
        active_orders = [o for o in orders if o["status"] in ("报价中", "已下单", "已出货")]
        if last_contact_dt and last_contact_dt < ninety_days_ago_dt and not active_orders:
            stale_customers.append({
                "id": cust["id"], "name": cust["name"],
                "last_contact_at": last_contact,
                "days_since_contact": days_since or 90,
            })

        # 2. 高价值未转化：A 级客户但无任何订单
        tier = (extra1.get("tier") or "").strip().upper()
        if tier == "A" and not orders:
            high_value_unconverted.append({
                "id": cust["id"], "name": cust["name"],
                "tier": "A", "country": extra1.get("country", ""),
            })

        # 3. 数据不完整：完整度 < 40%
        # 传入已解析的 extra1/extra2 避免 compute_data_completeness 内重复 json.loads
        score_result = compute_data_completeness(cust, _extra1=extra1, _extra2=extra2)
        if score_result["score"] < 40:
            incomplete_data.append({
                "id": cust["id"], "name": cust["name"],
                "completeness_score": score_result["score"],
                "missing_fields": score_result["missing_fields"],
            })

        # 4. 需跟进：30-90 天内未联系（ninety_days_ago < thirty_days_ago）
        if last_contact_dt and ninety_days_ago_dt <= last_contact_dt < thirty_days_ago_dt:
            need_followup.append({
                "id": cust["id"], "name": cust["name"],
                "last_contact_at": last_contact,
                "days_since_contact": days_since or 30,
            })

    return {
        "summary": {
            "total_customers": len(all_custs),
            "stale_count": len(stale_customers),
            "high_value_unconverted_count": len(high_value_unconverted),
            "incomplete_count": len(incomplete_data),
            "need_followup_count": len(need_followup),
        },
        "stale_customers": stale_customers,
        "high_value_unconverted": high_value_unconverted,
        "incomplete_data": incomplete_data,
        "need_followup": need_followup,
    }


# ── AI 客户简报 ───────────────────────────────────────────────────────────────

def build_briefing(customer_id: int, *, company_id: int) -> str:
    """为指定客户组装 AI 可读的简报上下文。

    简报结构（5 段式）：
      1. 客户身份（名称、国家、等级、职位、买家类型、主营品类）
      2. 联系方式（email、电话、社媒）
      3. 历史互动（跟进备注、最近接触时间）
      4. 关联订单（最近 5 笔，含状态/金额/日期）
      5. 数据完整度提示（低于 60% 时列出缺失字段）

    Returns:
        格式化的 markdown 文本块，供 helpers.build_query() 注入。
    """
    cust = get(customer_id, company_id=company_id)
    if not cust:
        return ""

    extra1 = _json_load(cust.get("extra1", "{}"))
    extra2 = _json_load(cust.get("extra2", "{}"))

    lines = [f"\n## 客户简报：{cust['name']}"]

    # 1. 客户身份
    identity_parts = []
    if extra1.get("country"):
        identity_parts.append(f"国家: {extra1['country']}")
    if extra1.get("tier"):
        identity_parts.append(f"等级: {extra1['tier']} 级")
    if extra2.get("title"):
        identity_parts.append(f"职位: {extra2['title']}")
    if extra1.get("buyer_type"):
        identity_parts.append(f"买家类型: {extra1['buyer_type']}")
    if extra1.get("main_category"):
        identity_parts.append(f"主营品类: {extra1['main_category']}")
    if identity_parts:
        lines.append("**客户身份**：" + "，".join(identity_parts))

    # 2. 联系方式
    contact_parts = []
    contact_name = (cust.get("contact") or "").strip()
    email = (extra2.get("email") or "").strip()
    phone = (extra2.get("phone") or "").strip()
    whatsapp = (extra2.get("whatsapp") or "").strip()
    wechat = (extra2.get("wechat") or "").strip()
    linkedin = (extra1.get("linkedin_url") or "").strip()
    if contact_name:
        contact_parts.append(f"联系人: {contact_name}")
    if email:
        contact_parts.append(f"邮箱: {email}")
    if phone:
        contact_parts.append(f"电话: {phone}")
    if whatsapp:
        contact_parts.append(f"WhatsApp: {whatsapp}")
    if wechat:
        contact_parts.append(f"微信: {wechat}")
    if linkedin:
        contact_parts.append(f"LinkedIn: {linkedin}")
    if contact_parts:
        lines.append("**联系方式**：" + "，".join(contact_parts))

    # 2b. 其他联系人（contacts 表；缺表静默省略，不挡聊天）
    try:
        from trade import contacts as contacts_module

        extras = contacts_module.list_additional(customer_id, company_id=company_id)
        other_bits = []
        for p in extras:
            bit = (p.get("name") or "").strip() or "未命名"
            role = (p.get("title") or p.get("function") or "").strip()
            em = (p.get("email") or "").strip()
            detail = "/".join(x for x in (bit, role, em) if x)
            if detail:
                other_bits.append(detail)
        if other_bits:
            lines.append("**其他联系人**：" + "；".join(other_bits))
    except Exception:
        pass

    # 3. 历史互动
    note = (cust.get("note") or "").strip()
    follow_up = (extra2.get("follow_up_note") or "").strip()
    last_contact = (extra2.get("last_contact_at") or "").strip()
    if note:
        lines.append(f"**备注/跟进记录**：{note}")
    if follow_up:
        lines.append(f"**AI 跟进建议**：{follow_up}")
    if last_contact:
        lines.append(f"**最近联系时间**：{last_contact}")

    # 3b. 客户画像（已确认 + ai_visible；失败静默，不挡聊天）
    try:
        from trade.profile import briefing_profile_section

        section = briefing_profile_section(customer_id, company_id=company_id)
        if section:
            lines.append(section)
    except Exception:
        pass

    # 4. 最近订单（5 笔）
    from trade.order import list_by_customer as _list_orders
    orders = _list_orders(customer_id, company_id=company_id)
    if orders:
        lines.append("\n**关联订单**：")
        for o in orders[:5]:
            parts = [f"  [{o['status']}] {o['product_name']}"]
            if o.get("total_amount"):
                parts.append(f"{o['total_amount']} {o.get('currency', 'USD')}")
            if o.get("created_at"):
                parts.append(f"({o['created_at'][:10]})")
            lines.append(" | ".join(parts))

    # 5. 数据完整度提示
    completeness = compute_data_completeness(cust)
    if completeness["score"] < 60:
        missing = "、".join(completeness["missing_fields"][:5])
        lines.append(f"\n⚠️ 数据完整度仅 {completeness['score']}%，缺少字段：{missing}。"
                      f"如需要可提醒用户补充。")

    return "\n".join(lines) + "\n"


# ── CLI smoke test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    from trade.database import init_db

    init_db()

    # Create
    cust = create("示例贸易公司", "contact@example.com", "测试客户", company_id=1)
    print("Created:", json.dumps(cust, indent=2, ensure_ascii=False))

    # List by company
    all_custs = list_by_company(1)
    print(f"\nCustomers for company 1 ({len(all_custs)}):")
    for c in all_custs:
        print(f"  [{c['id']}] {c['name']}")

    # Clean up
    delete(cust["id"], company_id=1)
    print("\nCleaned up test customer.")
