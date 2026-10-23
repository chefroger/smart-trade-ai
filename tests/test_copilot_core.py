"""聊天副驾核心逻辑测试（平台无关部分：extract / context / draft）。

副驾的验收标准里最硬的三条都在这里钉住：
    - 铁律 3 数字只从库里取（草稿里没有出处的数字必须被剔除）
    - 铁律 4 客户匹配宁缺毋滥（低于阈值按新客户，且不带既有上下文）
    - 抽取失败必须分类报错（协议不兼容 / 模型不支持视觉），不许假装读到了
"""

from __future__ import annotations

import json
import time

import pytest

from trade.copilot import context as ctx_mod
from trade.copilot import draft as draft_mod
from trade.copilot import extract as extract_mod
from trade.copilot.numbers import extract_numbers as extract_mod_numbers
from trade.copilot.types import CONFIDENCE_THRESHOLD, CustomerContext, SourceRef

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

    def test_404_with_vision_path_is_protocol_not_no_vision(self):
        """端点 404 的文案里常带 v1/vision 字样 —— 不许误判成"模型不支持看图"。"""
        kind, _ = extract_mod._classify_error(
            RuntimeError("404 not found: /v1/vision")
        )
        assert kind == "protocol"


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


# ── 复审回归：数字识别覆盖（P0）────────────────────────────────────────────


class TestNumberCoverage:
    """复审 P0：11 种漏网形态每一种都必须被识别并替换掉。"""

    @pytest.mark.parametrize("form", [
        "USD 3.50", "3.50 USD", "30 days", "10%", "10 percent",
        "500 pieces", "50 dollars", "100 sets", "500", "三天", "五百个",
    ])
    def test_unbacked_form_is_stripped(self, form):
        ctx = CustomerContext(matched=False, new_contact=True)
        cleaned, changed = draft_mod.strip_unbacked_numbers(
            f"Our offer: {form}.", ctx
        )
        assert changed is True, f"漏掉了数字形态：{form!r}"
        assert "（待确认）" in cleaned

    def test_p0_whole_sentence_with_empty_library(self):
        """空产品库时，这整句必须被清理 —— 之前原样放行（changed=False）。"""
        ctx = CustomerContext(matched=False, new_contact=True)
        raw = "Delivery in 30 days, price USD 3.50, 10% discount, qty 500 pieces."
        cleaned, changed = draft_mod.strip_unbacked_numbers(raw, ctx)
        assert changed is True
        for token in ("30 days", "USD 3.50", "10%", "500 pieces"):
            assert token not in cleaned

    def test_library_and_draft_spellings_are_equivalent(self):
        """库里写 USD 3.50 / 30 days，草稿写 $3.50 / 30 天，必须算同一个数字。"""
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{
                "label": "价格表.md",
                "excerpt": "USD 3.50, 500 pcs, 30 days",
            }],
        )
        cleaned, changed = draft_mod.strip_unbacked_numbers(
            "Price is $3.50, MOQ 500, delivery 30 天.", ctx
        )
        assert changed is False, cleaned
        assert "$3.50" in cleaned and "30 天" in cleaned

    def test_unknown_currency_word_is_money_not_bare(self):
        """50 dollars 与 $50 归一后必须相同（金额类）。"""
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "q", "price": "$50"}],
        )
        cleaned, changed = draft_mod.strip_unbacked_numbers(
            "It costs 50 dollars.", ctx
        )
        assert changed is False
        assert "50 dollars" in cleaned


# ── 复审回归：产品库检索真的进文件（P1-1）────────────────────────────────


class TestLoadProductEntries:
    def _patch_libraries(self, monkeypatch, libs):
        import trade.library as library_module
        monkeypatch.setattr(library_module, "list_by_company", lambda cid: libs)

    def test_scans_files_and_extracts_facts(self, tmp_path, monkeypatch):
        (tmp_path / "valve-price.md").write_text(
            "# Valve\nMOQ: 500 pcs\nPrice: USD 3.50\nDelivery: 30 days\n",
            encoding="utf-8",
        )
        (tmp_path / "unrelated.txt").write_text("nothing here", encoding="utf-8")
        self._patch_libraries(monkeypatch, [
            {"id": 1, "name": "产品库", "root_path": str(tmp_path)},
        ])

        entries, facts = ctx_mod.load_product_entries("valve MOQ", company_id=1)
        assert len(entries) == 1
        assert "valve-price.md" in entries[0]["label"]
        values = " ".join(fact.value for fact in facts)
        assert "500" in values and "3.50" in values

        # 抽出来的 facts 必须能让草稿侧认可同样的数字
        ctx = CustomerContext(product_entries=entries, facts=facts)
        cleaned, changed = draft_mod.strip_unbacked_numbers(
            "Price USD 3.50, MOQ 500 pcs.", ctx
        )
        assert changed is False, cleaned

    def test_ignores_missing_root(self, monkeypatch):
        self._patch_libraries(monkeypatch, [
            {"id": 1, "name": "坏库", "root_path": "/definitely/not/here"},
        ])
        assert ctx_mod.load_product_entries("valve", company_id=1) == ([], [])

    def test_no_keywords_returns_empty(self, monkeypatch):
        self._patch_libraries(monkeypatch, [
            {"id": 1, "name": "产品库", "root_path": "/tmp"},
        ])
        assert ctx_mod.load_product_entries("   ", company_id=1) == ([], [])


# ── 复审回归：历史串户 / 关键词降级 / 同名多候选（P1-2、P1-3、P2）──────────


class TestHistoryAndMatchingHardening:
    def test_customer_id_substring_does_not_pull_other_history(self, monkeypatch):
        ctx = CustomerContext(matched=True, customer_id=1, customer_name="Acme")

        class _CM:
            @staticmethod
            def search_history(company_id, time_range="all", limit=20, **kw):
                return [
                    {"query": "1 号方案报价", "response": "x"},
                    {"query": "Acme 询价", "response": "y"},
                ]

        import trade.chat_memory as real_cm
        monkeypatch.setattr(real_cm, "search_history", _CM.search_history)

        assert ctx_mod.load_history(ctx, company_id=1) == ["Acme 询价"]

    def test_short_customer_name_gets_no_history(self, monkeypatch):
        ctx = CustomerContext(matched=True, customer_id=1, customer_name="A")

        class _CM:
            @staticmethod
            def search_history(company_id, time_range="all", limit=20, **kw):
                return [{"query": "A 公司报价", "response": ""}]

        import trade.chat_memory as real_cm
        monkeypatch.setattr(real_cm, "search_history", _CM.search_history)

        assert ctx_mod.load_history(ctx, company_id=1) == []

    def test_keyword_hit_without_name_overlap_is_new(self, monkeypatch):
        monkeypatch.setattr(
            ctx_mod, "_list_company_customers",
            lambda cid: [{"id": 1, "name": "Other Co"}],
        )
        monkeypatch.setattr(
            ctx_mod, "_fuzzy_search",
            lambda q, cid: [
                {"customer_id": 1, "score": 1.0, "match_type": "keyword"},
            ],
        )
        monkeypatch.setattr(
            ctx_mod, "_get_customer",
            lambda cid, company: {"id": cid, "name": "Other Co"},
        )
        result = ctx_mod.match_customer("Acme", company_id=1)
        assert result.matched is False
        assert result.new_contact is True

    def test_keyword_hit_with_name_overlap_matches(self, monkeypatch):
        monkeypatch.setattr(
            ctx_mod, "_list_company_customers",
            lambda cid: [{"id": 1, "name": "Acme Ltd"}],
        )
        monkeypatch.setattr(
            ctx_mod, "_fuzzy_search",
            lambda q, cid: [
                {"customer_id": 1, "score": 1.0, "match_type": "keyword"},
            ],
        )
        monkeypatch.setattr(
            ctx_mod, "_get_customer",
            lambda cid, company: {"id": cid, "name": "Acme Ltd"},
        )
        result = ctx_mod.match_customer("Acme", company_id=1)
        assert result.matched is True
        assert result.customer_id == 1

    def test_same_name_duplicates_are_ambiguous(self, monkeypatch):
        monkeypatch.setattr(
            ctx_mod, "_list_company_customers",
            lambda cid: [{"id": 1, "name": "Acme"}, {"id": 2, "name": "acme"}],
        )
        # 同名多候选必须在调模糊检索之前就按新客户处理（不许猜一个）
        monkeypatch.setattr(
            ctx_mod, "_fuzzy_search",
            lambda q, cid: (_ for _ in ()).throw(AssertionError("不该走模糊检索")),
        )
        result = ctx_mod.match_customer("Acme", company_id=1)
        assert result.matched is False
        assert result.new_contact is True


# ── 复审回归：草稿生成契约（P1-4、P1-5、P2）──────────────────────────────


class TestDraftRobustness:
    def test_agent_exception_becomes_error(self, monkeypatch):
        def boom(prompt, *, company_id):
            raise RuntimeError("boom")

        # 打 _run_once 而不是 _run_via_existing_chat：后者会先 import
        # trade.api.chat（重模块），在很短的测试超时里会先超时。
        monkeypatch.setattr(draft_mod, "_run_once", boom)
        result = draft_mod.generate_draft(
            "hi", CustomerContext(new_contact=True), company_id=1, timeout=0.5
        )
        assert not result.ok
        assert "boom" in result.error

    def test_system_exit_is_contained(self, monkeypatch):
        """Hermes 的 RelaunchExit 继承 SystemExit —— 不许穿透出 generate_draft。"""
        def relaunch(prompt, *, company_id):
            raise SystemExit(3)

        monkeypatch.setattr(draft_mod, "_run_once", relaunch)
        result = draft_mod.generate_draft(
            "hi", CustomerContext(new_contact=True), company_id=1, timeout=0.5
        )
        assert not result.ok
        assert "SystemExit" in result.error

    def test_timeout_is_really_enforced(self, monkeypatch):
        started = []

        def hang(prompt, *, company_id):
            started.append(True)
            time.sleep(5)
            return "late"

        monkeypatch.setattr(draft_mod, "_run_once", hang)
        result = draft_mod.generate_draft(
            "hi", CustomerContext(new_contact=True), company_id=1, timeout=0.2
        )
        assert started, "后台调用应该已经启动"
        assert not result.ok
        assert "超时" in result.error

    def test_placeholder_literal_in_customer_message_is_not_expanded(self):
        ctx = CustomerContext(matched=False, new_contact=True)
        prompt = draft_mod.build_prompt("please keep {history} literally", ctx)
        assert "please keep {history} literally" in prompt

    def test_sources_dropped_when_their_number_is_stripped(self):
        kept = draft_mod._reconcile_sources(
            [SourceRef(label="报价单", value="$99.99"), SourceRef(label="客户档案", value="Acme")],
            "Price （待确认）.",
        )
        assert kept == [SourceRef(label="客户档案", value="Acme")]


class TestExtractionContract:
    def test_raw_is_preserved_on_parse_failure(self):
        result = extract_mod.parse_extraction("完全不是 JSON")
        assert result.raw == "完全不是 JSON"
        assert result.error_kind == "parse"

    def test_raw_is_preserved_on_success(self):
        raw = json.dumps({"contact": "A", "messages": [], "confidence": 0.9})
        assert extract_mod.parse_extraction(raw).raw == raw

    def test_low_confidence_flag(self):
        low = json.dumps({
            "contact": "A", "messages": [],
            "confidence": CONFIDENCE_THRESHOLD - 0.1,
        })
        high = json.dumps({"contact": "A", "messages": [], "confidence": 1.0})
        assert extract_mod.parse_extraction(low).low_confidence is True
        assert extract_mod.parse_extraction(high).low_confidence is False

    def test_error_result_is_not_low_confidence(self):
        assert extract_mod.parse_extraction("nope").low_confidence is False


# ── 复审 2：粘连规格 / 幻影价格 / 时间换算 ────────────────────────────────

_GLUED_SPECS = ["40W", "24W", "0.5W", "3000K", "2700K", "IP65", "100lm", "DC24V"]


class TestGluedSpecNumbers:
    @pytest.mark.parametrize("form", _GLUED_SPECS)
    def test_unbacked_glued_spec_is_stripped(self, form):
        """无出处时整段剔除，不许残留 ".5W" / "DC（待确认）" 这类碎屑。"""
        ctx = CustomerContext(matched=False, new_contact=True)
        cleaned, changed = draft_mod.strip_unbacked_numbers(f"Spec {form}.", ctx)
        assert changed is True, form
        assert form not in cleaned
        assert cleaned == "Spec （待确认）."

    @pytest.mark.parametrize("form", _GLUED_SPECS)
    def test_backed_glued_spec_is_kept(self, form):
        """facts 里有同写法时保留（有出处就能写）。"""
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "规格书.pdf", "excerpt": f"Spec {form}"}],
        )
        cleaned, changed = draft_mod.strip_unbacked_numbers(f"Spec {form}.", ctx)
        assert changed is False, cleaned
        assert form in cleaned

    def test_chinese_neighbour_does_not_block_glued_spec(self):
        """汉字紧邻英文单位（"40W的灯"）也必须识别。"""
        ctx = CustomerContext(new_contact=True)
        cleaned, changed = draft_mod.strip_unbacked_numbers("40W的灯", ctx)
        assert changed is True
        assert cleaned == "（待确认）的灯"

    def test_spec_unit_keeps_its_identity(self):
        """40W 与 40 pcs 不是同一个数字，不能互相背书。"""
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "p", "excerpt": "Power 40W"}],
        )
        cleaned, changed = draft_mod.strip_unbacked_numbers("Qty 40 pcs", ctx)
        assert changed is True
        assert "40 pcs" not in cleaned


class TestPhantomPriceRegression:
    def test_e27_model_does_not_create_phantom_price(self):
        text = "Bulb E27 USD 1.25 MOQ 1000 pcs"
        assert extract_mod_numbers(text) == {"$1.25", "1000"}

        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "price.xlsx", "excerpt": text}],
        )
        # 真价必须有出处、保留
        kept, changed = draft_mod.strip_unbacked_numbers("Price $1.25", ctx)
        assert changed is False, kept
        # 幻影价必须被剔除
        cleaned, changed = draft_mod.strip_unbacked_numbers("Price $27", ctx)
        assert changed is True
        assert "$27" not in cleaned


class TestTimeUnitNormalization:
    def test_weeks_and_days_are_not_interchangeable(self):
        from trade.copilot.numbers import extract_numbers
        assert extract_numbers("2 weeks") == {"14d"}
        assert extract_numbers("2 days") == {"2d"}
        assert extract_numbers("两周") == {"14d"}

    def test_two_weeks_does_not_back_two_days(self):
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "q", "excerpt": "Delivery 2 weeks"}],
        )
        cleaned, changed = draft_mod.strip_unbacked_numbers("Delivery in 2 days", ctx)
        assert changed is True
        assert "2 days" not in cleaned

    def test_two_weeks_backs_fourteen_days(self):
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "q", "excerpt": "Delivery 2 weeks"}],
        )
        cleaned, changed = draft_mod.strip_unbacked_numbers("Delivery in 14 days", ctx)
        assert changed is False, cleaned


class TestChineseQuantities:
    def test_arabic_digits_with_chinese_measure_word(self):
        from trade.copilot.numbers import extract_numbers
        assert extract_numbers("共500件") == {"500"}
        assert extract_numbers("500个") == {"500"}

    def test_chinese_numeral_matches_arabic_library_value(self):
        from trade.copilot.numbers import extract_numbers
        assert extract_numbers("五百个") == {"500"}
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "p", "excerpt": "MOQ 500"}],
        )
        cleaned, changed = draft_mod.strip_unbacked_numbers("起订五百个", ctx)
        assert changed is False, cleaned


def test_search_terms_split_chinese_punctuation():
    assert ctx_mod._search_terms("LED，灯带") == ["led", "灯带"]
    assert ctx_mod._search_terms("阀门、法兰") == ["阀门", "法兰"]


# ── 审计批：简写金额 / 单位身份 / 牌号 / 小数残文 ─────────────────────────


class TestMagnitudeMoney:
    @pytest.mark.parametrize("text,key", [
        ("USD 2K", "$2000"),
        ("2K USD", "$2000"),
        ("3M USD", "$3000000"),
        ("price 2.5K USD", "$2500"),
        ("$2K", "$2000"),
        ("500 USD", "$500"),
    ])
    def test_shorthand_money_is_scaled(self, text, key):
        assert extract_mod_numbers(text) == {key}

    def test_shorthand_backs_the_full_amount_not_the_prefix(self):
        """库里的 USD 2K 必须给 $2000 背书，不能给 $2 背书（也不能反过来）。"""
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "报价.md", "excerpt": "Unit price USD 2K"}],
        )
        kept, changed = draft_mod.strip_unbacked_numbers("Total $2000", ctx)
        assert changed is False, kept
        stripped, changed = draft_mod.strip_unbacked_numbers("Total $2", ctx)
        assert changed is True
        assert "$2" not in stripped

    def test_brand_3m_is_not_money_nor_meters(self):
        """品牌 3M、网络制式 5G 不能被当成数字剔除，也不能被当成 3 米 / 5 克。"""
        ctx = CustomerContext(new_contact=True)
        for text in ("Use 3M tape", "supports 5G"):
            cleaned, changed = draft_mod.strip_unbacked_numbers(text, ctx)
            assert changed is False, cleaned


class TestUnitIdentity:
    def test_measure_units_do_not_back_each_other(self):
        """库里 40 kg 不能给 40 pcs / 40 mm / 40 sets 背书（审计 P1-3）。"""
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "规格书", "excerpt": "Weight 40 kg"}],
        )
        for draft in ("MOQ 40 pcs", "length 40 mm", "40 sets", "40 tons"):
            cleaned, changed = draft_mod.strip_unbacked_numbers(draft, ctx)
            assert changed is True, f"{draft!r} 被误判为有出处"
            assert "40" not in cleaned, cleaned

    def test_same_unit_still_backed(self):
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "规格书", "excerpt": "Weight 40 kg"}],
        )
        cleaned, changed = draft_mod.strip_unbacked_numbers("weight 40 kg", ctx)
        assert changed is False, cleaned

    @pytest.mark.parametrize("library,draft", [
        ("MOQ 500", "500 pcs"),
        ("MOQ 500 pcs", "MOQ 500"),
        ("500 pieces", "500 sets"),
    ])
    def test_count_units_are_interchangeable(self, library, draft):
        """计数单位归还为裸数字：MOQ 500 与 500 pcs 是同一件事。"""
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "报价", "excerpt": library}],
        )
        cleaned, changed = draft_mod.strip_unbacked_numbers(draft, ctx)
        assert changed is False, cleaned

    def test_color_temperature_distinct_from_bare_number(self):
        assert extract_mod_numbers("3000K") == {"3000k"}
        assert extract_mod_numbers("3000") == {"3000"}


class TestGradeCodes:
    @pytest.mark.parametrize("code,key", [
        ("S304", "s304"), ("Q235", "q235"),
        ("DN50", "dn50"), ("PN16", "pn16"),
    ])
    def test_grade_codes_are_visible(self, code, key):
        assert extract_mod_numbers(code) == {key}

    def test_grade_does_not_back_plain_number(self):
        ctx = CustomerContext(new_contact=True)
        cleaned, changed = draft_mod.strip_unbacked_numbers("Material S304", ctx)
        assert changed is True
        assert "S304" not in cleaned

    @pytest.mark.parametrize("text", ["we do B2B", "Q3 报告", "USB3 接口"])
    def test_common_tokens_are_not_numbers(self, text):
        """B2B / Q3 / USB3 这类普通词不能被当成数字剔除。"""
        assert extract_mod_numbers(text) == set()

    def test_dn50_does_not_back_50_pcs(self):
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "图纸", "excerpt": "flange DN50"}],
        )
        cleaned, changed = draft_mod.strip_unbacked_numbers("MOQ 50 pcs", ctx)
        assert changed is True, cleaned


class TestDecimalLeftover:
    def test_unknown_unit_leaves_no_partial_replacement(self):
        """旧行为把 0.5N 剔成 "（待确认）.5N" —— 宁可整段不动，也不留半截。"""
        ctx = CustomerContext(new_contact=True)
        for text in ("weight 0.5N", "size 3.5X"):
            cleaned, _ = draft_mod.strip_unbacked_numbers(text, ctx)
            assert cleaned == text, cleaned

    def test_magnitude_money_is_fully_removed(self):
        ctx = CustomerContext(new_contact=True)
        cleaned, changed = draft_mod.strip_unbacked_numbers("About 1.5M USD", ctx)
        assert changed is True
        assert ".5M" not in cleaned


# ── 复审 3：中文计量单位身份 + 斤换算 ─────────────────────────────────────


class TestChineseUnits:
    @pytest.mark.parametrize("text,key", [
        ("40 公斤", "40kg"), ("40公斤", "40kg"), ("40 千克", "40kg"),
        ("40 克", "40g"), ("40 吨", "40t"),
        ("40 毫米", "40mm"), ("40 厘米", "40cm"), ("40 米", "40m"),
        ("四十公斤", "40kg"),
    ])
    def test_cn_measure_maps_to_english_key(self, text, key):
        assert extract_mod_numbers(text) == {key}

    @pytest.mark.parametrize("text,key", [("40 斤", "20kg"), ("八十斤", "40kg")])
    def test_jin_is_half_a_kilogram(self, text, key):
        assert extract_mod_numbers(text) == {key}

    def test_cn_units_block_cross_dimension_backing(self):
        """库里的 40 pcs 不能给中文草稿的 公斤/毫米/克 背书。"""
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "报价", "excerpt": "每箱 40 pcs"}],
        )
        for draft in ("箱重 40 公斤", "长度 40 毫米", "含 40 克"):
            cleaned, changed = draft_mod.strip_unbacked_numbers(draft, ctx)
            assert changed is True, f"{draft!r} 被误判为有出处"

    def test_bare_number_does_not_back_cn_unit(self):
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "报价", "excerpt": "40"}],
        )
        cleaned, changed = draft_mod.strip_unbacked_numbers("含 40 克", ctx)
        assert changed is True, cleaned

    @pytest.mark.parametrize("library,draft", [
        ("40 kg", "40 公斤"), ("500 g", "500 克"), ("40 mm", "40 毫米"),
        ("40 kg", "40 千克"), ("40 kg", "80 斤"), ("80 斤", "40 kg"),
    ])
    def test_cn_and_english_units_match_each_other(self, library, draft):
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "规格书", "excerpt": library}],
        )
        cleaned, changed = draft_mod.strip_unbacked_numbers(draft, ctx)
        assert changed is False, cleaned

    def test_cn_count_units_stay_bare(self):
        ctx = CustomerContext(
            matched=True, customer_id=1, customer_name="Acme",
            product_entries=[{"label": "报价", "excerpt": "MOQ 500 pcs"}],
        )
        cleaned, changed = draft_mod.strip_unbacked_numbers("起订 500 个", ctx)
        assert changed is False, cleaned
