"""Skill 激活词冲突守卫。

配套：scripts/audit_skill_triggers.py、docs/skill-trigger-conflicts.md
"""

from __future__ import annotations

import pytest


def test_no_exact_cross_skill_trigger_conflicts():
    """不同 skill 不得共享完全相同的 trigger（大小写不敏感）。"""
    from collections import defaultdict

    from trade.skill_registry import _BLOCKED_SKILLS, _SKILLS

    by_trigger: dict[str, list[str]] = defaultdict(list)
    for skill in _SKILLS:
        if skill["name"] in _BLOCKED_SKILLS:
            continue
        seen: set[str] = set()
        for trigger in skill.get("triggers", []):
            key = trigger.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            by_trigger[key].append(skill["name"])

    conflicts = {t: names for t, names in by_trigger.items() if len(names) > 1}
    assert not conflicts, f"跨 skill 精确触发词冲突: {conflicts}"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("出一份合同", "b2b-doc-generation"),
        ("帮我写开发信", "b2b-cold-outreach"),
        ("写开发信", "b2b-cold-outreach"),
        ("阿拉伯市场注意事项", "b2b-trade-compliance"),
        ("招标", "b2b-tender-info"),
        ("招标合规怎么做", "b2b-trade-compliance"),
        ("找招标", "b2b-tender-info"),
        ("写一封开发信给德国客户", "b2b-cold-outreach"),
    ],
)
def test_p0_misroute_probes(query, expected):
    from trade.skill_router import match_skill

    result = match_skill(query)
    assert result is not None, f"{query!r} 无命中"
    assert result["name"] == expected, f"{query!r} → {result['name']}，期望 {expected}"


def test_bare_help_me_check_does_not_trigger_chat_memory():
    """裸「帮我查一下」不应再被 chat-memory 的「帮我查」吞掉。"""
    from trade.skill_router import match_skill

    result = match_skill("帮我查一下")
    assert result is None or result["name"] != "chat-memory"


def test_audit_script_strict_passes():
    """审计脚本 --strict 应在当前注册表上通过。"""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "audit_skill_triggers.py"
    spec = importlib.util.spec_from_file_location("audit_skill_triggers", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    report = mod.run_audit()
    assert not report["exact_conflicts"]
    assert not report["p0_probe_failures"], report["p0_probe_failures"]
