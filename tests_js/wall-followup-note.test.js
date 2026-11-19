/**
 * 主联系人卡片：客户级跟进备注单独一行（口径 C，2026-11-18）。
 * 人物 note 保持空；客户级 follow_up_note 只在这里展示，语义不混。
 */
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { loadRegion, SRC } = require('./_extract');

describe('wall-followup-note', () => {
    const tmap = {
        'cust.followup_note': '跟进备注',
        'cust.followup_note_hint': '客户级备注，显示在主联系人卡片',
    };
    const ctx = loadRegion('wall-followup-note', '{ _primaryFollowUpNoteHtml }', {
        esc: (s) => String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;'),
        t: (k) => tmap[k] || k,
    });

    it('主卡显示客户级跟进备注', () => {
        const html = ctx._primaryFollowUpNoteHtml('下周跟进报价', true);
        assert.match(html, /wall-followup-note/);
        assert.match(html, /跟进备注/);
        assert.match(html, /下周跟进报价/);
    });

    it('非主卡不显示', () => {
        assert.equal(ctx._primaryFollowUpNoteHtml('下周跟进报价', false), '');
    });

    it('空备注 / 纯空白不显示', () => {
        assert.equal(ctx._primaryFollowUpNoteHtml('', true), '');
        assert.equal(ctx._primaryFollowUpNoteHtml('   ', true), '');
        assert.equal(ctx._primaryFollowUpNoteHtml(null, true), '');
    });

    it('备注内容走 HTML 转义', () => {
        const html = ctx._primaryFollowUpNoteHtml('<img src=x onerror=alert(1)>', true);
        assert.doesNotMatch(html, /<img/);
        assert.match(html, /&lt;img/);
    });
});

// 接线级：函数本身全过但没人调用就是回归（d33b48f 就是这么漏掉的）
describe('wall-followup-note 接线', () => {
    it('openCustomerWall 人物卡片调用 _primaryFollowUpNoteHtml(e2.follow_up_note, isPrimary)', () => {
        assert.match(
            SRC,
            /_primaryFollowUpNoteHtml\(\s*e2\.follow_up_note\s*,\s*isPrimary\s*\)/,
            '主干墙人物卡片必须调用 _primaryFollowUpNoteHtml(e2.follow_up_note, isPrimary)',
        );
    });
});
