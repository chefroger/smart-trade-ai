/**
 * 验厂计划的隐私守卫（2026-11-20 审计 P0-1）：
 * 内部页默认不勾选 —— 公开页和内部页在同一次打印任务里，
 * 默认勾选等于把「内部风险」连同客户私密画像一起打出去。
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const SRC = fs.readFileSync(
    path.join(__dirname, '..', 'static', 'js', 'customers.js'), 'utf8');

test('打印预览的「内部页」默认不勾选', () => {
    const m = SRC.match(/<input type="checkbox" data-sheet="internal"[^>]*>/);
    assert.ok(m, '找不到 internal 复选框');
    assert.doesNotMatch(m[0], /checked/, '内部页不得默认勾选');
    // 公开页仍应默认勾选
    const pub = SRC.match(/<input type="checkbox" data-sheet="public"[^>]*>/);
    assert.ok(pub, '找不到 public 复选框');
    assert.match(pub[0], /checked/, '公开页应默认勾选');
});

test('长图的「含内部信息」默认不勾选', () => {
    const m = SRC.match(/<input type="checkbox" id="vl-internal"[^>]*>/);
    assert.ok(m, '找不到 vl-internal 复选框');
    assert.doesNotMatch(m[0], /checked/, '长图默认不得含内部信息');
});
