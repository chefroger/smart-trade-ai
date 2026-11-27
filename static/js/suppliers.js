// ═════════════════════ SUPPLIERS VIEW（供应商管理一期 · 第一批）═════════════════════
// #region suppliers-ui —— 供 tests_js/suppliers.test.js 抽取测试，勿删标记

const _spState = {
    tab: 'directory',          // directory | compare | import | rfqs
    importSub: 'upload',       // upload | drafts
    draftStatus: 'pending',    // pending | approved | rejected | all
    selectedSupplierId: null,
    filters: { q: '', status: '', supplier_type: '', is_starred: '' },
    suppliers: [],
    detail: null,
    compareQuery: { product_name: '', spec_model: '' },
    compareResult: null,
    csvResult: null,
    extractResult: null,
    drafts: [],
    pendingDraftCount: 0,
    rfqFilters: { status: '', q: '' },
    rfqs: [],
    selectedRfqId: null,
    rfqDetail: null,
    companyInquiries: [],
    poFilters: { status: '', supplier_id: '', q: '' },
    pos: [],
    selectedPoId: null,
    poDetail: null,
    companyOrders: [],
    consolidations: [],
    pool: [],
    consStatusFilter: '',
};

const _SP_STATUS_CLASS = {
    '候选': 's-cand',
    '洽谈中': 's-talk',
    '合作中': 's-coop',
    '暂停': 's-pause',
    '黑名单': 's-black',
};

function _spFormatVat(canIssueVat, taxPoint) {
    if (canIssueVat === 1) {
        const pt = (taxPoint !== null && taxPoint !== undefined && taxPoint !== '')
            ? '<b>+' + esc(String(taxPoint)) + '%</b>'
            : '';
        return '<span class="sp-vat ok">可开专票' + pt + '</span>';
    }
    if (canIssueVat === 0) return '<span class="sp-vat no">不开票</span>';
    return '<span class="sp-vat tbc">专票待确认</span>';
}

function _spFormatSelfProduced(val) {
    if (val === 1) return '<span class="sp-self yes">自产</span>';
    if (val === 0) return '<span class="sp-self no">外协/调货</span>';
    return '<span class="sp-self tbc">待确认</span>';
}

function _spFormatPriceCell(value, currency, isConverted) {
    if (value === null || value === undefined || value === '') {
        return '<span class="sp-mut">—</span>';
    }
    const cur = esc(currency || 'CNY');
    const num = esc(String(value));
    const badge = isConverted ? '<span class="sp-conv">换算</span>' : '';
    return '<span class="sp-num">' + cur + ' ' + num + '</span>' + badge;
}

function _spFormatQuotedAt(val) {
    const text = (val === null || val === undefined) ? '' : String(val).trim();
    return text ? esc(text) : '<span class="sp-mut">日期未注明</span>';
}

function _spBuildDirectoryRowsHtml(items) {
    if (!items || !items.length) {
        return '<tr><td colspan="7"><div class="sp-state"><h3>暂无供应商</h3><p>点击右上角「新建供应商」，或前往「导入与确认」通过 CSV 模板批量导入。</p></div></td></tr>';
    }
    return items.map(function (s) {
        const stCls = _SP_STATUS_CLASS[s.status] || 's-cand';
        const loc = [s.province, s.city].filter(Boolean).join(' · ');
        const sub = [s.short_name, loc].filter(Boolean).join(' / ');
        const starCls = s.is_starred ? 'sp-star-btn on' : 'sp-star-btn';
        const starChar = s.is_starred ? '★' : '☆';
        const ratingText = s.rating ? (esc(String(s.rating)) + ' / 5') : '—';
        return '<tr class="sp-row" data-sp-open="' + esc(String(s.id)) + '">'
            + '<td><button type="button" class="' + starCls + '" data-sp-star="' + esc(String(s.id)) + '" data-sp-starred="' + (s.is_starred ? '1' : '0') + '" title="切换星标">' + starChar + '</button></td>'
            + '<td><div class="rname">' + esc(s.name) + '</div>' + (sub ? '<div class="rsub">' + esc(sub) + '</div>' : '') + '</td>'
            + '<td>' + (s.supplier_type ? '<span class="sp-chip">' + esc(s.supplier_type) + '</span>' : '<span class="sp-mut">—</span>') + '</td>'
            + '<td>' + (s.main_products ? esc(s.main_products) : '<span class="sp-mut">—</span>') + '</td>'
            + '<td><span class="sp-st ' + stCls + '">' + esc(s.status || '候选') + '</span></td>'
            + '<td>' + _spFormatVat(s.can_issue_vat, s.tax_point) + '</td>'
            + '<td class="sp-num">' + ratingText + '</td>'
            + '</tr>';
    }).join('');
}

function _spBuildCompareGroupsHtml(result) {
    if (!result || !result.product_name) {
        return '<div class="sp-state"><h3>输入产品名称开始比价</h3><p>支持按产品名称和规格型号跨供应商对比：自产标记、质量备注、交期、MOQ、含税与不含税价（含税换算仅在有开票加点时展示，不同单位自动分组）。</p></div>';
    }
    const groups = result.unit_groups || [];
    const noQuotes = result.no_quote_suppliers || [];
    if (!groups.length && !noQuotes.length) {
        return '<div class="sp-state"><h3>未找到匹配的供应商能力或报价</h3><p>请调整产品名称或规格关键词重试。</p></div>';
    }
    const parts = [];
    groups.forEach(function (g) {
        const lowExcl = (g.lowest_excl_tax !== null && g.lowest_excl_tax !== undefined)
            ? ('最低不含税：' + esc(String(g.lowest_excl_tax))) : '';
        const lowIncl = (g.lowest_incl_tax !== null && g.lowest_incl_tax !== undefined)
            ? ('最低含税：' + esc(String(g.lowest_incl_tax))) : '';
        const lowSummary = [lowExcl, lowIncl].filter(Boolean).join(' · ') || '暂无有效原价最低值';
        const rows = (g.suppliers || []).map(function (row) {
            const prod = row.product || {};
            const lq = row.latest_quote || {};
            const rowCls = lq.expired ? 'is-expired' : '';
            const lead = prod.lead_time_text || (prod.lead_time_days !== null && prod.lead_time_days !== undefined ? (String(prod.lead_time_days) + ' 天') : '—');
            const moqVal = (prod.moq !== null && prod.moq !== undefined) ? prod.moq : lq.moq;
            const moqText = (moqVal !== null && moqVal !== undefined && moqVal !== '') ? esc(String(moqVal)) : '—';
            const rangeArr = row.price_excl_range || row.price_incl_range;
            const rangeText = rangeArr ? (esc(String(rangeArr[0])) + ' ~ ' + esc(String(rangeArr[1]))) : '—';
            const expTag = lq.expired ? '<span class="sp-exp">已过期</span>' : '';
            return '<tr class="' + rowCls + '">'
                + '<td><div class="rname">' + esc(row.supplier_name) + '</div>'
                + (row.payment_terms ? '<div class="rsub">' + esc(row.payment_terms) + '</div>' : '') + '</td>'
                + '<td>' + _spFormatSelfProduced(prod.is_self_produced !== undefined ? prod.is_self_produced : 2) + '</td>'
                + '<td>' + (prod.quality_note ? esc(prod.quality_note) : '<span class="sp-mut">—</span>') + '</td>'
                + '<td>' + esc(lead) + '</td>'
                + '<td class="sp-num">' + moqText + '</td>'
                + '<td>' + _spFormatPriceCell(lq.price_excl_tax, lq.currency, lq.price_excl_tax_converted) + '</td>'
                + '<td>' + _spFormatPriceCell(lq.price_incl_tax, lq.currency, lq.price_incl_tax_converted) + '</td>'
                + '<td><div>' + rangeText + '</div><div class="rsub">共 ' + esc(String(row.quote_count || 0)) + ' 条</div></td>'
                + '<td>' + _spFormatQuotedAt(lq.quoted_at) + expTag + '</td>'
                + '</tr>';
        }).join('');
        parts.push(
            '<div class="sp-cmp-grp">'
            + '<div class="gh"><span>单位组：' + esc(g.unit) + '</span><span class="r">' + lowSummary + '</span></div>'
            + '<table class="sp-cmp"><thead><tr>'
            + '<th>供应商</th><th>自产</th><th>质量备注</th><th>交期</th><th>MOQ</th>'
            + '<th>不含税价</th><th>含税价</th><th>历史区间</th><th>最近报价日期</th>'
            + '</tr></thead><tbody>' + rows + '</tbody></table></div>'
        );
    });
    if (noQuotes.length) {
        const nqRows = noQuotes.map(function (s) {
            const p = (s.products && s.products[0]) || {};
            return '<tr><td>' + esc(s.supplier_name) + '</td>'
                + '<td>' + _spFormatSelfProduced(p.is_self_produced !== undefined ? p.is_self_produced : 2) + '</td>'
                + '<td>' + esc(p.spec_model || '—') + '</td>'
                + '<td>' + esc(p.quality_note || '—') + '</td>'
                + '<td>' + esc(p.lead_time_text || (p.lead_time_days != null ? String(p.lead_time_days) + ' 天' : '—')) + '</td></tr>';
        }).join('');
        parts.push(
            '<div class="sp-cmp-grp">'
            + '<div class="gh"><span>仅有能力登记、暂无报价</span><span class="r">' + esc(String(noQuotes.length)) + ' 家</span></div>'
            + '<table class="sp-cmp"><thead><tr><th>供应商</th><th>自产</th><th>规格</th><th>质量备注</th><th>交期</th></tr></thead><tbody>'
            + nqRows + '</tbody></table></div>'
        );
    }
    return parts.join('');
}

function _spFormatRfqStatus(status) {
    if (status === 'decided') return '<span class="sp-st s-coop">已选厂</span>';
    return '<span class="sp-st s-talk">待回复</span>';
}

function _spBuildRfqRowsHtml(items) {
    if (!items || !items.length) {
        return '<tr><td colspan="6"><div class="sp-state"><h3>暂无采购询价单</h3><p>点击「新建采购询价」向多家供应商发询价、记录回复并选定供应商。</p></div></td></tr>';
    }
    return items.map(function (r) {
        const sub = [r.spec_model, r.title].filter(Boolean).join(' · ');
        const qtyText = (r.quantity !== null && r.quantity !== undefined && r.quantity !== '')
            ? (esc(String(r.quantity)) + (r.unit ? ' ' + esc(r.unit) : ''))
            : (r.unit ? esc(r.unit) : '—');
        const custText = r.customer_name ? esc(r.customer_name) : '<span class="sp-mut">—</span>';
        const respCount = Number(r.responded_count || 0);
        const totalCount = Number(r.total_responses || 0);
        const progText = '已回 ' + esc(String(respCount)) + ' / 共 ' + esc(String(totalCount));
        const selText = r.selected_supplier_name
            ? '<span class="sp-self yes">' + esc(r.selected_supplier_name) + '</span>'
            : '<span class="sp-mut">—</span>';
        return '<tr class="sp-row" data-rfq-open="' + esc(String(r.id)) + '">'
            + '<td><div class="rname">' + esc(r.product_name) + '</div>' + (sub ? '<div class="rsub">' + esc(sub) + '</div>' : '') + '</td>'
            + '<td class="sp-num">' + qtyText + '</td>'
            + '<td>' + custText + '</td>'
            + '<td class="sp-num">' + progText + '</td>'
            + '<td>' + selText + '</td>'
            + '<td>' + _spFormatRfqStatus(r.status) + '</td>'
            + '</tr>';
    }).join('');
}

function _spBuildRfqResponsesHtml(responses) {
    if (!responses || !responses.length) {
        return '<tr><td colspan="8"><div class="sp-state"><h3>暂未添加供应商</h3><p>在上方选择本公司供应商加入本采购询价单。</p></div></td></tr>';
    }
    return responses.map(function (r) {
        const rid = esc(String(r.id));
        const isSel = Number(r.selected || 0) === 1;
        const isResp = Number(r.responded || 0) === 1;
        const rowCls = isSel ? 'sp-rfq-sel' : '';
        const respBadge = isResp
            ? '<span class="sp-self yes">已回</span>'
            : '<span class="sp-self tbc">未回</span>';
        const exclVal = (r.price_excl_tax !== null && r.price_excl_tax !== undefined) ? String(r.price_excl_tax) : '';
        const inclVal = (r.price_incl_tax !== null && r.price_incl_tax !== undefined) ? String(r.price_incl_tax) : '';
        const curVal = r.currency || 'CNY';
        const daysVal = (r.lead_time_days !== null && r.lead_time_days !== undefined) ? String(r.lead_time_days) : '';
        const ltxtVal = r.lead_time_text || '';
        const moqVal = (r.moq !== null && r.moq !== undefined) ? String(r.moq) : '';
        const selBtn = isSel
            ? '<button type="button" class="btn" data-rfq-unselect="' + rid + '">取消选定</button>'
            : '<button type="button" class="btn btn-primary" data-rfq-select="' + rid + '">选定</button>';
        return '<tr class="' + rowCls + '" data-rfq-resp-row="' + rid + '">'
            + '<td><div class="rname">' + esc(r.supplier_name || '') + '</div>'
            + (isSel ? '<div class="rsub" style="color:var(--accent);font-weight:600;">已选定供应商</div>' : '')
            + (r.quote_id ? '<div class="rsub">已沉淀报价 #' + esc(String(r.quote_id)) + '</div>' : '') + '</td>'
            + '<td><label style="display:inline-flex;align-items:center;gap:4px;cursor:pointer;">'
            + '<input type="checkbox" data-rfq-f="responded"' + (isResp ? ' checked' : '') + '> ' + respBadge + '</label>'
            + (r.responded_at ? '<div class="rsub">' + esc(r.responded_at) + '</div>' : '') + '</td>'
            + '<td><input type="text" data-rfq-f="price_excl_tax" placeholder="不含税" value="' + esc(exclVal) + '" style="width:78px;"></td>'
            + '<td><input type="text" data-rfq-f="price_incl_tax" placeholder="含税" value="' + esc(inclVal) + '" style="width:78px;">'
            + '<input type="text" data-rfq-f="currency" value="' + esc(curVal) + '" style="width:50px;margin-left:4px;" title="币种"></td>'
            + '<td><input type="text" data-rfq-f="lead_time_days" placeholder="天数" value="' + esc(daysVal) + '" style="width:56px;"> '
            + '<input type="text" data-rfq-f="lead_time_text" placeholder="周期说明" value="' + esc(ltxtVal) + '" style="width:88px;"></td>'
            + '<td><input type="text" data-rfq-f="moq" placeholder="MOQ" value="' + esc(moqVal) + '" style="width:68px;"></td>'
            + '<td><input type="text" data-rfq-f="notes" placeholder="备注" value="' + esc(r.notes || '') + '" style="width:120px;"></td>'
            + '<td style="white-space:nowrap;">'
            + '<button type="button" class="btn" data-rfq-save="' + rid + '">保存</button> '
            + selBtn + ' '
            + '<button type="button" class="sp-lnk danger" data-rfq-del="' + rid + '">删除</button>'
            + '</td></tr>';
    }).join('');
}

const _PO_STATUS_CLASS = {
    '已下单': 's-cand',
    '生产中': 's-talk',
    '待出货': 's-pause',
    '已出货': 's-coop',
    '完成': 's-coop',
};

function _spFormatPoStatus(status) {
    const cls = _PO_STATUS_CLASS[status] || 's-cand';
    return '<span class="sp-st ' + cls + '">' + esc(status || '已下单') + '</span>';
}

function _spFormatCutoffBadge(daysToCutoff, cutoffDate) {
    if (!cutoffDate) return '<span class="sp-mut">未设截关日</span>';
    if (daysToCutoff === null || daysToCutoff === undefined) return esc(cutoffDate);
    const n = Number(daysToCutoff);
    if (n < 0) return '<span class="sp-cut over">已过 ' + esc(String(Math.abs(n))) + ' 天</span>';
    if (n === 0) return '<span class="sp-cut warn">今日截关</span>';
    if (n <= 3) return '<span class="sp-cut warn">剩 ' + esc(String(n)) + ' 天</span>';
    return '<span class="sp-cut ok">剩 ' + esc(String(n)) + ' 天</span>';
}

function _spBuildPoRowsHtml(items) {
    if (!items || !items.length) {
        return '<tr><td colspan="7"><div class="sp-state"><h3>暂无采购单</h3><p>点击「新建采购单」或「从询价单生成」创建采购单。</p></div></td></tr>';
    }
    return items.map(function (po) {
        const sub = [po.spec_model, po.quantity != null ? (String(po.quantity) + (po.unit ? ' ' + po.unit : '')) : ''].filter(Boolean).join(' · ');
        const ordLabel = po.order_display_no
            ? ('<div class="rname">' + esc(po.order_display_no) + '</div>' + (po.customer_name ? '<div class="rsub">' + esc(po.customer_name) + '</div>' : ''))
            : '<span class="sp-mut">—</span>';
        const amtText = (po.amount !== null && po.amount !== undefined && po.amount !== '')
            ? ('<span class="sp-num">' + esc(po.currency || 'CNY') + ' ' + esc(String(po.amount)) + '</span>')
            : '<span class="sp-mut">—</span>';
        return '<tr class="sp-row" data-po-open="' + esc(String(po.id)) + '">'
            + '<td class="sp-num"><b>' + esc(po.po_no || ('PO' + po.id)) + '</b></td>'
            + '<td>' + esc(po.supplier_name || '') + '</td>'
            + '<td><div class="rname">' + esc(po.product_name) + '</div>' + (sub ? '<div class="rsub">' + esc(sub) + '</div>' : '') + '</td>'
            + '<td>' + ordLabel + '</td>'
            + '<td>' + amtText + '</td>'
            + '<td class="sp-num">' + esc(po.promised_date || '—') + '</td>'
            + '<td>' + _spFormatPoStatus(po.status) + '</td>'
            + '</tr>';
    }).join('');
}

function _spBuildConsolidationCardsHtml(consolidations, pool) {
    if (!consolidations || !consolidations.length) {
        return '<div class="sp-state"><h3>暂无拼柜计划</h3><p>点击「新建拼柜」创建拼柜，并从下方待拼池将采购单装入对应货柜。</p></div>';
    }
    const poolOpts = '<option value="">从待拼池选择采购单...</option>' + (pool || []).map(function (p) {
        return '<option value="' + esc(String(p.id)) + '">' + esc((p.po_no || ('PO' + p.id)) + ' · ' + (p.supplier_name || '') + ' · ' + (p.product_name || '')) + '</option>';
    }).join('');

    return consolidations.map(function (c) {
        const cid = esc(String(c.id));
        const items = c.items || [];
        const itemsHtml = items.length
            ? '<table class="sp-mini"><thead><tr><th>采购单号</th><th>供应商</th><th>产品</th><th>采购单状态</th><th>约定交期</th><th style="width:60px;">操作</th></tr></thead><tbody>'
              + items.map(function (it) {
                  return '<tr>'
                      + '<td class="sp-num"><b>' + esc(it.po_no || '') + '</b></td>'
                      + '<td>' + esc(it.supplier_name || '') + '</td>'
                      + '<td>' + esc(it.product_name || '') + (it.spec_model ? ' <span class="sp-mut">(' + esc(it.spec_model) + ')</span>' : '') + '</td>'
                      + '<td>' + _spFormatPoStatus(it.po_status) + '</td>'
                      + '<td class="sp-num">' + esc(it.promised_date || '—') + '</td>'
                      + '<td><button type="button" class="sp-lnk danger" data-cons-rm-item="' + esc(String(it.item_id)) + '" data-cons-id="' + cid + '">移出</button></td>'
                      + '</tr>';
              }).join('') + '</tbody></table>'
            : '<div class="sp-mut" style="font-size:12px;padding:6px 0;">柜内暂无采购单</div>';

        const meta = [
            c.destination_port ? ('目的港：' + esc(c.destination_port)) : '',
            c.carrier ? ('船司/货代：' + esc(c.carrier)) : '',
            c.cutoff_date ? ('截关日：' + esc(c.cutoff_date)) : '',
            c.etd ? ('预计开船：' + esc(c.etd)) : '',
        ].filter(Boolean).join(' · ');

        return '<div class="sp-cons-card" data-cons-card="' + cid + '">'
            + '<div class="ch">'
            + '<span class="sp-num" style="font-weight:700;font-size:14px;">' + esc(c.code || ('CG' + c.id)) + '</span>'
            + '<span class="sp-chip">' + esc(c.status || '组货中') + '</span>'
            + _spFormatCutoffBadge(c.days_to_cutoff, c.cutoff_date)
            + '<span class="sp-mut" style="font-size:12px;">共 ' + esc(String(items.length)) + ' 单</span>'
            + '<div style="margin-left:auto;display:flex;gap:6px;">'
            + '<button type="button" class="sp-lnk" data-cons-edit="' + cid + '">编辑</button>'
            + '<button type="button" class="sp-lnk danger" data-cons-del="' + cid + '">删除</button>'
            + '</div></div>'
            + (meta ? '<div class="sp-mut" style="font-size:12px;margin-bottom:8px;">' + meta + '</div>' : '')
            + itemsHtml
            + '<div style="display:flex;gap:6px;margin-top:8px;align-items:center;">'
            + '<select data-cons-add-sel="' + cid + '" style="flex:1;max-width:360px;">' + poolOpts + '</select>'
            + '<button type="button" class="btn" data-cons-add-btn="' + cid + '">+ 添加采购单</button>'
            + '</div></div>';
    }).join('');
}

function _spBuildPoolRowsHtml(pool, consolidations) {
    if (!pool || !pool.length) {
        return '<tr><td colspan="6"><div class="sp-mut" style="padding:10px;text-align:center;">待拼池为空（所有未出货采购单均已入柜）</div></td></tr>';
    }
    const consOpts = '<option value="">选择拼柜...</option>' + (consolidations || []).map(function (c) {
        return '<option value="' + esc(String(c.id)) + '">' + esc((c.code || ('CG' + c.id)) + (c.destination_port ? (' · ' + c.destination_port) : '')) + '</option>';
    }).join('');
    return pool.map(function (p) {
        const pid = esc(String(p.id));
        return '<tr>'
            + '<td class="sp-num"><b>' + esc(p.po_no || ('PO' + p.id)) + '</b></td>'
            + '<td>' + esc(p.supplier_name || '') + '</td>'
            + '<td>' + esc(p.product_name || '') + '</td>'
            + '<td>' + _spFormatPoStatus(p.status) + '</td>'
            + '<td class="sp-num">' + esc(p.promised_date || '—') + '</td>'
            + '<td style="white-space:nowrap;">'
            + '<select data-pool-cons-sel="' + pid + '" style="width:150px;">' + consOpts + '</select> '
            + '<button type="button" class="btn" data-pool-join="' + pid + '">加入</button>'
            + '</td></tr>';
    }).join('');
}

function _spBuildDeliveryAlertsBriefHtml(alerts) {
    if (!alerts || !alerts.length) return '';
    const rows = alerts.map(function (a) {
        const tag = a.is_overdue
            ? '<span class="sp-cut over">逾期 ' + esc(String(a.days_overdue)) + ' 天</span>'
            : '<span class="sp-cut warn">剩 ' + esc(String(a.days_left)) + ' 天</span>';
        return '<div class="sp-brief-al">'
            + '<span class="sp-num"><b>' + esc(a.po_no || ('PO' + a.id)) + '</b></span> '
            + esc(a.supplier_name || '') + ' · ' + esc(a.product_name || '') + ' '
            + tag
            + '</div>';
    }).join('');
    return '<div class="sp-brief-alerts" id="rail-brief-delivery-alerts">'
        + '<div class="sp-brief-al-h">交期提醒（' + esc(String(alerts.length)) + '）</div>'
        + rows + '</div>';
}

function _spBuildOrderLinkedPosHtml(pos) {
    if (!pos || !pos.length) {
        return '<div class="sp-mut" style="font-size:12px;">暂无关联采购单</div>';
    }
    return '<table class="sp-mini"><thead><tr><th>采购单号</th><th>供应商</th><th>产品</th><th>状态</th><th>约定交期</th></tr></thead><tbody>'
        + pos.map(function (p) {
            return '<tr>'
                + '<td class="sp-num"><b>' + esc(p.po_no || ('PO' + p.id)) + '</b></td>'
                + '<td>' + esc(p.supplier_name || '') + '</td>'
                + '<td>' + esc(p.product_name || '') + '</td>'
                + '<td>' + _spFormatPoStatus(p.status) + '</td>'
                + '<td class="sp-num">' + esc(p.promised_date || '—') + '</td>'
                + '</tr>';
        }).join('') + '</tbody></table>';
}

function _spFormatExtractError(errCode, filePath) {
    const code = String(errCode || '');
    const lower = String(filePath || '').toLowerCase();
    if (code === 'unsupported_type') {
        if (/\.(jpe?g|png|gif|webp|bmp|tiff?|heic)$/i.test(lower)) {
            return '图片 / 扫描件暂不支持，需要先 OCR';
        }
        return '文件格式暂不支持（目前支持 txt/md/csv/tsv/xlsx/docx/pdf）';
    }
    if (code === 'needs_ocr') return '扫描版 PDF 暂不支持，需要先 OCR';
    if (code === 'file_not_found') return '文件或路径不存在';
    if (code === 'empty') return '文件内容为空';
    if (code === 'truncated') return '文件内容过长被截断，未自动抽取';
    return code || '未知错误';
}

function _spBuildExtractResultHtml(er) {
    if (!er) return '';
    const failed = Array.isArray(er.failed) ? er.failed : [];
    const failRows = failed.map(function (f) {
        return '<tr><td>' + esc(f.file || '') + '</td><td style="color:var(--accent);">' + esc(_spFormatExtractError(f.error, f.file)) + '</td></tr>';
    }).join('');
    return '<div class="sp-warn-box" style="margin-top:8px;">'
        + '已处理文件：<b>' + esc(String(er.files_processed || 0)) + '</b>，生成待确认草稿：<b>' + esc(String(er.drafts_created || 0)) + '</b> 条，失败/跳过：<b>' + esc(String(failed.length)) + '</b> 个。'
        + ' <button type="button" class="sp-lnk" id="sp-go-drafts-btn">前往确认区审核 →</button></div>'
        + (failRows ? '<table class="sp-mini"><thead><tr><th>未处理 / 失败文件</th><th>原因</th></tr></thead><tbody>' + failRows + '</tbody></table>' : '');
}
// #endregion suppliers-ui

function renderSuppliersViewInto(container) {
    container.innerHTML = '<div class="sp-wrap" id="sp-root"></div>';
    _spRefreshPendingCount();
    _spRenderRoot(container);
    _spLoadSuppliers();
}

function _spGetRoot() {
    return document.getElementById('sp-root');
}

async function _spRefreshPendingCount() {
    const list = await api('GET', '/api/trade/supplier-quote-drafts?status=pending', null, null, { silent: true });
    if (Array.isArray(list)) {
        _spState.pendingDraftCount = list.length;
        const badge = document.getElementById('sp-draft-badge');
        if (badge) {
            badge.textContent = String(list.length);
            badge.style.display = list.length > 0 ? '' : 'none';
        }
    }
}

function _spRenderRoot() {
    const root = _spGetRoot();
    if (!root) return;
    const t = _spState.tab;
    const badgeStyle = _spState.pendingDraftCount > 0 ? '' : ' style="display:none"';
    root.innerHTML =
        '<div class="sp-head">'
        + '<h2>' + btnIcon('building-complex') + ' 供应商管理</h2>'
        + '<div class="sp-head-acts">'
        + '<button type="button" class="btn btn-primary" id="sp-new-btn">' + btnIcon('plus') + ' 新建供应商</button>'
        + '</div></div>'
        + '<div class="sp-tabs" role="tablist">'
        + '<button type="button" class="sp-tab' + (t === 'directory' ? ' on' : '') + '" data-sp-tab="directory"><span class="zh">供应商名录</span><span class="en">DIRECTORY</span></button>'
        + '<button type="button" class="sp-tab' + (t === 'compare' ? ' on' : '') + '" data-sp-tab="compare"><span class="zh">产品能力（比价）</span><span class="en">COMPARE</span></button>'
        + '<button type="button" class="sp-tab' + (t === 'import' ? ' on' : '') + '" data-sp-tab="import"><span class="zh">导入与确认</span><span class="en">IMPORT</span><span class="sp-n" id="sp-draft-badge"' + badgeStyle + '>' + esc(String(_spState.pendingDraftCount)) + '</span></button>'
        + '<button type="button" class="sp-tab' + (t === 'rfqs' ? ' on' : '') + '" data-sp-tab="rfqs"><span class="zh">采购询价</span><span class="en">RFQ</span></button>'
        + '<button type="button" class="sp-tab' + (t === 'pos' ? ' on' : '') + '" data-sp-tab="pos"><span class="zh">采购单</span><span class="en">PO</span></button>'
        + '<button type="button" class="sp-tab' + (t === 'consolidations' ? ' on' : '') + '" data-sp-tab="consolidations"><span class="zh">拼柜看板</span><span class="en">CONSOL</span></button>'
        + '</div>'
        + '<div class="sp-body" id="sp-body"></div>';

    root.querySelector('#sp-new-btn').addEventListener('click', function () {
        _spOpenSupplierModal(null);
    });
    root.querySelectorAll('[data-sp-tab]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            _spState.tab = btn.getAttribute('data-sp-tab');
            if (_spState.tab === 'directory') {
                _spState.selectedSupplierId = null;
                _spRenderRoot();
                _spLoadSuppliers();
            } else if (_spState.tab === 'compare') {
                _spRenderRoot();
                _spRenderBody();
            } else if (_spState.tab === 'import') {
                _spRenderRoot();
                _spRenderBody();
                if (_spState.importSub === 'drafts') _spLoadDrafts();
            } else if (_spState.tab === 'rfqs') {
                _spState.selectedRfqId = null;
                _spState.rfqDetail = null;
                _spRenderRoot();
                _spLoadRfqs();
            } else if (_spState.tab === 'pos') {
                _spState.selectedPoId = null;
                _spState.poDetail = null;
                _spRenderRoot();
                _spLoadPos();
            } else if (_spState.tab === 'consolidations') {
                _spRenderRoot();
                _spLoadConsolidations();
            }
        });
    });
    _spRenderBody();
}

function _spRenderBody() {
    const body = document.getElementById('sp-body');
    if (!body) return;
    if (_spState.tab === 'directory') {
        if (_spState.selectedSupplierId && _spState.detail) {
            _spRenderDetail(body, _spState.detail);
        } else {
            _spRenderDirectory(body);
        }
    } else if (_spState.tab === 'compare') {
        _spRenderCompare(body);
    } else if (_spState.tab === 'rfqs') {
        if (_spState.selectedRfqId && _spState.rfqDetail) {
            _spRenderRfqDetail(body, _spState.rfqDetail);
        } else {
            _spRenderRfqsList(body);
        }
    } else if (_spState.tab === 'pos') {
        if (_spState.selectedPoId && _spState.poDetail) {
            _spRenderPoDetail(body, _spState.poDetail);
        } else {
            _spRenderPosList(body);
        }
    } else if (_spState.tab === 'consolidations') {
        _spRenderConsolidations(body);
    } else {
        _spRenderImport(body);
    }
}

// ── 名录页签 ────────────────────────────────────────────────────────────────

async function _spLoadSuppliers() {
    const f = _spState.filters;
    const qs = new URLSearchParams();
    if (f.q) qs.set('q', f.q);
    if (f.status) qs.set('status', f.status);
    if (f.supplier_type) qs.set('supplier_type', f.supplier_type);
    if (f.is_starred !== '') qs.set('is_starred', f.is_starred);
    const url = '/api/trade/suppliers' + (qs.toString() ? '?' + qs.toString() : '');
    const res = await api('GET', url);
    if (Array.isArray(res)) {
        _spState.suppliers = res;
        if (_spState.tab === 'directory' && !_spState.selectedSupplierId) {
            _spRenderBody();
        }
    }
}

function _spRenderDirectory(body) {
    const f = _spState.filters;
    const statuses = ['', '候选', '洽谈中', '合作中', '暂停', '黑名单'];
    const types = ['', '工厂', '贸易商', '工贸一体', '未知'];
    const stOpts = statuses.map(function (s) {
        return '<option value="' + esc(s) + '"' + (f.status === s ? ' selected' : '') + '>' + esc(s || '全部状态') + '</option>';
    }).join('');
    const tyOpts = types.map(function (s) {
        return '<option value="' + esc(s) + '"' + (f.supplier_type === s ? ' selected' : '') + '>' + esc(s || '全部类型') + '</option>';
    }).join('');

    body.innerHTML =
        '<div class="sp-bar">'
        + '<input type="text" id="sp-q" placeholder="搜索供应商名称 / 简称 / 主营品类..." value="' + esc(f.q) + '" style="flex:1;min-width:220px;">'
        + '<select id="sp-status-filter">' + stOpts + '</select>'
        + '<select id="sp-type-filter">' + tyOpts + '</select>'
        + '<label style="display:inline-flex;align-items:center;gap:4px;font-size:12px;cursor:pointer;">'
        + '<input type="checkbox" id="sp-star-filter"' + (f.is_starred === '1' ? ' checked' : '') + '> 仅星标</label>'
        + '<button type="button" class="btn" id="sp-search-btn">筛选</button>'
        + '</div>'
        + '<div class="sp-table-wrap"><table class="sp-table">'
        + '<thead><tr><th style="width:36px;">星标</th><th>供应商</th><th style="width:90px;">类型</th><th>主营品类</th><th style="width:90px;">状态</th><th style="width:120px;">开票</th><th style="width:70px;text-align:right;">评分</th></tr></thead>'
        + '<tbody>' + _spBuildDirectoryRowsHtml(_spState.suppliers) + '</tbody></table></div>';

    const applyFilter = function () {
        _spState.filters.q = (document.getElementById('sp-q')?.value || '').trim();
        _spState.filters.status = document.getElementById('sp-status-filter')?.value || '';
        _spState.filters.supplier_type = document.getElementById('sp-type-filter')?.value || '';
        _spState.filters.is_starred = document.getElementById('sp-star-filter')?.checked ? '1' : '';
        _spLoadSuppliers();
    };
    body.querySelector('#sp-search-btn').addEventListener('click', applyFilter);
    body.querySelector('#sp-status-filter').addEventListener('change', applyFilter);
    body.querySelector('#sp-type-filter').addEventListener('change', applyFilter);
    body.querySelector('#sp-star-filter').addEventListener('change', applyFilter);
    body.querySelector('#sp-q').addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') applyFilter();
    });

    body.querySelectorAll('[data-sp-star]').forEach(function (btn) {
        btn.addEventListener('click', async function (ev) {
            ev.stopPropagation();
            const sid = Number(btn.getAttribute('data-sp-star'));
            const cur = btn.getAttribute('data-sp-starred') === '1';
            const updated = await api('PUT', '/api/trade/suppliers/' + sid, { is_starred: cur ? 0 : 1 });
            if (updated) _spLoadSuppliers();
        });
    });

    body.querySelectorAll('[data-sp-open]').forEach(function (tr) {
        tr.addEventListener('click', function () {
            const sid = Number(tr.getAttribute('data-sp-open'));
            _spOpenDetail(sid);
        });
    });
}

// ── 供应商详情面板 ──────────────────────────────────────────────────────────

async function _spOpenDetail(supplierId) {
    const detail = await api('GET', '/api/trade/suppliers/' + supplierId);
    if (!detail) return;
    _spState.selectedSupplierId = supplierId;
    _spState.detail = detail;
    _spRenderBody();
}

function _spRenderDetail(body, d) {
    const stCls = _SP_STATUS_CLASS[d.status] || 's-cand';
    const loc = [d.province, d.city, d.address].filter(Boolean).join(' ');
    const contactsHtml = (d.contacts && d.contacts.length)
        ? d.contacts.map(function (c) {
            const priTag = c.is_primary ? '<span class="pri">主联系人</span>' : '';
            const info = [
                c.role ? '角色：' + esc(c.role) : '',
                c.phone ? '电话：' + esc(c.phone) : '',
                c.wechat ? '微信：' + esc(c.wechat) : '',
                c.email ? '邮箱：' + esc(c.email) : '',
                c.qq ? 'QQ：' + esc(c.qq) : '',
            ].filter(Boolean).join(' · ');
            return '<div class="sp-person">'
                + '<div class="nm">' + esc(c.name) + priTag + '</div>'
                + '<div class="acts">'
                + '<button type="button" class="sp-lnk" data-sp-edit-contact="' + esc(String(c.id)) + '">编辑</button>'
                + '<button type="button" class="sp-lnk danger" data-sp-del-contact="' + esc(String(c.id)) + '">删除</button>'
                + '</div>'
                + '<div style="font-size:12px;color:var(--muted);margin-top:4px;">' + (info || '—') + '</div>'
                + (c.note ? '<div style="font-size:11.5px;margin-top:2px;">' + esc(c.note) + '</div>' : '')
                + '</div>';
        }).join('')
        : '<div class="sp-mut" style="font-size:12px;padding:6px 0;">暂无联系人</div>';

    const productsHtml = (d.products && d.products.length)
        ? '<table class="sp-mini"><thead><tr><th>产品名</th><th>规格</th><th>自产</th><th>交期 / MOQ</th><th>质量备注</th><th style="width:76px;">操作</th></tr></thead><tbody>'
        + d.products.map(function (p) {
            const lead = p.lead_time_text || (p.lead_time_days != null ? String(p.lead_time_days) + ' 天' : '—');
            const moq = p.moq != null ? ('MOQ ' + esc(String(p.moq))) : '';
            return '<tr>'
                + '<td><b>' + esc(p.product_name) + '</b>' + (p.unit ? '<div class="rsub">单位：' + esc(p.unit) + '</div>' : '') + '</td>'
                + '<td>' + esc(p.spec_model || '—') + '</td>'
                + '<td>' + _spFormatSelfProduced(p.is_self_produced) + '</td>'
                + '<td>' + esc(lead) + (moq ? '<div class="rsub">' + moq + '</div>' : '') + '</td>'
                + '<td>' + esc(p.quality_note || '—') + '</td>'
                + '<td><button type="button" class="sp-lnk" data-sp-edit-prod="' + esc(String(p.id)) + '">编辑</button> '
                + '<button type="button" class="sp-lnk danger" data-sp-del-prod="' + esc(String(p.id)) + '">删除</button></td>'
                + '</tr>';
        }).join('') + '</tbody></table>'
        : '<div class="sp-mut" style="font-size:12px;padding:6px 0;">暂无产品能力登记</div>';

    const quotesHtml = (d.quotes && d.quotes.length)
        ? '<table class="sp-mini"><thead><tr><th>产品 / 规格</th><th>不含税价</th><th>含税价</th><th>报价日 / 有效期</th><th>来源</th><th style="width:76px;">操作</th></tr></thead><tbody>'
        + d.quotes.map(function (q) {
            const rowCls = q.expired ? 'is-expired' : '';
            const expTag = q.expired ? '<span class="sp-exp">已过期</span>' : '';
            const srcCls = q.source === 'ai-extract' ? 'sp-src ai' : 'sp-src';
            return '<tr class="' + rowCls + '">'
                + '<td><b>' + esc(q.product_name) + '</b>' + (q.spec_model ? '<div class="rsub">' + esc(q.spec_model) + '</div>' : '') + '</td>'
                + '<td>' + _spFormatPriceCell(q.price_excl_tax, q.currency, false) + '</td>'
                + '<td>' + _spFormatPriceCell(q.price_incl_tax, q.currency, false) + '</td>'
                + '<td>' + _spFormatQuotedAt(q.quoted_at) + expTag + (q.valid_until ? '<div class="rsub">有效期：' + esc(q.valid_until) + '</div>' : '') + '</td>'
                + '<td><span class="' + srcCls + '">' + esc(q.source || 'manual') + '</span></td>'
                + '<td><button type="button" class="sp-lnk" data-sp-edit-quote="' + esc(String(q.id)) + '">编辑</button> '
                + '<button type="button" class="sp-lnk danger" data-sp-del-quote="' + esc(String(q.id)) + '">删除</button></td>'
                + '</tr>';
        }).join('') + '</tbody></table>'
        : '<div class="sp-mut" style="font-size:12px;padding:6px 0;">暂无报价记录</div>';

    body.innerHTML =
        '<div class="sp-detail-head">'
        + '<button type="button" class="btn" id="sp-back-btn">' + btnIcon('arrow-left') + ' 返回名录</button>'
        + '<h3 style="margin:0;font-size:15px;">' + esc(d.name) + '</h3>'
        + '<span class="sp-st ' + stCls + '">' + esc(d.status || '候选') + '</span>'
        + '<div style="margin-left:auto;display:flex;gap:8px;">'
        + '<button type="button" class="btn" id="sp-edit-sup-btn">编辑基本信息</button>'
        + '<button type="button" class="btn btn-danger" id="sp-del-sup-btn">删除供应商</button>'
        + '</div></div>'
        + '<div class="sp-detail-grid">'
        + '<div class="sp-col">'
        + '<div class="sp-sec"><div class="sp-sec-h"><span class="t">基本信息</span></div>'
        + '<div class="sp-kv">'
        + '<div class="k">简称</div><div class="v">' + esc(d.short_name || '—') + '</div>'
        + '<div class="k">类型</div><div class="v">' + esc(d.supplier_type || '—') + '</div>'
        + '<div class="k">主营品类</div><div class="v">' + esc(d.main_products || '—') + '</div>'
        + '<div class="k">地区地址</div><div class="v">' + esc(loc || '—') + '</div>'
        + '<div class="k">开票能力</div><div class="v">' + _spFormatVat(d.can_issue_vat, d.tax_point) + '</div>'
        + '<div class="k">结算方式</div><div class="v">' + esc(d.payment_terms || '—') + '</div>'
        + '<div class="k">常规交期</div><div class="v">' + (d.lead_time_days != null ? esc(String(d.lead_time_days)) + ' 天' : '—') + '</div>'
        + '<div class="k">来源</div><div class="v">' + esc(d.source || '—') + '</div>'
        + '<div class="k">备注</div><div class="v">' + esc(d.note || '—') + '</div>'
        + '</div></div>'
        + '<div class="sp-sec"><div class="sp-sec-h"><span class="t">联系人（' + esc(String((d.contacts || []).length)) + '）</span>'
        + '<div class="acts"><button type="button" class="btn" id="sp-add-contact-btn">+ 新增联系人</button></div></div>'
        + contactsHtml + '</div>'
        + '</div>'
        + '<div class="sp-col">'
        + '<div class="sp-sec"><div class="sp-sec-h"><span class="t">产品能力（' + esc(String((d.products || []).length)) + '）</span>'
        + '<div class="acts"><button type="button" class="btn" id="sp-add-prod-btn">+ 登记产品能力</button></div></div>'
        + productsHtml + '</div>'
        + '<div class="sp-sec"><div class="sp-sec-h"><span class="t">最近报价（显示 ' + esc(String((d.quotes || []).length)) + ' / 共 ' + esc(String(d.quotes_total || 0)) + ' 条）</span>'
        + '<div class="acts"><button type="button" class="btn btn-primary" id="sp-add-quote-btn">+ 追加报价</button></div></div>'
        + quotesHtml + '</div>'
        + '</div></div>';

    body.querySelector('#sp-back-btn').addEventListener('click', function () {
        _spState.selectedSupplierId = null;
        _spState.detail = null;
        _spRenderBody();
        _spLoadSuppliers();
    });
    body.querySelector('#sp-edit-sup-btn').addEventListener('click', function () { _spOpenSupplierModal(d); });
    body.querySelector('#sp-del-sup-btn').addEventListener('click', function () { _spOpenDeleteSupplierModal(d); });
    body.querySelector('#sp-add-contact-btn').addEventListener('click', function () { _spOpenContactModal(d.id, null); });
    body.querySelector('#sp-add-prod-btn').addEventListener('click', function () { _spOpenProductModal(d.id, null); });
    body.querySelector('#sp-add-quote-btn').addEventListener('click', function () { _spOpenQuoteModal(d.id, null); });

    body.querySelectorAll('[data-sp-edit-contact]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const cid = Number(btn.getAttribute('data-sp-edit-contact'));
            const item = (d.contacts || []).find(function (x) { return x.id === cid; });
            if (item) _spOpenContactModal(d.id, item);
        });
    });
    body.querySelectorAll('[data-sp-del-contact]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const cid = Number(btn.getAttribute('data-sp-del-contact'));
            if (!confirm('确认删除该联系人？')) return;
            const ok = await api('DELETE', '/api/trade/suppliers/contacts/' + cid);
            if (ok) _spOpenDetail(d.id);
        });
    });
    body.querySelectorAll('[data-sp-edit-prod]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const pid = Number(btn.getAttribute('data-sp-edit-prod'));
            const item = (d.products || []).find(function (x) { return x.id === pid; });
            if (item) _spOpenProductModal(d.id, item);
        });
    });
    body.querySelectorAll('[data-sp-del-prod]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const pid = Number(btn.getAttribute('data-sp-del-prod'));
            if (!confirm('确认删除该产品能力行？（已有历史报价会保留）')) return;
            const ok = await api('DELETE', '/api/trade/supplier-products/' + pid);
            if (ok) _spOpenDetail(d.id);
        });
    });
    body.querySelectorAll('[data-sp-edit-quote]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const qid = Number(btn.getAttribute('data-sp-edit-quote'));
            const item = (d.quotes || []).find(function (x) { return x.id === qid; });
            if (item) _spOpenQuoteModal(d.id, item);
        });
    });
    body.querySelectorAll('[data-sp-del-quote]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const qid = Number(btn.getAttribute('data-sp-del-quote'));
            if (!confirm('确认删除该条报价记录？')) return;
            const ok = await api('DELETE', '/api/trade/supplier-quotes/' + qid);
            if (ok) _spOpenDetail(d.id);
        });
    });
}

// ── 比价页签 ────────────────────────────────────────────────────────────────

function _spRenderCompare(body) {
    const q = _spState.compareQuery;
    body.innerHTML =
        '<div class="sp-cmp-bar">'
        + '<span class="sp-lbl">产品名称</span>'
        + '<input type="text" id="sp-cmp-prod" placeholder="输入产品名称，如 陶瓷马克杯" value="' + esc(q.product_name) + '" style="flex:1;min-width:200px;">'
        + '<span class="sp-lbl">规格型号</span>'
        + '<input type="text" id="sp-cmp-spec" placeholder="可选，如 350ml" value="' + esc(q.spec_model) + '" style="width:180px;">'
        + '<button type="button" class="btn btn-primary" id="sp-cmp-go">开始比价</button>'
        + '</div>'
        + '<div id="sp-cmp-result">' + _spBuildCompareGroupsHtml(_spState.compareResult) + '</div>';

    const runCompare = async function () {
        const pn = (document.getElementById('sp-cmp-prod')?.value || '').trim();
        const sm = (document.getElementById('sp-cmp-spec')?.value || '').trim();
        if (!pn) {
            toast('请输入要对比的产品名称');
            return;
        }
        _spState.compareQuery = { product_name: pn, spec_model: sm };
        const qs = new URLSearchParams({ product_name: pn });
        if (sm) qs.set('spec_model', sm);
        const res = await api('GET', '/api/trade/supplier-compare?' + qs.toString());
        if (res) {
            _spState.compareResult = res;
            const box = document.getElementById('sp-cmp-result');
            if (box) box.innerHTML = _spBuildCompareGroupsHtml(res);
        }
    };
    body.querySelector('#sp-cmp-go').addEventListener('click', runCompare);
    body.querySelector('#sp-cmp-prod').addEventListener('keydown', function (ev) { if (ev.key === 'Enter') runCompare(); });
    body.querySelector('#sp-cmp-spec').addEventListener('keydown', function (ev) { if (ev.key === 'Enter') runCompare(); });
}

// ── 导入与确认页签 ──────────────────────────────────────────────────────────

function _spRenderImport(body) {
    const sub = _spState.importSub;
    body.innerHTML =
        '<div class="sp-seg2">'
        + '<button type="button" class="' + (sub === 'upload' ? 'on' : '') + '" data-sp-imp-sub="upload">批量导入与 AI 抽取</button>'
        + '<button type="button" class="' + (sub === 'drafts' ? 'on' : '') + '" data-sp-imp-sub="drafts">确认区（待确认 ' + esc(String(_spState.pendingDraftCount)) + '）</button>'
        + '</div>'
        + '<div id="sp-imp-panel"></div>';

    body.querySelectorAll('[data-sp-imp-sub]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            _spState.importSub = btn.getAttribute('data-sp-imp-sub');
            _spRenderImport(body);
            if (_spState.importSub === 'drafts') _spLoadDrafts();
        });
    });

    const panel = document.getElementById('sp-imp-panel');
    if (sub === 'upload') {
        _spRenderImportUpload(panel);
    } else {
        _spRenderDraftsList(panel);
    }
}

function _spRenderImportUpload(panel) {
    let csvResHtml = '';
    if (_spState.csvResult) {
        const r = _spState.csvResult;
        const errRows = (r.errors || []).map(function (e) {
            return '<tr><td>第 ' + esc(String(e.row)) + ' 行</td><td style="color:var(--accent);">' + esc(e.error) + '</td></tr>';
        }).join('');
        csvResHtml =
            '<div class="sp-rsum" style="margin-top:8px;">'
            + '<div><div class="n">' + esc(String(r.ok_rows || 0)) + '</div><div class="d">成功行数</div></div>'
            + '<div><div class="n">' + esc(String(r.created_suppliers || 0)) + '</div><div class="d">新建供应商</div></div>'
            + '<div><div class="n">' + esc(String(r.created_quotes || 0)) + '</div><div class="d">新增报价</div></div>'
            + '<div><div class="n r">' + esc(String(r.error_count || 0)) + '</div><div class="d">失败行数</div></div>'
            + '</div>'
            + (errRows ? '<table class="sp-mini" style="margin-top:8px;"><thead><tr><th style="width:90px;">行号</th><th>失败原因</th></tr></thead><tbody>' + errRows + '</tbody></table>' : '');
    }

    let extResHtml = '';
    if (_spState.extractResult) {
        extResHtml = _spBuildExtractResultHtml(_spState.extractResult);
    }

    panel.innerHTML =
        '<div class="sp-imp2">'
        + '<div class="sp-card">'
        + '<h4>1. CSV 模板批量导入</h4>'
        + '<p>下载标准模板，一次导入供应商、联系人、产品能力与报价历史。同文件内同名供应商自动合并；坏行逐行报错、好行照常入库。</p>'
        + '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">'
        + '<button type="button" class="btn" id="sp-dl-tpl-btn">' + btnIcon('download') + ' 下载 CSV 模板</button>'
        + '<input type="file" id="sp-csv-file" accept=".csv" style="font-size:12px;">'
        + '<button type="button" class="btn btn-primary" id="sp-csv-upload-btn">' + btnIcon('upload') + ' 上传导入</button>'
        + '</div>'
        + csvResHtml
        + '</div>'
        + '<div class="sp-card">'
        + '<h4>2. AI 文件夹报价抽取</h4>'
        + '<p>输入本机报价文件或文件夹绝对路径（每行一个，支持 txt/csv/xlsx/docx/pdf）。抽取结果仅写入确认区草稿，人工核对批准后才进入正式报价库。</p>'
        + '<textarea id="sp-extract-paths" rows="4" placeholder="/Users/yourname/Documents/供应商报价单" style="width:100%;font-family:var(--font-mono);font-size:12px;padding:6px 8px;border:1px solid var(--line-strong);"></textarea>'
        + '<div style="display:flex;gap:8px;align-items:center;">'
        + '<button type="button" class="btn btn-primary" id="sp-extract-go-btn">开始 AI 抽取</button>'
        + '<span id="sp-extract-status" class="sp-mut" style="font-size:12px;"></span>'
        + '</div>'
        + extResHtml
        + '</div>'
        + '</div>';

    panel.querySelector('#sp-dl-tpl-btn').addEventListener('click', async function () {
        const opts = _buildApiOpts('GET', null, TOKEN, currentCompanyId);
        const r = await fetch('/api/trade/suppliers/template', opts);
        if (!r.ok) {
            toast('下载模板失败');
            return;
        }
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'trade-supplier-template.csv';
        a.click();
        URL.revokeObjectURL(url);
    });

    panel.querySelector('#sp-csv-upload-btn').addEventListener('click', async function () {
        const inp = document.getElementById('sp-csv-file');
        if (!inp || !inp.files || !inp.files.length) {
            toast('请先选择要上传的 CSV 文件');
            return;
        }
        const fd = new FormData();
        fd.append('file', inp.files[0]);
        const res = await api('POST', '/api/trade/suppliers/bulk', fd);
        if (res) {
            _spState.csvResult = res;
            toast('导入完成：成功 ' + res.ok_rows + ' 行，失败 ' + res.error_count + ' 行');
            _spRenderImportUpload(panel);
        }
    });

    panel.querySelector('#sp-extract-go-btn').addEventListener('click', async function () {
        const raw = document.getElementById('sp-extract-paths')?.value || '';
        const paths = raw.split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
        if (!paths.length) {
            toast('请先输入至少一个文件或文件夹路径');
            return;
        }
        const stEl = document.getElementById('sp-extract-status');
        if (stEl) stEl.textContent = '正在抽取，请稍候...';
        const res = await api('POST', '/api/trade/suppliers/extract', { paths: paths });
        if (stEl) stEl.textContent = '';
        if (res) {
            _spState.extractResult = res;
            await _spRefreshPendingCount();
            toast('抽取完成：生成 ' + res.drafts_created + ' 条草稿');
            _spRenderImportUpload(panel);
        }
    });

    const goBtn = panel.querySelector('#sp-go-drafts-btn');
    if (goBtn) {
        goBtn.addEventListener('click', function () {
            _spState.importSub = 'drafts';
            const body = document.getElementById('sp-body');
            if (body) _spRenderImport(body);
            _spLoadDrafts();
        });
    }
}

async function _spLoadDrafts() {
    const st = _spState.draftStatus || 'pending';
    const list = await api('GET', '/api/trade/supplier-quote-drafts?status=' + encodeURIComponent(st));
    if (Array.isArray(list)) {
        _spState.drafts = list;
        if (st === 'pending') {
            _spState.pendingDraftCount = list.length;
            const badge = document.getElementById('sp-draft-badge');
            if (badge) {
                badge.textContent = String(list.length);
                badge.style.display = list.length > 0 ? '' : 'none';
            }
        }
        const panel = document.getElementById('sp-imp-panel');
        if (panel && _spState.tab === 'import' && _spState.importSub === 'drafts') {
            _spRenderDraftsList(panel);
        }
    }
}

function _spRenderDraftsList(panel) {
    const st = _spState.draftStatus;
    const filterHtml =
        '<div class="sp-bar" style="margin-bottom:10px;">'
        + '<span class="sp-lbl">状态筛选</span>'
        + '<select id="sp-draft-st-sel">'
        + '<option value="pending"' + (st === 'pending' ? ' selected' : '') + '>待确认</option>'
        + '<option value="approved"' + (st === 'approved' ? ' selected' : '') + '>已批准</option>'
        + '<option value="rejected"' + (st === 'rejected' ? ' selected' : '') + '>已驳回</option>'
        + '<option value="all"' + (st === 'all' ? ' selected' : '') + '>全部</option>'
        + '</select></div>';

    const items = _spState.drafts || [];
    if (!items.length) {
        panel.innerHTML = filterHtml + '<div class="sp-state"><h3>当前筛选下暂无草稿</h3><p>AI 抽取生成的报价草稿会先进入这里，经你核对修改、批准后才写入正式报价库。</p></div>';
    } else {
        const cards = items.map(function (d) {
            const matchText = d.matched_supplier_name
                ? ('已匹配：' + esc(d.matched_supplier_name))
                : '批准后将按原文名自动匹配或新建供应商';
            const actions = d.status === 'pending'
                ? '<button type="button" class="btn" data-sp-draft-edit="' + esc(String(d.id)) + '">编辑字段</button>'
                  + '<button type="button" class="btn btn-primary" data-sp-draft-approve="' + esc(String(d.id)) + '">批准入库</button>'
                  + '<button type="button" class="btn btn-danger" data-sp-draft-reject="' + esc(String(d.id)) + '">驳回</button>'
                : '<span class="sp-chip mono">' + esc(d.status === 'approved' ? '已批准入库' : '已驳回留痕') + '</span>';

            return '<div class="sp-draft">'
                + '<div class="dh"><span class="no">#' + esc(String(d.id)) + '</span>'
                + '<b>' + esc(d.supplier_name_raw || '（未识别供应商名）') + '</b>'
                + '<span class="sp-mut" style="font-size:11.5px;">' + matchText + '</span>'
                + '</div>'
                + '<div class="db">'
                + '<div class="f">'
                + '<div><div class="k">产品名</div><div class="v">' + esc(d.product_name || '—') + '</div></div>'
                + '<div><div class="k">规格型号</div><div class="v">' + esc(d.spec_model || '—') + '</div></div>'
                + '<div><div class="k">单位</div><div class="v">' + esc(d.unit || '—') + '</div></div>'
                + '<div><div class="k">币种</div><div class="v">' + esc(d.currency || 'CNY') + '</div></div>'
                + '<div><div class="k">不含税价</div><div class="v">' + _spFormatPriceCell(d.price_excl_tax, d.currency, false) + '</div></div>'
                + '<div><div class="k">含税价</div><div class="v">' + _spFormatPriceCell(d.price_incl_tax, d.currency, false) + '</div></div>'
                + '<div><div class="k">起订量 (MOQ)</div><div class="v">' + (d.moq != null ? esc(String(d.moq)) : '—') + '</div></div>'
                + '<div><div class="k">报价日期</div><div class="v">' + _spFormatQuotedAt(d.quoted_at) + '</div></div>'
                + '<div><div class="k">有效期</div><div class="v">' + esc(d.valid_until || '—') + '</div></div>'
                + '</div>'
                + '<div class="ex"><span class="sp-lbl">原文摘录</span><q>' + esc(d.raw_excerpt || '（无摘录）') + '</q>'
                + '<div class="sp-mut" style="word-break:break-all;">来源：' + esc(d.source_file) + '</div></div>'
                + '</div>'
                + '<div class="df">' + actions + '</div>'
                + '</div>';
        }).join('');
        panel.innerHTML = filterHtml + cards;
    }

    panel.querySelector('#sp-draft-st-sel').addEventListener('change', function (ev) {
        _spState.draftStatus = ev.target.value;
        _spLoadDrafts();
    });
    panel.querySelectorAll('[data-sp-draft-edit]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const did = Number(btn.getAttribute('data-sp-draft-edit'));
            const item = items.find(function (x) { return x.id === did; });
            if (item) _spOpenDraftEditModal(item);
        });
    });
    panel.querySelectorAll('[data-sp-draft-approve]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const did = Number(btn.getAttribute('data-sp-draft-approve'));
            const res = await api('POST', '/api/trade/supplier-quote-drafts/' + did + '/approve');
            if (res) {
                toast('已批准入正式报价库');
                await _spRefreshPendingCount();
                _spLoadDrafts();
            }
        });
    });
    panel.querySelectorAll('[data-sp-draft-reject]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const did = Number(btn.getAttribute('data-sp-draft-reject'));
            const res = await api('POST', '/api/trade/supplier-quote-drafts/' + did + '/reject');
            if (res) {
                toast('已驳回并留痕');
                await _spRefreshPendingCount();
                _spLoadDrafts();
            }
        });
    });
}

// ── 动态模态弹窗（增改删表单）───────────────────────────────────────────────

function _spMountModal(html) {
    _removeDynamicModals();
    const wrap = document.createElement('div');
    wrap.className = 'modal-backdrop';
    wrap.id = 'sp-dynamic-modal';
    wrap.innerHTML = '<div class="modal" style="max-width:560px;">' + html + '</div>';
    document.body.appendChild(wrap);
    wrap.querySelectorAll('[data-sp-close]').forEach(function (btn) {
        btn.addEventListener('click', function () { wrap.remove(); });
    });
    return wrap;
}

function _spOpenSupplierModal(existing) {
    const s = existing || {};
    const isEdit = !!s.id;
    const modal = _spMountModal(
        '<h3>' + (isEdit ? '编辑供应商' : '新建供应商') + '</h3>'
        + '<div class="form-group"><label>供应商全称 *</label><input type="text" id="spf-name" value="' + esc(s.name || '') + '"></div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>简称</label><input type="text" id="spf-short" value="' + esc(s.short_name || '') + '"></div>'
        + '<div class="form-group"><label>类型</label><input type="text" id="spf-type" placeholder="工厂 / 贸易商 / 工贸一体" value="' + esc(s.supplier_type || '') + '"></div>'
        + '</div>'
        + '<div class="form-group"><label>主营品类</label><input type="text" id="spf-main" value="' + esc(s.main_products || '') + '"></div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>省</label><input type="text" id="spf-prov" value="' + esc(s.province || '') + '"></div>'
        + '<div class="form-group"><label>市</label><input type="text" id="spf-city" value="' + esc(s.city || '') + '"></div>'
        + '<div class="form-group"><label>状态</label><select id="spf-status">'
        + ['候选', '洽谈中', '合作中', '暂停', '黑名单'].map(function (v) {
            return '<option value="' + esc(v) + '"' + ((s.status || '候选') === v ? ' selected' : '') + '>' + esc(v) + '</option>';
        }).join('') + '</select></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>可开专票</label><select id="spf-vat">'
        + '<option value="2"' + ((s.can_issue_vat === undefined || s.can_issue_vat === 2) ? ' selected' : '') + '>待确认</option>'
        + '<option value="1"' + (s.can_issue_vat === 1 ? ' selected' : '') + '>是</option>'
        + '<option value="0"' + (s.can_issue_vat === 0 ? ' selected' : '') + '>否</option>'
        + '</select></div>'
        + '<div class="form-group"><label>开票加点 (%)</label><input type="text" id="spf-tax" placeholder="如 8.0" value="' + (s.tax_point != null ? esc(String(s.tax_point)) : '') + '"></div>'
        + '<div class="form-group"><label>评分 (1-5)</label><input type="text" id="spf-rating" value="' + (s.rating != null ? esc(String(s.rating)) : '') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>结算方式</label><input type="text" id="spf-pay" value="' + esc(s.payment_terms || '') + '"></div>'
        + '<div class="form-group"><label>交期（天）</label><input type="text" id="spf-lead" value="' + (s.lead_time_days != null ? esc(String(s.lead_time_days)) : '') + '"></div>'
        + '</div>'
        + '<div class="form-group"><label>详细地址</label><input type="text" id="spf-addr" value="' + esc(s.address || '') + '"></div>'
        + '<div class="form-group"><label>备注</label><textarea id="spf-note">' + esc(s.note || '') + '</textarea></div>'
        + '<div class="form-actions"><button type="button" class="btn" data-sp-close="1">取消</button>'
        + '<button type="button" class="btn btn-primary" id="spf-save">保存</button></div>'
    );
    modal.querySelector('#spf-save').addEventListener('click', async function () {
        const payload = {
            name: (document.getElementById('spf-name').value || '').trim(),
            short_name: document.getElementById('spf-short').value.trim(),
            supplier_type: document.getElementById('spf-type').value.trim(),
            main_products: document.getElementById('spf-main').value.trim(),
            province: document.getElementById('spf-prov').value.trim(),
            city: document.getElementById('spf-city').value.trim(),
            status: document.getElementById('spf-status').value,
            can_issue_vat: Number(document.getElementById('spf-vat').value),
            tax_point: document.getElementById('spf-tax').value.trim() || null,
            rating: document.getElementById('spf-rating').value.trim() || null,
            payment_terms: document.getElementById('spf-pay').value.trim(),
            lead_time_days: document.getElementById('spf-lead').value.trim() || null,
            address: document.getElementById('spf-addr').value.trim(),
            note: document.getElementById('spf-note').value.trim(),
        };
        if (!payload.name) { toast('请填写供应商全称'); return; }
        const res = isEdit
            ? await api('PUT', '/api/trade/suppliers/' + s.id, payload)
            : await api('POST', '/api/trade/suppliers', payload);
        if (res) {
            modal.remove();
            if (res.duplicate_warning) toast(res.duplicate_warning, { sticky: true });
            else toast(isEdit ? '已更新供应商' : '已新建供应商');
            if (_spState.selectedSupplierId) _spOpenDetail(_spState.selectedSupplierId);
            else _spLoadSuppliers();
        }
    });
}

function _spOpenDeleteSupplierModal(d) {
    const modal = _spMountModal(
        '<h3>确认删除供应商</h3>'
        + '<div class="sp-warn-box">将永久删除供应商 <b>' + esc(d.name) + '</b>，并级联删除其全部 '
        + '<b>' + esc(String((d.contacts || []).length)) + '</b> 位联系人、'
        + '<b>' + esc(String((d.products || []).length)) + '</b> 条产品能力及 '
        + '<b>' + esc(String(d.quotes_total || 0)) + '</b> 条报价历史，删除后不可恢复。</div>'
        + '<div class="form-actions"><button type="button" class="btn" data-sp-close="1">取消</button>'
        + '<button type="button" class="btn btn-danger" id="sp-confirm-del">确认级联删除</button></div>'
    );
    modal.querySelector('#sp-confirm-del').addEventListener('click', async function () {
        const res = await api('DELETE', '/api/trade/suppliers/' + d.id);
        if (res) {
            modal.remove();
            toast('已删除供应商');
            _spState.selectedSupplierId = null;
            _spState.detail = null;
            _spRenderBody();
            _spLoadSuppliers();
        }
    });
}

function _spOpenContactModal(supplierId, existing) {
    const c = existing || {};
    const isEdit = !!c.id;
    const modal = _spMountModal(
        '<h3>' + (isEdit ? '编辑联系人' : '新增联系人') + '</h3>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>姓名 *</label><input type="text" id="spc-name" value="' + esc(c.name || '') + '"></div>'
        + '<div class="form-group"><label>角色</label><input type="text" id="spc-role" placeholder="老板/业务报价/跟单/财务/仓储" value="' + esc(c.role || '业务报价') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>电话</label><input type="text" id="spc-phone" value="' + esc(c.phone || '') + '"></div>'
        + '<div class="form-group"><label>微信</label><input type="text" id="spc-wechat" value="' + esc(c.wechat || '') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>邮箱</label><input type="text" id="spc-email" value="' + esc(c.email || '') + '"></div>'
        + '<div class="form-group"><label>QQ</label><input type="text" id="spc-qq" value="' + esc(c.qq || '') + '"></div>'
        + '</div>'
        + '<div class="form-group"><label><input type="checkbox" id="spc-primary"' + (c.is_primary ? ' checked' : '') + '> 设为主联系人（将自动取消同供应商其他主联系人）</label></div>'
        + '<div class="form-group"><label>备注</label><input type="text" id="spc-note" value="' + esc(c.note || '') + '"></div>'
        + '<div class="form-actions"><button type="button" class="btn" data-sp-close="1">取消</button>'
        + '<button type="button" class="btn btn-primary" id="spc-save">保存</button></div>'
    );
    modal.querySelector('#spc-save').addEventListener('click', async function () {
        const payload = {
            name: document.getElementById('spc-name').value.trim(),
            role: document.getElementById('spc-role').value.trim() || '其他',
            phone: document.getElementById('spc-phone').value.trim(),
            wechat: document.getElementById('spc-wechat').value.trim(),
            email: document.getElementById('spc-email').value.trim(),
            qq: document.getElementById('spc-qq').value.trim(),
            is_primary: document.getElementById('spc-primary').checked ? 1 : 0,
            note: document.getElementById('spc-note').value.trim(),
        };
        if (!payload.name) { toast('请填写联系人姓名'); return; }
        const res = isEdit
            ? await api('PUT', '/api/trade/suppliers/contacts/' + c.id, payload)
            : await api('POST', '/api/trade/suppliers/' + supplierId + '/contacts', payload);
        if (res) { modal.remove(); _spOpenDetail(supplierId); }
    });
}

function _spOpenProductModal(supplierId, existing) {
    const p = existing || {};
    const isEdit = !!p.id;
    const modal = _spMountModal(
        '<h3>' + (isEdit ? '编辑产品能力' : '登记产品能力（同品名+规格自动更新）') + '</h3>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>产品名 *</label><input type="text" id="spp-name" value="' + esc(p.product_name || '') + '"></div>'
        + '<div class="form-group"><label>规格型号</label><input type="text" id="spp-spec" value="' + esc(p.spec_model || '') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>单位</label><input type="text" id="spp-unit" placeholder="件 / kg / 台" value="' + esc(p.unit || '') + '"></div>'
        + '<div class="form-group"><label>是否自产</label><select id="spp-self">'
        + '<option value="2"' + ((p.is_self_produced === undefined || p.is_self_produced === 2) ? ' selected' : '') + '>待确认</option>'
        + '<option value="1"' + (p.is_self_produced === 1 ? ' selected' : '') + '>是（自产）</option>'
        + '<option value="0"' + (p.is_self_produced === 0 ? ' selected' : '') + '>否（外协/调货）</option>'
        + '</select></div>'
        + '<div class="form-group"><label>MOQ</label><input type="text" id="spp-moq" value="' + (p.moq != null ? esc(String(p.moq)) : '') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>交期天数</label><input type="text" id="spp-days" value="' + (p.lead_time_days != null ? esc(String(p.lead_time_days)) : '') + '"></div>'
        + '<div class="form-group"><label>交期说明</label><input type="text" id="spp-ltxt" placeholder="如 旺季 20 天" value="' + esc(p.lead_time_text || '') + '"></div>'
        + '</div>'
        + '<div class="form-group"><label>质量备注</label><input type="text" id="spp-qual" value="' + esc(p.quality_note || '') + '"></div>'
        + '<div class="form-group"><label>包装信息</label><input type="text" id="spp-pack" value="' + esc(p.packing_info || '') + '"></div>'
        + '<div class="form-actions"><button type="button" class="btn" data-sp-close="1">取消</button>'
        + '<button type="button" class="btn btn-primary" id="spp-save">保存</button></div>'
    );
    modal.querySelector('#spp-save').addEventListener('click', async function () {
        const payload = {
            product_name: document.getElementById('spp-name').value.trim(),
            spec_model: document.getElementById('spp-spec').value.trim(),
            unit: document.getElementById('spp-unit').value.trim(),
            is_self_produced: Number(document.getElementById('spp-self').value),
            moq: document.getElementById('spp-moq').value.trim() || null,
            lead_time_days: document.getElementById('spp-days').value.trim() || null,
            lead_time_text: document.getElementById('spp-ltxt').value.trim(),
            quality_note: document.getElementById('spp-qual').value.trim(),
            packing_info: document.getElementById('spp-pack').value.trim(),
        };
        if (!payload.product_name) { toast('请填写产品名'); return; }
        const res = isEdit
            ? await api('PUT', '/api/trade/supplier-products/' + p.id, payload)
            : await api('POST', '/api/trade/suppliers/' + supplierId + '/products', payload);
        if (res) { modal.remove(); _spOpenDetail(supplierId); }
    });
}

function _spOpenQuoteModal(supplierId, existing) {
    const q = existing || {};
    const isEdit = !!q.id;
    const modal = _spMountModal(
        '<h3>' + (isEdit ? '修改报价（纠错）' : '追加报价（不覆盖历史）') + '</h3>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>产品名 *</label><input type="text" id="spq-name" value="' + esc(q.product_name || '') + '"></div>'
        + '<div class="form-group"><label>规格型号</label><input type="text" id="spq-spec" placeholder="设备类可写年份/工时/配置" value="' + esc(q.spec_model || '') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>单位</label><input type="text" id="spq-unit" value="' + esc(q.unit || '') + '"></div>'
        + '<div class="form-group"><label>币种</label><input type="text" id="spq-cur" value="' + esc(q.currency || 'CNY') + '"></div>'
        + '<div class="form-group"><label>MOQ</label><input type="text" id="spq-moq" value="' + (q.moq != null ? esc(String(q.moq)) : '') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>不含税价</label><input type="text" id="spq-excl" value="' + (q.price_excl_tax != null ? esc(String(q.price_excl_tax)) : '') + '"></div>'
        + '<div class="form-group"><label>含税价</label><input type="text" id="spq-incl" value="' + (q.price_incl_tax != null ? esc(String(q.price_incl_tax)) : '') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>报价日期</label><input type="date" id="spq-date" value="' + esc(q.quoted_at || '') + '"></div>'
        + '<div class="form-group"><label>有效期至</label><input type="date" id="spq-valid" value="' + esc(q.valid_until || '') + '"></div>'
        + '</div>'
        + '<div class="form-group"><label>备注</label><input type="text" id="spq-notes" value="' + esc(q.notes || '') + '"></div>'
        + '<div class="form-actions"><button type="button" class="btn" data-sp-close="1">取消</button>'
        + '<button type="button" class="btn btn-primary" id="spq-save">保存</button></div>'
    );
    modal.querySelector('#spq-save').addEventListener('click', async function () {
        const payload = {
            product_name: document.getElementById('spq-name').value.trim(),
            spec_model: document.getElementById('spq-spec').value.trim(),
            unit: document.getElementById('spq-unit').value.trim(),
            currency: document.getElementById('spq-cur').value.trim() || 'CNY',
            moq: document.getElementById('spq-moq').value.trim() || null,
            price_excl_tax: document.getElementById('spq-excl').value.trim() || null,
            price_incl_tax: document.getElementById('spq-incl').value.trim() || null,
            quoted_at: document.getElementById('spq-date').value.trim(),
            valid_until: document.getElementById('spq-valid').value.trim(),
            notes: document.getElementById('spq-notes').value.trim(),
        };
        if (!payload.product_name) { toast('请填写产品名'); return; }
        const res = isEdit
            ? await api('PUT', '/api/trade/supplier-quotes/' + q.id, payload)
            : await api('POST', '/api/trade/suppliers/' + supplierId + '/quotes', payload);
        if (res) { modal.remove(); _spOpenDetail(supplierId); }
    });
}

function _spOpenDraftEditModal(d) {
    const modal = _spMountModal(
        '<h3>编辑草稿 #' + esc(String(d.id)) + '</h3>'
        + '<div class="form-group"><label>供应商名称</label><input type="text" id="spd-sup" value="' + esc(d.supplier_name_raw || '') + '"></div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>产品名</label><input type="text" id="spd-prod" value="' + esc(d.product_name || '') + '"></div>'
        + '<div class="form-group"><label>规格型号</label><input type="text" id="spd-spec" value="' + esc(d.spec_model || '') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>单位</label><input type="text" id="spd-unit" value="' + esc(d.unit || '') + '"></div>'
        + '<div class="form-group"><label>不含税价</label><input type="text" id="spd-excl" value="' + (d.price_excl_tax != null ? esc(String(d.price_excl_tax)) : '') + '"></div>'
        + '<div class="form-group"><label>含税价</label><input type="text" id="spd-incl" value="' + (d.price_incl_tax != null ? esc(String(d.price_incl_tax)) : '') + '"></div>'
        + '<div class="form-group"><label>起订量 (MOQ)</label><input type="text" id="spd-moq" value="' + (d.moq != null ? esc(String(d.moq)) : '') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>报价日期</label><input type="text" id="spd-date" value="' + esc(d.quoted_at || '') + '"></div>'
        + '<div class="form-group"><label>有效期</label><input type="text" id="spd-valid" value="' + esc(d.valid_until || '') + '"></div>'
        + '</div>'
        + '<div class="form-actions"><button type="button" class="btn" data-sp-close="1">取消</button>'
        + '<button type="button" class="btn btn-primary" id="spd-save">保存草稿</button></div>'
    );
    modal.querySelector('#spd-save').addEventListener('click', async function () {
        const payload = {
            supplier_name_raw: document.getElementById('spd-sup').value.trim(),
            product_name: document.getElementById('spd-prod').value.trim(),
            spec_model: document.getElementById('spd-spec').value.trim(),
            unit: document.getElementById('spd-unit').value.trim(),
            price_excl_tax: document.getElementById('spd-excl').value.trim() || null,
            price_incl_tax: document.getElementById('spd-incl').value.trim() || null,
            moq: document.getElementById('spd-moq').value.trim() || null,
            quoted_at: document.getElementById('spd-date').value.trim(),
            valid_until: document.getElementById('spd-valid').value.trim(),
        };
        const res = await api('PUT', '/api/trade/supplier-quote-drafts/' + d.id, payload);
        if (res) { modal.remove(); _spLoadDrafts(); }
    });
}

// ── 采购询价页签（供应商管理一期 · 第二批）───────────────────────────────────

async function _spLoadRfqs() {
    const f = _spState.rfqFilters;
    const qs = new URLSearchParams();
    if (f.status) qs.set('status', f.status);
    if (f.q) qs.set('q', f.q);
    const url = '/api/trade/rfqs' + (qs.toString() ? '?' + qs.toString() : '');
    const res = await api('GET', url);
    if (Array.isArray(res)) {
        _spState.rfqs = res;
        if (_spState.tab === 'rfqs' && !_spState.selectedRfqId) {
            _spRenderBody();
        }
    }
}

function _spRenderRfqsList(body) {
    const f = _spState.rfqFilters;
    body.innerHTML =
        '<div class="sp-bar">'
        + '<input type="text" id="rfq-q" placeholder="搜索采购询价产品名 / 主题..." value="' + esc(f.q) + '" style="flex:1;min-width:220px;">'
        + '<select id="rfq-status-filter">'
        + '<option value=""' + (f.status === '' ? ' selected' : '') + '>全部状态</option>'
        + '<option value="open"' + (f.status === 'open' ? ' selected' : '') + '>待回复</option>'
        + '<option value="decided"' + (f.status === 'decided' ? ' selected' : '') + '>已选厂</option>'
        + '</select>'
        + '<button type="button" class="btn" id="rfq-search-btn">筛选</button>'
        + '<button type="button" class="btn btn-primary" id="rfq-new-btn">' + btnIcon('plus') + ' 新建采购询价</button>'
        + '</div>'
        + '<div class="sp-table-wrap"><table class="sp-table">'
        + '<thead><tr><th>产品 / 规格</th><th style="width:100px;">数量</th><th style="width:140px;">关联客户</th><th style="width:110px;">回复进度</th><th style="width:140px;">选中供应商</th><th style="width:90px;">状态</th></tr></thead>'
        + '<tbody>' + _spBuildRfqRowsHtml(_spState.rfqs) + '</tbody></table></div>';

    const applyFilter = function () {
        _spState.rfqFilters.q = (document.getElementById('rfq-q')?.value || '').trim();
        _spState.rfqFilters.status = document.getElementById('rfq-status-filter')?.value || '';
        _spLoadRfqs();
    };
    body.querySelector('#rfq-search-btn').addEventListener('click', applyFilter);
    body.querySelector('#rfq-status-filter').addEventListener('change', applyFilter);
    body.querySelector('#rfq-q').addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') applyFilter();
    });
    body.querySelector('#rfq-new-btn').addEventListener('click', function () {
        _spOpenRfqModal(null);
    });
    body.querySelectorAll('[data-rfq-open]').forEach(function (tr) {
        tr.addEventListener('click', function () {
            const rid = Number(tr.getAttribute('data-rfq-open'));
            _spOpenRfqDetail(rid);
        });
    });
}

async function _spOpenRfqDetail(rfqId) {
    const detail = await api('GET', '/api/trade/rfqs/' + rfqId);
    if (!detail) return;
    if (!_spState.suppliers || !_spState.suppliers.length) {
        const sups = await api('GET', '/api/trade/suppliers', null, null, { silent: true });
        if (Array.isArray(sups)) _spState.suppliers = sups;
    }
    _spState.selectedRfqId = rfqId;
    _spState.rfqDetail = detail;
    _spRenderBody();
}

function _spRenderRfqDetail(body, d) {
    const qtyText = (d.quantity !== null && d.quantity !== undefined && d.quantity !== '')
        ? (esc(String(d.quantity)) + (d.unit ? ' ' + esc(d.unit) : ''))
        : (d.unit ? esc(d.unit) : '—');
    const supOpts = (_spState.suppliers || []).map(function (s) {
        return '<option value="' + esc(String(s.id)) + '">' + esc(s.name) + '</option>';
    }).join('');

    body.innerHTML =
        '<div class="sp-detail-head">'
        + '<button type="button" class="btn" id="rfq-back-btn">' + btnIcon('arrow-left') + ' 返回采购询价列表</button>'
        + '<h3 style="margin:0;font-size:15px;">' + esc(d.product_name) + (d.spec_model ? '（' + esc(d.spec_model) + '）' : '') + '</h3>'
        + _spFormatRfqStatus(d.status)
        + '<div style="margin-left:auto;display:flex;gap:8px;">'
        + '<button type="button" class="btn" id="rfq-edit-btn">编辑采购询价</button>'
        + '<button type="button" class="btn btn-danger" id="rfq-del-btn">删除采购询价</button>'
        + '</div></div>'
        + '<div class="sp-sec" style="margin-bottom:12px;">'
        + '<div class="sp-kv">'
        + '<div class="k">询价主题</div><div class="v">' + esc(d.title || '—') + '</div>'
        + '<div class="k">数量 / 单位</div><div class="v">' + qtyText + '</div>'
        + '<div class="k">目标交期</div><div class="v">' + esc(d.target_delivery_date || '—') + '</div>'
        + '<div class="k">关联客户</div><div class="v">' + esc(d.customer_name || '—') + '</div>'
        + '<div class="k">关联询盘</div><div class="v">' + esc(d.inquiry_title || (d.inquiry_id ? ('#' + String(d.inquiry_id)) : '—')) + '</div>'
        + '<div class="k">备注</div><div class="v">' + esc(d.note || '—') + '</div>'
        + '</div></div>'
        + '<div class="sp-sec">'
        + '<div class="sp-sec-h"><span class="t">供应商回复（已回 ' + esc(String(d.responded_count || 0)) + ' / 共 ' + esc(String(d.total_responses || 0)) + '）</span>'
        + '<div class="acts" style="display:flex;gap:6px;align-items:center;">'
        + '<select id="rfq-add-sup-sel" style="min-width:180px;"><option value="">选择本公司供应商...</option>' + supOpts + '</select>'
        + '<button type="button" class="btn btn-primary" id="rfq-add-sup-btn">+ 添加供应商</button>'
        + '</div></div>'
        + '<div class="sp-table-wrap"><table class="sp-table">'
        + '<thead><tr><th>供应商</th><th style="width:92px;">是否已回</th><th style="width:96px;">不含税价</th><th style="width:150px;">含税价 / 币种</th><th style="width:165px;">交期</th><th style="width:82px;">MOQ</th><th>备注</th><th style="width:160px;">操作</th></tr></thead>'
        + '<tbody>' + _spBuildRfqResponsesHtml(d.responses || []) + '</tbody></table></div></div>';

    body.querySelector('#rfq-back-btn').addEventListener('click', function () {
        _spState.selectedRfqId = null;
        _spState.rfqDetail = null;
        _spRenderBody();
        _spLoadRfqs();
    });
    body.querySelector('#rfq-edit-btn').addEventListener('click', function () {
        _spOpenRfqModal(d);
    });
    body.querySelector('#rfq-del-btn').addEventListener('click', async function () {
        if (!confirm('确认删除该采购询价单？（其回复行与已沉淀的询价报价将一并删除）')) return;
        const ok = await api('DELETE', '/api/trade/rfqs/' + d.id);
        if (ok) {
            toast('已删除采购询价单');
            _spState.selectedRfqId = null;
            _spState.rfqDetail = null;
            _spRenderBody();
            _spLoadRfqs();
        }
    });
    body.querySelector('#rfq-add-sup-btn').addEventListener('click', async function () {
        const sid = document.getElementById('rfq-add-sup-sel')?.value || '';
        if (!sid) { toast('请先选择要加入的供应商'); return; }
        const res = await api('POST', '/api/trade/rfqs/' + d.id + '/responses', { supplier_id: Number(sid) });
        if (res) {
            toast('已加入采购询价单');
            _spOpenRfqDetail(d.id);
        }
    });

    body.querySelectorAll('[data-rfq-save]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const rid = Number(btn.getAttribute('data-rfq-save'));
            const tr = body.querySelector('[data-rfq-resp-row="' + rid + '"]');
            if (!tr) return;
            const val = function (k) {
                const el = tr.querySelector('[data-rfq-f="' + k + '"]');
                return el ? el.value.trim() : '';
            };
            const respCb = tr.querySelector('[data-rfq-f="responded"]');
            const payload = {
                responded: respCb && respCb.checked ? 1 : 0,
                price_excl_tax: val('price_excl_tax') || null,
                price_incl_tax: val('price_incl_tax') || null,
                currency: val('currency') || 'CNY',
                lead_time_days: val('lead_time_days') || null,
                lead_time_text: val('lead_time_text'),
                moq: val('moq') || null,
                notes: val('notes'),
            };
            const res = await api('PUT', '/api/trade/rfq-responses/' + rid, payload);
            if (res) {
                toast('已保存供应商回复');
                _spOpenRfqDetail(d.id);
            }
        });
    });

    body.querySelectorAll('[data-rfq-select]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const rid = Number(btn.getAttribute('data-rfq-select'));
            const res = await api('POST', '/api/trade/rfq-responses/' + rid + '/select');
            if (res) {
                toast('已选定该供应商');
                _spOpenRfqDetail(d.id);
            }
        });
    });

    body.querySelectorAll('[data-rfq-unselect]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const rid = Number(btn.getAttribute('data-rfq-unselect'));
            const res = await api('POST', '/api/trade/rfq-responses/' + rid + '/unselect');
            if (res) {
                toast('已取消选定');
                _spOpenRfqDetail(d.id);
            }
        });
    });

    body.querySelectorAll('[data-rfq-del]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const rid = Number(btn.getAttribute('data-rfq-del'));
            if (!confirm('确认删除该回复行？（已沉淀报价将同步删除）')) return;
            const ok = await api('DELETE', '/api/trade/rfq-responses/' + rid);
            if (ok) {
                toast('已删除回复行');
                _spOpenRfqDetail(d.id);
            }
        });
    });
}

async function _spOpenRfqModal(existing) {
    const r = existing || {};
    const isEdit = !!r.id;
    const inqs = await api('GET', '/api/trade/rfqs/inquiries', null, null, { silent: true });
    _spState.companyInquiries = Array.isArray(inqs) ? inqs : [];
    const inqOpts = '<option value="">不关联询盘</option>' + _spState.companyInquiries.map(function (iq) {
        const label = (iq.title || ('询盘 #' + iq.id)) + (iq.customer_name ? (' — ' + iq.customer_name) : '');
        const sel = (r.inquiry_id && Number(r.inquiry_id) === Number(iq.id)) ? ' selected' : '';
        return '<option value="' + esc(String(iq.id)) + '" data-cust-id="' + esc(String(iq.customer_id || '')) + '" data-cust-name="' + esc(iq.customer_name || '') + '"' + sel + '>' + esc(label) + '</option>';
    }).join('');

    const modal = _spMountModal(
        '<h3>' + (isEdit ? '编辑采购询价' : '新建采购询价') + '</h3>'
        + '<div class="form-group"><label>询价主题（可选）</label><input type="text" id="rfqf-title" placeholder="如：德客 Q4 阀门采购询价" value="' + esc(r.title || '') + '"></div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>产品名称 *</label><input type="text" id="rfqf-prod" value="' + esc(r.product_name || '') + '"></div>'
        + '<div class="form-group"><label>规格型号</label><input type="text" id="rfqf-spec" value="' + esc(r.spec_model || '') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>数量</label><input type="text" id="rfqf-qty" value="' + (r.quantity != null ? esc(String(r.quantity)) : '') + '"></div>'
        + '<div class="form-group"><label>单位</label><input type="text" id="rfqf-unit" placeholder="件 / 台 / kg" value="' + esc(r.unit || '') + '"></div>'
        + '<div class="form-group"><label>目标交期</label><input type="date" id="rfqf-date" value="' + esc(r.target_delivery_date || '') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>关联客户询盘</label><select id="rfqf-inq">' + inqOpts + '</select></div>'
        + '<div class="form-group"><label>关联客户（选询盘自动带出）</label><input type="text" id="rfqf-cust-name" readonly value="' + esc(r.customer_name || '') + '" placeholder="选择询盘后自动带出"><input type="hidden" id="rfqf-cust-id" value="' + (r.customer_id != null ? esc(String(r.customer_id)) : '') + '"></div>'
        + '</div>'
        + '<div class="form-group"><label>备注</label><textarea id="rfqf-note">' + esc(r.note || '') + '</textarea></div>'
        + '<div class="form-actions"><button type="button" class="btn" data-sp-close="1">取消</button>'
        + '<button type="button" class="btn btn-primary" id="rfqf-save">保存</button></div>'
    );

    const inqSel = modal.querySelector('#rfqf-inq');
    inqSel.addEventListener('change', function () {
        const opt = inqSel.options[inqSel.selectedIndex];
        const cid = opt ? (opt.getAttribute('data-cust-id') || '') : '';
        const cname = opt ? (opt.getAttribute('data-cust-name') || '') : '';
        modal.querySelector('#rfqf-cust-id').value = cid;
        modal.querySelector('#rfqf-cust-name').value = cname;
    });

    modal.querySelector('#rfqf-save').addEventListener('click', async function () {
        const inqVal = modal.querySelector('#rfqf-inq').value.trim();
        const custVal = modal.querySelector('#rfqf-cust-id').value.trim();
        const payload = {
            title: modal.querySelector('#rfqf-title').value.trim(),
            product_name: modal.querySelector('#rfqf-prod').value.trim(),
            spec_model: modal.querySelector('#rfqf-spec').value.trim(),
            quantity: modal.querySelector('#rfqf-qty').value.trim() || null,
            unit: modal.querySelector('#rfqf-unit').value.trim(),
            target_delivery_date: modal.querySelector('#rfqf-date').value.trim(),
            inquiry_id: inqVal ? Number(inqVal) : null,
            customer_id: custVal ? Number(custVal) : null,
            note: modal.querySelector('#rfqf-note').value.trim(),
        };
        if (!payload.product_name) { toast('请填写产品名称'); return; }
        const res = isEdit
            ? await api('PUT', '/api/trade/rfqs/' + r.id, payload)
            : await api('POST', '/api/trade/rfqs', payload);
        if (res) {
            modal.remove();
            toast(isEdit ? '已更新采购询价单' : '已新建采购询价单');
            if (_spState.selectedRfqId) _spOpenRfqDetail(_spState.selectedRfqId);
            else _spLoadRfqs();
        }
    });
}

// ── 采购单页签（供应商管理一期 · 第三批）─────────────────────────────────────

async function _spLoadPos() {
    if (!_spState.suppliers || !_spState.suppliers.length) {
        const sups = await api('GET', '/api/trade/suppliers', null, null, { silent: true });
        if (Array.isArray(sups)) _spState.suppliers = sups;
    }
    const f = _spState.poFilters;
    const qs = new URLSearchParams();
    if (f.status) qs.set('status', f.status);
    if (f.supplier_id) qs.set('supplier_id', f.supplier_id);
    if (f.q) qs.set('q', f.q);
    const url = '/api/trade/purchase-orders' + (qs.toString() ? '?' + qs.toString() : '');
    const res = await api('GET', url);
    if (Array.isArray(res)) {
        _spState.pos = res;
        if (_spState.tab === 'pos' && !_spState.selectedPoId) {
            _spRenderBody();
        }
    }
}

function _spRenderPosList(body) {
    const f = _spState.poFilters;
    const statuses = ['', '已下单', '生产中', '待出货', '已出货', '完成'];
    const stOpts = statuses.map(function (s) {
        return '<option value="' + esc(s) + '"' + (f.status === s ? ' selected' : '') + '>' + esc(s || '全部状态') + '</option>';
    }).join('');
    const supOpts = '<option value="">全部供应商</option>' + (_spState.suppliers || []).map(function (s) {
        const sel = String(f.supplier_id) === String(s.id) ? ' selected' : '';
        return '<option value="' + esc(String(s.id)) + '"' + sel + '>' + esc(s.name) + '</option>';
    }).join('');

    body.innerHTML =
        '<div class="sp-bar">'
        + '<input type="text" id="po-q" placeholder="搜索采购单号 / 产品名 / 客户订单号..." value="' + esc(f.q) + '" style="flex:1;min-width:220px;">'
        + '<select id="po-status-filter">' + stOpts + '</select>'
        + '<select id="po-sup-filter">' + supOpts + '</select>'
        + '<button type="button" class="btn" id="po-search-btn">筛选</button>'
        + '<button type="button" class="btn" id="po-from-rfq-btn">从询价单生成</button>'
        + '<button type="button" class="btn btn-primary" id="po-new-btn">' + btnIcon('plus') + ' 新建采购单</button>'
        + '</div>'
        + '<div class="sp-table-wrap"><table class="sp-table">'
        + '<thead><tr><th style="width:105px;">采购单号</th><th>供应商</th><th>产品 / 规格</th><th style="width:130px;">关联客户订单</th><th style="width:110px;">金额</th><th style="width:105px;">约定交期</th><th style="width:86px;">状态</th></tr></thead>'
        + '<tbody>' + _spBuildPoRowsHtml(_spState.pos) + '</tbody></table></div>';

    const applyFilter = function () {
        _spState.poFilters.q = (document.getElementById('po-q')?.value || '').trim();
        _spState.poFilters.status = document.getElementById('po-status-filter')?.value || '';
        _spState.poFilters.supplier_id = document.getElementById('po-sup-filter')?.value || '';
        _spLoadPos();
    };
    body.querySelector('#po-search-btn').addEventListener('click', applyFilter);
    body.querySelector('#po-status-filter').addEventListener('change', applyFilter);
    body.querySelector('#po-sup-filter').addEventListener('change', applyFilter);
    body.querySelector('#po-q').addEventListener('keydown', function (ev) { if (ev.key === 'Enter') applyFilter(); });
    body.querySelector('#po-new-btn').addEventListener('click', function () { _spOpenPoModal(null); });
    body.querySelector('#po-from-rfq-btn').addEventListener('click', function () { _spOpenPoFromRfqModal(); });
    body.querySelectorAll('[data-po-open]').forEach(function (tr) {
        tr.addEventListener('click', function () {
            const pid = Number(tr.getAttribute('data-po-open'));
            _spOpenPoDetail(pid);
        });
    });
}

async function _spOpenPoDetail(poId) {
    const detail = await api('GET', '/api/trade/purchase-orders/' + poId);
    if (!detail) return;
    _spState.selectedPoId = poId;
    _spState.poDetail = detail;
    _spRenderBody();
}

function _spRenderPoDetail(body, d) {
    const qtyText = (d.quantity !== null && d.quantity !== undefined && d.quantity !== '')
        ? (esc(String(d.quantity)) + (d.unit ? ' ' + esc(d.unit) : ''))
        : (d.unit ? esc(d.unit) : '—');
    const amtText = (d.amount !== null && d.amount !== undefined && d.amount !== '')
        ? (esc(d.currency || 'CNY') + ' ' + esc(String(d.amount)))
        : '—';
    const ordText = d.order_display_no
        ? (esc(d.order_display_no) + (d.customer_name ? ('（' + esc(d.customer_name) + '）') : ''))
        : '—';
    const consList = (d.consolidations && d.consolidations.length)
        ? d.consolidations.map(function (c) {
            return '<span class="sp-chip">' + esc(c.code || ('CG' + c.id)) + (c.cutoff_date ? (' · 截关 ' + esc(c.cutoff_date)) : '') + '</span>';
        }).join(' ')
        : '<span class="sp-mut">未加入拼柜</span>';
    const contact = d.primary_contact;
    const contactText = contact
        ? [contact.name, contact.phone, contact.wechat ? ('微信:' + contact.wechat) : ''].filter(Boolean).join(' · ')
        : '—';

    body.innerHTML =
        '<div class="sp-detail-head">'
        + '<button type="button" class="btn" id="po-back-btn">' + btnIcon('arrow-left') + ' 返回采购单列表</button>'
        + '<h3 style="margin:0;font-size:15px;">' + esc(d.po_no || ('PO' + d.id)) + ' · ' + esc(d.product_name) + '</h3>'
        + _spFormatPoStatus(d.status)
        + '<div style="margin-left:auto;display:flex;gap:8px;">'
        + '<button type="button" class="btn" id="po-todo-btn">+ 生成待办</button>'
        + '<button type="button" class="btn" id="po-edit-btn">编辑采购单</button>'
        + '<button type="button" class="btn btn-danger" id="po-del-btn">删除采购单</button>'
        + '</div></div>'
        + '<div class="sp-sec" style="margin-bottom:12px;">'
        + '<div class="sp-sec-h"><span class="t">采购单信息</span></div>'
        + '<div class="sp-kv">'
        + '<div class="k">采购单号</div><div class="v sp-num"><b>' + esc(d.po_no || ('PO' + d.id)) + '</b></div>'
        + '<div class="k">供应商</div><div class="v">' + esc(d.supplier_name || '') + '</div>'
        + '<div class="k">主联系人</div><div class="v">' + esc(contactText) + '</div>'
        + '<div class="k">产品 / 规格</div><div class="v">' + esc(d.product_name) + (d.spec_model ? ('（' + esc(d.spec_model) + '）') : '') + '</div>'
        + '<div class="k">数量 / 金额</div><div class="v">' + qtyText + ' · ' + amtText + '</div>'
        + '<div class="k">下单日 / 约定交期</div><div class="v sp-num">' + esc(d.ordered_at || '—') + ' / ' + esc(d.promised_date || '—') + '</div>'
        + '<div class="k">关联客户订单</div><div class="v">' + ordText + '</div>'
        + '<div class="k">所在拼柜</div><div class="v">' + consList + '</div>'
        + '<div class="k">备注</div><div class="v">' + esc(d.note || '—') + '</div>'
        + '</div></div>'
        + '<div class="sp-sec">'
        + '<div class="sp-sec-h"><span class="t">催货话术草稿（仅生成文本，需手动复制发送）</span></div>'
        + '<div style="display:flex;gap:8px;flex-wrap:wrap;padding:6px 0;">'
        + '<button type="button" class="btn" data-po-draft="upcoming">临期提醒话术</button>'
        + '<button type="button" class="btn" data-po-draft="overdue">逾期催货话术</button>'
        + '<button type="button" class="btn" data-po-draft="cutoff">拼柜截关催货话术</button>'
        + '</div></div>';

    body.querySelector('#po-back-btn').addEventListener('click', function () {
        _spState.selectedPoId = null;
        _spState.poDetail = null;
        _spRenderBody();
        _spLoadPos();
    });
    body.querySelector('#po-edit-btn').addEventListener('click', function () { _spOpenPoModal(d); });
    body.querySelector('#po-del-btn').addEventListener('click', async function () {
        if (!confirm('确认删除该采购单？（拼柜明细将同步移出，拼柜本身不受影响）')) return;
        const ok = await api('DELETE', '/api/trade/purchase-orders/' + d.id);
        if (ok) {
            toast('已删除采购单');
            _spState.selectedPoId = null;
            _spState.poDetail = null;
            _spRenderBody();
            _spLoadPos();
        }
    });
    body.querySelector('#po-todo-btn').addEventListener('click', async function () {
        const todayIso = new Date().toISOString().slice(0, 10);
        const pDate = (d.promised_date || '').trim();
        const title = '催货：' + (d.supplier_name || '') + ' ' + (d.product_name || '')
            + '（采购单 ' + (d.po_no || ('PO' + d.id)) + '，约定交期 ' + (pDate || '待定') + '）';
        const res = await api('POST', '/api/trade/todos', {
            title: title,
            due_date: pDate || todayIso,
        });
        if (res) {
            toast('已加入待办清单');
            if (typeof loadTodos === 'function') loadTodos(true);
        }
    });
    body.querySelectorAll('[data-po-draft]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const variant = btn.getAttribute('data-po-draft');
            const res = await api('POST', '/api/trade/purchase-orders/' + d.id + '/followup-draft', { variant: variant });
            if (res && res.text) {
                _spOpenFollowupDraftModal(res.text);
            }
        });
    });
}

function _spOpenFollowupDraftModal(text) {
    const modal = _spMountModal(
        '<h3>催货话术（草稿，需你手动发送）</h3>'
        + '<div class="form-group"><textarea id="sp-followup-text" rows="6" style="width:100%;font-size:13px;line-height:1.6;">' + esc(text) + '</textarea></div>'
        + '<div class="form-actions"><button type="button" class="btn" data-sp-close="1">关闭</button>'
        + '<button type="button" class="btn btn-primary" id="sp-followup-copy">复制话术</button></div>'
    );
    modal.querySelector('#sp-followup-copy').addEventListener('click', async function () {
        const val = modal.querySelector('#sp-followup-text').value;
        try {
            await navigator.clipboard.writeText(val);
            toast('已复制到剪贴板，请手动发送');
        } catch (_e) {
            modal.querySelector('#sp-followup-text').select();
            document.execCommand('copy');
            toast('已复制，请手动发送');
        }
    });
}

async function _spOpenPoFromRfqModal() {
    const decided = await api('GET', '/api/trade/rfqs?status=decided');
    if (!Array.isArray(decided)) return;
    if (!decided.length) {
        toast('暂无「已选厂」的采购询价单，请先在采购询价页签选定供应商');
        return;
    }
    const opts = decided.map(function (r) {
        const lbl = '#' + r.id + ' ' + r.product_name + (r.spec_model ? (' (' + r.spec_model + ')') : '')
            + (r.selected_supplier_name ? (' — ' + r.selected_supplier_name) : '');
        return '<option value="' + esc(String(r.id)) + '">' + esc(lbl) + '</option>';
    }).join('');
    const modal = _spMountModal(
        '<h3>从已选厂采购询价单生成采购单</h3>'
        + '<div class="form-group"><label>选择已选厂的采购询价单</label><select id="po-rfq-sel">' + opts + '</select></div>'
        + '<div class="form-actions"><button type="button" class="btn" data-sp-close="1">取消</button>'
        + '<button type="button" class="btn btn-primary" id="po-rfq-go">生成采购单</button></div>'
    );
    modal.querySelector('#po-rfq-go').addEventListener('click', async function () {
        const rid = Number(modal.querySelector('#po-rfq-sel').value);
        const res = await api('POST', '/api/trade/purchase-orders/from-rfq', { rfq_id: rid });
        if (res) {
            modal.remove();
            toast('已生成采购单 ' + (res.po_no || ('PO' + res.id)));
            _spOpenPoDetail(res.id);
        }
    });
}

async function _spOpenPoModal(existing) {
    const p = existing || {};
    const isEdit = !!p.id;
    const [sups, ords] = await Promise.all([
        (_spState.suppliers && _spState.suppliers.length)
            ? Promise.resolve(_spState.suppliers)
            : api('GET', '/api/trade/suppliers', null, null, { silent: true }),
        api('GET', '/api/trade/purchase-orders/orders', null, null, { silent: true }),
    ]);
    if (Array.isArray(sups)) _spState.suppliers = sups;
    _spState.companyOrders = Array.isArray(ords) ? ords : [];

    const supOpts = '<option value="">请选择供应商...</option>' + (_spState.suppliers || []).map(function (s) {
        const sel = (p.supplier_id && Number(p.supplier_id) === Number(s.id)) ? ' selected' : '';
        return '<option value="' + esc(String(s.id)) + '"' + sel + '>' + esc(s.name) + '</option>';
    }).join('');
    const ordOpts = '<option value="">不关联客户订单</option>' + _spState.companyOrders.map(function (o) {
        const lbl = (o.display_no || ('SO' + o.id)) + (o.customer_name ? (' — ' + o.customer_name) : '') + (o.product_name ? (' (' + o.product_name + ')') : '');
        const sel = (p.order_id && Number(p.order_id) === Number(o.id)) ? ' selected' : '';
        return '<option value="' + esc(String(o.id)) + '"' + sel + '>' + esc(lbl) + '</option>';
    }).join('');
    const stOpts = ['已下单', '生产中', '待出货', '已出货', '完成'].map(function (st) {
        return '<option value="' + esc(st) + '"' + ((p.status || '已下单') === st ? ' selected' : '') + '>' + esc(st) + '</option>';
    }).join('');

    const modal = _spMountModal(
        '<h3>' + (isEdit ? '编辑采购单' : '新建采购单') + '</h3>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>采购单号（留空自动生成）</label><input type="text" id="pof-no" value="' + esc(p.po_no || '') + '"' + (isEdit ? ' readonly' : ' placeholder="留空自动生成 PO{id}"') + '></div>'
        + '<div class="form-group"><label>供应商 *</label><select id="pof-sup">' + supOpts + '</select></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>产品名称 *</label><input type="text" id="pof-prod" value="' + esc(p.product_name || '') + '"></div>'
        + '<div class="form-group"><label>规格型号</label><input type="text" id="pof-spec" value="' + esc(p.spec_model || '') + '"></div>'
        + '</div>'
        + '<div class="form-group"><label>关联客户订单（可选）</label><select id="pof-ord">' + ordOpts + '</select></div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>数量</label><input type="text" id="pof-qty" value="' + (p.quantity != null ? esc(String(p.quantity)) : '') + '"></div>'
        + '<div class="form-group"><label>单位</label><input type="text" id="pof-unit" value="' + esc(p.unit || '') + '"></div>'
        + '<div class="form-group"><label>总金额</label><input type="text" id="pof-amt" value="' + (p.amount != null ? esc(String(p.amount)) : '') + '"></div>'
        + '<div class="form-group"><label>币种</label><input type="text" id="pof-cur" value="' + esc(p.currency || 'CNY') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>下单日</label><input type="date" id="pof-ord-at" value="' + esc(p.ordered_at || '') + '"></div>'
        + '<div class="form-group"><label>约定交期</label><input type="date" id="pof-prom" value="' + esc(p.promised_date || '') + '"></div>'
        + '<div class="form-group"><label>状态</label><select id="pof-status">' + stOpts + '</select></div>'
        + '</div>'
        + '<div class="form-group"><label>备注</label><textarea id="pof-note">' + esc(p.note || '') + '</textarea></div>'
        + '<div class="form-actions"><button type="button" class="btn" data-sp-close="1">取消</button>'
        + '<button type="button" class="btn btn-primary" id="pof-save">保存</button></div>'
    );

    modal.querySelector('#pof-save').addEventListener('click', async function () {
        const supVal = modal.querySelector('#pof-sup').value.trim();
        const ordVal = modal.querySelector('#pof-ord').value.trim();
        const payload = {
            supplier_id: supVal ? Number(supVal) : null,
            product_name: modal.querySelector('#pof-prod').value.trim(),
            spec_model: modal.querySelector('#pof-spec').value.trim(),
            order_id: ordVal ? Number(ordVal) : null,
            quantity: modal.querySelector('#pof-qty').value.trim() || null,
            unit: modal.querySelector('#pof-unit').value.trim(),
            amount: modal.querySelector('#pof-amt').value.trim() || null,
            currency: modal.querySelector('#pof-cur').value.trim() || 'CNY',
            ordered_at: modal.querySelector('#pof-ord-at').value.trim(),
            promised_date: modal.querySelector('#pof-prom').value.trim(),
            status: modal.querySelector('#pof-status').value,
            note: modal.querySelector('#pof-note').value.trim(),
        };
        if (!isEdit) payload.po_no = modal.querySelector('#pof-no').value.trim();
        if (!payload.supplier_id) { toast('请选择供应商'); return; }
        if (!payload.product_name) { toast('请填写产品名称'); return; }
        const res = isEdit
            ? await api('PUT', '/api/trade/purchase-orders/' + p.id, payload)
            : await api('POST', '/api/trade/purchase-orders', payload);
        if (res) {
            modal.remove();
            toast(isEdit ? '已更新采购单' : '已新建采购单');
            if (_spState.selectedPoId) _spOpenPoDetail(_spState.selectedPoId);
            else _spLoadPos();
        }
    });
}

// ── 拼柜看板页签（供应商管理一期 · 第三批）───────────────────────────────────

async function _spLoadConsolidations() {
    const qs = _spState.consStatusFilter ? ('?status=' + encodeURIComponent(_spState.consStatusFilter)) : '';
    const [cons, pool] = await Promise.all([
        api('GET', '/api/trade/consolidations' + qs),
        api('GET', '/api/trade/consolidations/pool'),
    ]);
    if (Array.isArray(cons)) _spState.consolidations = cons;
    if (Array.isArray(pool)) _spState.pool = pool;
    if (_spState.tab === 'consolidations') _spRenderBody();
}

function _spRenderConsolidations(body) {
    const st = _spState.consStatusFilter || '';
    body.innerHTML =
        '<div class="sp-bar">'
        + '<select id="cons-status-filter">'
        + '<option value=""' + (st === '' ? ' selected' : '') + '>全部拼柜状态</option>'
        + '<option value="组货中"' + (st === '组货中' ? ' selected' : '') + '>组货中</option>'
        + '<option value="已截关"' + (st === '已截关' ? ' selected' : '') + '>已截关</option>'
        + '<option value="已发运"' + (st === '已发运' ? ' selected' : '') + '>已发运</option>'
        + '</select>'
        + '<button type="button" class="btn btn-primary" id="cons-new-btn" style="margin-left:auto;">' + btnIcon('plus') + ' 新建拼柜</button>'
        + '</div>'
        + '<div id="cons-cards">' + _spBuildConsolidationCardsHtml(_spState.consolidations, _spState.pool) + '</div>'
        + '<div class="sp-sec" style="margin-top:16px;">'
        + '<div class="sp-sec-h"><span class="t">待拼池（未入柜采购单 · 共 ' + esc(String((_spState.pool || []).length)) + ' 单）</span></div>'
        + '<div class="sp-table-wrap"><table class="sp-table">'
        + '<thead><tr><th style="width:105px;">采购单号</th><th>供应商</th><th>产品</th><th style="width:86px;">状态</th><th style="width:105px;">约定交期</th><th style="width:230px;">加入拼柜</th></tr></thead>'
        + '<tbody>' + _spBuildPoolRowsHtml(_spState.pool, _spState.consolidations) + '</tbody></table></div></div>';

    body.querySelector('#cons-status-filter').addEventListener('change', function (ev) {
        _spState.consStatusFilter = ev.target.value;
        _spLoadConsolidations();
    });
    body.querySelector('#cons-new-btn').addEventListener('click', function () {
        _spOpenConsolidationModal(null);
    });
    body.querySelectorAll('[data-cons-edit]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const cid = Number(btn.getAttribute('data-cons-edit'));
            const item = (_spState.consolidations || []).find(function (x) { return x.id === cid; });
            if (item) _spOpenConsolidationModal(item);
        });
    });
    body.querySelectorAll('[data-cons-del]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const cid = Number(btn.getAttribute('data-cons-del'));
            if (!confirm('确认删除该拼柜？（柜内采购单本身不会被删除，将回到待拼池）')) return;
            const ok = await api('DELETE', '/api/trade/consolidations/' + cid);
            if (ok) { toast('已删除拼柜'); _spLoadConsolidations(); }
        });
    });
    body.querySelectorAll('[data-cons-add-btn]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const cid = Number(btn.getAttribute('data-cons-add-btn'));
            const sel = body.querySelector('[data-cons-add-sel="' + cid + '"]');
            const poId = sel ? Number(sel.value) : 0;
            if (!poId) { toast('请先从待拼池选择采购单'); return; }
            const res = await api('POST', '/api/trade/consolidations/' + cid + '/items', { purchase_order_id: poId });
            if (res) { toast('已加入拼柜'); _spLoadConsolidations(); }
        });
    });
    body.querySelectorAll('[data-cons-rm-item]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const cid = Number(btn.getAttribute('data-cons-id'));
            const itemId = Number(btn.getAttribute('data-cons-rm-item'));
            const ok = await api('DELETE', '/api/trade/consolidations/' + cid + '/items/' + itemId);
            if (ok) { toast('已移出拼柜'); _spLoadConsolidations(); }
        });
    });
    body.querySelectorAll('[data-pool-join]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            const poId = Number(btn.getAttribute('data-pool-join'));
            const sel = body.querySelector('[data-pool-cons-sel="' + poId + '"]');
            const cid = sel ? Number(sel.value) : 0;
            if (!cid) { toast('请先选择目标拼柜'); return; }
            const res = await api('POST', '/api/trade/consolidations/' + cid + '/items', { purchase_order_id: poId });
            if (res) { toast('已加入拼柜'); _spLoadConsolidations(); }
        });
    });
}

function _spOpenConsolidationModal(existing) {
    const c = existing || {};
    const isEdit = !!c.id;
    const stOpts = ['组货中', '已截关', '已发运'].map(function (st) {
        return '<option value="' + esc(st) + '"' + ((c.status || '组货中') === st ? ' selected' : '') + '>' + esc(st) + '</option>';
    }).join('');
    const modal = _spMountModal(
        '<h3>' + (isEdit ? '编辑拼柜' : '新建拼柜') + '</h3>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>拼柜编号（留空自动生成）</label><input type="text" id="cf-code" placeholder="留空自动生成 CG{id}" value="' + esc(c.code || '') + '"></div>'
        + '<div class="form-group"><label>状态</label><select id="cf-status">' + stOpts + '</select></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>目的港</label><input type="text" id="cf-port" value="' + esc(c.destination_port || '') + '"></div>'
        + '<div class="form-group"><label>船司 / 货代</label><input type="text" id="cf-carrier" value="' + esc(c.carrier || '') + '"></div>'
        + '</div>'
        + '<div class="form-row">'
        + '<div class="form-group"><label>截关日</label><input type="date" id="cf-cutoff" value="' + esc(c.cutoff_date || '') + '"></div>'
        + '<div class="form-group"><label>预计开船日 (ETD)</label><input type="date" id="cf-etd" value="' + esc(c.etd || '') + '"></div>'
        + '</div>'
        + '<div class="form-group"><label>备注</label><textarea id="cf-note">' + esc(c.note || '') + '</textarea></div>'
        + '<div class="form-actions"><button type="button" class="btn" data-sp-close="1">取消</button>'
        + '<button type="button" class="btn btn-primary" id="cf-save">保存</button></div>'
    );
    modal.querySelector('#cf-save').addEventListener('click', async function () {
        const payload = {
            code: modal.querySelector('#cf-code').value.trim(),
            status: modal.querySelector('#cf-status').value,
            destination_port: modal.querySelector('#cf-port').value.trim(),
            carrier: modal.querySelector('#cf-carrier').value.trim(),
            cutoff_date: modal.querySelector('#cf-cutoff').value.trim(),
            etd: modal.querySelector('#cf-etd').value.trim(),
            note: modal.querySelector('#cf-note').value.trim(),
        };
        const res = isEdit
            ? await api('PUT', '/api/trade/consolidations/' + c.id, payload)
            : await api('POST', '/api/trade/consolidations', payload);
        if (res) {
            modal.remove();
            toast(isEdit ? '已更新拼柜' : '已新建拼柜');
            _spLoadConsolidations();
        }
    });
}

// ── 今日简报「交期提醒」联动（复用 /brief/today 返回的 delivery_alerts，不额外请求受门禁接口）────

async function _spInjectBriefDeliveryAlerts() {
    if (typeof currentCompanyId === 'undefined' || !currentCompanyId) return;
    const alerts = (typeof window !== 'undefined' && Array.isArray(window._lastBriefDeliveryAlerts))
        ? window._lastBriefDeliveryAlerts
        : [];
    if (!alerts.length) return;
    const html = _spBuildDeliveryAlertsBriefHtml(alerts.slice(0, 10));
    if (!html) return;
    const railBrief = document.getElementById('rail-brief');
    if (railBrief) {
        const old = railBrief.querySelector('#rail-brief-delivery-alerts');
        if (old) old.remove();
        railBrief.insertAdjacentHTML('beforeend', html);
        return;
    }
    const card = document.querySelector('.brief-kpi-card');
    if (card) {
        const old = card.querySelector('#rail-brief-delivery-alerts');
        if (old) old.remove();
        card.insertAdjacentHTML('beforeend', html);
    }
}

if (typeof loadTodayBrief === 'function' && !loadTodayBrief._spDeliveryWrapped) {
    const _origLoadTodayBrief = loadTodayBrief;
    loadTodayBrief = async function (silent) {
        await _origLoadTodayBrief(silent);
        await _spInjectBriefDeliveryAlerts();
    };
    loadTodayBrief._spDeliveryWrapped = true;
}
