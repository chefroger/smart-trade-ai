/**
 * S4 / O-新21：前端本地兜底词表与后端 trade/privacy_terms.py 同步。
 *
 * 打印/长图前用的是前端这份兜底（API 词表拉取失败时），必须同样：
 *  - 补全中/英/法/葡/西/日称谓；
 *  - partner/brother/son/family 只在所属语境才算；
 *  - 「和夫人」判为家庭信息，「王先生」不算。
 */

const test = require('node:test');
const assert = require('node:assert');
const { SRC } = require('./_extract');

// 抽出家庭词表 + _vPrivateFilter（不含密语弹窗区段）
const START = SRC.indexOf('let _V_FAMILY_CJK');
const END = SRC.indexOf('// W13：密语弹窗');
assert.ok(START !== -1 && END > START, '找不到前端家庭词表区段');
const SEGMENT = SRC.slice(START, END);
const { filter } = new Function(SEGMENT + '\nreturn { filter: _vPrivateFilter };')();

function blocked(line) {
    return filter(line) === '';
}

test('S4 新增称谓在前端同样拦截', () => {
    const positives = [
        '奶奶生日 5 月 1 日', '爷爷喜欢下棋', '外公在上海', '外婆做饭好吃',
        '女婿负责报关', '儿媳在医院值班', '媳妇刚生完孩子',
        '侄子今年高考', '侄女在国外留学', '外甥周末来帮忙', '外甥女上初中',
        '叔叔是厂长', '阿姨喜欢兰花', '舅舅做物流', '姑姑在银行工作',
        '男朋友在工厂', '女朋友做设计', '未婚夫是德国人', '未婚妻负责财务',
        'mom called yesterday', 'mum is visiting', 'dad is retired',
        'his grandson is six', 'her granddaughter is two',
        'grandmother lives with them', 'grandfather was a sailor',
        'girlfriend is a doctor', 'boyfriend works in sales',
        'fiancé is French', 'fiancée is Spanish',
        'niece is eight', 'nephew is at college', 'my brother-in-law drives',
        'femme et enfants', 'mari travaille ici', 'fils aîné', 'fille cadette',
        'filho mais velho', 'filha mais nova', 'mujer y hijos', 'marido trabaja',
        '妻は会社員です', '奥さんが来ました', '夫は営業です', '娘が大学に行く',
        '息子は小学生',
        '王先生和夫人一起来了', '和夫人一起来的王先生',
    ];
    for (const line of positives) {
        assert.ok(blocked(line), `未拦截：${line}`);
    }
});

test('S4 不应拦的 8 条在前端放行', () => {
    const negatives = [
        '合作伙伴 partner：ABC Trading',
        'Brother Industries 打印机报价',
        'S. C. Johnson & Son 询盘',
        'family business since 1980',
        '我们的 partner 工厂',
        'Son Heung-min 签名球衣',
        '王先生是采购经理',
        '王夫人是采购总监',
    ];
    for (const line of negatives) {
        assert.ok(!blocked(line), `误伤：${line}`);
    }
});

test('所属语境下的 partner/brother/son/family 仍然拦截', () => {
    for (const line of [
        'my partner handles logistics',
        'his brother is the owner',
        'John\'s son works at the plant',
        '我的 partner 在德国',
    ]) {
        assert.ok(blocked(line), `未拦截：${line}`);
    }
});

test('单字 夫/娘 的常见误伤词放行', () => {
    for (const line of ['功夫不负有心人', '老板娘说下周到货', '姑娘负责前台', '新娘家在上海']) {
        assert.ok(!blocked(line), `误伤：${line}`);
    }
});
