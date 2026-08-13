"""
Trade AI Assistant — 客户管理模块。

B2B 客户 CRUD，支持可选的文档库关联。
所有操作均受 company_id 作用域限制，实现多租户隔离。
"""

import json

from trade.database import get_connection


def create(
    name: str,
    contact: str = "",
    note: str = "",
    *,
    company_id: int,
    country: str = "",
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
    _skip_dedup: bool = False,
) -> dict:
    """创建一条归属于指定公司的客户记录。返回新行的字典表示。

    _skip_dedup 内部参数：bulk_save() 等调用方已在外部做过去重时传入 True，
    跳过本函数内的 O(n) 软去重扫描，避免 N+1 性能退化。
    """
    extra1 = json.dumps({
        "country": country,
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
    }, ensure_ascii=False)

    conn = get_connection()
    try:
        # 软去重检查：在同一连接内用 SQL json_extract 做原子查询，
        # 消除之前 list_by_company() 跨连接的 TOCTOU 竞态窗口
        _warn = None
        if not _skip_dedup and (email or company_website):
            _email_check = (email or "").strip().lower()
            _site_check = (company_website or "").strip().lower()
            if _email_check:
                dup = conn.execute(
                    "SELECT 1 FROM customers WHERE company_id = ? "
                    "AND LOWER(COALESCE(json_extract(extra2, '$.email'), '')) = ? "
                    "LIMIT 1",
                    (company_id, _email_check),
                ).fetchone()
                if dup:
                    _warn = "email_already_exists"
            if not _warn and _site_check:
                dup = conn.execute(
                    "SELECT 1 FROM customers WHERE company_id = ? "
                    "AND LOWER(COALESCE(json_extract(extra1, '$.company_website'), '')) = ? "
                    "LIMIT 1",
                    (company_id, _site_check),
                ).fetchone()
                if dup:
                    _warn = "website_already_exists"

        cur = conn.execute(
            "INSERT INTO customers (company_id, name, contact, note, extra1, extra2) VALUES (?, ?, ?, ?, ?, ?)",
            (company_id, name, contact, note, extra1, extra2),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM customers WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        result = _row_to_dict(row)
        if _warn:
            result["duplicate_warning"] = _warn
        return result
    finally:
        conn.close()


def list_by_company(company_id: int) -> list[dict]:
    """返回指定公司的所有客户，按最新创建排在前面。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM customers WHERE company_id = ? ORDER BY id DESC",
            (company_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


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


def update(
    customer_id: int,
    *,
    company_id: int,
    **kwargs,
) -> dict | None:
    """更新客户字段（单事务，部分失败统一回滚）。

    基础字段: name, contact, note
    extra1 字段: country, tier, linkedin_url, company_website, social_media, buyer_type, main_category, match_score
    extra2 字段: title, email, backup_email, phone, whatsapp, wechat, source, last_contact_at, follow_up_note
    """
    extra1_keys = {"country", "tier", "linkedin_url", "company_website", "social_media", "buyer_type", "main_category", "match_score"}
    extra2_keys = {"title", "email", "backup_email", "phone", "whatsapp", "wechat", "source", "last_contact_at", "follow_up_note"}
    basic_allowed = {"name", "contact", "note"}

    extra1_updates = {k: v for k, v in kwargs.items() if k in extra1_keys and v is not None}
    extra2_updates = {k: v for k, v in kwargs.items() if k in extra2_keys and v is not None}
    basic_updates = {k: v for k, v in kwargs.items() if k in basic_allowed and v is not None}

    if not (extra1_updates or extra2_updates or basic_updates):
        return get(customer_id, company_id=company_id)

    conn = get_connection()
    try:
        conn.execute("BEGIN")

        # 读取当前 JSON 用于合并（company_id 贯穿所有写操作）
        row = conn.execute(
            "SELECT extra1, extra2 FROM customers WHERE id = ? AND company_id = ?",
            (customer_id, company_id),
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        current_extra1 = json.loads(row["extra1"]) if row["extra1"] else {}
        current_extra2 = json.loads(row["extra2"]) if row["extra2"] else {}

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

        # 基础字段
        if basic_updates:
            set_clause = ", ".join(f"{k} = ?" for k in basic_updates)
            values = list(basic_updates.values()) + [customer_id, company_id]
            sql = f"UPDATE customers SET {set_clause}, updated_at = datetime('now','localtime') WHERE id = ? AND company_id = ?"
            n = conn.execute(sql, values).rowcount
            if n == 0:
                conn.rollback()
                return None

        conn.commit()
        return get(customer_id, company_id=company_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete(customer_id: int, *, company_id: int) -> bool:
    """按公司作用域删除客户。如果删除了行则返回 True。"""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM customers WHERE id = ? AND company_id = ?",
            (customer_id, company_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


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
    result = {
        "id": row["id"],
        "company_id": row["company_id"],
        "name": row["name"],
        "contact": row["contact"],
        "note": row["note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    # 扩展字段（JSON 列）：前端依赖 extra1/extra2 展示额外信息
    try:
        result["extra1"] = row["extra1"] or "{}"
    except Exception:
        result["extra1"] = "{}"
    try:
        result["extra2"] = row["extra2"] or "{}"
    except Exception:
        result["extra2"] = "{}"
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
            name (必填), contact, note, country, tier, linkedin_url,
            company_website, social_media (dict), email, backup_email,
            phone, whatsapp, wechat, source, buyer_type, follow_up_note,
            main_category, match_score
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
        ws = (ex1.get("company_website", "") or "").strip().lower()
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
        # website-based 去重
        cust_website = (cust.get("company_website") or "").strip().lower()
        if cust_website and cust_website in existing_websites:
            skipped += 1
            continue

        result = create(
            name=name,
            contact=cust.get("contact", ""),
            note=cust.get("note", ""),
            company_id=company_id,
            country=cust.get("country", ""),
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
    import re as _re

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
        site = (extra1.get("company_website", "") or "").strip().lower()
        if site:
            site = _re.sub(r'^https?://(www\.)?', '', site).rstrip('/')
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

        last_contact = (extra2.get("last_contact_at") or cust.get("updated_at") or "").strip()

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
