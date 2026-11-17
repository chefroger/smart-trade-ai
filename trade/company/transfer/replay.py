"""Hindsight 远程记忆重放（best-effort）。

Hindsight 没有 list/export API，源机器的 bank 无法整体拉取。导入后把本地
conversations 重新 retain 到目标公司新的 bank_id，尽可能恢复可检索记忆。
无 API key 时直接跳过，不阻断导入。
"""

from __future__ import annotations

import threading
import time


def replay_hindsight(company_id: int, conversations: list[dict],
                     library_names: dict[int, str] | None = None,
                     customer_names: dict[int, str] | None = None) -> dict:
    """同步重放；调用方按需放进后台线程。返回统计。"""
    try:
        from trade import memory as memory_mod
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "error": str(exc), "replayed": 0}

    if not conversations:
        return {"status": "skipped", "replayed": 0}
    if not memory_mod.is_available():
        return {"status": "disabled", "replayed": 0}

    bank_id = f"trade-company-{company_id}"
    replayed = failed = 0
    for row in conversations:
        try:
            ok = memory_mod.retain_conversation(
                row.get("query") or "",
                row.get("response") or "",
                library_name=(library_names or {}).get(row.get("library_id") or -1, ""),
                customer_name=(customer_names or {}).get(row.get("customer_id") or -1, ""),
                company_id=company_id,
                bank_id=bank_id,
            )
            replayed += 1 if ok else 0
            failed += 0 if ok else 1
        except Exception:  # noqa: BLE001 — 单条失败不阻断其余
            failed += 1
        time.sleep(0.05)
    return {"status": "done", "replayed": replayed, "failed": failed, "bank_id": bank_id}


def replay_hindsight_async(company_id: int, conversations: list[dict],
                           library_names: dict[int, str] | None = None,
                           customer_names: dict[int, str] | None = None) -> str:
    """在后台线程重放，返回 "queued" / "disabled"。"""
    try:
        from trade import memory as memory_mod

        if not conversations or not memory_mod.is_available():
            return "disabled"
    except Exception:  # noqa: BLE001
        return "disabled"

    thread = threading.Thread(
        target=replay_hindsight,
        args=(company_id, conversations, library_names, customer_names),
        daemon=True,
    )
    thread.start()
    return "queued"
