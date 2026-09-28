/**
 * api() 请求选项构造的行为测试 —— 零依赖（Node 内置 node:test）。
 *
 * 背景：前端原本有若干处手写 fetch，绕过了 api() 的超时与 401 自愈。
 * 收拢时最大的一处是文件上传（multipart）—— api() 原先只会 JSON.stringify(body)，
 * 所以先把「构造请求选项」抽成纯函数并支持 FormData，再让上传走 api()。
 */

const test = require('node:test');
const assert = require('node:assert');
const { loadRegion } = require('./_extract');

function loadBuildApiOpts(onNormalize) {
    const normalizeBody = onNormalize || ((b) => b);
    return loadRegion(
        'api-opts',
        '{ _buildApiOpts: _buildApiOpts }',
        { normalizeBody: normalizeBody, FormData: FormData },
    )._buildApiOpts;
}

test('带上会话与公司鉴权头', () => {
    const build = loadBuildApiOpts();

    const opts = build('GET', null, 'tok-123', 7);

    assert.strictEqual(opts.headers['X-Hermes-Session-Token'], 'tok-123');
    assert.strictEqual(opts.headers['X-Company-ID'], '7');
    assert.strictEqual(opts.method, 'GET');
});

test('token / 公司为空时不写该头（避免发出空鉴权头）', () => {
    const build = loadBuildApiOpts();

    const opts = build('GET', null, '', null);

    assert.ok(!('X-Hermes-Session-Token' in opts.headers));
    assert.ok(!('X-Company-ID' in opts.headers));
});

test('JSON body：设置 Content-Type 并序列化', () => {
    const build = loadBuildApiOpts();

    const opts = build('POST', { a: 1 }, 'tok', 1);

    assert.strictEqual(opts.headers['Content-Type'], 'application/json');
    assert.strictEqual(opts.body, '{"a":1}');
});

test('JSON body 会先过 normalizeBody（沿用原有规整逻辑）', () => {
    let called = false;
    const build = loadBuildApiOpts((b) => { called = true; return { normalized: true }; });

    const opts = build('POST', { a: 1 }, 'tok', 1);

    assert.strictEqual(called, true, 'normalizeBody 必须被调用');
    assert.strictEqual(opts.body, '{"normalized":true}');
});

test('FormData body：直接透传且不设 Content-Type（否则会丢 boundary）', () => {
    const build = loadBuildApiOpts();
    const form = new FormData();
    form.append('subdir', '报价单');

    const opts = build('POST', form, 'tok', 1);

    assert.strictEqual(opts.body, form, 'multipart body 必须原样透传');
    assert.ok(!('Content-Type' in opts.headers),
        'multipart 不能让调用方指定 Content-Type —— 浏览器需要自己带 boundary');
});

test('无 body：不设 body 也不设 Content-Type', () => {
    const build = loadBuildApiOpts();

    const opts = build('DELETE', null, 'tok', 1);

    assert.ok(!('body' in opts));
    assert.ok(!('Content-Type' in opts.headers));
});
