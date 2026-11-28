// M7 等待面板历史预估行测试：渲染真实历史中位数与「暂无足够历史」，且绝不弹确认窗
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const waitSrc = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'js', 'wait.js'),
  'utf8'
);

test('wait.js 支持 job_start.estimate 渲染历史预估与「暂无足够历史」，且无 confirm/alert 确认弹窗', () => {
  assert.match(waitSrc, /ev\.estimate\s*&&\s*ev\.estimate\.message/, '应读取 job_start 事件中的 estimate.message');
  assert.match(waitSrc, /this\.estimateEl/, '任务等待面板应包含 estimateEl 预估展示位');
  assert.doesNotMatch(waitSrc, /\b(?:window\.)?(?:confirm|alert|prompt)\s*\(/, '等待面板绝不得弹出任何确认弹窗');
});
