"""`trade company` —— 公司管理命令（作者用的隐藏功能，**不写进用户文档**）。

## 为什么需要

界面上的「删除」走 `DELETE /companies/{id}` → `crud.delete()`，**只做软删除**
（`is_active=0`）。删完公司从列表里消失，但：

  - 桌面上的公司文件夹（`~/Desktop/{公司名}/`）**还在**
  - `~/.trade/{slug}/` **还在**
  - 数据库行**还在**（只是 is_active=0）

`crud.purge()` 能把这些物理删干净，但全项目**没有任何入口调用它** ——
这就是"错误安装后留下的公司很难清理"的根本原因。

另外 `crud.delete()` 的注释写着「数据保留 30 天后由 purge() 执行物理清理」，
而既然没人调用 purge，那句 30 天承诺实际是空的。

## 为什么不放 UI

物理删除不可逆，且要连桌面文件夹一起删（那里面可能已经有用户的真实文件）。
放进隐藏的 CLI 而不是界面按钮，是为了不让人误点。

## 命令

    trade company list                    列出全部公司（含已软删除的）
    trade company purge <slug|id>         先打印"将要删除什么"，不动手
    trade company purge <slug|id> --yes   真的删
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
import time
from pathlib import Path

from trade.company.workdir import _WORK_DIR_CATEGORIES

# 桌面目录的识别指纹：工作目录由 _setup_work_directory 建成含这些分类子目录的结构。
# 用「命中数」而不是「全部命中」判定 —— 用户可能删掉或改名个别分类目录。
_ORPHAN_MIN_HITS = 5

# 清理口令：删除公司/残留目录前必须输入。
#
# 定位是**防误操作**（客户机常被远程操作，误删不可恢复），不是防攻击 ——
# 代码是公开的，口令自然也公开，这一点作者已知情（同许可证私钥那套「防君子不防小人」）。
# 校验发生在**预览之后、删除之前**：先看到"将要删什么"，再输口令授权。
# 只读的 `list` 不需要口令（诊断要方便）。
_PURGE_PASSWORD = "Lele@885918"


def _stdin_is_tty() -> bool:
    """当前是否有可用的交互终端。

    **Windows 上 `sys.stdin` 可能是 `None`** —— 用 `pythonw.exe` 跑、或进程被
    以无控制台方式分离启动时就是如此，直接调 `.isatty()` 会 AttributeError。
    那种环境当然也不该尝试读口令，一律当作"没有 TTY"。
    """
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _check_password(provided: str | None) -> tuple[str, str]:
    """校验清理口令。返回 (状态, 附加提示)。

    状态：``ok`` / ``wrong`` / ``no_tty`` / ``error``。

    没有 TTY 时不尝试读输入 —— `getpass` 在非交互环境会去读 stdin，
    在脚本/管道里表现为"卡住"或读到脏数据，不如直接告诉用户改用 `--password`。
    """
    if provided:
        return ("ok", "") if provided == _PURGE_PASSWORD else ("wrong", "")

    import getpass

    if not _stdin_is_tty():
        return (
            "no_tty",
            "  当前不是交互终端。请改用：\n"
            "      trade company <子命令> <目标> --yes --password <口令>\n",
        )
    try:
        entered = getpass.getpass("请输入清理口令：")
    except Exception as e:
        return ("error", f"  无法读取口令（{e}）。请改用 --password 传入。\n")
    return ("ok", "") if entered == _PURGE_PASSWORD else ("wrong", "")


def _password_gate(provided: str | None, lines: list[str]) -> bool:
    """在预览之后执行口令校验。通过返回 True；否则把原因写进 lines 并返回 False。"""
    status, hint = _check_password(provided)
    if status == "ok":
        return True
    lines.append("")
    if status in ("wrong", "error"):
        lines.append("  ✗ 口令错误，未执行任何删除。")
    else:  # no_tty
        lines.append("  ✗ 未提供口令，未执行任何删除。")
    if hint:
        lines.append(hint.rstrip("\n"))
    lines.append("")
    return False


def _parse_flags(args: list[str]) -> tuple[bool, str | None]:
    """从参数里取 --yes 与 --password <值>。返回 (yes, password)。"""
    yes = "--yes" in args
    password = None
    if "--password" in args:
        idx = args.index("--password")
        if idx + 1 < len(args):
            password = args[idx + 1]
    return yes, password


# ── 辅助 ──────────────────────────────────────────────────────────────────

def _resolve(target: str) -> dict | None:
    """按数字 ID 或 slug 找到公司（含已软删除的）。找不到返回 None。"""
    from trade.company import crud

    target = (target or "").strip()
    if not target:
        return None
    if target.isdigit():
        return crud.get(int(target))
    return crud.get_by_slug(target)


def _path_key(path: Path | str) -> str:
    """跨平台可比较的路径键（用于集合成员判断）。

    **Windows 的坑**：路径不区分大小写（`C:\\Users\\X` 与 `c:\\users\\x` 是同一个
    目录），而字符串比较区分。直接用 `str(path.resolve())` 做 `in` 判断时，只要
    记录里的大小写与实际解析结果不一致，同一目录就会被判成"不在已知集合里" ——
    后果是**在用公司的桌面文件夹被当成残留**，被 `purge-dir` 删掉。

    用 `os.path.normcase` 统一：Windows 上转小写，POSIX 上是恒等（正是要的语义）。

    注意 `relative_to()` 不受影响 —— `PureWindowsPath` 的比较本身就是大小写不敏感的，
    所以目录护栏那两处不用改。
    """
    p = Path(path)
    try:
        p = p.resolve()
    except (OSError, RuntimeError):
        # 解析失败时退回原路径，至少不崩：路径过长/权限（OSError），
        # 符号链接成环（3.12 及以前抛 RuntimeError）。输入来自数据库里的
        # `extra1.work_dir`，属于外部数据，不能假定它一定能解析。
        pass
    return os.path.normcase(str(p))


def _dir_stat(path: Path) -> dict:
    """统计一个目录：是否存在、文件数、总大小。不存在时全为 0。"""
    if not path.is_dir():
        return {"exists": False, "files": 0, "bytes": 0}
    files = 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            files += 1
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return {"exists": True, "files": files, "bytes": total}


def _clear_readonly_bits(root: Path) -> None:
    """清掉树下所有文件的只读属性（Windows 上 `rmtree` 需要）。

    Windows 上带只读属性的文件删不掉（WinError 5），而从共享盘/光盘/压缩包
    拷来的文件夹常带着这个属性。删除前统一清掉 —— 反正整棵树马上要删掉，
    改属性是授权范围内的动作。
    """
    try:
        entries = list(root.rglob("*"))
    except OSError:
        return  # 枚举都失败（路径过长/权限）就交给 rmtree 去报错
    for p in entries:
        try:
            if p.is_file() and not (p.stat().st_mode & stat.S_IWRITE):
                p.chmod(stat.S_IWRITE)
        except OSError:
            continue


def _rmtree(path: Path) -> None:
    """删除目录树，扛住两个 Windows 特有的失败模式。

    - **只读文件**：`shutil.rmtree` 遇到只读文件直接 WinError 5 → 先清属性再试。
    - **瞬时占用**：杀毒软件、资源管理器缩略图、OneDrive 同步会短暂锁住文件
      （WinError 32），这种锁通常几百毫秒内消失 —— 重试两次，比让用户
      "关掉资源管理器再跑一遍"强。

    POSIX 上两件事都不需要（目录写权限决定能否删除），但多做无害：
    第一次就成功时直接返回，不会走到重试。
    """
    last: OSError | None = None
    for attempt in range(3):
        try:
            shutil.rmtree(path)
            return
        except OSError as e:
            last = e
            if attempt < 2:  # 还有重试机会：清掉只读位、等一下让瞬时的锁释放
                _clear_readonly_bits(path)
                time.sleep(0.3 * (attempt + 1))
    raise last


def _reconfigure_streams() -> None:
    """把报告输出的编码错误降级，避免"删完了却崩在打印上"。

    控制台输出不受影响（PEP 528 直接写 UTF-16），但**重定向/管道**时 Windows
    用的是本地代码页（中文机 cp936、英文机 cp1252），而 `✓ ✗ ⚠` 不在其中 ——
    `print` 会抛 UnicodeEncodeError。删除动作已经发生，却崩在最后的报告上，
    操作者会以为没删成功（客户机常被远程操作，输出正是走管道）。
    只降级 `errors`、不改编码：控制台里中文照常，个别符号变 `?` 而已。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass  # 被包装/已关闭的流（pytest 捕获、GUI 环境）—— 无所谓


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"


def _delete_guard_ok(path: Path) -> bool:
    """该目录是否在「允许删除」的范围内。

    与 `crud.purge()` 的护栏一致：只删 TRADE_HOME 下、或桌面下的目录。
    在别处（用户自己搬走了工作目录）一律不动 —— 这里如实标出来给用户看。
    """
    from trade.company.crud import TRADE_HOME
    from trade.company.workdir import _get_desktop_path

    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in (TRADE_HOME, _get_desktop_path()):
        try:
            resolved.relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def _related_counts(company_id: int) -> dict:
    """统计关联行数（删除前让用户知道影响面）。"""
    from trade.database import get_connection

    conn = get_connection()
    try:
        out = {}
        for table in ("libraries", "customers", "conversations", "orders"):
            try:
                out[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE company_id = ?", (company_id,)
                ).fetchone()[0]
            except Exception:
                out[table] = 0
        return out
    finally:
        conn.close()


def _resolve_work_dir(company: dict) -> tuple[Path | None, str]:
    """找出这家公司的桌面工作目录。返回 (路径, 来源说明)。

    优先用 `extra1.work_dir` 里记录的路径；**记录为空时按公司名去桌面找** ——
    早期版本创建的公司没记这个字段（实测本机 company_id=4「万花筒」就是
    `extra1={}`），而它的桌面文件夹真实存在。不找回来的话，purge 会把那个
    文件夹留在桌面上 —— 正是用户抱怨的那种残留。

    只接受带 Trade 目录指纹的目录（≥5 个分类子目录），避免误认同名文件夹。
    """
    from trade.company.workdir import _get_desktop_path

    recorded = company.get("work_dir") or ""
    if recorded:
        return Path(recorded), "记录"

    desktop = _get_desktop_path()
    if not desktop.is_dir():
        return None, ""
    for candidate_name in (company.get("name") or "", company.get("slug") or ""):
        candidate_name = candidate_name.strip()
        if not candidate_name:
            continue
        candidate = desktop / candidate_name
        if is_trade_work_dir(candidate):
            return candidate, "按公司名找到"
    return None, ""


# ── 孤儿目录：桌面有 Trade 结构、数据库却没记录 ────────────────────────────

def is_trade_work_dir(path: Path) -> bool:
    """判断一个目录是不是 Trade 建的公司工作目录（按分类子目录指纹）。"""
    if not path.is_dir():
        return False
    try:
        names = {p.name for p in path.iterdir() if p.is_dir()}
    except OSError:
        return False
    hits = sum(1 for cat, _ in _WORK_DIR_CATEGORIES if cat in names)
    return hits >= _ORPHAN_MIN_HITS


def _known_company_paths_and_names() -> tuple[set[str], set[str]]:
    """返回 (已知 work_dir 的 resolve 路径集合, 已知公司名/slug 的集合)。

    **名字这一路是防误报的关键**：早期版本创建的公司 `extra1` 是空的
    （没记录 work_dir），但桌面文件夹真实存在且在**使用中**。只按路径判定就会
    把在用公司的文件夹当成孤儿 —— 而 purge-dir 会把它删掉。实测本机就有这种
    （company_id=4「万花筒」extra1={}，`~/Desktop/万花筒/` 却在用）。
    """
    import json as _json

    from trade.database import get_connection

    paths: set[str] = set()
    names: set[str] = set()
    conn = get_connection()
    try:
        for row in conn.execute("SELECT name, slug FROM companies"):
            if row[0]:
                names.add(str(row[0]).strip().lower())
            if row[1]:
                names.add(str(row[1]).strip().lower())
        for row in conn.execute(
            "SELECT extra1 FROM trade_companies WHERE extra1 IS NOT NULL AND extra1 != ''"
        ):
            try:
                wd = _json.loads(row[0]).get("work_dir", "")
                if wd:
                    paths.add(_path_key(wd))
            except Exception:
                continue
    finally:
        conn.close()
    return paths, names


def find_orphan_work_dirs() -> list[Path]:
    """桌面上有 Trade 目录结构、但**不属于任何已记录公司**的目录。

    错误安装的典型残留：文件夹建出来了，数据库却没落记录（或库被清过），
    于是从界面和 `list` 都看不到它，只能扫桌面找出来。

    判定保守：与任一公司的 **work_dir 路径**或**名字/slug** 相符就不算孤儿 ——
    宁可漏报（用户还能手动 purge-dir），绝不能误报（会删掉在用公司的真实文件）。
    """
    from trade.company.workdir import _get_desktop_path

    desktop = _get_desktop_path()
    if not desktop.is_dir():
        return []

    known_paths, known_names = _known_company_paths_and_names()

    orphans = []
    for child in desktop.iterdir():
        if not child.is_dir() or not is_trade_work_dir(child):
            continue
        if child.name.strip().lower() in known_names:
            continue  # 名字对得上某家公司 → 不是孤儿（老数据没记路径的情况）
        try:
            if _path_key(child) in known_paths:
                continue
        except OSError:
            continue
        orphans.append(child)
    return sorted(orphans)


# ── 命令：list ────────────────────────────────────────────────────────────

def list_companies() -> str:
    """`trade company list` 的实现。"""
    from trade.company.crud import TRADE_HOME
    from trade.database import get_connection

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, slug, is_active, created_at FROM companies ORDER BY id"
        ).fetchall()
        extra = {}
        for r in conn.execute(
            "SELECT company_id, data_dir, extra1 FROM trade_companies"
        ):
            work_dir = ""
            try:
                import json as _json

                if r[2]:
                    work_dir = _json.loads(r[2]).get("work_dir", "") or ""
            except Exception:
                work_dir = ""
            extra[r[0]] = (r[1] or "", work_dir)
    finally:
        conn.close()

    lines = ["", "══ 公司列表 ══"]
    if not rows:
        lines.append("  （数据库里没有任何公司）")
    for r in rows:
        cid, name, slug, is_active, created = r[0], r[1], r[2], r[3], r[4]
        data_dir, work_dir = extra.get(cid, ("", ""))
        state = "启用" if is_active else "已软删除"
        lines.append(f"  [{cid}] {name}  (slug: {slug})  — {state}  建于 {created}")
        if data_dir:
            st = _dir_stat(Path(data_dir))
            mark = f"{st['files']} 个文件 / {_fmt_size(st['bytes'])}" if st["exists"] else "不存在"
            lines.append(f"        数据目录 {data_dir}  [{mark}]")
        if work_dir:
            st = _dir_stat(Path(work_dir))
            mark = f"{st['files']} 个文件 / {_fmt_size(st['bytes'])}" if st["exists"] else "不存在"
            lines.append(f"        桌面目录 {work_dir}  [{mark}]")

    orphans = find_orphan_work_dirs()
    if orphans:
        lines.append("")
        lines.append("  ⚠ 桌面上还有 Trade 目录结构、但数据库无记录（错误安装的典型残留）：")
        for p in orphans:
            st = _dir_stat(p)
            lines.append(f"      {p}  [{st['files']} 个文件 / {_fmt_size(st['bytes'])}]")
        lines.append("      清理：trade company purge-dir \"<上面的路径>\"")
    lines.append("")
    lines.append(f"  数据根目录: {TRADE_HOME}")
    lines.append("")
    return "\n".join(lines)


# ── 命令：purge ───────────────────────────────────────────────────────────

def purge_company(target: str, *, yes: bool = False, password: str | None = None) -> tuple[str, int]:
    """`trade company purge` 的实现。返回 (报告文本, 退出码)。

    不加 `--yes` 时只打印计划并返回 1 —— 不用交互式确认，因为这条命令主要在
    远程 shell 里用，交互式提示容易踩到没有 TTY 的坑；强制两步更可靠。
    """
    from trade.company import crud

    company = _resolve(target)
    if not company:
        return f"✗ 找不到公司：{target!r}（用 trade company list 看有哪些）", 1

    cid = company["id"]
    tc = crud.get_trade_company(cid) or {}
    data_dir = Path(tc["data_dir"]) if tc.get("data_dir") else None

    work_dir = None
    conn = None
    try:
        from trade.database import get_connection

        conn = get_connection()
        row = conn.execute(
            "SELECT extra1 FROM trade_companies WHERE company_id = ?", (cid,)
        ).fetchone()
        if row and row[0]:
            import json as _json

            wd = _json.loads(row[0]).get("work_dir", "")
            company["work_dir"] = wd or ""
    except Exception:
        company["work_dir"] = ""
    finally:
        if conn is not None:
            conn.close()

    # 记录为空时按名字回找（老数据），否则 purge 会把桌面文件夹留在原地
    work_dir, work_dir_src = _resolve_work_dir(company)

    counts = _related_counts(cid)
    lines = [
        "",
        "══ 将要删除 ══",
        f"  公司      [{cid}] {company['name']}  (slug: {company['slug']})",
        f"  状态      {'启用' if company['is_active'] else '已软删除'}",
        f"  数据库行  1 家公司 + {counts['libraries']} 个文档库 + "
        f"{counts['customers']} 个客户 + {counts['conversations']} 条对话 + "
        f"{counts['orders']} 个订单（级联删除）",
    ]

    skipped: list[str] = []
    for label, path in (("数据目录", data_dir), ("桌面目录", work_dir)):
        if not path:
            continue
        st = _dir_stat(path)
        if not st["exists"]:
            lines.append(f"  {label}  {path}  [不存在，跳过]")
            continue
        if _delete_guard_ok(path):
            src = f"（{work_dir_src}）" if label == "桌面目录" and work_dir_src else ""
            lines.append(
                f"  {label}  {path}{src}  "
                f"[{st['files']} 个文件 / {_fmt_size(st['bytes'])}，一并删除]"
            )
        else:
            # 在护栏之外（用户把工作目录搬到了别处）—— 只提示，不动它
            lines.append(f"  {label}  {path}  [在保护范围之外，**不会删除**]")
            skipped.append(str(path))

    if not yes:
        lines.append("")
        lines.append("  以上是预览。确认无误后加 --yes 执行：")
        lines.append(f"      trade company purge {target} --yes")
        lines.append("")
        return "\n".join(lines), 1

    # 口令闸门：预览已打印、删除尚未开始 —— 用户看到影响面之后才被要求授权
    if not _password_gate(password, lines):
        return "\n".join(lines), 1

    ok = crud.purge(cid)
    lines.append("")
    if not ok:
        lines.append("  ✗ 删除失败（公司可能已不存在）")
        return "\n".join(lines), 1

    # crud.purge() 只删它从 extra1 里读到的 work_dir。老数据那里是空的，
    # 所以「按名字回找到」的那个文件夹它不会碰 —— 必须在这里补删，
    # 否则 purge 完桌面上仍留着公司文件夹（正是用户抱怨的残留）。
    if work_dir and work_dir_src == "按公司名找到" and _delete_guard_ok(work_dir):
        try:
            _rmtree(work_dir)
        except OSError as e:
            lines.append(f"  ⚠ 桌面目录删除失败：{e}")

    # 复核：把"说删了"变成"确认删了"
    lines.append("  ✓ 数据库行已删除")
    for label, path in (("数据目录", data_dir), ("桌面目录", work_dir)):
        if not path or not _delete_guard_ok(path):
            continue
        lines.append(
            f"  {'✓' if not path.exists() else '✗'} {label} {path} "
            f"{'已删除' if not path.exists() else '仍存在（请手动检查）'}"
        )
    if skipped:
        lines.append(f"  ⚠ 以下目录在保护范围外，未删除，请自行处理：{'、'.join(skipped)}")
    lines.append("")
    return "\n".join(lines), 0


def purge_dir(path_str: str, *, yes: bool = False, password: str | None = None) -> tuple[str, int]:
    """删除一个**孤儿**工作目录（数据库里没有对应公司记录的那种）。

    只接受通过 `is_trade_work_dir()` 指纹校验、且在桌面下的目录 ——
    避免这条命令被当成任意删除工具使用。
    """
    from trade.company.workdir import _get_desktop_path

    path = Path(path_str).expanduser()
    if not path.is_dir():
        return f"✗ 目录不存在：{path}", 1
    if not is_trade_work_dir(path):
        return (
            f"✗ 这个目录不像 Trade 建的公司文件夹（缺少分类子目录）：{path}\n"
            "  为防误删，本命令只处理带 Trade 目录结构的文件夹。",
            1,
        )
    try:
        path.resolve().relative_to(_get_desktop_path().resolve())
    except (ValueError, OSError):
        return f"✗ 只允许删除桌面下的目录：{path}", 1

    # 属于在用公司的文件夹一律不碰 —— 即便用户手动指定。
    # 这类文件夹（老数据没记 work_dir）里有该公司的真实业务文件，删了不可恢复。
    known_paths, known_names = _known_company_paths_and_names()
    looks_live = path.name.strip().lower() in known_names
    if not looks_live:
        try:
            looks_live = _path_key(path) in known_paths
        except OSError:
            looks_live = False
    if looks_live:
        return (
            f"✗ 这个文件夹属于一个**在用中的公司**，不能按残留目录删除：{path}\n"
            "  它里面可能有该公司的真实业务文件。\n"
            f"  若确实要清理，请先删除那家公司（会连文件夹一起清）：\n"
            f"      trade company purge <slug 或 ID>\n",
            1,
        )

    st = _dir_stat(path)
    preview = (
        f"\n══ 将要删除 ══\n"
        f"  {path}  [{st['files']} 个文件 / {_fmt_size(st['bytes'])}]\n"
    )
    if not yes:
        return (
            preview
            + f"\n  确认无误后加 --yes 执行：\n"
            f"      trade company purge-dir \"{path}\" --yes\n",
            1,
        )

    # 同样在预览之后、删除之前过口令闸门
    gate_lines: list[str] = []
    if not _password_gate(password, gate_lines):
        return preview + "\n".join(gate_lines), 1

    # 删除前先落审计（`crud.purge` 同样先写审计再动手）。公司场景传 company_id=0,
    # 因为孤儿目录本来就没有对应公司记录。
    #
    # 注意**不要**往被删的目录里写"凭据"文件 —— 那个文件会随 rmtree 一起消失,
    # 等于什么痕迹都没留（我第一版就是这么写的，纯属自欺）。
    try:
        from trade.company.crud import _write_audit_log

        _write_audit_log(
            0,
            "purge_orphan_dir",
            f"删除残留目录 {path}（{st['files']} 个文件 / {_fmt_size(st['bytes'])}）",
        )
    except Exception:
        pass  # 审计失败不阻断删除（但上面那句捕获范围要窄，避免吞掉 rmtree 的错误）

    try:
        _rmtree(path)
    except OSError as e:
        return f"✗ 删除失败：{e}", 1
    return f"  ✓ 已删除 {path}（{st['files']} 个文件 / {_fmt_size(st['bytes'])}）\n", 0


# ── 命令分发 ──────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    """`trade company <子命令>` 的入口。返回退出码。"""
    _reconfigure_streams()  # 报告里带 ✓/✗/⚠，Windows 管道输出要先降级编码错误
    sub = argv[0] if argv else ""
    rest = argv[1:]

    if sub in ("", "list"):
        print(list_companies())
        return 0

    if sub == "purge":
        if not rest:
            print("用法：trade company purge <slug 或 ID> [--yes [--password <口令>]]")
            return 1
        yes, password = _parse_flags(rest[1:])
        text, code = purge_company(rest[0], yes=yes, password=password)
        print(text)
        return code

    if sub == "purge-dir":
        if not rest:
            print('用法：trade company purge-dir "<桌面目录路径>" [--yes [--password <口令>]]')
            return 1
        yes, password = _parse_flags(rest[1:])
        text, code = purge_dir(rest[0], yes=yes, password=password)
        print(text)
        return code

    print(f"未知子命令：{sub}")
    print("可用：list / purge <slug|id> / purge-dir <路径>")
    return 1
