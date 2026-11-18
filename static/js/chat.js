// ═════════════════════ CHAT VIEW ═════════════════════
function renderChatViewInto(container, ctx, name) {
    const coName = currentCompanyId ? (companies.find(c => c.id === currentCompanyId)?.name || '') : '';
    const isDaily = ctx === 'daily';
    // 今日简报：zip s1 两栏（对话 + 右侧简报/待办/定时任务），不再用页内标题条
    const topbarHtml = isDaily ? '' : `
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
            <div class="chat-input-inner">
                <textarea id="msg-input" aria-label="${currentLang==='en'?'Message':'输入消息'}" placeholder="AWAITING COMMAND · ${esc(t('chat.ph.' + ctx))}" rows="1"
                    onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMsg();}"
                    oninput="this.style.height='24px';this.style.height=(this.scrollHeight>80?80:this.scrollHeight)+'px';"></textarea>
                <button type="button" class="chat-attach-btn" id="attach-btn" title="${currentLang==='en'?'Attach files':'添加文件'}" aria-label="${currentLang==='en'?'Attach files':'添加文件'}">${typeof iconHtml==='function'?iconHtml('paperclip',20):'📎'}</button>
                <input type="file" id="chat-file-input" multiple hidden>
                <button type="button" class="chat-send-btn" onclick="sendMsg()" id="send-btn" title="${currentLang==='en'?'Send':'发送'}">${typeof iconHtml==='function'?iconHtml('send',16):''}<span>${currentLang==='en'?'Send':'发送'}</span></button>
                <button type="button" class="chat-stop-btn hidden" id="stop-btn" title="${currentLang==='en'?'Stop':'停止'}">■ ${currentLang==='en'?'Stop':'停止'}</button>
            </div>
        </div>
        </section>
        </div>
        <div class="drop-overlay" id="drop-overlay"><div class="drop-overlay-inner">&#128193; ${currentLang==='en'?'Drop files to add':'释放以添加文件'}</div></div>`;

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
    // 每日简报视图：额外拉取一次 cron 状态（全局轮询已覆盖）+ 今日 KPI
    if (ctx === 'daily') {
        _shownCronOutputs = new Set();
        loadCronStatus(false);
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
            '<div class="rail-bh"><span class="t">' + esc(t('brief.title')) + '</span>' +
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

async function doUpdateSystem() {
    const btn = document.getElementById('update-banner');
    if (!(await _confirmTradeUpdate())) return;
    if (btn) btn.textContent = '更新中...';
    _setUpdateInFlight(true);
    try {
        const resp = await api('POST', '/api/trade/system/update',
            {target_sha: _pendingUpdateTarget || null},
            {'X-Confirm-Update': 'yes'});
        if (resp?.ok) {
            // 只显示用户在确认框里见过的 SHA；预览失败时宁可不显示
            const appliedShort = (_pendingUpdateTarget || '').slice(0, 8);
            const suffix = appliedShort ? '（目标 ' + appliedShort + '）' : '';
            toast('✅ 更新完成。请点击"🔄 重启"以应用新版本。' + suffix);
            // 非致命步骤失败只算警告，不阻止升级，但必须让用户看见
            if (resp.warnings && resp.warnings.length) {
                toast('⚠️ 升级完成，但有 ' + resp.warnings.length + ' 项警告：' + resp.warnings.join('; '),
                    {sticky: true});
            }
            // 后端永不自动重启：升级**全部完成**后才露出重启按钮
            if (btn) { btn.remove(); }
            _setUpdateInFlight(false);
            _showRestartPrompt();
            checkVersion();
        } else if (resp?.error || (resp?.errors && resp.errors.length)) {
            // 之前这里只有一句「更新失败」，用户无从知道原因
            toast(_updateErrorText(resp), {sticky: true});
            if (btn) btn.textContent = '⬆️ 升级';
            _setUpdateInFlight(false);
        } else {
            // resp 为 null 时 api() 已 toast，不重复提示
            _setUpdateInFlight(false);
        }
    } catch(e) {
        // 更新请求不会触发服务重启（后端不自动重启）：按普通网络失败处理
        toast(t('sys.update_network'));
        if (btn) btn.textContent = '⬆️ 升级';
        _setUpdateInFlight(false);
    }
}

async function loadCronStatus(isPoll = false) {
    if (!currentCompanyId) return;
    const data = await api('GET', '/api/trade/cron/today', null, undefined, {
        silent: isPoll,
    });
    if (!data) return;
    const {completed, pending, current_time} = data;

    // 常驻右栏：今日待办 + 定时任务输出（所有主视图；详情页由 CSS 隐藏）
    const railTodo = document.getElementById('rail-todo');
    if (railTodo) {
        // 标红：当前时间落到条目执行窗口内（与后端同一口径）
        // - 用后端 current_time（不是浏览器 new Date），避免两套时间源在跨分钟时打架
        // - missed（已过窗口终点）/ unknown_schedule 一律不红：漏做的任务不是「当前」
        // - 单点任务「15:30」窗口就是该分钟；范围「09:00-10:30」窗口为区间
        function _toMin(hhmm) {
            const m = String(hhmm || '').match(/^(\d{1,2}):(\d{2})/);
            return m ? (parseInt(m[1], 10) * 60 + parseInt(m[2], 10)) : null;
        }
        let _nowMin = _toMin(current_time);
        if (_nowMin == null) { const d = new Date(); _nowMin = d.getHours() * 60 + d.getMinutes(); }
        function _taskIsNow(task) {
            if (!task || task.unknown_schedule || task.missed) return false;
            const parts = String(task.time || '').split('-');
            const s = _toMin(parts[0]);
            if (s == null) return false;
            const e = (parts.length > 1) ? _toMin(parts[1]) : s;
            if (e == null) return false;
            return _nowMin >= s && _nowMin <= e;
        }
        let todoHtml = '<div class="rail-bh"><span class="t">' + esc(t('brief.todo')) +
            '</span><span class="lbl">TODO · ' + (pending.length + completed.length) + '</span></div>';
        for (const task of pending) {
            todoHtml += '<div class="rail-todo-item' + (_taskIsNow(task) ? ' now' : '') + '"><span class="tx">' +
                esc(task.name) + '<span class="sub">' + esc(task.time || '') + '</span></span></div>';
        }
        for (const task of completed) {
            todoHtml += '<div class="rail-todo-item done"><span class="tx">' +
                esc(task.name) + '<span class="sub">' + esc(task.time || '') + '</span></span></div>';
        }
        // 轮询每 30s 会重建列表：保留用户滚动位置，避免跳回顶部
        const _todoScroll = railTodo.scrollTop;
        railTodo.innerHTML = todoHtml;
        railTodo.scrollTop = _todoScroll;
        const railCron = document.getElementById('rail-cron');
        if (railCron) {
            let cronHtml = '<div class="rail-bh"><span class="t">' + esc(t('brief.cron')) +
                '</span><span class="lbl">CRON</span></div>';
            const outs = completed.filter(function (x) { return x.output; }).slice(0, 4);
            if (!outs.length) {
                cronHtml += '<p class="rail-line">' + esc(t('brief.cron_empty')) + '</p>';
            }
            outs.forEach(function (task) {
                const line = String(task.output || '').replace(/\s+/g, ' ').slice(0, 90);
                cronHtml += '<div class="rail-cron-item"><span class="mono">' +
                    esc(task.time || '') + '</span><span>' + esc(line) + '</span></div>';
            });
            railCron.innerHTML = cronHtml;
        }
        loadTodayBrief(isPoll).catch(function () {});
        return;
    }

    // 顶部进度横幅已下线：其功能（今日简报/待办/定时任务）由常驻右栏承载。
    // 右栏缺失时无需再兜底渲染（正常情况 #app-rail 常驻）。
    return;

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
                panelHtml += `<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:13px;"><span style="color:var(--accent-green);">✓</span><span style="font-weight:500;">${esc(t.name)}</span><span style="color:var(--text-muted);font-size:11px;">${esc(t.time)}</span></div>`;
            }
        }
        if (pending.length) {
            panelHtml += `<div style="font-size:12px;color:var(--text-secondary);margin:6px 0;">待处理 (${pending.length})</div>`;
            for (const t of pending) {
                panelHtml += _cronTaskLine(t);
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
    const raw = marked.parse(content || '');
    body.innerHTML = DOMPurify.sanitize(raw, {
        ALLOWED_TAGS: ['p','br','strong','em','b','i','ul','ol','li','h1','h2','h3','h4','h5','h6',
            'blockquote','code','pre','a','table','thead','tbody','tr','th','td','hr','span','div','img'],
        ALLOWED_ATTR: ['href','target','class','id','style','src','alt','width','height'],
    });
    if (files && files.length) {
        const s = document.createElement('div'); s.className = 'sources';
        s.innerHTML = '<div class="sources-title">📄 '+(currentLang==='en'?'References':'参考文件')+'</div>' + files.map(f => '<div>📎 '+esc(f.file||f)+(f.status==='cached' ? ' <span class="muted">（'+(currentLang==='en'?'from cached extraction':'来自缓存提取')+'）</span>' : '')+'</div>').join('');
        body.appendChild(s);
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
        head.innerHTML = '<span class="mh-tag">▶ TRADE · ASSISTANT</span>' +
            '<span class="mh-rule"></span><span class="mh-t">' + _msgHHMM(timeStr) + '</span>';
        msgHead = head;
        div.appendChild(head);
    }
    div.appendChild(body);

    // AI 回复右侧加「📋 复制」按钮，点击写入剪贴板
    if (role === 'assistant' && content) {
        const copyBtn = document.createElement('button');
        copyBtn.textContent = '📋';
        copyBtn.title = currentLang==='en'?'Copy to clipboard':'复制到剪贴板';
        // 复制按钮：无外框，放进助手标题行右侧（跟随标题，短消息也不会下溢遮挡下一条）
        copyBtn.style.cssText = 'background:none;border:none;padding:0 2px;font-size:15px;line-height:1;cursor:pointer;color:var(--muted);opacity:0.7;transition:opacity 0.15s;';
        copyBtn.onmouseenter = function() { this.style.opacity = '1'; };
        copyBtn.onmouseleave = function() { this.style.opacity = '0.7'; };
        copyBtn.onclick = function(e) {
            e.stopPropagation();
            navigator.clipboard.writeText(content).then(function() {
                copyBtn.textContent = '✅'; setTimeout(function() { copyBtn.textContent = '📋'; }, 1500);
            }).catch(function() {
                copyBtn.textContent = '❌'; setTimeout(function() { copyBtn.textContent = '📋'; }, 1500);
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
            + '<span class="warn">' + esc(t('chat.blocks.draft_warn')) + '</span></div>'
            + (d.subject ? '<div class="subj">' + esc(d.subject) + '</div>' : '')
            + '<pre class="body">' + esc(d.body || '') + '</pre>'
            + '<button type="button" class="draft-copy">' + esc(t('chat.blocks.copy_draft')) + '</button>';
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

function _handleNextAction(action) {
    /** NEXT chip：把动作写成可编辑的聊天指令，不自动外发。 */
    const ct = currentChatContainer;
    if (!ct) return;
    const input = ct.querySelector('#msg-input');
    if (!input) return;
    const act = (action && action.action) || '';
    let prompt = (action && action.label) || '';
    if (act === 'gen_pi') {
        prompt = prompt || (currentLang === 'en'
            ? 'Generate a PI from this quotation'
            : '按这份报价生成 PI');
    } else if (act === 'customs_lookup') {
        prompt = prompt || (currentLang === 'en'
            ? 'Look up customs import records for this customer'
            : '查这家客户的海关进口记录');
    } else {
        // add_todo 等未接线动作：不填入
        return;
    }
    input.value = prompt;
    input.focus();
    input.style.height = '24px';
    input.style.height = (input.scrollHeight > 80 ? 80 : input.scrollHeight) + 'px';
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
    // 归属记账：让切换公司时能统一作废这条流（否则旧流会写进新公司的窗口）
    const ownerCid = currentCompanyId;
    const streamCtl = _beginChatStream(ownerCid);
    // 切公司后旧流的输出必须丢弃：addMsg 写的是全局 currentChatContainer
    function deliver(role, text, save, convId, blocks) {
        if (!_chatStreamBelongsTo(ownerCid)) return;
        addMsg(role, text, null, save, convId, blocks);
    }
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
    let responseBlocks = null;
    let sawDone = false;  // 服务端是否发过 done（区分「服务端没内容」与「连接断了」）
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
                    case 'tool_start': addToolItem(data.tool_call_id,data.name,'running',data.args?Object.entries(data.args).map(([k,v])=>`${k}=${fmtArg(v)}`).join(', '):''); break;
                    case 'tool_complete': updateTool(data.tool_call_id,'done',data.result_preview||'完成'); break;
                    case 'thinking':
                        if (!progDiv.querySelector('.thinking-msg')) { const t=document.createElement('div'); t.className='thinking-msg'; t.style.cssText='font-size:12px;color:var(--text-muted);padding:4px 0;'; t.textContent='💭 '+(data.message||'思考中...'); progDiv.appendChild(t); }
                        break;
                    case 'analysis_gate': {
                        // 不通过时正文会给出完整原因，这里只做一行进度提示。
                        const files = (data.files||[]).length;
                        const skipped = (data.skipped||[]);
                        const note = document.createElement('div'); note.className='thinking-msg';
                        const ok = data.status === 'complete';
                        note.style.cssText = 'font-size:12px;color:'+(ok?'var(--text-muted)':'var(--accent-red)')+';padding:4px 0;';
                        note.textContent = (ok ? '✓ 已完整读取 ' : '⚠ 完整读取未通过，已完整读取 ') + files + ' 个文件'
                            + (skipped.length ? '；未纳入：' + skipped.map(function(s){return s.file;}).join(', ') : '');
                        // 能力边界如实披露：本机无法逐 Sheet/逐页核验时必须说出来
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
                        break;
                    }
                    case 'response':
                        responseText = data.text||'';
                        responseConvId = data.conversation_id || null;
                        _currentConvId = data.conversation_id || null;
                        responseBlocks = data.blocks || null;
                        break;
                    case 'warning': if (data.message) toast('⚠️ ' + data.message); break;
                    case 'done': sawDone = true; break;  // 服务端正常收尾的标记（用于区分「服务端没内容」与「连接断了」）
                    case 'error': progDiv.innerHTML=`<div class="msg-avatar" style="background:var(--accent-red);color:#fff;">⚠</div><div class="msg-body" style="color:var(--accent-red);">${esc(data.message)}</div>`; sendBtn.disabled = false; return;
                    }
                    eventType='';dataStr='';
                }
            }
        }
        progDiv.remove();
        const outcome = _sseStreamOutcome(!!responseText, sawDone);
        if (outcome.kind === 'response') deliver('assistant', responseText, true, responseConvId, responseBlocks);
        else deliver('assistant', outcome.message, true, null);
    } catch(e) {
        progDiv.remove();
        _currentConvId = null;
        // AbortError 分两种：用户主动停止（应提示）与切公司导致的作废（不该再往页面写）
        if (e.name==='AbortError') deliver('assistant','🛑 已停止生成。');
        else deliver('assistant',`网络错误：${e.message}`);
    } finally {
        clearInterval(elapsedTimer);
        _currentConvId = null;
        _endChatStream(streamCtl);
        if (stopBtn) { stopBtn.classList.add('hidden'); stopBtn.onclick = null; }
        // 每轮对话结束后刷新用量（后端在 agent 返回时已记账）
        loadUsageToday();
    }
    sendBtn.disabled = false;
}

