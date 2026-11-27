/**
 * 供应商管理一期 · 第一批 前端基础用例（A13）：
 * 覆盖名录列表渲染、比价按单位分组、自产三态、过期标灰、换算标记与 XSS 转义。
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const { loadRegion } = require('./_extract');

function loadSuppliersUi() {
    const escMap = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
    const esc = (s) => String(s || '').replace(/[&<>"']/g, (ch) => escMap[ch]);
    return loadRegion(
        'suppliers-ui',
        '{ _spBuildDirectoryRowsHtml, _spBuildCompareGroupsHtml, _spFormatSelfProduced, _spFormatPriceCell, _spFormatQuotedAt, _spBuildRfqRowsHtml, _spBuildRfqResponsesHtml, _spFormatRfqStatus, _spBuildPoRowsHtml, _spFormatCutoffBadge, _spBuildConsolidationCardsHtml, _spBuildPoolRowsHtml, _spBuildDeliveryAlertsBriefHtml, _spBuildOrderLinkedPosHtml, _spFormatExtractError, _spBuildExtractResultHtml }',
        { esc },
    );
}

test('名录视图：空态与正常供应商行渲染 + XSS 转义', () => {
    const ui = loadSuppliersUi();
    const emptyHtml = ui._spBuildDirectoryRowsHtml([]);
    assert.match(emptyHtml, /暂无供应商/);

    const rowsHtml = ui._spBuildDirectoryRowsHtml([
        {
            id: 7,
            name: '顺达<script>alert(1)</script>陶瓷',
            short_name: '顺达',
            supplier_type: '工厂',
            main_products: '马克杯',
            province: '广东',
            city: '佛山',
            status: '合作中',
            can_issue_vat: 1,
            tax_point: 8,
            rating: 5,
            is_starred: 1,
        },
    ]);
    assert.doesNotMatch(rowsHtml, /<script>/);
    assert.match(rowsHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
    assert.match(rowsHtml, /可开专票/);
    assert.match(rowsHtml, /\+8%/);
    assert.match(rowsHtml, /★/);
});

test('比价视图：按不同单位分组展示、自产三态、换算标记、过期标灰且原样显示后端价格', () => {
    const ui = loadSuppliersUi();
    const html = ui._spBuildCompareGroupsHtml({
        product_name: '铝型材接头',
        unit_groups: [
            {
                unit: '件',
                lowest_excl_tax: 90,
                lowest_incl_tax: null,
                suppliers: [
                    {
                        supplier_name: '甲供应商',
                        payment_terms: '30%定金',
                        product: { is_self_produced: 1, quality_note: '出口品质', lead_time_days: 15, moq: 500 },
                        latest_quote: {
                            currency: 'CNY',
                            price_excl_tax: 100,
                            price_incl_tax: 108,
                            price_excl_tax_converted: false,
                            price_incl_tax_converted: true,
                            quoted_at: '2026-11-20',
                            expired: false,
                        },
                        quote_count: 2,
                        price_excl_range: [98, 100],
                    },
                    {
                        supplier_name: '乙供应商',
                        product: { is_self_produced: 2, quality_note: '' },
                        latest_quote: {
                            currency: 'CNY',
                            price_excl_tax: 90,
                            price_incl_tax: null,
                            price_excl_tax_converted: false,
                            price_incl_tax_converted: false,
                            quoted_at: '2026-08-01',
                            expired: true,
                        },
                        quote_count: 1,
                        price_excl_range: [90, 90],
                    },
                ],
            },
            {
                unit: 'kg',
                lowest_excl_tax: 25,
                lowest_incl_tax: null,
                suppliers: [],
            },
        ],
        no_quote_suppliers: [],
    });

    assert.match(html, /单位组：件/);
    assert.match(html, /单位组：kg/);
    assert.match(html, /自产/);
    assert.match(html, /待确认/);
    assert.match(html, /CNY 108<\/span><span class="sp-conv">换算<\/span>/);
    assert.match(html, /is-expired/);
    assert.match(html, /已过期/);
});

test('O-供3：空报价日期在前端显示「日期未注明」', () => {
    const ui = loadSuppliersUi();
    assert.match(ui._spFormatQuotedAt(''), /日期未注明/);
    assert.match(ui._spFormatQuotedAt(null), /日期未注明/);
    assert.equal(ui._spFormatQuotedAt('2026-11-20'), '2026-11-20');

    const html = ui._spBuildCompareGroupsHtml({
        product_name: '工业阀门',
        unit_groups: [
            {
                unit: '台',
                lowest_excl_tax: 88,
                lowest_incl_tax: null,
                suppliers: [
                    {
                        supplier_name: '空日期厂',
                        product: { is_self_produced: 2 },
                        latest_quote: {
                            currency: 'CNY',
                            price_excl_tax: 88,
                            price_incl_tax: null,
                            quoted_at: '',
                            expired: false,
                        },
                        quote_count: 1,
                        price_excl_range: [88, 88],
                    },
                ],
            },
        ],
        no_quote_suppliers: [],
    });
    assert.match(html, /日期未注明/);
});

test('采购询价页签：列表渲染（空态/进度/选中供应商/两态/XSS）与回复行渲染（未回/选定高亮/原样价格）', () => {
    const ui = loadSuppliersUi();
    assert.match(ui._spBuildRfqRowsHtml([]), /暂无采购询价单/);

    const listHtml = ui._spBuildRfqRowsHtml([
        {
            id: 11,
            product_name: '不锈钢阀门<script>x</script>',
            spec_model: 'DN50',
            title: '德客急单',
            quantity: 200,
            unit: '台',
            customer_name: 'Euro Buyer',
            responded_count: 2,
            total_responses: 3,
            selected_supplier_name: '顺达阀门厂',
            status: 'decided',
        },
        {
            id: 12,
            product_name: '法兰垫片',
            quantity: null,
            unit: '件',
            customer_name: null,
            responded_count: 0,
            total_responses: 1,
            selected_supplier_name: null,
            status: 'open',
        },
    ]);
    assert.doesNotMatch(listHtml, /<script>/);
    assert.match(listHtml, /已回 2 \/ 共 3/);
    assert.match(listHtml, /顺达阀门厂/);
    assert.match(listHtml, /已选厂/);
    assert.match(listHtml, /待回复/);

    assert.match(ui._spBuildRfqResponsesHtml([]), /暂未添加供应商/);
    const respHtml = ui._spBuildRfqResponsesHtml([
        {
            id: 101,
            supplier_name: '甲厂',
            responded: 1,
            responded_at: '2026-11-27',
            price_excl_tax: 88.5,
            price_incl_tax: null,
            currency: 'CNY',
            lead_time_days: 15,
            lead_time_text: '常规',
            moq: 100,
            notes: '含包装',
            quote_id: 501,
            selected: 1,
        },
        {
            id: 102,
            supplier_name: '乙厂',
            responded: 0,
            responded_at: '',
            price_excl_tax: null,
            price_incl_tax: null,
            currency: 'CNY',
            selected: 0,
        },
    ]);
    assert.match(respHtml, /sp-rfq-sel/);
    assert.match(respHtml, /已选定供应商/);
    assert.match(respHtml, /取消选定/);
    assert.match(respHtml, /value="88\.5"/);
    assert.match(respHtml, /未回/);
    assert.match(respHtml, /选定<\/button>/);
});

test('采购单与拼柜看板：列表/倒计时徽标/待拼池/今日简报交期提醒/订单关联采购单渲染与 XSS 转义', () => {
    const ui = loadSuppliersUi();
    assert.match(ui._spBuildPoRowsHtml([]), /暂无采购单/);
    const poHtml = ui._spBuildPoRowsHtml([
        {
            id: 5,
            po_no: 'PO5',
            supplier_name: '顺达<script>x</script>厂',
            product_name: '球阀',
            spec_model: 'DN50',
            quantity: 100,
            unit: '台',
            order_display_no: 'SO12',
            customer_name: 'Euro Buyer',
            amount: 12000,
            currency: 'CNY',
            promised_date: '2026-12-01',
            status: '生产中',
        },
    ]);
    assert.doesNotMatch(poHtml, /<script>/);
    assert.match(poHtml, /PO5/);
    assert.match(poHtml, /SO12/);
    assert.match(poHtml, /CNY 12000/);

    // 截关倒计时徽标：已过红、≤3天橙、>3天普通、无截关日
    assert.match(ui._spFormatCutoffBadge(-2, '2026-11-25'), /sp-cut over/);
    assert.match(ui._spFormatCutoffBadge(0, '2026-11-27'), /今日截关/);
    assert.match(ui._spFormatCutoffBadge(2, '2026-11-29'), /sp-cut warn/);
    assert.match(ui._spFormatCutoffBadge(7, '2026-12-04'), /sp-cut ok/);
    assert.match(ui._spFormatCutoffBadge(null, ''), /未设截关日/);

    const consHtml = ui._spBuildConsolidationCardsHtml(
        [
            {
                id: 3,
                code: 'CG3',
                status: '组货中',
                destination_port: '鹿特丹',
                cutoff_date: '2026-11-29',
                days_to_cutoff: 2,
                items: [
                    { item_id: 9, po_no: 'PO5', supplier_name: '顺达厂', product_name: '球阀', po_status: '生产中', promised_date: '2026-12-01' },
                ],
            },
        ],
        [{ id: 6, po_no: 'PO6', supplier_name: '乙厂', product_name: '垫片', status: '已下单', promised_date: '' }],
    );
    assert.match(consHtml, /CG3/);
    assert.match(consHtml, /鹿特丹/);
    assert.match(consHtml, /PO5/);
    assert.match(consHtml, /移出/);

    const poolHtml = ui._spBuildPoolRowsHtml(
        [{ id: 6, po_no: 'PO6', supplier_name: '乙厂', product_name: '垫片', status: '已下单', promised_date: '' }],
        [{ id: 3, code: 'CG3', destination_port: '鹿特丹' }],
    );
    assert.match(poolHtml, /PO6/);
    assert.match(poolHtml, /CG3/);

    assert.equal(ui._spBuildDeliveryAlertsBriefHtml([]), '');
    const briefHtml = ui._spBuildDeliveryAlertsBriefHtml([
        { id: 5, po_no: 'PO5', supplier_name: '顺达厂', product_name: '球阀', is_overdue: true, days_overdue: 3, days_left: 0 },
    ]);
    assert.match(briefHtml, /交期提醒/);
    assert.match(briefHtml, /逾期 3 天/);

    const linkedHtml = ui._spBuildOrderLinkedPosHtml([
        { id: 5, po_no: 'PO5', supplier_name: '顺达厂', product_name: '球阀', status: '生产中', promised_date: '2026-12-01' },
    ]);
    assert.match(linkedHtml, /PO5/);
    assert.match(linkedHtml, /顺达厂/);
});

test('工单 #2 & #4：AI 抽取结果框展示未处理扫描件原因，草稿编辑弹窗含 MOQ 输入框', () => {
    const ui = loadSuppliersUi();
    const { SRC } = require('./_extract');

    // #2：结果框展示失败/跳过文件名与中文原因
    const html = ui._spBuildExtractResultHtml({
        files_processed: 3,
        drafts_created: 6,
        failed: [{ file: '/tmp/quotes/scan_01.jpg', error: 'unsupported_type' }],
    });
    assert.match(html, /scan_01\.jpg/);
    assert.match(html, /OCR/);

    // #4：草稿卡片与编辑弹窗都包含 MOQ
    const modalIdx = SRC.indexOf('function _spOpenDraftEditModal');
    assert.ok(modalIdx !== -1, '找不到 _spOpenDraftEditModal');
    const modalBody = SRC.slice(modalIdx, modalIdx + 3000);
    assert.match(modalBody, /id="spd-moq"/, '编辑弹窗必须包含 MOQ 输入框');
    assert.match(modalBody, /moq:\s*document\.getElementById\('spd-moq'\)/, '保存草稿必须提交 moq 字段');
});
