---
name: auto-smtp-email
description: "(已禁用) SMTP 邮件发送 — 此 skill 已被禁用，不会被系统触发"
when_to_use:
  - "配置自动 SMTP 发邮件"
  - "用户提到「自动发邮件」「smtp 配置」"
  - "不要用于：手动单封邮件（用 b2b-cold-outreach）"
triggers:
  - 发邮件
  - 发送邮件
  - SMTP 发送
  - 发开发信
  - 群发邮件
  - 批量发送
  - 预览后发送
  - send email
  - smtp send
  - send cold email
  - bulk send
  - mail out
  - 帮我发
  - 发出去
category: 系统工具
version: 1.0.0
author: Trade
injection_prompt: |
  此技能已被 Trade 停用（auto-smtp-email 不在安装清单里，也不会被路由触发）。

  **不要调用 SMTP / smtplib，不要读取或写入 SMTP 凭证，也不要自动发送任何邮件。**

  需要发邮件时：用 b2b-cold-outreach 生成草稿，由用户自己复制发送。
---
