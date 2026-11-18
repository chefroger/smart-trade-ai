/**
 * 画像出处：来源标签 + 日期（source_at 只截到 YYYY-MM-DD）。
 */
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { loadRegion } = require('./_extract');

const tmap = {
    'profile.src_chat': '对话',
    'profile.src_email': '邮件',
    'profile.src_visit': '验厂',
    'profile.src_manual': '手工',
};
const ctx = loadRegion(
    'profile-source',
    '{ _profileSourceLabel, _profileSourceDate }',
    { t: (k) => tmap[k] || k }
);

describe('profile-source', () => {
    it('来源类型标签', () => {
        assert.equal(ctx._profileSourceLabel({ source_type: 'chat' }), '对话');
        assert.equal(ctx._profileSourceLabel({ source_type: 'email' }), '邮件');
        assert.equal(ctx._profileSourceLabel({ source_type: 'visit' }), '验厂');
        assert.equal(ctx._profileSourceLabel({ source_type: 'manual' }), '手工');
        assert.equal(ctx._profileSourceLabel({}), '手工');
    });

    it('source_at 截到日期，空值返回空串', () => {
        assert.equal(ctx._profileSourceDate({ source_at: '2026-11-17T09:00:00+08:00' }), '2026-11-17');
        assert.equal(ctx._profileSourceDate({ source_at: '2026-11-18 10:00:00' }), '2026-11-18');
        assert.equal(ctx._profileSourceDate({ source_at: '' }), '');
        assert.equal(ctx._profileSourceDate({}), '');
    });
});
