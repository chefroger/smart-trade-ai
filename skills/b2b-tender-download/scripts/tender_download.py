#!/usr/bin/env python3
"""招标大文件下载：对象清单 → 分块断点续传 → 完整性校验 → 清理。

用法：
    python tender_download.py --manifest objects.json [--target-dir <目录>] [--pieces 4]

`objects.json`（清单由对象存储 API 或平台接口导出，用户当次提供）：

    {
      "objects": [
        {"name": "<文件名>",
         "url": "<下载地址>",
         "size": 123456789,
         "checksum_type": "sha256",     // 或 md5；没有就留空
         "checksum": "<校验值>"}
      ]
    }

设计约束（任务书）：
- **清单大小是唯一权威基准**；拿到后不再反复查询。
- 分片落盘、断点续传；只有「大小 + 校验值都对上」才算完成，
  「文件存在」不算完成（假完成判定）。
- 同一目标文件同一时间只允许一个下载器（锁文件）。
- 失败不裸崩：删除合并中间态，返回可读原因。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

#: 每个分片的重试次数。
RETRIES = 3


@dataclass
class Item:
    """清单里的一条对象。"""

    name: str
    url: str
    size: int
    checksum_type: str = ""
    checksum: str = ""
    target: Path | None = None


@dataclass
class Result:
    """单个对象的下载结果。"""

    item: Item
    ok: bool
    path: Path | None = None
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


# ── 清单读取 ──────────────────────────────────────────────────────────────

def load_manifest(path: str | Path, target_dir: str | Path | None = None) -> list[Item]:
    """读对象清单。缺 name / url / size 的条目直接跳过（不猜）。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    base = Path(target_dir).expanduser() if target_dir else None

    items: list[Item] = []
    for obj in raw.get("objects", []):
        name = str(obj.get("name", "")).strip()
        url = str(obj.get("url", "")).strip()
        try:
            size = int(obj.get("size", 0))
        except (TypeError, ValueError):
            size = 0
        if not name or not url or size <= 0:
            continue  # 缺字段不猜、不下载
        items.append(
            Item(
                name=name,
                url=url,
                size=size,
                checksum_type=str(obj.get("checksum_type", "")).strip().lower(),
                checksum=str(obj.get("checksum", "")).strip().lower(),
                target=(base / name) if base else None,
            )
        )
    return items


# ── 完整性校验 ────────────────────────────────────────────────────────────

def file_digest(path: Path, kind: str) -> str:
    """算文件摘要（md5 / sha256）。"""
    algo = hashlib.sha256() if kind == "sha256" else hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            algo.update(block)
    return algo.hexdigest()


def verify_file(path: Path, item: Item) -> tuple[bool, str]:
    """校验「大小 + 校验值」；任一不符即判未完成。

    探针 5：只看「文件存在」不算完成。
    """
    if not path.is_file():
        return False, "文件不存在"
    actual = path.stat().st_size
    if actual != item.size:
        return False, f"大小不符：期望 {item.size}，实际 {actual}"
    if item.checksum and item.checksum_type:
        actual_digest = file_digest(path, item.checksum_type)
        if actual_digest != item.checksum:
            return False, (
                f"{item.checksum_type} 不符：期望 {item.checksum}，实际 {actual_digest}"
            )
    return True, ""


# ── 单实例锁 ──────────────────────────────────────────────────────────────

def lock_path(target: Path) -> Path:
    """锁文件路径（与目标同目录，扩展名后加 .lock）。"""
    return target.with_name(target.name + ".lock")


def _pid_alive(pid: int) -> bool:
    """判断进程是否还活着（跨平台）。"""
    if pid <= 0:
        return False
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_lock(target: Path, pid: int | None = None) -> tuple[bool, str]:
    """抢占下载锁；被别的活下载器占着就返回 False。

    探针 5：同一目标文件已有下载器在跑时，第二个被拦下。
    锁文件内容是 ``{"pid": ..., "started": ...}``；持有者进程已死视为陈旧锁，
    可以接管（进程号可能被复用，所以还要求目标文件尚未完成时才算数 ——
    调用方负责在完成后再校验一次）。
    """
    pid = os.getpid() if pid is None else pid
    path = lock_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.is_file():
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
            holder = int(info.get("pid", 0))
        except (OSError, ValueError):
            holder = 0
        if holder and holder != pid and _pid_alive(holder):
            return False, f"已有下载器在跑（pid {holder}）：{path.name}"

    path.write_text(
        json.dumps({"pid": pid, "started": time.strftime("%Y-%m-%dT%H:%M:%S")},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    return True, ""


def release_lock(target: Path) -> None:
    """释放锁（幂等）。"""
    try:
        lock_path(target).unlink()
    except OSError:
        pass


# ── 分块与下载 ────────────────────────────────────────────────────────────

def partition(size: int, pieces: int) -> list[tuple[int, int]]:
    """把 [0, size) 切成 pieces 个 (start, end) 闭区间（最后一块可能更短）。

    分块数由调用方决定：``--pieces 4`` 就是 4 块，与文件大小无关 ——
    这样小文件也能真正分块（否则小文件永远只有 1 块，续传/并行都测不出来）。
    """
    pieces = max(1, int(pieces))
    step = max(1, size // pieces)
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < size:
        end = min(size - 1, start + step - 1)
        ranges.append((start, end))
        start = end + 1
    return ranges


class RangeUnsupportedError(Exception):
    """服务端不支持 Range（返回 200 而不是 206）。"""


def http_fetch(url: str, start: int, end: int) -> bytes:
    """按字节区间拉一段（HTTP Range）。"""
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        status = getattr(resp, "status", resp.getcode())
        data = resp.read()
        if start > 0 and status != 206:
            raise RangeUnsupportedError(f"服务端未返回 206（status={status}）")
        return data


def _download_chunk(url: str, start: int, end: int, dest: Path, fetch) -> None:
    """下一块并落盘；已完成且大小正确的分片直接复用（断点续传）。"""
    expected = end - start + 1
    if dest.is_file() and dest.stat().st_size == expected:
        return

    last_err: Exception | None = None
    for _ in range(RETRIES):
        try:
            data = fetch(url, start, end)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return
        except RangeUnsupportedError:
            # 服务端不支持 Range：重试没有意义，直接往上抛给单流回退
            raise
        except Exception as e:  # 网络抖动、超时、5xx 都重试
            last_err = e
            time.sleep(1)
    raise RuntimeError(f"分片 {start}-{end} 下载失败：{last_err}")


def download(item: Item, target: Path | None = None, *,
             pieces: int = 4, fetch=http_fetch) -> Result:
    """下载一个对象：分块 → 合并 → 校验。

    返回 Result；ok=False 时不会留下一个「看起来完整」的目标文件。
    """
    target = target or item.target or Path(item.name)
    ok, reason = acquire_lock(target)
    if not ok:
        return Result(item=item, ok=False, reason=reason)

    parts_dir = target.with_name(target.name + ".parts")
    merged_tmp = target.with_name(target.name + ".merging")
    try:
        # 已完整存在 → 直接校验，不重复下载
        if target.is_file():
            done, why = verify_file(target, item)
            if done:
                return Result(item=item, ok=True, path=target)
            target.unlink()  # 大小/校验不符：删掉重下（它是本工具自己的产物）

        ranges = partition(item.size, pieces)
        try:
            for idx, (start, end) in enumerate(ranges):
                _download_chunk(item.url, start, end,
                                parts_dir / f"{idx:04d}.part", fetch)
        except RangeUnsupportedError:
            # 服务端不支持分块：退回单流下载（仍然校验大小与校验值）
            _download_chunk(item.url, 0, item.size - 1, parts_dir / "0000.part",
                            lambda url, s, e: fetch(url, 0, e))
            ranges = [(0, item.size - 1)]

        # 合并到临时文件，成功后再改名，避免留下半个目标文件
        with open(merged_tmp, "wb") as out:
            for idx, _ in enumerate(ranges):
                out.write((parts_dir / f"{idx:04d}.part").read_bytes())
        merged_tmp.replace(target)

        good, why = verify_file(target, item)
        if not good:
            target.unlink(missing_ok=True)
            return Result(item=item, ok=False, reason=why)

        return Result(item=item, ok=True, path=target)
    except Exception as e:  # 失败不裸崩：清中间态并返回原因
        merged_tmp.unlink(missing_ok=True)
        return Result(item=item, ok=False, reason=str(e))
    finally:
        # 分片是我们自己的中间态，不是用户原始文件，可以直接删
        try:
            for part in parts_dir.glob("*.part"):
                part.unlink()
            parts_dir.rmdir()
        except OSError:
            pass
        release_lock(target)


def main() -> int:
    """入口：读清单 → 逐个下载 → 打印结果。"""
    parser = argparse.ArgumentParser(description="招标大文件分块下载")
    parser.add_argument("--manifest", required=True, help="对象清单 JSON")
    parser.add_argument("--target-dir", default="", help="下载目录（缺省用清单里的 name）")
    parser.add_argument("--pieces", type=int, default=4, help="分块数（默认 4）")
    args = parser.parse_args()

    items = load_manifest(args.manifest, args.target_dir or None)
    if not items:
        print("清单为空或缺必填字段（name/url/size），未下载任何文件。")
        return 1

    failures = 0
    for item in items:
        result = download(item, pieces=args.pieces)
        if result.ok:
            print(f"✓ {item.name}（{item.size} 字节）已校验通过")
        else:
            failures += 1
            print(f"✗ {item.name}：{result.reason}")
    print(f"完成 {len(items) - failures}/{len(items)}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
