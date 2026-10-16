---
name: chat-memory
description: "对话历史长期记忆查询工具。当用户询问之前/上次/以前谈过的内容，或需要调取特定时间段的对话记录时使用。提供时序查询（按今天/本周/本月/全部）和结果筛选能力。此技能不主动注入历史——Agent 通过此技能的工具描述自行判断调用时机。"
when_to_use:
  - "用户询问「之前」「上次」「以前」谈过的内容"
  - "需要调取特定时间段的对话记录"
  - "用户重复出现的话题，Agent 无法从当前上下文回忆"
  - "需要了解用户长期偏好 / 过往订单历史"
  - "不要用于：跨公司查询（按公司隔离）"
triggers:
  - 之前
  - 上次
  - 以前
  - 那天
  - 昨天
  - 前天
  - 上周
  - 上礼拜
  - 上上周
  - 这个月
  - 本月
  - 上个月
  - 上个月初
  - 上个月底
  - 今年
  - 今年年初
  - 去年
  - 前几个月
  - 几个月前
  - 再上一周
  - 历史
  - 记录
  - 对话
  - 说过
  - 聊过
  - 讨论过
  - 还记得
  - 记不记得
  - 回忆
  - 翻看
  - 回去看
  - 过去
  - 往事
  - 曾经
  - 上次聊天
  - 上次对话
  - 之前提到
  - 之前说过
  - 历史记录
  - 历史对话
  - 聊天记录
  - 对话记录
  - 聊天历史
  - 帮我找
  - 查一下之前
  - 帮我查
  - 看到过
  # 英文
  - yesterday
  - last week
  - this week
  - last month
  - this month
  - last year
  - this year
  - a few months ago
  - early this year
category: 系统工具
version: "1.0.0"
author: Foreign Trade Assistant
injection_prompt: |
  你是 chat-memory 技能。当用户需要查询历史对话时，主动调用以下工具。
  不要等到用户说"查历史"才行动——只要用户的问题涉及过去讨论过的内容，就立即查询。

  **company_id 必填**，必须从 system prompt 的 Trade Context 段读取；**不要**让用户输入或自己编。

  **触发词 → time_range 映射（必须严格按这张表传）**：
  - 今天 / today           → time_range=today
  - 昨天 / yesterday       → time_range=yesterday
  - 这周 / 本周 / this week  → time_range=this_week
  - 上周 / 上礼拜 / last week → time_range=last_week
  - 这个月 / 本月 / this month → time_range=this_month
  - 上个月 / 上个月底 / last month → time_range=last_month
  - 今年 / 今年年初 / this year → time_range=this_year
  - 去年 / last year       → time_range=last_year

  **枚举表达不了的相对区间**（"上上周三""3 月初""前几个月""再上一周"）：
  - 上上周/上上周三/再上一周 → recent_days=14
  - 前几个月                 → recent_months=N（N=2..6）
  - 3 月初                    → recent_months=2 或 3
  - 算不出                   → recent_days=30 兜底

  **recent_days 与 recent_months 互斥**（与 time_range 也互斥，二选一）。

  调用方式：chat_memory_list(company_id=<从 Trade Context 段读>, time_range="all", limit=20)
  最近模式：chat_memory_list(company_id=N, recent_days=14, limit=20)
  结果格式：[{created_at, query, response}, ...]
  每次对话只能调用一次此工具。
---
# Chat Memory — 对话长期记忆

## 功能定位

查询本公司（company_id）下的历史对话记录。

## 工具

### chat_memory_list

**描述**：查询历史对话记录。当用户提到"之前""上次""以前"等时间相关词汇，
或询问过去讨论过的内容时使用此工具。

**参数**：
- `company_id` (**必填**): 当前会话的公司 ID。从 system prompt 的 Trade Context 段读取；不要让用户输入。
- `time_range`: 时间范围枚举值（与 `recent_days`/`recent_months` 互斥）
  - `"today"` — 今天（00:00 → 现在）
  - `"yesterday"` — 昨天（昨天 00:00 → 今天 00:00）
  - `"this_week"` — 本周（本周一 00:00 → 现在）
  - `"last_week"` — 上周（上周一 00:00 → 本周一 00:00）
  - `"this_month"` — 本月（本月 1 号 00:00 → 现在）
  - `"last_month"` — 上月（上月 1 号 00:00 → 本月 1 号 00:00）
  - `"this_year"` — 今年（今年 1 月 1 日 00:00 → 现在）
  - `"last_year"` — 去年（去年 1 月 1 日 00:00 → 今年 1 月 1 日 00:00）
  - `"all"` — 全部历史（默认）
- `recent_days`: 可选，过去 N 天（含今天）。用于枚举表达不了的相对区间（"上上周三" → 14）。
- `recent_months`: 可选，过去 N 个月（含本月）。用于 "前几个月" 这类模糊词。
- `limit`: 最大返回消息数，默认 20

**返回值**：
```json
{
  "company_id": 1,
  "time_range": "last_week",
  "recent_days": null,
  "recent_months": null,
  "count": 5,
  "rows": [
    {"id": 123, "query": "...", "response": "...", "created_at": "2026-05-10T14:32:00"}
  ]
}
```

## 使用示例

**用户**："你上次推荐的那个供应商叫什么名字？"

→ 调用 `chat_memory_list(company_id=1, time_range="all", limit=20)`
→ 从结果中找到与供应商相关的对话
→ 回答用户问题

**用户**："我们这周谈过哪些客户？"

→ 调用 `chat_memory_list(company_id=1, time_range="this_week", limit=20)`
→ 汇总结果中涉及客户的对话
→ 回答用户问题

**用户**："上礼拜三跟你说过那个德国客户叫什么来着？"

→ 枚举表达不了，用 `recent_days=14`（覆盖"上上周三"到今天）：
→ `chat_memory_list(company_id=1, recent_days=14, limit=20)`

**用户**："前几个月有没有谈到 XXX？"

→ 模糊时间词，用 `recent_months=3`：
→ `chat_memory_list(company_id=1, recent_months=3, limit=20)`
