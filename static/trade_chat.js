// ═════════════════════ STATE ═════════════════════
let companies = [];
let currentCompanyId = null;
let currentView = 'chat';       // chat | customers | tasks | directory | history
let currentChatContext = 'daily'; // daily | lead | platform | social | linkedin | customs | docs | docgen | osint
let currentChatName = '今日简报';
let currentLibraryId = null;
let currentCustomerId = null;
let _currentConvId = null;       // 当前 AI 回复的 conversation_id，用于评分
let editingCustomerData = null; // for customer detail panel
let _onboardingStep = 1;          // 1 = welcome card, 2 = OSINT input + results
let _onboardingInputText = '';    // user-entered company name/website
let currentLang = 'zh';           // zh | en

// ═════════════════════ I18N ═════════════════════
const I18N = {
    zh: {
        // nav
        'nav.daily':'今日简报','nav.lead':'客户开发','nav.platform':'网站诊断',
        'nav.social':'社媒营销','nav.linkedin':'LinkedIn','nav.customs':'海关数据',
        'nav.customers':'客户管理','nav.docs':'文档库','nav.docgen':'文档生成',
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
        // footer buttons
        'footer.update':'⬆️ 系统更新','footer.restart':'🔄 重启',
        'footer.skills':'📖 技能帮助','footer.skills_update':'🔄 Skills',
        'footer.upgrade':'⬆️ 升级说明','footer.onboarding':'🎓 新手引导',
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
        'modal.skills.title':'📖 全部 38 个技能速查',
        'modal.skills.desc':'在聊天框输入关键词，Trade 自动匹配合适的技能。点击复制图标可复制快速启动提示词。',
        // common
        'btn.close':'关闭','btn.cancel':'取消','btn.save':'保存','btn.ok':'确定',
        // license
        'license.expired':'已到期','license.expiring':'即将到期','license.trial':'试用',
        'license.active':'已激活','license.req_code':'申请码',
        'license.activate_btn':'🔑 输入激活码','license.days_left':'剩余 {n} 天',
        // toast
        'toast.copied':'已复制','toast.saved':'已保存','toast.deleted':'已删除',
        'toast.updated':'已更新','toast.error':'操作失败','toast.network':'网络错误',
        'toast.no_company':'请先选择公司','toast.csv_ok':'成功导入 {n} 个客户',
        // customer view
        'customer.title':'客户管理','customer.add':'添加客户',
        'customer.import':'📥 CSV导入','customer.search':'搜索客户...',
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
        // orders
        'order.title':'新增订单','order.edit_title':'编辑订单',
        'order.no':'订单号','order.product':'产品名称 *','order.qty':'数量',
        'order.unit':'单位','order.price':'单价','order.currency':'币种',
        'order.amount':'总金额','order.status':'状态','order.delivery':'交货日期',
        'order.payment':'付款方式','order.notes':'备注',
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
        'cust.field.country':'国家','cust.field.category':'主营品类','cust.field.score':'匹配度',
        'cust.field.score_none':'未评分','cust.field.email':'邮箱','cust.field.phone':'电话',
        'cust.field.backup_email':'备用邮箱','cust.field.contact':'联系方式','cust.field.note':'备注',
        'cust.field.follow':'AI 跟进建议','cust.field.no_orders':'暂无订单，点击「新增订单」添加。',
        'cust.field.order_fail':'订单加载失败',
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
        'sys.updating':'⏳ 更新中...','sys.restarting':'⏳ 重启中...',
        'sys.update_done_restart':'✅ 系统更新完成！正在重启...',
        'sys.update_done':'✅ 更新完成。请点击"🔄 重启"以应用新版本。',
        'sys.update_fail':'❌ 更新失败: ','sys.update_unknown':'⚠️ 更新结果未知，请检查网络后重试',
        'sys.update_network':'⚠️ 更新请求失败，请检查网络连接后重试',
        'sys.restart_toast':'🔄 正在重启 Trade 服务...',
        'sys.restart_ok':'✅ 重启命令已发送，页面将在几秒后刷新',
        'sys.restart_fail':'❌ 重启失败: ',
        'sys.restart_wait':'🔄 服务正在重启，页面即将刷新...',
        'sys.restart_timeout':'⚠️ 服务重启超时，请手动刷新页面',
        'sys.skills_updating':'⏳ 更新中...',
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
    },
    en: {
        'nav.daily':'Daily Briefing','nav.lead':'Lead Gen','nav.platform':'Site Audit',
        'nav.social':'Social','nav.linkedin':'LinkedIn','nav.customs':'Customs',
        'nav.customers':'Customers','nav.docs':'Documents','nav.docgen':'Doc Gen',
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
        'footer.update':'⬆️ Update','footer.restart':'🔄 Restart',
        'footer.skills':'📖 Skills Help','footer.skills_update':'🔄 Skills',
        'footer.upgrade':'⬆️ Upgrade Guide','footer.onboarding':'🎓 Tutorial',
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
        'modal.skills.title':'📖 All 38 Skills Reference',
        'modal.skills.desc':'Type keywords in chat — Trade auto-matches the right skill. Click copy icon for quick prompts.',
        'btn.close':'Close','btn.cancel':'Cancel','btn.save':'Save','btn.ok':'OK',
        'license.expired':'Expired','license.expiring':'Expiring Soon','license.trial':'Trial',
        'license.active':'Active','license.req_code':'Request Code',
        'license.activate_btn':'🔑 Enter Activation Code','license.days_left':'{n} days left',
        'toast.copied':'Copied','toast.saved':'Saved','toast.deleted':'Deleted',
        'toast.updated':'Updated','toast.error':'Error','toast.network':'Network Error',
        'toast.no_company':'Please select a company first','toast.csv_ok':'Imported {n} customers',
        'customer.title':'Customers','customer.add':'Add Customer',
        'customer.import':'📥 Import CSV','customer.search':'Search...',
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
        'order.title':'New Order','order.edit_title':'Edit Order',
        'order.no':'Order No.','order.product':'Product *','order.qty':'Qty',
        'order.unit':'Unit','order.price':'Unit Price','order.currency':'Currency',
        'order.amount':'Total','order.status':'Status','order.delivery':'Delivery',
        'order.payment':'Payment Terms','order.notes':'Notes',
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
        'cust.field.country':'Country','cust.field.category':'Main Category','cust.field.score':'Match Score',
        'cust.field.score_none':'Not Rated','cust.field.email':'Email','cust.field.phone':'Phone',
        'cust.field.backup_email':'Backup Email','cust.field.contact':'Contact Info','cust.field.note':'Notes',
        'cust.field.follow':'AI Follow-up','cust.field.no_orders':'No orders yet. Click "+ New Order" to add.',
        'cust.field.order_fail':'Failed to load orders',
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
        'sys.updating':'⏳ Updating...','sys.restarting':'⏳ Restarting...',
        'sys.update_done_restart':'✅ Update complete! Restarting...',
        'sys.update_done':'✅ Update complete. Click "🔄 Restart" to apply.',
        'sys.update_fail':'❌ Update failed: ','sys.update_unknown':'⚠️ Update result unknown, check network',
        'sys.update_network':'⚠️ Update request failed, check network',
        'sys.restart_toast':'🔄 Restarting Trade...',
        'sys.restart_ok':'✅ Restart command sent, page will refresh soon',
        'sys.restart_fail':'❌ Restart failed: ',
        'sys.restart_wait':'🔄 Service restarting, page will refresh...',
        'sys.restart_timeout':'⚠️ Restart timeout, please refresh manually',
        'sys.skills_updating':'⏳ Updating...',
        'sys.skills_ok':'✅ Skills updated!',
        'sys.skills_fail':'❌ Update failed: ',
        'sys.skills_error':'❌ Update error: ',
        'skills.copied':'Prompt copied: ',
        'import.importing':'Importing...','import.confirm':'Confirm Upload',
        'guide.rest':'No task scheduled now',
        'guide.progress':"Today's Progress",
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
    // 3. Footer 按钮
    var map = {
        'system-update-btn': 'footer.update', 'system-restart-btn': 'footer.restart',
        'skills-help-btn': 'footer.skills', 'skills-update-btn': 'footer.skills_update',
        'upgrade-help-btn': 'footer.upgrade',
        'onboarding-btn': 'footer.onboarding',
    };
    for (var id in map) { var b = document.getElementById(id); if (b) b.textContent = t(map[id]); }
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
    var viewMap = {'customers':'nav.customers','tasks':'nav.tasks','history':'nav.history'};
    document.querySelectorAll('.nav-item').forEach(function(el) {
        var ctx = el.getAttribute('data-chat-context');
        var view = el.getAttribute('data-view');
        var key = (ctx && ctxMap[ctx]) || (view && viewMap[view]);
        if (key) {
            var label = el.querySelector('.nav-label');
            if (label) label.textContent = t(key);
            if (ctx && view === 'chat') {
                el.setAttribute('onclick', "navToView('chat','"+ctx+"','"+t(key)+"')");
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

// ═════════════════════ 客户开发向导 (b2b-customer-finder) ═════════════════════
let _wizardStep = 0;            // 0=hidden, 1=product, 2=market, 3=type, 4=running, 5=results
let _wizardAnswers = { product: '', market: '', customerType: '' };
let _wizardStreamCtl = null;
let _wizardResponse = '';

function isOnboardingCompleted() {
    try { return localStorage.getItem('_onboarding_completed') === '1'; } catch(_) { return false; }
}

// ═════════════════════ 客户开发向导 UI ═════════════════════
function showWizardInLeadView() {
    // 在 lead 聊天上下文中显示客户开发向导卡片
    var msgs = document.getElementById('chat-messages');
    var empty = document.getElementById('chat-empty');
    if (!msgs || !empty) return;
    empty.style.display = 'none';
    // 移除已有向导卡片
    var old = document.getElementById('wizard-card');
    if (old) old.remove();
    _wizardStep = 1;
    var card = document.createElement('div');
    card.id = 'wizard-card';
    card.innerHTML = wizardRenderStep1();
    msgs.appendChild(card);
    setTimeout(function() {
        var inp = document.getElementById('wizard-product-input');
        if (inp) inp.focus();
    }, 200);
}

function wizardRenderStep1() {
    return `<div class="onboarding-card" style="margin:0 auto;max-width:580px;">
        <div class="onboarding-step-indicator">
            <span class="onb-step active">● 卖什么</span><span class="onb-step-arrow">→</span>
            <span class="onb-step">○ 卖到哪</span><span class="onb-step-arrow">→</span>
            <span class="onb-step">○ 找谁</span>
        </div>
        <h2 class="onboarding-title" style="font-size:20px;">先告诉我：你卖什么产品？</h2>
        <p style="text-align:center;color:var(--text-secondary);font-size:14px;margin-bottom:16px;">
            随便说就行，"LED灯""五金""纺织品"都可以</p>
        <div class="onboarding-input-row">
            <input type="text" id="wizard-product-input" placeholder="例如：LED工矿灯、不锈钢螺丝、全棉T恤..."
                class="onboarding-text-input"
                onkeydown="if(event.key==='Enter')wizardNext()" autofocus />
        </div>
        <button class="btn btn-primary btn-lg" onclick="wizardNext()">下一步：卖到哪里去？ →</button>
        <div class="onboarding-skip" style="display:flex;justify-content:flex-end;">
            <a onclick="wizardClose()" title="跳过向导">跳过向导</a>
        </div>
    </div>`;
}

function wizardRenderStep2() {
    return `<div class="onboarding-card" style="margin:0 auto;max-width:580px;">
        <div class="onboarding-step-indicator">
            <span class="onb-step done">✓ 卖什么</span><span class="onb-step-arrow">→</span>
            <span class="onb-step active">● 卖到哪</span><span class="onb-step-arrow">→</span>
            <span class="onb-step">○ 找谁</span>
        </div>
        <h2 class="onboarding-title" style="font-size:20px;">想卖到哪个国家或地区？</h2>
        <p style="text-align:center;color:var(--text-secondary);font-size:14px;margin-bottom:16px;">
            比如"德国""美国""中东""东南亚"，可以写多个</p>
        <div class="onboarding-input-row">
            <input type="text" id="wizard-market-input" placeholder="例如：德国、美国、中东..."
                class="onboarding-text-input"
                onkeydown="if(event.key==='Enter')wizardNext()" autofocus />
        </div>
        <button class="btn btn-primary btn-lg" onclick="wizardNext()">下一步：找什么类型？ →</button>
        <div class="onboarding-skip" style="display:flex;justify-content:space-between;">
            <a onclick="wizardBack()">← 返回修改</a>
            <a onclick="wizardClose()">跳过向导</a>
        </div>
    </div>`;
}

function wizardRenderStep3() {
    return `<div class="onboarding-card" style="margin:0 auto;max-width:580px;">
        <div class="onboarding-step-indicator">
            <span class="onb-step done">✓ 卖什么</span><span class="onb-step-arrow">→</span>
            <span class="onb-step done">✓ 卖到哪</span><span class="onb-step-arrow">→</span>
            <span class="onb-step active">● 找谁</span>
        </div>
        <h2 class="onboarding-title" style="font-size:20px;">想找什么类型的客户？</h2>
        <div class="wizard-choice-row">
            <button class="wizard-choice-btn" onclick="wizardSelectType('distributor',this)">
                <span class="wc-icon">📦</span>
                <div class="wc-text">
                    <div class="wc-title">批发商 / 分销商</div>
                    <div class="wc-desc">大量采购再分销到本地市场</div>
                </div>
            </button>
            <button class="wizard-choice-btn" onclick="wizardSelectType('oem',this)">
                <span class="wc-icon">🏭</span>
                <div class="wc-text">
                    <div class="wc-title">品牌商 / OEM 工厂</div>
                    <div class="wc-desc">贴牌生产，长期大单</div>
                </div>
            </button>
            <button class="wizard-choice-btn" onclick="wizardSelectType('retailer',this)">
                <span class="wc-icon">🏪</span>
                <div class="wc-text">
                    <div class="wc-title">零售商 / 连锁店</div>
                    <div class="wc-desc">小批量多频次采购</div>
                </div>
            </button>
            <button class="wizard-choice-btn" onclick="wizardSelectType('any',this)">
                <span class="wc-icon">🌍</span>
                <div class="wc-text">
                    <div class="wc-title">都行，帮我一起找</div>
                    <div class="wc-desc">让 AI 自动判断最合适的类型</div>
                </div>
            </button>
        </div>
        <button class="btn btn-primary btn-lg wizard-launch-btn" id="wizard-launch-btn" disabled
            onclick="wizardLaunch()">🚀 开始找客户！</button>
        <div class="onboarding-skip" style="display:flex;justify-content:space-between;">
            <a onclick="wizardBack()">← 返回修改</a>
            <a onclick="wizardClose()">跳过向导</a>
        </div>
    </div>`;
}

function wizardNext() {
    if (_wizardStep === 1) {
        var inp = document.getElementById('wizard-product-input');
        _wizardAnswers.product = (inp?.value || '').trim();
        if (!_wizardAnswers.product) { toast(t('toast.wizard_product')); return; }
        _wizardStep = 2;
        updateWizardCard(wizardRenderStep2());
        setTimeout(function() { var el = document.getElementById('wizard-market-input'); if (el) el.focus(); }, 200);
    } else if (_wizardStep === 2) {
        var inp2 = document.getElementById('wizard-market-input');
        _wizardAnswers.market = (inp2?.value || '').trim();
        if (!_wizardAnswers.market) { toast(t('toast.wizard_market')); return; }
        _wizardStep = 3;
        updateWizardCard(wizardRenderStep3());
    }
}

function wizardBack() {
    if (_wizardStep === 2) {
        _wizardStep = 1;
        updateWizardCard(wizardRenderStep1());
        setTimeout(function() { var el = document.getElementById('wizard-product-input'); if (el) { el.value = _wizardAnswers.product; el.focus(); } }, 200);
    } else if (_wizardStep === 3) {
        _wizardStep = 2;
        updateWizardCard(wizardRenderStep2());
        setTimeout(function() { var el = document.getElementById('wizard-market-input'); if (el) { el.value = _wizardAnswers.market; el.focus(); } }, 200);
    }
}

function wizardSelectType(type, btn) {
    _wizardAnswers.customerType = type;
    document.querySelectorAll('.wizard-choice-btn').forEach(function(b) { b.classList.remove('selected'); });
    btn.classList.add('selected');
    var launch = document.getElementById('wizard-launch-btn');
    if (launch) { launch.disabled = false; launch.style.opacity = '1'; }
}

function updateWizardCard(html) {
    var card = document.getElementById('wizard-card');
    if (!card) return;
    var inner = card.querySelector('.onboarding-card');
    if (inner) inner.outerHTML = html;
    else card.innerHTML = html;
}

function wizardClose() {
    _wizardStep = 0; _wizardAnswers = { product: '', market: '', customerType: '' };
    var card = document.getElementById('wizard-card'); if (card) card.remove();
    var empty = document.getElementById('chat-empty'); if (empty) empty.style.display = '';
}

async function wizardLaunch() {
    var a = _wizardAnswers;
    var typeNames = { distributor: '批发商/分销商', oem: '品牌商/OEM工厂', retailer: '零售商/连锁店', any: '所有类型' };
    var typeName = typeNames[a.customerType] || a.customerType;
    var promptText = '帮我找客户。产品=' + a.product + '，市场=' + a.market + '，客户类型=' + typeName;

    _wizardStep = 4;
    updateWizardCard(`<div class="onboarding-card" style="margin:0 auto;max-width:580px;text-align:center;">
        <div class="onboarding-icon">🔍</div>
        <h2 class="onboarding-title">正在帮你找客户...</h2>
        <p style="text-align:center;color:var(--text-secondary);font-size:14px;margin-bottom:8px;">
            自动多通道搜索中，请稍候</p>
        <div style="width:60px;height:4px;background:var(--border-light);border-radius:2px;margin:0 auto;overflow:hidden;">
            <div style="width:30%;height:100%;background:var(--primary);border-radius:2px;animation:wizardProgress 1.5s ease-in-out infinite;"></div>
        </div>
    </div>`);

    // 发送消息到聊天区
    var textarea = document.getElementById('msg-input');
    if (textarea) {
        textarea.value = promptText;
        // 移除向导卡片，用正常聊天流展示
        setTimeout(function() { wizardClose(); }, 500);
        setTimeout(function() { sendMsg(); }, 600);
    }
}

// 向导进度条动画
(function() {
    var style = document.createElement('style');
    style.textContent = '@keyframes wizardProgress { 0% { transform: translateX(-100%); } 100% { transform: translateX(400%); } }';
    document.head.appendChild(style);
})();
function saveState() {
    if (currentCompanyId) sessionStorage.setItem('trade_cid', currentCompanyId);
    else sessionStorage.removeItem('trade_cid');
    sessionStorage.setItem('trade_view', currentView);
    if (currentChatContext) sessionStorage.setItem('trade_ctx', currentChatContext);
}
function loadSavedCid() { return parseInt(sessionStorage.getItem('trade_cid') || '0') || null; }

// ═════════════════════ API ═════════════════════
let _authRecovering = false;

// 把请求体里 id 类字段的空字符串规范化为 null，避免后端 422 int_parsing
function normalizeBody(body) {
    if (!body || typeof body !== 'object') return body;
    var out = {};
    var idFields = ['library_id', 'customer_id', 'company_id'];
    for (var k in body) {
        if (body[k] === '' && (idFields.indexOf(k) >= 0 || /(^|_)(id|ids)$/i.test(k))) {
            out[k] = null;
        } else {
            out[k] = body[k];
        }
    }
    return out;
}

// 401 自动恢复：token 失效（服务重启）→ 重取新 token；公司缺失 → 重载公司列表
async function recoverAuth(method, path, body) {
    if (_authRecovering) return null;
    _authRecovering = true;
    try {
        // 服务重启后旧页面 token 失效：重新拉取 /trade 提取新 token
        var fresh = await fetch('/trade?_=' + Date.now(), { cache: 'no-store' });
        if (fresh.ok) {
            var html = await fresh.text();
            var m = html.match(/(?:const|let|var)\s+TOKEN\s*=\s*"([^"]+)"/);
            if (m && m[1] && m[1] !== TOKEN) {
                TOKEN = m[1];
                var retry = await api(method, path, body);
                if (retry !== null) return retry;
            }
        }
        // token 没变 → 可能是 X-Company-ID 缺失/失效 → 重载公司
        var prevCid = currentCompanyId;
        currentCompanyId = null;
        await loadCompanies();
        if (prevCid && !companies.find(function(c) { return c.id === prevCid; })) {
            toast(t('toast.no_company'));
            return null;
        }
        if (currentCompanyId) {
            var retry2 = await api(method, path, body);
            if (retry2 !== null) return retry2;
        }
        return null;
    } catch (e) {
        return null;
    } finally {
        _authRecovering = false;
    }
}

async function api(method, path, body) {
    const opts = { method, headers: {} };
    if (TOKEN) opts.headers['X-Hermes-Session-Token'] = TOKEN;
    if (currentCompanyId) opts.headers['X-Company-ID'] = String(currentCompanyId);
    if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(normalizeBody(body)); }
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), 120000);
    opts.signal = ctrl.signal;
    try {
        const r = await fetch(path, opts);
        clearTimeout(tid);
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            const msg = err.detail || `请求失败 (${r.status})`;
            if (r.status === 401) {
                // 自动恢复一次：重取 token / 重载公司
                const recovered = await recoverAuth(method, path, body);
                if (recovered !== null) return recovered;
                toast(t('toast.no_company'));
            }
            else if (r.status === 402) showLicenseExpired(msg);
            else if (r.status === 404) toast(msg);
            else if (r.status === 409) toast(msg);
            else toast(msg);
            return null;
        }
        return r.json();
    } catch(e) {
        clearTimeout(tid);
        if (e.name === 'AbortError') { toast(t('toast.request_timeout')); return null; }
        throw e;
    }
}

// ── 许可证 ──

async function loadLicenseStatus() {
    try {
        const r = await fetch('/api/trade/license/status');
        const data = await r.json();
        const bar = document.getElementById('license-bar');
        if (!bar) return;

        var _daysLeft = (typeof data.days_remaining === 'number') ? data.days_remaining : 999;
        var _bgColor = _daysLeft <= 7 ? '#FEF3C7' : '#DBEAFE';
        if (data.status === 'expired' || data.status === 'tampered') _bgColor = '#FEE2E2';
        var reqCodeHtml = data.request_code
            ? ' · ' + t('license.req_code') + ': <code style="background:' + _bgColor + ';padding:1px 6px;border-radius:3px;font-size:11px;user-select:all;cursor:text;" onclick="navigator.clipboard.writeText(this.textContent);toast(t(\'toast.copied\'))">' + esc(data.request_code) + '</code>'
            : '';

        if (data.status === 'expired') {
            bar.style.display = 'block'; bar.style.background = '#FEF2F2'; bar.style.color = '#991B1B';
            bar.innerHTML = '⚠️ ' + t('license.expired') + ' · <a href="#" onclick="showActivateModal()" style="color:#DC2626;text-decoration:underline;">' + t('license.activate_btn') + '</a>' + reqCodeHtml;
        } else if (data.status === 'active' && data.days_remaining <= 7) {
            bar.style.display = 'block';
            bar.style.background = data.days_remaining === 0 ? '#FEF2F2' : '#FFFBEB';
            bar.style.color = data.days_remaining === 0 ? '#991B1B' : '#92400E';
            bar.innerHTML = '✅ ' + t('license.active') + ' · ' + t('license.expiring') + (data.expires_at ? ' ' + data.expires_at.slice(0, 10) : '') + ' · <a href="#" onclick="showActivateModal()" style="color:' + (data.days_remaining===0?'#DC2626':'#D97706') + ';text-decoration:underline;font-weight:600;">' + t('license.activate_btn') + '</a>' + reqCodeHtml;
        } else if (data.status === 'active') {
            bar.style.display = 'block'; bar.style.background = '#F0FDF4'; bar.style.color = '#166534';
            bar.innerHTML = '✅ ' + t('license.active') + (data.expires_at ? ' · ' + t('license.expiring') + ' ' + data.expires_at.substring(0, 10) : '');
        } else if (data.status === 'trial') {
            bar.style.display = 'block';
            bar.style.background = data.days_remaining <= 7 ? '#FFFBEB' : '#EFF6FF';
            bar.style.color = data.days_remaining <= 7 ? '#92400E' : '#1E40AF';
            bar.innerHTML = '⏳ ' + t('license.trial') + ' ' + t('license.days_left', {n: data.days_remaining}) + ' · <a href="#" onclick="showActivateModal()" style="color:' + (data.days_remaining <= 7 ? '#D97706' : '#2563EB') + ';text-decoration:underline;">' + t('license.activate_btn') + '</a>' + reqCodeHtml;
        } else if (data.status === 'tampered') {
            bar.style.display = 'block'; bar.style.background = '#FEF2F2'; bar.style.color = '#991B1B';
            bar.innerHTML = '⚠️ License Error · <a href="#" onclick="showActivateModal()" style="color:#DC2626;text-decoration:underline;font-weight:600;">Reactivate</a>' + reqCodeHtml;
        }
    } catch(e) {}
}

function showLicenseExpired(msg) {
    const div = document.createElement('div');
    div.className = 'modal-backdrop';
    div.innerHTML = '<div class="modal" style="text-align:center;max-width:420px;">' +
        '<h3>⏰ ' + esc(msg || t('license.expired')) + '</h3>' +
        '<p style="margin:8px 0;color:var(--text-secondary);">' + (currentLang==='en'?'Contact Roger Lococo for activation':'请联系 Roger Lococo 获取激活码继续使用') + '</p>' +
        '<img src="/static/wechat-contact.jpeg" alt="WeChat QR" style="width:200px;border-radius:8px;margin:8px 0;">' +
        '<p style="font-size:11px;color:var(--text-muted);">' + (currentLang==='en'?'WeChat QR · Note "Trade"':'微信扫码 · 备注「Trade」') + '</p>' +
        '<p style="font-size:11px;color:var(--text-muted);">📧 lauroge@gmail.com</p>' +
        '<button class="btn btn-primary" onclick="showActivateModal()">' + t('license.activate_btn') + '</button>' +
        '<button class="btn" onclick="this.closest(\'.modal-backdrop\').remove()" style="margin-top:8px;">' + t('btn.close') + '</button>' +
    '</div>';
    document.body.appendChild(div);
}

async function showActivateModal() {
    _removeDynamicModals();
    var reqCode = '';
    try {
        var s = await fetch('/api/trade/license/status');
        var sd = await s.json();
        reqCode = sd.request_code || '';
    } catch(e) {}
    const div = document.createElement('div');
    div.className = 'modal-backdrop';
    div.innerHTML = '<div class="modal" style="text-align:center;">' +
        '<h3>🔑 ' + (currentLang==='en'?'Activate Trade Assistant':'激活 Trade Assistant') + '</h3>' +
        '<p style="margin:8px 0;color:var(--text-secondary);">' + (currentLang==='en'?'Send the code below to the author to get an activation code':'请将下方申请码发送给作者获取激活码') + '</p>' +
        (reqCode ? '<div style="background:var(--bg-secondary);padding:10px 14px;border-radius:var(--radius-sm);font-family:monospace;font-size:16px;letter-spacing:2px;margin:8px 0;cursor:pointer;user-select:all;" onclick="navigator.clipboard.writeText(this.textContent);toast(t(\'toast.copied\'))" title="' + (currentLang==='en'?'Click to copy':'点击复制') + '">' + reqCode + '</div>' : '') +
        '<input type="text" id="activate-code-input" aria-label="Activation code" placeholder="' + (currentLang==='en'?'Paste activation code':'粘贴作者提供的激活码') + '" style="width:100%;padding:10px;border:1px solid var(--border);border-radius:var(--radius-sm);font-family:monospace;font-size:14px;text-align:center;text-transform:uppercase;margin:12px 0;">' +
        '<button class="btn btn-primary" onclick="doActivate()" style="margin-top:8px;">✅ ' + (currentLang==='en'?'Activate':'激活') + '</button>' +
        '<button class="btn" onclick="this.closest(\'.modal-backdrop\').remove()">' + t('btn.cancel') + '</button>' +
        '<p id="activate-msg" style="margin-top:10px;font-size:12px;"></p>' +
    '</div>';
    document.body.appendChild(div);
    setTimeout(() => document.getElementById('activate-code-input')?.focus(), 100);
}

async function doActivate() {
    const input = document.getElementById('activate-code-input');
    const msg = document.getElementById('activate-msg');
    const code = input.value.trim();
    if (!code) { msg.textContent = currentLang === 'en' ? 'Please enter the activation code' : '请输入激活码'; msg.style.color = 'var(--accent-red)'; return; }
    try {
        const r = await fetch('/api/trade/license/activate', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({code})
        });
        const data = await r.json();
        if (data.ok) {
            msg.textContent = data.message;
            msg.style.color = 'var(--accent-green)';
            setTimeout(() => {
                _removeDynamicModals();
                loadLicenseStatus();
            }, 1500);
        } else {
            msg.textContent = data.error || t('toast.activate_fail');
            msg.style.color = 'var(--accent-red)';
        }
    } catch(e) {
        msg.textContent = t('toast.network_retry');
        msg.style.color = 'var(--accent-red)';
    }
}

// ── 重启协调 ──
// 清理前端运行时缓存，但保留用户上下文（trade_cid 让重启后不必重新选公司）
function _clearRuntimeCaches() {
    try {
        // 清理视图缓存（DOM 引用 + 渲染状态），强制重启后重新拉取
        if (typeof viewCache === 'object') {
            for (const k of Object.keys(viewCache)) delete viewCache[k];
        }
        // 仅清理与服务端 schema 强耦合的会话状态，保留 trade_cid（公司选择）
        const preserveKeys = new Set(['trade_cid', '_trade_reload_state']);
        const ssKeys = [];
        for (let i = 0; i < sessionStorage.length; i++) ssKeys.push(sessionStorage.key(i));
        ssKeys.forEach(k => { if (!preserveKeys.has(k)) sessionStorage.removeItem(k); });
    } catch(_) { /* sessionStorage 在隐私模式下可能抛错，忽略 */ }
}

// ── 重启前状态保存 / 恢复（避免 hard reload 丢失阅读位置）──────────

function _saveReloadState() {
    try {
        const state = {
            view: currentView || 'chat',
            scrollY: window.scrollY || document.documentElement.scrollTop || 0,
            chatCtx: currentView === 'chat' ? (currentChatContext || '') : '',
            chatName: currentView === 'chat' ? (currentChatName || '') : '',
            ts: Date.now(),
        };
        sessionStorage.setItem('_trade_reload_state', JSON.stringify(state));
    } catch(_) {}
}

function _restoreReloadState() {
    try {
        const raw = sessionStorage.getItem('_trade_reload_state');
        if (!raw) return null;
        sessionStorage.removeItem('_trade_reload_state');
        const state = JSON.parse(raw);
        // 超过 5 分钟的旧状态丢弃（可能是残留）
        if (Date.now() - state.ts > 300000) return null;
        return state;
    } catch(_) { return null; }
}

// 通过 /api/status 的 started_at 时间戳检测进程是否已重启，然后 hard-reload
// 不依赖 DOWN→UP 序列：新进程启动快时 DOWN 瞬间无法捕捉
async function _waitForRestartAndReload(onTimeout) {
    let attempts = 0;
    const maxAttempts = 120;   // 120 × 1s = 2 分钟兜底
    // 保存当前 started_at，重启后新进程的时间戳会不同
    let oldStartedAt = -1;  // -1 = 无法获取（旧服务无此字段 / 请求失败）
    try {
        const r0 = await fetch('/api/status?_=' + Date.now(), { cache: 'no-store' });
        if (r0.ok) {
            const d0 = await r0.json();
            // 旧服务可能无此字段 → 存 -1，只要能获取到新值就视为重启成功
            oldStartedAt = (typeof d0.started_at === 'number') ? d0.started_at : -1;
        }
    } catch(_) {}

    console.log('[重启] 开始轮询 /api/status (old started_at=' + oldStartedAt + ') ...');
    const tick = async () => {
        attempts++;
        try {
            const r = await fetch('/api/status?_=' + Date.now(), { cache: 'no-store' });
            if (r.ok) {
                const d = await r.json();
                const cur = (typeof d.started_at === 'number') ? d.started_at : -1;
                // 检测到重启：started_at 从旧值变为新值（-1→数值也算）
                if (cur > 0 && cur !== oldStartedAt) {
                    console.log('[重启] 第 ' + attempts + ' 次 — 检测到新进程 (started_at=' + cur + ')，刷新页面');
                    _saveReloadState();  // 保存当前浏览位置，reload 后恢复
                    _clearRuntimeCaches();
                    try { sessionStorage.removeItem('_upgrade_in_progress'); } catch(_) {}
                    location.href = '/trade?_=' + Date.now();
                    return;
                }
            }
        } catch(_) { /* 旧进程已下线但新进程未就绪，继续等 */ }
        if (attempts >= maxAttempts) {
            console.error('[重启] 超时 (' + maxAttempts + ' 次轮询)，请手动刷新');
            toast(t('sys.restart_timeout'));
            if (typeof onTimeout === 'function') onTimeout();
            return;
        }
        setTimeout(tick, 1000);
    };
    setTimeout(tick, 500);
}

// ── 系统更新 ──
async function doTradeUpdate(e) {
    // 用 currentTarget 或回退到事件对象，再不行直接查 DOM
    const btn = (e && (e.currentTarget || e.target)) || document.querySelector('#system-update-btn');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = t('sys.updating');
    toast(t('sys.restart_toast').replace('Restarting','Updating'));
    var updateFailed = false;
    var restartScheduled = false;
    try {
        const resp = await api('POST', '/api/trade/system/update');
        if (!resp) {
            updateFailed = true;
        } else if (resp.ok) {
            restartScheduled = !!resp.restart_scheduled;
            if (restartScheduled) {
                toast(t('sys.update_done_restart'));
            } else {
                toast(t('sys.update_done'));
            }
        } else if (resp.error || (resp.errors && resp.errors.length)) {
            const errMsg = resp.error || resp.errors.join('; ');
            toast(t('sys.update_fail') + errMsg);
            updateFailed = true;
        } else {
            toast(t('sys.update_unknown'));
            updateFailed = true;
        }
    } catch(e) {
        toast(t('sys.update_network'));
        updateFailed = true;
    }
    if (updateFailed || !restartScheduled) {
        btn.disabled = false;
        btn.textContent = t('footer.update');
        return;
    }
    // 存入标记，页面 reload 后检测并显示 toast
    try { sessionStorage.setItem('_trade_upgrade_done', '1'); } catch(_) {}
    _waitForRestartAndReload(() => {
        btn.disabled = false;
        btn.textContent = t('footer.update');
    });
}

// ── 数据备份 ──
async function doRestartTrade(e) {
    const btn = (e && (e.currentTarget || e.target)) || document.querySelector('#system-restart-btn');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = t('sys.restarting');
    toast(t('sys.restart_toast'));
    try {
        const resp = await api('POST', '/api/trade/system/restart');
        if (resp && resp.ok) {
            toast(t('sys.restart_ok'));
        } else {
            toast(t('sys.restart_fail') + (resp?.error || ''));
        }
    } catch(e) {
        toast(t('sys.restart_wait'));
    }
    _waitForRestartAndReload(() => {
        btn.disabled = false;
        btn.textContent = t('footer.restart');
    });
}

// ── Skills 帮助 ──
const _ALL_SKILLS = [
    {g:"客户开发",items:[
        {n:"b2b-osint",d:"客户背景调查（6 层检测：WHOIS/邮箱/制裁/技术栈/LinkedIn/评分）",t:"背调、查公司、查域名、查邮箱、due diligence"},
        {n:"b2b-email-intel",d:"邮箱情报 — 120+ 平台检测邮箱注册状态",t:"查邮箱、邮箱注册、邮箱背调、email lookup"},
        {n:"b2b-lead-generation",d:"多通道客户搜索与开发（Google Maps/LinkedIn/Facebook）",t:"找客户、开发客户、lead generation、cold email"},
        {n:"b2b-customer-finder",d:"傻瓜式客户开发向导 — 三问启动 + 自动搜索 + 开发信生成",t:"怎么找客户、客户开发向导、customer finder、找客户"},
        {n:"b2b-cold-outreach",d:"B2B 冷 outreach 邮件撰写（开发信/推广信/跟进信）",t:"开发信、写推广信、cold email、outreach"},
        {n:"b2b-email-imitation",d:"开发信仿写与再创作 — 分析优秀邮件样本，学结构学风格",t:"仿写开发信、按照样本、模仿邮件、email imitation"},
        {n:"b2b-buyer-persona",d:"买家画像与角色分层 — 按角色定制 FAB 价值主张",t:"买家画像、按角色写、给采购写、buyer persona"},
        {n:"auto-trade-customer-development",d:"全自动客户开发流水线 — 搜索→背调→评分→写信→发送",t:"全自动客户开发、一键开发、auto customer dev"},
    ]},{g:"内容营销",items:[
        {n:"b2b-social-media",d:"社媒营销（Facebook/Instagram/TikTok/YouTube）",t:"社媒、Facebook、TikTok、内容日历、social media"},
        {n:"b2b-linkedin-marketing",d:"LinkedIn 营销策略与内容（Profile/帖子/InMail）",t:"LinkedIn、领英、linkedin marketing、InMail"},
        {n:"b2b-kol-imitation",d:"LinkedIn/社媒 KOL 风格模仿 — 分析风格应用到自家品牌",t:"模仿风格、学大V、KOL imitation、imitate influencer"},
        {n:"b2b-reddit-engagement",d:"Reddit 社区互动 — 通过专业评论建立信任引流",t:"Reddit、社区评论、reddit comment、专业评论"},
        {n:"b2b-seo-aeo",d:"SEO+AEO 文章生成 — 针对 Google + AI 搜索优化",t:"SEO文章、AEO文章、搜索引擎优化、seo article"},
        {n:"b2b-short-video",d:"外贸 B2B 短视频脚本生成（TikTok/Shorts/Reels）",t:"短视频、视频脚本、TikTok脚本、short video"},
        {n:"b2b-market-analysis",d:"市场分析作战地图 — 认证/关税/关键词/3 秒 Hook",t:"市场分析、目标市场、作战地图、market analysis"},
        {n:"b2b-daily-automation",d:"定时任务（早安简报/日报/周报/定时发布）",t:"每日任务、定时任务、早安简报、cron、日报"},
    ]},{g:"文档管理",items:[
        {n:"b2b-document",d:"本地文档分析与提取（PDF/Word/Excel 等）",t:"分析文档、读报价、看合同、analyze document"},
        {n:"b2b-doc-generation",d:"生成报价/合同/提案/PPT（DOCX/XLSX/PPTX）",t:"生成报价单、生成合同、做 PPT、generate doc"},
        {n:"b2b-tech-drawing",d:"工程图纸分析（实验性）— 从 PDF 图纸提取材料/尺寸/公差",t:"图纸、工程图、铸件图、技术图纸、blueprint"},
        {n:"b2b-data-directory",d:"数据目录结构管理与初始化",t:"数据目录、数据结构、我的数据存在哪"},
    ]},{g:"平台与数据",items:[
        {n:"b2b-platform",d:"B2B 平台店铺诊断优化（阿里/MIC/独立站）",t:"平台诊断、阿里国际站、关键词优化、店铺诊断"},
        {n:"b2b-customs-data",d:"海关数据分析找采购商与市场趋势",t:"海关数据、进出口记录、找买家、customs data"},
    ]},{g:"客户与销售",items:[
        {n:"b2b-customer-intel",d:"单一客户深度画像 — 15 维度全方位情报档案",t:"客户画像、深度画像、送礼建议、回扣、了解客户"},
        {n:"b2b-customer-mgmt",d:"客户档案与分级管理（A/B/C 级、订单跟踪）",t:"客户管理、客户档案、客户分级、CRM"},
        {n:"b2b-sales-pipeline",d:"销售管线策略 — 30 天跟进表 + KPI 追踪 + 健康度看板",t:"销售推进、跟进计划、怎么跟进、sales pipeline"},
        {n:"b2b-inquiry-training",d:"询盘回复与 Top Sales 训练 — 双AI对抗训练法",t:"询盘训练、回复练习、模拟买家、反对意见"},
        {n:"b2b-exhibition",d:"展会全流程管理 — 展前邀约、展中跟进、展后转化",t:"展会、参展、广交会、trade show"},
        {n:"b2b-product-description",d:"产品描述生成器 — FAB 方法生成产品卖点与销售资料",t:"产品描述、产品文案、Sales Kit、product description"},
        {n:"b2b-trade-ops",d:"外贸履约与售后沟通（催款/索赔/展会/验厂/物流/售后）",t:"催款、索赔、展会、验厂、节日问候、物流"},
        {n:"b2b-inquiry-meeting",d:"询盘分析会主持 — 周度复盘/逐人点评/重点询盘/跟进行动表",t:"询盘分析会、询盘复盘、周会、业务员复盘"},
        {n:"b2b-sales-playbook",d:"销冠经验封装器 — SOP/话术库/新人路线/避坑清单/钩子武器库",t:"销冠经验、销售SOP、话术库、新人培训"},
        {n:"b2b-guarantee-proposal",d:"商业提案生成器 — 三档方案/ROI分析/实施路线图",t:"商业提案、战略建议书、ROI分析、方案建议书"},
    ]},{g:"合规与支持",items:[
        {n:"b2b-trade-compliance",d:"外贸合规检查 — 文化禁忌/缩写/Incoterms/翻译二审/投标",t:"文化禁忌、Incoterms、翻译二审、Amazon上架检查"},
        {n:"b2b-onboarding",d:"新公司全套部署方案（公司介绍/产品/营销/竞品分析）",t:"新公司、部署、全套方案、怎么开始、首次设置"},
        {n:"b2b-skill-generator",d:"根据需求描述自动创建新的 B2B Skill",t:"生成 skill、创建技能、create skill、new skill"},
        {n:"b2b-six-thinking-hats",d:"六顶思考帽决策教练 — 系统化分析复杂外贸决策",t:"决策分析、思考帽、利弊分析、decision making"},
        {n:"chat-memory",d:"历史对话查询（按今天/本周/本月/全部检索）",t:"之前说过、上周聊的、历史记录、chat history"},
        {n:"auto-smtp-email",d:"[已禁用] 点此了解设计理念",t:"【此技能已禁用】发邮件、群发、SMTP 发送"},
    ]},
];

function showUpgradeHelp() {
    showModal('upgrade-help-modal');
}

function showSkillsHelp() {
    var container = $('skills-help-content');
    if (!container) return;
    var html = '';
    for (var gi = 0; gi < _ALL_SKILLS.length; gi++) {
        var group = _ALL_SKILLS[gi];
        html += '<div style="margin-bottom:16px;"><h4 style="font-size:14px;font-weight:600;margin:0 0 6px;padding-bottom:4px;border-bottom:2px solid var(--primary);color:var(--primary);">' + esc(group.g) + '</h4>';
        for (var si = 0; si < group.items.length; si++) {
            var sk = group.items[si];
        var firstTrigger = sk.t.split('、')[0];
        html += '<div style="display:flex;align-items:flex-start;gap:8px;padding:6px 8px;border-radius:4px;cursor:pointer;" onmouseover="this.style.background=\'var(--bg-input)\'" onmouseout="this.style.background=\'\'" onclick="var t=this.querySelector(\'code\').textContent;navigator.clipboard.writeText(\'' + esc(firstTrigger) + '\');toast(t(\'skills.copied\')+\'' + esc(firstTrigger) + '\')" title="' + (currentLang==='en'?'Click to copy prompt':'点击复制提示词') + '">';
            html += '<code style="font-size:12px;white-space:nowrap;background:var(--bg-muted);padding:1px 6px;border-radius:3px;min-width:130px;">' + esc(sk.n) + '</code>';
            html += '<span style="flex:1;font-size:12px;color:var(--text-secondary);">' + esc(sk.d) + '</span>';
            html += '<span style="font-size:11px;color:var(--text-muted);white-space:nowrap;">💬 ' + esc(sk.t.split('、').slice(0,2).join(' | ')) + '</span>';
            html += '</div>';
        }
        html += '</div>';
    }
    container.innerHTML = html;
    showModal('skills-help-modal');
}

// ── Skills 更新 ──
async function updateSkills(e) {
    const btn = (e && (e.currentTarget || e.target)) || document.querySelector('#skills-update-btn');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = t('sys.skills_updating');
    try {
        const resp = await api('POST', '/api/trade/skills/update');
        if (resp?.ok) {
            toast(t('sys.skills_ok'));
        } else if (resp) {
            toast(t('sys.skills_fail') + (resp.error || ''));
        }
    } catch(e) {
        toast(t('sys.skills_error') + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = t('footer.skills_update');
    }
}

// ═════════════════════ UI HELPERS ═════════════════════
function $(id) { return document.getElementById(id); }
function showModal(id) { $(id).classList.remove('hidden'); }
function hideModal(id) { $(id).classList.add('hidden'); }
function toast(msg) {
    const c = $('toast-container');
    const t = document.createElement('div'); t.className = 'toast'; t.textContent = msg;
    c.appendChild(t); setTimeout(() => t.remove(), 3000);
}
function esc(s) { const d = document.createElement('div'); d.textContent = s||''; return d.innerHTML; }

// 安全移除动态弹窗（跳过静态模版弹窗避免误删 HTML 中的 modal-backdrop 骨架）
const _STATIC_MODAL_IDS = new Set(['company-modal','customer-modal','library-modal','upgrade-help-modal','skills-help-modal']);
function _removeDynamicModals() {
    document.querySelectorAll('.modal-backdrop').forEach(function(e) {
        if (!_STATIC_MODAL_IDS.has(e.id)) e.remove();
    });
}

// ═════════════════════ NAVIGATION ═════════════════════
// 视图缓存：{ viewKey: { element, rendered, context } }
const viewCache = {};
// 当前活跃的 chat 容器（用于解决多视图 DOM 中相同 ID 元素的查找问题）
let currentChatContainer = null;

function navToView(view, chatCtx, chatName) {
    // 新手引导进行中时阻止导航
    if (!isOnboardingCompleted() && document.getElementById('onboarding-panel')) {
        toast(t('toast.complete_onboarding'));
        return;
    }
    // 未选择公司时，所有菜单点击都显示固定提示页
    if (!currentCompanyId) {
        renderNoCompanyPage();
        return;
    }

    currentView = view;
    if (chatCtx) { currentChatContext = chatCtx; currentChatName = chatName || ''; }
    saveState();

    // Update sidebar active
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    const activeItem = document.querySelector(`.nav-item[data-view="${view}"][data-chat-context="${chatCtx||''}"]`) ||
                       document.querySelector(`.nav-item[data-view="${view}"]`);
    if (activeItem) activeItem.classList.add('active');

    // 隐藏所有视图，并清除非缓存内容（如 empty state）
    const main = $('main-content');
    for (const key in viewCache) {
        viewCache[key].element.style.display = 'none';
    }
    // 移除 main 中不属于视图缓存的子元素（首次从 empty state 切换时）
    const cachedIds = new Set(Object.keys(viewCache).map(k => 'view-' + k));
    for (const child of Array.from(main.children)) {
        if (child.id === 'guidance-bar') continue;  // 不删除全局横幅
        if (!cachedIds.has(child.id)) {
            child.remove();
        }
    }

    // 构建缓存 key
    const cacheKey = view + (chatCtx ? '-' + chatCtx : '');

    if (!viewCache[cacheKey]) {
        // 首次渲染此视图：创建容器 div 并挂到 main
        const container = document.createElement('div');
        container.className = view === 'chat' ? 'chat-view' : 'panel-view';
        container.id = 'view-' + cacheKey;
        main.appendChild(container);
        viewCache[cacheKey] = { element: container, rendered: false };

        switch (view) {
            case 'chat':
                currentChatContainer = container;
                renderChatViewInto(container, chatCtx, chatName);
                break;
            case 'customers':
                renderCustomersViewInto(container);
                break;
            case 'tasks':
                renderTasksViewInto(container);
                break;
            case 'history':
                renderHistoryViewInto(container);
                break;
        }
        viewCache[cacheKey].rendered = true;
    }

    viewCache[cacheKey].element.style.display = 'flex';
    // 记录当前活跃的 chat 容器
    if (view === 'chat') {
        currentChatContainer = viewCache[cacheKey].element;
        // 切换到聊天视图时直接滚动到底部（最新消息）
        requestAnimationFrame(() => {
            const msg = currentChatContainer?.querySelector('#chat-messages');
            if (msg) msg.scrollTop = msg.scrollHeight;
        });
        // 绑定滚动监听——每次激活聊天视图都重新挂载浮标
        setTimeout(() => {
            const msg = currentChatContainer?.querySelector('#chat-messages');
            if (msg) _ensureScrollHint(msg);
        }, 300);
    }
}

// ═════════════════════ CHAT VIEW ═════════════════════
function renderChatViewInto(container, ctx, name) {
    const coName = currentCompanyId ? (companies.find(c => c.id === currentCompanyId)?.name || '') : '';

    container.innerHTML = `
        <div class="chat-topbar">
            <div style="display:flex;align-items:center;gap:8px;">
                <h2>${esc(name)}</h2>
                ${coName ? `<span class="company-badge" style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;background:rgba(59,130,246,0.08);color:var(--primary);border-radius:999px;font-size:12px;font-weight:500;">🏢 ${esc(coName)}</span>` : ''}
                <span class="chat-context-tag" id="chat-context-tag"></span>
            </div>
            <div class="chat-topbar-actions">
                ${ctx === 'docs' ? `
                <select id="chat-library-select" aria-label="选择文档库" onchange="onChatLibraryChange(this.value)" style="padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg-card);">
                    <option value="">${t('chat.library')}</option>
                </select>
                <button onclick="showAddLibraryModal()" title="${t('chat.lib.add')}" style="height:30px;width:30px;border-radius:var(--radius-sm);border:1px solid var(--border);background:var(--bg-card);cursor:pointer;font-size:16px;">+</button>` : ''}
                <button onclick="clearChat()">${t('chat.clr')}</button>
            </div>
        </div>
        <div class="chat-messages" id="chat-messages">
            <div class="empty-state" id="chat-empty">
                <div class="empty-icon">💬</div>
                <h2>${esc(name)}</h2>
                <p>${t('chat.ph.' + ctx)}</p>
            </div>
        </div>
        <div class="chat-input-area">
            <div class="chat-input-inner">
                <textarea id="msg-input" aria-label="输入消息" placeholder="${t('chat.ph.' + ctx)}" rows="1"
                    onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMsg();}"
                    oninput="this.style.height='24px';this.style.height=(this.scrollHeight>80?80:this.scrollHeight)+'px';"></textarea>
                <button onclick="sendMsg()" id="send-btn" title="发送">↑</button>
                <button id="stop-btn" class="hidden" title="停止">■</button>
            </div>
        </div>
        <div class="drop-overlay" id="drop-overlay"><div class="drop-overlay-inner">&#128193; ${currentLang==='en'?'Drop files to add':'释放以添加文件'}</div></div>`;

    if (ctx === 'docs') loadChatLibrarySelect();
    loadChatHistory();
    // 客户开发向导（lead 上下文 + 未完成 onboarding 时显示）
    if (ctx === 'lead' && !isOnboardingCompleted()) {
        setTimeout(function() { showWizardInLeadView(); }, 300);
    }
    // 每日简报视图：额外拉取一次 cron 状态（全局轮询已覆盖）
    if (ctx === 'daily') {
        _shownCronOutputs = new Set();
        loadCronStatus(false);
    }
}

// ═════════════════════ 全局 cron 轮询与工作台横幅 ═════════════════════
let _cronPollTimer = null;
let _shownCronOutputs = new Set();  // 已展示过的 cron 输出任务名

// 标准任务时间表（与后端 standard_tasks 对应）
const TASK_SCHEDULE = [
    {name:'早安简报', time:'09:00', until:'09:30', desc:'查看今日汇率、大宗商品行情、客户跟进提醒'},
    {name:'邮件处理与跟进', time:'09:00', until:'10:30', desc:'回复客户邮件，跟进待处理询盘'},
    {name:'精准加人 (LinkedIn)', time:'10:00', until:'11:30', desc:'在 LinkedIn 上搜索并添加目标客户'},
    {name:'评论互动与私信致谢', time:'11:30', until:'12:00', desc:'回复社媒评论，发送感谢私信'},
    {name:'客户开发', time:'13:30', until:'15:30', desc:'分析客户资料，生成开发信和跟进序列'},
    {name:'LinkedIn 内容发布', time:'15:30', until:'17:00', desc:'发布 LinkedIn 内容'},
    {name:'B2B 平台检查', time:'15:30', until:'17:00', desc:'检查阿里国际站/中国制造网新询盘和待跟进报价'},
    {name:'每日工作总结', time:'17:00', until:'17:30', desc:'填写当日工作成果和明日计划'},
];

function _parseTime(t) { const [h,m] = t.split(':').map(Number); return h*60+m; }

function _getCurrentTaskGuidance(currentTime) {
    const now = _parseTime(currentTime || new Date().toLocaleTimeString('zh-CN',{hour12:false}).slice(0,5));
    for (const task of TASK_SCHEDULE) {
        const start = _parseTime(task.time);
        const end = _parseTime(task.until);
        if (now >= start && now < end) return task;
    }
    return null;  // 休息时段
}

function _renderGuidanceBar(currentTimeStr, completed, pending) {
    const guidance = _getCurrentTaskGuidance(currentTimeStr);
    const doneCount = completed.length, totalPending = pending.length;

    let barHtml = `<div id="guidance-bar" style="flex-shrink:0;max-height:20vh;overflow-y:auto;background:var(--bg-card);border-bottom:1px solid var(--border);padding:6px 12px;line-height:1.4;font-size:12px;">`;

    // 当前任务行
    if (guidance) {
        barHtml += `<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">`;
        barHtml += `<span style="font-size:15px;">⏰</span>`;
        barHtml += `<span style="font-weight:600;font-size:13px;color:var(--primary);">${esc(guidance.name)}</span>`;
        barHtml += `<span style="font-size:13px;color:var(--text-secondary);">${guidance.desc}</span>`;
        barHtml += `</div>`;
    } else {
        barHtml += `<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">`;
        barHtml += `<span style="font-size:15px;">☕</span>`;
        barHtml += '<span style="font-size:13px;color:var(--text-secondary);">'+t('guide.rest')+' · '+esc(currentTimeStr)+'</span>';
        barHtml += `</div>`;
    }

    // 进度条
    const total = doneCount + totalPending;
    const pct = total > 0 ? Math.round(doneCount/total*100) : 0;
    barHtml += '<div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);margin-bottom:1px;"><span>'+t('guide.progress')+'</span><span>'+doneCount+'/'+total+'</span></div>';
    barHtml += `<div style="height:3px;background:var(--bg-main);border-radius:2px;overflow:hidden;margin-bottom:4px;"><div style="height:100%;width:${pct}%;background:var(--accent-green);border-radius:2px;transition:width 0.3s;"></div></div>`;

    // 今日所有定时任务列表（从 completed + pending 合并，按时间排序）
    const _stripEmoji = s => s.replace(/[\u{1F600}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{1F900}-\u{1F9FF}\u{200D}\u{FE0F}]/gu, '').trim();
    const all = [...completed, ...pending].sort((a, b) => {
        const ta = (a.time || '').split('-')[0], tb = (b.time || '').split('-')[0];
        return ta.localeCompare(tb);
    });
    const items = all.map(t => `<div style="font-size:11px;color:var(--text-muted);line-height:1.6;">${esc(t.time)} ${esc(_stripEmoji(t.name))}</div>`);
    barHtml += `<div>${items.join('')}</div>`;

    // 文档生成上下文：显示单证模板下载
    if (currentChatContext === 'docgen') {
        barHtml += `<div style="margin-top:4px;padding-top:4px;border-top:1px solid var(--border-light);font-size:11px;display:flex;gap:8px;align-items:center;">
            <span>📄</span>
            <a href="#" onclick="event.preventDefault();downloadManagementTables();" style="color:var(--primary);text-decoration:none;">下载单证模板（商业发票/装箱单/形式发票/报价单）</a>
        </div>`;
    }

    barHtml += `</div>`;
    return barHtml;
}

function startCronPolling() {
    stopCronPolling();
    _cronPollTimer = setInterval(() => {
        if (currentCompanyId) loadCronStatus(true);
    }, 30000);
}

function stopCronPolling() {
    if (_cronPollTimer) { clearInterval(_cronPollTimer); _cronPollTimer = null; }
}

// ── 版本更新检查 ──
let _versionPollTimer = null;

async function checkVersion() {
    // 关闭版本升级提醒：用户手上版本稳定就不强制升级
    try {
        const r = await fetch('/api/status?_=' + Date.now(), { cache: 'no-store' });
        if (!r.ok) return;
        const data = await r.json();
        console.log('Version check: current=' + data.version + ' latest=' + (data.latest_version || ''));
    } catch(e) { /* 静默 */ }
}

function startVersionCheck() {
    stopVersionCheck();
    checkVersion();
    _versionPollTimer = setInterval(checkVersion, 10 * 60 * 1000); // 每 10 分钟
}

function stopVersionCheck() {
    if (_versionPollTimer) { clearInterval(_versionPollTimer); _versionPollTimer = null; }
}

async function doUpdateSystem() {
    const btn = document.getElementById('update-banner');
    if (btn) btn.textContent = '更新中...';
    var restartScheduled = false;
    try {
        const resp = await api('POST', '/api/trade/system/update');
        if (resp?.ok) {
            restartScheduled = !!resp.restart_scheduled;
            toast(restartScheduled ? '✅ 系统更新完成！正在重启...' : '✅ 更新完成。请点击"🔄 重启"以应用新版本。');
        } else if (resp?.error || (resp?.errors && resp.errors.length)) {
            toast('⚠️ 更新失败');
        }
        // resp 为 null 时 api() 已 toast，不重复提示
    } catch(e) {
        // 升级请求路径上服务器有可能抢先重启，吞异常并继续走重启等待流程
        toast('🔄 服务正在重启，页面即将刷新...');
        restartScheduled = true;
    }
    if (!restartScheduled) {
        // 升级未触发重启（可能已是最新版本或更新失败），立即重新检查版本状态
        if (btn) { btn.remove(); }
        checkVersion();
        return;
    }
    // 后端 BackgroundTasks 已调度重启——等待 DOWN→UP 后强制刷新（清 cache + cache-bust）
    _waitForRestartAndReload(() => {
        if (btn) btn.textContent = '⬆️ 升级';
    });
}

async function loadCronStatus(isPoll = false) {
    if (!currentCompanyId) return;
    const data = await api('GET', '/api/trade/cron/today');
    if (!data) return;
    const {completed, pending, current_time} = data;

    // 更新全局顶部横幅
    const main = $('main-content');
    let bar = document.getElementById('guidance-bar');
    const barHtml = _renderGuidanceBar(current_time, completed, pending);
    if (bar) {
        bar.outerHTML = barHtml;
    } else {
        main.insertAdjacentHTML('afterbegin', barHtml);
    }

    // 在今日简报视图更新 cron 面板；在任意聊天视图追加 cron 输出
    const ct = currentChatContainer;
    if (!ct || currentView !== 'chat') return;
    const container = ct.querySelector('#chat-messages');
    if (!container) return;

    const isDailyView = currentChatContext === 'daily';

    // 只在今日简报视图更新 cron 面板
    if (isDailyView) {
        let panel = container.querySelector('.cron-panel');
        let panelHtml = `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">`;
        panelHtml += `<div style="font-weight:600;font-size:14px;">📋 今日任务清单 <span style="font-weight:400;color:var(--text-muted);font-size:12px;">${current_time}</span></div>`;
        panelHtml += `<div style="font-size:12px;color:${pending.length === 0 ? 'var(--accent-green)' : 'var(--accent)'};">${pending.length === 0 ? '✅ 全部完成' : '⏳ ' + pending.length + ' 项待处理'}</div>`;
        panelHtml += `</div>`;
        if (completed.length) {
            panelHtml += `<div style="font-size:12px;color:var(--accent-green);margin-bottom:6px;">已完成 (${completed.length})</div>`;
            for (const t of completed) {
                panelHtml += `<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:13px;"><span style="color:var(--accent-green);">✓</span><span style="font-weight:500;">${esc(t.name)}</span><span style="color:var(--text-muted);font-size:11px;">${t.time}</span></div>`;
            }
        }
        if (pending.length) {
            panelHtml += `<div style="font-size:12px;color:var(--text-secondary);margin:6px 0;">待处理 (${pending.length})</div>`;
            for (const t of pending) {
                panelHtml += `<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:13px;"><span style="color:${t.missed ? 'var(--accent-red)' : 'var(--text-muted)'};">${t.missed ? '⚠' : '○'}</span><span style="font-weight:500;color:${t.missed ? 'var(--accent-red)' : ''};">${esc(t.name)}</span><span style="color:var(--text-muted);font-size:11px;">${t.scheduled}</span>${t.missed ? '<span style="color:var(--accent-red);font-size:11px;">（已过时）</span>' : ''}</div>`;
            }
        }
        if (panel) {
            panel.innerHTML = panelHtml;
        } else {
            panel = document.createElement('div');
            panel.className = 'cron-panel';
            panel.style.cssText = 'background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;margin-bottom:12px;box-shadow:var(--shadow-sm);';
            panel.innerHTML = panelHtml;
            const emptyEl = container.querySelector('.empty-state');
            if (emptyEl) emptyEl.insertAdjacentElement('afterend', panel);
            else container.insertAdjacentElement('afterbegin', panel);
        }
    }

    // 增量追加已完成任务的 AI 输出（仅今日简报视图，避免干扰其他对话）
    if (isDailyView) {
        for (const t of completed) {
            if (!t.output || _shownCronOutputs.has(t.name)) continue;
            const msgDiv = document.createElement('div');
            msgDiv.className = 'message assistant msg-cron-output';
            // 截断 cron 输出中的冗余管理指令
            let cleanOutput = t.output || '';
            const truncIdx = cleanOutput.search(/管理命令参考|##?\s*管理命令|crontab\s*命令参考/i);
            if (truncIdx >= 0) cleanOutput = cleanOutput.substring(0, truncIdx).trimEnd();
            msgDiv.innerHTML = `<div class="bubble"><div class="bubble-meta"><span class="cron-badge" style="display:inline-block;padding:2px 8px;background:var(--primary);color:#fff;border-radius:999px;font-size:10px;margin-bottom:6px;">⏰ ${esc(t.name)} · ${esc(t.time)}</span></div><div class="cron-output-content">${DOMPurify.sanitize(marked.parse(cleanOutput))}</div></div>`;
            container.appendChild(msgDiv);
            _shownCronOutputs.add(t.name);
        }
        if (completed.length) {
            const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 120;
            if (nearBottom) container.scrollTop = container.scrollHeight;
        }
    }
}

// ── 滚动到底部浮标（用户不在底部时始终显示）─────────

let _lastHintContainer = null;

function _ensureScrollHint(container) {
    // 同一个容器不重复绑定 scroll 监听
    if (container === _lastHintContainer) return;
    _lastHintContainer = container;
    container.style.position = 'relative';

    // 创建浮标（全局唯一，跟随活跃容器）
    const _getHint = () => {
        let h = document.getElementById('scroll-hint');
        if (!h) {
            h = document.createElement('div');
            h.id = 'scroll-hint';
            h.title = '回到底部';
            h.innerHTML = '▼';
            h.style.cssText = 'position:absolute;right:16px;bottom:80px;width:36px;height:36px;'
                + 'background:var(--primary);color:#fff;border-radius:50%;display:none;align-items:center;justify-content:center;'
                + 'cursor:pointer;font-size:16px;box-shadow:0 2px 8px rgba(0,0,0,0.2);z-index:10;transition:transform 0.15s;animation:pulseHint 2s infinite;';
            h.onmouseenter = () => h.style.transform = 'scale(1.1)';
            h.onmouseleave = () => h.style.transform = 'scale(1)';
            h.onclick = () => {
                const ct = currentChatContainer;
                const msg = ct?.querySelector('#chat-messages');
                if (msg) msg.scrollTop = msg.scrollHeight;
                h.style.display = 'none';
            };
        }
        return h;
    };

    const _update = () => {
        const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 120;
        const hint = _getHint();
        if (nearBottom) {
            hint.style.display = 'none';
        } else {
            if (hint.parentElement !== container) {
                // 切换视图时把浮标移到新容器
                if (hint.parentElement) hint.remove();
                container.appendChild(hint);
            }
            hint.style.display = 'flex';
        }
    };

    container.addEventListener('scroll', _update, { passive: true });
    _update();
}

function onChatLibraryChange(libId) {
    currentLibraryId = libId ? parseInt(libId) : null;
    const ct = currentChatContainer;
    if (!ct) return;
    const tag = ct.querySelector('#chat-context-tag');
    if (libId) {
        const sel = ct.querySelector('#chat-library-select');
        tag.textContent = '📁 ' + (sel.options[sel.selectedIndex]?.text || '');
        tag.style.display = 'block';
    } else {
        tag.style.display = 'none';
    }
    loadChatHistory();
}

async function loadChatLibrarySelect() {
    if (!currentCompanyId) return;
    const ct = currentChatContainer;
    if (!ct) return;
    const data = await api('GET', '/api/trade/libraries');
    const sel = ct.querySelector('#chat-library-select');
    if (!sel) return;
    // 按名称去重（同名文档库只保留一个）
    const seen = new Set();
    const unique = (data||[]).filter(l => {
        if (seen.has(l.name)) return false;
        seen.add(l.name);
        return true;
    });
    sel.innerHTML = '<option value="">' + t('chat.library') + '</option>' +
        unique.map(l => `<option value="${l.id}">${esc(l.name)}</option>`).join('');
}

// ═════════════════════ DRAG & DROP / PASTE FILES ═════════════════════

function _formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

const _IMAGE_EXTENSIONS = new Set(['png','jpg','jpeg','gif','bmp','webp','svg','ico']);

function _isImageFile(name) {
    const dot = name.lastIndexOf('.');
    return dot > -1 && _IMAGE_EXTENSIONS.has(name.slice(dot + 1).toLowerCase());
}

let _pendingDropFiles = [];

async function _collectFilesFromDataTransfer(dt) {
    const files = [];
    const entries = [];
    // 先尝试 webkitGetAsEntry（支持递归目录）
    if (dt.items && dt.items.length) {
        for (const item of dt.items) {
            if (item.kind === 'file') {
                const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
                if (entry) { entries.push(entry); } else { files.push(item.getAsFile()); }
            }
        }
    }
    // 回退到直接取 files
    if (!entries.length && dt.files && dt.files.length) {
        for (const f of dt.files) files.push(f);
    }

    // 递归读取目录
    async function _readEntry(entry, prefix) {
        if (entry.isFile) {
            const f = await new Promise(r => entry.file(r));
            Object.defineProperty(f, '_relPath', { value: prefix + entry.name, writable: true });
            files.push(f);
        } else if (entry.isDirectory) {
            const reader = entry.createReader();
            // readEntries 每次最多返回 ~100 条，需循环读取直到空
            const allEntries = [];
            while (true) {
                const batch = await new Promise(r => reader.readEntries(r));
                if (!batch.length) break;
                allEntries.push(...batch);
            }
            for (const e of allEntries) await _readEntry(e, prefix + entry.name + '/');
        }
    }
    for (const e of entries) await _readEntry(e, '');
    return files;
}

// 公司工作目录下的 9 个子目录名 — 与 trade/company.py _WORK_DIR_CATEGORIES 同步
const _WORK_SUBDIRS = ['报价单','合同','客户资料','产品规格','发票','物流单据','认证资质','营销素材','海关数据'];

// 上传文件到后端指定子目录
async function _uploadToWorkDir(files, subdir) {
    const form = new FormData();
    form.append('subdir', subdir);
    for (const f of files) {
        form.append('files', f, f._relPath || f.name);
    }
    const opts = { method: 'POST', headers: {}, body: form };
    if (TOKEN) opts.headers['X-Hermes-Session-Token'] = TOKEN;
    if (currentCompanyId) opts.headers['X-Company-ID'] = String(currentCompanyId);
    const resp = await fetch('/api/trade/upload-files', opts);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `上传失败 (${resp.status})`);
    }
    return await resp.json();
}

function _showDropModal(files) {
    _removeDynamicModals();
    _pendingDropFiles = files;

    const totalSize = files.reduce((s, f) => s + f.size, 0);
    const fileListHtml = files.slice(0, 20).map(f =>
        `<div class="file-item">${esc(f._relPath || f.name)} <span style="color:var(--text-muted)">${_formatBytes(f.size)}</span></div>`
    ).join('') + (files.length > 20 ? `<div class="file-item" style="color:var(--text-muted)">... 还有 ${files.length - 20} 个文件</div>` : '');

    const subdirOpts = _WORK_SUBDIRS.map(d => `<option value="${d}">${d}</option>`).join('');

    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.id = 'drop-file-modal';
    backdrop.onclick = function(e) { if (e.target === backdrop) backdrop.remove(); };
    backdrop.innerHTML = `
    <div class="modal" style="max-width:440px;width:95%;" onclick="event.stopPropagation()">
        <h3 style="margin:0 0 4px;">拖入 ${files.length} 个文件 (${_formatBytes(totalSize)})</h3>
        <div class="drop-file-list">${fileListHtml}</div>
        <div style="margin:10px 0;">
            <label style="font-size:13px;color:var(--text-muted);">存入工作目录：</label>
            <select id="drop-subdir-select" style="width:100%;padding:8px;border-radius:6px;border:1px solid var(--border);font-size:14px;margin-top:4px;">${subdirOpts}</select>
        </div>
        <div style="display:flex;gap:8px;">
            <button class="btn btn-primary" id="drop-confirm-btn" style="flex:1;">确认导入</button>
            <button class="btn" onclick="this.closest('.modal-backdrop').remove()">取消</button>
        </div>
    </div>`;
    document.body.appendChild(backdrop);

    backdrop.querySelector('#drop-confirm-btn').onclick = async function() {
        const subdir = backdrop.querySelector('#drop-subdir-select').value;
        const btn = backdrop.querySelector('#drop-confirm-btn');
        btn.disabled = true; btn.textContent = t('import.importing');
        try {
            const result = await _uploadToWorkDir(_pendingDropFiles, subdir);
            toast(t('toast.imported', {n: result.uploaded, dir: subdir}));
            const input = document.getElementById('msg-input');
            if (input) {
                // 检查是否有图片文件，提示 Agent 使用 vision 或 OCR
                const hasImages = _pendingDropFiles.some(f => _isImageFile(f._relPath || f.name));
                let hint = `[已导入 ${result.uploaded} 个文件到「${result.target_path}」，请递归读取该目录下的所有文件并分析`;
                if (hasImages) {
                    hint += `。图片文件请优先使用 vision 工具识别文字内容；如无 vision 能力，执行 tesseract <图片路径> stdout -l chi_sim+eng 进行 OCR 识别`;
                }
                hint += ']\n\n';
                input.value = hint + input.value;
                input.focus();
            }
            backdrop.remove();
        } catch (e) {
            toast(t('toast.import_fail') + ': ' + e.message);
            btn.disabled = false; btn.textContent = t('import.confirm');
        }
    };
}

function setupDropZone() {
    const overlay = document.getElementById('drop-overlay');
    let _dragCounter = 0;

    function handleDragOver(e) {
        e.preventDefault(); e.stopPropagation();
    }

    function handleDragEnter(e) {
        e.preventDefault(); e.stopPropagation();
        _dragCounter++;
        if (overlay) overlay.classList.add('show');
    }

    function handleDragLeave(e) {
        e.preventDefault(); e.stopPropagation();
        _dragCounter--;
        if (_dragCounter <= 0) { _dragCounter = 0; if (overlay) overlay.classList.remove('show'); }
    }

    async function handleDrop(e) {
        e.preventDefault(); e.stopPropagation();
        _dragCounter = 0;
        if (overlay) overlay.classList.remove('show');
        // 不拦截拖到已有弹窗上的文件（如用户在库弹窗上误拖）
        if (e.target.closest('.modal-backdrop')) return;
        const dt = e.dataTransfer;
        if (!dt || !dt.files.length) return;
        const files = await _collectFilesFromDataTransfer(dt);
        if (!files.length) return;
        _showDropModal(files);
    }

    document.body.addEventListener('dragover', handleDragOver, false);
    document.body.addEventListener('dragenter', handleDragEnter, false);
    document.body.addEventListener('dragleave', handleDragLeave, false);
    document.body.addEventListener('drop', handleDrop, false);

    document.addEventListener('paste', async function(e) {
        if (!e.clipboardData || !e.clipboardData.files.length) return;
        if (e.target.tagName === 'TEXTAREA' && e.target.id === 'msg-input') {
            e.preventDefault();
            const files = await _collectFilesFromDataTransfer(e.clipboardData);
            if (!files.length) return;
            _showDropModal(files);
        }
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupDropZone);
} else {
    setupDropZone();
}

function showAddLibraryModal() {
    ['lib-name','lib-path','lib-desc'].forEach(id => $(id).value = '');
    showModal('library-modal');
}

async function createLibrary() {
    const name = $('lib-name').value.trim();
    const path = $('lib-path').value.trim();
    if (!name || !path) { toast(t('toast.input_required')); return; }
    const desc = $('lib-desc').value.trim();
    const r = await api('POST', '/api/trade/libraries', {name, root_path: path, description: desc});
    if (r?.id) {
        toast(t('toast.lib_added', {name: name}));
        hideModal('library-modal');
        loadChatLibrarySelect();
    } else {
        toast(r?.detail || t('toast.lib_add_fail'));
    }
}

async function clearChat() {
    const ct = currentChatContainer;
    if (!ct) return;
    ct.querySelector('#chat-messages').innerHTML = `<div class="empty-state"><div class="empty-icon">💬</div><h2>${esc(currentChatName)}</h2></div>`;
}

// ═════════════════════ CHAT MESSAGES ═════════════════════
function addMsg(role, content, files, save, convId) {
    const ct = currentChatContainer;
    if (!ct) return;
    const container = ct.querySelector('#chat-messages');
    // Remove empty state
    const emptyEl = container.querySelector('.empty-state');
    if (emptyEl) emptyEl.remove();

    const div = document.createElement('div');
    div.className = `message ${role}`;
    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.textContent = role === 'user' ? '👤' : '🤖';
    const body = document.createElement('div');
    body.className = 'msg-body';
    const raw = marked.parse(content || '');
    body.innerHTML = DOMPurify.sanitize(raw, {
        ALLOWED_TAGS: ['p','br','strong','em','b','i','ul','ol','li','h1','h2','h3','h4','h5','h6',
            'blockquote','code','pre','a','table','thead','tbody','tr','th','td','hr','span','div','img'],
        ALLOWED_ATTR: ['href','target','class','id','style','src','alt','width','height'],
    });
    if (files && files.length) {
        const s = document.createElement('div'); s.className = 'sources';
        s.innerHTML = '<div class="sources-title">📄 '+(currentLang==='en'?'References':'参考文件')+'</div>' + files.map(f => '<div>📎 '+esc(f.file||f)+'</div>').join('');
        body.appendChild(s);
    }
    div.appendChild(avatar); div.appendChild(body);

    // AI 回复右侧加「📋 复制」按钮，点击写入剪贴板
    if (role === 'assistant' && content) {
        const copyBtn = document.createElement('button');
        copyBtn.textContent = '📋';
        copyBtn.title = currentLang==='en'?'Copy to clipboard':'复制到剪贴板';
        copyBtn.style.cssText = 'position:absolute;top:6px;right:8px;background:none;border:1px solid #D1D5DB;border-radius:4px;padding:2px 6px;font-size:12px;cursor:pointer;color:#9CA3AF;opacity:0.5;transition:opacity 0.15s;';
        copyBtn.onmouseenter = function() { this.style.opacity = '1'; };
        copyBtn.onmouseleave = function() { this.style.opacity = '0.5'; };
        copyBtn.onclick = function(e) {
            e.stopPropagation();
            navigator.clipboard.writeText(content).then(function() {
                copyBtn.textContent = '✅'; setTimeout(function() { copyBtn.textContent = '📋'; }, 1500);
            }).catch(function() {
                copyBtn.textContent = '❌'; setTimeout(function() { copyBtn.textContent = '📋'; }, 1500);
            });
        };
        div.style.position = 'relative';
        div.appendChild(copyBtn);

        // 评分按钮 — 仅传入 convId 时显示（避免全局变量竞态）
        const convIdForRating = convId;
        if (convIdForRating) {
            const ratingDiv = document.createElement('div');
            ratingDiv.className = 'msg-rating';
            ratingDiv.style.cssText = 'display:flex;align-items:center;gap:6px;margin-top:8px;padding-top:8px;border-top:1px solid var(--border-light);';
            ratingDiv.innerHTML = '<span style="font-size:11px;color:var(--text-muted);">'+(currentLang==='en'?'Rate this reply: ':'评价此回复：')+'</span>'
                + '<button class="rating-btn" data-r="👍" style="border:1px solid #D1D5DB;border-radius:4px;padding:2px 8px;font-size:13px;cursor:pointer;background:#fff;">👍</button>'
                + '<button class="rating-btn" data-r="👎" style="border:1px solid #D1D5DB;border-radius:4px;padding:2px 8px;font-size:13px;cursor:pointer;background:#fff;">👎</button>';
            body.appendChild(ratingDiv);

            ratingDiv.querySelectorAll('.rating-btn').forEach(function(btn) {
                btn.addEventListener('click', async function(e) {
                    e.stopPropagation();
                    var rVal = this.dataset.r === '👍' ? 4 : 2;
                    await api('POST', '/api/trade/conversations/' + convIdForRating + '/rate', { rating: rVal, feedback: '' });
                    ratingDiv.innerHTML = '<span style="font-size:11px;color:var(--accent-green);">✅ '+(currentLang==='en'?'Thanks for feedback':'感谢反馈')+'</span>';
                });
            });
        }
    }

    container.appendChild(div);
    // 只在用户发消息或新 AI 回复流式到达时自动滚到底部
    // 历史加载和手动浏览不强制滚动
}

async function loadChatHistory() {
    if (!currentCompanyId) return;
    const ct = currentChatContainer;
    if (!ct) return;
    // 按 context 过滤，避免不同主题的对话混在一起
    const ctx = encodeURIComponent(currentChatContext || '');
    const params = currentLibraryId
        ? `?library_id=${currentLibraryId}&limit=30`
        : `?context=${ctx}&limit=30`;
    const data = await api('GET', `/api/trade/conversations${params}`);
    if (!data || !data.length) return;
    const container = ct.querySelector('#chat-messages');
    if (!container) return;
    // Remove empty state
    const emptyEl = container.querySelector('.empty-state');
    if (emptyEl) emptyEl.remove();

    container.innerHTML = '';
    data.reverse().forEach(c => {
        let filesRead = [];
        try { filesRead = c.files_read ? JSON.parse(c.files_read) : []; } catch(e) { filesRead = []; }
        if (c.query) addMsg('user', c.query, filesRead, false);
        if (c.response) addMsg('assistant', c.response, null, false);
    });
    // 加载历史后直接滚动到底部（最新消息）
    container.scrollTop = container.scrollHeight;
}

// ═════════════════════ SSE STREAMING ═════════════════════
const TOOL_NAMES = {
    read_file:'📄 读取文件',list_files:'📂 列出文件',file_extract:'📋 提取文档',
    web_search:'🌐 搜索',web_fetch:'📥 抓取',memory_recall:'🧠 回忆',
    memory_retain:'💾 保存',execute_code:'💻 代码',terminal:'🖥️ 终端',
    delegate_task:'🤖 委派',vision:'👁️ 图像',skill_load:'📦 技能',
};
function fmtTool(name) { return TOOL_NAMES[name] || `🔧 ${name.replace(/_/g,' ')}`; }
function fmtArg(v) { return typeof v==='string' ? (v.length>80?v.slice(0,77)+'...':v) : JSON.stringify(v).slice(0,80); }

async function sendMsg() {
    if (!currentCompanyId) { toast('请先选择公司'); return; }
    const ct = currentChatContainer;
    if (!ct) { toast('请先点击一个聊天入口'); return; }
    const input = ct.querySelector('#msg-input');
    const query = input.value.trim();
    if (!query) return;

    // 本地触发：显示工作清单 → 拉取 cron 状态，不调 Agent
    if (query === '显示工作清单' || query === '工作清单' || query === '今日任务') {
        addMsg('user', query, null);
        input.value = '';
        input.style.height = '24px';  // 复位输入框高度
        await loadCronStatus();
        return;
    }

    addMsg('user', query, null);
    input.value = '';
    input.style.height = '24px';  // 复位输入框高度
    const sendBtn = ct.querySelector('#send-btn');
    if (sendBtn) sendBtn.disabled = true;

    // 用户可主动取消 SSE 流（替代原硬性 10 分钟超时）
    // 网站诊断等复杂 skill 可能需要 >10 分钟，依赖 SSE 心跳保活即可
    const streamCtl = new AbortController();
    const stopBtn = ct.querySelector('#stop-btn');
    if (stopBtn) {
        stopBtn.classList.remove('hidden');
        stopBtn.onclick = () => streamCtl.abort();
    }
    // 计时器：显示已用时，让用户知道仍在工作
    const elapsedTimer = setInterval(() => {
        const sec = Math.floor((Date.now() - startMs) / 1000);
        const m = Math.floor(sec / 60), s = sec % 60;
        const tEl = progDiv.querySelector('.elapsed');
        if (tEl) tEl.textContent = `⏱ ${m}:${s.toString().padStart(2,'0')}`;
    }, 1000);
    const startMs = Date.now();

    const container = ct.querySelector('#chat-messages');
    const progDiv = document.createElement('div');
    progDiv.className = 'message assistant';
    const pid = 'prog-' + Date.now();
    progDiv.id = pid;
    progDiv.innerHTML = '<div class="msg-avatar">🤖</div><div class="msg-body"><div class="thinking-msg">💭 '+t('misc.thinking')+'</div><div class="elapsed" style="font-size:11px;color:var(--text-muted);margin-top:4px;"></div></div>';
    container.appendChild(progDiv);
    container.scrollTop = container.scrollHeight;

    const toolEls = {};
    let progressDiv = null;
    let responseText = '';
    let responseConvId = null;
    _currentConvId = null;

    function ensureProgress() {
        if (!progressDiv) { progressDiv = document.createElement('div'); progressDiv.className = 'tool-progress'; progDiv.appendChild(progressDiv); }
        return progressDiv;
    }
    function addToolItem(tcId, name, status, detail) {
        const div = ensureProgress();
        const el = document.createElement('div');
        el.className = `tool-item ${status}`; el.id = `tool-${tcId}`;
        // 安全构建 DOM：textContent 防止工具参数中的 HTML 注入
        const icon = document.createElement('span');
        icon.className = 'tool-icon';
        icon.textContent = status === 'running' ? '◌' : status === 'done' ? '✓' : '✗';
        const body = document.createElement('div');
        body.className = 'tool-body';
        const nameEl = document.createElement('div');
        nameEl.className = 'tool-name';
        nameEl.textContent = fmtTool(name);
        const detailEl = document.createElement('div');
        detailEl.className = 'tool-detail';
        detailEl.textContent = detail || '';
        body.appendChild(nameEl);
        body.appendChild(detailEl);
        el.appendChild(icon);
        el.appendChild(body);
        div.appendChild(el); container.scrollTop = container.scrollHeight;
        toolEls[tcId] = el;
    }
    function updateTool(tcId, status, detail) {
        const el = toolEls[tcId]; if (!el) return;
        el.className = `tool-item ${status}`;
        el.querySelector('.tool-icon').textContent = status==='running'?'◌':status==='done'?'✓':'✗';
        if (detail) el.querySelector('.tool-detail').textContent = detail;
        container.scrollTop = container.scrollHeight;
    }

    try {
        const r = await fetch('/api/trade/chat/stream', {
            method:'POST',
            headers:{'Content-Type':'application/json','X-Hermes-Session-Token':TOKEN,'X-Company-ID':String(currentCompanyId)},
            body:JSON.stringify({library_id:currentLibraryId,customer_id:currentCustomerId,query,context:currentChatContext,language:currentLang}),
            signal:streamCtl.signal,
        });
        if (!r.ok) { progDiv.remove(); addMsg('assistant', `⚠️ 请求失败 (${r.status})`, null); sendBtn.disabled = false; return; }

        const reader = r.body.getReader(); const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const {done,value} = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, {stream:true});
            const lines = buffer.split('\n'); buffer = lines.pop()||'';
            let eventType='',dataStr='';
            for (const raw of lines) {
                const line = raw.replace(/\r$/,'');
                if (line.startsWith('event: ')) { eventType=line.slice(7).trim(); continue; }
                if (line.startsWith('data: ')) { dataStr=line.slice(6).trimStart(); continue; }
                if (line===''&&eventType&&dataStr) {
                    let data;
                    try { data = JSON.parse(dataStr); } catch(e) { eventType='';dataStr='';continue; }
                    switch(eventType) {
                    case 'tool_start': addToolItem(data.tool_call_id,data.name,'running',data.args?Object.entries(data.args).map(([k,v])=>`${k}=${fmtArg(v)}`).join(', '):''); break;
                    case 'tool_complete': updateTool(data.tool_call_id,'done',data.result_preview||'完成'); break;
                    case 'thinking':
                        if (!progDiv.querySelector('.thinking-msg')) { const t=document.createElement('div'); t.className='thinking-msg'; t.style.cssText='font-size:12px;color:var(--text-muted);padding:4px 0;'; t.textContent='💭 '+(data.message||'思考中...'); progDiv.appendChild(t); }
                        break;
                    case 'response': responseText = data.text||''; responseConvId = data.conversation_id || null; _currentConvId = data.conversation_id || null; break;
                    case 'error': progDiv.innerHTML=`<div class="msg-avatar" style="background:var(--accent-red);color:#fff;">⚠</div><div class="msg-body" style="color:var(--accent-red);">${esc(data.message)}</div>`; sendBtn.disabled = false; return;
                    }
                    eventType='';dataStr='';
                }
            }
        }
        progDiv.remove();
        if (responseText) addMsg('assistant', responseText, null, true, responseConvId);
        else addMsg('assistant', '⚠️ Agent 未返回有效回复。', null, true, null);
    } catch(e) {
        progDiv.remove();
        _currentConvId = null;
        if (e.name==='AbortError') addMsg('assistant','🛑 已停止生成。',null);
        else addMsg('assistant',`网络错误：${e.message}`,null);
    } finally {
        clearInterval(elapsedTimer);
        _currentConvId = null;
        if (stopBtn) { stopBtn.classList.add('hidden'); stopBtn.onclick = null; }
    }
    sendBtn.disabled = false;
}

// ═════════════════════ CUSTOMERS VIEW ═════════════════════
async function renderCustomersViewInto(container) {
    const coName = currentCompanyId ? (companies.find(c => c.id === currentCompanyId)?.name || '') : '';
    container.innerHTML = `
        <div class="panel-topbar">
            <h2>👥 ${t('customer.title')}${coName ? '<span style="margin-left:10px;padding:3px 10px;background:rgba(59,130,246,0.08);color:var(--primary);border-radius:999px;font-size:12px;font-weight:500;">🏢 '+esc(coName)+'</span>' : ''}</h2>
            <div class="panel-topbar-actions">
                <button class="btn btn-danger" id="batch-delete-btn" style="display:none;" onclick="batchDeleteCustomers()">🗑 ${currentLang==='en'?'Batch Delete':'批量删除'}</button>
                <input class="panel-search" id="cust-search" aria-label="搜索客户" placeholder="${t('customer.search')}" oninput="filterCustomers()">
                <select id="cust-tier-filter" aria-label="筛选客户等级" onchange="filterCustomers()" style="padding:7px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg-card);">
                    <option value="">${currentLang==='en'?'All Tiers':'全部等级'}</option><option value="A">A</option><option value="B">B</option><option value="C">C</option><option value="none">${t('cust.field.tier_none')}</option>
                </select>
                <select id="cust-sort" aria-label="客户排序方式" onchange="renderCustomersTable(allCustomers)" style="padding:7px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg-card);">
                    <option value="name">按名称排序</option><option value="updated_at">按最近跟进</option>
                </select>
                <button class="btn btn-primary" onclick="showCustomerEditModal()">+ 添加客户</button>
            </div>
        </div>
        <div class="panel-body">
            <div id="cust-import-banner" style="display:flex;align-items:center;gap:12px;padding:10px 14px;margin-bottom:12px;background:var(--bg-muted);border-radius:var(--radius-sm);border:1px dashed var(--border);">
                <span style="font-size:13px;">📋 批量导入客户？</span>
                <button class="btn-xs" onclick="downloadCsvTemplate()" style="text-decoration:none;">📥 下载 CSV 模板</button>
                <button class="btn-xs" onclick="downloadManagementTables()" style="text-decoration:none;margin-left:4px;">📊 下载管理表格</button>
                <span style="font-size:12px;color:var(--text-muted);">填好后上传 →</span>
                <input type="file" id="cust-bulk-file" accept=".csv" style="display:none;" onchange="bulkImportCustomers()">
                <button class="btn-xs primary" onclick="$('cust-bulk-file').click()">📤 上传导入</button>
            </div>
            <table class="data-table" id="customers-table">
                <thead><tr>
                    <th style="width:30px;"><input type="checkbox" id="select-all-customers" onchange="toggleSelectAllCustomers(this)" title="全选"></th>
                    <th>客户信息</th><th style="width:50px;">操作</th>
                </tr></thead>
                <tbody id="customers-tbody"></tbody>
            </table>
            <div id="customers-loading" class="loading-row hidden"><div class="spinner"></div>加载中...</div>
            <div id="customers-empty" class="empty-state hidden"><div class="empty-icon">👤</div><h2>暂无客户</h2><p>点击「添加客户」逐个添加，或下载模板批量导入</p></div>
        </div>`;
    await loadCustomersData();
}

let allCustomers = [];
async function loadCustomersData() {
    if (!currentCompanyId) return;
    $('customers-loading').classList.remove('hidden');
    allCustomers = await api('GET', '/api/trade/customers') || [];
    // Enrich with library associations
    for (let c of allCustomers) {
        const libs = await api('GET', `/api/trade/customers/${c.id}/libraries`) || [];
        c._libraries = libs;
    }
    $('customers-loading').classList.add('hidden');
    renderCustomersTable(allCustomers);
}

function _parseExtra1(c) { try { return JSON.parse(c.extra1||'{}'); } catch(e) { return {}; } }
function _parseExtra2(c) { try { return JSON.parse(c.extra2||'{}'); } catch(e) { return {}; } }

function renderCustomersTable(data) {
    const tbody = $('customers-tbody');
    const empty = $('customers-empty');
    if (!data.length) {
        tbody.innerHTML = '';
        empty.classList.remove('hidden');
        $('batch-delete-btn').style.display = 'none';
        return;
    }
    empty.classList.add('hidden');

    const sortBy = ($('cust-sort')?.value) || 'name';
    const sorted = [...data].sort((a, b) => {
        if (sortBy === 'updated_at') return (b.updated_at || '').localeCompare(a.updated_at || '');
        return (a.name || '').localeCompare(b.name || '');
    });

    tbody.innerHTML = sorted.map(c => {
        const ex1 = _parseExtra1(c);
        const ex2 = _parseExtra2(c);
        const tier = ex1['tier'] || '';
        const tierLabel = tier || '--';
        const tierColor = tier === 'A' ? 'var(--accent-green)' : tier === 'B' ? 'var(--accent)' : tier === 'C' ? 'var(--accent-red)' : 'var(--text-muted)';
        const buyerType = ex1['buyer_type'] || '';
        const mainCategory = ex1['main_category'] || '';
        const matchScore = ex1['match_score'] || 0;
        const country = ex1['country'] || '';
        const contact = c.contact || '';
        const title = ex2['title'] || '';
        const email = ex2['email'] || '';
        const phone = ex2['phone'] || ex2['whatsapp'] || '';
        const note = (c.note || '').slice(0, 40);
        const updated = (c.updated_at || c.created_at || '').slice(0, 10);
        const subLine = [title, mainCategory, country, email, phone].filter(Boolean).join(' · ');
        const matchStars = matchScore > 0 ? '★'.repeat(matchScore) + '☆'.repeat(5 - matchScore) : '';
        return `<tr style="cursor:pointer;" onclick="showCustomerDetail(${c.id})">
            <td style="width:30px;" onclick="event.stopPropagation()"><input type="checkbox" class="cust-checkbox" value="${c.id}" onchange="updateBatchDeleteBtn()"></td>
            <td style="padding:8px 10px;">
                <div style="font-weight:600;font-size:13px;color:var(--text-primary);">${esc(c.name)}${contact ? '<span style="font-weight:400;color:var(--text-muted);margin-left:6px;">' + esc(contact) + '</span>' : ''}</div>
                <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                    <span style="color:${tierColor};font-weight:600;">● ${tierLabel} 级</span>
                    ${buyerType ? '<span style="background:var(--bg-muted);padding:1px 6px;border-radius:3px;font-size:10px;">' + esc(buyerType) + '</span>' : ''}
                    ${matchStars ? '<span style="color:var(--accent);font-size:10px;">' + matchStars + '</span>' : ''}
                    ${subLine ? '<span>' + esc(subLine) + '</span>' : ''}
                    ${note ? '<span style="color:var(--text-muted);">📝 ' + esc(note) + '</span>' : ''}
                    <span style="color:var(--text-muted);margin-left:auto;font-size:10px;white-space:nowrap;">${esc(updated)}</span>
                </div>
            </td>
            <td style="width:50px;text-align:right;padding-right:8px;" onclick="event.stopPropagation()"><button class="btn-xs" onclick="showCustomerEditModal(${c.id})">编辑</button></td>
        </tr>`;
    }).join('');

    $('select-all-customers').checked = false;
    $('batch-delete-btn').style.display = 'none';
}

function toggleSelectAllCustomers(el) {
    document.querySelectorAll('.cust-checkbox').forEach(cb => cb.checked = el.checked);
    updateBatchDeleteBtn();
}

function updateBatchDeleteBtn() {
    const checked = document.querySelectorAll('.cust-checkbox:checked').length;
    $('batch-delete-btn').style.display = checked > 0 ? 'inline-flex' : 'none';
}

async function batchDeleteCustomers() {
    const checked = document.querySelectorAll('.cust-checkbox:checked');
    if (!checked.length) return;
    if (!confirm(`确定删除选中的 ${checked.length} 个客户？此操作不可恢复。`)) return;

    let deleted = 0;
    for (const cb of checked) {
        const r = await api('DELETE', `/api/trade/customers/${cb.value}`);
        if (r?.ok) deleted++;
    }
    toast(`已删除 ${deleted} 个客户`);
    await loadCustomersData();
    if (currentView === 'customers') renderCustomersTable(allCustomers);
}

function filterCustomers() {
    const search = ($('cust-search')?.value||'').toLowerCase();
    const tier = $('cust-tier-filter')?.value||'';
    let filtered = allCustomers;
    if (search) filtered = filtered.filter(c => (c.name||'').toLowerCase().includes(search) || (c.contact||'').toLowerCase().includes(search));
    if (tier) {
        filtered = filtered.filter(c => {
            const t = _parseExtra1(c)['tier'] || c.tier || '';
            if (tier==='none') return !t;
            return t === tier;
        });
    }
    renderCustomersTable(filtered);
}

// ── Customer Detail Slide Panel ────────────────────────────────
async function showCustomerDetail(cid) {
    closeCustomerDetail();  // 先关闭旧面板，防止重复 id
    const c = allCustomers.find(x => x.id === cid);
    if (!c) return;
    editingCustomerData = c;

    const extra1 = _parseExtra1(c);
    const extra2 = _parseExtra2(c);
    const tier = extra1['tier'] || '';
    const buyerType = extra1['buyer_type'] || '';
    const mainCategory = extra1['main_category'] || '';
    const matchScore = extra1['match_score'] || 0;
    const country = extra1['country'] || '';
    const linkedin = extra1['linkedin_url'] || '';
    const website = extra1['company_website'] || '';
    const title = extra2['title'] || '';
    const email = extra2['email'] || '';
    const phone = extra2['phone'] || '';
    const whatsapp = extra2['whatsapp'] || '';
    const backupEmail = extra2['backup_email'] || '';
    const followUpNote = extra2['follow_up_note'] || '';

    const libs = c._libraries || await (async () => {
        const result = await api('GET', `/api/trade/customers/${cid}/libraries`) || [];
        if (c._libraries === undefined) c._libraries = result;
        return result;
    })();
    if (c._libraries === undefined) c._libraries = libs;

    // 加载该客户关联文档库的最近对话（每个库 3 条）
    let recentConvs = [];
    for (const lib of libs.slice(0, 3)) {
        const libConvs = await api('GET', `/api/trade/conversations?library_id=${lib.id}&limit=3`) || [];
        recentConvs = recentConvs.concat(libConvs);
    }
    // 去重 + 按时间排序 + 取最近 5 条
    const seen = new Set();
    recentConvs = recentConvs
        .filter(c => { const k = c.id; if (seen.has(k)) return false; seen.add(k); return true; })
        .sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
        .slice(0, 5);

    // Backdrop
    const backdrop = document.createElement('div');
    backdrop.className = 'slide-panel-backdrop';
    backdrop.id = 'customer-detail-panel';
    backdrop.onclick = function(e) { if (e.target === backdrop) closeCustomerDetail(); };
    var scoreLabels = {1:currentLang==='en'?'Low':'低',3:currentLang==='en'?'Med':'中',5:currentLang==='en'?'High':'高'};
    var buyerTypes = currentLang==='en'
        ? ['Brand','Distributor','Agent','Installer','Maintenance','Competitor','Other']
        : ['品牌商','分销商','代理商','安装商','维保商','同行','其他'];
    backdrop.innerHTML = `
    <div class="slide-panel">
        <div class="slide-panel-header">
            <h3>👤 ${esc(c.name)}</h3>
            <button class="slide-panel-close" onclick="closeCustomerDetail()">×</button>
        </div>
        <div class="panel-section">
            <div class="panel-section-title">${t('customer.detail.basic')}</div>
            <div class="panel-field-row">
                <div class="panel-field"><label for="detail-name">${t('cust.field.name')}</label><input type="text" value="${esc(c.name)}" id="detail-name"></div>
                <div class="panel-field"><label for="detail-title">${t('cust.field.title')}</label><input type="text" value="${esc(title)}" id="detail-title"></div>
            </div>
            <div class="panel-field-row">
                <div class="panel-field"><label for="detail-tier">${t('cust.field.tier')}</label><select id="detail-tier">
                    <option value="" ${!tier?'selected':''}>${t('cust.field.tier_none')}</option>
                    <option value="A" ${tier==='A'?'selected':''}>A</option>
                    <option value="B" ${tier==='B'?'selected':''}>B</option>
                    <option value="C" ${tier==='C'?'selected':''}>C</option>
                </select></div>
                <div class="panel-field"><label for="detail-buyer-type">${t('cust.field.buyer')}</label><select id="detail-buyer-type">
                    <option value="" ${!buyerType?'selected':''}>${t('cust.field.buyer_none')}</option>
                    ${buyerTypes.map(t => '<option value="'+t+'" '+(buyerType===t?'selected':'')+'>'+t+'</option>').join('')}
                </select></div>
                <div class="panel-field"><label for="detail-country">${t('cust.field.country')}</label><input type="text" value="${esc(country)}" id="detail-country"></div>
            </div>
            <div class="panel-field-row">
                <div class="panel-field"><label for="detail-main-category">${t('cust.field.category')}</label><input type="text" value="${esc(mainCategory)}" id="detail-main-category"></div>
                <div class="panel-field"><label for="detail-match-score">${t('cust.field.score')}</label><select id="detail-match-score">
                    <option value="0" ${matchScore==0?'selected':''}>${t('cust.field.score_none')}</option>
                    ${[1,2,3,4,5].map(function(s){return '<option value="'+s+'" '+(matchScore==s?'selected':'')+'>'+s+(scoreLabels[s]?' - '+scoreLabels[s]:'')+'</option>';}).join('')}
                </select></div>
            </div>
            <div class="panel-field-row">
                <div class="panel-field"><label for="detail-email">${t('cust.field.email')}</label><input type="text" value="${esc(email)}" id="detail-email"></div>
                <div class="panel-field"><label for="detail-phone">${t('cust.field.phone')}</label><input type="text" value="${esc(phone)}" id="detail-phone"></div>
            </div>
            <div class="panel-field-row">
                <div class="panel-field"><label for="detail-whatsapp">WhatsApp</label><input type="text" value="${esc(whatsapp)}" id="detail-whatsapp"></div>
            </div>
            <div class="panel-field-row">
                <div class="panel-field"><label for="detail-linkedin">LinkedIn</label><input type="text" value="${esc(linkedin)}" id="detail-linkedin"></div>
                <div class="panel-field"><label for="detail-website">${t('cust.field.website')}</label><input type="text" value="${esc(website)}" id="detail-website"></div>
            </div>
            <div class="panel-field-row">
                <div class="panel-field"><label for="detail-backup-email">${t('cust.field.backup_email')}</label><input type="text" value="${esc(backupEmail)}" id="detail-backup-email"></div>
                <div class="panel-field"><label for="detail-contact">${t('cust.field.contact')}</label><input type="text" value="${esc(c.contact||'')}" id="detail-contact"></div>
            </div>
            <div class="panel-field"><label for="detail-note">${t('cust.field.note')}</label><textarea id="detail-note">${esc(c.note||'')}</textarea></div>
            <div class="panel-field"><label for="detail-follow-up-note">${t('cust.field.follow')}</label><textarea id="detail-follow-up-note">${esc(followUpNote)}</textarea></div>
            <button class="btn btn-primary" onclick="saveCustomerDetail(${c.id})" style="width:100%;">${t('customer.detail.save')}</button>
        </div>
        <div class="panel-section">
            <div class="panel-section-title">${t('customer.detail.libs')} (${libs.length})</div>
            <div class="panel-linked-libs" id="detail-libs">
                ${libs.map(l => `
                <div class="panel-linked-lib">
                    📄 ${esc(l.name)}
                    <span class="unlink-btn" onclick="unlinkCustomerLib(${c.id},${l.id})" title="${currentLang==='en'?'Unlink':'取消关联'}">×</span>
                </div>`).join('')}
            </div>
            <div style="margin-top:8px;display:flex;gap:6px;">
                <select id="detail-link-lib" aria-label="关联文档库" style="flex:1;padding:7px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;">
                    <option value="">${t('customer.detail.link_lib')}</option>
                </select>
                <button class="btn-xs primary" onclick="linkCustomerLib(${c.id})">${t('customer.detail.link_btn')}</button>
            </div>
        </div>
        <div class="panel-section">
            <div class="panel-section-title">${t('customer.detail.orders')} (<span id="detail-order-count">-</span>) <button class="btn-xs" style="margin-left:8px;" onclick="showOrderModal(${c.id})">${t('customer.detail.add_order')}</button></div>
            <div id="detail-orders"><div class="loading-row"><div class="spinner"></div>${t('misc.loading_orders')}</div></div>
        </div>
        <div class="panel-section">
            <div class="panel-section-title">${t('customer.detail.convs')} (${recentConvs.length})</div>
            <div id="detail-convs">
                ${recentConvs.length ? recentConvs.map(conv => `
                <div class="panel-conv-item" onclick="closeCustomerDetail();showConversationDetail(${conv.id})">
                    <div class="conv-time">${esc((conv.created_at||'').slice(0,16))}</div>
                    <div class="conv-query">${esc((conv.query||'').slice(0,80))}</div>
                </div>`).join('') : '<p style="color:var(--text-muted);font-size:12px;">'+t('customer.detail.no_convs')+'</p>'}
            </div>
        </div>
        <button class="btn btn-primary" style="width:100%;" data-chat-cust-id="${c.id}" data-chat-cust-name="${esc(c.name)}">${t('customer.detail.chat_btn')}</button>
    </div>`;
    document.body.appendChild(backdrop);

    // 绑定安全的事件监听（避免 onclick 中的 XSS 注入）
    backdrop.querySelector('[data-chat-cust-id]').addEventListener('click', function() {
        closeCustomerDetail();
        startChatWithCustomer(
            parseInt(this.getAttribute('data-chat-cust-id')),
            this.getAttribute('data-chat-cust-name')
        );
    });

    // Load library options for linking
    const allLibs = await api('GET', '/api/trade/libraries') || [];
    const linkedIds = libs.map(l=>l.id);
    const sel = $('detail-link-lib');
    if (sel) sel.innerHTML = '<option value="">' + t('customer.detail.link_lib') + '</option>' +
        allLibs.filter(l=>!linkedIds.includes(l.id)).map(l=>`<option value="${l.id}">${esc(l.name)}</option>`).join('');
    // 异步加载订单
    loadOrdersForCustomer(cid);
}

function closeCustomerDetail() {
    const panel = $('customer-detail-panel');
    if (panel) panel.remove();
}

async function saveCustomerDetail(cid) {
    const name = $('detail-name')?.value?.trim();
    const contact = $('detail-contact')?.value?.trim()||'';
    const note = $('detail-note')?.value?.trim()||'';
    const country = $('detail-country')?.value?.trim()||'';
    const tier = $('detail-tier')?.value||'';
    const buyerType = $('detail-buyer-type')?.value||'';
    const mainCategory = $('detail-main-category')?.value?.trim()||'';
    const matchScore = parseInt($('detail-match-score')?.value) || 0;
    const linkedin = $('detail-linkedin')?.value?.trim()||'';
    const title = $('detail-title')?.value?.trim()||'';
    const email = $('detail-email')?.value?.trim()||'';
    const phone = $('detail-phone')?.value?.trim()||'';
    const whatsapp = $('detail-whatsapp')?.value?.trim()||'';
    const website = $('detail-website')?.value?.trim()||'';
    const backupEmail = $('detail-backup-email')?.value?.trim()||'';
    const followUpNote = $('detail-follow-up-note')?.value?.trim()||'';

    await api('PUT', `/api/trade/customers/${cid}`, {name, contact, note, country, tier, linkedin_url: linkedin,
        title, email, phone, whatsapp, company_website: website, backup_email: backupEmail, buyer_type: buyerType, follow_up_note: followUpNote, main_category: mainCategory, match_score: matchScore});
    toast(t('toast.saved'));
    closeCustomerDetail();
    await loadCustomersData();
}

async function linkCustomerLib(cid) {
    const lid = $('detail-link-lib')?.value;
    if (!lid) { toast(t('toast.select_library')); return; }
    const r = await api('POST', `/api/trade/customers/${cid}/libraries/${lid}`);
    if (r && r.ok) { toast('已关联'); closeCustomerDetail(); await loadCustomersData(); showCustomerDetail(cid); }
    else toast(r?.detail||'关联失败');
}

async function unlinkCustomerLib(cid, lid) {
    const r = await api('DELETE', `/api/trade/customers/${cid}/libraries/${lid}`);
    if (r && r.ok) { toast('已取消关联'); closeCustomerDetail(); await loadCustomersData(); showCustomerDetail(cid); }
}

function startChatWithCustomer(cid, name) {
    currentCustomerId = cid;
    currentChatContext = 'lead';
    currentChatName = '客户: ' + name;
    saveState();
    navToView('chat', 'lead', '客户: ' + name);
}

// ── Order List / Modal ─────────────────────────────────────

async function loadOrdersForCustomer(cid) {
    const container = $('detail-orders');
    if (!container) return;
    try {
        const orders = await api('GET', `/api/trade/customers/${cid}/orders`) || [];
        $('detail-order-count').textContent = orders.length;
        if (!orders.length) {
            container.innerHTML = '<p style="color:var(--text-muted);font-size:12px;">'+t('cust.field.no_orders')+'</p>';
            return;
        }
        container.innerHTML = orders.map(o => {
            const stColor = o.status==='已下单'?'var(--accent-green)':o.status==='已出货'?'var(--primary)':o.status==='已完成'?'var(--text-muted)':'var(--accent)';
            return `<div style="padding:6px 0;border-bottom:1px solid var(--border-light);font-size:12px;cursor:pointer;" onclick="showOrderEditModal(${o.id})">
                <span style="color:${stColor};font-weight:500;">● ${esc(o.status)}</span>
                <b>${esc(o.product_name)}</b>
                ${o.quantity ? '<span style="color:var(--text-secondary);">'+esc(o.quantity)+(o.unit||'')+'</span>' : ''}
                ${o.total_amount ? '<span style="color:var(--accent);font-weight:500;"> '+esc(o.total_amount)+' '+esc(o.currency||'USD')+'</span>' : ''}
                ${o.order_no ? '<span style="color:var(--text-muted);margin-left:8px;">#'+esc(o.order_no)+'</span>' : ''}
            </div>`;
        }).join('');
    } catch(e) { container.innerHTML = '<p style="color:var(--accent-red);font-size:12px;">'+t('cust.field.order_fail')+'</p>'; }
}

function showOrderModal(cid) { showOrderEditModal(null, cid); }

function showOrderEditModal(oid, presetCid) {
    // 先清理旧的订单弹窗，防止重复 id
    const old = document.getElementById('order-modal-backdrop');
    if (old) old.remove();
    const isEdit = !!oid;
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.id = 'order-modal-backdrop';
    backdrop.onclick = e => { if (e.target===backdrop) backdrop.remove(); };
    var stLabels = [t('order.status_quoting'),t('order.status_ordered'),t('order.status_shipped'),t('order.status_done'),t('order.status_cancelled')];
    backdrop.innerHTML = '<div class="modal" style="max-width:520px;width:95%;" onclick="event.stopPropagation()">' +
        '<h3>' + (isEdit ? t('order.edit_title') : t('order.title')) + '</h3>' +
        '<input type="hidden" id="order-edit-id" value="'+(oid||'')+'">' +
        '<input type="hidden" id="order-cust-id" value="'+(presetCid||'')+'">' +
        '<div id="order-cust-row" style="display:'+(presetCid?'none':'block')+';">' +
            '<div class="form-group"><label for="order-cust-sel">'+t('order.cust_label')+'</label><select id="order-cust-sel"></select></div>' +
        '</div>' +
        '<div class="form-row">' +
            '<div class="form-group"><label for="order-product">'+t('order.product')+'</label><input type="text" id="order-product" placeholder="e.g. ADSS Cable"></div>' +
            '<div class="form-group"><label for="order-no">'+t('order.no')+'</label><input type="text" id="order-no" placeholder="PO-2026-001"></div>' +
        '</div>' +
        '<div class="form-row">' +
            '<div class="form-group"><label for="order-qty">'+t('order.qty')+'</label><input type="number" id="order-qty" placeholder="1000" step="any" min="0"></div>' +
            '<div class="form-group"><label for="order-unit">'+t('order.unit')+'</label><input type="text" id="order-unit" value="'+(currentLang==='en'?'set':'套')+'"></div>' +
        '</div>' +
        '<div class="form-row">' +
            '<div class="form-group"><label for="order-price">'+t('order.price')+'</label><input type="number" id="order-price" placeholder="0.35" step="any" min="0"></div>' +
            '<div class="form-group"><label for="order-currency">'+t('order.currency')+'</label><select id="order-currency"><option>USD</option><option>EUR</option><option>CNY</option></select></div>' +
        '</div>' +
        '<div class="form-row">' +
            '<div class="form-group"><label for="order-total">'+t('order.amount')+'</label><input type="number" id="order-total" placeholder="3500" step="any" min="0"></div>' +
            '<div class="form-group"><label for="order-status">'+t('order.status')+'</label><select id="order-status">'+stLabels.map(function(s){return '<option>'+s+'</option>';}).join('')+'</select></div>' +
        '</div>' +
        '<div class="form-row">' +
            '<div class="form-group"><label for="order-delivery">'+t('order.delivery')+'</label><input type="date" id="order-delivery"></div>' +
            '<div class="form-group"><label for="order-payment">'+t('order.payment')+'</label><input type="text" id="order-payment" placeholder="T/T 30/70"></div>' +
        '</div>' +
        '<div class="form-group"><label for="order-notes">'+t('order.notes')+'</label><textarea id="order-notes" style="min-height:50px;" placeholder="Notes"></textarea></div>' +
        '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">' +
            (isEdit?'<button class="btn btn-danger" onclick="deleteOrder('+oid+')">'+t('order.btn_delete')+'</button>':'') +
            '<button class="btn" onclick="this.closest(\'.modal-backdrop\').remove()">'+t('btn.cancel')+'</button>' +
            '<button class="btn btn-primary" onclick="saveOrder()">'+t('btn.save')+'</button>' +
        '</div>' +
    '</div>';
    document.body.appendChild(backdrop);

    if (isEdit) {
        api('GET', `/api/trade/orders/${oid}`).then(o => {
            if (!o) return;
            $('order-product').value = o.product_name||'';
            $('order-no').value = o.order_no||'';
            $('order-qty').value = o.quantity||'';
            $('order-unit').value = o.unit||'套';
            $('order-price').value = o.unit_price||'';
            $('order-currency').value = o.currency||'USD';
            $('order-total').value = o.total_amount||'';
            $('order-status').value = o.status||'报价中';
            $('order-delivery').value = (o.delivery_date||'').slice(0,10);
            $('order-payment').value = o.payment_terms||'';
            $('order-notes').value = o.notes||'';
        });
    }
    // 加载客户下拉
    if (!presetCid) {
        api('GET', '/api/trade/customers').then(list => {
            const sel = $('order-cust-sel');
            sel.innerHTML = '<option value="">'+t('order.cust_select')+'</option>' + (list||[]).map(c=>'<option value="'+c.id+'">'+esc(c.name)+'</option>').join('');
        });
    }
}

async function saveOrder() {
    const editId = $('order-edit-id').value;
    const custId = $('order-cust-id').value || $('order-cust-sel').value;
    const product = $('order-product').value.trim();
    if (!custId || !product) { toast(t('toast.cust_product_required')); return; }
    const body = {
        customer_id: parseInt(custId), product_name: product,
        order_no: $('order-no').value.trim(),
        quantity: parseFloat($('order-qty').value)||0,
        unit: $('order-unit').value.trim(),
        unit_price: parseFloat($('order-price').value)||0,
        currency: $('order-currency').value,
        total_amount: parseFloat($('order-total').value)||0,
        status: $('order-status').value,
        delivery_date: $('order-delivery').value,
        payment_terms: $('order-payment').value.trim(),
        notes: $('order-notes').value.trim(),
    };
    if (editId) {
        await api('PUT', `/api/trade/orders/${editId}`, body);
    } else {
        await api('POST', '/api/trade/orders', body);
    }
    document.querySelector('.modal-backdrop')?.remove();
    loadOrdersForCustomer(custId);
    toast(editId ? t('order.updated') : t('order.created'));
}

async function deleteOrder(oid) {
    if (!confirm(t('order.confirm_delete'))) return;
    await api('DELETE', `/api/trade/orders/${oid}`);
    document.querySelector('.modal-backdrop')?.remove();
    // 刷新当前打开的客户详情
    const custId = $('order-cust-id').value;
    if (custId) loadOrdersForCustomer(custId);
    toast(t('order.deleted'));
}

// ── Customer CRUD Modal ──────────────────────────────────────
function showCustomerEditModal(cid) {
    if (cid) {
        const c = allCustomers.find(x => x.id === cid);
        if (!c) return;
        const extra1 = _parseExtra1(c);
        const extra2 = _parseExtra2(c);
        $('customer-modal-title').textContent = '编辑客户';
        $('cust-edit-id').value = cid;
        $('cust-name').value = c.name||'';
        $('cust-title').value = extra2['title']||'';
        $('cust-country').value = extra1['country']||'';
        $('cust-email').value = extra2['email']||c.contact||'';
        $('cust-phone').value = extra2['phone']||'';
        $('cust-whatsapp').value = extra2['whatsapp']||'';
        $('cust-contact').value = c.contact||'';
        $('cust-linkedin').value = extra1['linkedin_url']||'';
        $('cust-website').value = extra1['company_website']||'';
        $('cust-tier').value = extra1['tier']||'';
        $('cust-buyer-type').value = extra1['buyer_type']||'';
        $('cust-main-category').value = extra1['main_category']||'';
        $('cust-match-score').value = extra1['match_score']||0;
        $('cust-backup-email').value = extra2['backup_email']||'';
        $('cust-follow-up-note').value = extra2['follow_up_note']||'';
        $('cust-note').value = c.note||'';
    } else {
        $('customer-modal-title').textContent = '添加客户';
        $('cust-edit-id').value = '';
        ['cust-name','cust-contact','cust-title','cust-country','cust-email','cust-phone','cust-whatsapp','cust-linkedin','cust-website','cust-tier','cust-buyer-type','cust-main-category','cust-match-score','cust-backup-email','cust-note','cust-follow-up-note'].forEach(id => $(id).value='');
    }
    showModal('customer-modal');
}

async function saveCustomer() {
    const name = $('cust-name').value.trim();
    if (!name) { toast('请填写客户名称'); return; }
    const editId = $('cust-edit-id').value;
    const contact = ($('cust-contact')?.value?.trim() || '');
    const note = $('cust-note').value.trim();
    const country = $('cust-country').value.trim();
    const tier = $('cust-tier').value;
    const buyerType = $('cust-buyer-type').value;
    const mainCategory = $('cust-main-category').value.trim();
    const matchScore = parseInt($('cust-match-score').value) || 0;
    const linkedin = $('cust-linkedin').value.trim();
    const title = $('cust-title').value.trim();
    const email = $('cust-email').value.trim();
    const phone = $('cust-phone').value.trim();
    const whatsapp = $('cust-whatsapp').value.trim();
    const website = $('cust-website').value.trim();
    const backupEmail = $('cust-backup-email').value.trim();
    const followUpNote = $('cust-follow-up-note').value.trim();

    const body = {name, contact, note, country, tier, linkedin_url: linkedin,
        title, email, phone, whatsapp, company_website: website, backup_email: backupEmail, buyer_type: buyerType, follow_up_note: followUpNote, main_category: mainCategory, match_score: matchScore};
    if (editId) {
        await api('PUT', `/api/trade/customers/${editId}`, body);
    } else {
        await api('POST', `/api/trade/customers`, body);
    }
    hideModal('customer-modal');
    await loadCustomersData();
    if (currentView === 'customers') renderCustomersTable(allCustomers);
    toast(editId ? '客户已更新' : '客户已添加');
}

// ── 批量导入 ───────────────────────────────────────────
async function bulkImportCustomers() {
    const fileInput = document.getElementById('cust-bulk-file');
    if (!fileInput || !fileInput.files.length) return;
    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append('file', file);
    const btn = fileInput.nextElementSibling;
    btn.disabled = true; btn.textContent = '导入中...';

    try {
        const resp = await fetch('/api/trade/customers/bulk', {
            method: 'POST',
            headers: { 'X-Hermes-Session-Token': TOKEN, 'X-Company-ID': String(currentCompanyId) },
            body: formData,
        });
        const result = await resp.json();
        if (resp.ok) {
            toast(`导入完成：新增 ${result.created} 条，跳过 ${result.skipped} 条（重复或空行）`);
            await loadCustomersData();
            if (currentView === 'customers') renderCustomersTable(allCustomers);
        } else {
            toast(result.detail || '导入失败');
        }
    } catch (e) {
        toast('导入失败: ' + e.message);
    }
    btn.disabled = false; btn.textContent = '📤 上传导入';
    fileInput.value = '';
}

// ── 下载管理表格 Excel ──────────────────────────────
async function downloadManagementTables() {
    try {
        const headers = {};
        if (TOKEN) headers['X-Hermes-Session-Token'] = TOKEN;
        if (currentCompanyId) headers['X-Company-ID'] = String(currentCompanyId);
        const resp = await fetch('/api/trade/templates/download', { headers });
        if (!resp.ok) { toast('下载管理表格失败'); return; }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'trade-management-tables.xlsx';
        a.click();
        URL.revokeObjectURL(url);
        toast('✅ 管理表格下载完成');
    } catch(e) { toast('下载管理表格失败: ' + e.message); }
}

// ── 下载 CSV 模板（需携带 auth header） ─────────────
async function downloadCsvTemplate() {
    try {
        const headers = {};
        if (TOKEN) headers['X-Hermes-Session-Token'] = TOKEN;
        if (currentCompanyId) headers['X-Company-ID'] = String(currentCompanyId);
        const resp = await fetch('/api/trade/customers/template', { headers });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            toast(err.detail || '下载模板失败');
            return;
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'trade-customer-template.csv';
        a.click();
        URL.revokeObjectURL(url);
    } catch(e) {
        toast('下载模板失败: ' + e.message);
    }
}

// ═════════════════════ TASKS VIEW ═════════════════════
// ═══ 定时任务模板（基于外贸业务员标准工作流程）═════
const TASK_TEMPLATES = [
    {id:'morning-brief',name:'🌅 早安简报',time:'09:00',required:true,
     desc:'使用 web_search 获取实时汇率、大宗商品价格、目标市场新闻，结合昨日对话生成简报',
     prompt:'按照 b2b-daily-automation 技能中的早安简报规范生成今日简报。必须使用 web_search 逐项搜索实时汇率（USD/EUR/GBP→CNY）、大宗商品价格（金/铜/铝/原油）、目标市场新闻。查询昨日对话记录和客户待跟进清单。所有数值必须来自搜索结果，不得编造或留空。'},
    {id:'email-followup',name:'📧 邮件处理与跟进',time:'09:00-10:30',required:false,
     desc:'回复所有未读消息，发送跟进邮件。新消息 2 小时内回复 100%',
     prompt:'帮我整理今天待处理的邮件和跟进事项：列出昨日至今天收到的客户消息、需要跟进的客户（按 A/B/C 优先级）、明天需要发送的提醒邮件模板。'},
    {id:'linkedin-add',name:'🔍 精准加人 (LinkedIn)',time:'10:00-11:30',required:false,
     desc:'搜索关键词+职位，发送连接请求+Add Note，目标 30-50 人/天',
     prompt:'生成本日 LinkedIn 精准加人计划：根据我公司的产品和目标市场，列出今天应该搜索的 5 个关键词组合，每个关键词推荐 3-5 个搜索过滤条件（行业/地区/职位），并生成 Add Note 模板。'},
    {id:'linkedin-engage',name:'💬 评论互动与私信致谢',time:'11:30-12:00',required:false,
     desc:'评论目标客户 10-15 条动态，新增连接发送感谢私信',
     prompt:'帮我生成本日 LinkedIn 互动计划：列出需要评论的客户类型和评论模板（3 种场景），以及新增连接后的感谢私信模板。'},
    {id:'linkedin-content',name:'📢 LinkedIn 内容发布',time:'15:30',required:false,
     desc:'发布或转发 1 条内容（案例/痛点/工厂/证书），≥3 帖/周',
     prompt:'请生成本日的 LinkedIn 帖子（5 维度轮换：视频/照片/文章/投票/Document）。内容围绕我公司产品和行业，带 5 个 hashtag，可直接复制粘贴发布。'},
    {id:'platform-check',name:'🏪 B2B 平台检查',time:'15:30-17:00',required:false,
     desc:'检查阿里国际站/Made-in-China 等平台询盘、排名、发布产品',
     prompt:'生成今日 B2B 平台检查清单：新询盘数量、待回复询盘、产品排名变化、需要发布的产品数量。给出具体可执行的操作步骤。'},
    {id:'customer-dev',name:'👥 客户开发',time:'13:30-15:30',required:false,
     desc:'新客户搜索/加人/开发信发送，目标日均 20-30 个有效触达',
     prompt:'生成本日客户开发计划：根据我公司的产品和目标市场，列出 5 个找客户渠道（LinkedIn/Facebook/Google Maps/B2B平台/海关数据），每个渠道给出具体搜索方法和开发信模板。'},
    {id:'daily-summary',name:'📊 每日工作总结',time:'17:00',required:false,
     desc:'更新客户表/CRM，复盘当日完成情况，规划次日优先级',
     prompt:'请帮我生成今日工作总结模板，包含：今日完成事项清单、客户互动汇总、新增客户统计、待跟进事项、明日优先级安排。如果是周五，加上本周 KPI 对比和下周计划。'},
    {id:'weekly-report',name:'📋 每周复盘报告',time:'周五 17:30',required:false,
     desc:'周复盘：亮点/短板/KPI对比/下周行动清单',
     prompt:'请生成本周复盘报告模板，包含：本周完成事项、KPI 完成情况（新增人脉/有效对话/需求线索/预约会议/内容发布）、亮点与短板分析、竞品洞察、下周行动清单。'},
];

function getCustomTemplates() {
    try { return JSON.parse(localStorage.getItem('trade_custom_templates') || '[]'); } catch(e) { return []; }
}

function getAllTemplates() {
    return [...TASK_TEMPLATES, ...getCustomTemplates()];
}

function deleteCustomTemplate(id) {
    if (!confirm('删除此自定义模板？')) return;
    let customs = getCustomTemplates();
    customs = customs.filter(t => t.id !== id);
    localStorage.setItem('trade_custom_templates', JSON.stringify(customs));
    const ct = currentChatContainer;
    if (ct && currentView === 'tasks') renderTasksViewInto(ct);
}

function renderTasksViewInto(container) {
    const coName = currentCompanyId ? (companies.find(c => c.id === currentCompanyId)?.name || '') : '';
    const allTemplates = getAllTemplates();

    const renderCard = (t) => {
        const isCustom = t.custom === true;
        const hasEdit = templateEdits[t.id];
        const displayTime = (hasEdit && hasEdit.time) || t.time;
        return `
        <div class="task-card" style="position:relative;">
            ${isCustom ? `<button onclick="deleteCustomTemplate('${t.id}')" style="position:absolute;top:8px;right:8px;background:none;border:none;cursor:pointer;font-size:14px;color:var(--accent-red);">×</button>` : ''}
            <div class="task-card-header">
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
                    <input type="checkbox" class="task-template-check" data-id="${t.id}" ${t.required ? 'checked disabled' : ''}>
                    <span class="task-card-name">${esc(t.name)}</span>
                    ${t.required ? '<span style="font-size:10px;color:var(--accent);background:#FEF3C7;padding:1px 6px;border-radius:999px;">必选</span>' : ''}
                    ${isCustom ? '<span style="font-size:10px;color:var(--primary);background:#EFF6FF;padding:1px 6px;border-radius:999px;">自定义</span>' : ''}
                </label>
            </div>
            <div style="display:flex;align-items:center;gap:6px;margin:6px 0;">
                <span style="font-size:11px;color:var(--text-muted);">🕐</span>
                <input type="text" class="task-time-input" data-id="${t.id}" value="${esc(displayTime)}" style="width:100px;padding:2px 6px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px;font-family:monospace;" onchange="onTemplateTimeChange('${t.id}', this.value)">
                ${t.cron ? `<span style="font-size:10px;color:var(--text-muted);font-family:monospace;">${esc(t.cron)}</span>` : ''}
            </div>
            <div style="font-size:11px;color:var(--text-secondary);margin-bottom:8px;">${esc(t.desc || '')}</div>
            <div class="task-card-actions">
                <button onclick="editTemplatePrompt('${t.id}')" style="font-size:11px;">✏️ 编辑 Prompt</button>
                <button onclick="runSingleTemplate('${t.id}')" style="font-size:11px;">▶ 执行一次</button>
            </div>
        </div>`;
    };

    container.innerHTML = `
    <div class="panel-view" style="display:flex;flex-direction:column;height:100%;overflow-y:auto;">
        <div class="panel-topbar">
            <h2>⏰ 定时任务${coName ? `<span style="margin-left:10px;padding:3px 10px;background:rgba(59,130,246,0.08);color:var(--primary);border-radius:999px;font-size:12px;font-weight:500;">🏢 ${esc(coName)}</span>` : ''}</h2>
            <div class="panel-topbar-actions">
                <button class="btn btn-primary" onclick="batchCreateCronTasks()">⚡ 批量生成选中任务</button>
                <button class="btn btn-danger" onclick="clearAllCronTasks()">🗑 清空全部任务</button>
            </div>
        </div>
        <div class="panel-body" style="overflow-y:auto;padding:16px 20px;">
            <!-- 定时任务使用说明书 -->
            <details style="margin-bottom:16px;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">
                <summary style="cursor:pointer;padding:12px 16px;font-weight:600;font-size:14px;background:var(--bg);user-select:none;">
                    📖 定时任务使用说明书（点击展开 / 收起）
                </summary>
                <div style="padding:16px 20px;font-size:13px;line-height:1.8;color:var(--text-secondary);">

                <h4 style="margin:0 0 10px 0;color:var(--text-primary);">一、什么是定时任务？</h4>
                <p>定时任务就像一个闹钟。你告诉它「每天几点要做什么事」，时间一到，系统会自动帮你去执行。</p>
                <p>比如你可以设置：每天早上 9 点自动搜索当日汇率、每周五下午 5 点生成周报。</p>

                <h4 style="margin:18px 0 10px 0;color:var(--text-primary);">二、Cron 表达式是什么？</h4>
                <p>Cron 表达式是用来描述「什么时候执行」的一串代码。它由 <b>5 个数字</b>组成，用空格隔开：</p>
                <div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:12px 16px;font-family:monospace;font-size:14px;text-align:center;margin:8px 0;">
                    <b>分钟 小时 日 月 星期</b>
                </div>
                <p>看不懂没关系，下面逐个解释 👇</p>

                <table style="width:100%;border-collapse:collapse;margin:10px 0;font-size:13px;">
                <thead>
                <tr style="background:var(--bg);">
                    <th style="padding:8px 12px;text-align:left;border:1px solid var(--border);">位置</th>
                    <th style="padding:8px 12px;text-align:left;border:1px solid var(--border);">叫什么</th>
                    <th style="padding:8px 12px;text-align:left;border:1px solid var(--border);">可以填什么</th>
                    <th style="padding:8px 12px;text-align:left;border:1px solid var(--border);">什么意思</th>
                </tr>
                </thead>
                <tbody>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);"><b>第 1 个</b></td><td style="padding:8px 12px;border:1px solid var(--border);">分钟</td><td style="padding:8px 12px;border:1px solid var(--border);">0 ~ 59</td><td style="padding:8px 12px;border:1px solid var(--border);">在每小时的第几分运行。填 0 代表整点，填 30 代表半点</td></tr>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);"><b>第 2 个</b></td><td style="padding:8px 12px;border:1px solid var(--border);">小时</td><td style="padding:8px 12px;border:1px solid var(--border);">0 ~ 23</td><td style="padding:8px 12px;border:1px solid var(--border);">在几点运行。0=半夜12点，8=早上8点，14=下午2点，20=晚上8点</td></tr>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);"><b>第 3 个</b></td><td style="padding:8px 12px;border:1px solid var(--border);">日</td><td style="padding:8px 12px;border:1px solid var(--border);">1 ~ 31</td><td style="padding:8px 12px;border:1px solid var(--border);">在每月第几天运行。填 * 代表每天都行</td></tr>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);"><b>第 4 个</b></td><td style="padding:8px 12px;border:1px solid var(--border);">月</td><td style="padding:8px 12px;border:1px solid var(--border);">1 ~ 12</td><td style="padding:8px 12px;border:1px solid var(--border);">在几月运行。填 * 代表每月都行</td></tr>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);"><b>第 5 个</b></td><td style="padding:8px 12px;border:1px solid var(--border);">星期</td><td style="padding:8px 12px;border:1px solid var(--border);">0 ~ 7</td><td style="padding:8px 12px;border:1px solid var(--border);">星期几运行。0=周日，1=周一...6=周六。填 * 代表每天</td></tr>
                </tbody>
                </table>

                <h4 style="margin:18px 0 10px 0;color:var(--text-primary);">三、常用写法速查表</h4>
                <table style="width:100%;border-collapse:collapse;margin:10px 0;font-size:13px;">
                <thead>
                <tr style="background:var(--bg);">
                    <th style="padding:8px 12px;text-align:left;border:1px solid var(--border);">你想要的</th>
                    <th style="padding:8px 12px;text-align:left;border:1px solid var(--border);">Cron 表达式</th>
                    <th style="padding:8px 12px;text-align:left;border:1px solid var(--border);">大白话解释</th>
                </tr>
                </thead>
                <tbody>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);">每天上午 9:00</td><td style="padding:8px 12px;border:1px solid var(--border);font-family:monospace;">0 9 * * *</td><td style="padding:8px 12px;border:1px solid var(--border);">每天 9 点整触发</td></tr>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);">每天下午 3:30</td><td style="padding:8px 12px;border:1px solid var(--border);font-family:monospace;">30 15 * * *</td><td style="padding:8px 12px;border:1px solid var(--border);">每天 15:30 触发</td></tr>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);">每个工作日（周一到周五）9:00</td><td style="padding:8px 12px;border:1px solid var(--border);font-family:monospace;">0 9 * * 1-5</td><td style="padding:8px 12px;border:1px solid var(--border);">周一至周五的早上 9 点</td></tr>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);">每周一早上 8:30</td><td style="padding:8px 12px;border:1px solid var(--border);font-family:monospace;">30 8 * * 1</td><td style="padding:8px 12px;border:1px solid var(--border);">只在每周一 8:30 触发</td></tr>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);">每周五下午 5:30</td><td style="padding:8px 12px;border:1px solid var(--border);font-family:monospace;">30 17 * * 5</td><td style="padding:8px 12px;border:1px solid var(--border);">只在每周五 17:30 触发</td></tr>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);">每月 1 号上午 10:00</td><td style="padding:8px 12px;border:1px solid var(--border);font-family:monospace;">0 10 1 * *</td><td style="padding:8px 12px;border:1px solid var(--border);">每个月 1 号触发</td></tr>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);">每隔 30 分钟</td><td style="padding:8px 12px;border:1px solid var(--border);font-family:monospace;">*/30 * * * *</td><td style="padding:8px 12px;border:1px solid var(--border);">每 30 分钟跑一次</td></tr>
                </tbody>
                </table>

                <h4 style="margin:18px 0 10px 0;color:var(--text-primary);">四、特殊符号说明</h4>
                <table style="width:100%;border-collapse:collapse;margin:10px 0;font-size:13px;">
                <thead>
                <tr style="background:var(--bg);">
                    <th style="padding:8px 12px;text-align:left;border:1px solid var(--border);">符号</th>
                    <th style="padding:8px 12px;text-align:left;border:1px solid var(--border);">名字</th>
                    <th style="padding:8px 12px;text-align:left;border:1px solid var(--border);">怎么用</th>
                    <th style="padding:8px 12px;text-align:left;border:1px solid var(--border);">举例</th>
                </tr>
                </thead>
                <tbody>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);font-family:monospace;">*</td><td style="padding:8px 12px;border:1px solid var(--border);">星号（通配）</td><td style="padding:8px 12px;border:1px solid var(--border);">代表「所有可能的值」。填在小时位置就是每小时，填在日位置就是每天</td><td style="padding:8px 12px;border:1px solid var(--border);"><code>0 9 * * *</code> = 每天 9 点</td></tr>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);font-family:monospace;">,</td><td style="padding:8px 12px;border:1px solid var(--border);">逗号（列举）</td><td style="padding:8px 12px;border:1px solid var(--border);">列出多个值，用逗号隔开</td><td style="padding:8px 12px;border:1px solid var(--border);"><code>0 9,14,18 * * *</code> = 每天 9点、14点、18点各跑一次</td></tr>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);font-family:monospace;">-</td><td style="padding:8px 12px;border:1px solid var(--border);">横线（范围）</td><td style="padding:8px 12px;border:1px solid var(--border);">从 A 到 B 的所有值</td><td style="padding:8px 12px;border:1px solid var(--border);"><code>0 9 * * 1-5</code> = 周一到周五</td></tr>
                <tr><td style="padding:8px 12px;border:1px solid var(--border);font-family:monospace;">/</td><td style="padding:8px 12px;border:1px solid var(--border);">斜杠（间隔）</td><td style="padding:8px 12px;border:1px solid var(--border);">每隔多少就触发一次</td><td style="padding:8px 12px;border:1px solid var(--border);"><code>*/15 * * * *</code> = 每 15 分钟跑一次</td></tr>
                </tbody>
                </table>

                <h4 style="margin:18px 0 10px 0;color:var(--text-primary);">五、执行时间怎么填？</h4>
                <p>在模板中，<b>「执行时间」</b>字段不需要写 Cron 表达式，直接写时间就行：</p>
                <ul style="margin:4px 0;padding-left:20px;">
                    <li>写 <code>09:00</code> — 系统会自动生成 <code>0 9 * * 1-5</code>（工作日早 9 点）</li>
                    <li>写 <code>09:00-10:30</code> — 代表一个时间段，系统会用开始时间 09:00</li>
                    <li>写 <code>周五 17:30</code> — 如果你在 Cron 表达式里填了覆盖值，则以 Cron 表达式为准</li>
                </ul>
                <p>如果你想精确控制，直接改右边的 <b>「Cron 表达式」</b>框。</p>

                <h4 style="margin:18px 0 10px 0;color:var(--text-primary);">六、执行 Prompt 怎么写？</h4>
                <p>Prompt 就是告诉 Agent「你要帮我做什么」的一段话。用大白话写就行，就像你在聊天框里打字一样。</p>
                <p><b>写好 Prompt 的 3 个要点：</b></p>
                <ol style="margin:4px 0;padding-left:20px;">
                    <li><b>说清楚目标</b>：不要写「帮我查资料」，要写「帮我查今天的 USD/CNY 汇率、铜价、铝价」</li>
                    <li><b>说清楚格式</b>：不要写「生成简报」，要写「用表格列出，包含实时数值、变化幅度、数据来源」</li>
                    <li><b>说清楚要求</b>：不要写「写开发信」，要写「用英语写，100 字以内，先提客户痛点再讲我们的解决方案」</li>
                </ol>
                <p>💡 <b>重要提醒</b>：Prompt 要写<b>任务本身做什么</b>，不要写多余的话。Agent 会自动执行，不需要你说「请」、「谢谢」。</p>

                <h4 style="margin:18px 0 10px 0;color:var(--text-primary);">七、操作步骤</h4>
                <ol style="margin:4px 0;padding-left:20px;">
                    <li><b>钩选</b>你想要的任务模板（或点「➕ 自定义模板」写自己的）</li>
                    <li><b>编辑执行时间</b>和<b>Cron 表达式</b>（用上面速查表参考）</li>
                    <li>点「✏️ 编辑 Prompt」检查或修改任务指令</li>
                    <li>点<b>「⚡ 批量生成选中任务」</b>，Agent 自动创建定时任务</li>
                    <li>下方「📡 已激活的定时任务」会显示当前所有运行中的任务</li>
                    <li>如果需要马上执行，点任务旁的「▶ 执行一次」按钮</li>
                </ol>

                <h4 style="margin:18px 0 10px 0;color:var(--text-primary);">八、常见问题</h4>
                <p><b>Q: 任务会在我关掉浏览器后执行吗？</b></p>
                <p>A: 会的。定时任务由后台服务独立运行，不需要你一直开着浏览器。只要电脑开着、Trade 系统在运行就行。</p>
                <p><b>Q: 我能把电脑关了吗？</b></p>
                <p>A: 不能。Trade 系统需要运行时电脑保持开机。可以设置 Trade 开机自启动（安装脚本会提示配置），这样每次开机自动运行。</p>
                <p><b>Q: 任务执行结果在哪看？</b></p>
                <p>A: 结果会发送到聊天界面中。如果你在早上 9 点前打开界面，可以看到早安简报自动推送。</p>
                <p><b>Q: Cron 表达式写错了怎么办？</b></p>
                <p>A: 不会造成损害，只是任务不会按时执行或不执行。删掉重建就行。</p>

                </div>
            </details>

            <!-- 模板库 -->
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                <div style="font-size:13px;font-weight:600;color:var(--text-secondary);">📋 任务模板库（钩选 → 编辑时间 → 批量生成）</div>
                <button class="btn btn-xs" onclick="showAddCustomTemplateModal()" style="color:var(--primary);">➕ 自定义模板</button>
            </div>
            <div class="task-grid" id="task-templates-grid">
                ${allTemplates.map(renderCard).join('')}
            </div>

            <!-- 分隔线 -->
            <hr style="border:none;border-top:2px dashed var(--border);margin:20px 0;">

            <!-- 已激活任务 -->
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                <div style="font-size:13px;font-weight:600;color:var(--text-secondary);">📡 已激活的定时任务</div>
                <button class="btn btn-xs" onclick="loadActiveCronJobs()">🔄 刷新</button>
            </div>
            <div class="task-grid" id="active-tasks-grid">
                <div style="color:var(--text-muted);font-size:12px;padding:12px;">加载中...</div>
            </div>
        </div>
    </div>`;
    loadActiveCronJobs();
}

// ── 模板操作 ──

// 全局编辑存储 { templateId: { time, prompt } }
let templateEdits = {};

function onTemplateCheckChange() {
    // 仅用于视觉反馈，实际选中状态从 checkbox 读取
}

function onTemplateTimeChange(id, value) {
    if (!templateEdits[id]) templateEdits[id] = {};
    templateEdits[id].time = value;
}

function editTemplatePrompt(id) {
    const t = TASK_TEMPLATES.find(x => x.id === id);
    if (!t) return;
    const currentPrompt = (templateEdits[id] && templateEdits[id].prompt) || t.prompt;
    showPromptEditorModal(t.name, currentPrompt, (newPrompt) => {
        if (!templateEdits[id]) templateEdits[id] = {};
        templateEdits[id].prompt = newPrompt;
        toast(`"${t.name}" Prompt 已更新`);
    });
}

function showPromptEditorModal(title, currentText, onSave) {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.id = 'prompt-editor-modal';
    backdrop.onclick = function(e) { if (e.target === backdrop) backdrop.remove(); };
    backdrop.innerHTML = `
    <div class="modal" style="max-width:640px;width:95%;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
            <h3>✏️ 编辑：${esc(title)}</h3>
            <button class="slide-panel-close" onclick="document.getElementById('prompt-editor-modal').remove()">×</button>
        </div>
        <div class="form-group">
            <label for="prompt-editor-text">任务 Prompt（Agent 将按此指令执行）</label>
            <textarea id="prompt-editor-text" style="width:100%;min-height:200px;font-family:monospace;font-size:13px;padding:10px;">${esc(currentText)}</textarea>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">
            <button class="btn" onclick="document.getElementById('prompt-editor-modal').remove()">取消</button>
            <button class="btn btn-primary" onclick="(function(){
                const text = document.getElementById('prompt-editor-text').value;
                document.getElementById('prompt-editor-modal').remove();
                arguments[0](text);
            })(arguments[0])">💾 保存</button>
        </div>
    </div>`;
    // 保存回调绑定
    const saveBtn = backdrop.querySelector('.btn-primary');
    saveBtn.setAttribute('data-onsave', 'true');
    // 重新绑定 onclick
    const textarea = backdrop.querySelector('#prompt-editor-text');
    saveBtn.onclick = function() {
        const newText = textarea.value;
        backdrop.remove();
        onSave(newText);
    };
    document.body.appendChild(backdrop);
}

function showAddCustomTemplateModal() {
    const old = document.getElementById('custom-template-modal');
    if (old) old.remove();  // 先清理旧的，防止重复 id
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.id = 'custom-template-modal';
    backdrop.onclick = function(e) { if (e.target === backdrop) backdrop.remove(); };
    backdrop.innerHTML = `
    <div class="modal" style="max-width:600px;width:95%;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
            <h3>➕ 自定义任务模板</h3>
            <button class="slide-panel-close" onclick="document.getElementById('custom-template-modal').remove()">×</button>
        </div>
        <div class="form-group"><label for="custom-tmpl-name">任务名称 *</label><input type="text" id="custom-tmpl-name" placeholder="例如：海关数据每日监控"></div>
        <div class="form-row">
            <div class="form-group"><label for="custom-tmpl-time">执行时间 *</label><input type="text" id="custom-tmpl-time" placeholder="09:00 或 09:00-10:30" value="09:00"></div>
            <div class="form-group"><label for="custom-tmpl-cron">Cron 表达式</label><input type="text" id="custom-tmpl-cron" placeholder="0 9 * * 1-5" value="0 9 * * 1-5"></div>
        </div>
        <div class="form-group"><label for="custom-tmpl-desc">任务描述</label><input type="text" id="custom-tmpl-desc" placeholder="简要描述任务内容"></div>
        <div class="form-group"><label for="custom-tmpl-prompt">执行 Prompt *</label><textarea id="custom-tmpl-prompt" style="width:100%;min-height:150px;font-family:monospace;font-size:13px;padding:10px;" placeholder="Agent 将按此指令执行..."></textarea></div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">
            <button class="btn" onclick="document.getElementById('custom-template-modal').remove()">取消</button>
            <button class="btn btn-primary" onclick="saveCustomTemplate()">💾 保存模板</button>
        </div>
    </div>`;
    document.body.appendChild(backdrop);
}

function saveCustomTemplate() {
    const name = document.getElementById('custom-tmpl-name').value.trim();
    const time = document.getElementById('custom-tmpl-time').value.trim();
    const cron = document.getElementById('custom-tmpl-cron').value.trim();
    const desc = document.getElementById('custom-tmpl-desc').value.trim();
    const prompt = document.getElementById('custom-tmpl-prompt').value.trim();
    if (!name || !time || !prompt) { toast('请填写任务名称、时间和 Prompt'); return; }

    const id = 'custom-' + Date.now();
    const tpl = {id, name, time, cron, desc, prompt, custom: true};
    let customs = [];
    try { customs = JSON.parse(localStorage.getItem('trade_custom_templates') || '[]'); } catch(e) {}
    customs.push(tpl);
    localStorage.setItem('trade_custom_templates', JSON.stringify(customs));
    document.getElementById('custom-template-modal').remove();
    toast(`自定义模板「${name}」已添加`);
    // 刷新视图
    const ct = currentChatContainer;
    if (ct && currentView === 'tasks') renderTasksViewInto(ct);
}

function runSingleTemplate(id) {
    const t = getAllTemplates().find(x => x.id === id);
    if (!t) return;
    const prompt = (templateEdits[id] && templateEdits[id].prompt) || t.prompt;
    runSingleTask(t.name, prompt);
}

function runSingleTask(taskName, prompt) {
    if (!currentCompanyId) { toast('请先选择公司'); return; }
    navToView('chat', 'daily', taskName);
    setTimeout(() => {
        const ct = currentChatContainer;
        const input = ct ? ct.querySelector('#msg-input') : null;
        if (input) {
            input.value = prompt;
            sendMsg();
        }
    }, 300);
}

function batchCreateCronTasks() {
    if (!currentCompanyId) { toast('请先选择公司'); return; }
    const checks = document.querySelectorAll('.task-template-check:checked');
    if (!checks.length) { toast('请至少选择一个任务模板'); return; }

    const allTemplates = getAllTemplates();
    const selected = [];
    checks.forEach(cb => {
        const id = cb.dataset.id;
        const t = allTemplates.find(x => x.id === id);
        if (!t) return;
        const time = (templateEdits[id] && templateEdits[id].time) || t.time;
        const cronExpr = t.cron || cronFromTime(time);
        const prompt = (templateEdits[id] && templateEdits[id].prompt) || t.prompt;
        selected.push(`任务名: ${t.name} | schedule: ${cronExpr} | Prompt: ${prompt}`);
    });

    navToView('chat', 'daily', '定时任务批量创建');
    setTimeout(() => {
        const ct = currentChatContainer;
        const input = ct ? ct.querySelector('#msg-input') : null;
        if (input) {
            input.value = `请使用 cronjob 工具为我批量创建以下定时任务，所有任务使用 --deliver local：\n${selected.join('\n')}\n\n请为每个任务创建 cron job 并返回创建结果。`;
            sendMsg();
        }
    }, 300);
}

async function clearAllCronTasks() {
    if (!confirm('确定删除所有已激活的定时任务？此操作不可恢复。')) return;
    navToView('chat', 'daily', '清空定时任务');
    setTimeout(() => {
        const ct = currentChatContainer;
        const input = ct ? ct.querySelector('#msg-input') : null;
        if (input) {
            input.value = '请使用 cronjob 工具列出并删除所有现有的 cron 定时任务。逐一删除，完成后告知结果。';
            sendMsg();
            // 刷新列表
            setTimeout(loadActiveCronJobs, 5000);
        }
    }, 300);
}

async function loadActiveCronJobs() {
    if (!currentCompanyId) return;
    const data = await api('GET', '/api/trade/cron/jobs');
    const grid = document.getElementById('active-tasks-grid');
    if (!grid) return;
    if (!data || !data.length) {
        grid.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:12px;">暂无已激活的定时任务。请从上方模板库钩选后点击「批量生成」。</div>';
        return;
    }
    grid.innerHTML = data.map(j => `
        <div class="task-card">
            <div class="task-card-header">
                <span class="task-card-name">${esc(j.name)}</span>
                <span style="font-size:10px;color:${j.enabled ? 'var(--accent-green)' : 'var(--text-muted)'};">${j.enabled ? '● 运行中' : '○ 已暂停'}</span>
            </div>
            <div class="task-card-schedule">🕐 ${esc(j.schedule)}</div>
            ${j.next_run ? `<div style="font-size:11px;color:var(--accent-green);margin-bottom:6px;">▶ 下次执行：${esc(j.next_run)}</div>` : ''}
            <div class="task-card-actions">
                <button onclick="runActiveJob('${esc(j.id)}')">▶ 立即执行</button>
            </div>
        </div>
    `).join('');
}

function runActiveJob(jobId) {
    if (!currentCompanyId) return;
    navToView('chat', 'daily', '立即执行任务');
    setTimeout(() => {
        const ct = currentChatContainer;
        const input = ct ? ct.querySelector('#msg-input') : null;
        if (input) {
            input.value = `请使用 cronjob 工具手动触发一次任务 ID ${jobId}，将结果输出到当前对话。`;
            sendMsg();
        }
    }, 300);
}

function cronFromTime(timeStr) {
    // 将 "09:00" 或 "09:00-10:30" 转换为 cron 表达式
    const first = timeStr.split('-')[0].trim(); // "09:00"
    const parts = first.split(':');
    if (parts.length !== 2) return '0 9 * * 1-5';
    const h = parseInt(parts[0]), m = parseInt(parts[1]);
    return `${m} ${h} * * 1-5`;
}

// ═════════════════════ DIRECTORY VIEW ═════════════════════
function renderDirectoryViewInto(container) {
    const coName = currentCompanyId ? (companies.find(c => c.id === currentCompanyId)?.name || '') : '';
    container.innerHTML = `
        <div class="panel-topbar">
            <h2>📂 数据目录${coName ? `<span style="margin-left:10px;padding:3px 10px;background:rgba(59,130,246,0.08);color:var(--primary);border-radius:999px;font-size:12px;font-weight:500;">🏢 ${esc(coName)}</span>` : ''}</h2>
            <div class="panel-topbar-actions">
                <button class="btn" onclick="toast('功能开发中：将在文件管理器中打开')">📂 打开目录</button>
            </div>
        </div>
        <div class="panel-body" style="display:flex;gap:16px;">
            <div style="width:320px;flex-shrink:0;">
                <div class="dir-tree" id="dir-tree">
                    <div class="loading-row"><div class="spinner"></div>加载目录结构...</div>
                </div>
            </div>
            <div style="flex:1;">
                <div class="file-preview" id="file-preview">
                    <div style="color:var(--text-muted);text-align:center;padding:40px;">👈 点击左侧文件查看内容</div>
                </div>
            </div>
        </div>`;
    loadDirectoryTree();
}

async function loadDirectoryTree() {
    // Build tree from known structure since we can't browse server filesystem via API
    // Show the standard ~/.trade/ layout
    const co = companies.find(c => c.id === currentCompanyId);
    const slug = co?.slug || 'default';

    const tree = [
        {name:'company-profile.md',icon:'📄',type:'file'},
        {name:'products.md',icon:'📄',type:'file'},
        {name:'agent-identity.md',icon:'📄',type:'file'},
        {name:'business-scope.md',icon:'📄',type:'file'},
        {name:'competitors.md',icon:'📄',type:'file'},
        {name:'certifications.md',icon:'📄',type:'file'},
        {name:'marketing-strategy.md',icon:'📄',type:'file'},
        {name:'sales-playbook.md',icon:'📄',type:'file'},
        {name:'libraries/',icon:'📂',type:'dir',children:[
            {name:'{lib-slug}/',icon:'📂',type:'dir',children:[
                {name:'index.md',icon:'📄',type:'file'},
                {name:'changelog.md',icon:'📄',type:'file'},
                {name:'metadata.md',icon:'📄',type:'file'},
            ]}
        ]},
        {name:'clients/',icon:'📂',type:'dir',children:[
            {name:'{client-slug}/',icon:'📂',type:'dir',children:[
                {name:'profile.md',icon:'📄',type:'file'},
                {name:'contacts.md',icon:'📄',type:'file'},
                {name:'interactions.md',icon:'📄',type:'file'},
                {name:'requirements.md',icon:'📄',type:'file'},
                {name:'quotes.md',icon:'📄',type:'file'},
                {name:'orders.md',icon:'📄',type:'file'},
                {name:'notes.md',icon:'📄',type:'file'},
            ]}
        ]},
    ];

    $('dir-tree').innerHTML = `<div style="font-weight:600;margin-bottom:8px;color:var(--text-secondary);">~/.trade/${esc(slug)}/</div>` +
        renderTreeItems(tree, 0);

    // 委托事件：文件树点击（避免 onclick 中直接拼接文件名导致 XSS）
    $('dir-tree').onclick = function(e) {
        var el = e.target.closest && e.target.closest('[data-file-click]');
        if (el && el.getAttribute('data-file-click') === 'preview') {
            previewFile(el.getAttribute('data-file-name'));
        }
    };

    // Also load agent identity preview if available
    const identity = await api('GET', `/api/trade/companies/${currentCompanyId}/agent-identity`);
    if (identity?.agent_identity_md) {
        $('file-preview').innerHTML = `<div class="file-preview-header"><h3>📄 agent-identity.md</h3></div>
            <div>${DOMPurify.sanitize(marked.parse(identity.agent_identity_md), {ALLOWED_TAGS:['p','br','strong','em','ul','ol','li','h1','h2','h3','blockquote','code','pre','a','table','thead','tbody','tr','th','td','hr','span'],ALLOWED_ATTR:['href','target','class']})}</div>`;
    }
}

function renderTreeItems(items, depth) {
    return items.map(item => {
        const indent = depth * 20;
        const attrs = item.type === 'file'
            ? `data-file-name="${esc(item.name)}" data-file-click="preview"`
            : '';
        return `<div class="dir-tree-item ${item.type}" style="padding-left:${indent}px;" ${attrs}>
            <span class="tree-icon">${item.icon}</span> ${esc(item.name)}
        </div>` + (item.children ? renderTreeItems(item.children, depth+1) : '');
    }).join('');
}

function previewFile(name) {
    $('file-preview').innerHTML = `<div class="file-preview-header"><h3>📄 ${esc(name)}</h3></div>
        <p style="color:var(--text-muted);">文件内容通过 Agent 对话中的 read_file 工具访问。在侧边栏中选择对应功能入口后，Agent 会自动读取相关文件。</p>`;
}

// ═════════════════════ HISTORY VIEW ═════════════════════
async function renderHistoryViewInto(container) {
    const coName = currentCompanyId ? (companies.find(c => c.id === currentCompanyId)?.name || '') : '';
    container.innerHTML = `
        <div class="panel-topbar">
            <h2>💬 ${t('history.title')}${coName ? '<span style="margin-left:10px;padding:3px 10px;background:rgba(59,130,246,0.08);color:var(--primary);border-radius:999px;font-size:12px;font-weight:500;">🏢 '+esc(coName)+'</span>' : ''}</h2>
            <div class="panel-topbar-actions">
                <input class="panel-search" id="conv-search" aria-label="搜索对话" placeholder="${currentLang==='en'?'Search conversations...':'搜索对话...'}" oninput="filterConversations()">
            </div>
        </div>
        <div class="panel-body">
            <div class="conv-list" id="conv-list">
                <div class="loading-row"><div class="spinner"></div>加载对话记录...</div>
            </div>
        </div>`;
    await loadConversations();
}

let allConversations = [];
async function loadConversations() {
    if (!currentCompanyId) return;
    allConversations = await api('GET', '/api/trade/conversations?limit=100') || [];
    renderConversationsList(allConversations);
}

function renderConversationsList(data) {
    const container = $('conv-list');
    if (!data.length) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">💬</div><h2>'+t('history.no_records')+'</h2></div>';
        return;
    }
    container.innerHTML = data.map(c => `
        <div class="conv-list-item" style="display:flex;align-items:flex-start;gap:8px;">
            <div style="flex:1;min-width:0;" onclick="showConversationDetail(${c.id})">
                <div class="conv-meta">
                    <span>${esc((c.created_at||'').slice(0,16))}</span>
                    ${c.library_id ? '<span style="background:#EFF6FF;color:var(--primary);padding:2px 6px;border-radius:4px;">📁 '+t('nav.docs')+'</span>' : ''}
                </div>
                <div class="conv-q">${esc(c.query||'').slice(0,100)}</div>
                <div class="conv-a">${esc(c.response||'').slice(0,150)}</div>
            </div>
            <button class="btn-xs" style="color:var(--accent-red);border-color:var(--accent-red);flex-shrink:0;margin-top:2px;"
                onclick="event.stopPropagation();deleteConversation(${c.id})" title="${t('hist.delete_title')}">🗑</button>
        </div>
    `).join('');
}

async function deleteConversation(cid) {
    if (!confirm(t('hist.confirm_delete'))) return;
    const r = await api('DELETE', `/api/trade/conversations/${cid}`);
    if (r && r.ok) {
        toast(t('hist.deleted'));
        allConversations = allConversations.filter(c => c.id !== cid);
        renderConversationsList(allConversations);
    } else {
        toast(r?.detail || t('hist.delete_fail'));
    }
}

function filterConversations() {
    const search = ($('conv-search')?.value||'').toLowerCase();
    if (!search) { renderConversationsList(allConversations); return; }
    const filtered = allConversations.filter(c =>
        (c.query||'').toLowerCase().includes(search) || (c.response||'').toLowerCase().includes(search)
    );
    renderConversationsList(filtered);
}

function showConversationDetail(cid) {
    const c = allConversations.find(x => x.id === cid);
    if (!c) return;

    // 从对话记录读取真实的 context；旧数据无 context 则回退到旧逻辑
    if (c.context) {
        currentChatContext = c.context;
    } else if (c.library_id) {
        currentChatContext = 'docs';
    } else {
        currentChatContext = 'daily';
    }
    currentLibraryId = c.library_id || null;
    currentChatName = '对话详情';
    currentCustomerId = null;

    // 强制重建目标视图
    const cacheKey = 'chat-' + currentChatContext;
    if (viewCache[cacheKey]) {
        viewCache[cacheKey].element.remove();
        delete viewCache[cacheKey];
    }

    navToView('chat', currentChatContext, currentChatName);

    // 用 MutationObserver 等 DOM 渲染完成后再拉取数据
    const tryLoad = () => {
        const ct = currentChatContainer;
        if (!ct || !ct.querySelector('#chat-messages')) {
            // DOM 还没到位，再等一轮
            requestAnimationFrame(tryLoad);
            return;
        }
        loadChatHistory();
    };
    requestAnimationFrame(tryLoad);
}

// ═════════════════════ ONBOARDING GUIDE ═════════════════════

function showOnboardingGuide() {
    for (const key in viewCache) {
        viewCache[key].element.remove();
        delete viewCache[key];
    }
    _onboardingStep = 1;
    _onboardingInputText = '';
    _onboardingOsinResponse = '';
    if (_onboardingStreamCtl) { _onboardingStreamCtl.abort(); }
    _onboardingStreamCtl = null;
    $('main-content').innerHTML = `<div id="onboarding-panel" class="onboarding-panel"><div class="onboarding-card" id="onboarding-card">${renderOnboardingStep1HTML()}</div></div>`;
}

function renderOnboardingStep1HTML() {
    return `<div id="onboarding-step1"><div class="onboarding-icon">🎉</div><h2 class="onboarding-title">欢迎使用 Trade AI</h2><p class="onboarding-subtitle">Trade 可以帮你<strong>自动搜索客户背景信息（OSINT）</strong>，并基于你的产品定位<strong>撰写专业 B2B 开发信</strong>。</p><div class="onboarding-features"><div class="onb-feature"><span>🔍</span> 海关数据 · 社媒分析 · 官网诊断</div><div class="onb-feature"><span>📧</span> AI 写开发信 · 跟进序列 · 报价单</div><div class="onb-feature"><span>🤖</span> 7x24 自动获客 · 定时任务调度</div></div><button class="btn btn-primary btn-lg" onclick="onboardingGoToStep2()">🚀 开发第一个客户</button><div class="onboarding-skip"><a href="#" onclick="onboardingSkip(event)">跳过引导，直接开始</a></div></div>`;
}

function renderOnboardingStep2HTML() {
    return `<div id="onboarding-step2"><div class="onboarding-step-indicator"><span class="onb-step done">✓ 了解 Trade</span><span class="onb-step-arrow">→</span><span class="onb-step active">● 开发客户</span></div><h3 class="onboarding-title" style="font-size:18px;margin-bottom:6px;">试试对目标客户做背调</h3><p style="color:var(--text-secondary);font-size:13px;margin-bottom:16px;">输入客户公司名或官网，AI 将自动搜索公开信息并生成开发信</p><div class="onboarding-input-row"><input type="text" id="onboarding-osint-input" placeholder="粘贴客户公司名或网址，如：acme-corp.com" class="onboarding-text-input" onkeydown="if(event.key==='Enter')onboardingStartOSINT()" autofocus /><button class="btn btn-primary" id="onboarding-send-btn" onclick="onboardingStartOSINT()">开始分析</button><button id="onboarding-stop-btn" class="hidden" style="background:var(--accent-red);color:#fff;border:none;padding:8px 16px;border-radius:var(--radius-sm);cursor:pointer;" onclick="onboardingStopOSINT()">🛑 停止</button></div><div id="onboarding-results-area"></div><div id="onboarding-actions" class="hidden"></div><div class="onboarding-skip"><a href="#" onclick="onboardingSkip(event)">跳过引导，直接开始</a></div></div>`;
}

function onboardingGoToStep2() {
    _onboardingStep = 2;
    $('onboarding-card').innerHTML = renderOnboardingStep2HTML();
    setTimeout(function() { var inp = $('onboarding-osint-input'); if (inp) inp.focus(); }, 100);
}

async function onboardingStartOSINT() {
    var input = $('onboarding-osint-input');
    var query = input.value.trim();
    if (!query) { toast(t('toast.enter_company')); return; }
    _onboardingInputText = query;
    input.disabled = true;
    $('onboarding-send-btn').disabled = true;
    $('onboarding-stop-btn').classList.remove('hidden');
    var resultsArea = $('onboarding-results-area');
    resultsArea.innerHTML = '';
    var prompt = '请对 ' + query + ' 做全面的客户背景调查（OSINT），然后基于我的公司产品生成一封专业的 B2B 开发信。';
    _onboardingStreamCtl = new AbortController();
    var progDiv = document.createElement('div');
    progDiv.className = 'onboarding-progress';
    progDiv.innerHTML = '<div class="thinking-msg">💭 '+t('misc.thinking')+'</div>';
    resultsArea.appendChild(progDiv);
    var toolEls = {};
    var progressDiv = null;
    var responseText = '';
    function ensureProgress() {
        if (!progressDiv) { progressDiv = document.createElement('div'); progressDiv.className = 'tool-progress'; progDiv.appendChild(progressDiv); }
        return progressDiv;
    }
    function addToolItem(tcId, name, status, detail) {
        var div = ensureProgress();
        var el = document.createElement('div');
        el.className = 'tool-item ' + status;
        el.id = 'onb-tool-' + tcId;
        // 安全构建 DOM：textContent 防止注入
        var icon = document.createElement('span');
        icon.className = 'tool-icon';
        icon.textContent = status === 'running' ? '◌' : status === 'done' ? '✓' : '✗';
        var body = document.createElement('div');
        body.className = 'tool-body';
        var nameEl = document.createElement('div');
        nameEl.className = 'tool-name';
        nameEl.textContent = fmtTool(name);
        var detailEl = document.createElement('div');
        detailEl.className = 'tool-detail';
        detailEl.textContent = detail || '';
        body.appendChild(nameEl);
        body.appendChild(detailEl);
        el.appendChild(icon);
        el.appendChild(body);
        div.appendChild(el);
        resultsArea.scrollTop = resultsArea.scrollHeight;
        toolEls[tcId] = el;
    }
    function updateTool(tcId, status, detail) {
        var el = toolEls[tcId]; if (!el) return;
        el.className = 'tool-item ' + status;
        var icon = el.querySelector('.tool-icon'); if (icon) icon.textContent = status==='running'?'◌':status==='done'?'✓':'✗';
        if (detail) { var d = el.querySelector('.tool-detail'); if (d) d.textContent = detail; }
        resultsArea.scrollTop = resultsArea.scrollHeight;
    }
    function resetInputs() {
        if (input) input.disabled = false;
        var sb = $('onboarding-send-btn'); if (sb) sb.disabled = false;
        var st = $('onboarding-stop-btn'); if (st) st.classList.add('hidden');
        _onboardingStreamCtl = null;
    }
    try {
        var resp = await fetch('/api/trade/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Hermes-Session-Token': TOKEN, 'X-Company-ID': String(currentCompanyId) },
            body: JSON.stringify({ query: prompt }),
            signal: _onboardingStreamCtl.signal
        });
        if (!resp.ok) { progDiv.remove(); resultsArea.innerHTML = '<div class="onb-error">请求失败 (' + resp.status + ')</div>'; resetInputs(); return; }
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';
        while (true) {
            var _a = await reader.read(), done = _a.done, value = _a.value;
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            var lines = buffer.split('\n');
            buffer = lines.pop() || '';
            var eventType = '', dataStr = '';
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].replace(/\r$/, '');
                if (line.startsWith('event: ')) { eventType = line.slice(7).trim(); continue; }
                if (line.startsWith('data: ')) { dataStr = line.slice(6).trimStart(); continue; }
                if (line === '' && eventType && dataStr) {
                    var data;
                    try { data = JSON.parse(dataStr); } catch(e) { eventType=''; dataStr=''; continue; }
                    switch (eventType) {
                        case 'tool_start':
                            addToolItem(data.tool_call_id, data.name, 'running', data.args ? Object.entries(data.args).map(function(kv) { return kv[0] + '=' + (typeof kv[1]==='string'?(kv[1].length>60?kv[1].slice(0,60)+'...':kv[1]):String(kv[1])); }).join(', ') : '');
                            break;
                        case 'tool_complete':
                            updateTool(data.tool_call_id, 'done', data.result_preview || '完成');
                            break;
                        case 'response':
                            responseText = data.text || '';
                            break;
                        case 'error':
                            progDiv.innerHTML = '<div class="onb-error">' + esc(data.message) + '</div>';
                            resetInputs();
                            return;
                    }
                    eventType = ''; dataStr = '';
                }
            }
        }
        progDiv.remove();
        if (responseText) {
            _onboardingOsinResponse = responseText;
            var respDiv = document.createElement('div');
            respDiv.className = 'onboarding-response';
            var raw = marked.parse(responseText);
            respDiv.innerHTML = DOMPurify.sanitize(raw, { ALLOWED_TAGS: ['p','br','strong','em','b','i','ul','ol','li','h1','h2','h3','h4','h5','h6','blockquote','code','pre','a','table','thead','tbody','tr','th','td','hr','span','div','img'], ALLOWED_ATTR: ['href','target','class','id','style','src','alt','width','height'] });
            resultsArea.appendChild(respDiv);
            showOnboardingActions();
        } else {
            resultsArea.innerHTML = '<div class="onb-error">AI 未返回有效回复，请重试。</div>';
        }
    } catch(e) {
        progDiv.remove();
        if (e.name === 'AbortError') resultsArea.innerHTML = '<div class="onb-info">已停止生成。</div>';
        else resultsArea.innerHTML = '<div class="onb-error">网络错误：' + esc(e.message) + '</div>';
    } finally { resetInputs(); }
}

function onboardingStopOSINT() {
    if (_onboardingStreamCtl) { _onboardingStreamCtl.abort(); _onboardingStreamCtl = null; }
}

function showOnboardingActions() {
    var actionsDiv = $('onboarding-actions');
    actionsDiv.classList.remove('hidden');
    actionsDiv.innerHTML = '<button class="btn btn-primary" onclick="onboardingSaveAndContinue()">✅ 保存到客户库</button><button class="btn" onclick="onboardingFinish()">进入主界面</button>';
}

async function onboardingSaveAndContinue() {
    var inputText = _onboardingInputText.trim();
    var customerName = inputText;
    var website = '';
    try {
        var url = new URL(inputText.startsWith('http') ? inputText : 'https://' + inputText);
        customerName = url.hostname.replace(/^www\./, '').split('.')[0];
        website = url.hostname;
    } catch(_) {}
    var body = { name: customerName, note: _onboardingOsinResponse };
    if (website) body.company_website = website;
    var r = await api('POST', '/api/trade/customers', body);
    if (r?.id) { toast('客户已保存到客户库'); onboardingFinish(); }
    else toast(r?.detail || '保存失败，请重试');
}

function onboardingFinish() {
    try { localStorage.setItem('_onboarding_completed', '1'); } catch(_) {}
    navToView('chat', 'daily', '今日简报');
}

function restartOnboarding() {
    // 清除引导完成标记，重新启动新手引导
    try { localStorage.removeItem('_onboarding_completed'); } catch(_) {}
    showOnboardingGuide();
}

function onboardingSkip(e) {
    if (e) e.preventDefault();
    // 标记已完成 — 引导是可选的，跳过就不再显示
    try { localStorage.setItem('_onboarding_completed', '1'); } catch(_) {}
    navToView('chat', 'daily', '今日简报');
}

// ═════════════════════ COMPANY MANAGEMENT ═════════════════════
function showAddCompanyModal() {
    switchModalTab('tab-companies');
    showModal('company-modal');
    loadCompanyListUI();
}

function switchModalTab(tab) {
    $('tab-companies').classList.toggle('hidden', tab !== 'tab-companies');
    $('tab-identity').classList.toggle('hidden', tab !== 'tab-identity');
    $('tab-btn-companies').classList.toggle('active', tab === 'tab-companies');
    $('tab-btn-identity').classList.toggle('active', tab === 'tab-identity');
    if (tab === 'tab-identity') loadIdentityForCurrentCompany();
}

async function loadCompanies() {
    const prev = currentCompanyId;
    companies = await api('GET', '/api/trade/companies') || [];
    const sel = $('company-select');
    sel.innerHTML = '<option value="">— 选择公司 —</option>' +
        companies.map(c => `<option value="${c.id}" ${c.id===prev?'selected':''}>${esc(c.name)}</option>`).join('');
    if (prev && !companies.find(c=>c.id===prev)) {
        // Previously selected company was deleted
        currentCompanyId = null;
        saveState();
    }
}

function loadCompanyListUI() {
    const container = $('company-list-ui');
    if (!companies.length) {
        container.innerHTML = '<p style="color:var(--text-muted);font-size:13px;">暂无公司，请下方创建。</p>';
        return;
    }
    container.innerHTML = companies.map(c => `
        <div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border-light);">
            <div style="flex:1;"><div style="font-weight:600;font-size:13px;">${esc(c.name)}</div>
            <div style="font-size:11px;color:var(--text-muted);">${esc(c.slug)} · ${c.contact_email ? ' · ' + esc(c.contact_email) : ''}</div></div>
            <button class="btn btn-danger btn-xs" onclick="deleteCompany(${c.id})">删除</button>
        </div>`).join('');
}

function autoSlug() {
    const name = $('co-name').value.trim();
    const slugEl = $('co-slug');
    if (!name) {
        slugEl.value = '';
        slugEl.placeholder = '自动生成';
        slugEl.style.color = 'var(--text-muted)';
        return;
    }
    // 前端实时生成 slug 预览（与后端的 _slugify 逻辑一致）
    let s = name.toLowerCase()
        .replace(/[^\w\s-]/g, '')
        .replace(/[\s_]+/g, '-')
        .replace(/--+/g, '-')
        .replace(/^-|-$/g, '') || 'company';
    slugEl.value = s;
    slugEl.style.color = '';
}

async function createCompany() {
    const name = $('co-name').value.trim();
    if (!name) { toast('请填写公司名称'); return; }
    const slug = $('co-slug').value.trim();
    const body = {name};
    if (slug) body.slug = slug;
    ['contact_name','contact_email','website'].forEach(f => {
        const elId = 'co-' + f.replace(/_/g, '-');
        const v = (document.getElementById(elId)?.value || '').trim();
        if (v) body[f] = v;
    });
    const r = await api('POST', '/api/trade/companies', body);
    if (r?.id) {
        if (r.work_dir_is_new === false) {
            toast(`桌面目录已存在，已创建为：${r.work_dir.split('/').pop()}`);
        } else {
            toast('公司创建成功，桌面工作目录已就绪');
        }
        ['co-name','co-slug','co-contact-name','co-contact-email','co-website'].forEach(id=>$(id).value='');
        await loadCompanies();
        onCompanyChange(r.id);
    } else toast(r?.detail||'创建失败');
}

async function deleteCompany(id) {
    if (!confirm('确定停用该公司？数据将保留 30 天后自动清理。')) return;
    const r = await api('DELETE', `/api/trade/companies/${id}`);
    if (r?.ok) { toast('已删除'); if (currentCompanyId===id) onCompanyChange(''); await loadCompanies(); loadCompanyListUI(); }
    else toast(r?.detail||'删除失败');
}

async function onCompanyChange(cid) {
    // 清空视图缓存
    for (const key in viewCache) {
        viewCache[key].element.remove();
        delete viewCache[key];
    }
    // 中止进行中的新手引导流，防止 reader 泄漏
    if (_onboardingStreamCtl) { _onboardingStreamCtl.abort(); _onboardingStreamCtl = null; }
    // 清空 cron 输出记录，防止跨公司污染
    _shownCronOutputs = new Set();
    if (cid) {
        const newCid = parseInt(cid);
        // 先更新前端状态（让后续 API 调用带上正确的 X-Company-ID header）
        currentCompanyId = newCid;
        // 通知后端切换 session 绑定（旧 cid 会触发 403，因此 _enforce_company_binding 需放行 /switch 端点）
        try { await api('POST', '/api/trade/companies/' + newCid + '/switch'); } catch(_) {}
        saveState();
        // 首个公司 + 引导未完成 → 显示新手引导
        if (companies.length === 1 && !isOnboardingCompleted()) {
            showOnboardingGuide();
            return;
        }
        navToView('chat', 'daily', '今日简报');
    } else {
        currentCompanyId = null;
        saveState();
        renderNoCompanyPage();
    }
}

async function loadIdentityForCurrentCompany() {
    if (!currentCompanyId) return;
    const r = await api('GET', `/api/trade/companies/${currentCompanyId}/agent-identity`);
    if (r) $('identity-editor').value = r.agent_identity_md || '';
}

async function saveCompanyIdentity() {
    if (!currentCompanyId) return;
    const identity = $('identity-editor').value;
    const r = await api('PUT', `/api/trade/companies/${currentCompanyId}/agent-identity`, {agent_identity_md:identity});
    if (r?.company_id) { toast('身份配置已保存'); hideModal('company-modal'); }
    else toast(r?.detail||'保存失败');
}

// ═════════════════════ INIT ═════════════════════
document.addEventListener('DOMContentLoaded', async () => {
    // 初始化语言
    initLang();

    // 检测是否刚完成系统升级（页面 reload 后显示 toast）
    try {
        if (sessionStorage.getItem('_trade_upgrade_done')) {
            sessionStorage.removeItem('_trade_upgrade_done');
            setTimeout(() => toast('✅ 系统更新完成！'), 500);
        }
    } catch(_) {}

    // 许可证状态检查
    loadLicenseStatus();

    try {
        await loadCompanies();
    } catch(e) {
        console.error('Init loadCompanies failed:', e);
    }
    const savedCid = loadSavedCid();
    if (savedCid && companies.find(c => c.id === savedCid)) {
        currentCompanyId = savedCid;
    } else if (companies.length === 1) {
        currentCompanyId = companies[0].id;
    }

    // 检测重启前保存的浏览状态（避免 hard reload 丢失阅读位置）
    const reloadState = _restoreReloadState();

    if (currentCompanyId) {
        saveState();
        const sel = $('company-select');
        if (sel) sel.value = currentCompanyId;
        // 首个公司 + 引导未完成 → 显示新手引导
        if (companies.length === 1 && !isOnboardingCompleted()) {
            showOnboardingGuide();
            startCronPolling();
            startVersionCheck();
            return;
        }
        // 恢复之前的视图或默认打开今日简报
        const restoreView = reloadState?.view || 'chat';
        const restoreCtx = reloadState?.chatCtx || 'daily';
        const restoreName = reloadState?.chatName || '今日简报';
        navToView(restoreView, restoreCtx, restoreName);
        // 恢复滚动位置（等 DOM 渲染完成后）
        if (reloadState?.scrollY > 0) {
            setTimeout(() => { window.scrollTo({ top: reloadState.scrollY, behavior: 'instant' }); }, 200);
        }
        startCronPolling();
        startVersionCheck();
    } else {
        renderNoCompanyPage();
    }
});

// 页面关闭时清理轮询
window.addEventListener('beforeunload', () => { stopCronPolling(); stopVersionCheck(); });

function renderNoCompanyPage() {
    // 清除视图缓存
    for (const key in viewCache) {
        viewCache[key].element.remove();
        delete viewCache[key];
    }
    $('main-content').innerHTML = `<div class="empty-state"><div class="empty-icon">🏢</div><h2>请先选择或创建公司</h2><p>Trade AI 为多公司隔离架构</p><button onclick="showAddCompanyModal()">➕ 创建公司</button></div>`;
}
