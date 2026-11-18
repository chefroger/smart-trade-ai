/**
 * 画像挂到下拉：options / 回显值 / 提交体 的纯函数。
 */
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { loadRegion } = require('./_extract');

const tmap = {
    'profile.attach_none': '不挂人',
    'profile.attach_primary': '主联系人：{name}',
    'profile.attach_primary_default': '主联系人',
    'profile.attach_contact_fallback': '附加联系人',
};
function t(key, params) {
    let s = tmap[key] || key;
    if (params) {
        Object.keys(params).forEach(function (k) {
            s = s.replace('{' + k + '}', String(params[k]));
        });
    }
    return s;
}
const esc = (s) => String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

const ctx = loadRegion(
    'profile-attach',
    '{ _profileAttachOptions, _profileAttachValue, _profileAttachBody, _profileAttachSelectHtml }',
    { t, esc }
);

const people = [
    { id: null, name: 'Hans Mueller', is_primary: true },
    { id: 7, name: 'Lena', is_primary: false },
];

describe('profile-attach', () => {
    it('有主联系人时选项含 none / primary / 每个附加联系人', () => {
        const opts = ctx._profileAttachOptions(people);
        assert.deepEqual(opts.map((o) => o.value), ['none', 'primary', 'contact:7']);
        assert.equal(opts[0].label, '不挂人');
        assert.equal(opts[1].label, '主联系人：Hans Mueller');
        assert.equal(opts[2].label, 'Lena');
    });

    it('没有主联系人时不出现 primary', () => {
        const opts = ctx._profileAttachOptions([{ id: 9, name: 'Mara' }]);
        assert.deepEqual(opts.map((o) => o.value), ['none', 'contact:9']);
    });

    it('条目回显值映射', () => {
        assert.equal(ctx._profileAttachValue({ attach_to: 'none' }), 'none');
        assert.equal(ctx._profileAttachValue({ attach_to: 'primary' }), 'primary');
        assert.equal(ctx._profileAttachValue({ attach_to: 'contact', contact_id: 7 }), 'contact:7');
        assert.equal(ctx._profileAttachValue({ attach_to: 'contact', contact_id: null }), 'none');
    });

    it('提交体解析', () => {
        assert.deepEqual(ctx._profileAttachBody('none'), { attach_to: 'none', contact_id: null });
        assert.deepEqual(ctx._profileAttachBody('primary'), { attach_to: 'primary', contact_id: null });
        assert.deepEqual(ctx._profileAttachBody('contact:7'), { attach_to: 'contact', contact_id: 7 });
        assert.deepEqual(ctx._profileAttachBody('contact:abc'), { attach_to: 'none', contact_id: null });
        assert.deepEqual(ctx._profileAttachBody(''), { attach_to: 'none', contact_id: null });
    });

    it('下拉 HTML 转义联系人名', () => {
        const html = ctx._profileAttachSelectHtml('pf-attach', [{ id: 3, name: '<img>' }], 'contact:3');
        assert.match(html, /&lt;img&gt;/);
        assert.doesNotMatch(html, /<img>/);
        assert.match(html, /value="contact:3" selected/);
    });
});
