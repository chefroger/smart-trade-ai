/**
 * esc() / escJs() 的行为测试 —— 零依赖（Node 内置 node:test）。
 *
 * 背景：static/trade_chat.js 是零构建工具的静态资源，没有模块导出。为了在 Node 侧
 * 测到真实的生产函数（而不是复制一份实现），这里按 `#region html-escape-utils` 标记
 * 从源码里抽出整段工具函数，再用 new Function 重建等价作用域取出来。
 */

const test = require('node:test');
const assert = require('node:assert');
const { loadRegion } = require('./_extract');

/** 模拟浏览器 textContent -> innerHTML 的序列化行为（不转义引号），供旧实现调用。 */
function makeDocumentShim() {
    return {
        createElement() {
            let text = '';
            return {
                set textContent(v) { text = v == null ? '' : String(v); },
                get textContent() { return text; },
                get innerHTML() {
                    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                },
            };
        },
    };
}

/**
 * 载入被测函数。production 代码里它们挂在全局作用域，测试侧用 new Function 重建
 * 一段等价作用域；document 作为形参注入，保证旧实现也能被调用。
 */
function loadEscUtils() {
    return loadRegion('html-escape-utils', '{ esc: esc, escJs: escJs }', { document: makeDocumentShim() });
}

/** 把 HTML 实体还原，用来模拟浏览器解析属性时的解码步骤。 */
function htmlDecode(s) {
    return s
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&');
}

const { esc, escJs } = loadEscUtils();

// ── esc()：HTML 文本 / 属性转义 ─────────────────────────────────────────────

test('esc 转义双引号，防止闭合 HTML 属性', () => {
    assert.strictEqual(esc('a"b'), 'a&quot;b');
});

test('esc 转义单引号', () => {
    assert.strictEqual(esc("a'b"), 'a&#39;b');
});

test('esc 保留 & < > 的转义（回归护栏）', () => {
    assert.strictEqual(esc('<script>&</script>'), '&lt;script&gt;&amp;&lt;/script&gt;');
});

test('esc 对 null / undefined / 空值返回空串（沿用原语义）', () => {
    assert.strictEqual(esc(null), '');
    assert.strictEqual(esc(undefined), '');
    assert.strictEqual(esc(''), '');
});

test('属性上下文：客户名里的引号无法闭合 value="..." 注入新属性', () => {
    const payload = 'x" autofocus onfocus="alert(1)';

    // 复刻 trade_chat.js 客户详情面板的写法
    const html = `<input type="text" value="${esc(payload)}">`;

    // 注入的引号若生效，就会出现「" + 空格 + autofocus」这种属性边界
    assert.ok(!html.includes('" autofocus'), `引号逃逸出了 value 属性：${html}`);

    // 反解 value 区间必须完整还原原值（旧实现下正则会提前撞上注入的引号，只能取到 "x"）
    const valueAttr = html.match(/value="([^"]*)"/);
    assert.ok(valueAttr, `value 属性结构被破坏：${html}`);
    assert.strictEqual(htmlDecode(valueAttr[1]), payload);
});

// ── escJs()：内联事件处理器里的 JS 字符串 ───────────────────────────────────

test('escJs 存在：内联 onclick 里的值需要 JS 字面量转义', () => {
    assert.strictEqual(typeof escJs, 'function');
});

test('escJs 产出可直接嵌入 onclick 的 JS 字面量，含引号与换行也不越狱', () => {
    const payload = "a'b\"c\nd\\e";

    const raw = escJs(payload);
    // 属性值里不能出现裸双引号，否则会闭合 onclick="..."
    assert.ok(!raw.includes('"'), `escJs 结果不应含裸双引号，实际：${raw}`);

    // 模拟浏览器：先 HTML 解码，再交给 JS 解析器 —— 必须是合法字面量且等于原值
    const asJs = htmlDecode(raw);
    const value = new Function('return ' + asJs)();
    assert.strictEqual(value, payload);
});

test('escJs 挡得住内联处理器注入（单引号闭合逃逸）', () => {
    const payload = "'); alert(1); //";

    const raw = escJs(payload);
    const asJs = htmlDecode(raw);
    // 必须仍解析为单个字符串字面量，而不是被拆成多条语句
    const value = new Function('return ' + asJs)();
    assert.strictEqual(value, payload);
});
