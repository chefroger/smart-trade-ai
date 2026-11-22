"""制裁名单的刷新调度与兼容接口（工单 P0-1）。

架构：
  - `sources.py` 负责下载 + 解析（官方主机白名单）
  - `store.py` 负责写入本地 SQLite 与查询
  - 本模块只做两件事：**后台每日刷新**，以及给旧调用方保留的薄封装

关键约束：`check_sanctions()` 不在请求路径上下载任何东西。名单只能在
后台刷新时更新；首次安装尚未刷新时，健康度会如实标记 degraded。
"""

from __future__ import annotations

import logging
import os
import threading
import time

from trade.osint.sanctions.sources import SOURCES, ParsedList, Source, fetch_source
from trade.osint.sanctions.store import (
    _connect,
    ensure_writable_db,
    list_entries,
    mark_failure,
    rebuild_fts,
    save_list,
)
from trade.osint.sanctions.store import (
    get_coverage as _get_coverage,
)

logger = logging.getLogger(__name__)

# 服务启动后延迟 60 秒再开始首次刷新（别和启动高峰抢带宽）
_INITIAL_DELAY_SECONDS = 60.0
# 之后每 24 小时刷新一次
_REFRESH_INTERVAL_SECONDS = 24 * 3600.0

_refresh_lock = threading.Lock()
_refresh_thread: threading.Thread | None = None


def refresh_all(
    *,
    fetch=fetch_source,
    sources: tuple[Source, ...] = SOURCES,
) -> dict:
    """下载并逐份刷新名单（每份名单单独一个事务，互不影响）。

    Args:
        fetch: 可注入的抓取函数（测试用），签名 (Source) -> ParsedList。
        sources: 要刷新的名单（测试可传子集）。

    Returns:
        {名单名: {"ok": bool, "entries": int, "aliases": int, "rows": int} | {"ok": False, "error": str}}
    """
    conn = _connect(write=True)
    results: dict[str, dict] = {}
    try:
        ensure_writable_db(conn)
        for source in sources:
            try:
                parsed: ParsedList = fetch(source)
                # 空解析按失败处理，旧数据原样保留（2026-11-22 审计 P1-1）。
                # 触发条件：官方格式变更、空文件、截断下载后解析器返回 0 行而不抛异常。
                if not parsed.rows or int(parsed.primary or 0) <= 0:
                    raise ValueError(
                        "解析结果为空"
                        f"（主名 {parsed.primary}，源行 {parsed.rows_total}），"
                        "保留上次成功数据"
                    )
                save_list(conn, source, parsed)
                # 立即重建 FTS：外部内容索引没有触发器，不重建的话查询端
                # 会按旧 rowid 匹配到新行（漏命中）。
                rebuild_fts(conn)
                conn.commit()
                results[source.name] = {
                    "ok": True,
                    "entries": parsed.primary,
                    "aliases": parsed.aliases,
                    "rows": parsed.rows_total,
                }
                logger.info(
                    "制裁名单刷新完成: %s（主名 %d，别名 %d，源行数 %d）",
                    source.name, parsed.primary, parsed.aliases, parsed.rows_total,
                )
            except Exception as exc:  # noqa: BLE001 —— 单份名单失败不拖垮其它
                logger.warning("制裁名单刷新失败: %s — %s", source.name, exc)
                mark_failure(conn, source, f"{type(exc).__name__}: {exc}")
                conn.commit()
                results[source.name] = {"ok": False, "error": str(exc)}
    finally:
        conn.close()
    return results


def start_background_refresh(
    delay: float = _INITIAL_DELAY_SECONDS,
    interval: float = _REFRESH_INTERVAL_SECONDS,
) -> bool:
    """启动后台刷新线程（幂等）。

    - 服务启动 60 秒后首次刷新，之后每 24 小时一次；
    - `TRADE_SANCTIONS_REFRESH=off` 可关闭（测试与离线环境）；
    - 线程为守护线程：进程退出不等待；刷新失败只记日志，绝不影响服务。
    """
    if os.environ.get("TRADE_SANCTIONS_REFRESH", "on").strip().casefold() in (
        "off", "0", "false", "no",
    ):
        return False

    global _refresh_thread
    with _refresh_lock:
        if _refresh_thread is not None and _refresh_thread.is_alive():
            return False

        def _loop() -> None:
            time.sleep(max(0.0, delay))
            while True:
                try:
                    refresh_all()
                except Exception:
                    logger.exception("制裁名单后台刷新异常")
                time.sleep(interval)

        _refresh_thread = threading.Thread(
            target=_loop, daemon=True, name="sanctions-refresh",
        )
        _refresh_thread.start()
        return True


# ── 旧接口兼容 ──────────────────────────────────────────────────────────────


def get_coverage() -> dict:
    """每份名单的覆盖情况（见 store.get_coverage）。"""
    return _get_coverage()


def get_cache() -> dict[str, list[dict]]:
    """返回内存形态的名单数据（兼容旧调用方；按需读取本地库）。"""
    return {source.name: list_entries(source.name) for source in SOURCES}


def load_ofac_sanctions() -> None:
    """兼容旧接口：数据由后台刷新写入本地库，这里**不下载**。"""
    return None


def load_un_sanctions() -> None:
    """兼容旧接口：数据由后台刷新写入本地库，这里**不下载**。"""
    return None
