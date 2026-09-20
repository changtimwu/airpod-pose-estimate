/* ============================================================
   mock.js — a fake arm at 25 Hz, speaking the real wire contract.
   Owner 03 · INTERFACE.

   Exists so the whole front end can be built, demoed and rehearsed on a
   Windows laptop with no AirPods, no Mac and no server running — and so a
   dead Bluetooth stack on stage costs us a screen, not the demo. It emits
   byte-identical `frame` and `event` payloads to §4 of the contract, so
   swapping it for /stream is a change of source, not a change of code.

   Drive it:  move the pointer   — Y is forearm pitch, X is roll
              hold SPACE         — snap into the pose and hold it
   ============================================================ */
(function (global) {
  'use strict';

  var HZ = 25;

  var LABELS = { tree: { en: 'Tree', sa: 'Vrksasana' } };

  /* Hypothesis only — Signal replaces these with measured values in
     poses.yaml. Arms overhead, palms together: the forearm is furthest
     from the calibration zero, which makes it the most separable pose
     on the arm we have. */
  var BAND = { pitch: [62, 90], roll: [-45, 45], exit: 8 };

  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }

  function Mock(onMessage) {
    this.onMessage = onMessage;
    this.t = 0;
    this.status = 'uncalibrated';
    this.calibT = 0;
    this.holdMs = 0;
    this.elapsed = 0;
    this.matched = false;
    this.pitch = -88; this.roll = 0; this.yaw = 0;
    this.tgtPitch = -88; this.tgtRoll = 0;
    this.assist = false;
    this.hist = [];
    this.score = 0;
    this.started = 0;

    var self = this;
    this._move = function (e) {
      var h = global.innerHeight || 800, w = global.innerWidth || 1200;
      self.tgtPitch = clamp(90 - (e.clientY / h) * 190, -92, 92);
      self.tgtRoll = clamp((e.clientX / w - 0.5) * 150, -80, 80);
    };
    this._down = function (e) { if (e.code === 'Space') { e.preventDefault(); self.assist = true; } };
    this._up = function (e) { if (e.code === 'Space') self.assist = false; };

    addEventListener('pointermove', this._move);
    addEventListener('keydown', this._down);
    addEventListener('keyup', this._up);

    this.timer = setInterval(function () { self.tick(); }, 1000 / HZ);
  }

  Mock.prototype.stop = function () {
    clearInterval(this.timer);
    removeEventListener('pointermove', this._move);
    removeEventListener('keydown', this._down);
    removeEventListener('keyup', this._up);
  };

  Mock.prototype.command = function (cmd) {
    if (cmd === 'calibrate') { this.status = 'calibrating'; this.calibT = 0; }
    else if (cmd === 'start' && (this.status === 'ready' || this.status === 'complete')) {
      this.status = 'active'; this.holdMs = 0; this.elapsed = 0; this.started = this.t;
      this.emit({ event: 'pose_entered', pose: 'tree' });
    }
    else if (cmd === 'skip') { this.status = 'ready'; this.holdMs = 0; }
    else if (cmd === 'reset') { this.status = 'ready'; this.holdMs = 0; this.elapsed = 0; this.score = 0; }
  };

  Mock.prototype.emit = function (o) {
    o.v = 1; o.type = 'event'; o.t = this.t;
    this.onMessage(o);
  };

  Mock.prototype.tick = function () {
    var dt = 1 / HZ;
    this.t += dt;

    /* assist snaps the arm into the middle of the band with a little life
       left in it — a perfectly still arm on screen reads as a frozen UI */
    var tp = this.assist ? 76 + Math.sin(this.t * 1.7) * 5 : this.tgtPitch;
    var tr = this.assist ? Math.sin(this.t * 1.1) * 11 : this.tgtRoll;

    var k = this.assist ? 0.24 : 0.2;
    this.pitch += (tp - this.pitch) * k + (Math.random() - 0.5) * 0.5;
    this.roll += (tr - this.roll) * k + (Math.random() - 0.5) * 0.7;
    this.yaw += (Math.random() - 0.5) * 0.4 + 0.02;   // drifts, as it does in life

    if (this.status === 'calibrating') {
      this.calibT += dt;
      if (this.calibT >= 2) {
        this.status = 'ready';
        this.emit({ event: 'calibrated' });
      }
    }

    /* hysteresis: enter on the band, leave only on the band plus margin */
    var m = this.matched ? BAND.exit : 0;
    var inBand = this.pitch >= BAND.pitch[0] - m && this.pitch <= BAND.pitch[1] + m &&
                 this.roll >= BAND.roll[0] - m && this.roll <= BAND.roll[1] + m;

    if (this.status === 'active') {
      if (inBand && !this.matched) this.emit({ event: 'pose_entered', pose: 'tree' });
      if (!inBand && this.matched) this.emit({ event: 'pose_lost', pose: 'tree', hold_ms: Math.round(this.holdMs) });
      this.matched = inBand;
      this.holdMs = inBand ? this.holdMs + dt * 1000 : 0;
      this.elapsed += dt * 1000;
    } else {
      this.matched = false;
      this.holdMs = 0;
    }

    /* steadiness = 1 − normalised variance over the last two seconds */
    this.hist.push(this.pitch);
    if (this.hist.length > HZ * 2) this.hist.shift();
    var mean = 0, i;
    for (i = 0; i < this.hist.length; i++) mean += this.hist[i];
    mean /= this.hist.length;
    var varr = 0;
    for (i = 0; i < this.hist.length; i++) varr += Math.pow(this.hist[i] - mean, 2);
    varr /= this.hist.length;
    this.score = clamp(1 - Math.sqrt(varr) / 12, 0, 1);

    var mid = (BAND.pitch[0] + BAND.pitch[1]) / 2;
    var err = Math.abs(this.pitch - mid);

    this.onMessage({
      v: 1, type: 'frame', t: this.t, wall: Date.now() / 1000,
      status: this.status,
      arm: {
        pitch: +this.pitch.toFixed(2), roll: +this.roll.toFixed(2), yaw: +this.yaw.toFixed(2),
        quality: 'good'
      },
      pose: {
        target: 'tree',
        detected: inBand ? 'tree' : null,
        match: inBand,
        confidence: +clamp(1 - err / 40, 0, 1).toFixed(3),
        error_deg: +err.toFixed(2),
        hold_ms: Math.round(this.holdMs),
        target_ms: 10000,
        band: BAND.pitch
      },
      session: {
        index: 0, total: 1, sequence: ['tree'],
        labels: LABELS,
        score: +this.score.toFixed(3),
        elapsed_ms: Math.round(this.elapsed)
      }
    });
  };

  global.Mock = Mock;
})(window);
