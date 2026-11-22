#!/bin/bash
# ==============================================================================
# 发版：把 stable 快进到当前 main，并打 tag（2026-11-20 起更新跟随 stable）
# ==============================================================================
# 用法： scripts/promote-stable.sh 0.8.0 [--skip-tests] [--note "一句话说明"]
#
# 做的事：
#   1. 校验在 main、工作区干净、与 origin/main 同步
#   2. 跑全量测试（除非 --skip-tests）
#   3. 更新 pyproject.toml 版本号 + 在 CHANGELOG 顶部插入本节
#   4. 提交、打 v<版本> tag、推送 main 与 tag
#   5. 把 stable 快进到同一提交并推送
# ==============================================================================
set -euo pipefail

VERSION="${1:-}"
SKIP_TESTS=0
NOTE=""
shift || true
while [ $# -gt 0 ]; do
    case "$1" in
        --skip-tests) SKIP_TESTS=1; shift ;;
        --note) NOTE="${2:-}"; shift 2 ;;
        *) echo "未知参数：$1"; exit 1 ;;
    esac
done

if [ -z "$VERSION" ]; then
    echo "用法：scripts/promote-stable.sh <版本号，如 0.8.0> [--skip-tests] [--note \"...\"]"
    exit 1
fi

cd "$(dirname "$0")/.."

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "main" ]; then
    echo "✗ 必须在 main 上发版（当前：$BRANCH）"; exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
    echo "✗ 工作区不干净，先提交或 stash"; exit 1
fi

git fetch origin main --quiet
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
    echo "✗ 本地 main 与 origin/main 不一致，先 push/pull"; exit 1
fi

if [ "$SKIP_TESTS" -eq 0 ]; then
    echo "→ 跑后端测试…"
    python -m pytest tests/ -q
    echo "→ 跑前端测试…"
    node --test tests_js/
fi

CURRENT="$(grep -m1 '^version' pyproject.toml | sed 's/.*"\(.*\)".*/\1/')"
if [ "$CURRENT" = "$VERSION" ]; then
    echo "✗ 版本号已经是 $VERSION，请 bump"
    exit 1
fi

# 只改 pyproject 的 version 行
python3 - "$VERSION" <<'PY'
import re, sys
p = "pyproject.toml"
v = sys.argv[1]
s = open(p, encoding="utf-8").read()
s2 = re.sub(r'(?m)^version = "[^"]*"', f'version = "{v}"', s, count=1)
if s == s2:
    raise SystemExit("未能替换 pyproject 版本号")
open(p, "w", encoding="utf-8").write(s2)
PY

# 与 CHANGELOG.md 既有风格一致：每条带短 SHA（按提交整理）
LAST_TAG="$(git describe --tags --abbrev=0 2>/dev/null || true)"
if [ -n "$LAST_TAG" ]; then
    LOG="$(git log --no-merges --pretty='- `%h` %s' "$LAST_TAG"..HEAD)"
else
    LOG="$(git log --no-merges --pretty='- `%h` %s' -50)"
fi
[ -n "$NOTE" ] && LOG="- $NOTE
$LOG"

# 审计 O-21：非发版提交必须带「包外改动」披露行。只在发版时提醒，不阻断
# （历史提交无法补写，卡住发布没有意义）。
if [ -n "$LAST_TAG" ]; then
    python3 scripts/check_commit_disclosure.py "$LAST_TAG..HEAD" --warn-only || true
fi

python3 - "$VERSION" "$LOG" <<'PY'
import sys
v, log = sys.argv[1], sys.argv[2]
from datetime import date
head = f"## v{v} — {date.today().isoformat()}\n\n{log}\n\n"
try:
    old = open("CHANGELOG.md", encoding="utf-8").read()
except FileNotFoundError:
    old = "# CHANGELOG\n\n"
# 新版本小节必须插在 # CHANGELOG 标题之后，不能插到文件最前面（否则标题被压到中间）
if old.startswith("# CHANGELOG"):
    header, _, rest = old.partition("\n")
    new = header + "\n\n" + head + rest.lstrip("\n")
else:
    new = "# CHANGELOG\n\n" + head + old
open("CHANGELOG.md", "w", encoding="utf-8").write(new)
PY

git add pyproject.toml CHANGELOG.md
git commit -m "chore(release): v$VERSION"
git tag -a "v$VERSION" -m "v$VERSION"
git push origin main
git push origin "v$VERSION"

# stable 快进到与 main 同一提交
git push origin "main:stable"

echo ""
echo "✓ 已发布 v$VERSION"
echo "  更新用户将拉到 stable@$(git rev-parse --short HEAD)"
