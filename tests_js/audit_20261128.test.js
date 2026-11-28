'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');

test('P2-3: chat.js 与 views.js 的 DOMPurify 白名单放开 details/summary 且禁止 data-*', () => {
    const chatJs = fs.readFileSync(path.join(ROOT, 'static/js/chat.js'), 'utf8');
    const viewsJs = fs.readFileSync(path.join(ROOT, 'static/js/views.js'), 'utf8');

    assert.match(chatJs, /ALLOWED_TAGS:[\s\S]*?'details'\s*,\s*'summary'/);
    assert.match(chatJs, /ALLOW_DATA_ATTR:\s*false/);
    assert.match(viewsJs, /ALLOWED_TAGS:[\s\S]*?'details'\s*,\s*'summary'/);
    assert.match(viewsJs, /ALLOW_DATA_ATTR:\s*false/);
});

test('P2-8 & P3-17: suppliers.js 不再传硬编码 budget: 180，且连续空响应终止轮询', () => {
    const supJs = fs.readFileSync(path.join(ROOT, 'static/js/suppliers.js'), 'utf8');
    assert.doesNotMatch(supJs, /budget\s*:\s*180/);
    assert.match(supJs, /missCount\s*>=\s*3/);
});

test('P2-4 & P2-B: wait.js 运行中禁用重试按钮，终态启用并在回调后刷新结论标签', () => {
    const waitJs = fs.readFileSync(path.join(ROOT, 'static/js/wait.js'), 'utf8');
    assert.match(waitJs, /data-pending-retry/);
    assert.match(waitJs, /retryBtn\.disabled\s*=\s*true/);
    assert.match(waitJs, /res\.overall_rating\s*&&\s*selfWait\.verdictEl/);
});
