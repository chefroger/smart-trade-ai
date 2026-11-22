// #region wait
/* ═══════════════════════════════════════════════════════════════
   TradeWait（SW）· trade 统一等待组件 · 设计稿 v1（2026-11-22）
   - 纯 Canvas2D + DOM，无依赖、无 CDN。three.js 不是必需。
   - 画布只画抽象图形（网格、扫描、准星、红色倒三角），不画任何“数据”。
   - 所有文字读数由 push() 的真实事件驱动，DOM 渲染（textContent，防注入）。
   - 降级：prefers-reduced-motion / trade_fx=0 / 低端 GPU / 页面隐藏 / 不在视口 → 静态帧。
   - 取消按钮是普通 DOM 按钮，画布 pointer-events:none，永不遮挡操作。
   ═══════════════════════════════════════════════════════════════ */
(function (global) {
  'use strict';

  var INK = '12,13,14', RED = '210,40,30';
  var PHASES = {
    searching:   { en: 'SEARCHING',       zh: '检索中' },
    analyzing:   { en: 'ANALYZING',       zh: '分析中' },
    correlating: { en: 'CORRELATING',     zh: '关联比对中' },
    composing:   { en: 'COMPOSING',       zh: '整理答复中' },
    working:     { en: 'PROCESSING',      zh: '处理中' },
    acquired:    { en: 'TARGET ACQUIRED', zh: '已完成' },
    partial:     { en: 'INCOMPLETE',      zh: '未完成 · 已保存部分结果' },
    aborted:     { en: 'ABORTED',         zh: '已停止' },
    failed:      { en: 'ERROR',           zh: '失败' }
  };
  var SRC_STATUS = { hit: '命中', miss: '未命中', error: '出错', timeout: '超时', skipped: '跳过', done: '完成' };
  var MAX_ANIMATED = 2;          // 同屏最多 2 个实例在动，其余静态
  var FRAME_MS = 1000 / 30;      // 30fps 上限

  // ── 隐私兜底：读数里屏蔽邮箱/长数字（电话、证件号）。真正的白名单在后端，见工单 ─────
  function redact(s) {
    s = String(s == null ? '' : s);
    s = s.replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, '[邮箱已隐藏]');
    s = s.replace(/\+?\d[\d\s-]{6,}\d/g, '[号码已隐藏]');
    return s.length > 80 ? s.slice(0, 77) + '…' : s;
  }
  function stripEmoji(s) { return String(s || '').replace(/^[\u2600-\u27BF\uD83C-\uDBFF\uDC00-\uDFFF\uFE0F\s]+/, ''); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function fmtT(ms) { var s = Math.max(0, Math.floor(ms / 1000)); return pad(Math.floor(s / 60)) + ':' + pad(s % 60); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function rng(seed) { return function () { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }; }

  var mq = global.matchMedia ? global.matchMedia('(prefers-reduced-motion: reduce)') : null;
  function motionAllowed() {
    if (SW.forceStatic) return false;
    if (mq && mq.matches) return false;
    try { if (localStorage.getItem('trade_fx') === '0') return false; } catch (e) {}
    return true;
  }

  // ── 共享动画循环：一个 rAF 驱动所有实例 ──────────────────────────
  var Engine = {
    list: [], raf: 0, last: 0,
    add: function (w) { this.list.push(w); this.kick(); },
    remove: function (w) { var i = this.list.indexOf(w); if (i >= 0) this.list.splice(i, 1); },
    animatedCount: function () { return this.list.filter(function (w) { return w.animating; }).length; },
    kick: function () {
      if (this.raf || document.hidden) return;
      if (!this.list.some(function (w) { return w.animating && w.visible && !w.three; })) return;
      var self = this;
      this.raf = requestAnimationFrame(function (t) { self.tick(t); });
    },
    tick: function (ts) {
      this.raf = 0;
      if (ts - this.last >= FRAME_MS) {
        this.last = ts;
        this.list.forEach(function (w) { if (w.animating && w.visible && !w.three) w._frame(ts); });
      }
      this.kick();
    }
  };
  document.addEventListener('visibilitychange', function () { Engine.kick(); });
  if (mq && mq.addEventListener) mq.addEventListener('change', function () { Engine.list.forEach(function (w) { w._applyMotion(); }); });

  // ── 实例 ──────────────────────────────────────────────────────
  function Wait(host, opts) {
    this.opts = opts || {};
    this.mode = this.opts.mode === 'task' ? 'task' : 'chat';
    this.t0 = Date.now();
    this.phaseKey = '';
    this.sources = [];          // task：{key,label,status,t}
    this.tools = {};            // chat：{id:{label,status}}
    this.final = false;
    this.visible = true;
    this.quality = 2;           // 2=完整 1=精简 0=静态（低端 GPU 自动降级）
    this.cost = 0; this.frames = 0; this.skip = 0;
    this.rand = rng(this.mode === 'task' ? 4111 : 977);
    this.nodes = [];
    this.ret = { x: 0, y: 0, tx: 0, ty: 0, lock: 0, hold: 0 };
    this.sweep = 0;
    this._build(host);
    var self = this;
    this.timer = setInterval(function () { self._tickClock(); }, 1000);
    this._tickClock();
    if (global.ResizeObserver) { this.ro = new ResizeObserver(function () { self._resize(); }); this.ro.observe(this.stageEl); }
    if (global.IntersectionObserver) {
      this.io = new IntersectionObserver(function (es) { self.visible = es[0].isIntersecting; if (self.visible) Engine.kick(); });
      this.io.observe(this.root);
    }
    this._resize();
    Engine.add(this);
    if (this.mode === 'task' && typeof SW.attach3d === 'function' && motionAllowed() && !SW.no3d) this.three = SW.attach3d(this);
    this._applyMotion();
    Status.add(this);
    this.phase(this.mode === 'task' ? 'searching' : 'analyzing');
  }

  Wait.prototype._build = function (host) {
    var r = el('div', 'sw ' + (this.mode === 'task' ? 'sw-task' : 'sw-chat'));
    r.setAttribute('data-sw', this.mode);
    var self = this;
    var cancel = el('button', 'sw-btn', this.opts.cancelText || '停止 · ABORT');
    cancel.type = 'button';
    cancel.addEventListener('click', function () {
      if (self.final) return;
      if (typeof self.opts.onCancel === 'function') self.opts.onCancel();
      self.finish({ phase: 'aborted' });
    });
    this.cancelBtn = cancel;
    var phrase = el('div', 'sw-phrase');
    phrase.setAttribute('role', 'status'); phrase.setAttribute('aria-live', 'polite');
    this.wEl = el('div', 'w'); this.ulEl = el('div', 'ul'); var tri = el('span', 'tri'); this.zhEl = el('div', 'zh');
    phrase.appendChild(this.wEl); phrase.appendChild(this.ulEl); phrase.appendChild(tri); phrase.appendChild(this.zhEl);
    var center = el('div', 'sw-center'); center.appendChild(phrase);
    this.cv = el('canvas', 'sw-cv'); this.cv.setAttribute('aria-hidden', 'true');
    this.ctx = this.cv.getContext('2d');

    if (this.mode === 'chat') {
      var top = el('div', 'sw-top');
      var l = el('span', 'lbl'); var t1 = el('span', 'tri'); t1.style.marginRight = '8px';
      l.appendChild(t1); l.appendChild(document.createTextNode(this.opts.title || 'TRADE · ASSISTANT  ///  等待回复'));
      this.clockEl = el('span', 'sw-elapsed', 'T+00:00');
      top.appendChild(l); top.appendChild(this.clockEl);
      this.toolsEl = el('div', 'sw-tools');
      var act = el('div', 'sw-actions'); act.appendChild(cancel);
      r.appendChild(this.cv); r.appendChild(top); r.appendChild(center); r.appendChild(this.toolsEl); r.appendChild(act);
      this.stageEl = r;
    } else {
      var stage = el('div', 'sw-stage'); stage.appendChild(this.cv);
      var hud = el('div', 'sw-hud');
      var hl = el('span', 'lbl'); var t2 = el('span', 'tri'); t2.style.marginRight = '8px';
      hl.appendChild(t2); hl.appendChild(document.createTextNode('/// SURVEILLANCE · 监视画面'));
      this.countEl = el('span', 'lbl', '0 / 0 SOURCES');
      hud.appendChild(hl); hud.appendChild(this.countEl);
      stage.appendChild(hud); stage.appendChild(center);
      var side = el('div', 'sw-side');
      var bar = el('div', 'sw-bar'); var bl = el('span'); var t3 = el('span', 'tri'); bl.appendChild(t3);
      bl.appendChild(document.createTextNode(this.opts.title || '背调 · BACKGROUND CHECK'));
      this.clockEl = el('span', '', 'T+00:00'); bar.appendChild(bl); bar.appendChild(this.clockEl);
      var kv = el('div', 'sw-kv');
      kv.appendChild(el('span', 'k', 'TARGET')); this.targetEl = el('span', 'v', '—'); kv.appendChild(this.targetEl);
      kv.appendChild(el('span', 'k', 'STATUS')); this.statusEl = el('span', 'v', '—'); kv.appendChild(this.statusEl);
      kv.appendChild(el('span', 'k', 'PROGRESS'));
      var pw = el('span', 'v'); this.progTxt = el('span', '', '0 / 0'); var pb = el('div', 'sw-prog'); this.progFill = el('i');
      pb.appendChild(this.progFill); pw.appendChild(this.progTxt); pw.appendChild(pb); kv.appendChild(pw);
      this.logEl = el('div', 'sw-log'); this.logEl.setAttribute('role', 'log'); this.logEl.setAttribute('aria-live', 'polite');
      var foot = el('div', 'sw-foot');
      this.verdictEl = el('span', 'sw-verdict'); foot.appendChild(this.verdictEl);
      foot.appendChild(el('span')); foot.appendChild(cancel);
      side.appendChild(bar); side.appendChild(kv); side.appendChild(this.logEl); side.appendChild(foot);
      r.appendChild(stage); r.appendChild(side);
      this.stageEl = stage;
    }
    host.appendChild(r);
    this.root = r;
  };

  Wait.prototype._applyMotion = function () {
    if (this.three && !this.final && motionAllowed()) { this.animating = true; this.root.classList.remove('is-static'); this.root.setAttribute('data-render', 'three'); return; }
    if (this.three && !this.final) this._drop3d('motion');
    this.root.setAttribute('data-render', '2d');
    var want = motionAllowed() && this.quality > 0 && !this.final && Engine.animatedCount() - (this.animating ? 1 : 0) < MAX_ANIMATED;
    this.animating = !!want;
    this.root.classList.toggle('is-static', !this.animating);
    if (this.animating) Engine.kick(); else this._draw(0, true);
  };

  Wait.prototype._resize = function () {
    var w = Math.max(1, this.stageEl.clientWidth), h = Math.max(1, this.stageEl.clientHeight);
    var dpr = Math.min(global.devicePixelRatio || 1, 2);
    this.cv.width = Math.round(w * dpr); this.cv.height = Math.round(h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.W = w; this.H = h;
    // 抽象节点：固定种子；聊天模式避开中间文字区
    var R = rng(this.mode === 'task' ? 4111 : 977); this.nodes = [];
    var n = this.mode === 'task' ? 26 : 22;
    for (var i = 0; i < n; i++) {
      var x = R() * w, y = this.mode === 'chat' ? 44 + R() * (h - 80) : 28 + R() * (h - 48);
      if (this.mode === 'chat' && x > w * 0.3 && x < w * 0.7) x = x < w / 2 ? x - w * 0.22 : x + w * 0.22;
      this.nodes.push({ x: Math.max(14, Math.min(w - 14, x)), y: y, hl: 0 });
    }
    if (!this.ret.x) { var s = this.nodes[0]; this.ret.x = this.ret.tx = s.x; this.ret.y = this.ret.ty = s.y; }
    if (!this.three) this._draw(performance.now(), !this.animating);
  };

  Wait.prototype._frame = function (ts) {
    if (this.quality === 1 && (this.skip++ & 1)) return;     // 精简档：15fps
    var a = performance.now();
    this._draw(ts, false);
    if (SW.debugCost) { var e = a + SW.debugCost; while (performance.now() < e) {} } // 仅演示：模拟低端 GPU
    var c = performance.now() - a;
    this.cost = this.frames ? this.cost * 0.9 + c * 0.1 : c; this.frames++;
    if (this.frames > 20) {
      if (this.cost > 12 && this.quality > 0) { this.quality = 0; this._applyMotion(); this._emitQuality(); }
      else if (this.cost > 6 && this.quality > 1) { this.quality = 1; this.frames = 0; this._emitQuality(); }
    }
  };
  Wait.prototype._emitQuality = function () { this.root.setAttribute('data-quality', ['static', 'lite', 'full'][this.quality]); };

  // ── 绘制 ──────────────────────────────────────────────────────
  Wait.prototype._draw = function (ts, still) {
    var c = this.ctx, w = this.W, h = this.H; if (!c || !w) return;
    var t = still ? 0 : ts / 1000;
    c.clearRect(0, 0, w, h);
    c.fillStyle = '#FBFCFC'; c.fillRect(0, 0, w, h);
    // 网格 + 十字点（撒马利亚人画面里的 “+” 阵列）
    var g = 32; c.lineWidth = 1;
    c.strokeStyle = 'rgba(' + INK + ',.045)'; c.beginPath();
    for (var x = g; x < w; x += g) { c.moveTo(x + .5, 0); c.lineTo(x + .5, h); }
    for (var y = g; y < h; y += g) { c.moveTo(0, y + .5); c.lineTo(w, y + .5); }
    c.stroke();
    c.strokeStyle = 'rgba(' + INK + ',.22)'; c.beginPath();
    for (x = g * 2; x < w; x += g * 2) for (y = g * 2; y < h; y += g * 2) { c.moveTo(x - 3, y + .5); c.lineTo(x + 3, y + .5); c.moveTo(x + .5, y - 3); c.lineTo(x + .5, y + 3); }
    c.stroke();
    // 枕形畸变边框：两侧竖线向内弯（撒马利亚人 = pincushion，The Machine = barrel）
    c.strokeStyle = 'rgba(' + INK + ',.55)'; c.beginPath();
    c.moveTo(5, 4); c.quadraticCurveTo(13, h / 2, 5, h - 4);
    c.moveTo(w - 5, 4); c.quadraticCurveTo(w - 13, h / 2, w - 5, h - 4); c.stroke();
    c.fillStyle = 'rgba(' + INK + ',.7)';
    c.fillRect(7, h * 0.3, 4, 7); c.fillRect(w - 11, h * 0.62, 4, 7);
    if (this.mode === 'chat') this._drawChat(c, w, h, t, still); else this._drawTask(c, w, h, t, still);
  };

  function ring(c, x, y, r, rot, alpha) {
    c.strokeStyle = 'rgba(' + INK + ',' + alpha + ')'; c.lineWidth = 1;
    c.beginPath(); c.arc(x, y, r, 0, 6.2832); c.stroke();
    c.lineWidth = 2; c.beginPath();
    for (var k = 0; k < 3; k++) { var a = rot + k * 2.094; c.moveTo(x + Math.cos(a) * (r + 4), y + Math.sin(a) * (r + 4)); c.arc(x, y, r + 4, a, a + 0.7); }
    c.stroke(); c.lineWidth = 1;
    c.beginPath();
    [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(function (d) { c.moveTo(x + d[0] * (r - 4), y + d[1] * (r - 4)); c.lineTo(x + d[0] * (r + 1), y + d[1] * (r + 1)); });
    c.stroke();
  }
  function brackets(c, x, y, s, k, color) {
    var L = s * 0.35; c.strokeStyle = color; c.lineWidth = 1.5; c.beginPath();
    [[-1, -1], [1, -1], [1, 1], [-1, 1]].forEach(function (d) {
      var cx = x + d[0] * s, cy = y + d[1] * s;
      c.moveTo(cx, cy - d[1] * L * k); c.lineTo(cx, cy); c.lineTo(cx - d[0] * L * k, cy);
    });
    c.stroke(); c.lineWidth = 1;
  }
  function tri(c, x, y, s, a) {  // 红色倒三角 = 目标
    c.fillStyle = 'rgba(' + RED + ',' + a + ')';
    c.beginPath(); c.moveTo(x - s, y - s * 0.6); c.lineTo(x + s, y - s * 0.6); c.lineTo(x, y + s * 0.95); c.closePath(); c.fill();
  }

  Wait.prototype._drawChat = function (c, w, h, t, still) {
    var full = this.quality === 2 && !still;
    var sx = still ? w * 0.26 : (t * w * 0.16) % (w + 80) - 40;
    if (full) {
      var gr = c.createLinearGradient(sx - 120, 0, sx, 0);
      gr.addColorStop(0, 'rgba(' + INK + ',0)'); gr.addColorStop(1, 'rgba(' + INK + ',.035)');
      c.fillStyle = gr; c.fillRect(sx - 120, 0, 120, h);
    }
    c.strokeStyle = 'rgba(' + INK + ',.35)'; c.beginPath(); c.moveTo(sx + .5, 0); c.lineTo(sx + .5, h); c.stroke();
    var self = this;
    this.nodes.forEach(function (n) {
      if (Math.abs(n.x - sx) < 4) n.hl = 1; else n.hl *= 0.94;
      c.fillStyle = 'rgba(' + INK + ',' + (0.22 + n.hl * 0.6) + ')';
      c.beginPath(); c.arc(n.x, n.y, 1.6 + n.hl, 0, 6.2832); c.fill();
    });
    this._reticle(c, t, still, 15);
  };

  Wait.prototype._reticle = function (c, t, still, r) {
    var R = this.ret;
    if (!still) {
      R.x += (R.tx - R.x) * 0.12; R.y += (R.ty - R.y) * 0.12;
      var near = Math.abs(R.tx - R.x) + Math.abs(R.ty - R.y) < 1.5;
      R.lock = near ? Math.min(1, R.lock + 0.08) : Math.max(0, R.lock - 0.2);
      if (near && R.lock >= 1) { if (!R.hold) R.hold = t + 1.1; if (t > R.hold) { var n = this.nodes[Math.floor(this.rand() * this.nodes.length)]; R.tx = n.x; R.ty = n.y; R.hold = 0; } }
    } else { R.lock = 1; }
    ring(c, R.x, R.y, r, still ? 0.4 : t * 1.4, 0.75);
    if (R.lock > 0) { brackets(c, R.x, R.y, r + 10, R.lock, 'rgba(' + INK + ',.85)'); tri(c, R.x, R.y, r * 0.42, R.lock); }
  };

  Wait.prototype._drawTask = function (c, w, h, t, still) {
    var full = this.quality === 2 && !still;
    var avail = h - 30 - 84, cx = w / 2, cy = 30 + avail / 2, orb = Math.min(w * 0.3, avail / 2 - 22);
    // 外圈 / 轨道（圆形 = 撒马利亚人的“全景监狱”母题）
    c.strokeStyle = 'rgba(' + INK + ',.12)'; c.beginPath(); c.arc(cx, cy, orb + 26, 0, 6.2832); c.stroke();
    c.setLineDash([3, 5]); c.strokeStyle = 'rgba(' + INK + ',.35)'; c.beginPath(); c.arc(cx, cy, orb, 0, 6.2832); c.stroke(); c.setLineDash([]);
    // 径向扫描
    var sa = still ? -0.9 : t * 0.9;
    if (full && c.createConicGradient) {
      var cg = c.createConicGradient(sa - 0.9, cx, cy);
      cg.addColorStop(0, 'rgba(' + INK + ',0)'); cg.addColorStop(0.143, 'rgba(' + INK + ',.07)'); cg.addColorStop(0.144, 'rgba(' + INK + ',0)'); cg.addColorStop(1, 'rgba(' + INK + ',0)');
      c.fillStyle = cg; c.beginPath(); c.moveTo(cx, cy); c.arc(cx, cy, orb + 26, sa - 0.9, sa); c.closePath(); c.fill();
    }
    if (!this.final) { c.strokeStyle = 'rgba(' + INK + ',.4)'; c.beginPath(); c.moveTo(cx, cy); c.lineTo(cx + Math.cos(sa) * (orb + 26), cy + Math.sin(sa) * (orb + 26)); c.stroke(); }
    // 背景抽象点（不代表任何数据）
    this.nodes.forEach(function (n) { c.fillStyle = 'rgba(' + INK + ',.16)'; c.fillRect(n.x, n.y, 1.5, 1.5); });
    // 来源节点：位置与标签只来自真实事件
    var N = this.sources.length, self = this;
    this.sources.forEach(function (s, i) {
      var a = -Math.PI / 2 + i * (6.2832 / Math.max(N, 1));
      s.ax = s.ax == null ? a : s.ax + (a - s.ax) * (still ? 1 : 0.15);
      var x = cx + Math.cos(s.ax) * orb, y = cy + Math.sin(s.ax) * orb;
      var swept = !still && Math.abs(((sa - s.ax) % 6.2832 + 6.2832) % 6.2832) < 0.25;
      if (s.status === 'running') {
        c.setLineDash([2, 4]); c.lineDashOffset = still ? 0 : -t * 20;
        c.strokeStyle = 'rgba(' + INK + ',.45)'; c.beginPath(); c.moveTo(cx, cy); c.lineTo(x, y); c.stroke(); c.setLineDash([]);
        ring(c, x, y, 6, still ? 0 : t * 3, 0.8);
      } else if (s.status === 'hit') {
        c.strokeStyle = 'rgba(' + INK + ',.55)'; c.beginPath(); c.moveTo(cx, cy); c.lineTo(x, y); c.stroke();
        c.fillStyle = 'rgba(' + INK + ',1)'; c.beginPath(); c.arc(x, y, 5.5, 0, 6.2832); c.fill();
        c.strokeStyle = 'rgba(' + INK + ',.8)'; c.beginPath(); c.arc(x, y, 9 + (swept ? 2 : 0), 0, 6.2832); c.stroke();
      } else if (s.status === 'error' || s.status === 'timeout') {
        c.strokeStyle = 'rgba(' + RED + ',.9)'; c.beginPath(); c.arc(x, y, 6, 0, 6.2832);
        c.moveTo(x - 3.5, y - 3.5); c.lineTo(x + 3.5, y + 3.5); c.moveTo(x + 3.5, y - 3.5); c.lineTo(x - 3.5, y + 3.5); c.stroke();
      } else if (s.status === 'skipped') {
        c.setLineDash([1, 3]); c.strokeStyle = 'rgba(' + INK + ',.4)'; c.beginPath(); c.arc(x, y, 6, 0, 6.2832); c.stroke(); c.setLineDash([]);
      } else {
        c.strokeStyle = 'rgba(' + INK + ',' + (swept ? .9 : .5) + ')'; c.beginPath(); c.arc(x, y, 5.5, 0, 6.2832); c.stroke();
      }
      // 标签：来源名（真实）
      c.font = '10px "Share Tech Mono", "Noto Sans SC", monospace';
      c.fillStyle = s.status === 'error' || s.status === 'timeout' ? 'rgba(' + RED + ',1)' : 'rgba(58,62,66,.95)';
      var right = Math.cos(s.ax) >= -0.05;
      c.textAlign = right ? 'left' : 'right'; c.textBaseline = 'middle';
      c.fillText(s.label, x + (right ? 13 : -13), y);
    });
    // 中心目标：双圈 + 红色倒三角；完成后四角锁定
    var pulse = still || this.final ? 1 : 0.55 + 0.45 * Math.abs(Math.sin(t * 2.2));
    ring(c, cx, cy, 22, still ? 0.3 : -t * 0.8, 0.9);
    c.strokeStyle = 'rgba(' + INK + ',.5)'; c.beginPath(); c.arc(cx, cy, 30, 0, 6.2832); c.stroke();
    tri(c, cx, cy, 9, pulse);
    if (this.final) brackets(c, cx, cy, 40, 1, this.phaseKey === 'failed' || this.phaseKey === 'aborted' ? 'rgba(' + RED + ',.9)' : 'rgba(' + INK + ',.9)');
  };

  // ── 状态 / 事件 ───────────────────────────────────────────────
  Wait.prototype._tickClock = function () {
    if (this.final) return;
    this.clockEl.textContent = 'T+' + fmtT(Date.now() - this.t0);
  };

  Wait.prototype.phase = function (key, zh) {
    var p = PHASES[key] || PHASES.working;
    var zhText = zh ? redact(zh) : p.zh;
    if (key === this.phaseKey && this.zhEl.textContent === zhText) return;
    this.phaseKey = key; this.zhEl.textContent = zhText;
    if (this.statusEl) this.statusEl.textContent = p.en + ' · ' + zhText;
    var words = p.en.split(' '), self = this, i = 0;
    clearTimeout(this._wt);
    var reveal = function () {
      self.wEl.textContent = words[i];
      self.ulEl.style.width = Math.max(30, self.wEl.offsetWidth * 0.9) + 'px';
      i++; if (i < words.length) self._wt = setTimeout(reveal, self.animating ? 420 : 0);
      else if (words.length > 1) self._wt = setTimeout(function () { self.wEl.textContent = p.en; self.ulEl.style.width = Math.max(30, self.wEl.offsetWidth * 0.9) + 'px'; }, self.animating ? 420 : 0);
    };
    if (this.animating) reveal(); else { this.wEl.textContent = p.en; this.ulEl.style.width = '60px'; }
    if (!this.animating) this._draw(0, true);
  };

  Wait.prototype._log = function (text, cls, strong) {
    if (!this.logEl) return;
    var row = el('div', 'row ' + (cls || ''));
    row.appendChild(el('span', 'ts', '+' + fmtT(Date.now() - this.t0)));
    row.appendChild(el('span', 'dot'));
    var tx = el('span', 'tx');
    if (strong) { tx.appendChild(el('b', '', redact(strong))); tx.appendChild(document.createTextNode(text ? ' · ' + redact(text) : '')); }
    else tx.textContent = redact(text);
    row.appendChild(tx);
    var stick = this.logEl.scrollTop + this.logEl.clientHeight >= this.logEl.scrollHeight - 4;
    this.logEl.appendChild(row);
    while (this.logEl.children.length > 200) this.logEl.removeChild(this.logEl.firstChild);
    if (stick) this.logEl.scrollTop = this.logEl.scrollHeight;
  };

  /** 追加一条任务读数（Hermes 升级日志等）。文字由调用方负责过滤敏感内容。 */
  Wait.prototype.note = function (text, opts) {
    if (this.mode !== 'task' || this.final) return;
    opts = opts || {};
    this._log(opts.detail || '', opts.cls || '', text);
  };

  Wait.prototype._progress = function () {
    var n = this.sources.length, d = this.sources.filter(function (s) { return s.status !== 'running'; }).length;
    if (this.countEl) this.countEl.textContent = d + ' / ' + n + ' SOURCES';
    if (this.progTxt) this.progTxt.textContent = d + ' / ' + n;
    if (this.progFill) this.progFill.style.width = (n ? (d / n) * 100 : 0) + '%';
  };

  /** 唯一入口：传入后端真实事件。只读取白名单字段，其他字段（如工具参数 args）一律丢弃。 */
  Wait.prototype.push = function (ev) {
    if (!ev || this.final) return;
    var type = ev.type;
    if (this.mode === 'chat') {
      if (type === 'thinking') this.phase(/整理|答复/.test(ev.message || '') ? 'composing' : 'analyzing', ev.message);
      else if (type === 'tool_start') {
        var lab = redact(stripEmoji(ev.label || ev.name || '工具'));
        this.tools[ev.id] = { label: lab, status: 'run' };
        var n = Object.keys(this.tools).length;
        this.phase(n > 1 ? 'correlating' : 'searching', '正在调用：' + lab); this.curTool = lab;
      } else if (type === 'tool_complete' || type === 'tool_failed') {
        if (this.tools[ev.id]) this.tools[ev.id].status = type === 'tool_failed' ? 'err' : 'ok';
      } else if (type === 'analysis_gate') {
        this.phase('analyzing', ev.ok ? '已完整读取 ' + (ev.files || 0) + ' 个文件' : '完整读取未通过');
      }
      this._renderTools();
    } else {
      if (type === 'job_start') { this.targetEl.textContent = redact(ev.target || '—'); this._log('预算 ' + (ev.budget || '?') + ' 秒', '', '任务已启动'); this.phase('searching'); }
      else if (type === 'source_start') {
        var key = String(ev.source || ''), s = this._src(key);
        if (!s) { s = { key: key, label: redact(ev.label || key), status: 'running' }; this.sources.push(s); }
        s.status = 'running';
        this._log('查询中…', '', s.label);
      } else if (type === 'source_done') {
        var s2 = this._src(String(ev.source || ''));
        if (s2) {
          s2.status = ev.status || 'done';
          var bad = s2.status === 'error' || s2.status === 'timeout';
          this._log((SRC_STATUS[s2.status] || s2.status) + (ev.ms != null ? ' · ' + (ev.ms / 1000).toFixed(1) + 's' : ''), s2.status === 'hit' ? 'hit' : (bad ? 'bad' : ''), s2.label);
          var running = this.sources.some(function (x) { return x.status === 'running'; });
          this.phase(running ? 'correlating' : 'composing', running ? null : '汇总评分中');
        }
      } else if (type === 'verdict') {
        var un = (ev.unverified || []).length;
        this._log(un ? un + ' 项未核验' : '全部来源已返回', 'hit', '评级 ' + (ev.rating || '未知'));
        this.finish({ phase: 'acquired', zh: un ? '已完成 · ' + un + ' 项未核验' : '已完成', verdict: ev.rating });
        return;
      } else if (type === 'error') { this._log(ev.message || '', 'bad', '错误'); this.finish({ phase: 'failed' }); return; }
      else if (type === 'cancelled') { this._log('', 'bad', '已取消'); this.finish({ phase: 'aborted' }); return; }
      this._progress();
    }
    if (this.three) this.three.sync(ev);
    else if (!this.animating) this._draw(0, true);
    Status.update();
  };
  Wait.prototype._src = function (k) { for (var i = 0; i < this.sources.length; i++) if (this.sources[i].key === k) return this.sources[i]; return null; };
  Wait.prototype._renderTools = function () {
    var self = this; this.toolsEl.textContent = '';
    Object.keys(this.tools).slice(-4).forEach(function (id) { var t = self.tools[id]; self.toolsEl.appendChild(el('span', 't ' + t.status, t.label)); });
  };

  Wait.prototype.finish = function (o) {
    if (this.final) return;
    o = o || {};
    this.final = true;
    var three = this.three;
    this.phase(o.phase || 'acquired', o.zh);
    this.root.classList.add('is-final');
    this.cancelBtn.disabled = true; this.cancelBtn.textContent = o.phase === 'aborted' ? '已停止' : '完成';
    if (this.verdictEl && o.verdict) {
      this.verdictEl.textContent = 'CONCLUSION:';
      var tag = el('span', 'tag' + (/高|严重|high/i.test(o.verdict) ? '' : ' neutral'), redact(o.verdict));
      this.verdictEl.appendChild(tag);
    }
    this._progress && this.mode === 'task' && this._progress();
    clearInterval(this.timer);
    this.animating = false; this.root.classList.add('is-static');
    Status.remove(this);
    if (three) three.finalize(o.phase || 'acquired');   // 3D：推镜到目标并停留，最后一帧保留在画布上
    else this._draw(0, true);
    Engine.list.forEach(function (w) { if (!w.animating && !w.final) w._applyMotion(); });
  };

  Wait.prototype._drop3d = function (why) {
    if (!this.three) return;
    try { this.three.dispose(); } catch (e) {}
    this.three = null; this.root.setAttribute('data-render', '2d'); this.root.setAttribute('data-3d-drop', why || '');
    this._applyMotion(); if (!this.animating) this._draw(0, true);
  };

  Wait.prototype.destroy = function () {
    Status.remove(this);
    if (this.three) { try { this.three.dispose(); } catch (e) {} this.three = null; }
    clearInterval(this.timer); clearTimeout(this._wt);
    if (this.ro) this.ro.disconnect(); if (this.io) this.io.disconnect();
    Engine.remove(this);
    if (this.root.parentNode) this.root.parentNode.removeChild(this.root);
    Engine.list.forEach(function (w) { if (!w.animating && !w.final) w._applyMotion(); });
  };

  // ── 内联模式：按钮 / 状态行 ──────────────────────────────────
  function inline(target, o) {
    o = o || {};
    var prev = target.innerHTML, wasDisabled = target.disabled;
    var s = el('span', 'sw-inline' + (motionAllowed() ? '' : ' is-static'));
    s.appendChild(el('span', 'tri')); s.appendChild(el('span', 'w', o.en || 'WORKING'));
    if (o.zh) s.appendChild(el('span', 'zh', o.zh));
    target.textContent = ''; target.appendChild(s);
    if (o.disable !== false && 'disabled' in target) target.disabled = true;
    return function restore() { target.innerHTML = prev; if ('disabled' in target) target.disabled = wasDisabled; };
  }

  // ── 顶栏真实任务状态（替代装饰轮播；只用真实事件，空闲时还原）──────────
  // 两个元素都要接管：顶栏 #app-top-status 和侧栏 #sys-status（工单 §3.1）。
  // 优先级：画像页 > 等待状态 > 装饰轮播 —— 画像页打开时 customers.js 拥有顶栏，
  // 这里只接管侧栏，不覆盖画像统计。
  var Status = {
    list: [], saved: {},
    ids: function () { return SW.statusElIds || ['app-top-status', 'sys-status']; },
    add: function (w) { if (this.list.indexOf(w) < 0) this.list.push(w); this.update(); },
    remove: function (w) { var i = this.list.indexOf(w); if (i >= 0) this.list.splice(i, 1); this.update(); },
    active: function () { return this.list.length > 0; },
    text: function () {
      var task = this.list.filter(function (w) { return w.mode === 'task'; })[0];
      if (task) {
        var n = task.sources.length, d = task.sources.filter(function (s) { return s.status !== 'running'; }).length;
        return (task.opts.statusLabel || '背调进行中') + (n ? ' ' + d + '/' + n : '') + (this.list.length > 1 ? ' · 另有 ' + (this.list.length - 1) + ' 项等待' : '');
      }
      var c = this.list[0];
      return '对话处理中' + (c.curTool ? ' · 正在调用：' + c.curTool : '');
    },
    update: function () {
      var text = this.active() ? this.text() : '';
      var profileOwns = document.body.classList.contains('profile-open');
      this.ids().forEach(function (id) {
        var e = document.getElementById(id);
        if (!e) return;
        // 画像页统计优先：顶栏让给 customers.js，侧栏仍显示等待
        if (text && id === 'app-top-status' && profileOwns) return;
        if (text) {
          if (!(id in this.saved)) this.saved[id] = e.textContent;
          e.textContent = text; e.setAttribute('data-wait', '1');
        } else if (id in this.saved) {
          e.textContent = this.saved[id]; delete this.saved[id]; e.removeAttribute('data-wait');
        }
      }, this);
    }
  };
  global.TradeWaitStatus = {
    active: function () { return Status.active(); },
    text: function () { return Status.active() ? Status.text() : ''; },
    refresh: function () { Status.update(); }
  };

  var SW = {
    statusElIds: ['app-top-status', 'sys-status'],
    no3d: false,
    mount: function (host, opts) { return new Wait(host, opts); },
    _motionAllowed: function () { return motionAllowed(); },
    inline: inline,
    redact: redact,
    forceStatic: false,
    debugCost: 0,
    refreshMotion: function () { Engine.list.forEach(function (w) { w._applyMotion(); }); },
    _engine: Engine
  };
  global.TradeWait = SW;
})(window);
// #endregion wait
