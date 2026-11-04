# 豁免说明：客户语义检索（向量）

- 日期：2026-11-04
- 来源：负责人决定（2026-11-04 审计后的口径）
- 状态：生效中；默认关闭（opt-in）

## 1. 豁免对象

- `trade/embeddings.py`（embedding 后端抽象）
- `trade/vec_search.py`（客户向量索引与检索）
- `trade/skill_semantic.py`（混合 skill 路由，默认仍走关键词）
- `pyproject.toml` 的 `[semantic]` extra（`sqlite-vec`）
- 可选的 `sentence-transformers` 后端

## 2. 为什么保留，却默认关闭

- 目标用户是几十到几百个客户的小外贸团队，关键词检索加模型自行挑选通常已经够用。
- 目前**没有在真实外贸数据上验证过收益**；仓库里的测试都用合成样例。
- 可用性优先：多一个原生扩展（sqlite-vec）、多一步安装、多一类静默失效面。
- 结论：保留能力，**默认关闭**；需要时显式开启，失败自动降级，不阻塞任何主流程。

## 3. 用什么模型 / 后端

- 默认后端 `tfidf`：纯 Python 字符 n-gram（2–4），本地计算，不联网、不下载模型。
- 可选后端 `sentence-transformers`：默认模型 `paraphrase-multilingual-MiniLM-L12-v2`
  （可用 `TRADE_ST_MODEL` 覆盖），首次使用时由该库自行下载。
- 没有远程 embedding API；没有按次计费。

## 4. 数据去向

- 向量与词表只写在本机 `~/.trade/data/trade.db` 的 `vec_customers` / `vec_meta` 表。
- 索引文本包含客户姓名、联系人、备注、职位、国家、邮箱、网站、品类、来源。
- 不发送给任何第三方；查询按 `company_id` 过滤，不跨公司返回。

## 5. 如何开启 / 关闭 / 清理

```bash
# 开启（需要先装扩展）
pip install sqlite-vec
TRADE_SEMANTIC=on python server.py

# 查看状态
trade vec status

# 用全量客户重建索引（词表按全量语料重新 fit）
TRADE_SEMANTIC=on trade vec rebuild

# 清空索引与词表（关闭状态下也可用）
trade vec clear
```

关闭方式：不设 `TRADE_SEMANTIC`（默认即关闭）。关闭后不导入 sqlite-vec、
不写/不查向量，客户搜索只走关键词。

## 6. 硬性约束

- **永不阻塞启动、安装、主流程**。
- sqlite-vec 缺失、扩展加载失败、维度/模型不匹配时，一律静默降级为关键词检索。
- 安装器与升级链路不再默认安装 sqlite-vec。
- 删除客户、物理删除公司（purge）时同步清理向量；
  小库（≤500 条客户）写入时全量重建，避免 TF-IDF 词表冻结导致新内容搜不到。

## 7. 重新评估条件

- 出现真实用户需求；或
- 用真实外贸数据完成「关键词 vs 向量」对比，证明有净收益；或
- 上游 sqlite-vec 在目标平台全部有 wheel、且安装失败率可忽略。

满足任一条件后再讨论是否改为默认开启。
