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


def _skill_md_triggers():
    """读取每个 skills/*/SKILL.md 的 frontmatter triggers。"""
    import re
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parent.parent
    out = {}
    for path in sorted((root / "skills").glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", text, re.S)
        if not match:
            continue
        data = yaml.safe_load(match.group(1)) or {}
        triggers = [str(t) for t in (data.get("triggers") or [])]
        if triggers:
            out[path.parent.name] = triggers
    return out


def test_every_skill_md_has_chinese_and_english_triggers():
    """W6 补全：每个 SKILL.md 的触发词必须中英双全。"""
    import re

    cjk = re.compile(r"[\u4e00-\u9fff]")
    latin = re.compile(r"[A-Za-z]")
    missing = {
        name: triggers
        for name, triggers in _skill_md_triggers().items()
        if not any(cjk.search(t) for t in triggers)
        or not any(latin.search(t) for t in triggers)
    }
    assert not missing, f"SKILL.md 触发词缺少中/英文: {list(missing)}"



def test_every_skill_md_trigger_is_routable_in_registry():
    """O-新16 恢复：SKILL.md 声明过的触发词必须在注册表里，Trade 才路由得到。

    与 tests/test_skill_trigger_parity.py 是同一不变量；912d1a0 加过这条，
    74aafa3 清理分歧表时连它一起删了且未说明。这里保留一份，避免
    「声明了但路由不到」只在另一个文件里才被发现。
    """
    from trade.skill_registry import _SKILLS

    registry = {
        skill["name"]: {str(t).strip().lower() for t in skill.get("triggers", [])}
        for skill in _SKILLS
    }
    missing = {}
    for name, triggers in _skill_md_triggers().items():
        if name not in registry:
            continue
        extra = sorted({t.lower() for t in triggers} - registry[name])
        if extra:
            missing[name] = extra
    assert not missing, f"SKILL.md 触发词未进入注册表（路由不到）: {missing}"
