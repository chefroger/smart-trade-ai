/**
 * 客户墙「返回」导航守卫（2026-11-20 用户反馈）。
 *
 * 症状：验厂计划 → 「返回客户详情」→ 客户墙 → 「返回客户列表」或 ESC，
 * 结果又落回验厂计划。
 * 根因：客户墙是固定定位覆盖层，主内容区可能停在别的视图（如验厂页）；
 * 只关覆盖层（closeCustomerWall）会露出底下原视图。
 *
 * 修法约束：导航必须加在「返回」入口（backFromCustomerWall），
 * 不能加进 closeCustomerWall —— navToView 开头也调它，会递归导航。
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const SRC = fs.readFileSync(
    path.join(__dirname, '..', 'static', 'js', 'customers.js'), 'utf8');

/** 取两个锚点之间的源码：从 startMarker 起到 endMarker 止。 */
function sliceBetween(startMarker, endMarker) {
    const start = SRC.indexOf(startMarker);
    assert.ok(start > 0, `找不到 ${startMarker}`);
    const stop = SRC.indexOf(endMarker, start + startMarker.length);
    assert.ok(stop > start, `找不到 ${endMarker}（在 ${startMarker} 之后）`);
    return SRC.slice(start, stop);
}

const closeWallBody = sliceBetween('function closeCustomerWall()', 'function backFromCustomerWall()');
const backWallBody = sliceBetween('function backFromCustomerWall()', 'async function openCustomerWall');

test('客户墙「返回」走 backFromCustomerWall，而不是裸 closeCustomerWall', () => {
    assert.match(
        SRC,
        /\$\('wall-back'\)\?\.addEventListener\('click', backFromCustomerWall\)/,
        'wall-back 必须绑到 backFromCustomerWall',
    );
    assert.doesNotMatch(
        SRC,
        /\$\('wall-back'\)\?\.addEventListener\('click', closeCustomerWall\)/,
        'wall-back 不能再直接绑 closeCustomerWall（那样不会切回列表）',
    );
});

test('ESC 关客户墙也走 backFromCustomerWall', () => {
    const escBlock = sliceBetween('if (!_wallEscBound) {', '// 编辑弹窗 / 侧滑详情 / 跟进弹窗 是否打开');
    assert.match(escBlock, /backFromCustomerWall\(\);/, 'ESC 必须落回客户列表');
    assert.doesNotMatch(escBlock, /closeCustomerWall\(\);/, 'ESC 不得只关覆盖层');
});

test('backFromCustomerWall 在非客户列表视图时切回列表', () => {
    assert.match(backWallBody, /closeCustomerWall\(\);/, '要先关覆盖层');
    assert.match(
        backWallBody,
        /currentView !== 'customers'/,
        '非客户列表视图必须切回 customers',
    );
    assert.match(backWallBody, /navToView\('customers'\)/, '要真的导航到客户列表');
});

test('closeCustomerWall 自身不得导航（否则 navToView → closeCustomerWall 递归）', () => {
    assert.doesNotMatch(
        closeWallBody,
        /navToView\(/,
        'closeCustomerWall 里不能调 navToView：navToView 开头就调它，会无限递归',
    );
});
