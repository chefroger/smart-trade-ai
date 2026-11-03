# scripts/

- `tender_download.py` — 招标附件批量下载：分块续传、大小与校验双验、`.lock` 单实例锁、Range 不支持时回退整包

约定：
- 脚本支持 `--lang zh|en`（或环境变量 `TRADE_LANG`）
- 失败单件记原因并继续整批，不中断
