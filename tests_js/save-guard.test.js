/**
 * 写操作的"假成功"守卫：api() 失败返回 null，必须拦住后续的成功提示。
 *
 * 背景（2026-10-21 审计）：`api()` 在 !r.ok 时已自行 toast 失败原因并返回 null，
 * 但五处写操作丢弃了返回值直接往下走 —— 关弹窗 + toast("已创建/已保存/已删除")。
 * 后果是销售填完客户/订单表单点保存，看到"客户已添加"，库里却没有；弹窗一关，
 * 填的内容随 DOM 一起消失。API 抛 404/422 时必现。
 *
 * 这些函数直接操作 DOM，没法按 #region 抽出来求值，所以这里做**源码级**断言：
 * 从每个 api() 写点看到它的成功提示之间，必须出现一个基于返回值的提前 return。
 */

const test = require('node:test');
const assert = require('node:assert');
const { SRC } = require('./_extract');

/**
 * 每个写点：(名字, 定位 api() 调用的特征串, 该写点之后紧跟的成功提示特征串)
 */
const WRITES = [
    {
        name: '订单保存（新建/编辑）',
        call: "await api('PUT', `/api/trade/orders/${editId}`, body)",
        success: "toast(editId ? t('order.updated') : t('order.created'))",
    },
    {
        name: '客户详情保存',
        call: 'await api(\'PUT\', `/api/trade/customers/${cid}`, {name, contact',
        success: "toast(t('toast.saved'))",
    },
    {
        name: '客户新增/编辑',
        call: "await api('POST', `/api/trade/customers`, body)",
        success: "toast(editId ? '客户已更新' : '客户已添加')",
    },
    {
        name: '订单删除',
        call: 'await api(\'DELETE\', `/api/trade/orders/${oid}`)',
        success: "toast(t('order.deleted'))",
    },
    {
        name: '对话评分',
        call: "await api('POST', '/api/trade/conversations/' + convIdForRating + '/rate'",
        success: "'Thanks for feedback'",
    },
];

for (const w of WRITES) {
    test(`${w.name}：api() 失败时不弹成功提示`, () => {
        const callIdx = SRC.indexOf(w.call);
        assert.ok(callIdx !== -1, `找不到写操作调用：${w.call.slice(0, 45)}`);

        const successIdx = SRC.indexOf(w.success, callIdx);
        assert.ok(successIdx !== -1, `找不到该写点对应的成功提示：${w.success}`);

        // 窗口从调用点前 500 字符起（`const r =` / `var r =` 可能写在 await 之前，
        // 如三元表达式或 `var rated = await api(...)`），到成功提示为止 ——
        // 这段里必须有「接住返回值 + 提前 return」这一对。
        const from = Math.max(0, callIdx - 500);
        const window = SRC.slice(from, successIdx);
        assert.ok(
            /(?:const|let|var)\s+(\w+)\s*=[\s\S]*?await api\([\s\S]*?;[\s\S]*?if\s*\(\s*!\1\s*\)\s*return;/.test(window),
            `${w.name}：api() 的返回值被丢弃了 —— 失败时会关弹窗并弹一个假的成功提示。\n` +
            '需要在 await api(...) 之后接「const r = ...; if (!r) return;」' +
            '（api() 失败时已自行 toast 原因，此处只需拦住后续的 UI 变更）。',
        );
    });
}

test('公司切换的 /switch 是唯一允许丢弃返回值的写点', () => {
    // 它包在 try/catch 里，且失败会在后续业务请求上以 403 显式暴露，不属于"假成功"
    assert.ok(
        /try \{ await api\('POST', '\/api\/trade\/companies\/.+\/switch'\); \} catch\(_\) \{\}/.test(SRC),
        '/switch 调用点应保持 try/catch 包裹（切换失败由后续请求的 403 暴露）',
    );
});
