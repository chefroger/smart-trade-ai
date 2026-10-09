"""
Trade AI Assistant — B2B Skills 安装器。

将项目内置的 37 个 skill 从 Python 包目录复制到 Hermes runtime skills 目录：
  {package}/skills/b2b-*/SKILL.md → ~/.hermes/skills/b2b-*/SKILL.md

Hermes Agent 从 ~/.hermes/skills/ 自动发现 skill 定义并注入到 AI 提示词中。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import urllib.error
import urllib.request
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


def _copy_skills(src: Path, dst_base: Path, progress_callback=None) -> list[str]:
    """将 src 下的所有 skill 目录复制到 dst_base 对应的 skill 目录。

    每个 skill 在目标创建 dst_base/{name}/SKILL.md。
    处理 b2b-* 和 auto-* 前缀的目录，忽略其他文件和目录。

    Args:
        progress_callback: 可选回调 f(msg)，每安装一个 skill 调用一次

    Returns:
        已安装的 skill 目录名列表（如 ["b2b-document", "auto-smtp-email", ...]）
    """
    installed = []
    for skill_dir in sorted(src.iterdir()):
        if not skill_dir.is_dir():
            continue
        if not (skill_dir.name.startswith("b2b-") or skill_dir.name.startswith("auto-") or skill_dir.name == "chat-memory"):
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

    print(
        f"\n[update_skills] Done. {updated} updated, {skipped} skipped, {failed} failed."
    )
    if updated > 0:
        print("Hermes will pick up the updated skills on the next request.")
