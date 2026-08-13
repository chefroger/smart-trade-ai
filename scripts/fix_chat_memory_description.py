#!/usr/bin/env python3
"""修复 chat-memory 的多行 description 块标量 → 单行 + 加 when_to_use。

不依赖通用正则（chat-memory 的多行内容含双引号干扰），用针对性硬编码修复。
"""
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def main():
    skill_md = SKILLS_DIR / "chat-memory" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")

    # 旧 frontmatter（已知结构）
    # ---
    # name: chat-memory
    # description: >
    #   对话历史长期记忆查询工具。...
    #   ...
    #   ...自行判断调用时机。
    # triggers: []
    # category: b2b-sales
    # version: "1.0.0"
    # author: Foreign Trade Assistant
    # injection_prompt: |

    # 目标：
    # ---
    # name: chat-memory
    # description: "对话历史长期记忆查询工具。当用户询问之前/上次/以前谈过的内容..."
    # when_to_use:
    #   - "..."
    # triggers: []

    old_block = '''---
name: chat-memory
description: >
  对话历史长期记忆查询工具。当用户询问"之前""上次""以前"谈过的内容，
  或需要调取特定时间段的对话记录时使用。
  提供时序查询（按今天/本周/本月/全部）和结果筛选能力。
  此技能不主动注入历史——Agent 通过此技能的工具描述自行判断调用时机。
triggers: []'''

    new_block = '''---
name: chat-memory
description: "对话历史长期记忆查询工具。当用户询问之前/上次/以前谈过的内容，或需要调取特定时间段的对话记录时使用。提供时序查询（按今天/本周/本月/全部）和结果筛选能力。此技能不主动注入历史——Agent 通过此技能的工具描述自行判断调用时机。"
when_to_use:
  - "用户询问「之前」「上次」「以前」谈过的内容"
  - "需要调取特定时间段的对话记录"
  - "用户重复出现的话题，Agent 无法从当前上下文回忆"
  - "需要了解用户长期偏好 / 过往订单历史"
  - "不要用于：跨公司查询（按公司隔离）"
triggers: []'''

    if old_block not in text:
        print("❌ 找不到预期块。可能 chat-memory frontmatter 已改动")
        # 看实际内容
        print(text[:500])
        return

    new_text = text.replace(old_block, new_block)
    skill_md.write_text(new_text, encoding="utf-8")
    print("✅ chat-memory 修复完成")


if __name__ == "__main__":
    main()
