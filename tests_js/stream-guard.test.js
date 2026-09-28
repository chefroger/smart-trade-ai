/**
 * 聊天流归属管理的行为测试 —— 零依赖（Node 内置 node:test）。
 *
 * 回归的 bug：切换公司时只 abort 了新手引导流，聊天流的 AbortController 是 sendMsg 的
 * 局部变量，无人持有 → 旧流继续跑（白烧 token），且结束收尾走 addMsg()，而 addMsg 读的是
 * 全局 currentChatContainer（此刻已指向新公司的容器）→ A 公司的 AI 回复被写进 B 公司的会话窗口。
 *
 * 这里的被测对象是抽出来的归属记账逻辑，AbortController 在 Node 22 是全局可用的。
 */

const test = require('node:test');
const assert = require('node:assert');
const { loadRegion } = require('./_extract');

function loadStreamGuard() {
    return loadRegion('stream-guard', `{
        _beginChatStream: _beginChatStream,
        _abortChatStream: _abortChatStream,
        _endChatStream: _endChatStream,
        _chatStreamBelongsTo: _chatStreamBelongsTo,
    }`);
}

test('新建的流归属于发起它的公司', () => {
    const g = loadStreamGuard();

    g._beginChatStream(1);

    assert.strictEqual(g._chatStreamBelongsTo(1), true);
    assert.strictEqual(g._chatStreamBelongsTo(2), false, '不得认领其它公司的流');
});

test('没有活跃流时任何公司都不算归属（防止空态误判）', () => {
    const g = loadStreamGuard();

    assert.strictEqual(g._chatStreamBelongsTo(1), false);
});

test('_abortChatStream 真的触发 abort 并清空归属', () => {
    const g = loadStreamGuard();

    const ctl = g._beginChatStream(1);
    assert.strictEqual(ctl.signal.aborted, false);

    g._abortChatStream();

    assert.strictEqual(ctl.signal.aborted, true, '必须真的 abort，否则旧流会继续消耗 token');
    assert.strictEqual(g._chatStreamBelongsTo(1), false, 'abort 后归属必须清空');
});

test('切公司后旧流不再归属任何公司（跨公司串话的防线）', () => {
    const g = loadStreamGuard();

    const oldCtl = g._beginChatStream(1);
    g._abortChatStream();          // onCompanyChange 的动作
    g._beginChatStream(2);         // 新公司的新流

    assert.strictEqual(oldCtl.signal.aborted, true, '旧流必须已被中止');
    assert.strictEqual(g._chatStreamBelongsTo(1), false, 'A 公司的旧流不得再往页面写内容');
    assert.strictEqual(g._chatStreamBelongsTo(2), true);
});

test('_endChatStream 只清理自己那条流，不误清后来的流', () => {
    const g = loadStreamGuard();

    const oldCtl = g._beginChatStream(1);
    g._beginChatStream(2);         // 旧流还在收尾时用户已切到新公司并发起新流

    g._endChatStream(oldCtl);      // 旧流 finally 收尾

    assert.strictEqual(g._chatStreamBelongsTo(2), true, '不得把新公司的流清掉');
});

test('重复 abort / 重复收尾都不抛错', () => {
    const g = loadStreamGuard();

    assert.doesNotThrow(() => g._abortChatStream());
    const ctl = g._beginChatStream(1);
    assert.doesNotThrow(() => g._endChatStream(ctl));
    assert.doesNotThrow(() => g._endChatStream(ctl));
    assert.doesNotThrow(() => g._abortChatStream());
});
