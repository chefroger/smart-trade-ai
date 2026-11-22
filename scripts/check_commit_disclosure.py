#!/usr/bin/env python3
"""检查提交说明是否带「包外改动」披露行（审计 O-21）。

约定：每个非发版提交的正文都要有一行
    Touched outside task scope: <文件> — <改了什么>   （没动写 none）
或中文写法
    包外改动：none
纯发版提交（主题以 ``chore(release)`` 开头，只动 CHANGELOG + pyproject）豁免。

用法：
    python scripts/check_commit_disclosure.py                 # origin/main..HEAD
    python scripts/check_commit_disclosure.py v0.9.25..HEAD
    python scripts/check_commit_disclosure.py --warn-only     # 只打印，退出码恒 0

退出码：全部合规 0；有缺失 1（--warn-only 时恒 0）。
"""

from __future__ import annotations

import re
import subprocess
import sys

# git log 的字段分隔符：\x1e 分隔提交，\x1f 分隔字段（正文里不会出现）
_COMMIT_SEP = "\x1e"
_FIELD_SEP = "\x1f"

_DISCLOSURE_RE = re.compile(
    r"(?im)^[ \t]*(?:touched outside task scope[ \t]*:|包外改动[ \t]*[:：])"
)

# 纯发版提交只改 CHANGELOG + pyproject，按审计口径算 N/A
_RELEASE_SUBJECT_RE = re.compile(r"^chore\(release\)")


def parse_log(text: str) -> list[tuple[str, str, str]]:
    """把 ``git log`` 输出解析成 (sha, subject, body)。"""
    commits: list[tuple[str, str, str]] = []
    for chunk in text.split(_COMMIT_SEP):
        # 只去掉 git 补的行分隔符；不能用 strip() —— Python 的 isspace 把
        # \x1f（字段分隔符）也当空白，会把空正文的分隔符吃掉。
        chunk = chunk.strip("\r\n")
        if not chunk:
            continue
        parts = chunk.split(_FIELD_SEP)
        if len(parts) < 3:
            continue
        sha, subject, body = parts[0].strip(), parts[1].strip(), parts[2]
        commits.append((sha, subject, body))
    return commits


def missing_disclosure(commits: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    """返回缺少披露行的 (短 SHA, 主题) 列表（发版提交跳过）。"""
    missing: list[tuple[str, str]] = []
    for sha, subject, body in commits:
        if _RELEASE_SUBJECT_RE.match(subject):
            continue
        if _DISCLOSURE_RE.search(body or ""):
            continue
        missing.append((sha[:7], subject))
    return missing


def read_log(rev_range: str) -> str:
    """读取提交日志（正文用 \x1f 与主题隔开）。"""
    result = subprocess.run(
        ["git", "log", "--no-merges", f"--pretty=format:%H{_FIELD_SEP}%s{_FIELD_SEP}%b{_COMMIT_SEP}", rev_range],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout


def main(argv: list[str]) -> int:
    warn_only = "--warn-only" in argv
    args = [a for a in argv if not a.startswith("--")]
    rev_range = args[0] if args else "origin/main..HEAD"
    try:
        missing = missing_disclosure(parse_log(read_log(rev_range)))
    except subprocess.CalledProcessError as exc:
        print(f"读取提交历史失败：{exc}", file=sys.stderr)
        return 0 if warn_only else 1
    if not missing:
        print(f"✓ {rev_range}：全部提交都带披露行")
        return 0
    print(f"✗ {rev_range}：{len(missing)} 笔提交缺少披露行（Touched outside task scope:）")
    for sha, subject in missing:
        print(f"  - {sha} {subject}")
    return 0 if warn_only else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
