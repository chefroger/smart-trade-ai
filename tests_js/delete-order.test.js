/**
 * deleteOrder 的取值顺序守卫。
 *
 * 背景（2026-10-23 全面审计）：deleteOrder 先 `_closeOrderModal()`（移除整个
 * #order-modal-backdrop），再读 `$('order-cust-id').value` —— 元素已不存在，
 * 每次删除都抛 TypeError，列表不刷新、成功提示也不弹。
 *
 * 这里做源码级顺序断言：custId 必须在关弹窗之前读取。
 */

const test = require('node:test');
const assert = require('node:assert');
const { SRC } = require('./_extract');

test('deleteOrder 先读 custId 再关闭弹窗', () => {
  const start = SRC.indexOf('async function deleteOrder');
  assert.ok(start > 0, '找不到 deleteOrder');

  const end = SRC.indexOf('\n}', start);
  assert.ok(end > start, '找不到 deleteOrder 结尾');
  const body = SRC.slice(start, end);

  // 用带缩进的整行定位，避免命中注释里提到的 `_closeOrderModal()`
  const readIndex = body.indexOf("const custId = $('order-cust-id')");
  const closeIndex = body.indexOf('\n    _closeOrderModal();');

  assert.ok(readIndex > 0, 'deleteOrder 必须读取 order-cust-id');
  assert.ok(closeIndex > 0, 'deleteOrder 必须关闭订单弹窗');
  assert.ok(
    readIndex < closeIndex,
    'custId 必须在 _closeOrderModal() 之前读取（弹窗一关元素就没了）',
  );
});
