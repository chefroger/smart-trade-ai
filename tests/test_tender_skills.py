"""招标技能（G1–G6）的验收探针。

任务书 §4 的 9 组探针，按批次落在这里：

- 第 1 批（G2 + G3）：探针 1–4；探针 8/9 只覆盖本批两个 skill
- 第 2 批（G4 + G5）：探针 5–6
- 第 3 批（G1 + G6）：探针 7 + 探针 8 全量

每条测试都对应任务书里一句可验收的话，不做「看起来对」的断言。
"""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# 两个 skill 的 scripts 目录要能被 import
MAIL_SCRIPTS = ROOT / "skills" / "b2b-tender-mail" / "scripts"
PROCESSING_SCRIPTS = ROOT / "skills" / "b2b-tender-processing" / "scripts"
sys.path.insert(0, str(MAIL_SCRIPTS))
sys.path.insert(0, str(PROCESSING_SCRIPTS))

import tender_mail_core as mail  # noqa: E402

SKILL_DIRS = {
    "b2b-tender-mail": ROOT / "skills" / "b2b-tender-mail",
    "b2b-tender-processing": ROOT / "skills" / "b2b-tender-processing",
}


def _load_processing_script():
    """按路径导入 build_inquiry_sheet（目录名带连字符，不能用普通 import）。"""
    path = PROCESSING_SCRIPTS / "build_inquiry_sheet.py"
    spec = importlib.util.spec_from_file_location("build_inquiry_sheet", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── 探针 1：G2 增量与账号跳过 ────────────────────────────────────────────

class TestProbe1Incremental:
    """状态 last_uid=100 时，UID ≤100 不重复抓，>100 才抓；空授权码跳过并列出。"""

    def test_filter_new_uids(self):
        assert mail.filter_new_uids([90, 100, 101, 105, 102], 100) == [101, 102, 105]

    def test_filter_with_no_previous_state(self):
        assert mail.filter_new_uids([3, 1, 2], 0) == [1, 2, 3]

    def test_empty_auth_code_is_skipped_and_listed(self, tmp_path):
        cfg = tmp_path / "mail_accounts.json"
        cfg.write_text(
            '{"accounts": [{"email": "a@example.com", "imap_host": "imap.example.com",'
            ' "imap_port": 993, "auth_code": ""}]}',
            encoding="utf-8",
        )
        accounts = mail.load_config(cfg)
        runnable, skipped = mail.select_runnable(accounts)

        assert runnable == []
        assert len(skipped) == 1
        assert "授权码为空" in skipped[0][1]

    def test_missing_fields_are_skipped(self):
        accounts = [
            mail.Account(email="", imap_host="h", imap_port=993, auth_code="x"),
            mail.Account(email="a@x.com", imap_host="", imap_port=993, auth_code="x"),
            mail.Account(email="b@x.com", imap_host="h", imap_port=993, auth_code="x"),
        ]
        runnable, skipped = mail.select_runnable(accounts)

        assert [a.email for a in runnable] == ["b@x.com"]
        assert {s[1] for s in skipped} == {"缺 email", "缺 imap_host"}

    def test_blacklist_reports_reason(self):
        reason = mail.should_skip("no-reply@example.com", "您的验证码 123456")

        assert reason is not None
        assert "黑名单" in reason

    def test_blacklist_lets_business_mail_through(self):
        assert mail.should_skip("buyer@example.com", "RFQ for 200 pcs valves") is None

    def test_state_round_trip(self, tmp_path):
        state_file = tmp_path / "state.json"
        mail.save_state(state_file, datetime(2026, 11, 2, 9, 30, 0), 12345)

        state = mail.load_state(state_file)
        assert state["last_uid"] == 12345
        assert state["last_check"].startswith("2026-11-02T09:30")

    def test_corrupt_state_is_treated_as_first_run(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text("{not json", encoding="utf-8")

        assert mail.load_state(state_file) == {}


# ── 探针 2：G2 只读（不置已读）──────────────────────────────────────────

class TestProbe2ReadOnly:
    """拉取必须走不置已读标志的方式。"""

    def test_fetch_uses_body_peek(self):
        calls = []

        class FakeConn:
            def uid(self, command, *args):
                calls.append((command, args))
                return "OK", [(b"header", b"raw-bytes")]

        raw = mail.fetch_raw(FakeConn(), 42)

        assert raw == b"raw-bytes"
        command, args = calls[0]
        assert command == "FETCH"
        assert "BODY.PEEK" in args[-1], "没有用 PEEK 语义 —— 会把邮件标成已读"

    def test_no_plain_rfc822_fetch_in_core(self):
        """整个核心模块里不得出现会把邮件标已读的拉取方式。"""
        source = (MAIL_SCRIPTS / "tender_mail_core.py").read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )

        assert '"RFC822"' not in code and "(RFC822)" not in code
        assert "BODY.PEEK" in code


# ── 探针 3：G2 落盘规则 ─────────────────────────────────────────────────

def _simple_mail(subject: str, attachment: tuple[str, bytes] | None = None) -> mail.ParsedMail:
    return mail.ParsedMail(
        sender="buyer@example.com",
        subject=subject,
        date=datetime(2026, 11, 2, 10, 0, 0),
        body="请查收附件。",
        attachments=[attachment] if attachment else [],
    )


class TestProbe3Landing:
    """同天同主题不覆盖；附件 MD5 去重；内联小图不进附件目录。"""

    def test_same_day_same_subject_does_not_overwrite(self, tmp_path):
        first = mail.save_mail(tmp_path, _simple_mail("RFQ 阀门"), 1)
        second = mail.save_mail(tmp_path, _simple_mail("RFQ 阀门"), 2)

        assert first != second
        assert first.is_file() and second.is_file()
        assert "_2" in second.name, "第二封没有加 UID 后缀"

    def test_attachment_md5_dedupes(self, tmp_path):
        payload = b"same-bytes"
        parsed = _simple_mail("RFQ", ("a.pdf", payload))
        parsed.attachments.append(("copy.pdf", payload))

        mail.save_mail(tmp_path, parsed, 1)

        files = list(tmp_path.rglob("*.pdf"))
        assert len(files) == 1, f"同内容附件被存了 {len(files)} 份"

    def test_inline_image_is_not_an_attachment(self):
        msg = EmailMessage()
        msg["From"] = "buyer@example.com"
        msg["Subject"] = "RFQ with signature"
        msg["Date"] = "Mon, 02 Nov 2026 10:00:00 +0800"
        msg.set_content("正文")
        # 签名里的内联 logo
        msg.add_related(
            b"\x89PNG-fake", maintype="image", subtype="png", cid="<logo123>"
        )
        # 真正的业务附件
        msg.add_attachment(
            b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="drawing.pdf"
        )

        parsed = mail.parse_message(msg.as_bytes())

        assert [name for name, _ in parsed.attachments] == ["drawing.pdf"]

    def test_illegal_filename_chars_replaced(self):
        assert mail.safe_filename("a/b\\c:d*e?f") == "a_b_c_d_e_f"

    def test_subject_normalization_strips_reply_prefix(self):
        assert mail.normalize_subject("RE: Fwd: 招标文件") == "招标文件"


# ── 探针 4：G3 询价单 ───────────────────────────────────────────────────

SPEC = {
    "tender_no": "T-2026-001",
    "buyer": "某采购方",
    "project_name": "阀门",
    "deadline": "2026-12-01",
    "status": "待报价",
    "date": "2026-11-02",
    "skeleton": False,
    "rows": [
        {
            "no": 1,
            "part_no": "A-100",
            "name_src": "Gate valve",
            "name_zh": "闸阀",
            "qty": 10,
            "unit_weight": 12.5,
            "material": "WCB",
        },
        {
            # 装配体拆件：单台 3 件 × 4 台
            "no": 2,
            "part_no": "B-200",
            "name_src": "Valve body",
            "name_zh": "阀体",
            "unit_qty": 3,
            "units": 4,
            "unit_weight": 2.0,
            "material": "WCB",
        },
        {
            # 缺单重
            "no": 3,
            "part_no": "C-300",
            "name_src": "Gasket",
            "name_zh": "垫片",
            "qty": 100,
            "unit_weight": None,
            "material": "",
        },
    ],
}


class TestProbe4InquirySheet:
    """11 列固定、装配体展开、缺单重写「按图纸」、单价/总价/交货期留空、汇总公式。"""

    @pytest.fixture()
    def sheet(self, tmp_path):
        from openpyxl import load_workbook

        module = _load_processing_script()
        result = module.build(SPEC, tmp_path)
        wb = load_workbook(result["sheet"])
        return ws_result(module, result, wb)

    def test_header_is_exactly_11_columns(self, sheet):
        module, _result, ws = sheet
        headers = [c.value for c in ws[1]][:11]

        assert headers == module.HEADERS
        assert len(module.HEADERS) == 11

    def test_data_starts_at_row_2(self, sheet):
        _module, _result, ws = sheet

        assert ws.cell(row=2, column=1).value == 1
        assert ws.cell(row=2, column=2).value == "A-100"

    def test_assembly_row_quantity_and_trace_note(self, sheet):
        _module, _result, ws = sheet

        assert ws.cell(row=3, column=5).value == 12, "数量应 = 单台 3 × 4 台"
        assert "（单台 3 × 4 台）" in ws.cell(row=3, column=4).value

    def test_missing_weight_says_by_drawing(self, sheet):
        _module, _result, ws = sheet

        assert ws.cell(row=4, column=6).value == "按图纸"

    def test_price_total_lead_time_are_empty(self, sheet):
        _module, _result, ws = sheet

        for row in (2, 3, 4):
            assert ws.cell(row=row, column=9).value is None   # 单价
            assert ws.cell(row=row, column=10).value is None  # 总价
            assert ws.cell(row=row, column=11).value is None  # 交货期

    def test_total_weight_uses_formula(self, sheet):
        _module, _result, ws = sheet

        assert ws.cell(row=2, column=7).value == "=E2*F2"

    def test_summary_row_has_sum_formulas(self, sheet):
        _module, result, ws = sheet

        summary_row = 5  # 3 行数据 + 表头 + 1
        assert ws.cell(row=summary_row, column=1).value == "汇总"
        assert ws.cell(row=summary_row, column=7).value == "=SUM(G2:G4)"
        assert ws.cell(row=summary_row, column=10).value == "=SUM(J2:J4)"

    def test_folder_name_follows_rule(self, sheet):
        module, _result, _ws = sheet

        assert module.project_folder_name(SPEC) == "2026-11-02-T-2026-001阀门-待报价"

    def test_folder_name_omits_number_when_absent(self):
        module = _load_processing_script()
        spec = dict(SPEC, tender_no="")

        assert module.project_folder_name(spec) == "2026-11-02-阀门-待报价"


class TestProbe4Skeleton:
    """缺主文件时只出骨架：数量「待确认」、单重/材质「按图纸」。"""

    def test_skeleton_sheet(self, tmp_path):
        from openpyxl import load_workbook

        module = _load_processing_script()
        spec = dict(SPEC, skeleton=True)
        result = module.build(spec, tmp_path)
        ws = load_workbook(result["sheet"])["询价单"]

        assert result["skeleton"] is True
        assert ws.cell(row=2, column=5).value == "待确认"
        assert ws.cell(row=2, column=6).value == "按图纸"
        assert ws.cell(row=2, column=8).value == "按图纸"


def ws_result(module, result, wb):
    """夹具返回三元组：模块、构建结果、活动工作表。"""
    return module, result, wb["询价单"]


# ── 探针 8（本批部分）：注册与触发分界 ──────────────────────────────────

class TestProbe8Registration:
    """本批 2 个 skill 必须可查，且触发词不抢邻近 skill。"""

    def test_both_skills_registered(self):
        from trade.skill_registry import get_skill_by_name

        for name in SKILL_DIRS:
            assert get_skill_by_name(name) is not None, f"{name} 未注册"

    def test_skill_dirs_exist(self):
        for name, path in SKILL_DIRS.items():
            assert (path / "SKILL.md").is_file(), f"{name} 缺 SKILL.md"

    def test_frontmatter_has_required_fields(self):
        for name, path in SKILL_DIRS.items():
            text = (path / "SKILL.md").read_text(encoding="utf-8")
            front = text.split("---")[1]

            for field in ("name:", "description:", "when_to_use:", "triggers:",
                          "category:", "version: 1.0.0", "author:"):
                assert field in front, f"{name} frontmatter 缺 {field}"

    def test_trigger_routing_stays_in_lane(self):
        from trade.skill_router import match_skills

        cases = {
            "抓邮件归档": "b2b-tender-mail",
            "生成询价单": "b2b-tender-processing",
        }
        for query, expected in cases.items():
            hits = [h["skill_name"] for h in match_skills(query)]
            assert expected in hits, f"{query} 没命中 {expected}（实际 {hits}）"
            assert hits[0] == expected, f"{query} 被 {hits[0]} 抢走了"

    def test_mail_triggers_do_not_steal_email_skills(self):
        from trade.skill_router import match_skills

        hits = [h["skill_name"] for h in match_skills("抓邮件归档")]

        assert "b2b-email-intel" not in hits
        assert "b2b-email-imitation" not in hits

    def test_inquiry_triggers_do_not_steal_doc_generation(self):
        from trade.skill_router import match_skills

        hits = [h["skill_name"] for h in match_skills("生成询价单")]

        assert "b2b-doc-generation" not in hits

    def test_new_dirs_are_synced_by_prefix_rule(self, tmp_path, monkeypatch):
        """安装同步按 b2b-* 前缀自动带上新目录 —— 不需要为新 skill 写特例。"""
        from trade.post_install.skills import _copy_skills

        monkeypatch.setenv("TRADE_HOME", str(tmp_path / "trade-home"))
        installed = _copy_skills(ROOT / "skills", tmp_path / "hermes" / "skills")

        for name in SKILL_DIRS:
            assert name in installed, f"{name} 没有被前缀规则同步"
            assert (tmp_path / "hermes" / "skills" / name / "SKILL.md").is_file()

    def test_triggers_contain_no_company_or_platform_names(self):
        """触发词里不得出现具体公司名 / 平台名。"""
        from trade.skill_registry import get_skill_by_name

        banned = ("alibaba", "made-in-china", "globalsources", "1688", "amazon")
        for name in SKILL_DIRS:
            entry = get_skill_by_name(name)
            blob = " ".join(entry["triggers"]).lower()
            for word in banned:
                assert word not in blob, f"{name} 触发词含平台名 {word}"


# ── 探针 9（本批部分）：通用化自查 ─────────────────────────────────────

class TestProbe9Generalization:
    """西里尔字母 0 命中；不写死具体公司名 / 项目编号。"""

    @staticmethod
    def _all_text() -> str:
        chunks = []
        for path in SKILL_DIRS.values():
            for f in path.rglob("*"):
                if f.is_file() and f.suffix in (".md", ".py", ".json"):
                    chunks.append(f.read_text(encoding="utf-8"))
        return "\n".join(chunks)

    def test_no_cyrillic(self):
        assert not re.search(r"[\u0400-\u04FF]", self._all_text()), "出现西里尔字母"

    def test_no_hardcoded_credentials(self):
        text = self._all_text()

        assert "auth_code\": \"<" in text or "<IMAP 授权码>" in text
        # 不得出现形似真实授权码的长串
        assert not re.search(r"auth_code\"\s*:\s*\"[A-Za-z0-9+/]{16,}", text)

    def test_placeholders_used_in_example_config(self):
        example = (MAIL_SCRIPTS / "mail_accounts.example.json").read_text(encoding="utf-8")

        assert "<your-email@example.com>" in example
        assert "<imap.example.com>" in example
        assert "<IMAP 授权码>" in example
