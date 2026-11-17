# trade 邮箱绑定（只读 IMAP）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户绑定邮箱（IMAP 只读），手动拉取收件箱，按客户地址精确匹配，在客户卡片墙展示邮件。

**Architecture:** `trade/mailbox.py`（imaplib 只读）+ `trade/mailbox_store.py`（secrets / CRUD / 匹配入库）+ `trade/api/mailboxes.py`（session 鉴权、无公司隔离）+ 前端邮箱面板与卡片墙接线。三张新表 `mailboxes` / `emails` / `email_matches`；凭证在 DB 同目录 `mailbox_secrets.json`。

**Tech Stack:** Python 标准库 `imaplib` / `email`、FastAPI、SQLite、vanilla JS SPA（S-01）。零新 pip 依赖。

> **实现变更（2026-11-17，审计后）**：存储形态已从本文的「三表 + `email_matches`
> 关联表」改为 **`emails` 两列**（`company_id` / `customer_id`，均可空）。
> 决策：Lau 2026-11-17 定。`email_matches` 表不再创建；一封邮件只挂一个客户
> （多命中时取 `find_customer_matches()` 的第一对），未匹配到客户的邮件照样入库、
> 两列留 NULL。下方凡写 `email_matches` 的段落均按此理解。

**Spec:** `docs/mailbox-imap-binding-design-2026-11-16.md`  
**Branch:** `feat/mailbox-imap-binding`（从当前 main 检出）  
**Author:** `Roger Lau <chefrogerlau@126.com>`；提交须含 `Touched outside task scope:` 行；禁止 Co-Authored-By。

---

## File map

| 文件 | 职责 |
|---|---|
| Create `trade/mailbox.py` | 预设表、test_connection、fetch_new、正文截断、错误映射；只读 EXAMINE + ID |
| Create `trade/mailbox_store.py` | secrets 读写、mailbox/email/matches CRUD、地址匹配、pull 编排（含 120s 超时断点续） |
| Create `trade/api/mailboxes.py` | REST：test/bind/secret/list/delete/pull/pull-all |
| Modify `trade/api/customers.py` | `GET /customers/{id}/emails` |
| Modify `trade/api/models.py` | Pydantic 请求体 |
| Modify `trade/api/__init__.py` | include mailboxes router |
| Modify `trade/database.py` | SCHEMA_SQL 三表 + 索引；`_EXPECTED_TABLES` |
| Create `static/js/mailboxes.js` | 邮箱面板 UI |
| Modify `static/trade_chat.html` | 侧栏入口 |
| Modify `static/js/ui.js` | `navToView('mailboxes')` |
| Modify `static/js/customers.js` | 卡片墙邮件卡 |
| Modify `static/js/i18n.js` | 文案键 |
| Modify `static/trade_chat.css` | 指南/列表少量 S-01 样式（若现有类不够） |
| Modify `tests_js/_extract.js` | 加载 `mailboxes.js` |
| Create `tests/test_mailbox_imap.py` | mock imaplib |
| Create `tests/test_mailbox_store.py` | secrets/匹配/去重/解绑 |
| Create `tests/test_mailbox_api.py` | FastAPI 路由 |
| Extend `tests/test_conversation_important.py` 或新建 `tests/test_mailbox_schema.py` | 旧库升级 |

---

### Task 0: 建分支

**Files:** none（git only）

- [ ] **Step 1: 从 main 建功能分支**

```bash
cd "/Users/rogerlau/Desktop/Foreign Trade Assistant"
git checkout main
git pull --ff-only origin main   # 若已有本地 docs 提交则先 push 或保留
git checkout -b feat/mailbox-imap-binding
```

Expected: 在 `feat/mailbox-imap-binding`，包含已合并的规格文档提交。

- [ ] **Step 2: 确认工作区干净（除 reports/ 等无关未跟踪）**

```bash
git status -sb
```

---

### Task 1: Schema — 三表进 `init_db`

**Files:**
- Modify: `trade/database.py`（`SCHEMA_SQL` 末尾表定义区、`_EXPECTED_TABLES`）
- Test: `tests/test_mailbox_schema.py`

- [ ] **Step 1: 写失败测试（缺表 / 升级）**

```python
# tests/test_mailbox_schema.py
"""邮箱三表：新装存在；旧库 init_db 可升级且旧数据原样。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def test_init_db_creates_mailbox_tables(tmp_path, monkeypatch):
    """新库 init_db 后 mailboxes/emails/email_matches 存在。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    from trade import database as db

    db.init_db()
    conn = db.get_connection()
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert {"mailboxes", "emails", "email_matches"} <= names
        cols = {r[1] for r in conn.execute("PRAGMA table_info(emails)")}
        assert "company_id" not in cols
        assert "customer_id" not in cols
    finally:
        conn.close()


def test_init_db_upgrades_legacy_without_mailbox_tables(tmp_path, monkeypatch):
    """无邮箱表的旧库：塞客户后 init_db，旧行仍在，新表空，二次启动不新增备份。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    data = tmp_path / "data"
    data.mkdir()
    db_path = data / "trade.db"
    # 最小旧库：仅 companies + customers（无 mailboxes）
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE companies (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE trade_companies (
            id INTEGER PRIMARY KEY, name TEXT, slug TEXT, is_active INTEGER DEFAULT 1,
            data_dir TEXT DEFAULT '', created_at TEXT, updated_at TEXT,
            extra1 TEXT DEFAULT '{}', extra2 TEXT DEFAULT '{}', extra3 TEXT DEFAULT '{}'
        );
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY, company_id INTEGER, name TEXT NOT NULL,
            contact TEXT DEFAULT '', note TEXT DEFAULT '',
            created_at TEXT, updated_at TEXT,
            extra1 TEXT DEFAULT '{}', extra2 TEXT DEFAULT '{}', extra3 TEXT DEFAULT '{}'
        );
        INSERT INTO trade_companies (id, name, slug, is_active)
        VALUES (1, '旧公司', 'old', 1);
        INSERT INTO customers (id, company_id, name, extra2)
        VALUES (1, 1, 'Acme', '{"email":"buyer@example.com"}');
        """
    )
    conn.commit()
    conn.close()

    from trade import database as db
    monkeypatch.setattr(db, "_get_db_path", lambda: db_path)

    backups_before = list((tmp_path / "backups").glob("trade-*.db")) if (tmp_path / "backups").exists() else []
    db.init_db()
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT name FROM customers WHERE id=1").fetchone()[0] == "Acme"
        assert conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0] == 0
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mailboxes'"
        ).fetchone()
    finally:
        conn.close()

    n1 = len(list((tmp_path / "backups").glob("trade-*.db"))) if (tmp_path / "backups").exists() else 0
    db.init_db()
    n2 = len(list((tmp_path / "backups").glob("trade-*.db"))) if (tmp_path / "backups").exists() else 0
    assert n2 == n1  # 二次启动不新增备份
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest tests/test_mailbox_schema.py -v
```

Expected: FAIL（表不存在 / import 断言失败）

- [ ] **Step 3: 在 `SCHEMA_SQL` 追加三表（放在 `CREATE INDEX` 区附近、`SCHEMA_SQL` 字符串内）**

```sql
CREATE TABLE IF NOT EXISTS mailboxes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL DEFAULT 'imap',
    preset TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    email_address TEXT NOT NULL UNIQUE,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 993,
    use_ssl INTEGER NOT NULL DEFAULT 1,
    username TEXT NOT NULL,
    last_uidvalidity INTEGER,
    last_uid INTEGER,
    last_sync_at TEXT,
    last_error TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mailbox_id INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    uid TEXT,
    from_addr TEXT,
    to_addrs TEXT,
    subject TEXT,
    snippet TEXT,
    body_text TEXT,
    received_at TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(mailbox_id, message_id)
);

CREATE TABLE IF NOT EXISTS email_matches (
    email_id INTEGER NOT NULL,
    company_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    UNIQUE(email_id, company_id, customer_id)
);
CREATE INDEX IF NOT EXISTS idx_email_matches_company_customer
    ON email_matches(company_id, customer_id, email_id);
CREATE INDEX IF NOT EXISTS idx_emails_mailbox ON emails(mailbox_id);
CREATE INDEX IF NOT EXISTS idx_emails_received ON emails(received_at);
```

并把 `"mailboxes"`, `"emails"`, `"email_matches"` 加入 `_EXPECTED_TABLES`。

- [ ] **Step 4: 跑测试确认通过**

```bash
python -m pytest tests/test_mailbox_schema.py -v
```

Expected: PASS（若旧库夹具缺其它 `_EXPECTED_TABLES` 导致反复备份，按失败信息把夹具补到「缺邮箱三表、其余表齐」或 monkeypatch `_needs_schema_work` 只测建表路径；优先补全夹具表名到与 `_EXPECTED_TABLES` 一致后再断言。）

- [ ] **Step 5: Commit**

```bash
git add trade/database.py tests/test_mailbox_schema.py
git commit --author='Roger Lau <chefrogerlau@126.com>' -m "$(cat <<'EOF'
feat(db): 邮箱绑定三表 mailboxes/emails/email_matches

Touched outside task scope: none
EOF
)"
```

---

### Task 2: 凭证文件 `mailbox_store` secrets

**Files:**
- Create: `trade/mailbox_store.py`（先只做 secrets + 路径）
- Test: `tests/test_mailbox_store.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_mailbox_store.py 片段
def test_secrets_roundtrip_and_chmod(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    from trade import database as db
    db.init_db()
    from trade import mailbox_store as ms

    path = ms.secrets_path()
    assert path.parent == db._get_db_path().parent
    ms.set_secret(1, "auth-code-16chars")
    assert ms.get_secret(1) == "auth-code-16chars"
    assert oct(path.stat().st_mode & 0o777) == "0o600" or path.stat().st_mode & 0o077 == 0
    ms.delete_secret(1)
    assert ms.get_secret(1) is None
```

（Windows 上 chmod 可能无效：断言改为「文件存在且可读」；用 `os.name == "nt"` 分支。）

- [ ] **Step 2: 跑测 FAIL → 实现**

```python
# trade/mailbox_store.py
"""邮箱绑定存储：凭证、mailbox CRUD、匹配入库、拉取编排。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from trade.database import _get_db_path, get_connection


def secrets_path() -> Path:
    """凭证文件与 trade.db 同目录。"""
    return _get_db_path().parent / "mailbox_secrets.json"


def _load_secrets() -> dict[str, str]:
    p = secrets_path()
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def _save_secrets(data: dict[str, str]) -> None:
    p = secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name != "nt":
        os.chmod(p, 0o600)


def get_secret(mailbox_id: int) -> str | None:
    return _load_secrets().get(str(mailbox_id))


def set_secret(mailbox_id: int, secret: str) -> None:
    data = _load_secrets()
    data[str(mailbox_id)] = secret
    _save_secrets(data)


def delete_secret(mailbox_id: int) -> None:
    data = _load_secrets()
    data.pop(str(mailbox_id), None)
    _save_secrets(data)
```

- [ ] **Step 3: 测试 PASS → Commit**

```bash
git add trade/mailbox_store.py tests/test_mailbox_store.py
git commit --author='Roger Lau <chefrogerlau@126.com>' -m "$(cat <<'EOF'
feat(mailbox): 凭证文件 mailbox_secrets.json（DB 同目录）

Touched outside task scope: none
EOF
)"
```

---

### Task 3: IMAP 接入层 `trade/mailbox.py`

**Files:**
- Create: `trade/mailbox.py`
- Test: `tests/test_mailbox_imap.py`

- [ ] **Step 1: 写失败测试（mock imaplib，禁止真连）**

覆盖：
1. `PRESETS` 含 126/163/qq/gmail  
2. `map_imap_error`：535 → 授权码文案；timeout → 网络文案  
3. `html_to_text` / `truncate_body`（5000 + 标记）  
4. `test_connection` 成功路径：mock 连接 → login → ID 命令 → logout  
5. `fetch_new` 首拉：SINCE + UID 降序截 500；增量 UID>last  

示例骨架：

```python
# tests/test_mailbox_imap.py
from unittest.mock import MagicMock, patch

from trade import mailbox as mb


def test_map_auth_failed():
    msg = mb.map_imap_error(Exception("AUTHENTICATION failed 535"))
    assert "授权码" in msg


def test_truncate_body():
    body = "x" * 5001
    out = mb.truncate_body(body)
    assert out.endswith("…（正文过长，仅显示前 5000 字）")
    assert len(out) == 5000 + len("…（正文过长，仅显示前 5000 字）")


def test_html_to_text_keeps_breaks():
    assert "hello" in mb.html_to_text("<p>hello<br>world</p>")


@patch("trade.mailbox.imaplib.IMAP4_SSL")
def test_test_connection_sends_id(mock_ssl):
    client = MagicMock()
    mock_ssl.return_value = client
    client.login.return_value = ("OK", [b"Logged in"])
    client._simple_command.return_value = ("OK", [b""])  # 若用 _simple_command 发 ID
    mb.test_connection("imap.126.com", 993, "u@126.com", "sixteencharscode")
    client.login.assert_called_once()
    # 断言发过 ID（按实现选用的底层 API 调整）
```

- [ ] **Step 2: 实现 `trade/mailbox.py` 最小面**

必须导出：

```python
PRESETS = {
    "126": ("imap.126.com", 993),
    "163": ("imap.163.com", 993),
    "qq": ("imap.qq.com", 993),
    "gmail": ("imap.gmail.com", 993),
}

BODY_MAX = 5000
BODY_TRUNC_MARK = "…（正文过长，仅显示前 5000 字）"
SNIPPET_MAX = 200
FIRST_PULL_DAYS = 90
FIRST_PULL_LIMIT = 500

class MailboxError(Exception):
    """带小白可读 message 的邮箱错误。"""

def map_imap_error(exc: BaseException) -> str: ...
def html_to_text(html: str) -> str: ...
def truncate_body(text: str) -> str: ...
def extract_body(msg) -> str: ...  # text/plain 优先，否则 HTML→text
def test_connection(host, port, username, secret) -> None: ...
def fetch_new(mailbox_row: dict, secret: str) -> tuple[list[dict], dict]:
    """返回 (messages, cursor_update)。
    messages 项含 message_id/from_addr/to_addrs/subject/snippet/body_text/received_at/uid。
    cursor_update 含 last_uidvalidity/last_uid（本轮成功处理到的最大 UID）。
    只读 EXAMINE；登录后发 ID；不下载附件。
    """
```

`fetch_new` 规则（与规格一致）：
- 无游标或 UIDVALIDITY 变：SINCE 90 天，UID 降序最多 500  
- 有游标：UID > last_uid  
- message_id 缺失：用 `X-GM-MSGID` 或 `f"{uidvalidity}:{uid}"`  
- 函数本身不写库；超时由上层 `mailbox_store.pull_one` 用线程/截止时间包一层（Task 4）

- [ ] **Step 3: 测试 PASS → Commit**

```bash
git add trade/mailbox.py tests/test_mailbox_imap.py
git commit --author='Roger Lau <chefrogerlau@126.com>' -m "$(cat <<'EOF'
feat(mailbox): IMAP 只读接入（EXAMINE + ID + 游标拉取）

Touched outside task scope: none
EOF
)"
```

---

### Task 4: 匹配入库 + pull 编排

**Files:**
- Modify: `trade/mailbox_store.py`
- Test: `tests/test_mailbox_store.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_match_from_or_to_case_insensitive(tmp_path, monkeypatch):
    # 建两公司两客户；邮件 From 命中 A，To 命中 B → 两行 email_matches，emails 仅 1 行
    ...

def test_dedupe_d1_skips_second_insert(tmp_path, monkeypatch):
    # 同一 message_id 入库两次 → emails 行数仍 1；正文保持首次
    ...

def test_unbind_deletes_secret_emails_matches(tmp_path, monkeypatch):
    ...

def test_pull_timeout_advances_cursor(monkeypatch):
    # mock fetch_new 在中途模拟超时路径：已入库 N 封后 raise；断言 last_uid 前进
    ...
```

- [ ] **Step 2: 实现关键 API**

```python
def normalize_addr(s: str) -> str:
    return (s or "").strip().lower()

def find_customer_matches(from_addr: str, to_addrs: list[str]) -> list[tuple[int, int]]:
    """扫全部公司 customers.extra2 email/backup_email → [(company_id, customer_id), ...]"""

def insert_email_ignore(conn, mailbox_id, msg: dict) -> int | None:
    """INSERT OR IGNORE；返回 email_id（新建或已存在）。已存在则不更新正文（D1）。"""

def attach_matches(conn, email_id: int, pairs: list[tuple[int, int]]) -> int:
    """INSERT OR IGNORE into email_matches；返回新插入数。"""

def create_mailbox(...) -> dict: ...
def list_mailboxes() -> list[dict]: ...  # 含 has_secret、email_count，无 secret
def delete_mailbox(mailbox_id: int) -> None: ...
def update_secret(mailbox_id: int, secret: str) -> None: ...  # 先 test_connection

PULL_TIMEOUT_SEC = 120

def pull_one(mailbox_id: int) -> dict:
    """返回 {pulled, matched, error?}。
    用线程跑 fetch_new；每成功入库一封可推进内存游标；
    超时：写 last_error（含已拉 N），提交已写入 + last_uid=已成功最大 UID，不回滚。
    """

def pull_all() -> dict:
    """串行 pull_one；返回 {results: [...]}。"""

def list_customer_emails(company_id: int, customer_id: int, limit: int = 50) -> list[dict]:
    """JOIN email_matches WHERE company_id AND customer_id ORDER BY received_at DESC。"""
```

- [ ] **Step 3: PASS → Commit**

```bash
git add trade/mailbox_store.py tests/test_mailbox_store.py
git commit --author='Roger Lau <chefrogerlau@126.com>' -m "$(cat <<'EOF'
feat(mailbox): 匹配入库、D1 去重、120s 断点续拉

Touched outside task scope: none
EOF
)"
```

---

### Task 5: API 路由

**Files:**
- Create: `trade/api/mailboxes.py`
- Modify: `trade/api/models.py`, `trade/api/customers.py`, `trade/api/__init__.py`
- Test: `tests/test_mailbox_api.py`

- [ ] **Step 1: 模型**

```python
# trade/api/models.py 追加
from typing import Literal

MailboxPreset = Literal["126", "163", "qq", "gmail", "custom"]

class MailboxTestRequest(BaseModel):
    preset: MailboxPreset
    email_address: str
    secret: str
    host: str | None = None
    port: int | None = None
    username: str | None = None

class MailboxCreateRequest(MailboxTestRequest):
    display_name: str = ""

class MailboxSecretUpdate(BaseModel):
    secret: str
```

- [ ] **Step 2: `trade/api/mailboxes.py`**

```python
router = APIRouter(tags=["mailboxes"])

@router.post("/mailboxes/test")
def api_test(payload: MailboxTestRequest):
    # resolve host/port/username；mailbox.test_connection；MailboxError → 400
    ...

@router.post("/mailboxes", status_code=201)
def api_create(payload: MailboxCreateRequest):
    # 地址已存在 → 409「该邮箱已经绑定过了，先解绑再绑」
    # 先 test_connection，再 create + set_secret
    ...

@router.put("/mailboxes/{mailbox_id}/secret")
def api_secret(...): ...

@router.get("/mailboxes")
def api_list(): ...

@router.delete("/mailboxes/{mailbox_id}")
def api_delete(...): ...

@router.post("/mailboxes/{mailbox_id}/pull")
def api_pull(...): ...

@router.post("/mailboxes/pull-all")
def api_pull_all(): ...
```

注意：父路由已有 `require_session`；**不要**加 `require_company`。前端仍可能带 `X-Company-ID`，`_enforce_company_binding` 会校验绑定——这是 SPA 常态，业务层忽略公司头即可。

- [ ] **Step 3: `customers.py` 增加**

```python
@router.get("/customers/{customer_id}/emails")
def list_customer_emails(customer_id: int, company_id: int = Depends(require_company), limit: int = 50):
    # 客户不存在或不属本公司 → 404
    # return mailbox_store.list_customer_emails(company_id, customer_id, min(max(limit,1),50))
```

- [ ] **Step 4: `__init__.py` `include_router(mailboxes_router)`**

- [ ] **Step 5: API 测试（TestClient + mock test_connection / pull）→ Commit**

```bash
git add trade/api/mailboxes.py trade/api/models.py trade/api/customers.py trade/api/__init__.py tests/test_mailbox_api.py
git commit --author='Roger Lau <chefrogerlau@126.com>' -m "$(cat <<'EOF'
feat(api): 邮箱绑定/拉取 REST 与客户邮件列表

Touched outside task scope: none
EOF
)"
```

---

### Task 6: 前端邮箱面板

**Files:**
- Create: `static/js/mailboxes.js`
- Modify: `static/trade_chat.html`（侧栏）、`static/js/ui.js`、`static/js/i18n.js`、`tests_js/_extract.js`
- Modify: `static/trade_chat.css`（仅当缺类时）

- [ ] **Step 1: HTML 侧栏**（客户管理下一行）

```html
<div class="nav-item" data-view="mailboxes" onclick="navToView('mailboxes')">
    <span class="nav-icon" data-icon="mail"></span><span class="nav-label" data-i18n="nav.mailboxes">邮箱</span>
</div>
```

- [ ] **Step 2: `ui.js` switch 增加 `case 'mailboxes': renderMailboxesViewInto(container); break;`**

- [ ] **Step 3: `mailboxes.js`**

实现：
- `renderMailboxesViewInto(container)`：指南 + 表单 + 列表  
- 指南：常量 `MAILBOX_GUIDE`（中文全文，按规格「附录对齐」三处改措辞）；英文 UI 顶部加 `Guide in Chinese only…`  
- 选 preset 自动展开对应段；预填 host/port  
- username：非 custom 隐藏，值=邮箱地址  
- 测试按钮 → `POST /mailboxes/test`；成功后启用绑定  
- 绑定 → `POST /mailboxes`  
- 列表：拉取 / 更新授权码（prompt 或小表单）/ 解绑  
- 全部走 `api()` + `esc()` / `t()`

- [ ] **Step 4: i18n 键** `nav.mailboxes`、`mailbox.*`（标题、按钮、空态、拉取中…）

- [ ] **Step 5: `_extract.js` 在 `customers.js` 后加入 `mailboxes.js`**

- [ ] **Step 6: `node --test tests_js/*.test.js` 全过 → Commit**

```bash
git add static/js/mailboxes.js static/trade_chat.html static/js/ui.js static/js/i18n.js static/trade_chat.css tests_js/_extract.js
git commit --author='Roger Lau <chefrogerlau@126.com>' -m "$(cat <<'EOF'
feat(ui): 侧栏邮箱面板（指南/绑定/拉取）

Touched outside task scope: none
EOF
)"
```

---

### Task 7: 卡片墙邮件卡

**Files:**
- Modify: `static/js/customers.js`（约 400–410 行邮件段）

- [ ] **Step 1: 打开墙时并行请求**

```javascript
const mailRes = await api('GET', '/customers/' + id + '/emails');
const mailList = (mailRes && mailRes.emails) || mailRes || [];
```

（按实际 API 返回形 `{emails: [...]}` 解析。）

- [ ] **Step 2: 替换空态块**

- 有绑定且有邮件：列表主题 / 对方 / 日期；点击展开 `esc(body_text)`  
- `EMAIL // n` 用真实条数  
- 右上角刷新：`POST /mailboxes/pull-all`，按钮置灰「拉取中…」，完成后重拉本卡 emails  
- 未绑定：档案邮箱 +「只显示邮箱地址，不读取邮箱」+ 按钮 `navToView('mailboxes')`  
- 先 `GET /mailboxes` 判断是否已绑（length>0）

- [ ] **Step 3: 手动看 xss-guard 仍要求用户字段走 `esc()` → Commit**

```bash
git add static/js/customers.js
git commit --author='Roger Lau <chefrogerlau@126.com>' -m "$(cat <<'EOF'
feat(ui): 卡片墙邮件卡接真实拉取与刷新

Touched outside task scope: none
EOF
)"
```

---

### Task 8: 回归与推送

- [ ] **Step 1: 跑测试**

```bash
python -m pytest tests/test_mailbox_schema.py tests/test_mailbox_store.py tests/test_mailbox_imap.py tests/test_mailbox_api.py -v
node --test tests_js/*.test.js
```

Expected: 全 PASS。确认测试与提交说明中无真实邮箱/授权码。

- [ ] **Step 2: 推远端**

```bash
git push -u origin feat/mailbox-imap-binding
gh pr create --title "feat(mailbox): 邮箱绑定（只读 IMAP）+ 卡片墙邮件卡" --body "$(cat <<'EOF'
## Summary
- IMAP 只读绑定（126/163/QQ/Gmail/custom），手动拉取，精确地址匹配
- email_matches 关联表；D1 去重；pull-all 120s 断点续
- 侧栏邮箱面板 + 卡片墙邮件卡

## Test plan
- [ ] pytest mailbox_* 全过
- [ ] node tests_js 全过
- [ ] 旧库升级：新表在、旧数据在、二次不备
- [ ] 故意错授权码 → 小白提示
- [ ] Lau 真机：绑定 → 拉取 → 卡片墙见信

EOF
)"
```

（若 `gh` token 失效，用 git push 后手动开 PR。）

---

## Spec coverage checklist

| 规格项 | Task |
|---|---|
| 三表 + _EXPECTED_TABLES + 无 ALTER 旧表 | 1 |
| secrets 路径/600/不解进备份 | 2 |
| IMAP EXAMINE/ID/游标/5000/错误映射 | 3 |
| 匹配 From/To、matches、D1、解绑、T3 120s | 4 |
| REST + 客户 emails + session only | 5 |
| 侧栏面板 + 指南对齐 | 6 |
| 卡片墙 + pull-all 刷新 | 7 |
| 测试/推送/禁真实凭证 | 8 |

## Self-review notes

- 无 TBD；超时统一 **120s + 断点续（T3）**；去重统一 **D1**  
- `emails` 无 company/customer 列；匹配只在 `email_matches`  
- 409 文案不用「另一家公司」  
- 父路由 session 已挂；邮箱路由勿再加 `require_company`
