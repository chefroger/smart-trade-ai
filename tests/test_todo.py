"""用户待办（P2-12）：CRUD / 分组 / 跨公司隔离 / 校验 / 客户删除容错 / API。

待办是公司内的独立清单，与定时任务（cron）无关。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def test_db(monkeypatch, tmp_path):
    """临时库 + 隔离桌面工作目录（与 test_visit_plan 同一套做法）。"""
    db_path = tmp_path / "trade.db"

    import trade.database as _db
    original_db = _db._get_db_path
    _db._get_db_path = lambda: db_path

    from trade.database import SCHEMA_SQL, _add_spare_columns
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    _add_spare_columns(conn)
    conn.commit()
    conn.close()

    import trade.company as _co

    def _mock_work_dir(company_name, slug, suggested_name=""):
        work_dir = tmp_path / (suggested_name or company_name)
        work_dir.mkdir(parents=True, exist_ok=True)
        for cat_name, _ in _co._WORK_DIR_CATEGORIES:
            (work_dir / cat_name).mkdir(parents=True, exist_ok=True)
        return work_dir, True

    monkeypatch.setattr(_co, "_setup_work_directory", _mock_work_dir)

    yield db_path

    _db._get_db_path = original_db


@pytest.fixture
def company_id(test_db):
    from trade import company
    return company.create(name="Todo Co", slug="todo-co")["id"]


@pytest.fixture
def customer_id(company_id):
    from trade import customer
    return customer.create("ACME", company_id=company_id)["id"]


class TestTodoCrud:
    def test_create_list_update_delete(self, company_id, customer_id):
        from trade import todo

        created = todo.create_todo(
            company_id,
            title="  给客户报价  ",
            due_date="2026-11-21",
            customer_id=customer_id,
        )
        # 标题去首尾空白后入库
        assert created["title"] == "给客户报价"
        assert created["due_date"] == "2026-11-21"
        assert created["customer_id"] == customer_id
        assert created["customer_name"] == "ACME"
        assert created["done"] == 0
        assert created["done_at"] is None
        assert created["source"] == "manual"

        listing = todo.list_todos(company_id, today="2026-11-21")
        assert any(x["id"] == created["id"] for x in listing["today_items"])

        # done=True 写入 done_at
        done = todo.update_todo(created["id"], company_id=company_id, done=True)
        assert done["done"] == 1
        assert done["done_at"]

        # done=False 清空 done_at
        undone = todo.update_todo(created["id"], company_id=company_id, done=False)
        assert undone["done"] == 0
        assert undone["done_at"] is None

        # 改标题
        renamed = todo.update_todo(created["id"], company_id=company_id, title="改标题")
        assert renamed["title"] == "改标题"

        assert todo.delete_todo(created["id"], company_id=company_id) is True
        assert todo.delete_todo(created["id"], company_id=company_id) is False
        assert todo.update_todo(created["id"], company_id=company_id, title="x") is None

    def test_none_customer_allowed(self, company_id):
        """不关联客户是合法用法。"""
        from trade import todo

        t = todo.create_todo(company_id, title="买咖啡")
        assert t["customer_id"] is None
        assert t["customer_name"] == ""


class TestGrouping:
    def test_overdue_today_and_done_groups(self, company_id, test_db):
        # 日期必须相对「真实今天」：done=True 写的是 now，写死日期会跨天失效
        from datetime import date, timedelta

        from trade import todo

        today = date.today().isoformat()
        # 逾期：due_date < today，按 date 升序
        todo.create_todo(company_id, title="逾期1", due_date=(date.today() - timedelta(days=1)).isoformat())
        todo.create_todo(company_id, title="逾期2", due_date=(date.today() - timedelta(days=30)).isoformat())
        # 今天：due_date == today
        todo.create_todo(company_id, title="今天1", due_date=today)
        # 无期限：归入今天
        todo.create_todo(company_id, title="无期限")
        # 今天完成
        t_done = todo.create_todo(company_id, title="今天完成", due_date="2026-11-01")  # 截止日不影响完成分组
        todo.update_todo(t_done["id"], company_id=company_id, done=True)
        # 过去完成：直接改写 done_at，不应出现在今天的「已完成」里
        t_old = todo.create_todo(company_id, title="旧完成")
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "UPDATE todos SET done = 1, done_at = ? WHERE id = ?",
            ("2020-01-01 09:00:00", t_old["id"]),
        )
        conn.commit()
        conn.close()

        result = todo.list_todos(company_id, today=today)

        assert result["today"] == today
        assert [x["title"] for x in result["overdue"]] == ["逾期2", "逾期1"]
        assert {x["title"] for x in result["today_items"]} == {"今天1", "无期限"}
        assert [x["title"] for x in result["done"]] == ["今天完成"]
        assert result["upcoming"] == []
        assert result["counts"] == {"overdue": 2, "today": 2, "done": 1, "upcoming": 0}

    def test_future_todo_moves_between_groups(self, company_id):
        """未来待办必须出现在 upcoming，且改日期后正确迁移（不能从列表消失）。"""
        from trade import todo

        today = "2026-11-21"
        t = todo.create_todo(company_id, title="明天", due_date="2026-11-22")

        # 明天：只在 upcoming
        result = todo.list_todos(company_id, today=today)
        assert [x["id"] for x in result["upcoming"]] == [t["id"]]
        assert all(x["id"] != t["id"] for x in result["overdue"])
        assert all(x["id"] != t["id"] for x in result["today_items"])

        # 改成今天：移到 today_items
        todo.update_todo(t["id"], company_id=company_id, due_date=today)
        result = todo.list_todos(company_id, today=today)
        assert any(x["id"] == t["id"] for x in result["today_items"])
        assert all(x["id"] != t["id"] for x in result["upcoming"])

        # 改成昨天：移到 overdue
        todo.update_todo(t["id"], company_id=company_id, due_date="2026-11-20")
        result = todo.list_todos(company_id, today=today)
        assert any(x["id"] == t["id"] for x in result["overdue"])
        assert all(x["id"] != t["id"] for x in result["upcoming"])

        # counts 与各组长短一致
        for key, group in (
            ("overdue", "overdue"),
            ("today", "today_items"),
            ("done", "done"),
            ("upcoming", "upcoming"),
        ):
            assert result["counts"][key] == len(result[group])


class TestCrossCompanyIsolation:
    def test_other_company_cannot_see_or_touch(self, company_id):
        from trade import company, todo

        t = todo.create_todo(company_id, title="A 公司待办")
        other = company.create(name="Other Co", slug="other-co")["id"]

        visible = todo.list_todos(other)
        assert all(x["id"] != t["id"] for grp in ("overdue", "today_items", "upcoming", "done")
                   for x in visible[grp])
        assert todo.update_todo(t["id"], company_id=other, title="偷偷改") is None
        assert todo.delete_todo(t["id"], company_id=other) is False
        # 原公司仍能读到，且未被修改
        mine = todo.list_todos(company_id)
        assert any(x["title"] == "A 公司待办" for x in mine["today_items"])


class TestValidation:
    def test_empty_title_rejected(self, company_id):
        from trade import todo

        with pytest.raises(todo.TodoError):
            todo.create_todo(company_id, title="   ")

    def test_title_too_long_rejected(self, company_id):
        from trade import todo

        with pytest.raises(todo.TodoError):
            todo.create_todo(company_id, title="x" * 201)

    def test_invalid_due_date_rejected(self, company_id):
        from trade import todo

        for bad in ("2026/11/21", "2026-13-01", "2026-02-30", "明天"):
            with pytest.raises(todo.TodoError):
                todo.create_todo(company_id, title="x", due_date=bad)

    def test_update_validates_fields(self, company_id):
        from trade import todo

        t = todo.create_todo(company_id, title="合法")
        with pytest.raises(todo.TodoError):
            todo.update_todo(t["id"], company_id=company_id, title="")
        with pytest.raises(todo.TodoError):
            todo.update_todo(t["id"], company_id=company_id, due_date="bad")

    def test_foreign_customer_rejected(self, company_id):
        from trade import company, customer, todo

        other = company.create(name="Other Owner Co", slug="other-owner-co")["id"]
        other_cust = customer.create("别家客户", company_id=other)["id"]

        with pytest.raises(todo.TodoError):
            todo.create_todo(company_id, title="挂别家客户", customer_id=other_cust)

        t = todo.create_todo(company_id, title="自己的")
        with pytest.raises(todo.TodoError):
            todo.update_todo(t["id"], company_id=company_id, customer_id=other_cust)


class TestAsBool:
    def test_string_booleans(self):
        from trade.todo import _as_bool

        for v in ("true", "1", "yes", True, 1):
            assert _as_bool(v) is True
        for v in ("false", "0", "no", "", "False", "No", None, 0):
            assert _as_bool(v) is False
        # 其余非空值按 Python 真值
        assert _as_bool("whatever") is True

    def test_done_accepts_string_false(self, company_id):
        """前端传 "false" 不能被当成真（否则「取消完成」会翻回完成）。"""
        from trade import todo

        t = todo.create_todo(company_id, title="x")
        todo.update_todo(t["id"], company_id=company_id, done=True)
        undone = todo.update_todo(t["id"], company_id=company_id, done="false")
        assert undone["done"] == 0
        assert undone["done_at"] is None


class TestCustomerDeleted:
    def test_todo_survives_and_name_empty(self, company_id, customer_id, test_db):
        from trade import customer, todo

        t = todo.create_todo(company_id, title="跟进", customer_id=customer_id)
        assert customer.delete(customer_id, company_id=company_id) is True

        # 客户被删后待办仍在，关联字段保留原值但取不到名称
        listing = todo.list_todos(company_id)
        row = next(x for x in listing["today_items"] if x["id"] == t["id"])
        assert row["customer_id"] == customer_id
        assert row["customer_name"] == ""


@pytest.fixture
def setup_mocks():
    """Hermes 不在 CI 里，按老规矩 mock 掉（API 层导入用）。"""
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


@pytest.fixture
def api_client(test_db, setup_mocks):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from trade import company
    from trade.api import deps, router

    cid = company.create(name="API Todo Co", slug="api-todo-co")["id"]
    token = "todo-api-token"
    deps.set_session_token(token)
    deps._ACTIVE_COMPANY.pop(token, None)

    app = FastAPI()
    app.include_router(router, prefix="/api/trade")
    return TestClient(app), token, cid


def _h(token: str, cid: int) -> dict[str, str]:
    return {"X-Hermes-Session-Token": token, "X-Company-ID": str(cid)}


class TestTodoApi:
    def test_crud_endpoints(self, api_client):
        client, token, cid = api_client
        h = _h(token, cid)

        r = client.post("/api/trade/todos", json={"title": "打电话"}, headers=h)
        assert r.status_code == 200
        created = r.json()
        assert created["title"] == "打电话"
        tid = created["id"]

        r = client.get("/api/trade/todos", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert any(x["id"] == tid for x in body["today_items"])

        r = client.patch(f"/api/trade/todos/{tid}", json={"done": True}, headers=h)
        assert r.status_code == 200
        assert r.json()["done"] == 1

        r = client.delete(f"/api/trade/todos/{tid}", headers=h)
        assert r.status_code == 200
        assert r.json() == {"ok": True}

        # 已删除再删 → 404
        r = client.delete(f"/api/trade/todos/{tid}", headers=h)
        assert r.status_code == 404

    def test_invalid_input_is_400(self, api_client):
        client, token, cid = api_client
        h = _h(token, cid)

        r = client.post("/api/trade/todos", json={"title": "  "}, headers=h)
        assert r.status_code == 400

        r = client.post(
            "/api/trade/todos", json={"title": "x", "due_date": "bad"}, headers=h
        )
        assert r.status_code == 400

    def test_patch_done_string_false(self, api_client):
        """PATCH 传字符串 "false" 应按未完成处理。"""
        client, token, cid = api_client
        h = _h(token, cid)

        tid = client.post("/api/trade/todos", json={"title": "x"}, headers=h).json()["id"]
        r = client.patch(f"/api/trade/todos/{tid}", json={"done": True}, headers=h)
        assert r.json()["done"] == 1

        r = client.patch(f"/api/trade/todos/{tid}", json={"done": "false"}, headers=h)
        assert r.status_code == 200
        assert r.json()["done"] == 0
        assert r.json()["done_at"] is None

    def test_patch_missing_is_404(self, api_client):
        client, token, cid = api_client
        h = _h(token, cid)

        r = client.patch("/api/trade/todos/99999", json={"title": "x"}, headers=h)
        assert r.status_code == 404
