/**
 * cron 任务行的三种状态必须区分：已过时 / 未到点 / **调度未知**。
 *
 * 后端在解析不出调度时返回 `{scheduled: null, missed: null, unknown_schedule: true}`
 * （步进式 cron 表达式 `_cron_to_time` 处理不了）。前端若按老逻辑渲染，
 * 会把 null 直接拼进 HTML —— 界面上出现 "null"，且状态显示成「待执行」。
 */
const test = require('node:test');
const assert = require('node:assert');
const { loadRegion } = require('./_extract');

// 用真实的 esc（html-escape-utils 区段），不用桩 —— 桩不转义就测不出 XSS
const { esc } = loadRegion('html-escape-utils', '{ esc: esc }');
const { _cronTaskLine } = loadRegion(
    'cron-task-line',
    '{ _cronTaskLine: _cronTaskLine }',
    { esc: esc, escJs: (s) => esc(JSON.stringify(String(s || ''))) }
);

test('调度未知时显示「调度未知」而不是 null', () => {
    const html = _cronTaskLine({ name: '每五分钟跑', unknown_schedule: true, scheduled: null, missed: null });

    assert.doesNotMatch(html, /null/, 'null 被直接渲染进界面');
    assert.match(html, /调度未知/);
    assert.match(html, /无法解析/);
});

test('调度未知不得显示成「已过时」', () => {
    const html = _cronTaskLine({ name: 'X', unknown_schedule: true, missed: null });

    assert.doesNotMatch(html, /已过时/, '未知不是"已过时"——那是确定的判断');
});

test('确实已过时仍显示红色已过时', () => {
    const html = _cronTaskLine({ name: 'X', scheduled: '09:00', missed: true });

    assert.match(html, /已过时/);
    assert.match(html, /09:00/);
});

test('未到点显示时刻、不警示', () => {
    const html = _cronTaskLine({ name: 'X', scheduled: '15:30', missed: false });

    assert.match(html, /15:30/);
    assert.doesNotMatch(html, /已过时|调度未知/);
});

test('任务名转义（防注入）', () => {
    const html = _cronTaskLine({ name: '<img onerror=x>', scheduled: '09:00', missed: false });

    assert.doesNotMatch(html, /<img/, '任务名未转义');
});
