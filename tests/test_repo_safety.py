"""仓库安全闸门 scripts/repo_safety.sh 单测（M6）。"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "repo_safety.sh"


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
    return subprocess.run(
        ["bash", str(SCRIPT), str(repo)],
        capture_output=True,
        text=True,
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
