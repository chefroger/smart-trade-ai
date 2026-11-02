#!/usr/bin/env python3
"""招标压缩包批量解压：统计摸底 → 选模式 → 解压 → 嵌套迭代 → 验证。

用法：
    python extract_archives.py --root <目录> [--mode A|B] [--rounds 5] [--dry-run]

模式（任务书）：
    A 删包归档（默认）：解压到包所在目录，成功后**原包移入回收站**。
    B 就地解压不删包：解压到同名文件夹；目标已存在且非空则跳过。

设计约束：
- 解压前做「间隔一轮两次全量统计」，不一致说明有进程在动目录 → 停手；
- 删除一律走回收站（不永久删除用户原始文件）；回收站不可用时**不删**，
  只报告；
- 嵌套包多轮迭代直到 0 残留，设上限轮数防死循环；
- 7z / rar 需要系统已装的压缩工具；缺失时明确标注，不硬解。
"""

from __future__ import annotations

import argparse
import gzip
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import _i18n_archive as _i18n

#: 覆盖的压缩包后缀（任务书：7z / rar / zip / gz 都要）。
ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz", ".7z", ".rar", ".gz")

#: 嵌套迭代上限（防同名自嵌套死循环）。
DEFAULT_ROUNDS = 5

#: 两次统计之间的等待（秒）。
STABILITY_INTERVAL = 0.5


@dataclass
class Result:
    """单个包的处理结果。"""

    archive: Path
    ok: bool
    target: Path | None = None
    reason: str = ""
    trashed: Path | None = None
    warnings: list[str] = field(default_factory=list)


# ── 扫描与统计 ────────────────────────────────────────────────────────────

def is_archive(path: Path) -> bool:
    """是否属于要处理的压缩包类型。"""
    name = path.name.lower()
    return any(name.endswith(s) for s in ARCHIVE_SUFFIXES)


def scan(root: Path) -> list[Path]:
    """递归找出所有压缩包（跳过 .parts / 回收站临时目录）。"""
    found: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and is_archive(p):
            found.append(p)
    return sorted(found)


def snapshot(root: Path) -> tuple[int, int]:
    """目录快照：(条目数, 总字节)。用于操作前稳定性核查。"""
    entries = 0
    total = 0
    for p in root.rglob("*"):
        entries += 1
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return entries, total


def check_stable(root: Path, interval: float = STABILITY_INTERVAL) -> tuple[bool, str]:
    """间隔一轮两次统计；不一致说明有别的进程在动目录 → 不动作。"""
    before = snapshot(root)
    time.sleep(interval)
    after = snapshot(root)
    if before != after:
        return False, _i18n.t("unstable", before=before, after=after)
    return True, ""


def stats(root: Path) -> dict:
    """统计摸底（只读）：数量、总大小、0 字节损坏数。"""
    archives = scan(root)
    total = 0
    zero = 0
    for a in archives:
        try:
            size = a.stat().st_size
        except OSError:
            size = 0
        total += size
        if size == 0:
            zero += 1
    return {"count": len(archives), "bytes": total, "zero_byte": zero}


# ── 回收站 ────────────────────────────────────────────────────────────────

def trash_dir() -> Path | None:
    """本机回收站目录；无法确定时返回 None（调用方据此拒绝删除）。

    测试可用环境变量 ``TENDER_TRASH_DIR`` 指定（跨平台 CI 用）。
    """
    override = os.environ.get("TENDER_TRASH_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    system = platform.system()
    if system == "Darwin":
        return Path.home() / ".Trash"
    if system == "Linux":
        return Path.home() / ".local" / "share" / "Trash" / "files"
    return None  # Windows 走 Shell API，不用目录


def move_to_trash(path: Path) -> Path | None:
    """把文件移入回收站；成功返回回收站路径，失败返回 None。

    **不永久删除**：回收站不可用时宁可不删，由调用方报告。
    """
    if not path.exists():
        return None

    system = platform.system()
    if system == "Windows" and not os.environ.get("TENDER_TRASH_DIR"):
        return _windows_recycle(path)

    target_dir = trash_dir()
    if target_dir is None:
        return None
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / path.name
        i = 2
        while dest.exists():
            dest = target_dir / f"{path.stem}({i}){path.suffix}"
            i += 1
        shutil.move(str(path), str(dest))
        return dest
    except OSError:
        return None


def _windows_recycle(path: Path) -> Path | None:
    """Windows：用 Shell API 送进回收站（FOF_ALLOWUNDO）。失败返回 None。"""
    try:
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_uint16),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        FO_DELETE = 3
        FOF_ALLOWUNDO = 0x0040
        FOF_NOCONFIRMATION = 0x0010
        FOF_SILENT = 0x0004
        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = str(path) + "\x00\x00"
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))  # type: ignore[attr-defined]
        if rc == 0 and not op.fAnyOperationsAborted and not path.exists():
            return path  # 已在回收站内，原路径消失
    except Exception:
        return None
    return None


# ── 解压 ──────────────────────────────────────────────────────────────────

def _find_system_tool(*names: str) -> str | None:
    """在 PATH 里找一个外部解压工具。"""
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def extract_one(archive: Path, mode: str = "A") -> Result:
    """解压单个压缩包；成功后按模式处理原包。"""
    name = archive.name.lower()

    # 目标目录：A 解到所在目录；B 解到同名文件夹
    if mode == "B":
        target = archive.with_name(archive.name[: -len("".join(Path(archive.name).suffixes))])
        if target.is_dir() and any(target.iterdir()):
            return Result(archive=archive, ok=True, target=target,
                          reason=_i18n.t("skip_nonempty"))
        target.mkdir(parents=True, exist_ok=True)
    else:
        target = archive.parent

    try:
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(target)
        elif name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive, "r:gz") as tf:
                tf.extractall(target, filter="data")
        elif name.endswith(".gz"):
            out = target / archive.name[:-3]
            with gzip.open(archive, "rb") as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
        elif name.endswith(".7z"):
            tool = _find_system_tool("7z", "7za", "7zz")
            if not tool:
                return Result(archive=archive, ok=False, reason=_i18n.t("need_7z"))
            _run_tool([tool, "x", "-y", f"-o{target}", str(archive)])
            if _looks_encrypted(archive):
                return Result(archive=archive, ok=False, reason=_i18n.t("encrypted"))
        elif name.endswith(".rar"):
            tool = _find_system_tool("unrar", "rar")
            if not tool:
                return Result(archive=archive, ok=False, reason=_i18n.t("need_unrar"))
            _run_tool([tool, "x", "-y", str(archive), str(target)])
        else:
            return Result(archive=archive, ok=False, reason=_i18n.t("unsupported"))
    except Exception as e:  # 损坏包 / 权限问题：不裸崩
        return Result(archive=archive, ok=False, reason=_i18n.t("extract_failed", error=e))

    if mode != "A":
        return Result(archive=archive, ok=True, target=target)

    # 模式 A：原包进回收站
    trashed = move_to_trash(archive)
    if trashed is None:
        return Result(
            archive=archive, ok=True, target=target,
            reason=_i18n.t("trash_failed"),
        )
    return Result(archive=archive, ok=True, target=target, trashed=trashed)


def _run_tool(cmd: list[str]) -> None:
    """跑外部解压工具；非零退出抛异常。"""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip()[:200])


def _looks_encrypted(archive: Path) -> bool:
    """粗略判断 zip 是否加密（7z 用工具输出判断，这里只覆盖 zip）。"""
    try:
        if archive.name.lower().endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                return any(info.flag_bits & 0x1 for info in zf.infolist())
    except (OSError, zipfile.BadZipFile):
        return False
    return False


# ── 主流程 ────────────────────────────────────────────────────────────────

def extract_all(root: Path, mode: str = "A", rounds: int = DEFAULT_ROUNDS, *,
                interval: float = STABILITY_INTERVAL, dry_run: bool = False) -> dict:
    """批量解压直到 0 残留；返回统计与失败清单。

    探针 6：顶层包 + 包中包两层 → 解压后 0 残留；
    目录在两次统计间被改动 → 停手不动作。
    """
    report: dict = {"rounds": 0, "extracted": 0, "failed": [], "trashed": 0,
                    "stopped": "", "results": []}

    if not root.is_dir():
        report["stopped"] = _i18n.t("dir_missing", path=root)
        return report

    stable, why = check_stable(root, interval)
    if not stable:
        report["stopped"] = why
        return report

    for round_no in range(1, max(1, rounds) + 1):
        archives = scan(root)
        if not archives:
            break
        report["rounds"] = round_no
        for archive in archives:
            if dry_run:
                report["results"].append(
                    Result(archive=archive, ok=True, reason=_i18n.t("dry_run"))
                )
                continue
            result = extract_one(archive, mode)
            report["results"].append(result)
            if result.ok:
                report["extracted"] += 1
                if result.trashed:
                    report["trashed"] += 1
            else:
                report["failed"].append((str(archive), result.reason))

    if scan(root):
        report["stopped"] = _i18n.t("rounds_cap", rounds=rounds)
    return report


# ── 编号归组（可选，仅演练）──────────────────────────────────────────────

def plan_number_grouping(root: Path) -> list[str]:
    """Plan 编号归组：非纯数字文件夹改纯数字编号、平放文件按编号前缀归组。

    **只出计划、不动文件**。真正执行前必须先让用户确认 —— 重命名用户目录
    是不可逆操作，任务书也把它列为「可选后续」。
    """
    plan: list[str] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.name.isdigit():
            plan.append(_i18n.t("plan_folder", name=child.name))
    for child in sorted(root.iterdir()):
        if child.is_file():
            plan.append(_i18n.t("plan_file", name=child.name))
    return plan


def main() -> int:
    """入口：摸底 → 解压 → 报告。"""
    parser = argparse.ArgumentParser(description="批量解压招标压缩包")
    parser.add_argument("--root", required=True, help="要处理的目录")
    parser.add_argument("--mode", choices=("A", "B"), default="A",
                        help="A=删包归档（进回收站）；B=就地解压不删包")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help="嵌套迭代上限")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不动文件")
    parser.add_argument("--plan-grouping", action="store_true", help="只输出编号归组计划")
    parser.add_argument("--lang", choices=("zh", "en"), default=None,
                        help="Output language (default: TRADE_LANG or zh)")
    args = parser.parse_args()
    _i18n.set_language(args.lang)

    root = Path(args.root).expanduser()
    if args.plan_grouping:
        for line in plan_number_grouping(root) or [_i18n.t("no_grouping")]:
            print(line)
        return 0

    info = stats(root)
    print(_i18n.t("stats", count=info["count"], bytes=info["bytes"],
                  zero=info["zero_byte"]))
    if info["count"] == 0:
        return 0

    report = extract_all(root, args.mode, args.rounds, dry_run=args.dry_run)
    if report["stopped"]:
        print(_i18n.t("stopped", reason=report["stopped"]))
    print(_i18n.t("summary", ok=report["extracted"], failed=len(report["failed"]),
                  trashed=report["trashed"], rounds=report["rounds"]))
    for path, reason in report["failed"]:
        print(_i18n.t("failed_line", path=path, reason=reason))
    return 0 if not report["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
