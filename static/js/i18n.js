// ═════════════════════ I18N ═════════════════════
const I18N = {
    zh: {
        // nav
        'nav.daily':'今日简报','nav.lead':'客户开发','nav.platform':'网站诊断',
        'nav.social':'社媒营销','nav.linkedin':'LinkedIn','nav.customs':'海关数据',
        'nav.customers':'客户管理','nav.mailboxes':'邮箱','nav.docs':'文档库','nav.docgen':'文档生成',
        'nav.osint':'客户背调','nav.tasks':'定时任务','nav.history':'对话记录',
        'nav.workbench':'📊 工作台','nav.outreach':'🔍 获客引流',
        'nav.sales':'👤 销售转化','nav.tools':'🛠️ 工具','nav.hist':'💬 历史',
        // company
        'company.select':'— 选择公司 —','company.add':'添加公司',
        // chat placeholders
        'chat.ph.daily':'输入任何问题，或说「早安简报」开始今天的工作...',
        'chat.ph.lead':'说三个信息：卖什么？卖到哪？找什么客户？',
        'chat.ph.platform':'粘贴任何网站链接（B2B平台/公司官网/独立站），我来全面诊断优化...',
        'chat.ph.social':'描述社媒需求，如「帮我规划本周 Facebook 内容日历」...',
        'chat.ph.linkedin':'描述 LinkedIn 营销需求，如「优化我的 LinkedIn Profile」...',
        'chat.ph.customs':'上传海关数据文件后，描述分析需求...',
        'chat.ph.docs':'在下方选择文档库后提问，或直接粘贴文件内容...',
        'chat.ph.docgen':'描述要生成的文档：如「做一份欧洲客户的报价单PPT」...',
        'chat.ph.osint':'输入邮箱/域名/公司名，我来做全面的背景调查...',
        'chat.clr':'🗑️ 清屏','chat.library':'— 选择文档库 —','chat.lib.add':'添加文档库',
        // footer buttons —— 只写文字：图标固定在 HTML 里（不随语言变），
        // 这些文案由 applyI18n 填进按钮的 data-tip，悬停时显示。
        'footer.update':'更新系统','footer.restart':'重启',
        'footer.skills':'技能帮助','footer.skills_update':'更新技能',
        'footer.upgrade':'升级说明','footer.onboarding':'新手引导',
        'footer.copilot':'聊天副驾',
        // modals - company
        'modal.co.title':'🏢 公司设置','modal.co.tab_list':'公司列表','modal.co.tab_identity':'Agent 身份',
        'modal.co.add_title':'添加新公司','modal.co.name':'公司名称 *','modal.co.name_ph':'例如：我的外贸公司',
        'modal.co.slug_ph':'自动生成','modal.co.slug_tt':'由系统根据公司名称自动生成',
        'modal.co.contact':'联系人','modal.co.contact_ph':'姓名',
        'modal.co.email':'邮箱','modal.co.website':'网站',
        'modal.co.identity_desc':'配置当前选中公司的 AI Agent 身份。系统会在对话时注入此内容。',
        'modal.co.identity_label':'Agent 身份 (Markdown)',
        'modal.co.identity_ph':'粘贴 agent-identity.md 内容...',
        'modal.co.create':'创建公司','modal.co.save':'保存',
        // modals - customer
        'modal.cust.title':'添加客户','modal.cust.title_edit':'编辑客户',
        'modal.cust.name':'公司名称 *','modal.cust.name_ph':'客户公司名称',
        'modal.cust.contact':'联系人','modal.cust.contact_ph':'联系人姓名',
        'modal.cust.title_f':'职位','modal.cust.country':'国家','modal.cust.country_ph':'如 Italy',
        'modal.cust.email':'邮箱','modal.cust.phone':'电话',
        'modal.cust.whatsapp':'WhatsApp','modal.cust.linkedin':'LinkedIn URL',
        'modal.cust.website':'公司网站','modal.cust.tier':'客户等级',
        'modal.cust.tier_none':'未分级',
        'modal.cust.buyer':'买家类型','modal.cust.buyer_none':'未设置',
        'modal.cust.category':'主营品类','modal.cust.category_ph':'客户主营产品或行业',
        'modal.cust.backup_email':'备用邮箱','modal.cust.score':'匹配度',
        'modal.cust.score_none':'未评分','modal.cust.note':'备注 / 跟进项目',
        'modal.cust.note_ph':'该联系人负责的项目、需求、注意事项等',
        'modal.cust.follow':'AI 跟进建议','modal.cust.follow_ph':'AI 基于客户画像自动生成的跟进策略...',
        // modals - library
        'modal.lib.title':'📁 添加文档库',
        'modal.lib.desc':'将本地文件夹关联为文档库，Agent 可通过 read_file 读取其中的文件。',
        'modal.lib.name':'库名称 *','modal.lib.name_ph':'例如：产品报价库',
        'modal.lib.path':'文件夹路径 *','modal.lib.path_ph':'/Users/xxx/Documents/客户资料',
        'modal.lib.path_hint':'📌 Mac: 文件夹上右键 → Option键 → 复制路径名',
        'modal.lib.notes':'描述','modal.lib.notes_ph':'可选',
        'modal.lib.create':'添加',
        // modals - upgrade help
        'modal.upgrade.title':'⬆️ 如何升级 Trade',
        'modal.upgrade.p1':'通过 <strong>Hermes</strong>（AI 助手）来升级 Trade 是最简单的方式。Hermes 会自动执行所有更新命令，遇到报错会自行排查重试。',
        'modal.upgrade.steps':'操作步骤',
        'modal.upgrade.li1':'打开终端：<br><b>macOS</b> — 在 Launchpad 搜索「终端」<br><b>Windows</b> — 按 <code>Win+R</code>，输入 <code>powershell</code>，回车',
        'modal.upgrade.li2':'输入 <code>hermes</code> 并回车，启动 Hermes',
        'modal.upgrade.li3':'在 Hermes 对话框中输入以下内容并回车：',
        'modal.upgrade.cmd':'帮我更新trade，并重启trade，地址是https://github.com/chefroger/smart-trade-ai',
        'modal.upgrade.p2':'等待执行完毕，看到「重启完成」提示后，刷新浏览器页面（<kbd>Ctrl+Shift+R</kbd>）即可。',
        'modal.upgrade.p3':'如果 <code>hermes</code> 命令找不到，说明 Hermes Agent 未安装。请先参考安装说明安装 Hermes。',
        // modals - skills help
        'modal.skills.title':'📖 全部 45 个技能速查',
        'modal.skills.desc':'在聊天框输入关键词，Trade 自动匹配合适的技能。点击复制图标可复制快速启动提示词。',
        // common
        'btn.close':'关闭','btn.cancel':'取消','btn.save':'保存','btn.ok':'确定',
        // license
        'license.expired':'已到期',
        'license.expired_soft':'历史与资料仍在，起草已暂停；激活后立即恢复',
        'license.trial_summary':'试用以来：起草 {drafts} 次 · 处理询盘 {inquiries} 次 · 调用产品库 {lookups} 次',
        'license.expiring':'即将到期','license.valid_until':'有效期至','license.trial':'试用',
        'license.active':'已激活','license.req_code':'申请码',
        'license.activate_btn':'🔑 输入激活码','license.days_left':'剩余 {n} 天',
        'license.paid_only':'该功能仅对付费用户开放',
        // toast
        'toast.copied':'已复制','toast.saved':'已保存','toast.deleted':'已删除',
        'toast.updated':'已更新','toast.error':'操作失败','toast.network':'网络错误',
        'toast.no_company':'请先选择公司','toast.csv_ok':'成功导入 {n} 个客户',
        // customer view
        'customer.title':'客户管理','customer.add':'添加客户',
        'customer.import':'📥 CSV导入','customer.search':'搜索公司、联系人、邮箱、标签',
        'customer.detail.save':'💾 保存修改',
        'customer.detail.libs':'📁 关联文档库','customer.detail.orders':'📦 订单',
        'customer.detail.add_order':'+ 新增订单','customer.detail.convs':'💬 最近对话',
        'customer.detail.no_convs':'暂无关联对话。点击下方按钮开始和此客户对话。',
        'customer.detail.chat_btn':'💬 和此客户开始对话',
        'customer.detail.basic':'基本信息',
        'customer.detail.link_lib':'— 选择文档库 —',
        'customer.detail.link_btn':'关联',
        // tasks
        'task.title':'定时任务','task.no_active':'暂无已激活的定时任务。请从上方模板库钩选后点击「批量生成」。',
        'task.run_now':'▶ 立即执行','task.template':'📋 任务模板库',
        'task.batch':'批量生成','task.running':'● 运行中','task.paused':'○ 已暂停',
        // history
        'history.title':'对话记录',
        'history.no_records':'暂无对话记录',
        // quality stats（近 30 天评分概览）
        'quality.rated':'近30天评分','quality.avg':'均分','quality.worst':'待改进',
        // orders
        'order.title':'新增订单','order.edit_title':'编辑订单',
        'order.no':'订单号','order.product':'产品名称 *','order.qty':'数量',
        'order.unit':'单位','order.price':'单价','order.currency':'币种',
        'order.price_pending':'单价待谈',
        'order.price_pending_legacy':'单价待谈（旧数据，单价未填）',
        'order.items':'商品明细','order.add_line':'+ 添加商品','order.remove_line':'删除这一行',
        'order.line_total':'行总额','order.items_count':'等{n}项',
        'order.items_required':'至少添加一行商品','order.item_name_required':'请填写每一行的品名',
        'order.total_pending':'合计待谈','order.price_per_line':'按行报价',
        'order.amount':'总金额','order.status':'状态','order.delivery':'交货日期',
        'order.payment':'付款方式','order.notes':'备注',
        'order.incoterm':'贸易术语','order.port_loading':'装运港','order.port_ph':'如 宁波',
        'order.container':'柜型','order.lead_time':'交期文案','order.lead_time_ph':'如 定金后 25 天',
        'order.shipped_at':'出货日','order.shipped_ph':'YYYY-MM 或 YYYY-MM-DD',
        // onboarding
        'onb.welcome':'欢迎使用 Trade AI Assistant！',
        'onb.welcome_desc':'我是你的 AI 外贸助手，让我帮你快速上手。',
        'onb.start_btn':'🚀 开始',
        'onb.step1_done':'✓ 了解 Trade','onb.step2_active':'● 开发客户',
        'onb.step2_title':'试试对目标客户做背调',
        'onb.step2_desc':'输入客户公司名或官网，AI 将自动搜索公开信息并生成开发信',
        'onb.analyze_btn':'开始分析','onb.stop_btn':'🛑 停止',
        'onb.skip':'跳过引导，直接开始',
        // misc
        'misc.thinking':'正在思考...','misc.loading':'加载中...',
        'misc.no_data':'暂无数据','misc.empty':'暂无内容',
        'misc.loading_orders':'加载订单...',
        'misc.file_preview':'文件内容通过 Agent 对话中的 read_file 工具访问。在侧边栏中选择对应功能入口后，Agent 会自动读取相关文件。',
        'misc.drop_title':'📁 拖放文件到此处',
        'misc.drop_subdir':'上传到子目录：','misc.drop_total':'共 {n} 个文件',
        'misc.drop_confirm':'确认上传','misc.drop_too_many':'... 还有 {n} 个文件',
        // customer detail panel fields
        'cust.field.name':'客户名称','cust.field.title':'联系人职位','cust.field.tier':'等级',
        'cust.field.website':'公司网站',
        'cust.field.tier_none':'未分级','cust.field.buyer':'买家类型','cust.field.buyer_none':'未设置',
        'cust.field.country':'国家','cust.field.city':'城市','cust.field.category':'主营品类','cust.field.score':'匹配度',
        'cust.field.score_none':'未评分','cust.field.email':'邮箱','cust.field.phone':'电话',
        'cust.field.backup_email':'备用邮箱','cust.field.contact':'联系方式','cust.field.note':'备注',
        'cust.field.function':'职能','cust.field.responsibility':'职责',
        'cust.field.follow':'AI 跟进建议','cust.field.no_orders':'暂无订单，点击「新增订单」添加。',
        'cust.followup_note':'跟进备注','cust.followup_note_hint':'客户级备注，显示在主联系人卡片',
        'cust.field.order_fail':'订单加载失败',
        'cust.summary.total':'{n} 位客户','cust.summary.follow_up':'{n} 待跟进',
        'cust.summary.overdue':'{n} 逾期','cust.summary.orders':'{amt} 累计订单',
        'brief.title':'今日简报','brief.new_inquiries':'新询盘','brief.overdue':'逾期跟进',
        'brief.pending_ship':'待出货','brief.summary_empty':'今日简报待生成',
        'brief.todo':'待办','brief.cron':'定时任务输出','brief.cron_empty':'今日暂无定时任务输出',
        'brief.cron_no_jobs':'暂无已激活的定时任务','brief.cron_setup':'去设置定时任务 →',
        'brief.cron_waiting':'待首次执行','brief.cron_silent':'无新内容',
        'brief.cron_today_tag':'今日','brief.cron_view_full':'点击查看完整定时任务输出',
        'todo.add':'添加待办','todo.placeholder':'写点要做的，回车保存',
        'todo.due':'截止日期','todo.customer':'关联客户','todo.no_customer':'— 无客户 —',
        'todo.save':'保存','todo.overdue':'逾期','todo.today':'今天','todo.upcoming':'将来',
        'todo.empty':'暂无待办，点右上角 + 添加','todo.confirm_delete':'删除这条待办？',
        'todo.empty_label':'这条待办没有内容','todo.added':'已加入待办',
        'chat.cmd.sub':'请下达指令 · 客户开发、询盘回复、报价、单证，直接说',
        'brief.dash':'—',
        'chat.blocks.draft_warn':'草稿 · 不会自动发送','chat.blocks.copy_draft':'复制草稿',
        'chat.blocks.next':'NEXT · 下一步','chat.blocks.copied':'已复制',
        'chat.blocks.edit_draft':'继续修改','chat.blocks.gen_pi':'生成 PI',
        'chat.blocks.copy_note':'复制后由你自己在邮箱里发出',
        'chat.blocks.edit_prompt':'继续修改这封邮件草稿','chat.blocks.gen_pi_prompt':'按这份报价生成 PI',
        'brief.done':'完成 · {n}',
        'profile.open':'客户画像','profile.title':'客户画像','profile.back_wall':'← 返回卡片墙',
        'profile.circle':'人物圈','profile.prefs':'喜好禁忌与往来',
        'profile.sec.family':'家庭 // FAMILY','profile.sec.suppliers':'其他供应商或竞品 // SUPPLIERS',
        'profile.sec.prefs':'喜好 // PREFERENCES','profile.sec.taboos':'禁忌 // TABOOS',
        'profile.sec.dates':'重要日期 // DATES','profile.sec.gifts':'礼物往来 // GIFTS',
        'profile.add':'＋添加','profile.add_gift':'＋礼物','profile.extract_chat':'从聊天提取',
        'profile.extract_email':'从邮件提取','profile.confirm':'确认','profile.void':'作废',
        'profile.delete':'删除','profile.delete_confirm':'确定删除这条手工记录？',
        'profile.ai_use':'给 AI 用','profile.ai_on':'开','profile.ai_off':'关',
        'profile.show_quote':'原句','profile.ask':'索要',
        'profile.pending':'待确认 · {n}',
        'profile.solicit_note':'仅本机 · 不导出 · 不给 AI',
        'profile.restart':'重启后可用','profile.empty_circle':'暂无人物圈记录',
        'profile.empty_prefs':'暂无喜好/禁忌/往来','profile.confirmed':'已确认',
        'profile.saved':'已保存','profile.pick_category':'选择分类',
        'profile.bad_category':'分类无效','profile.subject_ph':'对象（如姓名）',
        'profile.content_ph':'事实内容','profile.pick_direction':'往来方向',
        'profile.item_ph':'物品','profile.extract_done':'提取完成：事实 {f} · 礼物 {g} · 丢弃 {d}',
        'profile.src_chat':'对话','profile.src_email':'邮件','profile.src_visit':'验厂','profile.src_manual':'手工',
        'profile.edit':'编辑','profile.add_fact':'添加画像条目','profile.edit_fact':'编辑画像条目',
        'profile.gift_add_title':'添加礼物往来','profile.gift_edit_title':'编辑礼物往来',
        'profile.category':'分类','profile.subject':'对象','profile.content':'内容',
        'profile.content_required':'内容不能为空','profile.item':'物品','profile.item_required':'物品不能为空',
        'profile.direction':'方向','profile.approx_value':'金额','profile.currency':'币种',
        'profile.gift_date':'日期','profile.occasion':'场合','profile.note':'备注',
        'profile.invalid_amount':'金额无效',
        'profile.attach':'挂到','profile.attach_none':'不挂人',
        'profile.attach_primary':'主联系人：{name}','profile.attach_primary_default':'主联系人',
        'profile.attach_contact_fallback':'附加联系人',
        'cust.summary.plus_currencies':'+{n} 种',
        // order modal
        'order.cust_label':'客户 *','order.cust_select':'-- 选择客户 --',
        'order.status_quoting':'报价中','order.status_ordered':'已下单','order.status_shipped':'已出货','order.status_done':'已完成','order.status_cancelled':'已取消',
        'order.btn_delete':'🗑 删除','order.confirm_delete':'确定删除此订单？',
        'order.created':'订单已创建','order.updated':'订单已更新','order.deleted':'订单已删除',
        // history
        'hist.delete_title':'删除此对话','hist.confirm_delete':'确定删除这条对话记录？此操作不可恢复。',
        'hist.deleted':'对话已删除','hist.delete_fail':'删除失败',
        // toast
        'toast.input_required':'请填写库名称和文件夹路径','toast.lib_added':'文档库「{name}」已添加',
        'toast.lib_add_fail':'添加失败','toast.saved':'已保存','toast.deleted':'已删除',
        'toast.cust_product_required':'请选择客户并填写品名','toast.select_library':'请选择文档库',
        'toast.complete_onboarding':'请先完成新手引导','toast.enter_company':'请输入公司名或网址',
        'toast.wizard_product':'请先告诉我你卖什么产品','toast.wizard_market':'请告诉我目标市场',
        'toast.activate_fail':'激活失败','toast.network_retry':'网络错误，请重试',
        'toast.request_timeout':'请求超时',
        'toast.imported':'已导入 {n} 个文件到「{dir}」','toast.import_fail':'导入失败',
        // wizard
        'wiz.step1_title':'先告诉我：你卖什么产品？','wiz.step1_desc':'随便说就行，"LED灯""五金""纺织品"都可以',
        'wiz.step1_ph':'例如：LED工矿灯、不锈钢螺丝、全棉T恤...',
        'wiz.step1_btn':'下一步：卖到哪里去？ →','wiz.step1_indicator':'● 卖什么',
        'wiz.step2_title':'想卖到哪个国家或地区？','wiz.step2_desc':'比如"德国""美国""中东""东南亚"，可以写多个',
        'wiz.step2_ph':'例如：德国、美国、中东...',
        'wiz.step2_btn':'下一步：找什么类型？ →','wiz.step2_indicator':'● 卖到哪',
        'wiz.step3_title':'想找什么类型的客户？','wiz.step3_indicator':'● 找谁',
        'wiz.type_distributor':'批发商 / 分销商','wiz.type_distributor_desc':'大量采购再分销到本地市场',
        'wiz.type_oem':'品牌商 / OEM 工厂','wiz.type_oem_desc':'贴牌生产，长期大单',
        'wiz.type_retailer':'零售商 / 连锁店','wiz.type_retailer_desc':'小批量多频次采购',
        'wiz.type_any':'都行，帮我一起找','wiz.type_any_desc':'让 AI 自动判断最合适的类型',
        'wiz.launch_btn':'🚀 开始找客户！','wiz.back':'← 返回修改','wiz.skip':'跳过向导',
        'wiz.step_done':'✓ 卖什么','wiz.step2_done':'✓ 卖到哪',
        'wiz.searching':'正在帮你找客户...','wiz.searching_desc':'自动多通道搜索中，请稍候',
        'wiz.type_names.distributor':'批发商/分销商','wiz.type_names.oem':'品牌商/OEM工厂',
        'wiz.type_names.retailer':'零售商/连锁店','wiz.type_names.any':'所有类型',
        // onboarding
        'onb.welcome_title':'欢迎使用 Trade AI','onb.welcome_desc2':'Trade 可以帮你<strong>自动搜索客户背景信息（OSINT）</strong>，并基于你的产品定位<strong>撰写专业 B2B 开发信</strong>。',
        'onb.feat1':'海关数据 · 社媒分析 · 官网诊断','onb.feat2':'AI 写开发信 · 跟进序列 · 报价单',
        'onb.feat3':'7x24 自动获客 · 定时任务调度',
        'onb.start_btn':'🚀 开发第一个客户','onb.skip_btn':'跳过引导，直接开始',
        // upgrade/restart button states
        'sys.updating':'更新中...','sys.restarting':'重启中...',
        'sys.updating_now':'正在拉取最新代码并安装依赖，请稍候（约 1 分钟）…',
        'sys.update_done_restart':'✅ 更新完成。请点击"🔄 重启"以应用新版本。',
        'sys.update_done':'✅ 更新完成。请点击"🔄 重启"以应用新版本。',
        'sys.update_fail':'❌ 更新失败: ','sys.update_unknown':'⚠️ 更新结果未知，请检查网络后重试',
        'sys.update_network':'⚠️ 更新请求失败，请检查网络连接后重试',
        'sys.update_confirm':'将从 GitHub 拉取 main 分支代码、安装依赖；更新完成后由你手动点击「重启」生效。\n升级前会自动备份数据库。\n\n确定现在更新吗？',
        'sys.update_confirm_current':'当前版本 {current}，目标提交 {target}。\n将拉取并安装这个提交；更新完成后由你手动点击「重启」生效。\n升级前会自动备份数据库。\n\n确定现在更新吗？',
        'usage.today':'今日已用 {used} / {limit} tokens',
        'usage.unlimited':'今日已用 {used} tokens',
        'usage.over':'今日已用 {used} / {limit} tokens · 已超额度（不拦截）',
        'sys.restart_toast':'🔄 正在重启 Trade 服务...',
        'sys.restart_ok':'✅ 重启命令已发送，页面将在几秒后刷新',
        'sys.restart_fail':'❌ 重启失败: ',
        'sys.restart_busy_update':'更新正在进行中，请等更新完成后再点重启。',
        'sys.restart_wait':'🔄 服务正在重启，页面即将刷新...',
        'sys.restart_timeout':'⚠️ 服务重启超时，请手动刷新页面',
        'sys.skills_updating':'更新中...',
        'sys.skills_ok':'✅ Skills 更新完成！已同步最新版本',
        'sys.skills_fail':'❌ 更新失败: ',
        'sys.skills_error':'❌ 更新出错: ',
        // skills help
        'skills.copied':'提示词已复制: ',
        // import button
        'import.importing':'导入中...','import.confirm':'确认导入',
        // guidance bar
        'guide.rest':'当前时段暂无安排',
        'guide.progress':'今日进度',
        // mailbox panel
        'mailbox.title':'邮箱',
        'mailbox.guide_en_tip':'Guide in Chinese only for now — ask us if you need English help.',
        'mailbox.guide_title':'连接指南',
        'mailbox.form_title':'绑定新邮箱',
        'mailbox.list_title':'已绑定邮箱',
        'mailbox.preset':'邮箱类型',
        'mailbox.preset_custom':'其他 IMAP',
        'mailbox.email':'邮箱地址',
        'mailbox.secret':'授权码 / 应用密码',
        'mailbox.secret_ph':'填 16 位 IMAP 授权码，不是网页登录密码',
        'mailbox.display_name':'显示名称（可选）',
        'mailbox.display_name_ph':'如：询价邮箱',
        'mailbox.host':'IMAP 服务器',
        'mailbox.port':'端口',
        'mailbox.username':'登录用户名',
        'mailbox.username_ph':'默认与邮箱地址相同',
        'mailbox.test':'测试连接',
        'mailbox.bind':'绑定',
        'mailbox.testing':'测试中…',
        'mailbox.test_ok':'连接成功',
        'mailbox.test_fail':'连接失败',
        'mailbox.test_first':'请先测试连接并通过后再绑定',
        'mailbox.need_email_secret':'请填写邮箱地址和授权码',
        'mailbox.bind_ok':'邮箱已绑定',
        'mailbox.faq':'常见问题',
        'mailbox.empty_title':'尚未绑定邮箱',
        'mailbox.empty_hint':'按上方指南获取授权码，测试通过后绑定',
        'mailbox.col_email':'邮箱',
        'mailbox.col_status':'同步状态',
        'mailbox.col_actions':'操作',
        'mailbox.synced_at':'上次同步',
        'mailbox.never_synced':'尚未拉取',
        'mailbox.email_count':'本地已缓存 {n} 封邮件',
        'mailbox.pull':'拉取',
        'mailbox.pulling':'拉取中…',
        'mailbox.pull_done':'已拉取 {n} 封新邮件',
        'mailbox.update_secret':'更新授权码',
        'mailbox.secret_prompt':'输入新的 IMAP 授权码（测不通会保留旧码）',
        'mailbox.secret_updated':'授权码已更新',
        'mailbox.unbind':'解绑',
        'mailbox.unbind_confirm':'解绑将删除该邮箱的本地邮件缓存，确定继续？',
        'mailbox.unbind_ok':'已解绑',
        // contacts（附加联系人 + 墙内标签）
        'contacts.add':'添加联系人',
        'contacts.empty':'暂无联系人',
        'contacts.primary_badge':'主',
        'contacts.extra_badge':'附加',
        'contacts.edit':'编辑',
        'contacts.delete':'删除',
        'contacts.delete_confirm':'确定删除联系人「{name}」？',
        'contacts.deleted':'已删除联系人',
        'contacts.add_title':'添加联系人',
        'contacts.edit_title':'编辑联系人',
        'contacts.name':'姓名 *',
        'contacts.function':'职能',
        'contacts.title_f':'职位',
        'contacts.responsibility':'职责（如：主要对接人）',
        'contacts.email':'邮箱',
        'contacts.phone':'电话',
        'contacts.whatsapp':'WhatsApp',
        'contacts.wechat':'微信',
        'contacts.note':'备注',
        'contacts.name_required':'请填写姓名',
        'contacts.saved':'联系人已保存',
        'contacts.tags_title':'标签',
        'contacts.tags_ph':'输入标签，回车或逗号添加',
        'contacts.tags_add':'添加',
        'contacts.tags_empty':'暂无标签',
        'contacts.tags_too_long':'单个标签最多 20 个字符',
        'contacts.tags_too_many':'标签最多 20 个',
        // inquiry（墙内询盘区 N4）
        'inquiry.section':'询盘',
        'inquiry.empty':'暂无询盘，新建一个开始跟进',
        'inquiry.title_ph':'询盘标题',
        'inquiry.create':'新建询盘',
        'inquiry.delete':'删除',
        'inquiry.stage_auto':'自动（按询盘推导）',
        'inquiry.manual_badge':'手',
        'inquiry.manual_title':'手动锁定，点击卡片墙可改回自动',
        'inquiry.created':'询盘已创建',
        'inquiry.updated':'询盘已更新',
        'inquiry.deleted':'询盘已删除',
    },
    en: {
        'nav.daily':'Daily Briefing','nav.lead':'Lead Gen','nav.platform':'Site Audit',
        'nav.social':'Social','nav.linkedin':'LinkedIn','nav.customs':'Customs',
        'nav.customers':'Customers','nav.mailboxes':'Mailboxes','nav.docs':'Documents','nav.docgen':'Doc Gen',
        'nav.osint':'Due Diligence','nav.tasks':'Tasks','nav.history':'History',
        'nav.workbench':'📊 Workspace','nav.outreach':'🔍 Outreach',
        'nav.sales':'👤 Sales','nav.tools':'🛠️ Tools','nav.hist':'💬 History',
        'company.select':'— Select Company —','company.add':'Add',
        'chat.ph.daily':'Ask anything, or say "Morning briefing" to start...',
        'chat.ph.lead':'What do you sell? Where? Who are you looking for?',
        'chat.ph.platform':'Paste any website URL for a full audit...',
        'chat.ph.social':'Describe your social media needs...',
        'chat.ph.linkedin':'Describe your LinkedIn marketing needs...',
        'chat.ph.customs':'Upload customs data, then describe your analysis needs...',
        'chat.ph.docs':'Select a library below, or paste file content...',
        'chat.ph.docgen':'Describe the document: e.g. "Create a quotation PPT for EU client"...',
        'chat.ph.osint':'Enter email/domain/company name for background check...',
        'chat.clr':'🗑️ Clear','chat.library':'— Select Library —','chat.lib.add':'Add Library',
        'footer.update':'Update','footer.restart':'Restart',
        'footer.skills':'Skills Help','footer.skills_update':'Update Skills',
        'footer.upgrade':'Upgrade Guide','footer.onboarding':'Tutorial',
        'footer.copilot':'Chat Copilot',
        'modal.co.title':'🏢 Company Settings','modal.co.tab_list':'Companies','modal.co.tab_identity':'Agent Identity',
        'modal.co.add_title':'Add Company','modal.co.name':'Company Name *','modal.co.name_ph':'e.g. My Trading Co.',
        'modal.co.slug_ph':'Auto-generated','modal.co.slug_tt':'Auto-generated from company name',
        'modal.co.contact':'Contact','modal.co.contact_ph':'Name',
        'modal.co.email':'Email','modal.co.website':'Website',
        'modal.co.identity_desc':'Configure the AI Agent identity for this company. Injected into every conversation.',
        'modal.co.identity_label':'Agent Identity (Markdown)',
        'modal.co.identity_ph':'Paste agent-identity.md content...',
        'modal.co.create':'Create Company','modal.co.save':'Save',
        'modal.cust.title':'Add Customer','modal.cust.title_edit':'Edit Customer',
        'modal.cust.name':'Company Name *','modal.cust.name_ph':'Customer company name',
        'modal.cust.contact':'Contact','modal.cust.contact_ph':'Contact name',
        'modal.cust.title_f':'Title','modal.cust.country':'Country','modal.cust.country_ph':'e.g. Italy',
        'modal.cust.email':'Email','modal.cust.phone':'Phone',
        'modal.cust.whatsapp':'WhatsApp','modal.cust.linkedin':'LinkedIn URL',
        'modal.cust.website':'Website','modal.cust.tier':'Tier',
        'modal.cust.tier_none':'None',
        'modal.cust.buyer':'Buyer Type','modal.cust.buyer_none':'Not set',
        'modal.cust.category':'Main Category','modal.cust.category_ph':'Customer main product category',
        'modal.cust.backup_email':'Backup Email','modal.cust.score':'Match Score',
        'modal.cust.score_none':'Not rated',
        'modal.cust.note':'Notes','modal.cust.note_ph':'Projects, requirements, notes...',
        'modal.cust.follow':'AI Follow-up','modal.cust.follow_ph':'AI-generated follow-up strategy...',
        'modal.lib.title':'📁 Add Library',
        'modal.lib.desc':'Link a local folder as a document library. Agent can read files via read_file.',
        'modal.lib.name':'Library Name *','modal.lib.name_ph':'e.g. Product Quotes',
        'modal.lib.path':'Folder Path *','modal.lib.path_ph':'/Users/xxx/Documents/clients',
        'modal.lib.path_hint':'📌 Mac: Right-click folder → Hold Option → Copy path',
        'modal.lib.notes':'Description','modal.lib.notes_ph':'Optional',
        'modal.lib.create':'Add',
        'modal.upgrade.title':'⬆️ How to Upgrade Trade',
        'modal.upgrade.p1':'The easiest way is to let <strong>Hermes</strong> (AI assistant) handle it. It runs all commands and retries on errors.',
        'modal.upgrade.steps':'Steps',
        'modal.upgrade.li1':'Open terminal:<br><b>macOS</b> — Launchpad → Terminal<br><b>Windows</b> — <code>Win+R</code> → <code>powershell</code>',
        'modal.upgrade.li2':'Type <code>hermes</code> and press Enter to launch Hermes',
        'modal.upgrade.li3':'In the Hermes dialog, paste the following:',
        'modal.upgrade.cmd':'Help me update Trade and restart it. Repo: https://github.com/chefroger/smart-trade-ai',
        'modal.upgrade.p2':'Wait for completion, then refresh the page (<kbd>Ctrl+Shift+R</kbd>).',
        'modal.upgrade.p3':'If <code>hermes</code> is not found, Hermes Agent is not installed. See install guide first.',
        'modal.skills.title':'📖 All 45 Skills Reference',
        'modal.skills.desc':'Type keywords in chat — Trade auto-matches the right skill. Click copy icon for quick prompts.',
        'btn.close':'Close','btn.cancel':'Cancel','btn.save':'Save','btn.ok':'OK',
        'license.expired':'Expired',
        'license.expired_soft':'Your history and data are still here; drafting is paused until activation',
        'license.trial_summary':'Since trial start: {drafts} drafts · {inquiries} inquiries handled · {lookups} product-library lookups',
        'license.expiring':'Expiring Soon','license.valid_until':'Valid until','license.trial':'Trial',
        'license.active':'Active','license.req_code':'Request Code',
        'license.activate_btn':'🔑 Enter Activation Code','license.days_left':'{n} days left',
        'license.paid_only':'Available to paid users only.',
        'toast.copied':'Copied','toast.saved':'Saved','toast.deleted':'Deleted',
        'toast.updated':'Updated','toast.error':'Error','toast.network':'Network Error',
        'toast.no_company':'Please select a company first','toast.csv_ok':'Imported {n} customers',
        'customer.title':'Customers','customer.add':'Add Customer',
        'customer.import':'📥 Import CSV','customer.search':'Search company, contact, email, tag',
        'customer.detail.save':'💾 Save',
        'customer.detail.libs':'📁 Linked Libraries','customer.detail.orders':'📦 Orders',
        'customer.detail.add_order':'+ New Order','customer.detail.convs':'💬 Recent Conversations',
        'customer.detail.no_convs':'No conversations. Click below to start chatting with this customer.',
        'customer.detail.chat_btn':'💬 Chat with this Customer',
        'customer.detail.basic':'Basic Info',
        'customer.detail.link_lib':'— Select Library —',
        'customer.detail.link_btn':'Link',
        'task.title':'Scheduled Tasks','task.no_active':'No active tasks. Check templates above and click "Batch Generate".',
        'task.run_now':'▶ Run Now','task.template':'📋 Task Templates',
        'task.batch':'Batch Generate','task.running':'● Running','task.paused':'○ Paused',
        'history.title':'Chat History',
        'history.no_records':'No chat history',
        // quality stats（30-day rating overview）
        'quality.rated':'Ratings (30d)','quality.avg':'Avg','quality.worst':'Needs work',
        'order.title':'New Order','order.edit_title':'Edit Order',
        'order.no':'Order No.','order.product':'Product *','order.qty':'Qty',
        'order.unit':'Unit','order.price':'Unit Price','order.currency':'Currency',
        'order.price_pending':'Price TBD',
        'order.price_pending_legacy':'Price TBD (legacy data, price not filled)',
        'order.items':'Line items','order.add_line':'+ Add item','order.remove_line':'Remove this line',
        'order.line_total':'Line total','order.items_count':'({n} items)',
        'order.items_required':'Add at least one line','order.item_name_required':'Enter a product name on every line',
        'order.total_pending':'Total TBD','order.price_per_line':'Priced per line',
        'order.amount':'Total','order.status':'Status','order.delivery':'Delivery',
        'order.payment':'Payment Terms','order.notes':'Notes',
        'order.incoterm':'Incoterm','order.port_loading':'Port of loading','order.port_ph':'e.g. Ningbo',
        'order.container':'Container','order.lead_time':'Lead time','order.lead_time_ph':'e.g. 25 days after deposit',
        'order.shipped_at':'Shipped at','order.shipped_ph':'YYYY-MM or YYYY-MM-DD',
        'onb.welcome':'Welcome to Trade AI Assistant!',
        'onb.welcome_desc':"I'm your AI trade assistant. Let me help you get started.",
        'onb.start_btn':'🚀 Get Started',
        'onb.step1_done':'✓ About Trade','onb.step2_active':'● Find Customers',
        'onb.step2_title':'Try a background check on a prospect',
        'onb.step2_desc':'Enter a company name or website — AI will search public info and generate an outreach email',
        'onb.analyze_btn':'Start Analysis','onb.stop_btn':'🛑 Stop',
        'onb.skip':'Skip tutorial',
        'misc.thinking':'Thinking...','misc.loading':'Loading...',
        'misc.no_data':'No data','misc.empty':'Nothing here yet',
        'misc.loading_orders':'Loading orders...',
        'misc.file_preview':'File content is accessed via the read_file tool during Agent conversations. Select a feature in the sidebar and the Agent will automatically read relevant files.',
        'misc.drop_title':'📁 Drop files here',
        'misc.drop_subdir':'Upload to:','misc.drop_total':'{n} files total',
        'misc.drop_confirm':'Confirm Upload','misc.drop_too_many':'... {n} more files',
        'cust.field.name':'Customer Name','cust.field.title':'Title','cust.field.tier':'Tier',
        'cust.field.website':'Website',
        'cust.field.tier_none':'None','cust.field.buyer':'Buyer Type','cust.field.buyer_none':'Not Set',
        'cust.field.country':'Country','cust.field.city':'City','cust.field.category':'Main Category','cust.field.score':'Match Score',
        'cust.field.score_none':'Not Rated','cust.field.email':'Email','cust.field.phone':'Phone',
        'cust.field.backup_email':'Backup Email','cust.field.contact':'Contact Info','cust.field.note':'Notes',
        'cust.field.function':'Function','cust.field.responsibility':'Responsibility',
        'cust.field.follow':'AI Follow-up','cust.field.no_orders':'No orders yet. Click "+ New Order" to add.',
        'cust.followup_note':'Follow-up note','cust.followup_note_hint':'Customer-level note, shown on the primary contact card',
        'cust.field.order_fail':'Failed to load orders',
        'cust.summary.total':'{n} customers','cust.summary.follow_up':'{n} follow-ups',
        'cust.summary.overdue':'{n} overdue','cust.summary.orders':'{amt} order total',
        'brief.title':'Today brief','brief.new_inquiries':'New inquiries','brief.overdue':'Overdue',
        'brief.pending_ship':'To ship','brief.summary_empty':'Brief not generated yet',
        'brief.todo':'To-do','brief.cron':'Cron outputs','brief.cron_empty':'No cron output today',
        'brief.cron_no_jobs':'No active cron jobs','brief.cron_setup':'Configure cron jobs →',
        'brief.cron_waiting':'Waiting for first run','brief.cron_silent':'No new updates',
        'brief.cron_today_tag':'Today','brief.cron_view_full':'Click to view full cron output',
        'todo.add':'Add to-do','todo.placeholder':'What needs doing? Press Enter to save',
        'todo.due':'Due date','todo.customer':'Customer','todo.no_customer':'— No customer —',
        'todo.save':'Save','todo.overdue':'Overdue','todo.today':'Today','todo.upcoming':'Upcoming',
        'todo.empty':'No to-dos yet — click + to add','todo.confirm_delete':'Delete this to-do?',
        'todo.empty_label':'This to-do has no text','todo.added':'Added to to-do',
        'chat.cmd.sub':'Give a command · customer dev, inquiry reply, quotes, docs — just say it',
        'brief.dash':'—',
        'chat.blocks.draft_warn':'Draft · will not auto-send','chat.blocks.copy_draft':'Copy draft',
        'chat.blocks.next':'NEXT','chat.blocks.copied':'Copied',
        'chat.blocks.edit_draft':'Edit more','chat.blocks.gen_pi':'Generate PI',
        'chat.blocks.copy_note':'You send it yourself from your mailbox',
        'chat.blocks.edit_prompt':'Revise this email draft','chat.blocks.gen_pi_prompt':'Generate a PI from this quotation',
        'brief.done':'DONE · {n}',
        'profile.open':'Customer profile','profile.title':'Customer profile','profile.back_wall':'← Back to wall',
        'profile.circle':'People circle','profile.prefs':'Prefs & gifts',
        'profile.sec.family':'FAMILY','profile.sec.suppliers':'OTHER SUPPLIERS',
        'profile.sec.prefs':'PREFERENCES','profile.sec.taboos':'TABOOS',
        'profile.sec.dates':'KEY DATES','profile.sec.gifts':'GIFTS',
        'profile.add':'+ Add','profile.add_gift':'+ Gift','profile.extract_chat':'Extract from chat',
        'profile.extract_email':'Extract from email','profile.confirm':'Confirm','profile.void':'Void',
        'profile.delete':'Delete','profile.delete_confirm':'Delete this manual entry?',
        'profile.ai_use':'Use for AI','profile.ai_on':'ON','profile.ai_off':'OFF',
        'profile.show_quote':'Quote','profile.ask':'Asked for',
        'profile.pending':'PENDING · {n}',
        'profile.solicit_note':'Local only · not exported · never sent to AI',
        'profile.restart':'Available after restart','profile.empty_circle':'No circle facts yet',
        'profile.empty_prefs':'No prefs / gifts yet','profile.confirmed':'Confirmed',
        'profile.saved':'Saved','profile.pick_category':'Pick a category',
        'profile.bad_category':'Invalid category','profile.subject_ph':'Subject (e.g. name)',
        'profile.content_ph':'Fact content','profile.pick_direction':'Direction',
        'profile.item_ph':'Item','profile.extract_done':'Extracted: facts {f} · gifts {g} · dropped {d}',
        'profile.src_chat':'Talk','profile.src_email':'Email','profile.src_visit':'Visit','profile.src_manual':'Manual',
        'profile.edit':'Edit','profile.add_fact':'Add profile entry','profile.edit_fact':'Edit profile entry',
        'profile.gift_add_title':'Add gift','profile.gift_edit_title':'Edit gift',
        'profile.category':'Category','profile.subject':'Subject','profile.content':'Content',
        'profile.content_required':'Content is required','profile.item':'Item','profile.item_required':'Item is required',
        'profile.direction':'Direction','profile.approx_value':'Amount','profile.currency':'Currency',
        'profile.gift_date':'Date','profile.occasion':'Occasion','profile.note':'Note',
        'profile.invalid_amount':'Invalid amount',
        'profile.attach':'Attach to','profile.attach_none':'No one',
        'profile.attach_primary':'Primary: {name}','profile.attach_primary_default':'Primary',
        'profile.attach_contact_fallback':'Contact',
        'cust.summary.plus_currencies':'+{n} more',
        'order.cust_label':'Customer *','order.cust_select':'-- Select Customer --',
        'order.status_quoting':'Quoting','order.status_ordered':'Ordered','order.status_shipped':'Shipped','order.status_done':'Completed','order.status_cancelled':'Cancelled',
        'order.btn_delete':'🗑 Delete','order.confirm_delete':'Delete this order?',
        'order.created':'Order created','order.updated':'Order updated','order.deleted':'Order deleted',
        'hist.delete_title':'Delete','hist.confirm_delete':'Delete this conversation? This cannot be undone.',
        'hist.deleted':'Conversation deleted','hist.delete_fail':'Delete failed',
        'toast.input_required':'Please fill in library name and path','toast.lib_added':'Library "{name}" added',
        'toast.lib_add_fail':'Failed to add','toast.saved':'Saved','toast.deleted':'Deleted',
        'toast.cust_product_required':'Please select customer and fill in product name','toast.select_library':'Please select a library',
        'toast.complete_onboarding':'Please complete the tutorial first','toast.enter_company':'Please enter a company name or URL',
        'toast.wizard_product':'What do you sell?','toast.wizard_market':'Which market?',
        'toast.activate_fail':'Activation failed','toast.network_retry':'Network error, please retry',
        'toast.request_timeout':'Request timeout',
        'toast.imported':'Imported {n} files to "{dir}"','toast.import_fail':'Import failed',
        'wiz.step1_title':'First: what do you sell?','wiz.step1_desc':'Anything works — "LED lights", "hardware", "textiles"...',
        'wiz.step1_ph':'e.g. LED high bay lights, stainless steel bolts...',
        'wiz.step1_btn':'Next: which markets? →','wiz.step1_indicator':'● What',
        'wiz.step2_title':'Which country or region?','wiz.step2_desc':'e.g. "Germany", "US", "Middle East", "Southeast Asia"',
        'wiz.step2_ph':'e.g. Germany, US, Middle East...',
        'wiz.step2_btn':'Next: what type of customer? →','wiz.step2_indicator':'● Where',
        'wiz.step3_title':'What type of customer?','wiz.step3_indicator':'● Who',
        'wiz.type_distributor':'Wholesaler / Distributor','wiz.type_distributor_desc':'Bulk purchase for local distribution',
        'wiz.type_oem':'Brand / OEM Factory','wiz.type_oem_desc':'OEM production, long-term large orders',
        'wiz.type_retailer':'Retailer / Chain Store','wiz.type_retailer_desc':'Small batch, high frequency',
        'wiz.type_any':'Any type works','wiz.type_any_desc':'Let AI decide the best fit',
        'wiz.launch_btn':'🚀 Find Customers!','wiz.back':'← Back','wiz.skip':'Skip',
        'wiz.step_done':'✓ Products','wiz.step2_done':'✓ Markets',
        'wiz.searching':'Searching for customers...','wiz.searching_desc':'Multi-channel search in progress',
        'wiz.type_names.distributor':'Wholesaler/Distributor','wiz.type_names.oem':'Brand/OEM',
        'wiz.type_names.retailer':'Retailer/Chain','wiz.type_names.any':'All Types',
        'onb.welcome_title':'Welcome to Trade AI','onb.welcome_desc2':'Trade can <strong>auto-research customer backgrounds (OSINT)</strong> and <strong>write professional B2B outreach emails</strong> based on your products.',
        'onb.feat1':'Customs data · Social media · Website audit','onb.feat2':'AI cold emails · Follow-up · Quotations',
        'onb.feat3':'24/7 auto lead gen · Scheduled tasks',
        'onb.start_btn':'🚀 Find First Customer','onb.skip_btn':'Skip, start directly',
        'sys.updating':'Updating...','sys.restarting':'Restarting...',
        'sys.updating_now':'Pulling latest code and installing dependencies, please wait (~1 min)…',
        'sys.update_done_restart':'✅ Update complete. Click "🔄 Restart" to apply.',
        'sys.update_done':'✅ Update complete. Click "🔄 Restart" to apply.',
        'sys.update_fail':'❌ Update failed: ','sys.update_unknown':'⚠️ Update result unknown, check network',
        'sys.update_network':'⚠️ Update request failed, check network',
        'sys.update_confirm':'This will pull code from the GitHub main branch and install dependencies. You restart manually when it finishes.\nYour database is backed up before upgrading.\n\nUpdate now?',
        'sys.update_confirm_current':'Current version {current}, target commit {target}.\nThis will install that commit; you restart manually when it finishes.\nYour database is backed up before upgrading.\n\nUpdate now?',
        'usage.today':'Today {used} / {limit} tokens',
        'usage.unlimited':'Today {used} tokens',
        'usage.over':'Today {used} / {limit} tokens · over quota (not blocked)',
        'sys.restart_toast':'🔄 Restarting Trade...',
        'sys.restart_ok':'✅ Restart command sent, page will refresh soon',
        'sys.restart_fail':'❌ Restart failed: ',
        'sys.restart_busy_update':'Update in progress — restart after it finishes.',
        'sys.restart_wait':'🔄 Service restarting, page will refresh...',
        'sys.restart_timeout':'⚠️ Restart timeout, please refresh manually',
        'sys.skills_updating':'Updating...',
        'sys.skills_ok':'✅ Skills updated!',
        'sys.skills_fail':'❌ Update failed: ',
        'sys.skills_error':'❌ Update error: ',
        'skills.copied':'Prompt copied: ',
        'import.importing':'Importing...','import.confirm':'Confirm Upload',
        'guide.rest':'No task scheduled now',
        'guide.progress':"Today's Progress",
        'mailbox.title':'Mailboxes',
        'mailbox.guide_en_tip':'Guide in Chinese only for now — ask us if you need English help.',
        'mailbox.guide_title':'Connection guide',
        'mailbox.form_title':'Bind a mailbox',
        'mailbox.list_title':'Bound mailboxes',
        'mailbox.preset':'Provider',
        'mailbox.preset_custom':'Other IMAP',
        'mailbox.email':'Email address',
        'mailbox.secret':'Auth code / app password',
        'mailbox.secret_ph':'IMAP authorization code — not your web login password',
        'mailbox.display_name':'Display name (optional)',
        'mailbox.display_name_ph':'e.g. Inquiry inbox',
        'mailbox.host':'IMAP host',
        'mailbox.port':'Port',
        'mailbox.username':'Login username',
        'mailbox.username_ph':'Usually same as email address',
        'mailbox.test':'Test connection',
        'mailbox.bind':'Bind',
        'mailbox.testing':'Testing…',
        'mailbox.test_ok':'Connected',
        'mailbox.test_fail':'Connection failed',
        'mailbox.test_first':'Test the connection successfully before binding',
        'mailbox.need_email_secret':'Enter email address and authorization code',
        'mailbox.bind_ok':'Mailbox bound',
        'mailbox.faq':'FAQ',
        'mailbox.empty_title':'No mailbox bound yet',
        'mailbox.empty_hint':'Follow the guide above, test, then bind',
        'mailbox.col_email':'Mailbox',
        'mailbox.col_status':'Sync status',
        'mailbox.col_actions':'Actions',
        'mailbox.synced_at':'Last sync',
        'mailbox.never_synced':'Never pulled',
        'mailbox.email_count':'{n} messages cached locally',
        'mailbox.pull':'Pull',
        'mailbox.pulling':'Pulling…',
        'mailbox.pull_done':'Pulled {n} new message(s)',
        'mailbox.update_secret':'Update auth code',
        'mailbox.secret_prompt':'New IMAP authorization code (keeps old code if test fails)',
        'mailbox.secret_updated':'Authorization code updated',
        'mailbox.unbind':'Unbind',
        'mailbox.unbind_confirm':'Unbind removes cached mail for this account. Continue?',
        'mailbox.unbind_ok':'Unbound',
        'contacts.add':'Add contact',
        'contacts.empty':'No contacts yet',
        'contacts.primary_badge':'Primary',
        'contacts.extra_badge':'Extra',
        'contacts.edit':'Edit',
        'contacts.delete':'Delete',
        'contacts.delete_confirm':'Delete contact "{name}"?',
        'contacts.deleted':'Contact deleted',
        'contacts.add_title':'Add contact',
        'contacts.edit_title':'Edit contact',
        'contacts.name':'Name *',
        'contacts.function':'Function',
        'contacts.title_f':'Title',
        'contacts.responsibility':'Responsibility',
        'contacts.email':'Email',
        'contacts.phone':'Phone',
        'contacts.whatsapp':'WhatsApp',
        'contacts.wechat':'WeChat',
        'contacts.note':'Note',
        'contacts.name_required':'Name is required',
        'contacts.saved':'Contact saved',
        'contacts.tags_title':'Tags',
        'contacts.tags_ph':'Type a tag, Enter or comma to add',
        'contacts.tags_add':'Add',
        'contacts.tags_empty':'No tags yet',
        'contacts.tags_too_long':'Each tag max 20 characters',
        'contacts.tags_too_many':'At most 20 tags',
        'inquiry.section':'Inquiries',
        'inquiry.empty':'No inquiries yet — create one to start tracking',
        'inquiry.title_ph':'Inquiry title',
        'inquiry.create':'New inquiry',
        'inquiry.delete':'Delete',
        'inquiry.stage_auto':'Auto (from inquiries)',
        'inquiry.manual_badge':'M',
        'inquiry.manual_title':'Manually locked — open the wall to switch back to Auto',
        'inquiry.created':'Inquiry created',
        'inquiry.updated':'Inquiry updated',
        'inquiry.deleted':'Inquiry deleted',
    }
};

function t(key, params) {
    var s = (I18N[currentLang] && I18N[currentLang][key]) || (I18N.zh && I18N.zh[key]) || key;
    if (params) { for (var k in params) s = s.replace('{'+k+'}', params[k]); }
    return s;
}

function switchLang(lang) {
    if (lang === currentLang) return;
    currentLang = lang;
    try { localStorage.setItem('trade_lang', lang); } catch(_) {}
    // 完整刷新 UI
    _applyLanguage();
}

function initLang() {
    try { currentLang = localStorage.getItem('trade_lang') || 'zh'; } catch(_) { currentLang = 'zh'; }
    var sel = document.getElementById('lang-select');
    if (sel) sel.value = currentLang;
    _applyLanguage();
}

function _applyLanguage() {
    // 1. 侧边栏
    _updateSidebarLabels();
    // 2. 公司选择器
    var cs = document.getElementById('company-select');
    if (cs && cs.options[0]) cs.options[0].text = t('company.select');
    var addBtn = document.querySelector('.csel-row button');
    if (addBtn) { addBtn.title = t('company.add'); addBtn.textContent = '+'; }
    // 3. Footer 按钮 —— 图标（textContent）写在 HTML 里，这里只填悬停提示。
    //    早期把图标和文字一起塞进 i18n（'⬆️ 系统更新'），改图标要同步改两份翻译；
    //    现在翻译只管文字。
    var map = {
        'system-update-btn': 'footer.update', 'system-restart-btn': 'footer.restart',
        'copilot-settings-btn': 'footer.copilot',
        'skills-help-btn': 'footer.skills', 'skills-update-btn': 'footer.skills_update',
        'upgrade-help-btn': 'footer.upgrade',
        'onboarding-btn': 'footer.onboarding',
    };
    for (var id in map) {
        var b = document.getElementById(id);
        if (b) b.setAttribute('data-tip', t(map[id]));
    }
    // 4. 静态 modal 文本更新
    _updateStaticModals();
    // 5. 重新渲染当前视图
    if (currentView === 'chat') {
        navToView('chat', currentChatContext, t('nav.' + currentChatContext));
    } else {
        navToView(currentView);
    }
    // 6. 更新页面标题
    document.title = currentLang === 'en' ? 'Trade AI Assistant' : 'Trade AI Assistant — 智能外贸销售助手';
    // 7. 用量文案随语言刷新（公司未选时函数内部自行隐藏）
    loadUsageToday();
}

function _updateSidebarLabels() {
    var sectionKeys = ['nav.workbench', 'nav.outreach', 'nav.sales', 'nav.tools', 'nav.hist'];
    document.querySelectorAll('.nav-section-title').forEach(function(el, i) {
        if (i < sectionKeys.length) el.textContent = t(sectionKeys[i]);
    });
    var ctxMap = {
        'daily':'nav.daily','lead':'nav.lead','platform':'nav.platform',
        'social':'nav.social','linkedin':'nav.linkedin','customs':'nav.customs',
        'docs':'nav.docs','docgen':'nav.docgen','osint':'nav.osint',
    };
    var viewMap = {'customers':'nav.customers','mailboxes':'nav.mailboxes','tasks':'nav.tasks','history':'nav.history'};
    document.querySelectorAll('.nav-item').forEach(function(el) {
        var ctx = el.getAttribute('data-chat-context');
        var view = el.getAttribute('data-view');
        var key = (ctx && ctxMap[ctx]) || (view && viewMap[view]);
        if (key) {
            var label = el.querySelector('.nav-label');
            if (label) label.textContent = t(key);
            if (ctx && view === 'chat') {
                // O-17：不再动态写 onclick（CSP script-src-attr 'none'），
                // 改更新 data-args，语言切换时导航名一起翻译
                el.setAttribute('data-act', 'navToView');
                el.setAttribute('data-args', JSON.stringify(['chat', ctx, t(key)]));
            }
        }
    });
    if (currentView === 'chat') currentChatName = t('nav.' + currentChatContext);
}

function _updateStaticModals() {
    // Company modal
    var cm = document.getElementById('company-modal');
    if (cm) {
        var h3 = cm.querySelector('h3'); if (h3) h3.textContent = t('modal.co.title');
        var tb1 = document.getElementById('tab-btn-companies'); if (tb1) tb1.textContent = t('modal.co.tab_list');
        var tb2 = document.getElementById('tab-btn-identity'); if (tb2) tb2.textContent = t('modal.co.tab_identity');
        var h4 = cm.querySelector('#tab-companies h4'); if (h4) h4.textContent = t('modal.co.add_title');
        var lbls = cm.querySelectorAll('label');
        lbls.forEach(function(l) {
            var f = l.getAttribute('for');
            if (f === 'co-name') l.textContent = t('modal.co.name');
            else if (f === 'co-contact-name') l.textContent = t('modal.co.contact');
            else if (f === 'co-contact-email') l.textContent = t('modal.co.email');
            else if (f === 'co-website') l.textContent = t('modal.co.website');
            else if (f === 'identity-editor') l.textContent = t('modal.co.identity_label');
        });
        var inps = cm.querySelectorAll('input');
        inps.forEach(function(inp) {
            if (inp.id === 'co-name') inp.placeholder = t('modal.co.name_ph');
            else if (inp.id === 'co-slug') { inp.placeholder = t('modal.co.slug_ph'); inp.title = t('modal.co.slug_tt'); }
            else if (inp.id === 'co-contact-name') inp.placeholder = t('modal.co.contact_ph');
        });
        var ta = cm.querySelector('#identity-editor'); if (ta) ta.placeholder = t('modal.co.identity_ph');
        var btns = cm.querySelectorAll('.form-actions button');
        btns.forEach(function(b) {
            if (b.textContent.includes('创建') || b.textContent.includes('Create')) b.textContent = t('modal.co.create');
            else if (b.textContent.includes('保存') || b.textContent.includes('Save')) b.textContent = t('btn.save');
            else if (b.textContent.includes('关闭') || b.textContent.includes('Close')) b.textContent = t('btn.close');
        });
    }
    // Customer modal
    var cum = document.getElementById('customer-modal');
    if (cum) {
        var ch3 = cum.querySelector('h3'); if (ch3 && !ch3.textContent.includes('编辑') && !ch3.textContent.includes('Edit')) ch3.textContent = t('modal.cust.title');
        var clbls = cum.querySelectorAll('label');
        clbls.forEach(function(l) {
            var f = l.getAttribute('for');
            var m = {'cust-name':'modal.cust.name','cust-contact':'modal.cust.contact','cust-title':'modal.cust.title_f',
                'cust-country':'modal.cust.country','cust-email':'modal.cust.email','cust-phone':'modal.cust.phone',
                'cust-whatsapp':'modal.cust.whatsapp','cust-linkedin':'modal.cust.linkedin','cust-website':'modal.cust.website',
                'cust-tier':'modal.cust.tier','cust-buyer-type':'modal.cust.buyer','cust-main-category':'modal.cust.category',
                'cust-backup-email':'modal.cust.backup_email','cust-match-score':'modal.cust.score',
                'cust-note':'modal.cust.note','cust-follow-up-note':'modal.cust.follow'};
            if (m[f]) l.textContent = t(m[f]);
        });
        var cpls = cum.querySelectorAll('input[placeholder]');
        cpls.forEach(function(inp) {
            if (inp.id === 'cust-name') inp.placeholder = t('modal.cust.name_ph');
            else if (inp.id === 'cust-contact') inp.placeholder = t('modal.cust.contact_ph');
            else if (inp.id === 'cust-country') inp.placeholder = t('modal.cust.country_ph');
        });
        var cta = cum.querySelector('#cust-note'); if (cta) cta.placeholder = t('modal.cust.note_ph');
        var cfa = cum.querySelector('#cust-follow-up-note'); if (cfa) cfa.placeholder = t('modal.cust.follow_ph');
        var csels = cum.querySelectorAll('select');
        csels.forEach(function(s) {
            if (s.id === 'cust-tier' && s.options[0]) s.options[0].text = t('modal.cust.tier_none');
            if (s.id === 'cust-buyer-type' && s.options[0]) s.options[0].text = t('modal.cust.buyer_none');
            if (s.id === 'cust-match-score' && s.options[0]) s.options[0].text = t('modal.cust.score_none');
        });
        var cbtns = cum.querySelectorAll('.form-actions button');
        cbtns.forEach(function(b) {
            if (b.textContent.includes('取消') || b.textContent.includes('Cancel')) b.textContent = t('btn.cancel');
            else if (b.textContent.includes('保存') || b.textContent.includes('Save')) b.textContent = t('btn.save');
        });
    }
    // Library modal
    var lm = document.getElementById('library-modal');
    if (lm) {
        var lh3 = lm.querySelector('h3'); if (lh3) lh3.textContent = t('modal.lib.title');
        var lp = lm.querySelector('p'); if (lp) lp.textContent = t('modal.lib.desc');
        var llbls = lm.querySelectorAll('label');
        llbls.forEach(function(l) {
            var f = l.getAttribute('for');
            if (f === 'lib-name') l.textContent = t('modal.lib.name');
            else if (f === 'lib-path') l.textContent = t('modal.lib.path');
            else if (f === 'lib-desc') l.textContent = t('modal.lib.notes');
        });
        var lips = lm.querySelectorAll('input');
        lips.forEach(function(inp) {
            if (inp.id === 'lib-name') inp.placeholder = t('modal.lib.name_ph');
            else if (inp.id === 'lib-path') inp.placeholder = t('modal.lib.path_ph');
            else if (inp.id === 'lib-desc') inp.placeholder = t('modal.lib.notes_ph');
        });
        var lhint = lm.querySelector('.hint'); if (lhint) lhint.textContent = t('modal.lib.path_hint');
        var lbtns = lm.querySelectorAll('.form-actions button');
        lbtns.forEach(function(b) {
            if (b.textContent.includes('取消') || b.textContent.includes('Cancel')) b.textContent = t('btn.cancel');
            else if (b.textContent.includes('添加') || b.textContent.includes('Add')) b.textContent = t('modal.lib.create');
        });
    }
    // Upgrade help modal
    var um = document.getElementById('upgrade-help-modal');
    if (um) {
        var uh3 = um.querySelector('h3'); if (uh3) uh3.textContent = t('modal.upgrade.title');
        var btns = um.querySelectorAll('.form-actions button');
        btns.forEach(function(b) { b.textContent = t('btn.close'); });
    }
    // Skills help modal
    var sm = document.getElementById('skills-help-modal');
    if (sm) {
        var sh3 = sm.querySelector('h3'); if (sh3) sh3.textContent = t('modal.skills.title');
        var sp = sm.querySelector('p'); if (sp) sp.textContent = t('modal.skills.desc');
        var sbtns = sm.querySelectorAll('.form-actions button');
        sbtns.forEach(function(b) { b.textContent = t('btn.close'); });
    }
}
let _onboardingOsinResponse = ''; // accumulated AI response text
let _onboardingStreamCtl = null;  // AbortController for SSE stream

