/**
 * 客户开发向导（V1）：聊天视图按栏目各缓存一份、id 相同，
 * 向导必须插到当前视图，且不能依赖可能已被历史消息移除的 #chat-empty。
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'wizard.js'), 'utf8');

test('向导在 currentChatContainer 内查找聊天容器', () => {
    assert.match(SRC, /currentChatContainer/, '必须用 currentChatContainer 限定作用域');
    assert.doesNotMatch(
        SRC,
        /document\.getElementById\('chat-messages'\)/,
        '不能全局 getElementById：会命中隐藏的其它栏目视图',
    );
});

test('不依赖 #chat-empty 是否存在', () => {
    assert.doesNotMatch(
        SRC,
        /if\s*\(!msgs\s*\|\|\s*!empty\)\s*return/,
        '有历史消息时空态会被移除，不能因此直接 return',
    );
});
