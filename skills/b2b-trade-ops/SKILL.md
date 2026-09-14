---
name: b2b-trade-ops
description: 外贸履约 & 售后 & 运营沟通 — 催款、索赔、展会、验厂、节日问候、样品跟进、物流异常、售后维护、满意度调查、年度总结
when_to_use:
  - "履约运营：催款 / 索赔 / 展会 / 验厂 / 物流 / 售后"
  - "用户提到「催款」「索赔」「展会」「验厂」「物流」「售后」"
  - "生成年度总结 / 满意度报告"
  - "不要用于：客户开发阶段"
triggers:
  - 催款
  - 催货款
  - 催尾款
  - 付款逾期
  - 催一下付款
  - 要货款
  - 客户还没付款
  - 催账
  - 索赔
  - 投诉
  - 质量投诉
  - 货有问题
  - 客户投诉
  - 退货
  - 退款
  - 理赔
  - 赔偿
  - 展会邀请
  - 邀请函
  - 广交会
  - 展会邀约
  - 参展
  - 验厂
  - 客户要来工厂
  - 节日问候
  - 节日祝福
  - 物流异常
  - 售后维护
  - 满意度调查
  - 年度总结
  - 样品寄送
  - 催一下
  - 货到哪里了
  - 交期确认
category: 履约运营
version: 1.0.0
author: Foreign Trade Assistant
injection_prompt: |
  你是 b2b-trade-ops 技能。覆盖外贸业务中「成交之后」的所有运营沟通场景。当用户需要处理以下任意场景时，按对应规则执行。

  ## 场景路由
  - 催款 / 要货款 / 催付尾款 → Phase 1
  - 客户投诉 / 质量索赔 / 货有问题 / 索赔处理 → Phase 2
  - 展会邀请 / 广交会 / 邀请函 → Phase 3
  - 验厂邀请 / 客户要来工厂 / 审核 / audit → Phase 4
  - 节日问候 / 节日祝福 / 客户祝福 → Phase 5
  - 样品寄送 / 寄样 / 样品跟进 → Phase 6
  - 二次催付 / 再催款 / 还没付 → Phase 7
  - 物流异常 / 货运延迟 / 船期 / 航变 / tracking → Phase 8
  - 售后维护 / 收货后跟进 / 安装使用 / after-sales → Phase 9
  - 满意度调查 / 客户反馈 / survey → Phase 10
  - 年度总结 / 年终 / 合作回顾 / annual review → Phase 11

  ## 核心规则
  1. **语言**：输出语言匹配目标客户语言，默认英语
  2. **语气**：始终专业、有温度、不卑不亢。催款时尤其要「先关心再要求」
  3. **发送前自检**：生成任何内容后，对照文末 Quality Gate Checklist 逐项检查

  如果用户意图不明确，先问清楚场景和客户信息再生成。
---

## Phase 1: 催款邮件 (Payment Reminder)

**铁律**：先问对方是否遇到任何问题，再提付款。永远不要上来就催。

### 温和催款（首次逾期 < 7 天）

```
Subject: Checking in — Invoice #[number]

Hi [Name],

Hope everything's going well on your end.

I wanted to check in on invoice #[number] (due [date]) — just making sure
there weren't any issues with the shipment or documentation that might be
holding things up.

If everything's fine, would you be able to process the payment this week?
Happy to resend the invoice if needed.

Thanks,
[Your name]
```

### 友好提醒（逾期 7-14 天）

```
Subject: Quick follow-up — Invoice #[number]

Hi [Name],

I know you're busy — just a gentle nudge on invoice #[number], which is
now [X] days past due.

No worries if there's a specific reason for the delay — if something came
up on your end, let me know and we can figure out a solution together.

Otherwise, I'd appreciate it if you could let me know when we can expect
the payment.

Best,
[Your name]
```

---

## Phase 2: 索赔处理 (Claim Handling)

**铁律**：先道歉并安抚情绪，再谈责任划分。永远不要上来就推责任。

### 标准索赔回复

```
Subject: Regarding your concern — Order #[number]

Dear [Name],

Thank you for bringing this to our attention. I'm very sorry to hear
about [specific issue — damaged goods / quality problem / delay].

I've immediately flagged this with our QC / production / logistics team
to investigate what happened. Here's what I can tell you so far:

[Preliminary findings if any, or "We're reviewing the full production
and inspection records"]

To resolve this quickly for you, here's what I propose:

1. [Immediate fix — replacement / refund / discount on next order]
2. [Root cause investigation — timeline]
3. [Preventive measure — what we'll change going forward]

I take full responsibility for making this right. Can we schedule a
quick call to discuss the details?

Best regards,
[Your name]
```

### 索赔处理要点
- **响应速度**：30 分钟内确认收到投诉，1 小时内给初步方案
- **不争论**：客户说有问题，先认可感受 ("I understand your frustration")
- **给方案**：不要问客户想要什么，你先主动提方案（显得专业且有担当）
- **第三方**：责任不明确时（质量问题 vs 运输损坏），建议 SGS/BV 等第三方检测作为中立依据

---

## Phase 3: 展会邀请 (Exhibition Invitation)

**铁律**：展位号 + 时间 + 「你来了能带走什么」（样品/目录/报价），三要素缺一不可。

```
Subject: [Your Company] at [Exhibition Name] — Booth [Number]

Dear [Name],

Quick heads-up — we'll be exhibiting at [Exhibition Name] this [month],
and I'd love to connect in person if you're attending.

Details:
- Exhibition: [Full name]
- Dates: [Start] — [End]
- Venue: [Name], [City], [Country]
- Our Booth: Hall [X], Booth [Y]

What you can expect at our booth:
- [New product sample 1]
- [New product sample 2]
- Exclusive show-only pricing for existing partners
- Latest product catalog (print + USB)

If you're planning to come, let me know your preferred time slot and
I'll block out time for a private meeting. I can also help with visitor
pre-registration if you need it.

Hope to see you there!

Best regards,
[Your name]
[Phone] | [WeChat/WhatsApp]
```

---

## Phase 4: 验厂邀请 (Factory Audit Invitation)

**铁律**：工厂地址 + 接待人联系方式 + 验厂当天议程，三要素缺一不可。

```
Subject: Factory Visit — [Your Company], [Date]

Dear [Name],

Thank you for your interest in auditing our facility. We'd be happy to
welcome you.

Visit Details:
- Date: [Date]
- Time: [Start time]
- Factory Address: [Full address in both English and local language]
- Contact Person on Site: [Name], [Phone], [WeChat/WhatsApp]

Proposed Agenda:
| Time  | Activity |
|-------|----------|
| 09:00 | Welcome & company introduction |
| 09:30 | Factory tour — raw material → production → QC → packaging |
| 11:00 | Sample room & showroom visit |
| 11:30 | QC process & certification review |
| 12:00 | Working lunch |
| 13:30 | Discussion — requirements, timeline, next steps |
| 14:30 | Wrap-up & departure |

We'll provide:
- Hotel pick-up and drop-off (if needed)
- Lunch
- Sample kit to take home

Please let me know if there are specific areas you'd like to focus on,
or if you have any dietary requirements. Looking forward to meeting you!

Best regards,
[Your name]
```

---

## Phase 5: 节日问候 (Holiday Greetings)

**铁律**：先确认客户确实过那个节日！不要向印度教客户发 Christmas，不要向穆斯林客户发 Lunar New Year。

### 节日对照速查

| 客户所在区域 | 适用节日 | 禁忌 |
|------------|---------|------|
| 欧美/拉美 | Christmas (12/25), New Year (1/1) | 对非基督徒慎发 Christmas，用 "Season's Greetings" |
| 中东/穆斯林 | Eid al-Fitr, Eid al-Adha | 不饮酒祝福、不提及猪肉、不送红酒 |
| 印度 | Diwali (印度教), Holi | 不向穆斯林印度客户发 Diwali |
| 中国/东南亚华人 | Lunar New Year, Mid-Autumn | 不要给非华人客户发 |
| 日本 | New Year (1/1-1/3), Obon | 正式敬语 |
| 韩国 | Seollal, Chuseok | 正式敬语 |
| 以色列/犹太人 | Rosh Hashanah, Passover | 发 Christmas 可能冒犯 |

### 通用安全版

```
Subject: Season's Greetings from [Your Company]

Dear [Name],

As the year draws to a close, I wanted to take a moment to thank you
for your trust and partnership throughout [year].

It's been a pleasure working with you on [specific project or order],
and I look forward to continuing our collaboration in the year ahead.

Wishing you and your team a wonderful holiday season and a prosperous
new year!

Warm regards,
[Your name]
```

---

## Phase 6: 样品寄送跟进 (Sample Shipping Follow-Up)

**铁律**：追踪号 + 预计到达日 + 使用说明，三要素必发。

```
Subject: Your samples are on the way — Tracking #[number]

Dear [Name],

Good news — your samples have been shipped!

Shipping Details:
- Carrier: [DHL / FedEx / UPS / TNT]
- Tracking Number: [number]
- Tracking Link: [URL]
- Estimated Delivery: [Date]

Package Contents:
- [Item 1] × [Qty]
- [Item 2] × [Qty]
- Product catalog & business card

Sample Notes:
[Any specific instructions — how to test, what to look for,
key specs to verify]

I'll follow up with you after delivery to make sure everything arrived
safely. In the meantime, feel free to reach out with any questions.

Best,
[Your name]
```

### 预计到达日 +1 天跟进

```
Subject: Did the samples arrive okay?

Hi [Name],

Just checking — the tracking shows delivery was completed yesterday.
I wanted to make sure everything arrived in good condition.

If you have any questions after reviewing the samples, I'm here to help.
Happy to hop on a call to walk you through anything.

Best,
[Your name]
```

---

## Phase 7: 二次催付 / 折中方案 (Second Payment Reminder)

**铁律**：第一次是「温和提醒」，第二次是「给台阶下」——提供折中方案而非施压。

| 折中方案 | 适用场景 | 话术 |
|---------|---------|------|
| 分两笔付 | 客户现金流紧张 | "Would splitting into two payments help — 50% now, 50% in 30 days?" |
| 延长 3 天 | 客户说"正在安排" | "If an extra 3 days makes it easier, we can extend to [date]." |
| 部分发货 | 急需部分货物 | "We could ship 50% of the order now against partial payment." |

```
Subject: Flexible payment option — Invoice #[number]

Hi [Name],

I understand that cash flow can be tight, especially with everything
going on. I wanted to offer some flexibility on invoice #[number]
(originally due [date]):

Option A: Split into two payments — 50% this week, 50% by [date]
Option B: Extend the deadline by [X] days to [new date]
Option C: Ship a portion of the order against partial payment

Happy to discuss which works best for you. Our goal is to find a
solution that keeps things moving smoothly for both sides.

Best,
[Your name]
```

---

## Phase 8: 物流异常处理 (Logistics Issue)

**铁律**：主动提供船公司官网查询链接 + 本地代理电话，不等客户问。

```
Subject: Shipping update — Order #[number] / Container #[number]

Dear [Name],

I wanted to proactively let you know about a change in the shipping
schedule for your order.

Original Schedule:
- Vessel: [Name]
- ETD: [Date]
- ETA: [Date]

Updated Schedule:
- Vessel: [Name]
- ETD: [Date] (delayed by [X] days due to [reason])
- ETA: [Date]

Tracking Resources:
- Carrier website: [URL]
- Container tracking: [URL with container number]
- Local agent contact: [Name], [Phone], [Email]

I'm monitoring the situation closely and will update you immediately if
anything changes. I've also asked our logistics team to explore
alternative routing if the delay extends further.

My apologies for the inconvenience — I know this impacts your planning.
Rest assured we're doing everything we can on our end.

Best regards,
[Your name]
```

---

## Phase 9: 售后维护 (After-Sales Check-In)

**铁律**：收货后第 7 天主动询问安装/使用情况。不推销、不催单、纯关心。

```
Subject: How's everything working out? — Order #[number]

Hi [Name],

It's been about a week since your order arrived — just wanted to check
in and see how everything's working out.

- Did the products meet your expectations?
- Any issues with installation or usage?
- Anything you'd like us to improve for next time?

No rush on any of this — just making sure you're taken care of.

If anything comes up down the road, you know where to find me.

Best,
[Your name]
```

### 售后跟进时间线

| 时机 | 动作 |
|------|------|
| 收货当天 | 确认签收 |
| 收货第 7 天 | 安装/使用情况询问（本次） |
| 收货第 30 天 | 产品表现反馈 + 温和复购提醒 |
| 收货第 90 天 | 请求评价 / 案例引用许可 |

---

## Phase 10: 满意度调查 (Satisfaction Survey)

**铁律**：5 个选择题以内。承诺改进。不要让客户写作文。

```
Subject: Quick feedback? (5 questions, 2 minutes)

Hi [Name],

As part of our commitment to continuous improvement, I'd love your
quick feedback on our recent collaboration. Just 5 multiple-choice
questions — should take 2 minutes.

1. Product quality vs expectations?
   [ ] Exceeded  [ ] Met  [ ] Below

2. Communication & responsiveness?
   [ ] Excellent  [ ] Good  [ ] Needs improvement

3. On-time delivery?
   [ ] On time  [ ] Slightly delayed  [ ] Significantly delayed

4. Packaging condition upon arrival?
   [ ] Perfect  [ ] Minor issues  [ ] Damaged

5. Likelihood to order again?
   [ ] Definitely  [ ] Maybe  [ ] Unlikely

Any additional comments are welcome but entirely optional.

Your feedback directly shapes how we improve — I personally review
every response and will act on what you share.

Thank you for your trust and partnership!

Best,
[Your name]
```

---

## Phase 11: 年度合作总结 (Annual Review)

**铁律**：用数据代替空话。降价幅度、返单率、交付准点率——数字比感情有用。

```
Subject: [Year] in Review — Thank You for a Great Year

Dear [Name],

As [year] comes to a close, I wanted to share a quick recap of our
collaboration this year — and thank you for being a valued partner.

Our Year in Numbers:
- Total orders: [X]
- Total value: [Amount]
- Products delivered: [X] units across [Y] SKUs
- On-time delivery rate: [X]%
- Average lead time: [X] days
- Quality pass rate: [X]% first inspection

What's New for [next year]:
- [New product/capability 1]
- [New certification 1]
- [Process improvement 1]

Looking Ahead:
Based on this year's trends, I'd suggest we plan for:
- [Specific recommendation based on data]

Thank you again for your trust — it means a lot to our entire team.
Here's to an even better [next year]!

Warm regards,
[Your name]
```

---

## Quality Gate Checklist — 运营邮件发送前 30 秒自检

> 每次生成运营类邮件前，对照对应场景逐条检查。漏掉任何一项都意味着专业度打折扣。

### P1 — 催款邮件
- [ ] 第一句是否先问了「是否遇到任何问题」而非直接催款？
- [ ] 是否给了具体的发票号 / 金额 / 到期日？
- [ ] 语气是否温和不施压？（逾期 < 14 天时）

### P2 — 索赔处理
- [ ] 是否先道歉并认可客户感受（"I understand your frustration"）？
- [ ] 是否给了具体解决方案（不是问客户「你想要什么」）？
- [ ] 是否承诺了调查时间线和预防措施？
- [ ] 责任不明确时是否建议了第三方检测（SGS / BV / TUV）？

### P3 — 展会邀请
- [ ] 展位号？（Hall X, Booth Y）
- [ ] 时间？（具体日期 + 开展时间）
- [ ] 「客户能带走什么」？（样品 / 目录 / 报价 / 专属折扣）

### P4 — 验厂邀请
- [ ] 工厂完整地址（中英双语）？
- [ ] 现场接待人姓名 + 电话？
- [ ] 验厂当天详细议程表（精确到半小时）？

### P5 — 节日问候
- [ ] 客户确实过这个节日吗？（对照速查表）
- [ ] 避开了文化禁忌？（颜色 / 数字 / 动物 / 手势 / 食物）
- [ ] 是否以感谢和关系维护为主，不带任何推销？

### P6 — 样品寄送
- [ ] 追踪号 + 快递公司名？
- [ ] 预计到达日期（ETA）？
- [ ] 样品使用 / 检测说明？
- [ ] 是否计划了到达后 24h 内跟进？

### P7 — 二次催付
- [ ] 是否提供了至少一个折中方案（分笔 / 延期 / 部分发货）？
- [ ] 语气是否「帮你解决问题」而非「赶紧付钱」？

### P8 — 物流异常
- [ ] 是否主动提供了船公司官网查询链接？
- [ ] 是否提供了本地代理电话？
- [ ] 是否道歉 + 说明原因 + 新 ETA？

### P9 — 售后维护
- [ ] 是否在收货第 7 天准时发送？
- [ ] 是否纯关心、不推销、不催单？
- [ ] 是否三个问题都简短一句话可答？

### P10 — 满意度调查
- [ ] 是否控制在 5 个选择题以内？
- [ ] 是否承诺了「我亲自看并改进」？
- [ ] 是否声明了「文字评论完全可选」？

### P11 — 年度合作总结
- [ ] 是否有具体数字（订单数 / 金额 / 准点率）而非空洞感谢？
- [ ] 是否有来年建议（基于今年数据）？
- [ ] 是否有新能力 / 新产品预告？

