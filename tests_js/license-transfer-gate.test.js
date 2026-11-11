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
    assert.ok(
        /loadLicenseStatus[\s\S]{0,400}_applyLicenseGates\(\)/.test(SRC),
        '拿到许可证状态后必须调用 _applyLicenseGates()',
    );
});

test('导入入口默认隐藏，由 JS 按状态放行', () => {
    const m = /<div[^>]*id="import-company-row"[^>]*>/.exec(HTML);
    assert.ok(m, 'static/trade_chat.html 缺少 id="import-company-row" 的导入入口容器');
    assert.ok(
        /class="[^"]*\bhidden\b[^"]*"/.test(m[0]),
        '导入入口必须在 HTML 里默认带 hidden class（试用用户不该先看到再被藏）',
    );
    assert.ok(
        /import-company-row[\s\S]{0,200}classList\.toggle\('hidden',\s*!_licenseActivated\)/.test(SRC),
        '_applyLicenseGates() 必须按 _licenseActivated 开关导入入口的 hidden class',
    );
});

test('导出按钮在渲染时按状态决定，不事后隐藏', () => {
    const idx = SRC.indexOf('function loadCompanyListUI()');
    assert.ok(idx !== -1, '找不到 loadCompanyListUI()');
    const body = SRC.slice(idx, idx + 2000);
    assert.ok(
        /_licenseActivated\s*\?[\s\S]*?onclick="exportCompany\(/.test(body),
        '导出按钮必须写成「已激活才渲染」，不能无条件输出再靠 CSS 隐藏',
    );
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
