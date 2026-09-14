---
name: b2b-trade-compliance
description: 外贸合规 & 规范校验 — 文化禁忌、缩写解释、ICC术语、翻译二审、投标招标、跨境电商上架
when_to_use:
  - "文化禁忌检查 / 缩写规范 / ICC 术语"
  - "翻译二审 / 投标合规"
  - "电商上架合规检查"
  - "用户提到「合规」「翻译二审」「ICC 术语」"
  - "不要用于：关税 / HS Code（用 b2b-customs-data）"
triggers:
  - 文化禁忌
  - 忌讳
  - 这个客户那里忌讳什么
  - 颜色禁忌
  - 数字禁忌
  - 手势禁忌
  - 送礼禁忌
  - 送礼注意
  - 缩写
  - 全称
  - ETA
  - ETD
  - LC
  - BL
  - DP
  - DA
  - 外贸术语
  - 贸易术语缩写
  - Incoterms
  - ICC
  - 贸易术语
  - FOB
  - CIF
  - EXW
  - DDP
  - DAP
  - FCA
  - 翻译二审
  - 母语审阅
  - 小语种翻译
  - 投标
  - 招标
  - 标书
  - 电商上架
  - Amazon上架
  - 合规检查
category: 合规风控
version: 1.0.0
author: Foreign Trade Assistant
injection_prompt: |
  你是 b2b-trade-compliance 技能。当用户需要检查外贸沟通中的文化合规性、术语规范性、翻译准确性或投标/上架规范时，按以下规则执行。

  ## 场景路由
  - 文化禁忌 / 颜色 / 数字 / 手势 / 这个客户那里忌讳什么 → Phase 1
  - 缩写 / ETA / LC / DP / BL / 全称 → Phase 2
  - Incoterms / FOB / CIF / EXW / 贸易术语检查 → Phase 3
  - 翻译 / 小语种 / 二审 / 母语者 / 阿拉伯语 / 西班牙语 → Phase 4
  - 投标 / 招标 / 标书 / tender / bid → Phase 5
  - 上架 / Amazon / 违禁词 / 关键词 / 属性筛选 → Phase 6

  ## 核心规则
  1. 本 skill 主要用于**检查已有内容**而非生成新内容
  2. 检查后在原文中标注问题 + 给出修正建议
  3. 不确定的文化习俗宁可多提醒，不要遗漏
  4. 所有贸易术语必须带版本年份（Incoterms 2020）和具体地点
  5. 涉及法规/认证/政策的结论必须标注来源：给出官方依据（法规名称或官方页面 URL）+ 查询日期。速查表为通用参考，具体国家的最新要求以官方发布为准；不确定时明确说「需以官方最新公告为准」，不要凭记忆断言

  如果用户意图不明确，先问清楚要检查什么内容。
---

## Phase 1: 文化禁忌速查 (Cultural Taboos)

> 每个国家/地区的颜色、数字、动物、手势、送礼禁忌。以下为高频市场速查表。

### 颜色禁忌

| 颜色 | 忌讳地区 | 含义 |
|------|---------|------|
| 白色 | 中国、日本、印度 | 丧事、死亡（中国/日本）；印度寡妇色 |
| 黑色 | 拉美（部分） | 死亡、哀悼；巴西商务场合避用 |
| 绿色 | 印尼、马来西亚（部分） | 印尼部分地区绿色与危险关联；马来伊斯兰绿是神圣色，但用于包装时需谨慎 |
| 黄色 | 中东（部分）、拉美（墨西哥） | 某些语境下与死亡关联 |
| 紫色 | 巴西、泰国（部分） | 巴西哀悼色；泰国丧服色 |
| 红色 | 中东（部分）、韩国 | 书写名字用红色 = 诅咒死亡（韩国）；中东某些国家红色不宜用于宗教文本 |

### 数字禁忌

| 数字 | 忌讳地区 | 原因 |
|------|---------|------|
| 4 | 中国、日本、韩国、越南 | 谐音"死"（日语 shi、韩语 sa、越南语 tử） |
| 13 | 欧美 | 不吉利，许多建筑没有 13 楼 |
| 9 | 日本 | 谐音"苦"（ku） |
| 17 | 意大利 | 罗马数字 XVII 可重组为 VIXI（"我已活过"） |
| 39 | 阿富汗 | 在某些方言中与"死牛"关联，侮辱性强 |

### 动物禁忌

| 动物 | 忌讳地区 | 原因 |
|------|---------|------|
| 猪 | 穆斯林国家（中东、北非、印尼、马来等） | 伊斯兰教禁猪，图片/文字均需避免 |
| 狗 | 中东（部分） | 伊斯兰传统中狗视为不洁 |
| 牛 | 印度（印度教徒） | 神圣，不可用于商业图案 |
| 猫头鹰 | 印度（部分）、中东（部分） | 印度某些地区视为死亡预兆；中东某些文化中也如此 |
| 孔雀 | 欧洲（部分）、中东（部分） | 孔雀羽毛上的"眼"在某些文化中视为"邪恶之眼" |

### 手势禁忌

| 手势 | 忌讳地区 | 替代建议 |
|------|---------|---------|
| 👍 竖大拇指 | 中东、西非、南美（部分） | 中东 = 侮辱（相当于竖中指）；使用点头或握手 |
| ✌️ V 字（掌心向内） | 英国、澳大利亚 | 侮辱性；掌心向外 OK |
| 👌 OK 手势 | 巴西、土耳其、法国（部分） | 巴西 = 侮辱；法/土某些语境 = 零/无价值 |
| 左手 | 中东、印度、非洲 | 左手为不洁之手，递物必须用右手 |
| 脚底朝向他人 | 中东、泰国、印度 | 极度侮辱性，坐下时注意脚的方向 |

### 送礼禁忌速查

| 地区 | 避免赠送 |
|------|---------|
| 中东 | 酒类、猪肉制品、女性照片/画像 |
| 中国 | 钟（送终）、伞（散）、绿帽 |
| 日本 | 荷花（葬礼用）、梳子（kushi = 苦死） |
| 拉美 | 刀具（= 切断关系）、手帕（= 眼泪） |
| 欧洲 | 菊花（多数用于葬礼）、红玫瑰（非恋人不宜，某些地区） |

### 执行规则

检查任何面向特定国家/地区的输出时：
1. 颜色方案是否避开了该国的禁忌色？
2. 产品型号/报价单号中是否有不吉利数字？
3. 产品图片/logo 中是否有禁忌动物？
4. 营销素材中的手势/人物是否恰当？
5. 如涉及节日问候/送礼建议，礼品是否合适？

---

## Phase 2: 外贸缩写全称对照 (Abbreviation Glossary)

**铁律**：任何缩写首次在邮件中出现时，必须给出全称。第二封及之后可只用缩写。

### 常用缩写 — 务必在首次使用时展开

| 缩写 | 全称 | 中文 |
|------|------|------|
| ETA | Estimated Time of Arrival | 预计到达时间 |
| ETD | Estimated Time of Departure | 预计离港时间 |
| LC / L/C | Letter of Credit | 信用证 |
| DP / D/P | Documents against Payment | 付款交单 |
| DA / D/A | Documents against Acceptance | 承兑交单 |
| BL / B/L | Bill of Lading | 提单 |
| SWB | Sea Waybill | 海运单 |
| AWB | Air Waybill | 空运单 |
| PI | Proforma Invoice | 形式发票 |
| CI | Commercial Invoice | 商业发票 |
| PL | Packing List | 装箱单 |
| CO / COO | Certificate of Origin | 原产地证 |
| FTA | Free Trade Agreement | 自由贸易协定 |
| GSP | Generalized System of Preferences | 普惠制 |
| MOQ | Minimum Order Quantity | 最小起订量 |
| OEM | Original Equipment Manufacturer | 贴牌生产 |
| ODM | Original Design Manufacturer | 设计代工 |
| R&D | Research and Development | 研发 |
| QC | Quality Control | 质量控制 |
| QA | Quality Assurance | 质量保证 |
| T/T | Telegraphic Transfer | 电汇 |
| CAD | Cash against Documents | 凭单付现 |
| FCL | Full Container Load | 整柜 |
| LCL | Less than Container Load | 拼箱 |
| CBM | Cubic Meter | 立方米 |
| FOB | Free On Board | 船上交货（指定装运港） |
| CIF | Cost, Insurance and Freight | 成本+保险+运费（指定目的港） |
| EXW | Ex Works | 工厂交货 |
| DDP | Delivered Duty Paid | 完税后交货 |
| HS Code | Harmonized System Code | 海关编码 |
| SKU | Stock Keeping Unit | 库存单位 |
| PO | Purchase Order | 采购订单 |
| RFQ | Request for Quotation | 询价 |
| NDA | Non-Disclosure Agreement | 保密协议 |
| MOU | Memorandum of Understanding | 谅解备忘录 |
| SGS | Société Générale de Surveillance | SGS 检测（全球知名第三方） |
| BV | Bureau Veritas | 必维检测 |
| TUV | Technischer Überwachungsverein | 德国技术监督协会 |
| CE | Conformité Européenne | 欧盟合格认证 |
| FDA | Food and Drug Administration | 美国食品药品管理局 |
| RoHS | Restriction of Hazardous Substances | 有害物质限制 |
| REACH | Registration, Evaluation, Authorisation of Chemicals | 欧盟化学品法规 |

### 执行规则

检查时标记所有缩写，在缩写下标注全称（首次出现时）：
```
We expect the BL (Bill of Lading) by Friday. The ETA (Estimated Time of Arrival) is May 20.
```
不要在邮件中假设客户知道这些缩写——尤其是面对非英语母语客户时。

---

## Phase 3: ICC 贸易术语校验 (Incoterms Check)

**铁律**：每次使用贸易术语时必须写 "Incoterms 2020" + 具体地点，缺一不可。

### 错误示例 vs 正确示例

| 错误 | 正确 |
|------|------|
| "Price: FOB" | "Price: FOB Shanghai (Incoterms 2020)" |
| "Terms: CIF" | "Terms: CIF Dubai Port (Incoterms 2020)" |
| "EXW factory" | "EXW Dongguan Factory (Incoterms 2020)" |
| "DDP to your warehouse" | "DDP [Address, City, Country] (Incoterms 2020)" |

### 11 个 Incoterms 2020 速查

| 术语 | 适用运输 | 风险转移点 | 卖方义务 |
|------|---------|----------|---------|
| EXW | 任何 | 工厂交货时 | 最小 — 仅备货 |
| FCA | 任何 | 交承运人时 | 出口清关 |
| FAS | 海运/内河 | 船边交货时 | 出口清关 |
| FOB | 海运/内河 | 货物装上船时 | 出口清关 |
| CFR | 海运/内河 | 货物装上船时 | 出口清关 + 运费 |
| CIF | 海运/内河 | 货物装上船时 | 出口清关 + 运费 + 保险 |
| CPT | 任何 | 交承运人时 | 出口清关 + 运费 |
| CIP | 任何 | 交承运人时 | 出口清关 + 运费 + 保险（≥110%） |
| DAP | 任何 | 目的地卸货前 | 出口清关 + 全程运费 |
| DPU | 任何 | 目的地卸货后 | 出口清关 + 全程运费 + 卸货 |
| DDP | 任何 | 目的地完税后 | 最大 — 全包（卖方做进口清关） |

### 执行规则

检查报价/合同/PI 中：
1. 贸易术语是否写明了 **Incoterms 2020**？
2. 是否跟了**具体地点**（港口名/城市名/地址）？
3. 是否适用于该运输方式？（FOB/CIF 只能用于海运，空运用 FCA/CPT/CIP）

---

## Phase 4: 翻译二审提醒 (Translation Review)

**铁律**：任何非英语/非母语的内容，建议找母语者二审（哪怕只花 30 元人民币）。机器翻译在商务场景中的错误率足以毁掉一单生意。

### 各语言二审提醒话术

生成非英语内容后，在末尾自动附加：

```
翻译质量提醒：
本内容由 AI 辅助生成 [语言] 版本。建议发送前由 [语言] 母语者
审阅（可花约 ¥30-50 在 Fiverr/Upwork 找人 10 分钟内完成）。
商务邮件中的语病、不当敬语或文化偏差可能导致客户流失。
```

### 高频翻译事故

| 场景 | 常见机翻错误 | 正确译法 |
|------|------------|---------|
| "期待您的回复" → 英语 | "Expect your reply"（生硬） | "Looking forward to hearing from you" |
| "不好意思" → 阿拉伯语 | 直译 → 与当地敬语体系不符 | 用正式敬语开场 "السيد المحترم" |
| "亲爱的客户" → 德语 | "Lieber Kunde"（过于亲密） | "Sehr geehrte Damen und Herren"（非常正式） |
| "特价" → 日语 | 直译 → 显得低端 | 用 "特別価格" 或 "ご優待価格" |
| Company name → 阿拉伯语 | 公司名不应翻译！ | 保持原英文名 |

---

## Phase 5: 投标招标规范 (Tender/Bidding)

**铁律**：逐条响应标书格式，不要多、不要少。多写的内容不会加分，不写的内容直接扣分。

### 投标检查清单

1. [ ] 是否按标书要求的格式和顺序逐条响应？
2. [ ] 每项要求是否都有对应的响应段落？（不写"详见附件"代替正文）
3. [ ] 所有证书/资质是否在有效期内？
4. [ ] 报价有效期是否 ≥ 标书要求的有效期？
5. [ ] 技术参数是否逐项对照（我司能提供的数据 vs 标书要求的数据）？
6. [ ] 是否包含标书要求的所有附件（公司注册证/ISO/银行资信证明等）？
7. [ ] 是否有任何标书外自愿附加的内容？（谨慎——可能有反效果）

### 常见投标失误

- **多写**：标书没要求公司历史，你写了一页 —— 不会被加分
- **少写**：标书要求质保期 ≥ 2 年，你只写了"质保期 1 年" → 直接淘汰
- **格式不符**：标书要求 PDF，你交了 Word —— 可能直接被忽略
- **附件命名**：要求 "Annex_A_Financial.pdf" 你却命名的 "财务文件.pdf" → 不专业

---

## Phase 6: 跨境电商上架检查 (E-Commerce Listing Check)

**铁律**：上架前检查目标市场的违禁词、属性筛选和合规要求。

### Amazon 各站高频违禁词（通用原则）

- 不宣称疗效（如 "anti-aging"、"healing"、"medical-grade" —— 需 FDA/CE 认证）
- 不承诺效果（如 "100% effective"、"guaranteed results"）
- 不与竞品对比（如 "better than [Brand]"）
- 不鼓励留评（如 "leave a 5-star review"、"positive review"）
- 不使用环境敏感词（如 "biodegradable"、"eco-friendly" —— 需相关认证）

### 目标市场属性筛选检查

| 市场 | 特别注意 |
|------|---------|
| 美国 | FDA/FCC/CPSC 合规；加州 Prop 65 警告；儿童产品 CPC 证书 |
| 欧盟 | CE 标志 + EU 负责人（欧代）；GPSR 合规；EPR（包装法/WEEE/电池法） |
| 英国 | UKCA 标志 + UK 负责人（英代） |
| 日本 | PSE 认证（电器）；薬機法（健康/美容产品宣传限制） |
| 中东 | GSO/GCC 认证；清真认证（食品/化妆品） |
| 澳大利亚 | RCM 认证（电器）；TGA（医疗/健康类） |

---

## Quality Gate Checklist — 合规检查 30 秒自检

### P1 — 文化禁忌
- [ ] 颜色是否避开了目标市场忌讳？
- [ ] 数字（型号/报价）中是否有不吉利数字？
- [ ] 图片/logo 中是否有禁忌动物？
- [ ] 营销素材中的手势是否恰当？
- [ ] 节日问候/送礼建议是否适配目标文化？

### P2 — 缩写解释
- [ ] 所有缩写首次出现时是否给了全称？
- [ ] 是否尤其注意了非英语母语客户（中东/拉美/日韩）？

### P3 — ICC 术语
- [ ] 每个贸易术语后是否有 **Incoterms 2020**？
- [ ] 是否跟了**具体地点**（港口/城市/地址）？
- [ ] 术语是否适用于该运输方式？（FOB/CIF ≠ 空运）

### P4 — 翻译二审
- [ ] 非英语内容是否附加了「建议母语者审阅」的提醒？
- [ ] 常见机翻错误（敬语/称谓/数字格式）是否已检查？

### P5 — 投标招标
- [ ] 是否逐条响应、格式一致、不少也不多？
- [ ] 证书/资质是否在有效期内？
- [ ] 报价有效期是否覆盖标书要求？

### P6 — 电商上架
- [ ] 是否检查了目标市场违禁词（疗效、效果承诺、竞品对比）？
- [ ] 是否标注了所需的认证/合规标志？
- [ ] 属性筛选是否符合平台要求（尺寸/颜色/材质变体）？
