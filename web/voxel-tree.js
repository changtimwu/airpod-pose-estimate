/* ============================================================
   voxel-tree.js — the tree that keeps growing while you hold.
   Owner 03 · INTERFACE. Geometry only; every colour lives in style.css.

   Two halves:

   1. A GROWER that emits voxels in birth order and never finishes. It is a
      breadth-first queue of growing tips, so every limb extends at once and
      the thing looks alive rather than drawn. When the queue runs dry it
      raises the crown and throws new shoots, forever.

   2. A RENDERER that draws those voxels as isometric cubes, DOM-ordered by
      depth once at build time, and reveals them by birth index. Revealing
      count n is a pure function of n, so running growth backwards — the
      wilt — is the same code path as running it forwards.

   Isometric projection, camera fixed at +x +y +z:
       sx = (x - z) * TW
       sy = (x + z) * TH - y * VH        with VH = 2 * TH, so cubes stack flush
   Painter's order is ascending (x + y + z): larger is nearer the camera.
   ============================================================ */
(function (global) {
  'use strict';

  var SVGNS = 'http://www.w3.org/2000/svg';

  var TW = 15;      // half-width of a cube's top diamond
  var TH = 7.5;     // quarter-height of that diamond
  var VH = 15;      // cube side height on screen (= 2 * TH)

  var BUDGET = 1500;   // voxels generated up front — about five minutes of holding.
                       // Costs 3 paths each at load; past this the tree stops.
  var GROUND_R = 4.2;  // grass platform radius, in voxels — small enough that
                       // a one-block seedling still owns the frame

  /* deterministic: the tree must be byte-identical every frame and every
     run, or it shimmers at 25 Hz and looks like a bug. */
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function norm(v) {
    var m = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) || 1;
    return [v[0] / m, v[1] / m, v[2] / m];
  }

  /* ── the grower ────────────────────────────────────────────
     Rates are tuned so the first three seconds already read as a plant.
     A demo that shows nothing for ten seconds is a demo nobody watches.
  */
  function growTree(seed, budget) {
    var rng = mulberry32(seed);
    var voxels = [];
    var seen = Object.create(null);
    var bank = [];            // bark voxels that can sprout a later shoot
    var crown = { x: 0, y: 0, z: 0 };
    var tips = [];

    function put(x, y, z, pal) {
      var k = x + ',' + y + ',' + z;
      if (seen[k]) return;
      seen[k] = 1;
      voxels.push({ x: x, y: y, z: z, pal: pal });
    }

    var trunk = [];     // the depth-0 column, kept so it can thicken later
    var girth = 1;

    function bark(x, y, z, isTrunk) {
      put(x, y, z, rng() < 0.28 ? 'bark2' : 'bark');
      if (y > crown.y) { crown.x = x; crown.y = y; crown.z = z; }
      if (isTrunk) trunk.push([x, y, z]);
      if (bank.length < 400) bank.push([x, y, z]);
    }

    /* Every generation lays down another ring of bark, tapering with
       height. It is what stops a long hold turning into a mushroom —
       and it is the literal thing a real tree does with the time. */
    function thicken(cap) {
      girth++;
      var added = 0, top = Math.max(1, crown.y);
      for (var i = 0; i < trunk.length && added < cap; i++) {
        var c = trunk[i];
        var r = girth * (1 - Math.min(0.85, c[1] / top * 0.9));
        if (r < 1) continue;
        for (var dx = -girth; dx <= girth && added < cap; dx++)
          for (var dz = -girth; dz <= girth && added < cap; dz++) {
            if (dx * dx + dz * dz > r * r) continue;
            var k = (c[0] + dx) + ',' + c[1] + ',' + (c[2] + dz);
            if (seen[k]) continue;
            put(c[0] + dx, c[1], c[2] + dz, rng() < 0.3 ? 'bark2' : 'bark');
            added++;
          }
      }
    }

    /* leaf clusters fill centre-out so they bloom rather than blink */
    function cluster(cx, cy, cz, r, allowBloom) {
      var cells = [], dx, dy, dz, d;
      var R = Math.ceil(r) + 1;
      for (dx = -R; dx <= R; dx++)
        for (dy = -R; dy <= R; dy++)
          for (dz = -R; dz <= R; dz++) {
            d = Math.sqrt(dx * dx + dy * dy * 1.5 + dz * dz);
            if (d > r) continue;
            if (d > r - 0.9 && rng() < 0.45) continue;   // ragged silhouette
            cells.push([d, dx, dy, dz]);
          }
      cells.sort(function (a, b) { return a[0] - b[0]; });
      for (var i = 0; i < cells.length; i++) {
        var pal;
        if (allowBloom && rng() < 0.085) pal = 'bloom';
        else pal = rng() < 0.34 ? 'leafA' : (rng() < 0.5 ? 'leafB' : 'leafC');
        put(cx + cells[i][1], cy + cells[i][2], cz + cells[i][3], pal);
      }
    }

    function spawn(tip, n) {
      for (var i = 0; i < n; i++) {
        var side = norm([rng() - 0.5, 0, rng() - 0.5]);
        tips.push({
          p: [tip.p[0], tip.p[1], tip.p[2]],
          d: norm([
            tip.d[0] * 0.3 + side[0] * 1.05,
            tip.d[1] * 0.35 + 0.42,
            tip.d[2] * 0.3 + side[2] * 1.05
          ]),
          life: Math.max(2, Math.round((tip.life + 4) * 0.58)),
          w: tip.depth === 0 ? 1 : 1,
          depth: tip.depth + 1
        });
      }
    }

    tips.push({ p: [0, 0, 0], d: [0, 1, 0], life: 11, w: 2, depth: 0 });

    var guard = 0;
    while (voxels.length < budget && guard++ < budget * 8) {

      if (!tips.length) {
        /* Never finished. Thicken the trunk, raise the crown, then throw
           two shoots off the existing frame. This is "keeps growing". */
        thicken(26);
        tips.push({ p: [crown.x, crown.y, crown.z], d: [0, 1, 0],
                    life: 4 + ((rng() * 4) | 0), w: 1, depth: 0 });
        for (var s = 0; s < 2 && bank.length; s++) {
          var b = bank[(rng() * bank.length) | 0];
          var side = norm([rng() - 0.5, 0, rng() - 0.5]);
          tips.push({ p: [b[0], b[1], b[2]],
                      d: norm([side[0], 0.55 + rng() * 0.5, side[2]]),
                      life: 3 + ((rng() * 3) | 0), w: 1, depth: 1 });
        }
        continue;
      }

      var tip = tips.shift();

      /* reach for the light, and wander a little. The trunk wanders far
         less than the limbs do, or it comes out as a staircase. */
      var wob = tip.depth === 0 ? 0.09 : 0.32;
      tip.d = norm([
        tip.d[0] + (rng() - 0.5) * wob,
        tip.d[1] + (tip.depth === 0 ? 0.16 : 0.075),
        tip.d[2] + (rng() - 0.5) * wob
      ]);
      tip.p = [tip.p[0] + tip.d[0], tip.p[1] + tip.d[1], tip.p[2] + tip.d[2]];

      var px = Math.round(tip.p[0]), py = Math.round(tip.p[1]), pz = Math.round(tip.p[2]);
      var isTrunk = tip.depth === 0;
      if (tip.w >= 2) {
        bark(px, py, pz, isTrunk); bark(px + 1, py, pz, isTrunk);
        bark(px, py, pz + 1, isTrunk); bark(px + 1, py, pz + 1, isTrunk);
      } else {
        bark(px, py, pz, isTrunk);
      }

      tip.life--;
      if (tip.life > 0) { tips.push(tip); continue; }   // breadth-first: all limbs at once

      var mature = voxels.length > 210;
      cluster(px, py, pz, tip.depth === 0 ? 2.9 : tip.depth === 1 ? 2.5 : 1.9, mature);
      if (tip.depth < 3) spawn(tip, tip.depth === 0 ? 3 : (rng() < 0.35 ? 3 : 2));
    }

    /* the diorama it stands on — always visible, never part of growth */
    var ground = [];
    for (var gx = -8; gx <= 8; gx++)
      for (var gz = -8; gz <= 8; gz++) {
        var dist = Math.sqrt(gx * gx + gz * gz);
        if (dist > GROUND_R + rng() * 0.8) continue;
        ground.push({ x: gx, y: -1, z: gz, pal: dist > GROUND_R - 1.2 ? 'grass2' : 'grass' });
        if (dist < GROUND_R - 1.6) ground.push({ x: gx, y: -2, z: gz, pal: 'dirt' });
      }

    return { voxels: voxels, ground: ground };
  }

  /* ── renderer ─────────────────────────────────────────────── */

  function faces(sx, sy) {
    return [
      /* top    */ 'M' + sx + ' ' + sy + 'l' + TW + ' ' + TH + 'l' + (-TW) + ' ' + TH + 'l' + (-TW) + ' ' + (-TH) + 'Z',
      /* left   */ 'M' + (sx - TW) + ' ' + (sy + TH) + 'l' + TW + ' ' + TH + 'v' + VH + 'l' + (-TW) + ' ' + (-TH) + 'Z',
      /* right  */ 'M' + (sx + TW) + ' ' + (sy + TH) + 'l' + (-TW) + ' ' + TH + 'v' + VH + 'l' + TW + ' ' + (-TH) + 'Z'
    ];
  }

  function VoxelTree(opts) {
    var grown = growTree(opts.seed || 20260920, opts.budget || BUDGET);
    var list = [], i, v;

    for (i = 0; i < grown.ground.length; i++) { v = grown.ground[i]; v.birth = -1; list.push(v); }
    for (i = 0; i < grown.voxels.length; i++) { v = grown.voxels[i]; v.birth = i;  list.push(v); }

    for (i = 0; i < list.length; i++) {
      v = list[i];
      v.sx = (v.x - v.z) * TW;
      v.sy = (v.x + v.z) * TH - v.y * VH;
      v.depth = v.x + v.y + v.z;
    }

    /* DOM order is painter's order, fixed once. Reveal order is birth order.
       Keeping those two independent is what makes this cheap. */
    var drawOrder = list.slice().sort(function (a, b) { return a.depth - b.depth; });

    var frag = document.createDocumentFragment();
    for (i = 0; i < drawOrder.length; i++) {
      v = drawOrder[i];
      var g = document.createElementNS(SVGNS, 'g');
      g.setAttribute('class', 'vox vox--' + v.pal);
      var f = faces(v.sx, v.sy);
      for (var k = 0; k < 3; k++) {
        var p = document.createElementNS(SVGNS, 'path');
        p.setAttribute('d', f[k]);
        p.setAttribute('class', 'f' + k);
        g.appendChild(p);
      }
      if (v.birth >= 0) g.style.display = 'none';
      v.el = g;
      frag.appendChild(g);
    }
    opts.mount.appendChild(frag);

    /* birth-ordered view (same objects as `list`, just the growing ones),
       plus a prefix-min/max so the bounding box for any reveal count is O(1) */
    this.byBirth = grown.voxels;

    var gMinX = 1e9, gMaxX = -1e9, gMinY = 1e9, gMaxY = -1e9;
    for (i = 0; i < grown.ground.length; i++) {
      v = list[i];
      if (v.sx - TW < gMinX) gMinX = v.sx - TW;
      if (v.sx + TW > gMaxX) gMaxX = v.sx + TW;
      if (v.sy < gMinY) gMinY = v.sy;
      if (v.sy + 2 * TH + VH > gMaxY) gMaxY = v.sy + 2 * TH + VH;
    }

    var n = this.byBirth.length;
    this.pMinX = new Float32Array(n + 1); this.pMaxX = new Float32Array(n + 1);
    this.pMinY = new Float32Array(n + 1); this.pMaxY = new Float32Array(n + 1);
    this.pMinX[0] = gMinX; this.pMaxX[0] = gMaxX; this.pMinY[0] = gMinY; this.pMaxY[0] = gMaxY;
    for (i = 0; i < n; i++) {
      v = this.byBirth[i];
      this.pMinX[i + 1] = Math.min(this.pMinX[i], v.sx - TW);
      this.pMaxX[i + 1] = Math.max(this.pMaxX[i], v.sx + TW);
      this.pMinY[i + 1] = Math.min(this.pMinY[i], v.sy);
      this.pMaxY[i + 1] = Math.max(this.pMaxY[i], v.sy + 2 * TH + VH);
    }

    this.cam = opts.cam;
    this.shown = 0;
    this.scale = 0;
    this.max = n;
  }

  VoxelTree.prototype.count = function () { return this.shown; };
  VoxelTree.prototype.capacity = function () { return this.max; };

  /* Reveal exactly n voxels. Only the delta touches the DOM, so a 25 Hz
     frame is a handful of writes even when the tree is enormous. */
  VoxelTree.prototype.reveal = function (n) {
    n = n < 0 ? 0 : n > this.max ? this.max : n | 0;
    var i;
    if (n > this.shown) {
      for (i = this.shown; i < n; i++) this.byBirth[i].el.style.display = '';
    } else if (n < this.shown) {
      for (i = this.shown - 1; i >= n; i--) this.byBirth[i].el.style.display = 'none';
    } else return;
    this.shown = n;
  };

  /* The camera pulls back as the tree outgrows the frame. Without this
     "keeps growing forever" means "grows off the top of the screen". */
  VoxelTree.prototype.frame = function (dt) {
    var n = this.shown;
    var minX = this.pMinX[n], maxX = this.pMaxX[n];
    var minY = this.pMinY[n], maxY = this.pMaxY[n];

    var w = Math.max(maxX - minX, 120);
    var h = Math.max(maxY - minY, 130);
    /* the frame is the viewBox minus what the HUD covers: the bottom rail
       and panels own the last ~180 units, so the diorama sits above them */
    var target = Math.min(720 / w, 640 / h, 2.1);

    if (this.scale === 0) this.scale = target;
    else this.scale += (target - this.scale) * Math.min(1, dt / 0.9);   // ~1 s pull-back

    var s = this.scale;
    var cx = (minX + maxX) / 2;
    var tx = 500 - s * cx;
    var ty = 812 - s * maxY;
    this.cam.setAttribute('transform', 'translate(' + tx.toFixed(2) + ' ' + ty.toFixed(2) + ') scale(' + s.toFixed(4) + ')');
  };

  global.VoxelTree = VoxelTree;
})(window);
