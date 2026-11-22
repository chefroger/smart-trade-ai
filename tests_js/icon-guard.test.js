/**
 * 图标存在性守卫（U2）：
 * iconHtml(name) / btnIcon(name) / data-icon="name" / lucide-<name>.svg
 * 都会拼成 /static/icons/lucide-<name>.svg 做 mask；文件缺失时静默 404、图标空白。
 * 这里扫字面量引用，保证每个引用的文件都在。
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const ICON_DIR = path.join(ROOT, 'static', 'icons');
const JS_DIR = path.join(ROOT, 'static', 'js');

function sources() {
    const js = fs.readdirSync(JS_DIR)
        .filter(f => f.endsWith('.js'))
        .map(f => fs.readFileSync(path.join(JS_DIR, f), 'utf8'));
    js.push(fs.readFileSync(path.join(ROOT, 'static', 'trade_chat.html'), 'utf8'));
    return js.join('\n');
}

function referencedIcons(src) {
    const names = new Set();
    const patterns = [
        /iconHtml\(\s*['"]([a-z0-9-]+)['"]/g,
        // btnIcon() 是 iconHtml() 的包装，图标名同样是字面量 —— 必须一起扫，
        // 否则 btnIcon('typo') 引用不存在的文件不会被守卫发现（2026-11-20 审计）
        /btnIcon\(\s*['"]([a-z0-9-]+)['"]/g,
        /data-icon="([a-z0-9-]+)"/g,
        /lucide-([a-z0-9-]+)\.svg/g,
    ];
    for (const re of patterns) {
        let m;
        while ((m = re.exec(src)) !== null) names.add(m[1]);
    }
    return names;
}

test('每个被引用的 lucide 图标文件都存在', () => {
    const names = referencedIcons(sources());
    const missing = [...names].filter(n => !fs.existsSync(path.join(ICON_DIR, `lucide-${n}.svg`)));
    assert.deepStrictEqual(missing, [], '缺少图标文件：' + missing.join(', '));
});

test('新增图标保留 lucide-static 许可证头', () => {
    const file = path.join(ICON_DIR, 'lucide-layout-dashboard.svg');
    assert.ok(fs.existsSync(file), 'lucide-layout-dashboard.svg 必须存在（右栏今日简报在用）');
    const head = fs.readFileSync(file, 'utf8').split('\n').slice(0, 3).join('\n');
    assert.match(head, /lucide-static/);
    assert.match(head, /ISC/);
});

test('所有图标文件不得有杂散属性块', () => {
    // 2026-11-22：曾有 15 个文件在根 <svg> 结束后又粘了一整块属性
    // （xmlns/width/height/... 再跟一个 `>`），结构非法但浏览器可能容忍；
    // 只查 viewBox/currentColor 的旧断言抓不到。
    const files = fs.readdirSync(ICON_DIR).filter(f => /^lucide-.*\.svg$/.test(f));
    assert.ok(files.length > 0, 'static/icons 下没有图标文件');
    for (const f of files) {
        const src = fs.readFileSync(path.join(ICON_DIR, f), 'utf8');
        assert.strictEqual((src.match(/<svg\b/g) || []).length, 1, `${f} 根元素数量不为 1`);
        assert.strictEqual((src.match(/<\/svg>/g) || []).length, 1, `${f} 结束标签数量不为 1`);
        assert.strictEqual((src.match(/xmlns=/g) || []).length, 1, `${f} 出现重复的 xmlns 属性块`);

        // 根元素闭合后、第一个子元素之前只能是空白；出现 name="value" 就是杂散属性
        const open = src.search(/<svg\b[^>]*>/);
        assert.ok(open >= 0, `${f} 没有 <svg>`);
        const after = src.slice(src.indexOf('>', open) + 1);
        const child = after.search(/<[a-zA-Z]/);
        const between = child === -1 ? after : after.slice(0, child);
        assert.ok(!/[\w:.-]+\s*=/.test(between), `${f} 根元素后存在杂散属性块`);
    }
});

test('视觉收尾 16 个图标全部存在且格式一致', () => {
    const names = [
        'arrow-down-wide-narrow', 'arrow-left', 'book-open', 'briefcase-business',
        'clipboard-list', 'copy', 'folder-open', 'graduation-cap', 'history',
        'layout-dashboard', 'message-circle', 'search-check', 'share-2', 'ship',
        'target', 'user-round',
    ];
    for (const n of names) {
        const file = path.join(ICON_DIR, `lucide-${n}.svg`);
        assert.ok(fs.existsSync(file), `缺少 static/icons/lucide-${n}.svg`);
        const src = fs.readFileSync(file, 'utf8');
        assert.match(src, /<!-- @license lucide-static v0\.544\.0 - ISC -->/, `${n} 许可证头不对`);
        assert.match(src, /class="lucide lucide-[\w-]+"/, `${n} 缺 lucide class`);
        assert.match(src, /viewBox="0 0 24 24"/, `${n} 不是 24×24`);
        assert.match(src, /stroke="currentColor"/, `${n} 必须用 currentColor`);
    }
});
