"""trade.embeddings 模块测试（纯标准库，无外部依赖）。"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trade.embeddings import (  # noqa: E402
    TfidfBackend,
    cosine_sim,
    get_backend,
    reset_backend,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_backend()
    yield
    reset_backend()


def test_cosine_sim_basic():
    assert cosine_sim([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_sim([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_sim([], []) == 0.0
    assert cosine_sim([1.0], [1.0, 2.0]) == 0.0  # 维度不一致


def test_tfidf_fit_embed_roundtrip():
    b = TfidfBackend()
    corpus = ["客户背景调查", "开发信写作", "客户背景调查报告"]
    b.fit(corpus)
    assert b.dim > 0
    vecs = b.embed(corpus)
    assert len(vecs) == 3
    # L2 归一化
    for v in vecs:
        assert math.sqrt(sum(x * x for x in v)) == pytest.approx(1.0)
    # 相同文本相似度为 1；"客户背景调查" vs "客户背景调查报告" 应高于 vs "开发信写作"
    s_same = cosine_sim(vecs[0], vecs[0])
    s_close = cosine_sim(vecs[0], vecs[2])
    s_far = cosine_sim(vecs[0], vecs[1])
    assert s_same == pytest.approx(1.0)
    assert s_close > s_far


def test_tfidf_english():
    b = TfidfBackend()
    b.fit(["due diligence check", "cold email writing"])
    vecs = b.embed(["due diligence", "cold email"])
    assert cosine_sim(vecs[0], b.embed(["due diligence check"])[0]) > 0.5


def test_tfidf_embed_before_fit_raises():
    b = TfidfBackend()
    with pytest.raises(RuntimeError):
        b.embed(["hello"])


def test_tfidf_empty_text_zero_vector():
    b = TfidfBackend()
    b.fit(["hello world"])
    vecs = b.embed([""])
    assert all(v == 0.0 for v in vecs[0])


def test_tfidf_deterministic():
    corpus = ["背调", "开发信", "报价单"]
    b1, b2 = TfidfBackend(), TfidfBackend()
    b1.fit(corpus)
    b2.fit(corpus)
    assert b1.embed(["背调"]) == b2.embed(["背调"])


def test_get_backend_defaults_to_tfidf_without_st(monkeypatch):
    monkeypatch.setenv("TRADE_EMBEDDING_BACKEND", "tfidf")
    b = get_backend()
    assert isinstance(b, TfidfBackend)
    # 单例
    assert get_backend() is b


def test_get_backend_explicit_tfidf(monkeypatch):
    monkeypatch.setenv("TRADE_EMBEDDING_BACKEND", "tfidf")
    assert isinstance(get_backend(), TfidfBackend)


# ── 用途隔离与状态持久化（2026-10-13 集成时补，对应实测事故）─────────────────

class TestScopeIsolation:
    """两个消费者（skill 路由 / 客户向量检索）各用各的后端实例。

    实测事故：共用一个 TF-IDF 单例时，客户索引重建（在客户语料上重新 fit）
    会把 skill 路由的矩阵作废（dim 285→48），语义命中全部变成 0.0 —— 静默失效。
    """

    def test_scopes_get_separate_instances(self):
        reset_backend()
        a = get_backend("tfidf", scope="alpha")
        b = get_backend("tfidf", scope="beta")
        assert a is not b, "不同 scope 必须拿到不同实例"
        assert get_backend("tfidf", scope="alpha") is a, "同 scope 内应是单例"

    def test_fit_in_one_scope_does_not_touch_the_other(self):
        """一方的 fit 不得改变另一方的向量空间（维度/词表都不许动）。"""
        reset_backend()
        a = get_backend("tfidf", scope="alpha")
        b = get_backend("tfidf", scope="beta")
        a.fit(["灯具 出口 德国 汉堡", "紧固件 美国 家得宝"])
        before = a.embed(["灯具 出口"])[0]
        dim_before = a.dim

        # 另一方在自己的语料上 fit（真实场景：客户索引重建）
        b.fit(["完全不同的语料 只有这一条 内容也很短"])

        assert a.dim == dim_before, "对方的 fit 改变了本方的词表维度"
        assert a.embed(["灯具 出口"])[0] == before, "对方的 fit 改变了本方的向量"


class TestStatePersistence:
    """fit 状态可导出/恢复 —— 跨进程复用同一向量空间的前提。"""

    def test_export_load_round_trip_same_vectors(self):
        b1 = TfidfBackend()
        b1.fit(["灯具 出口 德国", "紧固件 美国 客户", "家纺 澳大利亚"])
        state = b1.export_state()
        assert state and state["vocab"] and len(state["vocab"]) == len(state["idf"])

        b2 = TfidfBackend()
        assert b2.load_state(state) is True
        assert b2.dim == b1.dim
        assert b2.embed(["灯具 出口"])[0] == b1.embed(["灯具 出口"])[0]

    def test_unfitted_exports_empty_and_load_rejects_garbage(self):
        assert TfidfBackend().export_state() == {}
        assert TfidfBackend().load_state({}) is False
        assert TfidfBackend().load_state({"vocab": ["a"], "idf": []}) is False
