"""extract —— 把截图转成结构化对话（平台无关）。

## 走哪条模型通道

用 **Hermes 的 `async_call_llm(task="vision", ...)`**，不裸直调 openai SDK。
理由：视觉配置来自 `auxiliary.vision`，裸直调要自己解析 base_url/key，
还会踩到不可用的 custom provider。

Hermes 这条通道（`tools/vision_tools.py` 的 vision_analyze 用的是同一条）：
    - 接受标准 OpenAI messages，图片以 `image_url` 的 base64 data URL 内联；
    - 自带超时、温度与错误分类；
    - 注意：provider 不可用时 Hermes 会**内部回落到 auto chain** —— 所以
      Trade 必须先筛掉不可用的 custom provider。

**抽取模型使用用户配置的视觉模型，且必须显式传入**（2026-11-05 口径）：
优先 `auxiliary.vision`，缺失时回退主模型；解析不到就报错；
**绝不把 provider/model 留空交给 Hermes auto chain**，也不写死某家服务商/
型号 —— 具体名字以后会变。

## 两类错误必须分开（任务书 §3）

    ① 协议不兼容：服务商不是 OpenAI 兼容端点 → 直调/辅助通道都走不通
    ② 模型不支持视觉：协议通、模型收不了图

两类都不许拿 OCR 硬凑、不许假装读到了 —— 宁可明确报错让用户换模型。
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from trade.copilot.types import (
    CapturedWindow,
    DialogMessage,
    ExtractedDialog,
)

_log = logging.getLogger(__name__)

# 对外文案不写死服务商/型号：配置会变，用户也可能换成别的视觉模型。
NO_VISION_MESSAGE = "当前模型不支持看图，请在副驾设置中配置可用的视觉模型。"

# 视觉抽取超时：截图 base64 较大，15s 在真实网络下偏紧（2026-11-05 实测超时）。
# 默认 30s，可用 TRADE_COPILOT_EXTRACT_TIMEOUT 覆盖。
DEFAULT_EXTRACT_TIMEOUT = 30.0


def _extract_timeout() -> float:
    raw = os.environ.get("TRADE_COPILOT_EXTRACT_TIMEOUT", "").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_EXTRACT_TIMEOUT
    return value if value > 0 else DEFAULT_EXTRACT_TIMEOUT


def _load_hermes_config() -> dict:
    """读取 Hermes 配置（单独抽出便于测试替换）。"""
    from hermes_cli.config import load_config

    return load_config() or {}


def _custom_provider_configured(cfg: dict, provider: str) -> bool:
    """custom:<name> 是否真的在 config.custom_providers 里。"""
    if not provider.lower().startswith("custom:"):
        return True
    name = provider.split(":", 1)[1].strip().lower()
    for item in cfg.get("custom_providers") or []:
        if str(item.get("name", "")).strip().lower() == name:
            return True
    return False


def resolve_extract_model() -> tuple[str, str] | None:
    """解析副驾抽取模型的 (provider, model)。

    2026-11-05 口径：**使用用户配置的视觉模型**，不写死服务商/型号。
    优先 `auxiliary.vision`（真正的视觉配置），缺失时回退主模型；
    若是未配置的 `custom:*` 则跳过（否则 Hermes 会内部回落 auto chain，
    把图片发给用户没选的服务商）。解析不到 → None，调用方报错。
    """
    try:
        cfg = _load_hermes_config()
    except Exception as exc:
        _log.warning("读取 Hermes 配置失败，副驾拒绝自动选模型：%s", exc)
        return None

    def _accept(provider: str, model: str) -> tuple[str, str] | None:
        provider = (provider or "").strip()
        model = (model or "").strip()
        if not provider or not model:
            return None
        if not _custom_provider_configured(cfg, provider):
            return None
        return provider, model

    aux = (cfg.get("auxiliary") or {}).get("vision") or {}
    resolved = _accept(aux.get("provider", ""), aux.get("model", ""))
    if resolved:
        return resolved

    main = cfg.get("model")
    if isinstance(main, dict):
        return _accept(
            main.get("provider", ""),
            main.get("default") or main.get("model") or "",
        )
    if isinstance(main, str) and ":" in main:
        provider, _, model = main.partition(":")
        return _accept(provider, model)
    return None

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
    "404 page not found",
    "404 not found",
)
# 网络不可达：与"服务商协议不兼容"是两回事，混在一起会把用户引去改模型配置
_NETWORK_HINTS = (
    "no route to host",
    "network is unreachable",
    "connection refused",
    "connection reset",
    "temporary failure in name resolution",
    "name or service not known",
    "timed out",
    "timeout",
)


def _classify_error(exc: Exception) -> tuple[str, str]:
    """把异常分成四类：("protocol"|"network"|"no_vision"|"other", 人类可读原因)。

    先判协议：路由/端点类的 404 文案里常带 "vision" 字样，顺序反了会误报成
    "模型不支持看图"，把用户引到错误的修复方向。
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    # 超时先说清楚：截图 base64 较大时 30s 也可能不够，别让用户以为配置坏了。
    if "timed out" in text or "timeout" in text:
        return "network", (
            "模型响应超时（截图较大或网络较慢）。请重试；"
            "若持续失败，再检查网络/代理。"
        )
    if any(h in text for h in _PROTOCOL_HINTS):
        return "protocol", (
            "当前服务商与副驾的识别方式不兼容（需要 OpenAI 兼容的视觉端点）。"
            "请在副驾设置里为抽取指定一个兼容的视觉模型。"
        )
    if any(h in text for h in _NETWORK_HINTS):
        return "network", (
            "无法连接到模型服务（网络不可达或超时）。请检查网络/代理后重试；"
            "如果其它功能都正常，再检查副驾的视觉模型配置。"
        )
    if any(h in text for h in _NO_VISION_HINTS):
        return "no_vision", NO_VISION_MESSAGE
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


def _license_block_reason() -> str:
    """到期软着陆：抽取本身也是付费 LLM 调用，到期后不再跑（返回阻断原因）。"""
    try:
        from trade.license import check_license

        ok, msg = check_license()
    except Exception:
        return ""  # 许可证模块异常不阻断
    if ok:
        return ""
    return msg or "试用/许可证已到期"


async def extract_dialog(
    captured: CapturedWindow,
    *,
    provider: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
) -> ExtractedDialog:
    """把一次窗口读取转成结构化对话。

    Args:
        captured: capture 的结果（带 base64 图像）。
        provider: 抽取模型的服务商（None = 解析 DeepSeek 主模型/视觉配置）。
        model: 抽取模型名（None = 同上）。
        timeout: 单次调用超时（秒；None = 默认 30s）。

    Returns:
        ExtractedDialog。失败时 error/error_kind 有值，**不返回空草稿式结果**。
    """
    timeout = timeout or _extract_timeout()
    blocked = _license_block_reason()
    if blocked:
        return ExtractedDialog(error=blocked, error_kind="license")
    if not provider or not model:
        resolved = resolve_extract_model()
        if resolved is None:
            return ExtractedDialog(error=NO_VISION_MESSAGE, error_kind="no_vision")
        provider, model = resolved
    if not captured.has_image():
        # 剪贴板通道没有图像 —— 走纯文本抽取
        return await extract_dialog_from_text(
            captured.text or "", provider=provider, model=model, timeout=timeout,
        )

    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": _EXTRACT_PROMPT},
            {"type": "image_url", "image_url": {"url": captured.image_data_url}},
        ]},
    ]
    return await _call_extract(messages, provider=provider, model=model, timeout=timeout)


async def extract_dialog_from_text(
    text: str, *, provider: str | None = None, model: str | None = None,
    timeout: float | None = None,
) -> ExtractedDialog:
    """纯文本抽取（剪贴板通道）。同样只转录、不回答。"""
    timeout = timeout or _extract_timeout()
    blocked = _license_block_reason()
    if blocked:
        return ExtractedDialog(error=blocked, error_kind="license")
    if not provider or not model:
        resolved = resolve_extract_model()
        if resolved is None:
            return ExtractedDialog(error=NO_VISION_MESSAGE, error_kind="no_vision")
        provider, model = resolved
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
    """调 Hermes 的 vision 通道并解析结果。

    隐私路由铁律：provider/model 必须显式给出；缺失时直接报错，
    不把请求交给 Hermes auto chain，也不换其他服务商重试。
    """
    if not provider or not model:
        return ExtractedDialog(error=NO_VISION_MESSAGE, error_kind="no_vision")
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
        "provider": provider,
        "model": model,
    }

    try:
        response = await async_call_llm(**kwargs)
    except Exception as exc:
        kind, reason = _classify_error(exc)
        _log.warning("副驾抽取调用失败（%s）：%s", kind, exc)
        return ExtractedDialog(error=reason, error_kind=kind)

    raw = _extract_text(response)
    if not raw:
        return ExtractedDialog(error=NO_VISION_MESSAGE, error_kind="no_vision")
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
