/**
 * 订单明细行（一单多商品）— 前端结构守卫。
 *
 * 断言点：
 * - 弹窗里有可增删的明细行容器，每行含 品名/数量/单位/单价/行总额；
 * - 数量×单价变化时自动算行总额，手填后不再覆盖；
 * - 提交体带 items，订单头只发订单级字段；
 * - 空行被忽略、填了内容却没品名要提示，不允许静默丢掉。
 */

const test = require('node:test');
const assert = require('node:assert');
const { SRC } = require('./_extract');

test('弹窗渲染明细容器与「添加商品」按钮', () => {
    assert.ok(SRC.includes('id="order-items"'), '缺少明细行容器 #order-items');
    assert.ok(SRC.includes("t('order.add_line')"), '缺少「添加商品」按钮');
    assert.ok(SRC.includes("t('order.items')"), '缺少「商品明细」标题');
});

test('明细行包含五个输入与删除按钮', () => {
    const idx = SRC.indexOf('function addOrderItemRow(item)');
    assert.ok(idx !== -1, '缺少 addOrderItemRow');
    const body = SRC.slice(idx, idx + 1600);

    for (const cls of ['oi-name', 'oi-qty', 'oi-unit', 'oi-price', 'oi-total']) {
        assert.ok(body.includes(cls), `明细行缺少字段 ${cls}`);
    }
    assert.ok(body.includes('removeOrderItemRow'), '明细行缺少删除按钮');
});

test('数量×单价自动算行总额，手填后不覆盖', () => {
    const idx = SRC.indexOf('function _orderRowRecalc(e)');
    assert.ok(idx !== -1, '缺少 _orderRowRecalc');
    const body = SRC.slice(idx, idx + 900);

    assert.match(body, /qty\s*\*\s*price/, '需要按 数量×单价 计算行总额');
    assert.match(body, /dataset\.manual === '1'/, '手填过行总额后不得被覆盖');
    assert.ok(
        SRC.includes(".oi-total').addEventListener('input'"),
        '行总额输入需要标记 manual',
    );
});

test('提交体带 items，不再发头级 product_name/amounts', () => {
    const idx = SRC.indexOf('async function saveOrder()');
    assert.ok(idx !== -1, '找不到 saveOrder');
    const body = SRC.slice(idx, idx + 1400);

    assert.match(body, /items: items/, '提交体必须带 items');
    assert.ok(!/product_name:/.test(body), '订单头不再平铺 product_name');
    assert.ok(!/quantity:\s*_numOrNull/.test(body), '订单头不再平铺数量');
    assert.match(body, /if \(items === null\)/, '品名缺失时提示而不是静默丢行');
    assert.match(body, /if \(!items\.length\)/, '空明细必须拦下');
});

test('空行忽略、有内容无品名返回 null', () => {
    const idx = SRC.indexOf('function _collectOrderItems()');
    assert.ok(idx !== -1, '缺少 _collectOrderItems');
    const body = SRC.slice(idx, idx + 1200);

    assert.match(body, /if \(!name && qty == null && price == null && total == null\) continue;/,
        '整行空应忽略');
    assert.match(body, /if \(!name\) return null;/, '有内容无品名必须报错');
});

test('编辑时回填客户并隐藏客户选择（旧 bug：下拉是空的）', () => {
    const idx = SRC.indexOf('function showOrderEditModal');
    assert.ok(idx !== -1, '找不到 showOrderEditModal');
    const body = SRC.slice(idx, idx + 7000);

    assert.match(body, /\$\('order-cust-id'\)\.value = o\.customer_id/, '编辑时必须回填客户 id');
    assert.match(body, /order-cust-row'\)\.style\.display = 'none'/, '编辑时客户行应隐藏');
});

test('列表对多商品显示「等N项」与合计待谈', () => {
    const idx = SRC.indexOf('async function loadOrdersForCustomer(cid)');
    const body = SRC.slice(idx, idx + 2500);

    assert.ok(body.includes("t('order.items_count'"), '多商品需要「等N项」');
    assert.ok(body.includes("t('order.total_pending'"), '合计为空时显示待谈');
    assert.ok(body.includes("t('order.price_per_line'"), '多行单价按行报价');
});
