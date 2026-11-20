/**
 * C2 两阶段导入：前端必须先预检、列出同名客户冲突、逐对决策后走 confirm 端点。
 * 静态源码断言（同 wizard-scope.test.js 的写法），不加载浏览器。
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const SRC = fs.readFileSync(
    path.join(__dirname, '..', 'static', 'js', 'views.js'), 'utf8');

test('导入改为先预检', () => {
    assert.match(SRC, /fd\.append\('preflight', 'true'\)/, '上传必须带 preflight=true');
    assert.match(SRC, /_renderImportConflicts/, '预检结果要交给冲突渲染');
});

test('冲突行提供合并与新建两种选择', () => {
    assert.match(SRC, /<option value="merge">/, '必须有「合并到」选项');
    assert.match(SRC, /<option value="create">/, '必须有「新建为」选项');
    assert.match(SRC, /proposed_new_name/, '新建后的名字用后端算好的 proposed_new_name');
});

test('确认走 confirm 端点，不再直接上传', () => {
    assert.match(SRC, /import-package\/.*\/confirm/, '必须调用 confirm 端点');
    assert.match(SRC, /customer_decisions/, '确认请求体必须带 customer_decisions');
});

test('批量和逐对选择都不绕过确认', () => {
    assert.match(SRC, /data-imp-bulk/, '需要有全部合并/全部新建');
    assert.match(SRC, /imp-confirm-btn/, '需要有开始导入按钮');
});

test('冲突列表渲染对用户数据做转义', () => {
    assert.match(SRC, /esc\(c\.source_name/, '源客户名必须 esc');
    assert.match(SRC, /esc\(c\.target_name/, '目标客户名必须 esc');
    assert.match(SRC, /esc\(newName\)/, '提议的新名字必须 esc');
});
