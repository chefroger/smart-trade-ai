"""`trade company` —— 作者用的公司清理命令。

## 为什么需要它

错误安装（如被国产 AI 助手代装）常见的后果是**留下几个用不上的公司**。
界面上的「删除」只做**软删除**：公司从列表消失，但

  - 桌面上的公司文件夹还在（正是用户说的"后续很难处理"）
  - `~/.trade/{slug}/` 还在
  - 数据库行还在（is_active=0）

`crud.purge()` 能物理删干净，但**全项目没有任何入口调用它**。
这个模块就是那个入口，且**刻意不做进 UI** —— 不可逆操作不该有按钮。

## 安全约定（本文件钉住的）

  - 不带 `--yes` 只打印计划、退出码 1，绝不动手（远程 shell 里交互确认不可靠）
  - 只删 TRADE_HOME 下与桌面下的目录，别处一律跳过并如实告知
  - `purge-dir` 只处理带 Trade 目录指纹的文件夹，不做通用删除工具
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import company_admin


@pytest.fixture
def env(monkeypatch, tmp_path):
    """临时库 + 临时「桌面」，建一家公司并真的落出目录结构。"""
    monkeypatch.setenv("TRADE_HOME", str(tmp_path / "trade"))
    desktop = tmp_path / "Desktop"
    desktop.mkdir()

    import trade.database as _db

    monkeypatch.setattr(_db, "_get_db_path", lambda: tmp_path / "trade.db")
    from trade.database import init_db

    init_db()

    import trade.company as co

    def _setup(name, slug, suggested_name=""):
        wd = desktop / (suggested_name or name)
        wd.mkdir(parents=True, exist_ok=True)
        for cat, _ in co._WORK_DIR_CATEGORIES:
            (wd / cat).mkdir(parents=True, exist_ok=True)
        return wd, True

    # 必须打在 **workdir 模块**上：crud.create() 是
    # `from trade.company.workdir import _setup_work_directory`，在模块上查这个名字；
    # 打在包级 re-export（trade.company._setup_work_directory）不会生效 ——
    # 那样真实函数会跑，建出的是不含分类子目录的空壳，测试就在错误的现场上断言。
    monkeypatch.setattr(co.workdir, "_setup_work_directory", _setup)
    monkeypatch.setattr(co.workdir, "_get_desktop_path", lambda: desktop)

    company = co.create(name="错误公司", slug="wrong-co")
    return {"company": company, "desktop": desktop, "tmp": tmp_path}


class TestList:
    def test_lists_company_with_dirs(self, env):
        out = company_admin.list_companies()

        assert "错误公司" in out
        assert "wrong-co" in out
        assert "启用" in out

    def test_lists_soft_deleted_companies_too(self, env):
        """软删除的必须也列出来 —— 否则用户以为已经删干净了。"""
        from trade.company import crud

        crud.delete(env["company"]["id"])

        out = company_admin.list_companies()

        assert "错误公司" in out, "软删除后从 list 里消失了，用户就看不到残留"
        assert "已软删除" in out

    def test_reports_missing_dir(self, env):
        import shutil

        shutil.rmtree(env["desktop"] / "错误公司")

        out = company_admin.list_companies()

        assert "不存在" in out


class TestPurgeRequiresConfirmation:
    def test_without_yes_only_previews(self, env):
        """不带 --yes 只打印计划、退出码 1，什么都不删。"""
        text, code = company_admin.purge_company("wrong-co")

        assert code == 1
        assert "--yes" in text, "要告诉用户怎么真正执行"
        # 数据库与目录都必须原封不动
        from trade.company import crud

        assert crud.get(env["company"]["id"]) is not None
        assert (env["desktop"] / "错误公司").is_dir()

    def test_preview_shows_what_will_be_deleted(self, env):
        text, _ = company_admin.purge_company("wrong-co")

        assert "错误公司" in text
        assert "桌面目录" in text
        assert "数据目录" in text

    def test_preview_counts_user_files(self, env):
        """目录里有几个文件要如实报 —— 用户据此判断是否真有资料在里面。"""
        (env["desktop"] / "错误公司" / "合同" / "客户合同.txt").write_text("x", encoding="utf-8")

        text, _ = company_admin.purge_company("wrong-co")

        assert "个文件" in text


class TestPurgeExecutes:
    def test_purges_db_and_both_dirs(self, env):
        """--yes 之后：数据库行、数据目录（~/.trade/{slug}/）、桌面目录都要真没了。"""
        cid = env["company"]["id"]
        # 数据目录是 TRADE_HOME/{slug}。TRADE_HOME 是 crud 模块**导入时**定下的常量
        # （conftest 设的临时目录），不是夹具里 monkeypatch 的那个 env —— 必须从
        # 常量取值，否则会去错地方找。
        from trade.company.crud import TRADE_HOME

        data_dir = TRADE_HOME / "wrong-co"
        assert data_dir.is_dir(), f"前置条件：数据目录应先存在（{data_dir}）"
        text, code = company_admin.purge_company("wrong-co", yes=True, password=company_admin._PURGE_PASSWORD)

        assert code == 0, text
        from trade.company import crud

        assert crud.get(cid) is None, "数据库行没删掉"
        assert not (env["desktop"] / "错误公司").exists(), "桌面文件夹没删掉 —— 这正是用户抱怨的残留"
        assert not data_dir.exists(), "数据目录没删掉"

    def test_purge_by_numeric_id(self, env):
        cid = env["company"]["id"]

        text, code = company_admin.purge_company(str(cid), yes=True, password=company_admin._PURGE_PASSWORD)

        assert code == 0
        from trade.company import crud

        assert crud.get(cid) is None

    def test_unknown_target_is_reported(self, env):
        text, code = company_admin.purge_company("no-such-company", yes=True, password=company_admin._PURGE_PASSWORD)

        assert code == 1
        assert "找不到" in text

    def test_reports_verified_deletion(self, env):
        """删完要复核并说出来，不能只说"已执行"。"""
        text, code = company_admin.purge_company("wrong-co", yes=True, password=company_admin._PURGE_PASSWORD)

        assert "已删除" in text


class TestDirGuard:
    def test_refuses_dir_outside_protected_roots(self, env, tmp_path):
        """工作目录若在保护区外（用户搬走了），不能删，且要如实告知。"""
        from trade.company import crud

        outside = tmp_path / "elsewhere" / "错误公司"
        (outside / "合同").mkdir(parents=True)
        crud.update_trade_company(
            env["company"]["id"], extra1=json.dumps({"work_dir": str(outside)})
        )

        text, code = company_admin.purge_company("wrong-co", yes=True, password=company_admin._PURGE_PASSWORD)

        assert code == 0
        assert "保护范围" in text, "要说明这个目录没被删"
        assert outside.is_dir(), "保护区外的目录被删了 —— 护栏失效"


class TestOrphanWorkDirs:
    """错误安装最典型的残留：桌面上有文件夹，数据库里没有记录。"""

    def test_detects_orphan_folder(self, env):
        orphan = env["desktop"] / "孤儿公司"
        for cat, _ in __import__("trade.company.workdir", fromlist=["x"])._WORK_DIR_CATEGORIES:
            (orphan / cat).mkdir(parents=True)

        found = company_admin.find_orphan_work_dirs()

        assert orphan in found

    def test_does_not_flag_known_company(self, env):
        """数据库里有记录的不算孤儿。"""
        found = company_admin.find_orphan_work_dirs()

        assert env["desktop"] / "错误公司" not in found

    def test_ignores_unrelated_desktop_dirs(self, env):
        (env["desktop"] / "我的照片").mkdir()
        (env["desktop"] / "随便一个文件夹").mkdir()

        assert company_admin.find_orphan_work_dirs() == []

    def test_list_surfaces_orphans(self, env):
        orphan = env["desktop"] / "孤儿公司"
        for cat, _ in __import__("trade.company.workdir", fromlist=["x"])._WORK_DIR_CATEGORIES:
            (orphan / cat).mkdir(parents=True)

        out = company_admin.list_companies()

        assert "孤儿公司" in out
        assert "purge-dir" in out, "要告诉用户怎么清它"


class TestPurgeDir:
    def _make_orphan(self, env, name="孤儿公司"):
        orphan = env["desktop"] / name
        for cat, _ in __import__("trade.company.workdir", fromlist=["x"])._WORK_DIR_CATEGORIES:
            (orphan / cat).mkdir(parents=True)
        return orphan

    def test_requires_yes(self, env):
        orphan = self._make_orphan(env)

        text, code = company_admin.purge_dir(str(orphan))

        assert code == 1
        assert orphan.is_dir(), "不带 --yes 就删了"

    def test_deletes_orphan(self, env):
        orphan = self._make_orphan(env)

        text, code = company_admin.purge_dir(str(orphan), yes=True, password=company_admin._PURGE_PASSWORD)

        assert code == 0
        assert not orphan.exists()

    def test_refuses_arbitrary_directory(self, env, tmp_path):
        """不能变成通用删除工具 —— 只处理带 Trade 目录指纹的文件夹。"""
        plain = tmp_path / "重要资料"
        plain.mkdir()
        (plain / "报价单.xlsx").write_text("x", encoding="utf-8")

        text, code = company_admin.purge_dir(str(plain), yes=True, password=company_admin._PURGE_PASSWORD)

        assert code == 1
        assert plain.is_dir(), "普通目录被删了 —— 这条命令太危险"

    def test_refuses_dir_outside_desktop(self, env, tmp_path):
        outside = tmp_path / "other" / "像公司的目录"
        for cat, _ in __import__("trade.company.workdir", fromlist=["x"])._WORK_DIR_CATEGORIES:
            (outside / cat).mkdir(parents=True)

        text, code = company_admin.purge_dir(str(outside), yes=True, password=company_admin._PURGE_PASSWORD)

        assert code == 1
        assert outside.is_dir()


class TestDispatch:
    def test_company_subcommand_dispatched(self, monkeypatch, env):
        """`trade company list` 要被 bootstrap 认出来并退出，不起服务。"""
        from trade import bootstrap

        monkeypatch.setattr(sys, "argv", ["trade", "company", "list"])
        ran = {}
        monkeypatch.setattr(
            "trade.company_admin.main", lambda argv: ran.setdefault("argv", argv) or 0
        )

        with pytest.raises(SystemExit):
            bootstrap.dispatch_subcommands()

        assert ran.get("argv") == ["list"]

    def test_unknown_subcommand_does_not_dispatch(self, monkeypatch):
        from trade import bootstrap

        monkeypatch.setattr(sys, "argv", ["trade", "--no-browser"])

        assert bootstrap.dispatch_subcommands() is False


class TestOrphanMustNotFlagLiveCompanies:
    """**真机跑出来的误报**：早期创建的公司 `extra1` 是空的（没记录 work_dir），
    但桌面文件夹真实存在且在**使用中**。

    实测现场（本机）：
        company_id=4 「万花筒」  extra1 = {}
        ~/Desktop/万花筒/        9 个分类目录齐全

    旧判定只看「记录的 work_dir」，于是把在用公司的文件夹判成孤儿 ——
    而 `purge-dir` 会把它删掉。**删掉在用公司的真实文件**是这条命令最坏的结果，
    所以：按名字/slug 也匹配一次，匹配上就不算孤儿。
    """

    def _make_trade_dir(self, parent, name):
        d = parent / name
        for cat, _ in __import__("trade.company.workdir", fromlist=["x"])._WORK_DIR_CATEGORIES:
            (d / cat).mkdir(parents=True)
        return d

    def test_folder_matching_live_company_name_is_not_orphan(self, env, monkeypatch):
        """公司 A 有桌面文件夹、但 extra1 为空（老数据）→ 不是孤儿。"""
        from trade.company import crud

        # 模拟老数据：清掉 work_dir 记录（公司本身仍在用）
        crud.update_trade_company(env["company"]["id"], extra1="{}")
        # 清掉记录后重建同名文件夹（模拟现场）
        import shutil

        shutil.rmtree(env["desktop"] / "错误公司")
        self._make_trade_dir(env["desktop"], "错误公司")

        found = company_admin.find_orphan_work_dirs()

        assert (env["desktop"] / "错误公司") not in found, (
            "在用公司的桌面文件夹被判成孤儿 —— purge-dir 会删掉它的真实文件"
        )

    def test_folder_matching_slug_is_not_orphan(self, env):
        from trade.company import crud

        crud.update_trade_company(env["company"]["id"], extra1="{}")
        import shutil

        shutil.rmtree(env["desktop"] / "错误公司")
        d = self._make_trade_dir(env["desktop"], "wrong-co")

        found = company_admin.find_orphan_work_dirs()

        assert d not in found

    def test_truly_orphan_folder_still_detected(self, env):
        """没有任何公司叫这个名字、也没记录过路径 → 仍是孤儿。"""
        d = self._make_trade_dir(env["desktop"], "谁都不是的公司")

        found = company_admin.find_orphan_work_dirs()

        assert d in found


class TestPurgeDirRefusesLiveCompanyFolder:
    """即便用户手动指定，也不该删在用公司的文件夹。"""

    def test_refuses_folder_matching_live_company(self, env):
        text, code = company_admin.purge_dir(
            str(env["desktop"] / "错误公司"), yes=True
        )

        assert code == 1, "删掉了在用公司的桌面文件夹"
        assert (env["desktop"] / "错误公司").is_dir()
        assert "purge" in text, "要告诉用户先删公司（trade company purge）"


class TestPurgeFindsUnrecordedWorkDir:
    """**真机发现的缺口**：老数据没记 work_dir，purge 会把桌面文件夹留在原地。

    实测现场：company_id=4「万花筒」`extra1={}`，`~/Desktop/万花筒/` 真实存在。
    `crud.purge()` 只删它从 extra1 读到的路径 —— 读不到就什么都不删，
    于是 purge 完桌面上仍留着那个文件夹（正是用户抱怨的残留）。
    """

    def test_preview_includes_name_matched_dir(self, env):
        from trade.company import crud

        # 模拟老数据：清掉 work_dir 记录，文件夹仍在
        crud.update_trade_company(env["company"]["id"], extra1="{}")

        text, _ = company_admin.purge_company("wrong-co")

        assert "桌面目录" in text, "没把桌面文件夹列进计划 —— 用户以为删干净了"
        assert "按公司名找到" in text, "要说明这个路径是回找来的，不是记录里的"

    def test_purge_actually_deletes_name_matched_dir(self, env):
        from trade.company import crud

        crud.update_trade_company(env["company"]["id"], extra1="{}")
        desktop_dir = env["desktop"] / "错误公司"
        assert desktop_dir.is_dir(), "前置条件：桌面文件夹存在"

        text, code = company_admin.purge_company("wrong-co", yes=True, password=company_admin._PURGE_PASSWORD)

        assert code == 0, text
        assert not desktop_dir.exists(), (
            "purge 完桌面文件夹还在 —— crud.purge() 读不到 work_dir 就不会删它"
        )

    def test_does_not_match_unrelated_same_name_dir(self, env, tmp_path):
        """同名但没有 Trade 目录结构 → 不是它的工作目录，不能删。"""
        from trade.company import crud

        crud.update_trade_company(env["company"]["id"], extra1="{}")
        import shutil

        shutil.rmtree(env["desktop"] / "错误公司")
        plain = env["desktop"] / "错误公司"  # 同名但只是普通文件夹
        plain.mkdir()
        (plain / "我的笔记.txt").write_text("x", encoding="utf-8")

        text, _ = company_admin.purge_company("wrong-co")

        assert "我的笔记" not in text, "把同名普通文件夹当成了工作目录"

    def test_purge_keeps_unrelated_same_name_dir(self, env):
        """确实删公司时，同名普通文件夹不能跟着消失。"""
        from trade.company import crud

        crud.update_trade_company(env["company"]["id"], extra1="{}")
        import shutil

        shutil.rmtree(env["desktop"] / "错误公司")
        plain = env["desktop"] / "错误公司"
        plain.mkdir()
        (plain / "我的笔记.txt").write_text("x", encoding="utf-8")

        company_admin.purge_company("wrong-co", yes=True, password=company_admin._PURGE_PASSWORD)

        assert (plain / "我的笔记.txt").is_file(), "误删了同名的普通文件夹"


class TestPurgePasswordGate:
    """删除前必须输入口令（防误操作；客户机常被远程操作，误删不可恢复）。

    定位说明：代码是公开的，口令自然也公开 —— 这是**防误操作**而不是防攻击，
    与许可证私钥同一性质，作者已知情。
    """

    PW = company_admin._PURGE_PASSWORD

    def test_correct_password_deletes(self, env):
        text, code = company_admin.purge_company("wrong-co", yes=True, password=self.PW)

        assert code == 0, text
        from trade.company import crud

        assert crud.get(env["company"]["id"]) is None

    def test_wrong_password_deletes_nothing(self, env):
        """口令错了必须什么都不删 —— 数据库、数据目录、桌面目录全都原封不动。"""
        from trade.company.crud import TRADE_HOME

        data_dir = TRADE_HOME / "wrong-co"
        text, code = company_admin.purge_company("wrong-co", yes=True, password="猜的")

        assert code == 1
        assert "口令错误" in text
        from trade.company import crud

        assert crud.get(env["company"]["id"]) is not None, "口令错误却删了数据库行"
        assert data_dir.is_dir(), "口令错误却删了数据目录"
        assert (env["desktop"] / "错误公司").is_dir(), "口令错误却删了桌面目录"

    def test_no_password_without_tty_refuses_with_hint(self, env, monkeypatch):
        """非交互环境没给口令 → 明确拒绝并告知怎么传，不能卡住等输入。"""
        import io
        import sys as _sys

        monkeypatch.setattr(_sys, "stdin", io.StringIO(""))  # isatty() 为 False

        text, code = company_admin.purge_company("wrong-co", yes=True, password=None)

        assert code == 1
        assert "--password" in text, "要告诉用户怎么把口令传进来"
        from trade.company import crud

        assert crud.get(env["company"]["id"]) is not None

    def test_preview_shown_before_asking_password(self, env, monkeypatch):
        """先看到「将要删什么」，再输口令 —— 顺序反了等于盲签。"""
        import io
        import sys as _sys

        monkeypatch.setattr(_sys, "stdin", io.StringIO(""))

        text, _ = company_admin.purge_company("wrong-co", yes=True, password=None)

        assert "将要删除" in text, "预览没了"
        assert text.index("将要删除") < text.index("口令"), "口令闸门在预览之前"

    def test_preview_mode_needs_no_password(self, env):
        """只看预览不需要口令（--yes 才过闸门）。"""
        text, code = company_admin.purge_company("wrong-co")

        assert code == 1
        assert "将要删除" in text
        assert "口令错误" not in text

    def test_list_needs_no_password(self, env):
        """列表是只读诊断，不加口令 —— 否则自己排查时反而麻烦。"""
        out = company_admin.list_companies()

        assert "错误公司" in out


class TestPurgeDirPasswordGate:
    def _make_orphan(self, env, name="孤儿公司"):
        d = env["desktop"] / name
        for cat, _ in __import__("trade.company.workdir", fromlist=["x"])._WORK_DIR_CATEGORIES:
            (d / cat).mkdir(parents=True)
        return d

    def test_wrong_password_keeps_dir(self, env):
        orphan = self._make_orphan(env)

        text, code = company_admin.purge_dir(str(orphan), yes=True, password="猜的")

        assert code == 1
        assert orphan.is_dir()

    def test_correct_password_deletes_dir(self, env):
        orphan = self._make_orphan(env)

        text, code = company_admin.purge_dir(
            str(orphan), yes=True, password=company_admin._PURGE_PASSWORD
        )

        assert code == 0
        assert not orphan.exists()

    def test_no_password_without_tty_refuses(self, env, monkeypatch):
        import io
        import sys as _sys

        monkeypatch.setattr(_sys, "stdin", io.StringIO(""))
        orphan = self._make_orphan(env)

        text, code = company_admin.purge_dir(str(orphan), yes=True, password=None)

        assert code == 1
        assert orphan.is_dir()


class TestFlagParsing:
    def test_parses_yes_and_password(self):
        yes, pw = company_admin._parse_flags(["--yes", "--password", "abc"])

        assert yes is True and pw == "abc"

    def test_password_absent_is_none(self):
        yes, pw = company_admin._parse_flags(["--yes"])

        assert yes is True and pw is None

    def test_password_flag_without_value_is_none(self):
        """`--password` 后面没跟值 → 当作没提供，走交互/拒绝分支，不能崩。"""
        _yes, pw = company_admin._parse_flags(["--yes", "--password"])

        assert pw is None


class TestOrphanPurgeLeavesAuditTrail:
    """删残留目录要留痕，且**不能**把"凭据"写进马上要删的目录里。

    第一版实现往被删目录里写了 `_删除前请确认.txt` 当凭据 —— 那个文件会随
    rmtree 一起消失，等于什么都没留下（代码看着在做事，实际没有）。
    改为写进项目已有的审计日志（crud.purge 也是先写审计再动手）。
    """

    def _make_orphan(self, env, name="孤儿公司"):
        d = env["desktop"] / name
        for cat, _ in __import__("trade.company.workdir", fromlist=["x"])._WORK_DIR_CATEGORIES:
            (d / cat).mkdir(parents=True)
        (d / "合同" / "某合同.txt").write_text("x", encoding="utf-8")
        return d

    def test_writes_audit_entry(self, env):
        orphan = self._make_orphan(env)

        company_admin.purge_dir(
            str(orphan), yes=True, password=company_admin._PURGE_PASSWORD
        )

        from trade.company.crud import _audit_dir

        files = list(_audit_dir().glob("*.jsonl"))
        assert files, "删了东西却没写审计日志"
        content = files[0].read_text(encoding="utf-8")
        assert "purge_orphan_dir" in content
        assert "孤儿公司" in content, "审计里要记下删的是哪个目录"
        assert "1 个文件" in content, "审计里要记下影响面"

    def test_does_not_rely_on_file_inside_deleted_dir(self, env):
        """删完目录里不能还需要有文件残留 —— 那种"凭据"必然随目录一起消失。"""
        orphan = self._make_orphan(env)

        company_admin.purge_dir(
            str(orphan), yes=True, password=company_admin._PURGE_PASSWORD
        )

        assert not orphan.exists()
        # 若实现靠"目录内的凭据文件"，这里就是它消失的证据 —— 审计必须写在目录之外
        from trade.company.crud import _audit_dir

        assert any(_audit_dir().glob("*.jsonl")), "痕迹必须落在被删目录之外"


class TestWindowsPathCaseInsensitivity:
    """Windows 路径不区分大小写，而**字符串比较区分**。

    这是 Windows 上最危险的一处差异：记录里的大小写与实际解析出的不一致时，
    同一个目录会被判成"不在已知集合里" → 在用公司的桌面文件夹被当成残留 →
    `purge-dir` 把它删掉。

    在 macOS 上测不了真实 Windows 行为，所以把 `os.path.normcase` 换成
    Windows 的语义（转小写）来模拟 —— `ntpath.normcase` 就是这么做的。
    """

    def _simulate_windows(self, monkeypatch):
        monkeypatch.setattr(company_admin.os.path, "normcase", lambda s: s.lower())

    def _live_company_with_odd_dir_name(self, env):
        """建一家公司，其桌面目录名与**公司名/slug 都不相符**。

        为什么必须这样构造：`_known_company_paths_and_names()` 有**两路**保护 ——
        记录路径、以及公司名/slug（后者是为老数据兜底的，见 §孤儿判定）。
        如果目录名恰好等于公司名，那么即使路径比较失效，名字那一路也会把它救下来，
        测试就**测不到** `_path_key` 的修复（我第一版就是这么写的，mutation 检验
        时两处集成测试都没变红，才发现是空转的）。

        目录名与名字脱钩后，唯一能救它的只剩记录路径这一路。
        """
        from trade.company import crud

        company = crud.create(name="甲", slug="jia", work_dir_name="acme-co-b")
        desktop_dir = env["desktop"] / "acme-co-b"

        # 先确认构造有效：名字这一路确实救不了它（否则测试又是空转）
        _, known_names = company_admin._known_company_paths_and_names()
        assert desktop_dir.name.lower() not in known_names, "目录名不该撞上公司名/slug"

        return company, desktop_dir

    def test_case_differing_record_is_not_orphan(self, env, monkeypatch):
        """记录里是大写路径、实际是小写（或反之）→ 同一目录，不算孤儿。"""
        from trade.company import crud

        company, desktop_dir = self._live_company_with_odd_dir_name(env)
        # 模拟记录里存的是另一种大小写的路径
        crud.update_trade_company(
            company["id"],
            extra1=json.dumps({"work_dir": str(desktop_dir).upper()}),
        )
        self._simulate_windows(monkeypatch)

        found = company_admin.find_orphan_work_dirs()

        assert desktop_dir not in found, (
            "大小写不同就判成孤儿 —— Windows 上会把在用公司的文件夹当残留"
        )

    def test_purge_dir_refuses_case_differing_live_folder(self, env, monkeypatch):
        """purge-dir 也必须认得出「大小写不同但同一个目录」。"""
        from trade.company import crud

        company, desktop_dir = self._live_company_with_odd_dir_name(env)
        crud.update_trade_company(
            company["id"],
            extra1=json.dumps({"work_dir": str(desktop_dir).upper()}),
        )
        self._simulate_windows(monkeypatch)

        text, code = company_admin.purge_dir(
            str(desktop_dir), yes=True, password=company_admin._PURGE_PASSWORD
        )

        assert code == 1, "大小写不同就放行删除 —— 会删掉在用公司的真实文件"
        assert desktop_dir.is_dir()

    def test_path_key_normalizes_case(self, monkeypatch):
        self._simulate_windows(monkeypatch)

        assert company_admin._path_key("/tmp/Acme") == company_admin._path_key("/tmp/acme")

    def test_path_key_never_raises_on_odd_input(self):
        """路径解析失败（过长/权限）时退回原串，不能让判断崩掉。"""
        assert isinstance(company_admin._path_key("C:\\不存在的\\很长\\路径" * 20), str)

    def test_path_key_never_raises_on_symlink_loop(self, tmp_path):
        """符号链接成环时 `resolve()` 会抛错（3.12 及以前是 RuntimeError，之后是
        OSError）—— 输入来自数据库的 `extra1.work_dir`，属外部数据，不能假定可解析。

        3.13 上 resolve 抛 OSError（已被 OSError 分支接住），此用例在
        3.11/3.12 才有区分度 —— 那两版正是 CI 覆盖的版本。
        """
        (tmp_path / "a").symlink_to(tmp_path / "b")
        (tmp_path / "b").symlink_to(tmp_path / "a")

        assert isinstance(company_admin._path_key(tmp_path / "a"), str)


class TestWindowsRobustness:
    """Windows 特有的三个失败模式（都在真机上会真的发生）。

    1. 管道/重定向输出时 stdout 用本地代码页，`✓ ✗ ⚠` 不在 cp936/cp1252 里
       → `print` 抛 UnicodeEncodeError，删除已发生却崩在报告上
    2. 只读文件让 `shutil.rmtree` 直接 WinError 5
    3. 杀毒/资源管理器短暂锁文件（WinError 32），稍等即消失
    """

    def _orphan_dir(self, env) -> Path:
        """造一个带 Trade 指纹的孤儿目录（数据库里没有的公司）。"""
        from trade.company.workdir import _WORK_DIR_CATEGORIES

        d = env["desktop"] / "残留公司"
        d.mkdir()
        for cat, _ in _WORK_DIR_CATEGORIES:
            (d / cat).mkdir()
        return d

    def test_reports_survive_undecodable_console(self, env, monkeypatch):
        """cp1252 管道里打印报告不能崩（真实 Windows 英文机场景）。"""
        import io

        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        monkeypatch.setattr(company_admin.sys, "stdout", stream)

        code = company_admin.main(["list"])

        assert code == 0, "编码不兼容时 list 崩了 —— 报告要能打出来"

    def test_readonly_files_do_not_block_deletion(self, env, monkeypatch):
        """只读文件：第一次 rmtree 失败，清掉只读位后重试成功。"""
        import shutil as _shutil
        import stat as _stat

        d = self._orphan_dir(env)
        ro = d / "报价单" / "只读文件.txt"
        ro.write_text("x", encoding="utf-8")
        ro.chmod(_stat.S_IREAD)

        real_rmtree = _shutil.rmtree

        def fake_rmtree(p, *a, **kw):
            # 模拟 Windows：只要树上还有只读文件就 WinError 5
            files = [f for f in Path(p).rglob("*") if f.is_file()]
            if any(not (f.stat().st_mode & _stat.S_IWRITE) for f in files):
                raise PermissionError(5, "Access is denied")
            real_rmtree(p, *a, **kw)

        monkeypatch.setattr(company_admin.shutil, "rmtree", fake_rmtree)

        text, code = company_admin.purge_dir(
            str(d), yes=True, password=company_admin._PURGE_PASSWORD
        )

        assert code == 0, f"只读文件把删除卡死了：{text}"
        assert not d.exists()

    def test_transient_lock_retries(self, env, monkeypatch):
        """被短暂占用（杀毒）→ 重试后成功，不再让用户"关掉再跑一遍"。"""
        import shutil as _shutil

        d = self._orphan_dir(env)
        real_rmtree = _shutil.rmtree
        calls = {"n": 0}

        def flaky_rmtree(p, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError(32, "The process cannot access the file")
            real_rmtree(p, *a, **kw)

        monkeypatch.setattr(company_admin.shutil, "rmtree", flaky_rmtree)

        text, code = company_admin.purge_dir(
            str(d), yes=True, password=company_admin._PURGE_PASSWORD
        )

        assert code == 0, f"瞬时占用没有重试：{text}"
        assert not d.exists()
        assert calls["n"] == 2, "应当重试一次后成功"

    def test_persistent_lock_still_reports_failure(self, env, monkeypatch):
        """一直删不掉时必须如实报错 —— 重试不能把失败吞成"成功"。"""
        d = self._orphan_dir(env)

        def always_fail(p, *a, **kw):
            raise PermissionError(32, "locked")

        monkeypatch.setattr(company_admin.shutil, "rmtree", always_fail)

        text, code = company_admin.purge_dir(
            str(d), yes=True, password=company_admin._PURGE_PASSWORD
        )

        assert code == 1
        assert "删除失败" in text
        assert d.is_dir(), "报失败就绝不能已经把目录删了"

    def test_no_stdin_is_treated_as_no_tty(self, env, monkeypatch):
        """Windows 上 sys.stdin 可能是 None（pythonw/无控制台）→ 不能崩，
        要按「没有 TTY」拒绝，并提示改用 --password。"""
        monkeypatch.setattr(company_admin.sys, "stdin", None)

        text, code = company_admin.purge_company(
            env["company"]["slug"], yes=True, password=None
        )

        assert code == 1
        assert "--password" in text
        assert env["desktop"].joinpath("错误公司").is_dir(), "没有口令就必须什么都不删"
