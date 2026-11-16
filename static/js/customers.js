// ═════════════════════ CUSTOMERS VIEW ═════════════════════
async function renderCustomersViewInto(container) {
    const coName = currentCompanyId ? (companies.find(c => c.id === currentCompanyId)?.name || '') : '';
    container.innerHTML = `
        <div class="panel-topbar">
            <h2>${typeof iconHtml==='function'?iconHtml('users',20):''} ${t('customer.title')}${coName ? '<span style="margin-left:10px;padding:3px 10px;border:1px solid var(--line);font-size:12px;font-weight:500;">'+esc(coName)+'</span>' : ''}</h2>
            <div class="panel-topbar-actions">
                <button class="btn btn-danger" id="batch-delete-btn" style="display:none;" onclick="batchDeleteCustomers()">${typeof iconHtml==='function'?iconHtml('trash',16):''} ${currentLang==='en'?'Batch Delete':'批量删除'}</button>
                <input class="panel-search" id="cust-search" aria-label="搜索客户" placeholder="${t('customer.search')}" oninput="filterCustomers()">
                <select id="cust-tier-filter" aria-label="筛选客户等级" onchange="filterCustomers()" style="padding:7px 10px;font-size:12px;">
                    <option value="">${currentLang==='en'?'All Tiers':'全部等级'}</option><option value="A">A</option><option value="B">B</option><option value="C">C</option><option value="none">${t('cust.field.tier_none')}</option>
                </select>
                <select id="cust-country-filter" aria-label="筛选国家" onchange="filterCustomers()" style="padding:7px 10px;font-size:12px;max-width:120px;">
                    <option value="">${currentLang==='en'?'All Countries':'全部国家'}</option>
                </select>
                <select id="cust-buyer-filter" aria-label="筛选买家类型" onchange="filterCustomers()" style="padding:7px 10px;font-size:12px;max-width:130px;">
                    <option value="">${currentLang==='en'?'All Buyer Types':'全部买家类型'}</option>
                </select>
                <select id="cust-stage-filter" aria-label="筛选商机阶段" onchange="filterCustomers()" style="padding:7px 10px;font-size:12px;max-width:120px;">
                    <option value="">${currentLang==='en'?'All Stages':'全部阶段'}</option>
                    <option value="询盘">询盘</option><option value="报价">报价</option>
                    <option value="样品">样品</option><option value="订单">订单</option>
                </select>
                <select id="cust-sort" aria-label="客户排序方式" onchange="filterCustomers()" style="padding:7px 10px;font-size:12px;">
                    <option value="follow_up">${currentLang==='en'?'Follow-up first':'待跟进优先'}</option>
                    <option value="name">${currentLang==='en'?'By name':'按名称排序'}</option>
                    <option value="updated_at">${currentLang==='en'?'Recently updated':'按最近跟进'}</option>
                </select>
                <button class="btn btn-primary" onclick="showCustomerEditModal()">${typeof iconHtml==='function'?iconHtml('plus',16):''} ${currentLang==='en'?'Add':'添加客户'}</button>
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
    _refreshCustomerFilterOptions();
    filterCustomers();
}

function _parseExtra1(c) { try { return JSON.parse(c.extra1||'{}'); } catch(e) { return {}; } }
function _parseExtra2(c) { try { return JSON.parse(c.extra2||'{}'); } catch(e) { return {}; } }
function _parseExtra3(c) { try { return JSON.parse(c.extra3||'{}'); } catch(e) { return {}; } }

/** 下次跟进日：读 CRM 实列 next_follow_up_date（YYYY-MM-DD）。 */
function _customerFollowUpDate(c) {
    const d = String(c.next_follow_up_date || '').trim();
    return /^\d{4}-\d{2}-\d{2}/.test(d) ? d.slice(0, 10) : '';
}

/** 今天本地日期 YYYY-MM-DD。 */
function _todayYmd() {
    const n = new Date();
    const m = n.getMonth() + 1, d = n.getDate();
    return n.getFullYear() + '-' + (m < 10 ? '0' : '') + m + '-' + (d < 10 ? '0' : '') + d;
}

function _isFollowUpOverdue(c) {
    const d = _customerFollowUpDate(c);
    return !!(d && d < _todayYmd());
}

/** 逾期天数（今天 − 跟进日，按本地日期；未逾期返回 0）。 */
function _followUpOverdueDays(c) {
    const d = _customerFollowUpDate(c);
    if (!d) return 0;
    const today = _todayYmd();
    if (d >= today) return 0;
    const a = new Date(d + 'T00:00:00');
    const b = new Date(today + 'T00:00:00');
    return Math.max(0, Math.round((b - a) / 86400000));
}

function _customerStage(c) {
    return String(c.stage || '询盘').trim();
}

const _CRM_STAGES = ['询盘', '报价', '样品', '订单'];

/** 填充国家 / 买家类型筛选项（来自现有客户 extra）。 */
function _refreshCustomerFilterOptions() {
    const countries = new Set();
    const buyers = new Set();
    allCustomers.forEach(function (c) {
        const e1 = _parseExtra1(c);
        if (e1.country) countries.add(e1.country);
        if (e1.buyer_type) buyers.add(e1.buyer_type);
    });
    const cSel = $('cust-country-filter');
    const bSel = $('cust-buyer-filter');
    if (cSel) {
        const cur = cSel.value;
        cSel.innerHTML = '<option value="">' + (currentLang === 'en' ? 'All Countries' : '全部国家') + '</option>' +
            [...countries].sort().map(function (v) {
                return '<option value="' + esc(v) + '"' + (cur === v ? ' selected' : '') + '>' + esc(v) + '</option>';
            }).join('');
    }
    if (bSel) {
        const cur = bSel.value;
        bSel.innerHTML = '<option value="">' + (currentLang === 'en' ? 'All Buyer Types' : '全部买家类型') + '</option>' +
            [...buyers].sort().map(function (v) {
                return '<option value="' + esc(v) + '"' + (cur === v ? ' selected' : '') + '>' + esc(v) + '</option>';
            }).join('');
    }
}

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

    const sortBy = ($('cust-sort')?.value) || 'follow_up';
    const today = _todayYmd();
    const sorted = [...data].sort((a, b) => {
        if (sortBy === 'updated_at') return (b.updated_at || '').localeCompare(a.updated_at || '');
        if (sortBy === 'follow_up') {
            const da = _customerFollowUpDate(a) || '9999-99-99';
            const db = _customerFollowUpDate(b) || '9999-99-99';
            // 逾期优先，再按跟进日升序，最后名称
            const oa = da < today ? 0 : 1;
            const ob = db < today ? 0 : 1;
            if (oa !== ob) return oa - ob;
            if (da !== db) return da.localeCompare(db);
        }
        return (a.name || '').localeCompare(b.name || '');
    });

    tbody.innerHTML = sorted.map((c, idx) => {
        const ex1 = _parseExtra1(c);
        const ex2 = _parseExtra2(c);
        const tier = ex1['tier'] || '';
        const tierLabel = tier || '--';
        const buyerType = ex1['buyer_type'] || '';
        const mainCategory = ex1['main_category'] || '';
        const country = ex1['country'] || '';
        const contact = c.contact || '';
        const title = ex2['title'] || '';
        const email = ex2['email'] || '';
        const note = (c.note || '').slice(0, 40);
        const follow = _customerFollowUpDate(c);
        const overdue = follow && follow < today;
        const stage = _customerStage(c);
        // 正文只拼 _CRM_STAGES 常量（再走 esc）；用户 stage 仅参与 class 比较
        const stageHtml = _CRM_STAGES.map(function (s) {
            return '<span class="pill' + (stage === s ? ' on' : '') + (overdue && stage === s ? ' hot' : '') + '">' + esc(s) + '</span>';
        }).join('');
        const subLine = [title, mainCategory, country, email].filter(Boolean).join(' · ');
        const followText = overdue
            ? (currentLang === 'en' ? 'Overdue' : '已逾期')
            : (follow || (currentLang === 'en' ? 'No follow-up date' : '未设跟进日'));
        return `<tr class="${overdue ? 'cust-overdue' : ''}" style="cursor:pointer;animation-delay:${(idx * 0.04).toFixed(2)}s;" onclick="openCustomerWall(${c.id})">
            <td style="width:30px;" onclick="event.stopPropagation()"><input type="checkbox" class="cust-checkbox" value="${c.id}" onchange="updateBatchDeleteBtn()"></td>
            <td style="padding:8px 10px;">
                <div style="font-weight:600;font-size:13px;">${esc(c.name)}${contact ? '<span style="font-weight:400;color:var(--muted);margin-left:6px;">' + esc(contact) + '</span>' : ''}</div>
                <div style="font-size:11px;color:var(--muted);margin-top:2px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                    <span style="font-weight:600;border:1px solid var(--line-strong);padding:1px 6px;font-family:var(--font-mono);"> ${esc(tierLabel)} </span>
                    ${buyerType ? '<span class="pill">' + esc(buyerType) + '</span>' : ''}
                    ${subLine ? '<span>' + esc(subLine) + '</span>' : ''}
                    ${note ? '<span>' + esc(note) + '</span>' : ''}
                    <span class="cust-follow" style="margin-left:auto;white-space:nowrap;">${typeof iconHtml==='function'?iconHtml(overdue?'triangle-exclamation-point':'calendar-clock',16):''} ${esc(followText)}${follow && !overdue ? ' · ' + esc(follow) : ''}</span>
                </div>
                <div class="stage-pills">${stageHtml}</div>
            </td>
            <td style="width:50px;text-align:right;padding-right:8px;" onclick="event.stopPropagation()"><button class="btn-xs" onclick="showCustomerEditModal(${c.id})">${currentLang==='en'?'Edit':'编辑'}</button></td>
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
    const country = $('cust-country-filter')?.value||'';
    const buyer = $('cust-buyer-filter')?.value||'';
    const stage = $('cust-stage-filter')?.value||'';
    let filtered = allCustomers;
    if (search) {
        filtered = filtered.filter(c => {
            const e1 = _parseExtra1(c); const e2 = _parseExtra2(c);
            const tags = (_parseExtra3(c).tags || []).join(' ');
            const blob = [c.name, c.contact, e1.country, e1.buyer_type, e2.email, e2.title, c.note, tags]
                .join(' ').toLowerCase();
            return blob.includes(search);
        });
    }
    if (tier) {
        filtered = filtered.filter(c => {
            const t = _parseExtra1(c)['tier'] || c.tier || '';
            if (tier==='none') return !t;
            return t === tier;
        });
    }
    if (country) filtered = filtered.filter(c => (_parseExtra1(c).country || '') === country);
    if (buyer) filtered = filtered.filter(c => (_parseExtra1(c).buyer_type || '') === buyer);
    if (stage) filtered = filtered.filter(c => _customerStage(c) === stage);
    renderCustomersTable(filtered);
}

// ── 客户卡片墙（S-01）────────────────────────────────────────
let _wallEscBound = false;

function _wallAnimateCount(el, target, currency) {
    if (!el) return;
    if (target == null || isNaN(target)) { el.textContent = '—'; return; }
    const prefix = (currency || 'USD') + ' ';
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        el.textContent = prefix + Number(target).toLocaleString('en-US');
        return;
    }
    let start = null;
    const dur = 750;
    const goal = Number(target);
    function step(ts) {
        if (!start) start = ts;
        const p = Math.min((ts - start) / dur, 1);
        const v = Math.round(goal * (1 - Math.pow(1 - p, 3)));
        el.textContent = prefix + v.toLocaleString('en-US');
        if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

function _orderProgress(status) {
    const s = status || '';
    if (s === '已完成') return 100;
    if (s === '已出货') return 75;
    if (s === '已下单') return 50;
    if (s === '报价中') return 25;
    return 15;
}

function closeCustomerWall() {
    const wall = $('customer-wall');
    if (!wall) return;
    wall.classList.remove('open');
    wall.setAttribute('inert', '');
    wall.setAttribute('aria-hidden', 'true');
}

async function openCustomerWall(cid) {
    const wall = $('customer-wall');
    if (!wall) return;
    closeCustomerDetail();

    // 卡片墙：overview + 客户关联邮件 + 是否已绑定邮箱（并行）
    const [ov, mailRes, mailboxRes] = await Promise.all([
        api('GET', `/api/trade/customers/${cid}/overview`),
        api('GET', `/api/trade/customers/${cid}/emails`),
        api('GET', '/api/trade/mailboxes'),
    ]);
    if (!ov || !ov.customer) {
        toast(currentLang === 'en' ? 'Failed to load customer wall' : '加载客户详情失败');
        return;
    }
    const mailRecords = Array.isArray(mailRes)
        ? mailRes
        : ((mailRes && mailRes.emails) ? mailRes.emails : []);
    const mailboxes = Array.isArray(mailboxRes) ? mailboxRes : [];
    const mailboxBound = mailboxes.length > 0;
    const c = ov.customer;
    // 同步本地列表缓存（阶段/跟进日实列）
    const cached = allCustomers.find(function (x) { return x.id === cid; });
    if (cached) Object.assign(cached, c);
    editingCustomerData = c;

    const e1 = _parseExtra1(c);
    const stage = _customerStage(c);
    const follow = _customerFollowUpDate(c);
    const overdue = _isFollowUpOverdue(c);
    const people = ov.people || [];
    const orders = ov.orders || [];
    const fileEmails = ov.emails || [];
    const keyChats = ov.key_talks || [];
    // 无 is_important 时后端用最近 5 条兜底——标题/统计不能仍写「重要对话」
    const talksAreImportant = keyChats.some(function (c) { return c.is_important; });
    const talksTitle = talksAreImportant
        ? (currentLang === 'en' ? 'Key talks' : '重要对话')
        : (currentLang === 'en' ? 'Recent talks' : '最近对话');
    const talksStatLabel = talksAreImportant
        ? (currentLang === 'en' ? 'Mail + key talks' : '邮件 + 重要对话')
        : (currentLang === 'en' ? 'Mail + talks' : '邮件 + 对话');
    const timeline = ov.timeline || [];
    const stats = ov.stats || {};
    const orderTotal = stats.order_total_amount;
    const orderCurrency = stats.order_total_currency || '';
    const byCurrency = stats.order_totals_by_currency || {};
    const multiCurrency = !orderCurrency && byCurrency && Object.keys(byCurrency).length > 1;
    const hasAmount = orderTotal != null && !isNaN(orderTotal);

    let seq = 0;
    function delay() { return ' style="animation-delay:' + ((seq++) * 0.06).toFixed(2) + 's"'; }
    function secHead(title, count) {
        return '<div class="wsec"><div class="wsec-head"><h4>' + title + '</h4><span class="cnt">' +
            count + '</span><span class="ddline" aria-hidden="true"></span></div>';
    }

    const overdueDays = overdue ? _followUpOverdueDays(c) : 0;
    const stamp = overdue
        ? (currentLang === 'en'
            ? ('THREAT · OVERDUE ' + overdueDays + ' DAYS')
            : ('THREAT · 已逾期 ' + overdueDays + ' 天'))
        : (e1.tier ? ('TIER ' + e1.tier) : 'POI');

    let bodyHtml = '';
    bodyHtml += secHead(currentLang === 'en' ? 'People' : '关联人物', 'PEOPLE // ' + people.length) + '<div class="wgrid">';
    people.forEach(function (p) {
        const ini = String(p.name || '?').trim().slice(0, 2).toUpperCase();
        const role = p.role || (currentLang === 'en' ? 'Primary contact' : '主要联系人');
        bodyHtml += '<article class="wcard"' + delay() + '><div class="wc-top"><span class="avatar">' + esc(ini) +
            '</span><span><span class="wc-name">' + esc(p.name) + '</span><br /><span class="wc-role">' + esc(role) +
            '</span></span><span class="tagchip dim" style="margin-left:auto">' +
            (currentLang==='en'?'ASSET · PRIMARY CONTACT':'ASSET · 主要联系人') +
            '</span></div>' +
            (p.note ? '<p class="muted">' + esc(p.note) + '</p>' : '') +
            (p.email ? '<p class="mono">' + esc(p.email) + '</p>' : '') +
            ([p.phone, p.whatsapp, p.wechat].filter(Boolean).length
                ? '<p class="muted">' + esc([p.phone, p.whatsapp ? 'WA '+p.whatsapp : '', p.wechat ? 'WeChat '+p.wechat : ''].filter(Boolean).join(' · ')) + '</p>'
                : '') +
            '</article>';
    });
    bodyHtml += '</div></div>';

    bodyHtml += secHead(currentLang === 'en' ? 'Orders' : '订单', 'ORDERS // ' + orders.length) + '<div class="wgrid">';
    if (!orders.length) {
        bodyHtml += '<div class="wall-empty"' + delay() + '>' + (currentLang==='en'?'No orders yet':'暂无订单记录') + '</div>';
    } else {
        orders.forEach(function (o) {
            const prog = _orderProgress(o.status);
            const amt = (o.total_amount != null && o.total_amount !== '')
                ? ((o.currency || 'USD') + ' ' + Number(o.total_amount).toLocaleString('en-US'))
                : (currentLang==='en'?'Price TBD':'金额待谈');
            const items = o.items || [];
            const product = items.length
                ? (items[0].product_name + (items.length > 1 ? ' 等' + items.length + '项' : ''))
                : (o.product_name || '');
            const qty = items.length
                ? items.map(function (it) { return (it.quantity || '') + (it.unit || ''); }).join(' / ')
                : ((o.quantity || '') + (o.unit || ''));
            bodyHtml += '<article class="wcard"' + delay() + '><div class="wc-top"><span class="mono">' + esc(o.order_no || ('#' + o.id)) +
                '</span><span class="tagchip dim" style="margin-left:auto">' + esc(o.status || '') + '</span></div>' +
                '<p class="wc-subj">' + esc(product) + '</p><p><span class="wc-amt">' + esc(amt) + '</span> <span class="muted">· ' +
                esc(qty) + '</span></p><div class="bar"><i style="width:' + prog + '%"></i></div>' +
                '<p class="muted">' + esc((o.updated_at || o.created_at || '').slice(0, 10)) + ' · ' + prog + '%</p></article>';
        });
    }
    bodyHtml += '</div></div>';

    const emailCount = mailboxBound ? mailRecords.length : 0;
    bodyHtml += '<div class="wsec"><div class="wsec-head"><h4>' + (currentLang === 'en' ? 'Email' : '邮件往来') +
        '</h4><span class="cnt">EMAIL // ' + emailCount + '</span>';
    if (mailboxBound) {
        bodyHtml += '<button type="button" class="btn" id="wall-email-refresh" style="margin-left:auto;font-size:11px;padding:4px 10px;">' +
            (currentLang === 'en' ? 'Refresh' : '刷新邮件') + '</button>';
    }
    bodyHtml += '<span class="ddline" aria-hidden="true"></span></div>';
    bodyHtml += '<div class="wgrid" id="wall-email-grid">';
    if (!mailboxBound) {
        bodyHtml += '<article class="wcard"' + delay() + '><div class="wc-top">' +
            (typeof iconHtml === 'function' ? iconHtml('mail', 20) : '') +
            '<span class="muted">' + (currentLang === 'en' ? 'Addresses on file' : '档案中的邮箱') + '</span></div>';
        if (fileEmails.length) {
            fileEmails.forEach(function (em) { bodyHtml += '<p class="mono">' + esc(em) + '</p>'; });
        } else {
            bodyHtml += '<p class="muted">' + (currentLang === 'en' ? 'No email on file' : '暂无邮箱') + '</p>';
        }
        bodyHtml += '<p class="muted">' + (currentLang === 'en'
            ? 'Shows addresses only — Trade does not read mail until you bind a mailbox.'
            : '只显示邮箱地址，不读取邮箱') + '</p>' +
            '<button type="button" class="primary" id="wall-goto-mailboxes">' +
            (currentLang === 'en' ? 'Open Mailboxes' : '去绑定邮箱') + '</button></article>';
    } else if (!mailRecords.length) {
        bodyHtml += '<div class="wall-empty"' + delay() + '>' +
            (currentLang === 'en' ? 'No synced emails for this customer yet.' : '暂无已同步的邮件记录') + '</div>';
    } else {
        mailRecords.forEach(function (m, idx) {
            const subj = m.subject || (currentLang === 'en' ? '(no subject)' : '（无主题）');
            const party = m.from_addr || '';
            const dt = (m.received_at || '').slice(0, 16).replace('T', ' ');
            bodyHtml += '<article class="wcard wall-mail-card"' + delay() + ' data-mail-idx="' + idx + '" style="cursor:pointer;">' +
                '<div class="wc-top"><span class="wc-subj">' + esc(subj) + '</span>' +
                '<span class="muted" style="margin-left:auto;white-space:nowrap;">' + esc(dt) + '</span></div>' +
                '<p class="mono muted">' + esc(party) + '</p>' +
                '<div class="wall-mail-body hidden"><p class="muted" style="white-space:pre-wrap;margin:8px 0 0;">' +
                esc(m.body_text || m.snippet || '') + '</p></div></article>';
        });
    }
    bodyHtml += '</div></div>';

    bodyHtml += secHead(talksTitle, 'TALKS // ' + keyChats.length) + '<div class="wgrid">';
    if (!keyChats.length) {
        bodyHtml += '<div class="wall-empty"' + delay() + '>' + (currentLang==='en'?'No conversations linked to this customer':'暂无关联到该客户的对话') + '</div>';
    } else {
        keyChats.forEach(function (conv) {
            bodyHtml += '<article class="wcard"' + delay() + '><div class="wc-top"><span class="tagchip dim">' +
                esc(conv.context || 'chat') + '</span><span class="muted">' + esc((conv.created_at || '').slice(0, 16)) +
                '</span>' + (conv.is_important ? '<span class="tagchip" style="margin-left:auto">' + (currentLang==='en'?'Important':'重要') + '</span>' : '') +
                '</div><p class="quote">' + esc((conv.query || '').slice(0, 160)) + '</p>' +
                '<p class="muted">' + esc((conv.response || '').slice(0, 120)) + '</p></article>';
        });
    }
    bodyHtml += '</div></div>';

    bodyHtml += secHead(currentLang === 'en' ? 'Timeline' : '互动时间线', 'TIMELINE') +
        '<div class="wgrid"><article class="wcard wide"' + delay() + '>';
    if (!timeline.length) {
        bodyHtml += '<div class="wall-empty">' + (currentLang==='en'?'No activity yet':'暂无互动记录') + '</div>';
    } else {
        bodyHtml += '<ul class="timeline">' + timeline.map(function (t) {
            return '<li><span class="t">' + esc(t.at || '') + '</span><p>' + esc(t.text || '') + '</p></li>';
        }).join('') + '</ul>';
    }
    bodyHtml += '</article></div></div>';

    wall.innerHTML =
        '<div class="wall-head">' +
        '<button type="button" class="wall-back" id="wall-back">' + (currentLang==='en'?'← Back to list':'← 返回客户列表') + '</button>' +
        '<div class="wall-title bracket"><div><h3>' + esc(c.name) + '</h3>' +
        '<div class="sub">' + esc([e1.country, e1.buyer_type, e1.main_category].filter(Boolean).join(' · ') || (currentLang==='en'?'Customer file':'客户档案')) +
        '<br />' + (currentLang==='en'?'Next follow-up: ':'下次跟进：') +
        (overdue ? '<span style="color:var(--accent);font-weight:700;">' + (currentLang==='en'?'Overdue':'已逾期') + '</span>' : esc(follow || '—')) +
        '</div></div><span class="wall-stamp">' + esc(stamp) + '</span></div>' +
        '<div class="wstats">' +
        '<div class="wstat"' + delay() + '><b>' + (stats.people_count || people.length) + '</b><span>' + (currentLang==='en'?'People':'关联人物') + '</span></div>' +
        '<div class="wstat"' + delay() + '><b>' + (stats.order_count || orders.length) + '</b><span>' + (currentLang==='en'?'Orders':'订单记录') + '</span></div>' +
        '<div class="wstat"' + delay() + '><b id="wall-stat-total">' +
        (multiCurrency
            ? esc(Object.keys(byCurrency).map(function (k) {
                return k + ' ' + Number(byCurrency[k]).toLocaleString('en-US');
            }).join(' · '))
            : (hasAmount ? '0' : '—')) +
        '</b><span>' + (currentLang==='en'?'Order total':'订单总额') + '</span></div>' +
        '<div class="wstat"' + delay() + '><b>' + (stats.mail_and_talk_count || ((mailboxBound ? mailRecords.length : fileEmails.length) + keyChats.length)) + '</b><span>' + talksStatLabel + '</span></div>' +
        '</div>' +
        '<div class="wall-actions">' +
        '<button type="button" class="primary" id="wall-edit">' + (currentLang==='en'?'Edit profile':'编辑档案') + '</button>' +
        '<button type="button" id="wall-add-order">' + (currentLang==='en'?'Add order':'添加订单') + '</button>' +
        '<button type="button" id="wall-stage-save">' + (currentLang==='en'?'Save stage / follow-up':'保存阶段与跟进日') + '</button>' +
        '<label style="font-size:12px;display:inline-flex;align-items:center;gap:6px;">' + (currentLang==='en'?'Stage':'商机阶段') +
        ' <select id="wall-stage">' + _CRM_STAGES.map(function (s) {
            return '<option value="' + esc(s) + '"' + (stage === s ? ' selected' : '') + '>' + esc(s) + '</option>';
        }).join('') + '</select></label>' +
        '<label style="font-size:12px;display:inline-flex;align-items:center;gap:6px;">' + (currentLang==='en'?'Follow-up':'下次跟进') +
        ' <input type="date" id="wall-follow" value="' + esc(follow) + '"></label>' +
        '</div><span class="ddline" aria-hidden="true"></span></div>' +
        '<div class="wall-scroll" id="wall-body">' + bodyHtml + '</div>';

    wall.classList.add('open');
    wall.removeAttribute('inert');
    wall.setAttribute('aria-hidden', 'false');
    $('wall-back')?.focus();
    // 单一币种才数字滚动；多币种已在上方直接列出各币种金额
    if (hasAmount && !multiCurrency) {
        _wallAnimateCount($('wall-stat-total'), orderTotal, orderCurrency);
    }

    $('wall-back')?.addEventListener('click', closeCustomerWall);
    $('wall-edit')?.addEventListener('click', function () { closeCustomerWall(); showCustomerDetail(cid); });
    $('wall-add-order')?.addEventListener('click', function () { showOrderModal(cid); });
    $('wall-stage-save')?.addEventListener('click', async function () {
        const nextStage = $('wall-stage')?.value || '询盘';
        const nextFollow = $('wall-follow')?.value || '';
        // 实列 stage / next_follow_up_date
        const saved = await api('PUT', `/api/trade/customers/${cid}`, {
            stage: nextStage,
            next_follow_up_date: nextFollow,
        });
        if (!saved) return;
        if (cached) {
            cached.stage = saved.stage;
            cached.next_follow_up_date = saved.next_follow_up_date;
        }
        toast(t('toast.saved'));
        filterCustomers();
        openCustomerWall(cid);
    });

    $('wall-goto-mailboxes')?.addEventListener('click', function () {
        closeCustomerWall();
        navToView('mailboxes');
    });
    $('wall-email-grid')?.addEventListener('click', function (e) {
        const card = e.target.closest('.wall-mail-card');
        if (!card || e.target.closest('button')) return;
        const body = card.querySelector('.wall-mail-body');
        if (body) body.classList.toggle('hidden');
    });
    $('wall-email-refresh')?.addEventListener('click', async function () {
        const btn = $('wall-email-refresh');
        if (!btn || btn.disabled) return;
        btn.disabled = true;
        btn.textContent = currentLang === 'en' ? 'Pulling…' : '拉取中…';
        await api('POST', '/api/trade/mailboxes/pull-all');
        openCustomerWall(cid);
    });

    if (!_wallEscBound) {
        _wallEscBound = true;
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeCustomerWall();
        });
    }
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
    // value 固定中文（与新建客户弹窗、后端既有数据一致），英文界面只翻译显示文本。
    // 旧版英文界面曾把 "Brand" 这类英文值写进 extra1，这里兼容读回（审计 P2-19）。
    var buyerTypeOptions = [
        ['品牌商', currentLang==='en'?'Brand':'品牌商'],
        ['分销商', currentLang==='en'?'Distributor':'分销商'],
        ['代理商', currentLang==='en'?'Agent':'代理商'],
        ['安装商', currentLang==='en'?'Installer':'安装商'],
        ['维保商', currentLang==='en'?'Maintenance':'维保商'],
        ['同行', currentLang==='en'?'Competitor':'同行'],
        ['其他', currentLang==='en'?'Other':'其他'],
    ];
    var _legacyBuyerType = {
        'Brand':'品牌商','Distributor':'分销商','Agent':'代理商','Installer':'安装商',
        'Maintenance':'维保商','Competitor':'同行','Other':'其他',
    };
    var buyerValue = _legacyBuyerType[buyerType] || buyerType;
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
                    <option value="" ${!buyerValue?'selected':''}>${t('cust.field.buyer_none')}</option>
                    ${buyerTypeOptions.map(function(o){return '<option value="'+o[0]+'" '+(buyerValue===o[0]?'selected':'')+'>'+o[1]+'</option>';}).join('')}
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

    const saved = await api('PUT', `/api/trade/customers/${cid}`, {name, contact, note, country, tier, linkedin_url: linkedin,
        title, email, phone, whatsapp, company_website: website, backup_email: backupEmail, buyer_type: buyerType, follow_up_note: followUpNote, main_category: mainCategory, match_score: matchScore});
    // 失败时 api() 已 toast 原因；保留详情面板让用户看到自己填的内容
    if (!saved) return;
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

/** 单价展示文案：null = 待谈；0 = 旧数据（Batch 1 前 0 与"未填"混用）。 */
function _orderPriceText(o) {
    if (o.unit_price == null) return t('order.price_pending');
    if (Number(o.unit_price) === 0) return t('order.price_pending_legacy');
    return t('order.price') + ' ' + o.unit_price + ' ' + (o.currency || 'USD');
}

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
            const items = o.items || [];
            // 多商品：首行品名 + 等N项；单价只对单行有意义，多行标「按行报价」
            const priceText = items.length > 1
                ? t('order.price_per_line')
                : _orderPriceText(items.length === 1 ? items[0] : o);
            const pendingTotal = o.total_amount == null && items.length > 0;
            return `<div style="padding:6px 0;border-bottom:1px solid var(--border-light);font-size:12px;cursor:pointer;" onclick="showOrderEditModal(${o.id})">
                <span style="color:${stColor};font-weight:500;">● ${esc(o.status)}</span>
                <b>${
                    items.length > 1
                        ? esc(items[0].product_name) + ' ' + t('order.items_count', {n: items.length})
                        : esc(o.product_name)
                }</b>
                ${o.quantity ? '<span style="color:var(--text-secondary);">'+esc(o.quantity)+esc(o.unit||'')+'</span>' : ''}
                <span style="color:var(--text-muted);"> ${esc(priceText)}</span>
                ${pendingTotal
                    ? '<span style="color:var(--text-muted);"> '+t('order.total_pending')+'</span>'
                    : (o.total_amount ? '<span style="color:var(--accent);font-weight:500;"> '+esc(o.total_amount)+' '+esc(o.currency||'USD')+'</span>' : '')}
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
    // value 必须是后端 Literal 认的中文；翻译只用于显示文本。
    // 以前 option 文本即 value，英文界面提交 "Quoting" → 422（审计 P1-7）。
    var stValues = ['报价中','已下单','已出货','已完成','已取消'];
    var stKeys = ['quoting','ordered','shipped','done','cancelled'];
    var stOptions = stValues.map(function(v, i) {
        return '<option value="' + v + '">' + t('order.status_' + stKeys[i]) + '</option>';
    }).join('');
    backdrop.innerHTML = '<div class="modal" style="max-width:660px;width:95%;" onclick="event.stopPropagation()">' +
        '<h3>' + (isEdit ? t('order.edit_title') : t('order.title')) + '</h3>' +
        '<input type="hidden" id="order-edit-id" value="'+(oid||'')+'">' +
        '<input type="hidden" id="order-cust-id" value="'+(presetCid||'')+'">' +
        '<div id="order-cust-row" style="display:'+((isEdit||presetCid)?'none':'block')+';">' +
            '<div class="form-group"><label for="order-cust-sel">'+t('order.cust_label')+'</label><select id="order-cust-sel"></select></div>' +
        '</div>' +
        '<div class="form-row">' +
            '<div class="form-group"><label for="order-no">'+t('order.no')+'</label><input type="text" id="order-no" placeholder="PO-2026-001"></div>' +
            '<div class="form-group"><label for="order-currency">'+t('order.currency')+'</label><select id="order-currency"><option>USD</option><option>EUR</option><option>CNY</option></select></div>' +
        '</div>' +
        '<div class="form-row">' +
            '<div class="form-group"><label for="order-status">'+t('order.status')+'</label><select id="order-status">'+stOptions+'</select></div>' +
            '<div class="form-group"><label for="order-delivery">'+t('order.delivery')+'</label><input type="date" id="order-delivery"></div>' +
        '</div>' +
        '<div class="form-row">' +
            '<div class="form-group"><label for="order-payment">'+t('order.payment')+'</label><input type="text" id="order-payment" placeholder="T/T 30/70"></div>' +
        '</div>' +
        '<div class="form-group">' +
            '<label>'+t('order.items')+'</label>' +
            '<div id="order-items"></div>' +
            '<button type="button" class="btn-xs" style="margin-top:6px;" onclick="addOrderItemRow()">'+t('order.add_line')+'</button>' +
        '</div>' +
        '<div class="form-group"><label for="order-notes">'+t('order.notes')+'</label><textarea id="order-notes" style="min-height:50px;" placeholder="Notes"></textarea></div>' +
        '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">' +
            (isEdit?'<button class="btn btn-danger" onclick="deleteOrder('+oid+')">'+t('order.btn_delete')+'</button>':'') +
            '<button class="btn" onclick="this.closest(\'.modal-backdrop\').remove()">'+t('btn.cancel')+'</button>' +
            '<button class="btn btn-primary" onclick="saveOrder()">'+t('btn.save')+'</button>' +
        '</div>' +
    '</div>';
    document.body.appendChild(backdrop);

    // 新建默认给一行空明细；编辑拉回数据后整体替换
    setOrderItems([]);

    if (isEdit) {
        api('GET', `/api/trade/orders/${oid}`).then(o => {
            if (!o) return;
            // 订单归属客户在编辑里不改：回填隐藏字段并保持隐藏（旧 bug：下拉是空的）
            $('order-cust-id').value = o.customer_id || '';
            $('order-cust-row').style.display = 'none';
            $('order-no').value = o.order_no||'';
            $('order-currency').value = o.currency||'USD';
            $('order-status').value = o.status||'报价中';
            $('order-delivery').value = (o.delivery_date||'').slice(0,10);
            $('order-payment').value = o.payment_terms||'';
            $('order-notes').value = o.notes||'';
            const items = (o.items && o.items.length)
                ? o.items
                : [{ // 迁移前数据 / 无明细：用头字段拼一行
                    product_name: o.product_name, quantity: o.quantity,
                    unit: o.unit, unit_price: o.unit_price,
                    total_amount: o.total_amount,
                }];
            setOrderItems(items);
        });
    }
    // 加载客户下拉
    if (!presetCid && !isEdit) {
        api('GET', '/api/trade/customers').then(list => {
            const sel = $('order-cust-sel');
            sel.innerHTML = '<option value="">'+t('order.cust_select')+'</option>' + (list||[]).map(c=>'<option value="'+c.id+'">'+esc(c.name)+'</option>').join('');
        });
    }
}

// ── 订单明细行（一单多商品）─────────────────────────────────────────────────

/** 输入框取数：空 → null（待谈/未填），否则数字。 */
function _numInput(el) {
    const raw = el ? String(el.value).trim() : '';
    if (!raw) return null;
    const n = parseFloat(raw);
    return Number.isFinite(n) ? n : null;
}

/** 新增一行商品；item 缺省 = 空行。 */
function addOrderItemRow(item) {
    const box = $('order-items');
    if (!box) return;
    const it = item || {};
    const pricePending = it.unit_price == null || Number(it.unit_price) === 0;
    const row = document.createElement('div');
    row.className = 'order-item-row';
    row.innerHTML =
        '<input type="text" class="oi-name" placeholder="'+t('order.product')+'">' +
        '<input type="number" class="oi-qty" step="any" min="0" placeholder="'+t('order.qty')+'">' +
        '<input type="text" class="oi-unit" placeholder="'+t('order.unit')+'">' +
        '<input type="number" class="oi-price" step="any" min="0" placeholder="'+t('order.price')+'">' +
        '<input type="number" class="oi-total" step="any" min="0" placeholder="'+t('order.line_total')+'">' +
        '<button type="button" class="btn-xs" title="'+t('order.remove_line')+'" onclick="removeOrderItemRow(this)">×</button>';
    row.querySelector('.oi-name').value = it.product_name || '';
    row.querySelector('.oi-qty').value = it.quantity == null ? '' : it.quantity;
    row.querySelector('.oi-unit').value = it.unit || '';
    row.querySelector('.oi-price').value = pricePending ? '' : it.unit_price;
    if (pricePending) {
        // null / 0 都不回填数字：留空就是"待谈"，占位符把状态说清楚
        row.querySelector('.oi-price').placeholder = t('order.price_pending');
        row.querySelector('.oi-price').title = t('order.price_pending_legacy');
    }
    row.querySelector('.oi-total').value = it.total_amount == null ? '' : it.total_amount;
    row.querySelectorAll('.oi-qty, .oi-price').forEach(el => {
        el.addEventListener('input', _orderRowRecalc);
    });
    // 手填行总额后不再被 数量×单价 覆盖
    row.querySelector('.oi-total').addEventListener('input', e => {
        e.target.dataset.manual = '1';
    });
    box.appendChild(row);
}

/** 数量/单价变化时自动算行总额（用户手填过就不再覆盖）。 */
function _orderRowRecalc(e) {
    const row = e.target.closest('.order-item-row');
    if (!row) return;
    const totalEl = row.querySelector('.oi-total');
    if (!totalEl || totalEl.dataset.manual === '1') return;
    const qty = _numInput(row.querySelector('.oi-qty'));
    const price = _numInput(row.querySelector('.oi-price'));
    totalEl.value = (qty != null && price != null)
        ? String(Math.round(qty * price * 100) / 100) : '';
}

function removeOrderItemRow(btn) {
    const row = btn.closest('.order-item-row');
    const box = $('order-items');
    if (!row || !box) return;
    if (box.querySelectorAll('.order-item-row').length <= 1) {
        // 至少保留一行：清空内容而不是删掉
        row.querySelectorAll('input').forEach(el => {
            el.value = '';
            delete el.dataset.manual;
        });
        return;
    }
    row.remove();
}

/** 用给定明细整体重建行；空数组 = 一行空行。 */
function setOrderItems(items) {
    const box = $('order-items');
    if (!box) return;
    box.innerHTML = '';
    (items && items.length ? items : [{}]).forEach(addOrderItemRow);
}

/** 收集明细：整行空忽略；填了内容却没品名 → 返回 null（调用方提示）。 */
function _collectOrderItems() {
    const rows = Array.from(document.querySelectorAll('#order-items .order-item-row'));
    const out = [];
    for (const row of rows) {
        const name = row.querySelector('.oi-name').value.trim();
        const qty = _numInput(row.querySelector('.oi-qty'));
        const unit = row.querySelector('.oi-unit').value.trim();
        const price = _numInput(row.querySelector('.oi-price'));
        const total = _numInput(row.querySelector('.oi-total'));
        if (!name && qty == null && price == null && total == null) continue;
        if (!name) return null;
        out.push({
            product_name: name,
            quantity: qty,
            unit: unit,
            unit_price: price,   // null = 待谈，不是 0
            total_amount: total,
        });
    }
    return out;
}

async function saveOrder() {
    const editId = $('order-edit-id').value;
    const custId = $('order-cust-id').value || $('order-cust-sel').value;
    if (!custId) { toast(t('toast.cust_product_required')); return; }
    const items = _collectOrderItems();
    if (items === null) { toast(t('order.item_name_required')); return; }
    if (!items.length) { toast(t('order.items_required')); return; }
    const body = {
        customer_id: parseInt(custId),
        // 明细行是商品的事实来源；订单头只发订单级字段
        items: items,
        order_no: $('order-no').value.trim(),
        currency: $('order-currency').value,
        status: $('order-status').value,
        delivery_date: $('order-delivery').value,
        payment_terms: $('order-payment').value.trim(),
        notes: $('order-notes').value.trim(),
    };
    const saved = editId
        ? await api('PUT', `/api/trade/orders/${editId}`, body)
        : await api('POST', '/api/trade/orders', body);
    // api() 失败返回 null 且已自行 toast 失败原因 —— 此时不能关弹窗，
    // 否则用户填的内容随弹窗一起消失，还会看到一个假的"已创建"提示。
    if (!saved) return;
    _closeOrderModal();
    loadOrdersForCustomer(custId);
    toast(editId ? t('order.updated') : t('order.created'));
}

async function deleteOrder(oid) {
    if (!confirm(t('order.confirm_delete'))) return;
    const gone = await api('DELETE', `/api/trade/orders/${oid}`);
    // 失败时 api() 已 toast 原因；订单还在列表里，不能弹"已删除"
    if (!gone) return;
    // 先读表单值再关弹窗 —— _closeOrderModal() 会移除整个 backdrop，
    // 之后 $('order-cust-id') 必为 null（审计：每次删除都抛 TypeError）
    const custId = $('order-cust-id')?.value;
    _closeOrderModal();
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
    const saved = editId
        ? await api('PUT', `/api/trade/customers/${editId}`, body)
        : await api('POST', `/api/trade/customers`, body);
    // 失败时 api() 已 toast 原因；保留弹窗，用户填的内容不能跟着消失
    if (!saved) return;
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
        // 走 api() 统一封装：拿到 120s 超时与 401 自愈（原先裸 fetch 无超时）
        const result = await api('POST', '/api/trade/customers/bulk', formData);
        // result 为 null 时 api() 已经 toast 过失败原因，这里不重复提示
        if (result) {
            toast(`导入完成：新增 ${result.created} 条，跳过 ${result.skipped} 条（重复或空行）`);
            await loadCustomersData();
            if (currentView === 'customers') renderCustomersTable(allCustomers);
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

