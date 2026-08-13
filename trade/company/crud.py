"""
Trade AI Assistant — 公司数据层 CRUD。

管理两张表：
  - companies: 公司基本信息（名称、slug、联系方式、激活状态）
  - trade_companies: Trade 业务扩展信息（数据目录、Agent 身份、会话状态）
"""

from __future__ import annotations

import json as _json
import os
import shutil
from datetime import datetime as _dt
from pathlib import Path

from trade.database import get_connection

# ── 模块级常量 ────────────────────────────────────────────────────────────────

# Trade 用户数据目录
# 优先级: TRADE_HOME 环境变量 > Windows %LOCALAPPDATA% > ~/.trade/
_TRADE_HOME_RAW = os.environ.get("TRADE_HOME", "").strip()
if _TRADE_HOME_RAW:
    TRADE_HOME = Path(_TRADE_HOME_RAW)  # 显式设置，直接使用
elif os.name == "nt":
    _local_appdata = os.environ.get(
        "LOCALAPPDATA", str(Path.home() / "AppData" / "Local")
    )
    TRADE_HOME = Path(_local_appdata) / "trade"
else:
    TRADE_HOME = Path.home() / ".trade"  # macOS / Linux 默认路径


# ── 数据库辅助函数 ────────────────────────────────────────────────────────────

def _db_get_one(sql: str, args: tuple = ()) -> tuple | None:
    """执行单行查询并返回结果行（sqlite3.Row），未找到时返回 None。

    每次调用都从连接池获取新连接，用完即关闭，避免长连接泄漏。
    """
    conn = get_connection()
    try:
        row = conn.execute(sql, args).fetchone()
        return row
    finally:
        conn.close()


def _row_to_company(row) -> dict:
    """将 companies 表的数据库行转换为业务字典。

    所有字段一一映射，is_active 转为 Python bool 类型。
    """
    return {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "logo_url": row["logo_url"],
        "website": row["website"],
        "contact_name": row["contact_name"],
        "contact_email": row["contact_email"],
        "address": row["address"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_tc(row) -> dict:
    """将 trade_companies 表的数据库行转换为业务字典。

    is_active 转为 Python bool，其余字段原样返回。
    """
    return {
        "company_id": row["company_id"],
        "data_dir": row["data_dir"],
        "agent_identity_md": row["agent_identity_md"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


# ── companies 表 CRUD ─────────────────────────────────────────────────────────

def list_all(include_inactive: bool = False) -> list[dict]:
    """返回未软删除的公司列表（脱敏版），按名称排序。

    脱敏：仅返回 id/name/slug/is_active，不暴露 contact_email/address 等 PII。
    详情通过 get() 获取完整字段。

    Args:
        include_inactive: True 时包含 is_active=0 的软删除公司
    """
    conn = get_connection()
    try:
        if include_inactive:
            # 包含所有公司（管理员视图）
            sql = "SELECT id, name, slug, is_active FROM companies ORDER BY name"
            rows = conn.execute(sql).fetchall()
        else:
            # 默认仅返回活跃公司（用户视图），软删除的公司不出现
            sql = (
                "SELECT id, name, slug, is_active FROM companies "
                "WHERE is_active = 1 ORDER BY name"
            )
            rows = conn.execute(sql).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "slug": r["slug"],
                "is_active": bool(r["is_active"]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def get(company_id: int) -> dict | None:
    """返回公司完整字典（含所有字段），未找到时返回 None。"""
    row = _db_get_one("SELECT * FROM companies WHERE id = ?", (company_id,))
    return _row_to_company(row) if row else None


def slug_from_id(company_id: int) -> str | None:
    """根据公司 ID 返回 slug（用于 prompt 文件路径解析 / 数据目录查找）。"""
    row = _db_get_one("SELECT slug FROM companies WHERE id = ?", (company_id,))
    return row[0] if row else None


def get_by_slug(slug: str) -> dict | None:
    """根据 slug 返回公司字典，未找到时返回 None。

    用于通过 URL 中的 slug 标识查找公司。
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, name, slug, logo_url, website, contact_name, "
            "contact_email, address, is_active, created_at, updated_at "
            "FROM companies WHERE slug = ?",
            (slug,),
        ).fetchone()
        return _row_to_company(row) if row else None
    finally:
        conn.close()


def create(
    name: str,
    slug: str | None = None,
    logo_url: str = "",
    website: str = "",
    contact_name: str = "",
    contact_email: str = "",
    address: str = "",
    *,
    work_dir_name: str = "",
) -> dict:
    """创建新公司，同时创建 trade_companies 记录 + 桌面工作目录 + 文档库。

    事务保护：任何步骤失败都会回滚数据库并清理已创建的目录。

    Args:
        name: 公司名称（必填）
        slug: URL 标识（省略时从 name 自动生成）
        work_dir_name: 桌面工作目录的自定义名称（为空则用公司名）

    Returns:
        完整公司字典 + work_dir / work_dir_is_new / libraries 扩展字段
    """
    from trade.company.workdir import (
        _ensure_data_dir,
        _register_work_libraries,
        _setup_work_directory,
        _slugify,
        _validate_slug,
    )

    if not name or not name.strip():
        raise ValueError("Company name cannot be empty")

    if not slug:
        slug = _slugify(name)  # 从公司名自动生成 slug
    slug = _validate_slug(slug)  # 校验 slug 合法性（防路径穿越、非法字符）

    data_dir = None
    work_dir = None
    is_new = True  # 标记工作目录是否为新创建（回滚时据此决定是否清理）
    conn = get_connection()

    try:
        # slug 唯一性检查：冲突时自动追加 -N 后缀
        base_slug = slug
        counter = 1
        while True:
            existing = conn.execute(
                "SELECT id FROM companies WHERE slug = ?", (slug,)
            ).fetchone()
            if not existing:
                break
            counter += 1
            slug = f"{base_slug}-{counter}"

        # 1) 创建 ~/.trade/{slug}/ 数据目录
        data_dir = str(_ensure_data_dir(slug, TRADE_HOME))

        # 2) 创建桌面工作目录（含外贸分类子目录）
        work_dir, is_new = _setup_work_directory(
            name, slug, suggested_name=work_dir_name
        )

        # 3) 写入 companies 表
        cursor = conn.execute(
            "INSERT INTO companies (name, slug, logo_url, website, "
            "contact_name, contact_email, address) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, slug, logo_url, website, contact_name, contact_email, address),
        )
        company_id = cursor.lastrowid

        # 4) 写入 trade_companies 表（工作目录路径存入 extra1 JSON）
        _extra1 = _json.dumps({"work_dir": str(work_dir)})
        conn.execute(
            "INSERT INTO trade_companies (company_id, data_dir, extra1) "
            "VALUES (?, ?, ?)",
            (company_id, data_dir, _extra1),
        )
        conn.commit()

        # 5) 注册桌面工作目录下的文档库
        libs = _register_work_libraries(company_id, work_dir)

        result = get(company_id)
        if result:
            result["work_dir"] = str(work_dir)
            result["work_dir_is_new"] = is_new
            result["libraries"] = libs
        return result

    except Exception:
        conn.rollback()  # 数据库回滚，不残留脏数据
        # 清理本事务中创建的文件系统资源（仅清理本次新建的目录）
        import shutil as _shutil

        if is_new and work_dir and work_dir.exists():
            try:
                _shutil.rmtree(str(work_dir))
            except OSError:
                pass  # 目录清理失败不影响原始异常抛出
        if data_dir:
            _data_path = Path(data_dir)
            if _data_path.exists():
                try:
                    _shutil.rmtree(str(_data_path))
                except OSError:
                    pass
        raise  # 重新抛出原始异常
    finally:
        conn.close()


def update(
    company_id: int,
    name: str | None = None,
    logo_url: str | None = None,
    website: str | None = None,
    contact_name: str | None = None,
    contact_email: str | None = None,
    address: str | None = None,
    is_active: bool | None = None,
) -> dict | None:
    """更新公司字段。仅更新传入的非 None 字段（部分更新）。

    返回更新后的公司字典，公司不存在时返回 None。
    """
    conn = get_connection()
    try:
        if not conn.execute(
            "SELECT 1 FROM companies WHERE id = ?", (company_id,)
        ).fetchone():
            return None  # 公司不存在

        # 动态构建 SET 子句，只更新传入的非 None 字段
        fields, vals = [], []
        for fname, fval in [
            ("name", name),
            ("logo_url", logo_url),
            ("website", website),
            ("contact_name", contact_name),
            ("contact_email", contact_email),
            ("address", address),
        ]:
            if fval is not None:
                fields.append(f"{fname} = ?")
                vals.append(fval)

        if is_active is not None:
            fields.append("is_active = ?")
            vals.append(1 if is_active else 0)

        if fields:
            # 仅当有字段需要更新时才执行 SQL
            fields.append("updated_at = datetime('now', 'localtime')")
            vals.append(company_id)
            conn.execute(
                f"UPDATE companies SET {', '.join(fields)} WHERE id = ?", vals
            )
            conn.commit()

        return get(company_id)
    finally:
        conn.close()


def delete(company_id: int) -> bool:
    """软删除公司：设置 is_active=0 + 记录 deleted_at 时间戳。

    数据保留 30 天后由 purge() 执行物理清理。
    返回 True 表示软删除成功，False 表示公司不存在或已删除。
    """
    conn = get_connection()
    try:
        n = conn.execute(
            "UPDATE companies SET is_active = 0, "
            "updated_at = datetime('now','localtime') "
            "WHERE id = ? AND is_active = 1",
            (company_id,),
        ).rowcount
        conn.commit()
        if n > 0:
            # 写入审计日志（用于后续 30 天倒计时清理）
            _write_audit_log(company_id, "soft_delete", "公司已软删除，数据保留 30 天")
        return n > 0
    finally:
        conn.close()


def purge(company_id: int) -> bool:
    """物理删除公司及其所有关联数据 + 清理文件系统数据目录。

    仅管理员调用。不可逆操作。执行前先写入审计日志。
    返回 True 表示删除成功。
    """
    tc = get_trade_company(company_id)
    company = get(company_id)
    slug = company["slug"] if company else None
    data_dir_str = tc["data_dir"] if tc else None

    # 提取桌面工作目录路径（存于 extra1 JSON）
    work_dir_str = ""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT extra1 FROM trade_companies WHERE company_id = ?",
            (company_id,),
        ).fetchone()
        if row and row["extra1"]:
            try:
                work_dir_str = _json.loads(row["extra1"]).get("work_dir", "") or ""
            except (ValueError, TypeError):
                work_dir_str = ""
    finally:
        conn.close()

    # 写入审计日志（不可逆操作前的最终记录）
    _write_audit_log(company_id, "purge", "物理删除公司及所有数据")

    conn = get_connection()
    try:
        n = conn.execute(
            "DELETE FROM companies WHERE id = ?", (company_id,)
        ).rowcount
        conn.commit()
        if n > 0:
            # 清理文件系统：trade_companies.data_dir（仅当目录在 TRADE_HOME 下）
            if data_dir_str:
                data_path = Path(data_dir_str)
                if data_path.exists():
                    try:
                        # 安全校验：确保 data_dir 在 TRADE_HOME 下，防止误删系统目录
                        data_path.resolve().relative_to(TRADE_HOME.resolve())
                    except ValueError:
                        pass  # 不在 TRADE_HOME 下，跳过清理（不删除外部目录）
                    else:
                        try:
                            shutil.rmtree(data_path)
                        except OSError:
                            pass  # 目录清理失败不抛异常
            # 清理文件系统：~/.trade/{slug}/
            if slug:
                slug_dir = TRADE_HOME / slug
                if slug_dir.exists():
                    try:
                        shutil.rmtree(slug_dir)
                    except OSError:
                        pass
            # 清理桌面工作目录（仅当位于桌面目录下，防止误删用户数据）
            if work_dir_str:
                work_path = Path(work_dir_str)
                if work_path.exists():
                    try:
                        from trade.company.workdir import _get_desktop_path
                        desktop = _get_desktop_path().resolve()
                        work_path.resolve().relative_to(desktop)
                    except ValueError:
                        pass  # 不在桌面下，跳过清理
                    else:
                        try:
                            shutil.rmtree(work_path)
                        except OSError:
                            pass
        return n > 0
    finally:
        conn.close()


# ── trade_companies 表 CRUD ────────────────────────────────────────────────────

def get_trade_company(company_id: int) -> dict | None:
    """返回公司对应的 trade_companies 记录，未找到时返回 None。

    trade_companies 表存储 Trade 业务扩展数据：data_dir、agent_identity_md 等。
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT company_id, data_dir, agent_identity_md, is_active, created_at "
            "FROM trade_companies WHERE company_id = ?",
            (company_id,),
        ).fetchone()
        return _row_to_tc(row) if row else None
    finally:
        conn.close()


def update_trade_company(
    company_id: int,
    data_dir: str | None = None,
    agent_identity_md: str | None = None,
    is_active: bool | None = None,
    extra1: str | None = None,
) -> dict | None:
    """更新 trade_companies 字段（部分更新）。

    仅更新传入的非 None 字段。extra1 字段存储 JSON（工作目录路径等元数据）。
    """
    conn = get_connection()
    try:
        if not conn.execute(
            "SELECT 1 FROM trade_companies WHERE company_id = ?", (company_id,)
        ).fetchone():
            return None  # trade_companies 记录不存在

        fields, vals = [], []
        if data_dir is not None:
            fields.append("data_dir = ?")
            vals.append(data_dir)
        if agent_identity_md is not None:
            fields.append("agent_identity_md = ?")
            vals.append(agent_identity_md)
        if is_active is not None:
            fields.append("is_active = ?")
            vals.append(1 if is_active else 0)
        if extra1 is not None:
            fields.append("extra1 = ?")
            vals.append(extra1)

        if fields:
            vals.append(company_id)
            conn.execute(
                f"UPDATE trade_companies SET {', '.join(fields)} "
                "WHERE company_id = ?",
                vals,
            )
            conn.commit()

        return get_trade_company(company_id)
    finally:
        conn.close()


def get_agent_identity(company_id: int) -> str:
    """返回公司的 Agent 身份标识文本。

    优先级链（高到低）：
      1. trade_companies.agent_identity_md 数据库字段（在线编辑 / 首次引导写入）
      2. ~/.trade/{slug}/agent-identity.md 磁盘文件（用户手动编辑）
      3. '' 空字符串 → 回退到通用 TRADE_SYSTEM_PROMPT

    Agent 身份文本会被注入到系统提示词中，让 AI 知道自己在为哪家公司服务。
    """
    tc = get_trade_company(company_id)
    if not tc:
        return ""

    # 数据库内联覆盖优先（前端编辑后保存到这里）
    if tc.get("agent_identity_md"):
        return tc["agent_identity_md"]

    # 其次检查磁盘文件（用户可能手动编辑了文件）
    data_dir = Path(tc["data_dir"]) if tc.get("data_dir") else None
    if data_dir and data_dir.exists():
        identity_file = data_dir / "agent-identity.md"
        if identity_file.exists():
            return identity_file.read_text(encoding="utf-8")

    return ""


# ── 审计日志 ──────────────────────────────────────────────────────────────────

def _audit_dir() -> Path:
    """审计日志目录: ~/.trade/audit/。

    按天分文件: YYYY-MM-DD.jsonl，每行一条 JSON 记录。
    """
    d = TRADE_HOME / "audit"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_audit_log(company_id: int, action: str, detail: str) -> None:
    """追加一行 JSON 审计日志到当天的审计文件中。

    审计日志记录所有敏感操作（创建、软删除、物理删除），用于追溯。

    Args:
        company_id: 操作的数据库公司 ID
        action: 操作类型（如 "soft_delete"、"purge"）
        detail: 操作详情的自然语言描述
    """
    log_file = _audit_dir() / f"{_dt.now().strftime('%Y-%m-%d')}.jsonl"
    entry = _json.dumps(
        {
            "ts": _dt.now().isoformat(),
            "company_id": company_id,
            "action": action,
            "detail": detail,
        },
        ensure_ascii=False,
    )
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        import logging
        logging.warning("审计日志写入失败: %s", log_file)
