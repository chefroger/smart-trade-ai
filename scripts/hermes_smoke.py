"""Hermes 嵌入冒烟：验证 Trade 与 Hermes 的耦合点仍可导入（2026-11-21 审计 P2-6）。

CI 的普通测试全部用 mock，从不真正加载 Hermes —— 而「Hermes 升级后
import 副作用变了」正是踩过的坑（见 COMPATIBILITY.md）。本脚本在**装了真实
Hermes 的环境**里跑，验证：

  1. `trade.bootstrap.prepare_hermes_import_paths()` 能正常完成
  2. Hermes 版本可解析且不低于 `_MIN_HERMES_VERSION`
  3. Trade 依赖的 6 个核心耦合点模块都能 import（列表见下方 coupling_points，
     与 CLAUDE.md 的 Coupling Points 清单手工同步；CLAUDE.md 在本机是 gitignore，
     不进仓库，所以这里不再声称「一一对应」）

**不构造 AIAgent**：那需要用户自己的 API key，CI 里没有。
只验证「能不能加载」，不验证「能不能对话」。

用法：
    python scripts/hermes_smoke.py
退出码：0 通过 / 1 失败（打印具体哪一项）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    # 让 scripts/ 里的脚本也能 import 仓库内的 trade 包
    sys.path.insert(0, str(repo))
    os.environ.setdefault("HERMES_HOME", str(Path.home() / ".hermes"))

    failures: list[str] = []

    # 1) 与真实运行完全一致的路径准备（懒加载守卫 + sys.path + 激活后恢复）
    try:
        from trade.bootstrap import _MIN_HERMES_VERSION, prepare_hermes_import_paths

        prepare_hermes_import_paths()
        print(f"✓ prepare_hermes_import_paths()（最低版本要求 {_MIN_HERMES_VERSION}）")
    except Exception as exc:  # noqa: BLE001 — 冒烟脚本要把原因完整打印出来
        print(f"✗ prepare_hermes_import_paths 失败：{exc}")
        return 1

    # 2) 版本可解析且不低于下限
    try:
        from packaging.version import Version

        from trade.hermes_compat import hermes_version

        version = hermes_version()
        # 解析不到版本：这是警告而非失败（浅克隆没有 tag 时会出现）
        if not version:
            print("⚠ 无法解析 Hermes 版本（可能是浅克隆没有 tag），跳过版本比较")
        elif Version(str(version)) < Version(_MIN_HERMES_VERSION):
            failures.append(
                f"Hermes 版本 {version} 低于最低要求 {_MIN_HERMES_VERSION}"
            )
        else:
            print(f"✓ Hermes 版本 {version}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"版本检查异常：{exc}")

    # 3) 逐个 import 耦合点（与 CLAUDE.md「Hermes Coupling Points」手工同步）
    coupling_points = [
        ("run_agent", "AIAgent"),
        ("hermes_cli.config", "load_config"),
        ("hermes_cli.auth", "PROVIDER_REGISTRY"),
        ("hermes_cli.models", "provider_model_ids"),
        ("hermes_cli.env_loader", "load_hermes_dotenv"),
        ("hermes_constants", "get_hermes_home"),
    ]
    for module_name, symbol in coupling_points:
        try:
            module = __import__(module_name, fromlist=[symbol])
            # 符号存在性单独查：模块能 import 但符号被改名同样会炸 Trade
            if not hasattr(module, symbol):
                failures.append(f"{module_name} 缺少符号 {symbol}")
            else:
                print(f"✓ {module_name}.{symbol}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"import {module_name} 失败：{exc}")

    # 4) 汇总
    if failures:
        print("\n✗ Hermes 冒烟失败：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\n✓ Hermes 冒烟全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
