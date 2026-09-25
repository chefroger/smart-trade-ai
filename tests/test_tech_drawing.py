"""工程图纸处理测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade import tech_drawing


class _FakePage:
    def __init__(self, text, images=()):
        self._text = text
        self._images = list(images)

    def get_text(self):
        return self._text

    def get_images(self):
        return self._images


class _FakeDoc:
    def __init__(self, pages):
        self._pages = pages

    def __iter__(self):
        return iter(self._pages)

    def __len__(self):
        return len(self._pages)

    def close(self):
        pass


@pytest.fixture
def pdf(tmp_path):
    """一份占位 PDF（内容由 fitz mock 提供）。"""
    path = tmp_path / "drawing.pdf"
    path.write_bytes(b"%PDF-placeholder")
    return path


def test_json_parse_tolerates_trailing_text():
    """模型偶尔在 JSON 后附说明，不能因此丢掉整个结果。"""
    parsed = tech_drawing.parse_json_object('{"ok": true, "part_name": "舱口框架"}\n\n以上为识别结果。')

    assert parsed == {"ok": True, "part_name": "舱口框架"}


def test_json_parse_strips_code_fence():
    """```json 围栏包裹的输出也要能解析。"""
    parsed = tech_drawing.parse_json_object('```json\n{"ok": true, "part_name": "A"}\n```')

    assert parsed == {"ok": True, "part_name": "A"}


def test_json_parse_returns_none_for_garbage():
    """完全不是 JSON 时返回 None，由调用方兜底。"""
    assert tech_drawing.parse_json_object("抱歉，我无法识别这张图") is None
    assert tech_drawing.parse_json_object("") is None


def test_sparse_text_page_with_image_needs_vision(pdf, monkeypatch):
    """标题栏只有少量文字的图纸页也要读图，否则主体内容会丢。"""
    title_block = "零件名 舱口框架 图号 К-959.2 材料 铸钢 GOST 977-88 精度等级 12-7-0-0"
    monkeypatch.setattr(tech_drawing.fitz, "open", lambda _: _FakeDoc([
        _FakePage(title_block, images=[("xref",)]),
    ]))

    assert tech_drawing.pages_needing_vision(tech_drawing.fitz.open("x")) == [0]


def test_prompt_renders_without_format_crash():
    """提示词里的 JSON 示例含花括号，必须能安全渲染出图纸文本。"""
    rendered = tech_drawing.render_prompt("图号 К-959.2 材料 铸钢")

    assert "图号 К-959.2 材料 铸钢" in rendered
    # JSON 示例里的花括号必须原样保留，不能被当成占位符吃掉
    assert '"ok": true' in rendered
    assert '"part_name"' in rendered


def test_text_pdf_reaches_llm(pdf, monkeypatch):
    """文字层 PDF 不能再因提示词渲染而崩溃，必须真正走到 LLM。"""
    monkeypatch.setattr(tech_drawing.fitz, "open", lambda _: _FakeDoc(
        [_FakePage("零件名 舱口框架 图号 К-959.2 材料 铸钢 1 组 GOST 977-88 精度等级 12-7-0-0 尺寸 120mm 公差 ±0.5mm 表面处理 喷砂 热处理 正火 备注 铸件需探伤合格后方可交付")]))
    calls = []

    def _fake_llm(prompt, images=None):
        calls.append((prompt, images))
        return {"ok": True, "part_name": "舱口框架", "drawing_number": "К-959.2"}

    monkeypatch.setattr(tech_drawing, "_call_llm", _fake_llm)

    result = tech_drawing.analyze_drawing(pdf)

    assert calls and calls[0][1] is None      # 文字层不带图
    assert result["source"] == "text"
    assert result["result"]["part_name"] == "舱口框架"


def test_scanned_pdf_uses_vision(pdf, monkeypatch):
    """扫描件要渲染成图片走视觉通道。"""
    monkeypatch.setattr(tech_drawing.fitz, "open", lambda _: _FakeDoc([_FakePage("   ", images=[("xref",)])]))
    monkeypatch.setattr(tech_drawing, "_render_pages", lambda doc, dpi=200, only=None: [b"png-bytes"])
    calls = []

    def _fake_llm(prompt, images=None):
        calls.append((prompt, images))
        return {"ok": True, "part_name": "扫描零件"}

    monkeypatch.setattr(tech_drawing, "_call_llm", _fake_llm)

    result = tech_drawing.analyze_drawing(pdf)

    assert calls[0][1] == [b"png-bytes"]
    assert result["source"] == "image"
    assert result["result"]["part_name"] == "扫描零件"


def test_mixed_pdf_reads_both_text_and_scanned_pages(pdf, monkeypatch):
    """图纸标题栏有文字、主体是扫描图时，两部分都要读到。"""
    long_text = "零件名 舱口框架 图号 К-959.2 材料 铸钢 1 组 GOST 977-88 精度等级 12-7-0-0 尺寸 120mm 公差 ±0.5mm 表面处理 喷砂 热处理 正火 备注 铸件需探伤"
    monkeypatch.setattr(tech_drawing.fitz, "open", lambda _: _FakeDoc([
        _FakePage(long_text),                    # 第 1 页：标题栏文字
        _FakePage("   ", images=[("xref",)]),    # 第 2 页：扫描图，无文字层
    ]))
    rendered = []

    def _fake_render(doc, dpi=200, only=None):
        rendered.append(only)
        return [b"page2-png"]

    monkeypatch.setattr(tech_drawing, "_render_pages", _fake_render)
    calls = []
    monkeypatch.setattr(tech_drawing, "_call_llm",
                        lambda prompt, images=None: calls.append((prompt, images)) or {"ok": True})

    result = tech_drawing.analyze_drawing(pdf)

    assert rendered == [[1]]                    # 只有扫描页被渲染
    assert calls[0][1] == [b"page2-png"]        # 图片确实送进了视觉通道
    assert "舱口框架" in calls[0][0]            # 标题栏文字也没丢
    assert result["source"] == "image"


def test_vision_failure_is_reported_not_silently_empty(pdf, monkeypatch):
    """视觉不可用时要明确报错，不能返回空结论让用户以为分析成功。"""
    monkeypatch.setattr(tech_drawing.fitz, "open", lambda _: _FakeDoc([_FakePage("   ", images=[("xref",)])]))
    monkeypatch.setattr(tech_drawing, "_render_pages", lambda doc, dpi=200, only=None: [b"png-bytes"])
    monkeypatch.setattr(tech_drawing, "_call_llm", lambda prompt, images=None: None)

    result = tech_drawing.analyze_drawing(pdf)

    assert result["ok"] is False
    assert "视觉" in result["error"] or "vision" in result["error"].lower()


def test_text_layer_llm_failure_keeps_raw_text(pdf, monkeypatch):
    """文字层 LLM 失败时保留原始文字，供人工审阅。"""
    monkeypatch.setattr(tech_drawing.fitz, "open", lambda _: _FakeDoc(
        [_FakePage("零件名 舱口框架 图号 К-959.2 材料 铸钢 1 组 GOST 977-88 精度等级 12-7-0-0 尺寸 120mm 公差 ±0.5mm 表面处理 喷砂 热处理 正火 备注 铸件需探伤合格后方可交付")]))
    monkeypatch.setattr(tech_drawing, "_call_llm", lambda prompt, images=None: None)

    result = tech_drawing.analyze_drawing(pdf)

    assert result["ok"] is True
    assert result["source"] == "text_fallback"
    assert "舱口框架" in result["raw_text"]
