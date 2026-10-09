/**
 * 语法守卫：static/trade_chat.js 必须能通过 node 的语法解析。
 *
 * 为什么需要单独一条：这个文件没有构建步骤，也没有打包器 —— 一个语法错误
 * 在开发机上不会以任何方式暴露（浏览器打开才白屏），而其余 JS 测试是按
 * `#region` 抽取片段求值，**不解析文件其余部分**，所以语法错误会静默通过。
 *
 * 实际发生过（本次修复过程中）：在 JSDoc 里写了 `*` + `/5` 这样的字符序列，
 * 其中的斜杠星号**提前终止了块注释**，把后面整段代码变成语法错误。
 */

const test = require('node:test');
const assert = require('node:assert');
const { execFileSync } = require('node:child_process');
const path = require('node:path');

const JS_PATH = path.join(__dirname, '..', 'static', 'trade_chat.js');

test('trade_chat.js 语法可解析', () => {
    try {
        execFileSync(process.execPath, ['--check', JS_PATH], { stdio: 'pipe' });
    } catch (e) {
        const detail = (e.stderr || e.stdout || Buffer.from('')).toString();
        assert.fail(`static/trade_chat.js 存在语法错误：\n${detail}`);
    }
});
