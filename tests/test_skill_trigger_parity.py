"""SKILL.md frontmatter 的 triggers 与 trade/skill_registry.py 的一致性（2026-11-11 审计）。

背景
----
Trade 的技能路由**只读注册表**（`trade/skill_router.py` 的 `_PRECOMPILED` 从
`skill_registry._SKILLS` 构建），Hermes 的技能索引**只读 name + description**
（`agent/skill_utils.extract_skill_description`，60 字符上限）。

⇒ **SKILL.md frontmatter 里的 `triggers` 谁都不读**。它是一个「声明」，
不是路由表。声明与路由表一旦分家，SKILL.md 承诺会触发的问法在 Trade 里
就静默路由不到 —— 2026-11-11 审计实测 14 个问法 `match_skill()` 返回 None：

    帮我写产品 / 描述产品 / 产品话术 / 做决策 / 方案选择 / 抖音视频 /
    催一下 / 合规检查 / 电商上架 / 论坛评论 / 评论引流 / 主题集群 / 帮我找 / 本月

本文件钉住两件事：
1. SKILL.md 声明的触发词必须能在注册表里找到（除非在 `_ALLOWED_DIVERGENCE`
   里显式登记了原因）；
2. 登记在案的分歧不许悄悄变大 —— 新增未登记的分歧即失败。

为什么不用「注册表 ⊇ SKILL.md」做单向断言
------------------------------------------
反向（注册表有的 SKILL.md 没有）有 500+ 条，那不是漂移而是正常的：
注册表是路由表，可以比声明���（Hermes 也不读它）。本文件只查
「声明了但路由不到」这一个方向 —— 它才是用户能感知到的故障。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"


def _frontmatter(name: str) -> dict:
    """读取指定 skill 的 frontmatter。"""
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    assert match, f"{name} 缺 frontmatter"
    return yaml.safe_load(match.group(1)) or {}


def _declared_triggers() -> dict[str, set[str]]:
    """SKILL.md frontmatter 里声明的触发词（归一化到小写）。"""
    result: dict[str, set[str]] = {}
    for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
        fm = _frontmatter(skill_md.parent.name)
        result[skill_md.parent.name] = {
            str(t).strip().lower() for t in (fm.get("triggers") or [])
        }
    return result


def _registry_triggers() -> dict[str, set[str]]:
    """注册表里的触发词（归一化到小写）。"""
    from trade.skill_registry import _SKILLS

    return {
        s["name"]: {str(t).strip().lower() for t in (s.get("triggers") or [])}
        for s in _SKILLS
    }


# 已登记的声明-路由分歧：skill → (触发词, 原因)
# 原因只写「为什么不并入注册表」，不写「以后再说」。
_ALLOWED_DIVERGENCE: dict[str, dict[str, str]] = {
    # ── 归属冲突：另一个 skill 已经拥有这个词，两个都加会靠打分器抢 ──
    "b2b-buyer-persona": {"客户画像": "归 b2b-customer-intel（画像主战场在那里）"},
    "b2b-customer-finder": {
        "帮我找客户": "归 b2b-lead-generation（找客户全链路）",
        "怎么找客户": "归 b2b-lead-generation",
    },
    "b2b-customer-intel": {
        "customer profile": "归 b2b-customer-mgmt",
        "客户档案": "归 b2b-customer-mgmt（档案管理 vs 深度画像）",
    },
    "b2b-customs-data": {
        "市场调研": "归 b2b-market-analysis",
        "竞争对手分析": "归 b2b-market-analysis",
    },
    "b2b-doc-generation": {"商业提案": "归 b2b-guarantee-proposal"},
    "b2b-email-intel": {"背景调查": "归 b2b-osint（完整背调）"},
    "b2b-exhibition": {"trade fair": "归 b2b-trade-ops"},
    "b2b-inquiry-training": {"sales training": "归 b2b-sales-playbook"},
    "b2b-lead-generation": {
        "客户分析": "归 b2b-customer-intel",
        "客户跟进": "归 b2b-sales-pipeline",
        "开发信": "归 b2b-cold-outreach",
    },
    # 注：询盘/报价/谈判 裸词已从 SKILL.md 声明与注册表同步删掉（2026-11-11），
    # 改用「询盘处理/报价策略/谈判技巧」等复合词，避免抢 inquiry/doc-gen 等技能。
    "b2b-onboarding": {
        "产品介绍": "归 b2b-product-description",
        "竞争对手分析": "归 b2b-market-analysis",
    },
    "b2b-product-description": {
        "产品推广": "归 b2b-cold-outreach",
        "产品目录": "归 b2b-data-directory",
    },
    "b2b-sales-playbook": {
        "objection handling": "归 b2b-inquiry-training",
        # 有意收窄：裸短词会把无关问法劫持进来
        "not responding": (
            "裸词会把 'the shipment is not responding' 也劫持进来；"
            "注册表用带宾语的 'customer is not responding' 覆盖同一意图"
        ),
    },
    "b2b-six-thinking-hats": {"风险评估": "归 b2b-osint"},
    "b2b-trade-ops": {
        "参展": "归 b2b-exhibition",
        "展会邀约": "归 b2b-exhibition",
        "广交会": "归 b2b-exhibition",
        "展会邀请": "归 b2b-exhibition（那里已有「展会邀约」）",
    },
    "chat-memory": {
        "帮我找": (
            "裸词会把 '帮我找招标 / 帮我找供应商' 全部劫持到历史查询；"
            "注册表用 '帮我找之前 / 帮我找上次 / 帮我找历史' 的长词形式"
        ),
    },
}


class TestTriggerParity:
    """SKILL.md 声明的触发词必须在注册表里能路由到，否则就是静默故障。"""

    def test_no_unregistered_divergence(self):
        """未登记的声明-路由分歧即失败 —— 新增触发词必须同步注册表。"""
        declared = _declared_triggers()
        registry = _registry_triggers()
        offenders: list[tuple[str, str]] = []
        for skill, words in declared.items():
            missing = words - registry.get(skill, set())
            for word in sorted(missing):
                if word in _ALLOWED_DIVERGENCE.get(skill, {}):
                    continue
                offenders.append((skill, word))
        assert not offenders, (
            "SKILL.md 声明了但注册表没有 → Trade 路由不到该 skill："
            f"{offenders}。要么补进 trade/skill_registry.py，"
            "要么在 tests/test_skill_trigger_parity.py 的 _ALLOWED_DIVERGENCE 里登记原因。"
        )

    def test_allowed_divergence_still_needed(self):
        """登记在案的分歧不许悄悄消失 —— 归属调整后要同步清理这张表。"""
        declared = _declared_triggers()
        registry = _registry_triggers()
        stale: list[tuple[str, str]] = []
        for skill, entries in _ALLOWED_DIVERGENCE.items():
            for word in entries:
                # 已经并进注册表 → 这条登记过期了
                if word in registry.get(skill, set()):
                    stale.append((skill, word))
                # SKILL.md 已经不声明了 → 登记也过期
                elif word not in declared.get(skill, set()):
                    stale.append((skill, word))
        assert not stale, (
            f"_ALLOWED_DIVERGENCE 里的登记已过期（词已并入或 SKILL.md 已不再声明）：{stale}"
        )

    def test_allowed_divergence_has_reason(self):
        """每条登记都要写清楚原因 —— 否则「以后再说」会变成永久债务。"""
        for skill, entries in _ALLOWED_DIVERGENCE.items():
            for word, reason in entries.items():
                assert reason.strip(), f"{skill}.{word} 缺原因"
                assert len(reason.strip()) >= 10, f"{skill}.{word} 的原因太含糊：{reason!r}"
