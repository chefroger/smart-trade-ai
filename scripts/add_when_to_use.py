#!/usr/bin/env python3
"""给所有 37 个 SKILL.md 加 when_to_use 字段。

策略：
- 从 description 提炼"何时用"
- 从 category 推导"不要用于"
- 保留原有 frontmatter + body 不动
- 在 description 后插入 when_to_use

生成规则：
- triggers 关键词 → 3-5 条"用户说...时"场景
- 通用兜底：基于 description 拆解
- "不要用于"基于 category 互斥关系
"""
import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


# ─────────────────────────────────────────────────────────────────────────────
# 每个 skill 的 when_to_use 配置（手工精写，确保质量）
# key = skill 目录名
# value = when_to_use 列表
# ─────────────────────────────────────────────────────────────────────────────

WHEN_TO_USE = {
    "b2b-osint": [
        "用户提到「背景调查」「背调」「尽职调查」「due diligence」",
        "用户粘贴公司名 / 域名 / 邮箱要求验证真伪",
        "用户询问「这家公司是真的吗」「客户是不是骗子」",
        "签合同 / 大额订单前要求风险评估",
        "用户提到 OFAC / 制裁名单 / 风险评估",
        "不要用于：邮箱营销列表批量验证（用 b2b-email-intel）",
    ],
    "b2b-email-intel": [
        "用户提供单个邮箱地址要求查背景",
        "用户询问「这个邮箱是不是企业邮箱」",
        "需要判断邮箱是 Gmail/Yahoo 还是公司域名",
        "批量验证邮箱是否有效（建议 ≤500 封/次）",
        "用户提到「邮箱检测」「邮箱真实性」",
        "不要用于：完整公司背调（用 b2b-osint）",
    ],
    "b2b-lead-generation": [
        "用户提到「找客户」「开发客户」「开发信」",
        "需要多通道搜索客户（Google Maps / LinkedIn / Facebook / 海关数据）",
        "生成询盘回复 / 报价谈判 / 跟进邮件",
        "分析 B2B 平台（阿里国际站 / 中国制造网）的潜在客户",
        "用户粘贴产品 / 公司资料要求找潜在买家",
        "不要用于：单一客户深度画像（用 b2b-customer-intel）",
    ],
    "b2b-document": [
        "用户提供 PDF / Word / Excel / PPT 要求分析",
        "读取报价单 / 合同 / 产品规格书 / 装箱单",
        "提取文档关键数据生成结构化摘要",
        "对比多份文档的差异",
        "用户提到「分析文档」「看合同」「读报价」",
        "不要用于：生成新文档（用 b2b-doc-generation）",
    ],
    "b2b-doc-generation": [
        "用户要求生成报价单 / PI / 合同 / 商业提案",
        "一键生成 DOCX / XLSX / PPTX 格式文档",
        "需要可下载的单证模板",
        "用户提到「做一份报价」「生成合同」「导出 PPT」",
        "不要用于：读取现有文档内容（用 b2b-document）",
    ],
    "b2b-platform": [
        "分析阿里国际站 / 中国制造网 / TradeKey 产品页面",
        "输出 B2B 平台产品优化建议",
        "用户提到「阿里国际站」「中国制造网」「平台诊断」",
        "不要用于：Amazon / eBay / Shopify（用各平台专用 skill）",
    ],
    "b2b-linkedin-marketing": [
        "优化 LinkedIn 个人 Profile",
        "生成 LinkedIn 内容日历 / 文章 / InMail",
        "用户提到「LinkedIn 运营」「领英开发」",
        "不要用于：Facebook / Instagram / TikTok（用 b2b-social-media）",
    ],
    "b2b-social-media": [
        "生成 Facebook / Instagram / TikTok / YouTube 内容日历",
        "规划海外社媒运营策略",
        "用户提到「社媒运营」「Facebook 发帖」「TikTok 内容」",
        "不要用于：LinkedIn 运营（用 b2b-linkedin-marketing）",
    ],
    "b2b-customs-data": [
        "分析海关进出口数据",
        "筛选高价值采购商",
        "做市场调研 / 竞品分析",
        "用户提到「海关数据」「采购商」「进出口」",
        "不要用于：客户公司真伪验证（用 b2b-osint）",
    ],
    "b2b-onboarding": [
        "首次使用系统的新用户引导",
        "用户首次进入需要「创建公司 → 体验 OSINT + 开发信」",
        "用户说「不会用」「新手」",
        "不要用于：已熟悉系统的老用户",
    ],
    "b2b-daily-automation": [
        "配置工作日自动化任务（早报 / 开发信 / 社媒 / 每日总结）",
        "用户提到「定时任务」「自动发邮件」「cron」",
        "不要用于：单次执行的任务",
    ],
    "b2b-customer-mgmt": [
        "客户 A/B/C 分级管理",
        "客户详情面板 + 文档库关联",
        "CSV 批量导入 + 去重",
        "用户提到「客户管理」「分级」「导入客户」",
        "不要用于：单个客户深度画像（用 b2b-customer-intel）",
    ],
    "b2b-data-directory": [
        "结构化管理产品 / 客户 / 报价 / 合同 / 认证 / 物流知识库",
        "用户提到「数据目录」「知识库管理」",
        "不要用于：实时数据分析（用 b2b-market-analysis）",
    ],
    "chat-memory": [
        "用户询问「之前」「上次」「以前」谈过的内容",
        "需要调取特定时间段的对话记录",
        "用户重复出现的话题，Agent 无法从当前上下文回忆",
        "需要了解用户长期偏好 / 过往订单历史",
        "不要用于：跨公司查询（按公司隔离）",
    ],
    "b2b-skill-generator": [
        "用户要求「生成 skill」「创建 skill」「新增技能」",
        "用自然语言描述需求生成新 B2B Skill",
        "用户提到「做个新技能」「自动生成」",
        "不要用于：修改现有 skill",
    ],
    "b2b-trade-ops": [
        "履约运营：催款 / 索赔 / 展会 / 验厂 / 物流 / 售后",
        "用户提到「催款」「索赔」「展会」「验厂」「物流」「售后」",
        "生成年度总结 / 满意度报告",
        "不要用于：客户开发阶段",
    ],
    "b2b-trade-compliance": [
        "文化禁忌检查 / 缩写规范 / ICC 术语",
        "翻译二审 / 投标合规",
        "电商上架合规检查",
        "用户提到「合规」「翻译二审」「ICC 术语」",
        "不要用于：关税 / HS Code（用 b2b-customs-data）",
    ],
    "b2b-customer-finder": [
        "用户说「傻瓜式找客户」「一键找客户」「快速开发客户」",
        "新手不会自己找客户，要求三问启动",
        "用户问「怎么找客户」「找客户太难了」",
        "不要用于：深度客户开发（用 b2b-lead-generation）",
    ],
    "b2b-customer-intel": [
        "用户提供单一客户要求做 15 维深度画像",
        "用户问「这个客户什么性格」「决策风格」「送礼建议」",
        "分析客户决策链 / 采购偏好 / 社交风格",
        "用户提到「客户画像」「客户档案」「客户情报」",
        "不要用于：批量客户分析（用 b2b-customer-mgmt）",
    ],
    "b2b-buyer-persona": [
        "按决策角色（采购 / 技术 / 老板）分层定制 FAB 价值主张",
        "针对不同买家类型调整沟通策略",
        "用户提到「买家画像」「决策角色」「FAB」",
        "不要用于：客户深度画像（用 b2b-customer-intel）",
    ],
    "b2b-cold-outreach": [
        "生成个性化开发信 / 推广信 / 跟进信",
        "邮件语言匹配目标客户国家",
        "反垃圾规则 + 产品参数速查",
        "用户提到「冷邮件」「cold email」「推广信」",
        "不要用于：询盘回复（用 b2b-lead-generation）",
    ],
    "b2b-email-imitation": [
        "用户提供优秀邮件样本要求「仿写」",
        "分析邮件的 AIDA 结构 + 语气",
        "应用到自家产品生成新邮件",
        "用户提到「仿写邮件」「学习这封邮件」",
        "不要用于：零样本生成（用 b2b-cold-outreach）",
    ],
    "b2b-kol-imitation": [
        "用户指定 KOL / 网红要求模仿其风格",
        "生成「像 XXX」风格的文案",
        "用户提到「模仿 KOL」「学习 XXX 风格」",
        "不要用于：原创内容生成（用 b2b-social-media）",
    ],
    "b2b-reddit-engagement": [
        "Reddit 帖子营销 / 评论引流",
        "生成符合 Reddit 文化的回复",
        "用户提到「Reddit 营销」「reddit 推广」",
        "不要用于：Facebook / LinkedIn（用对应 skill）",
    ],
    "b2b-product-description": [
        "生成 Amazon / Shopify / 独立站产品描述",
        "针对不同平台调优文案风格",
        "用户提到「产品描述」「listing 文案」",
        "不要用于：产品选品（用 b2b-market-analysis）",
    ],
    "b2b-exhibition": [
        "展会前准备（资料 / 样品 / 名片）",
        "展会期间客户跟进与记录",
        "展后客户分级与跟进",
        "用户提到「参展」「广交会」「展会」",
        "不要用于：在线 B2B 平台",
    ],
    "b2b-inquiry-training": [
        "双 AI 对抗训练（模拟买家 vs 生成回复）",
        "迭代打磨询盘回复至 9.5 分",
        "用户提到「询盘回复训练」「AI 模拟买家」",
        "不要用于：直接询盘回复（用 b2b-lead-generation）",
    ],
    "b2b-market-analysis": [
        "目标国认证要求 / 关税政策",
        "关键词武器库 / 3 秒 Hook 等系统化市场进入策略",
        "用户提到「市场分析」「市场进入」「认证要求」",
        "不要用于：海关数据查询（用 b2b-customs-data）",
    ],
    "b2b-sales-pipeline": [
        "客户旅程 5 阶段映射",
        "30 天跟进表 + KPI 追踪",
        "管线健康度看板",
        "用户提到「销售管线」「pipeline」「KPI」",
        "不要用于：单次客户跟进",
    ],
    "b2b-seo-aeo": [
        "Google SEO + AEO（Answer Engine Optimization）",
        "针对 AI 搜索（ChatGPT / Perplexity）优化内容",
        "用户提到「SEO」「AEO」「AI 搜索优化」",
        "不要用于：付费广告投放",
    ],
    "b2b-short-video": [
        "生成 TikTok / Instagram Reels / YouTube Shorts 脚本",
        "短视频带货脚本与分镜",
        "用户提到「短视频脚本」「tiktok 带货」",
        "不要用于：长视频脚本",
    ],
    "b2b-six-thinking-hats": [
        "用六顶思考帽做多角度分析",
        "团队决策 / 复杂问题拆解",
        "用户提到「六顶思考帽」「多角度分析」",
        "不要用于：单一视角结论性判断",
    ],
    "auto-smtp-email": [
        "配置自动 SMTP 发邮件",
        "用户提到「自动发邮件」「smtp 配置」",
        "不要用于：手动单封邮件（用 b2b-cold-outreach）",
    ],
    "auto-trade-customer-development": [
        "全自动客户开发流水线",
        "定时搜索 + 自动生成开发信 + 自动发送",
        "用户提到「自动开发客户」「流水线」",
        "不要用于：人工介入的高价值客户（用 b2b-lead-generation）",
    ],
}


# YAML block scalar 安全字符正则
def _yaml_escape_item(s: str) -> str:
    """转义 YAML list item 中的特殊字符。"""
    # 双引号包裹，避免冒号/中文标点/特殊字符问题
    return f'"{s.replace(chr(34), chr(92)+chr(34))}"'


def _format_when_to_use(items: list[str]) -> str:
    """生成 YAML list 文本。"""
    lines = ["when_to_use:"]
    for item in items:
        # 拆行：如果 > 80 字符，保留整行（YAML 多行字符串用 >- 或直接 quoted）
        lines.append(f"  - {_yaml_escape_item(item)}")
    return "\n".join(lines)


def patch_skill(skill_md: Path) -> bool:
    """在 SKILL.md frontmatter 中插入 when_to_use 字段。

    插入位置：description 之后、triggers 之前。
    如果已有 when_to_use，跳过。
    """
    text = skill_md.read_text(encoding="utf-8")

    # 已有 when_to_use → 跳过
    if re.search(r"^when_to_use:", text, re.MULTILINE):
        return False

    skill_name = skill_md.parent.name
    if skill_name not in WHEN_TO_USE:
        print(f"⚠️  跳过（无配置）: {skill_name}")
        return False

    items = WHEN_TO_USE[skill_name]
    when_block = _format_when_to_use(items)

    # 在 `description: ...` 这一行后插入 when_to_use
    # description 是单行（项目约定）
    pattern = re.compile(r"^(description:[^\n]*\n)", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        print(f"⚠️  找不到 description: {skill_name}")
        return False

    # 插入
    new_text = text[:match.end()] + when_block + "\n" + text[match.end():]

    skill_md.write_text(new_text, encoding="utf-8")
    return True


def main():
    patched = 0
    skipped = 0
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        if patch_skill(skill_md):
            patched += 1
        else:
            skipped += 1
    print(f"✅ 新增 when_to_use: {patched} 个")
    print(f"⏭️  跳过: {skipped} 个（已存在 or 无配置）")


if __name__ == "__main__":
    main()
