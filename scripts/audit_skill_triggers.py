#!/usr/bin/env python3
"""审计 skill 激活词（triggers / aliases）冲突。

用法：
  python scripts/audit_skill_triggers.py           # 人类可读报告
  python scripts/audit_skill_triggers.py --json     # JSON（CI / 看板）
  python scripts/audit_skill_triggers.py --strict   # 有 P0 级问题时以退出码 1 失败

检查项：
  1. 跨 skill 完全相同的 trigger（精确冲突）
  2. 短 trigger 被其他 skill 的更长 trigger 包含（子串风险）
  3. 近平局误路由探针（score 差 ≤3）
  4. 非唯一 alias（显式「用 xxx」解析失败风险）
  5. skill_registry triggers 与 SKILL.md frontmatter 漂移
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trade.skill_registry import _BLOCKED_SKILLS, _SKILLS  # noqa: E402
from trade.skill_router import _parse_frontmatter, match_skills  # noqa: E402

# 已知、有意保留的短触发词（见 docs/skill-trigger-conflicts.md）
# 从「必须立即修」清单中排除，但仍会出现在报告的 risk 段。
KNOWN_SHORT_TRADEOFFS = frozenset(
    {
        "厂",  # china-leads：故意用单字与「工厂视频」打平，靠注册顺序保原技能
        "da",  # trade-compliance 缩写；≤2 ASCII 已禁子串匹配
        "bl",  # 同上
        "dp",
        "lc",
    }
)

# P0：明确误路由，strict 模式失败
P0_MISROUTE_PROBES = [
    ("出一份合同", "b2b-doc-generation"),
    ("帮我写开发信", "b2b-cold-outreach"),
    ("阿拉伯市场注意事项", "b2b-trade-compliance"),
    ("招标", "b2b-tender-info"),
    ("招标合规怎么做", "b2b-trade-compliance"),
]


def _active_skills() -> list[dict]:
    return [s for s in _SKILLS if s["name"] not in _BLOCKED_SKILLS]


def _trigger_index(skills: list[dict]) -> dict[str, list[str]]:
    by: dict[str, list[str]] = defaultdict(list)
    for s in skills:
        seen: set[str] = set()
        for t in s.get("triggers", []):
            key = t.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            by[key].append(s["name"])
    return by


def audit_exact_conflicts(by_trigger: dict[str, list[str]]) -> list[dict]:
    return [
        {"trigger": t, "skills": names}
        for t, names in sorted(by_trigger.items())
        if len(names) > 1
    ]


def audit_substring_risks(by_trigger: dict[str, list[str]], max_len: int = 4) -> list[dict]:
    risks: list[dict] = []
    items = list(by_trigger.items())
    for t, owners in items:
        if len(t) > max_len:
            continue
        subsumed: set[str] = set()
        for other, onames in items:
            if other == t:
                continue
            if t in other and not (set(owners) & set(onames)):
                subsumed.update(onames)
        if subsumed:
            risks.append(
                {
                    "trigger": t,
                    "len": len(t),
                    "owners": owners,
                    "collides_with": sorted(subsumed),
                    "known_tradeoff": t in KNOWN_SHORT_TRADEOFFS,
                }
            )
    risks.sort(key=lambda r: (r["len"], -len(r["collides_with"]), r["trigger"]))
    return risks


def audit_near_ties(by_trigger: dict[str, list[str]]) -> list[dict]:
    probes: set[str] = set()
    for t in by_trigger:
        if len(t) <= 3:
            probes.add(t)
        if len(t) <= 6:
            probes.add(f"帮我{t}")

    pair_counts: Counter[tuple[str, str]] = Counter()
    samples: dict[tuple[str, str], str] = {}
    for q in probes:
        results = match_skills(q)
        if len(results) < 2:
            continue
        if results[0]["score"] - results[1]["score"] > 3:
            continue
        pair = (results[0]["skill_name"], results[1]["skill_name"])
        pair_counts[pair] += 1
        samples.setdefault(pair, q)

    return [
        {
            "winner": a,
            "runner_up": b,
            "near_tie_count": c,
            "sample_query": samples[(a, b)],
        }
        for (a, b), c in pair_counts.most_common(30)
    ]


def audit_alias_conflicts(skills: list[dict]) -> list[dict]:
    alias_map: dict[str, list[str]] = defaultdict(list)
    names = {s["name"].lower() for s in skills}
    for s in skills:
        for a in s.get("aliases", []):
            alias_map[str(a).lower()].append(s["name"])

    conflicts: list[dict] = []
    for alias, owners in sorted(alias_map.items()):
        uniq = sorted(set(owners))
        if len(uniq) > 1:
            conflicts.append(
                {
                    "alias": alias,
                    "skills": uniq,
                    "also_skill_name": alias in names,
                    "note": (
                        "同时是 skill 名时，显式调用走 name 命中；"
                        "作为纯 alias 时因非唯一而解析失败"
                    ),
                }
            )
    return conflicts


def audit_registry_skillmd_drift() -> list[dict]:
    drifts: list[dict] = []
    for s in _SKILLS:
        path = ROOT / "skills" / s["name"] / "SKILL.md"
        if not path.is_file():
            drifts.append({"skill": s["name"], "issue": "missing_skill_md"})
            continue
        fm, _ = _parse_frontmatter(path.read_text(encoding="utf-8"))
        fm_triggers = fm.get("triggers")
        if fm_triggers is None:
            drifts.append({"skill": s["name"], "issue": "missing_frontmatter_triggers"})
            continue
        if isinstance(fm_triggers, str):
            fm_list = [
                x.strip().lower()
                for x in fm_triggers.replace("\n", ",").split(",")
                if x.strip()
            ]
        else:
            fm_list = [str(x).strip().lower() for x in fm_triggers]
        reg = {t.strip().lower() for t in s.get("triggers", [])}
        only_reg = sorted(reg - set(fm_list))
        only_fm = sorted(set(fm_list) - reg)
        if only_reg or only_fm:
            drifts.append(
                {
                    "skill": s["name"],
                    "issue": "trigger_diff",
                    "only_registry": only_reg[:15],
                    "only_skill_md": only_fm[:15],
                    "only_registry_count": len(only_reg),
                    "only_skill_md_count": len(only_fm),
                }
            )
    return drifts


def audit_p0_probes() -> list[dict]:
    failures: list[dict] = []
    for query, expected in P0_MISROUTE_PROBES:
        results = match_skills(query)
        actual = results[0]["skill_name"] if results else None
        if actual != expected:
            failures.append(
                {
                    "query": query,
                    "expected": expected,
                    "actual": actual,
                    "top": [
                        {
                            "skill": r["skill_name"],
                            "score": r["score"],
                            "hits": r["triggers_matched"][:3],
                        }
                        for r in results[:3]
                    ],
                }
            )
    return failures


def run_audit() -> dict:
    skills = _active_skills()
    by_trigger = _trigger_index(skills)
    exact = audit_exact_conflicts(by_trigger)
    risks = audit_substring_risks(by_trigger)
    unresolved_short = [r for r in risks if not r["known_tradeoff"] and r["len"] <= 2]
    return {
        "summary": {
            "active_skills": len(skills),
            "unique_triggers": len(by_trigger),
            "exact_cross_conflicts": len(exact),
            "substring_risk_triggers": len(risks),
            "unresolved_len_le_2": len(unresolved_short),
            "near_tie_pair_types": len(audit_near_ties(by_trigger)),
            "alias_multi_conflicts": len(audit_alias_conflicts(skills)),
            "registry_skillmd_drift": len(audit_registry_skillmd_drift()),
            "p0_probe_failures": len(audit_p0_probes()),
        },
        "exact_conflicts": exact,
        "substring_risks": risks,
        "near_ties": audit_near_ties(by_trigger),
        "alias_conflicts": audit_alias_conflicts(skills),
        "registry_skillmd_drift": audit_registry_skillmd_drift(),
        "p0_probe_failures": audit_p0_probes(),
    }


def _print_report(report: dict) -> None:
    s = report["summary"]
    print("=== Skill Trigger Conflict Audit ===")
    print(f"active skills          : {s['active_skills']}")
    print(f"unique triggers        : {s['unique_triggers']}")
    print(f"exact cross conflicts  : {s['exact_cross_conflicts']}")
    print(f"substring risk triggers: {s['substring_risk_triggers']}")
    print(f"unresolved len<=2      : {s['unresolved_len_le_2']}")
    print(f"near-tie pair types    : {s['near_tie_pair_types']}")
    print(f"alias multi conflicts  : {s['alias_multi_conflicts']}")
    print(f"registry↔SKILL.md drift: {s['registry_skillmd_drift']}")
    print(f"P0 probe failures      : {s['p0_probe_failures']}")

    if report["exact_conflicts"]:
        print("\n-- Exact conflicts --")
        for row in report["exact_conflicts"]:
            print(f"  {row['trigger']!r} -> {row['skills']}")

    print("\n-- Top substring risks (len<=4) --")
    for row in report["substring_risks"][:20]:
        tag = " [known]" if row["known_tradeoff"] else ""
        print(
            f"  {row['trigger']!r}@{row['owners']} ⊂ "
            f"{len(row['collides_with'])} skills{tag}"
        )

    print("\n-- Top near-tie pairs --")
    for row in report["near_ties"][:15]:
        print(
            f"  {row['near_tie_count']:3d}  {row['winner']} vs {row['runner_up']}"
            f"  e.g. {row['sample_query']!r}"
        )

    if report["p0_probe_failures"]:
        print("\n-- P0 probe failures --")
        for row in report["p0_probe_failures"]:
            print(
                f"  {row['query']!r}: expected {row['expected']}, "
                f"got {row['actual']} | {row['top']}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="精确冲突或 P0 探针失败时退出码 1",
    )
    args = parser.parse_args()
    report = run_audit()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)

    if args.strict:
        if report["exact_conflicts"] or report["p0_probe_failures"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
