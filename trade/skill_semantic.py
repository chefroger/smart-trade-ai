"""
Smart Trade AI — 混合 Skill 路由：关键词快路径 + 语义兜底（优化路线 P0-1）。

背景：现有 skill_router  pure 关键词打分（词边界 3 分 / 子串 1 分），
用户换个说法就匹配不上。本模块在其之上加一层语义检索：

    关键词高置信  → 直接用关键词结果（快、省 token、可解释）
    关键词低置信/无匹配 → 语义检索补位，两路加权融合

设计要点：
- 索引构建在 skill 注册表上（name + triggers + input_fmt + output_fmt），
  新增 skill 只需 rebuild()，无需改代码；
- embedding 后端复用 trade.embeddings（默认零依赖 TF-IDF，可切 st）；
- 所有阈值走环境变量，可线上调参；
- 失败时静默回退纯关键词，保证永不拖垮主流程。

环境变量：
    TRADE_ROUTER_MODE              keyword | hybrid（默认 keyword，保持现状）
    TRADE_HYBRID_KEYWORD_CONFIDENT 关键词多少分算"高置信"（默认 6，即 2 个词边界命中）
    TRADE_SEMANTIC_MIN_SCORE       语义最低分（默认 0.15，见下方校准说明）
    TRADE_HYBRID_W_KEYWORD         融合权重-关键词（默认 0.5）
    TRADE_HYBRID_W_SEMANTIC        融合权重-语义（默认 0.5）
    TRADE_SEMANTIC_TOP_K           语义候选数（默认 5）

## 阈值怎么定出来的（2026-10-13，自检索校准）

用 37 个 skill 的 **990 条触发词**做查询、对 skill 文档做自检索：

  - 自身 skill 得分：中位数 0.176，p25 0.068（长尾很重）
  - 噪声（其他 skill 最高分）：中位数 0.126，最高 0.678
  - 字面触发词的 top1 命中率只有 59% —— TF-IDF 字符 n-gram 在 37 个中文
    skill 上的区分度有限，**别指望它纠错**

默认取 0.15（略高于噪声中位数、低于正确中位数）。更重要的是：**990 条触发词
里没有一条落在"关键词无命中"桶**（触发词天生是关键词可见的），所以这套校准
只能证明"不误伤"，证明不了"有帮助"。真正能替关键词兜底的是**改写查询**，
那需要真实用户 query 评测集 —— 在评测集出来之前：

  - `TRADE_ROUTER_MODE` 默认保持 `keyword`（本模块不会生效）；
  - 融合公式保证了只要关键词有任何命中，top1 一定来自关键词（0.5·1.0=0.5
    高于任何"纯语义"得分上限 0.5·sem），所以开启 hybrid 也不会让语义压过
    确定的关键词信号 —— 语义只可能在关键词**完全没命中**时改变结果。
"""

from __future__ import annotations

import logging
import os
import threading

from trade.embeddings import cosine_sim, get_backend

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


def _load_registry_skills() -> list[dict]:
    """从 skill_registry 读取可用 skill（排除 _BLOCKED_SKILLS）。"""
    try:
        from trade.skill_registry import _BLOCKED_SKILLS, _SKILLS
    except ImportError:
        return []
    return [s for s in _SKILLS if s.get("name") not in _BLOCKED_SKILLS]


def build_documents(skills: list[dict]) -> list[tuple[str, str]]:
    """把每个 skill 拍平成一段检索文本。

    文本 = skill 名 + 触发词 + 输入/输出格式描述。触发词本身就是用户
    语言的同义表达，是最好的"查询-文档"对齐信号。
    """
    docs = []
    for s in skills:
        name = s.get("name", "")
        parts = [name.replace("-", " "), name]
        parts.extend(s.get("triggers") or [])
        parts.extend(s.get("aliases") or [])
        if s.get("input_fmt"):
            parts.append(str(s["input_fmt"]))
        if s.get("output_fmt"):
            parts.append(str(s["output_fmt"]))
        docs.append((name, " ".join(p for p in parts if p)))
    return docs


class SemanticSkillRouter:
    """语义 skill 检索器。线程安全；rebuild() 后可并发 search()。"""

    def __init__(self, skills: list[dict] | None = None, backend=None):
        self.skills = skills if skills is not None else _load_registry_skills()
        # scope 隔离：客户向量检索会在**自己的 fit 语料**上重建词表，共用实例会把
        # 这里的矩阵作废（实测：客户索引重建后本模块命中全变 0.0，静默失效）。
        self.backend = backend or get_backend(scope="skill_semantic")
        # **必须是可重入锁**：_ensure_built() 持锁后调用 rebuild()，而 rebuild()
        # 自己也取同一把锁 —— 普通 Lock 在这里是**永久死锁**（实测 search() 挂死，
        # 因为首个真实调用正好走 _ensure_built 这条路径；外部包原样如此，
        # 它的测试用 FakeRouter 顶掉了真路径所以没暴露）。
        self._lock = threading.RLock()
        self._names: list[str] = []
        self._matrix: list[list[float]] = []
        self._built = False

    def rebuild(self) -> int:
        """重建索引。返回索引的 skill 数量。"""
        docs = build_documents(self.skills)
        with self._lock:
            self._names = [name for name, _ in docs]
            texts = [text for _, text in docs]
            if self.backend.needs_fit:
                self.backend.fit(texts)
            self._matrix = self.backend.embed(texts)
            self._built = True
            logger.info("SemanticSkillRouter rebuilt: %d skills", len(self._names))
            return len(self._names)

    def _ensure_built(self):
        if not self._built:
            with self._lock:
                if not self._built:
                    self.rebuild()

    def search(
        self, query: str, top_k: int | None = None, min_score: float | None = None
    ) -> list[dict]:
        """返回 [{"skill_name", "score"(0~1), "rank"}]，按 score 降序。"""
        query = (query or "").strip()
        if not query:
            return []
        top_k = top_k if top_k is not None else _env_int("TRADE_SEMANTIC_TOP_K", 5)
        min_score = min_score if min_score is not None else _env_float("TRADE_SEMANTIC_MIN_SCORE", 0.15)
        try:
            self._ensure_built()
            with self._lock:
                names, matrix = self._names, self._matrix
            qvec = self.backend.embed([query])[0]
        except Exception as e:
            logger.warning("语义检索失败，回退空结果: %s", e)
            return []
        scored = []
        for i, name in enumerate(names):
            s = cosine_sim(qvec, matrix[i])
            if s >= min_score:
                scored.append({"skill_name": name, "score": round(s, 4), "rank": 0})
        scored.sort(key=lambda d: d["score"], reverse=True)
        for i, d in enumerate(scored[:top_k]):
            d["rank"] = i + 1
        return scored[:top_k]


# ── 进程级单例 ────────────────────────────────────────────────────────────

_router_singleton: SemanticSkillRouter | None = None
_router_lock = threading.Lock()


def get_semantic_router() -> SemanticSkillRouter:
    global _router_singleton
    with _router_lock:
        if _router_singleton is None:
            _router_singleton = SemanticSkillRouter()
        return _router_singleton


def reset_semantic_router() -> None:
    """测试用：清空单例。"""
    global _router_singleton
    with _router_lock:
        _router_singleton = None


# ── 混合匹配（可直接替换 match_skill 的 drop-in） ──────────────────────────

_EXPLICIT_SCORE = 9999  # 与 skill_router._EXPLICIT_SCORE 对齐


def hybrid_rank(
    keyword_hits: list[dict],
    semantic_hits: list[dict],
    w_keyword: float | None = None,
    w_semantic: float | None = None,
) -> list[dict]:
    """融合两路结果。

    keyword_hits: skill_router._score_skills() 的输出（score 为整数）。
    semantic_hits: SemanticSkillRouter.search() 的输出（score 0~1）。
    融合分 = w_kw * 归一化关键词分 + w_sem * 语义分；只出现在一路的，
    缺失路按 0 计。返回 [{"skill_name","score","source"}] 降序。
    """
    w_keyword = w_keyword if w_keyword is not None else _env_float("TRADE_HYBRID_W_KEYWORD", 0.5)
    w_semantic = w_semantic if w_semantic is not None else _env_float("TRADE_HYBRID_W_SEMANTIC", 0.5)
    max_kw = max([h.get("score", 0) for h in keyword_hits] + [1])
    merged: dict[str, dict] = {}
    for h in keyword_hits:
        name = h["skill_name"]
        merged[name] = {
            "skill_name": name,
            "kw_norm": h.get("score", 0) / max_kw,
            "sem": 0.0,
            "source": "keyword",
        }
    for h in semantic_hits:
        name = h["skill_name"]
        if name in merged:
            merged[name]["sem"] = h.get("score", 0.0)
            merged[name]["source"] = "hybrid"
        else:
            merged[name] = {
                "skill_name": name,
                "kw_norm": 0.0,
                "sem": h.get("score", 0.0),
                "source": "semantic",
            }
    ranked = []
    for name, m in merged.items():
        score = w_keyword * m["kw_norm"] + w_semantic * m["sem"]
        ranked.append({"skill_name": name, "score": round(score, 4), "source": m["source"]})
    ranked.sort(key=lambda d: d["score"], reverse=True)
    return ranked


def match_skill_hybrid(query: str) -> tuple[dict | None, list[dict]]:
    """混合路由主入口。

    返回 (best, alternatives)：
      best: {"skill_name","score","source"} 或 None；
      alternatives: 其余候选（供前端"是不是想找…"提示）。

    决策链：
      1. 显式调用（用 b2b-xxx）→ 绝对优先（沿用原逻辑）；
      2. 关键词 top 分 >= 高置信阈值 → 纯关键词结果；
      3. 否则语义检索 + 加权融合。
    任何异常 → 回退纯关键词，保证永不抛错。
    """
    try:
        from trade import skill_router

        kw_hits = skill_router._score_skills(query)
        # 显式调用直接透传（score 9999）
        if kw_hits and kw_hits[0].get("score", 0) >= _EXPLICIT_SCORE:
            best = dict(kw_hits[0])
            best["source"] = "explicit"
            return best, []

        confident = _env_int("TRADE_HYBRID_KEYWORD_CONFIDENT", 6)
        if kw_hits and kw_hits[0].get("score", 0) >= confident:
            best = {"skill_name": kw_hits[0]["skill_name"], "score": 1.0, "source": "keyword"}
            alts = [
                {"skill_name": h["skill_name"], "score": h["score"] / max(kw_hits[0]["score"], 1), "source": "keyword"}
                for h in kw_hits[1:4]
            ]
            return best, alts

        sem_hits = get_semantic_router().search(query)
        ranked = hybrid_rank(kw_hits, sem_hits)
        if not ranked:
            return None, []
        return ranked[0], ranked[1:4]
    except Exception as e:
        logger.warning("混合路由异常，回退关键词路由: %s", e)
        try:
            from trade import skill_router

            kw_hits = skill_router._score_skills(query)
            if not kw_hits:
                return None, []
            return {"skill_name": kw_hits[0]["skill_name"], "score": 1.0, "source": "keyword-fallback"}, []
        except Exception:
            return None, []
