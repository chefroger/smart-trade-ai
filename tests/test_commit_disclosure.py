"""审计 O-21：提交说明必须带「包外改动」披露行。

只测纯解析逻辑，不依赖真实 git 仓库。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_commit_disclosure import (  # noqa: E402
    missing_disclosure,
    parse_log,
)


def test_parse_log_splits_commits():
    raw = (
        "abc123\x1ffix: a\x1fbody line\x1e"
        "def456\x1fchore(release): v1.0\x1f"
    )
    commits = parse_log(raw)
    assert commits == [
        ("abc123", "fix: a", "body line"),
        ("def456", "chore(release): v1.0", ""),
    ]


def test_english_and_chinese_disclosure_accepted():
    commits = [
        ("a" * 40, "fix: x", "why\n\nTouched outside task scope: none"),
        ("b" * 40, "fix: y", "why\n\n包外改动：tests/test_x.py — 补测试"),
    ]
    assert missing_disclosure(commits) == []


def test_release_commits_are_exempt():
    assert missing_disclosure([("c" * 40, "chore(release): v0.9.26", "")]) == []


def test_missing_line_is_reported():
    commits = [
        ("d" * 40, "fix: no disclosure", "只有正文"),
        ("e" * 40, "fix: has disclosure", "Touched outside task scope: none"),
    ]
    assert missing_disclosure(commits) == [("ddddddd", "fix: no disclosure")]
