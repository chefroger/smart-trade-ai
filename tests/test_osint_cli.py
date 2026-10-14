"""`python -m trade.osint` / `trade osint` —— 6 层背调的命令行入口。

## 为什么有这个入口（2026-10-14）

skill 提示词原先写"调用 domain_whois(域名)"这类**裸函数名**，而它们不是 agent 的
工具，确定性管线 `osint_full_check()` 更是**全仓库无调用者** —— "6 层检测"在线上
从未按设计跑过。这个 CLI 把管线包成**确定的、跨平台可执行的命令**，提示词据此改写。

本文件钉三件事：
1. 报告渲染如实标注各层的未执行/降级/跳过（不许"看似查过、其实没查"）；
2. main 的参数处理与退出码；
3. **提示词指向这个命令**（而不是裸函数名）—— 防回退。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.osint import cli  # noqa: E402


def _sample_report() -> dict:
    """一份完整形态的报告（各层都给值，含一个降级层）。"""
    return {
        "target": "acme.com",
        "target_type": "domain",
        "overall_score": 72,
        "overall_rating": "medium",
        "flags": ["domain_age_new"],
        "layers": {
            "email_registration": None,
            "domain_intel": {
                "domain": "acme.com", "registered": True,
                "creation_date": "2026-01-02T00:00:00Z", "days_old": 30,
                "age_category": "new",
            },
            "email_verification": None,
            "tech_stack": {
                "technologies": ["Shopify"], "is_free_platform": True,
                "is_enterprise": False, "ssl_valid": True, "server": "nginx",
            },
            "sanctions": {
                "is_sanctioned": False, "risk_level": "none", "hits": [],
                "coverage": {"degraded": True, "total_entries": 2},
            },
            "linkedin": {"steps": [{"url": "https://www.linkedin.com/company/acme"}]},
        },
        "recommendations": ["建议人工复核"],
    }


class TestFormatReport:
    def test_renders_score_flags_and_layers(self):
        text = cli.format_report(_sample_report())
        assert "acme.com" in text and "72/100" in text
        assert "domain_age_new" in text
        assert "Shopify" in text                      # 技术栈层
        assert "linkedin.com/company/acme" in text     # LinkedIn 指令
        assert "建议人工复核" in text

    def test_degradation_is_stated_not_hidden(self):
        """制裁源降级必须如实标注 —— 这条是项目的诚实降级底线。"""
        text = cli.format_report(_sample_report())
        assert "降级" in text and "2 条内置样本" in text

    def test_unexecuted_layers_say_so(self):
        """没跑的层要写"未执行"，不能被静默省略成"看起来查过了"。"""
        text = cli.format_report(_sample_report())
        assert "邮箱注册检测：未执行" in text
        assert "企业邮箱验证：未执行" in text

    def test_skipped_whois_reason_is_shown(self):
        rep = _sample_report()
        rep["layers"]["domain_intel"] = {"skipped": True, "reason": "Company target — needs web search first"}
        text = cli.format_report(rep)
        assert "跳过" in text and "web search" in text


class TestMain:
    def test_no_target_prints_usage(self, capsys):
        assert cli.main([]) == 2
        assert "用法" in capsys.readouterr().out

    def test_two_targets_rejected(self, capsys):
        assert cli.main(["a.com", "b.com"]) == 2
        assert "一次只接受一个目标" in capsys.readouterr().out

    def test_json_output_is_valid_json(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "osint_full_check", lambda *a, **kw: _async(_sample_report()))
        assert cli.main(["acme.com", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["target"] == "acme.com"

    def test_pipeline_failure_returns_1(self, monkeypatch, capsys):
        async def _boom(*a, **kw):
            raise RuntimeError("管线炸了")

        monkeypatch.setattr(cli, "osint_full_check", _boom)
        assert cli.main(["acme.com"]) == 1
        assert "背调执行失败" in capsys.readouterr().out

    def test_flags_are_passed_through(self, monkeypatch):
        seen = {}

        async def _capture(target, **kw):
            seen.update(target=target, **kw)
            return _sample_report()

        monkeypatch.setattr(cli, "osint_full_check", _capture)
        cli.main(["acme.com", "--no-sanctions", "--no-linkedin"])
        assert seen["target"] == "acme.com"
        assert seen["include_sanctions"] is False
        assert seen["include_linkedin"] is False
        assert seen["include_tech_stack"] is True


def _async(value):
    """把同步返回值包成协程（main 里是 asyncio.run）。"""
    async def _coro():
        return value
    return _coro()


class TestConsoleSafety:
    def test_report_survives_undecodable_console(self, monkeypatch, capsys):
        """cp1252 管道里打印报告不能崩（Windows 英文机的真实场景）。

        `⚠/✗` 不在 cp1252/cp936 里 —— 没有 reconfigure 守卫时会崩在
        "已经查完之后"，agent 只看到 UnicodeEncodeError，白跑一次。
        """
        import io

        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        monkeypatch.setattr(sys, "stdout", stream)
        monkeypatch.setattr(cli, "osint_full_check", lambda *a, **kw: _async(_sample_report()))

        assert cli.main(["acme.com"]) == 0, "编码不兼容时命令崩了"


class TestDispatch:
    def test_osint_subcommand_dispatched(self, monkeypatch):
        """`trade osint <目标>` 要被 bootstrap 认出来并退出，不起服务。"""
        from trade import bootstrap

        monkeypatch.setattr(sys, "argv", ["trade", "osint", "acme.com"])
        ran = {}
        monkeypatch.setattr("trade.osint.cli.main", lambda argv: ran.setdefault("argv", argv) or 0)

        with pytest.raises(SystemExit):
            bootstrap.dispatch_subcommands()

        assert ran.get("argv") == ["acme.com"]


class TestPromptsPointAtTheCommand:
    """提示词必须给出**可执行的命令**，不能退回裸函数名（防回退）。

    背景：原先两份提示词都写"调用 domain_whois(域名)"——那些函数不是 agent 工具，
    管线也因此从未被真正触发过。
    """

    def _prompts(self) -> list[tuple[str, str]]:
        root = Path(__file__).resolve().parent.parent
        return [
            ("skills/b2b-osint/SKILL.md", (root / "skills/b2b-osint/SKILL.md").read_text(encoding="utf-8")),
            ("trade/skill_registry.py", (root / "trade/skill_registry.py").read_text(encoding="utf-8")),
        ]

    def test_prompts_use_the_cli_command(self):
        for name, text in self._prompts():
            assert "python -m trade.osint" in text, f"{name} 没有指向可执行的背调命令"

    def test_skill_injection_prompt_carries_the_command(self):
        """**注入版**（frontmatter 的 injection_prompt）也必须有命令。

        实测踩过：第一版只改到 SKILL.md 的**正文**，而每次进 system prompt 的是
        frontmatter 里的 injection_prompt —— 正文要模型主动 skill_view 才读到。
        两条路都得有，否则模型可能整轮都不知道该跑什么。
        """
        import yaml

        root = Path(__file__).resolve().parent.parent
        text = (root / "skills/b2b-osint/SKILL.md").read_text(encoding="utf-8")
        fm = yaml.safe_load(text.split("---", 2)[1])
        assert "python -m trade.osint" in (fm.get("injection_prompt") or ""), (
            "injection_prompt（注入进 system prompt 的那份）里没有背调命令"
        )

    def test_prompts_do_not_instruct_bare_function_calls(self):
        import re

        for name, text in self._prompts():
            hits = re.findall(r"调用 [a-z_][a-z_]*\(", text)
            assert not hits, f"{name} 仍让模型『调用』不存在的函数：{hits}"
