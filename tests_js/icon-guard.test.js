/**
 * 图标存在性守卫（U2）：
 * iconHtml(name) / data-icon="name" / lucide-<name>.svg 都会拼成
 * /static/icons/lucide-<name>.svg 做 mask；文件缺失时静默 404、图标空白。
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
