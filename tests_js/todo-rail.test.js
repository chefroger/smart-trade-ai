/**
 * 右栏待办接线守卫（P2-12）。
 *
 * 背景：右栏「待办」原先显示的是今天的定时任务，并没有真正的待办存储。
 * 现在待办有独立后端（/api/trade/todos），右栏必须：
 *   - 拉 /todos 而不是复用 cron 数据
 *   - 支持添加（标题 / 截止日 / 客户）、勾选完成、删除
 *   - NEXT chip 的「加入待办」直接写库，不再往聊天框填指令
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const CHAT = fs.readFileSync(
    path.join(__dirname, '..', 'static', 'js', 'chat.js'), 'utf8');
const UI = fs.readFileSync(
    path.join(__dirname, '..', 'static', 'js', 'ui.js'), 'utf8');

test('待办走独立接口，不复用 cron 数据', () => {
    assert.match(CHAT, /api\('GET', '\/api\/trade\/todos'/, '必须请求 /todos');
    assert.match(CHAT, /function loadTodos\(/, '必须有独立的 loadTodos');
});

test('右栏渲染四组：逾期 / 今天 / 将来 / 已完成', () => {
    assert.match(CHAT, /d\.overdue/, '缺逾期组');
    assert.match(CHAT, /d\.today_items/, '缺今天组');
    assert.match(CHAT, /d\.upcoming/, '缺将来组');
    assert.match(CHAT, /d\.done/, '缺已完成组');
});

test('支持添加 / 勾选 / 删除', () => {
    assert.match(CHAT, /api\('POST', '\/api\/trade\/todos'/, '缺新增');
    assert.match(CHAT, /api\('PATCH', '\/api\/trade\/todos\/' \+ id/, '缺勾选更新');
    assert.match(CHAT, /api\('DELETE', '\/api\/trade\/todos\/' \+ id/, '缺删除');
});

test('新增时携带截止日与关联客户', () => {
    assert.match(CHAT, /todo-add-due/, '缺截止日输入');
    assert.match(CHAT, /todo-add-customer/, '缺客户下拉');
    assert.match(CHAT, /body\.due_date/, '请求体必须带 due_date');
    assert.match(CHAT, /body\.customer_id/, '请求体必须带 customer_id');
});

test('NEXT chip 的「加入待办」直接写库', () => {
    assert.match(CHAT, /_addTodoFromAction/, '缺 add_todo 处理函数');
    assert.doesNotMatch(
        CHAT,
        /prompt = \(currentLang === 'en' \? 'Add to todo: ' : '加入待办：'\)/,
        '旧的「填进聊天框」逻辑必须删掉',
    );
});

test('切视图时同时刷新待办', () => {
    assert.match(UI, /loadTodos\(true\)/, 'navToView 应刷新待办');
});

test('待办文案经过转义', () => {
    assert.match(CHAT, /esc\(item\.title\)/, '标题必须 esc');
    assert.match(CHAT, /esc\(sub\)/, '日期/客户副标题必须 esc');
    assert.match(CHAT, /esc\(c\.name\)/, '客户名必须 esc');
});
