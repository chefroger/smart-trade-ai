/**
 * O-新22：前端备忘录口令锁只统计真正的密语错误（403）。
 *
 * api() 失败时统一返回 null，调用方拿不到状态码；网络错、500、后端 429
 * 都被当成失败各加 1，连续网络抖动就会把用户锁 60 秒。后端节流才是
 * 真正的防线，前端锁只该跟 403 走。
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const API_SRC = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'api.js'), 'utf8');

function loadApi(fetchImpl) {
    const start = API_SRC.indexOf('async function api(');
    const end = API_SRC.indexOf('// ── 许可证 ──', start);
    assert.ok(start !== -1 && end > start, '找不到 api()');
    const body = API_SRC.slice(start, end);
    const factory = new Function(
        'fetch', 'TOKEN', 'currentCompanyId', '_buildApiOpts',
        'recoverAuth', 'toast', 't', 'showLicenseExpired', 'setTimeout', 'clearTimeout',
        'AbortController',
        body + '\nreturn api;',
    );
    return factory(
        fetchImpl, '', null,
        () => ({ headers: {}, method: 'POST' }),
        async () => null,
        () => {},
        (k) => k,
        () => {},
        (fn) => fn,
        () => {},
        class { constructor() { this.signal = null; } },
    );
}

function response(status) {
    return {
        ok: false,
        status,
        json: async () => ({ detail: 'x' }),
    };
}

test('api() 把 403 交给 onStatus', async () => {
    const api = loadApi(async () => response(403));
    let seen = 0;
    const out = await api('POST', '/x', {}, null, { silent: true, onStatus: (s) => { seen = s; } });
    assert.strictEqual(out, null);
    assert.strictEqual(seen, 403);
});

test('api() 把 500 / 429 也如实交给 onStatus（由调用方决定是否计数）', async () => {
    for (const status of [500, 429]) {
        const api = loadApi(async () => response(status));
        let seen = 0;
        await api('POST', '/x', {}, null, { silent: true, onStatus: (s) => { seen = s; } });
        assert.strictEqual(seen, status);
    }
});

test('备忘录只在 403 时计失败（源码断言）', () => {
    const src = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'customers.js'), 'utf8');
    assert.match(src, /if \(memoStatus === 403\) _memoNoteFailure\(\);/);
    assert.doesNotMatch(
        src,
        /if \(!data\) \{\s*_memoNoteFailure\(\);\s*return;\s*\}/,
        '未区分状态码就计数会重现 O-新22',
    );
    // 两次 memo POST 都要带 onStatus
    const calls = src.match(/'\/api\/trade\/customers\/' \+ cid \+ '\/memo'/g) || [];
    assert.strictEqual(calls.length, 2);
    const withCb = src.match(/onStatus: memoStatusCb/g) || [];
    assert.strictEqual(withCb.length, 2);
});
