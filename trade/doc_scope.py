"""请求范围判定（门禁规则，不是提取器）。

缓存只允许用在两类请求：`summary`（整体概览）与 `locate`（找文件/定位）。
**其余一律 full_read**，这是 fail-closed 的默认值：把 full_read 误判成
summary 等于拿缓存回答具体事实，代价远大于多读一遍。

判定必须保守，且必须要有"文档指代"（文件/文档/资料/目录…）：
- "介绍一下这批资料" → summary
- "哪些文件涉及 LED" → locate
- "介绍一下这批价格文件" → full_read（含"价格"，money 文件一律全文）
- "总结一下我们的优势" → full_read（没有文档指代）
- 任何数字、价格、条款、名单、比较、统计 → full_read

本模块是门禁规则，改动不递增提取器版本；有自己的版本常量与表驱动测试。
"""

from __future__ import annotations

import re

SCOPE_RULES_VERSION = "2"

SCOPE_SUMMARY = "summary"
SCOPE_LOCATE = "locate"
SCOPE_FULL_READ = "full_read"

_SCOPES = frozenset({SCOPE_SUMMARY, SCOPE_LOCATE, SCOPE_FULL_READ})

# 文档指代：没有它就不认为用户是在说"这批文档"，避免普通闲聊误触发门禁。
_DOC_NOUN = r"(?:文件|文档|资料|附件|目录|文件夹|files?|documents?)"

_SUMMARY_PATTERNS = (
    rf"{_DOC_NOUN}.{{0,12}}(?:介绍|概述|概览|讲了什么|主要讲|主要内容|总结|summary|overview)",
    rf"(?:介绍|概述|概览|总结|summary|overview).{{0,12}}{_DOC_NOUN}",
)
_LOCATE_PATTERNS = (
    rf"(?:哪些|哪个|哪一个|在哪|which).{{0,10}}{_DOC_NOUN}",
    rf"{_DOC_NOUN}.{{0,10}}(?:在哪|位置|涉及|相关)",
)
# 出现任一特征就强制 full_read（数字、金额、条款、名单、比较/统计…）。
_FULL_READ_PATTERNS = (
    r"\d",
    r"价格|报价|金额|单价|汇率|折扣|税费|成本|利润|销售额",
    r"条款|合同|规格|参数|型号|交期|有效期|质保|数量阶梯",
    # 付款类与条款序号：审计 P1-2 的漏网问法，一律全文
    r"付款|支付|佣金|定金|尾款|账期|信用期|发票|收款|银行账号?",
    r"第[一二三四五六七八九十百\d]+条",
    # 具体事实类问法：数字/数量/客户等，概览句式也不能降低为 summary
    r"数字|多少|数量|数据|百分比|百分之|客户|供应商|名单",
    r"日期|客户名单|供应商名单",
    r"原文|逐字|引用|比较|统计|计算|核对|核算|汇总表|增长率|占比|合格率",
    # 英文同类事实词（用词边界避免命中 update 等普通单词）
    r"\b(?:prices?|amounts?|dates?|clauses?|quotes?|compar(?:e|ison)|"
    r"percents?|percentages?)\b",
)

# 否定概览句式优先于 summary/locate：如「不要总结，把文档逐条算清楚」。
_NEGATED_OVERVIEW_PATTERNS = (
    r"(?:不要|别|不用|不必|无需)\s*(?:只|再)?\s*(?:总结|概述|概览|摘要)",
    r"\b(?:do\s+not|don'?t)\s+(?:just\s+)?(?:summari[sz]e|overview)\b",
)


def detect_request_scope(query: str) -> str:
    """返回 summary / locate / full_read；无法保守判定时一律 full_read。"""
    text = str(query or "").strip().lower()
    if not text:
        return SCOPE_FULL_READ
    if any(re.search(pattern, text, re.IGNORECASE)
           for pattern in _NEGATED_OVERVIEW_PATTERNS):
        return SCOPE_FULL_READ
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in _FULL_READ_PATTERNS):
        return SCOPE_FULL_READ
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in _LOCATE_PATTERNS):
        return SCOPE_LOCATE
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in _SUMMARY_PATTERNS):
        return SCOPE_SUMMARY
    return SCOPE_FULL_READ


def scope_allows_cache(request_scope: str) -> bool:
    """只有 summary / locate 允许缓存旁路；未知值按 full_read。"""
    return request_scope in {SCOPE_SUMMARY, SCOPE_LOCATE}
