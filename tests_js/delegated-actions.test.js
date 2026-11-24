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
    target: { closest: (sel) => (sel === '[data-act]' ? el : null) },
    preventDefault() {},
  };
}

test('click 按 data-act 调全局函数并传 JSON 参数', () => {
  const { handlers, win } = load();
  const calls = [];
  win.myAction = (...args) => calls.push(args);
  const el = { dataset: { act: 'myAction', args: '["x",2]' }, value: '' };
  handlers.click(clickEvent(el));
  assert.deepStrictEqual(calls, [['x', 2]]);
});

test('data-event=1 传合成事件，currentTarget 指向按钮', () => {
  const { handlers, win } = load();
  let seen = null;
  win.withEvent = (ev, id) => { seen = { target: ev.currentTarget, id }; };
  const el = { dataset: { act: 'withEvent', event: '1', args: '[7]' }, value: '' };
  handlers.click(clickEvent(el));
  assert.strictEqual(seen.target, el);
  assert.strictEqual(seen.id, 7);
});

test('change 传元素 value；input 传元素本身', () => {
  const { handlers, win } = load();
  let changed = null;
  let inputted = null;
  win.onChange = (v) => { changed = v; };
  win.onInput = (el) => { inputted = el; };
  const select = { dataset: { onchange: 'onChange' }, value: 'en' };
  handlers.change({ target: { closest: () => select } });
  assert.strictEqual(changed, 'en');
  const input = { dataset: { oninput: 'onInput' } };
  handlers.input({ target: { closest: () => input } });
  assert.strictEqual(inputted, input);
});

test('未知动作只告警，不抛错', () => {
  const { handlers } = load();
  const el = { dataset: { act: '__missing__' }, value: '' };
  assert.doesNotThrow(() => handlers.click(clickEvent(el)));
});
