"""
工程图纸 PDF 自动处理模块（实验性）。

⚠️ 重要：AI 分析结果仅供初步参考，不可直接用于报价或生产。
所有尺寸、材料、标准均需人工逐项核实确认。

从客户发来的 PDF 图纸中辅助提取结构化生产信息（零件名、材料、尺寸、公差等）。
自动判断 PDF 类型（文字层 vs 扫描件），分别采用文本提取或 LLM Vision 处理。
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import fitz  # PyMuPDF — 已有依赖

_log = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────

_MIN_TEXT_CHARS = 50  # 少于 50 字符判定为扫描件
# 图纸页常见「标题栏有文字 + 主体是扫描图」：文字超过 _MIN_TEXT_CHARS 但远少于
# 一份正常文档，这类页也必须读图，否则主体内容会被当成「已提取」而丢掉。
_SPARSE_TEXT_CHARS = 500
_DEFAULT_DPI = 200    # 扫描件渲染 DPI
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 单页图片最大 5MB

# ── LLM prompt ───────────────────────────────────────────────────────────

_STRUCTURED_PROMPT = """你是一个工程图纸分析专家。请从以下工程图纸内容中提取结构化信息。

输出纯 JSON，不要任何解释文字：
{
  "ok": true,
  "part_name": "零件名称（如：舱口框架 / Hatch Frame）",
  "drawing_number": "图号（如：К-959.2）",
  "material": "材料及标准（如：铸钢 1组 GOST 977-88）",
  "precision_grade": "精度等级（如：12-7-0-0）",
  "standard": ["适用标准列表"],
  "dimensions": [
    {"label": "标注含义", "value": "数值", "unit": "mm"}
  ],
  "tolerances": ["公差要求"],
  "surface_finish": "表面处理要求",
  "heat_treatment": "热处理要求",
  "notes": ["其他技术要求/备注"]
}

图纸内容：
{text}"""


def parse_json_object(content: str | None) -> dict | None:
    """从模型输出里取第一个 JSON 对象，容忍围栏和尾随说明。

    ``json.loads`` 要求整段都是 JSON；模型经常在对象后面补一句说明，
    直接 loads 会抛 Extra data，导致整次分析被丢弃。
    """
    text = (content or "").strip()
    if not text:
        return None
    # ```json ... ``` 围栏
    if text.startswith("```"):
        text = text[3:]
        text = text.removeprefix("json").strip()
        text = text.rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    # 回退：从第一个 { 开始解一个完整对象，忽略后面多余内容
    start = text.find("{")
    if start < 0:
        return None
    try:
        parsed, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def render_prompt(text: str) -> str:
    """把图纸文本填进提示词模板。

    用 replace 而不是 str.format：模板里的 JSON 示例带花括号，
    format 会把 ``{"ok": true}`` 当成占位符并抛 KeyError。
    """
    return _STRUCTURED_PROMPT.replace("{text}", text)


def _detect_pdf_type(doc: fitz.Document) -> str:
    """判断 PDF 是文字层还是扫描件。

    统计所有页面文字总量。
    文字 > 50 字符 → 文字层；否则 → 扫描件。
    """
    total_chars = sum(len(page.get_text()) for page in doc)
    return "text" if total_chars >= _MIN_TEXT_CHARS else "image"


def pages_needing_vision(doc: fitz.Document) -> list[int]:
    """返回需要视觉读图的页下标（0 基）。

    按页判断而不是整份二选一：图纸常见「标题栏有文字层 + 主体是扫描图」，
    整份判成文字层会让扫描的主体内容被丢掉。
    """
    return [
        index
        for index, page in enumerate(doc)
        if len(page.get_text().strip()) < _SPARSE_TEXT_CHARS and page.get_images()
    ]


def _extract_text(doc: fitz.Document) -> str:
    """从文字层 PDF 提取全部文字。"""
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text().strip()
        if text:
            pages.append(f"--- Page {i+1} ---\n{text}")
    return "\n\n".join(pages) if pages else ""


def _render_pages(doc: fitz.Document, dpi: int = _DEFAULT_DPI,
                  only: list[int] | None = None) -> list[bytes]:
    """将 PDF 页渲染为 PNG 字节流（用于 Vision API）。

    ``only`` 给定时只渲染这些页下标（0 基），用于混合型图纸只送扫描页。
    """
    images = []
    for index, page in enumerate(doc):
        if only is not None and index not in only:
            continue
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")
        if len(img_bytes) > _MAX_IMAGE_BYTES:
            # 降分辨率重试
            pix = page.get_pixmap(dpi=100)
            img_bytes = pix.tobytes("png")
        images.append(img_bytes)
    return images


def _call_llm(prompt: str, images: list[bytes] | None = None) -> dict | None:
    """调用 LLM 分析图纸内容。

    复用 Trade 的 provider/model/api_key 配置。
    文字层 → text prompt；扫描件 → vision prompt + base64 图片。
    """
    try:
        from trade.helpers import get_agent_kwargs
        kwargs = get_agent_kwargs()
    except Exception as e:
        _log.warning("无法获取 LLM 配置: %s", e)
        return None

    api_key = kwargs.get("api_key", "")
    base_url = kwargs.get("base_url", "")
    model = kwargs.get("model", "")

    if not api_key or not model:
        _log.warning("LLM 未配置，无法分析图纸")
        return None

    try:
        import openai
        client = openai.OpenAI(api_key=api_key, base_url=base_url or None)

        messages: list[dict] = [{"role": "user", "content": []}]

        if images:
            # Vision 模式：文字 prompt + 图片
            messages[0]["content"].append({"type": "text", "text": prompt})
            for img in images[:3]:  # 最多 3 页
                b64 = base64.b64encode(img).decode("utf-8")
                messages[0]["content"].append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
        else:
            # 文本模式
            messages[0]["content"].append({"type": "text", "text": prompt})

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=2000,
        )
        parsed = parse_json_object(response.choices[0].message.content)
        if parsed is None:
            _log.warning("图纸分析结果不是有效 JSON，已放弃本次结果")
        return parsed
    except Exception as e:
        _log.exception("LLM 调用失败: %s", e)
        return None


def _format_dimensions(result: dict) -> list[dict]:
    """规范化尺寸字段。"""
    dims = result.get("dimensions", [])
    if not isinstance(dims, list):
        return []
    return [
        {
            "label": str(d.get("label", "")),
            "value": str(d.get("value", "")),
            "unit": str(d.get("unit", "mm")),
        }
        for d in dims
        if isinstance(d, dict)
    ]


def analyze_drawing(pdf_path: str | Path) -> dict:
    """分析工程图纸 PDF，返回结构化数据。

    Args:
        pdf_path: PDF 文件路径

    Returns:
        {
            "ok": bool,
            "source": "text" | "vision" | "error",
            "pages": int,
            "result": {
                "part_name": str,
                "drawing_number": str,
                "material": str,
                "standard": [str],
                "dimensions": [{"label": "", "value": "", "unit": "mm"}],
                "tolerances": [str],
                "surface_finish": str,
                "heat_treatment": str,
                "notes": [str],
            }
        }
    """
    path = Path(pdf_path)
    if not path.is_file():
        return {"ok": False, "source": "error", "error": f"文件不存在: {pdf_path}"}

    if path.suffix.lower() != ".pdf":
        return {"ok": False, "source": "error", "error": "仅支持 PDF 格式"}

    try:
        doc = fitz.open(str(path))
    except Exception as e:
        return {"ok": False, "source": "error", "error": f"PDF 打开失败: {e}"}

    try:
        pages = len(doc)
        result: dict | None = None

        text = _extract_text(doc)
        vision_pages = pages_needing_vision(doc)

        if vision_pages:
            # 扫描页（或混合型图纸的扫描部分）：渲染后走视觉通道，
            # 同时把已有的文字层一并送上，两部分都不丢。
            images = _render_pages(doc, only=vision_pages)
            if not images:
                return {"ok": False, "source": "error", "pages": pages,
                        "error": "PDF 渲染失败"}
            note = "【以下是工程图纸的扫描件/截图，请从图片中识别所有标注信息】"
            prompt = render_prompt((text[:8000] + "\n\n" + note) if text else note)
            result = _call_llm(prompt, images=images)
        else:
            if not text:
                return {"ok": False, "source": "error", "pages": pages,
                        "error": "PDF 无可提取文字"}
            prompt = render_prompt(text[:8000])
            result = _call_llm(prompt, images=None)

        if result is None:
            if not text:
                # 纯扫描件没有文字层可退，必须明确报错——返回空结论会让用户
                # 以为分析成功。视觉不可用时由调用方决定如何提示用户。
                return {
                    "ok": False,
                    "source": "error",
                    "pages": pages,
                    "error": "扫描件需要视觉能力，但当前模型未返回结果"
                             "（请确认所用模型支持看图，或配置 auxiliary.vision）",
                    "disclaimer": "AI 分析结果仅供初步参考，不可直接用于报价或生产。所有数据需人工逐项核实。",
                }
            # 有文字层可用，返回它供人工审阅
            return {
                "ok": True,
                "source": "text_fallback",
                "pages": pages,
                "raw_text": text[:5000],
                "hint": "LLM 分析不可用，已提取原始文字内容，请人工审阅",
                "disclaimer": "AI 分析结果仅供初步参考，不可直接用于报价或生产。所有数据需人工逐项核实。",
            }

        return {
            "ok": result.get("ok", True),
            "source": ("image" if vision_pages else "text") if result else "text_fallback",
            "pages": pages,
            "disclaimer": "AI 分析结果仅供初步参考，不可直接用于报价或生产。所有尺寸、材料、标准需人工逐项核实确认。",
            "result": {
                "part_name": result.get("part_name", "") or "",
                "drawing_number": result.get("drawing_number", "") or "",
                "material": result.get("material", "") or "",
                "precision_grade": result.get("precision_grade", "") or "",
                "standard": result.get("standard", []) or [],
                "dimensions": _format_dimensions(result),
                "tolerances": result.get("tolerances", []) or [],
                "surface_finish": result.get("surface_finish", "") or "",
                "heat_treatment": result.get("heat_treatment", "") or "",
                "notes": result.get("notes", []) or [],
            },
        }

    finally:
        doc.close()


# ── CLI 测试 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m trade.tech_drawing <pdf_path>")
        sys.exit(1)

    result = analyze_drawing(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
