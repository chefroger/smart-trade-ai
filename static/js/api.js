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

// #region api-opts —— 这段被 tests_js/api-opts.test.js 按标记整体抽取测试，勿删标记
// 构造请求选项：鉴权头 + body 编码。
// FormData（文件上传）必须原样透传且不设 Content-Type —— 否则会丢掉 multipart 的 boundary。
function _buildApiOpts(method, body, token, companyId, extraHeaders) {
    const opts = { method: method, headers: {} };
    if (token) opts.headers['X-Hermes-Session-Token'] = token;
    if (companyId) opts.headers['X-Company-ID'] = String(companyId);
    // 需要额外 header 的端点（如删除公司要 X-Confirm-Delete）走这里
    if (extraHeaders) Object.assign(opts.headers, extraHeaders);
    if (body instanceof FormData) {
        opts.body = body;
    } else if (body) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(normalizeBody(body));
    }
    return opts;
}
// #endregion api-opts

async function api(method, path, body, extraHeaders) {
    const opts = _buildApiOpts(method, body, TOKEN, currentCompanyId, extraHeaders);
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
            // 5xx / 429 是「用户需要看清原因」的失败，常驻显示
            else toast(msg, {sticky: r.status >= 500 || r.status === 429});
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

// #region license-gate
// 是否已付费激活（整机一份，见 trade/license.py）。
// 试用 / 到期 / tampered / license.json 被删 → activated=false，付费入口隐藏。
let _licenseActivated = false;
// 许可证状态读取失败/超时：付费界面 fail-open（可用性优先；界面隐藏不是安全边界）。
// 注意：license.json 被删时接口会正常返回 trial/expired，走成功分支，不会置这个标记。
let _licenseGateUnknown = false;

// 与左侧被 data-paid 隐藏的三组栏目保持一致：
// 销售转化（customers/docs/docgen）、工具（osint/tasks）、历史（history）。
const _PAID_VIEWS = new Set(['customers', 'tasks', 'history']);
const _PAID_CHAT_CTX = new Set(['docs', 'docgen', 'osint']);

function _isPaidDestination(view, chatCtx) {
    return _PAID_VIEWS.has(view) || (view === 'chat' && _PAID_CHAT_CTX.has(chatCtx || ''));
}

function _licenseGateAllowsPaid() {
    return _licenseActivated || _licenseGateUnknown;
}

/**
 * 按许可证状态开关付费功能的界面入口。
 * - 所有 [data-paid] 元素：默认 hidden，付费激活（或状态读取失败 fail-open）后显示；
 * - 「导入公司数据」那一行与公司列表「导出」按钮沿用同一判定；
 * - 状态变化时若公司弹窗正开着就重画一次。
 */
function _applyLicenseGates() {
    const showPaid = _licenseGateAllowsPaid();
    document.querySelectorAll('[data-paid]').forEach(el => {
        el.classList.toggle('hidden', !showPaid);
    });
    const row = document.getElementById('import-company-row');
    if (row) row.classList.toggle('hidden', !showPaid);
    const modal = document.getElementById('company-modal');
    if (modal && !modal.classList.contains('hidden')) loadCompanyListUI();
    // 运行中失去付费权限（例如 license.json 被删除后窗口重新聚焦）：如果当前正停在
    // 付费视图上，退回今日简报，避免内容继续可见。初始化阶段 currentCompanyId 还是
    // 空，不会在这里触发跳转。
    if (!showPaid
            && typeof currentCompanyId !== 'undefined' && currentCompanyId
            && typeof currentView !== 'undefined'
            && _isPaidDestination(currentView, currentChatContext)
            && typeof navToView === 'function') {
        navToView('chat', 'daily', '今日简报');
    }
}
// #endregion license-gate

async function loadLicenseStatus() {
    const ctrl = new AbortController();
    // 本地接口正常是毫秒级；超时也不锁界面，走下面的 fail-open。
    // 2 秒：初始化会 await 这个调用，不能让许可证接口把整个界面拖住。
    const timeoutId = setTimeout(() => ctrl.abort(), 2000);
    try {
        const opts = _buildApiOpts('GET', null, TOKEN, currentCompanyId);
        opts.signal = ctrl.signal;
        const r = await fetch('/api/trade/license/status', opts);
        if (!r.ok) throw new Error('license status ' + r.status);
        const data = await r.json();
        _licenseActivated = !!data.activated;
        _licenseGateUnknown = false;
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
            // 软着陆：说明数据还在、只是起草暂停，并保留激活入口
            bar.innerHTML = '⚠️ ' + t('license.expired') + ' · ' + t('license.expired_soft')
                + ' · <a href="#" onclick="showActivateModal()" style="color:#DC2626;text-decoration:underline;">' + t('license.activate_btn') + '</a>' + reqCodeHtml;
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
            // 第 20 天起显示价值小结（只报真实事件数，不估算）
            if (data.trial_summary) {
                var _ts = data.trial_summary;
                bar.innerHTML += '<div style="margin-top:4px;font-size:11px;opacity:.9;">📊 '
                    + esc(t('license.trial_summary')
                        .replace('{drafts}', String(_ts.drafts || 0))
                        .replace('{inquiries}', String(_ts.inquiries || 0))
                        .replace('{lookups}', String(_ts.product_lookups || 0)))
                    + '</div>';
            }
        } else if (data.status === 'tampered') {
            bar.style.display = 'block'; bar.style.background = '#FEF2F2'; bar.style.color = '#991B1B';
            bar.innerHTML = '⚠️ License Error · <a href="#" onclick="showActivateModal()" style="color:#DC2626;text-decoration:underline;font-weight:600;">Reactivate</a>' + reqCodeHtml;
        }
    } catch(e) {
        // 读不到状态（网络/401/超时）：付费 UI fail-open，不能因为本地接口抖动
        // 把付费用户的栏目全部藏掉。license.json 被删时接口正常返回 trial/expired，
        // 走上面的成功分支，会隐藏付费入口。
        _licenseGateUnknown = true;
    } finally {
        clearTimeout(timeoutId);
        _applyLicenseGates();
    }
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
        var s = await fetch('/api/trade/license/status', _buildApiOpts('GET', null, TOKEN, currentCompanyId));
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
        const r = await fetch('/api/trade/license/activate',
            _buildApiOpts('POST', {code}, TOKEN, currentCompanyId));
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
//
// maxSeconds：兜底等待秒数，默认 120（重启场景足够）。
// **重建运行环境必须传更大的值** —— 那一步要建 venv + 装全部依赖，5~10 分钟是常态，
// 用默认的 2 分钟会在真正成功之前就报「超时」，把用户吓去手动折腾。
async function _waitForRestartAndReload(onTimeout, maxSeconds) {
    let attempts = 0;
    const maxAttempts = maxSeconds || 120;   // 每 1 秒一次轮询
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

/**
 * 切换侧边栏按钮的「忙」态：忙时图标换成沙漏并禁用，闲时恢复原图标。
 *
 * 图标化之后不能再沿用旧写法（把 textContent 设成「更新中…」这样的文字）——
 * 那会把按钮上的图标直接抹掉，恢复时还得重新知道原图标长什么样。
 * 原图标记在 dataset 里，连续多次 busy 也不会把沙漏本身记成原图标。
 */
function _setBtnBusy(btn, busy) {
    if (!btn) return;
    if (busy) {
        if (btn.dataset.idleIcon === undefined) btn.dataset.idleIcon = btn.textContent;
        btn.disabled = true;
        btn.textContent = '⏳';
    } else {
        btn.disabled = false;
        if (btn.dataset.idleIcon !== undefined) btn.textContent = btn.dataset.idleIcon;
    }
}

// ── 今日 token 用量（只提示，不拦截）──
/**
 * 刷新侧栏底部的「今日已用 X / 上限」。
 *
 * 审计 P1-16 的额度提示，按用户要求**不做拦截**：超过上限只把文字标红，
 * 聊天照常执行。用裸 fetch 而不是 api()：失败时不该弹 toast 打扰聊天。
 */
async function loadUsageToday() {
    const el = $('usage-today');
    if (!el) return;
    if (!currentCompanyId) { el.hidden = true; return; }
    try {
        // 加时间戳 + no-store：额度会变，浏览器缓存旧响应会让升级后仍显示旧阈值
        const opts = _buildApiOpts('GET', null, TOKEN, currentCompanyId);
        opts.cache = 'no-store';
        const r = await fetch('/api/trade/usage/today?_=' + Date.now(), opts);
        if (!r.ok) { el.hidden = true; return; }
        const d = await r.json();
        const used = Number(d.used) || 0;
        const limit = Number(d.limit) || 0;
        const fmt = n => Number(n).toLocaleString('en-US');
        el.hidden = false;
        el.classList.toggle('over', !!d.exceeded);
        el.classList.toggle('warn', !d.exceeded && limit > 0 && used >= limit * 0.8);
        if (d.exceeded) {
            el.textContent = t('usage.over').replace('{used}', fmt(used)).replace('{limit}', fmt(limit));
        } else if (limit > 0) {
            el.textContent = t('usage.today').replace('{used}', fmt(used)).replace('{limit}', fmt(limit));
        } else {
            el.textContent = t('usage.unlimited').replace('{used}', fmt(used));
        }
    } catch(_) {
        el.hidden = true;
    }
}

// ── 系统更新 ──
let _pendingUpdateTarget = '';

/**
 * 更新前二次确认：展示当前版本 + 本次要安装的目标提交短 SHA。
 *
 * 目标 SHA 来自预览接口，并原样带到 /system/update —— 后端钉在这个提交上，
 * 保证"确认框看到的版本 = 实际安装的版本"（2026-10-28 口径）。
 * 预览失败时退回通用文案（确认本身不能因网络失败被跳过）。
 */
async function _confirmTradeUpdate() {
    let current = '';
    let target = '';
    _pendingUpdateTarget = '';
    try {
        const r = await fetch('/api/status?_=' + Date.now(), { cache: 'no-store' });
        if (r.ok) {
            const d = await r.json();
            current = d.version || '';
        }
    } catch(_) { /* 版本信息拿不到不影响确认 */ }
    try {
        const r = await fetch('/api/trade/system/update-preview?_=' + Date.now(), {
            cache: 'no-store',
            headers: {'X-Hermes-Session-Token': TOKEN},
        });
        if (r.ok) {
            const d = await r.json();
            if (d.ok && d.sha) {
                _pendingUpdateTarget = d.sha;
                target = d.short || d.sha.slice(0, 8);
            }
        }
    } catch(_) { /* 预览失败：后端会临场取 main，确认照常进行 */ }
    const msg = (current || target)
        ? t('sys.update_confirm_current')
            .replace('{current}', current || '?')
            .replace('{target}', target || '?')
        : t('sys.update_confirm');
    return confirm(msg);
}

/**
 * 更新完成后露出「重启」按钮（更新不再自动重启）。
 *
 * 为什么不自动重启：新代码起不来时旧服务还在，用户可以先看到更新结果、
 * 再决定何时重启；这是 audit P1-10 明确允许的替代方案。
 */
function _showRestartPrompt() {
    const rb = $('system-restart-btn');
    // 升级进行中绝不露出：此时重启会把升级打断，按钮必须等升级结束才出现
    if (rb && !_tradeUpdateInFlight) rb.hidden = false;
}

/**
 * 把升级失败结果拼成一段时间不会消失的提示文本。
 *
 * 后端返回 {error, errors, messages}：error 是给用户看的短句，messages 是
 * 逐步日志。只显示前半句时用户无法自助排查，所以附上日志最后几行。
 */
function _updateErrorText(resp) {
    const err = (resp && (resp.error || (resp.errors && resp.errors.join('; ')))) || '未知原因';
    let text = '❌ 更新失败：' + err;
    const msgs = (resp && resp.messages) || [];
    if (msgs.length) {
        // 最后 4 行足以定位（git / pip 的报错都在末尾），避免糊一屏
        text += '\n\n' + msgs.slice(-4).join('\n');
    }
    return text;
}

// 更新与重启必须串行：升级请求还在跑时点重启，watchdog 会把跑升级的进程
// 一起杀掉，pip 安装 / 模板同步 / 数据库检查全部中断
// （2026-11-11 实测：用户在 Step 3/7 点了重启，升级只做了一半）。
let _tradeUpdateInFlight = false;
// 升级前重启按钮是否已经可见（Hermes 升级等场景会提前露出）——
// 升级期间先收起，升级失败时按原样恢复。
let _restartPromptBeforeUpdate = false;

function _setUpdateInFlight(active) {
    _tradeUpdateInFlight = active;
    const rb = document.getElementById('system-restart-btn');
    if (!rb) return;
    rb.disabled = active;
    if (active) {
        // 升级期间收起重启按钮：它属于「升级完成后」的动作。提前露出来
        // 用户就会在升级途中点它，把升级线程一起杀掉（2026-11-11 实测）。
        _restartPromptBeforeUpdate = !rb.hidden;
        rb.hidden = true;
    } else if (_restartPromptBeforeUpdate) {
        rb.hidden = false;
        _restartPromptBeforeUpdate = false;
    }
}

async function doTradeUpdate(e) {
    // 用 currentTarget 或回退到事件对象，再不行直接查 DOM
    const btn = (e && (e.currentTarget || e.target)) || document.querySelector('#system-update-btn');
    if (!btn) return;
    if (!(await _confirmTradeUpdate())) return;
    _setBtnBusy(btn, true);
    _setUpdateInFlight(true);
    toast(t('sys.updating_now'));
    var updateFailed = false;
    var restartScheduled = false;
    try {
        const resp = await api('POST', '/api/trade/system/update',
            {target_sha: _pendingUpdateTarget || null},
            {'X-Confirm-Update': 'yes'});
        if (!resp) {
            updateFailed = true;
        } else if (resp.ok) {
            restartScheduled = !!resp.restart_scheduled;
            // 更新结果展示实际安装的提交（与确认框里的目标一致）
            // 只显示用户在确认框里见过的 SHA；预览失败时宁可不显示
            const appliedShort = (_pendingUpdateTarget || '').slice(0, 8);
            const suffix = appliedShort ? '（目标 ' + appliedShort + '）' : '';
            if (restartScheduled) {
                toast(t('sys.update_done_restart') + suffix);
            } else {
                toast(t('sys.update_done') + suffix);
            }
            // 非致命步骤（skills 同步等）失败只算警告，不阻止升级，但必须让用户看见
            if (resp.warnings && resp.warnings.length) {
                toast('⚠️ 升级完成，但有 ' + resp.warnings.length + ' 项警告：' + resp.warnings.join('; '),
                    {sticky: true});
            }
        } else if (resp.error || (resp.errors && resp.errors.length)) {
            // 常驻提示：3 秒自动消失的 toast 用户根本看不清（2026-10-29 反馈）
            toast(_updateErrorText(resp), {sticky: true});
            updateFailed = true;
        } else {
            toast(t('sys.update_unknown'));
            updateFailed = true;
        }
    } catch(e) {
        toast(t('sys.update_network'));
        updateFailed = true;
    }
    if (updateFailed) {
        _setBtnBusy(btn, false);
        _setUpdateInFlight(false);
        return;
    }
    if (!restartScheduled) {
        // 后端只更新不重启（audit P1-10）：露出重启按钮，让用户自己点
        _setBtnBusy(btn, false);
        _setUpdateInFlight(false);
        _showRestartPrompt();
        return;
    }
    // 存入标记，页面 reload 后检测并显示 toast
    try { sessionStorage.setItem('_trade_upgrade_done', '1'); } catch(_) {}
    _setUpdateInFlight(false);
    _waitForRestartAndReload(() => {
        _setBtnBusy(btn, false);
    });
}

// ── 数据备份 ──
async function doRestartTrade(e) {
    const btn = (e && (e.currentTarget || e.target)) || document.querySelector('#system-restart-btn');
    if (!btn) return;
    // 升级还在跑：重启会中断升级。后端同样会 409，这里提前拦下少一次往返。
    if (_tradeUpdateInFlight) {
        toast(t('sys.restart_busy_update'));
        return;
    }
    _setBtnBusy(btn, true);
    toast(t('sys.restart_toast'));
    let triggered = true;
    try {
        const resp = await api('POST', '/api/trade/system/restart');
        if (resp && resp.ok) {
            toast(t('sys.restart_ok'));
        } else if (resp) {
            toast(t('sys.restart_fail') + (resp.error || ''));
            triggered = false;
        } else {
            // api() 已经 toast 过具体原因（如 409 更新中）；服务没动，
            // 不能空等重启 —— 否则 120 秒后再弹一条误导性的「重启超时」。
            triggered = false;
        }
    } catch(e) {
        // 连接被掐断通常说明重启已经开始了
        toast(t('sys.restart_wait'));
    }
    if (!triggered) {
        _setBtnBusy(btn, false);
        return;
    }
    _waitForRestartAndReload(() => {
        _setBtnBusy(btn, false);
    });
}

