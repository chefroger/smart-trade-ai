#!/usr/bin/env python3
"""制裁名单真实下载冒烟（2026-11-23 审计 P0-A）。

普通测试全部 mock 网络，测不到「官方站点的重定向目标变了」这类问题。
本脚本对全部六份名单（OFAC SDN / OFAC 非 SDN / CSL / UN / EU / UK）真实
发起下载，只读前 1 MB 就断开，断言 HTTP 200、读到非空字节，且最终主机
仍在两层白名单内（入口主机 + 按入口配对的跳转目标）。

用法：
    python scripts/sanctions_smoke.py
退出码：0 通过 / 1 失败（逐项打印入口主机、最终主机与原因）
"""

from __future__ import annotations

import sys
from pathlib import Path

# 冒烟目标（S10）：覆盖全部名单。OFAC 与 UN 历史上都 302 到官方 CDN
# （审计 P0-A 的触发点）；EU / UK / CSL 也要查 —— EU 返回 500 时现有
# 只测两份的冒烟完全看不出来。
TARGETS = ("OFAC", "OFAC_NS", "CSL", "UN", "EU", "UK")


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    # 让 scripts/ 里的脚本也能 import 仓库内的 trade 包
    sys.path.insert(0, str(repo))

    from trade.osint.sanctions.sources import PROBE_BYTES, SOURCES, probe_official

    failures: list[str] = []
    for source in SOURCES:
        if source.name not in TARGETS:
            continue
        result = probe_official(source.urls[0], max_bytes=PROBE_BYTES)
        if result["ok"] and result["bytes_read"] <= 0:
            result["ok"] = False
            result["error"] = "下载 0 字节（空响应）"
        if result["ok"]:
            print(
                f"✓ {source.name}：{result['entry_host']} → "
                f"{result['final_host']}（已读 {result['bytes_read']} 字节）"
            )
        else:
            print(
                f"✗ {source.name}：入口 {result['entry_host'] or '?'} → "
                f"{result['final_host'] or '?'} —— {result['error']}"
            )
            failures.append(source.name)

    if failures:
        print("\n✗ 制裁名单真实下载冒烟失败：" + "、".join(failures))
        return 1
    print("\n✓ 制裁名单真实下载冒烟通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
