"""邮件情报模块测试 — 覆盖邮箱校验、站点显示名、用户名提取、结果格式化。

仅测试纯函数（不依赖 holehe 库），确保合规风险点（制裁/邮箱验证）
的格式化逻辑正确。
"""

from __future__ import annotations


class TestEmailValidation:
    def test_valid_email(self):
        from trade.email_intel import _is_valid_email
        assert _is_valid_email("user@example.com")
        assert _is_valid_email("a@b.co")

    def test_invalid_email(self):
        from trade.email_intel import _is_valid_email
        assert not _is_valid_email("not-an-email")
        assert not _is_valid_email("user@")
        assert not _is_valid_email("@example.com")
        assert not _is_valid_email("user example.com")
        assert not _is_valid_email("")

    def test_email_with_whitespace(self):
        from trade.email_intel import _is_valid_email
        assert _is_valid_email("  user@example.com  ")


class TestDisplayName:
    def test_known_domain(self):
        from trade.email_intel import _display_name
        assert _display_name("twitter.com") == "Twitter / X"
        assert _display_name("linkedin.com") == "LinkedIn"

    def test_unknown_domain(self):
        from trade.email_intel import _display_name
        # 未知域名回退到首段首字母大写
        assert _display_name("example.com") == "Example"


class TestExtractUsername:
    def test_username_key(self):
        from trade.email_intel import _extract_username
        assert _extract_username("twitter.com", {"username": "john"}) == "john"

    def test_user_key(self):
        from trade.email_intel import _extract_username
        assert _extract_username("twitter.com", {"user": "jane"}) == "jane"

    def test_none_value_ignored(self):
        from trade.email_intel import _extract_username
        # "none" / "null" 应被排除
        assert _extract_username("twitter.com", {"username": "none"}) is None
        assert _extract_username("twitter.com", {"username": "null"}) is None

    def test_empty_others(self):
        from trade.email_intel import _extract_username
        assert _extract_username("twitter.com", None) is None
        assert _extract_username("twitter.com", {}) is None


class TestFormatResult:
    def test_basic_format(self):
        from trade.email_intel import _format_result
        raw = {"name": "twitter.com", "exists": True, "others": {"username": "john"}}
        r = _format_result(raw)
        assert r["site"] == "twitter.com"
        assert r["exists"] is True
        assert r["profile_url"] == "https://twitter.com/john"
        assert r["site_display"] == "Twitter / X"

    def test_no_username(self):
        from trade.email_intel import _format_result
        raw = {"name": "example.com", "exists": False}
        r = _format_result(raw)
        assert r["exists"] is False
        assert r["profile_url"] is None
        assert r["site_display"] == "Example"


class TestErrorResult:
    def test_error_result_structure(self):
        from trade.email_intel import _error_result
        r = _error_result("user@example.com", "holehe not installed")
        assert r["email"] == "user@example.com"
        assert r["error"] == "holehe not installed"
        assert r["checked_count"] == 0
        assert r["results"] == []


class TestSocialSummary:
    def test_social_only(self):
        from trade.email_intel import _build_social_summary
        found = [
            {"site": "twitter.com", "profile_url": "https://twitter.com/john"},
            {"site": "example.com", "profile_url": None},  # 非社交站点，应被忽略
        ]
        summary = _build_social_summary(found)
        # _display_name("twitter.com") = "Twitter / X" → 键为 "twitter___x"
        assert "twitter___x" in summary
        assert summary["twitter___x"] == "https://twitter.com/john"

    def test_empty(self):
        from trade.email_intel import _build_social_summary
        assert _build_social_summary([]) == {}
