# scripts/

- `fetch_recent.py` — 拉取指定时间窗口内的新招标邮件
- `monitor_inbox.py` — 定时监控邮箱并增量抓取
- `backfill_attachments.py` — 为历史邮件补下载附件
- `tender_mail_core.py` — 共用逻辑（IMAP、附件落盘、去重）
- `mail_accounts.example.json` — 邮箱账号配置样例（复制为 `mail_accounts.json`）

约定：
- 脚本统一支持 `--lang zh|en`（或环境变量 `TRADE_LANG`）
- 全程 `BODY.PEEK`，不把邮件标记为已读
