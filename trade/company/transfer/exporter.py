"""单公司导出：DB 行 + 公司目录 + 资料库文件 + Hermes 公司记忆 -> ZIP。"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from trade.company.transfer import (
    FORMAT_VERSION,
    MAX_PACKAGE_BYTES,
    PACKAGE_FORMAT,
    PackageTooLargeError,
)
from trade.company.transfer import merge as merge_mod
from trade.company.transfer.manifest import sha256_file, write_checksums


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    cursor = conn.execute(sql, params)
    columns = [item[0] for item in cursor.description or []]
    return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]


def _schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return 0


def _app_version() -> str:
    try:
        from trade import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001
        return "unknown"


def _copy_tree(src: Path, dst: Path, warnings: list[str]) -> list[str]:
    """复制普通文件，拒绝符号链接；返回相对路径列表。"""
    copied: list[str] = []
    if not src.is_dir():
        warnings.append(f"directory missing: {src}")
        return copied
    for path in src.rglob("*"):
        if path.is_symlink():
            warnings.append(f"skipped symlink: {path}")
            continue
        if not path.is_file():
            continue
        if path.name == ".DS_Store":
            continue
        rel = path.relative_to(src).as_posix()
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied.append(rel)
    return copied


def _collect_files(staging: Path, manifest: dict, company_dir: Path | None,
                   libraries: list[dict], warnings: list[str]) -> None:
    files: list[dict] = []

    def add(path: Path, kind: str) -> None:
        if not path.is_file():
            return
        rel = path.relative_to(staging).as_posix()
        files.append({
            "path": rel,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "kind": kind,
        })

    if company_dir and company_dir.is_dir():
        _copy_tree(company_dir, staging / "company_data", warnings)
        for path in (staging / "company_data").rglob("*"):
            if path.is_file():
                add(path, "company")

    export_libraries = []
    for lib in libraries:
        root = Path(lib.get("root_path") or "")
        export_id = f"L{lib['id']}"
        export_libraries.append({
            "export_id": export_id,
            "source_id": lib["id"],
            "name": lib.get("name") or "",
            "root_path": str(root),
        })
        if root.is_dir():
            _copy_tree(root, staging / "libraries" / export_id, warnings)
            for path in (staging / "libraries" / export_id).rglob("*"):
                if path.is_file():
                    add(path, "library")
        else:
            warnings.append(f"library root missing: {root}")

    manifest["paths"]["libraries"] = export_libraries
    manifest["files"] = files


def export_company(company_id: int, dest_zip: Path | None = None,
                   max_bytes: int = MAX_PACKAGE_BYTES) -> dict:
    """导出一个公司，返回 {"path","bytes","company","warnings"}。"""
    from trade.database import _get_db_path
    from trade.post_install.backup import snapshot_db

    db_path = _get_db_path()
    if not db_path.is_file():
        raise FileNotFoundError(f"database not found: {db_path}")

    staging = Path(tempfile.mkdtemp(prefix="trade-company-export-"))
    if dest_zip is None:
        fd, temp_name = tempfile.mkstemp(prefix="trade-company-", suffix=".zip")
        os.close(fd)
        zip_path = Path(temp_name)
    else:
        zip_path = dest_zip
    warnings: list[str] = []

    try:
        snapshot = staging / "snapshot.db"
        snapshot_db(db_path, snapshot)
        conn = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
        try:
            company_rows = _rows(conn, "SELECT * FROM companies WHERE id = ?", (company_id,))
            if not company_rows:
                raise ValueError(f"company not found: {company_id}")
            company = company_rows[0]
            tc_rows = _rows(conn, "SELECT * FROM trade_companies WHERE company_id = ?", (company_id,))
            tc = tc_rows[0] if tc_rows else {}
            work_dir = ""
            try:
                work_dir = json.loads(tc.get("extra1") or "{}").get("work_dir", "")
            except (TypeError, ValueError):
                pass

            tables: dict[str, list[dict]] = {
                "companies": company_rows,
                "trade_company": tc_rows,
                "libraries": _rows(conn, "SELECT * FROM libraries WHERE company_id = ?", (company_id,)),
                "customers": _rows(conn, "SELECT * FROM customers WHERE company_id = ?", (company_id,)),
                "customer_libraries": _rows(
                    conn,
                    "SELECT cl.* FROM customer_libraries cl "
                    "JOIN customers c ON c.id = cl.customer_id WHERE c.company_id = ?",
                    (company_id,),
                ),
                "conversations": _rows(conn, "SELECT * FROM conversations WHERE company_id = ?", (company_id,)),
                "orders": _rows(conn, "SELECT * FROM orders WHERE company_id = ?", (company_id,)),
                "order_items": _rows(
                    conn,
                    "SELECT oi.* FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                    "WHERE o.company_id = ?",
                    (company_id,),
                ),
                "order_libraries": _rows(
                    conn,
                    "SELECT ol.* FROM order_libraries ol JOIN orders o ON o.id = ol.order_id "
                    "WHERE o.company_id = ?",
                    (company_id,),
                ),
                "usage_ledger": _rows(conn, "SELECT * FROM usage_ledger WHERE company_id = ?", (company_id,)),
                "trial_events": _rows(conn, "SELECT * FROM trial_events WHERE company_id = ?", (company_id,)),
                "doc_extractions": _rows(
                    conn, "SELECT * FROM doc_extractions WHERE tenant_id = ?", (str(company_id),)
                ),
            }
            schema_version = _schema_version(conn)
        finally:
            conn.close()

        # 不导出机器级字段
        for row in tables["trade_company"]:
            row.pop("data_dir", None)
            row.pop("license_data", None)

        db_dir = staging / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        table_meta: dict[str, dict] = {}
        for name, rows in tables.items():
            (db_dir / f"{name}.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            table_meta[name] = {
                "file": f"db/{name}.json",
                "rows": len(rows),
                "columns": list(rows[0].keys()) if rows else [],
            }

        manifest: dict = {
            "format": PACKAGE_FORMAT,
            "format_version": FORMAT_VERSION,
            "schema_version": schema_version,
            "app_version": _app_version(),
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "company": {
                key: company.get(key)
                for key in (
                    "id", "name", "slug", "logo_url", "website",
                    "contact_name", "contact_email", "address", "is_active",
                )
            },
            "paths": {
                "data_dir": tc.get("data_dir") or "",
                "work_dir": work_dir,
                "libraries": [],
            },
            "tables": table_meta,
            "files": [],
            "warnings": warnings,
            "excluded": [
                "license_data", "vec_customers", "vec_meta", "cron_job_companies",
                "*.pid", "caches", "~/.hermes/config.yaml", "~/.hermes/skills",
            ],
        }

        data_dir_raw = (tc.get("data_dir") or "").strip()
        company_dir = Path(data_dir_raw) if data_dir_raw else None
        _collect_files(staging, manifest,
                       company_dir if company_dir and company_dir.is_dir() else None,
                       tables["libraries"], warnings)

        memory_path = merge_mod._memory_file()
        if memory_path.is_file():
            blocks = merge_mod.extract_memory_blocks(
                memory_path.read_text(encoding="utf-8"), company.get("name") or ""
            )
            memory_dir = staging / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "hermes_memory.md").write_text(
                "\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8"
            )

        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_checksums(staging)

        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(staging).as_posix())

        size = zip_path.stat().st_size
        if size > max_bytes:
            zip_path.unlink(missing_ok=True)
            manual = [
                str(db_path),
                data_dir_raw,
                work_dir,
            ]
            raise PackageTooLargeError(size, max_bytes, [p for p in manual if p])

        return {
            "path": str(zip_path),
            "bytes": size,
            "company": manifest["company"],
            "warnings": warnings,
        }
    except Exception:
        zip_path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
