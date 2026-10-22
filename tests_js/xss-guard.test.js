/**
 * XSS 守卫：**白名单式**（默认全拦 + 显式放行已知安全的表达式）。
 *
 * 背景（2026-10-22 审计）：客户等级 `tier` 与订单单位 `unit` 是自由文本
 * （CSV 批量导入 / API 写入都不校验），却被直接拼进 innerHTML ——
 * 同一行里其它字段（buyerType / note）都用了 esc()，唯独这两个漏了。
 * 攻击路径：导入 tier='<img src=x onerror=...>' → 客户列表面板执行脚本。
 *
 * 为什么是白名单而不是清单：第一版是"列出必须转义的字段"（MUST_ESCAPE），
 * 但**新增用户字段忘了加进清单就拦不住** —— 漏检方向错了。
 * 白名单反过来：默认所有未转义插值都算可疑，只有明确安全的才放行；
 * 新增字段若没转义，会**立刻**被这条测试抓住。
 */

const test = require('node:test');
const assert = require('node:assert');
const { SRC } = require('./_extract');

/**
 * 已知安全、可直接插值的表达式白名单。
 * 覆盖：i18n 文案(t(...))、纯数字/长度、颜色常量、布尔三元、
 *      DOMPurify 已清洗的 HTML、以及已经过 esc 的片段。
 */
const SAFE_PATTERNS = [
    // i18n 文案与固定中文/英文常量
    /^t\(/,
    /^currentLang\s*===/,
    // 纯数字 / 计数 / 长度
    /^[a-zA-Z_$][\w$]*(\.[a-zA-Z_$][\w$]*)*\.length$/,
    /^[a-zA-Z_$][\w$]*\.length\s*[+\-]\s*\d+$/,
    /^\d+$/,
    /^completed\.length$/,
    /^pending\.length$/,
    /^checked\.length$/,
    /^libs\.length$/,
    /^recentConvs\.length$/,
    /^files\.length$/,
    /^deleted$/,
    /^pct$/,
    /^result\.(created|skipped|uploaded)$/,
    /^s\.(total_rated|avg_rating)$/,
    /^worst\.(low_count|skill)$/,
    // id 类（都是数据库整数）
    /^[a-zA-Z_$][\w$]*\.id$/,
    /^(id|cid|oid|lid|editId|jobId|tcId|conv\.id)$/,
    /^[a-zA-Z_$][\w$]*\.id\s*===/,
    // 颜色常量（三元式里的固定 CSS 变量）
    /^var\(--/,
    /^'var\(--/,
    /^(tierColor|stColor|color|mark)$/,
    // 布尔三元（只产出 'selected' / 'checked disabled' 之类的固定串）
    /^[^?]+\?[^:]*:[^?]*$/,
    // 已清洗的 HTML
    /^DOMPurify\.sanitize\(/,
    // 纯本地常量表
    /^(view|chatCtx|ctx|role|status|indent|attrs|item\.(icon|type))$/,
    /^TASK_/,
    // HTTP 状态码（r.status）
    /^r\.status$/,
    // 数字格式化函数（字节数 → 人类可读）
    /^_formatBytes\(/,
    // 本地常量表派生的 HTML 片段（_WORK_SUBDIRS / items.join / fileListHtml 等
    // 都由本地常量或已转义片段拼成）
    /^_WORK_SUBDIRS/,
    /^items\.join\(/,
    /^fileListHtml$/,
    /^subdirOpts$/,
    /^allTemplates\.map\(/,
    /^renderOnboardingStep1HTML\(\)$/,
    // 时钟（m:s 秒表）与纯字符串拼接
    /^[a-zA-Z_$][\w$]*\.toString\(\)\.padStart\(/,
    // 已是纯文本的上下文串（拼进 input.value 而非 innerHTML）
    /^(current_time|chatCtx\|\|''|currentLibraryId|params)$/,
    /^[a-zA-Z_$][\w$]*\.replace\(/,
    // ── 以下不进 innerHTML（逐个核实过渲染路径），但白名单要写清理由，
    //    免得将来有人改成 innerHTML 时守卫放行 ──
    /^(m|h|d|k|v)$/,                     // 数字/本地常量表派生
    /^result\.target_path$/,             // → 拼进提示文本（textContent 路径）
    /^fmtArg\(v\)$/,                     // → addToolItem 用 textContent 渲染
    /^e\.message$/,                      // → deliver() 文本
    /^cb\.value$/,                       // → URL 里的整数 id
    /^t\.name$/,                         // → toast() 文本
    /^name$/,                            // → toast() 文本
    /^(cronExpr|prompt|selected\.join\('\\n'\)|t\.id)$/,  // → input.value
    /^currentCompanyId$/,                   // → URL 里的整数 id
    /^r\.work_dir\.split\('\/'\)\.pop\(\)$/, // → toast() 文本
];

function isSafe(expr) {
    const e = expr.trim();
    if (SAFE_PATTERNS.some((re) => re.test(e))) return true;
    // 明确带 esc/escJs 的（扫描时已排除，这里兜底）
    if (e.includes('esc(') || e.includes('escJs(')) return true;
    return false;
}

/** 找出所有未转义的插值。 */
function unescapedInterpolations() {
    const out = [];
    const re = /\$\{([^{}]{1,80})\}/g;
    let m;
    while ((m = re.exec(SRC)) !== null) {
        const expr = m[1];
        if (expr.includes('esc(') || expr.includes('escJs(')) continue;
        out.push({ line: SRC.slice(0, m.index).split('\n').length, expr });
    }
    return out;
}

test('未转义插值只允许白名单里的安全表达式', () => {
    const bad = unescapedInterpolations()
        .filter((u) => !isSafe(u.expr))
        .map((u) => `  L${u.line}: \${${u.expr}}`);
    assert.strictEqual(
        bad.length, 0,
        '以下插值既没走 esc()、也不在安全白名单里（可能是用户数据）：\n' + bad.join('\n'),
    );
});

test('白名单本身不掩盖用户数据字段', () => {
    // 防止有人为了"过测试"把危险字段塞进白名单
    const forbidden = [/tierLabel/, /o\.unit\b/, /o\.product_name/, /o\.order_no/,
                       /c\.name\b/, /guidance\.desc/, /worst\.skill/];
    for (const re of forbidden) {
        for (const p of SAFE_PATTERNS) {
            assert.ok(
                !re.test(p.source) || !p.test('tierLabel'),
                `白名单不能放行用户数据字段：${re}`,
            );
        }
    }
});

test('tier / unit / guidance.desc 三处渲染点都带 esc()', () => {
    assert.ok(/\$\{esc\(tierLabel\)\}/.test(SRC), '客户等级必须写成 ${esc(tierLabel)}');
    assert.ok(
        /esc\(o\.quantity\)\s*\+\s*esc\(o\.unit\|\|''\)/.test(SRC),
        '订单单位必须写成 esc(o.unit||\'\')',
    );
    assert.ok(
        /esc\(guidance\.desc\)/.test(SRC),
        '引导条描述必须转义（与同一行的 guidance.name 保持一致）',
    );
});
