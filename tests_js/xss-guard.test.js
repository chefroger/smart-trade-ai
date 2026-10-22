/**
 * XSS 守卫：渲染用户可控数据时必须走 esc()。
 *
 * 背景（2026-10-22 审计）：客户等级 `tier` 与订单单位 `unit` 是自由文本
 * （CSV 批量导入 / API 写入都不校验），却被直接拼进 innerHTML ——
 * 同一行里其它字段（buyerType / note）都用了 esc()，唯独这两个漏了。
 * 攻击路径：导入 tier='<img src=x onerror=...>' → 客户列表面板执行脚本。
 */

const test = require('node:test');
const assert = require('node:assert');
const { SRC } = require('./_extract');

/** 找出所有 `${...}` 插值里**没有** esc()/escJs() 的表达式。 */
function unescapedInterpolations() {
    const out = [];
    const re = /\$\{([^{}]{1,80})\}/g;
    let m;
    while ((m = re.exec(SRC)) !== null) {
        const expr = m[1];
        if (expr.includes('esc(') || expr.includes('escJs(')) continue;
        out.push({ line: SRC.slice(0, m.index).split('\n').length, expr });
    }
    return out;
}

/**
 * 这些表达式的值是**用户可控的自由文本**，渲染时必须转义。
 * 数字 id / 颜色常量 / i18n 文案 / boolean 不在列。
 */
const MUST_ESCAPE = [
    { name: '客户等级 tier', re: /tierLabel|ex1\['tier'\]|extra1\['tier'\]/ },
    { name: '订单单位 unit', re: /o\.unit\b/ },
    { name: '客户名 name', re: /\bc\.name\b|\bcust\.name\b/ },
    { name: '订单产品名', re: /o\.product_name/ },
    { name: '公司名', re: /company\.name|co\.name/ },
];

test('用户可控字段的渲染都走了 esc()', () => {
    const bad = [];
    for (const item of unescapedInterpolations()) {
        for (const rule of MUST_ESCAPE) {
            if (rule.re.test(item.expr)) {
                bad.push(`  ${rule.name}: L${item.line} \${${item.expr}}`);
            }
        }
    }
    assert.strictEqual(
        bad.length, 0,
        '以下用户数据未转义就拼进 innerHTML（可被 CSV 导入注入脚本）：\n' + bad.join('\n'),
    );
});

test('tier 渲染点确实带 esc()', () => {
    assert.ok(
        /\$\{esc\(tierLabel\)\}/.test(SRC),
        '客户等级必须写成 ${esc(tierLabel)}',
    );
});

test('unit 渲染点确实带 esc()', () => {
    assert.ok(
        /esc\(o\.quantity\)\s*\+\s*esc\(o\.unit\|\|''\)/.test(SRC),
        '订单单位必须写成 esc(o.unit||\'\')',
    );
});
