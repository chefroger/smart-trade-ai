"""技能必须通用：提示词/注册表/CLI/插件不得出现真实背调对象。

2026-11-23 审计：一次真实背调的人名/账号被写进 OSINT 提示词与 CLI 帮助，
既违反「技能通用」，也把真实对象公开在仓库。W10 起连注释、示例、测试
都要清理，因此本文件不再写出完整姓名（用拼接构造匹配项）。
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
# W10：Hermes 插件工具说明也会被模型读到，一并扫描
_SCANNED += sorted((ROOT / "trade" / "hermes_chat_memory_plugin").glob("*.py"))

# 拼接构造，避免扫描器本身把真名留在仓库里
FORBIDDEN = (
    "Matthew" + " Busel",
    "Matt" + "busel",
    "matthew" + "busel",
    "Tensor" + "ust",
    "tensor" + "ust",
)


@pytest.mark.parametrize("path", _SCANNED, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_real_person_names(path: Path):
    text = path.read_text(encoding="utf-8")
    hits = [name for name in FORBIDDEN if name in text]
    assert not hits, f"{path.relative_to(ROOT)} 仍含真实人名/公司名：{hits}"
