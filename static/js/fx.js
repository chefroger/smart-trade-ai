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
    const dust = document.getElementById('dust');
    const btn = document.getElementById('fx-toggle');
    if (btn) btn.setAttribute('aria-checked', _fxOn ? 'true' : 'false');
    if (canvas) canvas.style.display = _fxOn ? 'block' : 'none';
    // 粒子层跟随总开关：关闭后整层隐藏，不只是停止移动
    if (dust) dust.style.display = _fxOn ? 'block' : 'none';
    try { localStorage.setItem('trade_fx', _fxOn ? '1' : '0'); } catch (_) {}
    if (_fxOn && _dustStart) _dustStart();
    if (_fxOn && _fxRenderer && !_fxRaf) _fxRaf = requestAnimationFrame(_fxLoop);
}

function setFxEnabled(on) {
    _fxOn = !!on;
    _fxApplyUi();
}

function toggleFx() {
    setFxEnabled(!_fxOn);
}

let _dustStart = null;

function _initDust() {
    /** zip 微光粒子：固定种子、缓慢漂移；reduced-motion / 关闭特效时整层隐藏并停止重绘。 */
    const cv = document.getElementById('dust');
    if (!cv || !cv.getContext) return;
    const ctx = cv.getContext('2d');
    if (!ctx) return;
    let w = 0, h = 0, ps = [];

    function rng(seed) {
        return function () {
            seed = (seed * 16807) % 2147483647;
            return (seed - 1) / 2147483646;
        };
    }

    function resize() {
        const host = cv.parentElement || document.body;
        w = Math.max(1, host.clientWidth);
        h = Math.max(1, host.clientHeight);
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        cv.width = Math.round(w * dpr);
        cv.height = Math.round(h * dpr);
        cv.style.width = w + 'px';
        cv.style.height = h + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        const r = rng(97);
        ps = [];
        for (let i = 0; i < 90; i++) {
            ps.push({
                x: r() * w, y: r() * h, s: r() * 1.4 + .4, a: r() * .28 + .06,
                // 外观保持原样，速度加快约 2.5 倍（±.30 ≈ 原 ±.12）
                vx: (r() - .5) * .30, vy: (r() - .5) * .30, red: i % 37 === 0,
            });
        }
    }

    function draw() {
        ctx.clearRect(0, 0, w, h);
        ps.forEach(function (p) {
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.s, 0, 6.283);
            ctx.fillStyle = p.red
                ? 'rgba(210,40,30,' + (p.a + .15) + ')'
                : 'rgba(12,13,14,' + p.a + ')';
            ctx.fill();
            if (p.s > 1.5) {
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.s * 3.2, 0, 6.283);
                ctx.fillStyle = 'rgba(12,13,14,' + (p.a * .12) + ')';
                ctx.fill();
            }
        });
    }

    resize();
    draw();
    window.addEventListener('resize', resize);
    let running = false;
    function loop() {
        // 关闭总开关后停止重绘；重新打开由 _fxApplyUi 调 _dustStart 续跑
        if (!_fxOn) { running = false; return; }
        ps.forEach(function (p) {
            p.x = (p.x + p.vx + w) % w;
            p.y = (p.y + p.vy + h) % h;
        });
        draw();
        requestAnimationFrame(loop);
    }
    _dustStart = function () {
        if (running) return;
        running = true;
        requestAnimationFrame(loop);
    };
    if (_fxOn) _dustStart();
}

function initFxBackground() {
    hydrateIcons(document);
    const btn = document.getElementById('fx-toggle');
    if (btn) btn.addEventListener('click', toggleFx);

    // 时钟走秒 + 状态文案轮播
    const STATUS = [
        '系统就绪 · SYSTEM READY',
        '客户档案已同步 · PROFILES SYNCED',
        '今日待跟进请留意 · FOLLOW-UPS DUE',
        '逾期客户已标红 · FOLLOW-UP OVERDUE',
    ];
    let statusIdx = 0;
    function pad2(n) { return (n < 10 ? '0' : '') + n; }
    function tickClock() {
        const now = new Date();
        const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
        const time = pad2(now.getHours()) + ':' + pad2(now.getMinutes()) + ':' +
            pad2(now.getSeconds());
        const el = document.getElementById('sys-clock');
        if (el) el.textContent = days[now.getDay()] + ' ' + time;
        // 统一外壳顶栏（zip s1–s4）
        const dateEl = document.getElementById('app-top-date');
        if (dateEl) {
            dateEl.textContent = now.getFullYear() + '.' +
                pad2(now.getMonth() + 1) + '.' + pad2(now.getDate()) + ' ' + days[now.getDay()];
        }
        const timeEl = document.getElementById('app-top-time');
        if (timeEl) timeEl.textContent = time;
    }
    tickClock();
    setInterval(tickClock, 1000);
    setInterval(function () {
        statusIdx = (statusIdx + 1) % STATUS.length;
        const text = STATUS[statusIdx];
        const el = document.getElementById('sys-status');
        if (el) el.textContent = text;
        const topEl = document.getElementById('app-top-status');
        if (topEl) topEl.textContent = text;
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
    // 粒子层不依赖 THREE：无 three.js 也保留 zip 的微光粒子
    _initDust();
    if (!window.THREE) {
        // 没有 three.js 也保留 dust 粒子；开关只影响动效，不强制关掉粒子层
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
        console.warn('three.js 背景初始化失败，已关闭 3D 特效', e);
        _fxRenderer = null;
    }
    _fxApplyUi();
}
