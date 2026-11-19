// ═════════════════════ CUSTOMERS VIEW ═════════════════════
// s2 客户列表：筛选/星标/分页状态
let _custTier = '';
let _custStage = '';
let _custStarred = false;
let _custOverdueOnly = false;
let _custPage = 1;
const _CUST_PAGE_SIZE = 10;

async function renderCustomersViewInto(container) {
    // 每次进入客户列表重置筛选/分页状态
    _custTier = ''; _custStage = ''; _custStarred = false; _custOverdueOnly = false; _custPage = 1;
    const coName = currentCompanyId ? (companies.find(c => c.id === currentCompanyId)?.name || '') : '';
    container.innerHTML = `
        <div class="cust-page">
            <div class="cust-head">
                <h2 class="cust-title">${currentLang === 'en' ? 'Customers' : '客户列表'}<span class="cust-idx">ASSET INDEX</span>${coName ? '<span class="cust-co">'+esc(coName)+'</span>' : ''}</h2>
                <div id="cust-summary-bar" class="cust-summary"></div>
                <div class="cust-head-actions">
                    <button class="btn" id="cust-import-btn">${typeof iconHtml==='function'?iconHtml('download',15):''} ${currentLang==='en'?'Import CSV':'导入 CSV'}</button>
                    <input type="file" id="cust-bulk-file" accept=".csv" style="display:none;" onchange="bulkImportCustomers()">
                    <button class="btn primary" onclick="showCustomerEditModal()">＋ ${currentLang==='en'?'New customer':'新建客户'}</button>
                </div>
            </div>
            <div class="cust-filters">
                <input class="cust-search" id="cust-search" aria-label="搜索客户" placeholder="${t('customer.search')}" oninput="filterCustomers()">
                <div class="cust-seg" id="cust-tier-seg" role="group" aria-label="分级">
                    <span class="seg-lbl">分级</span>
                    <button type="button" data-tier="" class="on">全部</button>
                    <button type="button" data-tier="A">A</button>
                    <button type="button" data-tier="B">B</button>
                    <button type="button" data-tier="C">C</button>
                    <button type="button" data-tier="none">${t('cust.field.tier_none')}</button>
                </div>
                <select id="cust-country-filter" aria-label="国家" onchange="filterCustomers()">
                    <option value="">${currentLang==='en'?'All Countries':'全部国家'}</option>
                </select>
                <select id="cust-buyer-filter" aria-label="买家类型" onchange="filterCustomers()">
                    <option value="">${currentLang==='en'?'All Buyer Types':'全部类型'}</option>
                </select>
                <div class="cust-seg" id="cust-stage-seg" role="group" aria-label="商机阶段"></div>
                <button type="button" class="cust-star-toggle" id="cust-starred-toggle" onclick="toggleStarredFilter()">☆ ${currentLang==='en'?'Starred only':'只看星标'}</button>
                <button type="button" class="cust-star-toggle" id="cust-overdue-toggle" onclick="toggleOverdueFilter()">⚠ ${currentLang==='en'?'Overdue only':'只看逾期'}</button>
                <select id="cust-sort" aria-label="排序" onchange="filterCustomers()">
                    <option value="follow_up">${currentLang==='en'?'Follow-up first':'待跟进优先'}</option>
                    <option value="name">${currentLang==='en'?'By name':'按名称排序'}</option>
                    <option value="updated_at">${currentLang==='en'?'Recently updated':'按最近跟进'}</option>
                </select>
            </div>
            <div class="cust-table-wrap">
                <table class="cust-table" id="customers-table">
                    <thead><tr>
                        <th class="c-star"></th>
                        <th>客户 <span class="th-lbl">/ CUSTOMER</span></th>
                        <th class="c-tier">分级</th>
                        <th class="c-country">国家</th>
                        <th class="c-buyer">买家类型</th>
                        <th class="c-stage">商机阶段</th>
                        <th class="c-tags">标签</th>
                        <th class="c-num">订单数</th>
                        <th class="c-amt">订单总额</th>
                        <th class="c-date">最近联系</th>
                        <th class="c-follow">下次跟进</th>
                    </tr></thead>
                    <tbody id="customers-tbody"></tbody>
                </table>
                <div id="customers-loading" class="loading-row hidden"><div class="spinner"></div>加载中...</div>
                <div id="customers-empty" class="empty-state hidden"><div class="empty-icon">👤</div><h2>暂无客户</h2><p>点击「新建客户」逐个添加，或用「导入 CSV」批量导入</p></div>
            </div>
            <div class="cust-foot" id="cust-foot"></div>
        </div>`;
    // 导入 CSV：选择文件直接上传
    const importBtn = $('cust-import-btn');
    if (importBtn) importBtn.addEventListener('click', function () { $('cust-bulk-file')?.click(); });
    // 分级 / 商机阶段 分段筛选（事件委托）
    const tierSeg = $('cust-tier-seg');
    if (tierSeg) tierSeg.addEventListener('click', function (e) {
        const b = e.target.closest('button[data-tier]');
        if (!b) return;
        _custTier = b.getAttribute('data-tier');
        Array.from(tierSeg.querySelectorAll('button')).forEach(function (x) { x.classList.toggle('on', x === b); });
        filterCustomers();
    });
    const stageSeg = $('cust-stage-seg');
    if (stageSeg) stageSeg.addEventListener('click', function (e) {
        const b = e.target.closest('button[data-stage]');
        if (!b) return;
        _custStage = b.getAttribute('data-stage');
        Array.from(stageSeg.querySelectorAll('button')).forEach(function (x) { x.classList.toggle('on', x === b); });
        filterCustomers();
    });
    await loadCustomersData();
}

let allCustomers = [];
let _customerSummary = null;
async function loadCustomersData() {
    if (!currentCompanyId) return;
    $('customers-loading').classList.remove('hidden');
    // 列表与顶栏汇总并行；汇总失败不阻断列表
    const [list, summary] = await Promise.all([
        api('GET', '/api/trade/customers'),
        api('GET', '/api/trade/customers/summary'),
    ]);
    allCustomers = list || [];
    _customerSummary = summary || null;
    _renderCustomerSummaryBar();
    // 侧栏「客户管理」逾期角标：随 summary 立即刷新（不等 30s 轮询）
    if (typeof _updateDailyBriefBadge === 'function') {
        _updateDailyBriefBadge(_customerSummary && _customerSummary.overdue);
    }
    // Enrich with library associations
    for (let c of allCustomers) {
        const libs = await api('GET', `/api/trade/customers/${c.id}/libraries`) || [];
        c._libraries = libs;
    }
    $('customers-loading').classList.add('hidden');
    _refreshCustomerFilterOptions();
    filterCustomers();
}

function _renderCustomerSummaryBar() {
    const el = $('cust-summary-bar');
    if (!el) return;
    const s = _customerSummary || {};
    const byCur = s.order_totals_by_currency || {};
    const curKeys = Object.keys(byCur);
    // 多币种不折算：主显示金额最大的币种，其余用「+N 种」
    let amtText = '—';
    if (curKeys.length) {
        curKeys.sort(function (a, b) { return (byCur[b] || 0) - (byCur[a] || 0); });
        const main = curKeys[0];
        const n = Number(byCur[main] || 0);
        const compact = n >= 1000
            ? (main + ' ' + (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'K')
            : (main + ' ' + n.toLocaleString('en-US'));
        amtText = compact + (curKeys.length > 1
            ? (' ' + t('cust.summary.plus_currencies', { n: curKeys.length - 1 }))
            : '');
    }
    // 币种来自订单表（用户/AI 可写），必须转义后再进 innerHTML
    const amtSafe = esc(amtText);
    el.innerHTML =
        '<span><b>' + t('cust.summary.total', { n: s.total || 0 }) + '</b></span>' +
        '<span>' + t('cust.summary.follow_up', { n: s.follow_up_pending || 0 }) + '</span>' +
        '<span>' + t('cust.summary.overdue', { n: s.overdue || 0 }) + '</span>' +
        '<span>' + t('cust.summary.orders', { amt: amtSafe }) + '</span>';
}

function _parseExtra1(c) { try { return JSON.parse(c.extra1||'{}'); } catch(e) { return {}; } }
function _parseExtra2(c) { try { return JSON.parse(c.extra2||'{}'); } catch(e) { return {}; } }
function _parseExtra3(c) { try { return JSON.parse(c.extra3||'{}'); } catch(e) { return {}; } }

// #region wall-followup-note
// 客户级跟进备注：只挂在主联系人卡片，单独一行并标明「客户级」，不混入人物 note
// （2026-11-18 口径 C：人物 note 保持空，客户级字段单独展示）
function _primaryFollowUpNoteHtml(note, isPrimary) {
    const text = String(note || '').trim();
    if (!isPrimary || !text) return '';
    return '<p class="muted wall-followup-note" title="' + esc(t('cust.followup_note_hint')) + '">' +
        '<span class="tagchip dim">' + esc(t('cust.followup_note')) + '</span> ' + esc(text) + '</p>';
}
// #endregion wall-followup-note

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

function _customerStageAuto(c) {
    // stage_auto true / 缺省 = 自动推导；false = 手动 override
    return c && c.stage_auto !== false;
}

const _CRM_STAGES = ['询盘', '报价', '样品', '订单'];

// #region wall-inquiries
/** 列表 pill：有效阶段高亮；手动锁定时当前 pill 加「手」角标。 */
function _stagePillsHtml(stage, stageAuto, overdue) {
    return _CRM_STAGES.map(function (s) {
        const on = stage === s;
        let html = '<span class="pill' + (on ? ' on' : '') + (overdue && on ? ' hot' : '') +
            '" style="position:relative">' + esc(s);
        if (on && !stageAuto) {
            html += '<span class="stage-manual-badge" title="' + esc(t('inquiry.manual_title')) +
                '">' + esc(t('inquiry.manual_badge')) + '</span>';
        }
        return html + '</span>';
    }).join('');
}

/** 墙内询盘区 HTML（人物之下、订单之上）。 */
function renderWallInquiriesSection(inquiries, delayFn) {
    const list = Array.isArray(inquiries) ? inquiries : [];
    let html = '<div class="wsec"><div class="wsec-head"><h4>' + t('inquiry.section') +
        '</h4><span class="cnt">INQUIRIES // ' + list.length +
        '</span><span class="ddline" aria-hidden="true"></span></div>';
    html += '<div class="wgrid" id="wall-inq-list">';
    if (!list.length) {
        html += '<div class="wall-empty"' + delayFn() + '>' + t('inquiry.empty') + '</div>';
    } else {
        list.forEach(function (inq) {
            const st = String(inq.stage || '询盘');
            const stageOpts = _CRM_STAGES.map(function (s) {
                return '<option value="' + esc(s) + '"' + (st === s ? ' selected' : '') +
                    '>' + esc(s) + '</option>';
            }).join('');
            html += '<article class="wcard"' + delayFn() + ' data-inquiry-id="' +
                esc(String(inq.id)) + '">' +
                '<div class="wc-top"><span class="wc-name">' + esc(inq.title || '') +
                '</span><span class="pill on">' + esc(st) + '</span></div>' +
                '<div style="margin-top:8px;display:flex;gap:6px;align-items:center;flex-wrap:wrap;">' +
                '<select class="wall-inq-stage" data-id="' + esc(String(inq.id)) + '">' +
                stageOpts + '</select>' +
                '<button type="button" class="btn-xs wall-inq-del" data-id="' +
                esc(String(inq.id)) + '">' + t('inquiry.delete') + '</button>' +
                '</div></article>';
        });
    }
    html += '</div>';
    html += '<div style="margin-top:8px;display:flex;gap:6px;align-items:center;flex-wrap:wrap;">' +
        '<input type="text" id="wall-inq-title" placeholder="' + esc(t('inquiry.title_ph')) +
        '" style="flex:1;min-width:120px;font-size:12px;padding:4px 8px;" />' +
        '<select id="wall-inq-stage-new">' +
        _CRM_STAGES.map(function (s) {
            return '<option value="' + esc(s) + '"' + (s === '询盘' ? ' selected' : '') +
                '>' + esc(s) + '</option>';
        }).join('') +
        '</select>' +
        '<button type="button" class="btn-xs" id="wall-inq-create">' + t('inquiry.create') +
        '</button></div></div>';
    return html;
}
// #endregion wall-inquiries

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

function _custStageIndex(stage) {
    const i = ['询盘', '报价', '样品', '订单'].indexOf(stage);
    return i < 0 ? 0 : i + 1;
}
function _custFmtMoney(n) { return Number(n || 0).toLocaleString('en-US'); }
function _custShortDate(v) {
    const s = String(v || '');
    if (!s) return '—';
    return s.length >= 10 ? s.slice(5, 10).replace('-', '.') : s;
}

let _custFiltered = [];

function renderCustomersTable(data) {
    const tbody = $('customers-tbody');
    const empty = $('customers-empty');
    if (!tbody || !empty) return;
    _custFiltered = data;
    if (!data.length) {
        tbody.innerHTML = '';
        empty.classList.remove('hidden');
        _custRenderFoot(0, 0, 0, 1, $('cust-sort')?.value || 'follow_up');
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
            const oa = da < today ? 0 : 1;
            const ob = db < today ? 0 : 1;
            if (oa !== ob) return oa - ob;
            if (da !== db) return da.localeCompare(db);
        }
        return (a.name || '').localeCompare(b.name || '');
    });

    const total = sorted.length;
    const pages = Math.max(1, Math.ceil(total / _CUST_PAGE_SIZE));
    if (_custPage > pages) _custPage = pages;
    if (_custPage < 1) _custPage = 1;
    const start = (_custPage - 1) * _CUST_PAGE_SIZE;
    const pageRows = sorted.slice(start, start + _CUST_PAGE_SIZE);

    tbody.innerHTML = pageRows.map((c) => {
        const ex1 = _parseExtra1(c);
        const ex2 = _parseExtra2(c);
        const tier = (ex1['tier'] || '').trim();
        const country = ex1['country'] || '';
        const buyer = ex1['buyer_type'] || '';
        const tags = (_parseExtra3(c).tags || []);
        const stage = _customerStage(c);
        const si = _custStageIndex(stage);
        const starred = Number(c.is_starred) === 1;
        const contact = c.contact || '';
        const title = ex2['title'] || '';
        const follow = _customerFollowUpDate(c);
        const overdue = !!(follow && follow < today);
        const od = overdue ? _followUpOverdueDays(c) : 0;
        const oc = Number(c.order_count || 0);
        const byCur = c.order_totals_by_currency || {};
        let amt = '—';
        if (c.order_total_amount != null && c.order_total_currency) {
            amt = esc(c.order_total_currency + ' ' + _custFmtMoney(c.order_total_amount));
        } else if (Object.keys(byCur).length > 1) {
            amt = currentLang === 'en' ? 'Multi' : '多币种';
        }
        let followHtml = '<span class="muted">—</span>';
        if (overdue) followHtml = '<span class="od">⚠ ' + (currentLang === 'en' ? 'Overdue ' : '逾期 ') + od + (currentLang === 'en' ? 'd' : ' 天') + '</span>';
        else if (follow) followHtml = '<span>' + esc(follow === today ? (currentLang === 'en' ? 'Today' : '今天') : _custShortDate(follow)) + '</span>';
        const processBtn = overdue
            ? (' <button type="button" class="cust-process" onclick="event.stopPropagation();openFollowUpModal(' + c.id + ')">' +
                (currentLang === 'en' ? 'Resolve' : '处理') + '</button>')
            : '';
        let dots = '';
        for (let i = 1; i <= 4; i++) dots += '<i class="' + (i <= si ? 'on' : '') + '"></i>';
        const tagHtml = tags.length
            ? tags.slice(0, 3).map(function (tg) { return '<span class="rtag">' + esc(tg) + '</span>'; }).join('')
            : '<span class="muted">—</span>';
        return '<tr class="cust-row' + (overdue ? ' overdue' : '') + '" onclick="openCustomerWall(' + c.id + ')">' +
            '<td class="c-star" onclick="event.stopPropagation()"><button type="button" class="star-btn' + (starred ? ' on' : '') + '" onclick="toggleCustomerStar(event,' + c.id + ')" aria-label="星标">★</button></td>' +
            '<td class="c-customer"><div class="rname">' + esc(c.name) + '</div>' +
            '<div class="rsub">' + esc([contact, title].filter(Boolean).join(' · ') || '—') + '</div></td>' +
            '<td class="c-tier">' + (tier ? '<span class="tchip">' + esc(tier) + '</span>' : '<span class="tchip none">' + (currentLang === 'en' ? 'n/a' : '未分级') + '</span>') + '</td>' +
            '<td>' + esc(country || '—') + '</td>' +
            '<td>' + esc(buyer || '—') + '</td>' +
            '<td class="c-stage"><span class="stage-dots">' + dots + '</span><span class="stage-tx">' + esc(stage) + '</span></td>' +
            '<td class="c-tags">' + tagHtml + '</td>' +
            '<td class="c-num">' + oc + '</td>' +
            '<td class="c-amt">' + amt + '</td>' +
            '<td class="c-date">' + esc(_custShortDate(c.last_contact_at)) + '</td>' +
            '<td class="c-follow">' + followHtml + processBtn + '</td>' +
            '</tr>';
    }).join('');

    _custRenderFoot(start + 1, Math.min(start + _CUST_PAGE_SIZE, total), total, pages, sortBy);
    _custRenderStageSeg();
}

function _custRenderFoot(start, end, total, pages, sortBy) {
    const f = $('cust-foot');
    if (!f) return;
    if (!total) { f.innerHTML = '<span class="foot-range">' + (currentLang === 'en' ? 'No customers' : '暂无客户') + '</span>'; return; }
    const noteMap = {
        follow_up: currentLang === 'en' ? 'Follow-up first · overdue → today → next date' : '按「待跟进优先」· 逾期 → 今天 → 下次跟进日期',
        name: currentLang === 'en' ? 'Sorted by name' : '按名称排序',
        updated_at: currentLang === 'en' ? 'Recently updated' : '按最近跟进',
    };
    let pager = '';
    for (let p = 1; p <= pages; p++) {
        pager += '<button type="button" class="pg' + (p === _custPage ? ' on' : '') + '" onclick="_custGoPage(' + p + ')">' + p + '</button>';
    }
    f.innerHTML = '<span class="foot-range">' + (currentLang === 'en' ? ('Showing ' + start + '–' + end + ' / ' + total) : ('显示 ' + start + '–' + end + ' / ' + total)) + '</span>' +
        '<span class="foot-note">' + esc(noteMap[sortBy] || '') + '</span>' +
        '<span class="foot-pager">' + (pages > 1 ? pager : '') + '</span>';
}

function _custRenderStageSeg() {
    const seg = $('cust-stage-seg');
    if (!seg) return;
    const counts = { '': 0, '询盘': 0, '报价': 0, '样品': 0, '订单': 0 };
    allCustomers.forEach(function (c) {
        const st = _customerStage(c);
        counts['']++;
        if (counts[st] != null) counts[st]++;
    });
    const order = ['', '询盘', '报价', '样品', '订单'];
    const labels = { '': (currentLang === 'en' ? 'All' : '全部'), '询盘': '询盘', '报价': '报价', '样品': '样品', '订单': '订单' };
    seg.innerHTML = '<span class="seg-lbl">' + (currentLang === 'en' ? 'Stage' : '商机阶段') + '</span>' +
        order.map(function (k) {
            return '<button type="button" data-stage="' + esc(k) + '"' + (_custStage === k ? ' class="on"' : '') + '>' +
                esc(labels[k]) + ' <b>' + counts[k] + '</b></button>';
        }).join('');
}

function _custGoPage(p) { _custPage = p; renderCustomersTable(_custFiltered); }

function toggleStarredFilter() {
    _custStarred = !_custStarred;
    const b = $('cust-starred-toggle');
    if (b) { b.classList.toggle('on', _custStarred); b.textContent = (_custStarred ? '★ ' : '☆ ') + (currentLang === 'en' ? 'Starred only' : '只看星标'); }
    filterCustomers();
}

function toggleOverdueFilter() {
    _custOverdueOnly = !_custOverdueOnly;
    const b = $('cust-overdue-toggle');
    if (b) {
        b.classList.toggle('on', _custOverdueOnly);
        b.textContent = '⚠ ' + (currentLang === 'en' ? 'Overdue only' : '只看逾期');
    }
    filterCustomers();
}

function openFollowUpModal(cid) {
    /** 逾期跟进处理：设置下次跟进日或标记不再跟进，提交后该客户退出逾期。 */
    const c = allCustomers.find(function (x) { return x.id === cid; });
    if (!c) return;
    const follow = _customerFollowUpDate(c) || '—';
    const od = _followUpOverdueDays(c);
    document.querySelectorAll('#followup-modal').forEach(function (el) { el.remove(); });
    const bd = document.createElement('div');
    bd.className = 'modal-backdrop';
    bd.id = 'followup-modal';
    const today = _todayYmd();
    bd.innerHTML =
        '<div class="modal" style="width:520px;max-width:94vw;">' +
        '<h3 style="margin:0 0 6px;">' + (currentLang === 'en' ? 'Resolve follow-up' : '跟进处理') + '</h3>' +
        '<p class="muted" style="font-size:12.5px;margin:0 0 14px;">' + esc(c.name) +
        ' · ' + (currentLang === 'en' ? 'was due ' : '原跟进日 ') + esc(follow) +
        ' · ' + (currentLang === 'en' ? 'overdue ' : '逾期 ') + od + (currentLang === 'en' ? 'd' : ' 天') + '</p>' +
        '<label style="display:flex;align-items:center;gap:8px;font-size:13px;margin-bottom:10px;">' +
        '<input type="checkbox" id="fu-no-more"> ' + (currentLang === 'en' ? 'No more follow-up (clear date)' : '不再跟进（清空下次跟进日）') + '</label>' +
        '<div class="form-group"><label for="fu-date">' + (currentLang === 'en' ? 'Next follow-up date' : '下次跟进日') + '</label>' +
        '<input type="date" id="fu-date" value="' + esc(today) + '"></div>' +
        '<div class="form-group"><label for="fu-note">' + (currentLang === 'en' ? 'Note (optional)' : '本次跟进备注（可选）') + '</label>' +
        '<textarea id="fu-note" rows="3" style="width:100%;box-sizing:border-box;"></textarea></div>' +
        '<p class="muted" style="font-size:11.5px;margin:0 0 14px;">' +
        (currentLang === 'en' ? 'This customer then leaves the overdue list; a timeline event is recorded.' : '处理后该客户不再计入逾期；处理记录会出现在客户详情时间线。') + '</p>' +
        '<div style="display:flex;gap:8px;justify-content:flex-end;">' +
        '<button type="button" id="fu-cancel">' + (currentLang === 'en' ? 'Cancel' : '取消') + '</button>' +
        '<button type="button" class="primary" id="fu-submit">' + (currentLang === 'en' ? 'Save & resolve' : '保存并解决逾期') + '</button>' +
        '</div></div>';
    document.body.appendChild(bd);
    bd.addEventListener('click', function (e) { if (e.target === bd) bd.remove(); });
    function onEsc(e) { if (e.key === 'Escape') { bd.remove(); document.removeEventListener('keydown', onEsc); } }
    document.addEventListener('keydown', onEsc);
    const noMore = document.getElementById('fu-no-more');
    const dateEl = document.getElementById('fu-date');
    noMore.addEventListener('change', function () { dateEl.disabled = noMore.checked; });
    document.getElementById('fu-cancel').addEventListener('click', function () { bd.remove(); });
    document.getElementById('fu-submit').addEventListener('click', async function () {
        const resolved = noMore.checked;
        const nd = dateEl.value;
        const note = (document.getElementById('fu-note').value || '').trim();
        if (!resolved && !nd) { toast(currentLang === 'en' ? 'Pick a date or mark no follow-up' : '请选择下次跟进日，或勾选不再跟进'); return; }
        const btn = this;
        btn.disabled = true;
        btn.textContent = currentLang === 'en' ? 'Saving…' : '保存中…';
        const r = await api('POST', '/api/trade/customers/' + cid + '/follow-up', {
            next_follow_up_date: resolved ? null : nd,
            resolved: resolved,
            note: note,
        });
        if (!r) { btn.disabled = false; btn.textContent = currentLang === 'en' ? 'Save & resolve' : '保存并解决逾期'; return; }
        bd.remove();
        toast(currentLang === 'en' ? 'Resolved; overdue badge updated' : '已处理，逾期角标已更新');
        await loadCustomersData();
    });
}

async function toggleCustomerStar(ev, cid) {
    if (ev) ev.stopPropagation();
    const c = allCustomers.find(function (x) { return x.id === cid; });
    if (!c) return;
    const next = Number(c.is_starred) === 1 ? 0 : 1;
    const r = await api('PUT', '/api/trade/customers/' + cid, { is_starred: next });
    if (!r) return;
    c.is_starred = next;
    renderCustomersTable(_custFiltered);
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
    const search = ($('cust-search')?.value || '').toLowerCase();
    const country = $('cust-country-filter')?.value || '';
    const buyer = $('cust-buyer-filter')?.value || '';
    let filtered = allCustomers;
    if (search) {
        filtered = filtered.filter(c => {
            const e1 = _parseExtra1(c); const e2 = _parseExtra2(c);
            const tags = (_parseExtra3(c).tags || []).join(' ');
            const extras = (c.extra_contacts || []).map(function (x) {
                return [x.name, x.email].join(' ');
            }).join(' ');
            const blob = [c.name, c.contact, e1.country, e1.city, e1.buyer_type, e2.email, e2.title, c.note, tags, extras]
                .join(' ').toLowerCase();
            return blob.includes(search);
        });
    }
    if (_custTier) {
        filtered = filtered.filter(c => {
            const tt = _parseExtra1(c)['tier'] || c.tier || '';
            if (_custTier === 'none') return !tt;
            return tt === _custTier;
        });
    }
    if (country) filtered = filtered.filter(c => (_parseExtra1(c).country || '') === country);
    if (buyer) filtered = filtered.filter(c => (_parseExtra1(c).buyer_type || '') === buyer);
    if (_custStage) filtered = filtered.filter(c => _customerStage(c) === _custStage);
    if (_custStarred) filtered = filtered.filter(c => Number(c.is_starred) === 1);
    if (_custOverdueOnly) {
        const tday = _todayYmd();
        filtered = filtered.filter(c => {
            const f = _customerFollowUpDate(c);
            return f && f < tday;
        });
    }
    _custPage = 1;
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
    // 「已取消」不在 4 档进度里，返回 -1 让调用方画取消态
    const s = status || '';
    if (s === '已取消') return -1;
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
    document.body.classList.remove('wall-open');
    // 页内视图返回：恢复打开前的顶栏标题（不依赖当前视图是哪一个）
    const tt = document.getElementById('app-top-title');
    const tl = document.getElementById('app-top-lbl');
    if (tt && tl) {
        if (wall._prevTop) {
            tt.textContent = wall._prevTop.t;
            tl.textContent = wall._prevTop.l;
            wall._prevTop = null;
        } else if (typeof currentView !== 'undefined' && currentView === 'customers') {
            tt.textContent = currentLang === 'en' ? 'Customers' : '客户管理';
            tl.textContent = '/ CUSTOMERS';
        }
    }
}

async function openCustomerWall(cid) {
    const wall = $('customer-wall');
    if (!wall) return;
    closeCustomerDetail();

    // 卡片墙：overview + 邮件 + 邮箱 + 时间线 + 画像（并行；画像失败不阻断）
    const [ov, mailRes, mailboxRes, timelineRes, factsRes, giftsRes, inqRes] = await Promise.all([
        api('GET', `/api/trade/customers/${cid}/overview`),
        api('GET', `/api/trade/customers/${cid}/emails`),
        api('GET', '/api/trade/mailboxes'),
        api('GET', `/api/trade/customers/${cid}/timeline?days=60`),
        api('GET', `/api/trade/customers/${cid}/facts`),
        api('GET', `/api/trade/customers/${cid}/gifts`),
        api('GET', `/api/trade/customers/${cid}/inquiries`),
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
    const timelineApi = Array.isArray(timelineRes) ? timelineRes : null;
    const c = ov.customer;
    // 同步本地列表缓存（阶段/跟进日实列）
    const cached = allCustomers.find(function (x) { return x.id === cid; });
    if (cached) Object.assign(cached, c);
    editingCustomerData = c;

    const e1 = _parseExtra1(c);
    const e2 = _parseExtra2(c);
    const stage = _customerStage(c);
    const follow = _customerFollowUpDate(c);
    const overdue = _isFollowUpOverdue(c);
    const people = ov.people || [];
    const orders = ov.orders || [];
    const fileEmails = ov.emails || [];
    const emailDetails = ov.email_details || [];
    const keyChats = ov.key_talks || [];
    // 优先用独立 timeline 接口；失败时回退 overview 内联（旧形状 text）
    const timeline = timelineApi || ov.timeline || [];
    const stats = ov.stats || {};
    // 无 is_important 时后端用最近 5 条兜底——标题/统计不能仍写「重要对话」
    const talksAreImportant = keyChats.length > 0 && !keyChats.some(function (c) {
        return c.is_important_fallback;
    }) && keyChats.some(function (c) { return c.is_important; });
    const talksTitle = talksAreImportant
        ? (currentLang === 'en' ? 'Key talks' : '重要对话')
        : (currentLang === 'en' ? 'Recent talks' : '最近对话');
    const emailStatN = (stats.email_count != null) ? stats.email_count : (mailboxBound ? mailRecords.length : fileEmails.length);
    const talkStatN = (stats.key_talk_count != null) ? stats.key_talk_count : keyChats.length;
    const talksStatLabel = talksAreImportant
        ? ((currentLang === 'en' ? 'Mail ' : '邮件 ') + emailStatN + (currentLang === 'en' ? ' · Key talks ' : ' · 重要对话 ') + talkStatN)
        : ((currentLang === 'en' ? 'Mail ' : '邮件 ') + emailStatN + (currentLang === 'en' ? ' · Talks ' : ' · 对话 ') + talkStatN);
    const quoteCount = stats.quote_count || 0;
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

    const inquiries = Array.isArray(inqRes) ? inqRes : [];
    const wallTags = (_parseExtra3(c).tags || []).slice();
    const factsPayload = (factsRes && typeof factsRes === 'object') ? factsRes : { available: false, items: [] };
    const giftsPayload = (giftsRes && typeof giftsRes === 'object') ? giftsRes : { available: false, items: [] };

    // ── s3 页内卡片墙：header + 4格KPI + 三栏 + 横贯时间线 ──
    function sect(cls) { return '<div class="wsec ' + cls + '">'; }
    function chHead(title, lbl) {
        return '<div class="ch"><span class="t">' + title + '</span><span class="ch-lbl">' + lbl + '</span></div>';
    }

    // 关联人物
    let peopleHtml = sect('sec-people') +
        '<div class="ch"><span class="t">' + (currentLang === 'en' ? 'People' : '人物') + '</span>' +
        '<span class="ch-acts"><button type="button" class="lnk" id="wall-add-contact">' + t('contacts.add') + '</button></span>' +
        '<span class="ch-lbl">PERSONS · ' + people.length + '</span></div>';
    if (!people.length) {
        peopleHtml += '<div class="wall-empty">' + t('contacts.empty') + '</div>';
    } else {
        people.forEach(function (p) {
            const isPrimary = !!p.is_primary || p.id == null;
            const ini = String(p.name || '?').trim().slice(0, 2).toUpperCase();
            const role = ([(p.title || '').trim(), (p.responsibility || '').trim()].filter(Boolean).join(' · ')
                || p.function || (isPrimary ? (currentLang === 'en' ? 'Primary contact' : '主要联系人') : ''));
            const fname = (p.function || (isPrimary ? '决策人' : '其他'));
            const acts = isPrimary
                ? ('<a href="#" class="lnk wall-edit-primary">' + t('contacts.edit') + '</a>')
                : ('<a href="#" class="lnk wall-edit-contact" data-id="' + esc(String(p.id)) + '">' + t('contacts.edit') + '</a>' +
                    '<a href="#" class="lnk wall-del-contact" data-id="' + esc(String(p.id)) + '" data-name="' + esc(p.name || '') + '">' + t('contacts.delete') + '</a>');
            peopleHtml += '<div class="person" data-contact-id="' + (p.id != null ? esc(String(p.id)) : '') + '" data-primary="' + (isPrimary ? '1' : '0') + '">' +
                '<span class="p-tag' + (isPrimary ? '' : ' o') + '">ASSET · ' + esc(fname) + '</span>' +
                '<div class="row1"><span class="avatar">' + esc(ini) + '</span><div>' +
                '<div class="nm">' + esc(p.name) + (isPrimary ? '<span class="zhu">主</span>' : '') + '</div>' +
                '<div class="role">' + esc(role) + '</div></div>' +
                '<span class="p-acts">' + acts + '</span></div>';
            const kv = [];
            if (p.email) kv.push('<span class="k">EMAIL</span><span class="v mono">' + esc(p.email) + '</span>');
            const phone = [p.phone, p.whatsapp ? 'WA ' + p.whatsapp : '', p.wechat ? 'WeChat ' + p.wechat : ''].filter(Boolean).join(' · ');
            if (phone) kv.push('<span class="k">PHONE</span><span class="v mono">' + esc(phone) + '</span>');
            if (kv.length) peopleHtml += '<div class="kv">' + kv.join('') + '</div>';
            peopleHtml += '</div>';
        });
    }
    peopleHtml += '</div>';

    // 询盘（复用现有区块）
    const inqHtml = renderWallInquiriesSection(inquiries, delay);

    // 订单
    let ordersHtml = sect('sec-orders') +
        chHead(currentLang === 'en' ? 'Orders' : '订单', 'ORDERS · ' + orders.length);
    if (!orders.length) {
        ordersHtml += '<div class="wall-empty">' + (currentLang === 'en' ? 'No orders yet' : '暂无订单记录') + '</div>';
    } else {
        const steps = currentLang === 'en'
            ? ['Quote', 'Ordered', 'Shipped', 'Done'] : ['报价中', '已下单', '已出货', '已完成'];
        orders.forEach(function (o) {
            const prog = _orderProgress(o.status);
            const cancelled = prog < 0;
            const filled = cancelled ? 0 : Math.round(prog / 100 * 4);
            const amt = (o.total_amount != null && o.total_amount !== '')
                ? ((o.currency || 'USD') + ' ' + Number(o.total_amount).toLocaleString('en-US'))
                : (currentLang === 'en' ? 'Price TBD' : '金额待谈');
            const items = o.items || [];
            const product = items.length
                ? (items[0].product_name + (items.length > 1 ? ' 等' + items.length + '项' : ''))
                : (o.product_name || '');
            const qty = items.length
                ? items.map(function (it) { return (it.quantity || '') + (it.unit || ''); }).join(' / ')
                : ((o.quantity || '') + (o.unit || ''));
            const logistics = [[o.incoterm, o.port_of_loading].filter(Boolean).join(' '), o.payment_terms || '', o.lead_time_text || ''].filter(Boolean).join(' / ');
            const containerLine = [o.container, o.port_of_loading].filter(Boolean).join(' ');
            let shipLine = '';
            if (o.shipped_at) shipLine = String(o.shipped_at).slice(0, 7).replace('-', '.') + (currentLang === 'en' ? ' shipped' : ' 出货');
            else if (o.delivery_date) shipLine = o.delivery_date;
            let segs = '', labels = '';
            for (let i = 0; i < 4; i++) {
                segs += '<i class="' + (i < filled ? 'f' : '') + '"></i>';
                labels += '<span class="' + (i === filled - 1 || (filled === 4 && i === 3) ? 'on' : '') + '">' + esc(steps[i]) + '</span>';
            }
            const r3 = [logistics, containerLine, shipLine].filter(Boolean)
                .map(function (x) { return '<span>' + esc(x) + '</span>'; }).join('');
            ordersHtml += '<div class="ord">' +
                '<div class="r1"><span class="no">' + esc(o.order_no || ('#' + o.id)) + '</span>' +
                '<span class="chip k">' + esc(o.status || '') + '</span>' +
                '<span class="amt">' + esc(amt) + '</span></div>' +
                '<div class="pn">' + esc(product) + '<span>' + esc(qty) + '</span></div>' +
                (cancelled
                    ? '<div class="r3"><span>' + (currentLang === 'en' ? 'Cancelled' : '已取消') + '</span></div>'
                    : ('<div class="prog">' + segs + '</div><div class="prog-l">' + labels + '</div>')) +
                (r3 ? '<div class="r3">' + r3 + '</div>' : '') +
                '</div>';
        });
    }
    ordersHtml += '</div>';

    // 邮件
    let mailHtml = sect('sec-mail') + '<div class="ch"><span class="t">' + (currentLang === 'en' ? 'Email' : '邮件') + '</span>';
    if (mailboxBound) {
        mailHtml += '<span class="ch-acts"><button type="button" class="lnk" id="wall-email-refresh">' + (currentLang === 'en' ? 'Refresh' : '刷新') + '</button></span>';
    }
    mailHtml += '<span class="ch-lbl">MAIL · ' + (mailboxBound ? mailRecords.length : emailDetails.length) + '</span></div>';
    const addrList = emailDetails.length
        ? emailDetails
        : fileEmails.map(function (em, i) { return { address: em, is_primary: i === 0 }; });
    if (!mailboxBound) {
        if (addrList.length) {
            addrList.forEach(function (em) {
                const addr = typeof em === 'string' ? em : (em.address || '');
                const isPri = typeof em === 'object' && em.is_primary;
                mailHtml += '<div class="addr">' + (typeof iconHtml === 'function' ? iconHtml('mail', 16) : '') +
                    '<span class="mono">' + esc(addr) + '</span>' +
                    (isPri ? '<span class="chip k" style="margin-left:auto">' + (currentLang === 'en' ? 'Primary' : '主') + '</span>' : '') + '</div>';
            });
        } else {
            mailHtml += '<div class="wall-empty">' + (currentLang === 'en' ? 'No email on file' : '暂无邮箱') + '</div>';
        }
        mailHtml += '<div class="mail-note">' + (currentLang === 'en'
            ? 'Addresses only — bind a mailbox to read mail.' : '只显示邮箱地址，不读取邮箱') + '</div>' +
            '<button type="button" class="lnk" id="wall-goto-mailboxes" style="margin-top:6px;">' +
            (currentLang === 'en' ? 'Open Mailboxes' : '去绑定邮箱') + '</button>';
    } else if (!mailRecords.length) {
        mailHtml += '<div class="wall-empty">' + (currentLang === 'en' ? 'No synced emails yet.' : '暂无已同步的邮件记录') + '</div>';
    } else {
        mailHtml += '<div id="wall-email-grid">';
        mailRecords.forEach(function (m, idx) {
            const subj = m.subject || (currentLang === 'en' ? '(no subject)' : '（无主题）');
            const party = m.from_addr || '';
            const dt = (m.received_at || '').slice(0, 16).replace('T', ' ');
            mailHtml += '<div class="it wall-mail-card" data-mail-idx="' + idx + '" style="cursor:pointer;">' +
                '<div class="r1"><span>' + esc(subj) + '</span><span class="mono">' + esc(dt) + '</span></div>' +
                '<p class="mono">' + esc(party) + '</p>' +
                '<div class="wall-mail-body hidden"><p style="white-space:pre-wrap;margin:6px 0 0;">' + esc(m.body_text || m.snippet || '') + '</p></div></div>';
        });
        mailHtml += '</div>';
    }
    mailHtml += '</div>';

    // 对话
    let talksHtml = sect('sec-talks') + chHead(talksTitle, 'TALKS · ' + keyChats.length);
    if (!keyChats.length) {
        talksHtml += '<div class="wall-empty">' + (currentLang === 'en' ? 'No conversations linked' : '暂无关联对话') + '</div>';
    } else {
        keyChats.forEach(function (conv) {
            const talkTitle = (conv.title || '').trim() || (conv.query || '').slice(0, 120);
            const talkSummary = (conv.summary || '').trim() || (conv.response || '').slice(0, 100);
            const dt = (conv.created_at || '').slice(5, 10).replace('-', '.');
            talksHtml += '<div class="it" data-conv-id="' + esc(String(conv.id || '')) + '" data-conv-summary="' + esc(conv.summary || '') + '">' +
                '<div class="r1"><span class="dot' + (conv.is_important ? '' : ' k') + '"></span><span class="wall-talk-title" style="cursor:text;" title="' +
                esc(currentLang === 'en' ? 'Double-click to edit' : '双击编辑标题') + '">' + esc(talkTitle) + '</span>' +
                '<span class="mono">' + esc(dt) + '</span></div>' +
                '<p class="wall-talk-summary">' + esc(talkSummary) + '</p></div>';
        });
    }
    talksHtml += '</div>';

    // 人物圈 / 喜好禁忌与往来（复用现有区块）
    const circleHtml = renderProfileCircleSection(cid, factsPayload, people, delay, mailboxBound);
    const prefsHtml = renderProfilePrefsSection(cid, factsPayload, giftsPayload, people, delay, mailboxBound);

    // 时间线
    let timelineHtml = sect('sec-timeline') + chHead(currentLang === 'en' ? 'Timeline' : '互动时间线', 'TIMELINE · LAST 60 DAYS') + '<div class="tl">';
    if (!timeline.length) {
        timelineHtml += '<div class="wall-empty">' + (currentLang === 'en' ? 'No activity yet' : '暂无互动记录') + '</div>';
    } else {
        timeline.forEach(function (t) {
            const kind = t.kind || '';
            let mk = '';
            if (kind === 'follow_up_due') mk = ' r';
            else if (kind === 'order_status' || kind === 'order_created') mk = ' f';
            const at = String(t.at || '').slice(5, 10).replace('-', '.');
            const title = t.title || t.text || '';
            const detail = t.detail || '';
            timelineHtml += '<div class="ev' + (kind === 'follow_up_due' ? ' next' : '') + '">' +
                '<div class="mk' + mk + '"></div><div class="dt">' + esc(at) + '</div>' +
                '<div class="tx"><b>' + esc(title) + '</b>' + (detail ? ' · ' + esc(detail) : '') + '</div></div>';
        });
    }
    timelineHtml += '</div></div>';

    // header 标签 chips + threat
    const tierChip = e1.tier ? ('<span class="chip on">' + (currentLang === 'en' ? 'TIER ' : '客户分级 ') + esc(e1.tier) + '</span>') : '';
    const locVals = [e1.country, e1.city].filter(Boolean);
    const locChip = locVals.length ? ('<span class="chip k">' + esc(locVals.join(' · ')) + '</span>') : '';
    const btChip = e1.buyer_type ? ('<span class="chip k">' + esc(e1.buyer_type) + '</span>') : '';
    const stageChip = '<span class="chip k">' + (currentLang === 'en' ? 'Stage · ' : '商机阶段 · ') + esc(stage) + '</span>';
    const starred = !!(c.starred || e1.starred);
    const starHtml = '<span class="star' + (starred ? ' on' : '') + '">' + (typeof iconHtml === 'function' ? iconHtml('star', 18) : '★') + '</span>';
    const threatHtml = overdue
        ? ('<span class="tri-d"></span>' + (currentLang === 'en' ? 'OVERDUE ' : '已逾期 ') + overdueDays + (currentLang === 'en' ? ' D' : ' 天'))
        : ('<span class="tri-d"></span>TODAY <span style="color:var(--muted)">→</span><span class="cn">' + esc(follow || (currentLang === 'en' ? 'Follow-up' : '待跟进')) + '</span>');

    // 4 格 KPI
    const statTotalHtml = multiCurrency
        ? esc(Object.keys(byCurrency).map(function (k) { return k + ' ' + Number(byCurrency[k]).toLocaleString('en-US'); }).join(' · '))
        : (hasAmount ? '0' : '—');
    const statsHtml = '<div class="stats">' +
        '<div><span class="n">' + (stats.people_count || people.length) + '</span><span class="d"><span class="lbl">PERSONS</span>' + (currentLang === 'en' ? 'People' : '关联人物') + '</span></div>' +
        '<div><span class="n">' + (stats.order_count || orders.length) + '</span><span class="d"><span class="lbl">ORDERS</span>' + (currentLang === 'en' ? 'Orders' : '订单数') + (quoteCount ? (' · ' + quoteCount + (currentLang === 'en' ? ' quoting' : ' 单报价中')) : '') + '</span></div>' +
        '<div><span class="n" id="wall-stat-total">' + statTotalHtml + '</span><span class="d"><span class="lbl">TOTAL · ' + esc(orderCurrency || (Object.keys(byCurrency)[0] || 'USD')) + '</span>' + (currentLang === 'en' ? 'Order total' : '订单总额') + '</span></div>' +
        '<div><span class="n">' + emailStatN + '<small>/</small>' + talkStatN + '</span><span class="d"><span class="lbl">MAIL / KEY TALKS</span>' + (currentLang === 'en' ? ('Mail ' + emailStatN + ' · talks ' + talkStatN) : ('邮件 ' + emailStatN + ' · 对话 ' + talkStatN)) + '</span></div>' +
        '</div>';

    wall.innerHTML =
        '<div class="det">' +
        '<div class="det-head">' +
        '<button type="button" class="wall-back" id="wall-back">' + (currentLang === 'en' ? '← Back to list' : '← 返回客户列表') + ' <kbd>ESC</kbd></button>' +
        '<div class="subject bracket">' + starHtml +
        '<span class="nm">' + esc(c.name) + '</span>' +
        '<div class="facts2">' + tierChip + locChip + btChip + stageChip +
        '<span class="tag-chips" id="wall-tags-chips"></span>' +
        '<input type="text" id="wall-tag-input" class="tag-in" placeholder="' + esc(t('contacts.tags_ph')) + '">' +
        '<button type="button" class="lnk" id="wall-tag-add">+</button>' +
        '</div>' +
        '<div class="threat">' + threatHtml + '</div>' +
        '</div>' +
        '</div>' +
        '<div class="det-actions">' +
        '<button type="button" class="primary" id="wall-edit">' + (currentLang === 'en' ? 'Edit profile' : '编辑档案') + '</button>' +
        '<button type="button" id="wall-open-profile">' + t('profile.open') + '</button>' +
        '<button type="button" id="wall-add-order">' + (currentLang === 'en' ? 'Add order' : '添加订单') + '</button>' +
        '<label class="da-lbl">' + (currentLang === 'en' ? 'Stage' : '商机阶段') + ' <select id="wall-stage">' + (function () {
            const wallSel = _customerStageAuto(c) ? '自动' : stage;
            return _CRM_STAGES.map(function (s) {
                return '<option value="' + esc(s) + '"' + (wallSel === s ? ' selected' : '') + '>' + esc(s) + '</option>';
            }).join('') + '<option value="自动"' + (wallSel === '自动' ? ' selected' : '') + '>' + esc(t('inquiry.stage_auto')) + '</option>';
        })() + '</select></label>' +
        '<label class="da-lbl">' + (currentLang === 'en' ? 'Follow-up' : '下次跟进') + ' <input type="date" id="wall-follow" value="' + esc(follow) + '"></label>' +
        '<button type="button" id="wall-stage-save">' + (currentLang === 'en' ? 'Save' : '保存') + '</button>' +
        '</div>' +
        statsHtml +
        '<div class="wall3">' +
        '<div class="col colL">' + peopleHtml + inqHtml + ordersHtml + '</div>' +
        '<div class="col colM">' + circleHtml + mailHtml + talksHtml + '</div>' +
        '<div class="col colR">' + prefsHtml + '</div>' +
        '</div>' +
        '<div class="wall-timeline">' + timelineHtml + '</div>' +
        '</div>';

    wall.classList.add('open');
    wall.removeAttribute('inert');
    wall.setAttribute('aria-hidden', 'false');
    document.body.classList.add('wall-open');
    const _tt = document.getElementById('app-top-title');
    const _tl = document.getElementById('app-top-lbl');
    if (_tt && _tl) {
        if (!wall._prevTop) wall._prevTop = { t: _tt.textContent, l: _tl.textContent };
        _tt.textContent = currentLang === 'en' ? 'Customer' : '客户详情';
        _tl.textContent = '/ ASSET PROFILE';
    }
    $('wall-back')?.focus();
    // 单一币种才数字滚动；多币种已在上方直接列出各币种金额
    if (hasAmount && !multiCurrency) {
        _wallAnimateCount($('wall-stat-total'), orderTotal, orderCurrency);
    }

    $('wall-back')?.addEventListener('click', closeCustomerWall);
    $('wall-edit')?.addEventListener('click', function () { closeCustomerWall(); showCustomerDetail(cid); });
    $('wall-open-profile')?.addEventListener('click', function () { openCustomerProfile(cid); });
    $('wall-add-order')?.addEventListener('click', function () { showOrderModal(cid); });
    _bindProfileCardActions(cid, wall, mailboxBound, function () {
        return _refreshProfileSections(cid, wall, people, mailboxBound);
    }, people);
    $('wall-add-contact')?.addEventListener('click', function () {
        _showContactModal(cid, null);
    });
    wall.querySelectorAll('.wall-edit-primary').forEach(function (a) {
        a.addEventListener('click', function (e) {
            e.preventDefault();
            closeCustomerWall();
            showCustomerEditModal(cid);
        });
    });
    // 双击重要对话标题 → 改 title/summary
    wall.querySelectorAll('.wall-talk-title').forEach(function (el) {
        el.addEventListener('dblclick', async function () {
            const card = el.closest('[data-conv-id]');
            const convId = card && card.getAttribute('data-conv-id');
            if (!convId) return;
            const curTitle = el.textContent || '';
            // 摘要默认值取库里真实 summary，不取卡片兜底显示的 AI 回复片段
            const curSummary = card ? (card.getAttribute('data-conv-summary') || '') : '';
            const title = window.prompt(
                currentLang === 'en' ? 'Talk title (max 60)' : '对话标题（最多 60 字）',
                curTitle
            );
            if (title == null) return;
            const summary = window.prompt(
                currentLang === 'en' ? 'Talk summary (max 200)' : '对话摘要（最多 200 字）',
                curSummary
            );
            if (summary == null) return;
            // 拼接而非模板插值：convId 来自 dataset 的整数 id；xss-guard 只认可转义插值
            const r = await api('PUT', '/api/trade/conversations/' + convId + '/note', {
                title: title.trim(), summary: summary.trim(),
            });
            if (!r) return;
            el.textContent = title.trim() || curTitle;
            if (sumEl) sumEl.textContent = summary.trim() || curSummary;
            toast(currentLang === 'en' ? 'Saved' : '已保存');
        });
    });
    wall.querySelectorAll('.wall-edit-contact').forEach(function (a) {
        a.addEventListener('click', function (e) {
            e.preventDefault();
            const id = parseInt(a.getAttribute('data-id'), 10);
            const person = people.find(function (p) { return p.id === id; });
            _showContactModal(cid, person || { id: id });
        });
    });
    wall.querySelectorAll('.wall-del-contact').forEach(function (a) {
        a.addEventListener('click', async function (e) {
            e.preventDefault();
            const id = parseInt(a.getAttribute('data-id'), 10);
            const nm = a.getAttribute('data-name') || '';
            if (!confirm(t('contacts.delete_confirm').replace('{name}', nm))) return;
            const r = await api('DELETE', `/api/trade/customers/${cid}/contacts/${id}`);
            if (!r || !r.ok) return;
            toast(t('contacts.deleted'));
            openCustomerWall(cid);
        });
    });
    _bindWallTags(cid, wallTags);
    $('wall-stage-save')?.addEventListener('click', async function () {
        const nextStage = $('wall-stage')?.value || '询盘';
        const nextFollow = $('wall-follow')?.value || '';
        // stage 新语义：四值=override；「自动」=清 override
        const saved = await api('PUT', `/api/trade/customers/${cid}`, {
            stage: nextStage,
            next_follow_up_date: nextFollow,
        });
        if (!saved) return;
        if (cached) {
            cached.stage = saved.stage;
            cached.stage_auto = saved.stage_auto;
            cached.stage_override = saved.stage_override;
            cached.next_follow_up_date = saved.next_follow_up_date;
        }
        toast(t('toast.saved'));
        filterCustomers();
        openCustomerWall(cid);
    });
    $('wall-inq-create')?.addEventListener('click', async function () {
        const title = ($('wall-inq-title')?.value || '').trim();
        const st = $('wall-inq-stage-new')?.value || '询盘';
        const r = await api('POST', `/api/trade/customers/${cid}/inquiries`, {
            title: title, stage: st,
        });
        if (!r) return;
        toast(t('inquiry.created'));
        openCustomerWall(cid);
        filterCustomers();
    });
    wall.querySelectorAll('.wall-inq-stage').forEach(function (sel) {
        sel.addEventListener('change', async function () {
            const id = sel.getAttribute('data-id');
            const r = await api('PUT', '/api/trade/inquiries/' + id, { stage: sel.value });
            if (!r) return;
            toast(t('inquiry.updated'));
            openCustomerWall(cid);
            filterCustomers();
        });
    });
    wall.querySelectorAll('.wall-inq-del').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const id = btn.getAttribute('data-id');
            const r = await api('DELETE', '/api/trade/inquiries/' + id);
            if (!r || !r.ok) return;
            toast(t('inquiry.deleted'));
            openCustomerWall(cid);
            filterCustomers();
        });
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
            if (e.key !== 'Escape') return;
            // 画像页打开时由它自己的监听逐层关闭（画像 → 墙 → 列表）
            const profile = document.getElementById('customer-profile');
            if (profile && profile.classList.contains('open')) return;
            closeCustomerWall();
        });
    }
}

// 客户编辑两处 UI 的 ESC 关闭（编辑表单弹窗优先，其次侧滑详情面板）
let _custEditEscBound = false;
function _bindCustEditEsc() {
    if (_custEditEscBound) return;
    _custEditEscBound = true;
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        const modal = document.getElementById('customer-modal');
        if (modal && !modal.classList.contains('hidden')) { hideModal('customer-modal'); return; }
        if (document.getElementById('customer-detail-panel')) { closeCustomerDetail(); }
    });
}

// ── Customer Detail Slide Panel ────────────────────────────────
async function showCustomerDetail(cid) {
    _bindCustEditEsc();
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
        <div class="slide-panel-content">
        <div class="slide-panel-main">
        <div class="panel-section panel-basic">
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
        </div>
        <div class="slide-panel-side">
        <div class="panel-section panel-libs">
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
        <div class="panel-section panel-orders">
            <div class="panel-section-title">${t('customer.detail.orders')} (<span id="detail-order-count">-</span>) <button class="btn-xs" style="margin-left:8px;" onclick="showOrderModal(${c.id})">${t('customer.detail.add_order')}</button></div>
            <div id="detail-orders"><div class="loading-row"><div class="spinner"></div>${t('misc.loading_orders')}</div></div>
        </div>
        <div class="panel-section panel-convs">
            <div class="panel-section-title">${t('customer.detail.convs')} (${recentConvs.length})</div>
            <div id="detail-convs">
                ${recentConvs.length ? recentConvs.map(conv => `
                <div class="panel-conv-item" onclick="closeCustomerDetail();showConversationDetail(${conv.id})">
                    <div class="conv-time">${esc((conv.created_at||'').slice(0,16))}</div>
                    <div class="conv-query">${esc((conv.query||'').slice(0,80))}</div>
                </div>`).join('') : '<p style="color:var(--text-muted);font-size:12px;">'+t('customer.detail.no_convs')+'</p>'}
            </div>
        </div>
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
            '<div class="form-group"><label for="order-incoterm">'+t('order.incoterm')+'</label><input type="text" id="order-incoterm" placeholder="FOB / CIF"></div>' +
        '</div>' +
        '<div class="form-row">' +
            '<div class="form-group"><label for="order-port">'+t('order.port_loading')+'</label><input type="text" id="order-port" placeholder="'+t('order.port_ph')+'"></div>' +
            '<div class="form-group"><label for="order-container">'+t('order.container')+'</label><input type="text" id="order-container" placeholder="1×20GP"></div>' +
        '</div>' +
        '<div class="form-row">' +
            '<div class="form-group"><label for="order-lead-time">'+t('order.lead_time')+'</label><input type="text" id="order-lead-time" placeholder="'+t('order.lead_time_ph')+'"></div>' +
            '<div class="form-group"><label for="order-shipped-at">'+t('order.shipped_at')+'</label><input type="text" id="order-shipped-at" placeholder="'+t('order.shipped_ph')+'"></div>' +
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
            $('order-incoterm').value = o.incoterm||'';
            $('order-port').value = o.port_of_loading||'';
            $('order-container').value = o.container||'';
            $('order-lead-time').value = o.lead_time_text||'';
            $('order-shipped-at').value = o.shipped_at||'';
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
        incoterm: $('order-incoterm').value.trim(),
        port_of_loading: $('order-port').value.trim(),
        container: $('order-container').value.trim(),
        lead_time_text: $('order-lead-time').value.trim(),
        shipped_at: $('order-shipped-at').value.trim(),
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
        $('cust-function').value = extra2['function']||'其他';
        $('cust-responsibility').value = extra2['responsibility']||'';
        $('cust-country').value = extra1['country']||'';
        $('cust-city').value = extra1['city']||'';
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
        ['cust-name','cust-contact','cust-title','cust-responsibility','cust-country','cust-city','cust-email','cust-phone','cust-whatsapp','cust-linkedin','cust-website','cust-tier','cust-buyer-type','cust-main-category','cust-match-score','cust-backup-email','cust-note','cust-follow-up-note'].forEach(id => $(id).value='');
        if ($('cust-function')) $('cust-function').value = '其他';
    }
    _bindCustEditEsc();
    showModal('customer-modal');
}

async function saveCustomer() {
    const name = $('cust-name').value.trim();
    if (!name) { toast('请填写客户名称'); return; }
    const editId = $('cust-edit-id').value;
    const contact = ($('cust-contact')?.value?.trim() || '');
    const note = $('cust-note').value.trim();
    const country = $('cust-country').value.trim();
    const city = ($('cust-city')?.value || '').trim();
    const tier = $('cust-tier').value;
    const buyerType = $('cust-buyer-type').value;
    const mainCategory = $('cust-main-category').value.trim();
    const matchScore = parseInt($('cust-match-score').value) || 0;
    const linkedin = $('cust-linkedin').value.trim();
    const title = $('cust-title').value.trim();
    const functionVal = ($('cust-function')?.value || '其他').trim();
    const responsibility = ($('cust-responsibility')?.value || '').trim();
    const email = $('cust-email').value.trim();
    const phone = $('cust-phone').value.trim();
    const whatsapp = $('cust-whatsapp').value.trim();
    const website = $('cust-website').value.trim();
    const backupEmail = $('cust-backup-email').value.trim();
    const followUpNote = $('cust-follow-up-note').value.trim();

    const body = {name, contact, note, country, city, tier, linkedin_url: linkedin,
        title, function: functionVal, responsibility, email, phone, whatsapp,
        company_website: website, backup_email: backupEmail, buyer_type: buyerType,
        follow_up_note: followUpNote, main_category: mainCategory, match_score: matchScore};
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

// ── 附加联系人弹窗 + 墙内标签 ───────────────────────
function _renderWallTagChips(tags) {
    const box = $('wall-tags-chips');
    if (!box) return;
    box.innerHTML = (tags || []).map(function (tag, idx) {
        return '<span class="tagchip" data-tag-idx="' + idx + '">' + esc(tag) +
            ' <a href="#" class="wall-tag-x" data-idx="' + idx + '" style="margin-left:4px;">×</a></span>';
    }).join('') || ('<span class="muted">' + esc(t('contacts.tags_empty')) + '</span>');
}

function _bindWallTags(cid, initialTags) {
    let tags = (initialTags || []).slice();
    _renderWallTagChips(tags);

    async function persist() {
        const saved = await api('PUT', `/api/trade/customers/${cid}`, { tags: tags });
        if (!saved) return false;
        const cached = allCustomers.find(function (x) { return x.id === cid; });
        if (cached) {
            try {
                const e3 = JSON.parse(cached.extra3 || '{}');
                e3.tags = tags;
                cached.extra3 = JSON.stringify(e3);
            } catch (e) {
                cached.extra3 = JSON.stringify({ tags: tags });
            }
        }
        return true;
    }

    $('wall-tags-chips')?.addEventListener('click', async function (e) {
        const a = e.target.closest('.wall-tag-x');
        if (!a) return;
        e.preventDefault();
        const idx = parseInt(a.getAttribute('data-idx'), 10);
        if (isNaN(idx)) return;
        tags.splice(idx, 1);
        _renderWallTagChips(tags);
        await persist();
    });

    async function addFromInput() {
        const input = $('wall-tag-input');
        if (!input) return;
        const raw = String(input.value || '');
        const parts = raw.split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean);
        let changed = false;
        for (let i = 0; i < parts.length; i++) {
            const s = parts[i];
            if (Array.from(s).length > 20) {
                toast(t('contacts.tags_too_long'));
                continue;
            }
            const key = s.toLowerCase();
            if (tags.some(function (x) { return x.toLowerCase() === key; })) continue;
            if (tags.length >= 20) {
                toast(t('contacts.tags_too_many'));
                break;
            }
            tags.push(s);
            changed = true;
        }
        input.value = '';
        if (!changed) return;
        _renderWallTagChips(tags);
        await persist();
    }

    $('wall-tag-add')?.addEventListener('click', addFromInput);
    $('wall-tag-input')?.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            addFromInput();
        }
    });
}

function _showContactModal(cid, person) {
    document.querySelectorAll('.contact-modal-backdrop').forEach(function (el) { el.remove(); });
    const isEdit = !!(person && person.id);
    const p = person || {};
    const funcs = ['决策人', '财务', '仓储', '其他'];
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop contact-modal-backdrop';
    backdrop.style.cssText = 'display:flex;position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:9999;align-items:center;justify-content:center;';
    backdrop.innerHTML =
        '<div class="modal" style="max-width:420px;width:92%;background:var(--bg);padding:16px;border:1px solid var(--line-strong);">' +
        '<h3 style="margin:0 0 12px;">' + esc(isEdit ? t('contacts.edit_title') : t('contacts.add_title')) + '</h3>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('contacts.name')) +
        '<input id="c-name" style="width:100%;margin-top:2px;" value="' + esc(p.name || '') + '" /></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('contacts.function')) +
        '<select id="c-function" style="width:100%;margin-top:2px;">' +
        funcs.map(function (f) {
            return '<option value="' + esc(f) + '"' + ((p.function || '其他') === f ? ' selected' : '') + '>' + esc(f) + '</option>';
        }).join('') + '</select></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('contacts.title_f')) +
        '<input id="c-title" style="width:100%;margin-top:2px;" value="' + esc(p.title || '') + '" /></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('contacts.responsibility')) +
        '<input id="c-responsibility" style="width:100%;margin-top:2px;" value="' +
        esc(p.responsibility || '') + '" /></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('contacts.email')) +
        '<input id="c-email" style="width:100%;margin-top:2px;" value="' + esc(p.email || '') + '" /></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('contacts.phone')) +
        '<input id="c-phone" style="width:100%;margin-top:2px;" value="' + esc(p.phone || '') + '" /></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('contacts.whatsapp')) +
        '<input id="c-whatsapp" style="width:100%;margin-top:2px;" value="' + esc(p.whatsapp || '') + '" /></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('contacts.wechat')) +
        '<input id="c-wechat" style="width:100%;margin-top:2px;" value="' + esc(p.wechat || '') + '" /></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('contacts.note')) +
        '<input id="c-note" style="width:100%;margin-top:2px;" value="' + esc(p.note || '') + '" /></label>' +
        '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">' +
        '<button type="button" id="c-cancel">' + esc(t('btn.cancel')) + '</button>' +
        '<button type="button" class="primary" id="c-save">' + esc(t('btn.save')) + '</button>' +
        '</div></div>';
    document.body.appendChild(backdrop);
    backdrop.querySelector('#c-cancel').addEventListener('click', function () { backdrop.remove(); });
    backdrop.addEventListener('click', function (e) {
        if (e.target === backdrop) backdrop.remove();
    });
    backdrop.querySelector('#c-save').addEventListener('click', async function () {
        const body = {
            name: ($('c-name')?.value || '').trim(),
            function: $('c-function')?.value || '其他',
            title: ($('c-title')?.value || '').trim(),
            responsibility: ($('c-responsibility')?.value || '').trim(),
            email: ($('c-email')?.value || '').trim(),
            phone: ($('c-phone')?.value || '').trim(),
            whatsapp: ($('c-whatsapp')?.value || '').trim(),
            wechat: ($('c-wechat')?.value || '').trim(),
            note: ($('c-note')?.value || '').trim(),
        };
        if (!body.name) {
            toast(t('contacts.name_required'));
            return;
        }
        let saved;
        if (isEdit) {
            saved = await api('PUT', `/api/trade/customers/${cid}/contacts/${person.id}`, body);
        } else {
            saved = await api('POST', `/api/trade/customers/${cid}/contacts`, body);
        }
        if (!saved) return;
        backdrop.remove();
        toast(t('contacts.saved'));
        openCustomerWall(cid);
    });
}


// ═════════════════════ 客户画像卡片（墙内 + W12 复用）═════════════════════

const _PROFILE_CIRCLE_CATS = ['家庭', '其他供应商或竞品'];
const _PROFILE_PREFS_CATS = ['喜好', '禁忌', '重要日期'];

function _profilePersonLabel(item, people) {
    /** 挂人展示小字。 */
    const at = item.attach_to || 'none';
    if (at === 'primary') {
        const p = (people || []).find(function (x) { return x.id == null || x.is_primary; });
        const nm = p && p.name ? p.name : (currentLang === 'en' ? 'Primary' : '主联系人');
        return ' · ' + (currentLang === 'en' ? 'Primary ' : '主联系人 ') + nm;
    }
    if (at === 'contact' && item.contact_id != null) {
        const p = (people || []).find(function (x) { return x.id === item.contact_id; });
        return p && p.name ? (' · ' + p.name) : '';
    }
    return '';
}

const _PROFILE_ALL_CATS = ['家庭', '其他供应商或竞品', '喜好', '禁忌', '重要日期', '礼物往来'];
const _PROFILE_GIFT_DIRECTIONS = ['我方赠送', '客户赠送', '客户索要'];
// 编辑时用：卡片只渲染 HTML，编辑弹窗需要原始条目；按 kind:id 缓存最近一次 GET 的结果
const _PROFILE_ITEM_CACHE = {};

function _profileCacheItem(kind, item) {
    if (item && item.id != null) _PROFILE_ITEM_CACHE[kind + ':' + item.id] = item;
}

// #region profile-source
// 出处：来源类型 + 日期（source_at 由后端按 source_ref 推导，不落库）
function _profileSourceLabel(item) {
    const st = (item && item.source_type) || 'manual';
    if (st === 'chat') return t('profile.src_chat');
    if (st === 'email') return t('profile.src_email');
    if (st === 'visit') return t('profile.src_visit');
    return t('profile.src_manual');
}

function _profileSourceDate(item) {
    const s = String((item && item.source_at) || '').trim();
    return s ? s.slice(0, 10) : '';
}
// #endregion profile-source

// #region profile-attach
// 挂到下拉：不挂人 / 主联系人（有才出现）/ 每个附加联系人
function _profileAttachOptions(people) {
    const opts = [{ value: 'none', label: t('profile.attach_none') }];
    const list = people || [];
    const primary = list.find(function (p) { return p.id == null || p.is_primary; });
    if (primary) {
        opts.push({
            value: 'primary',
            label: t('profile.attach_primary', {
                name: primary.name || t('profile.attach_primary_default'),
            }),
        });
    }
    list.filter(function (p) { return p.id != null; }).forEach(function (p) {
        opts.push({ value: 'contact:' + p.id, label: p.name || t('profile.attach_contact_fallback') });
    });
    return opts;
}

function _profileAttachValue(item) {
    const at = item && item.attach_to;
    if (at === 'primary') return 'primary';
    if (at === 'contact' && item.contact_id != null) return 'contact:' + item.contact_id;
    return 'none';
}

function _profileAttachBody(value) {
    if (value === 'primary') return { attach_to: 'primary', contact_id: null };
    if (String(value || '').indexOf('contact:') === 0) {
        const id = parseInt(String(value).slice(8), 10);
        if (!isNaN(id)) return { attach_to: 'contact', contact_id: id };
    }
    return { attach_to: 'none', contact_id: null };
}

function _profileAttachSelectHtml(id, people, selected) {
    return '<select id="' + esc(id) + '" style="width:100%;margin-top:2px;">' +
        _profileAttachOptions(people).map(function (o) {
            return '<option value="' + esc(o.value) + '"' + (o.value === selected ? ' selected' : '') + '>' +
                esc(o.label) + '</option>';
        }).join('') + '</select>';
}
// #endregion profile-attach

function _profileFactCardsHtml(items, people, delayFn) {
    /** 已确认事实卡片 HTML。 */
    let html = '';
    (items || []).forEach(function (f) {
        _profileCacheItem('fact', f);
        const src = _profileSourceLabel(f);
        const srcDate = _profileSourceDate(f);
        html += '<article class="wcard profile-fact"' + delayFn() + ' data-fact-id="' + esc(String(f.id)) + '">' +
            '<div class="wc-name">' + esc(f.subject || f.category) +
            '<span class="muted">' + esc(_profilePersonLabel(f, people)) + '</span></div>' +
            '<p>' + esc(f.content || '') + '</p>' +
            '<p class="muted profile-src">' + esc(src) + (srcDate ? ' · ' + esc(srcDate) : '') +
            (f.source_quote ? (' · <a href="#" class="profile-toggle-quote">' + t('profile.show_quote') + '</a>') : '') +
            '</p>' +
            (f.source_quote ? ('<p class="profile-quote muted" hidden>' + esc(f.source_quote) + '</p>') : '') +
            '<p class="muted"><a href="#" class="profile-edit-fact">' + t('profile.edit') + '</a> · ' +
            '<a href="#" class="profile-void-fact">' + t('profile.void') + '</a>' +
            (f.source_type === 'manual' ? (' · <a href="#" class="profile-del-fact">' + t('profile.delete') + '</a>') : '') +
            ' · <label class="profile-ai-lab"><input type="checkbox" class="profile-ai-vis"' +
            (f.ai_visible ? ' checked' : '') + '> ' + t('profile.ai_use') + '</label></p>' +
            '</article>';
    });
    return html;
}

function _profilePendingHtml(items, kind) {
    /** 待确认小字列表。 */
    const pending = (items || []).filter(function (x) { return x.status === '待确认'; });
    if (!pending.length) return '';
    let html = '<div class="profile-pending muted">';
    pending.forEach(function (f) {
        const q = (f.source_quote || f.content || '').slice(0, 40);
        const idAttr = kind === 'gift' ? ('data-gift-id="' + esc(String(f.id)) + '"') : ('data-fact-id="' + esc(String(f.id)) + '"');
        html += '<div ' + idAttr + '>' + esc(q) +
            ' · <a href="#" class="profile-confirm-' + kind + '">' + t('profile.confirm') + '</a>' +
            ' · <a href="#" class="profile-void-' + kind + '">' + t('profile.void') + '</a></div>';
    });
    html += '</div>';
    return html;
}

function renderProfileCircleSection(cid, factsPayload, people, delayFn, mailboxBound) {
    /** 「人物圈」区块 HTML。 */
    const avail = !!(factsPayload && factsPayload.available);
    const items = avail ? (factsPayload.items || []) : [];
    const confirmed = items.filter(function (f) {
        return f.status === '已确认' && _PROFILE_CIRCLE_CATS.indexOf(f.category) >= 0;
    });
    // 按挂人分组：primary → contact id → none
    confirmed.sort(function (a, b) {
        const ra = a.attach_to === 'primary' ? 0 : (a.attach_to === 'contact' ? 1 : 2);
        const rb = b.attach_to === 'primary' ? 0 : (b.attach_to === 'contact' ? 1 : 2);
        if (ra !== rb) return ra - rb;
        return (a.contact_id || 0) - (b.contact_id || 0);
    });
    let html = '<div class="wsec profile-circle" data-cid="' + cid + '"><div class="wsec-head"><h4>' +
        t('profile.circle') + '</h4><span class="cnt">CIRCLE // ' + confirmed.length +
        '</span><span class="ddline" aria-hidden="true"></span></div>';
    html += '<div style="margin:-4px 0 8px;display:flex;gap:8px;flex-wrap:wrap;">' +
        '<button type="button" class="btn-xs profile-add-fact" data-cats="circle">' + t('profile.add') + '</button>' +
        '<button type="button" class="btn-xs profile-extract-chat">' + t('profile.extract_chat') + '</button>' +
        (mailboxBound ? ('<button type="button" class="btn-xs profile-extract-email">' + t('profile.extract_email') + '</button>') : '') +
        '</div><div class="wgrid">';
    if (!avail) {
        html += '<div class="wall-empty"' + delayFn() + '>' + t('profile.restart') + '</div>';
    } else if (!confirmed.length) {
        html += '<div class="wall-empty"' + delayFn() + '>' + t('profile.empty_circle') + '</div>';
    } else {
        html += _profileFactCardsHtml(confirmed, people, delayFn);
    }
    html += '</div>';
    if (avail) html += _profilePendingHtml(items.filter(function (f) {
        return _PROFILE_CIRCLE_CATS.indexOf(f.category) >= 0;
    }), 'fact');
    html += '</div>';
    return html;
}

function renderProfilePrefsSection(cid, factsPayload, giftsPayload, people, delayFn, mailboxBound) {
    /** 「喜好禁忌与往来」区块 HTML。 */
    const fAvail = !!(factsPayload && factsPayload.available);
    const gAvail = !!(giftsPayload && giftsPayload.available);
    const facts = fAvail ? (factsPayload.items || []) : [];
    const gifts = gAvail ? (giftsPayload.items || []) : [];
    const confirmedFacts = facts.filter(function (f) {
        return f.status === '已确认' && _PROFILE_PREFS_CATS.indexOf(f.category) >= 0;
    });
    const confirmedGifts = gifts.filter(function (g) { return g.status === '已确认'; });
    const n = confirmedFacts.length + confirmedGifts.length;
    let html = '<div class="wsec profile-prefs" data-cid="' + cid + '"><div class="wsec-head"><h4>' +
        t('profile.prefs') + '</h4><span class="cnt">PREFS // ' + n +
        '</span><span class="ddline" aria-hidden="true"></span></div>';
    html += '<div style="margin:-4px 0 8px;display:flex;gap:8px;flex-wrap:wrap;">' +
        '<button type="button" class="btn-xs profile-add-fact" data-cats="prefs">' + t('profile.add') + '</button>' +
        '<button type="button" class="btn-xs profile-add-gift">' + t('profile.add_gift') + '</button>' +
        '<button type="button" class="btn-xs profile-extract-chat">' + t('profile.extract_chat') + '</button>' +
        (mailboxBound ? ('<button type="button" class="btn-xs profile-extract-email">' + t('profile.extract_email') + '</button>') : '') +
        '</div><div class="wgrid">';
    if (!fAvail && !gAvail) {
        html += '<div class="wall-empty"' + delayFn() + '>' + t('profile.restart') + '</div>';
    } else if (!n) {
        html += '<div class="wall-empty"' + delayFn() + '>' + t('profile.empty_prefs') + '</div>';
    } else {
        html += _profileFactCardsHtml(confirmedFacts, people, delayFn);
        confirmedGifts.forEach(function (g) {
            _profileCacheItem('gift', g);
            const isAsk = g.direction === '客户索要';
            const gDate = _profileSourceDate(g);
            html += '<article class="wcard profile-gift"' + delayFn() + ' data-gift-id="' + esc(String(g.id)) + '">' +
                '<div class="wc-name">' + (isAsk ? ('⚠ ' + t('profile.ask') + ' · ') : '') +
                esc(g.direction || '') + ' · ' + esc(g.item || '') +
                '<span class="muted">' + esc(_profilePersonLabel(g, people)) + '</span></div>' +
                (g.occasion || g.gift_date
                    ? ('<p class="muted">' + esc([g.gift_date, g.occasion].filter(Boolean).join(' · ')) + '</p>')
                    : '') +
                '<p class="muted profile-src">' + esc(_profileSourceLabel(g)) +
                (gDate ? ' · ' + esc(gDate) : '') +
                (g.source_quote ? (' · <a href="#" class="profile-toggle-quote">' + t('profile.show_quote') + '</a>') : '') +
                '</p>' +
                (g.source_quote ? ('<p class="profile-quote muted" hidden>' + esc(g.source_quote) + '</p>') : '') +
                '<p class="muted"><a href="#" class="profile-edit-gift">' + t('profile.edit') + '</a> · ' +
                '<a href="#" class="profile-void-gift">' + t('profile.void') + '</a>' +
                (g.source_type === 'manual' ? (' · <a href="#" class="profile-del-gift">' + t('profile.delete') + '</a>') : '') +
                (isAsk ? '' : (' · <label class="profile-ai-lab"><input type="checkbox" class="profile-ai-vis-gift"' +
                    (g.ai_visible ? ' checked' : '') + '> ' + t('profile.ai_use') + '</label>')) +
                '</p></article>';
        });
    }
    html += '</div>';
    if (fAvail) html += _profilePendingHtml(facts.filter(function (f) {
        return _PROFILE_PREFS_CATS.indexOf(f.category) >= 0;
    }), 'fact');
    if (gAvail) html += _profilePendingHtml(gifts, 'gift');
    html += '</div>';
    return html;
}

async function _refreshProfileSections(cid, root, people, mailboxBound) {
    /** 只刷新两张画像区块，不整墙重载（确认/作废/编辑后调用）。 */
    if (!root) return;
    const [factsRes, giftsRes] = await Promise.all([
        api('GET', `/api/trade/customers/${cid}/facts`),
        api('GET', `/api/trade/customers/${cid}/gifts`),
    ]);
    // 两个都失败时保留现状（api() 已 toast），不要把区块替换成「重启后可用」
    if (!factsRes && !giftsRes) return;
    const factsPayload = (factsRes && typeof factsRes === 'object')
        ? factsRes : { available: false, items: [] };
    const giftsPayload = (giftsRes && typeof giftsRes === 'object')
        ? giftsRes : { available: false, items: [] };
    const noDelay = function () { return ''; };
    const circle = root.querySelector('.profile-circle');
    const prefs = root.querySelector('.profile-prefs');
    if (circle) {
        circle.outerHTML = renderProfileCircleSection(cid, factsPayload, people || [], noDelay, mailboxBound);
    }
    if (prefs) {
        prefs.outerHTML = renderProfilePrefsSection(
            cid, factsPayload, giftsPayload, people || [], noDelay, mailboxBound
        );
    }
    _bindProfileCardActions(cid, root, mailboxBound, function () {
        return _refreshProfileSections(cid, root, people, mailboxBound);
    }, people);
}

function _bindProfileCardActions(cid, root, mailboxBound, refreshFn, people) {
    /** 绑定画像卡上的确认/作废/提取等操作。 */
    if (!root) return;
    root.querySelectorAll('.profile-toggle-quote').forEach(function (a) {
        a.addEventListener('click', function (e) {
            e.preventDefault();
            const q = a.closest('.wcard')?.querySelector('.profile-quote');
            if (q) q.hidden = !q.hidden;
        });
    });
    root.querySelectorAll('.profile-edit-fact').forEach(function (a) {
        a.addEventListener('click', function (e) {
            e.preventDefault();
            const id = a.closest('[data-fact-id]')?.getAttribute('data-fact-id');
            const item = _PROFILE_ITEM_CACHE['fact:' + id];
            if (!item) return;
            _showProfileFactModal(cid, _PROFILE_ALL_CATS, {
                item: item, people: people, onSaved: refresh,
            });
        });
    });
    root.querySelectorAll('.profile-edit-gift').forEach(function (a) {
        a.addEventListener('click', function (e) {
            e.preventDefault();
            const id = a.closest('[data-gift-id]')?.getAttribute('data-gift-id');
            const item = _PROFILE_ITEM_CACHE['gift:' + id];
            if (!item) return;
            _showProfileGiftModal(cid, {
                item: item, people: people, onSaved: refresh,
            });
        });
    });
    async function refresh() {
        if (typeof refreshFn === 'function') refreshFn();
        else openCustomerWall(cid);
    }
    root.querySelectorAll('.profile-confirm-fact').forEach(function (a) {
        a.addEventListener('click', async function (e) {
            e.preventDefault();
            const id = a.closest('[data-fact-id]')?.getAttribute('data-fact-id');
            if (!id) return;
            const r = await api('POST', `/api/trade/customers/${cid}/facts/${id}/confirm`);
            if (r) { toast(t('profile.confirmed')); refresh(); }
        });
    });
    root.querySelectorAll('.profile-void-fact').forEach(function (a) {
        a.addEventListener('click', async function (e) {
            e.preventDefault();
            const id = a.closest('[data-fact-id]')?.getAttribute('data-fact-id');
            if (!id) return;
            const r = await api('POST', `/api/trade/customers/${cid}/facts/${id}/void`);
            if (r) refresh();
        });
    });
    root.querySelectorAll('.profile-del-fact').forEach(function (a) {
        a.addEventListener('click', async function (e) {
            e.preventDefault();
            if (!confirm(t('profile.delete_confirm'))) return;
            const id = a.closest('[data-fact-id]')?.getAttribute('data-fact-id');
            if (!id) return;
            const r = await api('DELETE', `/api/trade/customers/${cid}/facts/${id}`);
            if (r) refresh();
        });
    });
    root.querySelectorAll('.profile-ai-vis').forEach(function (inp) {
        inp.addEventListener('change', async function () {
            const id = inp.closest('[data-fact-id]')?.getAttribute('data-fact-id');
            if (!id) return;
            await api('PUT', `/api/trade/customers/${cid}/facts/${id}`, { ai_visible: inp.checked ? 1 : 0 });
        });
    });
    root.querySelectorAll('.profile-confirm-gift').forEach(function (a) {
        a.addEventListener('click', async function (e) {
            e.preventDefault();
            const id = a.closest('[data-gift-id]')?.getAttribute('data-gift-id');
            if (!id) return;
            const r = await api('POST', `/api/trade/customers/${cid}/gifts/${id}/confirm`);
            if (r) { toast(t('profile.confirmed')); refresh(); }
        });
    });
    root.querySelectorAll('.profile-void-gift').forEach(function (a) {
        a.addEventListener('click', async function (e) {
            e.preventDefault();
            const id = a.closest('[data-gift-id]')?.getAttribute('data-gift-id');
            if (!id) return;
            const r = await api('POST', `/api/trade/customers/${cid}/gifts/${id}/void`);
            if (r) refresh();
        });
    });
    root.querySelectorAll('.profile-del-gift').forEach(function (a) {
        a.addEventListener('click', async function (e) {
            e.preventDefault();
            if (!confirm(t('profile.delete_confirm'))) return;
            const id = a.closest('[data-gift-id]')?.getAttribute('data-gift-id');
            if (!id) return;
            const r = await api('DELETE', `/api/trade/customers/${cid}/gifts/${id}`);
            if (r) refresh();
        });
    });
    root.querySelectorAll('.profile-ai-vis-gift').forEach(function (inp) {
        inp.addEventListener('change', async function () {
            const id = inp.closest('[data-gift-id]')?.getAttribute('data-gift-id');
            if (!id) return;
            await api('PUT', `/api/trade/customers/${cid}/gifts/${id}`, { ai_visible: inp.checked ? 1 : 0 });
        });
    });
    root.querySelectorAll('.profile-extract-chat').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            btn.disabled = true;
            const r = await api('POST', `/api/trade/customers/${cid}/facts/extract`, { source: 'chat', limit: 20 });
            btn.disabled = false;
            if (!r) return;
            toast(t('profile.extract_done', {
                f: r.added_facts || 0, g: r.added_gifts || 0, d: r.dropped_invalid || 0,
            }));
            refresh();
        });
    });
    root.querySelectorAll('.profile-extract-email').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            btn.disabled = true;
            const r = await api('POST', `/api/trade/customers/${cid}/facts/extract`, { source: 'email', limit: 20 });
            btn.disabled = false;
            if (!r) return;
            toast(t('profile.extract_done', {
                f: r.added_facts || 0, g: r.added_gifts || 0, d: r.dropped_invalid || 0,
            }));
            refresh();
        });
    });
    root.querySelectorAll('.profile-add-fact').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const mode = btn.getAttribute('data-cats') || 'prefs';
            const cats = mode === 'circle' ? _PROFILE_CIRCLE_CATS : _PROFILE_PREFS_CATS;
            _showProfileFactModal(cid, cats, { people: people, onSaved: refresh });
        });
    });
    root.querySelectorAll('.profile-add-gift').forEach(function (btn) {
        btn.addEventListener('click', function () {
            _showProfileGiftModal(cid, { people: people, onSaved: refresh });
        });
    });
}

function _showProfileFactModal(cid, cats, opts) {
    /** 添加 / 编辑事实弹窗：分类、对象、内容 + 挂到下拉。 */
    const o = opts || {};
    const item = o.item || null;
    const people = o.people || [];
    const onSaved = typeof o.onSaved === 'function'
        ? o.onSaved : function () { openCustomerWall(cid); };
    document.querySelectorAll('.profile-modal-backdrop').forEach(function (el) { el.remove(); });
    const catList = [];
    (cats || []).forEach(function (c) { if (catList.indexOf(c) < 0) catList.push(c); });
    if (item && item.category && catList.indexOf(item.category) < 0) catList.push(item.category);
    const curCat = (item && item.category) || catList[0] || '喜好';
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop profile-modal-backdrop';
    backdrop.style.cssText = 'display:flex;position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:9999;align-items:center;justify-content:center;';
    backdrop.innerHTML =
        '<div class="modal" style="max-width:460px;width:92%;background:var(--bg);padding:16px;border:1px solid var(--line-strong);">' +
        '<h3 style="margin:0 0 12px;">' + esc(item ? t('profile.edit_fact') : t('profile.add_fact')) + '</h3>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('profile.category')) +
        '<select id="pf-category" style="width:100%;margin-top:2px;">' +
        catList.map(function (c) {
            return '<option value="' + esc(c) + '"' + (c === curCat ? ' selected' : '') + '>' +
                esc(c) + '</option>';
        }).join('') + '</select></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('profile.subject')) +
        '<input id="pf-subject" maxlength="50" style="width:100%;margin-top:2px;" value="' +
        esc((item && item.subject) || '') + '" /></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('profile.content')) +
        '<textarea id="pf-content" maxlength="500" style="width:100%;margin-top:2px;min-height:80px;">' +
        esc((item && item.content) || '') + '</textarea></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('profile.attach')) +
        _profileAttachSelectHtml('pf-attach', people, _profileAttachValue(item)) + '</label>' +
        '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">' +
        '<button type="button" id="pf-cancel">' + esc(t('btn.cancel')) + '</button>' +
        '<button type="button" class="primary" id="pf-save">' + esc(t('btn.save')) + '</button>' +
        '</div></div>';
    document.body.appendChild(backdrop);
    backdrop.querySelector('#pf-cancel').addEventListener('click', function () { backdrop.remove(); });
    backdrop.addEventListener('click', function (e) {
        if (e.target === backdrop) backdrop.remove();
    });
    backdrop.querySelector('#pf-save').addEventListener('click', async function () {
        const body = Object.assign({
            category: backdrop.querySelector('#pf-category').value,
            subject: (backdrop.querySelector('#pf-subject').value || '').trim(),
            content: (backdrop.querySelector('#pf-content').value || '').trim(),
        }, _profileAttachBody(backdrop.querySelector('#pf-attach').value));
        if (!body.content) {
            toast(t('profile.content_required'));
            return;
        }
        const r = item
            ? await api('PUT', `/api/trade/customers/${cid}/facts/${item.id}`, body)
            : await api('POST', `/api/trade/customers/${cid}/facts`, body);
        if (!r) return;
        backdrop.remove();
        toast(t('profile.saved'));
        onSaved();
    });
}

function _showProfileGiftModal(cid, opts) {
    /** 添加 / 编辑礼物弹窗：方向、物品、金额、币种、日期、场合、备注 + 挂到下拉。 */
    const o = opts || {};
    const item = o.item || null;
    const people = o.people || [];
    const onSaved = typeof o.onSaved === 'function'
        ? o.onSaved : function () { openCustomerWall(cid); };
    document.querySelectorAll('.profile-modal-backdrop').forEach(function (el) { el.remove(); });
    const curDir = (item && item.direction) || _PROFILE_GIFT_DIRECTIONS[0];
    const curVal = (item && item.approx_value != null) ? String(item.approx_value) : '';
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop profile-modal-backdrop';
    backdrop.style.cssText = 'display:flex;position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:9999;align-items:center;justify-content:center;';
    backdrop.innerHTML =
        '<div class="modal" style="max-width:460px;width:92%;background:var(--bg);padding:16px;border:1px solid var(--line-strong);">' +
        '<h3 style="margin:0 0 12px;">' + esc(item ? t('profile.gift_edit_title') : t('profile.gift_add_title')) + '</h3>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('profile.direction')) +
        '<select id="pg-direction" style="width:100%;margin-top:2px;">' +
        _PROFILE_GIFT_DIRECTIONS.map(function (d) {
            return '<option value="' + esc(d) + '"' + (d === curDir ? ' selected' : '') + '>' +
                esc(d) + '</option>';
        }).join('') + '</select></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('profile.item')) +
        '<input id="pg-item" maxlength="200" style="width:100%;margin-top:2px;" value="' +
        esc((item && item.item) || '') + '" /></label>' +
        '<div style="display:flex;gap:8px;">' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;flex:1;">' + esc(t('profile.approx_value')) +
        '<input id="pg-value" type="number" min="0" step="0.01" style="width:100%;margin-top:2px;" value="' +
        esc(curVal) + '" /></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;width:110px;">' + esc(t('profile.currency')) +
        '<input id="pg-currency" maxlength="3" placeholder="USD" style="width:100%;margin-top:2px;" value="' +
        esc((item && item.currency) || '') + '" /></label></div>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('profile.gift_date')) +
        '<input id="pg-date" type="date" style="width:100%;margin-top:2px;" value="' +
        esc((item && item.gift_date) || '') + '" /></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('profile.occasion')) +
        '<input id="pg-occasion" maxlength="100" style="width:100%;margin-top:2px;" value="' +
        esc((item && item.occasion) || '') + '" /></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('profile.note')) +
        '<textarea id="pg-note" maxlength="500" style="width:100%;margin-top:2px;min-height:60px;">' +
        esc((item && item.note) || '') + '</textarea></label>' +
        '<label style="display:block;font-size:12px;margin-bottom:6px;">' + esc(t('profile.attach')) +
        _profileAttachSelectHtml('pg-attach', people, _profileAttachValue(item)) + '</label>' +
        '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">' +
        '<button type="button" id="pg-cancel">' + esc(t('btn.cancel')) + '</button>' +
        '<button type="button" class="primary" id="pg-save">' + esc(t('btn.save')) + '</button>' +
        '</div></div>';
    document.body.appendChild(backdrop);
    backdrop.querySelector('#pg-cancel').addEventListener('click', function () { backdrop.remove(); });
    backdrop.addEventListener('click', function (e) {
        if (e.target === backdrop) backdrop.remove();
    });
    backdrop.querySelector('#pg-save').addEventListener('click', async function () {
        const rawVal = (backdrop.querySelector('#pg-value').value || '').trim();
        let approx = null;
        if (rawVal) {
            approx = Number(rawVal);
            if (!isFinite(approx) || approx < 0) {
                toast(t('profile.invalid_amount'));
                return;
            }
        }
        const body = Object.assign({
            direction: backdrop.querySelector('#pg-direction').value,
            item: (backdrop.querySelector('#pg-item').value || '').trim(),
            approx_value: approx,
            currency: (backdrop.querySelector('#pg-currency').value || '').trim().toUpperCase(),
            gift_date: (backdrop.querySelector('#pg-date').value || '').trim(),
            occasion: (backdrop.querySelector('#pg-occasion').value || '').trim(),
            note: (backdrop.querySelector('#pg-note').value || '').trim(),
        }, _profileAttachBody(backdrop.querySelector('#pg-attach').value));
        if (!body.item) {
            toast(t('profile.item_required'));
            return;
        }
        const r = item
            ? await api('PUT', `/api/trade/customers/${cid}/gifts/${item.id}`, body)
            : await api('POST', `/api/trade/customers/${cid}/gifts`, body);
        if (!r) return;
        backdrop.remove();
        toast(t('profile.saved'));
        onSaved();
    });
}

// ── W12 独立画像页 ──────────────────────────────────────────────────────────

let _profileEscHandler = null;

function closeCustomerProfile() {
    /** 关闭画像页，回到卡片墙。 */
    const panel = $('customer-profile');
    if (!panel) return;
    panel.classList.remove('open');
    panel.setAttribute('inert', '');
    panel.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('profile-open');
    // 恢复打开前的顶栏标题
    const tt = document.getElementById('app-top-title');
    const tl = document.getElementById('app-top-lbl');
    if (tt && tl && panel._prevTop) {
        tt.textContent = panel._prevTop.t;
        tl.textContent = panel._prevTop.l;
        panel._prevTop = null;
    }
    if (_profileEscHandler) {
        document.removeEventListener('keydown', _profileEscHandler);
        _profileEscHandler = null;
    }
}

async function openCustomerProfile(cid) {
    /** W12：独立画像页（两栏 dossier；窄屏单列）。 */
    const panel = $('customer-profile');
    if (!panel) return;
    const [ov, factsRes, giftsRes, mailboxRes] = await Promise.all([
        api('GET', `/api/trade/customers/${cid}/overview`),
        api('GET', `/api/trade/customers/${cid}/facts`),
        api('GET', `/api/trade/customers/${cid}/gifts`),
        api('GET', '/api/trade/mailboxes'),
    ]);
    if (!ov || !ov.customer) {
        toast(currentLang === 'en' ? 'Failed to load profile' : '加载客户画像失败');
        return;
    }
    const c = ov.customer;
    const e1 = _parseExtra1(c);
    const people = ov.people || [];
    const mailboxBound = (Array.isArray(mailboxRes) ? mailboxRes : []).length > 0;
    const factsPayload = (factsRes && typeof factsRes === 'object') ? factsRes : { available: false, items: [] };
    const giftsPayload = (giftsRes && typeof giftsRes === 'object') ? giftsRes : { available: false, items: [] };
    let seq = 0;
    function delay() { return ' style="animation-delay:' + ((seq++) * 0.05).toFixed(2) + 's"'; }

    // people-strip（s4：人物卡，带 ASSET·职能 标签 / 职务 / 邮箱电话 / 编辑删除）
    let strip = '<div class="profile-people">';
    people.forEach(function (p) {
        const isPrimary = !!p.is_primary || p.id == null;
        const ini = String(p.name || '?').trim().slice(0, 2).toUpperCase();
        const role = [(p.title || '').trim(), (p.responsibility || '').trim()].filter(Boolean).join(' · ') || p.function || '';
        const fn = p.function || (isPrimary ? '决策人' : '其他');
        const acts = isPrimary
            ? '<a href="#" class="lnk pf-edit-primary">' + t('contacts.edit') + '</a>'
            : ('<a href="#" class="lnk pf-edit-contact" data-id="' + esc(String(p.id)) + '">' + t('contacts.edit') + '</a>' +
                '<a href="#" class="lnk pf-del-contact" data-id="' + esc(String(p.id)) + '" data-name="' + esc(p.name || '') + '">' + t('contacts.delete') + '</a>');
        const kv = [];
        if (p.email) kv.push('<span class="k">EMAIL</span><span class="v mono">' + esc(p.email) + '</span>');
        const phone = [p.phone, p.whatsapp ? 'WA ' + p.whatsapp : '', p.wechat ? 'WeChat ' + p.wechat : ''].filter(Boolean).join(' · ');
        if (phone) kv.push('<span class="k">PHONE</span><span class="v mono">' + esc(phone) + '</span>');
        strip += '<div class="pf-card" data-contact-id="' + (p.id != null ? esc(String(p.id)) : '') + '">' +
            '<span class="p-tag' + (isPrimary ? '' : ' o') + '">ASSET · ' + esc(fn) + '</span>' +
            '<div class="row1"><span class="avatar">' + esc(ini) + '</span><div>' +
            '<div class="nm">' + esc(p.name || '') + (isPrimary ? '<span class="zhu">主</span>' : '') + '</div>' +
            '<div class="role">' + esc(role) + '</div></div>' +
            '<span class="p-acts">' + acts + '</span></div>' +
            (kv.length ? '<div class="kv">' + kv.join('') + '</div>' : '') +
            '</div>';
    });
    if (!people.length) strip += '<div class="wall-empty">' + t('contacts.empty') + '</div>';
    strip += '</div>';

    const left = renderProfileCircleSection(cid, factsPayload, people, delay, mailboxBound);
    const right = renderProfilePrefsSection(cid, factsPayload, giftsPayload, people, delay, mailboxBound);

    panel.innerHTML =
        '<div class="wall-head">' +
        '<button type="button" class="wall-back" id="profile-back">' + t('profile.back_wall') + ' <kbd>ESC</kbd></button>' +
        '<div class="wall-title bracket"><div><h3>' + esc(c.name) + '</h3>' +
        '<div class="facts2">' +
        (e1.tier ? '<span class="tagchip">TIER ' + esc(String(e1.tier)) + '</span>' : '') +
        (_parseExtra3(c).tags || []).map(function (tag) {
            return '<span class="chip">' + esc(tag) + '</span>';
        }).join('') +
        '<span class="star ' + (c.is_starred ? 'on' : 'off') + '">★</span>' +
        '</div>' +
        '<div class="sub">' + esc([e1.country, e1.city, e1.buyer_type].filter(Boolean).join(' · ') || t('profile.title')) +
        '</div></div></div></div>' +
        '<div class="wall-scroll profile-dossier">' + strip +
        '<div class="profile-cols">' + left + right + '</div></div>';

    panel.classList.add('open');
    panel.removeAttribute('inert');
    panel.setAttribute('aria-hidden', 'false');
    document.body.classList.add('profile-open');
    const _pt = document.getElementById('app-top-title');
    const _pl = document.getElementById('app-top-lbl');
    if (_pt && _pl) {
        if (!panel._prevTop) panel._prevTop = { t: _pt.textContent, l: _pl.textContent };
        _pt.textContent = currentLang === 'en' ? 'Profile' : '客户画像';
        _pl.textContent = '/ ASSET DOSSIER';
    }
    // 画像页人物卡：编辑主联系人 / 编辑附加联系人 / 删除附加联系人
    panel.querySelectorAll('.pf-edit-primary').forEach(function (a) {
        a.addEventListener('click', function (e) { e.preventDefault(); showCustomerEditModal(cid); });
    });
    panel.querySelectorAll('.pf-edit-contact').forEach(function (a) {
        a.addEventListener('click', function (e) {
            e.preventDefault();
            const id = parseInt(a.getAttribute('data-id'), 10);
            const person = people.find(function (x) { return x.id === id; });
            _showContactModal(cid, person || { id: id });
        });
    });
    panel.querySelectorAll('.pf-del-contact').forEach(function (a) {
        a.addEventListener('click', async function (e) {
            e.preventDefault();
            const id = parseInt(a.getAttribute('data-id'), 10);
            const nm = a.getAttribute('data-name') || '';
            if (!confirm(t('contacts.delete_confirm').replace('{name}', nm))) return;
            const r = await api('DELETE', '/api/trade/customers/' + cid + '/contacts/' + id);
            if (!r || !r.ok) return;
            toast(t('contacts.deleted'));
            openCustomerProfile(cid);
        });
    });
    $('profile-back')?.addEventListener('click', closeCustomerProfile);
    _bindProfileCardActions(cid, panel, mailboxBound, function () {
        return _refreshProfileSections(cid, panel, people, mailboxBound);
    }, people);
    if (_profileEscHandler) document.removeEventListener('keydown', _profileEscHandler);
    _profileEscHandler = function (e) {
        if (e.key === 'Escape') {
            e.preventDefault();
            e.stopImmediatePropagation();
            closeCustomerProfile();
        }
    };
    document.addEventListener('keydown', _profileEscHandler);
}
