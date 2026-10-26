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
