/**
 * 单价「待谈」的展示层（Batch 1 缺口 A2）。
 *
 * 后端已允许单价存 NULL（待谈），但前端原先：列表不显示单价、编辑框把
 * NULL 回填成空、旧数据 0 回填成 "0" —— 用户看不到「待谈」这个状态，
 * 会以为单价是 0 元。这里做源码级断言钉住四处展示。
 */

const test = require('node:test');
const assert = require('node:assert');
const { SRC } = require('./_extract');

test('单价待谈的文案 helper 存在且区分 null 与旧数据 0', () => {
    const idx = SRC.indexOf('function _orderPriceText(o)');
    assert.ok(idx !== -1, '必须有 _orderPriceText(o) 统一单价展示口径');

    const body = SRC.slice(idx, idx + 500);
    assert.match(body, /o\.unit_price == null/, 'null 必须判为待谈');
    assert.match(body, /Number\(o\.unit_price\) === 0/, '0 必须单独判为旧数据');
    assert.match(body, /order\.price_pending_legacy/, '旧数据要有独立文案');
    assert.match(body, /order\.price_pending/, '新数据待谈文案');
});

test('中英文词典都有待谈文案', () => {
    assert.ok(SRC.includes("'order.price_pending':'单价待谈'"), '中文缺待谈文案');
    assert.ok(SRC.includes("'order.price_pending_legacy':'单价待谈（旧数据，单价未填）'"),
        '中文缺旧数据待谈文案');
    assert.ok(SRC.includes("'order.price_pending':'Price TBD'"), '英文缺待谈文案');
    assert.ok(SRC.includes("'order.price_pending_legacy':'Price TBD (legacy data, price not filled)'"),
        '英文缺旧数据待谈文案');
});

test('订单列表显式渲染单价状态', () => {
    const idx = SRC.indexOf('async function loadOrdersForCustomer(cid)');
    assert.ok(idx !== -1, '找不到订单列表渲染');
    const body = SRC.slice(idx, idx + 2000);

    assert.match(body, /_orderPriceText\(o\)/, '列表必须用统一 helper 显示单价/待谈');
});

test('编辑弹窗把 null 与 0 都留空，并用占位符说明待谈', () => {
    const idx = SRC.indexOf('$(\'order-price\').value');
    assert.ok(idx !== -1, '找不到单价回填');
    const body = SRC.slice(Math.max(0, idx - 600), idx + 400);

    assert.match(body, /pricePending/, '必须识别 null / 0 两种待谈来源');
    assert.match(body, /placeholder = _orderPriceText\(o\)/, '留空时用占位符说明待谈');
    assert.ok(
        !/order-price'\)\.value = o\.unit_price \|\| ''/.test(body),
        '旧写法会把 0 回填成 "0"，必须去掉',
    );
});
