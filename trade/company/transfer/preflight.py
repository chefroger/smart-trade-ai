"""导入预检：只读分析数据包，列出同名客户冲突（2026-11-20 审计 C2）。

与导入共用 merge_mod.norm_name，保证「预检说冲突」和「导入会合并」口径一致。
本模块绝不写库、不把包解压到磁盘。
"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

from trade.company.transfer import merge as merge_mod
from trade.company.transfer.importer import (
    AmbiguousCompanyError,
    InvalidPackageError,
    _find_targets,
)


def _read_json_member(zf: zipfile.ZipFile, name: str):
    """读 zip 里的 JSON 成员；缺失或损坏返回 None（预检不该因脏包直接崩）。"""
    try:
        raw = zf.read(name)
    except KeyError:
        # 包内没有这个成员：按缺失处理，由调用方用空值兜底
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        # JSON 损坏或非 UTF-8：按缺失处理，交给调用方兜底
        return None


def _as_int(value):
    """包内 id 能转 int 就转，否则原样返回（畸形包不因此崩掉）。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _proposed_name(base: str, taken: set[str]) -> str:
    """在已归一化的名字集合里找一个唯一的「名字 (n)」。"""
    n = 2
    # 逐个后缀试，直到归一化后不与已占用名字冲突
    while True:
        candidate = f"{base} ({n})"
        # 该后缀仍被占用：换下一个数字继续试
        if merge_mod.norm_name(candidate) not in taken:
            return candidate
        n += 1


def analyze_package(zip_path: Path, *, target_company_id: int | None = None,
                    force_new: bool = False) -> dict:
    """只读预检：解析包 → 解析目标公司 → 计算同名客户冲突。不写库。"""
    with zipfile.ZipFile(zip_path) as zf:
        manifest = _read_json_member(zf, "manifest.json") or {}
        source_customers = _read_json_member(zf, "db/customers.json") or []
    # 畸形包（审计 O-5）：manifest 不是 dict、company 是字符串等都不能崩成 500，
    # 按「没有公司信息」继续预检，由后续同名匹配决定能否导入。
    if not isinstance(manifest, dict):
        manifest = {}
    # 包内 customers.json 不是列表：按空处理，与导入的容错一致
    if not isinstance(source_customers, list):
        source_customers = []

    source_company = manifest.get("company")
    if not isinstance(source_company, dict):
        source_company = {}
    source_name = str(source_company.get("name") or "")

    from trade.database import get_connection

    conn = get_connection()
    try:
        # 包比本机 schema 新时拒绝（与 import_company 同一判断，避免预检通过、导入才报错）
        try:
            local_schema = int(
                conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
            )
            package_schema = int(manifest.get("schema_version") or 0)
        except (sqlite3.Error, TypeError, ValueError):
            # 表缺失或版本值畸形：两侧都按 0 处理，不让预检因此崩掉
            package_schema = local_schema = 0
        # 包 schema 更新：明确拒绝，提示先升级 Trade
        if package_schema > local_schema:
            raise InvalidPackageError(
                f"数据包来自更新版本的 Trade（schema {package_schema} > 本机 {local_schema}），"
                "请先更新 Trade 后再导入。"
            )

        matches = _find_targets(conn, source_name)
        target = None
        # 调用方显式指定目标公司：按其 id 解析
        if target_company_id is not None:
            row = conn.execute(
                "SELECT id, name, slug, is_active FROM companies WHERE id = ?",
                (target_company_id,),
            ).fetchone()
            # 指定了目标却不存在：直接报错，不猜
            if row is None:
                raise InvalidPackageError("target_company_id not found")
            target = dict(row)
            # 指定的公司名必须与包内公司名一致
            if merge_mod.norm_name(target["name"]) != merge_mod.norm_name(source_name):
                raise InvalidPackageError("target company name does not match package")
        # 显式要求新建公司：不匹配任何已有公司
        elif force_new:
            target = None
        # 目标机有多个同名公司：交给调用方选择
        elif len(matches) > 1:
            raise AmbiguousCompanyError([
                {"id": row["id"], "name": row["name"], "slug": row["slug"]}
                for row in matches
            ])
        # 恰好一个同名公司：按合并处理
        elif matches:
            target = matches[0]

        # 新建公司：新库里不可能有同名客户，冲突恒为空
        if target is None:
            return {
                "company": {"mode": "create", "target": None, "source_name": source_name},
                "conflicts": [],
                "summary": {
                    "customers_total": len(source_customers),
                    "conflicts": 0,
                    "new_customers": len(source_customers),
                },
            }

        target_id = int(target["id"])
        rows = conn.execute(
            "SELECT id, name FROM customers WHERE company_id = ?", (target_id,)
        ).fetchall()
    finally:
        conn.close()

    by_name: dict[str, list[dict]] = {}
    for row in rows:
        item = {"id": row[0], "name": row[1] or ""}
        by_name.setdefault(merge_mod.norm_name(item["name"]), []).append(item)
    # 目标库已用的名字 + 本次预检已提议的名字，保证后缀不撞车
    taken: set[str] = set(by_name)

    conflicts: list[dict] = []
    for cust in source_customers:
        source_cust_name = cust.get("name") or ""
        # 空名客户不参与冲突（否则会命中所有空名目标），直接按新建处理
        if not source_cust_name.strip():
            continue
        holders = by_name.get(merge_mod.norm_name(source_cust_name)) or []
        # 目标库没有同名客户：不构成冲突
        if not holders:
            continue
        # 名字完全一致（连大小写/空格都相同）：按精确匹配静默合并，不进冲突列表
        # （2026-11-23 审计 P2 残留）。大小写/空格不同仍算冲突，交给用户选。
        if any((h.get("name") or "").strip() == source_cust_name.strip() for h in holders):
            continue
        proposed = _proposed_name(source_cust_name, taken)
        taken.add(merge_mod.norm_name(proposed))
        item = {
            # 包内 id 可能是 JSON 字符串（审计 O-5）：能转数字就转，前端回传的
            # 决定是 int，不归一化会让 "7" 与 7 永远对不上、确认恒 400。
            "source_id": _as_int(cust.get("id")),
            "source_name": source_cust_name,
            "target_id": holders[0]["id"],
            "target_name": holders[0]["name"],
            "reason": "same_name_case_or_space",
            "proposed_new_name": proposed,
        }
        # 目标库历史遗留了两个同名客户：把候选都返回，让用户选
        if len(holders) > 1:
            item["reason"] = "multiple_targets"
            item["candidates"] = [{"id": h["id"], "name": h["name"]} for h in holders]
        conflicts.append(item)

    return {
        "company": {
            "mode": "merge",
            "target": {"id": target_id, "name": target["name"]},
            "source_name": source_name,
        },
        "conflicts": conflicts,
        "summary": {
            "customers_total": len(source_customers),
            "conflicts": len(conflicts),
            "new_customers": len(source_customers) - len(conflicts),
        },
    }
