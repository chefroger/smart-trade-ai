"""单公司导出：DB 行 + 公司目录 + Hermes 公司记忆 -> ZIP。

桌面资料库（可能有几百 GB）只导出元数据，文件由用户按需手动拷贝。
"""

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
    MAX_UNCOMPRESSED_BYTES,
    PACKAGE_FORMAT,
    PackageTooLargeError,
)
from trade.company.transfer import merge as merge_mod
from trade.company.transfer.manifest import sha256_file, write_checksums


def _dir_size(root: Path) -> int:
    """目录内普通文件总字节数；不跟进符号链接，读不了的文件按 0 计。"""
    total = 0
    if not root.is_dir():
        return 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        dirnames[:] = [name for name in dirnames if not (base / name).is_symlink()]
        for name in filenames:
            path = base / name
            if path.is_symlink():
                continue
            try:
                total += path.stat().st_size
            except OSError:
                pass
    return total


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
    """复制普通文件，拒绝符号链接；返回相对路径列表。

    用 `os.walk(followlinks=False)` 而不是 `rglob`：3.13 之前 `rglob` 会跟进
    符号链接目录，等于允许一个指向家目录的链接把公司包撑成整台机器。
    """
    copied: list[str] = []
    if not src.is_dir():
        warnings.append(f"directory missing: {src}")
        return copied
    for root, dirs, files in os.walk(src, followlinks=False):
        root_path = Path(root)
        # 符号链接目录整棵跳过（不进去，也不复制链接本身）
        dirs[:] = [name for name in dirs if not (root_path / name).is_symlink()]
        for name in files:
            path = root_path / name
            if path.is_symlink():
                warnings.append(f"skipped symlink: {path}")
                continue
            if name == ".DS_Store":
                continue
            rel = path.relative_to(src).as_posix()
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied.append(rel)
    return copied


def _collect_files(staging: Path, manifest: dict, company_dir: Path | None,
                   libraries: list[dict], warnings: list[str],
                   *, manual_paths: list[str] | None = None) -> None:
    """把公司数据目录装进包；桌面资料库只写元数据，文件一律不打包。

    桌面目录可能有几百 GB，打包既慢又容易把用户无关文件卷进来；迁移时由
    用户按需自己拷。DB/公司目录/记忆是 Trade 生成的内容，照常导出。
    """
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
        entry = {
            "export_id": export_id,
            "source_id": lib["id"],
            "name": lib.get("name") or "",
            "root_path": str(root),
            # 导入端重建库记录时没有别的地方能取到它；description 是用户可见元数据
            "description": lib.get("description") or "",
            # 桌面资料库文件永远不进包：用户按需手动拷贝
            "files_included": False,
        }
        export_libraries.append(entry)
        if root.is_dir() and _dir_size(root) > 0:
            warnings.append(f"资料库文件未打包，请手动拷贝：{root}")
            if manual_paths is not None:
                manual_paths.append(str(root))
        elif not root.is_dir():
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
    # 调用方给了目标路径时先写同目录临时文件、成功后再原子替换：导出失败不能
    # 先把用户原有的旧包删掉（2026-11-11 审计 O-2）。
    final_zip: Path | None = None
    if dest_zip is None:
        fd, temp_name = tempfile.mkstemp(prefix="trade-company-", suffix=".zip")
        os.close(fd)
        zip_path = Path(temp_name)
    else:
        final_zip = dest_zip
        final_zip.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=".trade-export-", suffix=".zip", dir=str(final_zip.parent)
        )
        os.close(fd)
        zip_path = Path(temp_name)
    warnings: list[str] = []

    # 快照必须放在 staging **之外**：staging 结整棵打进 zip，放里面会把整库
    # （所有公司、客户、对话、license）混进单公司包（2026-11-11 审计 P1-1）。
    snapshot_fd, snapshot_name = tempfile.mkstemp(
        prefix="trade-company-snapshot-", suffix=".db"
    )
    os.close(snapshot_fd)
    snapshot = Path(snapshot_name)

    try:
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
            # 必须在下面 pop("data_dir") 之前取出来：tc 与 tables["trade_company"][0]
            # 是**同一个 dict**，pop 之后这里永远读到空串，company_data 就再也不会
            # 被打包（2026-11-11 审计 P1-2）。
            data_dir_raw = (tc.get("data_dir") or "").strip()

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
                # trial_events 是许可证试用统计，不属于公司业务数据；导入会虚增
                # 新公司的「试用价值小结」计数，因此不导出（2026-11-11 审计 P3）。
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
                "data_dir": data_dir_raw,
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

        # 只认绝对路径：历史脏数据里出现过 "."，Path(".").is_dir() 为真，
        # 会把当前工作目录整棵打进包（迁移时等于泄露无关文件）。
        company_dir: Path | None = None
        if data_dir_raw:
            candidate = Path(data_dir_raw)
            if candidate.is_absolute():
                # 还必须落在 Trade 数据根下：脏数据里出现 "/" 这类绝对路径时，
                # 光看 is_absolute 会把整块文件系统打进包。
                from trade.company import crud as company_crud

                home = Path(company_crud.TRADE_HOME).resolve()
                resolved = candidate.resolve()
                if resolved == home:
                    warnings.append(f"skipped company dir (is TRADE_HOME): {data_dir_raw}")
                else:
                    try:
                        resolved.relative_to(home)
                        company_dir = candidate
                    except ValueError:
                        warnings.append(
                            f"skipped company dir (outside TRADE_HOME): {data_dir_raw}"
                        )
            else:
                warnings.append(f"skipped company dir (not absolute): {data_dir_raw}")
        manual_paths: list[str] = []
        _collect_files(
            staging, manifest,
            company_dir if company_dir and company_dir.is_dir() else None,
            tables["libraries"], warnings,
            manual_paths=manual_paths,
        )

        memory_path = merge_mod._memory_file()
        if memory_path.is_file():
            blocks = merge_mod.extract_memory_blocks(
                memory_path.read_text(encoding="utf-8-sig"), company.get("name") or ""
            )
            memory_dir = staging / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "hermes_memory.md").write_text(
                "\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8"
            )

        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 解压后总量也必须在本机导入上限内 —— 否则会导出一个「本机能生成、
        # 却永远导不回去」的包（文本类内容 1GiB 压缩包可膨胀到 2GiB 以上）。
        # 放在算 checksums 之前：超限时不必先把整棵目录哈希一遍。
        staging_files = [p for p in staging.rglob("*") if p.is_file()]
        unpacked_bytes = sum(p.stat().st_size for p in staging_files)
        if unpacked_bytes > MAX_UNCOMPRESSED_BYTES:
            raise PackageTooLargeError(
                unpacked_bytes, MAX_UNCOMPRESSED_BYTES,
                [p for p in (str(db_path), data_dir_raw, work_dir) if p],
            )
        write_checksums(staging)

        zip_path.parent.mkdir(parents=True, exist_ok=True)
        # 重新枚举一次：checksums.sha256 是刚写进去的
        zip_files = [p for p in staging.rglob("*") if p.is_file()]
        # 源文件 mtime 早于 1980 时 zipfile 默认抛 ValueError；夹紧即可，不必阻断导出
        with zipfile.ZipFile(
            zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6,
            strict_timestamps=False,
        ) as zf:
            for path in sorted(zip_files):
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

        if final_zip is not None:
            os.replace(zip_path, final_zip)
            zip_path = final_zip

        return {
            "path": str(zip_path),
            "bytes": size,
            "company": manifest["company"],
            "warnings": warnings,
            "manual_paths": manual_paths,
        }
    except Exception:
        zip_path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        # 快照在 staging 外，须单独清理；-wal/-shm 是 SQLite 可能留下的旁文件
        for suffix in ("", "-wal", "-shm"):
            Path(str(snapshot) + suffix).unlink(missing_ok=True)
