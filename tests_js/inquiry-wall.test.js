/**
 * 墙内询盘区渲染（空态 / 列表 / 手动角标）。
 */
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { loadRegion } = require('./_extract');

describe('wall-inquiries', () => {
    const tmap = {
        'inquiry.section': '询盘',
        'inquiry.empty': '暂无询盘，新建一个开始跟进',
        'inquiry.title_ph': '询盘标题',
        'inquiry.create': '新建询盘',
        'inquiry.delete': '删除',
        'inquiry.manual_badge': '手',
        'inquiry.manual_title': '手动锁定，点击卡片墙可改回自动',
    };
    const ctx = loadRegion(
        'wall-inquiries',
        '{ renderWallInquiriesSection, _stagePillsHtml }',
        {
            esc: (s) => String(s)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;'),
            t: (k) => tmap[k] || k,
            _CRM_STAGES: ['询盘', '报价', '样品', '订单'],
        }
    );

    it('空态文案', () => {
        const html = ctx.renderWallInquiriesSection([], () => '');
        assert.match(html, /暂无询盘，新建一个开始跟进/);
        assert.match(html, /新建询盘/);
        assert.match(html, /wall-inq-create/);
    });

    it('列表含标题、stage 下拉与删除', () => {
        const html = ctx.renderWallInquiriesSection(
            [{ id: 7, title: 'EU RFQ', stage: '报价' }],
            () => ''
        );
        assert.match(html, /EU RFQ/);
        assert.match(html, /data-inquiry-id="7"/);
        assert.match(html, /wall-inq-stage/);
        assert.match(html, /wall-inq-del/);
        assert.match(html, /报价/);
    });

    it('手动锁定角标出现在当前 stage pill', () => {
        const auto = ctx._stagePillsHtml('报价', true, false);
        assert.doesNotMatch(auto, /stage-manual-badge/);
        const manual = ctx._stagePillsHtml('报价', false, false);
        assert.match(manual, /stage-manual-badge/);
        assert.match(manual, /手/);
        assert.match(manual, /手动锁定/);
    });
});
