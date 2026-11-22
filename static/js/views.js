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
                <button onclick="editTemplatePrompt('${t.id}')" style="font-size:11px;">${btnIcon('pencil')} 编辑 Prompt</button>
                <button onclick="runSingleTemplate('${t.id}')" style="font-size:11px;">▶ 执行一次</button>
            </div>
        </div>`;
    };

    container.innerHTML = `
    <div class="panel-view" style="display:flex;flex-direction:column;height:100%;overflow-y:auto;">
        <div class="panel-topbar">
            <h2>⏰ 定时任务${coName ? `<span style="margin-left:10px;padding:3px 10px;background:rgba(59,130,246,0.08);color:var(--primary);border-radius:999px;font-size:12px;font-weight:500;">🏢 ${esc(coName)}</span>` : ''}</h2>
            <div class="panel-topbar-actions">
                <button class="btn btn-primary" onclick="batchCreateCronTasks()">${btnIcon('refresh-cw')} 批量生成选中任务</button>
                <button class="btn btn-danger" onclick="clearAllCronTasks()">${btnIcon('trash')} 清空全部任务</button>
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
                <button class="btn btn-xs" onclick="showAddCustomTemplateModal()" style="color:var(--primary);">${btnIcon('plus')} 自定义模板</button>
            </div>
            <div class="task-grid" id="task-templates-grid">
                ${allTemplates.map(renderCard).join('')}
            </div>

            <!-- 分隔线 -->
            <hr style="border:none;border-top:2px dashed var(--border);margin:20px 0;">

            <!-- 已激活任务 -->
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                <div style="font-size:13px;font-weight:600;color:var(--text-secondary);">📡 已激活的定时任务</div>
                <button class="btn btn-xs" onclick="loadActiveCronJobs()">${btnIcon('refresh-cw')} 刷新</button>
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
            })(arguments[0])">${btnIcon('check')} 保存</button>
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
            <button class="btn btn-primary" onclick="saveCustomTemplate()">${btnIcon('check')} 保存模板</button>
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
                <button onclick="runActiveJob(${escJs(j.id)})">▶ 立即执行</button>
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
                <button class="btn" onclick="toast('功能开发中：将在文件管理器中打开')">${btnIcon('folder-open')} 打开目录</button>
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
            <div class="quality-bar" id="quality-bar" style="display:none;"></div>
            <div class="conv-list" id="conv-list">
                <div class="loading-row"><div class="spinner"></div>加载对话记录...</div>
            </div>
        </div>`;
    await loadConversations();
    loadQualityStats();
}

// 质量概览（rating 闭环）：近 30 天评分总数 / 均分 / 低分最多的技能
async function loadQualityStats() {
    const bar = $('quality-bar');
    if (!bar || !currentCompanyId) return;
    const s = await api('GET', '/api/trade/conversations/quality-stats?days=30');
    // 无评分数据时不占位（新用户/未评分公司）
    if (!s || !s.total_rated) { bar.style.display = 'none'; return; }
    // by_skill 已按「低分优先」排序，取第一个有低分的技能作为待改进项
    const worst = (s.by_skill || []).find(x => x.low_count > 0);
    let txt = `📊 ${t('quality.rated')} ${s.total_rated} · ${t('quality.avg')} ${s.avg_rating}`;
    if (worst) txt += ` · ${t('quality.worst')} ${worst.skill} (👎×${worst.low_count})`;
    // 用 textContent 赋值，避免技能名/上下文注入 HTML
    bar.textContent = txt;
    bar.style.display = 'block';
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
                onclick="event.stopPropagation();deleteConversation(${c.id})" title="${t('hist.delete_title')}">${btnIcon('trash')}</button>
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
    _replaceMainContent(`<div id="onboarding-panel" class="onboarding-panel"><div class="onboarding-card" id="onboarding-card">${renderOnboardingStep1HTML()}</div></div>`);
}

function renderOnboardingStep1HTML() {
    return `<div id="onboarding-step1"><div class="onboarding-icon">🎉</div><h2 class="onboarding-title">欢迎使用 Trade AI</h2><p class="onboarding-subtitle">Trade 可以帮你<strong>自动搜索客户背景信息（OSINT）</strong>，并基于你的产品定位<strong>撰写专业 B2B 开发信</strong>。</p><div class="onboarding-features"><div class="onb-feature"><span>🔍</span> 海关数据 · 社媒分析 · 官网诊断</div><div class="onb-feature"><span>📧</span> AI 写开发信 · 跟进序列 · 报价单</div><div class="onb-feature"><span>🤖</span> 7x24 自动获客 · 定时任务调度</div></div><button class="btn btn-primary btn-lg" onclick="onboardingGoToStep2()">${btnIcon('target')} 开发第一个客户</button><div class="onboarding-skip"><a href="#" onclick="onboardingSkip(event)">跳过引导，直接开始</a></div></div>`;
}

function renderOnboardingStep2HTML() {
    return `<div id="onboarding-step2"><div class="onboarding-step-indicator"><span class="onb-step done">✓ 了解 Trade</span><span class="onb-step-arrow">→</span><span class="onb-step active">● 开发客户</span></div><h3 class="onboarding-title" style="font-size:18px;margin-bottom:6px;">试试对目标客户做背调</h3><p style="color:var(--text-secondary);font-size:13px;margin-bottom:16px;">输入客户公司名或官网，AI 将自动搜索公开信息并生成开发信</p><div class="onboarding-input-row"><input type="text" id="onboarding-osint-input" placeholder="粘贴客户公司名或网址，如：acme-corp.com" class="onboarding-text-input" onkeydown="if(event.key==='Enter')onboardingStartOSINT()" autofocus /><button class="btn btn-primary" id="onboarding-send-btn" onclick="onboardingStartOSINT()">开始分析</button><button id="onboarding-stop-btn" class="hidden" style="background:var(--accent-red);color:#fff;border:none;padding:8px 16px;border-radius:var(--radius-sm);cursor:pointer;" onclick="onboardingStopOSINT()">${btnIcon('x')} 停止</button></div><div id="onboarding-results-area"></div><div id="onboarding-actions" class="hidden"></div><div class="onboarding-skip"><a href="#" onclick="onboardingSkip(event)">跳过引导，直接开始</a></div></div>`;
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
    progDiv.innerHTML = '<div class="wait-body"></div>';
    resultsArea.appendChild(progDiv);
    var wait = null;
    try {
        if (typeof TradeWait !== 'undefined') {
            wait = TradeWait.mount(progDiv.querySelector('.wait-body'), {
                mode: 'chat',
                title: 'TRADE · ONBOARDING  ///  等待回复',
                onCancel: function () { onboardingStopOSINT(); }
            });
        }
    } catch (e) {
        console.warn('引导页等待界面挂载失败，使用旧样式', e);
        wait = null;
    }
    if (!wait) progDiv.innerHTML = '<div class="thinking-msg">💭 '+t('misc.thinking')+'</div>';
    var onbStopBtn = $('onboarding-stop-btn');
    if (onbStopBtn) { if (wait) onbStopBtn.classList.add('hidden'); else onbStopBtn.classList.remove('hidden'); }
    var toolEls = {};
    var progressDiv = null;
    var responseText = '';
    function ensureProgress() {
        if (!progressDiv) { progressDiv = document.createElement('div'); progressDiv.className = 'tool-progress'; progDiv.appendChild(progressDiv); }
        return progressDiv;
    }
    function addToolItem(tcId, name, status) {
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
        // 工具参数（args）可能含客户资料，不显示
        body.appendChild(nameEl);
        el.appendChild(icon);
        el.appendChild(body);
        div.appendChild(el);
        resultsArea.scrollTop = resultsArea.scrollHeight;
        toolEls[tcId] = el;
    }
    function updateTool(tcId, status) {
        var el = toolEls[tcId]; if (!el) return;
        el.className = 'tool-item ' + status;
        var icon = el.querySelector('.tool-icon'); if (icon) icon.textContent = status==='running'?'◌':status==='done'?'✓':'✗';
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
        if (!resp.ok) {
            progDiv.remove();
            if (resp.status === 402) {
                var err402 = await resp.json().catch(function() { return {}; });
                showLicenseExpired(err402.detail || t('license.expired'));
            } else {
                resultsArea.innerHTML = '<div class="onb-error">请求失败 (' + resp.status + ')</div>';
            }
            resetInputs();
            return;
        }
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
                            if (wait) wait.push({type:'tool_start', id:data.tool_call_id, label:fmtTool(data.name)});
                            else addToolItem(data.tool_call_id, data.name, 'running');
                            break;
                        case 'tool_complete':
                            if (wait) wait.push({type:'tool_complete', id:data.tool_call_id});
                            else updateTool(data.tool_call_id, 'done');
                            break;
                        case 'thinking':
                            if (wait) wait.push({type:'thinking', message:data.message});
                            break;
                        case 'job_attached':
                            // 引导页背调同样挂 task 面板（后端 B1）
                            _attachOsintTaskPanel(resultsArea, data);
                            break;
                        case 'response':
                            responseText = data.text || '';
                            if (wait) { wait.destroy(); wait = null; }
                            break;
                        case 'error':
                            if (wait) { wait.finish({phase:'failed'}); wait = null; }
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
        if (e.name === 'AbortError') {
            // 有等待面板时留在原地显示 ABORTED
            if (wait) { wait.finish({phase:'aborted'}); wait = null; }
            else { progDiv.remove(); resultsArea.innerHTML = '<div class="onb-info">已停止生成。</div>'; }
        } else {
            if (wait) { wait.finish({phase:'failed'}); wait = null; }
            progDiv.remove();
            resultsArea.innerHTML = '<div class="onb-error">网络错误：' + esc(e.message) + '</div>';
        }
    } finally {
        if (wait && !wait.final) { try { wait.destroy(); } catch (_) {} }
        resetInputs();
    }
}

function onboardingStopOSINT() {
    if (_onboardingStreamCtl) { _onboardingStreamCtl.abort(); _onboardingStreamCtl = null; }
}

function showOnboardingActions() {
    var actionsDiv = $('onboarding-actions');
    actionsDiv.classList.remove('hidden');
    actionsDiv.innerHTML = '<button class="btn btn-primary" onclick="onboardingSaveAndContinue()">' + btnIcon('check') + ' 保存到客户库</button><button class="btn" onclick="onboardingFinish()">进入主界面</button>';
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
            ${_licenseGateAllowsPaid() ? `<button class="btn btn-xs" onclick="exportCompany(${c.id})">导出</button>` : ''}
            <button class="btn btn-danger btn-xs" onclick="deleteCompany(${c.id})">删除</button>
        </div>`).join('');
}

// ── 公司数据导出 / 导入 ─────────────────────────────────────────────
let _pendingImportFile = null;
// 两阶段导入：预检返回的 upload_id，确认导入时凭它取回临时包（30 分钟有效）
let _importUploadId = null;

function _downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || 'trade-company.zip';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
}

async function exportCompany(cid) {
    if (!confirm('导出包包含客户资料、对话、记忆和 Agent 身份，不包含桌面资料库文件（需自行拷贝），且未加密。请妥善保管。继续导出？')) return;
    const expBtn = document.querySelector('button[onclick="exportCompany(' + cid + ')"]');
    const restoreExp = (expBtn && typeof TradeWait !== 'undefined')
        ? TradeWait.inline(expBtn, {en: 'EXPORTING', zh: '打包中'}) : null;
    try {
        const resp = await fetch(`/api/trade/companies/${cid}/export`, {
            headers: {
                'X-Hermes-Session-Token': TOKEN,
                'X-Company-ID': String(cid),
            },
        });
        if (resp.status === 413) {
            const data = await resp.json().catch(() => ({}));
            alert('数据包过大，未自动打包。\n请手动拷贝：\n' + (data.paths || []).join('\n'));
            return;
        }
        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            toast('导出失败：' + (data.detail || resp.status));
            return;
        }
        // 桌面目录超限时包内不含资料库文件，后端通过响应头告知需手动拷贝的路径
        let exportNote = null;
        const warnHeader = resp.headers.get('X-Trade-Export-Warnings');
        if (warnHeader) {
            try {
                const info = JSON.parse(decodeURIComponent(warnHeader));
                if (info.manual_paths && info.manual_paths.length) {
                    exportNote = '数据包已导出，但桌面资料库文件不随包迁移。\n'
                        + '请按需手动拷贝以下目录，导入后放到目标机对应的公司桌面目录：\n'
                        + info.manual_paths.join('\n');
                } else if (info.warnings && info.warnings.length) {
                    exportNote = '导出完成，有提示：\n' + info.warnings.join('\n');
                }
            } catch(_) { /* 头解析失败不影响下载 */ }
        }
        const blob = await resp.blob();
        const cd = resp.headers.get('content-disposition') || '';
        const match = /filename="?([^";]+)"?/.exec(cd);
        _downloadBlob(blob, match ? decodeURIComponent(match[1]) : `trade-company-${cid}.zip`);
        if (exportNote) alert(exportNote);
        else toast('导出完成，请妥善保管数据包');
    } catch (err) {
        toast('导出失败：' + (err && err.message ? err.message : err));
    } finally {
        if (restoreExp) restoreExp();
    }
}

function showImportCompanyDialog() {
    // 导入/导出是付费能力：入口隐藏之外，这里再挡一次控制台直接调用
    if (!_licenseGateAllowsPaid()) {
        toast(t('license.paid_only'));
        return;
    }
    document.querySelectorAll('.import-company-backdrop').forEach(el => el.remove());
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop import-company-backdrop';
    backdrop.innerHTML = `
        <div class="modal" style="max-width:560px;">
            <h3>📦 导入公司数据</h3>
            <p style="font-size:12px;color:var(--text-muted);line-height:1.6;">
                选择从另一台电脑导出的 <code>.zip</code>。包内含客户资料、对话、记忆和 Agent 身份，未加密。<br>
                桌面资料库文件不在包内，如有需要请自行拷贝到目标机对应目录。<br>
                同名公司已存在时默认合并；如果只是同名但不是同一家公司，勾选下面的强制新建。
            </p>
            <label style="display:flex;align-items:center;gap:8px;font-size:12px;margin:10px 0;">
                <input type="checkbox" id="imp-force-new"> 同名但不是同一家公司，强制新建（请先勾选，再选择文件）
            </label>
            <input type="file" id="imp-file" accept=".zip" style="width:100%;margin:10px 0;">
            <div id="imp-status" style="font-size:12px;color:var(--text-secondary);white-space:pre-wrap;line-height:1.6;min-height:40px;"></div>
            <div class="form-actions">
                <button class="btn" onclick="this.closest('.modal-backdrop').remove()">关闭</button>
            </div>
        </div>`;
    document.body.appendChild(backdrop);
    document.getElementById('imp-file').addEventListener('change', (event) => {
        const file = event.target.files && event.target.files[0];
        if (!file) return;
        _pendingImportFile = file;
        const forceNew = document.getElementById('imp-force-new').checked;
        uploadCompanyImport(file, null, forceNew);
    });
}

async function uploadCompanyImport(file, targetCompanyId, forceNew) {
    const status = document.getElementById('imp-status');
    if (status) status.textContent = '正在分析数据包，请勿关闭页面…';
    // 合并到非当前公司时先切换 session 绑定：导入端点会拒绝「绑定 A 却写 B」
    if (targetCompanyId && targetCompanyId !== currentCompanyId) {
        const switched = await api('POST', '/api/trade/companies/' + targetCompanyId + '/switch').catch(() => null);
        // 切换失败：停止上传，避免带着旧绑定去写另一个公司
        if (!switched) {
            if (status) status.textContent = '切换目标公司失败，请重试。';
            return;
        }
        currentCompanyId = targetCompanyId;
        saveState();
    }
    const fd = new FormData();
    fd.append('file', file);
    // 两阶段导入：先只读预检，列出同名客户冲突，用户逐对决定后再确认
    fd.append('preflight', 'true');
    if (targetCompanyId) fd.append('target_company_id', String(targetCompanyId));
    if (forceNew) fd.append('force_new', 'true');
    try {
        const resp = await fetch('/api/trade/companies/import-package', {
            method: 'POST',
            headers: { 'X-Hermes-Session-Token': TOKEN },
            body: fd,
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            // 公司级歧义（多个同名公司）：和 job 阶段一样用 prompt() 让用户指定目标，再重新预检
            if (resp.status === 409 && data.candidates) {
                const list = (data.candidates || [])
                    .map(function (c) { return c.id + ': ' + c.name + ' (' + c.slug + ')'; })
                    .join('\n');
                const answer = prompt('目标机有多个同名公司，请输入要合并的公司 ID：\n' + list);
                const targetId = parseInt(answer, 10);
                // 用户给了有效 ID：清掉旧的上传状态，带目标公司重新预检
                if (targetId) {
                    _importUploadId = null;
                    uploadCompanyImport(_pendingImportFile || file, targetId, false);
                } else if (status) {
                    // 用户取消：保留文件选择，提示后可再次选文件重试
                    status.textContent = '已取消：未选择目标公司';
                }
                return;
            }
            // 其它失败（非 zip / 过大 / 包不合规）：显示原因并清空选择以便重试
            if (status) status.textContent = '导入失败：' + (data.detail || resp.status);
            // 清空选择：否则重新选同一个文件不会触发 change，用户无法重试
            const inp = document.getElementById('imp-file');
            if (inp) inp.value = '';
            return;
        }
        // 预检成功：交给冲突渲染决定「无冲突直接确认」还是「逐对选择」
        _renderImportConflicts(data);
    } catch (err) {
        if (status) status.textContent = '导入失败：' + (err && err.message ? err.message : err);
        const inp = document.getElementById('imp-file');
        if (inp) inp.value = '';
    }
}

function _renderImportConflicts(data) {
    /** 预检结果：无冲突直接确认；有冲突渲染逐对选择（2026-11-20 审计 C2）。 */
    const status = document.getElementById('imp-status');
    _importUploadId = data.upload_id;

    // 无冲突：与今天一样的「一键导入」体验
    if (!data.conflicts || !data.conflicts.length) {
        if (status) status.textContent = '未发现同名客户，开始导入…';
        _confirmImport([]);
        return;
    }

    if (status) {
        // 每个冲突一行：左侧源客户名，右侧选择「合并到目标」或「新建为提议名」
        const rows = data.conflicts.map(function (c) {
            // 后端没算新名字时兜底为「原名 (2)」，避免出现空选项
            const newName = c.proposed_new_name || ((c.source_name || '') + ' (2)');
            return '<div class="imp-conflict" data-source-id="' + esc(String(c.source_id)) + '">' +
                '<div class="imp-conflict-name">' + esc(c.source_name || '') + '</div>' +
                '<select data-role="imp-action">' +
                '<option value="merge">合并到「' + esc(c.target_name || '') + '」</option>' +
                '<option value="create">新建为「' + esc(newName) + '」</option>' +
                '</select></div>';
        }).join('');
        status.innerHTML =
            '<div class="imp-conflict-title">发现 ' + esc(String(data.conflicts.length)) + ' 个同名客户，请逐个选择：</div>' +
            rows +
            '<div class="imp-conflict-actions">' +
            '<button type="button" class="btn btn-xs" data-imp-bulk="merge">全部合并</button>' +
            '<button type="button" class="btn btn-xs" data-imp-bulk="create">全部新建</button>' +
            '<button type="button" class="btn btn-primary btn-xs" id="imp-confirm-btn">开始导入</button>' +
            '</div>';
    }

    // 批量按钮：把每行的 select 统一设成同一动作
    document.querySelectorAll('[data-imp-bulk]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const action = btn.getAttribute('data-imp-bulk');
            document.querySelectorAll('select[data-role="imp-action"]').forEach(function (sel) {
                sel.value = action;
            });
        });
    });
    // 开始导入：收集逐对选择后确认
    document.getElementById('imp-confirm-btn')?.addEventListener('click', function () {
        // 逐行读取，batch 按钮只是「预填」，最终仍以用户的逐对选择为准
        const decisions = Array.prototype.map.call(
            document.querySelectorAll('.imp-conflict'),
            function (el) {
                return {
                    source_id: Number(el.getAttribute('data-source-id')),
                    action: el.querySelector('select[data-role="imp-action"]').value,
                };
            },
        );
        _confirmImport(decisions);
    });
}

async function _confirmImport(decisions) {
    /** 用预检结果 + 逐对选择开始导入。 */
    const status = document.getElementById('imp-status');
    // 没有 upload_id：预检没跑完或状态被清掉，只能让用户重新选文件
    if (!_importUploadId) {
        if (status) status.textContent = '导入链接已失效，请重新选择文件。';
        return;
    }
    if (status) status.textContent = '正在导入，请勿关闭页面…';
    try {
        const resp = await fetch(
            '/api/trade/companies/import-package/' + encodeURIComponent(_importUploadId) + '/confirm',
            {
                method: 'POST',
                headers: {
                    'X-Hermes-Session-Token': TOKEN,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({customer_decisions: decisions}),
            },
        );
        const data = await resp.json().catch(function () { return {}; });
        if (!resp.ok) {
            // 过期：upload_id 已被清掉，链接不能再用，提示重选文件
            if (resp.status === 410) {
                if (status) status.textContent = '导入链接已过期，请重新选择文件。';
            } else if (resp.status === 409) {
                // 409：另一请求正在导入，或还有未选择的冲突
                if (status) status.textContent = data.detail || '导入正在进行中，请稍候。';
            } else {
                // 其它错误：显示后端原因，让用户可重试
                if (status) status.textContent = '导入失败：' + (data.detail || resp.status);
            }
            // 清空选择：确认失败后让用户能重新选同一个文件发起新一轮预检
            const inp = document.getElementById('imp-file');
            if (inp) inp.value = '';
            return;
        }
        // 确认成功：upload_id 已消耗，轮询后台任务进度
        _importUploadId = null;
        pollImportJob(data.job_id);
    } catch (err) {
        if (status) status.textContent = '导入失败：' + (err && err.message ? err.message : err);
        const inp = document.getElementById('imp-file');
        if (inp) inp.value = '';
    }
}

async function pollImportJob(jobId) {
    const status = document.getElementById('imp-status');
    // task 模式面板：阶段只跟着真实的 status/phase 走，不估算、不显示百分比
    let wait = null;
    if (status && status.parentNode && typeof TradeWait !== 'undefined') {
        const host = document.createElement('div');
        host.className = 'wait-import-host';
        status.parentNode.insertBefore(host, status);
        try {
            wait = TradeWait.mount(host, {
                mode: 'task',
                title: '导入公司数据包',
                statusLabel: '导入公司数据包',
                cancelText: '关闭',
                onCancel: function () {}
            });
            wait.phase('working', '排队中');
        } catch (e) { console.warn('导入等待面板挂载失败', e); wait = null; }
    }
    for (let i = 0; i < 1800; i++) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        let data = null;
        try {
            const resp = await fetch(`/api/trade/companies/import-package/${jobId}`, {
                headers: { 'X-Hermes-Session-Token': TOKEN },
            });
            data = await resp.json();
            if (!resp.ok) {
                // 任务只存在进程内存里：服务重启后 404，再轮询 30 分钟也没用
                if (wait) wait.finish({phase: 'failed'});
                if (status) {
                    status.textContent = resp.status === 404
                        ? '导入任务已失效（服务可能重启过），请刷新页面后检查公司列表。'
                        : '查询导入状态失败：' + (data.detail || resp.status);
                }
                return;
            }
        } catch (err) {
            continue;
        }
        if (!data) continue;
        if (data.status === 'done') {
            const report = data.report || {};
            if (wait) wait.finish({phase: 'acquired', zh: '导入完成'});
            if (status) {
                status.textContent = '导入完成：' + (report.mode === 'created' ? '已新建公司' : '已合并到已有公司')
                    + '（' + ((report.target && report.target.name) || '') + '）\n'
                    + '客户 +' + ((report.tables && report.tables.customers && report.tables.customers.inserted) || 0)
                    + '，对话 +' + ((report.tables && report.tables.conversations && report.tables.conversations.inserted) || 0)
                    + '，订单 +' + ((report.tables && report.tables.orders && report.tables.orders.inserted) || 0)
                    + '，文件 ' + ((report.files && report.files.copied) || 0) + ' 个'
                    + (report.memory && report.memory.added ? '，记忆 +' + report.memory.added : '');
                // 导出时跳过的资料库文件：这里给出目标机的精确落盘位置
                if (report.warnings && report.warnings.length) {
                    status.textContent += '\n⚠️ ' + report.warnings.join('\n');
                }
            }
            await loadCompanies();
            if (report.target && report.target.id) {
                await onCompanyChange(report.target.id);
            }
            setTimeout(() => {
                const backdrop = document.querySelector('.import-company-backdrop');
                if (backdrop) backdrop.remove();
            }, 2000);
            return;
        }
        if (data.status === 'error') {
            if (wait) wait.finish({phase: 'failed'});
            if (data.code === 'ambiguous_company') {
                // prompt() 是纯文本，不能走 esc()（HTML 转义会把 A&B 显示成 A&amp;B），
                // 也不用模板插值，免得 XSS 守卫把它当成 innerHTML 渲染点
                const list = (data.candidates || [])
                    .map(function (c) { return c.id + ': ' + c.name + ' (' + c.slug + ')'; })
                    .join('\n');
                const answer = prompt('目标机有多个同名公司，请输入要合并的公司 ID：\n' + list);
                const targetId = parseInt(answer, 10);
                if (targetId && _pendingImportFile) {
                    uploadCompanyImport(_pendingImportFile, targetId, false);
                } else if (status) {
                    status.textContent = '已取消：未选择目标公司';
                }
                return;
            }
            if (status) status.textContent = '导入失败：' + (data.error || '未知错误');
            return;
        }
        if (wait) wait.phase('working', data.phase === 'queued' ? '排队中' : '正在导入');
        if (status) status.textContent = '导入中…（' + (data.phase || data.status) + '）';
    }
    if (wait) wait.finish({phase: 'failed', zh: '导入超时'});
    if (status) status.textContent = '导入超时，请查看日志或重试。';
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
        // 创建成功即关闭弹窗 —— 不需要用户再点一次「关闭」
        hideModal('company-modal');
        await loadCompanies();
        onCompanyChange(r.id);
    } else toast(r?.detail||'创建失败');
}

async function deleteCompany(id) {
    if (!confirm('确定停用该公司？数据将保留 30 天后自动清理。')) return;
    // 后端要求 X-Confirm-Delete: yes，否则 400（审计 P1-8）
    const r = await api('DELETE', `/api/trade/companies/${id}`, null, {
        'X-Confirm-Delete': 'yes',
    });
    if (r?.ok) { toast('已停用'); if (currentCompanyId===id) onCompanyChange(''); await loadCompanies(); loadCompanyListUI(); }
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
    // 中止进行中的聊天流：否则它会继续消耗 token，且结束后把回复写进新公司的会话窗口
    _abortChatStream();
    // 清空 cron 输出记录，防止跨公司污染
    _shownCronOutputs = new Set();
    // 清空"当前选中的库/客户"——它们是**上一家公司**的 id。留着会让下一次
    // 发消息把旧库塞进请求体：后端按新公司过滤后查不到（不会串数据），
    // 但 build_query 仍会走文档库分支注入 doc_context → 每次对话多付
    // 约 5700 token，并让 Agent 去扫一个不属于当前公司的目录。
    currentLibraryId = null;
    currentCustomerId = null;
    if (cid) {
        const newCid = parseInt(cid);
        const prevCid = currentCompanyId;
        // 先更新前端状态（让后续 API 调用带上正确的 X-Company-ID header）
        currentCompanyId = newCid;
        // 通知后端切换 session 绑定（旧 cid 会触发 403，因此 _enforce_company_binding 需放行 /switch 端点）。
        // 网络异常时 api() 会 throw；.catch 折算成 null，与 HTTP 失败走同一条回滚，
        // 否则前端显示新公司、后端仍绑旧公司，后续每个请求都 403（审计 O-7）。
        const switched = await api('POST', '/api/trade/companies/' + newCid + '/switch').catch(() => null);
        if (!switched) {
            // 切换失败：回滚前端选中，避免后续请求带着未绑定的公司 ID
            currentCompanyId = prevCid;
            const sel = $('company-select');
            if (sel && prevCid != null) sel.value = String(prevCid);
            toast('切换公司失败，请重试');
            return;
        }
        saveState();
        loadUsageToday();
        // 首个公司 + 引导未完成 → 显示新手引导
        if (companies.length === 1 && !isOnboardingCompleted()) {
            showOnboardingGuide();
            return;
        }
        navToView('chat', 'daily', '今日简报');
    } else {
        currentCompanyId = null;
        saveState();
        loadUsageToday();
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

// ═════════════════════ HERMES 版本过旧 → 升级面板 ═════════════════════
// Trade 进程内嵌 Hermes：Hermes 版本过旧时 agent 功能全废。桌面端（tradewin）用户
// 看不到终端，所以必须有个界面把「出什么问题 / 正在做什么 / 现在该做什么」讲清楚。
// 自动升级由后端在启动时已经拉起，这里只负责显示进度、失败重试、成功后刷新。
// #region hermes-upgrade

const HERMES_UPGRADE_TEXT = {
    idle:             {icon:'⬆️', title:'准备升级 Hermes', message:'Trade 需要更新版本的 Hermes，正在准备升级…'},
    checking_network: {icon:'🔍', title:'正在检查网络',    message:'正在确认能否访问 GitHub…'},
    upgrading:        {icon:'⬆️', title:'正在升级 Hermes', message:'升级进行中，请勿关闭 Trade。这一步可能需要几分钟。'},
    done:             {icon:'✅', title:'升级完成',        message:'Hermes 已升级完成。请点击「重启 Trade」使新版本生效。'},
    offline:          {icon:'🌐', title:'需要先开启代理',  message:'无法访问 GitHub，升级没有开始。请开启代理（VPN）后点「重试」。'},
    failed:           {icon:'⚠️', title:'升级失败',        message:'Hermes 没有升级成功。请确认网络通畅后点「重试」。'},
    // 不是「升级 Hermes」能解决的问题：Hermes 已经是新版，旧的是 Trade 自己的运行环境。
    // 用独立文案，否则会显示「正在准备升级 Hermes」把用户引到一条没结果的路上去
    // （2026-10-15 客户机实测：那一版就是这么卡住的）。
    rebuild_needed:   {icon:'🧰', title:'Trade 需要重建运行环境', message:'你的 Hermes 已经是新版，但 Trade 的运行环境还是旧的。点下面的按钮重建一次即可，数据不会丢。'},
    // 重建进行中：服务已经被停掉（否则换不了 venv），所以这一段界面是「最后一屏」——
    // 用户接下来看到的是轮询等待，不是进度条。文案必须说清「会自己回来」，否则他会以为卡死。
    rebuilding:       {icon:'🧰', title:'正在重建运行环境', message:'正在重装 Trade 的运行环境（约 5~10 分钟），期间 Trade 会暂时打不开。完成后页面会自动刷新，请不要关闭。'},
};

let _hermesUpgradeAbort = null;
let _hermesWait = null;

/** 升级等待面板：task 模式；读数行来自真实日志，先过滤路径与长 token。 */
function _mountHermesWait() {
    if (_hermesWait && _hermesWait.final) {
        try { _hermesWait.destroy(); } catch (e) {}
        _hermesWait = null;
    }
    if (_hermesWait) return _hermesWait;
    const host = $('hermes-upgrade-wait');
    if (!host || typeof TradeWait === 'undefined') return null;
    try {
        _hermesWait = TradeWait.mount(host, {
            mode: 'task',
            title: 'Hermes 升级 · UPGRADE',
            statusLabel: 'Hermes 升级中',
            cancelText: '收起',
            onCancel: function () {}
        });
        _hermesWait.phase('working', '升级中');
    } catch (e) {
        console.warn('升级等待面板挂载失败', e);
        _hermesWait = null;
    }
    return _hermesWait;
}

function _hermesWaitLine(line) {
    if (!_hermesWait) return;
    // 隐私/噪声过滤：绝对路径与超长标识不进读数
    const safe = String(line || '')
        .replace(/[A-Za-z]:\\[^\s"']+/g, '[路径]')
        .replace(/(?:\/[\w.\-]+){2,}/g, '[路径]')
        .replace(/\b[A-Za-z0-9_\-]{32,}\b/g, '[token]')
        .slice(0, 120);
    if (safe) _hermesWait.note(safe);
}

/**
 * 启动时检查 Hermes 是否过旧；需要升级则显示面板并返回 true。
 * 调用方据此中断常规初始化 —— 此时聊天/公司数据都还用不了。
 *
 * 用裸 fetch 而不是 api()：本检查发生在公司选择之前，api() 会附带 X-Company-ID
 * 并在失败时弹 toast，两者在这里都不合适。
 */
async function checkHermesCompatOrShowPanel() {
    let compat = null;
    try {
        const r = await fetch('/api/trade/system/hermes-compat', {
            headers: {'X-Hermes-Session-Token': TOKEN}, cache: 'no-store',
        });
        if (r.ok) compat = await r.json();
    } catch(_) {}
    // Hermes 后台升级成功但 Trade 还没重启：提示手动重启（不自动重启）
    if (compat && compat.usable && compat.restart_required) {
        _showRestartPrompt();
        toast('✅ Hermes 升级完成，请点击「🔄 重启」使新版本生效。');
    }
    // 拿不到状态就不拦 —— 不能因为一个检查把整个软件挡在门外
    if (!compat || compat.usable) return false;
    showHermesUpgradePanel(compat);
    return true;
}

/** 显示升级面板，渲染已有状态，并开始消费进度流。 */
function showHermesUpgradePanel(compat) {
    const overlay = $('hermes-upgrade-overlay');
    if (!overlay) return;
    overlay.classList.remove('hidden');
    renderHermesUpgradeSteps(compat.steps || []);
    const upgrade = compat.upgrade || {status:'idle', message:''};
    // 需要「重建 Trade 运行环境」时后端**没有**升级任务在跑（升级 Hermes 也解决不了），
    // 所以要显示专属文案，而不是 upgrade.status 的默认态。
    //
    // ⚠️ 这条分支**不能**再启动进度流：重建场景下后端状态恒为 idle，流的第一个 state
    // 事件就是 {status:'idle'}，会把刚设好的标题盖回「准备升级 Hermes」—— 正好又变成
    // 我们要消灭的那种误导（2026-10-15 用户截图实证）。重建没有进度可看，也不需要流。
    if (compat.fix === 'rebuild_trade_venv' && !upgrade.running) {
        applyHermesUpgradeState({status:'rebuild_needed', message: compat.reason});
    } else {
        applyHermesUpgradeState(upgrade);
        _mountHermesWait();
        startHermesUpgradeStream(0);
    }
}

/** 渲染三条可照做的升级步骤；命令整行可选中，方便复制。 */
function renderHermesUpgradeSteps(steps) {
    const box = $('hermes-upgrade-steps');
    if (!box) return;
    box.innerHTML = '';
    if (!steps.length) return;
    steps.forEach(function(step, i) {
        const div = document.createElement('div');
        div.className = 'hermes-upgrade-step';
        const title = document.createElement('div');
        title.className = 'hermes-upgrade-step-title';
        title.textContent = (i + 1) + ') ' + (step.title || '');
        const detail = document.createElement('div');
        detail.className = 'hermes-upgrade-step-detail';
        detail.textContent = step.detail || '';
        const code = document.createElement('code');
        code.textContent = step.command || '';
        div.appendChild(title);
        div.appendChild(detail);
        div.appendChild(code);
        box.appendChild(div);
    });
}

/** 按状态刷新面板文案与按钮（文案集中在上面的 HERMES_UPGRADE_TEXT）。 */
function applyHermesUpgradeState(upgrade) {
    const status = upgrade.status || 'idle';
    const text = HERMES_UPGRADE_TEXT[status] || HERMES_UPGRADE_TEXT.idle;
    const icon = $('hermes-upgrade-icon'), title = $('hermes-upgrade-title');
    const msg = $('hermes-upgrade-message'), actions = $('hermes-upgrade-actions');
    if (icon) icon.textContent = text.icon;
    if (title) title.textContent = text.title;
    // 后端可能给出更具体的说明（如退出码），有就用它
    if (msg) msg.textContent = upgrade.message || text.message;
    if (!actions) return;
    actions.innerHTML = '';

    // 只在「停下来了」的失败态给重试按钮：运行中给按钮会让用户以为可以加速
    const canRetry = (status === 'failed' || status === 'offline');
    if (canRetry) {
        const btn = document.createElement('button');
        btn.className = 'btn btn-primary';
        btn.textContent = '重试升级';
        btn.onclick = function() { retryHermesUpgrade(); };
        actions.appendChild(btn);
    }
    // 需要重建运行环境：给「开始重建」按钮，取代原来让用户自己去终端粘一行 curl。
    // 客群是电脑小白，那一行对他们等于「软件坏了」—— 按钮才是他们能用的东西。
    // 下面的步骤指引仍保留（折叠在按钮之后），作为万一自动重建走不通时的手动兜底。
    if (status === 'rebuild_needed') {
        const btn = document.createElement('button');
        btn.className = 'btn btn-primary';
        btn.textContent = '开始重建';
        btn.onclick = function() { startVenvRebuild(btn); };
        actions.appendChild(btn);
    }
    // Hermes 升级成功不再自动重启：与系统更新一致，由用户点重启
    if (status === 'done') {
        const btn = document.createElement('button');
        btn.className = 'btn btn-primary';
        btn.textContent = '重启 Trade';
        btn.onclick = function() { doRestartTrade({currentTarget: btn}); };
        actions.appendChild(btn);
    }
    // 升级已在进行/已结束时，步骤指引不占地方（失败时再显示出来给用户照做）。
    // rebuilding 也要隐藏：那时服务已经停了，屏上的「步骤」只会让人以为还要自己动手。
    const stepsBox = $('hermes-upgrade-steps');
    if (stepsBox) stepsBox.style.display = (status === 'upgrading' || status === 'checking_network' || status === 'done' || status === 'rebuilding') ? 'none' : 'block';
    // 统一等待面板跟着真实状态走
    if (_hermesWait) {
        if (status === 'done') _hermesWait.finish({phase: 'acquired', zh: '升级完成'});
        else if (status === 'failed' || status === 'offline') _hermesWait.finish({phase: 'failed'});
        else if (status === 'upgrading') _hermesWait.phase('working', '升级中');
        else if (status === 'checking_network') _hermesWait.phase('working', '检查网络');
    }
}

/** 手动重试：让后端重新走一遍「探网络 → hermes update」。 */
async function retryHermesUpgrade() {
    const actions = $('hermes-upgrade-actions');
    if (actions) actions.innerHTML = '<span style="font-size:12px;color:var(--text-muted);">正在重试…</span>';
    try {
        await fetch('/api/trade/system/hermes-upgrade', {
            method: 'POST', headers: {'X-Hermes-Session-Token': TOKEN},
        });
    } catch(_) {}
    startHermesUpgradeStream(0);
}

/**
 * 一键重建 Trade 的运行环境（venv 的解释器版本不对时）。
 *
 * 为什么不复用 doTradeUpdate：那是「升级代码」，这是「换掉跑代码的解释器」——
 * 后者要停服务 5~10 分钟、且必须替换 venv 目录，用户必须知情并确认（客群是电脑
 * 小白，服务毫无预兆地消失会让他们以为软件坏了）。
 *
 * 后端收到请求后会派一个独立子进程、随即本进程退出，所以这里的 fetch
 * **大概率拿不到响应**（连接被掐断）—— 那不是失败，是预期行为，照常进入等待。
 */
async function startVenvRebuild(btn) {
    const okToGo = confirm(
        '重建运行环境大约需要 5~10 分钟。\n\n' +
        '期间 Trade 会暂时打不开，完成后页面会自动刷新。\n\n' +
        '现在开始吗？'
    );
    if (!okToGo) return;

    if (btn) { btn.disabled = true; btn.textContent = '正在启动…'; }
    let rejected = null;
    try {
        const r = await fetch('/api/trade/system/rebuild-venv', {
            method: 'POST', headers: {'X-Hermes-Session-Token': TOKEN},
        });
        const data = await r.json().catch(function(){ return null; });
        // 只有后端**明确拒绝**（例如当前其实不需要重建）才停手；
        // 拿不到响应时按「已开始」处理 —— 见上面的说明
        if (data && data.ok === false) rejected = data.error || '重建没有启动。';
    } catch(_) { /* 服务在响应回来之前就被子进程停掉了 —— 预期之内 */ }

    if (rejected) {
        applyHermesUpgradeState({status:'failed', message: rejected + ' 可以按下面的步骤手动重装。'});
        return;
    }
    applyHermesUpgradeState({status:'rebuilding'});
    // 重建比普通重启慢得多，兜底窗口给到 15 分钟
    // （默认的 2 分钟会在它真正成功之前就报「超时」，把用户吓去手动折腾）
    _waitForRestartAndReload(function() {
        toast('重建耗时较长。如果页面没有自动刷新，请手动刷新一次；若一直打不开，请联系技术支持。');
    }, 900);
}

/**
 * 消费升级进度流（SSE）。断线不致命：面板上的「重试」和刷新页面都能恢复，
 * 所以这里吞掉异常，不弹错误。
 */
async function startHermesUpgradeStream(offset) {
    _mountHermesWait();
    if (_hermesUpgradeAbort) _hermesUpgradeAbort.abort();
    _hermesUpgradeAbort = new AbortController();
    try {
        const r = await fetch('/api/trade/system/hermes-upgrade/stream?offset=' + (offset || 0), {
            headers: {'X-Hermes-Session-Token': TOKEN},
            signal: _hermesUpgradeAbort.signal,
        });
        if (!r.ok || !r.body) return;
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const chunk = await reader.read();
            if (chunk.done) break;
            buffer += decoder.decode(chunk.value, {stream: true});
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            for (const raw of lines) {
                const line = raw.replace(/\r$/, '');
                if (!line.startsWith('data: ')) continue;
                let data;
                try { data = JSON.parse(line.slice(6)); } catch(_) { continue; }
                if (data.type === 'log') { appendHermesUpgradeLog(data.line); _hermesWaitLine(data.line); }
                else if (data.type === 'state') {
                    applyHermesUpgradeState(data);
                    // 升级成功不再自动重启：提示用户点重启（与系统更新一致）
                    if (data.status === 'done') { promptRestartAfterHermesUpgrade(); return; }
                }
            }
        }
    } catch(_) {}
}

/** 追加一行升级日志（自动滚到底部，让用户看到「有在动」）。 */
function appendHermesUpgradeLog(line) {
    const box = $('hermes-upgrade-log');
    if (!box) return;
    box.textContent += line + '\n';
    box.scrollTop = box.scrollHeight;
}

/** Hermes 升级成功：提示手动重启，不再自动等待服务重启。 */
function promptRestartAfterHermesUpgrade() {
    _showRestartPrompt();
    toast('✅ Hermes 升级完成，请点击「🔄 重启」使新版本生效。');
}

// #endregion hermes-upgrade

