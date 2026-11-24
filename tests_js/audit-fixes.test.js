/**
 * 2026-10-25 全面审计的前端修复守卫。
 *
 * 1. deleteCompany 必须带 X-Confirm-Delete: yes —— 后端没有这个头直接 400，
 *    于是前端永远显示"删除失败"。
 * 2. 订单状态 <option> 的 value 必须是后端 Literal 认的中文；
 *    以前 option 文本即 value，英文界面提交 "Quoting" 必 422。
 */

const test = require('node:test');
const assert = require('node:assert');
const { SRC } = require('./_extract');

test('deleteCompany 发送 X-Confirm-Delete', () => {
  const start = SRC.indexOf('async function deleteCompany');
  assert.ok(start > 0, '找不到 deleteCompany');
  const end = SRC.indexOf('\n}', start);
  const body = SRC.slice(start, end);
  assert.match(body, /X-Confirm-Delete/);
  assert.match(body, /'yes'/);
});

test('订单状态 option 的 value 固定为中文', () => {
  assert.match(SRC, /var stValues = \['报价中','已下单','已出货','已完成','已取消'\]/);
  assert.match(SRC, /<option value="' \+ v \+ '">/);
  assert.ok(
    !SRC.includes("stLabels.map(function(s){return '<option>'+s+'</option>';}"),
    '旧的无 value option 渲染必须删掉',
  );
});

test('守卫提示不再弹 toast（2026-10-29：默认关闭，警告无用）', () => {
  assert.ok(!SRC.includes('_toolGuardWarned'), '旧的守卫告警状态变量必须删掉');
  assert.ok(!SRC.includes('工具安全守卫未生效'), '不得再弹守卫未生效 toast');
  assert.ok(!SRC.includes('聊天已暂停'), '不得再声称聊天已暂停');
});

// 审计 O-18（2026-11-22）：S-01 线条/遮罩的墨色统一为 rgb(12,13,14)，
// 旧墨色 rgb(20,20,20) 在 CSS 里残留会让网格、hover、阴影偏暖。
test('CSS 不再残留旧墨色 rgba(20,20,20)', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'trade_chat.css'), 'utf8');
  assert.ok(!/rgba\(\s*20\s*,\s*20\s*,\s*20/.test(css), '旧墨色 rgba(20,20,20) 必须全部换成 12,13,14');
  assert.match(css, /--grid-line:\s*rgba\(12,\s*13,\s*14/);
});

// 审计 O-19：轮询只拿到「已完成」时不能直接结束动画，否则迟到的评级被吞。
test('待结论收尾会补详情取评级', () => {
  const start = SRC.indexOf('function _flushPendingDockVerdicts');
  assert.ok(start > 0, '找不到 _flushPendingDockVerdicts');
  const body = SRC.slice(start, start + 1600);
  assert.match(body, /'\/api\/trade\/osint\/jobs\/' \+ id/);
  assert.match(body, /overall_rating/);
});

test('api() 支持额外 header', () => {
  assert.match(SRC, /async function api\(method, path, body, extraHeaders(?:, options)?\)/);
  assert.match(SRC, /Object\.assign\(opts\.headers, extraHeaders\)/);
});

// 审计 P1-10：更新 = 拉代码 + 装依赖 + 重启，必须二次确认，不能一键静默装。
test('升级失败/警告用常驻提示，不再 3 秒一闪而过', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'trade_chat.css'), 'utf8');
  // toast 支持 sticky（不自动消失 + 关闭按钮）
  assert.match(SRC, /function toast\(msg, opts\)/);
  assert.match(SRC, /toast-close/);
  assert.match(css, /\.toast\.sticky/);
  // 升级入口的失败分支要带出真实原因，并常驻（W15 O-20 后只剩 doTradeUpdate）
  assert.match(SRC, /function _updateErrorText\(resp\)/);
  const hits = SRC.match(/toast\(_updateErrorText\(resp\), \{sticky: true\}\)/g) || [];
  assert.ok(hits.length >= 1, '升级入口要常驻显示失败原因');
  // 旧的一闪而过写法不得回来
  assert.ok(!SRC.includes("toast(t('sys.update_fail') + errMsg)"));
  assert.ok(!SRC.includes("toast('⚠️ 更新失败')"));
});

test('更新前有二次确认（只展示当前版本，不展示 release 目标版本）', () => {
  assert.match(SRC, /async function _confirmTradeUpdate\(\)/);
  assert.match(SRC, /return confirm\(msg\)/);
  assert.match(SRC, /'sys\.update_confirm_current'/);
  assert.match(SRC, /'sys\.update_confirm'/);
});

test('买家类型 option 的 value 固定中文（英文界面只翻译显示文本）', () => {
  assert.match(SRC, /var buyerTypeOptions = \[/);
  assert.match(SRC, /<option value="'\+o\[0\]\+'"/);
  assert.ok(!SRC.includes('buyerTypes.map'), '旧的“文本即 value”渲染必须删掉');
  // 兼容旧数据里已写入的英文值
  assert.match(SRC, /_legacyBuyerType/);
});

test('今日用量在侧栏展示，且只提示不拦截', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'trade_chat.html'), 'utf8');
  assert.match(html, /id="usage-today"/);
  assert.match(SRC, /async function loadUsageToday\(\)/);
  assert.match(SRC, /'\/api\/trade\/usage\/today\?_=' \+ Date\.now\(\)/);
  assert.match(SRC, /opts\.cache = 'no-store'/);
  assert.match(SRC, /classList\.toggle\('over'/);
  assert.match(SRC, /classList\.toggle\('warn'/);
  // 失败时静默隐藏，不能用 api() 在每轮聊天后弹 toast
  assert.match(SRC, /if \(!r\.ok\) \{ el\.hidden = true; return; \}/);
});

test('本地 JS 一律不用 SRI，且 .gitattributes 钉住 LF', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const root = path.join(__dirname, '..');
  const html = fs.readFileSync(path.join(root, 'static', 'trade_chat.html'), 'utf8');
  // 2026-10-29 事故：SRI 哈希按 LF 算，Windows 检出转 CRLF → 校验失败 →
  // 脚本被拒执行 → marked 未定义 → 发消息静默失败。同源本地文件不要 SRI。
  assert.ok(!html.includes('integrity='), '同源本地 script 不得带 integrity');
  const attrs = fs.readFileSync(path.join(root, '.gitattributes'), 'utf8');
  assert.match(attrs, /^\*\.js text eol=lf$/m, '.gitattributes 必须固定 *.js 为 LF');
});

test('markdown / DOMPurify 本地打包，离线可用', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'trade_chat.html'), 'utf8');
  assert.match(html, /\/static\/vendor\/marked\.umd\.js/);
  assert.match(html, /\/static\/vendor\/purify\.min\.js/);
  assert.ok(!/https:\/\/cdn/.test(html), '不得再从 CDN 加载前端依赖');
  assert.ok(fs.existsSync(path.join(__dirname, '..', 'static', 'vendor', 'marked.umd.js')));
  assert.ok(fs.existsSync(path.join(__dirname, '..', 'static', 'vendor', 'purify.min.js')));
});

test('更新不自动重启，完成后露出重启按钮', () => {
  assert.match(SRC, /function _showRestartPrompt\(\)/);
  assert.match(SRC, /rb\.hidden = false/);
  assert.ok(
    SRC.includes('_showRestartPrompt();'),
    '更新完成（restart_scheduled=false）时必须露出重启按钮',
  );
});

test('更新确认框展示目标 SHA，并把它传给后端（显示即所用）', () => {
  const start = SRC.indexOf('async function _confirmTradeUpdate');
  assert.ok(start > 0, '找不到 _confirmTradeUpdate');
  const body = SRC.slice(start, SRC.indexOf('\n}', start));
  assert.match(body, /\/api\/trade\/system\/update-preview/);
  assert.match(body, /_pendingUpdateTarget = d\.sha/);
  assert.match(body, /\{target\}/);
  const fn = 'async function doTradeUpdate';
  const b = SRC.slice(SRC.indexOf(fn), SRC.indexOf('\n}', SRC.indexOf(fn)));
  assert.match(b, /target_sha: _pendingUpdateTarget/, `${fn} 必须把目标 SHA 传给后端`);
});

test('无用入口 doUpdateSystem 已删除（W15 O-20）', () => {
  assert.ok(!SRC.includes('async function doUpdateSystem'));
});

test('Hermes 升级成功改为手动重启', () => {
  assert.match(SRC, /promptRestartAfterHermesUpgrade/);
  assert.ok(!SRC.includes('reloadAfterHermesUpgrade'), '旧的自动等待重启必须删掉');
});

test('更新入口先确认再 POST', () => {
  const fn = 'async function doTradeUpdate';
  const start = SRC.indexOf(fn);
  assert.ok(start > 0, `找不到 ${fn}`);
  const body = SRC.slice(start, SRC.indexOf('\n}', start));
  const confirmAt = body.indexOf('_confirmTradeUpdate');
  const postAt = body.indexOf("api('POST', '/api/trade/system/update'");
  assert.ok(confirmAt > 0 && confirmAt < postAt, `${fn} 必须先确认再发更新请求`);
  assert.match(body, /'X-Confirm-Update': 'yes'/, `${fn} 必须带后端要求的确认头`);
});

test('更新入口用统一按钮忙态机制', () => {
  // 手写 textContent/innerHTML 会把图标按钮的图标抹掉，恢复也只能硬编码 HTML。
  const fn = 'async function doTradeUpdate';
  const start = SRC.indexOf(fn);
  assert.ok(start > 0, `找不到 ${fn}`);
  const body = SRC.slice(start, SRC.indexOf('\n}', start));
  // 长等待用 _setBtnWait（返回 restore），短刷新用 _setBtnBusy；同一套“存原样、恢复原样”
  assert.match(body, /_setBtnBusy\(btn, true\)|_setBtnWait\(btn,/, `${fn} 必须用统一忙态机制进入等待`);
  assert.match(body, /_setBtnBusy\(btn, false\)|restoreBtn\(\)/, `${fn} 必须用统一机制还原按钮`);
  assert.ok(!/btn\.textContent\s*=/.test(body), `${fn} 不得手写 btn.textContent（会抹掉图标）`);
  assert.ok(!/btn\.innerHTML\s*=/.test(body), `${fn} 不得手写 btn.innerHTML（还原须走 dataset）`);
});

// P1-F：打印/长图前必须按内容过滤家庭称谓（分类不可靠）
test('验厂打印与长图过滤家庭称谓', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const src = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'customers.js'), 'utf8');
  assert.match(src, /function _vPrivateFilter\(/);
  // 打印统一走 _vsheetSec 内部的 _vPrivateFilter；长图显式过滤内部风险
  assert.match(src, /const safe = _vPrivateFilter\(text\)/);
  assert.match(src, /_vPrivateFilter\(pay\.risks\)/);
});

// P2：待办无截止日显示「未定日期」，并有原因输入
test('待办显示未定日期与原因', () => {
  assert.match(SRC, /未定日期/);
  assert.match(SRC, /id="todo-add-reason"/);
  assert.match(SRC, /原因：/);
});

test('切视图会关闭挂在 body 上的私密备忘录（W15 O-14）', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const src = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'ui.js'), 'utf8');
  const start = src.indexOf('function navToView');
  const body = src.slice(start, src.indexOf('\n}', start) + 2000);
  assert.match(body, /#memo-modal/, 'navToView 必须清理 #memo-modal');
  assert.match(body, /remove\(\)/);
});
