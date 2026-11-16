// ═════════════════════ S-01 three.js 背景（本地 three.min.js）═════════════════════
// 撒玛利亚人风：细线网格 + 微光粒子。加载失败 / 低端 / reduced-motion → 自动关。

let _fxOn = true;
let _fxRenderer = null;
let _fxScene = null;
let _fxCamera = null;
let _fxGrid = null;
let _fxRaf = null;
let _fxLast = 0;

/** 把 data-icon 占位换成 mask 图标（currentColor）。 */
function hydrateIcons(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-icon]').forEach(function (el) {
        const name = el.getAttribute('data-icon');
        if (!name) return;
        el.innerHTML = iconHtml(name, 20);
        el.removeAttribute('data-icon');
    });
}

/** 生成单色 Lucide 图标 HTML（mask，跟文字同色）。 */
function iconHtml(name, size) {
    const px = size || 20;
    const cls = px === 16 ? 'i i-16' : (px === 24 ? 'i i-24' : 'i i-20');
    return '<span class="' + cls + '" style="--i:url(\'/static/icons/lucide-' + name + '.svg\')" aria-hidden="true"></span>';
}

function _fxResize() {
    if (!_fxRenderer || !_fxCamera) return;
    _fxRenderer.setSize(window.innerWidth, window.innerHeight);
    _fxCamera.aspect = window.innerWidth / window.innerHeight;
    _fxCamera.updateProjectionMatrix();
}

function _fxBuildGrid() {
    if (!window.THREE) return null;
    const group = new THREE.Group();
    const mat = new THREE.LineBasicMaterial({ color: 0x9a9a97, transparent: true, opacity: 0.16 });
    const pts = [];
    for (let x = -16; x <= 16; x += 2) { pts.push(x, -9, 0, x, 9, 0); }
    for (let y = -9; y <= 9; y += 2) { pts.push(-16, y, 0, 16, y, 0); }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pts), 3));
    group.add(new THREE.LineSegments(g, mat));
    const redMat = new THREE.LineBasicMaterial({ color: 0xc8102e, transparent: true, opacity: 0.35 });
    const rg = new THREE.BufferGeometry();
    rg.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-16, 3.2, 0, 16, 3.2, 0]), 3));
    group.add(new THREE.LineSegments(rg, redMat));
    const N = 36;
    const pos = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) {
        pos[i * 3] = (Math.random() - 0.5) * 30;
        pos[i * 3 + 1] = (Math.random() - 0.5) * 16;
        pos[i * 3 + 2] = 0;
    }
    const pg = new THREE.BufferGeometry();
    pg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    group.add(new THREE.Points(pg, new THREE.PointsMaterial({
        color: 0x55554f, size: 0.05, transparent: true, opacity: 0.4,
    })));
    return group;
}

function _fxLoop(ts) {
    if (!_fxOn || !_fxRenderer) { _fxRaf = null; return; }
    _fxRaf = requestAnimationFrame(_fxLoop);
    if (ts - _fxLast < 33) return;
    _fxLast = ts;
    if (_fxGrid) _fxGrid.position.y = Math.sin(ts * 0.0001) * 0.15;
    _fxRenderer.render(_fxScene, _fxCamera);
}

function _fxApplyUi() {
    const canvas = document.getElementById('bg3d');
    const btn = document.getElementById('fx-toggle');
    if (btn) btn.setAttribute('aria-checked', _fxOn ? 'true' : 'false');
    if (canvas) canvas.style.display = _fxOn ? 'block' : 'none';
    try { localStorage.setItem('trade_fx', _fxOn ? '1' : '0'); } catch (_) {}
    if (_fxOn && _fxRenderer && !_fxRaf) _fxRaf = requestAnimationFrame(_fxLoop);
}

function setFxEnabled(on) {
    _fxOn = !!on;
    _fxApplyUi();
}

function toggleFx() {
    setFxEnabled(!_fxOn);
}

function initFxBackground() {
    hydrateIcons(document);
    const btn = document.getElementById('fx-toggle');
    if (btn) btn.addEventListener('click', toggleFx);

    // 时钟走秒 + 状态文案轮播
    const STATUS = ['系统就绪', '客户档案已同步', '今日待跟进请留意', '逾期客户已标红'];
    let statusIdx = 0;
    function pad2(n) { return (n < 10 ? '0' : '') + n; }
    function tickClock() {
        const el = document.getElementById('sys-clock');
        if (!el) return;
        const now = new Date();
        const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
        el.textContent = days[now.getDay()] + ' ' + pad2(now.getHours()) + ':' +
            pad2(now.getMinutes()) + ':' + pad2(now.getSeconds());
    }
    tickClock();
    setInterval(tickClock, 1000);
    setInterval(function () {
        const el = document.getElementById('sys-status');
        if (!el) return;
        statusIdx = (statusIdx + 1) % STATUS.length;
        el.textContent = STATUS[statusIdx];
    }, 4000);

    // reduced-motion / 用户偏好 / THREE 缺失 → 关
    try {
        const saved = localStorage.getItem('trade_fx');
        if (saved === '0') _fxOn = false;
        if (saved === '1') _fxOn = true;
    } catch (_) {}
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        _fxOn = false;
    }
    if (!window.THREE) {
        _fxOn = false;
        _fxApplyUi();
        return;
    }
    try {
        const canvas = document.getElementById('bg3d');
        if (!canvas) { _fxOn = false; return; }
        _fxRenderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
        _fxRenderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        _fxScene = new THREE.Scene();
        _fxCamera = new THREE.PerspectiveCamera(55, 1, 0.1, 100);
        _fxCamera.position.set(0, 0, 14);
        _fxGrid = _fxBuildGrid();
        if (_fxGrid) _fxScene.add(_fxGrid);
        _fxResize();
        window.addEventListener('resize', _fxResize);
    } catch (e) {
        console.warn('three.js 背景初始化失败，已关闭特效', e);
        _fxOn = false;
        _fxRenderer = null;
    }
    _fxApplyUi();
}
