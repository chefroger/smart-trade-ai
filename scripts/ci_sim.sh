#!/usr/bin/env bash
# 在「没有安装 Hermes」的环境里跑测试，复现 CI 条件。
#
# 为什么要这个：CI 不安装 Hermes（见 CLAUDE.md），但开发机上通常装了。
# 一旦测试依赖了本机存在的 Hermes 模块，本地会通过、CI 才报错。
# 这个脚本屏蔽 Hermes 的全部顶层模块，把 CI 的失败提前到本地。
#
# 用法：
#   scripts/ci_sim.sh                     # 跑全部测试
#   scripts/ci_sim.sh tests/test_api.py   # 只跑指定文件
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIM_DIR="$(mktemp -d)"
trap 'rm -rf "$SIM_DIR"' EXIT

# Hermes 的顶层模块（取自 hermes-agent 的 top_level.txt），
# 通用名字（如 utils、plugins）不列，避免屏蔽掉测试自己的辅助模块。
cat > "$SIM_DIR/sitecustomize.py" <<'PY'
"""模拟 CI：屏蔽 Hermes 的全部顶层模块。"""
import importlib.abc
import sys

BLOCKED = {
    "acp_adapter", "agent", "batch_runner", "cli", "cron", "gateway",
    "hermes_bootstrap", "hermes_cli", "hermes_constants", "hermes_logging",
    "hermes_state", "hermes_time", "mcp_serve", "model_tools", "providers",
    "run_agent", "tools", "toolset_distributions", "toolsets",
    "trajectory_compressor", "tui_gateway",
}


class _Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in BLOCKED:
            raise ImportError(f"blocked for CI simulation: {fullname}")
        return None


sys.meta_path.insert(0, _Blocker())
PY

echo "==> 模拟环境：已屏蔽 Hermes（CI 不安装它）"
cd "$ROOT"
if [ "$#" -gt 0 ]; then
    PYTHONPATH="$SIM_DIR" python -m pytest "$@"
else
    PYTHONPATH="$SIM_DIR" python -m pytest tests/ -q
fi
