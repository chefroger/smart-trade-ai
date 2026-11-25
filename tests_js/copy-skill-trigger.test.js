/**
 * P2-新2：点技能行复制的是触发词（data-arg2），不是技能名（data-arg）。
 * 同时保证剪贴板内容与 toast 显示一致。
 */
const test = require('node:test');
const assert = require('node:assert');
const { SRC } = require('./_extract');

function load() {
    const start = SRC.indexOf('function copySkillTrigger');
    assert.ok(start !== -1, '找不到 copySkillTrigger');
    const end = SRC.indexOf('\n}', start) + 2;
    let copied = '';
    let toasted = '';
    const fn = new Function(
        'navigator', 'toast', 't',
        SRC.slice(start, end) + '\nreturn copySkillTrigger;',
    )(
        { clipboard: { writeText: (v) => { copied = v; } } },
        (m) => { toasted = m; },
        (k) => k,
    );
    return { fn, getCopied: () => copied, getToasted: () => toasted };
}

test('复制触发词而不是技能名', () => {
    const { fn, getCopied, getToasted } = load();
    fn('b2b-sales-pipeline', '销售漏斗');
    assert.strictEqual(getCopied(), '销售漏斗');
    assert.ok(getToasted().endsWith('销售漏斗'));
    assert.ok(!getCopied().includes('b2b-sales-pipeline'));
});

test('剪贴板内容与 toast 一致（缺触发词时都退回技能名）', () => {
    const { fn, getCopied, getToasted } = load();
    fn('b2b-osint', '');
    assert.strictEqual(getCopied(), 'b2b-osint');
    assert.ok(getToasted().endsWith('b2b-osint'));
});
