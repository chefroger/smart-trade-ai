# trade 邮箱绑定（只读 IMAP）— 设计规格

- 日期：2026-11-16
- 基线：main @ `4ca11e7`
- 分支：`feat/mailbox-imap-binding`
- 来源：任务书 v2 + 审洞决议（U1=B2+S1，username=U，超时=T3，鉴权=A1，路径=P1）
- 本文件为实现真源；任务书附录连接指南文案仍照附录渲染（并按下方「附录对齐」改三处措辞）

## 目标

用户绑定自己的邮箱（可多个），trade **只读**拉收件箱，按客户邮箱精确匹配，供客户卡片墙邮件卡展示。

五条铁律：只拉收件箱；不拉附件；无定时拉取；仅手动拉取；只读（不发信 / 不删信 / 不标已读）。

## 架构（P1）

```
侧栏「邮箱」面板
  → trade/api/mailboxes.py   (require_session；不校验 X-Company-ID)
  → trade/mailbox.py         (imaplib，零新依赖，只读)
  → mailbox_secrets.json     (与 DB 同目录)
  → SQLite: mailboxes / emails / email_matches

卡片墙
  → GET /api/trade/customers/{id}/emails  (require_company)
  → 刷新 → POST /api/trade/mailboxes/pull-all
```

- 拉取失败只写 `last_error`，不阻塞启动与聊天主流程。
- 邮箱属于操作员本人（全局绑定），不属于某家公司。

## 存储

### `mailboxes`（全局，无 `company_id`）

| 列 | 说明 |
|---|---|
| `provider` | v1 恒 `'imap'` |
| `preset` | `126` / `163` / `qq` / `gmail` / `custom` |
| `email_address` | **全局唯一** |
| `username` | 默认 = `email_address`；仅 custom 可改 |
| `host`, `port`, `use_ssl` | 预设可改 |
| `last_uidvalidity`, `last_uid` | 增量游标 |
| `last_sync_at`, `last_error` | 同步状态 |
| `display_name`, `created_at` | |

### `emails`（一封一行）

- `UNIQUE(mailbox_id, message_id)`
- 字段：`uid`, `from_addr`, `to_addrs`, `subject`, `snippet`, `body_text`, `received_at`, …
- **不含** `company_id` / `customer_id`

### `email_matches`（多对多）

- `(email_id, company_id, customer_id)`
- `UNIQUE(email_id, company_id, customer_id)`
- 索引：`(company_id, customer_id, email_id)`（或含 `received_at` 的查询以 JOIN emails 排序）

### 凭证

- 路径：`_get_db_path().parent / "mailbox_secrets.json"`（跟随 `TRADE_HOME` / Windows `LOCALAPPDATA`，不硬编码 `~/.trade/`）
- 格式：`{mailbox_id: secret}`；文件权限 `600`
- API / 日志永不返回或打印 secret；备份与公司导出不带此文件
- 解绑：删 mailbox 行 + secrets 条目 + 该箱全部 emails + 其 matches

### Schema 升级

- 三表进 `SCHEMA_SQL`（`CREATE TABLE IF NOT EXISTS`）+ `_EXPECTED_TABLES`
- 禁止为此对旧表 `ALTER` / `DROP` / `RENAME`
- `init_db`：需改才备份；失败不自动还原（与现行为一致；自动还原另立项）

## 匹配规则

- 客户地址：`customers.extra2` 的 `email` / `backup_email`（去空格、大小写不敏感）
- 命中条件：客户地址出现在邮件 **From 或 To 任一**（To 为数组）
- **跨全部公司**查找；每命中一对 `(company_id, customer_id)` 写一行 `email_matches`
- 未命中：仍存 `emails` 行，matches 无行（不丢信）
- CC 不存、不匹配；域名匹配不做

## IMAP 接入（`trade/mailbox.py`）

预设（SSL 993）：

- `126` → `imap.126.com`
- `163` → `imap.163.com`
- `qq` → `imap.qq.com`
- `gmail` → `imap.gmail.com`
- `custom` → 用户自填

行为：

- `test_connection`：连通 + 登录成功才返回；失败抛可映射原因
- 登录后发 IMAP `ID`（RFC 2971）自报 Trade（163/126 必需；QQ/Gmail 无害）
- 选收件箱用 **`EXAMINE`**（非 `SELECT`），不改 `\Seen`
- 首拉：`SEARCH SINCE`（90 天）→ **UID 降序**最多 500 → `last_uid` = 已见最大 UID
- 增量：UID > `last_uid` 升序
- `UIDVALIDITY` 变化：全量重对 + `message_id` 去重兜底
- 正文：优先 `text/plain`；仅 HTML 则去标签转纯文本；超过 5000 字截断并加标记
- 附件：不下载、不存、不解析
- 模块不提供发信 / 删除 / 标已读

错误 → 小白文案：

- `535` / Authentication failed → 密码栏要填 16 位授权码，不是登录密码
- 连接超时 → 检查网络与服务器地址
- IMAP not enabled → 先去邮箱网页版开启 IMAP

## API

鉴权：邮箱绑定/列表/拉取仅 `require_session`（**A1**，不校验公司头）。  
`GET /customers/{id}/emails` 仍 `require_company`。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/trade/mailboxes/test` | 只测不存 |
| POST | `/api/trade/mailboxes` | 测通才入库；地址已存在 → **409**「该邮箱已经绑定过了，先解绑再绑」 |
| PUT | `/api/trade/mailboxes/{id}/secret` | 换授权码；测不通保留旧码 |
| GET | `/api/trade/mailboxes` | 列表 + 同步状态 + 邮件数；`has_secret`；无 secret |
| DELETE | `/api/trade/mailboxes/{id}` | 解绑全清 |
| POST | `/api/trade/mailboxes/{id}/pull` | 单箱手动拉 |
| POST | `/api/trade/mailboxes/pull-all` | 串行全拉；**单箱超时 120s（T3）**；失败记错继续下一箱 |
| GET | `/api/trade/customers/{id}/emails` | 本公司；`received_at` 倒序；limit 50 |

拉取超时（T3）：游标前进到本轮**已成功入库**的最大 UID；不回滚已写入；`last_error` 可含「超时，已拉 N 封」。

请求绑定体：`{preset, display_name?, email_address, host?, port?, username?, secret}`；`host`/`port` 可按 preset 默认；`username` 缺省 = `email_address`。

## 前端

- 侧栏：销售转化分组、客户管理之下；`data-view="mailboxes"`；图标现有 `mail`
- 面板全局，不随公司切换
- 结构：连接指南 → 绑定表单 → 已绑列表
- 表单：类型 / 地址 / 授权码（占位强调授权码）/ 显示名；服务器端口预填可改；username 不另开栏（仅 custom 可改）
- 「测试连接」→ `/test`；通过后「绑定」可用 → `POST`
- 列表行：手动拉取、更新授权码、解绑
- 指南：附录四段 + 其他 IMAP；选类型自动展开；英文 UI 仍中文指南 + 顶部英文提示句
- 卡片墙：接 `GET …/emails`；主题/对方/日期；点开纯文本（均 `esc()`）；刷新 = `pull-all`（置灰「拉取中…」）；未绑定空态 + 跳转邮箱面板
- 样式：S-01；文案走 `t()`

### 附录对齐（实现时改渲染用文案，不改步骤大意）

1. 「测试连接。通过就绑好了」→ 改为：测通后点「绑定」
2. QQ / FAQ「删了重绑」改授权码 → 改为：列表「更新授权码」
3. 409 / 提示不写「另一家公司」

## 测试与验收

- mock `imaplib`（不连真服）：测通/失败映射、UID 增量、message_id 去重、5000 截断、HTML→纯文本、精确匹配、`email_matches` 跨公司、解绑清凭证+邮件、`init_db` 不连网
- 旧库升级：带真实旧数据跑 `init_db`；新表建好、旧数据原样、二次启动不新增备份
- JS / Python 相关测试全过；CI 绿
- 真机验收仅 Lau；代码/测试/提交说明禁止真实邮箱与授权码
- 断网打开 trade 不得报错；邮箱面板空态

## 不做清单

Gmail OAuth；定时拉取；发信/删信/标已读；附件；域名匹配；CC；关系图谱；系统钥匙串；SMTP。

「跨公司共享邮箱」指多操作员共享同一绑定配置——本机单用户全局绑定 + 跨公司匹配客户，不在此禁止项内。

## 提交约定

- 分支 `feat/mailbox-imap-binding`；按模块分笔提交并推远端
- 范围外改动须写 `Touched outside task scope:`；否则 `none`
- 作者：`Roger Lau <chefrogerlau@126.com>`；禁止 Co-Authored-By
