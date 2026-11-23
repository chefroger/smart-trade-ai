"""技能必须通用：提示词/注册表/CLI 不得出现真实背调对象。

2026-11-23 审计：真实人名 Matthew Busel / Mattbusel / Tensorust 被写进
OSINT 提示词与 CLI 帮助，既违反「技能通用」，也把一次真实背调对象公开在仓库。
测试用例可以继续用真名，只扫描会被模型读到的文件。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# 会被注入模型或展示给用户的文件
_SCANNED = [
    ROOT / "trade" / "skill_registry.py",
    ROOT / "trade" / "prompt.py",
    ROOT / "trade" / "prompts.py",
    ROOT / "trade" / "osint" / "cli.py",
    ROOT / "trade" / "osint" / "orchestrator.py",
]
_SCANNED += sorted((ROOT / "skills").glob("*/SKILL.md"))

FORBIDDEN = (
    "Matthew Busel",
    "Mattbusel",
    "matthewbusel",
    "Tensorust",
    "tensorust",
)


@pytest.mark.parametrize("path", _SCANNED, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_real_person_names(path: Path):
    text = path.read_text(encoding="utf-8")
    hits = [name for name in FORBIDDEN if name in text]
    assert not hits, f"{path.relative_to(ROOT)} 仍含真实人名/公司名：{hits}"
