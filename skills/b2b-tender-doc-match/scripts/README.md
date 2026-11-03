# scripts/

- `match_archive.py` — 按招标清单匹配本地文件：编号规范化（保留分隔符）、名称相关匹配、成套整夹打包

约定：
- 脚本支持 `--lang zh|en`（或环境变量 `TRADE_LANG`）
- 匹配率低时如实报告，不放宽阈值凑数
