"""
Smart Trade AI — 本地 Embedding 后端抽象（优化路线 P0-1 / P0-2 共用基础）。

设计目标：
1. 零依赖默认可用：TfidfBackend 纯标准库实现，字符 n-gram 同时支持
   中英文（无需分词），离线可用，符合项目 local-first 定位。
2. 可插拔：TRADE_EMBEDDING_BACKEND=st 时使用 sentence-transformers
  （需另装，质量更高）；=tfidf 强制使用默认实现；=auto（默认）
   优先 st、不可用时回退 tfidf。
3. 线程安全：fit 之后只读；get_backend() 单例加锁。

环境变量：
    TRADE_EMBEDDING_BACKEND   tfidf | st | auto（默认 auto）
    TRADE_ST_MODEL            sentence-transformers 模型名
                              （默认 paraphrase-multilingual-MiniLM-L12-v2，
                               中英双语）
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading
from collections import Counter

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """小写 + 空白折叠。注意：不做分词，字符 n-gram 对中英文都有效。"""
    return _WS_RE.sub(" ", text.lower()).strip()


def cosine_sim(a: list[float], b: list[float]) -> float:
    """余弦相似度。假设输入已 L2 归一化；零向量返回 0.0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    s = sum(x * y for x, y in zip(a, b, strict=True))  # 长度已校验，strict 让不一致立刻暴露
    # 钳制浮点误差
    return max(-1.0, min(1.0, s))


class EmbeddingBackend:
    """后端协议：dim / needs_fit / fit(corpus) / embed(texts)。"""

    @property
    def dim(self) -> int:  # noqa: D102
        raise NotImplementedError

    @property
    def needs_fit(self) -> bool:  # noqa: D102
        return False

    def fit(self, corpus: list[str]) -> None:  # noqa: D102
        pass

    def embed(self, texts: list[str]) -> list[list[float]]:  # noqa: D102
        raise NotImplementedError


class TfidfBackend(EmbeddingBackend):
    """零依赖 TF-IDF（字符 n-gram）后端。

    - 不分词：对中文按字切 n-gram，对英文同样有效；
    - 确定性：词表按 (df desc, term asc) 排序后截断，同语料下向量稳定；
    - 输出 L2 归一化，可直接做点积当余弦相似度。
    """

    def __init__(self, ngram_range: tuple[int, int] = (2, 4), max_features: int = 4096):
        self.ngram_range = ngram_range
        self.max_features = max_features
        self._vocab: dict[str, int] = {}
        self._idf: list[float] = []
        self._fitted = False
        self._lock = threading.Lock()

    @property
    def dim(self) -> int:
        return len(self._vocab)

    @property
    def needs_fit(self) -> bool:
        return True

    @staticmethod
    def _ngrams(text: str, ngram_range: tuple[int, int]) -> list[str]:
        text = _normalize(text)
        if not text:
            return []
        # 去掉空格后按字符切 n-gram（空格本身不携带语义）
        chars = text.replace(" ", "")
        lo, hi = ngram_range
        out = []
        for n in range(lo, hi + 1):
            if len(chars) < n:
                continue
            out.extend(chars[i : i + n] for i in range(len(chars) - n + 1))
        return out

    def fit(self, corpus: list[str]) -> None:
        """在语料上构建词表与 IDF。线程安全，可重复调用（重建）。"""
        with self._lock:
            df: Counter[str] = Counter()
            n_docs = 0
            for doc in corpus:
                n_docs += 1
                for term in set(self._ngrams(doc, self.ngram_range)):
                    df[term] += 1
            # 按文档频率降序、词本身升序，保证确定性
            ranked = sorted(df.items(), key=lambda kv: (-kv[1], kv[0]))
            vocab_terms = [t for t, _ in ranked[: self.max_features]]
            self._vocab = {t: i for i, t in enumerate(vocab_terms)}
            n = max(n_docs, 1)
            self._idf = [math.log((1 + n) / (1 + df[t])) + 1.0 for t in vocab_terms]
            self._fitted = True
            logger.info("TfidfBackend fitted: %d docs, %d features", n_docs, len(self._vocab))

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self._fitted:
            raise RuntimeError("TfidfBackend.embed() before fit(). 先调用 fit(corpus)。")
        vecs = []
        for text in texts:
            tf: Counter[str] = Counter(self._ngrams(text, self.ngram_range))
            vec = [0.0] * len(self._vocab)
            for term, cnt in tf.items():
                idx = self._vocab.get(term)
                if idx is not None:
                    vec[idx] = cnt * self._idf[idx]
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            vecs.append(vec)
        return vecs


    def export_state(self) -> dict:
        """导出词表与 IDF（JSON 可序列化），供跨进程持久化。

        为什么需要：客户向量的写入与查询可能发生在**不同进程**（服务重启后）。
        TF-IDF 的空间由 fit 语料决定，若查询时没有同一份词表/IDF，向量不可比 ——
        只能降级。把 fit 结果存进库里，重启后 load_state() 即可继续用。
        """
        with self._lock:
            if not self._fitted:
                return {}
            return {
                "ngram_range": list(self.ngram_range),
                "max_features": self.max_features,
                "vocab": list(self._vocab.keys()),  # 顺序即索引
                "idf": list(self._idf),
            }

    def load_state(self, state: dict) -> bool:
        """从 export_state() 的结果恢复 fit 状态。失败返回 False（调用方降级）。"""
        try:
            vocab = [str(t) for t in (state.get("vocab") or [])]
            idf = [float(x) for x in (state.get("idf") or [])]
            if not vocab or len(vocab) != len(idf):
                return False
            ng = state.get("ngram_range") or list(self.ngram_range)
            with self._lock:
                self.ngram_range = (int(ng[0]), int(ng[1]))
                self.max_features = int(state.get("max_features") or self.max_features)
                self._vocab = {t: i for i, t in enumerate(vocab)}
                self._idf = idf
                self._fitted = True
            logger.info("TfidfBackend 状态已恢复：%d 维", len(vocab))
            return True
        except Exception as e:
            logger.warning("TfidfBackend.load_state 失败: %s", e)
            return False


class SentenceTransformersBackend(EmbeddingBackend):
    """sentence-transformers 后端（可选依赖，质量更高）。

    模型通过 TRADE_ST_MODEL 指定，默认 paraphrase-multilingual-MiniLM-L12-v2。
    首次 embed 时懒加载模型；未安装时抛 ImportError 由上层回退。
    """

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.environ.get(
            "TRADE_ST_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
        )
        self._model = None
        self._dim = 0
        self._lock = threading.Lock()

    @property
    def dim(self) -> int:
        self._ensure_model()
        return self._dim

    def _ensure_model(self):
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise ImportError(
                    "sentence-transformers 未安装：pip install sentence-transformers "
                    "，或设置 TRADE_EMBEDDING_BACKEND=tfidf 使用零依赖后端。"
                ) from e
            logger.info("Loading sentence-transformers model: %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)
            self._dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._ensure_model()
        arr = self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return [list(map(float, row)) for row in arr]


# ── 实例管理（按用途隔离）──────────────────────────────────────────────────

# **为什么不是单一全局单例**：TF-IDF 的向量空间由 fit 语料决定。skill 语义路由与
# 客户向量检索是两个不同的 fit 语料，共用一个实例时，一方的 fit 会让另一方已缓存的
# 矩阵作废 —— 实测：客户索引重建后（dim 285→48）skill 语义命中全部变成 0.0，
# **静默失效**（不报错、不降级提示）。所以按 scope 隔离实例；同 scope 内取单例。
_backends: dict[str, EmbeddingBackend] = {}
_backend_lock = threading.Lock()


def get_backend(kind: str | None = None, *, scope: str = "default") -> EmbeddingBackend:
    """返回某用途（scope）的后端实例：scope 内单例，scope 间互不影响。

    kind: "tfidf" | "st" | "auto" | None（读 TRADE_EMBEDDING_BACKEND，默认 tfidf）。
    auto 优先 sentence-transformers，不可用则回退 tfidf（并记日志）；
    注意 auto/st 首次加载模型可能触发下载（数百 MB），离线/弱网环境别用。
    """
    kind = (kind or os.environ.get("TRADE_EMBEDDING_BACKEND", "tfidf")).strip().lower()
    with _backend_lock:
        existing = _backends.get(scope)
        if existing is not None:
            return existing
        backend: EmbeddingBackend
        if kind == "tfidf":
            backend = TfidfBackend()
        elif kind == "st":
            backend = SentenceTransformersBackend()
        else:  # auto
            try:
                backend = SentenceTransformersBackend()
                # 触发一次懒加载检查，不可用立刻回退
                _ = backend.dim
            except Exception as e:
                logger.info("sentence-transformers 不可用，回退到 TfidfBackend: %s", e)
                backend = TfidfBackend()
        _backends[scope] = backend
        return backend


def reset_backend(scope: str | None = None) -> None:
    """测试用：清空实例缓存（给 scope 则只清该 scope）。"""
    with _backend_lock:
        if scope is None:
            _backends.clear()
        else:
            _backends.pop(scope, None)
