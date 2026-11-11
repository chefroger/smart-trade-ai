"""公司数据导出/导入回归测试（P1）。"""

from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path

import pytest

from trade import database
from trade.company import crud
from trade.company.transfer import AmbiguousCompanyError, InvalidPackageError, PackageTooLargeError
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
    (company_dir / "products.md").write_text("# Products\nWidget\n", encoding="utf-8")

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
        assert (Path(data_dir) / "companies" / slug / "products.md").is_file()

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
        assert Path(files[0]["file"]).is_file()
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


def test_package_too_large_cleans_up(desktop, tmp_path):
    source = crud.create(_unique("Large"))
    package = tmp_path / "large.zip"
    with pytest.raises(PackageTooLargeError):
        export_company(source["id"], package, max_bytes=10)
    assert not package.exists()


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
