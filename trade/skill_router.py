"""
Trade AI Assistant — Skill Router（匹配引擎 + 注入逻辑）。

从 skill_registry 读取 skill 注册表数据，提供：
  - match_skill(query)  — 关键词匹配，返回匹配的 skill dict 或 None
  - augment_query(query) — 将 skill injection prompt 注入用户 query

架构：
  skill_registry.py (L4 数据层) → skill_router.py (L2 逻辑层) → helpers.py (L2 调用方)
"""

from __future__ import annotations

import os
import re
import threading

# ─────────────────────────────────────────────────────────────────────────────
# mtime 缓存：OrderedDict LRU（上限 128，远大于 37 个 skill）
# ─────────────────────────────────────────────────────────────────────────────
from collections import OrderedDict
from pathlib import Path

from trade.skill_registry import (
    _EXPLICIT_RE,
    _SKILLS,
    get_skill_by_name,
    skill_names,
)

_injection_cache_lock = threading.Lock()
try:
    _INJECTION_CACHE_MAX = int(os.environ.get("TRADE_SKILL_CACHE_MAX", "128"))
except (ValueError, TypeError):
    _INJECTION_CACHE_MAX = 128
_INJECTION_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()

# ─────────────────────────────────────────────────────────────────────────────
# SKILL.md → injection_prompt 加载器
# ─────────────────────────────────────────────────────────────────────────────

def _get_hermes_skills_dir() -> Path:
    """解析 Hermes skills 目录路径（优先 HERMES_HOME 环境变量）。"""
    val = os.environ.get("HERMES_HOME", "").strip()
    if val:
        return Path(val) / "skills"
    # Windows: %LOCALAPPDATA%\hermes\skills, macOS/Linux: ~/.hermes/skills
    if os.name == "nt":
        _appdata = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(_appdata) / "hermes" / "skills"
    return Path.home() / ".hermes" / "skills"


def _get_skill_dir(skill_name: str) -> Path | None:
    """返回已安装 skill 的目录路径，或 None。

    查找顺序：~/.hermes/skills/ → package skills/
    """
    # 优先查找已安装的 skill
    skill_path = _get_hermes_skills_dir() / skill_name
    if (skill_path / "SKILL.md").is_file():
        return skill_path

    # Fallback：查找 package 内置的 skill
    try:
        import trade
        pkg_root = Path(trade.__file__).parent.parent
        pkg_skill = pkg_root / "skills" / skill_name
        if (pkg_skill / "SKILL.md").is_file():
            return pkg_skill
    except Exception:
        # 导入或路径解析异常时静默降级，不影响主流程
        pass
    return None


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 markdown YAML frontmatter。

    使用 PyYAML safe_load 解析，正确处理 | block scalar 格式。

    返回结果：
        (frontmatter_dict, body_content)。无有效 frontmatter 时返回 ({}, content)。
    """
    # 没有 YAML frontmatter 标记，返回原始内容
    if not content.startswith("---\n"):
        return {}, content

    import yaml

    try:
        # 定位第二个 --- 作为 frontmatter 结束标记
        second_dash = content.find("\n---\n", 4)
        # 没有找到结束标记，说明 frontmatter 不完整，返回原始内容
        if second_dash == -1:
            return {}, content

        fm_text = content[4:second_dash]
        body = content[second_dash + 5:]

        parsed = yaml.safe_load(fm_text)
        # safe_load 返回 None 或非字典时视为无效 frontmatter
        if parsed is None or not isinstance(parsed, dict):
            return {}, body

        return parsed, body
    except yaml.YAMLError:
        # YAML 解析异常时返回原始内容，避免因 frontmatter 格式问题阻塞整体流程
        return {}, content


def load_injection_prompt(skill_name: str) -> str | None:
    """从 SKILL.md frontmatter 加载 injection_prompt（mtime 缓存）。

    优先级：
      1. ~/.hermes/skills/{skill}/SKILL.md（用户安装版）
      2. {package}/skills/{skill}/SKILL.md（包内置版）
      3. None → 降级到 skill_registry 中的 augment_prompt 字段

    mtime 缓存：文件未变更时直接返回缓存内容，避免重复磁盘 IO。
    """
    # 如果未找到 skill 目录，则无法加载 injection_prompt
    skill_dir = _get_skill_dir(skill_name)
    if skill_dir is None:
        return None

    # 目录下没有 SKILL.md 文件，无法提取 injection_prompt
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None

    try:
        mtime = skill_md.stat().st_mtime
    except OSError:
        # 文件状态获取失败时静默返回 None，不阻塞后续匹配流程
        return None

    # mtime 缓存命中
    cache_key = skill_name
    with _injection_cache_lock:
        cached = _INJECTION_CACHE.get(cache_key)
        if cached is not None and cached[0] == mtime:
            return cached[1]

    # 读取文件并解析 frontmatter
    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError:
        # 文件读取失败时静默返回 None，不因单个 skill 读取异常影响整体
        return None

    fm, _ = _parse_frontmatter(content)
    injection = fm.get("injection_prompt", "")

    if injection:
        with _injection_cache_lock:
            # LRU: 移动到末尾 + 超限时弹出最老项
            _INJECTION_CACHE.pop(cache_key, None)
            _INJECTION_CACHE[cache_key] = (mtime, injection)
            while len(_INJECTION_CACHE) > _INJECTION_CACHE_MAX:
                _INJECTION_CACHE.popitem(last=False)

    return injection or None


# ─────────────────────────────────────────────────────────────────────────────
# 文本标准化
# ─────────────────────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    """去除首尾空白、小写化、压缩连续空白为单空格。"""
    return re.sub(r'\s+', ' ', text.strip().lower())


# ─────────────────────────────────────────────────────────────────────────────
# 核心匹配：评分计算
# ─────────────────────────────────────────────────────────────────────────────

_EXPLICIT_SCORE = 9999  # 显式调用（如 "用 b2b-osint"）获得绝对最高分

# 匹配权重
_BOUNDARY_WEIGHT = 3   # 词边界匹配（如独立词"背景调查"）
_SUBSTRING_WEIGHT = 1  # 宽松子串匹配（如"做一下背景调查再联系"）

# ── 预编译触发词正则（模块加载时一次性构建，避免每次 query 重复 re.compile）──
# 结构：[(skill_idx, skill_name, [(trigger_text, boundary_re, substring_re_or_None), ...]), ...]
_PRECOMPILED: list[tuple[int, str, list[tuple[str, re.Pattern, re.Pattern | None]]]] = []
for _idx, _skill in enumerate(_SKILLS):
    _triggers = _skill.get("triggers", [])
    if _triggers:
        _patterns: list[tuple[str, re.Pattern, re.Pattern | None]] = []
        for _kw in _triggers:
            _esc = re.escape(_kw)
            # ≤2 字符的纯 ASCII 触发词（缩写类：DA/BL/LC/DP 等）禁止子串匹配——
            # "DA" 会命中 today/data/update、"BL" 会命中 able/table，全是噪音。
            # 中文触发词（isascii=False）不受影响，保持子串匹配；
            # 3 字符的英文缩写（FOB/CIF/ETA）保留子串，以支持 "FOB上海" 混排场景。
            _disable_substring = len(_kw) <= 2 and _kw.isascii()
            _patterns.append((
                _kw,
                re.compile(r'\b' + _esc + r'\b', re.IGNORECASE),
                None if _disable_substring else re.compile(_esc, re.IGNORECASE),
            ))
        _PRECOMPILED.append((_idx, _skill["name"], _patterns))


def _score_skills(query: str) -> list[dict]:
    """对每个注册 skill 逐触发词计算匹配得分，返回排序后的评分列表。

    匹配策略：
      1. 显式调用（"用 b2b-xxx"）→ 该 skill 得 _EXPLICIT_SCORE，直接返回
      2. 关键词匹配 → 逐触发词检查：
         - 词边界匹配 (\b{trigger}\b) → 3 分
         - 宽松子串匹配 ({trigger})    → 1 分

    返回格式：
        [{"skill_name": str, "score": int, "triggers_matched": [str],
          "word_boundary_hits": int, "substring_hits": int}, ...]
    按 (-score, 注册顺序) 排序。无匹配时返回 []。
    """
    # 空查询直接返回空列表
    if not query or not query.strip():
        return []

    # ── 策略 1：显式 skill 调用（得分 9999，确保绝对优先）──
    explicit_match = _EXPLICIT_RE.search(query)
    if explicit_match:
        matched_text = explicit_match.group(0)
        normalized_match = matched_text.lower().replace(" ", "-").replace("_", "-")
        candidates = re.findall(r'b2b-[\w-]+', normalized_match)
        if candidates:
            skill_name_candidate = next(
                (name for c in candidates
                 for name in skill_names()
                 if name == c),
                None,
            )
            if skill_name_candidate:
                from trade.skill_registry import _BLOCKED_SKILLS
                if skill_name_candidate in _BLOCKED_SKILLS:
                    return []  # 显式调用被封禁的 skill，返回空（不触发）
                return [{
                    "skill_name": skill_name_candidate,
                    "score": _EXPLICIT_SCORE,
                    "triggers_matched": [],
                    "word_boundary_hits": 0,
                    "substring_hits": 0,
                }]

    # ── 策略 2：逐触发词评分（使用预编译正则 _PRECOMPILED，无 re.compile 开销）──
    normed = _norm(query)
    results = []

    from trade.skill_registry import _BLOCKED_SKILLS

    for idx, skill_name, patterns in _PRECOMPILED:
        if skill_name in _BLOCKED_SKILLS:
            continue  # 跳过被禁用的 skill（见 _BLOCKED_SKILLS 说明）
        total_score = 0
        triggers_matched: list[str] = []
        boundary_hits = 0
        substring_hits = 0

        for kw, boundary_re, substring_re in patterns:
            # 优先尝试词边界匹配（精确度更高）
            if boundary_re.search(normed):
                total_score += _BOUNDARY_WEIGHT
                boundary_hits += 1
                triggers_matched.append(kw)
                continue  # 词边界命中后不再尝试子串（避免重复计数）
            # 宽松子串匹配（substring_re 为 None 表示该触发词被禁止子串匹配，
            # 见预编译处对 ≤2 字符 ASCII 缩写触发词的处理）
            if substring_re is not None and substring_re.search(normed):
                total_score += _SUBSTRING_WEIGHT
                substring_hits += 1
                triggers_matched.append(kw)

        if total_score > 0:
            results.append({
                "skill_name": skill_name,
                "score": total_score,
                "triggers_matched": triggers_matched,
                "word_boundary_hits": boundary_hits,
                "substring_hits": substring_hits,
                "_order": idx,  # 注册顺序（用于等同分时打破平局）
            })

    # 按 (-score, 注册顺序) 降序排列，确保确定性
    results.sort(key=lambda r: (-r["score"], r["_order"]))
    # 移除内部排序键
    for r in results:
        del r["_order"]

    return results


def match_skills(query: str) -> list[dict]:
    """返回所有匹配的 skill 及其评分，按置信度降序排列。

    返回格式：
        [{"skill_name": str, "score": int, "triggers_matched": [str],
          "word_boundary_hits": int, "substring_hits": int}, ...]
    无匹配时返回空列表 []。
    """
    return _score_skills(query)


def match_skill(query: str) -> dict | None:
    """返回最高得分的 skill 注册表条目，或 None。

    维持向后兼容性。内部使用 _score_skills() 评分后取第一名。
    需要全部匹配结果时使用 match_skills()。

    匹配策略（按优先级）：
      1. 显式调用："用 b2b-email-intel" → 绝对优先（score=9999）
      2. 关键词匹配：逐触发词评分，词边界 3 分 + 子串 1 分 → 取最高分

    参数：
        query: 用户原始输入（自动标准化）

    返回：
        完整的 skill dict（含 name, triggers, augment_prompt 等），
        或 None 表示无匹配。
    """
    results = _score_skills(query)
    if not results:
        return None
    return get_skill_by_name(results[0]["skill_name"])


# ─────────────────────────────────────────────────────────────────────────────
# QA 对检索（从 references/qa_pairs.md 加载结构化知识）
# ─────────────────────────────────────────────────────────────────────────────

_QA_CACHE: dict[str, list[dict]] = {}  # skill_name → [{"q":..., "a":..., "keywords":[...], "tags":[...]}]
_QA_CACHE_LOCK = threading.Lock()


def _parse_qa_pairs(content: str) -> list[dict]:
    """解析 qa_pairs.md 文件，返回 QA 对列表。"""
    pairs = []
    current_q = ""
    current_a = ""
    current_keywords: list[str] = []
    current_tags: list[str] = []

    in_answer = False
    for line in content.split('\n'):
        stripped = line.strip()

        if stripped.startswith('## Q') and ':' in stripped[:10]:
            # 保存上一对
            if current_q and current_a:
                pairs.append({
                    "q": current_q.strip(),
                    "a": current_a.strip(),
                    "keywords": list(current_keywords),
                    "tags": list(current_tags),
                })
            # 新问题
            current_q = stripped.split(':', 1)[1].strip() if ':' in stripped else stripped
            current_a = ""
            current_keywords = []
            current_tags = []
            in_answer = True

        elif stripped.startswith('**答案**:'):
            current_a = stripped.replace('**答案**:', '').strip()
            in_answer = True

        elif in_answer and stripped and not stripped.startswith('**') and not stripped.startswith('##'):
            # 继续追加答案内容
            if current_a:
                current_a += ' ' + stripped
            else:
                current_a = stripped

        elif stripped.startswith('**标签**:'):
            current_tags = [t.strip() for t in stripped.replace('**标签**:', '').split(',')]

        elif stripped.startswith('**关键词**:'):
            current_keywords = [k.strip() for k in stripped.replace('**关键词**:', '').split(',')]

        elif stripped.startswith('## Q'):
            pass  # 下一个问题，循环会处理

    # 保存最后一对
    if current_q and current_a:
        pairs.append({
            "q": current_q.strip(),
            "a": current_a.strip(),
            "keywords": list(current_keywords),
            "tags": list(current_tags),
        })

    return pairs


def _load_qa_pairs(skill_name: str) -> list[dict]:
    """加载 skill 的 QA 对（mtime 缓存）。

    查找顺序：Hermes 已安装 skills 路径 → 源码 skills/ 目录（开发环境回退）。
    生产环境通过 install-trade-skills 将 references/ 同步到 ~/.hermes/skills/。
    """
    with _QA_CACHE_LOCK:
        if skill_name in _QA_CACHE:
            return _QA_CACHE[skill_name]

    qa_path = None

    # 1. 优先 Hermes 已安装路径（生产环境）
    skill_dir = _get_skill_dir(skill_name)
    if skill_dir:
        candidate = skill_dir / "references" / "qa_pairs.md"
        if candidate.is_file():
            qa_path = candidate

    # 2. 回退到源码目录（开发环境）
    if qa_path is None:
        try:
            import trade
            pkg_root = Path(trade.__file__).parent.parent
            src_qa = pkg_root / "skills" / skill_name / "references" / "qa_pairs.md"
            if src_qa.is_file():
                qa_path = src_qa
        except Exception:
            pass

    if qa_path is None:
        return []

    try:
        content = qa_path.read_text(encoding="utf-8")
    except OSError:
        return []

    pairs = _parse_qa_pairs(content)
    with _QA_CACHE_LOCK:
        _QA_CACHE[skill_name] = pairs
    return pairs


def _score_qa_relevance(query: str, pairs: list[dict]) -> list[dict]:
    """按与 query 的相关性对 QA 对评分排序，返回 top 5。

    评分策略：关键词单字匹配 > 标签匹配 > 问题标题词重叠。
    """
    import re as _re

    normed = _norm(query)
    scored = []

    for pair in pairs:
        score = 0

        # 关键词匹配：拆成单字/词逐项检查
        for kw in pair.get("keywords", []):
            kw_norm = _norm(kw)
            # 全词匹配
            if kw_norm in normed:
                score += 5
            else:
                # 拆词匹配（中文字符逐个检查，英文按空格拆）
                kw_chars = set(kw_norm.replace(' ', ''))
                query_chars = set(normed.replace(' ', ''))
                char_overlap = len(kw_chars & query_chars)
                if char_overlap >= 2:  # 至少 2 个字重叠
                    score += char_overlap

        # 标签匹配
        for tag in pair.get("tags", []):
            tag_norm = _norm(tag)
            if tag_norm in normed:
                score += 3
            else:
                tag_chars = set(tag_norm.replace(' ', ''))
                query_chars = set(normed.replace(' ', ''))
                if len(tag_chars & query_chars) >= 2:
                    score += 1

        # 问题标题词重叠
        q_normed = _norm(pair["q"])
        q_words = set(_re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', q_normed))
        query_words = set(_re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', normed))
        common = q_words & query_words
        score += len(common) * 2

        # 场景匹配
        for scene_tag in pair.get("tags", []):
            scene_norm = _norm(scene_tag)
            if any(w in normed for w in _re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', scene_norm)):
                score += 1

        scored.append({**pair, "_score": score})

    # 过滤零分，按分数降序，取 top 5
    scored = [s for s in scored if s["_score"] > 0]
    scored.sort(key=lambda x: -x["_score"])
    return scored[:5]


# ─────────────────────────────────────────────────────────────────────────────
# Query 增强（注入 skill prompt）
# ─────────────────────────────────────────────────────────────────────────────

# 注入标记（用于 LLM 识别这是系统注入的 skill 指令）
SKILL_INJECTION_MARKER = "[SKILL AUGMENTATION]"
SKILL_EXPLICIT_MARKER = "[SKILL EXPLICIT]"


def augment_query(
    query: str,
    *,
    skill_name: str | None = None,
    company_id: int | None = None,
) -> str:
    """将 skill injection prompt 注入用户 query。

    两种调用约定：
    1. 隐式匹配 — match_skill(query) 自动检测到 skill 后触发注入
    2. 显式指定 — LLM/frontend 已知要使用哪个 skill，直接通过参数传入 skill_name

    参数：
        query:      用户原始输入
        skill_name: 可选的显式 skill 名称（传入时覆盖自动匹配）
        company_id: 可选的公司 ID（用于 b2b-data-directory 等需要注入路径的 skill）

    返回：
        注入后的完整 query（含 [SKILL AUGMENTATION] 标记块）。
        无匹配且无显式 skill_name 时，原样返回 query，不做任何修改。
    """
    # 确定要注入的 skill
    # 优先使用显式传入的 skill_name，否则通过自动匹配检测
    from trade.skill_registry import _BLOCKED_SKILLS

    if skill_name:
        skill = get_skill_by_name(skill_name)
        if skill and skill["name"] in _BLOCKED_SKILLS:
            skill = None
    else:
        results = _score_skills(query)
        skill = get_skill_by_name(results[0]["skill_name"]) if results else None
    if skill and skill["name"] in _BLOCKED_SKILLS:
        return query

    # 如果两个路径都未匹配到 skill，原样返回用户 query，不做任何修改
    if skill is None:
        return query  # 无匹配 → 原样透传

    name = skill["name"]

    # 优先从 SKILL.md frontmatter 加载 injection_prompt，失败时降级到硬编码 augment_prompt
    augment = load_injection_prompt(name)
    # SKILL.md 中没有 injection_prompt 字段时，使用 skill_registry 中预定义的默认 prompt
    if augment is None:
        augment = skill.get("augment_prompt", "")

    # 检索最相关的 QA 对（references/qa_pairs.md），精准注入相关知识
    qa_pairs = _load_qa_pairs(name)
    qa_injection = ""
    if qa_pairs:
        relevant = _score_qa_relevance(query, qa_pairs)
        if relevant:
            qa_lines = ["\n## 相关知识（精准匹配）\n"]
            for i, r in enumerate(relevant):
                qa_lines.append(f"**Q{i+1}**: {r['q']}")
                qa_lines.append(f"**A{i+1}**: {r['a']}\n")
            qa_injection = "\n".join(qa_lines)

    # 路径相关 skill：注入公司数据目录路径
    data_dir_hint = ""
    if name == "b2b-data-directory" and company_id:
        from trade import company as _co
        tc = _co.get_trade_company(company_id)
        if tc and tc.get("data_dir"):
            # slug 在 companies 表中，不在 trade_companies 表中
            slug = _co.slug_from_id(company_id) or "unknown"
            data_dir_hint = (
                f"\n公司数据目录路径：{tc['data_dir']}\n"
                f"完整路径示例：~/.trade/companies/{slug}/"
            )

    # 组装注入块（含 QA 对精准匹配）
    injection = (
        f"\n"
        f"{SKILL_INJECTION_MARKER}\n"
        f"## 技能触发：{name}\n"
        f"{SKILL_EXPLICIT_MARKER if skill_name else ''}\n"
        f"{augment}"
        f"{data_dir_hint}"
        f"{qa_injection}"
        f"## 用户原始问题\n{query}\n"
        f"{SKILL_INJECTION_MARKER}\n"
    )

    return injection
