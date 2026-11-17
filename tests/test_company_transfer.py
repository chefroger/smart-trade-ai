"""公司数据导出/导入回归测试（P1）。"""

from __future__ import annotations

import json
import os
import uuid
import zipfile
from pathlib import Path

import pytest

from trade import database
from trade.company import crud
from trade.company.transfer import (
    FORMAT_VERSION,
    PACKAGE_FORMAT,
    AmbiguousCompanyError,
    InvalidPackageError,
    PackageTooLargeError,
    TransferError,
)
from trade.company.transfer.exporter import export_company
from trade.company.transfer.importer import import_company
from trade.company.transfer.paths import PathMapper


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _ensure_db():
    database.init_db()


@pytest.fixture(autouse=True)
def _cleanup_companies(_ensure_db):
    """本文件会创建多个公司；清掉它们，避免污染依赖公司数的 cron 测试。"""
    yield
    conn = database.get_connection()
    try:
        for table in ("usage_ledger", "trial_events", "cron_job_companies",
                      "doc_extractions"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM companies")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def desktop(tmp_path, monkeypatch):
    """把工作目录固定到临时 Desktop，避免测试写真实桌面。"""
    root = tmp_path / "Desktop"
    root.mkdir(parents=True, exist_ok=True)

    def fake_setup(name, slug, suggested_name=""):
        path = root / f"{name}-{slug}"
        path.mkdir(parents=True, exist_ok=True)
        return path, True

    monkeypatch.setattr("trade.company.workdir._setup_work_directory", fake_setup)
    monkeypatch.setattr("trade.company.workdir._get_desktop_path", lambda: root)
    return root


def _insert_sample_rows(company_id: int) -> dict:
    conn = database.get_connection()
    try:
        conn.execute(
            "INSERT INTO customers (company_id, name, contact, extra1, extra2) "
            "VALUES (?, ?, ?, ?, ?)",
            (company_id, "Northwind", "Michael",
             json.dumps({"tier": "A"}), json.dumps({"email": "m@example.com"})),
        )
        customer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        lib = conn.execute(
            "SELECT * FROM libraries WHERE company_id = ? ORDER BY id LIMIT 1",
            (company_id,),
        ).fetchone()
        library_id = lib[0]
        library_root = Path(lib[3])
        library_root.mkdir(parents=True, exist_ok=True)
        (library_root / "order.pdf").write_bytes(b"%PDF-1.4 test")
        conn.execute(
            "INSERT INTO conversations "
            "(company_id, customer_id, library_id, query, response, context, files_read) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (company_id, customer_id, library_id, "报价多少", "USD 1.00", "daily",
             json.dumps([{"file": str(library_root / "order.pdf")}])),
        )
        conn.execute(
            "INSERT INTO orders (company_id, customer_id, order_no, product_name, "
            "quantity, unit, unit_price, currency, total_amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (company_id, customer_id, "PO-1", "Widget", 100, "pcs", 1.0, "USD", 100.0),
        )
        order_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO order_items (order_id, position, product_name, quantity, "
            "unit, unit_price, currency, total_amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (order_id, 0, "Widget", 100, "pcs", 1.0, "USD", 100.0),
        )
        conn.execute(
            "INSERT INTO customer_libraries (customer_id, library_id) VALUES (?, ?)",
            (customer_id, library_id),
        )
        conn.commit()
        return {
            "customer_id": customer_id,
            "library_id": library_id,
            "library_root": library_root,
            "order_id": order_id,
        }
    finally:
        conn.close()


def _company_dir(created: dict) -> Path:
    conn = database.get_connection()
    try:
        row = conn.execute(
            "SELECT data_dir FROM trade_companies WHERE company_id = ?",
            (created["id"],),
        ).fetchone()
        assert row is not None
        return Path(row[0]) / "companies" / str(created["slug"])
    finally:
        conn.close()


def test_roundtrip_creates_company_and_rewrites_paths(desktop, tmp_path):
    name = _unique("Acme Transfer")
    source = crud.create(name)
    _insert_sample_rows(source["id"])
    company_dir = _company_dir(source)
    # 写有特征的内容：模板骨架自带 products.md，只断言 is_file() 会假绿
    marker = f"# Products\nUNIQUE-{uuid.uuid4().hex}\n"
    (company_dir / "products.md").write_text(marker, encoding="utf-8")

    package = tmp_path / "acme.zip"
    export_result = export_company(source["id"], package)
    assert export_result["bytes"] > 0
    assert package.is_file()

    crud.update(source["id"], name=name + " Old")
    report = import_company(package)
    assert report["mode"] == "created"
    assert report["target"]["name"] == name

    target_id = report["target"]["id"]
    conn = database.get_connection()
    try:
        target = conn.execute(
            "SELECT c.slug, t.data_dir FROM companies c "
            "JOIN trade_companies t ON t.company_id = c.id WHERE c.id = ?",
            (target_id,),
        ).fetchone()
        data_dir, slug = target[1], target[0]
        assert data_dir != "."
        imported = (Path(data_dir) / "companies" / slug / "products.md")
        assert imported.is_file()
        # 内容级断言：company_data 没进包时这里会读到模板默认内容而不是 marker
        assert imported.read_text(encoding="utf-8") == marker

        customer = conn.execute(
            "SELECT * FROM customers WHERE company_id = ?", (target_id,)
        ).fetchone()
        assert customer["name"] == "Northwind"
        conversation = conn.execute(
            "SELECT * FROM conversations WHERE company_id = ?", (target_id,)
        ).fetchone()
        files = json.loads(conversation["files_read"])
        # PathMapper 统一输出正斜杠；Windows 上 str(desktop) 是反斜杠
        assert files and files[0]["file"].replace("\\", "/").startswith(
            str(desktop).replace("\\", "/")
        )
        # 桌面资料库文件不随包迁移（用户按需手动拷贝），路径仍要改写到目标机
        assert not Path(files[0]["file"]).is_file()
        assert conn.execute(
            "SELECT COUNT(*) FROM orders WHERE company_id = ?", (target_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM order_items oi JOIN orders o ON o.id = oi.order_id "
            "WHERE o.company_id = ?", (target_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM customer_libraries cl JOIN customers c "
            "ON c.id = cl.customer_id WHERE c.company_id = ?", (target_id,)
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_chinese_text_and_filenames_survive_cross_platform_package(desktop, tmp_path):
    """中文公司名/客户/文件名在包里必须是 UTF-8，换平台导入后一字不差。

    跨平台的关键在 ZIP 条目名：非 ASCII 名必须带 UTF-8 标志位（0x800），
    否则 Python 在 Windows 上会按 CP437 解码成乱码。JSON/checksums/MEMORY
    则必须显式 UTF-8 写入和读取。本用例在 CI 的 macOS / Windows / Linux
    三平台各跑一遍。
    """
    name = _unique("宁波华翔进出口")
    # 用 ASCII slug 建公司：中文名经 _slugify 后含 CJK，会被 _validate_slug 拒绝
    source = crud.create(name, slug=_unique("ningbo"))
    conn = database.get_connection()
    try:
        conn.execute(
            "INSERT INTO customers (company_id, name) VALUES (?, ?)",
            (source["id"], "宁波华翔采购部"),
        )
        customer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        lib = conn.execute(
            "SELECT * FROM libraries WHERE company_id = ? ORDER BY id LIMIT 1",
            (source["id"],),
        ).fetchone()
        library_id = lib[0]
        library_root = Path(lib[3])
        library_root.mkdir(parents=True, exist_ok=True)
        chinese_file = library_root / "报价单-中文.pdf"
        chinese_file.write_bytes("中文内容，含税率 13%".encode())
        # 桌面资料库文件不随包走；用公司目录里的中文文件验证 ZIP 中文名/内容编码
        company_zh = _company_dir(source) / "中文资料.md"
        company_zh.write_text("公司简介：中文内容必须原样保留。\n", encoding="utf-8")
        conn.execute(
            "INSERT INTO conversations "
            "(company_id, customer_id, library_id, query, response, context, files_read) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source["id"], customer_id, library_id,
             "这批货含税价多少？", "含税 USD 1.20", "报价",
             json.dumps([{"file": str(chinese_file)}], ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()

    package = tmp_path / "chinese.zip"
    export_company(source["id"], package)

    with zipfile.ZipFile(package) as zf:
        names = zf.namelist()
        assert any("中文资料.md" in entry for entry in names)
        # 桌面资料库文件永不进包
        assert not any(entry.startswith("libraries/") for entry in names)
        # 非 ASCII 条目必须声明 UTF-8（否则 Windows 解压/读取会乱码）
        for info in zf.infolist():
            if any(ord(ch) > 127 for ch in info.filename):
                assert info.flag_bits & 0x800, f"missing UTF-8 flag: {info.filename}"
        # 所有文本载荷都必须能严格按 UTF-8 解码
        for entry in names:
            if entry.endswith((".json", ".md")) or entry == "checksums.sha256":
                zf.read(entry).decode("utf-8")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["company"]["name"] == name
        checksums = zf.read("checksums.sha256").decode("utf-8")
        assert "中文资料.md" in checksums

    report = import_company(package, force_new=True)
    target_id = report["target"]["id"]
    assert report["target"]["name"] == name

    conn = database.get_connection()
    try:
        assert conn.execute(
            "SELECT name FROM customers WHERE company_id = ?", (target_id,)
        ).fetchone()[0] == "宁波华翔采购部"
        query, response, files_read = conn.execute(
            "SELECT query, response, files_read FROM conversations "
            "WHERE company_id = ?", (target_id,)
        ).fetchone()
        assert (query, response) == ("这批货含税价多少？", "含税 USD 1.20")
        rewritten = json.loads(files_read)[0]["file"]
        assert "报价单-中文.pdf" in rewritten
        # 桌面资料库文件不随包走，导入后需用户自己拷
        assert not Path(rewritten).is_file()
        roots = [
            Path(row[0]) for row in conn.execute(
                "SELECT root_path FROM libraries WHERE company_id = ?", (target_id,)
            )
        ]
        data_dir, slug = conn.execute(
            "SELECT t.data_dir, c.slug FROM trade_companies t "
            "JOIN companies c ON c.id = t.company_id WHERE t.company_id = ?",
            (target_id,),
        ).fetchone()
    finally:
        conn.close()

    assert roots and not any((root / "报价单-中文.pdf").exists() for root in roots)
    # Trade 生成的公司目录内容必须随包迁移（中文文件名+内容都不变）
    assert (Path(data_dir) / "companies" / slug / "中文资料.md").read_text(
        encoding="utf-8"
    ) == "公司简介：中文内容必须原样保留。\n"


def test_orders_without_order_no_are_idempotent(desktop, tmp_path):
    """无 order_no 的订单靠签名去重：源/目标 customer_id 与明细自增 ID 不同，
    签名必须用重映射后的客户 ID 并剔除自增字段，否则重复导入会翻倍。"""
    name = _unique("No Order No")
    source = crud.create(name)
    target = crud.create(name)
    conn = database.get_connection()
    try:
        conn.execute(
            "INSERT INTO customers (company_id, name) VALUES (?, ?)",
            (source["id"], "Buyer"),
        )
        customer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO orders (company_id, customer_id, order_no, product_name, "
            "quantity, unit, unit_price, currency, total_amount) "
            "VALUES (?, ?, '', ?, ?, ?, ?, ?, ?)",
            (source["id"], customer_id, "No-No Widget", 5, "pcs", 2.0, "USD", 10.0),
        )
        order_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO order_items (order_id, position, product_name, quantity, "
            "unit, unit_price, currency, total_amount) VALUES (?, 0, ?, ?, ?, ?, ?, ?)",
            (order_id, "No-No Widget", 5, "pcs", 2.0, "USD", 10.0),
        )
        conn.commit()
    finally:
        conn.close()

    package = tmp_path / "no-no.zip"
    export_company(source["id"], package)
    first = import_company(package, target_company_id=target["id"])
    second = import_company(package, target_company_id=target["id"])
    assert first["tables"]["orders"]["inserted"] == 1
    assert second["tables"]["orders"]["inserted"] == 0

    conn = database.get_connection()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM orders WHERE company_id = ?", (target["id"],)
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_newer_schema_package_is_rejected(desktop, tmp_path):
    """包 schema 比本机新时拒绝导入，避免新字段被静默丢掉。"""
    source = crud.create(_unique("New Schema"))
    package = tmp_path / "schema.zip"
    export_company(source["id"], package)

    newer = tmp_path / "newer.zip"
    with zipfile.ZipFile(package) as src, zipfile.ZipFile(newer, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == "manifest.json":
                manifest = json.loads(data)
                manifest["schema_version"] = 999999
                data = json.dumps(manifest).encode("utf-8")
            dst.writestr(info, data)

    with pytest.raises(InvalidPackageError) as exc:
        import_company(newer)
    assert "更新版本" in str(exc.value)


@pytest.mark.skipif(os.name == "nt", reason="Windows 创建目录符号链接需要额外权限")
def test_export_does_not_follow_symlinked_directories(desktop, tmp_path):
    """python 3.13 前 rglob 会跟进符号链接目录：一个链接就能把家目录打进包。"""
    source = crud.create(_unique("Symlink"))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("OUTSIDE-SECRET", encoding="utf-8")
    link = _company_dir(source) / "linkdir"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink not supported here")

    package = tmp_path / "symlink.zip"
    export_company(source["id"], package)
    with zipfile.ZipFile(package) as zf:
        blob = b"".join(zf.read(name) for name in zf.namelist())
    assert b"OUTSIDE-SECRET" not in blob


def test_desktop_library_files_are_never_packed(desktop, tmp_path):
    """桌面资料库文件永不进包（可能有几百 GB），只打包 DB/公司目录/记忆。"""
    source = crud.create(_unique("Big Desktop"))
    rows = _insert_sample_rows(source["id"])

    package = tmp_path / "big-desktop.zip"
    result = export_company(source["id"], package)

    assert package.is_file()
    assert result["manual_paths"] == [str(rows["library_root"])]
    with zipfile.ZipFile(package) as zf:
        names = zf.namelist()
        assert "db/customers.json" in names
        assert "db/conversations.json" in names
        assert not any(name.startswith("libraries/") for name in names)
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert any("手动拷贝" in warning for warning in manifest["warnings"])
    assert manifest["paths"]["libraries"][0]["files_included"] is False

    report = import_company(package, force_new=True)
    lib_stats = report["tables"]["libraries"]
    assert lib_stats["skipped"] >= 1
    assert any("未包含在包中" in warning for warning in report["warnings"])

    conn = database.get_connection()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM customers WHERE company_id = ?", (report["target"]["id"],)
        ).fetchone()[0] == 1
        roots = [Path(row[0]) for row in conn.execute(
            "SELECT root_path FROM libraries WHERE company_id = ?",
            (report["target"]["id"],),
        )]
    finally:
        conn.close()
    assert roots and not any((root / "order.pdf").exists() for root in roots)


def test_export_package_excludes_whole_database_snapshot(desktop, tmp_path):
    """只导出本公司：包内不能出现整库快照（2026-11-11 审计 P1-1）。

    导出内部会用 snapshot_db 做一致性快照；快照若落在 staging 里会被原样
    打进 zip，等于把全部公司、客户、license 一起交出去。
    """
    source = crud.create(_unique("Export Only"))
    other = crud.create(_unique("Other Company"))
    secret = "SECRET-B-CUSTOMER-" + uuid.uuid4().hex
    conn = database.get_connection()
    try:
        conn.execute(
            "INSERT INTO customers (company_id, name) VALUES (?, ?)",
            (other["id"], secret),
        )
        conn.commit()
    finally:
        conn.close()

    package = tmp_path / "single.zip"
    export_company(source["id"], package)

    with zipfile.ZipFile(package) as zf:
        names = zf.namelist()
        assert not any(Path(name).name.startswith("snapshot.db") for name in names)
        blob = b"".join(zf.read(name) for name in names)
    assert secret.encode("utf-8") not in blob


def test_manifest_export_id_traversal_is_rejected(tmp_path):
    """manifest 里的 export_id 会拼进 staging 路径，必须拒路径逃逸（P2-1）。"""
    manifest = {
        "format": PACKAGE_FORMAT,
        "format_version": FORMAT_VERSION,
        "company": {"name": "Evil"},
        "tables": {},
        "paths": {"libraries": [{"export_id": "../../victim"}]},
    }
    package = tmp_path / "evil-manifest.zip"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("checksums.sha256", "")

    with pytest.raises(InvalidPackageError):
        import_company(package)


def test_merge_file_failure_rolls_back_db(desktop, tmp_path, monkeypatch):
    """文件拷贝在 commit 之前：失败必须回滚 DB，不能留下半合并状态（P1-1）。"""
    from trade.company.transfer import importer as importer_module

    name = _unique("Merge Rollback")
    source = crud.create(name)
    _insert_sample_rows(source["id"])
    target = crud.create(name)
    conn = database.get_connection()
    try:
        libs_before = conn.execute(
            "SELECT COUNT(*) FROM libraries WHERE company_id = ?", (target["id"],)
        ).fetchone()[0]
    finally:
        conn.close()
    package = tmp_path / "merge.zip"
    export_company(source["id"], package)

    def boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(importer_module, "_merge_copy", boom)

    with pytest.raises(RuntimeError):
        import_company(package, target_company_id=target["id"])

    conn = database.get_connection()
    try:
        # 客户/对话等 DB 变更必须整体回滚（库记录恢复导入前数量）
        assert conn.execute(
            "SELECT COUNT(*) FROM customers WHERE company_id = ?", (target["id"],)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM libraries WHERE company_id = ?", (target["id"],)
        ).fetchone()[0] == libs_before
    finally:
        conn.close()


def test_post_commit_failure_reports_backup_path(desktop, tmp_path, monkeypatch):
    """commit 之后的副作用（MEMORY）失败时，错误信息必须带备份路径。"""
    import re

    from trade.company.transfer import importer as importer_module

    hermes = tmp_path / "hermes"
    (hermes / "memories").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    name = _unique("Merge Backup")
    (hermes / "memories" / "MEMORY.md").write_text(
        "## Foreign Trade Assistant — B2B Trade Memory\n\n"
        f"[2026-11-10 10:00] [公司: {name}]\n  Q: q\n  A: a\n\n",
        encoding="utf-8",
    )

    source = crud.create(name)
    _insert_sample_rows(source["id"])
    target = crud.create(name)
    package = tmp_path / "merge.zip"
    export_company(source["id"], package)

    def boom(*_args, **_kwargs):
        raise RuntimeError("memory write failed")

    monkeypatch.setattr(importer_module.merge_mod, "append_memory_blocks", boom)

    with pytest.raises(TransferError) as exc:
        import_company(package, target_company_id=target["id"])

    message = str(exc.value)
    assert "memory write failed" in message
    match = re.search(r"导入前备份：(.+?)）", message)
    assert match, message
    assert Path(match.group(1)).is_file()
    # 此时 DB/文件已提交，客户应已在目标公司里
    conn = database.get_connection()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM customers WHERE company_id = ?", (target["id"],)
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_created_mode_does_not_overwrite_leftover_data_dir(desktop, tmp_path):
    """新建模式遇到上次删除残留的 slug 目录：保留原文件、冲突进归档（P1-2）。"""
    name = _unique("Residue")
    source = crud.create(name)
    company_dir = _company_dir(source)
    marker = f"# Products\nPKG-{uuid.uuid4().hex}\n"
    (company_dir / "products.md").write_text(marker, encoding="utf-8")
    (company_dir / "keep.txt").write_text("LEFTOVER", encoding="utf-8")
    package = tmp_path / "residue.zip"
    export_company(source["id"], package)

    # 模拟「公司记录已删、目录残留」：数据目录还在，DB 行没了
    conn = database.get_connection()
    try:
        conn.execute("DELETE FROM companies WHERE id = ?", (source["id"],))
        conn.commit()
    finally:
        conn.close()
    (company_dir / "products.md").write_text("LOCAL-EDIT", encoding="utf-8")

    report = import_company(package)
    assert report["mode"] == "created"
    # 残留文件不被覆盖；包里的版本进了 import_conflicts
    assert (company_dir / "products.md").read_text(encoding="utf-8") == "LOCAL-EDIT"
    assert (company_dir / "keep.txt").read_text(encoding="utf-8") == "LEFTOVER"
    # 冲突归档在 data_dir/import_conflicts（company_dir 的上一级上一级）
    conflicts = list((company_dir.parent.parent / "import_conflicts").rglob("products.md"))
    assert conflicts and conflicts[0].read_text(encoding="utf-8") == marker
    assert any("残留" in warning for warning in report["warnings"])


def test_same_name_different_slug_merges_and_is_idempotent(desktop, tmp_path):
    name = _unique("Same Name")
    source = crud.create(name)
    target = crud.create(name)  # 同名、不同 slug / id
    assert source["slug"] != target["slug"]
    _insert_sample_rows(source["id"])
    package = tmp_path / "same.zip"
    export_company(source["id"], package)

    before = database.get_connection()
    try:
        before_count = before.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    finally:
        before.close()

    report = import_company(package, target_company_id=target["id"])
    assert report["mode"] == "merged"
    assert report["target"]["slug"] == target["slug"]

    conn = database.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == before_count
        assert conn.execute(
            "SELECT COUNT(*) FROM customers WHERE company_id = ?", (target["id"],)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE company_id = ?", (target["id"],)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM customers WHERE company_id = ?", (source["id"],)
        ).fetchone()[0] == 1
    finally:
        conn.close()

    second = import_company(package, target_company_id=target["id"])
    assert second["tables"]["customers"]["inserted"] == 0
    assert second["tables"]["conversations"]["inserted"] == 0
    assert second["tables"]["orders"]["inserted"] == 0


def test_ambiguous_same_name_requires_target(desktop, tmp_path):
    name = _unique("Ambiguous")
    source = crud.create(name)
    crud.create(name)
    package = tmp_path / "ambiguous.zip"
    export_company(source["id"], package)
    with pytest.raises(AmbiguousCompanyError) as exc:
        import_company(package)
    assert len(exc.value.candidates) == 2


def test_force_new_creates_separate_company(desktop, tmp_path):
    name = _unique("Force New")
    source = crud.create(name)
    existing = crud.create(name)
    package = tmp_path / "force.zip"
    export_company(source["id"], package)
    report = import_company(package, force_new=True)
    assert report["mode"] == "created"
    assert report["target"]["id"] not in {source["id"], existing["id"]}
    assert report["target"]["name"] == name


def test_zip_traversal_is_rejected(tmp_path):
    package = tmp_path / "evil.zip"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("../evil.txt", "x")
        zf.writestr("manifest.json", "{}")
    with pytest.raises(InvalidPackageError):
        import_company(package)


def test_windows_style_backslash_traversal_is_rejected(tmp_path):
    """反斜杠条目先归一化再校验，不能借 Windows 分隔符绕过 ../ 检查。"""
    package = tmp_path / "evil-backslash.zip"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("..\\evil.txt", "x")
        zf.writestr("manifest.json", "{}")
    with pytest.raises(InvalidPackageError):
        import_company(package)


def test_package_too_large_cleans_up(desktop, tmp_path):
    source = crud.create(_unique("Large"))
    package = tmp_path / "large.zip"
    with pytest.raises(PackageTooLargeError):
        export_company(source["id"], package, max_bytes=10)
    assert not package.exists()


def test_export_refuses_package_its_own_importer_would_reject(desktop, tmp_path, monkeypatch):
    """导出的包解压后必须不超过导入上限，否则用户拿到一个永远导不回去的包。"""
    source = crud.create(_unique("Unpacked Limit"))
    monkeypatch.setattr("trade.company.transfer.exporter.MAX_UNCOMPRESSED_BYTES", 10)
    package = tmp_path / "too-big-unpacked.zip"
    with pytest.raises(PackageTooLargeError):
        export_company(source["id"], package)
    assert not package.exists()


def test_export_failure_preserves_existing_destination(desktop, tmp_path, monkeypatch):
    """导出失败不能删掉目标路径上原有的包（审计 O-2）：先写临时文件再原子替换。"""
    source = crud.create(_unique("Preserve"))
    package = tmp_path / "existing.zip"
    package.write_bytes(b"OLD-PACKAGE")

    def boom(*_args, **_kwargs):
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr("trade.post_install.backup.snapshot_db", boom)
    with pytest.raises(RuntimeError):
        export_company(source["id"], package)
    assert package.read_bytes() == b"OLD-PACKAGE"


def test_path_mapper_handles_windows_source():
    mapper = PathMapper([
        (r"C:\Users\alice\Desktop\Acme", "/Users/bob/Desktop/Acme"),
        (r"C:\Users\alice\.trade\acme", "/Users/bob/.trade/acme"),
    ])
    assert mapper.rewrite(r"C:\Users\alice\Desktop\Acme\报价单\a.pdf") == (
        "/Users/bob/Desktop/Acme/报价单/a.pdf"
    )
    assert mapper.rewrite(r"C:\Users\alice\.trade\acme\companies\acme\products.md") == (
        "/Users/bob/.trade/acme/companies/acme/products.md"
    )
    # Windows 路径大小写不敏感：盘符/目录大小写不同也必须命中
    assert mapper.rewrite(r"c:\users\ALICE\Desktop\Acme\a.pdf") == (
        "/Users/bob/Desktop/Acme/a.pdf"
    )
    # UNC 路径的前导 // 不能被归一化压掉
    unc = PathMapper([(r"\\server\share\Acme", "/data/Acme")])
    assert unc.rewrite(r"\\SERVER\share\Acme\a.pdf") == "/data/Acme/a.pdf"
    assert mapper.rewrite("/elsewhere/file.txt") == "/elsewhere/file.txt"


def test_memory_blocks_are_appended_once(desktop, tmp_path, monkeypatch):
    hermes = tmp_path / "hermes"
    (hermes / "memories").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    memory_file = hermes / "memories" / "MEMORY.md"
    memory_file.write_text("", encoding="utf-8")

    source_name = _unique("Memory Source")
    target_name = source_name.upper()
    source = crud.create(source_name)
    target = crud.create(target_name)
    memory_file.write_text(
        "## Foreign Trade Assistant — B2B Trade Memory\n\n"
        f"[2026-11-10 10:00] [公司: {source_name}]\n  Q: q1\n  A: a1\n\n",
        encoding="utf-8",
    )
    package = tmp_path / "memory.zip"
    export_company(source["id"], package)

    report = import_company(package, target_company_id=target["id"])
    assert report["memory"]["added"] == 1
    text = memory_file.read_text(encoding="utf-8")
    assert f"[公司: {target_name}]" in text

    again = import_company(package, target_company_id=target["id"])
    assert again["memory"]["added"] == 0
    assert again["memory"]["skipped"] >= 1
