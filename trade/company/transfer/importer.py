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
    total = 0
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise InvalidPackageError("too many entries")
        for info in infos:
            name = info.filename
            if not name or "\x00" in name or "\\" in name:
                raise InvalidPackageError(f"unsafe path: {name!r}")
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
                shutil.copyfileobj(src, out, length=1 << 20)
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


def _find_targets(conn: sqlite3.Connection, name: str) -> list[dict]:
    target = merge_mod.norm_name(name)
    rows = _rows(conn, "SELECT id, name, slug, is_active FROM companies")
    return [row for row in rows if merge_mod.norm_name(row.get("name")) == target]


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
                   force_new: bool = False) -> dict:
    """导入一个公司包，返回报告。异常时抛 TransferError / ValueError。"""
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
            created_lib = library_module.create(
                safe_name,
                str(root),
                description=source_lib.get("description") or "",
                company_id=target_id,
            )
            lib_map[source_lib["export_id"]] = root
            lib_by_name[key] = created_lib
            lib_name_by_id[created_lib["id"]] = safe_name
            if source_lib.get("source_id") is not None:
                lib_id_map[source_lib["source_id"]] = created_lib["id"]
            target_libs.append(created_lib)
            libs_inserted += 1

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
                "usage_ledger", "trial_events", "doc_extractions",
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
        for row in source_tables["customers"]:
            key = merge_mod.norm_name(row.get("name"))
            existing = cust_by_name.get(key)
            if existing:
                customer_map[row["id"]] = existing["id"]
                customer_skipped += 1
                for field in ("contact", "note"):
                    if not existing.get(field) and row.get(field):
                        conn.execute(
                            f"UPDATE customers SET {field} = ? WHERE id = ?",
                            (row[field], existing["id"]),
                        )
                continue
            new_row = _without_id(dict(row))
            new_row["company_id"] = target_id
            new_id = _insert(conn, "customers", new_row)
            customer_map[row["id"]] = new_id
            cust_by_name[key] = {"id": new_id, "name": row.get("name")}
            customer_names[new_id] = row.get("name") or ""
            customer_inserted += 1
        report["tables"]["customers"] = {
            "inserted": customer_inserted, "skipped": customer_skipped,
        }
        report["tables"]["libraries"] = {
            "inserted": libs_inserted, "skipped": libs_skipped,
        }

        # 客户 ↔ 资料库关联
        link_added = 0
        for link in source_tables["customer_libraries"]:
            customer_id = customer_map.get(link.get("customer_id"))
            library_id = lib_id_map.get(link.get("library_id"))
            if not customer_id or not library_id:
                continue
            _insert(conn, "customer_libraries", {
                "customer_id": customer_id,
                "library_id": library_id,
                "extra1": link.get("extra1") or "{}",
                "extra2": link.get("extra2") or "{}",
                "extra3": link.get("extra3") or "{}",
            }, or_ignore=True)
            link_added += 1
        report["tables"]["customer_libraries"] = {"inserted": link_added, "skipped": 0}

        # 对话
        existing_conv = {
            merge_mod.conversation_key(row)
            for row in _rows(conn, "SELECT * FROM conversations WHERE company_id = ?", (target_id,))
        }
        inserted_convs: list[dict] = []
        conv_inserted = conv_skipped = 0
        for row in source_tables["conversations"]:
            new_row = _without_id(dict(row))
            new_row["company_id"] = target_id
            new_row["customer_id"] = customer_map.get(row.get("customer_id"))
            new_row["library_id"] = lib_id_map.get(row.get("library_id"))
            if row.get("files_read"):
                new_row["files_read"] = mapper.rewrite_files_read(row.get("files_read"))
            key = merge_mod.conversation_key(new_row)
            if key in existing_conv:
                conv_skipped += 1
                continue
            new_id = _insert(conn, "conversations", new_row)
            existing_conv.add(key)
            conv_inserted += 1
            new_row["_new_id"] = new_id
            inserted_convs.append(new_row)
        report["tables"]["conversations"] = {
            "inserted": conv_inserted, "skipped": conv_skipped,
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
        existing_sig = {
            merge_mod.order_signature(row, items_by_order.get(row["id"], []))
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
                order_skipped += 1
                continue
            new_id = _insert(conn, "orders", new_row)
            order_map[row["id"]] = new_id
            for item in items:
                item_row = _without_id(dict(item))
                item_row["order_id"] = new_id
                _insert(conn, "order_items", item_row)
            existing_sig.add(sig)
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

        # usage / trial / doc cache
        usage_existing = {
            (row["ts"], row["skill"], row["provider"], row["model"],
             row["prompt_tokens"], row["completion_tokens"], row["cost_usd"])
            for row in _rows(conn, "SELECT * FROM usage_ledger WHERE company_id = ?", (target_id,))
        }
        usage_added = 0
        for row in source_tables["usage_ledger"]:
            key = (row.get("ts"), row.get("skill"), row.get("provider"), row.get("model"),
                   row.get("prompt_tokens"), row.get("completion_tokens"), row.get("cost_usd"))
            if key in usage_existing:
                continue
            new_row = {k: v for k, v in row.items() if k != "id"}
            new_row["company_id"] = target_id
            _insert(conn, "usage_ledger", new_row)
            usage_existing.add(key)
            usage_added += 1
        trial_added = 0
        trial_existing = {
            (row["ts"], row["kind"])
            for row in _rows(conn, "SELECT * FROM trial_events WHERE company_id = ?", (target_id,))
        }
        for row in source_tables["trial_events"]:
            key = (row.get("ts"), row.get("kind"))
            if key in trial_existing:
                continue
            new_row = {k: v for k, v in row.items() if k != "id"}
            new_row["company_id"] = target_id
            _insert(conn, "trial_events", new_row)
            trial_added += 1
        doc_added = 0
        for row in source_tables["doc_extractions"]:
            new_row = dict(row)
            new_row["tenant_id"] = str(target_id)
            before = conn.total_changes
            _insert(conn, "doc_extractions", new_row, or_ignore=True)
            if conn.total_changes > before:
                doc_added += 1
        report["tables"]["usage_ledger"] = {"inserted": usage_added, "skipped": 0}
        report["tables"]["trial_events"] = {"inserted": trial_added, "skipped": 0}
        report["tables"]["doc_extractions"] = {"inserted": doc_added, "skipped": 0}

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

        conn.commit()
        committed = True

        # 文件：公司目录
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
                    overwrite=(report["mode"] == "created"),
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

        # Hermes MEMORY.md
        memory_file = staging / "memory" / "hermes_memory.md"
        if memory_file.is_file():
            blocks = [
                block for block in memory_file.read_text(encoding="utf-8-sig").split("\n\n")
                if block.strip()
            ]
            target_name = target.get("name") or source_name
            rewritten = [merge_mod.rewrite_company_tag(block.strip(), target_name) for block in blocks]
            report["memory"] = merge_mod.append_memory_blocks(rewritten)

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
        # 合并模式在文件拷贝之前已经 commit（见上方 S8）；此时 rollback 无效，
        # 用户面对的是「库已合并、文件可能一半」的状态。必须把导入前备份路径
        # 带进错误信息 —— 否则只能自己去 backups 目录按时间戳猜（审计 P2-2）。
        if committed and backup_path is not None:
            raise TransferError(
                f"{exc}（数据库已合并；导入前备份：{backup_path}）"
            ) from exc
        raise
    finally:
        if conn is not None:
            conn.close()
        shutil.rmtree(staging, ignore_errors=True)
