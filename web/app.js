/* ============================================================
   app.js — wire to screen.
   Owner 03 · INTERFACE.

   Transport is SSE, per Bridge's scaffold: frames arrive on /stream,
   commands go out as POST /command. EventSource reconnects on its own,
   which is most of the §10 requirement for free.

   This file writes data-* attributes and CSS custom properties and
   nothing else. It never sets a style, never picks a colour, never
   reads one. §8 of the contract, and the reason Owner 04 can restyle
   the whole thing at T+55 without opening this file.

   ── The one deviation from the contract, stated plainly ──
   `pose.hold_ms` resets to zero the moment you leave the band. The tree
   must not, or a single wobble razes forty seconds of work in front of
   the judges. So the tree runs off a locally integrated `held`, which
   gains at 1x while matched and drains at 0.25x while not. A three
   second stumble costs three quarters of a second of tree.
   `hold_ms` still drives the inner ring, exactly as specified.
   ============================================================ */
(function () {
  'use strict';

  var GAIN = 1.0;
  var DECAY = 0.25;          // wobble tax: a quarter of the rate you earned it at
  var VOX_PER_SEC = 5;       // steady build — one block every 200 ms
  var VOX_HEADSTART = 6;     // the first seconds need to show something

  /* open-ended on purpose: the brief is that it keeps growing */
  var STAGES = [
    { at: 0,  id: 'seed',    name: 'Seed' },
    { at: 3,  id: 'sprout',  name: 'Sprout' },
    { at: 9,  id: 'sapling', name: 'Sapling' },
    { at: 22, id: 'tree',    name: 'Tree' },
    { at: 40, id: 'canopy',  name: 'Canopy' },
    { at: 65, id: 'bloom',   name: 'Bloom' }
  ];
  var RING_SECS = 30;        // past full bloom, every 30 s held is one more tree ring

  var STATUS_COPY = {
    disconnected: ['Connection lost', 'Holding the last frame. Retrying every second.'],
    no_device:    ['No samples', 'Check the bud is banded and the AirPods are the audio output'],
    uncalibrated: ['Not zeroed', 'Stand in Mountain, arm hanging, then calibrate'],
    calibrating:  ['Reading your zero', 'Stand still. Arm down.'],
    ready:        ['Zeroed', 'Raise both arms overhead to begin growing'],
    active:       ['Growing', 'Hold the pose. The tree builds while you do.'],
    complete:     ['Session complete', 'Your tree stands.'],
    __wilting:    ['Wilting', 'Find the pose again — nothing you grew is lost']
  };

  var $ = function (id) { return document.getElementById(id); };
  var root = document.documentElement;
  var body = document.body;

  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function fmtTime(s) {
    if (s < 60) return s.toFixed(s < 10 ? 1 : 0);
    return Math.floor(s / 60) + ':' + ('0' + Math.floor(s % 60)).slice(-2);
  }

  /* ── view ─────────────────────────────────────────────────── */

  var tree = new VoxelTree({ mount: $('voxels'), cam: $('tree-cam'), seed: 20260920 });
  var dial = new PoseDial($('arm-dial'));

  var held = 0;          // accumulated growth time, seconds — the tree's clock
  var wilt = 0;          // 0 lit and green, 1 drained
  var bestStreak = 0;
  var frame = null;      // last frame received; we render this until a newer one lands
  var stageIdx = -1;
  var lastWilt = -1;
  var seeded = false;
  var calibFrom = 0;   // device-clock t when calibration started (§7, 2000 ms)

  function voxelsFor(t) {
    return Math.floor(VOX_PER_SEC * t + VOX_HEADSTART * (1 - Math.exp(-t / 0.8)));
  }

  function stageFor(t) {
    var i = 0;
    for (var k = 0; k < STAGES.length; k++) if (t >= STAGES[k].at) i = k;
    return i;
  }

  /* what the outer ring is filling toward: the next milestone, or — once
     the tree is in full bloom — the next tree ring. */
  function ringProgress(t) {
    var i = stageFor(t);
    if (i < STAGES.length - 1) {
      var a = STAGES[i].at, b = STAGES[i + 1].at;
      return { pct: (t - a) / (b - a), label: STAGES[i].name, id: STAGES[i].id, rings: 0 };
    }
    var over = t - STAGES[STAGES.length - 1].at;
    return { pct: (over % RING_SECS) / RING_SECS, label: 'Ancient', id: 'bloom',
             rings: Math.floor(over / RING_SECS) + 1 };
  }

  var rail = $('sequence-rail').children;
  function paintRail(i) {
    for (var k = 0; k < rail.length; k++) {
      rail[k].dataset.reached = String(k <= i);
      rail[k].dataset.current = String(k === i);
    }
  }

  var lastText = 0;
  function paintText(now, st) {
    if (now - lastText < 90) return;
    lastText = now;

    $('growth-pct').firstChild.nodeValue = fmtTime(held);
    $('stage-name').textContent = st.rings ? st.label + ' · ' + st.rings + ' rings' : st.label;
    $('voxel-value').textContent = tree.count();
    $('held-value').textContent = fmtTime(held) + 's';

    if (!frame) return;
    $('score-value').textContent = Math.round(frame.session.score * 100) + '%';
    $('streak-value').textContent = (bestStreak / 1000).toFixed(1) + 's';
  }

  /* ── the loop ─────────────────────────────────────────────── */

  var last = 0;
  function loop(now) {
    requestAnimationFrame(loop);
    var dt = last ? Math.min(0.1, (now - last) / 1000) : 0;
    last = now;

    var matched = !!(frame && frame.pose && frame.pose.match);
    var live = frame && frame.status === 'active';

    if (live) held = Math.max(0, held + dt * (matched ? GAIN : -DECAY));

    /* only a live, unmatched hold drains the tree. Idling on the ready or
       complete screen must not make a healthy tree look sick. */
    var wTarget = (live && !matched) ? 1 : 0;
    wilt += (wTarget - wilt) * Math.min(1, dt / (wTarget > wilt ? 0.9 : 0.3));

    tree.reveal(voxelsFor(held));
    tree.frame(dt);

    var st = ringProgress(held);
    var idx = stageFor(held);
    if (idx !== stageIdx) { stageIdx = idx; paintRail(idx); body.dataset.stage = st.id; }

    /* --wilt drives a group filter, which is the one expensive thing on
       screen. Write it in coarse steps and let the CSS transition smooth
       the rest, so the filter re-renders a few times a second, not 25. */
    var w2 = Math.round(wilt * 20) / 20;
    if (w2 !== lastWilt) { lastWilt = w2; root.style.setProperty('--wilt', w2); }

    root.style.setProperty('--growth', (1 - Math.exp(-held / 28)).toFixed(3));
    root.style.setProperty('--hold-pct', clamp(st.pct, 0, 1).toFixed(4));

    paintText(now, st);
  }

  /* ── frames in ────────────────────────────────────────────── */

  function onFrame(f) {
    frame = f;

    body.dataset.status = f.status;
    body.dataset.pose = f.pose.target;
    body.dataset.match = String(!!f.pose.match);
    body.dataset.quality = f.arm.quality;

    root.style.setProperty('--arm-pitch', f.arm.pitch + 'deg');
    root.style.setProperty('--arm-roll', f.arm.roll + 'deg');
    root.style.setProperty('--streak-pct',
      f.pose.target_ms ? clamp(f.pose.hold_ms / f.pose.target_ms, 0, 1).toFixed(4) : 0);
    root.style.setProperty('--error-norm', clamp(f.pose.error_deg / 45, 0, 1).toFixed(3));

    dial.update(f.arm.pitch, f.arm.roll);
    if (f.pose.band) dial.setBand(f.pose.band);

    if (f.pose.hold_ms > bestStreak) bestStreak = f.pose.hold_ms;
    if (f.status === 'ready' || f.status === 'uncalibrated') { held = 0; bestStreak = 0; seeded = false; }

    /* ?held=90 drops the tree straight to ninety seconds of growth. For
       grabbing stills of a mature tree for the deck without standing in
       the pose for two minutes, and for eyeballing the camera at size. */
    if (!seeded && f.status === 'active') {
      seeded = true;
      var seek = /[?&]held=(\d+)/.exec(location.search);
      if (seek) held = Math.min(600, parseInt(seek[1], 10));
    }

    var labels = (f.session.labels || {})[f.pose.target];
    if (labels) {
      $('pose-name').textContent = labels.en || f.pose.target;
      $('pose-sanskrit').textContent = labels.sa || '';
    }

    /* `active` covers both holding and having just lost it. The status enum
       is frozen, so the distinction lives in the copy, not a new value. */
    var copy = STATUS_COPY[f.status] || [f.status, ''];
    if (f.status === 'active' && !f.pose.match) copy = STATUS_COPY.__wilting;
    $('status-text').textContent = copy[0];
    $('status-sub').textContent = copy[1];

    if (f.status === 'calibrating') {
      if (calibFrom === 0) calibFrom = f.t;
      $('calib-count').textContent = Math.max(0, 2 - (f.t - calibFrom)).toFixed(1);
    } else calibFrom = 0;
    if (f.status === 'complete') {
      $('final-held').textContent = fmtTime(held) + 's';
      $('final-score').textContent = Math.round(f.session.score * 100) + '%';
      $('final-voxels').textContent = tree.count();
    }
  }

  /* §4 events are one-shot triggers. The next frame corrects anything we
     miss, so nothing in here is allowed to hold state. */
  function onEvent(e) {
    if (e.event === 'calibrated') $('calib-count').textContent = '0.0';
    else if (e.event === 'device_lost') body.dataset.quality = 'stale';
    else if (e.event === 'device_found') body.dataset.quality = 'good';
  }

  /* ── transport ────────────────────────────────────────────── */

  var mock = null;
  var everLive = false;

  function goMock(reason) {
    if (mock) return;
    body.dataset.source = 'mock';
    $('sourcebadge').textContent = 'mock · ' + reason + ' · move the pointer, hold space';
    mock = new Mock(function (msg) {
      if (msg.type === 'frame') onFrame(msg); else onEvent(msg);
    });
  }

  function connect() {
    /* ?mock=1 forces the fake arm even when Bridge is up. This is the
       rehearsal path and the on-stage fallback, so it has to work while
       the real server is running, not only when it is dead. */
    if (/[?&]mock=1/.test(location.search)) { goMock('forced'); return; }

    var es;
    try { es = new EventSource('/stream'); }
    catch (err) { goMock('no server'); return; }

    var probe = setTimeout(function () { goMock('no server'); }, 1800);

    es.onmessage = function (ev) {
      var msg;
      try { msg = JSON.parse(ev.data); } catch (err) { return; }
      clearTimeout(probe);
      if (mock) { mock.stop(); mock = null; }
      everLive = true;
      body.dataset.source = 'live';
      if (msg.type === 'frame') onFrame(msg);
      else if (msg.type === 'event') onEvent(msg);
    };

    /* §10: never blank the UI. Dim it, say so, let EventSource retry. */
    es.onerror = function () {
      if (everLive) body.dataset.status = 'disconnected';
      else { clearTimeout(probe); goMock('no server'); }
    };
  }

  /* ── commands out ─────────────────────────────────────────── */

  function send(cmd) {
    if (mock) { mock.command(cmd); return; }
    fetch('/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ v: 1, type: 'command', cmd: cmd })
    })["catch"](function () {});
  }

  $('btn-calibrate').onclick = function () { send('calibrate'); };
  $('btn-start').onclick = function () { send('start'); };
  $('btn-skip').onclick = function () { send('skip'); };

  var cards = document.querySelectorAll('[data-cmd]');
  for (var i = 0; i < cards.length; i++) {
    cards[i].addEventListener('click', function () { send(this.dataset.cmd); });
  }

  addEventListener('keydown', function (e) {
    if (e.target.tagName === 'INPUT') return;
    var k = e.key.toLowerCase();
    if (k === 'c') send('calibrate');
    else if (k === 's') send('start');
    else if (k === 'k') send('skip');       // the escape hatch. Bound first, on purpose.
    else if (k === 'r') send('reset');
  });

  requestAnimationFrame(loop);
  connect();
})();
