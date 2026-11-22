// #region wait3d
/* ═══════════════════════════════════════════════════════════════
   TradeWait 3D 推镜层（只用于长任务 task 模式）· 设计稿 v2（2026-11-22）
   - 复用 fx.js 的 _fxRenderer（同一个 WebGL 上下文，不新建第二个），本地 three.min.js r128。
   - 通过 fxRegisterPass 在 fx.js 的循环里先渲染本场景到 renderer 左下角视口，
     同一帧内 drawImage 拷到面板的 2D 画布，然后 fx.js 照常画背景（会覆盖该区域）。
   - 镜头只在真实事件上移动：source_done=hit → 推近该来源节点；verdict → 推近中心目标并停留。
   - 不可用 / 上下文丢失 / 低端 GPU / trade_fx 关 / reduced-motion → 返回 null 或自动退回 Canvas2D。
   ═══════════════════════════════════════════════════════════════ */
(function (global) {
  'use strict';
  var SW = global.TradeWait;
  if (!SW) return;
  var INK = 0x0C0D0E, RED = 0xD2281E, PAPER = 0xFBFCFC;
  var lost = false, live = [];
  var COST_LIMIT = 8;          // 单帧（渲染 + 拷贝 + 叠字）均值超过 8ms → 退回 2D

  function rendererReady() {
    return !!(global.THREE && typeof fxRendererReady === 'function' && fxRendererReady() && typeof fxRegisterPass === 'function' && !lost);
  }
  function lineMat(op) { return new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: op }); }
  function circlePts(r, n, a0, a1) {
    var p = []; a0 = a0 || 0; a1 = a1 == null ? Math.PI * 2 : a1;
    for (var i = 0; i <= n; i++) { var a = a0 + (a1 - a0) * i / n; p.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0)); }
    return new THREE.BufferGeometry().setFromPoints(p);
  }
  function ease(a, b, k) { return a + (b - a) * k; }

  function Task3D(w) {
    this.w = w; this.nodes = {}; this.order = [];
    this.queue = []; this.focus = null; this.focusUntil = 0; this.final = false; this.stopAt = 0;
    this.cost = 0; this.frames = 0; this.disposables = [];
    var S = this.scene = new THREE.Scene();
    this.cam = new THREE.PerspectiveCamera(40, 1, 0.1, 200);
    this.home = { pos: new THREE.Vector3(0, -7, 24), look: new THREE.Vector3(0, 0, 0) };
    this.cam.position.copy(this.home.pos); this.look = this.home.look.clone(); this.cam.lookAt(this.look);
    this.camTo = this.home.pos.clone(); this.lookTo = this.home.look.clone();
    // 平面网格 + “+” 点阵（共享几何，控制 draw call）
    var gp = [];
    for (var x = -16; x <= 16; x += 2) gp.push(x, -12, 0, x, 12, 0);
    for (var y = -12; y <= 12; y += 2) gp.push(-16, y, 0, 16, y, 0);
    var gg = new THREE.BufferGeometry(); gg.setAttribute('position', new THREE.Float32BufferAttribute(gp, 3));
    S.add(new THREE.LineSegments(gg, lineMat(0.07)));
    var cp = [];
    for (x = -16; x <= 16; x += 4) for (y = -12; y <= 12; y += 4) cp.push(x - .25, y, 0, x + .25, y, 0, x, y - .25, 0, x, y + .25, 0);
    var cg = new THREE.BufferGeometry(); cg.setAttribute('position', new THREE.Float32BufferAttribute(cp, 3));
    S.add(new THREE.LineSegments(cg, lineMat(0.35)));
    // 轨道（虚线）与外圈
    this.R = 8;
    var orb = new THREE.Line(circlePts(this.R, 128), new THREE.LineDashedMaterial({ color: INK, dashSize: .3, gapSize: .45, transparent: true, opacity: .4 }));
    orb.computeLineDistances(); S.add(orb);
    S.add(new THREE.Line(circlePts(this.R + 1.8, 128), lineMat(0.14)));
    // 径向扫描：扇形 + 线
    this.sweep = new THREE.Group();
    var sector = new THREE.Mesh(new THREE.RingGeometry(0.1, this.R + 1.8, 24, 1, 0, 0.8), new THREE.MeshBasicMaterial({ color: INK, transparent: true, opacity: .04, depthWrite: false }));
    sector.rotation.z = -0.8; this.sweep.add(sector); this.sector = sector;
    var sl = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), new THREE.Vector3(this.R + 1.8, 0, 0)]);
    this.sweep.add(new THREE.Line(sl, lineMat(0.45))); S.add(this.sweep);
    // 中心目标：双圈 + 三段弧 + 红色倒三角
    S.add(new THREE.Line(circlePts(1.5, 64), lineMat(0.9)));
    S.add(new THREE.Line(circlePts(2.1, 64), lineMat(0.5)));
    this.arcs = new THREE.Group();
    for (var k = 0; k < 3; k++) this.arcs.add(new THREE.Line(circlePts(1.8, 12, k * 2.094, k * 2.094 + .7), lineMat(1)));
    S.add(this.arcs);
    var tg = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-.65, .4, .02), new THREE.Vector3(.65, .4, .02), new THREE.Vector3(0, -.62, .02)]);
    this.tri = new THREE.Mesh(tg, new THREE.MeshBasicMaterial({ color: RED, transparent: true, side: THREE.DoubleSide }));
    S.add(this.tri);
    // 节点共享几何 / 材质
    this.gRing = circlePts(.45, 32); this.gOuter = circlePts(.75, 32);
    this.gDisc = new THREE.CircleGeometry(.36, 24);
    this.mInk = new THREE.MeshBasicMaterial({ color: INK });
    this.mRed = new THREE.LineBasicMaterial({ color: RED });
    this.mLink = lineMat(.5);
    this.mDash = new THREE.LineDashedMaterial({ color: INK, dashSize: .2, gapSize: .3, transparent: true, opacity: .5 });
    var self = this;
    this.unreg = fxRegisterPass(function (ts, r) { self.render(ts, r); });
    if (!this.unreg) throw new Error('fx pass unavailable');
    this.sync({});
  }

  Task3D.prototype.node = function (s) {
    var n = this.nodes[s.key]; if (n) return n;
    var g = new THREE.Group();
    var ring = new THREE.Line(this.gRing, lineMat(.85)); g.add(ring);
    var outer = new THREE.Line(this.gOuter, lineMat(.8)); outer.visible = false; g.add(outer);
    var disc = new THREE.Mesh(this.gDisc, this.mInk); disc.visible = false; g.add(disc);
    var xg = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-.3, -.3, 0), new THREE.Vector3(.3, .3, 0), new THREE.Vector3(.3, -.3, 0), new THREE.Vector3(-.3, .3, 0)]);
    var xm = new THREE.LineSegments(xg, this.mRed); xm.visible = false; g.add(xm);
    var lg = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]);
    var link = new THREE.Line(lg, this.mDash);
    this.scene.add(g); this.scene.add(link);
    this.disposables.push(xg, lg);
    n = this.nodes[s.key] = { g: g, ring: ring, outer: outer, disc: disc, x: xm, link: link, a: null, s: s };
    this.order.push(s.key);
    return n;
  };

  /** 只响应真实事件：hit → 推近该节点；verdict/finalize → 推近目标 */
  Task3D.prototype.sync = function (ev) {
    var self = this;
    this.w.sources.forEach(function (s) { self.node(s); });
    if (ev && ev.type === 'source_done' && ev.status === 'hit' && this.nodes[ev.source]) {
      if (this.queue.length < 3) this.queue.push(ev.source);   // 命中太密时只排 3 个，避免镜头乱跳
    }
  };
  Task3D.prototype.finalize = function (phase) {
    this.final = phase; this.queue = []; this.focus = 'target';
    this.stopAt = performance.now() + 2600;   // 推近目标并停留后停止渲染，最后一帧留在 2D 画布上
  };

  Task3D.prototype.posOf = function (key) {
    if (key === 'target') return new THREE.Vector3(0, 0, 0);
    var n = this.nodes[key]; return n ? n.g.position.clone() : new THREE.Vector3();
  };

  Task3D.prototype.render = function (ts, r) {
    var w = this.w;
    // fx 被中途关掉时循环会停：这里也要主动退回 2D，避免面板冻结在最后一帧
    if (!rendererReady()) { w._drop3d('fxoff'); return; }
    if (!w.visible || !w.W) return;
    if (this.stopAt && performance.now() > this.stopAt) { this.dispose(); if (w.three === this) { w.three = null; w.root.setAttribute('data-render', 'three-final'); } return; }
    var t0 = performance.now(), t = ts / 1000, self = this;
    // ── 镜头：真实事件驱动的推近 / 跟踪 ──
    var now = performance.now();
    if (!this.final && (!this.focus || now > this.focusUntil)) {
      this.focus = this.queue.shift() || null; this.focusUntil = now + 1700;
    }
    if (this.focus) {
      var p = this.posOf(this.focus);
      var near = this.focus === 'target' ? 9 : 10.5;
      this.camTo.set(p.x * 0.85, p.y * 0.85 - near * 0.32, near); this.lookTo.copy(p);
    } else { this.camTo.copy(this.home.pos); this.lookTo.copy(this.home.look); }
    this.cam.position.lerp(this.camTo, 0.07); this.look.lerp(this.lookTo, 0.09);
    this.cam.up.set(0, 1, 0); this.cam.lookAt(this.look);
    this.cam.aspect = w.W / w.H; this.cam.updateProjectionMatrix();
    // ── 场景动画 ──
    this.sweep.rotation.z = this.final ? this.sweep.rotation.z : -t * 0.9;
    this.sweep.visible = !this.final;
    this.sector.material.opacity = ease(this.sector.material.opacity, this.focus ? 0.012 : 0.04, 0.1);  // 推近时扇形淡出，避免大面积灰块
    this.arcs.rotation.z = -t * 0.8;
    this.tri.material.opacity = this.final ? 1 : 0.55 + 0.45 * Math.abs(Math.sin(t * 2.2));
    var N = this.order.length;
    this.order.forEach(function (key, i) {
      var n = self.nodes[key], s = n.s;
      var a = Math.PI / 2 - i * (Math.PI * 2 / Math.max(N, 1));
      n.a = n.a == null ? a : ease(n.a, a, 0.15);
      n.g.position.set(Math.cos(n.a) * self.R, Math.sin(n.a) * self.R, 0.01);
      var lp = n.link.geometry.attributes.position; lp.setXYZ(1, n.g.position.x, n.g.position.y, 0); lp.needsUpdate = true;
      var hit = s.status === 'hit', bad = s.status === 'error' || s.status === 'timeout', run = s.status === 'running';
      n.disc.visible = hit; n.outer.visible = hit; n.x.visible = bad;
      n.ring.material.color.setHex(bad ? RED : INK);
      n.ring.rotation.z = run ? t * 3 : 0;
      n.link.visible = run || hit;
      n.link.material = hit ? self.mLink : self.mDash;
      if (run) { n.link.computeLineDistances(); }
    });
    // ── 渲染到共享 renderer 左下角视口，再拷贝到面板画布 ──
    var cvs = r.domElement, pr = r.getPixelRatio();
    var vw = Math.min(w.W, cvs.width / pr), vh = Math.min(w.H, cvs.height / pr);
    var prevColor = r.getClearColor(new THREE.Color()), prevAlpha = r.getClearAlpha();
    r.setScissorTest(true); r.setViewport(0, 0, vw, vh); r.setScissor(0, 0, vw, vh);
    r.setClearColor(PAPER, 1); r.clear();
    r.render(this.scene, this.cam);
    var c = w.ctx;
    c.clearRect(0, 0, w.W, w.H);
    c.drawImage(cvs, 0, cvs.height - vh * pr, vw * pr, vh * pr, 0, 0, vw, vh);
    r.setScissorTest(false); r.setViewport(0, 0, cvs.width / pr, cvs.height / pr); r.setClearColor(prevColor, prevAlpha);
    // ── 2D 叠层：枕形边框、真实来源标签（投影坐标）、锁定括号 ──
    this.overlay(c, w.W, w.H);
    var cost = performance.now() - t0 + (SW.debugCost || 0);
    this.cost = this.frames ? this.cost * 0.9 + cost * 0.1 : cost; this.frames++;
    if (this.frames > 20 && this.cost > (SW.cost3dLimit || COST_LIMIT)) w._drop3d('lowgpu');
  };

  Task3D.prototype.project = function (v) {
    var p = v.clone().project(this.cam);
    return { x: (p.x + 1) / 2 * this.w.W, y: (1 - p.y) / 2 * this.w.H, z: p.z };
  };
  Task3D.prototype.overlay = function (c, W, H) {
    c.strokeStyle = 'rgba(12,13,14,.55)'; c.lineWidth = 1; c.beginPath();
    c.moveTo(5, 4); c.quadraticCurveTo(13, H / 2, 5, H - 4); c.moveTo(W - 5, 4); c.quadraticCurveTo(W - 13, H / 2, W - 5, H - 4); c.stroke();
    var self = this;
    c.font = '10px "Share Tech Mono", "Noto Sans SC", monospace'; c.textBaseline = 'middle';
    this.order.forEach(function (key) {
      var n = self.nodes[key], s = n.s, q = self.project(n.g.position);
      if (q.z > 1 || q.x < -40 || q.x > W + 40 || q.y < 0 || q.y > H) return;
      var bad = s.status === 'error' || s.status === 'timeout';
      c.fillStyle = bad ? 'rgba(210,40,30,1)' : 'rgba(58,62,66,.95)';
      var right = q.x >= W / 2 - 4; c.textAlign = right ? 'left' : 'right';
      c.fillText(s.label, q.x + (right ? 14 : -14), q.y);
    });
    if (this.focus) {
      var f = this.project(this.posOf(this.focus)), sz = this.focus === 'target' ? 46 : 26;
      var col = this.final === 'failed' || this.final === 'aborted' ? 'rgba(210,40,30,.95)' : 'rgba(12,13,14,.9)';
      c.strokeStyle = col; c.lineWidth = 1.5; c.beginPath();
      [[-1, -1], [1, -1], [1, 1], [-1, 1]].forEach(function (d) {
        var x = f.x + d[0] * sz, y = f.y + d[1] * sz, L = sz * .35;
        c.moveTo(x, y - d[1] * L); c.lineTo(x, y); c.lineTo(x - d[0] * L, y);
      });
      c.stroke(); c.lineWidth = 1;
      if (this.focus !== 'target') {   // 锁定标签：只写真实来源名
        var lab = (this.nodes[this.focus] || {}).s; lab = lab ? lab.label : '';
        c.font = '10px "Share Tech Mono", "Noto Sans SC", monospace'; c.textAlign = 'left';
        var tw = c.measureText('LOCK · ' + lab).width + 12;
        c.fillStyle = 'rgba(12,13,14,1)'; c.fillRect(f.x - sz, f.y - sz - 18, tw, 14);
        c.fillStyle = '#FBFCFC'; c.fillText('LOCK · ' + lab, f.x - sz + 6, f.y - sz - 11);
      }
    }
  };

  Task3D.prototype.dispose = function () {
    if (this.unreg) { this.unreg(); this.unreg = null; }
    var i = live.indexOf(this); if (i >= 0) live.splice(i, 1);
    this.scene.traverse(function (o) { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
    this.disposables.forEach(function (g) { g.dispose(); });
  };

  SW.attach3d = function (w) {
    if (!rendererReady() || SW.no3d) return null;
    // 同屏只允许 1 个 3D 实例（工单 §5）：第二个长任务直接走 Canvas2D
    if (live.length >= 1) { w.root.setAttribute('data-3d-drop', 'busy'); return null; }
    try {
      var r = _fxRenderer;
      if (!r.__swLostBound) {
        r.__swLostBound = true;
        r.domElement.addEventListener('webglcontextlost', function (e) {
          e.preventDefault(); lost = true;
          live.slice().forEach(function (x) { x.w._drop3d('contextlost'); });
        });
        r.domElement.addEventListener('webglcontextrestored', function () { lost = false; });
      }
      var x = new Task3D(w); live.push(x); return x;
    } catch (e) { console.warn('3D 推镜初始化失败，使用 Canvas2D', e); return null; }
  };
  SW._3d = { live: live, ready: rendererReady };
})(window);
// #endregion wait3d
