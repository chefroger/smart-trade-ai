/**
 * 从 static/js 下的前端模块里按 `#region <name>` / `#endregion <name>` 标记抽出一段源码。
 *
 * 模块按 trade_chat.html 的 <script> 顺序拼回一份源码：标记和函数体与拆分前的
 * 单文件一致，段内函数之间的依赖（如 escJs → esc）仍在同一段作用域里。
 * 为什么用标记而不是大括号配对：源码里有正则字面量（如 /[&<>"']/g），任何基于引号
 * 状态机的配对都会把正则里的引号误判成字符串起点。
 */

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert');

const JS_DIR = path.join(__dirname, '..', 'static', 'js');
// 与 static/trade_chat.html 的脚本顺序一致：STATE 最先，INIT 最后。
const JS_ORDER = [
    'state.js',
    'i18n.js',
    'wizard.js',
    'api.js',
    'skills.js',
    'ui.js',
    'chat.js',
    'customers.js',
    'mailboxes.js',
    'suppliers.js',
    'views.js',
    'fx.js',
    'wait.js',
    'wait3d.js',
    'init.js',
];

/**
 * 按加载顺序读出全部前端模块并拼成一份源码。
 */
function readFrontendJs() {
    const parts = [];
    for (const name of JS_ORDER) {
        const file = path.join(JS_DIR, name);
        assert.ok(fs.existsSync(file), `static/js 缺少模块 ${name}`);
        parts.push(fs.readFileSync(file, 'utf8'));
    }
    return parts.join('');
}

const SRC = readFrontendJs();

/**
 * 取出指定区段的源码文本。标记缺失时断言失败，给出可读的失败原因。
 */
function extractRegion(name, src = SRC) {
    const begin = `// #region ${name}`;
    const end = `// #endregion ${name}`;
    const start = src.indexOf(begin);
    const stop = src.indexOf(end);
    assert.ok(start !== -1, `static/js 里必须存在标记 ${begin}`);
    assert.ok(stop > start, `static/js 里必须存在标记 ${end}`);
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

module.exports = { SRC, JS_DIR, JS_ORDER, readFrontendJs, extractRegion, loadRegion };
