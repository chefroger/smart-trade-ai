"""聊天副驾伴随服务（编排层）。

**默认关闭**：只有用户显式开启且看过隐私说明后，才注册热键、才读取。
本模块不负责启动 Trade；接入启动流程是单独一步（且在全功能完工前不做）。

流程：热键/按钮 → capture → extract → context → draft → ui。
任一步失败都返回结构化错误，绝不用空草稿或编造内容兜底。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from trade.copilot.settings import CopilotSettings, load_settings, save_settings

_log = logging.getLogger(__name__)


@dataclass
class CopilotEvent:
    """一次触发的结构化结果（给 ui / 日志用）。"""

    ok: bool = False
    stage: str = ""
    error: str = ""
    notice: str = ""
    captured: Any = None
    extracted: Any = None
    context: Any = None
    draft: Any = None
    confirmation: str = ""
    sources: list[Any] = field(default_factory=list)


class CopilotService:
    """副驾编排器。默认关闭；`enable()` 需要同意版本。"""

    def __init__(
        self,
        company_id: int,
        *,
        settings: CopilotSettings | None = None,
        settings_path=None,
        capture_fn: Callable[..., Any] | None = None,
        extract_fn: Callable[..., Any] | None = None,
        build_context_fn: Callable[..., Any] | None = None,
        draft_fn: Callable[..., Any] | None = None,
        ui=None,
        hotkey_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.company_id = company_id
        self.settings = settings or load_settings(settings_path)
        self.settings_path = settings_path
        self._capture_fn = capture_fn
        self._extract_fn = extract_fn
        self._build_context_fn = build_context_fn
        self._draft_fn = draft_fn
        self.ui = ui
        self._hotkey_factory = hotkey_factory
        self._hotkey = None
        self._paused = False
        self._lock = threading.Lock()

    # ── 开关 / 生命周期 ────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enabled and self.settings.consent_ok())

    @property
    def paused(self) -> bool:
        return self._paused

    def enable(self) -> tuple[bool, str]:
        """用户显式开启；未看过隐私说明（consent_version 不足）直接拒绝。"""
        if not self.settings.can_enable():
            return False, "请先阅读并同意副驾隐私说明。"
        self.settings.enabled = True
        save_settings(self.settings, self.settings_path)
        ok, reason = self.start_hotkey()
        return True, "" if ok else reason

    def disable(self) -> None:
        self.settings.enabled = False
        save_settings(self.settings, self.settings_path)
        self.stop_hotkey()

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def start_hotkey(self) -> tuple[bool, str]:
        """注册全局热键；失败只返回原因（降级为按钮触发）。"""
        if not self.enabled:
            return False, "副驾未开启。"
        if self._hotkey is not None:
            return True, ""
        try:
            if self._hotkey_factory is not None:
                hotkey = self._hotkey_factory(self._trigger_from_hotkey)
            else:
                from trade.copilot.hotkey import HotkeyListener

                hotkey = HotkeyListener(
                    self._trigger_from_hotkey, self.settings.hotkey
                )
            ok, reason = hotkey.start()
        except Exception as exc:
            return False, f"热键初始化失败：{exc}"
        if ok:
            self._hotkey = hotkey
        return ok, reason

    def stop_hotkey(self) -> None:
        hotkey, self._hotkey = self._hotkey, None
        if hotkey is not None:
            try:
                hotkey.stop()
            except Exception:
                pass

    def _trigger_from_hotkey(self) -> None:
        """热键线程 → 独立线程跑一次异步流程。"""
        threading.Thread(target=lambda: asyncio.run(self.trigger()), daemon=True).start()

    # ── 主流程 ────────────────────────────────────────────────────────

    async def trigger(self) -> CopilotEvent:
        if not self.enabled:
            return CopilotEvent(stage="gate", error="副驾未开启。")
        if self._paused:
            return CopilotEvent(stage="gate", error="副驾已暂停。")

        captured = await asyncio.to_thread(self._capture)
        if not captured.ok:
            return CopilotEvent(
                stage="capture",
                error=captured.error or "读取失败。",
                notice=getattr(captured, "notice", ""),
                captured=captured,
            )

        extracted = await self._extract(captured)
        if not extracted.ok:
            return CopilotEvent(
                stage="extract",
                error=extracted.error or "识别失败。",
                captured=captured,
                extracted=extracted,
            )

        message = extracted.latest_from_customer()
        if message is None or not (message.text or "").strip():
            return CopilotEvent(
                stage="extract",
                error="没有识别到客户消息。",
                captured=captured,
                extracted=extracted,
            )

        ctx = await asyncio.to_thread(self._build_context, extracted)
        if getattr(ctx, "needs_confirmation", False):
            return CopilotEvent(
                ok=False,
                stage="confirm",
                confirmation=getattr(ctx, "confirmation_question", "")
                or "请先确认客户身份。",
                captured=captured,
                extracted=extracted,
                context=ctx,
            )

        draft = await asyncio.to_thread(self._draft, message.text, ctx)
        if not draft.ok:
            return CopilotEvent(
                stage="draft",
                error=draft.error or "草稿生成失败。",
                captured=captured,
                extracted=extracted,
                context=ctx,
                draft=draft,
            )

        event = CopilotEvent(
            ok=True,
            stage="done",
            notice=getattr(captured, "notice", ""),
            captured=captured,
            extracted=extracted,
            context=ctx,
            draft=draft,
            sources=list(getattr(draft, "sources", []) or []),
        )
        self._show(event)
        return event

    def _capture(self):
        if self._capture_fn is not None:
            return self._capture_fn(
                use_clipboard=self.settings.use_clipboard,
                max_clipboard_chars=self.settings.clipboard_max_chars,
                refused_apps=tuple(self.settings.refused_apps),
            )
        from trade.copilot.capture import capture_conversation

        return capture_conversation(
            use_clipboard=self.settings.use_clipboard,
            max_clipboard_chars=self.settings.clipboard_max_chars,
            refused_apps=tuple(self.settings.refused_apps),
        )

    async def _extract(self, captured):
        if self._extract_fn is not None:
            result = self._extract_fn(captured)
            if asyncio.iscoroutine(result):
                return await result
            return result
        from trade.copilot.extract import extract_dialog

        return await extract_dialog(captured)

    def _build_context(self, extracted):
        if self._build_context_fn is not None:
            return self._build_context_fn(extracted)
        from trade.copilot.context import build_context

        return build_context(
            extracted.contact,
            company_id=self.company_id,
            product_keywords=extracted.full_text(),
        )

    def _draft(self, message_text: str, ctx):
        if self._draft_fn is not None:
            return self._draft_fn(message_text, ctx)
        from trade.copilot.draft import generate_draft

        return generate_draft(message_text, ctx, company_id=self.company_id)

    def _show(self, event: CopilotEvent) -> None:
        if self.ui is None:
            return
        try:
            self.ui.show_result(
                draft=event.draft.draft,
                summary=event.draft.summary_zh,
                sources=event.sources,
                notice=event.notice,
            )
        except Exception as exc:
            _log.warning("显示副驾草稿失败：%s", exc)
