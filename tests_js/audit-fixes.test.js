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

test('api() 支持额外 header', () => {
  assert.match(SRC, /async function api\(method, path, body, extraHeaders\)/);
  assert.match(SRC, /Object\.assign\(opts\.headers, extraHeaders\)/);
});

// 审计 P1-10：更新 = 拉代码 + 装依赖 + 重启，必须二次确认，不能一键静默装。
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

test('两个更新入口都先确认再 POST', () => {
  for (const fn of ['async function doTradeUpdate', 'async function doUpdateSystem']) {
    const start = SRC.indexOf(fn);
    assert.ok(start > 0, `找不到 ${fn}`);
    const body = SRC.slice(start, SRC.indexOf('\n}', start));
    const confirmAt = body.indexOf('_confirmTradeUpdate');
    const postAt = body.indexOf("api('POST', '/api/trade/system/update'");
    assert.ok(confirmAt > 0 && confirmAt < postAt, `${fn} 必须先确认再发更新请求`);
    assert.match(body, /'X-Confirm-Update': 'yes'/, `${fn} 必须带后端要求的确认头`);
  }
});
