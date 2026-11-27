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
        '{ _spBuildDirectoryRowsHtml, _spBuildCompareGroupsHtml, _spFormatSelfProduced, _spFormatPriceCell }',
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
