"""P6 回归测试：画像事实与礼物的同义去重（不误伤不同价格条款）。"""

from __future__ import annotations

import pytest


@pytest.fixture
def env(monkeypatch, tmp_path):
    """临时数据库与公司/客户夹具。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path))
    import trade.database as _db

    monkeypatch.setattr(_db, "_get_db_path", lambda: tmp_path / "trade.db")
    _db.init_db()

    import trade.company as co
    from trade import customer as cust_mod

    def _setup(name, slug, suggested_name=""):
        wd = tmp_path / (suggested_name or name)
        wd.mkdir(parents=True, exist_ok=True)
        for cat, _ in co._WORK_DIR_CATEGORIES:
            (wd / cat).mkdir(parents=True, exist_ok=True)
        return wd, True

    monkeypatch.setattr(co, "_setup_work_directory", _setup)
    cid = co.create(name="Dedup Co", slug="dedup-co")["id"]
    cust = cust_mod.create(company_id=cid, name="Acme Buyer")
    return {"cid": cid, "cust_id": cust["id"]}


def test_synonym_facts_are_deduped_while_distinct_terms_kept(env):
    """同义表达（如「不谈政治」与「不要聊政治话题」）只留一条；不同数值条款保留两条。"""
    from trade import profile

    first = profile._insert_pending_fact(
        company_id=env["cid"],
        customer_id=env["cust_id"],
        category="禁忌与偏好",
        subject="沟通禁忌",
        content="不谈政治",
        source_type="chat",
        source_ref=1,
        source_quote="聊天提到不谈政治",
    )
    second = profile._insert_pending_fact(
        company_id=env["cid"],
        customer_id=env["cust_id"],
        category="禁忌与偏好",
        subject="沟通禁忌",
        content="不要聊政治话题。",
        source_type="chat",
        source_ref=2,
        source_quote="别聊政治",
    )
    assert first is True
    assert second is False

    # 不同价格/付款条款不得误伤
    p1 = profile._insert_pending_fact(
        company_id=env["cid"],
        customer_id=env["cust_id"],
        category="商务偏好",
        subject="付款条款",
        content="要求 30% 定金 + 70% 见提单复印件",
        source_type="chat",
        source_ref=3,
        source_quote="30% deposit",
    )
    p2 = profile._insert_pending_fact(
        company_id=env["cid"],
        customer_id=env["cust_id"],
        category="商务偏好",
        subject="付款条款",
        content="要求 50% 定金 + 50% 见提单复印件",
        source_type="chat",
        source_ref=4,
        source_quote="50% deposit",
    )
    assert p1 is True
    assert p2 is True


def test_synonym_gifts_are_deduped(env):
    """同方向同日期、仅标点/空白不同的礼物不重复插入。"""
    from trade import profile

    g1 = profile._insert_pending_gift(
        company_id=env["cid"],
        customer_id=env["cust_id"],
        direction="我方赠送",
        item="龙井茶叶礼盒",
        approx_value=300,
        currency="CNY",
        gift_date="2026-10-01",
        occasion="中秋",
        source_type="chat",
        source_ref=1,
        source_quote="送了龙井茶叶礼盒",
    )
    g2 = profile._insert_pending_gift(
        company_id=env["cid"],
        customer_id=env["cust_id"],
        direction="我方赠送",
        item="龙井茶叶礼盒！",
        approx_value=300,
        currency="CNY",
        gift_date="2026-10-01",
        occasion="中秋节",
        source_type="chat",
        source_ref=2,
        source_quote="龙井茶叶礼盒",
    )
    assert g1 is True
    assert g2 is False
