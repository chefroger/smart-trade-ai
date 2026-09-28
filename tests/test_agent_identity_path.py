"""
公司身份文件（agent-identity.md）的读写路径一致性测试。

背景：身份文件是「文件优先」提示词链的最高优先级来源（prompts.resolve 第 1 步），
但历史上三处路径两两不同：
  - prompts.py 读 ~/.trade/companies/{slug}/agent_identity.md（下划线，基准目录少一层）
  - onboarding.py 写 ~/.trade/{slug}/companies/{slug}/agent-identity.md
  - company/crud.py 读 ~/.trade/{slug}/agent-identity.md
结果读取方永远读不到写入方写的文件，整层「改文件即生效」是死的，
身份实际只靠 DB 的 agent_identity_md 兜底。

约定（以模板/工作目录为准）：~/.trade/{slug}/companies/{slug}/agent-identity.md
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def trade_home(tmp_path, monkeypatch):
    """把 prompts 的数据目录指向临时目录。"""
    monkeypatch.setattr("trade.prompts._get_trade_home", lambda: tmp_path)
    return tmp_path


class TestAgentIdentityPath:
    """身份文件路径必须与模板/工作目录布局一致。"""

    def test_path_matches_workdir_layout(self, trade_home):
        """解析出的路径必须落在 {data_dir}/companies/{slug}/agent-identity.md。"""
        from trade.prompts import _company_identity_path

        assert _company_identity_path("acme") == (
            trade_home / "acme" / "companies" / "acme" / "agent-identity.md"
        )

    def test_identity_file_readable_after_template_copy(self, trade_home):
        """模板复制出公司目录后，读取方应能读到模板里的 agent-identity.md。

        这是端到端断言：只要路径约定与 _ensure_data_dir 不一致，这里就会读不到内容。
        """
        from trade.company.workdir import _ensure_data_dir
        from trade.prompts import get_agent_identity_by_slug

        _ensure_data_dir("acme", trade_home)

        copied = trade_home / "acme" / "companies" / "acme" / "agent-identity.md"
        assert copied.is_file(), "模板中的身份文件应被复制到该公司目录下"

        content = get_agent_identity_by_slug("acme")
        assert content.strip(), (
            "读取方读不到模板里的身份文件 —— 说明它的路径约定与工作目录不一致"
        )
        assert content.strip() == copied.read_text(encoding="utf-8").strip()

    def test_write_then_read_roundtrip(self, trade_home):
        """write_agent_identity 写出的内容必须能被 get_agent_identity_by_slug 读回。"""
        from trade.prompts import get_agent_identity_by_slug, write_agent_identity

        write_agent_identity("acme", "# 我是 Acme 的助手\n只讲英语。")

        assert get_agent_identity_by_slug("acme").strip() == "# 我是 Acme 的助手\n只讲英语。"

    def test_identity_file_wins_over_db_in_resolution(self, trade_home):
        """文件优先链：文件存在时自定义层取文件内容，且追加在基础规则之后。"""
        from trade.prompts import resolve_system_prompt, write_agent_identity

        write_agent_identity("acme", "文件里的身份")

        resolved = resolve_system_prompt(company_slug="acme", db_identity="DB 里的身份")

        assert "文件里的身份" in resolved, "文件优先级最高，不应被 DB 值顶替"
        assert "DB 里的身份" not in resolved
        # 基础规则块必须同时存在（历史上身份会把它们整体顶替）
        assert "# Disclaimer" in resolved, "基础规则块必须常驻"


class TestLegacyIdentityPathCompatibility:
    """历史遗留路径的一次性兼容读取。

    统一路径之前，「读取方」曾指向 ~/.trade/companies/{slug}/agent_identity.md
    （下划线、少一层 companies/{slug}）。用户可能已经手动编辑过那个文件，
    直接弃用会让改动凭空消失 —— 所以保留一次性兼容读取，规范路径优先。
    """

    def test_legacy_file_is_read_when_canonical_missing(self, trade_home):
        """规范路径没有文件时，回退读历史遗留路径。"""
        from trade.prompts import get_agent_identity_by_slug

        legacy = trade_home / "companies" / "acme" / "agent_identity.md"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("遗留路径里的身份", encoding="utf-8")

        assert get_agent_identity_by_slug("acme").strip() == "遗留路径里的身份"

    def test_canonical_wins_over_legacy(self, trade_home):
        """两处都存在时以规范路径为准。"""
        from trade.prompts import get_agent_identity_by_slug, write_agent_identity

        write_agent_identity("acme", "规范路径里的身份")
        legacy = trade_home / "companies" / "acme" / "agent_identity.md"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("遗留路径里的身份", encoding="utf-8")

        assert get_agent_identity_by_slug("acme").strip() == "规范路径里的身份"

    def test_no_file_anywhere_returns_empty(self, trade_home):
        """两处都没有时返回空串，由调用方兜底。"""
        from trade.prompts import get_agent_identity_by_slug

        assert get_agent_identity_by_slug("acme") == ""


class TestCrudIdentityReaderFileFallback:
    """第二个读取方 company/crud.get_agent_identity 的文件回退必须用同一路径。

    它被 api/companies.py 与 helpers.py 调用（helpers 拿它当 resolve 的 db_identity 入参），
    历史实现读 {data_dir}/agent-identity.md（少一层 companies/{slug}），文件回退永远命中不了。
    """

    def test_file_fallback_reads_canonical_path(self, tmp_path, monkeypatch):
        """DB 字段为空时应能读回规范路径下的身份文件。"""
        import trade.company as co
        from trade.company import crud

        # create() 会创建真实桌面工作目录，必须重定向到临时目录。
        # 注意 create() 里是函数内 `from trade.company.workdir import _setup_work_directory`，
        # 所以 patch 源模块而不是 crud 命名空间。
        def _mock_setup(cname, slug, suggested_name=""):
            wd = tmp_path / "workdir" / (suggested_name or cname)
            wd.mkdir(parents=True, exist_ok=True)
            for cat_name, _ in co._WORK_DIR_CATEGORIES:
                (wd / cat_name).mkdir(parents=True, exist_ok=True)
            return wd, True

        monkeypatch.setattr("trade.company.workdir._setup_work_directory", _mock_setup)

        # 建表（TRADE_HOME 已由 conftest 指向临时目录，不碰真实数据）
        from trade.database import init_db
        init_db()

        company = crud.create(name="Acme Identity Co", slug="acme-identity")
        cid = company["id"]
        slug = company["slug"]

        # 清空 DB 身份字段，逼它走文件回退
        crud.update_trade_company(cid, agent_identity_md="")

        # 在规范位置（模板/工作目录布局）写文件
        identity_file = crud.TRADE_HOME / slug / "companies" / slug / "agent-identity.md"
        identity_file.parent.mkdir(parents=True, exist_ok=True)
        identity_file.write_text("文件里的身份", encoding="utf-8")

        assert crud.get_agent_identity(cid).strip() == "文件里的身份", (
            "文件回退读的路径与工作目录布局不一致，用户手动编辑的文件永远读不到"
        )
