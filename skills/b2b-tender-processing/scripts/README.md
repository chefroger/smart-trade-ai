# scripts/

- `build_inquiry_sheet.py` — 读取招标行项，生成固定 11 列的 Excel 询价单（openpyxl）

约定：
- 脚本支持 `--lang zh|en`（或环境变量 `TRADE_LANG`）
- 列序固定，不因输入列名变化而重排
