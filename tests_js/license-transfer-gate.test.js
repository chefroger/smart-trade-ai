/**
 * 付费门禁：导入 / 导出入口只在**已激活（付费）**的界面上出现。
 *
 * 背景（2026-11-11）：公司数据打包导出/导入是迁移场景的核心功能，
 * 定价上属于付费能力。试用用户的界面上不应出现这两个按钮。
 *
 * 为什么做源码级断言：这两个入口分散在静态 HTML（导入按钮）和 JS
 * （导出按钮在 loadCompanyListUI() 里拼字符串），无法整段求值。
 *
 * 三条必须同时成立：
 *  1. 状态来源是 /api/trade/license/status 的 activated 字段；
 *  2. 导入入口默认隐藏（HTML 里带 hidden class），由 JS 按状态放行 ——
 *     否则试用用户会先看到按钮、再被藏掉（闪一下）；
 *  3. 导出按钮在渲染时就按状态决定渲不渲染，不靠事后隐藏。
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { SRC } = require('./_extract');

const HTML_PATH = path.join(__dirname, '..', 'static', 'trade_chat.html');
const HTML = fs.readFileSync(HTML_PATH, 'utf8');

test('许可证状态来自 /license/status 的 activated 字段', () => {
    assert.ok(
        /_licenseActivated\s*=\s*!!data\.activated/.test(SRC),
        '_licenseActivated 必须直接取 /license/status 返回的 activated',
    );
    const start = SRC.indexOf('async function loadLicenseStatus()');
    assert.ok(start !== -1, '找不到 loadLicenseStatus()');
    const end = SRC.indexOf('function showLicenseExpired', start);
    const body = SRC.slice(start, end > start ? end : start + 6000);
    assert.ok(/_applyLicenseGates\(\)/.test(body), '拿到许可证状态后必须调用 _applyLicenseGates()');
    assert.ok(/finally\s*\{[\s\S]*_applyLicenseGates\(\)/.test(body),
        '失败/超时路径也必须在 finally 里应用门禁');
});

test('导入入口默认隐藏，由 JS 按状态放行', () => {
    const m = /<div[^>]*id="import-company-row"[^>]*>/.exec(HTML);
    assert.ok(m, 'static/trade_chat.html 缺少 id="import-company-row" 的导入入口容器');
    assert.ok(
        /class="[^"]*\bhidden\b[^"]*"/.test(m[0]),
        '导入入口必须在 HTML 里默认带 hidden class（试用用户不该先看到再被藏）',
    );
    assert.ok(
        /import-company-row[\s\S]{0,300}classList\.toggle\('hidden',\s*!showPaid\)/.test(SRC),
        '_applyLicenseGates() 必须按 showPaid（付费或状态读取失败）开关导入入口',
    );
});

test('导出按钮在渲染时按状态决定，不事后隐藏', () => {
    const idx = SRC.indexOf('function loadCompanyListUI()');
    assert.ok(idx !== -1, '找不到 loadCompanyListUI()');
    const body = SRC.slice(idx, idx + 2000);
    assert.ok(
        /_licenseGateAllowsPaid\(\)\s*\?[\s\S]*?onclick="exportCompany\(/.test(body),
        '导出按钮必须写成「有付费权限才渲染」，不能无条件输出再靠 CSS 隐藏',
    );
});

test('试用期隐藏付费导航组 / ➕ / 左下角两个升级按钮', () => {
    // 导航三组：销售转化、工具、历史
    const paidSections = HTML.match(/<div class="nav-section[^"]*"[^>]*data-paid[^>]*>/g) || [];
    assert.strictEqual(paidSections.length, 3, '必须有三组 data-paid 导航');
    for (const tag of paidSections) {
        assert.ok(/class="[^"]*\bhidden\b/.test(tag), '付费导航组必须默认 hidden');
    }
    // 公司➕按钮
    const add = /<button[^>]*id="company-add-btn"[^>]*>/.exec(HTML);
    assert.ok(add, '找不到 company-add-btn');
    assert.ok(/data-paid/.test(add[0]) && /class="[^"]*\bhidden\b/.test(add[0]),
        '公司➕按钮必须 data-paid 且默认 hidden');
    // 左下角两个版本升级入口
    for (const id of ['system-update-btn', 'upgrade-help-btn']) {
        const btn = new RegExp(`<button[^>]*id="${id}"[^>]*>`).exec(HTML);
        assert.ok(btn, `找不到 #${id}`);
        assert.ok(/data-paid/.test(btn[0]) && /class="[^"]*\bhidden\b/.test(btn[0]),
            `#${id} 必须 data-paid 且默认 hidden`);
    }
});

test('门禁按 [data-paid] 统一开关，读取失败时 fail-open', () => {
    assert.ok(
        /querySelectorAll\('\[data-paid\]'\)[\s\S]{0,200}classList\.toggle\('hidden',\s*!showPaid\)/.test(SRC),
        '_applyLicenseGates 必须用 [data-paid] 统一 toggle hidden',
    );
    assert.ok(
        /function _licenseGateAllowsPaid\(\)\s*\{\s*return _licenseActivated \|\| _licenseGateUnknown;/.test(SRC),
        '付费权限 = 已激活 或 状态读取失败（fail-open）',
    );
    assert.ok(
        /catch\s*\(e\)\s*\{[\s\S]{0,200}_licenseGateUnknown\s*=\s*true/.test(SRC),
        '许可证读取失败必须置 _licenseGateUnknown',
    );
});

test('license.json 被删后回到页面会重新判定并退出付费视图', () => {
    assert.ok(
        /addEventListener\('focus'[\s\S]{0,120}loadLicenseStatus\(\)/.test(SRC),
        '窗口重新聚焦时应刷新许可证状态（删除 license.json 后无需刷新页面）',
    );
    assert.ok(
        /visibilitychange[\s\S]{0,160}loadLicenseStatus\(\)/.test(SRC),
        '页面重新可见时应刷新许可证状态',
    );
    assert.ok(
        /_isPaidDestination\(currentView, currentChatContext\)[\s\S]{0,160}navToView\('chat', 'daily'/.test(SRC.replace(/\s+/g, ' ')),
        '失去付费权限且当前停在付费视图时，应退回今日简报',
    );
});

test('付费视图/上下文有路由兜底', () => {
    assert.ok(/_PAID_VIEWS[\s\S]{0,200}customers[\s\S]{0,100}tasks[\s\S]{0,100}history/.test(SRC),
        '缺少付费视图集合');
    assert.ok(/_PAID_CHAT_CTX[\s\S]{0,160}docs[\s\S]{0,100}docgen[\s\S]{0,100}osint/.test(SRC),
        '缺少付费 chat 上下文集合');
    const navStart = SRC.indexOf('function navToView(');
    const navBody = SRC.slice(navStart, navStart + 1200);
    assert.ok(/_isPaidDestination\(view, chatCtx\)\s*&&\s*!_licenseGateAllowsPaid\(\)/.test(navBody),
        'navToView 必须拦截无权的付费目的地');
    assert.ok(/license\.paid_only/.test(navBody), '拦截时要提示付费专属');
});

test('试用用户拿不到导出/导入入口（两个按钮都不在 HTML 里裸奔）', () => {
    // 导入按钮：只允许出现在带 hidden 的容器里
    const importBtn = /<button[^>]*onclick="showImportCompanyDialog\(\)"[^>]*>/.exec(HTML);
    assert.ok(importBtn, '找不到导入按钮');
    const row = /<div[^>]*id="import-company-row"[^>]*>/.exec(HTML);
    assert.ok(
        row && row.index < importBtn.index,
        '导入按钮必须在 import-company-row 容器内（该容器默认 hidden）',
    );
    // 导出按钮：HTML 里不应有静态的导出按钮（它由 JS 按状态渲染）
    assert.ok(
        !/onclick="exportCompany\(/.test(HTML),
        'static/trade_chat.html 不应有静态导出按钮——它必须由 JS 按许可证状态渲染',
    );
});
