'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');

test('P3: 新手引导传入 #onboarding-results-area 时内嵌挂载，不打开全局 .wait-dock', () => {
    const chatSrc = fs.readFileSync(path.join(ROOT, 'static/js/chat.js'), 'utf8');
    assert.match(chatSrc, /function _attachOsintTaskPanel\(container,\s*job\)/);
    assert.match(chatSrc, /container\.id === 'onboarding-results-area'/);
    assert.match(chatSrc, /onb-osint-inline/);
    assert.match(chatSrc, /!p\.inline/);
    assert.match(chatSrc, /wd-close/);
});

test('P3: .wait-dock 宽度收缩到右下角（<= 460px），不再横跨 980px 遮挡页面', () => {
    const waitCss = fs.readFileSync(path.join(ROOT, 'static/wait.css'), 'utf8');
    assert.doesNotMatch(waitCss, /width:\s*min\(980px/);
    assert.match(waitCss, /width:\s*min\(460px/);
});

test('P4: 新手引导出结果后加宽卡片且表格支持横向滚动不裁切', () => {
    const css = fs.readFileSync(path.join(ROOT, 'static/trade_chat.css'), 'utf8');
    const viewsSrc = fs.readFileSync(path.join(ROOT, 'static/js/views.js'), 'utf8');
    assert.match(css, /\.onboarding-card\.has-results\s*\{[\s\S]*max-width:\s*min\(1040px/);
    assert.match(css, /\.onboarding-response\s*\{[\s\S]*overflow-x:\s*auto/);
    assert.match(css, /\.onboarding-response table\s*\{[\s\S]*width:\s*max-content/);
    assert.match(viewsSrc, /card\.classList\.add\('has-results'\)/);
});
