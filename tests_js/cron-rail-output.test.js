/**
 * 右栏「定时任务输出」（#rail-cron）渲染回归测试：
 * 1. 未选公司或无激活任务时必须渲染标题与引导，不得留空白；
 * 2. 展示全部已设置并激活的 Hermes cron 任务（不截断前 4 条），区分今日产出 / 历史产出 / 待首次执行；
 * 3. Markdown 摘要去噪且所有动态文本严格 HTML 转义。
 */
const test = require('node:test');
const assert = require('node:assert');
const { loadRegion } = require('./_extract');

const { esc } = loadRegion('html-escape-utils', '{ esc: esc }');

const I18N = {
    'brief.cron': '定时任务输出',
    'brief.cron_no_jobs': '暂无已激活的定时任务',
    'brief.cron_setup': '去设置定时任务 →',
    'brief.cron_waiting': '待首次执行',
    'brief.cron_silent': '无新内容',
    'brief.cron_today_tag': '今日',
    'brief.cron_view_full': '点击查看完整定时任务输出',
};

function mountRail() {
    const railEl = { innerHTML: '' };
    const ctx = loadRegion(
        'cron-rail-render',
        '{ _cronOutputPreview, _formatCronRunBadge, _renderRailCron }',
        {
            esc,
            t: (k) => I18N[k] || k,
            iconHtml: () => '<i class="ic"></i>',
            document: {
                getElementById: (id) => (id === 'rail-cron' ? railEl : null),
            },
            _cronOutputsByJob: {},
        },
    );
    return { railEl, ...ctx };
}

test('未选公司（null）时渲染标题与空态说明，不留空白框', () => {
    const { railEl, _renderRailCron } = mountRail();
    _renderRailCron(null);
    assert.match(railEl.innerHTML, /定时任务输出/);
    assert.match(railEl.innerHTML, /暂无已激活的定时任务/);
});

test('无激活任务时给出跳转到定时任务页的按钮', () => {
    const { railEl, _renderRailCron } = mountRail();
    _renderRailCron({ active_items: [], completed: [], pending: [] });
    assert.match(railEl.innerHTML, /data-act="navToView"/);
    assert.match(railEl.innerHTML, /去设置定时任务/);
});

test('完整展示全部 5 个已激活任务（不截断为 4 个）并区分今日/历史/待执行', () => {
    const { railEl, _renderRailCron } = mountRail();
    _renderRailCron({
        active_items: [
            { job_id: 'j1', name: '🌅 早安简报', time: '09:00', run_at: '2026-11-26 09:04', is_today: true, output: '# 早安简报\n\n**美元 USD**: 6.7088' },
            { job_id: 'j2', name: '🔍 精准加人', time: '10:00', run_at: '2026-11-25 10:07', is_today: false, output: 'LinkedIn 加人方案' },
            { job_id: 'j3', name: '💬 评论互动', time: '11:30', run_at: '2026-11-25 11:33', is_today: false, output: '互动清单' },
            { job_id: 'j4', name: '🏪 平台检查', time: '15:30', run_at: null, is_today: false, output: null, schedule: '30 15 * * 1-5' },
            { job_id: 'j5', name: '📊 每日总结', time: '17:00', run_at: '2026-11-26 17:01', is_today: true, output: null, silent: true },
        ],
    });
    assert.match(railEl.innerHTML, /CRON · 5/);
    assert.match(railEl.innerHTML, /今日 09:04/);
    assert.match(railEl.innerHTML, /11-25 10:07/);
    assert.match(railEl.innerHTML, /15:30 · 待首次执行/);
    assert.match(railEl.innerHTML, /无新内容/);
    assert.match(railEl.innerHTML, /美元 USD : 6\.7088/);
    assert.match(railEl.innerHTML, /data-act="openCronOutputModal" data-arg="j1"/);
});

test('任务名与产出摘要严格转义防 XSS', () => {
    const { railEl, _renderRailCron } = mountRail();
    _renderRailCron({
        active_items: [
            { job_id: 'j"><script>', name: '<img src=x onerror=1>', time: '09:00', is_today: true, output: '<svg onload=alert(1)>' },
        ],
    });
    assert.doesNotMatch(railEl.innerHTML, /<img/);
    assert.doesNotMatch(railEl.innerHTML, /<svg/);
    assert.doesNotMatch(railEl.innerHTML, /<script>/);
});
