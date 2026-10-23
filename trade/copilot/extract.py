"""extract —— 把截图转成结构化对话（平台无关）。

## 走哪条模型通道

用 **Hermes 的 `async_call_llm(task="vision", ...)`**，不裸直调 openai SDK。
理由（2026-10-22 实测）：客户视觉模型配在 `auxiliary.vision`（本机是
`custom:deepseek-vl`），而那个 provider 名**不在 Hermes 的 PROVIDER_REGISTRY、
也不在 config 的 custom_providers**（实跑 `_get_named_custom_provider("deepseek-vl")`
→ None）—— 裸直调拿不到它的 base_url 与 key。

Hermes 这条通道（`tools/vision_tools.py` 的 vision_analyze 用的是同一条）：
    - 自己解析 provider/model，走 auto chain（主 provider → OpenRouter → Nous →
      Anthropic → custom），与 trade 现有视觉能力**同源**（doctor 的「vision 读图」
      实测通过，用主模型 deepseek-flash）；
    - 接受标准 OpenAI messages，图片以 `image_url` 的 base64 data URL 内联；
    - 自带超时、温度与错误分类。

**默认跟随主模型**（决策 2026-10-22）：用户可在副驾设置里单独指定抽取模型；
指定了就传给 call_llm 的 provider/model 参数，不指定就让它自己解析。

## 两类错误必须分开（任务书 §3）

    ① 协议不兼容：服务商不是 OpenAI 兼容端点 → 直调/辅助通道都走不通
    ② 模型不支持视觉：协议通、模型收不了图

两类都不许拿 OCR 硬凑、不许假装读到了 —— 宁可明确报错让用户换模型。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from trade.copilot.types import (
    DEFAULT_TIMEOUT,
    CapturedWindow,
    DialogMessage,
    ExtractedDialog,
)

_log = logging.getLogger(__name__)

# 抽取结果的 JSON 契约（提示词与解析都以此为准）
_EXTRACT_PROMPT = """\
你是 B2B 外贸对话的转录助手。给你一张聊天软件窗口截图，请转录成结构化 JSON。

只做转录与分角色，**不要**回答问题、不要给建议、不要补全截图里没有的内容。

严格输出这个 JSON（不要任何解释文字、不要 markdown 代码块）：
{"app": "聊天软件名", "contact": "对方名称或昵称", "language": "en/zh/ja/ar/…",
 "messages": [{"who": "customer|me|unknown", "text": "消息原文"}], "confidence": 0.0}

规则：
- who：对方发的 = "customer"，我方发的 = "me"，分不清 = "unknown"
- text：**逐字**转录，保留原文语言与措辞；不要翻译、不要润色、不要总结
- 对方最后一条消息通常是 customer
- 截图模糊/被遮挡/看不清的部分，用 "…" 标记，不要猜
- 认不出 contact 就给 ""，不要编名字
- confidence：0.0–1.0，整体转录清晰度（1.0 = 完全清晰）
"""

# 判定"模型不支持视觉"的服务商错误特征（与 Hermes 的 _IMAGE_ERROR_RULES 同源思路）
# 注意：不要放裸 "vision" / "invalid_request" —— 它们会把 "404 at /vision"、
# 参数拼写错误之类的协议问题误判成"模型不支持看图"（复审 P2）。
_NO_VISION_HINTS = (
    "does not support",
    "not support image",
    "unsupported content",
    "unrecognized request argument",
    "image input",
    "content_policy",
    "multimodal",
)
# 判定"协议不兼容"的特征
_PROTOCOL_HINTS = (
    "unsupported protocol",
    "not an openai",
    "invalid base_url",
    "unsupported api",
    "no route",
    "404 page not found",
    "404 not found",
)


def _classify_error(exc: Exception) -> tuple[str, str]:
    """把异常分成两类：("protocol"|"no_vision"|"other", 人类可读原因)。

    先判协议：路由/端点类的 404 文案里常带 "vision" 字样，顺序反了会误报成
    "模型不支持看图"，把用户引到错误的修复方向。
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(h in text for h in _PROTOCOL_HINTS):
        return "protocol", (
            "当前服务商与副驾的识别方式不兼容（需要 OpenAI 兼容的视觉端点）。"
            "请在副驾设置里为抽取指定一个兼容的视觉模型。"
        )
    if any(h in text for h in _NO_VISION_HINTS):
        return "no_vision", (
            "当前模型不支持看图，或服务端不接受图片输入。"
            "请在副驾设置里为抽取指定一个支持视觉的模型。"
        )
    return "other", f"抽取调用失败：{type(exc).__name__}: {exc}"


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    """从模型输出里解析 JSON 对象（容忍 ```json 包裹与前后杂音）。"""
    if not raw:
        return None
    text = raw.strip()
    # 去掉 markdown 代码块围栏
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    # 直接试
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    # 退一步：抓第一个 {...} 块
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _coerce_messages(raw: Any) -> list[DialogMessage]:
    """把模型给的 messages 规整成 DialogMessage 列表（只保留能用的）。"""
    out: list[DialogMessage] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        who = item.get("who")
        if who not in ("customer", "me", "unknown"):
            who = "unknown"
        text = item.get("text")
        if not isinstance(text, str):
            text = "" if text is None else str(text)
        text = text.strip()
        if not text:
            continue
        out.append(DialogMessage(who=who, text=text))
    return out


def parse_extraction(raw: str) -> ExtractedDialog:
    """把模型输出解析成 ExtractedDialog。

    **解析失败不吞**：返回带 error 的对象，UI 会照样展示原文并提示"可能不准"。
    """
    obj = _parse_json_object(raw)
    if obj is None:
        # raw 必须带回去 —— 错误文案承诺"原文已保留"，UI 要真的能展示它。
        return ExtractedDialog(
            raw=raw or "",
            error="识别结果不是有效 JSON，无法结构化（原文已保留，请人工核对）",
            error_kind="parse",
        )

    confidence = obj.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return ExtractedDialog(
        app=str(obj.get("app") or ""),
        contact=str(obj.get("contact") or ""),
        language=str(obj.get("language") or ""),
        messages=_coerce_messages(obj.get("messages")),
        confidence=confidence,
        raw=raw or "",
    )


async def extract_dialog(
    captured: CapturedWindow,
    *,
    provider: str | None = None,
    model: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> ExtractedDialog:
    """把一次窗口读取转成结构化对话。

    Args:
        captured: capture 的结果（带 base64 图像）。
        provider: 抽取模型的服务商（None = 跟随 Hermes 自动解析 = 主模型）。
        model: 抽取模型名（None = 跟随）。
        timeout: 单次调用超时（秒）。

    Returns:
        ExtractedDialog。失败时 error/error_kind 有值，**不返回空草稿式结果**。
    """
    if not captured.has_image():
        # 剪贴板通道没有图像 —— 走纯文本抽取
        return await extract_dialog_from_text(captured.text or "", timeout=timeout)

    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": _EXTRACT_PROMPT},
            {"type": "image_url", "image_url": {"url": captured.image_data_url}},
        ]},
    ]
    return await _call_extract(messages, provider=provider, model=model, timeout=timeout)


async def extract_dialog_from_text(
    text: str, *, provider: str | None = None, model: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> ExtractedDialog:
    """纯文本抽取（剪贴板通道）。同样只转录、不回答。"""
    if not text.strip():
        return ExtractedDialog(error="没有可抽取的文本", error_kind="empty")
    messages = [
        {"role": "user", "content": (
            _EXTRACT_PROMPT + "\n\n以下是聊天记录原文（纯文本，没有截图）：\n\n" + text
        )},
    ]
    return await _call_extract(messages, provider=provider, model=model, timeout=timeout)


async def _call_extract(
    messages: list, *, provider: str | None, model: str | None, timeout: float,
) -> ExtractedDialog:
    """调 Hermes 的 vision 通道并解析结果。"""
    try:
        from agent.auxiliary_client import async_call_llm
    except ImportError as exc:
        return ExtractedDialog(
            error=f"Hermes 视觉通道不可用：{exc}",
            error_kind="other",
        )

    kwargs: dict[str, Any] = {
        "task": "vision",
        "messages": messages,
        "temperature": 0.1,
        "timeout": timeout,
        "max_tokens": 2000,
    }
    if provider:
        kwargs["provider"] = provider
    if model:
        kwargs["model"] = model

    try:
        response = await async_call_llm(**kwargs)
    except Exception as exc:
        kind, reason = _classify_error(exc)
        _log.warning("副驾抽取调用失败（%s）：%s", kind, exc)
        return ExtractedDialog(error=reason, error_kind=kind)

    raw = _extract_text(response)
    if not raw:
        return ExtractedDialog(
            error="视觉模型没有返回内容（可能被服务商拒绝）。"
                  "请在副驾设置里为抽取指定一个支持视觉的模型。",
            error_kind="no_vision",
        )
    return parse_extraction(raw)


def _extract_text(response: Any) -> str:
    """从 OpenAI 风格响应里取文本（兼容 str / 对象 / dict）。"""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    # 走 Hermes 的归一化助手（它在多处用过）
    try:
        from agent.auxiliary_client import extract_content_or_reasoning  # type: ignore

        text = extract_content_or_reasoning(response)
        if text:
            return str(text)
    except Exception:
        pass
    # 手工兜底：OpenAI 风格
    try:
        choices = response.choices
        if choices:
            message = choices[0].message
            content = getattr(message, "content", None)
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(str(part.get("text") or ""))
                    elif hasattr(part, "text"):
                        parts.append(str(getattr(part, "text", "") or ""))
                return "".join(parts)
    except Exception:
        pass
    if isinstance(response, dict):
        content = response.get("content")
        if isinstance(content, str):
            return content
    return ""
