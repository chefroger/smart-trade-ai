/**
 * 许可证状态条（U3）：剩余 ≤7 天才写「即将到期」，其余 active 写「有效期至」。
 * 只测纯函数 _licenseBarText，不依赖 DOM。
 */
const test = require('node:test');
const assert = require('node:assert');
const { loadRegion } = require('./_extract');

const ZH = {
    'license.active': '已激活',
    'license.expiring': '即将到期',
    'license.valid_until': '有效期至',
    'license.trial': '试用',
    'license.days_left': '剩余 {n} 天',
    'license.activate_btn': '激活',
    'license.req_code': '申请码',
    'license.expired': '已过期',
    'license.expired_soft': '数据仍在，起草暂停',
    'license.trial_summary': '草稿 {drafts} · 询盘 {inquiries} · 查询 {lookups}',
};
const EN = {
    'license.active': 'Active',
    'license.expiring': 'Expiring Soon',
    'license.valid_until': 'Valid until',
    'license.trial': 'Trial',
    'license.days_left': '{n} days left',
    'license.activate_btn': 'Activate',
};

function load(map) {
    return loadRegion(
        'license-bar',
        '{ _licenseBarText: _licenseBarText, LICENSE_EXPIRING_DAYS: LICENSE_EXPIRING_DAYS }',
        {
            t: (key, params) => {
                let s = Object.prototype.hasOwnProperty.call(map, key) ? map[key] : key;
                if (params) {
                    for (const k of Object.keys(params)) s = s.split('{' + k + '}').join(String(params[k]));
                }
                return s;
            },
            esc: (s) => String(s),
        },
    );
}

test('active 剩余 365 天：写「有效期至」，不写「即将到期」', () => {
    const api = load(ZH);
    const r = api._licenseBarText({ status: 'active', days_remaining: 365, expires_at: '2027-11-19T00:00:00' });
    assert.match(r.text, /有效期至 2027-11-19/);
    assert.doesNotMatch(r.text, /即将到期/);
    assert.strictEqual(r.tone, 'ok');
});

test('active 剩余 8 天：仍写「有效期至」', () => {
    const api = load(ZH);
    const r = api._licenseBarText({ status: 'active', days_remaining: 8, expires_at: '2026-11-27' });
    assert.match(r.text, /有效期至/);
    assert.strictEqual(r.tone, 'ok');
});

test('active 剩余 7 天：写「即将到期」，warn', () => {
    const api = load(ZH);
    const r = api._licenseBarText({ status: 'active', days_remaining: 7, expires_at: '2026-11-26' });
    assert.match(r.text, /即将到期/);
    assert.strictEqual(r.tone, 'warn');
});

test('active 剩余 0 天：即将到期 + danger', () => {
    const api = load(ZH);
    const r = api._licenseBarText({ status: 'active', days_remaining: 0 });
    assert.match(r.text, /即将到期/);
    assert.strictEqual(r.tone, 'danger');
});

test('active 无 expires_at：只写「已激活」', () => {
    const api = load(ZH);
    const r = api._licenseBarText({ status: 'active', days_remaining: 365 });
    assert.strictEqual(r.text, '✅ 已激活');
});

test('英文界面写 Valid until', () => {
    const api = load(EN);
    const r = api._licenseBarText({ status: 'active', days_remaining: 365, expires_at: '2027-11-19' });
    assert.match(r.text, /Valid until 2027-11-19/);
    assert.doesNotMatch(r.text, /Expiring Soon/);
});

test('expired / trial / tampered 输出与旧行为一致（关键片段）', () => {
    const api = load(ZH);
    const expired = api._licenseBarText({ status: 'expired' });
    assert.match(expired.text, /已过期/);
    assert.match(expired.text, /数据仍在/);
    assert.strictEqual(expired.tone, 'danger');

    const trial = api._licenseBarText({ status: 'trial', days_remaining: 20 });
    assert.match(trial.text, /试用/);
    assert.strictEqual(trial.tone, 'info');

    const trial7 = api._licenseBarText({ status: 'trial', days_remaining: 5 });
    assert.strictEqual(trial7.tone, 'warn');

    const tampered = api._licenseBarText({ status: 'tampered' });
    assert.match(tampered.text, /License Error/);
    assert.strictEqual(tampered.tone, 'danger');
});

test('阈值常量固定为 7 天', () => {
    const api = load(ZH);
    assert.strictEqual(api.LICENSE_EXPIRING_DAYS, 7);
});
