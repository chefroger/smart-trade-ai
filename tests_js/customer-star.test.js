/**
 * 详情页头星标：后端只有 is_starred，没有 starred（P2，d33b48f 写错过）。
 * 这里钉住字段名，防止再写成不存在的 c.starred 导致星标恒不亮。
 */
const test = require('node:test');
const assert = require('node:assert');
const { SRC } = require('./_extract');

test('详情页星标用 is_starred 计算', () => {
    assert.match(
        SRC,
        /const starred = Number\(c\.is_starred\)\s*===\s*1;/,
        '详情页头星标必须用 Number(c.is_starred) === 1',
    );
});

test('不得使用不存在的 c.starred 字段', () => {
    assert.doesNotMatch(
        SRC,
        /c\.starred\s*\|\|/,
        '后端没有 c.starred 字段，使用它会让星标恒不亮',
    );
});
