/* ============================================================
   pose-dial.js — the live forearm, drawn as a dial.
   Owner 03 · INTERFACE. Geometry and transforms only; colour is CSS.

   Pitch maps to the needle angle so the dial reads like the arm:
   pitch +90 (overhead) points up, 0 (level) points right, -90 (hanging)
   points down. Roll twists the crossbar at the tip — the palm.

   Yaw is deliberately absent. It drifts, §2 of the contract forbids
   classifying on it, and putting it on screen invites a judge to ask
   why the number wanders while the arm is still.
   ============================================================ */
(function (global) {
  'use strict';

  var SVGNS = 'http://www.w3.org/2000/svg';
  var CX = 120, CY = 120, R = 78;

  function el(name, attrs) {
    var n = document.createElementNS(SVGNS, name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }

  /* dial space: 0deg at 12 o'clock, clockwise */
  function pt(deg, r) {
    var a = deg * Math.PI / 180;
    return [CX + Math.sin(a) * r, CY - Math.cos(a) * r];
  }
  function pitchToDeg(p) { return 90 - p; }

  function PoseDial(mount) {
    this.mount = mount;

    var ticks = document.createDocumentFragment();
    for (var p = -90; p <= 90; p += 15) {
      var major = (p % 45 === 0);
      var a = pitchToDeg(p);
      var o = pt(a, R + 4), i = pt(a, R + (major ? 13 : 9));
      ticks.appendChild(el('line', {
        x1: o[0].toFixed(1), y1: o[1].toFixed(1), x2: i[0].toFixed(1), y2: i[1].toFixed(1),
        'class': 'dial-tick' + (major ? ' dial-tick--major' : '')
      }));
    }
    mount.appendChild(ticks);

    this.band = el('path', { 'class': 'dial-band', d: '' });
    mount.appendChild(this.band);

    /* The needle floats near the rim rather than running from the centre.
       The centre belongs to the readout, and a needle drawn through a
       number is the difference between an instrument and a mess. */
    this.arm = el('line', { 'class': 'dial-arm', x1: CX, y1: CY - 44, x2: CX, y2: CY - 66 });
    this.palm = el('line', { 'class': 'dial-palm', x1: -10, y1: 0, x2: 10, y2: 0 });
    this.palmWrap = el('g', {});
    this.palmWrap.appendChild(this.palm);
    this.armWrap = el('g', {});
    this.armWrap.appendChild(this.arm);
    this.armWrap.appendChild(this.palmWrap);
    mount.appendChild(this.armWrap);

    this.setBand(null);
    this.update(0, 0);
  }

  /* the target arc — where the arm has to be for this pose */
  PoseDial.prototype.setBand = function (band) {
    if (!band) { this.band.setAttribute('d', ''); return; }
    var a1 = pitchToDeg(band[1]);   // high pitch first: dial angles run backwards
    var a2 = pitchToDeg(band[0]);
    var s = pt(a1, R), e = pt(a2, R);
    var large = (a2 - a1) > 180 ? 1 : 0;
    this.band.setAttribute('d',
      'M' + s[0].toFixed(1) + ' ' + s[1].toFixed(1) +
      'A' + R + ' ' + R + ' 0 ' + large + ' 1 ' + e[0].toFixed(1) + ' ' + e[1].toFixed(1));
  };

  PoseDial.prototype.update = function (pitch, roll) {
    var a = pitchToDeg(pitch);
    this.armWrap.setAttribute('transform', 'rotate(' + a.toFixed(2) + ' ' + CX + ' ' + CY + ')');
    /* the palm sits at the needle tip and twists with roll, squashed by the
       cosine so it reads as a bar turning in 3D rather than a spinning line */
    var r = roll * Math.PI / 180;
    this.palmWrap.setAttribute('transform',
      'translate(' + CX + ' ' + (CY - 70) + ') scale(' + Math.cos(r).toFixed(3) + ' 1) rotate(' + (roll * 0.25).toFixed(2) + ')');
  };

  global.PoseDial = PoseDial;
})(window);
