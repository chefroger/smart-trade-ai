"""P5 回归测试：确定性批量创建与公司隔离删除定时任务 API。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cron_env(monkeypatch, tmp_path):
    """隔离临时数据库、临时 jobs.json 与双公司环境。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    import trade.api.cron as cron_api
    import trade.database as _db

    monkeypatch.setattr(_db, "_get_db_path", lambda: tmp_path / "trade.db")
    monkeypatch.setattr(cron_api, "_JOBS_FILE", tmp_path / "hermes" / "cron" / "jobs.json")
    monkeypatch.setattr(cron_api, "_CRON_OUTPUT", tmp_path / "hermes" / "cron" / "output")
    _db.init_db()

    import trade.company as co

    def _setup(name, slug, suggested_name=""):
        wd = tmp_path / (suggested_name or name)
        wd.mkdir(parents=True, exist_ok=True)
        for cat, _ in co._WORK_DIR_CATEGORIES:
            (wd / cat).mkdir(parents=True, exist_ok=True)
        return wd, True

    monkeypatch.setattr(co, "_setup_work_directory", _setup)
    c1 = co.create(name="Alpha Co", slug="alpha-co")["id"]
    c2 = co.create(name="Beta Co", slug="beta-co")["id"]

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(cron_api.router, prefix="/api/trade")
    client = TestClient(app)
    return {"client": client, "c1": c1, "c2": c2}


def test_batch_create_lists_and_deletes_only_current_company(cron_env):
    """按模板批量创建 3 个 local 任务后列表可见，且清空仅删除当前公司任务。"""
    client = cron_env["client"]
    h1 = {"X-Company-ID": str(cron_env["c1"])}
    h2 = {"X-Company-ID": str(cron_env["c2"])}

    tasks = [
        {"name": "早安简报", "schedule": "0 9 * * 1-5", "prompt": "生成早安简报", "deliver": "local"},
        {"name": "客户跟进", "schedule": "30 10 * * 1-5", "prompt": "检查逾期客户", "deliver": "local"},
        {"name": "晚间总结", "schedule": "0 17 * * 1-5", "prompt": "汇总今日进展", "deliver": "local"},
    ]
    res = client.post("/api/trade/cron/jobs/batch", json={"tasks": tasks}, headers=h1)
    assert res.status_code == 200
    body = res.json()
    assert len(body["created"]) == 3
    assert body["failed"] == []
    assert all(item["deliver"] == "local" for item in body["created"])

    # 公司 2 也建 1 个任务
    res2 = client.post(
        "/api/trade/cron/jobs/batch",
        json={"tasks": [{"name": "Beta 日报", "schedule": "0 8 * * *", "prompt": "Beta", "deliver": "local"}]},
        headers=h2,
    )
    assert res2.status_code == 200
    assert len(res2.json()["created"]) == 1

    # 列表各自隔离
    list1 = client.get("/api/trade/cron/jobs", headers=h1).json()
    list2 = client.get("/api/trade/cron/jobs", headers=h2).json()
    assert len(list1) == 3
    assert len(list2) == 1

    # 清空公司 1 不影响公司 2
    cleared = client.delete("/api/trade/cron/jobs", headers=h1)
    assert cleared.status_code == 200
    assert cleared.json()["deleted_count"] == 3
    assert client.get("/api/trade/cron/jobs", headers=h1).json() == []
    assert len(client.get("/api/trade/cron/jobs", headers=h2).json()) == 1


def test_batch_create_partial_failure_keeps_succeeded_items(cron_env):
    """部分模板字段无效时，已成功的任务保留，失败项清晰返回。"""
    client = cron_env["client"]
    h1 = {"X-Company-ID": str(cron_env["c1"])}
    res = client.post(
        "/api/trade/cron/jobs/batch",
        json={
            "tasks": [
                {"name": "有效任务", "schedule": "0 9 * * *", "prompt": "ok", "deliver": "local"},
                {"name": "", "schedule": "0 9 * * *", "prompt": "bad", "deliver": "local"},
            ]
        },
        headers=h1,
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["created"]) == 1
    assert len(data["failed"]) == 1
    assert len(client.get("/api/trade/cron/jobs", headers=h1).json()) == 1
