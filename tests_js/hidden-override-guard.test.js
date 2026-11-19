/**
 * hidden 覆盖守卫（U1）：
 * 任何在 class="..." 里与 hidden 同时出现的 class，如果 CSS 给了它
 * `display: <非 none> !important`，那么 .hidden 就失效（同特异性、后写）。
 * 这类必须补一条 `.X.hidden { display: none !important; }`。
 *
 * 实测曾导致：「■ 停止」按钮空闲时常驻（chat-stop-btn 写了 inline-flex !important）。
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const JS_DIR = path.join(ROOT, 'static', 'js');
const HTML = path.join(ROOT, 'static', 'trade_chat.html');
const CSS = path.join(ROOT, 'static', 'trade_chat.css');

function readAllJs() {
    return fs.readdirSync(JS_DIR)
        .filter(f => f.endsWith('.js'))
        .map(f => fs.readFileSync(path.join(JS_DIR, f), 'utf8'))
        .join('\n');
}

function classesWithHidden(source) {
    const out = new Set();
    const re = /class="([^"]*)"/g;
    let m;
    while ((m = re.exec(source)) !== null) {
        const tokens = m[1].split(/\s+/).filter(Boolean);
        if (!tokens.includes('hidden')) continue;
        tokens.forEach(t => { if (t !== 'hidden' && !t.includes('${')) out.add(t); });
    }
    return out;
}

function importantDisplayRules(css) {
    // 返回 [{selector, value}]，只收 display: X !important
    const rules = [];
    const re = /([^{}]+)\{([^}]*)\}/g;
    let m;
    while ((m = re.exec(css)) !== null) {
        const selector = m[1].trim();
        const body = m[2];
        const d = body.match(/display\s*:\s*([^;]+?)\s*!important/);
        if (d) rules.push({ selector, value: d[1].trim() });
    }
    return rules;
}

const SOURCE = readAllJs() + '\n' + fs.readFileSync(HTML, 'utf8');
const CSS_TEXT = fs.readFileSync(CSS, 'utf8');
const RULES = importantDisplayRules(CSS_TEXT);

test('带 display !important 的 hidden 同现 class 必须有 .X.hidden 覆盖', () => {
    const offenders = [];
    for (const cls of classesWithHidden(SOURCE)) {
        const showing = RULES.filter(
            r => new RegExp('\\.' + cls.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?![\\w-])').test(r.selector)
                && r.value !== 'none',
        );
        if (!showing.length) continue;
        const guarded = RULES.some(
            r => new RegExp('\\.' + cls.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\.hidden(?![\\w-])').test(r.selector)
                && r.value === 'none',
        );
        if (!guarded) offenders.push(cls);
    }
    assert.deepStrictEqual(
        offenders, [],
        '这些 class 同时带 hidden 且被 display:…!important 覆盖，必须补 .X.hidden{display:none!important}：' + offenders.join(', '),
    );
});

test('停止按钮仍用 hidden 类切换（不要改成 style.display）', () => {
    const src = readAllJs();
    assert.match(src, /stopBtn\.classList\.remove\('hidden'\)/, '开始生成时应移除 hidden');
    assert.match(src, /stopBtn\.classList\.add\('hidden'\)/, '结束时（或无生成）应加回 hidden');
});
