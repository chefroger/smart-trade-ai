---
name: b2b-document
description: 外贸文档分析 — 读取报价单/合同/PI/装箱单等贸易单据，提取报价、条款、规格等关键数据
when_to_use:
  - "用户提供了外贸单据（报价单 / 合同 / PI / 装箱单 / 产品规格书）要求提取关键信息"
  - "需要对比多份报价单的价格差异"
  - "从合同或 PI 中提取付款条件、交期、贸易术语"
  - "不要用于：生成新文档（用 b2b-doc-generation）；普通非贸易文档阅读（用 Hermes 内置 office skills）"
triggers:
  - 读报价单
  - 对比报价
  - 提取合同条款
  - 分析PI
  - 看装箱单
  - 产品规格书
  - 贸易单据
  - 报价分析
  - invoice analysis
  - quotation comparison
  # ... (see skill_registry.py for full list)
category: 文档管理
version: 1.0.3
author: Foreign Trade Assistant
---

# b2b-document 详细规则（skill_view 按需加载）

## ⚠️ 铁律 — 违反任何一条意味着用户可能基于错误信息做商业决策

**R0 — 完整读取，禁止截断**：每个文件必须读到末尾。500 行的表不能只读前 50 行，多 sheet 的 Excel 不能只读第一个 sheet，40 页的 PDF 不能只读到第 5 页。如果工具返回了部分内容，用 offset 继续读下一段，循环直到全部读完。**节省 token 不是截断文件的理由——漏掉的那一行可能就是用户要的答案。**

**R0.5 — 结构保真**：Excel/CSV 保留全部列的原始顺序，不删除你认为"不重要"的列。多 sheet 工作簿必须读每个 sheet，sheet 名本身就是信息。PDF 中的表格必须在输出中保持表格格式——不能把表转成要点列表。**永远不要为了"更清晰"而重新排序、重新分组或简化文档的原始结构。结构即信息，改结构即改含义。**

**R1 — 没读不准说**：没有 read_file 过的文件，禁止对其内容做任何断言。哪怕你认为"应该是这样"，也先读文件。

**R2 — 数字必须溯源**：输出中的每个数字必须标注来源单元格/行号/段落。无法溯源的数字 = 幻觉。

**R3 — 数值原样搬运**：原始文档中的数字，**不改精度、不四舍五入、不换算单位**（除非用户要求）。3.50 ≠ 3.5 ≠ 3.500。

**R4 — 缺单位就标注**：源文档没标单位的数值，输出时加 "[单位未标注]"，不要猜。

**R5 — 找不到就说找不到**：查找了但文件中不存在的信息，在"已查找但未找到"段中列出。

## 分析流程

### Phase 1 — Survey（文件摸底）
1. 列出目标目录下所有文件
2. 确认每个文件的类型、sheet 数量、大致行数/页数
3. 按优先级排序：报价单（价格）→ 规格书（参数）→ 合同（条款）→ 记录（历史）→ 其他

### Phase 2 — Deep Read（逐文件完整精读）
对每个文件：
1. 用 read_file 读取文件。如果文件很大，分多次读取直到读完整个文件，不要在中间停止
2. Excel/CSV：按 sheet 逐个读取，每读到新 sheet 先记录 sheet 名，然后读完全部行列
3. 提取数值时严格保持原始精度、单位和格式
4. 保留原始的列顺序和行顺序，不重排不删减
5. 记录每个关键数据的精确位置（Sheet/行号/列号/段落）
6. 读完一个文件后立即将关键数据整理到结构化表格中，避免后续混淆

### Phase 3 — Cross-Reference（交叉验证）
1. 检查同一产品在不同文件中的价格是否一致 → 不一致就标冲突
2. 检查报价中的产品代码在规格书中是否有定义 → 没有就标缺失
3. 检查金额计算（数量 × 单价 = 总价）是否匹配 → 不匹配就算出差额
4. 所有冲突和异常必须在报告中显著标注

### Phase 4 — Verification Re-Read（抽检重读）
1. 选择 2-3 个最关键的数字（单价、总金额、MOQ）
2. 重新 read_file 确认你第一次读到的值是正确的
3. 如有差异，以重读结果为准，并在报告中注明"已二次确认"

## 输出格式（严格按此结构）

```
## 文档摘要
[一段话概述：共 X 个文件，涉及 X 个产品/X 个客户，数据时间范围]

## 关键数据
| 品名 | 规格 | 单价 [置信度] | MOQ | 交期 | 付款条件 | 来源 |
|------|------|-------------|-----|------|---------|------|
  | [确切] | [确切] | $3.50/pc [确切] | 1000 pcs [确切] | 30天 [确切] | T/T 30/70 [确切] | 📄 报价单.xlsx R12 |

  每个单元格后标注置信度标签

  ## ⚠️ 数据冲突与异常
  [如有] 列出所有发现的冲突/不一致/异常

  ## 已查找但未找到的信息
  [必须] 列出你在文件中查找了但没有找到的信息

  ## 建议
  [如有] 基于数据的业务建议，不要脱离数据做推测
  ```

  ## 置信度标签（每个关键数字后必标）

  | 标签 | 含义 | 示例 |
  |------|------|------|
  | [确切] | 直接从文档中读到的精确值 | "$3.50/pc [确切]" |
  | [计算] | 基于文档数值计算得出 | "$3,500.00 [计算：$3.50 × 1000]" |
  | [推断] | 合理推断，非直接读取 | "约30天 [推断：基于历史交期]" |
  | [不确定] | 文档模糊，用户应核实 | "TBD [不确定：单据此处空白]" |

  ## 引用格式
  - Excel: 📄 {文件名} | Sheet: {sheet名} | Row: {行号} | Col: {列号}
  - PDF: 📄 {文件名} | Page: {页码} | Section: {段落标题}
  - Word: 📄 {文件名} | Section: {标题} | Paragraph: {段落号}
---

Examples:
- `📄 2024年度报价单.xlsx  |  Sheet: Sheet1  |  Row: 12-15  |  Column: C-E`
- `📄 客户资料.xlsx  |  Sheet: 联系方式  |  Row: 3`
- `📄 产品规格书.pdf  |  Page: 4  |  Section: 技术参数`

For PDF files, cite page numbers. For Word documents, cite section headings.

## Domain Terminology — Universal B2B Trade

### How to Handle Industry Terms

1. **Read the documents first** — product names, model numbers, and technical parameters are defined in the spec sheets and quotes. Let the documents teach you the domain.
2. **Map Chinese ↔ English** on the fly — many B2B documents mix languages. Translate freely; the LLM's multilingual ability handles this.
3. **Respect the document's own terminology** — if the document calls something a "Model A-200", use that exact term. Don't guess synonyms.
4. **Group by SKU / model number** — product codes (e.g. `A-200`, `TYPE-B`, `Φ25×3`) are the universal key for cross-referencing across files.

### Common Cross-Industry Parameters

When extracting specifications, these parameter types appear across most industries:

| Parameter Category | Examples | Common Units |
|---|---|---|
| Dimensions | Length, width, height, diameter, thickness | mm, cm, m, inch |
| Weight | Net weight, gross weight | kg, g, lb, ton |
| Material | Composition, grade, finish | (varies by industry) |
| Capacity / Rating | Power, flow rate, load, pressure | W, kW, L/min, kN, MPa, bar |
| Quantity | MOQ, pack size, container load | pcs, sets, cartons, pallets |
| Color / Finish | Color code, surface treatment | (varies by industry) |
| Certification | ISO, CE, RoHS, FDA, etc. | — |

### Cross-Industry Commercial Terms (通用商务术语)

| 中文 | English | 缩写 |
|------|---------|------|
| 报价单 | Quotation / Price List | — |
| 形式发票 | Proforma Invoice | PI |
| 商业发票 | Commercial Invoice | CI |
| 装箱单 | Packing List | PL |
| 提单 | Bill of Lading | B/L |
| 成交记录 | Transaction Record | — |
| 合同 / 订单 | Contract / Purchase Order | PO |
| 交货期 | Delivery Time / Lead Time | — |
| 付款条件 | Payment Terms | T/T, L/C, D/P, D/A |
| 贸易术语 | Incoterms | FOB, CIF, EXW, DDP |
| 最小订单量 | Minimum Order Quantity | MOQ |
| 样品 | Sample | — |
| 大货 | Bulk Order / Mass Production | — |
| 尾款 | Balance Payment | — |
| 订金 | Deposit | — |
| 唛头 | Shipping Mark | — |

### Currencies

Recognize and distinguish between:
- `¥` / `CNY` / `RMB` — 人民币
- `$` / `USD` — 美元
- `€` / `EUR` — 欧元
- `£` / `GBP` — 英镑
- `¥` / `JPY` — 日元
- `₩` / `KRW` — 韩元

### Unit Conversions

- 1 英寸 (inch) = 25.4 mm
- 1 英尺 (foot) = 304.8 mm
- 1 磅 (lb) ≈ 0.4536 kg
- 1 美吨 (short ton) ≈ 907.2 kg
- 1 公吨 (metric ton) = 1000 kg
- 1 加仑 (US gallon) ≈ 3.785 L
- 1 MPa = 1 N/mm² = 145 psi
- 1 bar = 100 kPa
- °F = °C × 9/5 + 32

## Excel Table Extraction Guide

When reading Excel files, follow these rules:

1. **Multi-level headers**: If row 1 and 2 are merged/category headers, treat them as composite column names.
2. **Merged cells**: If a cell appears empty, check if it's part of a merged range — look at adjacent cells for context.
3. **Numeric precision**: Always preserve the **exact** number of decimal places as shown in the original. Do not round.
4. **Units**: Note the unit in the column header or nearby cells. Distinguish between `mm` / `cm` / `m` / `inch`.
5. **Currency**: Note the currency marker. Distinguish between `¥`, `$`, `€`, `£`.
6. **Empty rows**: Skip empty rows between data sections. Pay attention to **subtotal** and **total** rows.
7. **Multi-sheet workbooks**: Treat each sheet independently. Sheet name often indicates product category or customer.

## Cross-Reference Patterns

When analyzing B2B documents, look for these cross-file relationships (applicable to any industry):

- **Quote → Spec**: A quote lists a product code at a certain price; the spec sheet defines that code's full specifications. Always cross-check.
- **Quote → Customer**: A quote filename or header references a customer code; the customer file maps that code to company name, contact, address.
- **Transaction → Quote**: A transaction record references a quote number; cross-check the price and quantity match.
- **Multiple Quotes**: Same product from different vendors → compare prices.
- **Spec → Inventory**: A spec sheet defines what a product is; the inventory list tells you how many are in stock.

## Long-Term Memory — B2B Usage

You have a `memory` tool that stores durable facts across sessions, and a `chat_memory_list` tool
that reads Trade's conversation history (scoped by company). Use them to carry findings forward.

### What to Store
- **Product facts extracted from docs**: model numbers, specs, prices, MOQs, lead times
- **Customer requirements mentioned by user**: target markets, certification needs, budget ranges
- **Cross-file linkages discovered**: which spec file defines the product in which quote
- **User decisions and preferences**: preferred output language, format style, naming conventions

### When to Store
- After reading a product spec sheet → store key parameters
- After the user mentions a customer name or requirement → store it
- After cross-referencing multiple files → store the discovered relationships
- After generating a document → store what was generated and for whom

### Recall Before Analysis
At the start of a new task, check for relevant past context: previously stored facts are already
in your context, and past conversations are reachable via `chat_memory_list`. This connects new
questions to previous findings without the user needing to repeat context.

## Privacy & Confidentiality

B2B documents often contain sensitive information:
- Client names and contact details
- Pricing and margin information
- Supplier identities

When analyzing, **always** follow the active privacy mode. Do not expose raw file contents to external services unless explicitly permitted. Prefer local analysis with read_file over uploading to cloud parsers.
