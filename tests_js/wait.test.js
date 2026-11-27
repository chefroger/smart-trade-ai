/**
 * TradeWait（static/js/wait.js）行为测试。
 *
 * 组件是 DOM + Canvas2D 实现，这里用最小 DOM/Canvas 桩把它跑起来，
 * 只验证协议和降级规则，不验证像素。
 */
const test = require('node:test');
const assert = require('node:assert');
const { loadRegion } = require('./_extract');

function makeCtx() {
  const gradient = { addColorStop() {} };
  return new Proxy({}, {
    get(target, prop) {
      if (prop === 'measureText') return () => ({ width: 40 });
      if (prop === 'createLinearGradient' || prop === 'createConicGradient') return () => gradient;
      if (prop === 'canvas') return null;
      if (prop in target) return target[prop];
      return () => {};
    },
    set(target, prop, value) { target[prop] = value; return true; },
  });
}

function makeEl(tag) {
  const handlers = {};
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    children: [], parentNode: null, className: '', id: '', textContent: '',
    style: {}, attrs: {}, dataset: {},
    offsetWidth: 120, clientWidth: 480, clientHeight: 360,
    scrollTop: 0, scrollHeight: 0,
    classList: {
      _s: new Set(),
      add(c) { this._s.add(c); },
      remove(c) { this._s.delete(c); },
      toggle(c, on) { if (on === undefined ? !this._s.has(c) : on) this._s.add(c); else this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    },
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; },
    insertBefore(c) { this.children.push(c); c.parentNode = this; return c; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    removeAttribute(k) { delete this.attrs[k]; },
    getAttribute(k) { return this.attrs[k]; },
    addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
    removeEventListener() {},
    focus() {}, remove() { if (this.parentNode) this.parentNode.removeChild(this); },
    querySelector() { return makeEl('div'); },
    querySelectorAll() { return []; },
    getContext() { return makeCtx(); },
    _handlers: handlers,
    _click() { (handlers.click || []).forEach((fn) => fn({})); },
  };
  let html = '';
  Object.defineProperty(el, 'innerHTML', {
    get() { return html; },
    set(v) { html = String(v); this.children = []; },
  });
  return el;
}

function makeDocument() {
  const byId = {
    'app-top-status': makeEl('span'),
    'sys-status': makeEl('span'),
  };
  byId['app-top-status'].textContent = 'B2B 外贸助手 · TRADE';
  byId['sys-status'].textContent = 'B2B 外贸助手 · TRADE';
  const body = makeEl('body');
  body.classList.add('profile-open');
  body.classList.remove('profile-open');
  const doc = {
    body,
    hidden: false,
    createElement: (tag) => makeEl(tag),
    createTextNode: (text) => { const e = makeEl('#text'); e.textContent = String(text); return e; },
    getElementById: (id) => byId[id] || null,
    addEventListener() {},
  };
  return { doc, byId };
}

function makeWindow(opts) {
  opts = opts || {};
  const mq = {
    matches: !!opts.reduceMotion,
    addEventListener() {},
  };
  const win = {
    matchMedia: () => mq,
    devicePixelRatio: 1,
    ResizeObserver: class { observe() {} disconnect() {} },
    IntersectionObserver: class { constructor(cb) { this.cb = cb; } observe() {} disconnect() {} },
    requestAnimationFrame: () => 0,
  };
  return win;
}

function loadComponent(opts) {
  opts = opts || {};
  const { doc, byId } = makeDocument();
  const win = makeWindow(opts);
  const store = opts.storage || {};
  const localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
  };
  const code = loadRegion('wait', '{ TradeWait: window.TradeWait, Wait: null }',
    // 区段内只用了这些自由变量
    { window: win, document: doc, localStorage, requestAnimationFrame: win.requestAnimationFrame,
      ResizeObserver: win.ResizeObserver, IntersectionObserver: win.IntersectionObserver });
  // loadRegion 已执行整个 IIFE，window.TradeWait 已就位
  return { SW: win.TradeWait, doc, byId, win, store, code };
}

function mountTask(env) {
  const host = makeEl('div');
  const wait = env.SW.mount(host, { mode: 'task', title: '背调', statusLabel: '背调进行中' });
  return { host, wait };
}

test('redact 屏蔽邮箱与长数字', () => {
  const env = loadComponent();
  const out = env.SW.redact('联系 a.b@example.com，电话 13812345678');
  assert.match(out, /\[邮箱已隐藏\]/);
  assert.match(out, /\[号码已隐藏\]/);
  assert.ok(!out.includes('a.b@example.com'));
  env.SW._engine.list.slice().forEach((w) => w.destroy());
});

test('push 只读白名单字段：args 不进入任何读数', () => {
  const env = loadComponent();
  const { wait } = mountTask(env);
  wait.push({ type: 'job_start', target: 'acme.com', budget: 150, args: { secret: '客户资料' } });
  assert.strictEqual(wait.targetEl.textContent, 'acme.com');
  const dump = JSON.stringify(wait.logEl.children.map((c) => c.textContent));
  assert.ok(!dump.includes('cecret') && !dump.includes('客户资料'), 'args 不得进入任务读数');
  wait.destroy();
});

test('source_start / source_done 产生真实节点计数', () => {
  const env = loadComponent();
  const { wait } = mountTask(env);
  wait.push({ type: 'source_start', source: 'rdap', label: 'RDAP 域名注册' });
  wait.push({ type: 'source_start', source: 'ct', label: '证书透明度（CT）' });
  assert.strictEqual(wait.sources.length, 2);
  // 大动画文案跟随当前真实来源（不是只显示阶段名）
  assert.strictEqual(wait.zhEl.textContent, '正在查询：证书透明度（CT）');
  assert.strictEqual(wait.phaseKey, 'correlating');
  wait.push({ type: 'source_done', source: 'rdap', status: 'hit', ms: 1900 });
  assert.strictEqual(wait.countEl.textContent, '1 / 2 SOURCES');
  assert.strictEqual(wait.progTxt.textContent, '1 / 2');
  assert.strictEqual(wait.sources[0].status, 'hit');
  assert.strictEqual(wait.zhEl.textContent, '命中：RDAP 域名注册');
  wait.destroy();
});

test('verdict 后进入完成态并禁用取消', () => {
  const env = loadComponent();
  const { wait } = mountTask(env);
  wait.push({ type: 'verdict', rating: '低风险', unverified: [] });
  assert.strictEqual(wait.final, true);
  assert.strictEqual(wait.phaseKey, 'acquired');
  assert.strictEqual(wait.cancelBtn.disabled, true);
  wait.destroy();
});

test('取消按钮触发 onCancel 并进入 aborted', () => {
  const env = loadComponent();
  const host = makeEl('div');
  let cancelled = 0;
  const wait = env.SW.mount(host, { mode: 'chat', onCancel: () => { cancelled++; } });
  assert.ok(wait.cancelBtn._handlers.click && wait.cancelBtn._handlers.click.length);
  wait.cancelBtn._click();
  assert.strictEqual(cancelled, 1);
  assert.strictEqual(wait.phaseKey, 'aborted');
  wait.destroy();
});

test('onDismiss 只收起，不结束任务', () => {
  const env = loadComponent();
  const host = makeEl('div');
  let dismissed = 0;
  const wait = env.SW.mount(host, {
    mode: 'task',
    cancelText: '收起',
    onDismiss: () => { dismissed++; },
  });
  wait.cancelBtn._click();
  assert.strictEqual(dismissed, 1);
  assert.strictEqual(wait.final, false, '收起不应结束任务');
  assert.notStrictEqual(wait.phaseKey, 'aborted');
  wait.destroy();
});

test('连续高帧耗时降级到静态档', () => {
  const env = loadComponent();
  const { wait } = mountTask(env);
  env.SW.debugCost = 14;
  for (let i = 0; i < 24; i++) wait._frame(i * 40);
  env.SW.debugCost = 0;
  assert.strictEqual(wait.quality, 0, '超过 12ms 应降到静态档');
  assert.strictEqual(wait.animating, false);
  wait.destroy();
});

test('trade_fx=0 与 reduced-motion 都只显示静态帧', () => {
  const off = loadComponent({ storage: { trade_fx: '0' } });
  const a = mountTask(off).wait;
  assert.strictEqual(a.animating, false);
  a.destroy();

  const rm = loadComponent({ reduceMotion: true });
  const b = mountTask(rm).wait;
  assert.strictEqual(b.animating, false);
  b.destroy();
});

test('画像页打开时等待状态不覆盖顶栏统计，关闭后恢复接管', () => {
  const env = loadComponent();
  env.doc.body.classList.add('profile-open');
  env.byId['app-top-status'].textContent = '已确认 3 · 待确认 1';
  const { wait } = mountTask(env);
  assert.strictEqual(env.byId['app-top-status'].textContent, '已确认 3 · 待确认 1');
  assert.strictEqual(env.byId['sys-status'].textContent, '背调进行中');
  env.doc.body.classList.remove('profile-open');
  env.win.TradeWaitStatus.refresh();
  assert.strictEqual(env.byId['app-top-status'].textContent, '背调进行中');
  wait.destroy();
});

test('多个后台任务在顶栏汇总真实来源计数', () => {
  const env = loadComponent();
  const a = mountTask(env).wait;
  const b = mountTask(env).wait;
  a.push({type: 'source_start', source: 'a1', label: 'A1'});
  a.push({type: 'source_done', source: 'a1', status: 'hit', ms: 1});
  b.push({type: 'source_start', source: 'b1', label: 'B1'});
  const text = env.win.TradeWaitStatus.text();
  assert.strictEqual(text, '后台任务 1/2');
  a.destroy(); b.destroy();
});

test('顶栏同时接管两个状态元素，画像页优先', () => {
  const env = loadComponent();
  const { wait } = mountTask(env);
  assert.strictEqual(env.byId['app-top-status'].textContent, '背调进行中');
  assert.strictEqual(env.byId['sys-status'].textContent, '背调进行中');
  wait.sources.push({ key: 'a', label: 'A', status: 'running' });
  wait.push({ type: 'source_done', source: 'a', status: 'hit', ms: 1 });
  wait.destroy();
  assert.strictEqual(env.byId['app-top-status'].textContent, 'B2B 外贸助手 · TRADE');
  assert.strictEqual(env.byId['sys-status'].textContent, 'B2B 外贸助手 · TRADE');
});

test('verdict=limited 显示「仅完成制裁筛查」，不写成已完成', () => {
  const env = loadComponent();
  const { wait } = mountTask(env);
  wait.push({ type: 'verdict', rating: 'limited', unverified: [] });
  assert.strictEqual(wait.final, true);
  assert.strictEqual(wait.phaseKey, 'acquired');
  // 终态文案与大动画读数都必须是「仅完成制裁筛查」
  assert.match(wait.zhEl.textContent, /仅完成制裁筛查/);
  // 日志行是 span 嵌套：桩 DOM 不合成 textContent，手动收集每行文本
  const dump = wait.logEl.children.map(function (row) {
    return (row.children || []).map(function (c) {
      return String(c.textContent || '') + (c.children || []).map(function (g) {
        return String(g.textContent || '');
      }).join('');
    }).join(' ');
  }).join(' | ');
  assert.match(dump, /仅完成制裁筛查/);
  assert.ok(!/已完成$/.test(wait.zhEl.textContent), '不得把 limited 显示成已完成');
  wait.destroy();
});

test('finish 之后 phase 不再改文案（W15 O-24）', () => {
  const env = loadComponent();
  const { wait } = mountTask(env);
  wait.finish({ phase: 'acquired' });
  const before = wait.zhEl.textContent;
  wait.phase('searching', '不该出现');
  assert.strictEqual(wait.zhEl.textContent, before);
  wait.destroy();
});

test('O-等待1：failed 终态按钮文案为「已失败」，aborted 为「已停止」，成功类为「完成」', () => {
  const env = loadComponent();

  const wFail = mountTask(env).wait;
  wFail.push({ type: 'error', message: 'boom' });
  assert.strictEqual(wFail.phaseKey, 'failed');
  assert.strictEqual(wFail.cancelBtn.disabled, true);
  assert.strictEqual(wFail.cancelBtn.textContent, '已失败');
  wFail.destroy();

  const wAbort = mountTask(env).wait;
  wAbort.finish({ phase: 'aborted' });
  assert.strictEqual(wAbort.cancelBtn.textContent, '已停止');
  wAbort.destroy();

  ['acquired', 'partial', 'done'].forEach((ph) => {
    const wOk = mountTask(env).wait;
    wOk.finish({ phase: ph });
    assert.strictEqual(wOk.cancelBtn.textContent, '完成', `终态 ${ph} 应显示完成`);
    wOk.destroy();
  });
});

test('O-等待2：2D 共享引擎单实例 _frame 抛错时降级该实例，不阻塞其余实例动画', () => {
  const env = loadComponent();
  const broken = mountTask(env).wait;
  const healthy = mountTask(env).wait;

  let brokenCalls = 0;
  let healthyCalls = 0;
  broken._frame = () => {
    brokenCalls++;
    throw new Error('canvas draw failed');
  };
  healthy._frame = () => {
    healthyCalls++;
  };

  assert.strictEqual(broken.animating, true);
  assert.strictEqual(healthy.animating, true);

  assert.doesNotThrow(() => env.SW._engine.tick(100));
  assert.strictEqual(brokenCalls, 1);
  assert.strictEqual(broken.animating, false, '抛错实例应降为静态');
  assert.strictEqual(broken.root.classList.contains('is-static'), true);
  assert.strictEqual(healthyCalls, 1, '正常实例应照常执行');
  assert.strictEqual(healthy.animating, true);

  // 下一帧：降级实例不再触发，正常实例继续运行
  assert.doesNotThrow(() => env.SW._engine.tick(200));
  assert.strictEqual(brokenCalls, 1);
  assert.strictEqual(healthyCalls, 2);

  broken.destroy();
  healthy.destroy();
});
