"""仓库安全闸门 scripts/repo_safety.sh 单测（M6）。"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "repo_safety.sh"


def _find_bash() -> str:
    """跨平台定位可用 bash；Windows 避开 System32\\bash.exe（WSL 占位桩），优先取 Git Bash。"""
    if os.name != "nt":
        return shutil.which("bash") or "bash"

    candidates: list[Path] = []
    git_bin = shutil.which("git")
    if git_bin:
        git_root = Path(git_bin).resolve().parent.parent
        candidates.extend([
            git_root / "bin" / "bash.exe",
            git_root / "usr" / "bin" / "bash.exe",
        ])
    candidates.extend([
        Path(r"C:\Program Files\Git\bin\bash.exe"),
        Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
    ])
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    pytest.skip("Git Bash unavailable on Windows")


def _init_temp_repo(tmp_path: Path) -> Path:
    """初始化隔离临时 git 仓库并配置默认白名单。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    allow = repo / ".github" / "repo-safety-allow.txt"
    allow.parent.mkdir(parents=True, exist_ok=True)
    allow.write_text(
        "static/trade-customer-template.csv\n"
        "tests/fixtures/osint/sanctions/*.csv\n",
        encoding="utf-8",
    )
    return repo


def _run_gate(repo: Path) -> subprocess.CompletedProcess:
    """对指定仓库运行安全闸门脚本。"""
    bash = _find_bash()
    script_arg = SCRIPT.as_posix() if os.name == "nt" else str(SCRIPT)
    repo_arg = repo.as_posix() if os.name == "nt" else str(repo)
    return subprocess.run(
        [bash, script_arg, repo_arg],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_current_repository_passes_safety_gate():
    """当前仓库运行安全闸门应通过。"""
    res = _run_gate(REPO_ROOT)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "[repo-safety] OK" in res.stdout


def test_clean_temp_repo_with_allowlisted_files_passes(tmp_path):
    """白名单内 csv 与 .env.example 合规放行。"""
    repo = _init_temp_repo(tmp_path)
    (repo / ".env.example").write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")
    tpl = repo / "static" / "trade-customer-template.csv"
    tpl.parent.mkdir(parents=True, exist_ok=True)
    tpl.write_text("name\nFictional\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)

    res = _run_gate(repo)
    assert res.returncode == 0, res.stdout + res.stderr


def test_blocks_db_and_unlisted_csv(tmp_path):
    """提交 .db 或白名单外 .csv 时闸门失败并指出文件名。"""
    repo = _init_temp_repo(tmp_path)
    (repo / "x.db").write_bytes(b"sqlite-placeholder")
    (repo / "leak.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)

    res = _run_gate(repo)
    assert res.returncode != 0
    assert "x.db" in res.stdout
    assert "leak.csv" in res.stdout


def test_blocks_secret_content_without_printing_secret(tmp_path):
    """含疑似密钥长串的文件被拦截，且输出日志仅含文件名、绝不泄露密钥原文。"""
    repo = _init_temp_repo(tmp_path)
    # 虚构测试占位串（运行时拼接，避免源码文件自身触发扫描）
    fake_secret = "sk" + "-" + "AbCdEf1234567890XyZaBcDeF"
    (repo / "bad_config.txt").write_text(f"API_KEY={fake_secret}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)

    res = _run_gate(repo)
    assert res.returncode != 0
    assert "bad_config.txt" in res.stdout
    assert fake_secret not in res.stdout
    assert fake_secret not in res.stderr
