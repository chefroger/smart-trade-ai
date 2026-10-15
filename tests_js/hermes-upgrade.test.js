/**
 * Hermes 升级面板的行为测试 —— 零依赖（Node 内置 node:test）。
 *
 * 背景：Trade 进程内嵌 Hermes，Hermes 版本过旧时 agent 功能全废；而桌面端（tradewin）
 * 用户看不到终端。这个面板是他们唯一能看到的解释与出路，所以钉住两件事：
 *   1. 状态 → 文案的映射必须与后端的 6 个状态一一对应（少一个就会出现空白面板）；
 *   2. 「重试」按钮只在停下来的失败态出现 —— 升级中给按钮会让用户以为能加速。
 */

const test = require('node:test');
const assert = require('node:assert');
const { loadRegion } = require('./_extract');

/** 造一个最小的 DOM 替身：只需 getElementById + appendChild/innerHTML。 */
function makeDom() {
    const nodes = {};
    function makeNode() {
        const classes = new Set();
        return {
            textContent: '', innerHTML: '', style: {},
            className: '', onclick: null, scrollTop: 0, scrollHeight: 0,
            children: [],
            // showHermesUpgradePanel 会 classList.remove('hidden') —— stub 缺了它
            // 会在调用处抛 TypeError，看起来像产品 bug 其实是夹具不完整
            classList: {
                add: (c) => classes.add(c),
                remove: (c) => classes.delete(c),
                contains: (c) => classes.has(c),
            },
            appendChild(child) { this.children.push(child); return child; },
        };
    }
    const document = {
        getElementById(id) {
            if (!nodes[id]) nodes[id] = makeNode();
            return nodes[id];
        },
        createElement() { return makeNode(); },
    };
    const $ = (id) => document.getElementById(id);
    return { document, $, nodes };
}

function loadPanel(fetchStub) {
    const dom = makeDom();
    const calls = [];
    const fetch_ = fetchStub || ((url) => { calls.push(String(url)); return Promise.reject(new Error('测试里不发请求')); });
    const api = loadRegion(
        'hermes-upgrade',
        '{ HERMES_UPGRADE_TEXT: HERMES_UPGRADE_TEXT, applyHermesUpgradeState: applyHermesUpgradeState, renderHermesUpgradeSteps: renderHermesUpgradeSteps, showHermesUpgradePanel: showHermesUpgradePanel }',
        { document: dom.document, $: dom.$, TOKEN: 'tok', toast: () => {}, fetch: fetch_, _waitForRestartAndReload: () => {} },
    );
    return { api, nodes: dom.nodes, calls };
}

test('每个状态都有文案（缺一个就会出现空白面板）', () => {
    const { api } = loadPanel();

    for (const status of [
        'idle', 'checking_network', 'upgrading', 'done', 'offline', 'failed',
        // rebuild_needed 不是"升级 Hermes"的进度态，而是「Trade 自己需要重建」——
        // 2026-10-15 客户机实测时这一档根本不存在，界面只能显示别的态把人引错方向
        'rebuild_needed',
    ]) {
        const text = api.HERMES_UPGRADE_TEXT[status];
        assert.ok(text, `状态 ${status} 缺文案`);
        assert.ok(text.title && text.message, `状态 ${status} 的标题或说明为空`);
    }
});

test('界面认识后端给的 rebuild_trade_venv 方向', () => {
    // 前端按 compat.fix 决定文案；后端改了取值而前端没跟上，用户就会看到误导性提示。
    // 这里直接核对两个文件之间的契约字符串（本地 require，不依赖文件后半段的声明顺序）。
    const fs = require('node:fs');
    const path = require('node:path');
    const js = fs.readFileSync(path.join(__dirname, '..', 'static', 'trade_chat.js'), 'utf8');
    const py = fs.readFileSync(path.join(__dirname, '..', 'trade', 'hermes_compat.py'), 'utf8');

    assert.ok(js.includes('rebuild_trade_venv'), 'trade_chat.js 未处理 rebuild_trade_venv');
    assert.ok(py.includes('"rebuild_trade_venv"'), '后端未产出 rebuild_trade_venv');
});

test('后端给的具体说明优先于通用文案', () => {
    const { api, nodes } = loadPanel();

    api.applyHermesUpgradeState({ status: 'failed', message: '退出码 3' });

    assert.strictEqual(nodes['hermes-upgrade-message'].textContent, '退出码 3');
});

test('没有具体说明时回落到该状态的通用文案', () => {
    const { api, nodes } = loadPanel();

    api.applyHermesUpgradeState({ status: 'offline', message: '' });

    assert.strictEqual(nodes['hermes-upgrade-title'].textContent, '需要先开启代理');
    assert.ok(nodes['hermes-upgrade-message'].textContent.includes('代理'));
});

test('只有失败态才出现重试按钮（升级中给按钮会误导）', () => {
    for (const status of ['checking_network', 'upgrading', 'done']) {
        const { api, nodes } = loadPanel();
        api.applyHermesUpgradeState({ status });
        assert.strictEqual(nodes['hermes-upgrade-actions'].children.length, 0,
            `${status} 不该有按钮`);
    }
    for (const status of ['failed', 'offline']) {
        const { api, nodes } = loadPanel();
        api.applyHermesUpgradeState({ status });
        const buttons = nodes['hermes-upgrade-actions'].children;
        assert.strictEqual(buttons.length, 1, `${status} 应该有重试按钮`);
        assert.strictEqual(buttons[0].textContent, '重试升级');
    }
});

test('升级步骤渲染出可复制的完整命令', () => {
    const { api, nodes } = loadPanel();

    api.renderHermesUpgradeSteps([
        { title: '让 Hermes 自己升级', detail: '复制这一行', command: 'hermes update' },
    ]);

    const step = nodes['hermes-upgrade-steps'].children[0];
    const code = step.children[2];
    assert.strictEqual(code.textContent, 'hermes update');
    assert.strictEqual(step.children[0].textContent, '1) 让 Hermes 自己升级');
});

// ── 与 HTML / CSS 的一致性 ────────────────────────────────────────────────
// 上面几组用例用的是 stub 的 getElementById —— 它对任何 id 都返回一个新节点，
// 所以**发现不了"JS 里写的 id 在 HTML 里不存在"**（真实后果：面板永远不显示，
// 而逻辑测试全绿）。这里直接核对三个文件之间的契约。

const fs = require('node:fs');
const path = require('node:path');

const HTML = fs.readFileSync(path.join(__dirname, '..', 'static', 'trade_chat.html'), 'utf8');
const CSS = fs.readFileSync(path.join(__dirname, '..', 'static', 'trade_chat.css'), 'utf8');
const JS = fs.readFileSync(path.join(__dirname, '..', 'static', 'trade_chat.js'), 'utf8');

test('JS 引用的每个面板元素 id 都存在于 HTML', () => {
    const used = new Set(
        [...JS.matchAll(/\$\('(hermes-upgrade-[a-z-]+)'\)/g)].map((m) => m[1]),
    );
    assert.ok(used.size >= 5, `未解析到面板元素 id（实际 ${used.size} 个）`);
    for (const id of used) {
        assert.ok(HTML.includes(`id="${id}"`), `trade_chat.html 缺少 id="${id}"`);
    }
});

test('HTML 里的面板元素都被 JS 用到（避免留下死节点）', () => {
    const declared = [...HTML.matchAll(/id="(hermes-upgrade-[a-z-]+)"/g)].map((m) => m[1]);
    assert.ok(declared.length > 0, 'HTML 未声明任何面板元素');
    for (const id of declared) {
        assert.ok(JS.includes(`'${id}'`), `trade_chat.js 未使用 id="${id}"`);
    }
});

test('面板的样式类在 CSS 里有定义', () => {
    // 覆盖层与卡片是最关键的两个：没有它们，面板要么不显示、要么铺满全屏不可读
    for (const cls of ['.hermes-upgrade-overlay', '.hermes-upgrade-card', '.hermes-upgrade-step code']) {
        assert.ok(CSS.includes(cls), `trade_chat.css 缺少样式 ${cls}`);
    }
    // .hidden 必须真的能隐藏 —— 否则面板会在正常启动时也盖住界面
    assert.ok(/\.hermes-upgrade-overlay\.hidden\s*\{\s*display:\s*none/.test(CSS),
        'CSS 未定义 .hermes-upgrade-overlay.hidden 的隐藏规则');
});

// ── 重建场景：标题不许被进度流盖掉（2026-10-15 用户截图实证）──────────────
// 上一版把文案修对了，但紧接着启动了进度流：重建场景下后端没有升级任务，状态恒为
// idle，流的第一个 state 事件就把标题盖回「准备升级 Hermes」—— 又变成误导。
// 这组用例钉的是**交互**，不是文案（只测"每个状态有文案"发现不了它）。

test('rebuild 场景不启动进度流，标题保持"重建运行环境"', () => {
    const { api, nodes, calls } = loadPanel();

    api.showHermesUpgradePanel({
        fix: 'rebuild_trade_venv',
        reason: 'Hermes 0.22.0 需要 Python 3.14 运行时',
        steps: [{ title: '重新运行安装脚本', detail: '', command: 'curl -fsSL ... | bash' }],
        upgrade: { status: 'idle', running: false },
    });

    assert.strictEqual(nodes['hermes-upgrade-title'].textContent, 'Trade 需要重建运行环境');
    // 关键：一条流请求都不该发出 —— 发出去了就会被 idle 盖掉
    assert.deepStrictEqual(calls, [], `重建场景不该开进度流，却请求了 ${calls}`);
});

test('升级场景照常启动进度流（别把上面那条修过头）', () => {
    const { api, calls } = loadPanel();

    api.showHermesUpgradePanel({
        fix: 'upgrade_hermes',
        reason: 'Hermes 过旧',
        steps: [{ title: '让 Hermes 自己升级', detail: '', command: 'hermes update' }],
        upgrade: { status: 'upgrading', running: true, message: '正在升级 Hermes' },
    });

    assert.ok(calls.some((u) => u.includes('hermes-upgrade/stream')),
        '升级场景必须订阅进度流，否则用户看不到进度');
});
