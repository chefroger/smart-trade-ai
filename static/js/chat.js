// 统一「对话」页的场景快捷胶囊（保留原 8 项能力的可发现性；osint/docgen 带 data-paid）
const _CHAT_SCENE_PRESETS = [
    { key: 'brief',    labelKey: 'scene.brief',    promptZh: '生成今日早安简报：实时汇率、大宗商品行情、目标市场新闻和今日待跟进客户。', promptEn: 'Generate today\'s morning briefing with exchange rates, commodity prices, target market news, and follow-ups.' },
    { key: 'lead',     labelKey: 'nav.lead',       promptZh: '帮我做客户开发：我的产品是【产品】，目标市场是【国家/地区】，请制定找客户渠道和开发信。', promptEn: 'Help with lead generation: product is [product], target market is [region]. Suggest channels and cold outreach.' },
    { key: 'platform', labelKey: 'nav.platform',   promptZh: '帮我做网站诊断优化，目标网址：https://', promptEn: 'Audit and optimize this website: https://' },
    { key: 'social',   labelKey: 'nav.social',     promptZh: '帮我规划本周社媒营销内容日历（Facebook/Instagram/YouTube）并生成首条帖文：', promptEn: 'Plan this week\'s social media content calendar and draft the first post for: ' },
    { key: 'linkedin', labelKey: 'nav.linkedin',   promptZh: '帮我写一条高互动 LinkedIn 专业帖文，主题围绕：', promptEn: 'Write an engaging LinkedIn post about: ' },
    { key: 'customs',  labelKey: 'nav.customs',    promptZh: '请分析这份海关数据，筛选高潜力采购商并给出开发优先级：', promptEn: 'Analyze this customs data, shortlist high-potential buyers, and prioritize outreach: ' },
    { key: 'docgen',   labelKey: 'nav.docgen',     paid: true, promptZh: '帮我生成一份外贸文档（报价单/PI/产品介绍 PPT），具体需求：', promptEn: 'Generate a trade document (quotation / PI / product deck) with these details: ' },
    { key: 'osint',    labelKey: 'nav.osint',      paid: true, promptZh: '请对以下客户做全面背景调查（含公司工商、官网、社媒与制裁筛查）：', promptEn: 'Run full B2B background due diligence (company registry, website, social, sanctions) on: ' },
];

function _buildQuickScenesInnerHtml() {
    /** 生成场景快捷胶囊按钮列表 HTML（供首次渲染与语言切换复用）。 */
    let html = '';
    _CHAT_SCENE_PRESETS.forEach(function (item) {
        const paidAttr = item.paid ? ' class="scene-pill hidden" data-paid' : ' class="scene-pill"';
        html += '<button type="button"' + paidAttr +
            ' data-act="applyChatScenePreset" data-arg="' + esc(item.key) + '">' +
            esc(t(item.labelKey)) + '</button>';
    });
    return html;
}

function _refreshQuickSceneLabels() {
    /** 中英文切换时同步刷新已缓存对话页中的快捷胶囊、输入框占位符与副标题。 */
    document.querySelectorAll('#chat-quick-scenes').forEach(function (el) {
        el.innerHTML = _buildQuickScenesInnerHtml();
    });
    if (typeof _applyLicenseGates === 'function') _applyLicenseGates();
    const dailyView = document.getElementById('view-chat-daily');
    if (dailyView) {
        const inp = dailyView.querySelector('#msg-input');
        if (inp) inp.placeholder = 'AWAITING COMMAND · ' + t('chat.ph.daily');
        const sub = dailyView.querySelector('.cmd-sub');
        if (sub) sub.textContent = t('chat.cmd.sub');
        const emptyH2 = dailyView.querySelector('#chat-empty h2');
        if (emptyH2) emptyH2.textContent = t('nav.daily');
        const emptyP = dailyView.querySelector('#chat-empty p');
        if (emptyP) emptyP.textContent = t('chat.ph.daily');
    }
}

function applyChatScenePreset(sceneKey) {
    /** 点击场景快捷胶囊：预填对应指令并聚焦输入框。 */
    const item = _CHAT_SCENE_PRESETS.find(function (x) { return x.key === sceneKey; });
    if (!item) return;
    if (item.paid && !_licenseGateAllowsPaid()) {
        toast(t('license.paid_only'));
        return;
    }
    const text = currentLang === 'en' ? item.promptEn : item.promptZh;
    const ct = currentChatContainer;
    const input = ct ? ct.querySelector('#msg-input') : null;
    if (!input) return;
    input.value = text;
    input.focus();
    if (typeof _chatInputChanged === 'function') _chatInputChanged(input);
}

// ═════════════════════ CHAT VIEW ═════════════════════
function renderChatViewInto(container, ctx, name) {
    const coName = currentCompanyId ? (companies.find(c => c.id === currentCompanyId)?.name || '') : '';
    const isDaily = ctx === 'daily';
    // 统一对话：zip s1 两栏（对话 + 右侧简报/待办/定时任务），不再用页内标题条
    const topbarHtml = isDaily ? '' : `
        <div class="chat-topbar">
            <div style="display:flex;align-items:center;gap:8px;">
                <h2>${esc(name)}</h2>
                ${coName ? `<span class="company-badge" style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;background:rgba(59,130,246,0.08);color:var(--primary);border-radius:999px;font-size:12px;font-weight:500;">🏢 ${esc(coName)}</span>` : ''}
                <span class="chat-context-tag" id="chat-context-tag"></span>
            </div>
            <div class="chat-topbar-actions">
                ${ctx === 'docs' ? `
                <select id="chat-library-select" aria-label="选择文档库" data-onchange="onChatLibraryChange" style="padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;background:var(--bg-card);">
                    <option value="">${t('chat.library')}</option>
                </select>
                <button data-act="showAddLibraryModal" title="${t('chat.lib.add')}" style="height:30px;width:30px;border-radius:var(--radius-sm);border:1px solid var(--border);background:var(--bg-card);cursor:pointer;font-size:16px;">+</button>` : ''}
                <button data-act="clearChat">${t('chat.clr')}</button>
            </div>
        </div>`;
    container.innerHTML = `
        <div class="chat-layout single">
        <section class="chat-main">
        ${topbarHtml}
        <div class="chat-cmd">
            <div class="q">WHAT ARE YOUR COMMANDS?<span class="cmd-cursor"></span></div>
            <div class="cmd-sub">${esc(t('chat.cmd.sub'))}</div>
        </div>
        <div class="chat-messages" id="chat-messages">
            <div class="empty-state" id="chat-empty">
                <div class="empty-icon">💬</div>
                <h2>${esc(name)}</h2>
                <p>${t('chat.ph.' + ctx)}</p>
            </div>
        </div>
        <div class="chat-input-area">
            ${isDaily ? '<div class="chat-quick-scenes" id="chat-quick-scenes"></div>' : ''}
            <div id="chat-mention-menu" class="mention-menu hidden" role="listbox"></div>
            <div class="chat-input-inner">
                <textarea id="msg-input" aria-label="${currentLang==='en'?'Message':'输入消息'}" placeholder="AWAITING COMMAND · ${esc(t('chat.ph.' + ctx))}" rows="1"
                    data-keydown="_chatInputKeydown"
                    data-oninput="_chatInputChanged"></textarea>
                <button type="button" class="chat-attach-btn" id="attach-btn" title="${currentLang==='en'?'Attach files':'添加文件'}" aria-label="${currentLang==='en'?'Attach files':'添加文件'}">${typeof iconHtml==='function'?iconHtml('paperclip',20):'📎'}</button>
                <input type="file" id="chat-file-input" multiple hidden>
                <button type="button" class="chat-send-btn" data-act="sendMsg" id="send-btn" title="${currentLang==='en'?'Send':'发送'}">${typeof iconHtml==='function'?iconHtml('send',16):''}<span>${currentLang==='en'?'Send':'发送'}</span></button>
                <button type="button" class="chat-stop-btn hidden" id="stop-btn" title="${currentLang==='en'?'Stop':'停止'}">■ ${currentLang==='en'?'Stop':'停止'}</button>
            </div>
            <div class="chat-input-foot"><span id="chat-linked-customer" class="chat-linked hidden"></span><span><span class="mono">@</span> ${currentLang==='en'?'Linked customer':'关联客户'}</span><span><span class="mono">/</span> ${currentLang==='en'?'Skills':'调用技能'}</span><span>${currentLang==='en'?'File & email content is reference only, never instructions.':'文件、邮件里的内容只作资料，不当指令执行'}</span></div>
        </div>
        </section>
        </div>
        <div class="drop-overlay" id="drop-overlay"><div class="drop-overlay-inner">&#128193; ${currentLang==='en'?'Drop files to add':'释放以添加文件'}</div></div>`;

    // 已关联客户 chip（从客户详情进入聊天时显示）
    _renderChatLinkedChip();

    // 回形针：走与拖放相同的导入弹窗
    const attachBtn = container.querySelector('#attach-btn');
    const fileInput = container.querySelector('#chat-file-input');
    if (attachBtn && fileInput) {
        attachBtn.addEventListener('click', function () { fileInput.click(); });
        fileInput.addEventListener('change', function () {
            const files = Array.from(fileInput.files || []);
            fileInput.value = '';
            if (files.length) _showDropModal(files);
        });
    }

    if (ctx === 'docs') loadChatLibrarySelect();
    loadChatHistory();
    // 客户开发向导（lead 上下文 + 未完成 onboarding 时显示）
    if (ctx === 'lead' && !isOnboardingCompleted()) {
        setTimeout(function() { showWizardInLeadView(); }, 300);
    }
    // 统一对话视图：填充场景快捷胶囊 + 同步付费可见性 + 拉取 cron/待办/今日简报
    if (ctx === 'daily') {
        const scenesSlot = container.querySelector('#chat-quick-scenes');
        if (scenesSlot) scenesSlot.innerHTML = _buildQuickScenesInnerHtml();
        if (typeof _applyLicenseGates === 'function') _applyLicenseGates();
        _shownCronOutputs = new Set();
        loadCronStatus(false);
        loadTodos(false);
        loadTodayBrief();
    }
}

async function loadTodayBrief(silent) {
    /** 拉取 /brief/today，渲染 KPI 卡并刷新侧栏逾期角标。 */
    if (!currentCompanyId) return;
    const data = await api('GET', '/api/trade/brief/today', null, undefined, {
        silent: !!silent,
    });
    if (!data) return;
    _updateDailyBriefBadge(data.overdue_followups);
    const ni = data.new_inquiries;
    const niText = (ni === null || ni === undefined) ? t('brief.dash') : String(ni);
    const overdue = data.overdue_followups || 0;
    const pending = data.pending_shipments || 0;
    const summaryText = (data.summary && data.summary.text)
        ? data.summary.text
        : t('brief.summary_empty');
    const dateLabel = (data.date || '').slice(5).replace('-', '.') || '';
    // 常驻右栏：今日简报 KPI（所有主视图；详情页由 CSS 隐藏）
    const railBrief = document.getElementById('rail-brief');
    if (railBrief) {
        railBrief.innerHTML =
            '<div class="rail-bh"><span class="t">' +
            (typeof iconHtml === 'function' ? iconHtml('layout-dashboard', 16) : '') +
            esc(t('brief.title')) + '</span>' +
            '<span class="lbl">BRIEF' + (dateLabel ? ' · ' + esc(dateLabel) : '') + '</span></div>' +
            '<div class="rail-kpis">' +
            '<div><div class="n">' + esc(niText) + '</div><div class="lbl">' + esc(t('brief.new_inquiries')) + '</div></div>' +
            '<div><div class="n' + (overdue ? ' r' : '') + '">' + esc(String(overdue)) + '</div><div class="lbl">' + esc(t('brief.overdue')) + '</div></div>' +
            '<div><div class="n">' + esc(String(pending)) + '</div><div class="lbl">' + esc(t('brief.pending_ship')) + '</div></div>' +
            '</div><p class="rail-line">' + esc(summaryText) + '</p>';
        return;
    }
    // 无右栏时旧聊天内卡片兜底
    if (currentChatContext !== 'daily' || !currentChatContainer) return;
    const container = currentChatContainer.querySelector('#chat-messages');
    if (!container) return;
    let html = '<div class="brief-kpi-card">';
    html += '<div class="brief-kpi-head"><span class="brief-kpi-title">' + esc(t('brief.title')) + '</span>';
    html += '<span class="brief-kpi-date">BRIEF' + (dateLabel ? ' · ' + esc(dateLabel) : '') + '</span></div>';
    html += '<div class="brief-kpis">';
    html += '<div><div class="n">' + esc(niText) + '</div><div class="lbl">' + esc(t('brief.new_inquiries')) + '</div></div>';
    html += '<div><div class="n' + (overdue ? ' r' : '') + '">' + overdue + '</div><div class="lbl">' + esc(t('brief.overdue')) + '</div></div>';
    html += '<div><div class="n">' + pending + '</div><div class="lbl">' + esc(t('brief.pending_ship')) + '</div></div>';
    html += '</div>';
    html += '<p class="brief-line">' + esc(summaryText) + '</p></div>';
    let card = container.querySelector('.brief-kpi-card');
    if (card) {
        card.outerHTML = html;
    } else {
        const wrap = document.createElement('div');
        wrap.innerHTML = html;
        const node = wrap.firstChild;
        const cron = container.querySelector('.cron-panel');
        if (cron) cron.insertAdjacentElement('beforebegin', node);
        else {
            const emptyEl = container.querySelector('.empty-state');
            if (emptyEl) emptyEl.insertAdjacentElement('afterend', node);
            else container.insertAdjacentElement('afterbegin', node);
        }
    }
}

function _updateDailyBriefBadge(overdue) {
    /** 侧栏「今日简报」角标 = 逾期客户数（口径 §4-4）。 */
    const badge = document.getElementById('daily-brief-badge');
    if (!badge) return;
    const n = Number(overdue) || 0;
    if (n > 0) {
        badge.textContent = String(n);
        badge.hidden = false;
        badge.style.display = 'inline-block';
    } else {
        badge.hidden = true;
        badge.style.display = 'none';
    }
}

// ═════════════════════ 全局 cron 轮询与工作台横幅 ═════════════════════
let _cronPollTimer = null;
let _shownCronOutputs = new Set();  // 已展示过的 cron 输出任务名
let _cronOutputsByJob = {};         // 当前公司已激活定时任务最新产出缓存（jobKey -> item）

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

function startCronPolling() {
    stopCronPolling();
    _cronPollTimer = setInterval(() => {
        if (currentCompanyId) { loadCronStatus(true); loadTodos(true); }
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
        console.log('Version check: current=' + data.version);
        // 2026-10-29：不再弹「工具守卫未生效」toast —— 守卫默认关闭，
        // 用户在自己电脑上操作自己的数据，这条提示只制造焦虑、没有作用。
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

// #region cron-rail-render
function _cronOutputPreview(raw) {
    /** 将 Hermes cron Markdown 正文压缩为干净可读的单段摘要。 */
    const cleaned = String(raw || '')
        .replace(/^#{1,6}\s+/gm, '')
        .replace(/^\s*\|[-:\s|]+\|\s*$/gm, ' ')
        .replace(/^\s*[-━═—]{3,}\s*$/gm, ' ')
        .replace(/[|>`*_~]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    return cleaned.length > 120 ? (cleaned.slice(0, 120) + '…') : cleaned;
}

function _formatCronRunBadge(task) {
    /** 生成右栏定时任务条目的右侧时间/状态角标。 */
    const runAt = String((task && task.run_at) || '');
    const timeStr = String((task && task.time) || '');
    if (task && task.output) {
        if (task.is_today) {
            const hm = runAt.length >= 16 ? runAt.slice(11, 16) : timeStr;
            return t('brief.cron_today_tag') + (hm ? ' ' + hm : '');
        }
        if (runAt.length >= 16) return runAt.slice(5, 16);
        return runAt || timeStr;
    }
    if (task && task.silent) {
        const prefix = runAt.length >= 16 ? (runAt.slice(5, 16) + ' · ') : '';
        return prefix + t('brief.cron_silent');
    }
    return (timeStr ? (timeStr + ' · ') : '') + t('brief.cron_waiting');
}

function _renderRailCron(data) {
    /** 渲染常驻右栏「定时任务输出」：展示当前公司所有已设置并激活的 Hermes cron 任务及产出。 */
    const railCron = document.getElementById('rail-cron');
    if (!railCron) return;

    const activeItems = (data && Array.isArray(data.active_items)) ? data.active_items : [];
    const fallbackOuts = (data && Array.isArray(data.completed))
        ? data.completed.filter(function (x) { return x && x.output; })
        : [];
    const items = activeItems.length ? activeItems : fallbackOuts;

    _cronOutputsByJob = {};
    items.forEach(function (item, idx) {
        const key = String(item.job_id || ('idx-' + idx));
        _cronOutputsByJob[key] = item;
    });

    const lblText = 'CRON' + (items.length ? (' · ' + String(items.length)) : '');
    let cronHtml = '<div class="rail-bh"><span class="t">' +
        (typeof iconHtml === 'function' ? iconHtml('calendar-clock', 16) : '') +
        esc(t('brief.cron')) +
        '</span><span class="lbl">' + esc(lblText) + '</span></div>';

    if (!data) {
        cronHtml += '<p class="rail-line">' + esc(t('brief.cron_no_jobs')) + '</p>';
        railCron.innerHTML = cronHtml;
        return;
    }

    if (!items.length) {
        cronHtml += '<p class="rail-line">' + esc(t('brief.cron_no_jobs')) + '</p>' +
            '<button type="button" class="rail-cron-setup-btn" data-act="navToView" data-args=\'["tasks"]\'>' +
            esc(t('brief.cron_setup')) + '</button>';
        railCron.innerHTML = cronHtml;
        return;
    }

    items.forEach(function (task, idx) {
        const key = String(task.job_id || ('idx-' + idx));
        const badge = _formatCronRunBadge(task);
        const nameText = task.name || task.time || key;
        if (task.output) {
            const preview = _cronOutputPreview(task.output);
            cronHtml += '<div class="rail-cron-item clickable" data-act="openCronOutputModal" data-arg="' +
                esc(key) + '" title="' + esc(t('brief.cron_view_full')) + '">' +
                '<div class="rail-cron-head"><span class="rail-cron-name">' + esc(nameText) + '</span>' +
                '<span class="mono' + (task.is_today ? ' today' : '') + '">' + esc(badge) + '</span></div>' +
                '<div class="rail-cron-preview">' + esc(preview) + '</div>' +
                '</div>';
        } else {
            cronHtml += '<div class="rail-cron-item pending">' +
                '<div class="rail-cron-head"><span class="rail-cron-name">' + esc(nameText) + '</span>' +
                '<span class="mono">' + esc(badge) + '</span></div>' +
                (task.schedule ? '<div class="rail-cron-sub">' + esc(task.schedule) + '</div>' : '') +
                '</div>';
        }
    });
    railCron.innerHTML = cronHtml;
}
// #endregion cron-rail-render

async function openCronOutputModal(jobKey) {
    /** 打开弹窗展示指定 Hermes cron 任务的完整 Markdown 输出。 */
    const key = String(jobKey || '');
    if (!key) return;
    let item = _cronOutputsByJob[key] || null;
    if ((!item || !item.output) && key.indexOf('idx-') !== 0) {
        const fetched = await api('GET', '/api/trade/cron/jobs/' + encodeURIComponent(key) + '/output');
        if (fetched) {
            item = fetched;
            _cronOutputsByJob[key] = fetched;
        }
    }
    if (!item || !item.output) {
        toast(item && item.silent ? t('brief.cron_silent') : t('brief.cron_waiting'));
        return;
    }

    const old = document.getElementById('cron-output-modal');
    if (old) old.remove();

    const metaParts = [];
    if (item.run_at) metaParts.push(item.run_at);
    if (item.schedule) metaParts.push('Cron: ' + item.schedule);
    const metaText = metaParts.join(' · ');

    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.id = 'cron-output-modal';
    backdrop.onclick = function (e) { if (e.target === backdrop) backdrop.remove(); };
    backdrop.innerHTML =
        '<div class="modal" style="max-width:760px;width:95%;">' +
        '<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px;">' +
        '<div><h3 style="margin:0;">' + esc(item.name || t('brief.cron')) + '</h3>' +
        (metaText ? '<div style="font-size:11.5px;color:var(--text-muted);font-family:var(--mono);margin-top:3px;">' + esc(metaText) + '</div>' : '') +
        '</div>' +
        '<button type="button" class="slide-panel-close" data-act="removeById" data-arg="cron-output-modal">×</button>' +
        '</div>' +
        '<div class="cron-output-modal-body msg-body" id="cron-output-modal-md"></div>' +
        '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">' +
        '<button type="button" class="btn" data-act="copyCronOutput" data-arg="' + esc(key) + '">' + btnIcon('copy') + ' 复制内容</button>' +
        '<button type="button" class="btn btn-primary" data-act="removeById" data-arg="cron-output-modal">关闭</button>' +
        '</div></div>';

    document.body.appendChild(backdrop);
    const mdBody = backdrop.querySelector('#cron-output-modal-md');
    if (mdBody) _renderSafeMarkdownInto(mdBody, item.output);
}

function copyCronOutput(jobKey) {
    /** 复制指定定时任务输出的 Markdown 原文到剪贴板。 */
    const item = _cronOutputsByJob[String(jobKey || '')];
    if (!item || !item.output) return;
    navigator.clipboard.writeText(String(item.output));
    toast(t('toast.copied'));
}

async function loadCronStatus(isPoll = false) {
    if (!currentCompanyId) {
        _renderRailCron(null);
        return;
    }
    const data = await api('GET', '/api/trade/cron/today', null, undefined, {
        silent: isPoll,
    });
    if (!data) return;

    // 定时任务输出（展示当前公司已设置并激活的 Hermes cron 任务及其最新产出）
    _renderRailCron(data);
    loadTodayBrief(isPoll).catch(function () {});

    // 顶部进度横幅已下线：其功能（今日简报/待办/定时任务）由常驻右栏承载。
    // 右栏缺失时无需再兜底渲染（正常情况 #app-rail 常驻）。
    return;

}

// ── 待办（独立存储，P2-12）────────────────────────────────────────

let _todosData = null;

async function loadTodos(isPoll = false) {
    /** 拉取并渲染右栏待办；与定时任务（cron）完全独立。 */
    if (!currentCompanyId) return;
    const data = await api('GET', '/api/trade/todos', null, undefined, {silent: isPoll});
    if (!data) return;
    _todosData = data;
    _renderRailTodos();
    // 后台背调任务与待办同源刷新；轮询时跳过（避免反复重连 SSE）
    if (!isPoll) loadOsintJobs(false).catch(function () {});
}

function _todoItemHtml(item, done) {
    /** 单条待办：勾选钮 + 标题（+ 日期/客户）+ 删除钮。 */
    const parts = [];
    // 无截止日的未完成项明确显示「未定日期」（P2）
    if (item.due_date) parts.push(item.due_date);
    else if (!done) parts.push('未定日期');
    if (item.customer_name) parts.push(item.customer_name);
    if (item.reason) parts.push('原因：' + item.reason);
    const sub = parts.join(' · ');
    return '<div class="rail-todo-item' + (done ? ' done' : '') +
        '" data-todo-id="' + esc(String(item.id)) + '">' +
        '<button type="button" class="todo-check" data-role="toggle" aria-label="' +
        (done ? '取消完成' : '标记完成') + '">' + (done ? '✓' : '○') + '</button>' +
        '<span class="tx">' + esc(item.title) +
        (sub ? '<span class="sub">' + esc(sub) + '</span>' : '') +
        '</span>' +
        '<button type="button" class="todo-del" data-role="delete" aria-label="删除">×</button>' +
        '</div>';
}

function _renderRailTodos() {
    /** 按 逾期 / 今天 / 将来 / 已完成 渲染右栏。 */
    const el = document.getElementById('rail-todo');
    if (!el || !_todosData) return;
    const d = _todosData;
    const sc = el.scrollTop;
    const overdue = d.overdue || [];
    const todayItems = d.today_items || [];
    const upcoming = d.upcoming || [];
    const doneItems = d.done || [];
    const openCount = overdue.length + todayItems.length + upcoming.length;

    let html = '<div class="rail-bh"><span class="t">' +
        (typeof iconHtml === 'function' ? iconHtml('list-checks', 16) : '') +
        esc(t('brief.todo')) +
        '</span><span class="lbl">TODO · ' + esc(String(openCount)) + '</span>' +
        '<button type="button" class="todo-add-btn" id="todo-add-btn" aria-label="' +
        esc(t('todo.add')) + '">+</button></div>';

    // 添加表单默认收起，点 + 展开
    html += '<div id="todo-add-form" class="todo-add-form hidden">' +
        '<input type="text" id="todo-add-title" maxlength="200" placeholder="' +
        esc(t('todo.placeholder')) + '">' +
        '<div class="todo-add-row">' +
        '<input type="date" id="todo-add-due" aria-label="' + esc(t('todo.due')) + '">' +
        '<input type="text" id="todo-add-reason" maxlength="300" placeholder="原因（可选）">' +
        '<select id="todo-add-customer" aria-label="' + esc(t('todo.customer')) + '">' +
        '<option value="">' + esc(t('todo.no_customer')) + '</option></select>' +
        '<button type="button" class="btn btn-xs primary" id="todo-add-save">' +
        esc(t('todo.save')) + '</button>' +
        '</div></div>';

    const groups = [
        [overdue, t('todo.overdue')],
        [todayItems, t('todo.today')],
        [upcoming, t('todo.upcoming')],
    ];
    groups.forEach(function (g) {
        // 空分组不占位置
        if (!g[0].length) return;
        html += '<div class="rail-todo-sep">' + esc(g[1]) + '</div>';
        g[0].forEach(function (it) { html += _todoItemHtml(it, false); });
    });
    if (doneItems.length) {
        html += '<div class="rail-todo-sep">' +
            esc(t('brief.done', {n: doneItems.length})) + '</div>';
        doneItems.forEach(function (it) { html += _todoItemHtml(it, true); });
    }
    // 一条都没有：给一行空态，而不是留白
    if (!openCount && !doneItems.length) {
        html += '<p class="rail-line">' + esc(t('todo.empty')) + '</p>';
    }

    el.innerHTML = html;
    // 轮询重建会跳回顶部：保留原滚动位置
    el.scrollTop = sc;
    _bindRailTodos(el);
}

function _bindRailTodos(el) {
    /** 绑定添加/勾选/删除；每次重渲染都要重绑（innerHTML 会销毁旧节点）。 */
    document.getElementById('todo-add-btn')?.addEventListener('click', function () {
        const form = document.getElementById('todo-add-form');
        if (!form) return;
        form.classList.toggle('hidden');
        // 展开时才拉客户列表，避免每次轮询都请求
        if (!form.classList.contains('hidden')) {
            _fillTodoCustomers();
            document.getElementById('todo-add-title')?.focus();
        }
    });
    document.getElementById('todo-add-save')?.addEventListener('click', _saveTodo);
    document.getElementById('todo-add-title')?.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); _saveTodo(); }
    });

    el.querySelectorAll('.rail-todo-item').forEach(function (row) {
        const id = Number(row.getAttribute('data-todo-id'));
        row.querySelector('[data-role="toggle"]')?.addEventListener('click', function (e) {
            e.stopPropagation();
            // 当前是「已完成」就取消，否则标记完成
            _todoPatch(id, {done: !row.classList.contains('done')});
        });
        row.querySelector('[data-role="delete"]')?.addEventListener('click', function (e) {
            e.stopPropagation();
            // 删除不可撤销，先确认
            if (!confirm(t('todo.confirm_delete'))) return;
            _todoDelete(id);
        });
    });
}

async function _fillTodoCustomers() {
    /** 填充「关联客户」下拉；客户列表未加载时先取一次。 */
    const sel = document.getElementById('todo-add-customer');
    if (!sel) return;
    if (typeof allCustomers !== 'undefined' && !allCustomers.length) {
        try {
            const list = await api('GET', '/api/trade/customers', null, undefined, {silent: true});
            const arr = Array.isArray(list) ? list : ((list && list.items) || []);
            if (typeof allCustomers !== 'undefined') allCustomers = arr;
        } catch (e) {
            // 拉不到客户不影响「无客户」待办的添加
        }
    }
    const cur = sel.value;
    const list = (typeof allCustomers !== 'undefined' ? allCustomers : []) || [];
    sel.innerHTML = '<option value="">' + esc(t('todo.no_customer')) + '</option>' +
        list.map(function (c) {
            return '<option value="' + esc(String(c.id)) + '">' + esc(c.name) + '</option>';
        }).join('');
    sel.value = cur;
}

async function _saveTodo() {
    const titleEl = document.getElementById('todo-add-title');
    const dueEl = document.getElementById('todo-add-due');
    const custEl = document.getElementById('todo-add-customer');
    const title = (titleEl && titleEl.value || '').trim();
    // 标题为空：不提交，把焦点放回输入框
    if (!title) { if (titleEl) titleEl.focus(); return; }
    const reasonEl = document.getElementById('todo-add-reason');
    const body = {title: title};
    if (reasonEl && reasonEl.value.trim()) body.reason = reasonEl.value.trim();
    if (dueEl && dueEl.value) body.due_date = dueEl.value;
    if (custEl && custEl.value) body.customer_id = Number(custEl.value);
    const r = await api('POST', '/api/trade/todos', body);
    if (!r) return;
    if (titleEl) titleEl.value = '';
    if (dueEl) dueEl.value = '';
    const reasonClear = document.getElementById('todo-add-reason');
    if (reasonClear) reasonClear.value = '';
    if (custEl) custEl.value = '';
    await loadTodos(false);
}

async function _todoPatch(id, body) {
    const r = await api('PATCH', '/api/trade/todos/' + id, body);
    if (r) await loadTodos(false);
}

async function _todoDelete(id) {
    const r = await api('DELETE', '/api/trade/todos/' + id);
    if (r) await loadTodos(false);
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
    // 走 api() 统一封装：拿到 120s 超时与 401 自愈。
    // 历史上这里裸 fetch 且无超时，上传卡死时确认按钮会永久 disabled。
    const resp = await api('POST', '/api/trade/upload-files', form);
    if (!resp) throw new Error(t('toast.import_fail'));
    return resp;
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
    <div class="modal" style="max-width:440px;width:95%;" data-stop="1">
        <h3 style="margin:0 0 4px;">拖入 ${files.length} 个文件 (${_formatBytes(totalSize)})</h3>
        <div class="drop-file-list">${fileListHtml}</div>
        <div style="margin:10px 0;">
            <label style="font-size:13px;color:var(--text-muted);">存入工作目录：</label>
            <select id="drop-subdir-select" style="width:100%;padding:8px;border-radius:6px;border:1px solid var(--border);font-size:14px;margin-top:4px;">${subdirOpts}</select>
        </div>
        <div style="display:flex;gap:8px;">
            <button class="btn btn-primary" id="drop-confirm-btn" style="flex:1;">确认导入</button>
            <button class="btn" data-act="closeBackdrop">取消</button>
        </div>
    </div>`;
    document.body.appendChild(backdrop);

    backdrop.querySelector('#drop-confirm-btn').onclick = async function() {
        const subdir = backdrop.querySelector('#drop-subdir-select').value;
        const btn = backdrop.querySelector('#drop-confirm-btn');
        btn.disabled = true;
        let restoreBtn = null;
        try {
            if (typeof TradeWait !== 'undefined') restoreBtn = TradeWait.inline(btn, {en: 'IMPORTING', zh: '导入中'});
            else btn.textContent = t('import.importing');
            const result = await _uploadToWorkDir(_pendingDropFiles, subdir);
            toast(t('toast.imported', {n: result.uploaded, dir: subdir}));
            const input = document.getElementById('msg-input');
            if (input) {
                // 检查是否有图片文件，提示 Agent 使用 vision 识别
                const hasImages = _pendingDropFiles.some(f => _isImageFile(f._relPath || f.name));
                let hint = `[已导入 ${result.uploaded} 个文件到「${result.target_path}」，请递归读取该目录下的所有文件并分析`;
                if (hasImages) {
                    hint += `。图片文件请使用 vision 工具识别文字内容`;
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
/** 把时间戳格式化成 HH:MM；无法解析时回落到当前时间（实时消息用）。 */
function _msgHHMM(ts) {
    const pad = function (n) { return (n < 10 ? '0' : '') + n; };
    if (typeof ts === 'number' && isFinite(ts)) {
        const d = new Date(ts);
        return pad(d.getHours()) + ':' + pad(d.getMinutes());
    }
    if (ts) {
        const m = String(ts).match(/(\d{1,2}):(\d{2})/);
        if (m) return pad(parseInt(m[1], 10)) + ':' + m[2];
    }
    const now = new Date();
    return pad(now.getHours()) + ':' + pad(now.getMinutes());
}

function _renderSafeMarkdownInto(targetEl, content) {
    /** 将 Markdown 安全渲染进目标节点（禁止 data-* 属性并中和外链图片）。 */
    const raw = marked.parse(content || '');
    targetEl.innerHTML = DOMPurify.sanitize(raw, {
        ALLOWED_TAGS: ['p','br','strong','em','b','i','ul','ol','li','h1','h2','h3','h4','h5','h6',
            'blockquote','code','pre','a','table','thead','tbody','tr','th','td','hr','span','div','img'],
        // 不放行 style/id：模型输出不该带自定义样式与可覆盖的 DOM id（审计 P1-E）
        ALLOWED_ATTR: ['href','target','class','src','alt','width','height'],
        // S1：模型输出不得携带 data-*（可被委托层当成动作执行）
        ALLOW_DATA_ATTR: false,
    });
    // 跨源图片改为点击加载，防提示注入零点击外带数据
    if (typeof neutralizeRemoteImages === 'function') neutralizeRemoteImages(targetEl);
}

function addMsg(role, content, files, save, convId, blocks, timeStr) {
    const ct = currentChatContainer;
    if (!ct) return;
    const container = ct.querySelector('#chat-messages');
    // Remove empty state
    const emptyEl = container.querySelector('.empty-state');
    if (emptyEl) emptyEl.remove();

    const div = document.createElement('div');
    div.className = `message ${role}`;
    const body = document.createElement('div');
    body.className = 'msg-body';
    _renderSafeMarkdownInto(body, content);
    // 附件 chip：气泡下方单独一行（mockup .att），不再塞进消息正文
    let attachEl = null;
    if (files && files.length) {
        attachEl = document.createElement('div');
        attachEl.className = 'msg-att';
        attachEl.innerHTML = files.map(function (f) {
            return '<span class="att-chip">📎 ' + esc(f.file || f) +
                (f.status === 'cached'
                    ? ' <span class="muted">（' + (currentLang === 'en' ? 'cached' : '来自缓存提取') + '）</span>'
                    : '') + '</span>';
        }).join('');
    }
    // W10：结构化块（四格卡 / 草稿 / NEXT chips）—— 无 blocks 时保持纯文本
    if (role === 'assistant' && blocks) {
        const blocksEl = _renderChatBlocks(blocks);
        if (blocksEl) body.appendChild(blocksEl);
    }
    // 助手消息：▶ TRADE · ASSISTANT // HH:MM 标题行（mockup s1）；用户消息走右侧气泡
    let msgHead = null;
    if (role === 'assistant') {
        const head = document.createElement('div');
        head.className = 'msg-head';
        // mockup：TRADE · ASSISTANT // HH:MM → 虚线 → 分析完成
        head.innerHTML = '<span class="mh-tag">▶ TRADE · ASSISTANT // ' + _msgHHMM(timeStr) + '</span>' +
            '<span class="mh-rule"></span><span class="mh-done">' + (currentLang === 'en' ? 'Analysis done' : '分析完成') + '</span>';
        msgHead = head;
        div.appendChild(head);
    } else if (role === 'user') {
        // 用户消息：YOU · HH:MM 小标签（mockup）
        const uhead = document.createElement('div');
        uhead.className = 'msg-head user-head';
        uhead.innerHTML = '<span class="mh-tag">YOU</span><span class="mh-t">' + _msgHHMM(timeStr) + '</span>';
        div.appendChild(uhead);
    }
    div.appendChild(body);
    if (attachEl) div.appendChild(attachEl);

    // AI 回复右侧加「📋 复制」按钮，点击写入剪贴板
    if (role === 'assistant' && content) {
        const copyBtn = document.createElement('button');
        copyBtn.innerHTML = (typeof iconHtml === 'function' ? iconHtml('copy', 16) : '📋');
        copyBtn.title = currentLang==='en'?'Copy to clipboard':'复制到剪贴板';
        // 复制按钮：无外框，放进助手标题行右侧（跟随标题，短消息也不会下溢遮挡下一条）
        copyBtn.style.cssText = 'background:none;border:none;padding:0 2px;font-size:15px;line-height:1;cursor:pointer;color:var(--muted);opacity:0.7;transition:opacity 0.15s;';
        copyBtn.onmouseenter = function() { this.style.opacity = '1'; };
        copyBtn.onmouseleave = function() { this.style.opacity = '0.7'; };
        copyBtn.onclick = function(e) {
            e.stopPropagation();
            navigator.clipboard.writeText(content).then(function() {
                copyBtn.innerHTML = (typeof iconHtml === 'function' ? iconHtml('check', 16) : '✅');
                setTimeout(function() { copyBtn.innerHTML = (typeof iconHtml === 'function' ? iconHtml('copy', 16) : '📋'); }, 1500);
            }).catch(function() {
                copyBtn.innerHTML = (typeof iconHtml === 'function' ? iconHtml('x', 16) : '❌');
                setTimeout(function() { copyBtn.innerHTML = (typeof iconHtml === 'function' ? iconHtml('copy', 16) : '📋'); }, 1500);
            });
        };
        if (msgHead) {
            msgHead.appendChild(copyBtn);
        } else {
            div.style.position = 'relative';
            copyBtn.style.position = 'absolute';
            copyBtn.style.top = '30px';
            copyBtn.style.right = '8px';
            div.appendChild(copyBtn);
        }

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
                        var rated = await api('POST', '/api/trade/conversations/' + convIdForRating + '/rate', { rating: rVal, feedback: '' });
                        // 失败时 api() 已 toast 原因；评分没存上，不能显示"感谢反馈"
                        if (!rated) return;
                        ratingDiv.innerHTML = '<span style="font-size:11px;color:var(--accent-green);">✅ '+(currentLang==='en'?'Thanks for feedback':'感谢反馈')+'</span>';
                    });
                });
        }
    }

    container.appendChild(div);
    // 只在用户发消息或新 AI 回复流式到达时自动滚到底部
    // 历史加载和手动浏览不强制滚动
}

function _renderChatBlocks(blocks) {
    /** 渲染 SSE blocks：facts 四格卡 + 邮件草稿 + NEXT chips。 */
    if (!blocks || typeof blocks !== 'object') return null;
    const wrap = document.createElement('div');
    wrap.className = 'chat-blocks';

    if (Array.isArray(blocks.facts) && blocks.facts.length) {
        const grid = document.createElement('div');
        grid.className = 'chat-facts';
        blocks.facts.slice(0, 4).forEach(function (f) {
            const cell = document.createElement('div');
            cell.innerHTML = '<div class="lbl">' + esc(f.label || '') + '</div>'
                + '<div class="v">' + esc(f.value || '') + '</div>';
            grid.appendChild(cell);
        });
        wrap.appendChild(grid);
    }

    if (blocks.draft && typeof blocks.draft === 'object') {
        const d = blocks.draft;
        const box = document.createElement('div');
        box.className = 'chat-draft';
        const lang = (d.lang || 'en').toUpperCase();
        box.innerHTML = '<div class="bar"><span class="lbl">DRAFT · EMAIL · ' + esc(lang) + '</span>'
            + '<span class="warn"><span class="dot"></span>' + esc(t('chat.blocks.draft_warn')) + '</span></div>'
            + (d.subject ? '<div class="subj">' + esc(d.subject) + '</div>' : '')
            + '<pre class="body">' + esc(d.body || '') + '</pre>'
            + '<div class="draft-acts">'
            + '<button type="button" class="btn solid draft-copy">' + esc(t('chat.blocks.copy_draft')) + '</button>'
            + '<button type="button" class="btn draft-edit">' + esc(t('chat.blocks.edit_draft')) + '</button>'
            + '<button type="button" class="btn ghost draft-pi">' + esc(t('chat.blocks.gen_pi')) + '</button>'
            + '<span class="note">' + esc(t('chat.blocks.copy_note')) + '</span>'
            + '</div>';
        const btn = box.querySelector('.draft-copy');
        if (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                const text = (d.subject ? ('Subject: ' + d.subject + '\n\n') : '') + (d.body || '');
                navigator.clipboard.writeText(text).then(function () {
                    btn.textContent = t('chat.blocks.copied');
                    setTimeout(function () { btn.textContent = t('chat.blocks.copy_draft'); }, 1500);
                }).catch(function () {});
            });
        }
        // 继续修改 / 生成 PI：写进输入框（与 NEXT chip 同一套动作，不自动外发）
        const editBtn = box.querySelector('.draft-edit');
        if (editBtn) {
            editBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                _fillChatInput(t('chat.blocks.edit_prompt') + (d.subject ? ('：' + d.subject) : ''));
            });
        }
        const piBtn = box.querySelector('.draft-pi');
        if (piBtn) {
            piBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                _fillChatInput(t('chat.blocks.gen_pi_prompt'));
            });
        }
        wrap.appendChild(box);
    }

    if (Array.isArray(blocks.next_actions) && blocks.next_actions.length) {
        const row = document.createElement('div');
        row.className = 'chat-next';
        row.innerHTML = '<span class="lbl">' + esc(t('chat.blocks.next')) + '</span>';
        blocks.next_actions.forEach(function (a) {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'chip';
            chip.textContent = a.label || a.action || '';
            chip.addEventListener('click', function (e) {
                e.stopPropagation();
                _handleNextAction(a);
            });
            row.appendChild(chip);
        });
        wrap.appendChild(row);
    }

    return wrap.childNodes.length ? wrap : null;
}

// ═════════ @ 关联客户 / / 调用技能 下拉 ═════════
let _mention = { kind: '', start: 0, items: [], idx: 0, query: '' };
let _mentionSeq = 0;
let _chatLinkedName = '';

function _chatScope() {
    // 多个栏目各自缓存了一份聊天 DOM（id 相同），必须限定在当前可见视图内查找
    return (typeof currentChatContainer !== 'undefined' && currentChatContainer) || document;
}

function _mentionEl() { return _chatScope().querySelector('#chat-mention-menu'); }

function _mentionClose() {
    const m = _mentionEl();
    if (m) { m.classList.add('hidden'); m.innerHTML = ''; }
    _mention = { kind: '', start: 0, items: [], idx: 0, query: '' };
}

function _chatInputChanged(el) {
    /** textarea 输入：自适应高度 + 检测 @ / 触发下拉。 */
    el.style.height = '24px';
    el.style.height = (el.scrollHeight > 80 ? 80 : el.scrollHeight) + 'px';
    const caret = el.selectionStart || 0;
    const before = el.value.slice(0, caret);
    // 光标前最近的 @xxx 或 /xxx（允许紧跟中文/标点；邮箱 a@b 不触发）
    // 同时接受全角 ＠ / ／（中文输入法常见）
    const m = before.match(/(^|[^\w@/＠／])([@/＠／])([^\s@/＠／]*)$/);
    if (!m) { _mentionClose(); return; }
    const sym = (m[2] === '＠') ? '@' : (m[2] === '／' ? '/' : m[2]);
    // 先标记「下拉激活」，避免异步加载期间按 Enter 被当成发送
    _mention = { kind: sym, start: caret - m[3].length - 1, items: [], idx: 0, query: m[3] };
    _mentionOpen(sym, m[3], caret - m[3].length - 1);
}

async function _mentionOpen(sym, query, start) {
    const seq = ++_mentionSeq;
    const q = String(query || '').toLowerCase();
    let items = [];
    if (sym === '@') {
        // 客户列表：优先本地缓存，没有就拉一次并写回缓存
        let list = (typeof allCustomers !== 'undefined' && allCustomers.length) ? allCustomers : null;
        if (!list) {
            list = (await api('GET', '/api/trade/customers')) || [];
            if (typeof allCustomers !== 'undefined' && !allCustomers.length) allCustomers = list;
        }
        items = list.filter(function (c) {
            const hay = [c.name, c.contact, c.email, c.country].filter(Boolean).join(' ').toLowerCase();
            return !q || hay.indexOf(q) >= 0;
        }).slice(0, 8).map(function (c) {
            return {
                // 展示联系人姓名；没有联系人再退回公司名。公司名放副标题
                label: c.contact || c.name || ('#' + c.id),
                sub: [c.contact ? c.name : '', c.country, c.email].filter(Boolean).join(' · '),
                insert: '',
                run: function () { _chatLinkCustomer(c); },
            };
        });
    } else {
        // 技能：全部列出（按分组），选中后插入该技能的第一个触发词（技能路由按关键词生效）
        const flat = [];
        if (typeof _ALL_SKILLS !== 'undefined') {
            _ALL_SKILLS.forEach(function (g) {
                (g.items || []).forEach(function (it) {
                    // 已禁用的技能不进候选（如 auto-smtp-email）
                    if (String(it.d || '').indexOf('已禁用') >= 0) return;
                    flat.push({ it: it, group: g.g || '' });
                });
            });
        }
        items = flat.filter(function (row) {
            const it = row.it;
            const hay = [it.n, it.d, it.t].filter(Boolean).join(' ').toLowerCase();
            return !q || hay.indexOf(q) >= 0;
        }).map(function (row) {
            const it = row.it;
            const trig = String(it.t || '').split(/[、,，]/)[0].trim();
            return {
                label: it.n,
                sub: it.d || '',
                group: row.group,
                insert: (trig || it.n) + ' ',
                run: function () {},
            };
        });
    }
    if (seq !== _mentionSeq) return; // 期间又输入了，丢弃旧结果
    _mention = { kind: sym, start: start, items: items, idx: 0, query: query };
    _mentionRender();
}

function _mentionRender() {
    const m = _mentionEl();
    if (!m) return;
    if (!_mention.items.length) { m.classList.add('hidden'); m.innerHTML = ''; return; }
    let lastGroup = '';
    m.innerHTML = _mention.items.map(function (it, i) {
        let head = '';
        if (it.group && it.group !== lastGroup) {
            lastGroup = it.group;
            head = '<div class="mention-group">' + esc(it.group) + '</div>';
        }
        return head + '<div class="mention-item' + (i === _mention.idx ? ' on' : '') + '" role="option" data-i="' + i + '">' +
            '<b>' + esc(it.label) + '</b>' + (it.sub ? '<span class="sub">' + esc(it.sub) + '</span>' : '') + '</div>';
    }).join('');
    m.querySelectorAll('.mention-item').forEach(function (el) {
        el.addEventListener('mousedown', function (e) {
            e.preventDefault();
            _mentionPick(parseInt(el.getAttribute('data-i'), 10));
        });
    });
    m.classList.remove('hidden');
}

function _mentionMove(delta) {
    if (!_mention.items.length) return;
    _mention.idx = (_mention.idx + delta + _mention.items.length) % _mention.items.length;
    _mentionRender();
}

function _mentionPick(i) {
    const it = _mention.items[i];
    if (!it) return;
    const el = _chatScope().querySelector('#msg-input');
    if (!el) return;
    const caret = el.selectionStart || 0;
    el.value = el.value.slice(0, _mention.start) + (it.insert || '') + el.value.slice(caret);
    try { it.run(); } catch (e) {}
    _mentionClose();
    el.focus();
    el.style.height = '24px';
    el.style.height = (el.scrollHeight > 80 ? 80 : el.scrollHeight) + 'px';
}

function _chatInputKeydown(e) {
    // 下拉激活时（含加载中）：上下选择、Enter 选中、Esc 关闭；否则 Enter 发送
    if (_mention.kind) {
        if (e.key === 'ArrowDown') { e.preventDefault(); _mentionMove(1); return; }
        if (e.key === 'ArrowUp') { e.preventDefault(); _mentionMove(-1); return; }
        if (e.key === 'Escape') { e.preventDefault(); _mentionClose(); return; }
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (_mention.items.length) _mentionPick(_mention.idx);
            return;
        }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); }
}

function _chatLinkCustomer(c) {
    currentCustomerId = c.id;
    _chatLinkedName = c.name || ('#' + c.id);
    _renderChatLinkedChip();
    toast((currentLang === 'en' ? 'Linked customer: ' : '已关联客户：') + _chatLinkedName);
}

function _renderChatLinkedChip(root) {
    const scope = root || _chatScope();
    const el = scope.querySelector('#chat-linked-customer');
    if (!el) return;
    if (!currentCustomerId) { el.classList.add('hidden'); el.innerHTML = ''; return; }
    if (!_chatLinkedName && typeof allCustomers !== 'undefined') {
        const c = allCustomers.find(function (x) { return x.id === currentCustomerId; });
        if (c) _chatLinkedName = c.name || '';
    }
    el.innerHTML = '<span class="mono">@</span> ' + esc(_chatLinkedName || ('#' + currentCustomerId)) +
        ' <a href="#" class="chat-unlink" title="取消关联">×</a>';
    el.classList.remove('hidden');
    const un = el.querySelector('.chat-unlink');
    if (un) un.addEventListener('click', function (e) {
        e.preventDefault();
        currentCustomerId = null;
        _chatLinkedName = '';
        _renderChatLinkedChip();
    });
}

function _fillChatInput(text) {
    /** 把内容写进聊天输入框并聚焦（只填充，不发送）。 */
    const ct = currentChatContainer;
    if (!ct) return;
    const input = ct.querySelector('#msg-input');
    if (!input || !text) return;
    input.value = text;
    input.focus();
    input.style.height = '24px';
    input.style.height = (input.scrollHeight > 80 ? 80 : input.scrollHeight) + 'px';
}

async function _addTodoFromAction(action) {
    /** NEXT chip 的「加入待办」：直接写库并刷新右栏。 */
    const title = ((action && action.label) || '').trim();
    // 没有内容就不建空待办
    if (!title) { toast(t('todo.empty_label')); return; }
    const r = await api('POST', '/api/trade/todos', {title: title});
    if (!r) return;
    toast(t('todo.added'));
    await loadTodos(false);
}

function _handleNextAction(action) {
    /** NEXT chip：把动作写成可编辑的聊天指令，不自动外发。 */
    const act = (action && action.action) || '';
    let prompt = (action && action.label) || '';
    if (act === 'gen_pi') {
        prompt = prompt || t('chat.blocks.gen_pi_prompt');
    } else if (act === 'customs_lookup') {
        prompt = prompt || (currentLang === 'en'
            ? 'Look up customs import records for this customer'
            : '查这家客户的海关进口记录');
    } else if (act === 'add_todo') {
        // 待办已独立存储（P2-12）：直接落库，不再往聊天框塞指令
        _addTodoFromAction(action);
        return;
    } else {
        return;
    }
    _fillChatInput(prompt);
}

async function loadChatHistory() {
    if (!currentCompanyId) return;
    const ct = currentChatContainer;
    if (!ct) return;
    // 文档库视图按 library_id 过滤；统一对话（daily）按时间流汇总原 8 个入口历史
    const isUnified = currentChatContext === 'daily';
    const ctx = encodeURIComponent(currentChatContext || '');
    const params = currentLibraryId
        ? `?library_id=${currentLibraryId}&limit=30`
        : (isUnified ? '?limit=30' : `?context=${ctx}&limit=30`);
    const rawData = await api('GET', `/api/trade/conversations${params}`);
    if (!rawData || !rawData.length) return;
    // 统一对话流剔除绑定了文档库的纯文档库问答，避免与「文档库」入口重复
    const data = isUnified
        ? rawData.filter(function (c) { return !(c.context === 'docs' && c.library_id); })
        : rawData;
    if (!data.length) return;
    const container = ct.querySelector('#chat-messages');
    if (!container) return;
    // Remove empty state
    const emptyEl = container.querySelector('.empty-state');
    if (emptyEl) emptyEl.remove();

    container.innerHTML = '';
    data.reverse().forEach(c => {
        let filesRead = [];
        try {
            filesRead = Array.isArray(c.files_read) ? c.files_read
                : (c.files_read ? JSON.parse(c.files_read) : []);
        } catch(e) { filesRead = []; }
        if (c.query) addMsg('user', c.query, filesRead, false, null, null, c.created_at);
        // 结构化块随 extra1 回放（W10/P1-5）；没有块时保持纯文本
        const blocks = (c.extra1 && typeof c.extra1 === 'object')
            ? (c.extra1.trade_blocks || null) : null;
        if (c.response) addMsg('assistant', c.response, null, false, null, blocks, c.created_at);
    });
    // 加载历史后直接滚动到底部（最新消息）
    container.scrollTop = container.scrollHeight;
}

// ═════════════════════ SSE STREAMING ═════════════════════
const TOOL_NAMES = {
    read_file:'📄 读取文件',list_files:'📂 列出文件',search_files:'🔎 搜索文件',
    file_extract:'📋 提取文档',
    web_search:'🌐 搜索',web_fetch:'📥 抓取',memory_recall:'🧠 回忆',
    memory_retain:'💾 保存',execute_code:'💻 代码',terminal:'🖥️ 终端',
    delegate_task:'🤖 委派',vision:'👁️ 图像',skill_load:'📦 技能',
};
function fmtTool(name) { return TOOL_NAMES[name] || `🔧 ${name.replace(/_/g,' ')}`; }

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
        await loadTodos();
        return;
    }

    addMsg('user', query, null);
    input.value = '';
    input.style.height = '24px';  // 复位输入框高度
    const sendBtn = ct.querySelector('#send-btn');
    if (sendBtn) sendBtn.disabled = true;

    // 用户可主动取消 SSE 流（替代原硬性 10 分钟超时）
    // 网站诊断等复杂 skill 可能需要 >10 分钟，依赖 SSE 心跳保活即可
    // 归属记账：让切换公司时能统一作废这条流（否则旧流会写进新公司的窗口）
    const ownerCid = currentCompanyId;
    const streamCtl = _beginChatStream(ownerCid);
    _chatStreamActive++;   // 浮层据此区分“采集完成”与“正在生成回复”
    // 切公司后旧流的输出必须丢弃：addMsg 写的是全局 currentChatContainer
    function deliver(role, text, save, convId, blocks) {
        if (!_chatStreamBelongsTo(ownerCid)) return;
        addMsg(role, text, null, save, convId, blocks);
    }
    const container = ct.querySelector('#chat-messages');
    const progDiv = document.createElement('div');
    progDiv.className = 'message assistant waiting';
    progDiv.id = 'prog-' + Date.now();
    progDiv.innerHTML = '<div class="msg-avatar">🤖</div><div class="msg-body"></div>';
    const progBody = progDiv.querySelector('.msg-body');
    container.appendChild(progDiv);
    container.scrollTop = container.scrollHeight;

    // 统一等待界面：挂载失败时回落到旧的文字气泡（可用性优先，绝不阻断聊天）
    let wait = null;
    try {
        if (typeof TradeWait !== 'undefined') {
            wait = TradeWait.mount(progBody, {
                mode: 'chat',
                title: 'TRADE · ASSISTANT  ///  等待回复',
                onCancel: function () { streamCtl.abort(); },
            });
        }
    } catch (e) {
        console.warn('等待界面挂载失败，使用旧样式', e);
        wait = null;
    }
    if (!wait) {
        progBody.innerHTML = '<div class="thinking-msg">💭 ' + t('misc.thinking') +
            '</div><div class="elapsed" style="font-size:11px;color:var(--text-muted);margin-top:4px;"></div>';
    }

    const stopBtn = ct.querySelector('#stop-btn');
    if (stopBtn) {
        if (wait) {
            // 停止按钮由等待组件提供，旧按钮隐藏，避免两个停止入口
            stopBtn.classList.add('hidden');
            stopBtn.onclick = null;
        } else {
            stopBtn.classList.remove('hidden');
            stopBtn.onclick = () => streamCtl.abort();
        }
    }
    // 计时器只服务回落样式；统一组件自带 T+ 计时
    const startMs = Date.now();
    let elapsedTimer = null;
    if (!wait) {
        elapsedTimer = setInterval(() => {
            const sec = Math.floor((Date.now() - startMs) / 1000);
            const m = Math.floor(sec / 60), s = sec % 60;
            const tEl = progDiv.querySelector('.elapsed');
            if (tEl) tEl.textContent = `⏱ ${m}:${s.toString().padStart(2,'0')}`;
        }, 1000);
    }
    // 超过 45 秒没有任何字节：切到“连接等待中”（真实状态，不假装有进展）
    let silenceTimer = null;
    function armSilence() {
        if (!wait) return;
        clearTimeout(silenceTimer);
        silenceTimer = setTimeout(function () {
            if (wait && !wait.final) wait.phase('working', '连接等待中');
        }, 45000);
    }
    armSilence();

    const toolEls = {};
    let progressDiv = null;
    let responseText = '';
    let responseConvId = null;
    let responseBlocks = null;
    let sawDone = false;  // 服务端是否发过 done（区分「服务端没内容」与「连接断了」）
    _currentConvId = null;

    function ensureProgress() {
        if (!progressDiv) { progressDiv = document.createElement('div'); progressDiv.className = 'tool-progress'; progDiv.appendChild(progressDiv); }
        return progressDiv;
    }
    function addToolItem(tcId, name, status) {
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
        // 工具参数（args）可能含客户资料，任何等待样式都不显示
        body.appendChild(nameEl);
        el.appendChild(icon);
        el.appendChild(body);
        div.appendChild(el); container.scrollTop = container.scrollHeight;
        toolEls[tcId] = el;
    }
    function updateTool(tcId, status) {
        const el = toolEls[tcId]; if (!el) return;
        el.className = `tool-item ${status}`;
        el.querySelector('.tool-icon').textContent = status==='running'?'◌':status==='done'?'✓':'✗';
        container.scrollTop = container.scrollHeight;
    }

    try {
        const r = await fetch('/api/trade/chat/stream', {
            method:'POST',
            headers:{'Content-Type':'application/json','X-Hermes-Session-Token':TOKEN,'X-Company-ID':String(currentCompanyId)},
            body:JSON.stringify({library_id:currentLibraryId,customer_id:currentCustomerId,query,context:currentChatContext,language:currentLang}),
            signal:streamCtl.signal,
        });
        if (!r.ok) {
            progDiv.remove();
            if (r.status === 402) {
                const err = await r.json().catch(() => ({}));
                showLicenseExpired(err.detail || t('license.expired'));
            } else {
                deliver('assistant', `⚠️ 请求失败 (${r.status})`);
            }
            sendBtn.disabled = false;
            return;
        }

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
                    case 'tool_start':
                        if (wait) wait.push({type:'tool_start', id:data.tool_call_id, label:fmtTool(data.name)});
                        else addToolItem(data.tool_call_id,data.name,'running');
                        armSilence();
                        break;
                    case 'tool_complete':
                        if (wait) wait.push({type:'tool_complete', id:data.tool_call_id});
                        else updateTool(data.tool_call_id,'done');
                        // 后台背调刚启动：立刻刷新右栏任务面板，不必等切视图
                        if (data.name === 'osint_job_start' && typeof loadOsintJobs === 'function') loadOsintJobs(true);
                        break;
                    case 'job_attached':
                        // 后端确认了后台任务：在聊天流里挂 task 面板（工单 §4-B1）
                        _attachOsintTaskPanel(container, data);
                        break;
                    case 'thinking':
                        if (wait) wait.push({type:'thinking', message:data.message});
                        else if (!progDiv.querySelector('.thinking-msg')) { const t=document.createElement('div'); t.className='thinking-msg'; t.style.cssText='font-size:12px;color:var(--text-muted);padding:4px 0;'; t.textContent='💭 '+(data.message||'思考中...'); progDiv.appendChild(t); }
                        armSilence();
                        break;
                    case 'analysis_gate':
                        if (wait) {
                            wait.push({type:'analysis_gate',
                                ok: data.status === 'complete',
                                files: (data.files||[]).length,
                                note: data.coverage_note || ''});
                        } else {
                            // 不通过时正文会给出完整原因，这里只做一行进度提示。
                            const files = (data.files||[]).length;
                            const skipped = (data.skipped||[]);
                            const note = document.createElement('div'); note.className='thinking-msg';
                            const ok = data.status === 'complete';
                            note.style.cssText = 'font-size:12px;color:'+(ok?'var(--text-muted)':'var(--accent-red)')+';padding:4px 0;';
                            note.textContent = (ok ? '✓ 已完整读取 ' : '⚠ 完整读取未通过，已完整读取 ') + files + ' 个文件'
                                + (skipped.length ? '；未纳入：' + skipped.map(function(s){return s.file;}).join(', ') : '');
                            if (data.coverage_note) {
                                const cap = document.createElement('div');
                                cap.className = 'thinking-msg';
                                cap.style.cssText = 'font-size:12px;color:var(--text-muted);padding:2px 0 4px;';
                                cap.textContent = 'ℹ️ ' + data.coverage_note;
                                progDiv.appendChild(note);
                                progDiv.appendChild(cap);
                                break;
                            }
                            progDiv.appendChild(note);
                        }
                        break;
                    case 'response':
                        responseText = data.text||'';
                        responseConvId = data.conversation_id || null;
                        _currentConvId = data.conversation_id || null;
                        responseBlocks = data.blocks || null;
                        // 回答到达：等待组件让位（task 面板独立存在，不受影响）
                        if (wait) { wait.destroy(); wait = null; }
                        break;
                    case 'warning': if (data.message) toast('⚠️ ' + data.message); break;
                    case 'done': sawDone = true; break;  // 服务端正常收尾的标记（用于区分「服务端没内容」与「连接断了」）
                    case 'error':
                        if (wait) { wait.finish({phase:'failed'}); wait = null; }
                        progDiv.innerHTML=`<div class="msg-avatar" style="background:var(--accent-red);color:#fff;">⚠</div><div class="msg-body" style="color:var(--accent-red);">${esc(data.message)}</div>`;
                        sendBtn.disabled = false; return;
                    }
                    armSilence();
                    eventType='';dataStr='';
                }
            }
        }
        progDiv.remove();
        const outcome = _sseStreamOutcome(!!responseText, sawDone);
        if (outcome.kind === 'response') deliver('assistant', responseText, true, responseConvId, responseBlocks);
        else deliver('assistant', outcome.message, true, null);
    } catch(e) {
        _currentConvId = null;
        // AbortError 分两种：用户主动停止（应提示）与切公司导致的作废（不该再往页面写）
        if (e.name==='AbortError') {
            // 有等待面板时留在原地显示 ABORTED（组件按钮已是“已停止”）；回落样式照旧提示
            if (wait) { wait.finish({phase:'aborted'}); wait = null; }
            else { progDiv.remove(); deliver('assistant','🛑 已停止生成。'); }
        } else {
            if (wait) { wait.finish({phase:'failed'}); wait = null; }
            progDiv.remove();
            deliver('assistant',`网络错误：${e.message}`);
        }
    } finally {
        clearInterval(elapsedTimer);
        clearTimeout(silenceTimer);
        if (wait && !wait.final) { try { wait.destroy(); } catch (e) {} }
        _currentConvId = null;
        _endChatStream(streamCtl);
        _chatStreamActive = Math.max(0, _chatStreamActive - 1);
        _flushPendingDockVerdicts();
        _updateDock();
        if (stopBtn) { stopBtn.classList.add('hidden'); stopBtn.onclick = null; }
        // 每轮对话结束后刷新用量（后端在 agent 返回时已记账）
        loadUsageToday();
    }
    sendBtn.disabled = false;
}



// ── 后台背调任务（P1-1）────────────────────────────────────────────
// 任务在后端独立执行：切公司/刷新只停止本页渲染，不取消任务；
// 重新进入公司时按 seq 从头回放（不丢事件），运行中的任务继续追进度。

let _osintJobReaders = {};
let _osintJobCursors = {};   // jobId -> 已处理的最后 seq（断线重连只拉增量）

function _abortOsintJobReaders() {
    Object.keys(_osintJobReaders).forEach(function (key) {
        try { _osintJobReaders[key].abort(); } catch (e) {}
    });
    _osintJobReaders = {};
    _osintJobCursors = {};
}

function _osintStatusText(status) {
    const map = {
        queued: '排队中', running: '进行中', done: '已完成',
        partial: '未完成', failed: '失败', cancelled: '已取消',
    };
    return map[status] || String(status || '');
}

async function loadOsintJobs(isPoll) {
    if (!currentCompanyId) return;
    // 切公司（不是轮询）：气泡里的 task 面板属于旧公司，销毁；后端任务仍在跑。
    // 轮询刷新**不能**再 abort 读取器：job_attached 刚挂上面板时，一次并发的
    // loadOsintJobs 会把新连接掐掉，面板永远收不到 source 事件。
    if (_osintPanelsCompanyId !== null && _osintPanelsCompanyId !== currentCompanyId) {
        _detachOsintTaskPanels();
        _abortOsintJobReaders();
    }
    _osintPanelsCompanyId = currentCompanyId;
    const data = await api('GET', '/api/trade/osint/jobs?limit=10', null, undefined, {silent: !!isPoll});
    if (!data) return;
    const jobs = data.jobs || [];
    _renderRailOsintJobs(jobs);
    jobs.forEach(function (job) {
        if (job.status === 'queued' || job.status === 'running') _watchOsintJob(job.id);
    });
    // 刷新/重新进入公司：把仍在跑的任务恢复到浮层（事件按 seq 回放）
    jobs.forEach(function (job) {
        const running = job.status === 'queued' || job.status === 'running';
        if (running) {
            _attachOsintTaskPanel(null, {job_id: job.id, target: job.target, status: job.status});
            return;
        }
        const p = _osintTaskPanels[job.id];
        if (!p) return;
        p.status = job.status;
        // 聊天还在生成回复：采集完成也先别结束动画，等 _flushPendingDockVerdicts
        if (job.status === 'done' && _chatStreamActive > 0 && p.wait && !p.wait.final) {
            p.pendingVerdict = p.pendingVerdict || {rating: ''};
            p.wait.phase('composing', '采集完成，正在生成回复…');
            p.wait.cancelBtn.disabled = true;
            return;
        }
        if (p.wait && !p.wait.final) {
            const phase = job.status === 'cancelled' ? 'aborted' : (job.status === 'failed' ? 'failed' : 'acquired');
            const zh = job.status === 'partial' ? '未完成 · 已保存部分结果' : (phase === 'acquired' ? '采集完成' : undefined);
            p.wait.finish({phase: phase, zh: zh});
        }
    });
    _updateDock();
}

function _renderRailOsintJobs(jobs) {
    const el = document.getElementById('rail-osint-jobs');
    if (!el) return;
    if (!jobs.length) { el.innerHTML = ''; el.onclick = null; return; }

    let html = '<div class="rail-bh"><span class="t">' +
        (typeof iconHtml === 'function' ? iconHtml('search', 16) : '') +
        esc('后台背调') + '</span><span class="lbl">OSINT · ' +
        esc(String(jobs.length)) + '</span></div>';

    jobs.slice(0, 5).forEach(function (job) {
        const running = job.status === 'queued' || job.status === 'running';
        html += '<div class="rail-osint-item" data-job-id="' + esc(String(job.id)) + '">' +
            '<div class="osint-top"><span class="mono">' + esc(job.target) + '</span>' +
            '<span class="osint-status st-' + esc(job.status) + '">' +
            esc(_osintStatusText(job.status)) + '</span>' +
            (running ? '<button type="button" class="todo-del" data-role="cancel" aria-label="取消">×</button>' : '') +
            '</div>' +
            '<div class="rail-line" id="osint-prog-' + esc(String(job.id)) + '"></div>' +
            '</div>';
    });
    el.innerHTML = html;
    el.onclick = function (event) {
        const btn = event.target.closest('[data-role="cancel"]');
        if (!btn) return;
        const item = btn.closest('[data-job-id]');
        if (item) _cancelOsintJob(Number(item.getAttribute('data-job-id')));
    };
}

function _osintEventText(type, payload) {
    if (type === 'job_start') return '已启动（预算 ' + (payload.budget || '?') + ' 秒）';
    if (type === 'source_start') return '查询 ' + (payload.label || payload.source || '') + '…';
    if (type === 'source_done') {
        const st = {
            hit: '命中', candidate: '同名候选', miss: '未命中',
            error: '出错', timeout: '超时', skipped: '跳过', done: '完成',
        }[payload.status] || payload.status || '完成';
        return (payload.source || '来源') + '：' + st;
    }
    if (type === 'verdict') {
        const zh = {
            low: '低风险', medium: '中风险', high: '高风险',
            incomplete: '未完成核验', limited: '仅完成制裁筛查',
        }[payload.rating] || payload.rating || '未知';
        return '评级 ' + zh;
    }
    if (type === 'error') return '错误：' + (payload.message || '');
    if (type === 'cancelled') return '已取消';
    return type;
}

function _handleOsintJobSse(jobId, block) {
    const lines = String(block || '').split('\n');
    let type = '';
    let dataText = '';
    let seq = 0;
    lines.forEach(function (line) {
        if (line.indexOf('id: ') === 0) seq = parseInt(line.slice(4).trim(), 10) || 0;
        else if (line.indexOf('event: ') === 0) type = line.slice(7).trim();
        else if (line.indexOf('data: ') === 0) dataText = line.slice(6).trim();
    });
    if (!type || type === 'done') return;
    // 重连后只处理未见过的事件，避免日志重复、计数翻倍
    if (seq && seq <= (_osintJobCursors[jobId] || 0)) return;
    if (seq) _osintJobCursors[jobId] = seq;
    let payload = {};
    try { payload = JSON.parse(dataText || '{}'); } catch (e) { payload = {}; }
    const prog = document.getElementById('osint-prog-' + jobId);
    if (prog) prog.textContent = _osintEventText(type, payload);
    // 浮层里的 task 面板跟着同一条 SSE 驱动（节点/耗时/进度都来自真实事件）
    const panel = _osintTaskPanels[jobId];
    if (panel) {
        // 采集完成但答复还在生成：不要结束动画 —— 否则「动画结束」会被误读成
        // 「背调结束」。记下结论，等聊天流收尾时再 finish（文字继续提示生成中）。
        if (type === 'verdict' && _chatStreamActive > 0 && panel.wait && !panel.wait.final) {
            panel.pendingVerdict = payload;
            panel.status = 'done';
            panel.wait.phase('composing', '采集完成，正在生成回复…');
            panel.wait.cancelBtn.disabled = true;
            _updateDock();
            return;
        }
        if (type === 'error' || type === 'cancelled') panel.pendingVerdict = null;
        if (panel.wait && !panel.wait.final) {
            const ev = Object.assign({}, payload, {type: type});
            panel.wait.push(ev);
        }
        if (type === 'verdict') panel.status = 'done';
        else if (type === 'error') panel.status = 'failed';
        else if (type === 'cancelled') panel.status = 'cancelled';
        _updateDock();
    }
}

/** 聊天流收尾：把「采集完成、等回复」的面板补上结论并结束动画。 */
function _flushPendingDockVerdicts() {
    if (_chatStreamActive > 0) return;
    Object.keys(_osintTaskPanels).forEach(function (id) {
        const p = _osintTaskPanels[id];
        if (!p || !p.pendingVerdict || !p.wait || p.wait.final) return;
        const verdict = p.pendingVerdict;
        p.pendingVerdict = null;
        if (verdict && verdict.rating) {
            p.wait.push(Object.assign({}, verdict, {type: 'verdict'}));
            return;
        }
        // 轮询只知道「已完成」、列表接口不带评级：补一次详情再收尾。
        // 直接 finish 会让评级永久丢失 —— SSE 的 verdict 稍后到达时 wait
        // 已 final，push 被吞（2026-11-22 审计 O-19）。
        api('GET', '/api/trade/osint/jobs/' + id, null, undefined, {silent: true})
            .then(function (job) {
                const report = (job && job.report) || {};
                if (p.wait && !p.wait.final) {
                    if (report.overall_rating) {
                        p.wait.push({
                            type: 'verdict',
                            rating: report.overall_rating,
                            unverified: report.unverified || [],
                        });
                    } else {
                        p.wait.finish({phase: 'acquired', zh: '采集完成'});
                    }
                }
            })
            .catch(function () {
                if (p.wait && !p.wait.final) p.wait.finish({phase: 'acquired', zh: '采集完成'});
            });
    });
}

// 后台任务浮层：jobId -> {wait, tab, wrap, target, status}
// 非阻塞：浮层只占右下角，输入框、公司切换、栏目导航照常可用。
let _osintTaskPanels = {};
let _osintPanelsCompanyId = null;
let _osintActiveJobId = null;
let _osintDockHideTimer = null;
let _chatStreamActive = 0;

function _dockParts() {
    const root = document.getElementById('wait-dock');
    if (!root) return null;
    return {
        root: root,
        title: root.querySelector('.wd-title'),
        sub: root.querySelector('.wd-sub'),
        tabs: root.querySelector('.wd-tabs'),
        body: root.querySelector('.wd-body'),
        toggle: root.querySelector('.wd-toggle'),
    };
}

function _positionOsintDock(root) {
    /** 与**当前可见**的聊天输入区左右对齐（缓存视图里的隐藏输入区宽高为 0）。 */
    let ref = null;
    document.querySelectorAll('.chat-input-area').forEach(function (el) {
        if (ref) return;
        const r = el.getBoundingClientRect();
        // 隐藏的缓存视图 rect 为 0；选第一个真正有布局的
        if (r.width > 100 && r.height > 0) ref = el;
    });
    if (!ref) {
        // 非聊天视图：退回 CSS 的右下角兜底，绝不能把宽度设成 0
        root.style.left = '';
        root.style.right = '';
        root.style.width = '';
        root.style.bottom = '';
        return;
    }
    const r = ref.getBoundingClientRect();
    const dockW = Math.min(460, Math.max(280, Math.round(r.width)));
    root.style.right = 'auto';
    root.style.left = Math.max(12, Math.round(r.right - dockW)) + 'px';
    root.style.width = dockW + 'px';
    root.style.bottom = Math.max(12, Math.round(window.innerHeight - r.top + 12)) + 'px';
}

function _ensureDock() {
    const parts = _dockParts();
    if (!parts) return null;
    parts.root.classList.remove('hidden');
    if (!parts.root.dataset.bound) {
        parts.root.dataset.bound = '1';
        parts.toggle.addEventListener('click', function () {
            parts.root.classList.toggle('is-collapsed');
            parts.toggle.textContent = parts.root.classList.contains('is-collapsed') ? '展开' : '收起';
        });
        // 允许立即关闭浮层（尤其失败态不等 3 秒倒计时）
        if (!parts.root.querySelector('.wd-close')) {
            const closeBtn = document.createElement('button');
            closeBtn.type = 'button';
            closeBtn.className = 'wd-toggle wd-close';
            closeBtn.textContent = '关闭';
            closeBtn.addEventListener('click', function () {
                _detachOsintTaskPanels();
            });
            parts.toggle.parentNode.appendChild(closeBtn);
        }
        window.addEventListener('resize', function () {
            if (!parts.root.classList.contains('hidden')) _positionOsintDock(parts.root);
        });
    }
    _positionOsintDock(parts.root);
    return parts;
}

function _jobShortName(target) {
    return String(target || '').replace(/^(?:domain:|company:|公司:|person:|username:)/, '');
}

function _osintStatusZh(status) {
    const map = {queued: '排队中', running: '进行中', done: '已完成', failed: '失败', cancelled: '已取消', partial: '未完成'};
    return map[status] || '进行中';
}

function _updateDock() {
    const parts = _dockParts();
    if (!parts) return;
    // 内嵌到引导页等容器中的面板不进入全局右下角浮层
    const items = Object.keys(_osintTaskPanels)
        .map(function (id) { return _osintTaskPanels[id]; })
        .filter(function (p) { return p && !p.inline; });
    if (!items.length) { parts.root.classList.add('hidden'); return; }
    _ensureDock();
    _positionOsintDock(parts.root);

    const running = items.filter(function (p) { return p.status === 'queued' || p.status === 'running'; });
    let done = 0, total = 0;
    items.forEach(function (p) {
        const srcs = (p.wait && p.wait.sources) || [];
        total += srcs.length;
        done += srcs.filter(function (s) { return s.status !== 'running'; }).length;
    });
    parts.title.textContent = '后台任务 · ' + items.length + ' 项';
    if (running.length) {
        // 只用真实 source_start / source_done 计数
        parts.sub.textContent = '采集中 ' + done + ' / ' + total + ' · ' + running.length + ' 项进行中';
    } else if (_chatStreamActive > 0) {
        // 采集完了但答复还在生成：明确说出来，避免“动画结束=背调结束”的误判
        parts.sub.textContent = '采集完成，正在生成回复…';
    } else {
        parts.sub.textContent = '全部完成';
    }

    items.forEach(function (p) {
        if (!p.tab) return;
        p.tab.classList.toggle('is-done', p.status === 'done');
        p.tab.classList.toggle('is-bad', p.status === 'failed' || p.status === 'cancelled');
        p.tab.classList.toggle('is-active', String(_osintActiveJobId) === String(p.jobId));
        const st = p.tab.querySelector('.st');
        if (st) st.textContent = _osintStatusZh(p.status);
    });

    // 全部结束后：没有聊天在生成就自动收起（失败态快速收起避免长期遮挡）
    const allFailed = !running.length && items.every(function (p) {
        return p.status === 'failed' || p.status === 'cancelled';
    });
    clearTimeout(_osintDockHideTimer);
    if (!running.length && _chatStreamActive <= 0) {
        _osintDockHideTimer = setTimeout(function () {
            if (Object.keys(_osintTaskPanels).some(function (id) {
                const p = _osintTaskPanels[id];
                return p && !p.inline && (p.status === 'running' || p.status === 'queued');
            })) return;
            if (_chatStreamActive > 0) return;
            _detachOsintTaskPanels();
        }, allFailed ? 800 : 3000);
    }
}

function _selectOsintJob(jobId) {
    if (!_osintTaskPanels[jobId]) return;
    _osintActiveJobId = jobId;
    Object.keys(_osintTaskPanels).forEach(function (id) {
        const p = _osintTaskPanels[id];
        if (p.wrap) p.wrap.classList.toggle('is-active', String(id) === String(jobId));
    });
    _updateDock();
}

function _detachOsintTaskPanels() {
    Object.keys(_osintTaskPanels).forEach(function (id) {
        const p = _osintTaskPanels[id];
        try { if (p && p.wait) p.wait.destroy(); } catch (e) {}
        if (p && p.wrap && p.wrap.parentNode) p.wrap.parentNode.removeChild(p.wrap);
        if (p && p.tab && p.tab.parentNode) p.tab.parentNode.removeChild(p.tab);
    });
    _osintTaskPanels = {};
    _osintActiveJobId = null;
    clearTimeout(_osintDockHideTimer);
    const parts = _dockParts();
    if (parts) parts.root.classList.add('hidden');
}

function _attachOsintTaskPanel(container, job) {
    /** 把后台任务挂到右下角浮层；新手引导结果区则内嵌挂载，避免浮层遮挡按钮。 */
    if (!job || !job.job_id) return;
    if (typeof TradeWait === 'undefined') return;
    // 复用的已完成任务：右栏显示完成态即可，不挂浮层
    if (job.status && job.status !== 'queued' && job.status !== 'running') return;
    if (_osintTaskPanels[job.job_id]) return;
    const jobId = job.job_id;
    const target = _jobShortName(job.target);

    // P3：新手引导页传入 #onboarding-results-area 时内嵌在结果区内，不弹出全局 .wait-dock
    const isOnboarding = !!(
        container &&
        (container.id === 'onboarding-results-area' ||
            (typeof container.closest === 'function' && container.closest('.onboarding-card')))
    );
    if (isOnboarding) {
        const inlineBox = document.createElement('div');
        inlineBox.className = 'onb-osint-inline';
        const head = document.createElement('div');
        head.className = 'onb-osint-inline-head';
        const titleSpan = document.createElement('span');
        titleSpan.textContent = '后台背调 · ' + (target || ('任务 ' + jobId));
        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'onb-osint-inline-close';
        closeBtn.textContent = '收起';
        closeBtn.addEventListener('click', function () {
            const p = _osintTaskPanels[jobId];
            try { if (p && p.wait) p.wait.destroy(); } catch (e) {}
            if (inlineBox.parentNode) inlineBox.parentNode.removeChild(inlineBox);
            delete _osintTaskPanels[jobId];
        });
        head.appendChild(titleSpan);
        head.appendChild(closeBtn);
        inlineBox.appendChild(head);

        const body = document.createElement('div');
        inlineBox.appendChild(body);
        if (container.firstChild) container.insertBefore(inlineBox, container.firstChild);
        else container.appendChild(inlineBox);

        let wait = null;
        try {
            wait = TradeWait.mount(body, {
                mode: 'task',
                title: '背调 · BACKGROUND CHECK',
                statusLabel: '背调进行中',
                onCancel: function () { _cancelOsintJob(jobId); },
            });
        } catch (e) {
            console.warn('引导页内嵌背调面板挂载失败', e);
            inlineBox.remove();
            return;
        }
        _osintTaskPanels[jobId] = {
            jobId: jobId, target: target, wait: wait, tab: null, wrap: inlineBox,
            inline: true,
            status: job.status === 'queued' ? 'queued' : 'running',
        };
        _watchOsintJob(jobId);
        return;
    }

    const parts = _ensureDock();
    if (!parts) return;

    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'wd-tab';
    tab.textContent = target || ('任务 ' + jobId);
    const st = document.createElement('span');
    st.className = 'st';
    st.textContent = '进行中';
    tab.appendChild(st);
    tab.addEventListener('click', function () { _selectOsintJob(jobId); });
    parts.tabs.appendChild(tab);

    const wrap = document.createElement('div');
    // 先标 active 再 mount：隐藏容器宽高为 0，组件会画不出（并可能抛半径错误）
    wrap.className = 'wd-task is-active';
    parts.body.appendChild(wrap);

    let wait = null;
    try {
        wait = TradeWait.mount(wrap, {
            mode: 'task',
            title: '背调 · BACKGROUND CHECK',
            statusLabel: '背调进行中',
            onCancel: function () { _cancelOsintJob(jobId); },
        });
    } catch (e) {
        console.warn('背调 task 面板挂载失败', e);
        wrap.remove(); tab.remove();
        return;
    }
    _osintTaskPanels[jobId] = {
        jobId: jobId, target: target, wait: wait, tab: tab, wrap: wrap,
        status: job.status === 'queued' ? 'queued' : 'running',
    };
    if (_osintActiveJobId == null) _osintActiveJobId = jobId;
    else _selectOsintJob(_osintActiveJobId);
    _updateDock();
    _watchOsintJob(jobId);
}

function _watchOsintJob(jobId) {
    if (_osintJobReaders[jobId]) return;
    const controller = new AbortController();
    _osintJobReaders[jobId] = controller;
    const companyId = currentCompanyId;

    (async function () {
        try {
            const resp = await fetch('/api/trade/osint/jobs/' + jobId + '/events?after=' +
                (_osintJobCursors[jobId] || 0), {
                headers: {'X-Hermes-Session-Token': TOKEN, 'X-Company-ID': String(companyId)},
                signal: controller.signal,
            });
            if (!resp.ok || !resp.body) return;
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            while (true) {
                const chunk = await reader.read();
                if (chunk.done) break;
                buffer += decoder.decode(chunk.value, {stream: true});
                let idx;
                while ((idx = buffer.indexOf('\n\n')) >= 0) {
                    const block = buffer.slice(0, idx);
                    buffer = buffer.slice(idx + 2);
                    _handleOsintJobSse(jobId, block);
                }
            }
        } catch (e) {
            // abort（切公司/刷新）与网络错误都静默；任务在后端继续
        } finally {
            delete _osintJobReaders[jobId];
            if (currentCompanyId === companyId) loadOsintJobs(true).catch(function () {});
        }
    })();
}

async function _cancelOsintJob(jobId) {
    const r = await api('POST', '/api/trade/osint/jobs/' + jobId + '/cancel');
    if (r) await loadOsintJobs(true);
}
