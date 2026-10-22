"""聊天副驾核心逻辑测试（平台无关部分：extract / context / draft）。

副驾的验收标准里最硬的三条都在这里钉住：
    - 铁律 3 数字只从库里取（草稿里没有出处的数字必须被剔除）
    - 铁律 4 客户匹配宁缺毋滥（低于阈值按新客户，且不带既有上下文）
    - 抽取失败必须分类报错（协议不兼容 / 模型不支持视觉），不许假装读到了
"""

from __future__ import annotations

import json

from trade.copilot import context as ctx_mod
from trade.copilot import draft as draft_mod
from trade.copilot import extract as extract_mod
from trade.copilot.types import CustomerContext

# ── extract：JSON 解析与错误分类 ────────────────────────────────────────────


class TestParseExtraction:
    def test_parses_plain_json(self):
        raw = json.dumps({
            "app": "WeChat",
            "contact": "John Smith",
            "language": "en",
            "messages": [
                {"who": "customer", "text": "What is your MOQ?"},
                {"who": "me", "text": "We can offer 500 pcs."},
            ],
            "confidence": 0.9,
        })
        result = extract_mod.parse_extraction(raw)
        assert result.ok
        assert result.contact == "John Smith"
        assert result.language == "en"
        assert len(result.messages) == 2
        assert result.messages[0].who == "customer"
        assert result.confidence == 0.9

    def test_parses_fenced_json(self):
        raw = '```json\n{"contact": "A", "messages": [], "confidence": 0.5}\n```'
        result = extract_mod.parse_extraction(raw)
        assert result.ok
        assert result.contact == "A"

    def test_parses_json_with_surrounding_text(self):
        raw = '好的，结果如下：{"contact": "B", "messages": [], "confidence": 0.7} 希望有帮助'
        result = extract_mod.parse_extraction(raw)
        assert result.ok
        assert result.contact == "B"

    def test_invalid_json_does_not_swallow(self):
        """解析失败必须带 error（UI 要显示"可能不准"并展示原文），不许返回空结果。"""
        result = extract_mod.parse_extraction("完全不是 JSON")
        assert not result.ok
        assert "JSON" in result.error
        assert result.error_kind == "parse"

    def test_unknown_who_becomes_unknown(self):
        raw = json.dumps({
            "contact": "", "confidence": 0.4,
            "messages": [{"who": "系统通知", "text": "x"}, {"who": "me", "text": "y"}],
        })
        result = extract_mod.parse_extraction(raw)
        assert result.messages[0].who == "unknown"
        assert result.messages[1].who == "me"

    def test_empty_text_messages_dropped(self):
        raw = json.dumps({"contact": "A", "confidence": 0.5, "messages": [
            {"who": "customer", "text": "  "}, {"who": "me", "text": "ok"}]})
        result = extract_mod.parse_extraction(raw)
        assert len(result.messages) == 1

    def test_confidence_clamped(self):
        raw = json.dumps({"contact": "A", "confidence": 5.0, "messages": []})
        assert extract_mod.parse_extraction(raw).confidence == 1.0
        raw = json.dumps({"contact": "A", "confidence": -2, "messages": []})
        assert extract_mod.parse_extraction(raw).confidence == 0.0

    def test_latest_from_customer(self):
        raw = json.dumps({"contact": "A", "confidence": 0.9, "messages": [
            {"who": "me", "text": "hi"},
            {"who": "customer", "text": "first"},
            {"who": "customer", "text": "second"},
        ]})
        result = extract_mod.parse_extraction(raw)
        assert result.latest_from_customer().text == "second"


class TestErrorClassification:
    """两类错误必须分开（任务书 §3）。"""

    def test_no_vision_kind(self):
        kind, reason = extract_mod._classify_error(
            RuntimeError("model does not support image input")
        )
        assert kind == "no_vision"
        assert "视觉" in reason

    def test_protocol_kind(self):
        kind, reason = extract_mod._classify_error(
            RuntimeError("unsupported api, invalid base_url")
        )
        assert kind == "protocol"
        assert "不兼容" in reason

    def test_other_kind(self):
        kind, reason = extract_mod._classify_error(RuntimeError("连接超时"))
        assert kind == "other"
        assert "连接超时" in reason


# ── context：匹配阈值与宁缺毋滥 ───────────────────────────────────────────


class TestMatchCustomer:
    def _patch_customers(self, monkeypatch, customers):
        monkeypatch.setattr(ctx_mod, "_list_company_customers", lambda cid: customers)
        monkeypatch.setattr(ctx_mod, "_fuzzy_search", lambda q, cid: [])

    def test_no_company_is_new_contact(self):
        result = ctx_mod.match_customer("John", company_id=0)
        assert result.new_contact is True
        assert result.matched is False
        assert result.history == []

    def test_empty_contact_is_new_contact(self):
        result = ctx_mod.match_customer("", company_id=1)
        assert result.new_contact is True

    def test_exact_name_hit_ignores_punctuation(self, monkeypatch):
        customers = [{"id": 7, "name": "John Smith"}]
        self._patch_customers(monkeypatch, customers)
        result = ctx_mod.match_customer("john.smith", company_id=1)
        # 归一后完全相同 → 命中（不依赖向量分数）
        assert result.customer_id == 7
        assert result.matched is True
        assert result.match_score == 1.0

    def test_low_score_is_new_contact(self, monkeypatch):
        """低于阈值 → 按新客户，且不带任何既有上下文（铁律 4）。"""
        monkeypatch.setattr(
            ctx_mod, "_list_company_customers",
            lambda cid: [{"id": 1, "name": "A公司"}],
        )
        monkeypatch.setattr(
            ctx_mod, "_fuzzy_search",
            lambda q, cid: [{"customer_id": 1, "score": 0.45}],
        )
        result = ctx_mod.match_customer("某客户", company_id=1)
        assert result.matched is False
        assert result.new_contact is True
        assert result.history == []
        assert result.product_entries == []

    def test_high_score_hits(self, monkeypatch):
        monkeypatch.setattr(
            ctx_mod, "_list_company_customers",
            lambda cid: [{"id": 3, "name": "Acme"}],
        )
        monkeypatch.setattr(
            ctx_mod, "_fuzzy_search",
            lambda q, cid: [{"customer_id": 3, "score": 0.8}],
        )
        monkeypatch.setattr(
            ctx_mod, "_get_customer",
            lambda cid, company: {"id": cid, "name": "Acme"},
        )
        result = ctx_mod.match_customer("Acme Ltd", company_id=1)
        assert result.matched is True
        assert result.new_contact is False
        assert result.customer_id == 3

    def test_ambiguous_candidates_treated_as_new(self, monkeypatch):
        """多候选且分数接近 → 宁缺毋滥，按新客户（铁律 4）。"""
        monkeypatch.setattr(
            ctx_mod, "_list_company_customers",
            lambda cid: [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
        )
        monkeypatch.setattr(
            ctx_mod, "_fuzzy_search",
            lambda q, cid: [
                {"customer_id": 1, "score": 0.80},
                {"customer_id": 2, "score": 0.78},
            ],
        )
        result = ctx_mod.match_customer("某个公司", company_id=1)
        assert result.matched is False
        assert result.new_contact is True


class TestLoadHistory:
    def test_unmatched_customer_gets_no_history(self):
        ctx = CustomerContext(matched=False, new_contact=True)
        assert ctx_mod.load_history(ctx, company_id=1) == []

    def test_matched_customer_history_filtered_by_name(self, monkeypatch):
        ctx = CustomerContext(matched=True, customer_id=3, customer_name="Acme")

        class _CM:
            @staticmethod
            def search_history(company_id, time_range="all", limit=20, **kw):
                return [
                    {"query": "Acme 询价 1000 pcs", "response": "ok"},
                    {"query": "别家客户的对话", "response": "x"},
                ]

        import trade.chat_memory as real_cm
        monkeypatch.setattr(real_cm, "search_history", _CM.search_history)

        history = ctx_mod.load_history(ctx, company_id=1)
        assert len(history) == 1
        assert "Acme" in history[0]


# ── draft：数字出处（铁律 3）──────────────────────────────────────────────


class TestStripUnbackedNumbers:
    def _ctx(self):
        return CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "报价单.pdf", "price": "$3.50", "moq": "500 pcs"}],
        )

    def test_backed_number_kept(self):
        ctx = self._ctx()
        draft, changed = draft_mod.strip_unbacked_numbers(
            "Our price is $3.50 per piece.", ctx
        )
        assert changed is False
        assert "$3.50" in draft

    def test_unbacked_number_replaced_with_placeholder(self):
        """库里没有的数字必须被剔除，换成（待确认）——不许带着假出处留在草稿里。"""
        ctx = self._ctx()
        draft, changed = draft_mod.strip_unbacked_numbers(
            "Our price is $99.99 per piece, MOQ 100 pcs.", ctx
        )
        assert changed is True
        assert "$99.99" not in draft
        assert "（待确认）" in draft
        # 有出处的 $3.50 仍在
        ctx2 = self._ctx()
        draft2, _ = draft_mod.strip_unbacked_numbers(
            "Price $3.50, but shipping $99.99.", ctx2
        )
        assert "$3.50" in draft2
        assert "$99.99" not in draft2

    def test_no_product_entries_means_no_numbers(self):
        """产品库一条都没有 → 草稿里任何数字都不许出现。"""
        ctx = CustomerContext(matched=False, new_contact=True)
        draft, changed = draft_mod.strip_unbacked_numbers(
            "We can do $10 with MOQ 50 pcs.", ctx
        )
        assert changed is True
        assert "$10" not in draft
        assert "50" not in draft

    def test_number_extraction_handles_units(self):
        nums = draft_mod._extract_numbers("MOQ 500 pcs, 30 天交期, 33kV")
        assert "MOQ500" in nums or "500" in nums
        assert any("30" in n for n in nums)
        assert any("33" in n for n in nums)


class TestParseDraft:
    def test_parses_draft_json(self):
        raw = json.dumps({
            "draft": "Hello, our MOQ is 500 pcs.",
            "summary_zh": "回复了 MOQ 问题",
            "sources": [{"label": "报价单.pdf", "value": "500 pcs"}],
        })
        result = draft_mod.parse_draft(raw)
        assert result.ok
        assert "MOQ" in result.draft
        assert result.summary_zh == "回复了 MOQ 问题"
        assert len(result.sources) == 1
        assert result.sources[0].label == "报价单.pdf"

    def test_empty_draft_is_error(self):
        raw = json.dumps({"draft": "  ", "summary_zh": "", "sources": []})
        result = draft_mod.parse_draft(raw)
        assert not result.ok
        assert result.error


class TestBuildPrompt:
    def test_unmatched_customer_has_no_history_in_prompt(self):
        ctx = CustomerContext(matched=False, new_contact=True, customer_entries=None) \
            if hasattr(CustomerContext, "customer_entries") else \
            CustomerContext(matched=False, new_contact=True)
        prompt = draft_mod.build_prompt("What is MOQ?", ctx)
        assert "（无）" in prompt  # 历史段
        assert "未识别客户" in prompt
        assert "不许出现任何数字" in prompt  # 产品库空的警告

    def test_matched_customer_profile_present(self):
        ctx = CustomerContext(
            matched=True, customer_id=3, customer_name="Acme",
            product_entries=[{"label": "报价单.pdf", "price": "$3.50"}],
        )
        prompt = draft_mod.build_prompt("hi", ctx)
        assert "Acme" in prompt
        assert "报价单.pdf" in prompt
