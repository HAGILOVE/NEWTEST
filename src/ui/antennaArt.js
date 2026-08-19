/**
 * Scale drawings of each antenna archetype.
 *
 * Every drawing is generated from the dimensions the model synthesised, so the
 * picture is the design rather than an illustration of one: change the
 * frequency or the substrate and the geometry redraws to the new numbers.
 * Views are chosen per family - plan view where the layout is planar, side or
 * isometric where the third dimension is what defines the antenna.
 */
import { el, h } from './charts.js';

const W = 620, H = 370;
const T = {
  cu: 'var(--cu)', sub: 'var(--sub)', sub2: 'var(--sub2)', air: 'var(--air)',
  metal: 'var(--connector)', line: 'var(--diagram-stroke)',
};

/* ------------------------------------------------------------- primitives */

const rect = (g, x, y, w, hh, fill, extra = {}) =>
  el('rect', { x, y, width: Math.max(w, 0.5), height: Math.max(hh, 0.5), fill, stroke: T.line, 'stroke-width': 0.8, ...extra }, g);

const lbl = (g, x, y, text, anchor = 'start', cls = 'diagram-label') =>
  Object.assign(el('text', { x, y, class: cls, 'text-anchor': anchor }, g), { textContent: text });

const dimLine = (g, x1, y1, x2, y2, text, vertical = false) => {
  el('line', { x1, y1, x2, y2, class: 'dim-line' }, g);
  const tick = vertical ? { dx: 4, dy: 0 } : { dx: 0, dy: 4 };
  for (const [px, py] of [[x1, y1], [x2, y2]]) {
    el('line', { x1: px - tick.dx, x2: px + tick.dx, y1: py - tick.dy, y2: py + tick.dy, class: 'dim-line' }, g);
  }
  if (!text) return;
  const t = el('text', { class: 'diagram-dim', 'text-anchor': 'middle' }, g);
  if (vertical) t.setAttribute('transform', `translate(${x1 - 7},${(y1 + y2) / 2}) rotate(-90)`);
  else { t.setAttribute('x', (x1 + x2) / 2); t.setAttribute('y', y1 - 6); }
  t.textContent = text;
};

/** SMA / coax connector glyph. */
const coax = (g, x, y, dir = 'down') => {
  if (dir === 'down') {
    rect(g, x - 9, y, 18, 20, T.metal);
    el('line', { x1: x, y1: y - 8, x2: x, y2: y, stroke: T.cu, 'stroke-width': 3 }, g);
  } else {
    rect(g, x, y - 9, 20, 18, T.metal);
    el('line', { x1: x - 8, y1: y, x2: x, y2: y, stroke: T.cu, 'stroke-width': 3 }, g);
  }
};

/** Hatched ground plane edge-on. */
const groundBar = (g, x, y, w, thickness = 5) => {
  rect(g, x, y, w, thickness, T.cu);
  for (let i = 0; i < w; i += 9) {
    el('line', { x1: x + i, y1: y + thickness, x2: x + i - 6, y2: y + thickness + 7, stroke: T.line, 'stroke-width': 0.7 }, g);
  }
};

/** Fit a real-world extent (mm) into a pixel box. */
const fit = (mmW, mmH, boxW, boxH) => Math.min(boxW / Math.max(mmW, 1e-6), boxH / Math.max(mmH, 1e-6));

const num = (v, d = 1) => (Number.isFinite(v) ? v.toFixed(d) : '-');

/* ------------------------------------------------------------- drawings */
/* Each takes (g, ctx) where ctx = { dims, size, lambdaMm, count, arch, patch } */

function drawPatchFamily(g, ctx, variant) {
  const wMm = ctx.dims['Patch W'] ?? ctx.dims['Driven W'] ?? ctx.size.w;
  const lMm = ctx.dims['Patch L'] ?? ctx.dims['Driven L'] ?? ctx.size.l;
  const gndMm = ctx.groundMm || (Math.max(wMm, lMm) + ctx.lambdaMm * 0.5);

  // --- plan view (left) ---
  const s = fit(gndMm, gndMm, 210, 210);
  const gx = 26, gy = 58, gw = gndMm * s;
  rect(g, gx, gy, gw, gw, T.sub);
  const pw = wMm * s, pl = lMm * s;
  const px = gx + (gw - pw) / 2, py = gy + (gw - pl) / 2;
  rect(g, px, py, pw, pl, T.cu);
  if (variant === 'stacked') {
    el('rect', { x: px - 4, y: py - 4, width: pw + 8, height: pl + 8, fill: 'none',
      stroke: T.cu, 'stroke-width': 1.4, 'stroke-dasharray': '4 3' }, g);
    lbl(g, gx + gw / 2, gy - 8, 'dashed = parasitic patch above', 'middle');
  }
  if (variant === 'aperture') {
    rect(g, px + pw / 2 - pw * 0.2, py + pl / 2 - 2, pw * 0.4, 4, T.sub2);
    lbl(g, px + pw / 2 + pw * 0.22, py + pl / 2 + 3, 'coupling slot in the ground');
  } else {
    const fw = Math.max(pw * 0.09, 3);
    rect(g, px + pw / 2 - fw / 2, py + pl, fw, gy + gw - (py + pl), T.cu);
    const inset = (ctx.dims['Inset depth'] ?? lMm * 0.25) * s;
    rect(g, px + pw / 2 - fw / 2 - 4, py + pl - inset, 4, inset, T.sub);
    rect(g, px + pw / 2 + fw / 2, py + pl - inset, 4, inset, T.sub);
  }
  dimLine(g, px, py - 12, px + pw, py - 12, `W ${num(wMm, 2)} mm`);
  dimLine(g, px - 12, py, px - 12, py + pl, `L ${num(lMm, 2)} mm`, true);
  lbl(g, gx, gy + gw + 18, `ground ${num(gndMm, 0)} mm — plan view`, 'start', 'diagram-dim');

  // --- stack cross-section (right) ---
  const sx = 292, sw = 234, baseY = 210;
  const hMm = ctx.dims['Total h'] ?? ctx.dims['Substrate h'] ?? ctx.dims['Layer gap'] ?? ctx.size.h;
  groundBar(g, sx, baseY, sw);
  const stackPx = 46;
  if (variant === 'air') {
    const gapMm = ctx.dims['Air gap'] ?? hMm * 0.85;
    const carrierMm = ctx.dims['Carrier'] ?? Math.max(hMm - gapMm, 0.2);
    const gapPx = stackPx * (gapMm / hMm), carPx = Math.max(stackPx * (carrierMm / hMm), 5);
    rect(g, sx, baseY - gapPx, sw, gapPx, T.air);
    rect(g, sx + 10, baseY - gapPx - carPx, sw - 20, carPx, T.sub2);
    rect(g, sx + 46, baseY - gapPx - carPx - 5, sw - 92, 5, T.cu);
    for (const spx of [sx + 16, sx + sw - 24]) rect(g, spx, baseY - gapPx, 8, gapPx, 'var(--spacer)');
    lbl(g, sx + sw + 4, baseY - gapPx / 2, '', 'start');
    lbl(g, sx, baseY - gapPx - carPx - 16, `air gap ${num(gapMm, 2)} mm + ${num(carrierMm, 2)} mm carrier`);
    dimLine(g, sx - 12, baseY - gapPx - carPx - 5, sx - 12, baseY, `h ${num(hMm, 2)} mm`, true);
  } else if (variant === 'stacked') {
    rect(g, sx, baseY - stackPx * 0.45, sw, stackPx * 0.45, T.sub);
    rect(g, sx + 46, baseY - stackPx * 0.45 - 5, sw - 92, 5, T.cu);
    rect(g, sx, baseY - stackPx - 5, sw, stackPx * 0.5, T.sub2);
    rect(g, sx + 38, baseY - stackPx - 10, sw - 76, 5, T.cu);
    lbl(g, sx, baseY - stackPx - 20, 'parasitic patch on the upper layer');
    lbl(g, sx, baseY - stackPx * 0.45 - 14, 'driven patch');
  } else if (variant === 'aperture') {
    rect(g, sx, baseY - stackPx * 0.4, sw, stackPx * 0.4, T.sub);
    rect(g, sx, baseY - stackPx * 0.4 - 5, sw, 5, T.cu);
    rect(g, sx + sw / 2 - 14, baseY - stackPx * 0.4 - 5, 28, 5, T.sub);   // slot
    rect(g, sx, baseY - stackPx - 5, sw, stackPx * 0.5, T.sub2);
    rect(g, sx + 46, baseY - stackPx - 10, sw - 92, 5, T.cu);
    rect(g, sx + sw / 2 - 3, baseY, 6, 5, T.cu);
    lbl(g, sx, baseY - stackPx - 20, 'patch layer');
    lbl(g, sx, baseY + 26, 'feed line under the ground — slot couples through');
  } else {
    rect(g, sx, baseY - stackPx, sw, stackPx, T.sub);
    rect(g, sx + 46, baseY - stackPx - 5, sw - 92, 5, T.cu);
    dimLine(g, sx - 12, baseY - stackPx - 5, sx - 12, baseY, `h ${num(hMm, 2)} mm`, true);
  }
  coax(g, sx + sw - 34, baseY + 5);
  lbl(g, sx, 46, 'cross-section (vertical scale exaggerated)', 'start', 'diagram-dim');
}

function drawPlanarArray(g, ctx, steer) {
  const n = ctx.count || 4;
  const cols = Math.ceil(Math.sqrt(n)), rows = Math.ceil(n / cols);
  const pitch = ctx.dims.Spacing ?? ctx.dims.Pitch ?? ctx.lambdaMm * 0.7;
  const ew = ctx.patch ? ctx.patch.W * 1e3 : pitch * 0.45;
  const eh = ctx.patch ? ctx.patch.L * 1e3 : pitch * 0.35;
  const totW = cols * pitch, totH = rows * pitch;
  const s = fit(totW, totH, 250, 220);
  const ox = 28, oy = 62;
  rect(g, ox, oy, totW * s, totH * s, T.sub);
  const drawn = [];
  for (let i = 0, k = 0; i < rows; i++) {
    for (let j = 0; j < cols && k < n; j++, k++) {
      const cx = ox + (j + 0.5) * pitch * s, cy = oy + (i + 0.5) * pitch * s;
      rect(g, cx - (ew * s) / 2, cy - (eh * s) / 2, ew * s, eh * s, T.cu, { rx: 1 });
      drawn.push([cx, cy]);
    }
  }
  // corporate feed tree, or beamformer taps
  if (!steer && drawn.length > 1) {
    const spine = oy + totH * s + 12;
    for (const [cx, cy] of drawn) el('line', { x1: cx, y1: cy + (eh * s) / 2, x2: cx, y2: spine, stroke: T.cu, 'stroke-width': 1.4 }, g);
    el('line', { x1: drawn[0][0], y1: spine, x2: drawn[drawn.length - 1][0], y2: spine, stroke: T.cu, 'stroke-width': 1.6 }, g);
    coax(g, (drawn[0][0] + drawn[drawn.length - 1][0]) / 2, spine);
    lbl(g, ox, spine + 30, 'corporate feed network', 'start');
  } else {
    for (let i = 0; i < Math.min(drawn.length, 16); i += 4) {
      rect(g, drawn[i][0] - 6, oy + totH * s + 12, 30, 12, T.metal, { rx: 2 });
    }
    lbl(g, ox, oy + totH * s + 40, `${Math.ceil(n / 4)} × 4-channel beamformer ICs`, 'start');
  }
  dimLine(g, ox, oy - 12, ox + pitch * s, oy - 12, `pitch ${num(pitch, 1)} mm`);
  lbl(g, ox, oy + totH * s + 76, `${cols} × ${rows} = ${n} elements, panel ${num(totW, 0)} × ${num(totH, 0)} mm`, 'start', 'diagram-dim');

  // beam sketch on the right
  const bx = 400, by = 150;
  el('line', { x1: 310, y1: by + 74, x2: 520, y2: by + 74, stroke: T.line, 'stroke-width': 1 }, g);
  const scan = steer ? 32 : 0;
  for (const a of [-1, 0, 1]) {
    const ang = (scan + a * 12) * Math.PI / 180;
    el('line', { x1: bx, y1: by + 74, x2: bx + 96 * Math.sin(ang), y2: by + 74 - 96 * Math.cos(ang),
      stroke: 'var(--series-1)', 'stroke-width': a === 0 ? 2.4 : 1, opacity: a === 0 ? 1 : 0.45 }, g);
  }
  lbl(g, bx, by + 96, steer ? `beam steered ${scan}° — ±60° scan range` : 'fixed broadside beam', 'middle');
}

function drawSeriesArray(g, ctx) {
  const n = ctx.count || 6;
  const pitch = ctx.dims['Element pitch'] ?? ctx.lambdaMm * 0.85;
  const ew = ctx.patch ? ctx.patch.W * 1e3 : pitch * 0.5;
  const eh = ctx.patch ? ctx.patch.L * 1e3 : pitch * 0.3;
  const totH = n * pitch;
  const s = fit(ew * 2.6, totH, 150, 230);
  const cx = 120, oy = 52;
  rect(g, cx - (ew * 1.3 * s), oy, ew * 2.6 * s, totH * s, T.sub);
  for (let i = 0; i < n; i++) {
    const cy = oy + (i + 0.5) * pitch * s;
    rect(g, cx - (ew * s) / 2, cy - (eh * s) / 2, ew * s, eh * s, T.cu, { rx: 1 });
    if (i < n - 1) el('line', { x1: cx, y1: cy + (eh * s) / 2, x2: cx, y2: cy + pitch * s - (eh * s) / 2, stroke: T.cu, 'stroke-width': 2 }, g);
  }
  coax(g, cx, oy + totH * s + 2);
  dimLine(g, cx + ew * 1.3 * s + 14, oy, cx + ew * 1.3 * s + 14, oy + pitch * s, `${num(pitch, 1)} mm`, true);
  lbl(g, 250, 90, `${n} patches strung along one line.`);
  lbl(g, 250, 108, 'Minimal feed copper — the reason it beats a');
  lbl(g, 250, 124, 'corporate feed on a lossy laminate.');
  lbl(g, 250, 150, 'The trade: the beam squints with frequency,');
  lbl(g, 250, 166, 'because the inter-element phase is set by the');
  lbl(g, 250, 182, 'line length rather than by a splitter.');
  lbl(g, 250, 210, `Column ${num(ew * 1.6, 0)} × ${num(totH, 0)} mm`, 'start', 'diagram-dim');
}

function drawSiwSlotArray(g, ctx) {
  const a = ctx.dims['SIW width a'] ?? ctx.lambdaMm * 0.35;
  const pitch = ctx.dims['Via pitch'] ?? a * 0.25;
  const n = Math.min(ctx.count || 8, 32);
  const cols = Math.ceil(Math.sqrt(n)), rows = Math.ceil(n / cols);
  const s = fit(cols * a * 1.1, rows * a * 1.2, 260, 210);
  const ox = 30, oy = 62;
  rect(g, ox, oy, cols * a * 1.1 * s, rows * a * 1.2 * s, T.sub);
  for (let c = 0; c <= cols; c++) {
    const x = ox + c * a * 1.1 * s;
    for (let y = oy; y < oy + rows * a * 1.2 * s; y += Math.max(pitch * s, 5)) {
      el('circle', { cx: x, cy: y, r: 2, fill: T.cu }, g);
    }
  }
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const cx = ox + (c + 0.5) * a * 1.1 * s, cy = oy + (r + 0.5) * a * 1.2 * s;
      rect(g, cx - a * 0.22 * s, cy - 2.5, a * 0.44 * s, 5, T.sub2, { transform: `rotate(${r % 2 ? 14 : -14} ${cx} ${cy})` });
    }
  }
  lbl(g, ox, oy + rows * a * 1.2 * s + 20, `${n} slots cut in the SIW broad wall`, 'start', 'diagram-dim');
  lbl(g, 320, 86, `Via fences (pitch ${num(pitch, 2)} mm) form the`);
  lbl(g, 320, 102, `waveguide walls; broad wall a = ${num(a, 2)} mm`);
  lbl(g, 320, 118, 'sets the TE10 cutoff.');
  lbl(g, 320, 146, 'Slots alternate tilt so their radiation adds');
  lbl(g, 320, 162, 'in phase along the guide.');
  lbl(g, 320, 190, 'No microstrip feed network — this is how');
  lbl(g, 320, 206, 'mmWave arrays escape feed loss.');
}

function drawDRA(g, ctx) {
  const w = ctx.dims['DR width'] ?? 12, hh = ctx.dims['DR height'] ?? 8;
  const s = fit(w * 2.4, hh * 3, 200, 150);
  const cx = 150, baseY = 220;
  groundBar(g, cx - w * 1.6 * s, baseY, w * 3.2 * s);
  const bw = w * s, bh = hh * s, d = bw * 0.34;
  // isometric block
  const x0 = cx - bw / 2, y0 = baseY - bh;
  rect(g, x0, y0, bw, bh, T.sub2);
  el('path', { d: `M${x0},${y0} l${d},${-d * 0.55} h${bw} l${-d},${d * 0.55}Z`, fill: T.sub, stroke: T.line, 'stroke-width': 0.8 }, g);
  el('path', { d: `M${x0 + bw},${y0} l${d},${-d * 0.55} v${bh} l${-d},${d * 0.55}Z`, fill: T.air, stroke: T.line, 'stroke-width': 0.8 }, g);
  rect(g, x0 - 8, baseY - 3, 8, 3, T.cu);
  lbl(g, x0 - 30, baseY + 30, 'probe or slot feed', 'middle');
  dimLine(g, x0, y0 - 16, x0 + bw, y0 - 16, `${num(w, 1)} mm`);
  dimLine(g, x0 - 14, y0, x0 - 14, baseY, `${num(hh, 1)} mm`, true);
  lbl(g, 320, 90, `Ceramic block, εr ≈ ${num(ctx.dims['eps_r (DR)'] ?? 10, 0)}, resonating`);
  lbl(g, 320, 106, 'in the HEM11δ mode.');
  lbl(g, 320, 134, 'No conductor on the radiator at all, so');
  lbl(g, 320, 150, 'there is no conductor loss to speak of —');
  lbl(g, 320, 166, 'the reason DRAs win above ~30 GHz.');
  lbl(g, 320, 194, 'Production risk is the bond line: glue');
  lbl(g, 320, 210, 'thickness sets the resonance.');
}

function drawMonopole(g, ctx) {
  const len = ctx.dims['Element length'] ?? ctx.lambdaMm * 0.238;
  const gr = ctx.dims['Ground radius'] ?? ctx.lambdaMm * 0.25;
  const s = fit(gr * 2.4, len * 1.5, 240, 190);
  const cx = 170, baseY = 240;
  groundBar(g, cx - gr * s, baseY, gr * 2 * s);
  el('line', { x1: cx, y1: baseY, x2: cx, y2: baseY - len * s, stroke: T.cu, 'stroke-width': 4, 'stroke-linecap': 'round' }, g);
  coax(g, cx, baseY + 5);
  dimLine(g, cx + 34, baseY - len * s, cx + 34, baseY, `λ/4 = ${num(len, 1)} mm`, true);
  dimLine(g, cx, baseY + 52, cx + gr * s, baseY + 52, `ground radius ${num(gr, 0)} mm`);
  lbl(g, 330, 96, 'The ground plane is the other half of the');
  lbl(g, 330, 112, 'antenna — the image of the rod completes');
  lbl(g, 330, 128, 'the dipole.');
  lbl(g, 330, 156, `At ${num(gr / ctx.lambdaMm, 2)} λ radius the pattern peak tilts`);
  lbl(g, 330, 172, 'up off the horizon and gain drops.');
  lbl(g, 330, 200, 'A null points straight up: never use it');
  lbl(g, 330, 216, 'where the link can pass overhead.');
}

function drawDipole(g, ctx) {
  const total = ctx.dims['Total length'] ?? ctx.lambdaMm * 0.47;
  const s = fit(total * 1.35, 60, 300, 90);
  const cx = 175, cy = 130, halfPx = (total * s) / 2;
  el('line', { x1: cx - halfPx, y1: cy, x2: cx - 5, y2: cy, stroke: T.cu, 'stroke-width': 6, 'stroke-linecap': 'round' }, g);
  el('line', { x1: cx + 5, y1: cy, x2: cx + halfPx, y2: cy, stroke: T.cu, 'stroke-width': 6, 'stroke-linecap': 'round' }, g);
  el('path', { d: `M${cx - 5},${cy} q0,26 -18,34 M${cx + 5},${cy} q0,26 18,34`, fill: 'none', stroke: T.cu, 'stroke-width': 2 }, g);
  rect(g, cx - 26, cy + 60, 52, 22, T.metal, { rx: 3 });
  lbl(g, cx, cy + 74, 'balun', 'middle');
  coax(g, cx, cy + 82);
  dimLine(g, cx - halfPx, cy - 20, cx + halfPx, cy - 20, `${num(total, 1)} mm  (λ/2)`);
  dimLine(g, cx - halfPx, cy + 22, cx - 5, cy + 22, `arm ${num(total / 2, 1)} mm`);
  lbl(g, 30, 250, 'Fed without a balun, current flows on the outside of the coax shield:');
  lbl(g, 30, 266, 'the cable becomes part of the antenna and the pattern is no longer');
  lbl(g, 30, 282, 'the one you designed. The balun is not optional.');
}

function drawPIFA(g, ctx) {
  const pw = ctx.dims['Plate W'] ?? 20, pl = ctx.dims['Plate L'] ?? 16, ph = ctx.dims['Height'] ?? 5;
  const sw = ctx.dims['Short width'] ?? pw * 0.25;
  const s = fit(pw * 2.0, (pl + ph * 2) * 1.6, 210, 190);
  const ox = 60, baseY = 235, d = 30;
  groundBar(g, ox - 16, baseY, pw * s + 60);
  const plateY = baseY - ph * s * 3;
  el('path', { d: `M${ox},${plateY} l${d},${-d * 0.5} h${pw * s} l${-d},${d * 0.5}Z`, fill: T.cu, stroke: T.line, 'stroke-width': 0.8 }, g);
  rect(g, ox, plateY, sw * s, baseY - plateY, T.cu);       // shorting wall
  el('line', { x1: ox + sw * s + 12, y1: plateY, x2: ox + sw * s + 12, y2: baseY, stroke: T.cu, 'stroke-width': 3 }, g);
  coax(g, ox + sw * s + 12, baseY + 5);
  lbl(g, ox + sw * s / 2, plateY - 34, 'shorting wall', 'middle');
  lbl(g, ox + sw * s + 20, plateY + (baseY - plateY) / 2, 'feed pin', 'start');
  dimLine(g, ox, plateY - 12, ox + pw * s, plateY - 12, `${num(pw, 1)} mm`);
  dimLine(g, ox - 14, plateY, ox - 14, baseY, `h ${num(ph, 1)} mm`, true);
  lbl(g, 330, 100, 'A patch shorted along one edge resonates at');
  lbl(g, 330, 116, 'a quarter wave, not a half — half the footprint.');
  lbl(g, 330, 144, 'The chassis is part of the antenna. Ground');
  lbl(g, 330, 160, 'plane length usually sets the low-band');
  lbl(g, 330, 176, 'bandwidth, not the PIFA itself.');
  lbl(g, 330, 204, 'Slots in the plate add a second band.');
}

function drawIFA(g, ctx) {
  const kw = ctx.dims['Keep-out W'] ?? 18, kh = ctx.dims['Keep-out H'] ?? 6;
  const s = fit(kw * 1.5, kh * 4, 230, 130);
  const ox = 40, oy = 90;
  rect(g, ox - 20, oy - 22, kw * 1.5 * s + 40, kh * 5 * s + 60, T.sub);
  rect(g, ox - 20, oy + kh * s * 2.4, kw * 1.5 * s + 40, kh * 5 * s + 60 - (kh * s * 2.4 + 22), T.cu);
  lbl(g, ox - 14, oy + kh * s * 2.4 + 20, 'PCB ground plane', 'start');
  // meandered trace inside the keep-out
  const segs = 5, segW = (kw * s) / segs, top = oy, bot = oy + kh * s * 1.8;
  let d2 = `M${ox},${bot}`;
  for (let i = 0; i < segs; i++) {
    d2 += ` V${i % 2 ? bot : top} H${ox + (i + 1) * segW}`;
  }
  el('path', { d: d2, fill: 'none', stroke: T.cu, 'stroke-width': 3, 'stroke-linejoin': 'miter' }, g);
  el('line', { x1: ox, y1: bot, x2: ox, y2: oy + kh * s * 2.4, stroke: T.cu, 'stroke-width': 3 }, g);
  dimLine(g, ox, oy - 14, ox + kw * s, oy - 14, `keep-out ${num(kw, 1)} × ${num(kh, 1)} mm`);
  lbl(g, 320, 96, `Trace length ${num(ctx.dims['Trace length'] ?? 0, 1)} mm ≈ λ/4, meandered`);
  lbl(g, 320, 112, 'to fit the board edge.');
  lbl(g, 320, 140, 'Ground copper must be cleared under the');
  lbl(g, 320, 156, 'whole element, and nothing metal — battery,');
  lbl(g, 320, 172, 'shield can, display — within ~0.1 λ.');
  lbl(g, 320, 200, 'Zero BOM cost; efficiency is decided by the');
  lbl(g, 320, 216, 'layout, not by the antenna.');
}

function drawCollinear(g, ctx) {
  const n = ctx.dims.Sections ?? ctx.count ?? 4;
  const secLen = ctx.dims['Section length'] ?? ctx.lambdaMm * 0.52;
  const total = n * secLen;
  const s = fit(60, total * 1.15, 90, 240);
  const cx = 120, oy = 44;
  el('rect', { x: cx - 16, y: oy - 8, width: 32, height: total * s + 24, fill: T.air, stroke: T.line, 'stroke-width': 0.8, rx: 12 }, g);
  for (let i = 0; i < n; i++) {
    const y0 = oy + i * secLen * s;
    el('line', { x1: cx, y1: y0, x2: cx, y2: y0 + secLen * s * 0.82, stroke: T.cu, 'stroke-width': 4 }, g);
    if (i < n - 1) el('path', { d: `M${cx},${y0 + secLen * s * 0.82} q14,${secLen * s * 0.09} 0,${secLen * s * 0.18}`, fill: 'none', stroke: T.cu, 'stroke-width': 2 }, g);
  }
  coax(g, cx, oy + total * s + 16);
  dimLine(g, cx + 26, oy, cx + 26, oy + secLen * s, `${num(secLen, 0)} mm`, true);
  lbl(g, 190, 74, `${n} co-phased half-wave sections inside a radome.`);
  lbl(g, 190, 100, 'Each phasing section flips the current back');
  lbl(g, 190, 116, 'in phase, so the sections add along the axis');
  lbl(g, 190, 132, 'and the doughnut is squashed toward the horizon.');
  lbl(g, 190, 160, `Elevation beamwidth ≈ ${num(51 / n, 0)}° — mounting tilt`);
  lbl(g, 190, 176, 'becomes a real installation parameter.');
  lbl(g, 190, 204, `Overall length ${num(total, 0)} mm`, 'start', 'diagram-dim');
}

function drawBiconical(g, ctx) {
  const dia = ctx.dims['Disc diameter'] ?? ctx.lambdaMm * 0.5;
  const slant = ctx.dims['Cone slant'] ?? ctx.lambdaMm * 0.28;
  const s = fit(dia * 1.4, slant * 3, 200, 190);
  const cx = 160, cy = 150;
  const r = (dia * s) / 2, hgt = slant * s;
  el('path', { d: `M${cx},${cy - 6} L${cx - r},${cy - hgt} L${cx + r},${cy - hgt}Z`, fill: T.metal, stroke: T.line, 'stroke-width': 0.8 }, g);
  el('path', { d: `M${cx},${cy + 6} L${cx - r},${cy + hgt} L${cx + r},${cy + hgt}Z`, fill: T.metal, stroke: T.line, 'stroke-width': 0.8 }, g);
  el('ellipse', { cx, cy: cy - hgt, rx: r, ry: r * 0.18, fill: T.metal, stroke: T.line, 'stroke-width': 0.8 }, g);
  el('ellipse', { cx, cy: cy + hgt, rx: r, ry: r * 0.18, fill: T.metal, stroke: T.line, 'stroke-width': 0.8 }, g);
  coax(g, cx + r + 24, cy, 'right');
  el('line', { x1: cx, y1: cy, x2: cx + r + 24, y2: cy, stroke: T.cu, 'stroke-width': 2 }, g);
  dimLine(g, cx - r, cy - hgt - 16, cx + r, cy - hgt - 16, `${num(dia, 0)} mm`);
  lbl(g, 300, 110, 'The cone angle sets the impedance and the');
  lbl(g, 300, 126, 'slant length sets the lowest frequency —');
  lbl(g, 300, 142, 'a decade of bandwidth from one geometry.');
  lbl(g, 300, 170, 'Sheet metal or turned aluminium, not a PCB.');
  lbl(g, 300, 198, 'The EMC and spectrum-monitoring standard.');
}

function drawLoop(g, ctx) {
  const r = ctx.dims['Loop radius'] ?? 8;
  const s = fit(r * 4, r * 4, 170, 170);
  const cx = 130, cy = 150, rp = r * s;
  el('circle', { cx, cy, r: rp, fill: 'none', stroke: T.cu, 'stroke-width': 5 }, g);
  el('rect', { x: cx - 5, y: cy + rp - 4, width: 10, height: 8, fill: T.sub }, g);
  el('line', { x1: cx - 9, y1: cy + rp + 8, x2: cx + 9, y2: cy + rp + 8, stroke: T.cu, 'stroke-width': 3 }, g);
  el('line', { x1: cx - 9, y1: cy + rp + 14, x2: cx + 9, y2: cy + rp + 14, stroke: T.cu, 'stroke-width': 3 }, g);
  lbl(g, cx + 16, cy + rp + 16, 'tuning capacitor');
  dimLine(g, cx, cy - rp - 16, cx + rp, cy - rp - 16, `r = ${num(r, 1)} mm`);
  lbl(g, 300, 96, `Circumference / λ = ${num(ctx.dims['Circumference/lambda'] ?? 0, 3)}`);
  lbl(g, 300, 112, `Radiation resistance ${num(ctx.dims.R_rad ?? 0, 3)} Ω`);
  lbl(g, 300, 140, 'R_rad falls as (C/λ)⁴, so almost all of the');
  lbl(g, 300, 156, 'input power goes into the loss resistance.');
  lbl(g, 300, 184, 'What it buys: a magnetic-field antenna that');
  lbl(g, 300, 200, 'barely notices nearby dielectric — it keeps');
  lbl(g, 300, 216, 'working inside a metal-rich product.');
}

function drawYagi(g, ctx, printed) {
  const boom = ctx.dims['Boom length'] ?? ctx.dims['Board length'] ?? ctx.lambdaMm;
  const nDir = Math.min(ctx.dims.Directors ?? 3, 12);
  const refl = ctx.dims.Reflector ?? ctx.lambdaMm * 0.49;
  const driven = ctx.dims.Driven ?? ctx.dims['Driver length'] ?? ctx.lambdaMm * 0.47;
  const s = fit(boom * 1.1, refl * 1.35, 380, 190);
  const ox = 70, cy = 150;
  if (printed) rect(g, ox - 22, cy - (refl * s) / 2 - 14, boom * s + 50, refl * s + 28, T.sub);
  el('line', { x1: ox - 10, y1: cy, x2: ox + boom * s + 10, y2: cy, stroke: printed ? T.cu : T.metal, 'stroke-width': printed ? 2 : 5 }, g);
  const elems = [{ x: 0, len: refl, name: 'reflector' }, { x: boom * 0.12, len: driven, name: 'driven' }];
  for (let i = 0; i < nDir; i++) {
    elems.push({ x: boom * (0.12 + ((i + 1) * 0.88) / (nDir + 0.4)), len: driven * (0.94 - i * 0.012), name: '' });
  }
  elems.forEach((e, i) => {
    const x = ox + e.x * s, hl = (e.len * s) / 2;
    el('line', { x1: x, y1: cy - hl, x2: x, y2: cy + hl, stroke: T.cu, 'stroke-width': printed ? 4 : 5, 'stroke-linecap': 'round' }, g);
    if (e.name) lbl(g, x, cy - hl - 10 - i * 15, e.name, 'middle');   // staggered so they never overprint
  });
  const dx = ox + boom * 0.12 * s;
  el('line', { x1: dx, y1: cy, x2: dx, y2: cy + (refl * s) / 2 + 14, stroke: T.cu, 'stroke-width': 2 }, g);
  coax(g, dx, cy + (refl * s) / 2 + 14);
  dimLine(g, ox, cy + (refl * s) / 2 + 62, ox + boom * s, cy + (refl * s) / 2 + 62, `boom ${num(boom, 0)} mm  (${num(boom / ctx.lambdaMm, 2)} λ)`);
  el('path', { d: `M${ox + boom * s + 26},${cy} l-10,-7 v14Z`, fill: 'var(--series-1)' }, g);
  lbl(g, ox + boom * s + 32, cy + 4, 'main beam');
  lbl(g, ox, cy + (refl * s) / 2 + 92, `${nDir} director${nDir === 1 ? '' : 's'} on the boom. Gain follows boom length, not element`, 'start');
  lbl(g, ox, cy + (refl * s) / 2 + 108, 'count — adding elements to a short boom buys almost nothing.', 'start');
}

function drawLPDA(g, ctx) {
  const tau = ctx.dims.tau ?? 0.9, sigma = ctx.dims.sigma ?? 0.16;
  const longest = ctx.dims['Longest element'] ?? ctx.lambdaMm * 0.5;
  const boom = ctx.dims.Boom ?? ctx.lambdaMm * 1.6;
  const s = fit(boom * 1.05, longest * 1.3, 380, 190);
  const ox = 60, cy = 150;
  el('line', { x1: ox, y1: cy - 3, x2: ox + boom * s, y2: cy - 3, stroke: T.cu, 'stroke-width': 2 }, g);
  el('line', { x1: ox, y1: cy + 3, x2: ox + boom * s, y2: cy + 3, stroke: T.cu, 'stroke-width': 2 }, g);
  let len = longest, x = ox;
  for (let i = 0; i < 11 && len > longest * 0.18; i++) {
    const hl = (len * s) / 2;
    el('line', { x1: x, y1: cy - hl, x2: x, y2: cy + (i % 2 ? -3 : 3), stroke: T.cu, 'stroke-width': 4, 'stroke-linecap': 'round' }, g);
    el('line', { x1: x, y1: cy + hl, x2: x, y2: cy + (i % 2 ? 3 : -3), stroke: T.cu, 'stroke-width': 4, 'stroke-linecap': 'round' }, g);
    x += len * sigma * 2 * s;
    len *= tau;
  }
  coax(g, ox + boom * s + 16, cy, 'right');
  dimLine(g, ox, cy + (longest * s) / 2 + 26, ox + boom * s, cy + (longest * s) / 2 + 26, `boom ${num(boom, 0)} mm`);
  el('path', { d: `M${ox - 26},${cy} l10,-7 v14Z`, fill: 'var(--series-1)' }, g);
  lbl(g, 30, 258, `τ = ${tau}, σ = ${sigma}. Elements alternate across the twin boom so each cell is fed`, 'start');
  lbl(g, 30, 274, `out of phase. Size is set by the LOWEST frequency: longest element ${num(longest, 0)} mm.`, 'start');
}

function drawVivaldi(g, ctx) {
  const len = ctx.dims['Taper length'] ?? ctx.lambdaMm * 1.5;
  const ap = ctx.dims['Aperture width'] ?? ctx.lambdaMm * 0.7;
  const s = fit(len * 1.15, ap * 1.5, 330, 200);
  const ox = 60, cy = 150, L = len * s, A = (ap * s) / 2;
  rect(g, ox, cy - A * 1.3, L, A * 2.6, T.sub);
  const curve = (sign) => {
    let d = `M${ox + L * 0.1},${cy + sign * 1.5}`;
    for (let i = 0; i <= 40; i++) {
      const t = i / 40;
      const xx = ox + L * 0.1 + t * L * 0.9;
      const yy = cy + sign * (1.5 + (A - 1.5) * (Math.exp(3.2 * t) - 1) / (Math.exp(3.2) - 1));
      d += ` L${xx},${yy}`;
    }
    return d;
  };
  el('path', { d: `${curve(-1)} L${ox + L},${cy - A * 1.3} L${ox + L * 0.1},${cy - A * 1.3} Z`, fill: T.cu, stroke: T.line, 'stroke-width': 0.8 }, g);
  el('path', { d: `${curve(1)} L${ox + L},${cy + A * 1.3} L${ox + L * 0.1},${cy + A * 1.3} Z`, fill: T.cu, stroke: T.line, 'stroke-width': 0.8 }, g);
  el('circle', { cx: ox + L * 0.08, cy, r: 5, fill: T.sub }, g);
  el('line', { x1: ox + L * 0.08, y1: cy, x2: ox - 4, y2: cy + 34, stroke: T.cu, 'stroke-width': 2.5 }, g);
  coax(g, ox - 12, cy + 34, 'right');
  lbl(g, ox - 6, cy + 58, 'microstrip-to-slotline transition');
  dimLine(g, ox, cy - A * 1.3 - 14, ox + L, cy - A * 1.3 - 14, `${num(len, 0)} mm`);
  dimLine(g, ox + L + 14, cy - A, ox + L + 14, cy + A, `${num(ap, 0)} mm`, true);
  el('path', { d: `M${ox + L + 44},${cy} l-10,-7 v14Z`, fill: 'var(--series-1)' }, g);
  lbl(g, 30, 268, 'Low-frequency limit set by the aperture width (~λ/2 there); high-frequency limit', 'start');
  lbl(g, 30, 284, 'by the slot-line feed. Keep h below ~0.03 λ at the top of the band.', 'start');
}

function drawHorn(g, ctx) {
  const a = ctx.dims['Aperture a'] ?? 40, b = ctx.dims['Aperture b'] ?? 30;
  const ax = ctx.dims['Axial length'] ?? 60;
  const s = fit(ax * 1.5, a * 1.5, 250, 190);
  const ox = 60, cy = 150, L = ax * s, A = (a * s) / 2, wg = A * 0.34;
  el('path', { d: `M${ox},${cy - wg} L${ox + L},${cy - A} L${ox + L},${cy + A} L${ox},${cy + wg} Z`,
    fill: T.metal, stroke: T.line, 'stroke-width': 0.9, opacity: 0.9 }, g);
  rect(g, ox - 34, cy - wg, 34, wg * 2, T.metal);
  el('ellipse', { cx: ox + L, cy, rx: 7, ry: A, fill: 'none', stroke: T.line, 'stroke-width': 0.9, 'stroke-dasharray': '3 3' }, g);
  coax(g, ox - 34, cy - wg - 12);
  dimLine(g, ox + L + 20, cy - A, ox + L + 20, cy + A, `a ${num(a, 0)} mm`, true);
  dimLine(g, ox, cy + A + 26, ox + L, cy + A + 26, `axial ${num(ax, 0)} mm`);
  el('path', { d: `M${ox + L + 52},${cy} l-10,-7 v14Z`, fill: 'var(--series-1)' }, g);
  lbl(g, 350, 96, `Aperture ${num(a, 0)} × ${num(b, 0)} mm at`);
  lbl(g, 350, 112, `${num((ctx.dims['Aperture eff.'] ?? 0.51) * 100, 0)} % aperture efficiency.`);
  lbl(g, 350, 140, 'Axial length is chosen to hold the');
  lbl(g, 350, 156, 'aperture phase error under λ/8 —');
  lbl(g, 350, 172, 'shorter flares lose gain to phase.');
  lbl(g, 350, 200, 'All metal: no dielectric, no thermal');
  lbl(g, 350, 216, 'derating, power limited by breakdown.');
}

function drawSiwHorn(g, ctx) {
  const ap = ctx.dims['Aperture width'] ?? ctx.lambdaMm * 1.2;
  const fl = ctx.dims['Flare length'] ?? ctx.lambdaMm * 1.6;
  const pitch = ctx.dims['Via pitch'] ?? 1;
  const s = fit(fl * 1.2, ap * 1.6, 280, 180);
  const ox = 50, cy = 150, L = fl * s, A = (ap * s) / 2;
  rect(g, ox - 20, cy - A * 1.35, L + 44, A * 2.7, T.sub);
  for (const sign of [-1, 1]) {
    let x = ox, y = cy + sign * A * 0.22;
    while (x < ox + L) {
      el('circle', { cx: x, cy: y, r: 2.4, fill: T.cu }, g);
      x += Math.max(pitch * s, 8);
      y += sign * ((A - A * 0.22) / (L / Math.max(pitch * s, 8)));
    }
    let bx = ox - 18;
    while (bx < ox) { el('circle', { cx: bx, cy: cy + sign * A * 0.22, r: 2.4, fill: T.cu }, g); bx += 8; }
  }
  coax(g, ox - 24, cy, 'right');
  dimLine(g, ox + L + 16, cy - A, ox + L + 16, cy + A, `${num(ap, 1)} mm`, true);
  el('path', { d: `M${ox + L + 44},${cy} l-10,-7 v14Z`, fill: 'var(--series-1)' }, g);
  lbl(g, 30, 262, 'A horn built inside the board: two via fences flare apart to form the H-plane', 'start');
  lbl(g, 30, 278, 'aperture. Needs a thick stack (>0.1 λ) or the E-plane aperture is too small.', 'start');
}

function drawReflector(g, ctx) {
  const D = ctx.dims['Dish diameter'] ?? 300;
  const fD = ctx.dims['f/D'] ?? 0.4;
  const s = fit(D * 0.9, D * 1.15, 200, 210);
  const cx = 160, cy = 150, R = (D * s) / 2, f = fD * D * s;
  let d = '';
  for (let i = 0; i <= 40; i++) {
    const y = -R + (2 * R * i) / 40;
    const x = (y * y) / (4 * f);
    d += `${i ? 'L' : 'M'}${cx + x - 40},${cy + y}`;
  }
  el('path', { d, fill: 'none', stroke: T.metal, 'stroke-width': 5, 'stroke-linecap': 'round' }, g);
  const fx = cx - 40 + f;
  el('path', { d: `M${fx},${cy - 9} l14,-9 v36 l-14,-9Z`, fill: T.metal, stroke: T.line, 'stroke-width': 0.8 }, g);
  for (const yy of [-0.75, -0.35, 0.35, 0.75]) {
    el('line', { x1: fx, y1: cy, x2: cx - 40 + ((R * yy) ** 2) / (4 * f), y2: cy + R * yy, stroke: 'var(--series-1)', 'stroke-width': 1, opacity: 0.55 }, g);
    el('line', { x1: cx - 40 + ((R * yy) ** 2) / (4 * f), y1: cy + R * yy, x2: cx + 130, y2: cy + R * yy, stroke: 'var(--series-1)', 'stroke-width': 1.4 }, g);
  }
  dimLine(g, cx - 52, cy - R, cx - 52, cy + R, `D ${num(D, 0)} mm`, true);
  dimLine(g, cx - 40, cy + R + 24, fx, cy + R + 24, `f ${num(fD * D, 0)} mm`);
  lbl(g, 330, 100, `f/D = ${fD}, ${num(ctx.dims['3 dB beamwidth'] ?? 0, 2)}° beamwidth.`);
  lbl(g, 330, 128, `Surface RMS must stay under λ/50 =`);
  lbl(g, 330, 144, `${num(ctx.dims['Surface RMS'] ?? 0, 2)} mm for less than 0.3 dB of`);
  lbl(g, 330, 160, 'Ruze loss.');
  lbl(g, 330, 188, `Pointing accuracy needed: ±${num((ctx.dims['3 dB beamwidth'] ?? 1) / 4, 2)}°.`);
}

function drawReflectarray(g, ctx) {
  const side = ctx.dims['Panel side'] ?? 200;
  const pitch = ctx.dims['Cell pitch'] ?? ctx.lambdaMm * 0.5;
  const s = fit(side * 1.2, side * 1.2, 190, 190);
  const ox = 40, oy = 60, S = side * s;
  rect(g, ox, oy, S, S, T.sub);
  const nc = Math.max(Math.min(Math.round(side / pitch), 14), 3);
  const cell = S / nc;
  for (let i = 0; i < nc; i++) {
    for (let j = 0; j < nc; j++) {
      const r = Math.hypot(i - (nc - 1) / 2, j - (nc - 1) / 2);
      const k = 0.34 + 0.3 * (1 + Math.cos(r * 1.5)) / 2;   // phase-shaped element size
      rect(g, ox + i * cell + cell * (1 - k) / 2, oy + j * cell + cell * (1 - k) / 2, cell * k, cell * k, T.cu, { rx: 0.5 });
    }
  }
  const fx = ox + S + 90, fy = oy + S * 0.15;
  el('path', { d: `M${fx},${fy - 8} l12,-8 v32 l-12,-8Z`, fill: T.metal, stroke: T.line, 'stroke-width': 0.8 }, g);
  el('line', { x1: fx, y1: fy + 4, x2: ox + S * 0.5, y2: oy + S * 0.5, stroke: 'var(--series-2)', 'stroke-width': 1.2, 'stroke-dasharray': '4 3' }, g);
  for (const t of [0.2, 0.5, 0.8]) {
    el('line', { x1: ox + S, y1: oy + S * t, x2: ox + S + 70, y2: oy + S * t, stroke: 'var(--series-1)', 'stroke-width': 1.4 }, g);
  }
  lbl(g, fx - 30, fy + 40, 'offset feed horn');
  dimLine(g, ox, oy - 12, ox + S, oy - 12, `${num(side, 0)} mm`);
  lbl(g, 30, oy + S + 26, `${ctx.dims['Unit cells'] ?? nc * nc} phase-shifting cells at ${num(pitch, 1)} mm pitch`, 'start', 'diagram-dim');
  lbl(g, 30, oy + S + 50, 'Element size varies cell by cell to synthesise the parabolic phase front.', 'start');
  lbl(g, 30, oy + S + 66, 'Illuminated through the air, so there is no feed-network loss at all.', 'start');
}

function drawHelix(g, ctx) {
  const turns = Math.min(ctx.dims.Turns ?? 8, 16);
  const dia = ctx.dims.Diameter ?? ctx.lambdaMm / Math.PI;
  const pitch = ctx.dims.Pitch ?? ctx.lambdaMm * 0.24;
  const gnd = ctx.dims['Ground dia.'] ?? ctx.lambdaMm * 0.8;
  const total = turns * pitch;
  const s = fit(gnd * 1.2, total * 1.35, 150, 220);
  const cx = 130, baseY = 262, R = (dia * s) / 2, P = pitch * s;
  el('ellipse', { cx, cy: baseY, rx: (gnd * s) / 2, ry: (gnd * s) / 8, fill: T.cu, stroke: T.line, 'stroke-width': 0.8 }, g);
  let d = '';
  for (let i = 0; i <= turns * 36; i++) {
    const t = i / 36;
    const a = t * 2 * Math.PI;
    const x = cx + R * Math.cos(a);
    const y = baseY - t * P - R * 0.26 * Math.sin(a);
    d += `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
  }
  el('path', { d, fill: 'none', stroke: T.cu, 'stroke-width': 2.6, 'stroke-linejoin': 'round' }, g);
  coax(g, cx + R, baseY + 4);
  dimLine(g, cx - R - 20, baseY - total * s, cx - R - 20, baseY, `${num(total, 0)} mm`, true);
  dimLine(g, cx - R, baseY - total * s - 16, cx + R, baseY - total * s - 16, `Ø ${num(dia, 1)} mm`);
  lbl(g, 300, 96, `${turns} turns, C ≈ 1 λ, pitch ${num(pitch, 1)} mm.`);
  lbl(g, 300, 124, 'Circular polarisation falls out of the');
  lbl(g, 300, 140, 'geometry — no polariser, and the axial');
  lbl(g, 300, 156, 'ratio holds over a 1.7:1 band.');
  lbl(g, 300, 184, `Kraus: G = 15·C²·S·n. Long and awkward`);
  lbl(g, 300, 200, `to mount: ${num(total, 0)} mm of axial length.`);
}

function drawQHA(g, ctx) {
  const dia = ctx.dims.Diameter ?? 20, len = ctx.dims.Length ?? 60;
  const s = fit(dia * 3, len * 1.3, 130, 210);
  const cx = 130, oy = 56, R = (dia * s) / 2, L = len * s;
  el('rect', { x: cx - R * 1.5, y: oy - 10, width: R * 3, height: L + 24, fill: T.air, stroke: T.line, 'stroke-width': 0.8, rx: R * 1.2 }, g);
  for (let k = 0; k < 4; k++) {
    let d = '';
    for (let i = 0; i <= 40; i++) {
      const t = i / 40;
      const a = t * Math.PI + (k * Math.PI) / 2;
      d += `${i ? 'L' : 'M'}${(cx + R * Math.cos(a)).toFixed(1)},${(oy + t * L).toFixed(1)}`;
    }
    el('path', { d, fill: 'none', stroke: T.cu, 'stroke-width': k % 2 ? 1.6 : 2.6, opacity: k % 2 ? 0.55 : 1 }, g);
  }
  coax(g, cx, oy + L + 14);
  dimLine(g, cx + R * 1.7, oy, cx + R * 1.7, oy + L, `${num(len, 0)} mm`, true);
  lbl(g, 240, 90, 'Four helical filaments fed at 0/90/180/270°.');
  lbl(g, 240, 118, 'Gives a cardioid circularly-polarised pattern');
  lbl(g, 240, 134, 'with coverage down to the horizon and no');
  lbl(g, 240, 150, 'ground plane at all — so the platform under');
  lbl(g, 240, 166, 'it barely matters.');
  lbl(g, 240, 194, 'The feed network sets the axial ratio, and it');
  lbl(g, 240, 210, 'is the hard part of the build.');
}

function drawSlotCavity(g, ctx) {
  const sl = ctx.dims['Slot length'] ?? ctx.lambdaMm * 0.48;
  const sw = ctx.dims['Slot width'] ?? ctx.lambdaMm * 0.05;
  const depth = ctx.dims['Cavity depth'] ?? ctx.lambdaMm * 0.25;
  const s = fit(sl * 1.6, sl * 1.6, 180, 180);
  const ox = 40, oy = 66;
  rect(g, ox, oy, sl * 1.6 * s, sl * 1.6 * s, T.cu);
  rect(g, ox + sl * 0.3 * s, oy + (sl * 1.6 * s) / 2 - (sw * s) / 2, sl * s, Math.max(sw * s, 4), T.sub2, { rx: 2 });
  dimLine(g, ox + sl * 0.3 * s, oy + (sl * 1.6 * s) / 2 - 16, ox + sl * 1.3 * s, oy + (sl * 1.6 * s) / 2 - 16, `${num(sl, 1)} mm`);
  lbl(g, ox, oy + sl * 1.6 * s + 20, 'flush surface — the only feature is a slot', 'start', 'diagram-dim');
  // cross-section
  const cx2 = 300, baseY = 200, cw = 180, cd = Math.min(depth * s, 70);
  rect(g, cx2, baseY - cd, cw, cd, T.air);
  el('path', { d: `M${cx2},${baseY - cd} v${cd} h${cw} v${-cd}`, fill: 'none', stroke: T.metal, 'stroke-width': 5 }, g);
  rect(g, cx2, baseY - cd - 5, cw * 0.36, 5, T.metal);
  rect(g, cx2 + cw * 0.64, baseY - cd - 5, cw * 0.36, 5, T.metal);
  el('line', { x1: cx2 + cw * 0.5, y1: baseY, x2: cx2 + cw * 0.5, y2: baseY - cd, stroke: T.cu, 'stroke-width': 2 }, g);
  coax(g, cx2 + cw * 0.5, baseY);
  dimLine(g, cx2 + cw + 14, baseY - cd, cx2 + cw + 14, baseY, `λ/4 = ${num(depth, 1)} mm`, true);
  lbl(g, cx2, baseY - cd - 18, 'cavity makes it unidirectional', 'start');
  lbl(g, cx2, baseY + 40, 'Conformal: survives on aircraft skins', 'start');
  lbl(g, cx2, baseY + 56, 'and machine housings.', 'start');
}

function drawMEDipole(g, ctx) {
  const p = ctx.dims['Patch pair'] ?? ctx.lambdaMm * 0.25;
  const wall = ctx.dims['Vertical wall'] ?? ctx.lambdaMm * 0.25;
  const gnd = ctx.dims.Ground ?? ctx.lambdaMm * 0.9;
  const s = fit(gnd * 1.15, (wall + p) * 2.2, 220, 180);
  const cx = 160, baseY = 240;
  groundBar(g, cx - (gnd * s) / 2, baseY, gnd * s);
  const topY = baseY - wall * s;
  rect(g, cx - p * s - 5, topY - 5, p * s, 5, T.cu);
  rect(g, cx + 5, topY - 5, p * s, 5, T.cu);
  rect(g, cx - p * s - 5, topY, 5, wall * s, T.cu);
  rect(g, cx + p * s, topY, 5, wall * s, T.cu);
  el('path', { d: `M${cx},${baseY} v${-(wall * s) * 0.55} q0,-12 -14,-12 M${cx},${baseY - wall * s * 0.55} q0,-12 14,-12`, fill: 'none', stroke: T.cu, 'stroke-width': 2 }, g);
  coax(g, cx, baseY + 5);
  lbl(g, cx - p * s - 5, topY - 16, 'horizontal patch pair = electric dipole', 'start');
  lbl(g, cx + p * s + 14, topY + wall * s * 0.5, 'vertical walls =', 'start');
  lbl(g, cx + p * s + 14, topY + wall * s * 0.5 + 14, 'magnetic dipole', 'start');
  dimLine(g, cx - (gnd * s) / 2, baseY + 34, cx + (gnd * s) / 2, baseY + 34, `ground ${num(gnd, 0)} mm`);
  lbl(g, 30, 292, 'The two dipoles radiate complementary patterns, so E- and H-plane beamwidths', 'start');
  lbl(g, 30, 308, 'track within a few degrees across 40-60 % bandwidth — the base-station favourite.', 'start');
}

function drawLens(g, ctx) {
  const D = ctx.dims['Lens diameter'] ?? 40;
  const th = ctx.dims.Thickness ?? D * 0.35;
  const fl = ctx.dims['Focal length'] ?? D * 0.7;
  const s = fit((fl + th) * 1.3, D * 1.4, 250, 190);
  const cx = 130, cy = 150, R = (D * s) / 2, Th = th * s, F = fl * s;
  el('path', { d: `M${cx},${cy - R} q${Th * 1.6},${R} 0,${2 * R} L${cx - Th * 0.15},${cy + R} q${-Th * 0.2},${-R} 0,${-2 * R} Z`,
    fill: T.air, stroke: T.line, 'stroke-width': 1.2 }, g);
  rect(g, cx - F - 26, cy - 16, 26, 32, T.sub);
  rect(g, cx - F - 20, cy - 9, 14, 18, T.cu);
  lbl(g, cx - F - 30, cy + 34, 'patch or SIW feed on the PCB', 'start');
  for (const t of [-0.7, -0.3, 0.3, 0.7]) {
    el('line', { x1: cx - F, y1: cy, x2: cx, y2: cy + R * t, stroke: 'var(--series-1)', 'stroke-width': 1, opacity: 0.5 }, g);
    el('line', { x1: cx + Th * 0.8, y1: cy + R * t, x2: cx + 130, y2: cy + R * t, stroke: 'var(--series-1)', 'stroke-width': 1.4 }, g);
  }
  dimLine(g, cx - Th * 0.3, cy - R - 14, cx + Th * 1.4, cy - R - 14, `${num(th, 1)} mm`);
  dimLine(g, cx + Th * 2 + 20, cy - R, cx + Th * 2 + 20, cy + R, `Ø ${num(D, 0)} mm`, true);
  lbl(g, 30, 268, `Moulded hyperbolic lens (εr ≈ ${num(ctx.dims['Lens eps_r'] ?? 2.35, 2)}) over a PCB feed. Add a λ/4 matching`, 'start');
  lbl(g, 30, 284, 'groove or the front face reflects about 4 % of the incident power.', 'start');
}

/* ------------------------------------------------------------ dispatcher */

const DRAW = {
  patch: (g, c) => drawPatchFamily(g, c, 'solid'),
  patchAir: (g, c) => drawPatchFamily(g, c, 'air'),
  patchStacked: (g, c) => drawPatchFamily(g, c, 'stacked'),
  patchApertureCoupled: (g, c) => drawPatchFamily(g, c, 'aperture'),
  patchArray: (g, c) => drawPlanarArray(g, c, false),
  phasedArray: (g, c) => drawPlanarArray(g, c, true),
  seriesArray: drawSeriesArray,
  siwSlotArray: drawSiwSlotArray,
  dra: drawDRA,
  monopole: drawMonopole,
  dipole: drawDipole,
  pifa: drawPIFA,
  ifa: drawIFA,
  collinear: drawCollinear,
  biconical: drawBiconical,
  loopSmall: drawLoop,
  yagi: (g, c) => drawYagi(g, c, false),
  quasiYagi: (g, c) => drawYagi(g, c, true),
  lpda: drawLPDA,
  vivaldi: drawVivaldi,
  hornPyramidal: drawHorn,
  hornSiw: drawSiwHorn,
  reflector: drawReflector,
  reflectarray: drawReflectarray,
  helixAxial: drawHelix,
  qha: drawQHA,
  slotCavity: drawSlotCavity,
  meDipole: drawMEDipole,
  lens: drawLens,
};

/**
 * Render the geometry drawing for a candidate.
 * @param host   container element
 * @param cand   a recommendation candidate (arch, dims, size, count, patch)
 * @param D      the design result (for lambda0)
 */
export function antennaDrawing(host, cand, D, opts = {}) {
  host.innerHTML = '';
  host.classList.add('chart-host');
  const head = h('div', { class: 'chart-head' }, host);
  h('div', { class: 'chart-title', text: opts.title || `${cand.arch.name} — geometry` }, head);
  h('div', { class: 'chart-sub', text: opts.subtitle || 'Drawn from the synthesised dimensions: change the specification and this redraws.' }, head);
  const wrap = h('div', { class: 'chart-wrap' }, host);
  const svg = el('svg', {
    viewBox: `0 0 ${W} ${H}`, class: 'chart-svg diagram antenna-art',
    role: 'img', 'aria-label': `${cand.arch.name} geometry drawing`,
  }, wrap);
  const g = el('g', {}, svg);

  const ctx = {
    dims: cand.dims || {},
    size: cand.size || { w: 20, l: 20, h: 2 },
    lambdaMm: D.lambda0 * 1e3,
    count: cand.count || 1,
    patch: cand.patch,
    arch: cand.arch,
    groundMm: cand.arch.category === 'Microstrip' && D.groundM ? D.groundM * 1e3 : null,
  };
  const fn = DRAW[cand.arch.id];
  if (fn) {
    try { fn(g, ctx); }
    catch (err) {
      lbl(g, W / 2, H / 2, `drawing unavailable (${err.message})`, 'middle');
    }
  } else {
    lbl(g, W / 2, H / 2, 'No scale drawing for this type yet', 'middle');
  }

  // Centre the finished drawing in the viewBox and shrink it if it overflowed.
  // Doing it here rather than per-drawing means every family gets consistent
  // margins without each one having to lay itself out perfectly.
  try {
    const bb = g.getBBox();
    if (bb.width > 0 && bb.height > 0) {
      const pad = 12;
      const k = Math.min(1, (W - 2 * pad) / bb.width, (H - 2 * pad) / bb.height);
      const tx = (W - bb.width * k) / 2 - bb.x * k;
      const ty = (H - bb.height * k) / 2 - bb.y * k;
      g.setAttribute('transform', `translate(${tx.toFixed(2)},${ty.toFixed(2)}) scale(${k.toFixed(4)})`);
    }
  } catch (e) { /* getBBox is unavailable when the node is not laid out */ }
  return svg;
}

export { DRAW };
