"""`trade vec` —— 客户语义检索索引维护命令。

语义检索默认关闭（TRADE_SEMANTIC=off）。本命令用于：
  - status  查看开关、扩展可用性与索引状态
  - rebuild 用全量客户重建索引（需先开启开关）
  - clear   清空向量表与词表（关闭状态下也可用）
"""

from __future__ import annotations

import argparse
import sys
import time

from trade import vec_search
from trade.database import get_connection


def _status_text() -> str:
    enabled = vec_search.semantic_enabled()
    available = vec_search.vec_available()
    conn = get_connection()
    try:
        stats = vec_search.index_status(conn)
    finally:
        conn.close()

    lines = [
        f"开关（TRADE_SEMANTIC）：{'on' if enabled else 'off（默认）'}",
        f"sqlite-vec 可用：{'是' if available else '否'}",
        f"索引行数：{stats['rows']}",
    ]
    if stats["updated_at"]:
        updated = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stats["updated_at"]))
        lines.append(f"维度/模型：{stats['dim']} / {stats['model']}")
        lines.append(f"最后更新：{updated}")
    else:
        lines.append("尚未建立索引")
    if not enabled:
        lines.append("提示：设置 TRADE_SEMANTIC=on 后重启 Trade 才会启用语义检索。")
    return "\n".join(lines)


def _rebuild() -> int:
    if not vec_search.semantic_enabled():
        print("语义检索当前关闭。先设置 TRADE_SEMANTIC=on，再执行重建。")
        return 1
    if not vec_search.vec_available():
        print("sqlite-vec 不可用（未安装或扩展加载失败），无法重建。")
        print("安装后可重试：pip install sqlite-vec")
        return 1
    conn = get_connection()
    try:
        n = vec_search.rebuild_all_customers(conn)
    finally:
        conn.close()
    print(f"重建完成：写入 {n} 条客户向量。")
    return 0


def _clear() -> int:
    conn = get_connection()
    try:
        ok = vec_search.clear_all_vectors(conn)
    finally:
        conn.close()
    if ok:
        print("已清空客户向量索引与词表。")
        return 0
    print("清空失败：sqlite-vec 不可用或索引损坏。")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trade vec",
        description="客户语义检索索引维护（默认关闭，TRADE_SEMANTIC=on 启用）",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status", help="查看开关与索引状态")
    sub.add_parser("rebuild", help="用全量客户重建索引（需开启开关）")
    sub.add_parser("clear", help="清空向量索引与词表")

    args = parser.parse_args(argv)
    if args.command == "rebuild":
        return _rebuild()
    if args.command == "clear":
        return _clear()
    print(_status_text())
    return 0


if __name__ == "__main__":  # pragma: no cover - 手动调试入口
    sys.exit(main())
