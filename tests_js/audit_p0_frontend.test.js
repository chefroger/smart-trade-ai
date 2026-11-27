'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');

test('审计 P0: SSE eventType/dataStr 声明在 while 循环外，防止跨 chunk 丢事件', () => {
    const chatSrc = fs.readFileSync(path.join(ROOT, 'static/js/chat.js'), 'utf8');
    const viewsSrc = fs.readFileSync(path.join(ROOT, 'static/js/views.js'), 'utf8');
    assert.match(chatSrc, /let eventType = '', dataStr = '';\s*\n\s*while \(true\)/);
    assert.match(viewsSrc, /var eventType = '', dataStr = '';\s*\n\s*while \(true\)/);
});

test('审计 P0: 客户墙双击编辑对话标题不再引用未定义的 sumEl', () => {
    const custSrc = fs.readFileSync(path.join(ROOT, 'static/js/customers.js'), 'utf8');
    assert.match(custSrc, /const sumEl = card\.querySelector\(/);
    assert.match(custSrc, /card\.setAttribute\('data-conv-summary',\s*nextSummary\)/);
});

test('审计 P0: 增删自定义定时任务模板刷新 viewCache[tasks]，不覆写隐藏对话视图', () => {
    const viewsSrc = fs.readFileSync(path.join(ROOT, 'static/js/views.js'), 'utf8');
    assert.doesNotMatch(viewsSrc, /const ct = currentChatContainer;\s*\n\s*if \(ct && currentView === 'tasks'\)/);
    assert.match(viewsSrc, /const ct = viewCache\['tasks'\] && viewCache\['tasks'\]\.element;/);
});

test('审计 P0: onCompanyChange 清空 allCustomers 等全局业务缓存防跨公司串数据', () => {
    const viewsSrc = fs.readFileSync(path.join(ROOT, 'static/js/views.js'), 'utf8');
    assert.match(viewsSrc, /if \(typeof allCustomers !== 'undefined'\) allCustomers = \[\];/);
    assert.match(viewsSrc, /if \(typeof allConversations !== 'undefined'\) allConversations = \[\];/);
    assert.match(viewsSrc, /if \(typeof _todosData !== 'undefined'\) _todosData = \[\];/);
});
