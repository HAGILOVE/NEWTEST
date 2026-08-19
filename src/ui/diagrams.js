/**
 * Engineering diagrams: stack-up cross-section and patch plan view.
 * Both are drawn to scale from the solved design so the picture cannot drift
 * out of step with the numbers.
 */
import { el, h, fitWidth } from './charts.js';

/**
 * Sectional hatching, as an engineering drawing would use it: each material
 * family gets its own line angle and pitch, so a cut face is identifiable
 * without reading its label. Registered once per SVG.
 */
let hatchSeq = 0;
export function defineHatch(svg) {
  const id = `hx${hatchSeq++}`;
  const defs = el('defs', {}, svg);
  const pat = (name, angle, pitch, stroke, width, bg) => {
    const p = el('pattern', {
      id: `${id}-${name}`, width: pitch, height: pitch,
      patternUnits: 'userSpaceOnUse', patternTransform: `rotate(${angle})`,
    }, defs);
    if (bg) el('rect', { width: pitch, height: pitch, fill: bg }, p);
    el('line', { x1: 0, y1: 0, x2: 0, y2: pitch, stroke, 'stroke-width': width }, p);
  };
  pat('substrate', 45, 5, 'var(--diagram-stroke)', 0.55, 'var(--sub)');
  pat('carrier', 135, 5, 'var(--diagram-stroke)', 0.55, 'var(--sub2)');
  pat('metal', 45, 3, 'var(--diagram-stroke)', 0.5, 'var(--connector)');
  return {
    substrate: `url(#${id}-substrate)`,
    carrier: `url(#${id}-carrier)`,
    metal: `url(#${id}-metal)`,
  };
}

/** ISO-style dimension line with solid arrowheads at both ends. */
export function dimArrow(g, x1, y1, x2, y2, text, vertical = false, cls = 'diagram-dim') {
  el('line', { x1, y1, x2, y2, class: 'dim-line' }, g);
  const head = (px, py, dir) => {
    const a = vertical ? `M${px},${py} l-3.2,${dir * 7} h6.4 Z` : `M${px},${py} l${dir * 7},-3.2 v6.4 Z`;
    el('path', { d: a, fill: 'var(--text-muted)' }, g);
  };
  head(x1, y1, 1);
  head(x2, y2, -1);
  // witness lines, the short ticks that tie the dimension to the feature
  const w = 4;
  for (const [px, py] of [[x1, y1], [x2, y2]]) {
    el('line', Object.assign({ class: 'dim-line' },
      vertical ? { x1: px - w, x2: px + w, y1: py, y2: py } : { x1: px, x2: px, y1: py - w, y2: py + w }), g);
  }
  if (!text) return;
  const t = el('text', { class: cls, 'text-anchor': 'middle' }, g);
  if (vertical) t.setAttribute('transform', `translate(${x1 - 8},${(y1 + y2) / 2}) rotate(-90)`);
  else { t.setAttribute('x', (x1 + x2) / 2); t.setAttribute('y', y1 - 7); }
  t.textContent = text;
}

const LAYER_FILL = {
  copper: 'var(--cu)',
  air: 'var(--air)',
  substrate: 'var(--sub)',
  carrier: 'var(--sub2)',
  spacer: 'var(--spacer)',
};

/**
 * Cross-section of the stack-up with leader lines.
 * @param design result of runDesign()
 */
export function stackupDiagram(host, design, opts = {}) {
  const W = opts.width || fitWidth(host, 760, 420, 980);
  const H = opts.height || Math.round(W * 0.53);
  host.innerHTML = '';
  host.classList.add('chart-host');
  const head = h('div', { class: 'chart-head' }, host);
  h('div', { class: 'chart-title', text: opts.title || 'Stack-up cross-section' }, head);
  h('div', { class: 'chart-sub', text: 'Horizontal scale is true; vertical scale is exaggerated so thin layers stay visible.' }, head);
  const wrap = h('div', { class: 'chart-wrap' }, host);
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart-svg diagram', role: 'img', 'aria-label': 'stack-up cross section' }, wrap);
  const HATCH = defineHatch(svg);

  const { sol, stack, feed } = design;
  // The cross-section is cut through the E-plane, so it shows the X extent.
  const gndMm = (design.groundXM ?? design.groundM) * 1e3;
  const patchMm = sol.L * 1e3;
  const isAirGap = !!stack.composite;

  const drawW = W * 0.44;
  const scaleX = drawW / gndMm;
  const originX = 46;
  const gW = gndMm * scaleX;

  // ---- build the layer list, bottom-up -----------------------------------
  // Solid build: the laminate IS the board - one substrate, ground Cu under it.
  // Air-gap build: a separate ground PCB, then the gap, then the thin carrier.
  const cuUm = (design.spec.tCu ?? 35e-6) * 1e6;
  const layers = [];
  if (isAirGap) {
    const gndPcb = 1.6e-3;
    layers.push({ kind: 'substrate', h: gndPcb, full: true, label: `Ground PCB — FR-4 ${(gndPcb * 1e3).toFixed(2)} mm` });
    layers.push({ kind: 'copper', h: cuUm * 1e-6, full: true, label: `Ground copper ${cuUm.toFixed(0)} µm` });
    layers.push({ kind: 'air', h: stack.layers[0].h, full: true, label: `Air gap ${(stack.layers[0].h * 1e3).toFixed(2)} mm (εr 1.00)` });
    layers.push({ kind: 'carrier', h: stack.layers[1].h, full: false, label: `${stack.layers[1].name} carrier ${(stack.layers[1].h * 1e3).toFixed(2)} mm (εr ${stack.layers[1].er.toFixed(2)})` });
  } else {
    layers.push({ kind: 'copper', h: cuUm * 1e-6, full: true, label: `Ground copper ${cuUm.toFixed(0)} µm` });
    layers.push({ kind: 'substrate', h: stack.h, full: true, label: `${stack.layers[0].name} — ${(stack.h * 1e3).toFixed(2)} mm (εr ${stack.layers[0].er.toFixed(2)}, tanδ ${stack.layers[0].df.toFixed(4)})` });
  }
  layers.push({ kind: 'copper', h: cuUm * 1e-6, patch: true, full: false, label: `Patch copper ${cuUm.toFixed(0)} µm — ${(sol.W * 1e3).toFixed(1)} × ${(sol.L * 1e3).toFixed(1)} mm` });

  // vertical exaggeration: fit the whole stack into a fixed drawing height,
  // with a floor on the copper foils so they never vanish
  const totalMm = layers.reduce((a, l) => a + l.h * 1e3, 0);
  const drawH = 150;
  const vScale = drawH / Math.max(totalMm, 0.4);
  const hOf = (l) => Math.max(l.h * 1e3 * vScale, l.kind === 'copper' ? 4 : 6);

  const baseY = H - 92;
  let y = baseY;
  const placed = [];
  for (const L of layers) {
    const lh = hOf(L);
    y -= lh;
    const w = L.full ? gW : Math.min(L.patch ? patchMm * scaleX : patchMm * scaleX * 1.22, gW);
    const x = originX + (gW - w) / 2;
    // Cut faces get sectional hatching; copper foils and the air gap stay flat,
    // as they would on a real section view.
    const fill = L.kind === 'substrate' ? HATCH.substrate
      : L.kind === 'carrier' ? HATCH.carrier
      : (LAYER_FILL[L.kind] || 'var(--sub)');
    const r = el('rect', {
      x, y, width: w, height: lh, fill,
      stroke: 'var(--diagram-stroke)', 'stroke-width': 0.8,
    }, svg);
    el('title', {}, r).textContent = L.label;
    placed.push({ ...L, x, y, w, lh });
  }
  const topY = y;

  // ---- spacers for the air-gap build -------------------------------------
  if (isAirGap) {
    const gap = placed.find((p) => p.kind === 'air');
    const spW = 8;
    for (const sx of [originX + gW * 0.09, originX + gW * 0.91 - spW]) {
      el('rect', { x: sx, y: gap.y, width: spW, height: gap.lh, fill: LAYER_FILL.spacer, stroke: 'var(--diagram-stroke)', 'stroke-width': 0.8 }, svg);
    }
    placed.push({ label: 'Nylon M3 spacers (×4) set the gap', y: gap.y + gap.lh / 2, x: originX + gW * 0.09, w: spW, lh: 0, spacer: true });
  }

  // ---- feed --------------------------------------------------------------
  const patchLayer = placed[placed.length - 1];
  if (feed.type === 'probe') {
    const gndLayer = placed.find((p) => p.kind === 'copper');
    const fx = originX + gW / 2 + (feed.probeOffset || 0) * 1e3 * scaleX;
    el('rect', { x: fx - 1.8, y: patchLayer.y, width: 3.6, height: baseY - patchLayer.y, fill: LAYER_FILL.copper }, svg);
    el('rect', { x: fx - 10, y: baseY, width: 20, height: 24, fill: 'var(--connector)', stroke: 'var(--diagram-stroke)', 'stroke-width': 0.8 }, svg);
    el('text', { x: fx, y: baseY + 38, class: 'diagram-label', 'text-anchor': 'middle' }, svg).textContent = 'coaxial probe / SMA';
    void gndLayer;
  } else {
    // coplanar microstrip feed running out to the board edge
    const fy = patchLayer.y;
    el('rect', { x: patchLayer.x + patchLayer.w, y: fy, width: originX + gW - (patchLayer.x + patchLayer.w), height: patchLayer.lh, fill: LAYER_FILL.copper }, svg);
    el('rect', { x: originX + gW - 4, y: fy - 4, width: 16, height: 20, fill: 'var(--connector)', stroke: 'var(--diagram-stroke)', 'stroke-width': 0.8 }, svg);
    placed.push({ label: `${feed.type} feed, coplanar to the board edge`, y: fy, x: originX + gW + 12, w: 0, lh: 0, spacer: true });
  }

  // ---- overall height dimension -----------------------------------------
  // h is the ELECTRICAL height: patch copper down to the ground copper, which
  // for an air-gap build excludes the carrier PCB underneath the ground.
  const gndCu = placed.filter((p) => p.kind === 'copper')[0];
  const dimX = originX - 16;
  const dimTop = topY;
  const dimBot = gndCu.y;
  dimArrow(svg, dimX, dimTop, dimX, dimBot, `h = ${(stack.h * 1e3).toFixed(2)} mm`, true);

  // ---- callouts, one per layer, anchored to that layer's own height -------
  const cx = originX + gW + 40;
  const items = placed.filter((p) => p.label).reverse();
  const step = Math.min(24, (H - 130) / Math.max(items.length, 1));
  let ly = 44;
  for (const it of items) {
    const ay = it.spacer ? it.y : it.y + it.lh / 2;
    const ax = it.spacer ? it.x + it.w : it.x + it.w - 4;
    el('path', { d: `M${ax},${ay} L${cx - 12},${ly - 4} L${cx - 5},${ly - 4}`, class: 'leader', fill: 'none' }, svg);
    el('text', { x: cx, y: ly, class: 'diagram-label' }, svg).textContent = it.label;
    ly += step;
  }

  // ---- horizontal scale bar ---------------------------------------------
  const sbY = H - 30;
  dimArrow(svg, originX, sbY, originX + gW, sbY, null);
  el('text', { x: originX + gW / 2, y: sbY + 17, class: 'diagram-dim', 'text-anchor': 'middle' }, svg)
    .textContent = `ground X ${gndMm.toFixed(0)} mm  (${(gndMm / 1e3 / design.lambda0).toFixed(2)} λ₀)  —  section through the E-plane`;

  return svg;
}

/** Plan view of the patch with the feed geometry dimensioned. */
export function planView(host, design, opts = {}) {
  const W = opts.width || fitWidth(host, 480, 340, 620);
  const H = opts.height || Math.round(W * 0.86);
  host.innerHTML = '';
  host.classList.add('chart-host');
  const head = h('div', { class: 'chart-head' }, host);
  h('div', { class: 'chart-title', text: opts.title || 'Plan view — etch geometry' }, head);
  h('div', { class: 'chart-sub', text: 'Drawn to scale from the solved dimensions.' }, head);
  const wrap = h('div', { class: 'chart-wrap' }, host);
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart-svg diagram', role: 'img', 'aria-label': 'patch plan view' }, wrap);

  const { sol, feed } = design;
  // Plan view: x (the resonant length, E-plane) runs vertically down the page
  // so the feed enters from the bottom, as it does on the board.
  const gndXMm = (design.groundXM ?? design.groundM) * 1e3;
  const gndYMm = (design.groundYM ?? design.groundM) * 1e3;
  const s = Math.min((W - 100) / gndYMm, (H - 100) / gndXMm);
  const boardW = gndYMm * s, boardH = gndXMm * s;
  const gx = (W - boardW) / 2, gy = 50;

  el('rect', { x: gx, y: gy, width: boardW, height: boardH, fill: 'var(--sub)', stroke: 'var(--diagram-stroke)' }, svg);
  const pw = sol.W * 1e3 * s, pl = sol.L * 1e3 * s;
  const pxc = gx + (boardW - pw) / 2, pyc = gy + (boardH - pl) / 2;
  el('rect', { x: pxc, y: pyc, width: pw, height: pl, fill: 'var(--cu)', stroke: 'var(--diagram-stroke)' }, svg);

  if (feed.type === 'inset') {
    const fw = feed.feedLineWidth * 1e3 * s;
    const gap = feed.insetGap * 1e3 * s;
    const dep = feed.insetDepth * 1e3 * s;
    const fx = pxc + pw / 2;
    el('rect', { x: fx - fw / 2, y: pyc + pl - dep, width: fw, height: dep + (gy + boardH - (pyc + pl)), fill: 'var(--cu)' }, svg);
    el('rect', { x: fx - fw / 2 - gap, y: pyc + pl - dep, width: gap, height: dep, fill: 'var(--sub)' }, svg);
    el('rect', { x: fx + fw / 2, y: pyc + pl - dep, width: gap, height: dep, fill: 'var(--sub)' }, svg);
    el('text', { x: gx + boardW + 8, y: pyc + pl - dep / 2 + 4, class: 'diagram-label' }, svg)
      .textContent = `inset ${(feed.insetDepth * 1e3).toFixed(2)} mm`;
  } else if (feed.type === 'probe') {
    const off = feed.probeOffset * 1e3 * s;
    el('circle', { cx: pxc + pw / 2, cy: pyc + pl / 2 + off, r: 4, fill: 'var(--connector)', stroke: 'var(--diagram-stroke)' }, svg);
    el('text', { x: pxc + pw / 2 + 10, y: pyc + pl / 2 + off + 4, class: 'diagram-label' }, svg)
      .textContent = `probe ${(feed.probeOffset * 1e3).toFixed(2)} mm off centre`;
  } else if (feed.type === 'quarterWave' && feed.transformer) {
    const fw = feed.transformer.w * 1e3 * s;
    const len = feed.transformer.length * 1e3 * s;
    el('rect', { x: pxc + pw / 2 - fw / 2, y: pyc + pl, width: fw, height: len, fill: 'var(--cu)' }, svg);
    el('text', { x: pxc + pw / 2 + fw / 2 + 6, y: pyc + pl + len / 2, class: 'diagram-label' }, svg)
      .textContent = `λ/4: ${feed.transformer.z.toFixed(0)} Ω, ${(feed.transformer.length * 1e3).toFixed(2)} mm`;
  }

  // dimensions
  const dim = (x1, y1, x2, y2, text, vertical) => dimArrow(svg, x1, y1, x2, y2, text, vertical);
  dim(pxc, pyc - 12, pxc + pw, pyc - 12, `W = ${(sol.W * 1e3).toFixed(2)} mm`);
  dim(pxc - 12, pyc, pxc - 12, pyc + pl, `L = ${(sol.L * 1e3).toFixed(2)} mm`, true);
  dim(gx, gy + boardH + 26, gx + boardW, gy + boardH + 26, `ground Y = ${gndYMm.toFixed(0)} mm  (H-plane)`);
  dim(gx - 36, gy, gx - 36, gy + boardH, `ground X = ${gndXMm.toFixed(0)} mm  (E-plane)`, true);
  // Per-side margins - what the ground model actually consumes - dimensioned
  // rather than annotated, so they cannot collide with the W and L callouts.
  dim(pxc + pw + 16, gy, pxc + pw + 16, pyc, `mX ${((gndXMm - sol.L * 1e3) / 2).toFixed(1)}`, true);
  dim(gx, pyc + pl + 16, pxc, pyc + pl + 16, `mY ${((gndYMm - sol.W * 1e3) / 2).toFixed(1)}`);
  return svg;
}

/** Array layout preview for multi-element candidates. */
export function arrayLayout(host, count, spacingMm, elemW, elemL, opts = {}) {
  const W = opts.width || 420, H = opts.height || 300;
  host.innerHTML = '';
  host.classList.add('chart-host');
  const head = h('div', { class: 'chart-head' }, host);
  h('div', { class: 'chart-title', text: opts.title || `Array layout — ${count} elements` }, head);
  const wrap = h('div', { class: 'chart-wrap' }, host);
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart-svg diagram' }, wrap);
  const cols = Math.ceil(Math.sqrt(count));
  const rows = Math.ceil(count / cols);
  const totalW = cols * spacingMm, totalH = rows * spacingMm;
  const s = Math.min((W - 60) / totalW, (H - 60) / totalH);
  const ox = (W - totalW * s) / 2, oy = (H - totalH * s) / 2;
  el('rect', { x: ox, y: oy, width: totalW * s, height: totalH * s, fill: 'var(--sub)', stroke: 'var(--diagram-stroke)' }, svg);
  let n = 0;
  for (let r = 0; r < rows; r++) {
    for (let cc = 0; cc < cols && n < count; cc++, n++) {
      el('rect', {
        x: ox + (cc + 0.5) * spacingMm * s - (elemW * s) / 2,
        y: oy + (r + 0.5) * spacingMm * s - (elemL * s) / 2,
        width: elemW * s, height: elemL * s, fill: 'var(--cu)', rx: 1,
      }, svg);
    }
  }
  el('text', { x: W / 2, y: H - 8, class: 'diagram-dim', 'text-anchor': 'middle' }, svg)
    .textContent = `${cols} × ${rows}, pitch ${spacingMm.toFixed(1)} mm, panel ${(totalW).toFixed(0)} × ${(totalH).toFixed(0)} mm`;
  return svg;
}
