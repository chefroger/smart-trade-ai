/**
 * 付费 UI 门禁的行为测试（loadRegion + fake DOM）。
 *
 * 覆盖三态：
 *   - 已激活 → 付费入口显示；
 *   - 试用/到期 → 隐藏；
 *   - 许可证状态读取失败/超时 → fail-open 显示（可用性优先）。
 *
 * 注意：license.json 被删除时后端正常返回 trial/expired，属于第二态，不是 unknown。
 */

const test = require('node:test');
const assert = require('node:assert');
const { loadRegion } = require('./_extract');

function makeNode() {
    const classes = new Set();
    return {
        classes,
        classList: {
            toggle(name, force) {
                if (force) classes.add(name);
                else classes.delete(name);
            },
            contains: (name) => classes.has(name),
            add: (name) => classes.add(name),
            remove: (name) => classes.delete(name),
        },
    };
}

function loadGate() {
    const paidNodes = [makeNode(), makeNode(), makeNode()];
    const importRow = makeNode();
    const document = {
        querySelectorAll(selector) {
            return selector === '[data-paid]' ? paidNodes : [];
        },
        getElementById(id) {
            if (id === 'import-company-row') return importRow;
            return null; // company-modal 关闭
        },
    };
    const api = loadRegion(
        'license-gate',
        `{
            apply: _applyLicenseGates,
            allows: _licenseGateAllowsPaid,
            isPaidDestination: _isPaidDestination,
            setState: function (activated, unknown) {
                _licenseActivated = !!activated;
                _licenseGateUnknown = !!unknown;
            }
        }`,
        { document, loadCompanyListUI: () => {} },
    );
    return { api, paidNodes, importRow };
}

test('已激活：付费入口显示', () => {
    const { api, paidNodes, importRow } = loadGate();
    api.setState(true, false);
    api.apply();
    assert.strictEqual(api.allows(), true);
    for (const node of paidNodes) assert.strictEqual(node.classes.has('hidden'), false);
    assert.strictEqual(importRow.classes.has('hidden'), false);
});

test('试用/到期（activated=false）：付费入口隐藏', () => {
    const { api, paidNodes, importRow } = loadGate();
    api.setState(false, false);
    api.apply();
    assert.strictEqual(api.allows(), false);
    for (const node of paidNodes) assert.strictEqual(node.classes.has('hidden'), true);
    assert.strictEqual(importRow.classes.has('hidden'), true);
});

test('许可证状态读取失败：fail-open 显示，聊天不锁', () => {
    const { api, paidNodes, importRow } = loadGate();
    api.setState(false, true);
    api.apply();
    assert.strictEqual(api.allows(), true);
    for (const node of paidNodes) assert.strictEqual(node.classes.has('hidden'), false);
    assert.strictEqual(importRow.classes.has('hidden'), false);
});

test('付费目的地集合与左侧隐藏的三组一致（含 suppliers）', () => {
    const { api } = loadGate();
    for (const view of ['customers', 'suppliers', 'tasks', 'history']) {
        assert.strictEqual(api.isPaidDestination(view, ''), true, view);
    }
    for (const ctx of ['docs', 'docgen', 'osint']) {
        assert.strictEqual(api.isPaidDestination('chat', ctx), true, ctx);
    }
    assert.strictEqual(api.isPaidDestination('chat', 'daily'), false);
    assert.strictEqual(api.isPaidDestination('chat', 'lead'), false);
    assert.strictEqual(api.isPaidDestination('chat', 'platform'), false);
});

test('D2：试用状态下导航到 suppliers 视图被既有 navToView 门禁拦下', () => {
    const vm = require('node:vm');
    const { SRC } = require('./_extract');

    const navStart = SRC.indexOf('function navToView(');
    assert.ok(navStart !== -1, '找不到 navToView');
    const navEnd = SRC.indexOf('\nfunction ', navStart + 1);
    const navSrc = SRC.slice(navStart, navEnd > navStart ? navEnd : navStart + 4000);

    const { api } = loadGate();
    api.setState(false, false); // 试用态

    const toasts = [];
    let saved = false;
    const ctx = {
        currentCompanyId: 1,
        currentView: 'chat',
        currentChatContext: 'daily',
        currentChatName: '今日简报',
        isOnboardingCompleted: () => true,
        document: {
            getElementById: () => null,
            querySelectorAll: () => [],
            querySelector: () => null,
            body: { classList: { toggle() {} } },
        },
        _isPaidDestination: api.isPaidDestination,
        _licenseGateAllowsPaid: api.allows,
        t: (k) => k,
        toast: (msg) => toasts.push(msg),
        saveState: () => { saved = true; },
    };
    vm.runInNewContext(navSrc + '\nnavToView("suppliers");', ctx);

    assert.strictEqual(ctx.currentView, 'chat', '试用态下不应切到 suppliers 视图');
    assert.strictEqual(saved, false, '被拦截时不应调用 saveState');
    assert.deepStrictEqual(toasts, ['license.paid_only'], '应弹出付费专属提示');
});

test('D2：订单弹窗关联采购单区块遇 402/失败时静默隐藏', () => {
    const { SRC } = require('./_extract');
    assert.ok(
        /id="order-linked-pos-group"/.test(SRC),
        '关联采购单外层容器需带 id="order-linked-pos-group" 以便静默隐藏',
    );
    const idx = SRC.indexOf('/api/trade/purchase-orders?order_id=');
    assert.ok(idx !== -1, '找不到关联采购单接口调用');
    const block = SRC.slice(Math.max(0, idx - 260), idx + 600);
    assert.ok(/silent:\s*true/.test(block), '关联采购单请求必须 silent: true');
    assert.ok(/!Array\.isArray\(pos\)/.test(block), '返回 null（402/失败）时必须判非数组并隐藏');
    assert.ok(/\.catch\(/.test(block), '网络异常时也必须静默隐藏');
});

test('D4：今日简报交期提醒复用 /brief/today 数据，不额外请求受门禁的 /purchase-orders/alerts', () => {
    const { SRC } = require('./_extract');
    const idx = SRC.indexOf('async function _spInjectBriefDeliveryAlerts()');
    assert.ok(idx !== -1, '找不到 _spInjectBriefDeliveryAlerts');
    const body = SRC.slice(idx, idx + 800);
    assert.ok(
        !/\/api\/trade\/purchase-orders\/alerts/.test(body),
        '_spInjectBriefDeliveryAlerts 不得请求 /api/trade/purchase-orders/alerts（试用态会 402）',
    );
    assert.ok(/_lastBriefDeliveryAlerts/.test(body), '应直接复用 loadTodayBrief 缓存的 delivery_alerts');
});
