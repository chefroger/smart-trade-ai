# scripts/

- `extract_archives.py` — 批量解压 7z/rar/zip/gz：稳定性核查、嵌套包多轮展开、原包进回收站

约定：
- 脚本支持 `--lang zh|en`（或环境变量 `TRADE_LANG`）
- `--dry-run` 只统计不动文件；`--mode A|B` 控制是否回收原包
- 回收站不可用时只报告、不永久删除
