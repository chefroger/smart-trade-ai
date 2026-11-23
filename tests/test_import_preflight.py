"""导入预检与同名客户决策回归测试（2026-11-20 审计 C2）。"""

from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path

import pytest

from trade import database
from trade.company import crud
from trade.company.transfer import InvalidPackageError
from trade.company.transfer.exporter import export_company
from trade.company.transfer.importer import import_company
from trade.company.transfer.preflight import analyze_package


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _ensure_db():
    database.init_db()


@pytest.fixture(autouse=True)
def _cleanup_companies(_ensure_db):
    """本文件会创建多个公司；清掉它们，避免污染依赖公司数的其它测试。"""
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


def _insert_customer(company_id: int, name: str, **fields) -> int:
    """插一个客户；fields 只接受真实列，extra1/extra2 由调用方传入 JSON 文本。"""
    conn = database.get_connection()
    try:
        row = {"company_id": company_id, "name": name, **fields}
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        conn.execute(
            f"INSERT INTO customers ({cols}) VALUES ({marks})",
            tuple(row.values()),
        )
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        return new_id
    finally:
        conn.close()


def _customer_rows(company_id: int) -> list[tuple]:
    """目标公司全部客户的完整快照（用于断言预检只读）。"""
    conn = database.get_connection()
    try:
        return [
            tuple(row) for row in conn.execute(
                "SELECT * FROM customers WHERE company_id = ? ORDER BY id",
                (company_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _customer_by_name(company_id: int, name: str) -> dict:
    conn = database.get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM customers WHERE company_id = ? AND name = ?",
            (company_id, name),
        ).fetchone()
        return dict(row) if row is not None else {}
    finally:
        conn.close()


def _packaged_customers(package: Path) -> list[dict]:
    """读包内 db/customers.json，拿到源客户 id。"""
    with zipfile.ZipFile(package) as zf:
        return json.loads(zf.read("db/customers.json").decode("utf-8"))


def _delete_company(company_id: int) -> None:
    """模拟「包来自另一台机器」：导出后删掉源公司记录。"""
    conn = database.get_connection()
    try:
        conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        conn.commit()
    finally:
        conn.close()


def _export_and_forget(tmp_path: Path, source: dict) -> Path:
    package = tmp_path / f"{uuid.uuid4().hex}.zip"
    export_company(source["id"], package)
    _delete_company(source["id"])
    return package


def test_preflight_create_mode_when_no_same_name(desktop, tmp_path):
    """目标库没有同名公司：预检给出 create 模式且没有任何客户冲突。"""
    name = _unique("Preflight Solo")
    source = crud.create(name)
    _insert_customer(source["id"], "Only Buyer")
    package = _export_and_forget(tmp_path, source)

    result = analyze_package(package)

    assert result["company"]["mode"] == "create"
    assert result["company"]["target"] is None
    assert result["company"]["source_name"] == name
    assert result["conflicts"] == []
    assert result["summary"] == {
        "customers_total": 1, "conflicts": 0, "new_customers": 1,
    }


def test_preflight_reports_conflict_and_is_read_only(desktop, tmp_path):
    """同名客户要列出来，且预检绝不能改动目标库。"""
    name = _unique("Preflight Same")
    source = crud.create(name)
    source_customer_id = _insert_customer(source["id"], "Acme", contact="Bob")
    package = _export_and_forget(tmp_path, source)

    target = crud.create(name)
    target_customer_id = _insert_customer(
        target["id"], "ACME", contact="Alice",  # 大小写不同才算冲突
        extra1=json.dumps({"tier": "B"}),
    )
    before = _customer_rows(target["id"])
    packaged = _packaged_customers(package)

    result = analyze_package(package)

    assert result["company"]["mode"] == "merge"
    assert result["company"]["target"]["id"] == target["id"]
    assert result["summary"] == {
        "customers_total": 1, "conflicts": 1, "new_customers": 0,
    }
    conflict = result["conflicts"][0]
    assert conflict["source_id"] == packaged[0]["id"] == source_customer_id
    assert conflict["source_name"] == "Acme"
    assert conflict["target_id"] == target_customer_id
    assert conflict["target_name"] == "ACME"
    assert conflict["reason"] == "same_name_case_or_space"
    assert conflict["proposed_new_name"] == "Acme (2)"
    # 预检只读：客户行数与每个字段都必须原样
    assert _customer_rows(target["id"]) == before


def test_proposed_name_skips_taken_suffix(desktop, tmp_path):
    """目标库已有 `Acme (2)` 时，预检要提议 `Acme (3)`。"""
    name = _unique("Preflight Suffix")
    source = crud.create(name)
    _insert_customer(source["id"], "Acme")
    package = _export_and_forget(tmp_path, source)

    target = crud.create(name)
    _insert_customer(target["id"], "ACME")
    _insert_customer(target["id"], "ACME (2)")

    result = analyze_package(package)

    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["proposed_new_name"] == "Acme (3)"


def test_preflight_rejects_mismatched_target_company(desktop, tmp_path):
    """指定 target_company_id 但名字与包内公司不一致：直接报错，不猜。"""
    name = _unique("Preflight Target")
    source = crud.create(name)
    _insert_customer(source["id"], "Acme")
    package = tmp_path / f"{uuid.uuid4().hex}.zip"
    export_company(source["id"], package)

    other = crud.create(_unique("Preflight Other"))

    with pytest.raises(InvalidPackageError):
        analyze_package(package, target_company_id=other["id"])


def test_import_merge_fills_only_empty_fields(desktop, tmp_path):
    """merge 决策：保留目标非空字段，只补空字段（含 extra1/extra2 按 key 补）。"""
    name = _unique("Decision Merge")
    source = crud.create(name)
    _insert_customer(
        source["id"], "Acme", contact="Bob", note="src note",
        extra1=json.dumps({"tier": "A", "country": ""}),
        extra2=json.dumps({"email": "b@example.com"}),
    )
    package = _export_and_forget(tmp_path, source)
    source_customer_id = _packaged_customers(package)[0]["id"]

    target = crud.create(name)
    target_customer_id = _insert_customer(
        target["id"], "Acme", contact="Alice", note="",
        extra1=json.dumps({"tier": "B"}), extra2="",
    )

    report = import_company(
        package,
        target_company_id=target["id"],
        customer_decisions={source_customer_id: "merge"},
    )

    assert report["tables"]["customers"] == {"inserted": 0, "skipped": 1}
    assert len(_customer_rows(target["id"])) == 1
    row = _customer_by_name(target["id"], "Acme")
    assert row["id"] == target_customer_id
    # 目标非空：不动
    assert row["contact"] == "Alice"
    assert json.loads(row["extra1"])["tier"] == "B"
    # 目标为空：用源值补
    assert row["note"] == "src note"
    assert json.loads(row["extra2"]) == {"email": "b@example.com"}
    # 源值为空：不写入（country 键仍不存在，而不是被写成空串）
    assert "country" not in json.loads(row["extra1"])


def test_import_create_decision_adds_suffix(desktop, tmp_path):
    """create 决策：同名客户另建一条，名字带唯一后缀。"""
    name = _unique("Decision Create")
    source = crud.create(name)
    _insert_customer(source["id"], "Acme", contact="Bob")
    package = _export_and_forget(tmp_path, source)
    source_customer_id = _packaged_customers(package)[0]["id"]

    target = crud.create(name)
    _insert_customer(target["id"], "Acme", contact="Alice")

    report = import_company(
        package,
        target_company_id=target["id"],
        customer_decisions={source_customer_id: "create"},
    )

    assert report["tables"]["customers"] == {"inserted": 1, "skipped": 0}
    rows = _customer_rows(target["id"])
    assert len(rows) == 2
    names = [row[2] for row in rows]  # (id, company_id, name, ...)
    assert names == ["Acme", "Acme (2)"]
    new_row = _customer_by_name(target["id"], "Acme (2)")
    assert new_row["contact"] == "Bob"
    # 原有客户完全没变
    assert _customer_by_name(target["id"], "Acme")["contact"] == "Alice"


def test_import_without_decisions_keeps_silent_merge(desktop, tmp_path):
    """customer_decisions=None：保持历史行为（静默合并，客户数不增加）。"""
    name = _unique("Decision None")
    source = crud.create(name)
    _insert_customer(source["id"], "Acme", contact="Bob")
    package = _export_and_forget(tmp_path, source)

    target = crud.create(name)
    _insert_customer(target["id"], "Acme", contact="", note="")

    report = import_company(package, target_company_id=target["id"])

    assert report["tables"]["customers"] == {"inserted": 0, "skipped": 1}
    rows = _customer_rows(target["id"])
    assert len(rows) == 1
    # 历史行为：空 contact 被源值补齐
    assert _customer_by_name(target["id"], "Acme")["contact"] == "Bob"


# ── 审计 O-5 / O-4：畸形包与字符串 id 的容错 ──────────────────────────────


def _rewrite_zip_member(package: Path, member: str, transform) -> None:
    """重写 zip 里某个成员的字节（构造畸形包用），并同步更新校验和。"""
    import hashlib

    with zipfile.ZipFile(package) as zf:
        items = [(info, zf.read(info.filename)) for info in zf.infolist()]
    rewritten = b""
    for info, data in items:
        if info.filename == member:
            rewritten = transform(data)
            break
    # manifest.json 不参与校验；其余成员改了字节就必须改 checksums.sha256，
    # 否则 import_company 会在校验阶段拒绝，测不到目标路径。
    if member != "manifest.json":
        new_hash = hashlib.sha256(rewritten).hexdigest()
        updated = []
        for info, data in items:
            if info.filename == "checksums.sha256":
                lines = data.decode("utf-8").splitlines()
                lines = [
                    f"{new_hash}  {member}" if line.endswith(f"  {member}") else line
                    for line in lines
                ]
                data = ("\n".join(lines) + "\n").encode("utf-8")
            updated.append((info, data))
        items = updated
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as zf:
        for info, data in items:
            zf.writestr(info, rewritten if info.filename == member else data)


def test_preflight_malformed_company_field_does_not_crash(desktop, tmp_path):
    """manifest.company 是字符串时预检不能抛 AttributeError（审计 O-5）。"""
    source = crud.create(_unique("Malformed Company"))
    _insert_customer(source["id"], "Only Buyer")
    package = _export_and_forget(tmp_path, source)

    def _to_string_company(raw: bytes) -> bytes:
        manifest = json.loads(raw.decode("utf-8"))
        manifest["company"] = "oops-not-a-dict"
        return json.dumps(manifest).encode("utf-8")

    _rewrite_zip_member(package, "manifest.json", _to_string_company)

    result = analyze_package(package)

    assert result["company"]["mode"] == "create"
    assert result["company"]["source_name"] == ""
    assert result["summary"]["customers_total"] == 1


def test_preflight_normalizes_string_customer_ids(desktop, tmp_path):
    """包内客户 id 是字符串时，冲突里的 source_id 归一化成 int（审计 O-5）。"""
    name = _unique("String Ids")
    source = crud.create(name)
    source_customer_id = _insert_customer(source["id"], "Acme", contact="Bob")
    package = _export_and_forget(tmp_path, source)

    def _stringify_ids(raw: bytes) -> bytes:
        rows = json.loads(raw.decode("utf-8"))
        for row in rows:
            row["id"] = str(row["id"])
        return json.dumps(rows).encode("utf-8")

    _rewrite_zip_member(package, "db/customers.json", _stringify_ids)
    target = crud.create(name)
    _insert_customer(target["id"], "ACME", contact="Alice")

    conflict = analyze_package(package)["conflicts"][0]

    assert conflict["source_id"] == source_customer_id
    assert isinstance(conflict["source_id"], int)


def test_import_decision_with_string_key_is_honored(desktop, tmp_path):
    """决定用字符串 id 也要生效，不能被静默忽略退回 merge（审计 O-5）。"""
    name = _unique("String Decision")
    source = crud.create(name)
    _insert_customer(source["id"], "Acme", contact="Bob")
    package = _export_and_forget(tmp_path, source)
    source_customer_id = _packaged_customers(package)[0]["id"]

    target = crud.create(name)
    _insert_customer(target["id"], "ACME", contact="Alice")

    report = import_company(
        package,
        target_company_id=target["id"],
        customer_decisions={str(source_customer_id): "create"},
    )

    assert report["tables"]["customers"] == {"inserted": 1, "skipped": 0}
    assert len(_customer_rows(target["id"])) == 2


def test_import_tolerates_non_numeric_inquiry_source_id(desktop, tmp_path):
    """询盘的 source_id 损坏成非数字时导入照常完成（审计 O-4）。"""
    from trade import inquiry

    name = _unique("Bad Source Id")
    source = crud.create(name)
    source_customer_id = _insert_customer(source["id"], "Acme", contact="Bob")
    inquiry.create(source_customer_id, company_id=source["id"], title="询盘 A")
    package = _export_and_forget(tmp_path, source)

    def _corrupt_source_id(raw: bytes) -> bytes:
        rows = json.loads(raw.decode("utf-8"))
        for row in rows:
            row["source_id"] = "not-a-number"
        return json.dumps(rows).encode("utf-8")

    _rewrite_zip_member(package, "db/inquiries.json", _corrupt_source_id)
    target = crud.create(name)
    _insert_customer(target["id"], "Acme", contact="Alice")

    report = import_company(
        package,
        target_company_id=target["id"],
        customer_decisions={source_customer_id: "merge"},
    )

    assert report["tables"]["inquiries"]["inserted"] == 1
    conn = database.get_connection()
    try:
        row = conn.execute(
            "SELECT source_id FROM inquiries WHERE company_id = ?", (target["id"],)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None and row[0] is None


def test_preflight_exact_same_name_is_not_a_conflict(desktop, tmp_path):
    """完全同名的客户按精确匹配直接合并，不再列进冲突（审计 P2 残留）。"""
    name = _unique("Exact Name")
    source = crud.create(name)
    _insert_customer(source["id"], "Acme Trading", contact="Bob")
    package = _export_and_forget(tmp_path, source)

    target = crud.create(name)
    _insert_customer(target["id"], "Acme Trading", contact="Alice")

    result = analyze_package(package)

    assert result["conflicts"] == []
    # 不列冲突 = 导入时会按精确匹配合并，客户数不变
    assert result["summary"]["customers_total"] == 1
