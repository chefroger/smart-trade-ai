"""单公司导入：校验 ZIP、同名合并、ID/路径重映射、文件与记忆落盘。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from trade.company.transfer import (
    MAX_ENTRIES,
    MAX_UNCOMPRESSED_BYTES,
    AmbiguousCompanyError,
    InvalidPackageError,
    TransferError,
)
from trade.company.transfer import merge as merge_mod
from trade.company.transfer.manifest import load_manifest, verify_checksums
from trade.company.transfer.paths import build_mapper, ensure_within
from trade.company.transfer.replay import replay_hindsight_async


def _safe_extract(zip_path: Path, dest: Path) -> dict:
    """手动解压 + 安全校验（禁止 extractall）。返回 manifest。"""
    dest.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    total = 0          # ZIP 头声明的大小（提前拒绝明显超限的包）
    written_total = 0  # 实际写出的字节（头可以被篡改，最终以真实为准）
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise InvalidPackageError("too many entries")
        for info in infos:
            # Windows 工具生成的 ZIP 可能用反斜杠：归一成正斜杠后走同一套校验，
            # 而不是直接拒绝（否则「能生成却导不回来」）。
            name = info.filename.replace("\\", "/")
            if not name or "\x00" in name:
                raise InvalidPackageError(f"unsafe path: {info.filename!r}")
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise InvalidPackageError(f"unsafe path: {name!r}")
            if name in seen:
                raise InvalidPackageError(f"duplicate entry: {name}")
            seen.add(name)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise InvalidPackageError(f"symlink entry: {name}")
            if info.flag_bits & 0x1:
                raise InvalidPackageError("encrypted entries are not supported")
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise InvalidPackageError("package expands beyond limit")
            if info.compress_size and info.file_size > 50 * 1024 * 1024:
                ratio = info.file_size / max(info.compress_size, 1)
                if ratio > 200:
                    raise InvalidPackageError("suspicious compression ratio")
            target = dest / pure.as_posix()
            if not ensure_within(dest, target):
                raise InvalidPackageError(f"path escapes destination: {name}")
            if name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    written_total += len(chunk)
                    # 按实际写出的字节限额：ZIP 头声明的 file_size 不可信
                    if written_total > MAX_UNCOMPRESSED_BYTES:
                        raise InvalidPackageError("package expands beyond limit")
                    out.write(chunk)
    manifest = load_manifest(dest)
    verify_checksums(dest)
    return manifest


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    cursor = conn.execute(sql, params)
    columns = [item[0] for item in cursor.description or []]
    return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _without_id(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "id"}


def _inquiry_signature(row: dict) -> tuple:
    """询盘去重键：客户 + 标题 + 阶段 + 来源 + 创建时间（2026-11-20 审计 C1）。

    customer_id 必须是**重映射后**的值。created_at 由源包原样保留，重复导入
    同一份包时稳定。代价：同一秒内内容完全相同的两条询盘会被合并
    （与订单去重同一思路）。
    """
    return (
        row.get("customer_id"),
        (row.get("title") or "").strip(),
        (row.get("stage") or "").strip(),
        (row.get("source") or "").strip(),
        row.get("created_at"),
    )


def _visit_plan_signature(row: dict) -> tuple:
    """验厂计划去重键：客户 + 日期 + 标题 + 创建时间（payload 不参与）。

    二次导入同一份包会翻倍（2026-11-20 审计 C1）；payload 可能被导出清洗过，
    不放进键里。
    """
    return (
        row.get("customer_id"),
        row.get("visit_date"),
        (row.get("title") or "").strip(),
        row.get("created_at"),
    )


def _num_or_none(value) -> float | None:
    """把价格归一化为 float 或 None，避免 10 与 10.0 在去重键里不相等。"""
    # 空值返回 None
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _supplier_quote_signature(row: dict) -> tuple:
    """供应商报价去重键：(supplier_id 映射后, product_name, spec_model, quoted_at, price_excl_tax, price_incl_tax)。"""
    return (
        row.get("supplier_id"),
        (row.get("product_name") or "").strip(),
        (row.get("spec_model") or "").strip(),
        (row.get("quoted_at") or "").strip(),
        _num_or_none(row.get("price_excl_tax")),
        _num_or_none(row.get("price_incl_tax")),
    )


def _rfq_signature(row: dict) -> tuple:
    """采购询价单去重键：(customer_id 映射后, inquiry_id 映射后, product_name, spec_model, created_at)。"""
    return (
        row.get("customer_id"),
        row.get("inquiry_id"),
        (row.get("product_name") or "").strip(),
        (row.get("spec_model") or "").strip(),
        row.get("created_at"),
    )


_SUPPLIER_MERGE_TEXT_FIELDS = (
    "short_name", "supplier_type", "main_products", "province", "city",
    "address", "payment_terms", "source", "note",
)
_SUPPLIER_MERGE_NUM_FIELDS = ("rating", "tax_point", "lead_time_days")
_SUPPLIER_MERGE_JSON_FIELDS = ("extra1", "extra2", "extra3")


def _fill_empty_supplier_fields(conn: sqlite3.Connection, supplier_id: int, source: dict) -> None:
    """合并同名供应商：目标为空时用源值补齐，已有非空值不动。"""
    row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    # 目标行不存在时直接返回
    if row is None:
        return
    target = dict(row)
    changes: dict = {}
    for field in _SUPPLIER_MERGE_TEXT_FIELDS:
        # 目标为空串且源非空时补齐
        if not str(target.get(field) or "").strip() and str(source.get(field) or "").strip():
            changes[field] = source[field]
    for field in _SUPPLIER_MERGE_NUM_FIELDS:
        # 目标为 None 且源有值时补齐
        if target.get(field) is None and source.get(field) is not None:
            changes[field] = source[field]
    # can_issue_vat：目标为 2（待确认）且源为 0/1 时补齐
    if target.get("can_issue_vat") in (None, 2) and source.get("can_issue_vat") in (0, 1):
        changes["can_issue_vat"] = source["can_issue_vat"]
    for field in _SUPPLIER_MERGE_JSON_FIELDS:
        merged = _merge_json_blanks(target.get(field), source.get(field))
        if merged is not None:
            changes[field] = merged
    # 没有任何空缺字段可补则不写库
    if not changes:
        return
    cols = ", ".join(f"{k} = ?" for k in changes)
    conn.execute(
        f"UPDATE suppliers SET {cols} WHERE id = ?",
        (*changes.values(), supplier_id),
    )


def _insert(conn: sqlite3.Connection, table: str, row: dict,
            *, or_ignore: bool = False) -> int | None:
    valid = set(_columns(conn, table))
    keys = [key for key in row if key in valid]
    if not keys:
        return None
    placeholders = ", ".join("?" for _ in keys)
    verb = "INSERT OR IGNORE" if or_ignore else "INSERT"
    sql = f"{verb} INTO {table} ({', '.join(keys)}) VALUES ({placeholders})"
    cursor = conn.execute(sql, tuple(row[key] for key in keys))
    return cursor.lastrowid


def _load_table(root: Path, name: str) -> list[dict]:
    path = root / "db" / f"{name}.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """目标库是否已有指定表。"""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _contacts_table_exists(conn: sqlite3.Connection) -> bool:
    """目标库是否已有 contacts 表。"""
    return _table_exists(conn, "contacts")


def _find_targets(conn: sqlite3.Connection, name: str) -> list[dict]:
    target = merge_mod.norm_name(name)
    rows = _rows(conn, "SELECT id, name, slug, is_active FROM companies")
    return [row for row in rows if merge_mod.norm_name(row.get("name")) == target]


# 合并同名客户时允许「目标为空则用源值填」的文本字段
_MERGE_TEXT_FIELDS = ("contact", "note")
# 同理按 key 合并的 JSON 字段（extra3 是用户标签，不合并）
_MERGE_JSON_FIELDS = ("extra1", "extra2")


def _merge_json_blanks(target_raw, source_raw) -> str | None:
    """按 key 合并 JSON：目标缺 key 或值为空时用源值；没有任何变化返回 None。"""
    try:
        target = json.loads(target_raw) if target_raw else {}
        source = json.loads(source_raw) if source_raw else {}
    except (TypeError, ValueError):
        # 任一侧不是合法 JSON：不动，避免把用户数据改成意外结构
        return None
    # 非 dict 的畸形内容不动，避免把用户数据改成意外结构
    if not isinstance(target, dict) or not isinstance(source, dict):
        return None
    changed = False
    for key, value in source.items():
        # 目标已有非空值：保留目标
        if target.get(key) not in (None, "", [], {}):
            continue
        # 源值也是空：补了也没意义
        if value in (None, "", [], {}):
            continue
        target[key] = value
        changed = True
    return json.dumps(target, ensure_ascii=False) if changed else None


def _fill_empty_customer_fields(conn: sqlite3.Connection, customer_id: int,
                                source: dict) -> None:
    """合并同名客户：目标为空时用源值填充，非空一律不动（2026-11-20 审计 C2）。

    明确不碰 stage / stage_override / is_starred / next_follow_up_date ——
    这些是用户在目标库里的当前状态，不该被导入覆盖。
    """
    row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    # 目标行消失（并发删除）：不填，直接返回
    if row is None:
        return
    target = dict(row)
    changes: dict[str, str] = {}
    for field in _MERGE_TEXT_FIELDS:
        # 目标该字段为空、源值非空：记下要补的值
        if not str(target.get(field) or "").strip() and str(source.get(field) or "").strip():
            changes[field] = source[field]
    for field in _MERGE_JSON_FIELDS:
        merged = _merge_json_blanks(target.get(field), source.get(field))
        # 确实补进了内容：记为一次变更
        if merged is not None:
            changes[field] = merged
    # 没有任何空字段可补：不写库
    if not changes:
        return
    cols = ", ".join(f"{k} = ?" for k in changes)
    conn.execute(
        f"UPDATE customers SET {cols} WHERE id = ?",
        (*changes.values(), customer_id),
    )


def _unique_customer_name(base_name: str, existing_by_name: dict) -> str:
    """给「新建」的客户算一个不与现有同名客户冲突的名字。"""
    base = (base_name or "").strip() or "未命名客户"
    n = 2
    # 逐个后缀试，直到归一化后不与现有名字冲突
    while True:
        candidate = f"{base} ({n})"
        # 该后缀仍被占用：换下一个数字继续试
        if merge_mod.norm_name(candidate) not in existing_by_name:
            return candidate
        n += 1


def _target_context(conn: sqlite3.Connection, company_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM trade_companies WHERE company_id = ?", (company_id,)
    ).fetchone()
    if row is None:
        raise InvalidPackageError(f"trade_companies row missing for {company_id}")
    columns = [item[1] for item in conn.execute("PRAGMA table_info(trade_companies)")]
    tc = dict(zip(columns, row, strict=False))
    try:
        extra = json.loads(tc.get("extra1") or "{}")
    except (TypeError, ValueError):
        extra = {}
    return {"row": tc, "extra": extra, "work_dir": extra.get("work_dir") or ""}


def _safe_slug_hint(source_slug: str | None, name: str) -> str | None:
    value = (source_slug or "").strip()
    if value:
        try:
            from trade.company.workdir import _validate_slug

            return _validate_slug(value)
        except ValueError:
            pass
    # 中文名无法自动生成 slug 时，用一个稳定的 ASCII 前缀
    return "imported-company-" + datetime.now().strftime("%Y%m%d%H%M%S")


def _same_file(left: Path, right: Path) -> bool:
    """按块比较两个文件，避免把大文件整读进内存。"""
    if left.stat().st_size != right.stat().st_size:
        return False
    with open(left, "rb") as lf, open(right, "rb") as rf:
        while True:
            a = lf.read(1 << 20)
            b = rf.read(1 << 20)
            if a != b:
                return False
            if not a:
                return True


def _merge_copy(src: Path, dst: Path, conflict_root: Path, rel: str,
                *, overwrite: bool) -> str:
    """复制一个文件；返回 copied/skipped/conflict。"""
    if not src.is_file():
        return "skipped"
    if dst.is_file():
        if src.stat().st_size == 0:
            return "skipped"
        if dst.stat().st_size and _same_file(src, dst):
            return "skipped"
        if overwrite or dst.stat().st_size == 0:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return "copied"
        conflict = conflict_root / rel
        conflict.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, conflict)
        return "conflict"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return "copied"


def import_company(zip_path: Path, *, target_company_id: int | None = None,
                   force_new: bool = False,
                   customer_decisions: dict[int | str, str] | None = None) -> dict:
    """导入一个公司包，返回报告。异常时抛 TransferError / ValueError。

    customer_decisions：{源客户 id: "merge" | "create"}。None 时保持历史行为
    （同名客户静默合并）；调用方传入时必须覆盖所有冲突客户（API 层负责校验）。
    id 可能来自 JSON（字符串）也可能来自 API 模型（int），查找时统一按字符串比。
    """
    from trade.company import crud as company_crud
    from trade.database import _get_db_path, get_connection
    from trade.post_install.backup import snapshot_db

    staging = Path(tempfile.mkdtemp(prefix="trade-company-import-"))
    conn = None
    created_company_id = None
    created_data_dir = None
    created_data_dir_is_new = False
    created_work_dir = None
    work_dir_is_new = False
    backup_path = None
    committed = False  # 合并模式的 DB 提交发生在文件拷贝之前（见下方 except）
    report: dict = {
        "mode": None,
        "source": {},
        "target": {},
        "tables": {},
        "files": {"copied": 0, "skipped": 0, "conflicts": 0, "warnings": []},
        "identity": "kept",
        "memory": {},
        "hindsight": "skipped",
        "vectors": "skipped",
        "warnings": [],
        "backup": None,
    }

    try:
        manifest = _safe_extract(Path(zip_path), staging)
        source_company = manifest.get("company") or {}
        source_name = source_company.get("name") or ""
        source_slug = source_company.get("slug") or ""
        report["source"] = {
            "id": source_company.get("id"),
            "name": source_name,
            "slug": source_slug,
        }

        conn = get_connection()
        # 包比本机 schema 新时拒绝：导入端会按本机列过滤，静默丢掉新字段比
        # 明确要求先升级更糟（manifest 里记录的就是导出机的 schema 版本）。
        try:
            local_schema = int(
                conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
            )
            package_schema = int(manifest.get("schema_version") or 0)
        except (sqlite3.Error, TypeError, ValueError):
            package_schema = local_schema = 0
        if package_schema > local_schema:
            raise InvalidPackageError(
                f"数据包来自更新版本的 Trade（schema {package_schema} > 本机 {local_schema}），"
                "请先更新 Trade 后再导入。"
            )

        matches = _find_targets(conn, source_name)
        if target_company_id is not None:
            target = conn.execute(
                "SELECT id, name, slug, is_active FROM companies WHERE id = ?",
                (target_company_id,),
            ).fetchone()
            if target is None:
                raise InvalidPackageError("target_company_id not found")
            target = dict(zip(["id", "name", "slug", "is_active"], target, strict=False))
            if merge_mod.norm_name(target["name"]) != merge_mod.norm_name(source_name):
                raise InvalidPackageError("target company name does not match package")
            matches = [target]
        elif force_new:
            matches = []
        elif len(matches) > 1:
            raise AmbiguousCompanyError([
                {"id": row["id"], "name": row["name"], "slug": row["slug"]}
                for row in matches
            ])

        if matches:
            target = matches[0]
            target_id = int(target["id"])
            report["mode"] = "merged"
            if not target.get("is_active"):
                company_crud.update(target_id, is_active=True)
            db_path = _get_db_path()
            backup_dir = company_crud.TRADE_HOME / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / (
                "trade-before-import-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".db"
            )
            snapshot_db(db_path, backup_path)
            report["backup"] = str(backup_path)
        else:
            # 记录创建前的数据根目录：slug 目录可能是上次删除公司后残留的
            # （DB 没记录但磁盘目录还在），创建会复用它；失败清理时绝不能
            # 把这个用户目录连同里面残留的文件一起 rmtree。
            trade_home = Path(company_crud.TRADE_HOME)
            try:
                preexisting_roots = {
                    path.resolve() for path in trade_home.iterdir() if path.is_dir()
                }
            except OSError:
                preexisting_roots = set()
            created = company_crud.create(
                name=source_name,
                slug=_safe_slug_hint(source_slug, source_name),
                logo_url=source_company.get("logo_url") or "",
                website=source_company.get("website") or "",
                contact_name=source_company.get("contact_name") or "",
                contact_email=source_company.get("contact_email") or "",
                address=source_company.get("address") or "",
            )
            target_id = int(created["id"])
            created_company_id = target_id
            created_row = conn.execute(
                "SELECT data_dir FROM trade_companies WHERE company_id = ?", (target_id,)
            ).fetchone()
            created_data_dir = created_row[0] if created_row else None
            created_data_dir_is_new = bool(
                created_data_dir
                and Path(created_data_dir).resolve() not in preexisting_roots
            )
            created_work_dir = created.get("work_dir")
            work_dir_is_new = bool(created.get("work_dir_is_new"))
            report["mode"] = "created"

        target = company_crud.get(target_id) or {}
        ctx = _target_context(conn, target_id)
        raw_data_dir = (ctx["row"].get("data_dir") or "").strip()
        # 必须绝对路径：空串/"." 会让 Path(".") 通过 is_dir()，文件被写进当前工作目录；
        # 还必须在 TRADE_HOME 下，避免脏数据把文件写到任意位置。
        home = Path(company_crud.TRADE_HOME).resolve()
        target_data_dir = Path(raw_data_dir) if raw_data_dir else Path()
        if (not raw_data_dir or not target_data_dir.is_absolute()
                or target_data_dir.resolve() == home
                or not ensure_within(home, target_data_dir.resolve())):
            raise InvalidPackageError(f"target data_dir is invalid: {raw_data_dir!r}")
        if not target_data_dir.is_dir():
            raise InvalidPackageError(f"target data_dir missing: {target_data_dir}")
        raw_work_dir = (ctx["work_dir"] or "").strip()
        target_work_dir = (
            Path(raw_work_dir)
            if raw_work_dir and Path(raw_work_dir).is_absolute()
            else None
        )
        if target_work_dir is None or not target_work_dir.is_dir():
            from trade.company.workdir import _setup_work_directory

            target_work_dir, _ = _setup_work_directory(target.get("name") or source_name,
                                                      target.get("slug") or "")
        report["target"] = {
            "id": target_id,
            "name": target.get("name"),
            "slug": target.get("slug"),
        }

        # 资料库：按名称复用目标库；没有则在工作目录下新建
        from trade import library as library_module

        target_libs = _rows(conn, "SELECT * FROM libraries WHERE company_id = ?", (target_id,))
        lib_by_name = {merge_mod.norm_name(row.get("name")): row for row in target_libs}
        lib_map: dict[str, Path] = {}
        lib_id_map: dict[int, int] = {}
        lib_name_by_id: dict[int, str] = {}
        for lib_row in target_libs:
            lib_name_by_id[lib_row["id"]] = lib_row.get("name") or ""
        source_libs = manifest.get("paths", {}).get("libraries") or []
        libs_inserted = libs_skipped = 0
        for source_lib in source_libs:
            name = source_lib.get("name") or ""
            key = merge_mod.norm_name(name)
            existing = lib_by_name.get(key)
            if existing:
                lib_map[source_lib["export_id"]] = Path(existing["root_path"])
                if source_lib.get("source_id") is not None:
                    lib_id_map[source_lib["source_id"]] = existing["id"]
                libs_skipped += 1
                continue
            safe_name = "".join(ch for ch in name if ch not in '/\\:*?"<>|').strip() or "library"
            root = target_work_dir / safe_name
            root.mkdir(parents=True, exist_ok=True)
            # 用导入自身的事务插入，而不是 library_module.create（它独立连接并立即
            # commit）：否则文件拷贝失败时 rollback 只回滚主事务，库记录会残留。
            root_path = library_module._validate_root_path(str(root))
            new_lib_id = _insert(conn, "libraries", {
                "company_id": target_id,
                "name": safe_name,
                "root_path": root_path,
                "description": source_lib.get("description") or "",
            })
            created_lib = {
                "id": new_lib_id,
                "name": safe_name,
                "root_path": root_path,
                "description": source_lib.get("description") or "",
            }
            lib_map[source_lib["export_id"]] = root
            lib_by_name[key] = created_lib
            lib_name_by_id[created_lib["id"]] = safe_name
            if source_lib.get("source_id") is not None:
                lib_id_map[source_lib["source_id"]] = created_lib["id"]
            target_libs.append(created_lib)
            libs_inserted += 1

        # 导出时因桌面目录超限被跳过的资料库：这里补一条可操作的提示，
        # 告诉用户文件要手动拷到哪个目标目录（否则只会看到一个空库）
        for source_lib in source_libs:
            if source_lib.get("files_included") is not False:
                continue
            target_root = lib_map.get(source_lib.get("export_id"))
            if target_root is not None:
                report["warnings"].append(
                    f"资料库「{source_lib.get('name') or ''}」的文件未包含在包中，"
                    f"请把源桌面目录里的同名库手动拷贝到：{target_root}"
                )

        target_lib_roots = {row.get("name") or "": str(row["root_path"]) for row in target_libs}
        for source_lib in source_libs:
            if source_lib.get("export_id") in lib_map:
                target_lib_roots[source_lib.get("name") or ""] = str(
                    lib_map[source_lib["export_id"]]
                )
        mapper = build_mapper(
            manifest.get("paths") or {},
            str(target_data_dir),
            str(target_work_dir),
            target_lib_roots,
        )

        source_tables = {
            name: _load_table(staging, name)
            for name in (
                "trade_company", "libraries", "customers", "customer_libraries",
                "conversations", "orders", "order_items", "order_libraries",
                "order_events",
                "usage_ledger", "doc_extractions", "contacts",
                "customer_facts", "customer_gifts", "inquiries", "visit_plans",
                "suppliers", "supplier_contacts", "supplier_products", "supplier_quotes",
                "rfqs", "rfq_responses",
                "purchase_orders", "consolidations", "consolidation_items",
            )
        }
        source_tc = source_tables["trade_company"][0] if source_tables["trade_company"] else {}
        source_identity = source_tc.get("agent_identity_md") or ""

        # 客户
        target_customers = _rows(conn, "SELECT * FROM customers WHERE company_id = ?", (target_id,))
        cust_by_name = {merge_mod.norm_name(row.get("name")): row for row in target_customers}
        customer_map: dict[int, int] = {}
        customer_names: dict[int, str] = {row["id"]: row.get("name") or "" for row in target_customers}
        customer_inserted = customer_skipped = 0
        # 统一成字符串键（审计 O-5）：包内 id 可能是 "7"，API 决定是 7，
        # 直接 dict.get 会让 create 决定被静默忽略、退回 merge。
        decisions = {str(k): v for k, v in (customer_decisions or {}).items()}
        for row in source_tables["customers"]:
            key = merge_mod.norm_name(row.get("name"))
            existing = cust_by_name.get(key)
            decision = decisions.get(str(row["id"]))

            # 合并：用户选了 merge，或没提供决定（历史行为）
            if existing and decision != "create":
                customer_map[row["id"]] = existing["id"]
                customer_skipped += 1
                _fill_empty_customer_fields(conn, existing["id"], row)
                continue

            new_row = _without_id(dict(row))
            new_row["company_id"] = target_id
            # 新建：用户明确要求，或在目标库没有同名客户
            if existing and decision == "create":
                # 同名但不同公司：加唯一后缀，避免下次导入又冲突
                new_row["name"] = _unique_customer_name(row.get("name") or "", cust_by_name)
            new_id = _insert(conn, "customers", new_row)
            customer_map[row["id"]] = new_id
            # 按**新名字**登记：新建加了后缀时 key 会变，否则同包后续同名客户会匹配错
            cust_by_name[merge_mod.norm_name(new_row["name"])] = {
                "id": new_id, "name": new_row["name"],
            }
            customer_names[new_id] = new_row["name"] or ""
            customer_inserted += 1
        report["tables"]["customers"] = {
            "inserted": customer_inserted, "skipped": customer_skipped,
        }
        report["tables"]["libraries"] = {
            "inserted": libs_inserted, "skipped": libs_skipped,
        }

        # 客户 ↔ 资料库关联
        link_added = link_skipped = 0
        for link in source_tables["customer_libraries"]:
            customer_id = customer_map.get(link.get("customer_id"))
            library_id = lib_id_map.get(link.get("library_id"))
            # 映射不到客户或库：计 skipped，不再静默丢掉
            if not customer_id or not library_id:
                link_skipped += 1
                continue
            before = conn.total_changes
            _insert(conn, "customer_libraries", {
                "customer_id": customer_id,
                "library_id": library_id,
                "extra1": link.get("extra1") or "{}",
                "extra2": link.get("extra2") or "{}",
                "extra3": link.get("extra3") or "{}",
            }, or_ignore=True)
            # OR IGNORE 命中唯一键时 total_changes 不变 → 计 skipped
            if conn.total_changes > before:
                link_added += 1
            else:
                link_skipped += 1
        report["tables"]["customer_libraries"] = {
            "inserted": link_added, "skipped": link_skipped,
        }

        # 附加联系人：按 (lower(email), name) 去重合并；并建旧 id→新 id 映射（画像用）
        contact_inserted = contact_skipped = 0
        contact_map: dict[int, int] = {}
        has_contacts = _contacts_table_exists(conn)
        if has_contacts:
            existing_contacts = _rows(
                conn,
                "SELECT * FROM contacts WHERE company_id = ?",
                (target_id,),
            )
            existing_by_key: dict[tuple[int, str, str], int] = {}
            for er in existing_contacts:
                k = (
                    int(er["customer_id"]),
                    (er.get("email") or "").strip().lower(),
                    (er.get("name") or "").strip(),
                )
                existing_by_key[k] = int(er["id"])
            for row in source_tables["contacts"]:
                old_contact_id = row.get("id")
                mapped_cid = customer_map.get(row.get("customer_id"))
                if not mapped_cid:
                    contact_skipped += 1
                    continue
                key = (
                    int(mapped_cid),
                    (row.get("email") or "").strip().lower(),
                    (row.get("name") or "").strip(),
                )
                if key in existing_by_key:
                    # 判重跳过：映射到目标库已有行
                    if old_contact_id is not None:
                        contact_map[int(old_contact_id)] = existing_by_key[key]
                    contact_skipped += 1
                    continue
                new_row = _without_id(dict(row))
                new_row["company_id"] = target_id
                new_row["customer_id"] = mapped_cid
                new_row["is_primary"] = 0
                try:
                    new_cid = _insert(conn, "contacts", new_row)
                except Exception:
                    contact_skipped += 1
                    continue
                existing_by_key[key] = int(new_cid)
                if old_contact_id is not None:
                    contact_map[int(old_contact_id)] = int(new_cid)
                contact_inserted += 1
        else:
            contact_skipped = len(source_tables["contacts"])
        report["tables"]["contacts"] = {
            "inserted": contact_inserted, "skipped": contact_skipped,
        }

        # 对话（补旧 id→新 id 映射，供画像 source_ref 重映射）
        existing_conv_rows = _rows(
            conn, "SELECT * FROM conversations WHERE company_id = ?", (target_id,),
        )
        existing_conv = {
            merge_mod.conversation_key(row): int(row["id"])
            for row in existing_conv_rows
        }
        conversation_map: dict[int, int] = {}
        inserted_convs: list[dict] = []
        conv_inserted = conv_skipped = 0
        for row in source_tables["conversations"]:
            old_conv_id = row.get("id")
            new_row = _without_id(dict(row))
            new_row["company_id"] = target_id
            new_row["customer_id"] = customer_map.get(row.get("customer_id"))
            new_row["library_id"] = lib_id_map.get(row.get("library_id"))
            if row.get("files_read"):
                new_row["files_read"] = mapper.rewrite_files_read(row.get("files_read"))
            key = merge_mod.conversation_key(new_row)
            if key in existing_conv:
                if old_conv_id is not None:
                    conversation_map[int(old_conv_id)] = existing_conv[key]
                conv_skipped += 1
                continue
            new_id = _insert(conn, "conversations", new_row)
            existing_conv[key] = int(new_id)
            if old_conv_id is not None:
                conversation_map[int(old_conv_id)] = int(new_id)
            conv_inserted += 1
            new_row["_new_id"] = new_id
            inserted_convs.append(new_row)
        report["tables"]["conversations"] = {
            "inserted": conv_inserted, "skipped": conv_skipped,
        }

        # 客户画像 facts / gifts（旧包缺表文件时 _load_table 已返回 []）
        def _remap_attach(row: dict) -> tuple[str, int | None, bool]:
            """返回 (attach_to, contact_id, unmapped)。"""
            at = row.get("attach_to")
            old_cid = row.get("contact_id")
            # 旧包缺 attach_to：有 contact_id 当 contact，否则 none
            if at is None or at == "":
                at = "contact" if old_cid is not None else "none"
            at = str(at)
            if at == "primary":
                return "primary", None, False
            if at == "none":
                return "none", None, False
            if at == "contact":
                if old_cid is None:
                    return "none", None, True
                mapped = contact_map.get(int(old_cid))
                if mapped is None:
                    return "none", None, True
                return "contact", int(mapped), False
            return "none", None, True

        def _remap_source_ref(row: dict) -> int | None:
            """chat 重映射；email 一律 NULL。"""
            st = (row.get("source_type") or "").strip()
            ref = row.get("source_ref")
            if ref is None:
                return None
            if st == "email":
                return None
            if st == "chat":
                return conversation_map.get(int(ref))
            return None

        contact_unmapped = 0
        facts_inserted = facts_skipped = 0
        if _table_exists(conn, "customer_facts"):
            for row in source_tables["customer_facts"]:
                mapped_cust = customer_map.get(row.get("customer_id"))
                if not mapped_cust:
                    facts_skipped += 1
                    continue
                at, cid, unmapped = _remap_attach(row)
                if unmapped:
                    contact_unmapped += 1
                new_row = _without_id(dict(row))
                new_row["company_id"] = target_id
                new_row["customer_id"] = mapped_cust
                new_row["attach_to"] = at
                new_row["contact_id"] = cid
                new_row["source_ref"] = _remap_source_ref(row)
                before = conn.total_changes
                try:
                    _insert(conn, "customer_facts", new_row, or_ignore=True)
                except Exception:
                    facts_skipped += 1
                    continue
                if conn.total_changes > before:
                    facts_inserted += 1
                else:
                    facts_skipped += 1  # INSERT OR IGNORE 被指纹去重
        else:
            facts_skipped = len(source_tables["customer_facts"])
        report["tables"]["customer_facts"] = {
            "inserted": facts_inserted, "skipped": facts_skipped,
            "contact_unmapped": contact_unmapped,
        }

        gifts_inserted = gifts_skipped = 0
        gifts_unmapped = 0
        if _table_exists(conn, "customer_gifts"):
            for row in source_tables["customer_gifts"]:
                # 导出已排除客户索要；防御性再跳过
                if (row.get("direction") or "") == "客户索要":
                    gifts_skipped += 1
                    continue
                mapped_cust = customer_map.get(row.get("customer_id"))
                if not mapped_cust:
                    gifts_skipped += 1
                    continue
                at, cid, unmapped = _remap_attach(row)
                if unmapped:
                    gifts_unmapped += 1
                new_row = _without_id(dict(row))
                new_row["company_id"] = target_id
                new_row["customer_id"] = mapped_cust
                new_row["attach_to"] = at
                new_row["contact_id"] = cid
                new_row["source_ref"] = _remap_source_ref(row)
                before = conn.total_changes
                try:
                    _insert(conn, "customer_gifts", new_row, or_ignore=True)
                except Exception:
                    gifts_skipped += 1
                    continue
                if conn.total_changes > before:
                    gifts_inserted += 1
                else:
                    gifts_skipped += 1  # INSERT OR IGNORE 被指纹去重
        else:
            gifts_skipped = len(source_tables["customer_gifts"])
        report["tables"]["customer_gifts"] = {
            "inserted": gifts_inserted, "skipped": gifts_skipped,
            "contact_unmapped": gifts_unmapped,
        }

        # 询盘实体（旧包缺文件时 _load_table 已返回 []；映射不到客户则跳过）
        inq_inserted = inq_skipped = 0
        inquiry_map: dict[int, int] = {}
        if _table_exists(conn, "inquiries"):
            # 二次导入同一份包不能翻倍：按自然键判重（2026-11-20 审计 C1）
            existing_inq: dict[tuple, int] = {
                _inquiry_signature(row): int(row["id"])
                for row in _rows(
                    conn,
                    "SELECT id, customer_id, title, stage, source, created_at "
                    "FROM inquiries WHERE company_id = ?",
                    (target_id,),
                )
            }
            for row in source_tables["inquiries"]:
                old_inq_id = row.get("id")
                mapped_cust = customer_map.get(row.get("customer_id"))
                if not mapped_cust:
                    inq_skipped += 1
                    continue
                new_row = _without_id(dict(row))
                new_row["company_id"] = target_id
                new_row["customer_id"] = mapped_cust
                # source_id 语义未定义、当前恒为 NULL；若有值且指向对话则跟着
                # 重映射，否则置空 —— 不能把源库旧自增 id 带到目标库（C4）
                old_src = row.get("source_id")
                if old_src is not None:
                    # 畸形包里的 source_id 可能是非数字字符串（审计 O-4）：
                    # int() 失败不能连累整次导入，按「无来源」置空。
                    try:
                        new_row["source_id"] = conversation_map.get(int(old_src))
                    except (TypeError, ValueError):
                        new_row["source_id"] = None
                sig = _inquiry_signature(new_row)
                # 目标库里已有同一条：计 skipped，同时登记映射供 rfqs 复用
                if sig in existing_inq:
                    if old_inq_id is not None:
                        inquiry_map[int(old_inq_id)] = existing_inq[sig]
                    inq_skipped += 1
                    continue
                try:
                    new_inq_id = _insert(conn, "inquiries", new_row)
                    existing_inq[sig] = int(new_inq_id)
                    if old_inq_id is not None:
                        inquiry_map[int(old_inq_id)] = int(new_inq_id)
                    inq_inserted += 1
                except Exception:
                    inq_skipped += 1
        else:
            inq_skipped = len(source_tables["inquiries"])
        report["tables"]["inquiries"] = {
            "inserted": inq_inserted, "skipped": inq_skipped,
        }

        # 订单
        target_orders = _rows(conn, "SELECT * FROM orders WHERE company_id = ?", (target_id,))
        target_items = _rows(
            conn,
            "SELECT oi.* FROM order_items oi JOIN orders o ON o.id = oi.order_id "
            "WHERE o.company_id = ?",
            (target_id,),
        )
        items_by_order: dict[int, list[dict]] = {}
        for item in target_items:
            items_by_order.setdefault(item["order_id"], []).append(item)
        existing_sig: dict[tuple, int] = {
            merge_mod.order_signature(row, items_by_order.get(row["id"], [])): int(row["id"])
            for row in target_orders
        }
        source_items: dict[int, list[dict]] = {}
        for item in source_tables["order_items"]:
            source_items.setdefault(item["order_id"], []).append(item)
        order_map: dict[int, int] = {}
        order_inserted = order_skipped = 0
        for row in source_tables["orders"]:
            items = source_items.get(row["id"], [])
            new_row = _without_id(dict(row))
            new_row["company_id"] = target_id
            new_row["customer_id"] = customer_map.get(row.get("customer_id"))
            # 去重键必须用重映射后的 customer_id，否则与目标库已有订单永远对不上
            sig = merge_mod.order_signature(new_row, items)
            if sig in existing_sig:
                # 合并模式下同样登记旧→新 order_id 映射，供 purchase_orders.order_id 复用
                order_map[row["id"]] = existing_sig[sig]
                order_skipped += 1
                continue
            new_id = _insert(conn, "orders", new_row)
            order_map[row["id"]] = new_id
            for item in items:
                item_row = _without_id(dict(item))
                item_row["order_id"] = new_id
                _insert(conn, "order_items", item_row)
            existing_sig[sig] = int(new_id)
            order_inserted += 1
        for link in source_tables["order_libraries"]:
            order_id = order_map.get(link.get("order_id"))
            library_id = lib_id_map.get(link.get("library_id"))
            if order_id and library_id:
                _insert(conn, "order_libraries", {
                    "order_id": order_id,
                    "library_id": library_id,
                }, or_ignore=True)
        report["tables"]["orders"] = {
            "inserted": order_inserted, "skipped": order_skipped,
        }

        # order_events：用 order_map 重映射 order_id；映射不到就跳过；旧包无文件 → []
        events_inserted = events_skipped = 0
        for row in source_tables.get("order_events") or []:
            new_order_id = order_map.get(row.get("order_id"))
            if not new_order_id:
                events_skipped += 1
                continue
            new_row = _without_id(dict(row))
            new_row["company_id"] = target_id
            new_row["order_id"] = new_order_id
            try:
                _insert(conn, "order_events", new_row)
                events_inserted += 1
            except Exception:
                # 目标库尚无 order_events 表时跳过
                events_skipped += 1
        report["tables"]["order_events"] = {
            "inserted": events_inserted, "skipped": events_skipped,
        }

        # 验厂计划：company_id 重映射；customer_id 映射不到就置空（计划仍保留）
        vp_inserted = vp_skipped = 0
        # 二次导入同一份包会翻倍：按自然键判重（2026-11-20 审计 C1）
        existing_vp = {
            _visit_plan_signature(row)
            for row in _rows(
                conn,
                "SELECT customer_id, visit_date, title, created_at "
                "FROM visit_plans WHERE company_id = ?",
                (target_id,),
            )
        }
        for row in source_tables.get("visit_plans") or []:
            new_row = _without_id(dict(row))
            new_row["company_id"] = target_id
            old_cid = row.get("customer_id")
            if old_cid is not None:
                new_row["customer_id"] = customer_map.get(old_cid)
            sig = _visit_plan_signature(new_row)
            # 目标库里已有同一条计划：跳过，不重复插入
            if sig in existing_vp:
                vp_skipped += 1
                continue
            try:
                _insert(conn, "visit_plans", new_row)
                existing_vp.add(sig)
                vp_inserted += 1
            except Exception:
                vp_skipped += 1
        report["tables"]["visit_plans"] = {
            "inserted": vp_inserted, "skipped": vp_skipped,
        }

        # usage / trial / doc cache
        usage_existing = {
            (row["ts"], row["skill"], row["provider"], row["model"],
             row["prompt_tokens"], row["completion_tokens"], row["cost_usd"])
            for row in _rows(conn, "SELECT * FROM usage_ledger WHERE company_id = ?", (target_id,))
        }
        usage_added = usage_skipped = 0
        for row in source_tables["usage_ledger"]:
            key = (row.get("ts"), row.get("skill"), row.get("provider"), row.get("model"),
                   row.get("prompt_tokens"), row.get("completion_tokens"), row.get("cost_usd"))
            # 已存在同一笔用量记录：计 skipped
            if key in usage_existing:
                usage_skipped += 1
                continue
            new_row = {k: v for k, v in row.items() if k != "id"}
            new_row["company_id"] = target_id
            _insert(conn, "usage_ledger", new_row)
            usage_existing.add(key)
            usage_added += 1
        doc_added = 0
        for row in source_tables["doc_extractions"]:
            new_row = dict(row)
            new_row["tenant_id"] = str(target_id)
            before = conn.total_changes
            _insert(conn, "doc_extractions", new_row, or_ignore=True)
            if conn.total_changes > before:
                doc_added += 1
        # 其余没插进去的就是被 OR IGNORE 忽略的（P2-14：此前恒为 0）
        doc_skipped = len(source_tables["doc_extractions"]) - doc_added
        report["tables"]["usage_ledger"] = {
            "inserted": usage_added, "skipped": usage_skipped,
        }
        report["tables"]["doc_extractions"] = {
            "inserted": doc_added, "skipped": doc_skipped,
        }

        # 供应商四张正式表：suppliers / supplier_contacts / supplier_products / supplier_quotes
        supplier_map: dict[int, int] = {}
        sup_added = sup_skipped = 0
        if _table_exists(conn, "suppliers"):
            target_suppliers = _rows(conn, "SELECT * FROM suppliers WHERE company_id = ?", (target_id,))
            sup_by_name = {merge_mod.norm_name(row.get("name")): row for row in target_suppliers}
            for row in source_tables.get("suppliers") or []:
                old_sid = row.get("id")
                key = merge_mod.norm_name(row.get("name"))
                existing = sup_by_name.get(key)
                # 同公司已存在同名供应商：合并空缺字段，不新建重复行
                if existing:
                    if old_sid is not None:
                        supplier_map[int(old_sid)] = int(existing["id"])
                    _fill_empty_supplier_fields(conn, int(existing["id"]), row)
                    sup_skipped += 1
                    continue
                new_row = _without_id(dict(row))
                new_row["company_id"] = target_id
                new_sid = _insert(conn, "suppliers", new_row)
                if old_sid is not None:
                    supplier_map[int(old_sid)] = int(new_sid)
                sup_by_name[key] = {"id": new_sid, "name": new_row.get("name")}
                sup_added += 1
        else:
            sup_skipped = len(source_tables.get("suppliers") or [])
        report["tables"]["suppliers"] = {
            "inserted": sup_added, "added": sup_added, "skipped": sup_skipped,
        }

        sc_added = sc_skipped = 0
        if _table_exists(conn, "supplier_contacts"):
            existing_sc = {
                (
                    int(r["supplier_id"]),
                    (r.get("name") or "").strip(),
                    (r.get("phone") or "").strip(),
                    (r.get("email") or "").strip().lower(),
                )
                for r in _rows(
                    conn,
                    "SELECT supplier_id, name, phone, email FROM supplier_contacts WHERE company_id = ?",
                    (target_id,),
                )
            }
            suppliers_with_primary = {
                int(r["supplier_id"])
                for r in _rows(
                    conn,
                    "SELECT DISTINCT supplier_id FROM supplier_contacts WHERE company_id = ? AND is_primary = 1",
                    (target_id,),
                )
            }
            for row in source_tables.get("supplier_contacts") or []:
                mapped_sid = supplier_map.get(row.get("supplier_id"))
                # 映射不到目标供应商时跳过
                if not mapped_sid:
                    sc_skipped += 1
                    continue
                sc_key = (
                    int(mapped_sid),
                    (row.get("name") or "").strip(),
                    (row.get("phone") or "").strip(),
                    (row.get("email") or "").strip().lower(),
                )
                # 联系人已存在则跳过
                if sc_key in existing_sc:
                    sc_skipped += 1
                    continue
                new_row = _without_id(dict(row))
                new_row["company_id"] = target_id
                new_row["supplier_id"] = mapped_sid
                # 目标供应商已有主联系人时，导入的新联系人不覆盖主联系人标记
                if int(new_row.get("is_primary") or 0) == 1:
                    if mapped_sid in suppliers_with_primary:
                        new_row["is_primary"] = 0
                    else:
                        suppliers_with_primary.add(mapped_sid)
                _insert(conn, "supplier_contacts", new_row)
                existing_sc.add(sc_key)
                sc_added += 1
        else:
            sc_skipped = len(source_tables.get("supplier_contacts") or [])
        report["tables"]["supplier_contacts"] = {
            "inserted": sc_added, "added": sc_added, "skipped": sc_skipped,
        }

        supplier_product_map: dict[int, int] = {}
        sp_added = sp_skipped = 0
        if _table_exists(conn, "supplier_products"):
            existing_sp: dict[tuple[int, str, str], dict] = {}
            for r in _rows(conn, "SELECT * FROM supplier_products WHERE company_id = ?", (target_id,)):
                sp_key = (
                    int(r["supplier_id"]),
                    (r.get("product_name") or "").strip(),
                    (r.get("spec_model") or "").strip(),
                )
                existing_sp[sp_key] = r
            for row in source_tables.get("supplier_products") or []:
                old_spid = row.get("id")
                mapped_sid = supplier_map.get(row.get("supplier_id"))
                # 映射不到目标供应商时跳过
                if not mapped_sid:
                    sp_skipped += 1
                    continue
                prod_name = (row.get("product_name") or "").strip()
                spec_model = (row.get("spec_model") or "").strip()
                sp_key = (int(mapped_sid), prod_name, spec_model)
                existing = existing_sp.get(sp_key)
                # 能力行已存在：按 updated_at 较新者为准合并冲突字段
                if existing:
                    if old_spid is not None:
                        supplier_product_map[int(old_spid)] = int(existing["id"])
                    src_upd = str(row.get("updated_at") or "")
                    tgt_upd = str(existing.get("updated_at") or "")
                    if src_upd > tgt_upd:
                        conn.execute(
                            "UPDATE supplier_products SET "
                            "unit = ?, is_self_produced = ?, quality_note = ?, "
                            "lead_time_days = ?, lead_time_text = ?, moq = ?, "
                            "packing_info = ?, notes = ?, extra1 = ?, extra2 = ?, extra3 = ?, "
                            "updated_at = ? "
                            "WHERE id = ? AND company_id = ?",
                            (
                                row.get("unit") or "",
                                row.get("is_self_produced") if row.get("is_self_produced") in (0, 1, 2) else 2,
                                row.get("quality_note") or "",
                                row.get("lead_time_days"),
                                row.get("lead_time_text") or "",
                                row.get("moq"),
                                row.get("packing_info") or "",
                                row.get("notes") or "",
                                row.get("extra1") or "{}",
                                row.get("extra2") or "{}",
                                row.get("extra3") or "{}",
                                src_upd,
                                int(existing["id"]),
                                target_id,
                            ),
                        )
                        existing["updated_at"] = src_upd
                    sp_skipped += 1
                    continue
                new_row = _without_id(dict(row))
                new_row["company_id"] = target_id
                new_row["supplier_id"] = mapped_sid
                new_row["product_name"] = prod_name
                new_row["spec_model"] = spec_model
                new_spid = _insert(conn, "supplier_products", new_row)
                if old_spid is not None:
                    supplier_product_map[int(old_spid)] = int(new_spid)
                existing_sp[sp_key] = {"id": new_spid, "updated_at": new_row.get("updated_at") or ""}
                sp_added += 1
        else:
            sp_skipped = len(source_tables.get("supplier_products") or [])
        report["tables"]["supplier_products"] = {
            "inserted": sp_added, "added": sp_added, "skipped": sp_skipped,
        }

        # 采购询价单头（rfqs）：在 supplier_quotes 之前导入以便重映射 rfq_id
        rfq_map: dict[int, int] = {}
        rfq_added = rfq_skipped = 0
        if _table_exists(conn, "rfqs"):
            existing_rfqs: dict[tuple, int] = {
                _rfq_signature(r): int(r["id"])
                for r in _rows(
                    conn,
                    "SELECT id, customer_id, inquiry_id, product_name, spec_model, created_at "
                    "FROM rfqs WHERE company_id = ?",
                    (target_id,),
                )
            }
            for row in source_tables.get("rfqs") or []:
                old_rfq_id = row.get("id")
                new_row = _without_id(dict(row))
                new_row["company_id"] = target_id
                # customer_id 与 inquiry_id 映射不到时置 NULL，不中断导入
                old_cust_id = row.get("customer_id")
                if old_cust_id is not None:
                    try:
                        new_row["customer_id"] = customer_map.get(int(old_cust_id))
                    except (TypeError, ValueError):
                        new_row["customer_id"] = None
                else:
                    new_row["customer_id"] = None
                old_inq_id = row.get("inquiry_id")
                if old_inq_id is not None:
                    try:
                        new_row["inquiry_id"] = inquiry_map.get(int(old_inq_id))
                    except (TypeError, ValueError):
                        new_row["inquiry_id"] = None
                else:
                    new_row["inquiry_id"] = None
                sig = _rfq_signature(new_row)
                # 同去重签名已存在：跳过并记录旧→新映射
                if sig in existing_rfqs:
                    if old_rfq_id is not None:
                        rfq_map[int(old_rfq_id)] = existing_rfqs[sig]
                    rfq_skipped += 1
                    continue
                new_rfq_id = _insert(conn, "rfqs", new_row)
                existing_rfqs[sig] = int(new_rfq_id)
                if old_rfq_id is not None:
                    rfq_map[int(old_rfq_id)] = int(new_rfq_id)
                rfq_added += 1
        else:
            rfq_skipped = len(source_tables.get("rfqs") or [])
        report["tables"]["rfqs"] = {
            "inserted": rfq_added, "added": rfq_added, "skipped": rfq_skipped,
        }

        supplier_quote_map: dict[int, int] = {}
        sq_added = sq_skipped = 0
        if _table_exists(conn, "supplier_quotes"):
            existing_sq: dict[tuple, int] = {
                _supplier_quote_signature(r): int(r["id"])
                for r in _rows(
                    conn,
                    "SELECT id, supplier_id, product_name, spec_model, quoted_at, "
                    "price_excl_tax, price_incl_tax "
                    "FROM supplier_quotes WHERE company_id = ?",
                    (target_id,),
                )
            }
            for row in source_tables.get("supplier_quotes") or []:
                old_qid = row.get("id")
                mapped_sid = supplier_map.get(row.get("supplier_id"))
                # 映射不到目标供应商时跳过
                if not mapped_sid:
                    sq_skipped += 1
                    continue
                new_row = _without_id(dict(row))
                new_row["company_id"] = target_id
                new_row["supplier_id"] = mapped_sid
                old_spid = row.get("supplier_product_id")
                new_row["supplier_product_id"] = (
                    supplier_product_map.get(int(old_spid)) if old_spid is not None else None
                )
                old_cust_id = row.get("source_customer_id")
                new_row["source_customer_id"] = (
                    customer_map.get(int(old_cust_id)) if old_cust_id is not None else None
                )
                # 第二批：按 rfq_map 重映射 rfq_id，映射不到置 NULL
                old_rfq_id = row.get("rfq_id")
                if old_rfq_id is not None:
                    try:
                        new_row["rfq_id"] = rfq_map.get(int(old_rfq_id))
                    except (TypeError, ValueError):
                        new_row["rfq_id"] = None
                else:
                    new_row["rfq_id"] = None
                sig = _supplier_quote_signature(new_row)
                # 同去重键报价已存在时跳过（重复导入一条不增），但仍记录旧→新 id 供 rfq_responses 关联
                if sig in existing_sq:
                    if old_qid is not None:
                        supplier_quote_map[int(old_qid)] = existing_sq[sig]
                    sq_skipped += 1
                    continue
                new_qid = _insert(conn, "supplier_quotes", new_row)
                existing_sq[sig] = int(new_qid)
                if old_qid is not None:
                    supplier_quote_map[int(old_qid)] = int(new_qid)
                sq_added += 1
        else:
            sq_skipped = len(source_tables.get("supplier_quotes") or [])
        report["tables"]["supplier_quotes"] = {
            "inserted": sq_added, "added": sq_added, "skipped": sq_skipped,
        }

        # 采购询价回复行（rfq_responses）：按 (rfq_id 映射后, supplier_id 映射后) 去重
        rr_added = rr_skipped = 0
        if _table_exists(conn, "rfq_responses"):
            existing_rr: set[tuple[int, int]] = {
                (int(r["rfq_id"]), int(r["supplier_id"]))
                for r in _rows(
                    conn,
                    "SELECT rfq_id, supplier_id FROM rfq_responses WHERE company_id = ?",
                    (target_id,),
                )
            }
            for row in source_tables.get("rfq_responses") or []:
                mapped_rfq = rfq_map.get(row.get("rfq_id"))
                mapped_sup = supplier_map.get(row.get("supplier_id"))
                # 映射不到询价单或供应商时跳过
                if not mapped_rfq or not mapped_sup:
                    rr_skipped += 1
                    continue
                rr_key = (int(mapped_rfq), int(mapped_sup))
                # 同单同供应商回复已存在时跳过
                if rr_key in existing_rr:
                    rr_skipped += 1
                    continue
                new_row = _without_id(dict(row))
                new_row["company_id"] = target_id
                new_row["rfq_id"] = mapped_rfq
                new_row["supplier_id"] = mapped_sup
                old_qid = row.get("quote_id")
                if old_qid is not None:
                    try:
                        new_row["quote_id"] = supplier_quote_map.get(int(old_qid))
                    except (TypeError, ValueError):
                        new_row["quote_id"] = None
                else:
                    new_row["quote_id"] = None
                _insert(conn, "rfq_responses", new_row)
                existing_rr.add(rr_key)
                rr_added += 1
        else:
            rr_skipped = len(source_tables.get("rfq_responses") or [])
        report["tables"]["rfq_responses"] = {
            "inserted": rr_added, "added": rr_added, "skipped": rr_skipped,
        }

        # 供应商管理一期 · 第三批：purchase_orders / consolidations / consolidation_items
        po_map: dict[int, int] = {}
        po_added = po_skipped = 0
        if _table_exists(conn, "purchase_orders"):
            existing_pos: dict[tuple[str, int], int] = {
                ((r.get("po_no") or "").strip(), int(r["supplier_id"])): int(r["id"])
                for r in _rows(
                    conn,
                    "SELECT id, po_no, supplier_id FROM purchase_orders WHERE company_id = ?",
                    (target_id,),
                )
            }
            for row in source_tables.get("purchase_orders") or []:
                old_po_id = row.get("id")
                mapped_sup = supplier_map.get(row.get("supplier_id"))
                # 映射不到目标供应商时跳过
                if not mapped_sup:
                    po_skipped += 1
                    continue
                po_no_val = (row.get("po_no") or "").strip()
                po_key = (po_no_val, int(mapped_sup))
                # 去重签名 = (po_no, supplier 映射后)
                if po_key in existing_pos:
                    if old_po_id is not None:
                        po_map[int(old_po_id)] = existing_pos[po_key]
                    po_skipped += 1
                    continue
                new_row = _without_id(dict(row))
                new_row["company_id"] = target_id
                new_row["supplier_id"] = mapped_sup
                old_ord_id = row.get("order_id")
                if old_ord_id is not None:
                    try:
                        new_row["order_id"] = order_map.get(int(old_ord_id))
                    except (TypeError, ValueError):
                        new_row["order_id"] = None
                else:
                    new_row["order_id"] = None
                old_rfq_id = row.get("rfq_id")
                if old_rfq_id is not None:
                    try:
                        new_row["rfq_id"] = rfq_map.get(int(old_rfq_id))
                    except (TypeError, ValueError):
                        new_row["rfq_id"] = None
                else:
                    new_row["rfq_id"] = None
                new_po_id = _insert(conn, "purchase_orders", new_row)
                existing_pos[po_key] = int(new_po_id)
                if old_po_id is not None:
                    po_map[int(old_po_id)] = int(new_po_id)
                po_added += 1
        else:
            po_skipped = len(source_tables.get("purchase_orders") or [])
        report["tables"]["purchase_orders"] = {
            "inserted": po_added, "added": po_added, "skipped": po_skipped,
        }

        cons_map: dict[int, int] = {}
        cons_added = cons_skipped = 0
        if _table_exists(conn, "consolidations"):
            existing_cons: dict[tuple[str, str], int] = {
                ((r.get("code") or "").strip(), (r.get("cutoff_date") or "").strip()): int(r["id"])
                for r in _rows(
                    conn,
                    "SELECT id, code, cutoff_date FROM consolidations WHERE company_id = ?",
                    (target_id,),
                )
            }
            for row in source_tables.get("consolidations") or []:
                old_cons_id = row.get("id")
                cons_key = (
                    (row.get("code") or "").strip(),
                    (row.get("cutoff_date") or "").strip(),
                )
                # 去重签名 = (code, cutoff_date)
                if cons_key in existing_cons:
                    if old_cons_id is not None:
                        cons_map[int(old_cons_id)] = existing_cons[cons_key]
                    cons_skipped += 1
                    continue
                new_row = _without_id(dict(row))
                new_row["company_id"] = target_id
                new_cons_id = _insert(conn, "consolidations", new_row)
                existing_cons[cons_key] = int(new_cons_id)
                if old_cons_id is not None:
                    cons_map[int(old_cons_id)] = int(new_cons_id)
                cons_added += 1
        else:
            cons_skipped = len(source_tables.get("consolidations") or [])
        report["tables"]["consolidations"] = {
            "inserted": cons_added, "added": cons_added, "skipped": cons_skipped,
        }

        ci_added = ci_skipped = 0
        if _table_exists(conn, "consolidation_items"):
            existing_ci: set[tuple[int, int]] = {
                (int(r["consolidation_id"]), int(r["purchase_order_id"]))
                for r in _rows(
                    conn,
                    "SELECT consolidation_id, purchase_order_id FROM consolidation_items WHERE company_id = ?",
                    (target_id,),
                )
            }
            for row in source_tables.get("consolidation_items") or []:
                mapped_cons = cons_map.get(row.get("consolidation_id"))
                mapped_po = po_map.get(row.get("purchase_order_id"))
                # 映射不到目标拼柜或采购单时跳过
                if not mapped_cons or not mapped_po:
                    ci_skipped += 1
                    continue
                ci_key = (int(mapped_cons), int(mapped_po))
                # 去重键 = (consolidation 映射后, purchase_order 映射后)
                if ci_key in existing_ci:
                    ci_skipped += 1
                    continue
                new_row = _without_id(dict(row))
                new_row["company_id"] = target_id
                new_row["consolidation_id"] = mapped_cons
                new_row["purchase_order_id"] = mapped_po
                _insert(conn, "consolidation_items", new_row)
                existing_ci.add(ci_key)
                ci_added += 1
        else:
            ci_skipped = len(source_tables.get("consolidation_items") or [])
        report["tables"]["consolidation_items"] = {
            "inserted": ci_added, "added": ci_added, "skipped": ci_skipped,
        }

        # 公司身份 + 工作目录路径
        target_tc_extra = dict(ctx["extra"])
        target_tc_extra["work_dir"] = str(target_work_dir)
        conn.execute(
            "UPDATE trade_companies SET data_dir = ?, extra1 = ? WHERE company_id = ?",
            (str(target_data_dir), json.dumps(target_tc_extra, ensure_ascii=False), target_id),
        )
        if report["mode"] == "created":
            if source_identity:
                conn.execute(
                    "UPDATE trade_companies SET agent_identity_md = ? WHERE company_id = ?",
                    (source_identity, target_id),
                )
                report["identity"] = "imported"
        elif not (ctx["row"].get("agent_identity_md") or "").strip() and source_identity:
            conn.execute(
                "UPDATE trade_companies SET agent_identity_md = ? WHERE company_id = ?",
                (source_identity, target_id),
            )
            report["identity"] = "imported"

        # 文件：公司目录（在 commit **之前**落盘）
        # 顺序必须是「DB 变更 → 文件 → commit」：文件失败时还能 rollback DB，
        # 不会留下「库里已合并、文件没拷完」的半导入状态（2026-11-11 审计 P1-1）。
        # 新建模式下若数据目录是上次删除残留的（created_data_dir_is_new=False），
        # 绝不能覆盖里面已有的文件，按合并模式走冲突归档（P1-2）。
        overwrite_files = report["mode"] == "created" and created_data_dir_is_new
        if report["mode"] == "created" and not created_data_dir_is_new:
            report["warnings"].append(
                "目标数据目录是上次删除后的残留目录，已保留原有文件，冲突文件归档到 import_conflicts/"
            )
        conflict_root = target_data_dir / "import_conflicts" / datetime.now().strftime("%Y%m%d-%H%M%S")
        company_files = staging / "company_data"
        if company_files.is_dir():
            for src in company_files.rglob("*"):
                if not src.is_file():
                    continue
                rel = src.relative_to(company_files).as_posix()
                parts = rel.split("/")
                if len(parts) >= 2 and parts[0] == "companies" and parts[1] == source_slug:
                    parts[1] = target.get("slug") or parts[1]
                    rel = "/".join(parts)
                status = _merge_copy(
                    src, target_data_dir / rel, conflict_root, rel,
                    overwrite=overwrite_files,
                )
                report["files"][{"copied": "copied", "skipped": "skipped", "conflict": "conflicts"}.get(status, "skipped")] += 1

        # 文件：资料库
        for source_lib in source_libs:
            root = lib_map.get(source_lib.get("export_id"))
            if root is None:
                continue
            lib_src = staging / "libraries" / source_lib["export_id"]
            if not lib_src.is_dir():
                continue
            root.mkdir(parents=True, exist_ok=True)
            lib_conflict = root / "import_conflicts" / datetime.now().strftime("%Y%m%d-%H%M%S")
            for src in lib_src.rglob("*"):
                if not src.is_file():
                    continue
                rel = src.relative_to(lib_src).as_posix()
                status = _merge_copy(src, root / rel, lib_conflict, rel, overwrite=False)
                report["files"][{"copied": "copied", "skipped": "skipped", "conflict": "conflicts"}.get(status, "skipped")] += 1

        # 文件全部落盘后再提交；此后的 MEMORY/Hindsight 失败属于「DB 与文件已一致、
        # 只差记忆」，错误信息里带备份路径即可（见下方 except）。
        conn.commit()
        committed = True

        # 公司专属 MEMORY.md（写入目标公司的物理隔离目录，不再混入全局文件）
        memory_file = staging / "memory" / "hermes_memory.md"
        if memory_file.is_file():
            blocks = [
                block for block in memory_file.read_text(encoding="utf-8-sig").split("\n\n")
                if block.strip()
            ]
            target_name = target.get("name") or source_name
            target_slug = str(target.get("slug") or "")
            rewritten = [merge_mod.rewrite_company_tag(block.strip(), target_name) for block in blocks]
            report["memory"] = merge_mod.append_memory_blocks(
                rewritten, company_slug=target_slug
            )

        # Hindsight best-effort
        report["hindsight"] = replay_hindsight_async(
            target_id,
            inserted_convs,
            {row["id"]: row.get("name") or "" for row in target_libs},
            customer_names,
        )

        # 向量索引（语义检索开启时才真正执行）
        try:
            from trade import vec_search

            rebuild = getattr(vec_search, "rebuild_all_customers", None)
            if rebuild is not None:
                rebuild(conn)
                report["vectors"] = "rebuilt"
        except Exception as exc:  # noqa: BLE001
            report["warnings"].append(f"vector rebuild skipped: {exc}")

        return report
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
        if created_company_id is not None:
            try:
                cleanup = get_connection()
                cleanup.execute("DELETE FROM companies WHERE id = ?", (created_company_id,))
                cleanup.commit()
                cleanup.close()
            except sqlite3.Error:
                pass
            # 只删本次新建的目录：slug 目录可能是上次删除后残留的用户目录
            if created_data_dir and created_data_dir_is_new:
                shutil.rmtree(created_data_dir, ignore_errors=True)
            if created_work_dir and work_dir_is_new:
                shutil.rmtree(created_work_dir, ignore_errors=True)
        # 走到这里说明 DB 与文件都已提交，失败发生在 commit 之后的副作用
        # （MEMORY 写入 / 向量重建 / Hindsight 排队）。此时 rollback 已无效，
        # 导入结果本身是一致的；但要把导入前备份路径带进错误信息，方便用户
        # 需要时恢复（审计 P2-2）。文件拷贝阶段的失败不会走到这里 —— 那时
        # committed 仍为 False，主事务会被完整回滚。
        if committed and backup_path is not None:
            raise TransferError(
                f"{exc}（数据库已合并；导入前备份：{backup_path}）"
            ) from exc
        raise
    finally:
        if conn is not None:
            conn.close()
        shutil.rmtree(staging, ignore_errors=True)
