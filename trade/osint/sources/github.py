"""GitHub 公开资料（工单 P2-2）：全名、地点、建号时间、公开仓库数。

- 已知用户名（目标里给了 github.com/<u>）→ 直接查 /users/{u}
- 否则按人名/公司名/域名主干搜索，最多取前 3 个候选 profile，
  用「blog 域名吻合」优先，避免把同名的人挂错。
- 配置了 GITHUB_TOKEN 时带上（未配置按匿名配额，60 次/小时）。
"""

from __future__ import annotations

import os

from trade.osint.sources.base import (
    Fetcher,
    SourceResult,
    TargetContext,
    fetch_json,
    quote,
    skipped,
)

NAME = "github"
LABEL = "GitHub 公开资料"
SEARCH = "https://api.github.com/search/users?q={q}&per_page=5"
USER = "https://api.github.com/users/{login}"


def _headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _score(profile: dict, ctx: TargetContext, hint: str) -> int:
    """候选 profile 与目标的吻合度；域名出现在 blog 里权重最高。"""
    score = 0
    blog = str(profile.get("blog") or "").lower()
    if ctx.domain and ctx.domain.lower() in blog:
        score += 3
    hint_lower = hint.lower()
    for field in ("name", "company"):
        if hint_lower and hint_lower in str(profile.get(field) or "").lower():
            score += 1
    return score


def _facts(profile: dict) -> list[dict]:
    """把 profile 压成报告可引用的事实。"""
    login = profile.get("login") or ""
    name = profile.get("name") or login
    location = profile.get("location") or ""
    created = str(profile.get("created_at") or "")[:10]
    repos = profile.get("public_repos")
    followers = profile.get("followers")

    parts = [f"账号：{name}（{login}）"]
    if location:
        parts.append(f"地点：{location}")
    if created:
        parts.append(f"建号：{created}")
    if isinstance(repos, int):
        parts.append(f"公开仓库：{repos}")
    if isinstance(followers, int):
        parts.append(f"关注者：{followers}")
    return [{
        "text": "，".join(parts),
        "url": f"https://github.com/{login}" if login else "",
    }]


def run(ctx: TargetContext, fetch: Fetcher | None = None) -> SourceResult:
    """按用户名或名称查 GitHub；无可用线索返回 skipped。"""
    hint = (
        ctx.github_username
        or ctx.person_name
        or ctx.company_name
        or ((ctx.domain or "").split(".")[0] if ctx.domain else "")
    ).strip()
    if not hint:
        return skipped(NAME, "没有可用的 GitHub 搜索线索")

    headers = _headers()
    try:
        if ctx.github_username:
            profile = fetch_json(
                USER.format(login=quote(ctx.github_username)),
                fetch=fetch, headers=headers,
            )
            if not isinstance(profile, dict) or "login" not in profile:
                return SourceResult(NAME, "miss", error="GitHub 用户不存在或查询失败")
            return SourceResult(NAME, "hit", facts=_facts(profile), data=profile)

        search = fetch_json(
            SEARCH.format(q=quote(hint)), fetch=fetch, headers=headers,
        )
        items = (search or {}).get("items") if isinstance(search, dict) else None
        if not items:
            return SourceResult(NAME, "miss", error="GitHub 搜索无结果")

        candidates: list[dict] = []
        for item in items[:3]:
            login = item.get("login") if isinstance(item, dict) else None
            if not login:
                continue
            profile = fetch_json(
                USER.format(login=quote(login)), fetch=fetch, headers=headers,
            )
            if isinstance(profile, dict) and profile.get("login"):
                candidates.append(profile)
    except Exception as exc:  # noqa: BLE001
        return SourceResult(NAME, "error", error=f"GitHub 查询失败：{exc}")

    if not candidates:
        return SourceResult(NAME, "miss", error="GitHub 候选资料均不可读")

    best = max(candidates, key=lambda profile: _score(profile, ctx, hint))
    if _score(best, ctx, hint) <= 0:
        # 仅同名、没有任何吻合证据：宁可不报，也不把同名的人挂上去
        return SourceResult(
            NAME, "miss",
            error="GitHub 搜索到同名账号，但无域名/公司吻合，未采用",
        )
    return SourceResult(NAME, "hit", facts=_facts(best), data=best)
