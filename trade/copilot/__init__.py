"""聊天副驾（copilot）—— 平台无关的核心逻辑。

## 这个包是什么

用户在任意聊天软件里谈客户时，按热键 → 副驾读当前窗口可见内容 → 识别客户与上下文
→ 结合产品库与该客户历史 → 生成一版**可采用的草稿**悬浮展示 → 用户自己复制粘贴。

**永不发送**：界面上没有发送按钮，代码里没有任何向聊天软件注入文本的路径
（守卫测试见 tests/test_copilot_guard.py）。

## 模块分层（平台无关 vs 平台相关）

平台无关（纯逻辑，可单测，不许出现任何平台 API）：
    - `types`     数据契约
    - `extract`   截图 → 结构化对话（视觉模型）
    - `context`   客户匹配 + 上下文组装
    - `draft`     草稿生成

平台相关（§11 第 2、3 段实现，本次不做）：
    - `capture`   剪贴板 / 截图读取
    - `hotkey`    全局热键
    - `ui`        悬浮窗
    - `service`   托盘与总开关

## 视觉抽取为什么走 Hermes 的 auxiliary client

`extract` 需要一个"能看图的模型调用"。裸直调（openai SDK + base64）在这个部署形态下
走不通：客户视觉模型配在 `auxiliary.vision`（本机是 `custom:deepseek-vl`），而那个
provider 名**不在 Hermes 的 PROVIDER_REGISTRY、也不在 config 的 custom_providers**
（实跑 `_get_named_custom_provider("deepseek-vl")` → None）—— 裸直调拿不到它的
base_url 与 key。

Hermes 的 `async_call_llm(task="vision", messages=[...])` 则：
    - 自己解析 `auxiliary.vision` / 主模型，走它那套 auto chain（主 provider →
      OpenRouter → Nous → Anthropic → custom），**与 trade 现有视觉能力同源**
      （doctor 的「vision 读图」实测通过，用的就是主模型 deepseek-flash）；
    - 接受标准 OpenAI 格式的 messages，图片以 `image_url` 的 base64 data URL 内联
      （`tools/vision_tools.py:_media_messages`）；
    - 自带超时、温度、图片缩放与错误分类。

所以 `extract` 默认**跟随主模型**（决策 2026-10-22），不在这里另造 provider 解析。
"""

from trade.copilot.types import (
    CapturedWindow,
    CustomerContext,
    DialogMessage,
    DraftResult,
    ExtractedDialog,
    SourceRef,
)

__all__ = [
    "CapturedWindow",
    "CustomerContext",
    "DialogMessage",
    "DraftResult",
    "ExtractedDialog",
    "SourceRef",
]
