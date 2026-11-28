#!/usr/bin/env bash
# 仓库安全闸门：防止误提交密钥、私钥、数据库、环境文件与白名单外的数据表格。
# 用法：bash scripts/repo_safety.sh [repo_root]
# 约定：内容检查仅输出命中文件名，绝不打印匹配到的疑似密钥原文。

set -euo pipefail

REPO_ROOT="${1:-$(git rev-parse --show-toplevel)}"
cd "$REPO_ROOT"

ALLOW_FILE=".github/repo-safety-allow.txt"
ALLOW_PATTERNS=()
if [[ -f "$ALLOW_FILE" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%%#*}"
        line="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        [[ -z "$line" ]] && continue
        ALLOW_PATTERNS+=("$line")
    done < "$ALLOW_FILE"
fi

is_allowed_path() {
    local f="$1"
    local pat
    for pat in "${ALLOW_PATTERNS[@]:-}"; do
        [[ -z "$pat" ]] && continue
        # shellcheck disable=SC2053
        if [[ "$f" == $pat ]]; then
            return 0
        fi
    done
    return 1
}

FAIL=0

# 1. 路径检查（遍历 git 已跟踪文件）
while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    base="$(basename "$f")"

    # 允许 .env.example
    if [[ "$base" == ".env.example" ]]; then
        continue
    fi

    # 敏感路径与禁入类型
    if [[ "$f" == .trade/* ]] \
        || [[ "$f" == "docs/license-keys-backup.txt" ]] \
        || [[ "$base" == "license.json" ]] \
        || [[ "$base" == ".env" ]] \
        || [[ "$base" == .env.* ]] \
        || [[ "$f" == *.db ]] \
        || [[ "$f" == *.db-* ]] \
        || [[ "$f" == *.sqlite ]] \
        || [[ "$f" == *.sqlite3 ]] \
        || [[ "$f" == *.pem ]] \
        || [[ "$f" == *.key ]] \
        || [[ "$f" == *.p12 ]] \
        || [[ "$f" == *.zip ]]; then
        echo "[repo-safety] 禁止入库的敏感路径或文件类型: $f"
        FAIL=1
        continue
    fi

    # 数据表格仅允许白名单内模板与测试夹具
    if [[ "$f" == *.csv ]] || [[ "$f" == *.xlsx ]]; then
        if ! is_allowed_path "$f"; then
            echo "[repo-safety] 白名单外的数据表格文件: $f"
            FAIL=1
        fi
    fi
done < <(git ls-files)

# 2. 内容检查（仅输出文件名，严禁输出匹配行原文）
# 分段定义正则，避免脚本自身被误报
PAT_SK="sk""-[A-Za-z0-9]{20,}"
PAT_TVLY="tvly""-[A-Za-z0-9_-]{16,}"
PAT_GH="(ghp|gho|ghu|ghs|ghr)""_[A-Za-z0-9]{20,}"
PAT_PEM="-----BEGIN [A-Z ]*""PRIVATE KEY-----"
COMBINED_PAT="(${PAT_SK}|${PAT_TVLY}|${PAT_GH}|${PAT_PEM})"

MATCHED_FILES="$(git grep -n -I -E "$COMBINED_PAT" -- . ':(exclude)scripts/repo_safety.sh' \
    | grep -E -v "(sk|tvly)-(test|fake|dummy|placeholder|example)" \
    | cut -d: -f1 | sort -u || true)"
if [[ -n "$MATCHED_FILES" ]]; then
    while IFS= read -r mf; do
        [[ -z "$mf" ]] && continue
        echo "[repo-safety] 检测到疑似密钥或私钥内容（仅输出文件名）: $mf"
        FAIL=1
    done <<< "$MATCHED_FILES"
fi

if [[ "$FAIL" -ne 0 ]]; then
    echo "[repo-safety] 检查未通过，请清理上述文件或经评审更新 ${ALLOW_FILE}。"
    exit 1
fi

echo "[repo-safety] OK"
