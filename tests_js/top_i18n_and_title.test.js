'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');

test('P7: 英文界面顶栏状态文案与验厂标题走 i18n 且不含硬编码中文', () => {
    const fxSrc = fs.readFileSync(path.join(ROOT, 'static/js/fx.js'), 'utf8');
    const uiSrc = fs.readFileSync(path.join(ROOT, 'static/js/ui.js'), 'utf8');
    const i18nSrc = fs.readFileSync(path.join(ROOT, 'static/js/i18n.js'), 'utf8');

    assert.doesNotMatch(fxSrc, /'B2B 外贸助手/);
    assert.match(fxSrc, /STATUS_KEYS/);
    assert.match(fxSrc, /window\.refreshTopStatusText/);

    assert.doesNotMatch(uiSrc, /'visit':\s*\['验厂计划'/);
    assert.match(uiSrc, /'visit':\s*\[t\('nav\.visit'\)/);

    assert.match(i18nSrc, /'top\.status\.0':'B2B TRADE ASSISTANT · TRADE'/);
    assert.match(i18nSrc, /'nav\.visit':'Site Visit'/);
    assert.match(i18nSrc, /window\.refreshTopStatusText/);
});

test('U2: topMeta 支持回退 topMeta[v]，避免带 chatCtx 切到邮箱/定时任务时误显示旧标题', () => {
    const uiSrc = fs.readFileSync(path.join(ROOT, 'static/js/ui.js'), 'utf8');
    assert.match(uiSrc, /topMeta\[v \+ \(ctx \? '-' \+ ctx : ''\)\] \|\| topMeta\[v\]/);
});
