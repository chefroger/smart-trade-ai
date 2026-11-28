"""Gravatar 公开资料（工单 P2-2）：邮箱哈希对应的公开头像/简介。

只查公开 profile，不需要邮箱本身出现在结果里（接口按 SHA-256 查询）。
"""

from __future__ import annotations

import hashlib

from trade.osint.sources.base import (
    Fetcher,
    SourceResult,
    TargetContext,
    error_result,
    fetch_json,
    skipped,
)

NAME = "gravatar"
LABEL = "Gravatar 公开资料"
URL = "https://api.gravatar.com/v3/profiles/{hash}"


def _hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult:
    """查 Gravatar；无邮箱目标返回 skipped。"""
    if not ctx.email:
        return skipped(NAME, "目标不是邮箱")

    url = URL.format(hash=_hash(ctx.email))
    try:
        payload = fetch_json(url, fetch=fetch)
    except Exception as exc:  # noqa: BLE001
        if "404" in str(exc):
            return SourceResult(NAME, "miss", error="该邮箱没有 Gravatar 公开资料")
        return error_result(NAME, exc)
    if not isinstance(payload, dict):
        return SourceResult(NAME, "miss", error="该邮箱没有 Gravatar 公开资料")

    display = str(payload.get("display_name") or "").strip()
    location = str(payload.get("location") or "").strip()
    about = " ".join(str(payload.get("about_me") or "").split())[:160]
    profile_url = str(payload.get("profile_url") or "").strip()

    parts = []
    if display:
        parts.append(f"显示名：{display}")
    if location:
        parts.append(f"地点：{location}")
    if about:
        parts.append(f"简介：{about}")
    if not parts:
        return SourceResult(NAME, "miss", error="Gravatar 资料为空")

    # 审计 P1-D：邮箱哈希只能说明「该邮箱注册过 Gravatar」，不能证明
    # 画像属于背调对象本人 —— 保留内容但标为候选，不当作命中。
    return SourceResult(
        NAME,
        "candidate",
        facts=[{
            "text": "同名候选，未核实（Gravatar 邮箱画像）：" + "，".join(parts),
            "url": profile_url or "https://gravatar.com/",
        }],
        data={"display_name": display, "location": location, "about": about},
        error="Gravatar 画像未与目标独立核实",
    )
