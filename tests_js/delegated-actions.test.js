/**
 * O-17 第二步：data-act 委托动作分发器。
 * 只按全局函数名 + JSON 字面量参数调用，不解析表达式、不 eval。
 */
const test = require('node:test');
const assert = require('node:assert');
const { loadRegion } = require('./_extract');

function load() {
  const handlers = {};
  const doc = { addEventListener(type, fn) { handlers[type] = fn; } };
  const fakeWindow = {};
  loadRegion(
    'delegated-actions',
    '{}',
    { document: doc, window: fakeWindow, console },
  );
  return { handlers, win: fakeWindow };
}

function clickEvent(el) {
  return {
    target: { closest: (sel) => (sel.indexOf('[data-act]') >= 0 ? el : null) },
    preventDefault() {},
  };
}

test('click 按 data-act 调全局函数并传 JSON 参数', () => {
  const { handlers, win } = load();
  const calls = [];
  win.navToView = (...args) => calls.push(args);
  const el = { dataset: { act: 'navToView', args: '["x",2]' }, value: '' };
  handlers.click(clickEvent(el));
  assert.deepStrictEqual(calls, [['x', 2]]);
});

test('data-event=1 传合成事件，currentTarget 指向按钮', () => {
  const { handlers, win } = load();
  let seen = null;
  win.doTradeUpdate = (ev, id) => { seen = { target: ev.currentTarget, id }; };
  const el = { dataset: { act: 'doTradeUpdate', event: '1', args: '[7]' }, value: '' };
  handlers.click(clickEvent(el));
  assert.strictEqual(seen.target, el);
  assert.strictEqual(seen.id, 7);
});

test('change 传元素 value；input 传元素本身', () => {
  const { handlers, win } = load();
  let changed = null;
  let inputted = null;
  win.switchLang = (v) => { changed = v; };
  win.filterCustomers = (el) => { inputted = el; };
  const select = { dataset: { onchange: 'switchLang' }, value: 'en' };
  handlers.change({ target: { closest: () => select } });
  assert.strictEqual(changed, 'en');
  const input = { dataset: { oninput: 'filterCustomers' } };
  handlers.input({ target: { closest: () => input } });
  assert.strictEqual(inputted, input);
});

test('未知动作只告警，不抛错', () => {
  const { handlers } = load();
  const el = { dataset: { act: '__missing__' }, value: '' };
  assert.doesNotThrow(() => handlers.click(clickEvent(el)));
});

test('所有 data-act 目标都有全局函数实现', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const { readFrontendJs } = require('./_extract');
  const src = readFrontendJs() + fs.readFileSync(
    path.join(__dirname, '..', 'static', 'trade_chat.html'), 'utf8',
  );
  const names = new Set();
  const re = /data-(?:act|pre|onchange|oninput|enter|keydown)="([A-Za-z_$][\w$]*)"/g;
  let m;
  while ((m = re.exec(src))) names.add(m[1]);
  const special = new Set(['closeBackdrop', 'copySelf', 'removeById', 'toastArg']);
  const missing = [];
  for (const name of names) {
    if (special.has(name)) continue;
    const def = new RegExp('(?:async\\s+)?function\\s+' + name + '\\s*\\(');
    if (!def.test(src)) missing.push(name);
  }
  assert.deepStrictEqual(missing, [], 'data-act 指向了不存在的函数');
});


test('未登记的动作绝不执行 window[任意字符串]（S1）', () => {
  const { handlers, win } = load();
  let called = 0;
  win.api = () => { called += 1; };
  const el = { dataset: { act: 'api', args: '["DELETE","/api/trade/customers/1"]' }, value: '' };
  handlers.click(clickEvent(el));
  assert.strictEqual(called, 0);
});

test('消息正文内不执行任何动作（S1）', () => {
  const { handlers, win } = load();
  let called = 0;
  win.navToView = () => { called += 1; };
  const el = {
    dataset: { act: 'navToView', args: '["customers"]' },
    closest: (sel) => (sel === '.msg-body' ? {} : null),
    value: '',
  };
  handlers.click(clickEvent(el));
  assert.strictEqual(called, 0);
});

test('sanitize 明确禁止 data-* 属性（S1）', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const chat = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'chat.js'), 'utf8');
  const views = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'views.js'), 'utf8');
  const count = (chat + views).match(/ALLOW_DATA_ATTR\s*:\s*false/g) || [];
  assert.strictEqual(count.length, 3, '三处 DOMPurify.sanitize 都必须禁止 data-*');
});
