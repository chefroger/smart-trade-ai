# CHANGELOG

## v0.9.61 — 2026-11-26

- `1f412a1` fix(memo): 迁移旧版 memo.json 节流字段至 memo_throttle.json 并清理死字段（O-新30）
- `853c1e5` test(osint): 路由集成测试补齐 license_state 激活桩以适配后端付费技能门控
- `b162e55` feat(ui): 合并侧边栏 8 个聊天入口为统一「对话」，下沉 osint/docgen 付费门控至后端

## v0.9.60 — 2026-11-26

- `5bfb439` fix(memory): 补齐公司级隔离记忆消费、迁移与备份闭环（P2-新1/O-新33）
- `da703b9` fix(cron): 修复右栏定时任务输出展示、Hermes 响应提取与多公司归属推断

## v0.9.59 — 2026-11-26

- `3d96d3c` fix: 修复多公司记忆隔离、迁移备份与业务审计问题

## v0.9.58 — 2026-11-25

- 20261125g 审计批：O-新26～29 + W8 工作流
- `37eaf7c` ci(release): 手动触发直接出正式 Release 且串行发布（W8）
- `f28bb58` docs(osint): 记一笔 CJK 多目标不拆分（O-新29）
- `5d4f285` fix(memo): 节流改单调计时且按公司分桶（O-新28）
- `70cece5` fix(privacy): son/brother + 业务名词不算家庭成员（O-新27）
- `3251919` fix(osint): 英文疑问句剥句首助动词再取专名（O-新26）

## v0.9.57 — 2026-11-25

- S11/R12：未安装 Hermes 时给出界面安装引导
- `0ff98bb` fix(hermes): 未安装 Hermes 时给出安装引导（S11/R12）

## v0.9.56 — 2026-11-25

- 20261124 审计剩余项：S1–S10、P2-新1/2、O-新15～24
- `77142a4` test(memo): 修复重启用例在全量套件下的顺序依赖（S8 补）
- `95ff1aa` fix(ui): 技能行复制触发词而不是技能名（P2-新2）
- `0711108` fix(license): 剩余 5 处 _get_license_data 调用补 try（O-新24）
- `39d6986` fix(ui): 备忘录前端锁只统计 403（O-新22）
- `630879b` docs(app): 修正过期的 CSP 注释（O-新18）
- `76101fd` fix(ui): 合成事件的 preventDefault 转发真实事件（O-新17）
- `c7335f7` test(skills): 恢复 SKILL.md→注册表可路由守卫（O-新16）
- `3b5f018` test(sanctions): 种子改回生产依赖的真实两行（O-新15）
- `1283d5c` ci(sanctions): 冒烟覆盖全部六份名单（S10）
- `657d35d` fix(osint): 只有登记命中时改用「已查到公司登记」措辞（S9）
- `d7a5bf2` fix(memo): 锁定状态持久化且密语框关闭自动填充（S8）
- `bb657d9` fix(router): 补制裁触发词并收紧泛词与国籍复数（S7）
- `94952ca` fix(profile): 收紧「客户索要」判定词表（S6）
- `8019e06` fix(guard): 备份目录与扫描命令按主库处理（S5）
- `f5bf73a` fix(privacy): 补全家庭称谓并收敛日常英文词（S4 / O-新21）
- `d7f46e9` fix(osint): 名单不全时仍报出已确认命中（S3）
- `1ad9daa` fix(osint): 交付兜底区分中文目标与专名优先（S2）
- `cc69d94` fix(ui): 模型输出禁用 data-* 且委托层改白名单（S1）

## v0.9.55 — 2026-11-24

- 修复向导动态 <style> 与 style-src-elem 的冲突（O-17 补漏）
- `54c19dd` fix(ui): 向导动画不再运行时注入 style 元素（O-17 补漏）

## v0.9.54 — 2026-11-24

- O-17 样式收口：style-src-elem 只允许外部样式；脚本/事件 unsafe-inline 已移除
- `c5c3b37` security(csp): 样式元素只允许外部文件（O-17 样式收口）

## v0.9.53 — 2026-11-24

- 修复语言切换动态写 onclick 导致的 CSP 拦截（O-17 补漏）
- `4c602de` fix(ui): 语言切换不再动态写 onclick（O-17 补漏）

## v0.9.52 — 2026-11-24

- O-17 完成：147 个内联事件迁移到 data-* 委托，CSP script-src/attr 移除 unsafe-inline
- `1a06a10` security(csp): 完成内联事件迁移，移除 script unsafe-inline（O-17）
- `9ba90b4` refactor(ui): HTML 内联事件迁移到 data-act 委托（O-17 第二步）

## v0.9.51 — 2026-11-24

- O-新6：密语失败后端节流（5 次锁定 60 秒），刷新无法绕过
- `0e9823b` fix(memo): 密语失败后端节流（O-新6）

## v0.9.50 — 2026-11-24

- O-17 第一步：内联 script 元素使用 per-request nonce（script-src-elem），事件属性暂留回退
- `5f5d632` security(csp): 内联脚本改用 per-request nonce（O-17 第一步）

## v0.9.49 — 2026-11-24

- 2026-11-24 审计跟进：O-新1 短名子集降级、O-新2 动词剥离、O-新5 先生/夫人语境化，及 O-新3/4/7/8/10/11/12 小修
- `574f13a` fix: 审计小修 O-新3/4/7/8/10/11/12
- `1a6f1b6` fix(privacy): 「先生/夫人」改为所属语境才判家庭信息（O-新5）
- `84dbf1a` fix(api): 剥离查询动词后再取制裁筛查目标（O-新2）
- `4e7d34b` fix(osint): 短名子集命中降为 possible（O-新1）

## v0.9.48 — 2026-11-24

- 修复 CI：清空已失效的触发词分歧登记（测试修复，无功能变化）
- `74aafa3` test: 清空已失效的触发词分歧登记（修复 CI）

## v0.9.47 — 2026-11-24

- W6 路由补全：询盘真假/信用风险/采购习惯中英文触发词；全量 SKILL.md 双语补齐与注册表同步守卫
- `912d1a0` feat(skills): 检查并补全 SKILL.md 中英文触发词
- `7cf5d37` feat(router): W6 三条可选路由补英文触发词
- `f07c526` feat(router): 补全 W6 三条可选路由（询盘真假/信用风险/采购习惯）

## v0.9.46 — 2026-11-24

- 合并修正 d：W1–W15（个人命中降级、交付兜底、登记类评级、重定向钉主机、tkey 迁移、路由兜底、远程图新标签、draft Release、架构校验、真名清理、临时目录、落库竞态、隐私词表/备忘录/主库规则、礼物提示、29 项 O 级）
- `efe9ccd` fix: 处理 29 项 O 级审计项（W15）
- `a627b48` fix(profile): 手工事实像「客户索要」时提示改记礼物表（W14）
- `3b228f8` fix(privacy): 统一家庭词表 + 密语弹窗/锁定 + 主库窄规则（W13）
- `6382baf` fix(chat): 落库期间断开不再写第二条历史（W12）
- `bb99e5a` test: 隔离并清理测试临时目录（W11）
- `0f2f1dd` fix(osint): 清除仓库里的真实背调对象（W10）
- `35e894a` ci(release): 校验 Mac 产物架构并固定 arm64 runner（W9）
- `e4a65c9` fix(release): 手动触发也产出 draft Release（W8）
- `96229ab` fix(ui): 远程图片改为新标签页打开（W7）
- `52e17f7` fix(router): 人名兜底只认询问对象，业务技能优先（W6）
- `7742825` fix(osint): 归一化升级窗口就地重建旧库 tkey（W5）
- `3933b09` fix(osint): 制裁名单重定向钉死官方桶主机（W4）
- `d462a46` fix(osint): 只有登记类命中时不给 low/100（W3）
- `cb60553` fix(api): 交付前制裁兜底不再拿整句比对名单（W2）
- `ed3fcb8` fix(osint): 个人姓名命中降为 possible/medium（W1）

## v0.9.45 — 2026-11-23

- Release：arm64 构建改用 macos-latest
- `57025f9` ci(release): arm64 构建改用 macos-latest（macos-14 在公开仓库被取消）

## v0.9.44 — 2026-11-23

- Release：Intel/Apple Silicon 双架构 Mac 包
- `7c0a920` ci(release): Mac 包分 Intel / Apple Silicon 两种架构构建

## v0.9.43 — 2026-11-23

- Mac 包改为运行时使用用户自己的 Hermes（不内嵌）
- `cd145a7` feat(release): Mac 包改为运行时使用用户自己的 Hermes

## v0.9.42 — 2026-11-23

- Release：拦截低于 0.21.6 的 Hermes，禁止产出坏包
- `e5a065d` ci(release): 拦截低于 0.21.6 的 Hermes，禁止产出坏包

## v0.9.41 — 2026-11-23

- Release：Hermes 必需安装 + 冒烟，构建切 Python 3.14
- `6b0c1f3` ci(release): Hermes 改为必需安装并冒烟，构建切到 Python 3.14

## v0.9.40 — 2026-11-23

- P2 第二批：待办原因、路由接线、制裁超时、并发用例、安装器 throw
- `8dcbf23` fix: P2 第二批（待办原因、路由接线、制裁超时、并发用例、安装器 throw）

## v0.9.39 — 2026-11-23

- 修复测试后台任务抢锁导致的 CI 偶发红灯
- `f93ad1c` test(osint): 等后台任务结束再离开用例，消除 init_db 抢锁

## v0.9.38 — 2026-11-23

- P2 第一批：title 连字符、EDGAR 公司邮箱、conftest 隔离、导入精确同名/409
- `8ffe7d0` fix: P2 第一批（title 连字符、EDGAR 公司邮箱、conftest 隔离、导入精确同名）

## v0.9.37 — 2026-11-23

- 修复 Windows 主库路径检测（P1-F CI 红灯）
- `2113eeb` fix(privacy): 主库路径检测兼容 Windows 反斜杠（CI 红灯）

## v0.9.36 — 2026-11-23

- P1-F：私密备忘录、家庭称谓过滤、主库路径窄规则
- `a3409cf` feat(privacy): 密语备忘录、家庭称谓过滤与主库路径窄规则（P1-F）

## v0.9.35 — 2026-11-23

- P1-D/P1-G：同名候选与事实核验、制裁匹配分级与刷新退避、报告结果预览
- `e54e144` fix(sanctions): 归一化规则升级后强制刷新一次重建 tkey
- `2587bb9` test(osint): 同步同名候选断言并补匹配质量/退避用例
- `d7a0a70` fix(osint): 制裁匹配去停用词分级，刷新退避，未完成报告带结果预览（P1-G）
- `e816be0` fix(osint): 同名账号只作候选，事实库按本轮工具证据判定 verified（P1-D）

## v0.9.34 — 2026-11-23

- 修复 CI lint（B023）
- `9d28a33` test(chat): 绑定循环变量修复 ruff B023（CI lint 红灯）

## v0.9.33 — 2026-11-23

- P1-10 补口：老安装读取时补写试用锚点
- `6f6c37b` fix(license): 老安装读取时补写试用锚点

## v0.9.32 — 2026-11-23

- P1：流式竞态、许可证试用加固、去真实人名、CSP 与远程图片占位
- `d094e35` fix(ui): /trade 加 CSP，模型消息远程图片改点击加载（P1-E）
- `5e01c17` chore(skills): 提示词/CLI/注释里的真实背调对象换成虚构示例（P1-C）
- `17dbae4` fix(license): TRADE_TRIAL_DAYS 只在测试进程生效，试用起点双写（P1-10）
- `de8f94d` fix(chat): 先置 delivered 再发 response，消除成功回答后多写未完成报告（P1-1）

## v0.9.31 — 2026-11-23

- P0-C：人名/公司名说法兜底进背调，交付前强制补制裁结论
- `00efa0d` fix(osint): 人名/公司名说法兜底到背调，交付前强制补制裁结论（P0-C）

## v0.9.30 — 2026-11-23

- P0-A/P0-B 同版：修复前新装用户 OFAC/UN 名单为空、老用户名单停在 11-22；无核验时评级改为 limited
- `22c7d93` fix(osint): 无域名且公开来源零命中时评级改为 limited（P0-B）
- `dd3bec2` fix(sanctions): 放行 OFAC/UN 官方 CDN 跳转，新增 72h/7d 过期上限与真实下载冒烟（P0-A）

## v0.9.29 — 2026-11-23

- 审计 O-20：升级日志统一脱敏（JWT/24 位密钥/UNC 路径）
- `50904a3` fix(ui): Hermes 升级日志统一脱敏，折叠的原始日志不再泄露原文

## v0.9.28 — 2026-11-22

- 审计 O-22：畸形包/字符串 id、安装包版本与图标、冒烟 push 触发
- `bbc6653` fix(transfer,install,ci): 修复上次审计遗留的 5 项（O-22）

## v0.9.27 — 2026-11-22

- 审计 P2-9/O-21：EDGAR 真实联系邮箱与凭证文档；披露行检查
- `2c0bee6` fix(osint): EDGAR 联系邮箱换成真实地址并公开三个凭证的配置位置

## v0.9.26 — 2026-11-22

- 审计 P2-10/O-19/O-18：e_code 判定、迟到评级、墨色统一
- `022a9c2` fix(osint,ui): 用户名检索按 e_code 判定；浮层迟到评级不丢；CSS 墨色统一

## v0.9.25 — 2026-11-22

- 审计 P2-3/P2-5：总结成功保留 partial；同步预算 540s 收口
- `fddeb2e` fix(chat): 总结成功保留 partial 标记，同步预算收口到超时内

## v0.9.24 — 2026-11-22

- 审计 P2 批次：并发去重/取消竞态、查人路由、全角前缀、重定向白名单、等待面板收起
- `6c54272` fix(osint): 审计 P2 批次（并发/取消/前缀/收起/重定向）

## v0.9.23 — 2026-11-22

- 制裁名单空解析不再清库：按失败保留旧数据，coverage 判降级（审计 P1-1）
- `bb0677c` fix(osint): 空解析不得清空制裁名单（审计 P1-1）

## v0.9.22 — 2026-11-22

- 清理 15 个 SVG 图标的杂散属性块；icon-guard 增加全量结构断言
- `8404107` fix(icons): 清掉 15 个 SVG 的杂散属性块，并加守卫

## v0.9.21 — 2026-11-22

- 等待动画与聊天界面的线条统一：网格连续、墨色透明度、旧冷灰清理、拖拽浮层改纸面虚线
- `bb5782c` style(ui): 等待界面与聊天界面的线条收口

## v0.9.20 — 2026-11-22

- 修复在非首个聊天上下文发起背调时浮层宽度为 0（隐藏缓存输入区定位）
- `0349411` fix(wait): 浮层不能拿隐藏缓存视图的输入区定位（宽度 0 导致整窗不可见）

## v0.9.19 — 2026-11-22

- 背调去重只复用排队/运行中的任务；已完成任务重新跑，重复提问会看到新一轮进度动画
- `6c61d1c` fix(osint): 已完成任务不再被复用（大动画消失的根因）

## v0.9.18 — 2026-11-22

- 背调浮层与聊天区对齐；大动画文案跟随真实进度，采集完成到回复生成期间持续提示
- `81d8616` fix(wait): 浮层与聊天区对齐；文案跟随真实进度直到回复生成

## v0.9.17 — 2026-11-22

- 背调一致性：domain: 前缀修复 + 事实库复用/冲突并列 + 提示词固定清单
- `374ff64` fix(osint): 同一目标两次背调结果漂移的三个根因

## v0.9.16 — 2026-11-22

- 长任务等待改为右下角聚合浮层：多任务标签切换、不阻塞操作、采集完成与生成中分离、结束自动收起
- `caee65a` feat(wait): 长任务改为右下角聚合浮层（非阻塞）
- `0f1a29a` test(e2e): WebGL 上下文丢失回退与单实例限制
- `3519df3` test(e2e): 覆盖 Hermes 升级 task 面板与日志脱敏

## v0.9.15 — 2026-11-22

- 背调等待面板：断线按 seq 去重回放；历史重渲染后自动恢复运行中的任务
- `4721e28` fix(wait): 背调面板断线去重、历史重渲染后自动恢复

## v0.9.14 — 2026-11-22

- 统一等待界面（撒马利亚人）：chat/task/inline 三模式 + three.js 推镜 + 顶栏真实任务状态；全部等待点接入；聊天流新增 job_attached
- `1fcd5d7` feat(ui): 全部等待点接入统一等待界面 + job_attached
- `8cb55b0` feat(wait): 撒马利亚人统一等待组件（Canvas2D + three.js 推镜）

## v0.9.13 — 2026-11-22

- 长背调改走后台任务：提示词教模型用 tool_search 发现 osint_job_start，禁止 terminal 长跑（切公司会中断）
- `b12a857` fix(osint): 长背调改用后台任务，避免切公司中断

## v0.9.12 — 2026-11-22

- 背调后台任务：持久化 + SSE 续传 + 右栏进度（P1-1）
- `fd4dd99` feat(osint): 背调后台任务——持久化任务/事件 + SSE 续传 + 右栏进度（P1-1）

## v0.9.11 — 2026-11-22

- 背调不再加载当前公司业务上下文
- `60a824b` fix(prompt): 背调外部对象时不加载当前公司的业务上下文

## v0.9.10 — 2026-11-22

- P2-2 收尾：Gravatar/用户名跨站/FR-NO-BR 登记 + LinkedIn dork
- `2d7f305` feat(osint): 收尾 P2-2——Gravatar/用户名跨站/FR-NO-BR 登记 + LinkedIn dork

## v0.9.9 — 2026-11-22

- 背调第二批公开来源：PDNS/GLEIF/VIES/州登记/EDGAR/GDELT
- `ce03562` feat(osint): 第二批公开来源——PDNS/GLEIF/VIES/州登记/EDGAR/GDELT（P2-2）

## v0.9.8 — 2026-11-22

- 背调：人名类型 + RDAP/CT/Wayback/GitHub 公开来源
- `f1dd812` feat(osint): 人名类型 + RDAP/CT/Wayback/GitHub 公开来源（P2-1 / P2-2 第一批）

## v0.9.7 — 2026-11-22

- 背调报告照抄制裁抓取时间，不再由模型推断
- `058c1b4` fix(osint): CLI 输出制裁数据抓取时间，报告引用不再靠猜

## v0.9.6 — 2026-11-22

- 个人背调路由修复：不再被 LinkedIn 营销劫持；报告强制制裁结论
- `b770d92` fix(routing): 个人背调不再被 LinkedIn 营销劫持 + 报告强制写制裁结论

## v0.9.5 — 2026-11-22

- 制裁名单重建：官方源 + 本地库 + 后台每日刷新（P0-1）
- `65a8865` feat(sanctions): 制裁名单重建为官方源 + 本地库 + 后台每日刷新（P0-1）

## v0.9.4 — 2026-11-22

- 任务中止留下未完成报告 + 重试不重复执行工具（P0-5）
- `59d0f30` feat(chat): 任务中止留下未完成报告 + 重试不再重复执行工具（P0-5）

## v0.9.3 — 2026-11-22

- 背调评分 fail-closed（P0-2）+ 各层并发/超时/进度（P0-4）
- `37d6d4c` feat(osint): 背调各层并发 + 分层超时 + 进度事件（P0-4）
- `a014453` fix(osint): 关键层未核验时评分改为 fail-closed（P0-2）

## v0.9.2 — 2026-11-22

- 背调：系统代理模式下不再被误拦（含运行中切换代理立即生效）
- `4c41a40` feat(osint): 运行中切换代理立即生效，不用重启 Trade
- `3543d54` fix(osint): 系统代理模式下不再把本机代理当内网拦掉（P0-3）

## v0.9.1 — 2026-11-21

- Hermes 缺失时降级启动；macOS 双击入口；CI 覆盖 3.14 与前端/嵌入冒烟
- `1e9110c` feat(installer): macOS 生成可双击的 Trade.app（P2-11）
- `e4a53a6` ci(e2e): 启动失败时带上服务端日志；依赖对齐 test.yml
- `f7a7be0` test(e2e): Playwright 前端冒烟（P2-7）+ 修 Hermes 缺失时的启动崩溃
- `2233b58` ci: Hermes 冒烟改用官方安装脚本
- `9478878` ci: 覆盖部署用的 Python 3.14，并增加每晚 Hermes 冒烟（P2-6）

## v0.9.0 — 2026-11-21

- 新增独立待办（逾期/今天/将来/已完成，支持截止日与关联客户）
- `adb4060` feat(todo): 右栏待办接独立后端（P2-12 前端）
- `9190331` feat(todo): 增加「将来」分组并规范 done 布尔解析
- `c994ddc` feat(todo): 独立的用户待办存储与 API（P2-12 后端）

## v0.8.1 — 2026-11-21

- 清理 4 项审计小问题（顶栏假状态 / 单商品币种 / 清库确认 / 提示词批注）
- `5c7e0d8` fix(release): 发版脚本把新版本小节插在 CHANGELOG 标题之后
- `dd4aad2` test(release): 版本号改为与 CHANGELOG 交叉校验
- `ad103c4` fix(admin): 清库确认从写死口令改为输入公司名（P2-9）
- `774d5fe` fix(audit): 中性顶栏文案、单商品订单币种校验、清除提示词内部批注
- `a107e0a` docs(changelog): 历史按提交整理（1074 条非 merge 提交）
- `f28d959` chore: 历史变更记录（部分恢复）本地保留、不入库

## v0.8.0 — 2026-11-20

首个带版本号的稳定基线。

### 隐私
- 验厂计划不再带出「家庭 / 礼物往来」类画像原文：建议生成、打印件、长图、导出包、历史 payload 五处全部堵住
- 「家庭」类画像硬锁，不可打开进 AI 上下文

### 安全
- 本地服务增加 Host 头校验，堵住 DNS rebinding 读走会话凭据
- 供应链：声明 `cryptography` 依赖

### 公司与客户数据
- 导入改为「预检 → 逐对选择 → 确认」：同名客户不再被静默合并，可逐对选择合并或新建
- 二次导入不再产生重复的询盘与验厂计划
- 导出包不再包含敏感类画像
- 版本号改为读 pyproject（此前导出的 app_version 恒为 unknown）

### 其它
- 长期记忆（Hindsight）增加用户开关与真实连通性探测
- 修复客户墙「返回」在验厂页打开时落回验厂页的问题
- 按钮图标统一为 Lucide

## 历史提交记录（按日期，最新在前）

> 由 `git log --no-merges` 生成；v0.8.0 之前的历史按提交原样列出。

### 2026-11-19
- `2dd1c11` fix(visit): 按审计 O-1～O-6 修复（长图内外分离 / 测试 / days 校验 / 死代码 / 文档 / 标题换行）
- `2e60435` fix(chat): 其他栏目 @ / 下拉不显示——缓存视图里有多个同名 id
- `f938a6b` fix(chat): 技能候选剔除已禁用项；@ / 兼容全角 ＠ ／
- `ea66692` fix(chat): @ 显示联系人名、技能全量分组、任意栏目与句中触发
- `95f0a52` feat(chat): @ 关联客户 / / 调用技能 下拉真正可用
- `b02228c` style(rail): 待办限高调整为 45%
- `9b9b466` style(rail): 待办框限高 36%，剩余高度给定时任务输出
- `f3d52cd` feat(ui): 助手回复限宽 92%；右栏待办去掉勾选框（无待办存储，避免误导）
- `c2d7557` fix(visit): 打印内部页空白——水印铺满整页背景图，关闭「背景图形」时整页被丢弃
- `bb030ec` fix(visit): 打印改为按 A4 尺寸自然分页，彻底绕开 break 兼容问题
- `7ccc0f2` fix(visit): 打印分页只保留一个方向，消除第二页空白
- `da2c0ac` fix(visit): 打印第二页空白——去掉双重分页（WebKit 会多出空白页）
- `de8d13a` fix(visit): 打印 A4 空白——遗留 @media print 规则把预览层一起隐藏
- `fadd5e5` fix(visit/profile): 画像提醒补对象、含待确认项、进入即带出；AI 开关显示开/关
- `5b70203` fix(ui+visit): 时间线挤掉三栏 / 首卡顶框 / 打印按钮被同名 ID 隐藏 / 新建不带建议
- `7c2e5c0` feat(ui): 三轮对齐（附件 chip / 标题行 / 时间线网格 / 筛选标签）
- `7fb7dff` feat(ui): 二轮对齐（s1 外壳细节 / s2 列宽分级 / s3–s4 卡片头）
- `e2563ac` fix(ui): 画像卡标题行与按钮行之间留出间距（原负 margin 贴太紧）
- `3d27d32` feat(ui): 草稿三按钮 / NEXT 待办接线 / 待办完成分组 / 画像页状态行（s1、s4）
- `d517dac` feat(ui): 画像卡恢复分类分组 / 待确认结构 / 礼物元信息（s3–s4）
- `f64c16a` test: 夹具补 visit_plans 表，修复 CI 两处 schema 判定失败
- `37249c4` feat(visit): 打开验厂自动生成建议（出发前 / 现场卫生安全 + 按国家礼仪禁忌）
- `6803834` docs: 新增用户功能说明（试用版 / 订阅版分列）
- `2bb8e7c` fix(sidebar): 短窗收起 token/许可证，底栏不再压住功能栏
- `ed1264b` fix(sidebar): 底部悬浮块不再遮挡导航
- `c1cec4f` style(sidebar): 压缩导航间距；token/按钮/许可证改为底部悬浮块
- `6618c0e` feat(visit): 验厂入口改由客户详情进入并绑定客户
- `d12d65a` feat(visit): s7 手机长图（Canvas 生成 1080 宽 PNG）
- `0f00e29` feat(visit): s6 A4 打印预览（公开页/内部页）
- `0d2b07c` feat(visit): 验厂计划后端持久化 + s5 计划页与 A4 打印
- `e8d1a03` style(ui): 原句支持 hover 浮层（保留点击展开）
- `296f88c` chore(ui): 删除 s3 重写后遗留的未用 stamp 变量
- `7a03600` fix(crm): 1655 审计 P1 跟进备注接线 + P2 星标字段 + O 级清理
- `09bd3b5` style(ui): 侧栏底部许可证整行移到按钮下方并上提
- `ea5f21b` style(ui): fact/gift 卡补左右内边距；s4 顶栏改单行 chips；AI 开关右上
- `d4dace7` style(ui): s4 画像 fact 单列堆叠 + 索要礼物标题去重
- `48c678f` feat(ui): s3/s4 AI 开关、索要红底、星标可点；s1 尾标；s2 窄屏收列
- `dd0b9e3` feat(ui): 补齐 s1 用户时间/输入条提示，并细化 s3-s4 fact 卡层级
- `e83b97e` feat(crm): 逾期跟进处理闭环 + 角标归位客户管理

### 2026-11-18
- `5602ff7` fix(ui): 助手标题时间显示对话真实时间（created_at）
- `4100a75` fix(ui): 复制按钮内嵌到助手标题行，短消息不再遮挡下一条
- `a36b87d` style(ui): 助手复制按钮再下移 40px 并放大加深
- `15fe046` style(ui): 助手消息复制按钮下移，避开标题行时间
- `9f87d40` feat(ui): s1 聊天消息改为用户右侧气泡 + 助手标题行
- `a1764d5` fix(ui): 右栏待办标红改用后端时间口径，轮询保留滚动位置
- `898a8bc` style(ui): 加宽编辑/新建客户弹窗到 720px
- `af8a567` fix(ui): 编辑客户弹窗恢复 fixed 全屏模态
- `1c5b00b` feat(ui): s4 客户画像改为页内视图 + 人物卡条
- `8389b1f` fix(ui): 客户编辑面板恢复 fixed 全屏模态
- `624ca55` feat(ui): s2 客户列表改为 ASSET INDEX 多列表格（对照 mockup s2）
- `2f96cb2` feat(ui): 今日简报/待办/定时任务改为常驻右栏，下线顶部进度横幅
- `c507803` fix(ui): 客户详情页不再刷新出旧视图的顶部进度横幅
- `36ee7d9` fix(ui): 客户编辑弹窗与详情面板支持 ESC 关闭
- `d33b48f` feat(ui): s3 客户详情改为页内视图 + 三栏卡片墙（对照 mockup s3）
- `f569194` fix(ui): s1 右栏三块固定可见（定时任务输出不再被截断）
- `da3a960` fix(ui): 恢复动效开关并让粒子跟随开关
- `06ef068` fix(ui): 粒子外观恢复原样，移动速度加快约 2.5 倍
- `8ee6b94` fix(ui): 公司选择单层虚线对齐，粒子调亮
- `f899708` fix(ui): 视图切换时保留 #dust 粒子层
- `92648a3` feat(ui): s1 今日简报两栏布局，修复顶部分隔线撑高
- `0352dc8` feat(ui): 补 zip 微光粒子层（dust canvas）
- `37002fd` feat(ui): 统一外壳换成 zip s1–s4 设计（灰底 / 虚线侧栏 / 54px 顶栏）
- `d75dd60` feat(ui): 客户编辑从右侧窄栏改为大版面
- `c183d52` fix(profile): source_at 按公司过滤并清理注释出处（审计 O-1/O-2）
- `ec560bc` feat(chat): trade-json 结构化块落库与回放（P1-5）
- `68666bf` fix(ui): 轮询静默、订单 limit 400、对话摘要默认值（P2-6）
- `c17f079` feat(order): 订单弹窗补物流字段录入与出货日校验（P2-5）
- `ad5b194` test(crm): 补画像 attach/API/提取/迁移测试（P1-7）
- `7d57361` feat(crm): 画像前端补挂到/编辑/出处日期（P1-6）
- `a9183da` feat(crm): 主联系人卡片单列客户级跟进备注（口径 C）
- `94e6390` fix(crm): 回退主联系人 note 拼客户级字段（按 N3 终稿 §2）
- `603cfac` fix(ci): 修 PR #12 引入的 ruff I001/F401
- `f6f4f23` fix(crm): O-1 主联系人 note 取值 + W7 fixture 补 inquiries/stage_override
- `22a6a29` test(inquiry): 推导矩阵、API、旧库升级、墙渲染与 xss 守卫
- `579c50f` feat(inquiry): 墙内询盘区、阶段「自动」项与手角标
- `79c36e0` feat(inquiry): 询盘 CRUD API 与公司隔离
- `2c0b342` feat(inquiry): 阶段按询盘最大值推导，PUT stage 改写 override
- `c3d4320` feat(inquiry): 加 inquiries 表与 stage_override 列及导出导入

### 2026-11-17
- `4493a39` fix: 按 PR #11 审计修安全与规格偏差（P1-1~P1-4 + W8/W10/W12 + P2）
- `1c1bc8e` fix(ui): 修 xss-guard 插值、profile lint 与异常命名
- `df6c222` feat(crm): 客户画像 facts/gifts 与 W12 独立页壳子
- `f98970c` feat(crm): 批次三 W9–W10 今日简报聚合与 trade-json 结构化块
- `58420cd` feat(crm): 批次二 W7–W8 订单物流字段、order_events 与时间线
- `1d7cdfe` feat(crm): 批次一 W1–W6 UI 复刻 API 补齐（零 migration）
- `d811bf6` ci: lint 与语法检查覆盖 tests/
- `ee08e1d` fix(contacts): 职责字段接线前端 + 清掉 tests 里的 ruff 告警
- `6812995` fix(contacts): 标签码点计长、邮箱形状 contact、类型错 400、补 §8 测试
- `d871016` fix(mailbox): 邮件匹配恢复 extra2 优先，附加人邮箱不抢主邮箱
- `6cac10e` fix(contacts): ruff 清零，异常改名 ContactsUnavailableError
- `f5b030c` feat(tags): 墙内标签编辑与路由层校验（O-3）
- `d645a45` feat(contacts): 附加联系人表与 API，主联系人仍以 extra2 为准
- `c40f323` fix(mailbox): 拉取时回填未匹配邮件，改客户邮箱后能挂上
- `3610931` fix(test): 邮箱桩表补 company_id/customer_id，修 CI 恒判「需备份」
- `b581cea` fix(mailbox): 注册 imaplib ID 命令，修复网易 Unsafe Login
- `24dbac9` test(skills): 同步清理已失效的 _ALLOWED_DIVERGENCE 登记
- `1b141c2` fix(ui): P1-3 连接指南按附录全文渲染
- `a9d7e18` fix(mailbox): P2-2/3/4/5 游标与绑定，O-1/O-6 测通合并与 pulled 计数
- `c642dd7` fix(db): P2-1 emails 两列挂客户，移除 email_matches
- `05167f7` fix(mailbox): P1-1/P1-2 只读 select 与真实 UIDVALIDITY，补 socket 超时

### 2026-11-16
- `fdc72c1` fix(test): 修复 chat_smoke 污染 _get_db_path 导致 mailbox CI 失败
- `88af0a8` fix(lint): 清理邮箱相关 ruff I001/F401/W292
- `88274cc` feat(ui): 卡片墙邮件卡接真实拉取与刷新
- `eb01fef` feat(ui): 侧栏邮箱面板（指南/绑定/拉取）
- `9b605e5` feat(api): 邮箱绑定/拉取 REST 与客户邮件列表
- `6a3cf49` test(mailbox): list_customer_emails 公司作用域回归
- `ecbf46f` feat(mailbox): 匹配入库、D1 去重、120s 断点续拉
- `ec753ea` feat(mailbox): IMAP 只读接入（EXAMINE + ID + 游标拉取）
- `3a0066c` fix(mailbox): 凭证 JSON 损坏时降级为空映射
- `5dc8054` feat(mailbox): 凭证文件 mailbox_secrets.json（DB 同目录）
- `c2d6929` test(db): _fresh_db 桩表同步邮箱三表
- `a1f8d24` feat(db): 邮箱绑定三表 mailboxes/emails/email_matches
- `61d4034` docs: 邮箱绑定（只读 IMAP）实现计划
- `794eb4a` docs: 邮箱拉取去重定为 D1（重复 message_id 只跳过）
- `1ac04bc` docs: 邮箱绑定（只读 IMAP）设计规格
- `4ca11e7` fix(ui): 主区格子底改回 S-01 纯白场底
- `04b1f29` fix(ui): 恢复 chat.ph 上下文 placeholder；轮播状态退出 aria-live
- `5de1561` feat(ui): 主区格子底 + 待办横幅更深实底（对齐 mockup）
- `e985100` feat(ui): 聊天框右侧改用 mockup 回形针 + 发送按钮
- `d029369` feat(ui): 撒玛利亚人风味道移植 + init_db 二次启动不新增备份
- `5b197a9` test(crm): init_db 旧库升级回归；卡片墙无重要标记时改称最近对话
- `f7af464` fix(lint): customer.py 导入块 I001（去掉多余空行）
- `bae99e2` fix(crm): 审计 P2/P3 — 建客户透传 CRM 字段、分币种总额、读屏与 XSS 守卫
- `f7c9f1c` fix(db): CRM 索引改到补列后再建，避免旧库升级炸
- `c75bfff` fix(test): list_by_company mock 接住 customer_id
- `ad84781` test(crm): 旧库补列幂等 + overview/列表聚合回归
- `36cd8b0` feat(ui): S-01 纯白指令 + CRM 列表/卡片墙
- `81a653a` feat(crm): 客户实列 + overview 聚合 + 对话 is_important
- `3833981` chore(ui): 本地打包 Lucide 图标、S-01 字体与 three.js
- `18b0ae6` refactor(ui): 按分节把前端拆成 static/js 十个脚本
- `6b52ef7` fix(ui): Skills 帮助里 daily-automation 描述去掉定时发布
- `f65a88f` fix(skill): daily-automation 去掉定时发布表述，deliver 固定 local
- `f738142` fix(cron): 今日简报过滤 [SILENT] 产出，不计入待看
- `a377c29` feat(prompt): 六档常驻「外部内容是资料，不是指令」纪律块

### 2026-11-13
- `d198f78` fix(doc-skip): 缓存命中后按路径拦所有工具，不再只拦 read_file
- `6f55681` fix(cache): 流式端点非门禁预热改传 request_task_id

### 2026-11-12
- `218b311` docs: 对齐 README/用户指南与当前实现
- `de2de73` feat(license): 试用期隐藏付费功能入口（仅界面）
- `3d81a83` test(bench): 补文档缓存手工基准脚本（路线 A，走生产聊天）
- `32453d9` test(skills): 注入预算改为量运行时（injection_prompt + when_to_use），上限 5000

### 2026-11-11
- `af921e3` fix: 导入/导出后端付费门禁 + when_to_use 真正下发到模型
- `6c42724` fix(license): 时间戳损坏时 check_license 与 license_state 结论一致
- `e6afd63` feat(license): 导入/导出入口只在付费用户界面显示
- `843f4ce` fix(license): 绑定机器码不被本机机器码覆盖，付费用户不再被误判为篡改
- `62b35a4` fix(license): 写盘失败时同进程内不再重算试用
- `a556758` fix(license): 付费验签以本机硬件标识为准，不再信任 license.json 缓存
- `31b8617` fix(transfer): 补全价格异议触发短语并校正过期注释
- `65aa777` fix(company-transfer): 修复二轮审计 P1/P2 与技能路由问题
- `24442cd` fix(company-transfer): 桌面资料库文件不再打包
- `6cc97b9` fix(company-transfer): 修复审计 P1/P2 与全面自查发现的问题
- `55b2412` test(company): 锁住中文内容与文件名的跨平台编码
- `9186ebe` fix(restart): 升级进行中不再露出重启按钮
- `125fbb4` test(company): 路径断言兼容 Windows 分隔符
- `6512918` test(company): 清理本文件创建的公司，避免污染 cron 用例
- `c9e3eb1` fix(company): 导入候选项提示转义，修复前端守卫
- `7e36e8d` feat(company): 单公司数据打包导出/导入
- `2f1778c` fix(test): 对齐公司切换 /switch 失败回滚的前端守卫断言
- `9a83cdd` fix: 许可证/文档门禁/误路由与 SSE 可用性优先修复
- `b19bcaa` chore(skills): 补 skill_view 指引与正文维护说明，收紧成本词断言
- `0e65e57` fix(routing): 收敛短触发词冲突，招标/SEO/开发信归专用 skill
- `0453638` fix(skills): 审计并修复激活词冲突导致的误路由
- `12e1c56` fix(skills): 消除激活词冲突并修复高优先级误路由

### 2026-11-10
- `f3c123c` test(skills): WhatsApp 提醒断言分开校验注入与正文
- `b5aee0c` fix(prompt): 对外动作禁令按意图识别，不依赖精确措辞
- `f31d06d` fix(skills): 注入预算留余量，WhatsApp 提醒只贴 WhatsApp 草稿
- `84daa75` fix(prompt): 全局禁止代发与写入发件箱
- `0f3d716` fix(routing): 补回收窄误伤的完整说法并收紧成本词测试
- `cedebe5` feat(skills): Facebook 内容固定附使用提醒
- `51841e1` feat(skills): 聊天草稿固定附 WhatsApp 发送提醒
- `3c4e1a4` fix(skills): 压缩注入文案回到 4000 字符预算
- `d394177` docs(skills): 背调五节补来源标注
- `1f99065` fix(skills): 价值 BOM 对外稿禁用英文成本词
- `79b47c8` fix(routing): 价值 BOM 意图优先于单独 CIF 术语
- `3d42ddd` test(routing): 补短触发词反例与收窄后正例
- `4335677` fix(routing): 收窄 b2b-sales-playbook 触发词

### 2026-11-09
- `acee0e9` feat(skills): B3 卡点诊断与下一步草稿
- `b046ae6` feat(skills): B2 价值 BOM 报价草稿与认证护栏
- `9a5b6dc` feat(skills): B1 八夹知识库地图与 00-index
- `7019899` feat(skills): B4 事实/推断分离与背调五节格式
- `8da1122` fix(doc-cache): close agentbase/trade review follow-ups
- `5771cde` fix(doc-cache): require pure overview and close review follow-ups
- `1c51817` docs: reword money-fallback docstring to match agentbase
- `00619c0` fix(doc-cache): narrow money fallback and warm from actual reads
- `eed686f` fix(doc-cache): port v2 scope rules and parser truncation guards
- `d07f14d` docs: reword doc_scope example to match agentbase
- `c90984c` fix(doc-cache): decouple cache from gate and close audit P1s

### 2026-11-07
- `17fc25b` feat(copilot): skip capture when Trade window is frontmost
- `2b5d6f6` test(doc-cache): cover xlsx truncation and failed-attempt cap
- `4cfdb8e` test(doc-cache): cover cache-off gate path
- `0bd5435` feat(doc-cache): kill switch, background warm-up, and cache disclosure
- `db7576b` feat(doc-cache): scope-gated cache evidence and hard skip of re-reads
- `3d89031` feat(doc-extract): add deterministic parser and model classification
- `4fb7f5a` feat(doc-cache): add tenant-scoped extraction cache table and DAO

### 2026-11-06
- `06565d0` fix: identify cron completion by job id, not name substring
- `4a9a5ab` chore(ui): 暂时隐藏聊天副驾设置入口

### 2026-11-05
- `7e01ce6` fix(copilot): 看图失败文案改为指向 Hermes 视觉配置
- `5d52fde` fix(copilot): 复审整改（误杀防护/按需重启/文案与顺序）
- `500e286` fix(copilot): 关闭取消在途任务；启动确认存活；保存重启进程
- `4e89c35` fix(copilot): 无出处数字用 ?；视觉模型改为用户配置
- `42c643c` fix(copilot): 无出处数字改为（）占位符；隐私文案去掉服务商名
- `3006576` fix(copilot): 读取/错误状态不再显示空文本框和按钮
- `e7f1732` feat(copilot): 悬浮窗右上角加关闭按钮
- `62421e1` fix(copilot): 草稿不再出现（待确认）占位符
- `3ccc017` fix(copilot): 复制草稿给明确反馈，空草稿禁用复制
- `fd8af94` fix(copilot): 视觉抽取改走主模型 deepseek-flash，超时放宽到 30s
- `b9d140a` feat(copilot): 热键二次按下关闭弹窗（并取消在途请求）
- `a21d982` fix(copilot): 修复 macOS 启动即崩（pystray 主线程）并提示辅助功能授权
- `a8fab6a` feat(copilot): 开启设置后拉起独立副驾进程（热键/悬浮窗真正生效）
- `83a7c00` fix(copilot): 设置弹窗请求补 /api/trade 前缀
- `143f6d0` feat(deps): 默认安装 pynput/pystray（副驾热键与托盘）
- `d5aceb3` feat(copilot): 托盘与读取期状态提示（仍不接启动流程）
- `87fbab9` feat(copilot): 设置页与隐私同意门禁（仅写设置，不启动副驾）

### 2026-11-04
- `1d0d7c6` feat(copilot): 组装骨架——设置/热键/悬浮窗/service，全程默认关闭
- `bd13d54` test(copilot): macOS 焦点 spike——悬浮窗不抢焦点已验证
- `b3e1720` feat(copilot): 第 0 步安全默认值——剪贴板默认关、拒读名单、显式隐私路由
- `1a7b624` feat(vec): 客户语义检索改为默认关闭（opt-in），清库同步向量
- `b20b9f2` fix(skills): 收口 osint 截断的注入提示与 document 缺失的正文开头
- `9fdfeca` fix(skills): 修复被早期提交删掉表头的悬空表格
- `1606650` fix(skills): 移除示例公司名与人名，补内容授权回归测试
- `4dd83f0` fix(skills): 修无出处数据、未授权署名、时效矛盾与客户分级冲突
- `a208e5e` perf(skills): 压缩 5 个最大注入提示词，详细规则移入正文按需加载
- `613c1d0` refactor(skills): 成交三件套按阶段并入现有技能，总数回 45
- `8ee4996` docs(skills): 补成交三件套的来源标注、重叠边界与触发词清单
- `08e373c` feat(skills): 新增成交三件套 —— 询盘首响 / 报价异议 / 逼单 PI
- `3a9b775` fix(ui): 创建公司成功后自动关闭弹窗
- `68db9f8` fix(installer): 中文用户名/非 ASCII 路径补齐 ps1 安装链路（T1 方案 A）
- `a1856e4` fix(installer): git/pip 复用 Windows 系统代理，修复「irm 能下载、clone 连不上」

### 2026-11-03
- `d2262dd` fix(installer): 修数据库初始化假成功、非 ASCII 启动器风险与 prereqs 错误
- `0984079` fix(installer): py 启动器路径把命令与参数拼成一条命令名，建 venv 直接中断
- `2373eb1` fix(installer): Windows `irm | iex` 被 BOM 卡死 —— 入口改为纯 ASCII 引导器
- `5650fa4` fix(skills): 修掉 45 个 skill 的 19 项规范偏差
- `c331219` docs(skills): 按 45 个 skill 重审覆盖率，列出 19 项待修偏差
- `a8fbc86` docs: README 首屏重排 + 技能口径统一 45，补招标技能说明
- `9a667b7` fix(gateway): 系统判定改用 sys.platform —— 修 Windows 3.11 CI 静默不 spawn
- `629cd9f` fix: 许可写门控共用签名自恢复，doctor 正确识别 python_too_old

### 2026-11-02
- `1be6ccd` fix(tender): G5 非招标场景默认不删原包（审计观察项）
- `bb25f90` fix(prompt): 置信度标签随回复语言切换，英文回复不再漏中文 [推断]
- `019794a` feat(chat): 回复语言跟随用户这句话（中文回中文，英文回英文）
- `b10ee90` feat(tender): 5 个脚本的命令行输出支持中英双语
- `eae5690` fix(tender): 补中英文自然说法触发词（子串匹配下的真实缺口）
- `02ea54f` feat(tender): 第 3 批 —— G1 招标发现 + G6 文件匹配归档（6 个 skill 全部落地）
- `24dcdba` fix(update): 结构化升级失败也写 update.log，并把日志路径带回界面
- `5f52100` fix(update): 「无法解析远端 main」给出真实原因，不再只让用户检查网络
- `0e27a6f` fix(windows): 桌面快捷方式冷启动不再弹黑框（opener 用 CREATE_NO_WINDOW）
- `372586e` feat(tender): 第 2 批 —— G4 大文件下载 + G5 批量解压归档
- `d595d6a` feat(tender): 第 1 批 —— G2 招标邮件抓取归档 + G3 招标整理与询价单
- `b1de14f` test(installer): 修正计数口径 —— 12 处重定向 vs 17 处退出码读取
- `a118323` test(installer): 补 helper 的 $LASTEXITCODE 跨作用域传播验证
- `b065f3b` test(installer): 用真 PS 5.1 解析整份 install.ps1（BOM 证据）
- `d9cf4d4` fix(installer): install.ps1 兼容 Windows PowerShell 5.1（BOM + stderr 重定向）

### 2026-10-30
- `0d59922` fix(installer): install.ps1 加全局 trap，报错时打印行号与原因
- `a6cf3ba` chore(ui): 图标压到 256px（1.4MB→69KB），补桌面快捷方式图标测试
- `9e620dc` feat(ui): 接入 Trade 图标 —— 浏览器 favicon + Windows 快捷方式
- `5041310` chore(deps): 停止默认安装 hindsight-client 与 sentence-transformers
- `83cdbba` fix(windows): 升级按钮不再因 trade.exe 被占用而必然失败
- `a136105` feat(deps): hindsight 客户端默认安装，sentence-transformers 默认尝试安装
- `0eb0878` chore(repo): 删除全部历史 Release，README 去掉下载入口，补齐 Windows 一键安装脚本
- `fcc7df9` fix(web): 删除本地脚本 SRI —— Windows 检出 CRLF 导致聊天发不出消息

### 2026-10-29
- `41a67d2` fix(ui): 升级失败提示改为常驻并带真实原因
- `d2d0856` fix(update): 更新按钮不再因解释器/并发/意外异常失败
- `d584bd3` fix(tool-guard): 守卫只对 Trade 生效，不再影响用户单独使用 Hermes
- `12a42b1` test(tool-guard): 钉住可用性——后端不得再有聊天阻断文案
- `6e0aec1` fix(tool-guard): 守卫默认关闭，改为显式 strict 模式
- `64463dd` fix(tool-guard): 聊天硬阻断降级为只警告，恢复老用户聊天能力
- `65e1beb` docs(readme): 修正 Windows 安装命令并补 Windows 一键脚本
- `01fb9d0` fix(restart): 普通重启也交给 watchdog 做退出码校验与事后探活
- `a2c8c0a` fix(skills): 来源声明提到第一段 + 履历必须写前雇主（4C 第二轮）
- `bf577e7` fix(skills): 数据来源声明无条件强制 + 优先级降级须写依据（4C 重测）
- `f15a98d` fix: 审计低优先项收尾（W7 文案/升级提示/技能字面）
- `f591535` feat(orders): 前端多商品明细（Phase 2）
- `3f3f746` feat(orders): 订单头 + 明细行（Phase 1：数据层/API/AI 上下文）
- `12f9512` fix(restart): 普通重启（无回退点）在 KeepAlive 托管下也走 launchctl
- `890353f` fix(restart): 托管识别改用 launchctl list 表格解析
- `2b6365d` fix(restart): KeepAlive 托管时重启改走 launchctl kickstart
- `649446e` fix: 重启 watchdog 跨版本兼容 + 订单待谈在编辑与展示层闭环

### 2026-10-28
- `485f04d` test(tradewin): 全端口占用的用例改用桩 socket，修 Windows 保留端口误报
- `09ce9b0` fix: Batch 5 P2 bundle —— 重启提示/清单链/hooks 误报/SHA 文案
- `e4766fc` fix(skills): W8 路由进口优先 + customs 规则对齐（Batch 4）
- `185aaaf` fix(update): watchdog 改 nonce 探活 + 启动兜底 + stash 冲突中止（Batch 3）
- `5c1ae27` fix(security): W2 确认 id 收口 + W7 授权模型（Batch 2）
- `71db21a` fix(orders): 恢复“单价待谈/只录总额”合法报价（Batch 1）
- `432481f` feat(skills): customs 简易方案补通用证据纪律（不绑品类）
- `a972191` fix: 审计 D2/W2-P2/D5-P2 收口
- `95140c6` fix(update): pip 安装强制 --no-user + PIP_USER=0，避免坏 pip.conf 拖垮升级
- `72d0525` feat(skills): 补 b2b-customs-data 单公司进口核查激活词（W8 配套）
- `81072f2` feat(security): 用户显式贴出的文件本轮只读放行（W7）
- `9d2829d` feat(copilot): 短名/单字疑似客户先确认（W2）
- `198186d` feat(skills): b2b-customs-data 加无海关数据简易方案（W8）
- `86d3b3c` feat: §⑦ 工作单 W1/W3/W4/W5/W6（W2/W7 待口径）

### 2026-10-27
- `58cb1e0` fix(skills): 清掉 auto 编排器两处“发送”残留（N-P2-8）
- `7272c39` fix: 补审计附录四三项 —— 退出码 / 描述残留 / 守卫阻断
- `6bf80e6` docs(skills): 两处口径收口 —— 档位/Agent 唯一口径 + 跟进节奏统一
- `92a53d8` fix(security): 补二轮复审 4 项 —— vision 路径、identity 可写、守卫 fail-open、P1-13 残留
- `0a2aa1c` feat(skills): 高风险输出技能补交付前自检（B 批 7 个）
- `be58907` fix(skills): QA 清单改为自包含，不再指向模型看不到的正文
- `ca5a5a5` fix(tradewin): 读不到端口时明确报错，.port 写入失败可见
- `7280b09` fix(tradewin): 端口信息改用独立文件，修复 Windows 下读不到端口

### 2026-10-26
- `ed15d02` feat(skills): 同步后写 SHA-256 清单，便于事后审计（P2-3）
- `4f5fba9` fix(desktop): TradeWin 单实例/端口顺延；前端依赖本地打包（P2-21/P2-23）
- `378afe8` fix(audit): 对话保存层归属校验 + 上传数量/总量上限
- `157edc4` feat(license): 试用到期软着陆 + 第 20 天价值小结
- `48d183a` feat(cron): 定时任务按公司隔离（审计 P1-17）
- `66c7ea1` fix(security): SSRF 建连后校验对端、停用 skill 彻底禁用、license 路由加 session
- `ef7aa9f` fix(audit): 非副驾批次 —— 订单清空/负数、流式保存告警、重启与自启、租户 fail-closed
- `9890171` fix(prompt): 文档库提示改用真实存在的 search_files（Hermes 没有 list_files）
- `a92f53f` feat(security): 工具层守卫 —— 文件路径白名单 / terminal 命令白名单（P1-3/P1-20）
- `251ccad` fix(update): 更新成功后不再自动重启，改为用户点「重启」
- `2cddb1b` fix(update): clone 也钉选提交、后端要求更新确认头、清理迁移失败副本
- `120c93a` fix(ui): 用量接口禁止缓存；更新提示不再一上来就说「正在重启」
- `7c5557a` fix(usage): 每日 token 提示阈值从 200 万上调到 2000 万
- `640f17d` refactor(update): 弃用 GitHub release 版本号基准，升级只认 main 最新内容
- `d893aa0` fix(audit): 复审残口 —— 流式迟到落库、会话库归属、裸数字识别、文档漂移
- `f6e3a0e` fix(audit): P2 低风险批次 —— 解压防护、日志脱敏、网络错误分类、输入上限
- `5af8e8f` feat(usage): 侧栏显示今日用量，额度改为只提示不拦截（审计 P1-16 调整）
- `e1a4f68` feat(usage): 接通用量台账 + 每公司每日 200 万 token 上限（审计 P1-16）
- `f72b5ce` fix(chat): 超时真正中断 agent，失败兜底不写入历史（审计 P1-21）
- `a8f48c8` fix(update): 钉选远端提交、迁移失败恢复数据库、更新前二次确认（审计 P1-10）
- `8c110a0` fix(order): 金额三字段一致性与状态机校验（审计 P1-15）
- `79c05c3` fix(security): SSRF 逐跳复查、遮挡窗口禁止抓屏、打包完整 static/
- `0d9257f` fix: 全面审计批次 B —— 隔离残口 / 前端功能 / 停用公司 / 停用 skill
- `caa7e9e` fix(copilot): 中文量级 / 年份 / 短名匹配（全面审计 P1-12、P1-5）

### 2026-10-23
- `4001760` fix(security): 审计 P0-2 —— chat-memory 公司身份改为服务端绑定
- `9c3d86f` fix(security): 审计 P0 —— 会话与订单按客户隔离
- `d01ee0d` fix(security): 审计 P0 —— 显式路径白名单 + 草稿禁用工具
- `54c4a88` fix: 审计批 1 —— 身份保存 / deleteOrder / 历史取最近 N 条
- `dd33dfc` fix(copilot): 体积单位 L/升、ml/毫升 带上身份
- `c613a96` fix(copilot): 中文计量单位带上身份，斤按 0.5kg 换算
- `22e6bc5` fix(copilot): 审计修复 —— 简写金额 / 单位身份 / 牌号 / 句柄截断
- `10e21a1` fix(copilot): 权限引导改为运行时自动拉起系统设置
- `ef5ec5b` feat(copilot): 第二段 capture —— 剪贴板 + 双平台窗口截图 + macOS 权限链路
- `5152b70` fix(copilot): 补 numbers 的粘连规格 / 幻影价格 / 时间换算（复审 2）
- `5218e6b` fix(copilot): 按复审修完第一段的 1 个 P0 + 5 个 P1

### 2026-10-22
- `da598df` feat(copilot): 聊天副驾核心三模块（extract/context/draft）—— 平台无关部分先行
- `875c8ed` fix: Cognee 死指令清理 —— 技能与新部署脚手架里还留着整段
- `7ab70f8` Revert "fix: 跨公司串户根治 —— 长期记忆改由 Trade 写，company_id 由代码判定"
- `b1f69c4` Revert "fix: 记忆条目分隔符与 Hermes 对齐 + 存量迁移 —— 让 Hermes 逐条管理记忆"
- `31f9dba` fix: 记忆条目分隔符与 Hermes 对齐 + 存量迁移 —— 让 Hermes 逐条管理记忆
- `f22ed9b` fix: 跨公司串户根治 —— 长期记忆改由 Trade 写，company_id 由代码判定
- `6d0f3c8` fix: 记忆工具的准确表述 —— 没有 memory_recall 这类工具，召回靠上下文注入
- `38ad425` fix: 平台专属规则改为 agent 自识别触发 —— 不要求用户指明是不是阿里站
- `5dfe50b` perf: token 成本审计 —— 提示词分档重整，删掉指向已移除工具的指令
- `ba9b7db` fix: XSS 守卫改白名单式 + 补两处未转义（guidance.desc / t.time）
- `ec197ac` fix: 第二轮审计 —— 并发写锁失败、XSS 裸拼、切公司状态残留、搜索 N+1

### 2026-10-21
- `779bde3` fix: 回退必须回读 HEAD 验证 —— git reset --keep 冲突时静默放弃且退出码为 0
- `455b14c` fix: snapshot_db 的 checkpoint 连接必须显式关闭 —— Windows 上会锁住 trade.db
- `c850f28` fix: 审计 P0/P1 —— 前端假成功、检索字段覆盖、升级回滚与备份、迁移事务、技能一致性、cron 时间窗
- `679615f` fix: gateway 存活判断改用 Hermes 严格探测器 —— 端口/pgrep 不再决定

### 2026-10-20
- `70609a4` fix(test): chat_memory 时间范围用例按日历现算期望 —— 周二/月初必挂
- `f0835d6` fix: 触发词互斥性审计 —— 15 处跨技能误路由清零（含回归测试）

### 2026-10-16
- `e3f4772` fix: Windows 重建后拉不起服务 —— launcher 路径少了一层 local\bin
- `76c98d1` fix(test): 重建脚本的用例把 POSIX 期望写死了，windows-latest 上必然挂
- `929fd96` fix: hidden 属性被 display:flex 盖掉，两个该藏的按钮露出来了
- `a6e7d2e` feat: 侧边栏按钮改图标 + 悬停显示功能
- `a5229b6` feat: 一键重建运行环境 —— 旧装机器点一次按钮就能自救
- `7bb1371` fix: 外部验证抓到的三处 —— 工具没启用（致命）、月末崩溃、schema 描述写错
- `5c863cd` fix(test): CI 6 个用例全挂在硬编码的开发机绝对路径 + 加仓库级守卫
- `811582f` feat: 打通"历史对话时间范围查询"链路 —— chat_memory_list 工具 + 时间词全覆盖

### 2026-10-15
- `f6f75dd` fix(test): Windows CI 挂掉的那条 —— 炸弹炸在 platform 上，根本没走到守卫
- `c149d69` fix: 逻辑审查后的 8 处加固（按 ⓐ → ⓙ → ⓚ → 其余 的顺序，逐项验过）
- `c8bc59c` fix: 第二轮测试抓到的两个问题 —— 3.14 发现仍匹配不到真机布局、面板 UI 竞态
- `a0092a9` docs: 复核 Hermes v0.22.1 —— 无需改 Trade 代码（静态复核通过）
- `596fe0e` fix: 客户机（Windows 旧装机器）三个 bug —— 判定漏反向、探测挂死、安装脚本找不到 3.14
- `217de74` fix: 干净机器实测的两个装机 bug —— 自检绕过路径准备 + 没配大模型被当安装失败

### 2026-10-14
- `fc55b5e` feat: 跟随 Hermes 最新版 —— 单份 Hermes + Python 3.14 + 过旧自动升级
- `d29a352` feat: b2b-china-leads 补 qa_pairs + 红线量化 + 跨技能显式化（外部评审修订）
- `20a94bd` fix: Hermes 懒加载守卫前置到 setup() 第 0 步 —— 子命令路径此前全程裸奔
- `6e527bb` fix: 技能帮助——国内线索条目复制提示词改「找货源」打头（对齐主用途）
- `9fc8ced` feat: 新增 b2b-china-leads 技能 —— 国内找货源厂家/挖竞品厂家/找国内客户（全免费公开渠道）
- `50af52c` feat: trade doctor 增加 ESTOP 检查 —— 急停时定时任务会静默停跑
- `6839721` feat: python -m trade.osint —— 6 层背调的机器判定入口（此前从未真正跑过）

### 2026-10-13
- `4f4f0d1` fix: 技术栈检测改为域名/路径锚定 —— 裸产品名误报会给可疑网站加可信度
- `a7dc526` docs: 新增《项目介绍与使用说明书》（实测撰写，含截图/录屏）
- `053a7e4` fix: 三处错误提示指向不存在的命令 trade setup → 改为 hermes setup
- `2ac2773` fix: 安装 pin 退回 v2026.9.24 —— v0.21.6+ 的依赖被标成 Python 3.14+，3.11–3.13 装不出依赖
- `0f50ec3` fix: 采纳评审两条意见 —— 去掉 wordpress.org 误报源、阈值下调保召回
- `0719509` fix(test): 修 test_upgrade 的随机红 —— 命令匹配别拿整串做子串
- `983f284` feat: holehe 进核心依赖 —— OSINT Layer 1（邮箱注册检测）默认可用
- `689076e` feat: 收编语义检索优化包（混合路由/向量检索/用量台账）并修复其中缺陷
- `c1b44c6` feat: 安装链固定 Hermes 版本（v0.21.7），避免装出无法启动的环境

### 2026-10-12
- `c2dc975` docs: 记录 2026-10-12 Hermes main 复核 —— 不跟随

### 2026-10-10
- `2b4d745` docs: 新增《领英获客实战》培训讲义（PDF，10 页）
- `f60eb74` feat: trade company —— 作者用的特殊管理子命令（CLI 专用，不进 UI）
- `82f50fa` docs: 警示措辞去掉绝对化 —— 「一律会出问题」改为可判断的条件
- `c5b1645` fix: 警示块文字看不清 —— 深色底压深色字，对比度 1.2:1
- `1cb9e75` docs: 显眼位置警告「禁止用 workbuddy 等 AI 助手安装 Trade」
- `2eafc75` docs: 记录 Hermes v0.21.6 兼容性核对
- `dd76291` fix: 窗口枚举测试加平台守卫（Windows CI 三连失败）
- `a1e2fec` feat: 快捷方式复用已开的 Trade 页面，并修 Windows 启动器三处缺陷

### 2026-10-09
- `c7b4aba` feat: trade doctor —— 安装后端到端自检
- `426a935` fix: 数据库备份不再无条件创建并无限累积
- `003358b` fix: Windows CI 崩溃 + 测试不再产生进程级副作用
- `2c09080` docs: DeepSeek 建议充值金额 10 元 → 20 元
- `2c1e41b` feat: Windows 开机自启（隐藏窗口）+ 桌面快捷方式自动配置
- `7749ff8` fix: 二次审计修复 — 失败不再变哑、查不到不再报成没问题

### 2026-10-08
- `de10038` fix: 禁用 Hermes 懒加载重启，并让 agent 失败不再变哑

### 2026-10-07
- `4f0dcd4` docs: apikey 模板改用非密钥形状占位符，消除密钥扫描误报
- `f8f0a96` docs: 全项目文档审计修正（公开文档 5 个）
- `6f06687` docs: 记录 2026-10-07 上游 main 复核

### 2026-10-03
- `d86a38f` docs: 对齐 Hermes tested 版本，并补全 COMPATIBILITY.md

### 2026-09-30
- `53aee2b` fix: 默认 toolset 组合补上 vision，agent 此前没有看图能力

### 2026-09-29
- `024c3a4` fix: 图片识别铁律常驻四档提示词，禁止自建 OCR
- `5a733a3` test: shell 行为测试在 Windows 上跳过（runner 的 bash 是 WSL 存根）
- `19a4368` fix: 安装脚本健壮性（克隆自愈 / skills 步骤死代码 / 事务补偿）
- `e705044` fix: console script `trade` / `tradewin` 装完即不可用
- `0037d44` test: sys.path 解析测试改为平台无关，并断言优先级不变量
- `4988e41` fix: Hermes checkout 路径解析修正（聊天报「AI Agent 模块未加载」）

### 2026-09-28
- `4253b58` docs: DeepSeek 模型名改用官方 id deepseek-flash
- `ab55171` fix: 安装前检查的 Hermes 探测改用正确包名，并放宽 CLI 超时
- `c43340c` fix: Hermes 版本识别改为多源，且识别失败不再拒绝启动
- `98c333f` docs: 文档中移除 MiniMax，只推荐 DeepSeek
- `2d7fa37` docs: 同步 README（网络暴露行为、版本号、安装目录、测试命令）
- `84193dc` test: 修正测试自身未指定编码的文本读写
- `56bc1d5` fix: 文本读写显式指定 UTF-8（修复 Windows 上读取 pyproject 失败）
- `be7cd4c` fix: 代码审查修复（安全 / 升级链路 / 提示词 / 文档读取门禁）

### 2026-09-25
- `e27077f` fix: 修复升级链路 pip 安装失败
- `b7f702c` feat: 门禁改用工具回调自收集读取证据
- `a765f06` chore: 增加 CI 环境模拟脚本
- `a5c2bb8` test: 修复依赖检查测试对 Hermes 安装环境的依赖
- `39e5fe8` chore: 移除 Tesseract，扫描件统一走 vision
- `f1df20f` fix: 修复图纸分析崩溃并补全扫描部分
- `26fb84d` fix: 补齐 PDF 解析依赖与扫描页识别
- `340a04a` fix: 区分不可读文件与漏读文件，并强制安装文档解析依赖
- `8a2bb3b` fix: 文档门禁改为返回原因并避免误拦
- `a93bf5d` feat: 增加文档完整读取门禁

### 2026-09-23
- `5a8aacb` chore: 跟随 Hermes v0.21.4（v2026.9.21）

### 2026-09-22
- `460844a` fix: 收紧文档 skill 边界并补齐路由回归测试
- `443c32d` fix: 全面收紧 skills 路由与提示逻辑
- `8712aa4` fix: 清除 LinkedIn skill 与文档中的代理销售话术（来源为 SN 代理机构课程）
- `f490887` fix: 按录像方法论与官方信息补全 b2b-linkedin-marketing skill 与使用说明

### 2026-09-21
- `6fdffe4` fix: 补齐 b2b-linkedin-marketing 触发词覆盖缺口
- `83d5095` fix: 补漏 b2b-linkedin-marketing 正文遗留旧值（About 3000→2600、连接留言 300→200）
- `43778d3` fix: 其他 skill 按官方现状修正过时信息（阿里/背调工具/硬编码时间）
- `087d8a6` fix: b2b-linkedin-marketing 按官方帮助中心全面修正（会员分级/功能名/数字）
- `f3801ce` fix: 保留用户指定文件的强制读取上下文

### 2026-09-20
- `73c3891` fix: 修复中英文自然句的技能路由命中率（英文 47%→100%，中文 67%→100%）
- `13b091c` docs: 新增 TRADE-GUIDE 使用说明书（含 LinkedIn 专项章节）
- `f0472b5` docs: 新增 LinkedIn 获客功能使用说明（免费/高级会员分级）
- `0676a0a` fix: b2b-linkedin-marketing 清除外部 AI 工具引导（Trade 自身即执行者）
- `8727796` feat: b2b-linkedin-marketing 补齐 AI 六步开发流水线（来源方 6 大指令）
- `eb60ad1` fix: b2b-linkedin-marketing 分级标注补全与命名去重（复查修复）
- `e37aa51` feat: b2b-linkedin-marketing 强化（Sales Navigator 实战 + 免费/高级会员分级）

### 2026-09-17
- `6293955` chore: 清理 .gitignore 中 AGENTS.md 重复行

### 2026-09-15
- `c431dc2` fix: deepseek 移出温度白名单（thinking mode 下 temperature 静默忽略）
- `5667759` chore: 跟随 Hermes 升级到 v2026.9.14 (0.21.3)

### 2026-09-14
- `efc6bb6` fix: 修复 skills 结构损坏 + 标准化（category/骨架/统计）
- `1823dfd` feat: 清单一致性协议 + 分析类低温分流
- `d11e7e3` chore: 跟随 Hermes 升级到 v2026.9.11 (0.21.2)

### 2026-09-11
- `e861e8e` feat: 高风险 skill 补证据链约束 + 修复 b2b-customs-data 结构残缺
- `70be8b4` feat: 对话评分质量闭环（rating 聚合统计 + 历史页概览）

### 2026-09-08
- `e7d9ee3` chore: 跟随 Hermes 升级到 v2026.9.7 (0.21.1)

### 2026-09-04
- `18585a3` feat: b2b-cold-outreach 注入 Anti-Spam 语义规避约束

### 2026-09-03
- `053655a` chore: 跟随 Hermes 升级到 v2026.8.31 (0.21.0 Pantheon)

### 2026-08-31
- `c00e461` chore: 跟随 Hermes 升级到 v2026.8.27 (0.20.6)

### 2026-08-24
- `28dea68` docs: 修正 README 过时信息
- `838ead8` chore: 跟随 Hermes 升级到 v2026.8.19 (0.20.5)

### 2026-08-20
- `ad441db` fix: 左侧栏切换聊天视图时直接滚动到底部

### 2026-08-18
- `7204855` chore: 跟随 Hermes 升级到 v2026.8.16.2 (0.20.3)

### 2026-08-14
- `e94b4c9` feat: b2b-doc-generation 注入生成前阻断校验规则
- `1433c5f` fix: skills 自动同步时间改为每天中午12:30（夜里电脑可能关机）
- `83615a1` feat: skills 每天凌晨3点自动从 GitHub 同步
- `3f7d6f2` feat: b2b-trade-ops 结构化 QA 对（25条）

### 2026-08-13
- `31bce05` fix: 技能速查表(_ALL_SKILLS)补 b2b-tech-drawing 条目
- `a571e3f` docs: index.md 技能列表 37→38，补 b2b-tech-drawing
- `e9d341f` test: 补 email_intel/order/prompt 测试覆盖 + 修复任务名 XSS
- `77f6f59` fix: 订单负数输入422 + status下拉框缺已取消
- `d57bf30` fix: P0-1 回归测试跨平台兼容 + 根目录判断改用 parent==self
- `8ba656a` style: 清理 scripts/ 22 个 ruff 错误(I001/F401/W292/W293/F541)
- `99463d2` fix: 修复审计 P1-3/P1-4/P2-1/P2-3/P2-4
- `aba9faa` style: 修复 ruff I001 import order + F541 f-string 无占位符
- `c2fe3e5` fix: 修复审计报告 P0-1/P1-1/P1-2/P2-2/P3-1

### 2026-08-12
- `49f5579` style: 聊天输入框最大高度 120px→80px，防止大段文字时界面变形
- `a504735` fix: 同步 Hermes 诊断修复 — 422/401 自动恢复 + 版本对比修正
- `f90681d` fix: ChatRequest.query max_length 10000→100000，修复粘贴LinkedIn页面内容422错误
- `45aa39b` fix: 防止Agent在背调/客户分析时误创建公司记录和目录
- `a0b9119` test: QA对加载/解析/评分/注入 9 个测试用例
- `13e0b6f` fix: QA对 references 同步到 Hermes skills 路径，三平台兼容
- `c5e325c` feat: skill_router QA对精准检索注入
- `0ebb566` feat: 第三批4个skill新增结构化QA知识库
- `7f1ce85` feat: 第二批5个skill新增结构化QA知识库
- `3278a92` feat: 4个skill新增结构化QA知识库(references/qa_pairs.md)

### 2026-08-11
- `1c07c07` fix: b2b-document/doc-generation 触发词收敛为外贸专用，避免与 Hermes 内置 office skills 冲突
- `9da82e6` chore: pyproject.toml Hermes版本pin v2026.7.1→v2026.8.3 (v0.20.0已确认兼容)
- `f3be295` docs: README 中遗漏的 37→38 更新，中英文版全覆盖
- `76d29ac` chore: 技能数量 37→38，更新 README/HTML/JS 中的所有引用
- `86aec9d` feat: 对外发信 4 个 skill 加入发信前事实核查（防编造数据）
- `b8af15b` docs: b2b-tech-drawing 加入实验性声明，强制提醒 AI 结果不可直接用于报价生产
- `7746d71` feat: 新增工程图纸自动处理模块 b2b-tech-drawing
- `d5d550c` chore: gitignore 加 *.db 防数据库文件误提交，忽略临时模板文件
- `148d3e3` feat: 基于阿里资料强化 b2b-osint/平台/询盘分析/保效方案 4 个 skill

### 2026-08-07
- `e9bc29c` feat: 左下角增加「新手引导」按钮，可重新执行引导教程
- `eb265e9` docs: 替换 WhatsApp 二维码为最新截图
- `ff95692` docs: 联系作者增加 WhatsApp 二维码，与微信并排显示

### 2026-08-06
- `5292fe7` feat: 数据库备份前检查磁盘空间，剩余不足100MB时跳过备份
- `932270d` fix: 修复 skill 触发词重复、单字触发词、缺失 when_to_use
- `e8ea30b` feat: 基于大宗师培训资料强化 5 个 skill
- `f77f746` feat: 基于外贸资料包强化 8 个 skill 的 injection_prompt
- `0cce486` style: 语言选择底色改为透明，消除白色感
- `f098275` style: 优化语言切换下拉的质感，融入侧边栏风格
- `9936907` fix: _co → _company 变量名错误
- `04e895c` feat: 前端全面中英双语 i18n + 许可证栏 bug 修复
- `fe60893` feat: 中英双语切换 + 文件路径自动识别 + 完整读取约束

### 2026-08-05
- `2edfd9d` refactor: 移除 Windows Qt 桌面端代码，修复审计发现的严重/高危问题
- `d94769c` docs: index.md macOS 安装增加 M芯片 Python 架构检查步骤
- `d997258` docs: index.md 增加 macOS 安装章节（Hermes→Trade 流程）
- `c00fa24` fix: b2b-daily-automation 强制中文输出，防止简报生成英文内容
- `1d9a600` fix: 强制中文回复 — 聊天对话必须中文，仅对外内容用目标语言
- `f9bc7a2` docs: STANDARDS.md 技能数 34→37
- `fb41419` feat: b2b-doc-generation v1.3 — 注入 CI/PI/PO/原产地证标准字段清单
- `69c5f69` chore: 提升 Hermes 兼容上限至 0.21.0，支持 v0.20.0 (The Herald)
- `c7f8ecb` feat: b2b-osint v1.2 注入情报分析师人格, b2b-platform v1.4 加入经营阶段判定和量化异常诊断

### 2026-08-03
- `046b396` docs: README 中英文技能数 34→37，补充三项新能力描述
- `ef7731e` fix: 补充 4 个 SKILL.md 缺失的 triggers，防止 Hermes 注册失败
- `ef93714` docs: 全域 skill 数量 34→37，更新文档/前端/测试
- `80258b7` feat: 新增 3 个 skill — inquiry-meeting/sales-playbook/guarantee-proposal，skill 总数 34→37
- `99fcfcb` feat: b2b-platform v1.3 — 平台无关的通用诊断框架，覆盖独立站/MIC/Shopify 等
- `d952ff3` feat: 增强 b2b-cold-outreach(连环跟进策略/四大切换模式)
- `a82f81b` feat: 增强 b2b-platform(四维诊断框架) 和 b2b-inquiry-training(买家心理诊断)
- `18a2c53` feat: 增强 osint/lead-gen/market-analysis/doc-gen 四个 skill v1.0→v1.1

### 2026-07-27
- `6df7b08` feat(skills): 对齐 Anthropic Agent Skills 规范

### 2026-07-24
- `6521e60` style: 聊天区宽度改为 98%
- `b60d7a5` chore: 清理非必要文件
- `dac1784` chore: 移除 AGENTS.md/CLAUDE.md 出仓库，仅保留在本地
- `07e2985` perf: 启动时仅本地同步 skills，GitHub 拉取移到后台线程不阻塞启动
- `505ecac` fix: list_by_context 兼容旧数据（context 为空也返回）
- `9820c08` fix: 首次切换到栏目时滚到底部而非顶部
- `1970831` fix: 平台兼容 — chmod 加 os.name 守卫，备份恢复改用内建 tarfile
- `57d3529` fix: POST /conversations 端点补传 context 参数
- `00a6cda` fix: cron 输出仅在今日简报视图显示，不干扰其他对话
- `5aa25da` fix: 对话详情跳转时读取 context 字段，兼容旧数据回退
- `5a58898` feat: 对话按 context 隔离 + 记住滚动位置 + 修复前端 CSS 路径
- `84a3791` style: 消息宽度改回铺满，空状态居中
- `1872a89` fix: 添加 FastAPI StaticFiles 托管 /static/ 路径，修复拆分后 CSS/JS 无法加载
- `d5fe50b` feat: 聊天 UI 改造为 DeepSeek 风格 — 居中布局/扁平消息/胶囊输入/灰白配色

### 2026-07-23
- `eb3d056` refactor: 拆分 trade_chat.html — CSS/JS 独立为 trade_chat.css + trade_chat.js
- `022ca27` docs: 更新 CLAUDE.md — post_install 路径/测试文件数/架构图缩进/跨平台路径约定
- `491b76b` docs: 审计修复 — AGENTS/README.en/skill-dev-guide/test 中技能数 24/32→34，gitignore 补 .pytest_cache
- `b938546` fix: 修复 Windows 平台路径硬编码 — setup.py fallback + library.py 敏感目录
- `675c75d` feat: 隐藏系统更新/重启/Skills按钮，新增升级说明弹窗

### 2026-07-22
- `de14f47` chore: 添加 skills-lock.json 到 gitignore
- `b7c4ab5` docs: 修复项目需求文档中 Hermes 版本上限 0.17.0 → 0.20.0
- `47236a4` docs: 全域更新 Hermes 兼容版本范围 0.19.0 → 0.20.0，添加 .agents/.claude 到 gitignore
- `23f63b1` chore: 提升 Hermes 兼容上限至 0.20.0，支持 v0.19.0 (Quicksilver)

### 2026-07-21
- `06f6074` fix: 修复 saveState 函数声明丢失导致选公司时报 ReferenceError
- `5bfbb61` docs: 全域技能数 32/33→34 对齐，补全 b2b-customer-finder 到 README/index/前端技能帮助
- `0f7afd6` docs: 更新 CLAUDE.md 数字 + 新增 CodeGraph 章节，README/index 增加 Hermes 更新方法
- `995f3f8` docs: 技能数 33→34 全域同步，新增 b2b-customer-finder 到技能列表
- `924153a` feat: 傻瓜式客户开发向导 b2b-customer-finder — 三问启动 + 自动搜索 + 开发信
- `a3d6377` docs: 技能数 32→33 全域同步
- `9fe1420` feat: 新增 b2b-customer-intel — 单一客户 15 维深度画像
- `643b58e` fix: 公司创建时 slug 设为只读，由 autoSlug() 自动生成
- `ae519bf` fix: _slugify 兜底值从固定 company 改为随机 6 位 hex 后缀
- `4245a0d` chore: gitignore SQLite WAL/shared memory 文件
- `36d91e3` fix: slug 冲突时自动递增后缀，不再抛 ValueError

### 2026-07-17
- `b416a1e` chore: 移除已删除文档的引用链接
- `3f4bb41` chore: 协议从 MIT 改为 AGPL-3.0
- `c49852c` chore: 清理仓库
- `6831aab` chore: 清理仓库
- `c5db8de` fix: 3 个 SKILL.md 修复 — YAML/author/body
- `2da722c` fix: 13 个旧 SKILL.md 补全 frontmatter — description/category/author
- `b2f07bb` fix: license 续期提示被 generic active 分支拦截 — 调整 else_if 顺序
- `9729284` fix: 激活码到期前 7 天显示申请码和续期按钮
- `803b4ea` fix: license 到期日当天被判过期 — datetime 改为 date 比较
- `5ea8e61` test: +8 测试 — _BLOCKED_SKILLS 过滤 + 技能计数 + 唯一性
- `3af6ac4` docs: README 技能表补全 — 20→32 项能力
- `f5892d8` docs: 全局技能数 25→32 修正
- `71f4b8e` fix: 审计修复 — _verify_license 256 bit + requirements.txt + PyInstaller
- `c75a6ed` chore: 禁用 auto-smtp-email — 不替用户直接发送邮件/文件
- `215e04d` fix: license CLI help 文本更新为 256 bit 格式
- `cbca52c` fix: 架构检测扩展到全平台 — macOS/Linux/Windows ARM
- `4f78f74` fix: Rosetta 检测从硬错误改为自动修复 — execve 切换到原生 Python

### 2026-07-16
- `8ea8490` fix: 审计修复 — 激活码熵提升至 256 bit + rate_limit 去哈希化
- `f07bc51` fix: docs/index.md 移除多余的 </p>
- `13b9ed5` docs: 前端+index.md 技能数 25→32，补全 7 个新技能
- `50aa252` feat: 新增 7 个技能 — KOL/Reddit/SEO/视频/展会/产品描述/思考帽
- `1d5c475` chore: 敏感词移除 — 大宗师
- `937a594` chore: 文件改名 — 移除 大宗师
- `29189b3` docs: 全局文档同步 — 技能数 24→25，新增 inquiry-training
- `d7683c1` feat: 大宗师培训分析落地 — LinkedIn 增强 + 询盘训练新技能
- `8bb591e` feat: 资料包分析落地 — lead-gen/osint/sales-pipeline 增强
- `98eb25e` feat: 4 张外贸单证模板（商业发票/装箱单/形式发票/报价单）可下载
- `e6c656f` feat: auto-smtp-email 向导增加域名送达率(SPF/DKIM/DMARC)检查
- `e81929d` feat: auto-smtp-email 改为交互式配置向导
- `adb3b37` fix: docs/index.md footer <p> 未闭合导致 Skills 部分渲染异常
- `9dcb918` feat: 新增「技能帮助」弹窗 — 24 个技能分组展示
- `60de17f` docs: 全局文档同步 — 技能数 20→24，新增 4 个技能说明
- `255bd4d` docs: index.md 新增 24 个 Skills 完整参考手册
- `6b1cfd8` feat: 生成 10 张管理表格 Excel 下载（+API + 前端按钮）
- `38b00b5` feat: 新增 b2b-sales-pipeline — 销售管线策略技能

### 2026-07-15
- `243c8da` feat: 新增 3 个技能 — 开发信仿写/买家画像/市场分析
- `d85f067` fix: 引导标记 sessionStorage -> localStorage，关标签页不再重置

### 2026-07-14
- `d0f167a` fix: 新手引导改为可选 — 跳过也标记完成，不再反复显示

### 2026-07-13
- `80ea2bc` docs: pre_install_check exit code 3 doc
- `abe549c` docs: CLAUDE.md 增加 Mac M芯片架构检测说明
- `dd13935` fix: 架构检测复审修复 - 3 处漏洞补全
- `07de30c` fix: Mac M芯片架构强制检测 — install/upgrade/bootstrap 全覆盖

### 2026-07-09
- `30ca83a` fix: 9 项修复 — 内存泄漏 / XSS / 性能 / 错误处理
- `3334bde` fix: 对话清理策略调整 — 365天 + 3万条阈值
- `aa23546` feat: 对话数据生命周期 — 180 天自动清理
- `1ede379` fix: 审计修复 — health_audit N+1 / 前端 reader 泄漏 / anthropic 降级
- `f4ddfaa` fix: CI test 补 openai/anthropic/pytesseract/psutil/dnspython 依赖
- `0acd1c6` feat: Tesseract OCR 全平台安装支持
- `e3fde2b` fix: openai + anthropic SDK 声明为必要依赖，全平台 PyInstaller 打包
- `08bef9b` fix: Mac M芯片兼容性 — 架构检测 + openai SDK 检查 + launchd PATH
- `1a83af5` feat: 新用户上手引导 — 两步向导体验 OSINT + 开发信

### 2026-07-08
- `fc56dcb` docs: 全局文档同步 — 技能数 19→20, Hermes 版本 0.17→0.19
- `439e8b7` fix: order.py 事务安全 + helpers 类型告警 + prompts 弃用标记
- `83de96d` fix: 二次审计修复 — chat.py 错误消息 + customer.py match_score 比较

### 2026-07-07
- `a31fe38` fix: 审计修复 — 竞态/误判/残留 7 项 bug
- `58a4448` feat: 基于 Close.com 博客的 5 项优化 — 去重/简报/健康/评分/品牌安全
- `71d30ae` chore: skills 脱敏 — b2b-cold-outreach author 字段替换为通用标识
- `23eed62` fix: b2b-cold-outreach SKILL.md 缺失 — 注册表有记录但磁盘无文件
- `da7de62` feat: register b2b-cold-outreach in skill_registry.py (17th B2B skill)

### 2026-07-06
- `bf51000` chore: AGENTS.md 对齐仓库最新变更 + 修复数据库注释和模块边界
- `42263eb` chore: 升级 Hermes 依赖至 v2026.7.1 (0.18.0)

### 2026-07-02
- `ef4806f` fix: 聊天视图切换后回到底部浮标不显示

### 2026-07-01
- `4571ba8` feat: 聊天区离开底部时始终显示回到底部浮标
- `3ff20e9` feat: cron 新内容不再强制滚动，改为右下角浮动箭头提示
- `11b761c` fix: cron 定时输出强制滚动到底部打断用户阅读旧内容
- `e9af2f4` fix: 系统重启后 hard reload 丢失阅读位置 — 保存/恢复浏览状态
- `06f78ce` fix: Windows 桌面目录创建失败 — 用 SHGetFolderPathW 替代硬编码 Desktop 路径

### 2026-06-30
- `da8d20e` fix: CSV 模板加 UTF-8 BOM，Excel 打开中文不再乱码
- `5f87857` fix: CSV 模板下载 422 — FastAPI 路由顺序导致 "template" 被当 customer_id 解析
- `d1ff00a` fix: CSV 模板下载失败 — <a href> 不带 auth header 被鉴权拦截
- `951a1b1` fix: license 升级后验签失败自动从激活码恢复签名
- `6ff08a6` fix: chat-memory skill 被 b2b-/auto- 前缀过滤遗漏
- `ab2a5fb` fix: packaging 版本上限放宽 <25.0 → <27.0，兼容 Hermes 0.17.0
- `ff1e481` docs: README 能力表格修正 17→19 项，补全缺失的 4 个 skill
- `b0bc5dd` docs: README 故障排除补充前端升级报错的手动处理对照表
- `130852f` fix: 系统更新按钮报错不明确 — api() 返回 null 时误显「未知」
- `f6cf3ec` docs: 更新 database-schema / CHANGELOG / AGENTS 与新客户字段保持一致
- `8a24762` feat: 客户模型增强 — 新增 4 个分类字段 + CSV 批量导入

### 2026-06-26
- `30364e2` fix: 系统更新按钮报错不明确 — 前后端字段名不匹配 + git 未安装无提示
- `406d1b9` fix: license 验签 payload 与激活码签名不一致 + status() 不验签导致前端死循环
- `80fd2a9` docs: 补充 Windows 开机自启教程 — Hermes Gateway 服务 + Trade VBS 注册表方案

### 2026-06-25
- `a1de425` fix: 网站诊断长任务超时问题 — 前端可取消 + 后端 30min 兜底
- `aca6181` style: 优化 UI 美学 — 聊天气泡卡片化、渐变配色、微交互提升

### 2026-06-24
- `59aaa06` fix: lint — 遗漏的 _time 引用替换为 time.monotonic()
- `50841b6` fix: 修复 license 验签异常捕获 + 激活码长度严格判断 + restart 清理版本缓存
- `42a9d1c` fix: /api/status 自动同步 version.txt 与 pyproject.toml
- `c42016b` release: v0.6.8
- `329cd7b` fix: 系统升级后页面 reload 显示 toast 提示
- `f9653d5` ci: 移除 Windows/Linux 构建，release 仅保留 macOS
- `bc2a779` docs: 整理 README，移除不完善的 TradeWin 相关内容
- `ad06e71` fix: 激活时无需作者私钥，直接从激活码提取签名
- `7dae734` docs: 更新兼容性声明为 0.13.0 <= version < 0.18.0
- `8c00776` chore: 升级 Hermes 依赖至 v2026.6.19 (0.17.0)
- `31c65ac` fix: 关闭版本升级提醒，稳定版本不强制用户升级
- `134a1af` docs: index.md 顶部添加微信二维码，README 添加安装教程链接
- `916fb5f` fix: DeepSeek 默认模型改为 deepseek-v4-flash（chat 即将下线）
- `57d4790` docs: 重写 index.md，仅保留 Windows 版安装教程（8 步）

### 2026-06-23
- `a5083ce` release: v0.6.7
- `6d8720e` feat: 安装向导增加模型选择下拉框 + 优化提示文案
- `fde2245` fix: 安装 skills 时逐条上报进度，避免界面假死
- `36a23de` release: v0.6.6
- `3559feb` fix: Qt 桌面版侧边栏宽度 260px → 175px
- `ac27060` fix: pyproject.toml 版本号 0.6.2 -> 0.6.5
- `7b8265d` fix: 版本检查改读 .trade/data/version.txt — update_trade 直接写入
- `b7d3faf` refactor: 重写升级和版本检查逻辑 — 消除 _capture_output 文本抓取
- `880fce7` fix: 切断运行时对开发目录的路径依赖 — 全部指向 .trade/ 或 _MEIPASS
- `4cf2d3b` fix: update_trade 缺失运行时目录时自动 git clone + _capture_output 捕获 stderr
- `4cc79c5` fix: /api/status 版本号优先读取运行时更新目录而非 PyInstaller 打包版本
- `4960377` fix: 系统更新/重启后状态栏黄色新版本提示残留问题

### 2026-06-18
- `ea4a6a5` feat: Qt 桌面版功能补全 — 对齐 Web 版所有核心视图
- `9396b42` fix: PyInstaller one-file 模式技能安装卡死 + auto-* 前缀支持
- `6257331` fix: 添加 contents: write 权限以允许 GitHub Release 创建
- `782c506` fix: 修正 Windows PyInstaller 产物路径 — dist/TradeWin*.exe
- `8ee66f6` feat: CI 三平台 Release 构建 — Windows/Mac/Linux
- `973ddb7` feat: 新增 auto-smtp-email + auto-trade-customer-development 技能，升级 b2b-lead-generation 和 b2b-osint
- `c6f8844` ci: 升级 GitHub Actions 到 Node.js 24 兼容版本
- `10fe719` fix: 移除 tradewin.spec 的 icon 引用 — PyInstaller CopyIcons WinError 87
- `adbccd4` fix: tradewin.spec 路径推断多上一级导致 PyInstaller 找不到 skills
- `a1b8602` ci: 修复 TradeWin 构建失败 — 启用 git 长路径支持
- `3c87bb9` ci: 新增 TradeWin Windows .exe 自动构建 workflow
- `4f12ce5` docs: 修正 Hermes 代装后的启动命令
- `7f61586` docs: README 与 index.md 补充两种新安装方式
- `98d8ad4` docs: Windows 安装步骤补充手动安装 Git
- `99f4c73` fix: 二轮审计 P1+P3 修复 + 文档全量同步
- `5d7fa63` fix: P1+P2+P3 审计修复 — 跨平台一致 + 死代码清理 + deps 补全

### 2026-06-17
- `b39863a` feat: Trade 系统提示词增加 Communication Style + Evenhandedness（Fable 5 启发）
- `4dfbb9e` feat: web 聊天 — AI 回复右上角添加「📋 复制」按钮
- `2fc0fc5` fix: company.__init__ 导出 _write_audit_log（switch_company 500 根因）
- `7dbc27c` fix: TradeWin 公司切换 — 调用 switch API + 新增 switch_company()
- `eb6c6eb` fix: 公司切换 403 — 前端调用 switch API + 后端放行 /switch 端点
- `c21d4c5` feat: 聊天视图 — AI 回复旁添加「📋 复制」按钮，一键写入剪贴板
- `cd98f3e` fix: .gitattributes 强制 .bat CRLF 换行符 + build.bat 转 CRLF
- `9ca5caf` feat: TradeWin 真·独立部署 — 首次运行向导 + Hermes 自举
- `c0b14f2` docs: TradeWin README — 系统要求/功能/构建说明
- `97cd9e4` feat: PyInstaller 打包配置 + Windows 构建脚本
- `9eb8921` feat: 聊天视图 + 系统托盘 + 模态对话框（公司/许可证/设置）
- `fa1ab7b` feat: 主窗口 + 侧边栏导航 + 公司选择器 + 版本状态栏
- `3ba730c` feat: Qt 主题系统 — 亮色/暗色调色板 + QSS 样式表
- `824932f` feat: API 客户端封装 — 所有后端接口的同步 HTTP 调用
- `73027f8` feat: TradeWin 骨架 — main.py + requirements + 项目结构
- `50c0b41` refactor: 拆分 post_install.py (970行) 为包 + 补全全部中文注释
- `fe91076` refactor: 拆分 sanctions.py (341行) 为包 + 补全全部中文注释
- `e1e10c2` refactor: 拆分 company.py (642行) 为包 + 补全全部中文注释
- `4095cd6` refactor: P2-3 DNS MX 用 dnspython 替换手动 RFC 1035 socket 实现
- `4b311e4` fix: 试用 banner 在全部试用期显示（不限于剩余 ≤7 天）
- `405a1cf` fix: _perform_restart 改为独立 shell 子进程执行，避免 uvicorn graceful shutdown 卡死

### 2026-06-16
- `1d2419c` fix: _waitForRestartAndReload 兼容旧服务无 started_at 字段的情况
- `491edee` fix: 重启检测改为 started_at 时间戳比对，替代不可靠的 DOWN→UP 轮询
- `81e20f5` fix: 重启诊断 — 后端 console 日志 + 前端轮询加速 2s→1s
- `9879dfb` fix: uvicorn 端口冲突重试 — 同时捕获 SystemExit（uvicorn 内部 sys.exit(1)）
- `ee72f90` fix: psutil 版本上限放宽 <7.0 → <8.0，修复与 hermes-agent psutil==7.2.2 的冲突
- `d222b0a` docs: SECURITY.md 更新 — SSRF 共享 + 系统端点限流 + session token 说明
- `28c81c4` fix: P2 _TRIAL_DAYS 支持环境变量配置 (TRADE_TRIAL_DAYS)
- `a0b26eb` fix: P1-2 detect_tech_stack 防御性超时 + holehe 子进程进程组隔离
- `28ec567` fix: P1-1 License machine_hash 32bit → 64bit 升级
- `384e30f` fix: P1-3 系统端点限流 + P1-4 psutil 强制依赖
- `537e7ab` fix: P0 — http_get() 加 SSRF 防护 + tech_stack 复用共享校验
- `f317fce` docs: AGENTS.md 测试统计同步 168→189 (new: test_upgrade.py)
- `cf3f5c0` docs: 参考 Claude Fable 5 行为准则更新 CLAUDE.md
- `28d1e2b` test: 补全升级管线 21 个单元测试 + 更新文档
- `4964f46` fix: _perform_restart 先启新进程再杀旧进程 + 端口重试 + 失败标记补全

### 2026-06-15
- `03bad77` fix: 升级时同步运行目录代码 — 修复双目录部署版本号不更新
- `b7904de` fix: 升级时同步运行目录代码 — 修复双目录部署版本号不更新
- `0a529b3` fix: _perform_restart 在 macOS 上无法杀死旧进程导致重启失败
- `16d85a0` fix: _latest_version_cache 提升为模块级变量，修复 F821 lint 错误
- `6d40579` fix: 升级管线三处修复 — 版本检查缓存穿透/Windows重启/SystemExit捕获
- `c62ace8` release: v0.6.2 — Accuracy Protocol + 2 新 skills + 信息来源溯源
- `d4e04bf` feat: Accuracy Protocol — 文档分析防幻觉 + 信息来源溯源规则
- `d69b55b` feat: 新增 b2b-trade-ops / b2b-trade-compliance 技能，增强 lead-generation 质量门控
- `45e4322` fix: 修复 providers 端点 pconfig.display_name → pconfig.name
- `44c2da9` fix: 修复说明页重复段落、步骤引用不一致和错别字
- `f339c07` docs: 恢复 Windows 一键安装脚本为推荐方式
- `67f159c` docs: 面向零基础用户重写安装说明，区分 cmd/PowerShell
- `05d46d6` docs: 统一使用 PowerShell 语法，去除「钥匙」等生造词
- `6701607` fix: 代码块自动折行，不再截断长命令
- `dd2f5fd` fix: Pages 页面全宽布局，代码块不再截断
- `a8d3344` fix: 隐藏 Pages 页面顶部的 zip/tgz 下载按钮
- `ffdb064` feat: 项目介绍页 Windows 安装放首位，补充详细步骤和注意事项
- `4105d4f` feat: 添加 GitHub Pages 项目介绍页
- `098bdac` fix(test): 兼容 fastapi 0.137 的 _IncludedRouter 包装
- `8588bb3` fix: 系统升级流程支持完整重启 + 前端 cache 清理
- `e62fba0` fix: 修复 7 处隐藏 bug

### 2026-06-13
- `34a8c6f` fix: 修复 2 个 SKILL.md 的 broken markdown（未闭合 code fence）
- `f9402fe` fix: 海关数据分析报告加列映射披露规则
- `5d2140f` fix: 批量导入规则补充 TXT 文件支持
- `85956c1` feat: b2b-customer-mgmt 新增 Excel 批量导入规范
- `4418b75` refactor: license 改为全局存储，一台电脑一份
- `237e810` test: 更新 license 测试以匹配 request_code + cache 变更
- `0f70443` fix: 所有 datetime.fromisoformat 统一加 .replace(tzinfo=UTC)
- `1fa28a2` fix: 激活码验证两个 bug — .upper() 破坏 base64 + tz-naive 比较

### 2026-06-12
- `5e04d3c` fix: _machine_id 首次计算后持久化缓存，防止环境差异导致不一致
- `f0b0073` fix: 系统更新 git pull 失败时不静默返回成功
- `94d2c9c` fix: 激活弹窗显示申请码 + 修正 CLI help 格式
- `80a08dc` fix: 试用期内也显示激活申请码
- `d480b25` docs: 全面去 AI 味 + 文档补全
- `bdde6a2` perf: 减少重复 token 消耗 — system prompt 分级 + skill 注入缓存
- `6517293` feat: OSINT 搜索决策树升级 + 引用来源标注机制
- `bfc5f11` fix: 修复 17 处 lint 错误 — 未使用变量、未使用导入、导入排序、一行多语句

### 2026-06-11
- `cab5d06` chore: 版本检测轮询从1分钟改为10分钟
- `d348709` fix: 版本检测提高轮询频率 30min→1min + 加 console.log 调试
- `81b54f4` chore: bump version 0.6.0 → 0.6.1
- `fcc989a` docs: 更新 CHANGELOG/SECURITY/COMPATIBILITY/CLAUDE 至当前代码状态
- `b2bb2e2` fix: 全面代码审查修复 — 并发安全、缓存加锁、边界条件等9项
- `f22db63` fix: session级公司绑定 + list_companies脱敏（审计v2 High修复）
- `4482c4a` fix: 第六轮审计修复 — SSE线程、租户限流、SSRF、线程安全等7项

### 2026-06-10
- `ba92254` docs: README 故障排除步骤按平台分写，面向小白用户
- `ce2ff66` fix: .hermes/.trade 路径跨平台兼容 + README 故障排除
- `99123fc` fix: 第五轮审计修复 — 系统端点认证、License多租户、CDN SRI、PID三层验证等11项
- `9af6bb3` docs: CHANGELOG 0.6.0
- `e144786` chore: bump version 0.5.0 → 0.6.0
- `d0746a6` fix: 第四轮审计 — customer扩展字段、TOCTOU、大目录、文库切换
- `472adc8` fix: 系统更新/重启按钮三层防御，event undefined 也不炸
- `567d395` fix: 第三轮审计修复 — prompt注入、非原子create、upload目录、contact字段、cron污染
- `f256ecd` fix: update_trade_company 支持 extra1 参数，上传 fallback 路径可正常工作
- `ff0f410` fix: 上传文件到工作目录不再重新创建，防止生成 万花筒-2
- `0624940` fix: onclick 传 event 参数 — doTradeUpdate/doRestartTrade/updateSkills
- `056f42d` fix: 版本检查从前端调 GitHub API 改为走本地 /api/status 后端查询
- `c373344` docs: README 顶端加科学上网提示 + 免则声明；prompt 加 AI 免责块
- `064bd2e` fix: 拖拽上传 window.TOKEN → TOKEN — const 变量不挂 window 导致 session token 缺失
- `167645a` fix: 轮询 /api/status 加 cache-busting 参数防止浏览器缓存
- `7b486c9` fix: doTradeUpdate 增加轮询自动刷新，点击系统更新按钮后等待服务恢复
- `2059fac` fix: 代码审计修复 — slug错误表、event参数、interval泄露
- `8e08e85` feat: 页面顶部版本更新提示 — 每 30 分钟检查一次
- `b204902` fix: 开机自启动三平台全覆盖 + macOS Label 统一
- `0921614` feat: Windows 安装脚本增加开机自启动（Task Scheduler）

### 2026-06-09
- `4045f07` docs: Windows 安装说明增加长路径支持步骤
- `c9e6447` fix: P0/P1 安全审计修复 — 路径穿越、license加固、上传限制、PID校验

### 2026-06-08
- `2f1a0af` feat: 拖拽文件存入工作子目录，Agent 递归读取 + 图片 OCR
- `ae00b98` fix: Windows CI — upload sanitize 替换 .. 为 _ + 测试兼容反斜杠路径
- `c7c9fc9` fix: 重启按钮 — subprocess.Popen 拉起新进程 + 前端减少无意义重试
- `d1955da` feat: 聊天框拖拽/粘贴文件 — 读内容或导入文库
- `435a72c` fix: license 运行时签名验签防篡改
- `27b0ee6` docs: README 新增特别说明 — VPN、Tavily API、Hermes 辅助安装
- `7820a7e` fix: 公司工作目录创建路径错误 — 与 TRADE_HOME 解耦
- `6e4552a` chore: Hermes 0.16.0 兼容性升级

### 2026-06-04
- `e2e60ee` chore: bump version 0.4.4 → 0.5.0

### 2026-06-03
- `e9d12a2` docs: LLM 推荐不再包含 MiniMax，M3 上线后已无性价比
- `8cb95e3` feat: tradewin.exe — PyWebView 独立桌面应用
- `03eb43d` docs: CLAUDE.md 更新 — server拆分、新CLI、guidance bar、license

### 2026-06-02
- `1280266` fix: ruff — 添加 datetime import + 移除多余 f-string prefix
- `2525ff7` fix: P0审计修复 — 公司软删除 + trade-restore命令
- `053e756` fix: test_default_path 替代平台特定测试，避免 Windows PosixPath 错误
- `d0fa506` fix: license 测试用临时 Ed25519 密钥对替代真实密钥，CI 兼容
- `1cb008c` fix: CI 添加 cryptography 依赖，crypto 测试在无包时自动 skip
- `1ac61f6` docs: CLAUDE.md 测试数量 127→158，增加 test_license.py
- `db500f5` test: 添加 license.py 完整单元测试 (31 用例)
- `949ad7b` docs: Windows 安装简化 — 只需手动装 Python，Hermes 自动处理 Node+Git
- `f630e81` fix: Windows 路径适配 — Hermes 目录 + 私钥文件路径
- `6c81720` fix: 重启时校验 PID 属于 trade 进程，防止误杀
- `3774c98` fix: 许可证启动提示改进 + 私钥文件强制 600 权限

### 2026-06-01
- `8c890bc` fix: add path traversal defense in update_skills() (merged)
- `efcc780` fix: update_skills 增加 skill_name 路径穿越校验
- `07bdb5d` docs: README 项目结构补充 bootstrap.py + app.py
- `cc9b690` fix: library.create() 路径穿越防护 + order状态枚举 + chat重试减少
- `c4f584c` style: fix import order in trade/license.py
- `b9302ab` fix: library.update 增加 root_path 路径穿越防护
- `4d582a9` fix: 删除遗留的 _SECRET 引用，更新 docstring 和输入框提示
- `07b7a4c` chore: .gitignore 排除密钥备份文件
- `35ffdaf` fix: 激活码改为 Ed25519 非对称签名方案
- `eef31d2` fix: 激活码密钥改为内置常量，无需用户配置环境变量
- `c578412` fix: license 编解码改为纯 hex 格式，修复 base64 roundtrip bug
- `bc54604` fix: license 自动从 ~/.hermes/.env 加载 TRADE_LICENSE_SECRET
- `c533355` docs: license 机器码绑定实施计划
- `f300efd` feat: 到期界面显示申请码，点击可复制
- `dfdd0a7` feat: license 激活码编码内嵌机器码哈希，激活时验证本机硬件
- `b20b4cc` feat: license status 返回 request_code，到期时自动生成申请码
- `75b66f2` feat: license 添加本机硬件标识符 _machine_id()
- `11127a0` feat: 未指定文档库时自动注入公司所有文档库路径到 prompt

### 2026-05-29
- `781e827` docs: 修正 LLM 前置说明文案
- `907ea78` docs: 去掉 LLM 推荐方案中的价格列，价格不准确
- `c386235` docs: README 增加 LLM 订阅前置说明，推荐 DeepSeek V4 Flash 和 MiniMax M2.7
- `16d6e00` docs: 全量修复 14→15 skill 数量 + Hermes 版本引用不一致
- `109ffe1` chore: 升级 Hermes 版本 pin v0.14.0 → v0.15.0 (v2026.5.28)

### 2026-05-27
- `dc80f80` docs: 15项能力 + b2b-skill-generator 相关文档更新
- `5526870` feat: 新增 b2b-skill-generator — 用户可自行生成新 skill

### 2026-05-26
- `bfc5d45` feat: 重写每日工作总结模板，基于聊天记录/cron输出/客户变动等真实数据源
- `f1d0a35` refactor: guidance bar max-height 改为 20vh
- `4209c21` fix: guidance bar 改用 max-height:25vh，内容少时不占多余空间
- `3beca28` refactor: guidance bar 高度改为 25vh，任务列表可滚动
- `ce4dda5` fix: guidance bar 从绝对定位改为正常流，不再遮挡聊天内容
- `0f0b75a` fix: system prompt 注入当前公司名称和 ID，Agent 明确知道为哪家公司工作
- `f511517` fix: 添加内联 SVG favicon，消除 404 错误
- `0f7dc7b` fix: system prompt 加入公司数据隔离规则，防止 memory 跨公司泄露
- `6b54e02` feat: slug实时预览 + 高级外贸业务经理默认身份自动写入
- `74c9329` docs: Windows 安装部分补充前置软件和版本要求

### 2026-05-22
- `89db881` fix: update_trade 增加代码同步到运行目录的步骤
- `c48f274` refactor: P1整改 — 拆分server.py + customer.py company_id改必填
- `9d5e5a0` docs: 添加架构图 — 架构总览、Skill系统流程、多租户隔离
- `56a2c5f` refactor: guidance bar 去掉已完成/未完成标记，只显示当前时段任务
- `b491101` refactor: 移除 guidance bar 无功能的"去工作台"按钮
- `d6ceedf` fix: cron 任务输出在所有聊天视图均显示，不限于今日简报视图
- `1fc51da` fix: cron 输出自动过滤"管理命令参考"等冗余管理指令
- `0317a70` fix: guidance bar 只显示 jobs.json 中实际激活的定时任务
- `b7a8b0d` fix: 进度条总数改为实际激活的定时任务数，而非固定的8个
- `477081c` refactor: 定时任务列表改为每任务一行
- `ebec838` feat: guidance-bar 进度条下方添加今日定时任务列表
- `b71362f` docs: CLAUDE.md 补充前端架构和聊天记忆存储说明

### 2026-05-21
- `3a9e655` fix: a11y — 所有 form 元素添加 label for/aria-label + 修复 duplicate id
- `d1fe9f0` fix: update_trade 自动检测运行中的项目目录，而非固定 ~/.trade/foreign-trade-assistant
- `d265567` fix: 切换视图时保持 guidance-bar 不被清除
- `13ea380` fix: guidance-bar 改为绝对定位浮动提示条，不占文档流
- `317c203` fix: 减少顶部白色区域 — guidance-bar去border + chat-topbar padding减半
- `7eb80fb` fix: 工作台横幅重构 — 单行布局 + 字体加大 + 高度压缩
- `38aee2e` fix: 工作台横幅去掉上下padding
- `0d27612` feat: b2b-lead-generation 增强 — 邮件主题优化 + 多语言邮件生成
- `8dcf37a` fix: 工作台横幅高度压缩 — padding/gap/字号缩小，整体更紧凑
- `4b61022` fix: 系统更新后 ERR_EMPTY_RESPONSE — 延迟重启确保 HTTP 响应返回
- `f482fa6` fix: 唯一公司时下拉框显示公司名而非"选择公司"
- `9eb3ee7` fix: 前端 JSON.parse 防御 — 统一使用 _parseExtra1/2 包装函数
- `d6037d8` fix: 审计修复 — XSS 防护 + search_history 崩溃 + PID 清理
- `473a6cf` fix: API 层审计修复 — 数据隔离 + 线程安全 + 错误信息保留
- `b5c5e12` feat: 全局工作台横幅 + 30 秒 cron 轮询 — 系统指导业务员工作
- `0e9ff23` chore: 法律合规整改 — 品牌脱敏 + 免责声明 + 许可证声明更新
- `a33e79c` fix: 数据库升级前自动备份 + schema_migrations 表 + 数据安全表述修正
- `833ebc9` docs: README 顶部添加中英文切换链接
- `faf5e6e` docs: README 尾部旧命名修正 Foreign Trade Assistant → Smart Trade AI
- `4581ad8` docs: 添加英文版 README + 6 篇项目文档英译
- `e7c79e9` release: v0.4.4 — 仓库重命名为 smart-trade-ai + README 重构 + cron 输出展示修复
- `384c695` docs: README 截图交换位置 — 客户管理面板放首屏
- `9272573` docs: README 标题改为 Smart Trade AI
- `b5f2791` chore: 仓库重命名 foreign-trade-assistant → smart-trade-ai
- `353c2a8` docs: README 重构 — 痛点导向 + 截图 + 场景化功能分类
- `b21bf68` chore: lint 修复 — 移除未使用的 import/变量 + import 排序 + f-string 修复
- `2c41714` fix: update_skills 增加 3 次重试 + 递增退避应对 GitHub SSL 偶发超时
- `68777f2` fix: /system/update 等端点 401 — 移到不受 session token 保护的路由组
- `72abdd3` fix: 系统更新按钮全链路修复 — 自动重启 + 模板同步 + 新 skill 安装
- `218b6f1` fix: 今日简报视图展示 cron 任务实际输出为 AI 对话消息
- `f95e279` docs: 移除文档中的培训资料引用
- `958c859` docs: 补全 CLAUDE.md 架构图中缺失的模块 — orders API、order 业务层、license 模块
- `b59ab05` docs: 移除文档中的培训品牌引用
- `88e4cd1` feat: Skill 置信度评分 — 词边界3分+子串1分，多skill排序
- `0f85dc1` chore: b2b-lead-generation skill 增加内容真实性约束

### 2026-05-20
- `d4672c0` chore: 依赖加版本上限 + 文档解析库拆为 [docs] optional
- `68adcc3` fix: P0 数据隔离漏洞 — 订单跨公司校验 + OSINT 公司名误判域名 + 记忆隔离
- `32a60a7` fix: chat 端点 license 检查传入 cid 实现按公司隔离
- `0a64433` release: v0.4.3
- `3be14a6` feat: Skill 开发指南 + Agent 重试机制 + helpers 代码整理
- `e5e09f3` fix: 全面代码审计修复 — License安全、订单隔离、Chat限流、slug校验等
- `f466e20` docs: CHANGELOG v0.4.2 + README 项目结构补 orders/license + 文档链接
- `8af45b3` fix: OSINT 网络测试加 pytest.skip 防 flaky
- `6c07be9` fix: launchctl 用 shutil.which 定位完整路径
- `05e6615` feat: 4个skill增加内容真实性约束（onboarding/platform/customer-mgmt/daily-automation）
- `fcee107` feat: social-media + LinkedIn skills 增加内容真实性约束
- `f3ebe13` fix: 重启服务时补全 PATH，修复 macOS launchctl 找不到的问题
- `567c7e9` docs: 数据库表结构文档 + 关系图
- `4cb7f37` feat: 轻量订单系统 — orders 表 + CRUD + 3层上下文查询

### 2026-05-19
- `9311f51` fix: 删除多余的 } 导致 JS 解析错误
- `4550856` fix: 客户列表改为两行布局 + 移除微信字段 + 联系人和项目信息注入上下文
- `93f990e` feat: 客户表单增加联系人字段 + 上下文注入 title/note/联系方式
- `653926d` feat: 左下按钮 备份→重启 + 跨平台重启 API
- `97fbdb3` fix: agent_identity.md → agent-identity.md 文件名统一
- `0e0f573` chore: bump version to 0.4.2
- `ca4162b` chore: Roger Lau → Roger Lococo
- `4113286` chore: .gitignore 增加 LICENSE-TOOL.md
- `bf76043` feat: 新增 trade_companies.license_data 字段与启动校验
- `3153cb7` docs: README 添加微信联系方式
- `bbd2d93` chore: 联系邮箱改为 lauroge@gmail.com
- `0735b7b` chore: 移除过期分析文档 + 架构图入库 + CLI reference
- `f8b7e9d` docs: SECURITY.md 增加法律合规声明与许可证兼容性表
- `047ed5c` fix: parse函数统一 + count_files改os.scandir + recall补cid + 死代码清理
- `cf9310b` fix: LLM_API_KEY仅provider未知时兜底 + save类型一致 + recall防御 + config容错
- `dd3752b` fix: Bug11 save事务 + Bug6 后缀兜底 + Bug10/13 from e异常链
- `59a086e` fix: json.load→json.loads + CJK token覆盖 + import清理 + Depends注入
- `b8f65b6` chore: bump version to 0.4.1
- `0a20212` fix: backup_trade 无数据时返回 sys.exit(1) 替代空字符串
- `baebcfc` docs: README 测试数126→127，项目结构补cron.py，开发命令补ruff+coverage
- `4c3df40` docs: 更新 README/CHANGELOG/pyproject.toml 为 v0.4.0
- `5f7e24a` fix: cron/jobs API 适配 Hermes 实际 jobs.json 数据结构
- `bde3134` fix: git pull 失败时提供更明确的错误提示，确保用户知道数据不受影响
- `f94e2b0` fix: Windows 兼容性修复 — fcntl / ~/.hermes路径 / /tmp路径 / install.ps1
- `1223a04` fix: trade update 后自动重启 launchd/systemd 服务
- `f41ee67` fix: trade update/backup/skills-update 子命令正确路由，不再启动服务器
- `df62692` feat: 定时任务页面上方增加零基础使用说明书
- `d9c9cbd` feat: LinkedIn/lead-generation/social-media 增加输出语言规则
- `d94b651` fix: 调整 LinkedIn/social-media/lead-generation 产品与工厂内容比例
- `d5c6b6b` feat: lead-generation + social-media skills 全面转向客户价值导向
- `2410c37` feat: 安装脚本增加 macOS launchd 开机自启动，后台静默无终端窗口
- `a749ee1` fix: server.py Hermes 路径优先级 + 安装脚本修复
- `0323c6f` feat: LinkedIn 营销 skill 全面转向客户价值导向
- `b45a0ea` docs: 全项目中文注释补全 + if-branch 业务逻辑注释
- `2fa8151` fix: 修复 6 个逻辑错误 + library.py 中文注释补全
- `6547b25` feat: 启动时自动从 GitHub 拉取最新 B2B skills
- `f050fd2` fix: OSINT 背调时禁止注入历史对话，防止上一轮话题污染当前查询
- `a670eac` fix: 修复 3 个安全/稳定性漏洞

### 2026-05-18
- `645dd25` feat: 适配 Hermes v0.14 — config.model 兼容 + name_to_models 替换
- `6179f15` fix: customer.update 越权修复 + api_key 精确匹配
- `371b871` fix: SQLite busy_timeout + SSE QueueFull 防护 + 异常脱敏
- `842749c` fix: b2b-osint SKILL.md 修复 frontmatter 解析 + 重写 injection_prompt
- `aa316aa` feat: OSINT 背调质量提升 — 精简 system prompt + 分层传递
- `ef0b7c3` fix: 防止测试污染桌面 — TRADE_HOME 环境变量 + conftest 双保险
- `08e993e` fix: 修复 CI lint 失败 — cron.py 移除未使用的 import 并修正排序

### 2026-05-16
- `0e18603` feat: trade update + trade backup 命令 + API 端点 + 界面按钮
- `ea86100` feat: 界面前端增加 Skills 更新按钮 + 后端 API 端点
- `e4fb07f` feat: 新增 trade-skills-update 命令 — 从 GitHub 拉取最新 skill 定义
- `7eec83b` fix: osint skill 增加 STOP RULE — 防止对零数字足迹公司无限搜索
- `d022612` fix: osint skill 搜索策略优化 — 英文搜索 + 后缀去除 + LinkedIn 直达
- `2e1f41f` feat: b2b-osint & b2b-email-intel 链式挖掘升级
- `b88dc2c` fix: 引入 requirements.txt + install 脚本直接用 pip install -r
- `9a53274` fix: install 脚本显式安装 trade 依赖，不再依赖 hermes-agent 的间接依赖传递
- `1c2a889` feat: 安装脚本全程使用 venv，彻底解决 Homebrew PEP 668 限制
- `dca1a27` fix: install 脚本 pip install -e . 加 --no-deps 避免 hermes-agent git checkout 冲突
- `adf29cd` chore: 新增 CHANGELOG.md + pre-commit compileall hook
- `8dffa6c` refactor: F401 从全局豁免改为 per-file-ignores
- `c242eda` fix: post_install 模板路径优先从 package_skills 同级目录查找
- `0378ac4` fix: skill router 显式匹配改为精确匹配，避免 '用 b2b' 截断误匹配
- `148c5d3` fix: search_history 时间比较改用 strftime 匹配 SQLite 格式
- `53eb0fa` docs: UN 制裁名单限制说明 + fallback 原因注释
- `c21b38c` fix: 空公司名校验 + _slugify 空字符串 fallback 为 'company'
- `e9022d3` fix: email_background_check 改为子进程执行 holehe，消除 trio/asyncio 嵌套 event loop
- `1f24c08` fix: 修复 MEMORY.md 并发写 TOCTOU 竞态，改用 fcntl.flock 文件锁
- `14691fb` fix: update OFAC sanctions CSV URL (treasury.gov 已迁移到 ofac.treasury.gov)
- `2fcc24c` chore: add .worktrees/ to .gitignore

### 2026-05-15
- `9733dd6` server.py: shutil/hashlib 移到顶部统一 import，移除函数内重复 import
- `f57156a` ruff auto-fix: 172 lint issues + logging Filter 移到文件顶部 + E402 豁免
- `5983ca6` logging Filter 提前到 Hermes import 前 + CI 加 compileall 语法检查
- `e40c900` P0/P1: hermes版本对齐v0.13 + stderr hack→logging Filter + CI加Windows
- `e171066` 新增：使用说明书（面向最终用户）
- `9908693` 平台诊断 → 网站诊断：支持任何网站（B2B平台/公司官网/独立站）
- `a4ae5d8` P2 修复：toolsets ENV可配置 + 制裁阈值提高 + skill_router LRU + 可移植SQL + 参数统一
- `7c29a5f` P0/P1 修复：token估算 + WHOIS recv + ChatRequest Pydantic + DNS安全 + 时序比较 + 事务化update + CI多平台
- `cc78773` 修复：customer.update 重复的死代码行(updates 未定义→NameError) + saveCustomer 的  不存在
- `113fed9` b2b-customs-data: 自动创建海关数据目录 + 检查文件 + 用户提示
- `1b59ff7` 新增海关数据工作目录 + b2b-customs-data 自动读取该目录文件
- `8d388b6` create_agent: 显式启用 web_search 等 10 个 toolset（修复 Agent 无法搜索网络的问题）
- `9d14b26` 文案：单独生成 → 执行一次
- `20b0bf5` 修复：runSingleTemplate 未查自定义模板 + loadActiveCronJobs 用 document.getElementById 替代容器限定
- `acf5868` Windows 兼容：Gateway 启动 pgrep→tasklist/端口检测 + CREATE_NEW_PROCESS_GROUP
- `a9225dc` 任务模板：卡片式 Prompt 编辑器 + 自定义模板 + localStorage 持久化
- `25df4a1` 定时任务视图全面升级：模板库 + 已激活列表 + 编辑 + 批量生成 + 清空
- `18a964c` SKILL: 早安简报强制 web_search 获取实时汇率/商品价/新闻 + 详细格式规范
- `c3426b8` 修复：Gateway 检测改用 pgrep 而非 HTTP health check + 用 hermes CLI 启动
- `9281e0b` 新增：Cron 任务清单集成 — 今日简报自动显示 + 显示工作清单
- `cfd65df` Gateway：健康检查优先 → 已运行则复用，未运行则启动；Trade 退出后不关闭，start_new_session 独立进程组
- `6c033e6` Trade 启动时自动拉起 Hermes Gateway 子进程 + macOS launchd 开机自启配置

### 2026-05-14
- `e00b5d8` 隐藏数据目录入口（对最终用户无实际用途）
- `f5de14d` 修复：文档库下拉菜单按名称去重
- `fda9d76` 修复：JSON.parse(files_read) 容错空字符串和异常
- `9727dce` 修复：showConversationDetail 用 requestAnimationFrame 循环等待 DOM 就绪后再加载历史
- `f3cbac0` 修复：loadChatHistory null guard + showConversationDetail setTimeout 强制刷新
- `a80469b` 修复：currentChatContainer 在 loadChatHistory 之前赋值
- `e13aec1` 修复：对话记录跳转 → navToView 不再重置 currentLibraryId + 强制刷新缓存视图
- `39fb03f` 对话记录点击跳转：加载完整上下文历史而非仅单条
- `3b9f162` 前端客户表单全面扩展：title/email/phone/whatsapp/wechat/website/backup_email
- `efa680c` 客户表新增 title（职位）字段
- `7acb271` 客户管理增强：扩展字段 + 批量删除 + 排序 + 文档库自动关联
- `b756ec4` 新增：Agent 可从对话中提取客户信息并批量保存到数据库
- `170974e` 修复：多 chat 视图 DOM ID 冲突 → 改用 currentChatContainer.querySelector
- `fb7cb91` server.py: 静默屏蔽 Hermes 可选工具缺失的 stderr 警告（fal_client 等）
- `447783c` 新增：文档库页面添加「+」按钮，支持引入任意本地目录作为文档库
- `8acf3cf` Bump version to 0.3.0
- `bd30b26` P0+P1: 添加 LICENSE (MIT) + SECURITY.md + CI 徽章
- `7c194d9` CI: 跳过 hermes-agent git 依赖安装，直接 pip install 测试所需包
- `e5b5122` 前端：创建公司时提示桌面目录状态（新建 vs 重命名后缀）
- `66e8395` 修复：memory.py 的 fcntl.flock 改为跨平台文件锁（Windows 兼容）
- `ec6c4f3` 新增：ruff lint/format + pre-commit hooks + GitHub Actions CI
- `82922c7` pyproject.toml: 新增 dev 依赖 (pytest/pytest-asyncio/httpx) + pytest 配置
- `4381e06` 修复：客户详情面板对话加载 + customer_id 上下文注入
- `9cec284` 测试隔离：mock _setup_work_directory 到 tmp_path，避免污染桌面
- `32f2ebd` CLAUDE.md 更新测试说明 + README 安全部署章节 + 制裁名单持久化缓存
- `fc94784` 更新数据目录结构设计：数据库路径 + 桌面工作目录
- `539cf71` 更新 README：测试数 126 + LinkedIn 浏览器验证 + models.py
- `3d5eda8` 删除过时的 .claude.md，已被 CLAUDE.md 取代
- `4b95459` 重构：LinkedIn 验证从 Google 爬虫改为 Hermes browser_navigate
- `ae2ad7a` 安全加固：DOMPurify XSS 防护 + OFAC URL 注释
- `35e668f` 新增：/chat 端点真实 HTTP 冒烟测试（防依赖注入 500 回归）
- `116b133` 修复：POST /conversations files_read TypeError → 500
- `53180b4` SSE 升级 asyncio.Queue + CORS 动态端口 + 冒烟测试 + main()
- `0d2ca8e` 紧急修复：/chat 端点 500 + Pydantic body 补全 + 杂项修复
- `9377133` 代码质量优化：Pydantic 请求体 + 触发词去重 + 显式匹配归一化
- `785511d` 安全修复 + 稳定性修复 (code review 反馈)

### 2026-05-13
- `2598c4c` 重写 README：从头安装完整步骤 + 功能概览 + 项目结构
- `b6fdd99` 新增：PyInstaller 打包配置 + 构建脚本
- `c166e56` 新增：创建公司时自动建立桌面工作目录 + 关联文档库
- `b1eb1bf` 重构：统一 Hermes Agent 调用入口 + 启动时自动同步 skills
- `bbbd554` 修复：统一数据存储路径到 ~/.trade/ + 视图缓存机制
- `65f15d5` 从版本控制中移除无关文件
- `f85e83f` 修复：import 路径冲突导致 /api/trade/companies 404
- `3f2faf7` 重构：模块拆分 + 测试 + 全新前端 UI
- `f93f4e5` Initial commit: Foreign Trade Assistant B2B Q&A system

## 附录：已丢失的手写记录（仅存开头片段）

> 原内部变更日志被覆盖，完整内容无法恢复；以下为仅存的片段。
## [Unreleased]


### Added
- **中英双语界面（i18n）**：前端全量 i18n（约 250 个键）+ 左上角语言切换下拉；选择英文时 AI 分析与回复语言同步切换，面向外籍同事与海外用户
- **b2b-tech-drawing 技能（实验性）**：工程图纸 PDF 分析 — 文字层用 PyMuPDF 提取、扫描件渲染走 LLM Vision；带强制免责声明（结果不可直接用于报价/生产）
- **结构化 QA 知识库 + 精准检索注入**：多个 skill 的 `references/qa_pairs.md`（问题/答案/标签/场景/关键词格式）；`skill_router` 按关键词打分只注入最相关的几条，兼顾知识命中与 token 成本
- **对话评分质量闭环**：对话保存时记录匹配的 skill（`extra3`）；`GET /conversations/quality-stats` 按技能/场景聚合评分（均分、低分数、样本量）；历史对话页顶部展示质量概览，实现"用日常 👍/👎 数据持续发现该优化的 skill"
- **清单一致性协议**：系统提示词新增 R8（先结构化清点 N → 生成不手抄 → 交付前核对条数与参数）+ MINIMAL 补齐 R3-R7 准确规则（单位/置信度/冲突/缺失报告/重读）；b2b-doc-generation / b2b-cold-outreach 同步约束
- **生成前阻断校验（precheck）**：b2b-doc-generation 两阶段语义（报价可缺价/正式单证缺价阻断）+ 客户抬头硬匹配 + 结构性校验（金额=数量×单价、币种/贸易术语白名单）+ 正式单证必填字段阻断
- **发信前事实核查（5 问）**：对外发信类 skill 强制核查价格/认证/交期/参数的来源，无来源即删除，防编造数据流到客户
- **Anti-Spam 语义规避**：b2b-cold-outreach 禁 AI 腔开头与学术过渡词、禁词替换表、Subject 4-6 词硬约束、低摩擦 CTA、批量防内容指纹
- **一致性温度分流**：分析/提取类 skill 注入低温减少数据漂移，创作类保持默认温度；带 provider 白名单保护（规避不支持 temperature 的 provider 契约与 thinking mode 静默忽略）
- **证据链约束补齐**：b2b-customs-data 数据溯源（文件名+列名+行号）、b2b-trade-compliance 法规来源+查询日期
- **技能自动同步**：skills 每日 12:30 自动从 GitHub 同步（避开夜间关机时段），失败静默降级到本地哈希比较
- **新手引导按钮**：左下角可重新执行引导教程
- **b2b-cold-outreach 技能（第 20 个）**：B2B 冷 outreach 邮件撰写 — 开发信/推广信/跟进信，基于产品数据+历史报价+目标市场情报生成个性化邮件，含语言自动匹配、反营销腔自检、A/B 变体、3-5 个主题行
