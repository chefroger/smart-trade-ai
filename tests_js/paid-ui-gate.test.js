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

test('付费目的地集合与左侧隐藏的三组一致', () => {
    const { api } = loadGate();
    for (const view of ['customers', 'tasks', 'history']) {
        assert.strictEqual(api.isPaidDestination(view, ''), true, view);
    }
    for (const ctx of ['docs', 'docgen', 'osint']) {
        assert.strictEqual(api.isPaidDestination('chat', ctx), true, ctx);
    }
    assert.strictEqual(api.isPaidDestination('chat', 'daily'), false);
    assert.strictEqual(api.isPaidDestination('chat', 'lead'), false);
    assert.strictEqual(api.isPaidDestination('chat', 'platform'), false);
});
