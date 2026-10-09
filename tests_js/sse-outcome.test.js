/**
 * SSE 流结束后的「兜底文案」必须能区分失败类型。
 *
 * 历史 bug：`sendMsg` 只有一句
 *     else deliver('assistant', '⚠️ Agent 未返回有效回复。', true, null);
 * 于是三类完全不同的失败长得一模一样：
 *   1. agent 线程静默死亡（RelaunchExit）
 *   2. 服务端事件被丢弃（队列满）
 *   3. 网络中断（客户端没收到 done）
 * 用户拿到的信息既没原因、也没下一步。
 *
 * 现在的判据：`done` 是服务端在 finally 里必发的事件（trade/api/chat.py）。
 *   - 收到 done 却没有 response → 服务端走完了流程但没内容（服务端问题）
 *   - 没收到 done          → 连接中途断了（网络问题）
 * 两种情况的文案与建议必须不同。
 */

const test = require('node:test');
const assert = require('node:assert');
const { loadRegion } = require('./_extract');

const { _sseStreamOutcome } = loadRegion(
    'sse-outcome',
    '{ _sseStreamOutcome: _sseStreamOutcome }'
);

test('收到 response 时不必兜底', () => {
    const out = _sseStreamOutcome(true, true);
    assert.strictEqual(out.kind, 'response');
});

test('收到 done 但没有 response → 判为服务端未给内容', () => {
    const out = _sseStreamOutcome(false, true);
    assert.strictEqual(out.kind, 'silent');
    assert.match(out.message, /服务端|未给出/, '文案要指出问题出在服务端一侧');
    assert.doesNotMatch(out.message, /网络/, '不能把服务端问题说成网络问题');
});

test('没有 done → 判为连接中断', () => {
    const out = _sseStreamOutcome(false, false);
    assert.strictEqual(out.kind, 'interrupted');
    assert.match(out.message, /连接|网络/, '文案要指出是连接层面断了');
});

test('两种兜底文案必须不同（这是本修复的核心目的）', () => {
    const silent = _sseStreamOutcome(false, true).message;
    const interrupted = _sseStreamOutcome(false, false).message;

    assert.notStrictEqual(silent, interrupted, '不同失败必须给出不同提示');
});

test('兜底文案不得再是那句无信息量的老话', () => {
    for (const seenDone of [true, false]) {
        const out = _sseStreamOutcome(false, seenDone);
        assert.doesNotMatch(
            out.message,
            /未返回有效回复/,
            '「未返回有效回复」不含任何可操作信息，已被替换'
        );
    }
});
