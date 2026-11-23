"""导入预检 / 确认两阶段 API 回归测试（2026-11-20 审计 C2 T3）。

覆盖：预检只读、缺决定 409 不消耗 upload_id、完整决定 202、
过期 410、未知 source_id 400、并发确认只能开始一次导入。
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from trade import database
from trade.company import crud
from trade.company.transfer.exporter import export_company


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _ensure_db():
    database.init_db()


@pytest.fixture(autouse=True)
def _cleanup_companies(_ensure_db):
    """本文件会创建公司；清掉它们，避免污染依赖公司数的其它测试。"""
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


@pytest.fixture()
def setup_mocks():
    """CI 不装 Hermes，导入 trade.api 前先 mock 掉顶层模块。"""
    with patch.dict(sys.modules, {
        "hermes_cli": MagicMock(),
        "hermes_cli.config": MagicMock(),
        "hermes_cli.auth": MagicMock(),
        "hermes_cli.env_loader": MagicMock(),
        "hermes_cli.models": MagicMock(),
        "hermes_constants": MagicMock(),
        "run_agent": MagicMock(),
    }):
        import hermes_cli
        hermes_cli.__version__ = "0.13.0"
        yield


def _clear_pending(transfer) -> None:
    """清空预检登记表，并删掉对应的临时包。"""
    with transfer._PENDING_LOCK:
        entries = list(transfer._PENDING.values())
        transfer._PENDING.clear()
    for entry in entries:
        path = entry.get("zip_path")
        # 条目记录了临时包：一并删掉，避免测试残留
        if path is not None:
            Path(path).unlink(missing_ok=True)


@pytest.fixture()
def api_client(desktop, setup_mocks, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from trade.api import deps, transfer

    deps.set_session_token("test-token")
    deps._ACTIVE_COMPANY.clear()
    # 导入是付费能力；本文件只测两阶段流程，直接放行。
    monkeypatch.setattr("trade.api.transfer._require_paid_feature", lambda: None)

    # 限流窗口是 300 秒：不清空的话第二个用例必然 429。
    transfer._RATE.clear()
    with transfer._JOB_LOCK:
        transfer._JOBS.clear()
    _clear_pending(transfer)

    app = FastAPI()
    app.include_router(transfer.router, prefix="/api/trade")
    return TestClient(app), "test-token"


def _insert_customer(company_id: int, name: str, **fields) -> int:
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


def _customer_names(company_id: int) -> list[str]:
    conn = database.get_connection()
    try:
        return [
            row[0] for row in conn.execute(
                "SELECT name FROM customers WHERE company_id = ? ORDER BY id",
                (company_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _delete_company(company_id: int) -> None:
    """模拟「包来自另一台机器」：导出后删掉源公司记录。"""
    conn = database.get_connection()
    try:
        conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        conn.commit()
    finally:
        conn.close()


def _conflict_package(tmp_path: Path) -> tuple[Path, dict]:
    """导出含一个同名客户的包（源公司随后删除），并建好目标公司。"""
    name = _unique("API Preflight")
    source = crud.create(name)
    _insert_customer(source["id"], "Acme", contact="Bob")
    package = tmp_path / f"{uuid.uuid4().hex}.zip"
    export_company(source["id"], package)
    _delete_company(source["id"])

    target = crud.create(name)
    # 大小写不同才算冲突；完全同名现在按精确匹配直接合并
    _insert_customer(target["id"], "ACME", contact="Alice")
    return package, target


def _upload(client, token: str, package: Path, *, preflight: bool = True):
    with open(package, "rb") as fh:
        return client.post(
            "/api/trade/companies/import-package",
            headers={"X-Hermes-Session-Token": token},
            data={"preflight": "true" if preflight else "false"},
            files={"file": (package.name, fh, "application/zip")},
        )


def _confirm(client, token: str, upload_id: str, body: dict):
    return client.post(
        f"/api/trade/companies/import-package/{upload_id}/confirm",
        headers={"X-Hermes-Session-Token": token},
        json=body,
    )


def _wait_job(job_id: str) -> dict:
    from trade.api import transfer

    for _ in range(100):
        time.sleep(0.05)
        job = transfer._JOBS.get(job_id)
        # 后台线程已给出终态（成功或失败）：停止轮询
        if job and job.get("status") in ("done", "error"):
            return dict(job)
    raise AssertionError(f"job {job_id} did not finish: {transfer._JOBS.get(job_id)}")


class TestPreflightUpload:
    def test_preflight_returns_conflicts_without_writing(self, api_client, tmp_path):
        """预检只读：返回冲突、不增加客户行、不创建导入任务。"""
        from trade.api import transfer

        client, token = api_client
        package, target = _conflict_package(tmp_path)
        before_rows = _customer_rows(target["id"])
        before_jobs = len(transfer._JOBS)

        resp = _upload(client, token, package)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["upload_id"]
        assert body["expires_in"] == transfer._PENDING_TTL
        assert body["conflicts"], body
        assert body["conflicts"][0]["source_name"] == "Acme"
        assert body["company"]["target"]["id"] == target["id"]
        assert _customer_rows(target["id"]) == before_rows
        assert len(transfer._JOBS) == before_jobs


class TestConfirmImport:
    def test_missing_decisions_do_not_consume_upload(self, api_client, tmp_path):
        """缺决定 → 409 且列 missing；补全后同一 upload_id 仍能确认。"""
        from trade.api import transfer

        client, token = api_client
        package, target = _conflict_package(tmp_path)
        upload = _upload(client, token, package).json()
        upload_id = upload["upload_id"]
        conflicts = upload["conflicts"]

        resp = _confirm(client, token, upload_id, {})

        assert resp.status_code == 409, resp.text
        assert resp.json()["missing"] == [conflicts[0]["source_id"]]
        assert upload_id in transfer._PENDING

        decisions = [
            {"source_id": c["source_id"], "action": "create"} for c in conflicts
        ]
        retry = _confirm(
            client, token, upload_id, {"customer_decisions": decisions}
        )

        assert retry.status_code == 202, retry.text
        job = _wait_job(retry.json()["job_id"])
        assert job["status"] == "done", job
        assert len(_customer_rows(target["id"])) == 2

    def test_full_decisions_start_import_and_create_suffixed_customer(
        self, api_client, tmp_path
    ):
        """完整决定 → 202；后台导入完成，同名客户另建且带 (2) 后缀。"""
        client, token = api_client
        package, target = _conflict_package(tmp_path)
        upload = _upload(client, token, package).json()

        resp = _confirm(
            client, token, upload["upload_id"],
            {"default_action": "create"},
        )

        assert resp.status_code == 202, resp.text
        assert resp.json()["status"] == "queued"
        job = _wait_job(resp.json()["job_id"])
        assert job["status"] == "done", job
        assert _customer_names(target["id"]) == ["ACME", "Acme (2)"]

    def test_expired_upload_returns_410(self, api_client, tmp_path):
        """过期条目 → 410，并从登记表移除。"""
        from trade.api import transfer

        client, token = api_client
        package, _target = _conflict_package(tmp_path)
        upload_id = _upload(client, token, package).json()["upload_id"]

        with transfer._PENDING_LOCK:
            transfer._PENDING[upload_id]["expires_at"] = time.time() - 1

        resp = _confirm(client, token, upload_id, {"default_action": "merge"})

        assert resp.status_code == 410, resp.text
        assert upload_id not in transfer._PENDING

    def test_unknown_source_id_returns_400(self, api_client, tmp_path):
        """决定里出现预检之外的 source_id → 400，且不消耗 upload_id。"""
        from trade.api import transfer

        client, token = api_client
        package, _target = _conflict_package(tmp_path)
        upload_id = _upload(client, token, package).json()["upload_id"]

        resp = _confirm(
            client, token, upload_id,
            {"customer_decisions": [{"source_id": 999999, "action": "merge"}]},
        )

        assert resp.status_code == 400, resp.text
        assert upload_id in transfer._PENDING

    def test_concurrent_confirm_only_starts_one_import(self, api_client, tmp_path):
        """同一 upload_id 连续确认两次：第二次 409/410，不重复起导入任务。"""
        from trade.api import transfer

        client, token = api_client
        package, target = _conflict_package(tmp_path)
        upload = _upload(client, token, package).json()
        upload_id = upload["upload_id"]
        body = {"default_action": "create"}
        before_jobs = len(transfer._JOBS)

        first = _confirm(client, token, upload_id, body)
        second = _confirm(client, token, upload_id, body)

        assert first.status_code == 202, first.text
        assert second.status_code in (409, 410), second.text
        assert len(transfer._JOBS) == before_jobs + 1
        job = _wait_job(first.json()["job_id"])
        assert job["status"] == "done", job
        assert len(_customer_rows(target["id"])) == 2

    def test_string_customer_ids_can_be_confirmed(self, api_client, tmp_path):
        """审计 O-5：包内客户 id 是字符串时，预检归一化、确认不再恒 400。"""
        import hashlib
        import json
        import zipfile

        client, token = api_client
        package, target = _conflict_package(tmp_path)
        # 把包内 customers.json 的 id 改成字符串（模拟手改/第三方导出）
        with zipfile.ZipFile(package) as zf:
            items = [(info, zf.read(info.filename)) for info in zf.infolist()]
        rows = json.loads(
            next(data for info, data in items if info.filename == "db/customers.json")
        )
        for row in rows:
            row["id"] = str(row["id"])
        new_data = json.dumps(rows).encode("utf-8")
        new_hash = hashlib.sha256(new_data).hexdigest()
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as zf:
            for info, data in items:
                if info.filename == "db/customers.json":
                    data = new_data
                elif info.filename == "checksums.sha256":
                    lines = data.decode("utf-8").splitlines()
                    data = ("\n".join(
                        f"{new_hash}  db/customers.json"
                        if line.endswith("  db/customers.json") else line
                        for line in lines
                    ) + "\n").encode("utf-8")
                zf.writestr(info, data)

        upload = _upload(client, token, package).json()
        source_id = upload["conflicts"][0]["source_id"]
        assert isinstance(source_id, int), "预检必须把字符串 id 归一化成 int"

        resp = _confirm(
            client, token, upload["upload_id"],
            {"customer_decisions": [{"source_id": source_id, "action": "create"}]},
        )

        assert resp.status_code == 202, resp.text
        job = _wait_job(resp.json()["job_id"])
        assert job["status"] == "done", job
        assert _customer_names(target["id"]) == ["ACME", "Acme (2)"]


def test_non_preflight_upload_is_rejected(api_client, tmp_path):
    """旧的一步导入没有逐对决定：直接 409 要求先预检（审计 P2 残留）。"""
    client, token = api_client
    resp = client.post(
        "/api/trade/companies/import-package",
        headers={"X-Hermes-Session-Token": token},
        data={"preflight": "false"},
        files={"file": ("x.zip", b"not-a-zip", "application/zip")},
    )
    assert resp.status_code == 409
    assert "预检" in resp.json()["detail"]
