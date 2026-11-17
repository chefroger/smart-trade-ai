/**
 * 语法守卫：static/js 下每个前端模块都必须能通过 node 的语法解析。
 *
 * 为什么需要单独一条：这些文件没有构建步骤，也没有打包器 —— 一个语法错误
 * 在开发机上不会以任何方式暴露（浏览器打开才白屏），而其余 JS 测试是按
 * `#region` 抽取片段求值，**不解析文件其余部分**，所以语法错误会静默通过。
 *
 * 实际发生过（本次修复过程中）：在 JSDoc 里写了 `*` + `/5` 这样的字符序列，
 * 其中的斜杠星号**提前终止了块注释**，把后面整段代码变成语法错误。
 */

const test = require('node:test');
const assert = require('node:assert');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { JS_DIR, JS_ORDER } = require('./_extract');

test('每个前端模块语法可解析', () => {
    for (const name of JS_ORDER) {
        const file = path.join(JS_DIR, name);
        try {
            execFileSync(process.execPath, ['--check', file], { stdio: 'pipe' });
        } catch (e) {
            const detail = (e.stderr || e.stdout || Buffer.from('')).toString();
            assert.fail(`static/js/${name} 存在语法错误：\n${detail}`);
        }
    }
});

test('HTML 先内联 TOKEN，再按模块顺序加载', () => {
    const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'trade_chat.html'), 'utf8');
    const tokenAt = html.indexOf('<script>let TOKEN = "__TRADE_SESSION_TOKEN__";</script>');
    assert.ok(tokenAt !== -1, 'TOKEN 内联脚本必须留在模块脚本之前');
    let cursor = tokenAt;
    for (const name of JS_ORDER) {
        const tag = `<script src="/static/js/${name}"></script>`;
        const at = html.indexOf(tag, cursor);
        // 顺序错了或漏了一个模块，后加载的脚本会在依赖还没声明时执行
        assert.ok(at > cursor, `trade_chat.html 未按顺序加载 ${name}`);
        cursor = at + tag.length;
    }
});
