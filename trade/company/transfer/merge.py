"""导入时的幂等去重与 Hermes MEMORY.md 合并。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

_MEMORY_HEADER_RE = re.compile(
    r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2})\](?P<context>.*)$"
)
_COMPANY_TAG_RE = re.compile(r"\[公司:\s*([^,\]]+)")


def norm_name(name: str | None) -> str:
    """公司名匹配键：去首尾空白、压缩内部空白、大小写不敏感。"""
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def _company_from_header(line: str) -> str | None:
    match = _COMPANY_TAG_RE.search(line or "")
    return match.group(1).strip() if match else None


def extract_memory_blocks(text: str, company_name: str) -> list[str]:
    """从 MEMORY.md 提取属于指定公司的完整条目块。

    条目以 `[YYYY-MM-DD HH:MM] [公司: X, ...]` 开头，块之间以空行分隔。
    """
    if not text or not company_name:
        return []
    target = norm_name(company_name)
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if not current:
            return
        block = "\n".join(current).strip()
        first = current[0].strip()
        header = _MEMORY_HEADER_RE.match(first)
        if header and norm_name(_company_from_header(first)) == target:
            blocks.append(block)
        current.clear()

    for line in text.splitlines():
        if line.strip() == "":
            flush()
        else:
            current.append(line)
    flush()
    return blocks


def rewrite_company_tag(block: str, target_name: str) -> str:
    """把条目里的 `[公司: 源名]` 改成目标公司名称。"""
    def _replace(match: re.Match) -> str:
        return "[公司: " + target_name

    return _COMPANY_TAG_RE.sub(_replace, block, count=1)


def block_hash(block: str) -> str:
    return hashlib.sha256(block.strip().encode("utf-8")).hexdigest()


def _memory_file() -> Path:
    try:
        from trade.post_install.skills import _get_hermes_home

        hermes_root = _get_hermes_home()
    except Exception:  # noqa: BLE001 — 环境异常时退回常见路径
        raw = os.environ.get("HERMES_HOME", "").strip()
        if raw:
            hermes_root = Path(raw)
        elif os.name == "nt":
            local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
            hermes_root = Path(local) / "hermes"
        else:
            hermes_root = Path.home() / ".hermes"
    return Path(hermes_root) / "memories" / "MEMORY.md"


def append_memory_blocks(blocks: list[str]) -> dict:
    """把公司记忆块追加到 MEMORY.md 的 B2B 段；按块 hash 去重。

    返回 {"added": n, "skipped": n, "path": str}。
    """
    if not blocks:
        return {"added": 0, "skipped": 0, "path": str(_memory_file())}

    memory_file = _memory_file()
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file = memory_file.with_suffix(memory_file.suffix + ".lock")
    section = "## Foreign Trade Assistant — B2B Trade Memory\n"
    added = skipped = 0

    if os.name != "nt":
        import fcntl

    lock_fd = open(str(lock_file), "w")
    try:
        for _attempt in range(5):
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("cannot lock Hermes MEMORY.md")

        # utf-8-sig：Windows 记事本编辑过的 MEMORY.md 可能带 BOM，BOM 会让首行
        # 标题正则匹配失败，整段公司记忆被静默丢掉
        existing = memory_file.read_text(encoding="utf-8-sig") if memory_file.exists() else ""
        existing_hashes = {
            block_hash(block)
            for block in _split_all_blocks(existing)
        }
        fresh: list[str] = []
        for block in blocks:
            digest = block_hash(block)
            if digest in existing_hashes:
                skipped += 1
                continue
            existing_hashes.add(digest)
            fresh.append(block.strip())
            added += 1

        if fresh:
            payload = "\n\n".join(fresh) + "\n\n"
            if section not in existing:
                content = section + "\n" + payload + existing if existing else section + "\n" + payload
            else:
                idx = existing.find(section) + len(section)
                prefix = existing[:idx].rstrip("\n") + "\n\n"
                suffix = existing[idx:].lstrip("\n")
                content = prefix + payload + suffix
            memory_file.write_text(content, encoding="utf-8")
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                lock_fd.seek(0)
                msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        except Exception:  # noqa: BLE001
            pass
        lock_fd.close()
        try:
            lock_file.unlink(missing_ok=True)
        except OSError:
            pass

    return {"added": added, "skipped": skipped, "path": str(memory_file)}


def _split_all_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                blocks.append("\n".join(current).strip())
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())

    result: list[str] = []
    for block in blocks:
        lines = block.splitlines()
        # memory.py 会把条目直接接在段标题下一行（没有空行），这里剥掉标题再判断
        if lines and lines[0].startswith("## Foreign Trade Assistant"):
            lines = lines[1:]
            block = "\n".join(lines).strip()
        if block and _MEMORY_HEADER_RE.match(block.splitlines()[0].strip()):
            result.append(block)
    return result


def conversation_key(row: dict) -> str:
    payload = "|".join(
        str(row.get(key) or "")
        for key in ("query", "response", "created_at", "context")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def order_signature(row: dict, items: list[dict]) -> str:
    """订单去重键：优先 order_no，否则用客户 + 摘要 + 明细签名。

    `customer_id` 必须由调用方传入**重映射后**的值（源包与目标库的自增 ID
    不同，否则同一订单永远匹配不上）。明细里的自增/时间戳字段同理要剔除 ——
    两侧的 id / order_id / created_at 天然不同，带着它们算签名等于永不去重
    （2026-11-11 自查：无 order_no 的订单重复导入会翻倍）。
    """
    number = (row.get("order_no") or "").strip()
    if number:
        return "no:" + number
    volatile = {"id", "order_id", "created_at", "updated_at"}
    payload = {
        "customer_id": row.get("customer_id"),
        "product_name": row.get("product_name"),
        "quantity": row.get("quantity"),
        "unit": row.get("unit"),
        "unit_price": row.get("unit_price"),
        "currency": row.get("currency"),
        "total_amount": row.get("total_amount"),
        "created_at": row.get("created_at"),
        "items": sorted(
            json.dumps(
                {key: value for key, value in item.items() if key not in volatile},
                sort_keys=True,
                ensure_ascii=False,
            )
            for item in items
        ),
    }
    return "sig:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
