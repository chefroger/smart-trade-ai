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
test('更新前有二次确认，且带目标版本提示', () => {
  assert.match(SRC, /async function _confirmTradeUpdate\(\)/);
  assert.match(SRC, /return confirm\(msg\)/);
  assert.match(SRC, /'sys\.update_confirm_version'/);
  assert.match(SRC, /'sys\.update_confirm'/);
});

test('两个更新入口都先确认再 POST', () => {
  for (const fn of ['async function doTradeUpdate', 'async function doUpdateSystem']) {
    const start = SRC.indexOf(fn);
    assert.ok(start > 0, `找不到 ${fn}`);
    const body = SRC.slice(start, SRC.indexOf('\n}', start));
    const confirmAt = body.indexOf('_confirmTradeUpdate');
    const postAt = body.indexOf("api('POST', '/api/trade/system/update')");
    assert.ok(confirmAt > 0 && confirmAt < postAt, `${fn} 必须先确认再发更新请求`);
  }
});
