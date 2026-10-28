"""
Trade AI Assistant — B2B Skills 安装器。

将项目内置的 37 个 skill 从 Python 包目录复制到 Hermes runtime skills 目录：
  {package}/skills/b2b-*/SKILL.md → ~/.hermes/skills/b2b-*/SKILL.md

Hermes Agent 从 ~/.hermes/skills/ 自动发现 skill 定义并注入到 AI 提示词中。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


def _get_hermes_home() -> Path:
    """解析 Hermes 安装根目录（HERMES_HOME 环境变量 → 平台默认路径）。

    镜像 hermes_constants.get_hermes_home() 实现，避免 import 循环依赖。
    """
    val = os.environ.get("HERMES_HOME", "").strip()
    if val:
        return Path(val)  # 显式设置了 HERMES_HOME，直接使用
    if os.name == "nt":
        _local = os.environ.get(
            "LOCALAPPDATA", str(Path.home() / "AppData" / "Local")
        )
        return Path(_local) / "hermes"
    return Path.home() / ".hermes"


def _get_trade_home() -> Path:
    """解析 Trade 用户数据目录（TRADE_HOME 环境变量 → 平台默认路径）。

    macOS/Linux: ~/.trade/
    Windows:     %LOCALAPPDATA%\\trade\\
    """
    val = os.environ.get("TRADE_HOME", "").strip()
    if val:
        return Path(val)
    if os.name == "nt":
        local_appdata = os.environ.get(
            "LOCALAPPDATA", str(Path.home() / "AppData" / "Local")
        )
        return Path(local_appdata) / "trade"
    return Path.home() / ".trade"


def _get_package_skills_dir() -> Path | None:
    """查找已安装 pip 包中的 skills 目录。

    搜索策略（按优先级）：
      1. sys._MEIPASS — PyInstaller 打包模式的临时解压目录
      2. sys.path 中的 trade 包目录（pip install . 场景）
      3. 当前脚本所在目录的父级（pip install -e . 开发模式）

    Returns:
        skills 目录的 Path，找不到时返回 None
    """
    # 策略 0: PyInstaller one-file 模式 — sys._MEIPASS 是临时解压目录
    # tradewin.spec 已将 skills/ 打包为 datas，解压后位于 _MEIPASS/skills/
    _meipass = getattr(sys, "_MEIPASS", None)
    if _meipass:
        meipass_skills = Path(_meipass) / "skills"
        if meipass_skills.is_dir():
            return meipass_skills

    # 策略 1: 遍历 sys.path，检查每个路径下是否有 trade/__init__.py
    for prefix in list(sys.path):
        p = Path(prefix)
        if not p.is_dir():
            continue
        candidate = p / "trade" / "__init__.py"
        if candidate.exists():
            skills_dir = candidate.parent.parent / "skills"
            if skills_dir.is_dir():
                return skills_dir

    # 策略 2: 从本脚本所在路径向上查找（开发模式，本项目根目录）
    self_dir = Path(__file__).parent.parent.parent  # post_install/skills.py → 项目根
    dev_skills = self_dir / "skills"
    if dev_skills.is_dir():
        return dev_skills

    return None


_MANIFEST_SCHEMA = 2
_MANIFEST_NAME = ".sync-manifest.json"
_MANIFEST_HISTORY_LIMIT = 20


def _skill_dir_names(dst_base: Path) -> list[str]:
    """目标目录里的受管 skill 名（排除停用项与临时目录）。"""
    from trade.skill_registry import _BLOCKED_SKILLS

    try:
        return sorted(
            d.name for d in dst_base.iterdir()
            if d.is_dir()
            and (
                d.name.startswith("b2b-")
                or d.name.startswith("auto-")
                or d.name == "chat-memory"
            )
            and d.name not in _BLOCKED_SKILLS
        )
    except OSError:
        return []


def _manifest_files(dst_base: Path) -> dict[str, str]:
    """SKILL.md + references/ 下全部文件的 SHA-256（相对路径 → 哈希）。"""
    files: dict[str, str] = {}
    for name in _skill_dir_names(dst_base):
        skill_dir = dst_base / name
        candidates = []
        skill_md = skill_dir / "SKILL.md"
        if skill_md.is_file():
            candidates.append(skill_md)
        refs = skill_dir / "references"
        if refs.is_dir():
            candidates.extend(
                p for p in sorted(refs.rglob("*"))
                if p.is_file() and p.name != ".DS_Store"
                and p.suffix not in {".pyc", ".pyo"}
            )
        for path in candidates:
            try:
                files[path.relative_to(dst_base).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
            except OSError:
                continue
    return files


def _manifest_digest(updated_at: str, files: dict[str, str]) -> str:
    """清单自哈希：覆盖 schema / updated_at / files（history 用哈希链单独校验）。"""
    raw = json.dumps(
        {"schema": _MANIFEST_SCHEMA, "updated_at": updated_at, "files": files},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _history_entry_hash(entry: dict) -> str:
    """单条 history 的哈希（覆盖 prev_hash，形成链）。"""
    payload = {
        key: entry.get(key)
        for key in ("updated_at", "file_count", "manifest_hash", "prev_hash")
    }
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _verify_history_chain(history: list, anchor: str) -> bool:
    """按链顺序校验 history；截断后第一条的 prev_hash 必须等于 anchor。"""
    prev = anchor or ""
    for entry in history:
        if not isinstance(entry, dict):
            return False
        if entry.get("prev_hash") != prev:
            return False
        if entry.get("entry_hash") != _history_entry_hash(entry):
            return False
        prev = entry.get("entry_hash")
    return True


def _write_skill_manifest(dst_base: Path, names: list[str] | None = None) -> None:
    """写清单 v2：SKILL.md + references 全量哈希、历史、自哈希（审计 P2-3）。

    `names` 仅为兼容保留，**不决定清单内容**：安装路径只传本次新增 skill 时，
    清单会丢掉目录里已有条目（W5）。一律扫描目标目录。
    """
    try:
        files = _manifest_files(dst_base)
        updated_at = datetime.now().isoformat(timespec="seconds")
        manifest = dst_base / _MANIFEST_NAME
        history: list = []
        anchor = ""
        try:
            old = json.loads(manifest.read_text(encoding="utf-8"))
            old_history = old.get("history") if isinstance(old, dict) else None
            # 旧版清单没有链字段：直接重新起链，避免把无 entry_hash 的条目掺进来
            if isinstance(old_history, list) and all(
                isinstance(e, dict) and isinstance(e.get("entry_hash"), str)
                for e in old_history
            ):
                history = old_history[-_MANIFEST_HISTORY_LIMIT:]
                anchor = str(old.get("history_anchor") or "")
        except (OSError, ValueError):
            history = []
            anchor = ""
        digest = _manifest_digest(updated_at, files)
        entry = {
            "updated_at": updated_at,
            "file_count": len(files),
            "manifest_hash": digest,
            "prev_hash": history[-1]["entry_hash"] if history else anchor,
        }
        entry["entry_hash"] = _history_entry_hash(entry)
        history = history + [entry]
        if len(history) > _MANIFEST_HISTORY_LIMIT:
            dropped = len(history) - _MANIFEST_HISTORY_LIMIT
            anchor = history[dropped - 1]["entry_hash"]
            history = history[dropped:]
        data = {
            "schema": _MANIFEST_SCHEMA,
            "updated_at": updated_at,
            "history": history,
            "history_anchor": anchor,
            "files": files,
            "manifest_hash": digest,
        }
        tmp = manifest.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(manifest)
    except Exception as e:
        print(f"  ⚠ skill manifest 写入失败（不影响同步）：{e}", file=sys.stderr)


def verify_skill_manifest(dst_base: Path) -> dict:
    """读取清单并与磁盘比对（W5）；返回结构化报告，不抛异常。

    能发现：清单缺失/损坏、自哈希不符（清单被改）、文件缺失、清单漏记、
    文件哈希变化。签名/来源证明不在此层（另档）。
    """
    empty = {
        "ok": False, "reason": "",
        "missing_on_disk": [], "missing_in_manifest": [], "hash_mismatch": [],
    }
    manifest = dst_base / _MANIFEST_NAME
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except OSError:
        return {**empty, "reason": "manifest_missing"}
    except ValueError:
        return {**empty, "reason": "manifest_corrupt"}
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return {**empty, "reason": "manifest_invalid"}

    recorded: dict[str, str] = data["files"]
    updated_at = data.get("updated_at")
    expected = data.get("manifest_hash")
    if not isinstance(updated_at, str) or not isinstance(expected, str):
        return {**empty, "reason": "self_hash_missing"}
    if _manifest_digest(updated_at, recorded) != expected:
        return {**empty, "reason": "self_hash_mismatch"}

    history = data.get("history")
    anchor = data.get("history_anchor", "")
    if (
        not isinstance(history, list)
        or not isinstance(anchor, str)
        or not _verify_history_chain(history, anchor)
    ):
        return {**empty, "reason": "history_chain_mismatch"}

    actual = _manifest_files(dst_base)
    missing_on_disk = sorted(set(recorded) - set(actual))
    missing_in_manifest = sorted(set(actual) - set(recorded))
    hash_mismatch = sorted(
        name for name in set(recorded) & set(actual)
        if recorded[name] != actual[name]
    )
    ok = not (missing_on_disk or missing_in_manifest or hash_mismatch)
    return {
        "ok": ok,
        "reason": "ok" if ok else "files_mismatch",
        "missing_on_disk": missing_on_disk,
        "missing_in_manifest": missing_in_manifest,
        "hash_mismatch": hash_mismatch,
    }


def _verify_manifest_or_warn(dst_base: Path) -> None:
    """写完后立刻验一遍：写入/落盘异常要在日志里留痕，而不是静默。"""
    report = verify_skill_manifest(dst_base)
    if report["ok"]:
        return
    detail = report["reason"]
    if report["reason"] == "files_mismatch":
        detail += (
            f"（缺失 {len(report['missing_on_disk'])}，"
            f"漏记 {len(report['missing_in_manifest'])}，"
            f"哈希不符 {len(report['hash_mismatch'])}）"
        )
    print(f"  ⚠ skill 清单校验未通过：{detail}", file=sys.stderr)


def _purge_blocked_skills(dst_base: Path) -> None:
    """无条件删除 Hermes 运行时里的停用 skill 目录。

    只靠迭代源目录时命中 blocked 名来清理会漏：包内源目录日后被删掉后，
    用户机器上残留的旧目录就再也不会被清（审计 P1-13 残留）。
    """
    from trade.skill_registry import _BLOCKED_SKILLS

    for name in _BLOCKED_SKILLS:
        stale = dst_base / name
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)


def _copy_skills(src: Path, dst_base: Path, progress_callback=None) -> list[str]:
    """将 src 下的所有 skill 目录复制到 dst_base 对应的 skill 目录。

    每个 skill 在目标创建 dst_base/{name}/SKILL.md。
    处理 b2b-* 和 auto-* 前缀的目录，忽略其他文件和目录。

    Args:
        progress_callback: 可选回调 f(msg)，每安装一个 skill 调用一次

    Returns:
        已安装的 skill 目录名列表（如 ["b2b-document", "b2b-osint", ...]）；
        `_BLOCKED_SKILLS` 内的 skill 不会被复制
    """
    _purge_blocked_skills(dst_base)
    installed = []
    for skill_dir in sorted(src.iterdir()):
        if not skill_dir.is_dir():
            continue
        if not (skill_dir.name.startswith("b2b-") or skill_dir.name.startswith("auto-") or skill_dir.name == "chat-memory"):
            continue
        # 被 trade 停用的 skill 不允许装进 Hermes 运行时（审计 P1-13）：
        # 路由层不注入只是第一层，装进 ~/.hermes/skills/ 后模型仍能读到。
        from trade.skill_registry import _BLOCKED_SKILLS

        if skill_dir.name in _BLOCKED_SKILLS:
            stale = dst_base / skill_dir.name
            if stale.exists():
                shutil.rmtree(stale, ignore_errors=True)
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue

        # 复制 SKILL.md
        dest = dst_base / skill_dir.name / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_file, dest)

        # 同步复制 references/ 子目录（如 qa_pairs.md）
        refs_src = skill_dir / "references"
        if refs_src.is_dir():
            refs_dst = dst_base / skill_dir.name / "references"
            if refs_dst.exists():
                shutil.rmtree(refs_dst)
            shutil.copytree(refs_src, refs_dst)

        installed.append(skill_dir.name)
        if progress_callback:
            progress_callback(f"  ✓ {skill_dir.name}")

    # 安装路径也要全目录扫描：只传本次 installed 会丢掉目录里已有的 skill（W5）
    _write_skill_manifest(dst_base)
    _verify_manifest_or_warn(dst_base)
    return installed


def _copy_trade_template(src: Path, dst: Path) -> None:
    """将 .trade-template/ 目录复制到 Trade 运行时数据目录。

    仅当目标不存在时才复制，避免覆盖用户已有的模板修改。
    同时植入 prompts/system.md 初始提示词文件。

    Args:
        src: 源码中的 .trade-template/ 目录
        dst: Trade 运行时目录（~/.trade/）
    """
    if src.is_dir():
        dest = dst / ".trade-template"
        if not dest.exists():
            shutil.copytree(src, dest, dirs_exist_ok=False)
            for f in dest.rglob("*"):
                if f.is_file() and os.name != "nt":
                    f.chmod(0o644)  # 设置为用户可读写（Windows 不支持 chmod）

    # 植入初始 system prompt（仅当目标不存在时，避免覆盖用户自定义内容）
    prompts_src = src / "prompts" / "system.md"
    prompts_dir = dst / "prompts"
    prompts_dst = prompts_dir / "system.md"
    if prompts_src.is_file() and not prompts_dst.is_file():
        prompts_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prompts_src, prompts_dst)
        if os.name != "nt":
            prompts_dst.chmod(0o644)


# ── 公开 API ──────────────────────────────────────────────────────────────

def install_skills(progress_callback=None) -> None:
    """主入口：将 Trade B2B skills 安装到 Hermes skills 目录。

    调用方式：
      - pip install -e . 或 pip install .（setuptools post-install hook）
      - 手动执行: install-trade-skills（pyproject.toml console_scripts）

    Args:
        progress_callback: 可选回调函数 f(msg: str)，用于 PyInstaller wizard 进度报告

    处理流程：
      1. 查找包的 skills 源目录（含 PyInstaller _MEIPASS 支持）
      2. 复制所有 skill 到 ~/.hermes/skills/
      3. 复制 .trade-template/ 到 ~/.trade/

    Raises:
        SystemExit(1): 找不到 skills 目录或安装失败时
    """
    hermes_home = _get_hermes_home()
    trade_home = _get_trade_home()
    hermes_skills_dir = hermes_home / "skills"

    # 查找本地包中的 skills 源目录
    package_skills = _get_package_skills_dir()
    if package_skills is None:
        msg = (
            "[post_install] ERROR: Could not find skills directory.\n"
            f"  _MEIPASS: {getattr(sys, '_MEIPASS', 'N/A')}\n"
            f"  sys.path: {sys.path[:5]}...\n"
            "  Expected: <package-root>/skills/*/SKILL.md"
        )
        if progress_callback:
            progress_callback(msg)
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    info = (
        f"[post_install] Hermes home:   {hermes_home}\n"
        f"[post_install] Package skills: {package_skills}\n"
        f"[post_install] Hermes skills: {hermes_skills_dir}"
    )
    if progress_callback:
        progress_callback(info)
    else:
        print(info)

    installed = _copy_skills(package_skills, hermes_skills_dir, progress_callback=progress_callback)

    if installed:
        count_msg = f"[post_install] Installed {len(installed)} skills: {', '.join(installed)}"
        if progress_callback:
            progress_callback(count_msg)
        else:
            print(count_msg)
    else:
        warn_msg = "[post_install] WARNING: No skills found to install."
        if progress_callback:
            progress_callback(warn_msg)
        else:
            print(warn_msg, file=sys.stderr)

    # 同时复制 .trade-template 到 Trade 运行时数据目录
    template_dir = package_skills.parent / ".trade-template"
    if not template_dir.is_dir():
        # PyInstaller _MEIPASS 回退
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            template_dir = Path(meipass) / ".trade-template"
    if not template_dir.is_dir():
        # 开发模式回退：从脚本所在目录查找
        template_dir = Path(__file__).parent.parent.parent / ".trade-template"

    if template_dir.is_dir():
        template_msg = (
            f"[post_install] Trade home: {trade_home}"
        )
        if progress_callback:
            progress_callback(template_msg)
        else:
            print(template_msg)
        trade_home.mkdir(parents=True, exist_ok=True)
        _copy_trade_template(template_dir, trade_home)
        done_msg = f"[post_install] Trade data template installed to: {trade_home}/.trade-template"
        if progress_callback:
            progress_callback(done_msg)
        else:
            print(done_msg)

    if progress_callback:
        progress_callback("[post_install] Done.")
    else:
        print("[post_install] Done.")


def update_skills() -> None:
    """从 GitHub 拉取最新 B2B skill 定义 (SKILL.md) 更新到本地 Hermes 目录。

    与 install_skills 的区别：
      - install_skills: 从本地 pip 安装包中复制 skills（新安装时用）
      - update_skills:  从 GitHub main 分支下载最新 SKILL.md（更新时用）

    用法: trade-skills-update（或 python -m trade.post_install update）

    安全措施：
      - 路径穿越校验（skill 目录名限制 b2b- 前缀 + 小写字母连字符）
      - 下载内容校验（禁止以 ".." 开头的异常内容）
      - 最大 1MB 下载限制（防止内存耗尽）
      - 递增退避重试（网络波动时自动恢复）
    """
    hermes_home = _get_hermes_home()
    hermes_skills_dir = hermes_home / "skills"
    # 停用 skill 即使用户机器上有残留，也在更新开始时清掉
    _purge_blocked_skills(hermes_skills_dir)

    # 本地包中的 skills 目录（用于列出需要更新哪些 skill）
    package_skills = _get_package_skills_dir()
    if package_skills is None:
        print(
            "[update_skills] ERROR: Cannot find local skills directory.",
            file=sys.stderr,
        )
        sys.exit(1)

    # GitHub raw 文件 URL 前缀
    RAW_BASE = (
        "https://raw.githubusercontent.com/chefroger/smart-trade-ai/main/skills"
    )

    updated = 0
    skipped = 0
    failed = 0

    for skill_dir in sorted(package_skills.iterdir()):
        if not skill_dir.is_dir() or not (
            skill_dir.name.startswith("b2b-") or skill_dir.name.startswith("auto-") or skill_dir.name == "chat-memory"
        ):
            continue  # 只处理 b2b-、auto-、chat-memory skill 目录

        skill_name = skill_dir.name

        # 被停用的 skill 不参与同步，并清掉此前已经装过的目录（审计 P1-13）
        from trade.skill_registry import _BLOCKED_SKILLS

        if skill_name in _BLOCKED_SKILLS:
            stale = hermes_skills_dir / skill_name
            if stale.exists():
                shutil.rmtree(stale, ignore_errors=True)
            continue

        # 安全校验：skill 目录名只能是 b2b- 前缀 + 小写字母连字符
        if (
            ".." in skill_name
            or "/" in skill_name
            or "\\" in skill_name
            or not (skill_name.startswith("b2b-") or skill_name.startswith("auto-") or skill_name == "chat-memory")
        ):
            print(f"  ✗ {skill_name} (invalid name, skipped)", file=sys.stderr)
            failed += 1
            continue

        raw_url = f"{RAW_BASE}/{skill_name}/SKILL.md"
        dest_dir = hermes_skills_dir / skill_name
        dest_file = dest_dir / "SKILL.md"

        # 递增退避重试（应对 GitHub 偶发的 SSL 超时 / 丢包）
        _MAX_TRIES = 3
        _tried = 0
        _last_error = None

        while _tried < _MAX_TRIES:
            _tried += 1
            try:
                # 下载 GitHub 上的最新 SKILL.md
                req = urllib.request.Request(
                    raw_url,
                    headers={"User-Agent": "Trade-Skills-Updater/1.0"},
                )
                # 限制下载大小：1MB（实际 SKILL.md 仅需数 KB）
                _MAX_SKILL_BYTES = 1 * 1024 * 1024
                with urllib.request.urlopen(req, timeout=15) as resp:
                    remote_raw = resp.read(_MAX_SKILL_BYTES + 1)
                    if len(remote_raw) > _MAX_SKILL_BYTES:
                        print(
                            f"  ✗ {skill_name} (content too large, possible MITM)",
                            file=sys.stderr,
                        )
                        failed += 1
                        break
                    remote_content = remote_raw.decode("utf-8")

                # 下载后二次校验：禁止路径穿越内容
                if remote_content.startswith(".."):
                    print(
                        f"  ✗ {skill_name} (content validation failed, skipped)",
                        file=sys.stderr,
                    )
                    failed += 1
                    break

                # SHA256 哈希比对，避免重复下载
                remote_hash = hashlib.sha256(remote_content.encode()).hexdigest()
                if dest_file.is_file():
                    local_hash = hashlib.sha256(dest_file.read_bytes()).hexdigest()
                    if local_hash == remote_hash:
                        print(f"  ✓ {skill_name} (already up-to-date)")
                        skipped += 1
                        break

                # 写入更新内容到本地 Hermes skill 目录
                # newline="\n" 是关键：Windows 上 write_text 默认 newline=None 会把
                # "\n" 翻译成 "\r\n"，CRLF 的 SKILL.md 会让 frontmatter 解析失配
                # （triggers/injection_prompt 全丢）。解析器已做归一化兜底，这里
                # 从源头保证写出去的也是 LF。
                dest_dir.mkdir(parents=True, exist_ok=True)
                with open(dest_file, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(remote_content)
                print(f"  ↻ {skill_name} (updated)")
                updated += 1

                # 同步下载 references/qa_pairs.md（如果 GitHub 上存在）
                try:
                    qa_url = f"{RAW_BASE}/{skill_name}/references/qa_pairs.md"
                    qa_req = urllib.request.Request(
                        qa_url,
                        headers={"User-Agent": "Trade-Skills-Updater/1.0"},
                    )
                    with urllib.request.urlopen(qa_req, timeout=10) as qa_resp:
                        qa_raw = qa_resp.read(_MAX_SKILL_BYTES + 1)
                        if len(qa_raw) <= _MAX_SKILL_BYTES:
                            qa_dest = dest_dir / "references" / "qa_pairs.md"
                            qa_dest.parent.mkdir(parents=True, exist_ok=True)
                            qa_dest.write_bytes(qa_raw)
                except urllib.error.HTTPError:
                    pass  # 该 skill 没有 QA 对文件，正常跳过
                except Exception:
                    pass  # 网络或其他问题，不阻塞主流程

                break

            except urllib.error.HTTPError as e:
                print(
                    f"  ✗ {skill_name} (HTTP {e.code}: {raw_url})",
                    file=sys.stderr,
                )
                failed += 1
                break  # HTTP 错误（如 404）不需要重试
            except Exception as e:
                _last_error = e
                if _tried < _MAX_TRIES:
                    import time as _time
                    _time.sleep(1.0 * _tried)  # 递增退避：1s → 2s → 放弃
                    continue
                # 重试耗尽
                print(
                    f"  ✗ {skill_name} (error after {_MAX_TRIES} retries: {_last_error})",
                    file=sys.stderr,
                )
                failed += 1

    _write_skill_manifest(hermes_skills_dir)
    _verify_manifest_or_warn(hermes_skills_dir)
    print(
        f"\n[update_skills] Done. {updated} updated, {skipped} skipped, {failed} failed."
    )
    if updated > 0:
        print("Hermes will pick up the updated skills on the next request.")
