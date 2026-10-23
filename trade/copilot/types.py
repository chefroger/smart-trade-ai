"""副驾的数据契约（平台无关）。

刻意用 `dataclass` 而不是 TypedDict/Pydantic：这些对象要能跨线程传递
（capture 在线程、ui 在主线程），且**不得**因为序列化失败而抛异常 ——
副驾的任何一步失败都必须让用户看见"失败原因 + 可重试"，而不是崩在数据层。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# 发言方：customer=对方（客户），me=我方，unknown=分不清
Who = Literal["customer", "me", "unknown"]

# 读取通道
Channel = Literal["clipboard", "screenshot"]

# 单步操作的默认截止时间（秒）。任务书 §2 要求抽取/草稿都在 15s 内给出结果，
# 超时宁可明确报错让用户重试，也不要让悬浮窗一直转圈。
DEFAULT_TIMEOUT = 15.0

# 抽取置信度阈值：低于它 UI 必须提示"识别结果可能不准，请核对"。
CONFIDENCE_THRESHOLD = 0.6


@dataclass
class CapturedWindow:
    """一次读取的结果：窗口身份 + 内存中的图像。

    铁律 6：截图只在内存中处理，抽取完成后立即丢弃 —— 所以这里只带 base64
    字符串（不落盘），且不提供任何"保存到文件"的方法。
    """

    app_name: str = ""
    window_title: str = ""
    channel: Channel = "screenshot"
    # base64 data URL（data:image/png;base64,...）或 None（纯剪贴板通道无图）
    image_data_url: str | None = None
    # 剪贴板通道读到的文本（若有）
    text: str | None = None
    # 读取耗时（毫秒），用于 UI 与日志元数据
    elapsed_ms: int = 0

    def has_image(self) -> bool:
        return bool(self.image_data_url)


@dataclass
class DialogMessage:
    """一条对话消息。"""

    who: Who
    text: str


@dataclass
class ExtractedDialog:
    """视觉抽取的结果。

    `confidence` 是模型自报的抽取置信度（0.0–1.0）。低于阈值时 UI 必须提示
    "识别结果可能不准，请核对"，并且**照样展示原文**，不许吞。
    """

    app: str = ""
    contact: str = ""
    language: str = ""
    messages: list[DialogMessage] = field(default_factory=list)
    confidence: float = 0.0
    # 模型返回的原始文本 —— 解析失败时 UI 要"照样展示原文"（复审 P1-5：
    # 之前错误信息声称原文已保留，但对象里根本没有这个字段）。
    raw: str = ""
    # 抽取失败时的原因（给 UI 展示；成功时为空）
    error: str = ""
    # 错误分类：""（无错）/ "parse"（模型输出不是有效 JSON）/ "empty"（没有可抽取
    # 的文本）/ "protocol"（服务商不兼容）/ "no_vision"（模型不支持看图）/ "other"
    error_kind: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def low_confidence(self) -> bool:
        """成功但置信度低于阈值 —— UI 据此提示"可能不准，请核对"。"""
        return self.ok and self.confidence < CONFIDENCE_THRESHOLD

    def latest_from_customer(self) -> DialogMessage | None:
        """客户侧最后一条消息（草稿的输入）。"""
        for msg in reversed(self.messages):
            if msg.who == "customer":
                return msg
        return None

    def full_text(self) -> str:
        """整段对话的纯文本（供上下文组装与 UI 展示原文）。"""
        return "\n".join(f"{m.who}: {m.text}" for m in self.messages if m.text)


@dataclass
class SourceRef:
    """一条出处：数字来自哪个库的哪条记录。"""

    # 出处文字（文档名 / 客户档案字段名）
    label: str = ""
    # 该出处支撑的具体数字（价格、MOQ、规格…）
    value: str = ""


@dataclass
class CustomerContext:
    """客户匹配的上下文。

    铁律 4：匹配低于阈值 → `matched=False` + `new_contact=True`，**不带任何既有
    客户的历史**。宁可上下文为空，也不把别家客户的信息带进草稿。
    """

    # 客户库里的客户 id（未命中为 None）
    customer_id: int | None = None
    customer_name: str = ""
    # 是否命中既有客户
    matched: bool = False
    # 是否按新客户处理（未命中，或命中但置信度不足）
    new_contact: bool = True
    # 匹配得分（0–1），用于阈值判断与 UI 展示
    match_score: float = 0.0
    # 该客户近期对话要点（命中才有）
    history: list[str] = field(default_factory=list)
    # 产品库检索到的条目（label + 文本）
    product_entries: list[dict[str, Any]] = field(default_factory=list)
    # 产品库里可引用的数字及其出处（铁律 3：数字只从库里取）
    facts: list[SourceRef] = field(default_factory=list)


@dataclass
class DraftResult:
    """草稿生成的结果。"""

    # 草稿正文（与客户同语种）
    draft: str = ""
    # 一行中文大意
    summary_zh: str = ""
    # 数字出处列表（每条对应草稿里的一个数字）
    sources: list[SourceRef] = field(default_factory=list)
    # 生成失败时的原因（给 UI 展示）
    error: str = ""
    # 是否用了"（待确认）"占位（库里查不到该数字）
    has_placeholder: bool = False

    @property
    def ok(self) -> bool:
        return not self.error
