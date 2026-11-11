# Skill 激活词冲突审计与解决方案

> 审计脚本：`python scripts/audit_skill_triggers.py`  
> 路由真相源：`trade/skill_registry.py` 的 `triggers`（不是 SKILL.md）  
> 匹配规则：词边界 3 分 / 子串 1 分 / `priority_keywords` +4 / 长触发词与短语优先

## 结论摘要

| 维度 | 状态 |
|------|------|
| 跨 skill **精确相同**触发词 | **0**（健康） |
| 短词被子串包含（len≤4） | **~28** 个高风险词 |
| 近平局 skill 对 | **~30** 对（最高频：customer-finder↔lead-generation） |
| 非唯一 alias | **4** 组（多为「把兄弟 skill 名写进 aliases」） |
| registry ↔ SKILL.md 漂移 | **37/45** skill 触发词不一致 |

精确冲突已控住；真正的问题是 **过短/过泛激活词 + 子串计分** 造成的职责抢夺。

## 冲突类型

### A. 子串抢夺（主因）

短 trigger 会出现在其他 skill 的长 trigger 里。长词通常能靠更长命中或更高分赢，但：

1. 用户只说短词时，短词所有者独享命中（常误路由）
2. 两边同分时依赖注册顺序，行为脆弱

| 短触发词 | 归属 | 典型误伤 |
|----------|------|----------|
| `招标` | trade-compliance | 整族 tender-*（裸「招标」变合规检查） |
| `报价` / `询盘` / `谈判` | lead-generation | document / doc-generation / inquiry-* / playbook |
| `合同` | document | doc-generation（「出一份合同」中间插入量词后丢「出合同」） |
| `厂` | china-leads | short-video / trade-ops（**已知权衡**，见下） |
| `帮我查` | chat-memory | 任意「帮我查一下…」未写完时抢记忆 |
| `seo` | platform | seo-aeo 内容写作 |
| `开发信` | cold-outreach | 与 lead-generation「帮我写开发信」整句对撞 |
| 国别裸词 `阿拉伯`/`西班牙` | lead-generation | 文化禁忌/合规问句 |

### B. 职责重叠近平局

探针统计中最频繁的对：

1. `b2b-customer-finder` vs `b2b-lead-generation`（找客户）
2. `b2b-tender-*` vs `b2b-trade-compliance`（招标）
3. `b2b-doc-generation` vs `b2b-lead-generation`（报价）
4. `b2b-inquiry-training/meeting` vs `b2b-lead-generation`（询盘）
5. `b2b-document` vs `b2b-doc-generation`（合同/报价单：读 vs 写）

### C. Alias 设计混淆

多个 skill 把**另一个已存在的 skill 名**写进 `aliases`（例如 lead-generation 被 6 个 skill 互指）。  
显式 `用 b2b-xxx` 时 name 命中优先，通常仍可用；但：

- 非唯一纯 alias 会解析失败（`len(matches)!=1`）
- 读者会误以为 aliases = 同义触发，实际更像「相关技能注释」

### D. 双源触发词漂移

路由只读 registry；SKILL.md `triggers` 常落后或超前。Hermes 安装/文档展示会与真实路由不一致。

## 已知有意权衡（不要贸然删）

```text
b2b-china-leads 保留单字「厂」：
加「工厂」会与「工厂视频」双命中被抢走；单字打平后靠注册顺序保 china-leads。
```

```text
tender-* 故意不用裸「招标」：
历史约定裸词归 trade-compliance；tender 用 ≥3 字复合词 + 最长触发词破平局。
```

```text
≤2 字符 ASCII 缩写（DA/BL/LC/DP）已禁止子串匹配，只走词边界。
```

## 解决方案（分层）

### P0 — 修明确误路由（本次落地）

| 问题 | 改法 |
|------|------|
| 「出一份合同」→ document | doc-generation 补 `出一份合同`/`生成合同`/`做合同`/`写合同` |
| 「帮我写开发信」→ lead-generation | 从 lead-gen 删除该整句；cold-outreach 补 `帮我写开发信`/`写开发信` |
| 「帮我查一下」→ chat-memory | 删除记忆 skill 的裸 `帮我查`（保留「查一下之前…」） |
| 「阿拉伯/西班牙 + 市场注意」→ lead-gen | 删除裸国别词；改为 `阿拉伯客户`/`西班牙客户` 等 |
| 裸「招标」→ compliance | compliance 改为 `招标合规`/`投标合规`/`标书检查`；`招标`/`投标` 交给 tender-info |

### P1 — 收紧泛词，加领域加成

1. **lead-generation**：裸 `报价`/`询盘`/`谈判`/`成交` 改为带场景的短语，或给 document / inquiry-* / playbook / doc-generation 配 `priority_keywords`
2. **platform vs seo-aeo**：platform 的 `seo` 改为 `平台seo`/`店铺seo`/`alibaba seo`；seo-aeo 保留内容向触发词并加 priority
3. **document vs doc-generation**：读类触发词加「分析/审核/看」；写类加「做/出/生成」；对 `合同` 裸词考虑降权或拆分
4. **customer-finder vs lead-generation**：明确边界——finder=方法论向导，lead-gen=获客执行；共用词只留一处，另一处靠更长短语 + priority

### P2 — 机制与治理

1. **CI**：`python scripts/audit_skill_triggers.py --strict` + pytest 守卫精确冲突与 P0 探针
2. **单一真相源**：registry 生成或校验 SKILL.md `triggers`（禁止双向手改）
3. **aliases 语义拆分**：`related_skills` 与 `aliases` 分开；aliases 必须全局唯一且 ideally 非其它 skill 名
4. **短词策略**：中文 trigger 默认 ≥3 字；2 字词必须进 allowlist 并写明权衡
5. **模糊查询**：top2 分差 ≤1 且无 priority 时，可返回澄清（hybrid 路由已有语义兜底入口）

## 验收探针（P0）

```text
出一份合同          → b2b-doc-generation
帮我写开发信        → b2b-cold-outreach
帮我查一下          → 无命中或非 chat-memory
阿拉伯市场注意事项  → b2b-trade-compliance
招标                → b2b-tender-info
招标合规怎么做      → b2b-trade-compliance
找招标              → b2b-tender-info（回归）
```

## 维护命令

```bash
python scripts/audit_skill_triggers.py
python scripts/audit_skill_triggers.py --json
python scripts/audit_skill_triggers.py --strict
pytest tests/test_skill_trigger_conflicts.py -q
```
