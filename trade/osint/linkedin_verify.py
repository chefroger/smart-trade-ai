"""
Trade AI Assistant — OSINT Layer 6: LinkedIn 公司页验证。

LinkedIn 是外贸获客的核心渠道。我们不使用容易被反爬屏蔽的 Google 搜索方案，
而是生成精确的 browser_navigate 指令，由 Hermes Agent 通过内置浏览器直接访问
LinkedIn 进行验证，确保稳定可靠。
"""

from __future__ import annotations


def linkedin_company_verify(domain: str, company_name: str) -> dict:
    """生成 LinkedIn 验证的 browser_navigate 指令。

    不直接发起 HTTP 请求（会被反爬），而是返回 Hermes Agent 可直接执行的
    浏览器导航指令。Agent 看到此输出后会依次打开 LinkedIn 页面进行验证。

    Args:
        domain: 公司域名（如 "acme.com"）
        company_name: 公司名称

    Returns:
        {
            "method": "browser_navigate",           # 执行方式
            "domain": str,
            "company_name": str,
            "steps": [
                {"action": "navigate", "url": str, "purpose": str},
                ...
            ],
            "summary_instruction": str,             # LLM 应采取的行动总结
        }
    """
    domain_clean = domain.lower().strip()
    domain_clean = domain_clean.replace("https://", "").replace("http://", "")
    domain_clean = domain_clean.replace("www.", "")
    domain_clean = domain_clean.rstrip("/").split("/")[0]

    # 构建公司名搜索词（URL 编码）
    # 登录墙的搜索页无法直接读（2026-11-21 审计 §1.7：不绕登录），
    # 改为站点限定 dork，由 agent 的 web_search 执行；公司页本身公开，
    # 保留一次直接访问尝试。
    return {
        "method": "browser_navigate",
        "domain": domain_clean,
        "company_name": company_name,
        "steps": [
            {
                "action": "web_search",
                "query": f'site:linkedin.com/company "{company_name}"',
                "purpose": "用搜索引擎定位 LinkedIn 公司页（不登录、不触发反爬）",
            },
            {
                "action": "web_search",
                "query": f'site:linkedin.com/in "{company_name}"',
                "purpose": "核对是否有同名个人主页/员工档案，辅助判断决策链",
            },
            {
                "action": "navigate",
                "url": f"https://www.linkedin.com/company/{domain_clean.split('.')[0]}",
                "purpose": f"尝试直接访问 {domain_clean} 对应的 LinkedIn 公司页（公开页）",
            },
        ],
        "summary_instruction": (
            "请先用 web_search 执行上面的 site:linkedin.com dork，再尝试打开公司页，验证：\n"
            f"1. 公司 '{company_name}'（域名 {domain_clean}）是否有 LinkedIn 公司主页\n"
            "2. 如果有，公司规模（员工数）、所属行业、成立年份\n"
            f"3. 公司主页域名是否与 {domain_clean} 一致\n"
            "4. 综合评估公司在线存在的真实性\n\n"
            "将验证结果填入 OSINT 报告的 ## LinkedIn 部分。"
        ),
    }
