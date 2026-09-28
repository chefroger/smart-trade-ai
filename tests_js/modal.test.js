/**
 * 弹窗清理逻辑的行为测试 —— 零依赖（Node 内置 node:test）。
 *
 * 回归的 bug：保存/删除订单时用 document.querySelector('.modal-backdrop') 清理弹窗。
 * querySelector 返回的是**文档序第一个**匹配元素，而 trade_chat.html 里第一个
 * .modal-backdrop 是 #company-modal（静态骨架），动态 backdrop 是 appendChild 到
 * body 末尾排在后面 —— 于是公司设置弹窗被删掉、订单弹窗反而留在屏幕上，
 * 之后 showAddCompanyModal() 拿 $('company-modal') 直接 TypeError。
 *
 * 这里用一个记录调用的最小 DOM shim 测真实行为：不需要 jsdom，也不需要跑整个 SPA。
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { loadRegion } = require('./_extract');

/** 最小 DOM shim：够 _STATIC_MODAL_IDS / _removeDynamicModals / _closeOrderModal 用。 */
function makeFakeDom(ids) {
    // 每个节点记录自己是否被 remove 过，便于断言「谁被删了、谁没被删」
    const nodes = ids.map((id) => ({
        id,
        removed: false,
        remove() { this.removed = true; },
    }));
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const document = {
        querySelectorAll(selector) {
            assert.strictEqual(selector, '.modal-backdrop', '只应查询 .modal-backdrop');
            return nodes;
        },
        // 还原浏览器语义：返回文档序第一个匹配元素（已被移除的节点不再匹配）
        querySelector(selector) {
            assert.strictEqual(selector, '.modal-backdrop', '只应查询 .modal-backdrop');
            return nodes.find((n) => !n.removed) || null;
        },
        getElementById(id) { return byId.get(id) || null; },
    };
    return { nodes, byId, document };
}

function loadModalUtils(document) {
    return loadRegion(
        'modal-utils',
        '{ _STATIC_MODAL_IDS: _STATIC_MODAL_IDS, _removeDynamicModals: _removeDynamicModals, _closeOrderModal: _closeOrderModal }',
        { document },
    );
}

test('_removeDynamicModals 只删动态弹窗，保留静态骨架弹窗', () => {
    const { byId, document } = makeFakeDom(['company-modal', 'order-modal-backdrop', 'customer-modal']);
    const { _removeDynamicModals } = loadModalUtils(document);

    _removeDynamicModals();

    assert.strictEqual(byId.get('order-modal-backdrop').removed, true, '动态弹窗应被移除');
    assert.strictEqual(byId.get('company-modal').removed, false, '静态公司弹窗必须保留');
    assert.strictEqual(byId.get('customer-modal').removed, false, '静态客户弹窗必须保留');
});

test('_closeOrderModal 按 id 精确移除订单弹窗，不碰 #company-modal', () => {
    // 复刻 HTML 的文档序：静态公司弹窗在前，动态订单 backdrop 在后
    const { byId, document } = makeFakeDom(['company-modal', 'order-modal-backdrop']);
    const { _closeOrderModal } = loadModalUtils(document);

    _closeOrderModal();

    assert.strictEqual(byId.get('order-modal-backdrop').removed, true, '订单弹窗应被关闭');
    assert.strictEqual(byId.get('company-modal').removed, false,
        '公司设置弹窗绝不能被订单流程删掉（删掉后 showAddCompanyModal 会 TypeError）');
});

test('_closeOrderModal 在弹窗不存在时静默返回，不抛错', () => {
    const { document } = makeFakeDom(['company-modal']);
    const { _closeOrderModal } = loadModalUtils(document);

    assert.doesNotThrow(() => _closeOrderModal());
});

test('静态弹窗白名单覆盖 trade_chat.html 里全部骨架弹窗', () => {
    // 直接从 HTML 里扫出写死的 .modal-backdrop id，不抄一遍白名单（否则两边一起错还测不出来）
    const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'trade_chat.html'), 'utf8');
    const idsInHtml = [...html.matchAll(/class="modal-backdrop[^"]*"\s+id="([^"]+)"/g)].map((m) => m[1]);

    assert.ok(idsInHtml.length > 0, '应当能从 trade_chat.html 扫出骨架弹窗 id');
    const { _STATIC_MODAL_IDS } = loadModalUtils(makeFakeDom([]));
    for (const id of idsInHtml) {
        assert.ok(_STATIC_MODAL_IDS.has(id),
            `${id} 在 HTML 里是静态骨架弹窗，但不在 _STATIC_MODAL_IDS 白名单里 —— 新增静态弹窗时必须同步加白名单，否则会被动态清理误删`);
    }
});
