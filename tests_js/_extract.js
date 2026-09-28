/**
 * 从 static/trade_chat.js 里按 `#region <name>` / `#endregion <name>` 标记抽出一段源码。
 *
 * 为什么用标记而不是大括号配对：源码里有正则字面量（如 /[&<>"']/g），任何基于引号
 * 状态机的配对都会把正则里的引号误判成字符串起点。标记法简单且不会误判。
 * 抽出的整段一起求值，段内函数之间的依赖（如 escJs → esc）也就自然在作用域里。
 */

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert');

const JS_PATH = path.join(__dirname, '..', 'static', 'trade_chat.js');
const SRC = fs.readFileSync(JS_PATH, 'utf8');

/**
 * 取出指定区段的源码文本。标记缺失时断言失败，给出可读的失败原因。
 */
function extractRegion(name, src = SRC) {
    const begin = `// #region ${name}`;
    const end = `// #endregion ${name}`;
    const start = src.indexOf(begin);
    const stop = src.indexOf(end);
    assert.ok(start !== -1, `static/trade_chat.js 里必须存在标记 ${begin}`);
    assert.ok(stop > start, `static/trade_chat.js 里必须存在标记 ${end}`);
    return src.slice(start, stop);
}

/**
 * 抽出区段并求值，返回段内声明的对象。
 * exportsExpr 形如 '{ esc: esc, escJs: escJs }'，用来把需要的函数取出区段作用域。
 * 额外的形参通过 params 传入（如 document），保证依赖 DOM 的实现也能被调用。
 */
function loadRegion(name, exportsExpr, params = {}) {
    const region = extractRegion(name);
    const names = Object.keys(params);
    const values = names.map((k) => params[k]);
    const body = region + `\nreturn ${exportsExpr};`;
    return new Function(...names, body)(...values);
}

module.exports = { SRC, JS_PATH, extractRegion, loadRegion };
