"""「查不到」不得被报成「没问题」—— OSINT 三处同源缺陷。

## 共同模式

三处都是「外部查询失败 → 代码把失败当成一种**肯定的结论**输出」：

1. **技术栈**（`tech_stack.py:47`）：`is_enterprise` 默认 `True`，抓取失败时
   只写 `error` 字段、不改这个值 → 报告输出绿色的
   「✅ 网站使用企业级技术栈，可信度 +1」。**域名被墙反而加分。**

2. **MX 查询**（`email_verify.py:141-146`）：dnspython 缺失与任何 DNS 异常
   都返回 `([], False)`，与「域名确实没有 MX 记录」不可区分 → 加红旗
   「域名未检测到 MX 记录（可能是假域名）」；orchestrator 又把它一律映射成
   `personal_email_domain`（名字也不对 —— 这不是个人邮箱），scoring 扣 30 分。
   一次 DNS 抖动，客户被判成「用个人邮箱的假域名」。

3. **WHOIS**（`whois.py:76`）：失败只写 `error`，报告里既不出现域名条目、
   也不提「查不到」→ 读者以为域名已核验通过。

对做尽调的销售来说，这三条都会让人**拿着错误结论去谈生意**，比崩溃更危险。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── 1. 技术栈 ────────────────────────────────────────────────────────────────


class TestTechStackFailureNotEnterprise:
    def test_fetch_failure_is_not_enterprise(self, monkeypatch):
        """抓取失败时不得保留 is_enterprise=True。"""
        import urllib.request

        import trade.osint.tech_stack as ts

        def _boom(*_a, **_k):
            raise OSError("connection timed out")

        monkeypatch.setattr(urllib.request, "urlopen", _boom)

        result = ts.detect_tech_stack("example.com")

        assert result["error"], "前置条件：失败应记录 error"
        assert result["is_enterprise"] is not True, (
            "抓取失败却仍标 is_enterprise=True → 报告会输出「✅ 企业级技术栈，可信度 +1」"
        )

    def test_scoring_does_not_praise_unreachable_site(self):
        """评分侧：有 error 时不得输出企业级加分。"""
        from trade.osint.scoring import generate_recommendations

        recs = generate_recommendations(
            {"layers": {"tech_stack": {"error": "connection timed out", "is_enterprise": False}}}
        )
        joined = "\n".join(recs)

        assert "企业级技术栈" not in joined, "网站都没抓到时不能夸它技术栈好"
        assert "无法访问" in joined or "未能验证" in joined, "应如实披露未验证"

    def test_healthy_enterprise_site_still_praised(self):
        """正常抓到企业级技术栈时，加分建议仍在（别把好路径改坏）。"""
        from trade.osint.scoring import generate_recommendations

        recs = generate_recommendations(
            {"layers": {"tech_stack": {"error": None, "is_enterprise": True, "platforms": []}}}
        )

        assert "企业级技术栈" in "\n".join(recs)


# ── 2. MX 查询 ───────────────────────────────────────────────────────────────


class TestMxFailureDistinctFromNoRecord:
    def test_query_error_is_reported(self, monkeypatch):
        """DNS 查询本身失败时，结果里要能看出是「查询失败」而非「没有记录」。"""
        import trade.osint.email_verify as ev

        monkeypatch.setattr(
            ev, "_query_mx_records_impl", lambda _d: (_ for _ in ()).throw(OSError("dns timeout")),
            raising=False,
        )

        out = ev.verify_corporate_email("buyer@acme-industrial.com")

        assert out.get("mx_error"), "DNS 查询失败必须显式记录，否则与「无 MX 记录」混淆"
        assert "未检测到 MX 记录" not in " ".join(out.get("risk_flags", [])), (
            "DNS 抖动不该被说成「可能是假域名」"
        )

    def test_genuine_no_mx_still_flagged(self, monkeypatch):
        """确实没有 MX 记录时，红旗照旧（这是真实的假域名信号）。"""
        import trade.osint.email_verify as ev

        monkeypatch.setattr(
            ev, "_query_mx_records_impl", lambda _d: ([], False, None), raising=False
        )

        out = ev.verify_corporate_email("buyer@acme-industrial.com")

        assert "未检测到 MX 记录" in " ".join(out.get("risk_flags", []))


class TestOrchestratorFlagNames:
    """红旗名要对应真实含义 —— 否则扣分理由与事实不符。"""

    def test_mx_flag_is_not_labelled_personal_email(self):
        from trade.osint.orchestrator import _map_email_flags

        flags = _map_email_flags(["域名未检测到 MX 记录（可能是假域名）"])

        assert "personal_email_domain" not in flags, (
            "「无 MX 记录」被标成 personal_email_domain —— 扣分理由与事实不符"
        )
        assert "no_mx_record" in flags

    def test_personal_email_flag_kept(self):
        from trade.osint.orchestrator import _map_email_flags

        assert "personal_email_domain" in _map_email_flags(["使用个人邮箱域名"])

    def test_new_flag_has_smaller_deduction(self):
        """「无 MX」的证据强度低于「个人邮箱」，扣分应更轻。"""
        from trade.osint.scoring import _deductions

        d = _deductions()
        assert d["no_mx_record"] > 0
        assert d["no_mx_record"] < d["personal_email_domain"]


# ── 3. WHOIS ─────────────────────────────────────────────────────────────────


class TestWhoisFailureDisclosed:
    def test_recommendations_disclose_whois_unavailable(self):
        """WHOIS 查不到时必须在建议里说出来，不能当作已核验。

        报告里这一层的键名是 ``domain_intel``（见 orchestrator 的 layers 结构）。
        """
        from trade.osint.scoring import generate_recommendations

        recs = generate_recommendations(
            {"layers": {"domain_intel": {"error": "WHOIS 服务器无响应", "registered": None}}}
        )
        joined = "\n".join(recs)

        assert "WHOIS" in joined or "域名信息" in joined, (
            "WHOIS 失败未在建议中披露 → 读者以为域名已核验"
        )
        assert "未核验" in joined or "不可用" in joined or "未能" in joined


# ── 4. holehe 邮箱注册检测层 ─────────────────────────────────────────────────


class TestEmailRegistrationLayerDisclosed:
    """holehe 没装时必须说出来 —— 否则报告静默少一整层。

    holehe 在 requirements / pyproject / 安装脚本里**全都没有声明**（代码内懒加载），
    所以全新安装的机器上这一层永远不执行：120+ 平台的注册检测直接消失，
    而用户看到的报告看起来是完整的。
    """

    def test_missing_holehe_is_disclosed(self):
        from trade.osint.scoring import generate_recommendations

        recs = generate_recommendations(
            {"layers": {"email_registration": {"error": "holehe not installed: no module named holehe"}}}
        )
        joined = "\n".join(recs)

        assert "未执行" in joined or "不可用" in joined or "未安装" in joined, (
            "holehe 缺失时报告一字不提 —— 用户以为 120+ 平台检测跑过了"
        )
        assert "⚠️" in joined, "应给出警示标记"

    def test_healthy_layer_does_not_warn(self):
        from trade.osint.scoring import generate_recommendations

        recs = generate_recommendations(
            {"layers": {"email_registration": {"email": "a@b.com", "registered_platforms": []}}}
        )
        joined = "\n".join(recs)

        assert "未执行" not in joined and "未安装" not in joined
