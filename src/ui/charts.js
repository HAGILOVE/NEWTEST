/**
 * Dependency-free SVG chart library.
 *
 * Design rules enforced here:
 *  - one y-axis per chart, never two (two measures -> two stacked panels)
 *  - categorical hues assigned in fixed slot order, never cycled
 *  - a legend whenever there are 2+ series, plus direct labels when <= 4
 *  - crosshair + tooltip on line/area, per-mark tooltip on bars and points
 *  - every chart can flip to a data table (the relief rule for low-contrast hues)
 *  - colours come from CSS custom properties so light/dark swap in one place
 */

const NS = 'http://www.w3.org/2000/svg';
export const SERIES_VARS = [
  'var(--series-1)', 'var(--series-2)', 'var(--series-3)',
  'var(--series-4)', 'var(--series-5)', 'var(--series-6)',
];

export const el = (tag, attrs = {}, parent = null) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null) continue;
    n.setAttribute(k, String(v));
  }
  if (parent) parent.appendChild(n);
  return n;
};

export const h = (tag, attrs = {}, parent = null) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null) continue;
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k === 'html') n.innerHTML = v;
    else n.setAttribute(k, String(v));
  }
  if (parent) parent.appendChild(n);
  return n;
};

/** Nice axis ticks (Wilkinson-lite). */
export function niceTicks(min, max, count = 6) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { ticks: [0, 1], min: 0, max: 1 };
  if (min === max) { min -= 0.5; max += 0.5; }
  const span = max - min;
  const step0 = span / Math.max(count, 2);
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step * 1e-6; v += step) ticks.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  return { ticks, min: lo, max: hi, step };
}

export function fmt(v, digits = 3) {
  if (!Number.isFinite(v)) return '-';
  const a = Math.abs(v);
  if (a === 0) return '0';
  if (a >= 1e6 || a < 1e-3) return v.toExponential(2);
  return Number(v.toFixed(Math.max(0, digits - Math.max(0, Math.floor(Math.log10(a)) + 1)))).toString();
}

export function engFreq(f) {
  if (f >= 1e9) return `${(f / 1e9).toFixed(f / 1e9 >= 100 ? 0 : 3)} GHz`;
  if (f >= 1e6) return `${(f / 1e6).toFixed(1)} MHz`;
  return `${(f / 1e3).toFixed(1)} kHz`;
}

/* ------------------------------------------------------------------ scaffold */

class Chart {
  constructor(host, opts) {
    this.host = host;
    this.opts = opts;
    // Fixed viewBox width: the SVG scales to its container via CSS, so a
    // constant here keeps every chart at the same aspect ratio regardless of
    // when it is measured during layout.
    this.width = opts.width || 640;
    this.height = opts.height || 300;
    this.m = Object.assign({ t: 26, r: 18, b: 44, l: 62 }, opts.margin || {});
    host.innerHTML = '';
    host.classList.add('chart-host');

    if (opts.title) {
      const head = h('div', { class: 'chart-head' }, host);
      h('div', { class: 'chart-title', text: opts.title }, head);
      if (opts.subtitle) h('div', { class: 'chart-sub', text: opts.subtitle }, head);
    }

    this.wrap = h('div', { class: 'chart-wrap' }, host);
    this.svg = el('svg', {
      viewBox: `0 0 ${this.width} ${this.height}`,
      preserveAspectRatio: 'xMidYMid meet',
      role: 'img', class: 'chart-svg',
      'aria-label': opts.title || 'chart',
    }, this.wrap);
    this.g = el('g', {}, this.svg);
    this.iw = this.width - this.m.l - this.m.r;
    this.ih = this.height - this.m.t - this.m.b;
    this.tip = h('div', { class: 'chart-tip' }, this.wrap);
    this.tip.style.display = 'none';
  }

  axes({ x, y, xLabel, yLabel, xFmt, yFmt, xLog = false, grid = true, xTicksOverride = null }) {
    this.xLog = xLog;
    this.xDom = x; this.yDom = y;
    this.sx = (v) => {
      if (xLog) {
        const l0 = Math.log10(x.min), l1 = Math.log10(x.max);
        return this.m.l + ((Math.log10(Math.max(v, 1e-12)) - l0) / (l1 - l0)) * this.iw;
      }
      return this.m.l + ((v - x.min) / (x.max - x.min)) * this.iw;
    };
    this.sy = (v) => this.m.t + this.ih - ((v - y.min) / (y.max - y.min)) * this.ih;

    const gAx = el('g', { class: 'axis' }, this.g);
    const yt = niceTicks(y.min, y.max, this.opts.yTickCount || 6);
    for (const t of yt.ticks) {
      if (t < y.min - 1e-9 || t > y.max + 1e-9) continue;
      const yy = this.sy(t);
      if (grid) el('line', { x1: this.m.l, x2: this.m.l + this.iw, y1: yy, y2: yy, class: 'grid' }, gAx);
      el('text', { x: this.m.l - 8, y: yy + 4, class: 'tick tick-y' }, gAx)
        .textContent = yFmt ? yFmt(t) : fmt(t, 4);
    }
    const xticks = xTicksOverride || (xLog
      ? logTicks(x.min, x.max)
      : niceTicks(x.min, x.max, this.opts.xTickCount || 6).ticks);
    for (const t of xticks) {
      if (t < x.min - 1e-9 || t > x.max + 1e-9) continue;
      const xx = this.sx(t);
      if (grid) el('line', { x1: xx, x2: xx, y1: this.m.t, y2: this.m.t + this.ih, class: 'grid' }, gAx);
      el('text', { x: xx, y: this.m.t + this.ih + 18, class: 'tick tick-x' }, gAx)
        .textContent = xFmt ? xFmt(t) : fmt(t, 4);
    }
    el('line', { x1: this.m.l, x2: this.m.l + this.iw, y1: this.m.t + this.ih, y2: this.m.t + this.ih, class: 'axis-line' }, gAx);
    el('line', { x1: this.m.l, x2: this.m.l, y1: this.m.t, y2: this.m.t + this.ih, class: 'axis-line' }, gAx);
    if (xLabel) el('text', { x: this.m.l + this.iw / 2, y: this.height - 6, class: 'axis-label' }, gAx).textContent = xLabel;
    if (yLabel) {
      const t = el('text', { x: 0, y: 0, class: 'axis-label', transform: `translate(13,${this.m.t + this.ih / 2}) rotate(-90)` }, gAx);
      t.textContent = yLabel;
    }
    return this;
  }

  showTip(html, px, py) {
    this.tip.innerHTML = html;
    this.tip.style.display = 'block';
    const r = this.wrap.getBoundingClientRect();
    const sc = r.width / this.width;
    let left = px * sc + 12;
    if (left + this.tip.offsetWidth > r.width) left = px * sc - this.tip.offsetWidth - 12;
    this.tip.style.left = `${Math.max(0, left)}px`;
    this.tip.style.top = `${Math.max(0, py * sc - 10)}px`;
  }

  hideTip() { this.tip.style.display = 'none'; }

  legend(items) {
    if (!items || items.length < 2) return this;
    const lg = h('div', { class: 'chart-legend' }, this.host);
    for (const it of items) {
      const s = h('span', { class: 'lg-item' }, lg);
      h('span', { class: 'lg-swatch' }, s).style.background = it.color;
      h('span', { text: it.label }, s);
    }
    return this;
  }

  table(columns, rows, label = 'Data table') {
    const det = h('details', { class: 'chart-table' }, this.host);
    h('summary', { text: label }, det);
    const t = h('table', {}, det);
    const thead = h('thead', {}, t);
    const tr = h('tr', {}, thead);
    for (const c of columns) h('th', { text: c }, tr);
    const tb = h('tbody', {}, t);
    for (const r of rows) {
      const rr = h('tr', {}, tb);
      for (const c of r) h('td', { text: String(c) }, rr);
    }
    return this;
  }

  note(text) {
    if (text) h('p', { class: 'chart-note', text }, this.host);
    return this;
  }
}

/**
 * Reference-line label with a surface-coloured chip behind it, so it stays
 * legible wherever it lands (over a bar, a band, or a dense trace).
 */
function refLabel(g, x, y, text, anchor = 'start') {
  const grp = el('g', {}, g);
  const t = el('text', { x, y, class: 'ref-label', 'text-anchor': anchor }, grp);
  t.textContent = text;
  const w = text.length * 5.6 + 8;
  const rx = anchor === 'end' ? x - w + 4 : anchor === 'middle' ? x - w / 2 : x - 4;
  const bg = el('rect', { x: rx, y: y - 10, width: w, height: 13, fill: 'var(--surface-1)', opacity: 0.88, rx: 3 });
  grp.insertBefore(bg, t);
  return grp;
}

function logTicks(min, max) {
  const out = [];
  for (let e = Math.floor(Math.log10(min)); e <= Math.ceil(Math.log10(max)); e++) {
    for (const m of [1, 2, 5]) {
      const v = m * Math.pow(10, e);
      if (v >= min * 0.999 && v <= max * 1.001) out.push(v);
    }
  }
  return out;
}

/* --------------------------------------------------------------- line chart */

/**
 * @param series [{ name, points:[{x,y}], color?, dash?, markers? }]
 */
export function lineChart(host, opts) {
  const c = new Chart(host, opts);
  const series = opts.series.filter((s) => s.points && s.points.length);
  if (!series.length) { h('p', { class: 'chart-note', text: 'No data' }, host); return c; }

  const xs = series.flatMap((s) => s.points.map((p) => p.x));
  const ys = series.flatMap((s) => s.points.map((p) => p.y)).filter(Number.isFinite);
  const xDom = opts.xDomain || { min: Math.min(...xs), max: Math.max(...xs) };
  const yr = niceTicks(opts.yDomain ? opts.yDomain.min : Math.min(...ys),
                       opts.yDomain ? opts.yDomain.max : Math.max(...ys), opts.yTickCount || 6);
  const yDom = opts.yDomain || { min: yr.min, max: yr.max };
  c.axes({ x: xDom, y: yDom, xLabel: opts.xLabel, yLabel: opts.yLabel, xFmt: opts.xFmt, yFmt: opts.yFmt, xLog: opts.xLog });

  // reference bands / lines
  for (const b of opts.bands || []) {
    el('rect', { x: c.sx(b.from), y: c.m.t, width: Math.max(c.sx(b.to) - c.sx(b.from), 1), height: c.ih, class: 'band' }, c.g);
    if (b.label) el('text', { x: (c.sx(b.from) + c.sx(b.to)) / 2, y: c.m.t + 12, class: 'band-label' }, c.g).textContent = b.label;
  }
  for (const r of opts.hlines || []) {
    const y = c.sy(r.y);
    el('line', { x1: c.m.l, x2: c.m.l + c.iw, y1: y, y2: y, class: `ref-line ${r.kind || ''}` }, c.g);
    if (r.label) el('text', { x: c.m.l + c.iw - 4, y: y - 5, class: 'ref-label', 'text-anchor': 'end' }, c.g).textContent = r.label;
  }
  (opts.vlines || []).forEach((r, i) => {
    const x = c.sx(r.x);
    el('line', { x1: x, x2: x, y1: c.m.t, y2: c.m.t + c.ih, class: `ref-line ${r.kind || ''}` }, c.g);
    if (r.label) {
      // alternate the anchor row so adjacent markers do not overprint
      const row = c.m.t + 4 + (i % 2) * (c.ih * 0.42);
      const t = el('text', { class: 'ref-label', transform: `translate(${x - 5},${row}) rotate(-90)`, 'text-anchor': 'end' }, c.g);
      t.textContent = r.label;
    }
  });

  const clip = `clip${Math.random().toString(36).slice(2)}`;
  const cp = el('clipPath', { id: clip }, c.g);
  el('rect', { x: c.m.l, y: c.m.t - 4, width: c.iw, height: c.ih + 8 }, cp);
  const plot = el('g', { 'clip-path': `url(#${clip})` }, c.g);

  const labelRows = [];
  series.forEach((s, i) => {
    const color = s.color || SERIES_VARS[i % SERIES_VARS.length];
    const pts = s.points.filter((p) => Number.isFinite(p.y));
    if (s.fill) {
      const d = `M${c.sx(pts[0].x)},${c.sy(yDom.min)}` +
        pts.map((p) => `L${c.sx(p.x)},${c.sy(p.y)}`).join('') +
        `L${c.sx(pts[pts.length - 1].x)},${c.sy(yDom.min)}Z`;
      el('path', { d, fill: color, opacity: 0.12 }, plot);
    }
    const d = pts.map((p, j) => `${j ? 'L' : 'M'}${c.sx(p.x).toFixed(2)},${c.sy(p.y).toFixed(2)}`).join('');
    el('path', { d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'stroke-dasharray': s.dash || null }, plot);
    if (s.markers) {
      for (const p of pts) {
        if (p.marker === false) continue;
        el('circle', { cx: c.sx(p.x), cy: c.sy(p.y), r: 4.5, fill: color, stroke: 'var(--surface-1)', 'stroke-width': 2 }, plot);
      }
    }
    // direct label at the end of the trace, skipped when it would collide with
    // one already placed (the legend still carries the identity)
    if (series.length <= 4 && opts.directLabels !== false && pts.length) {
      const last = pts[pts.length - 1];
      const ly = c.sy(last.y) - 6;
      if (!labelRows.some((r) => Math.abs(r - ly) < 13)) {
        labelRows.push(ly);
        const tx = Math.min(c.sx(last.x) + 6, c.m.l + c.iw - 2);
        const t = el('text', { x: tx, y: ly, class: 'direct-label', 'text-anchor': 'end' }, c.g);
        t.textContent = s.name;
        t.setAttribute('fill', 'var(--text-secondary)');
      }
    }
  });

  // crosshair + tooltip
  const cross = el('line', { class: 'crosshair', y1: c.m.t, y2: c.m.t + c.ih, x1: 0, x2: 0, opacity: 0 }, c.g);
  const dots = series.map((s, i) => el('circle', {
    r: 5, fill: s.color || SERIES_VARS[i % SERIES_VARS.length],
    stroke: 'var(--surface-1)', 'stroke-width': 2, opacity: 0,
  }, c.g));
  const hit = el('rect', { x: c.m.l, y: c.m.t, width: c.iw, height: c.ih, fill: 'transparent' }, c.g);
  const inv = (px) => {
    if (opts.xLog) {
      const l0 = Math.log10(xDom.min), l1 = Math.log10(xDom.max);
      return Math.pow(10, l0 + ((px - c.m.l) / c.iw) * (l1 - l0));
    }
    return xDom.min + ((px - c.m.l) / c.iw) * (xDom.max - xDom.min);
  };
  hit.addEventListener('pointermove', (ev) => {
    const r = c.svg.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * c.width;
    const xv = inv(px);
    let rows = '';
    series.forEach((s, i) => {
      let best = null, bd = Infinity;
      for (const p of s.points) {
        const d = Math.abs(p.x - xv);
        if (d < bd && Number.isFinite(p.y)) { bd = d; best = p; }
      }
      if (!best) { dots[i].setAttribute('opacity', 0); return; }
      dots[i].setAttribute('cx', c.sx(best.x));
      dots[i].setAttribute('cy', c.sy(best.y));
      dots[i].setAttribute('opacity', 1);
      rows += `<div class="tip-row"><span class="tip-sw" style="background:${s.color || SERIES_VARS[i % SERIES_VARS.length]}"></span>${s.name}<b>${opts.tipFmt ? opts.tipFmt(best) : fmt(best.y, 4)}</b></div>`;
    });
    cross.setAttribute('x1', c.sx(xv)); cross.setAttribute('x2', c.sx(xv));
    cross.setAttribute('opacity', 1);
    c.showTip(`<div class="tip-head">${opts.xFmt ? opts.xFmt(xv) : fmt(xv, 4)}${opts.xUnit ? ' ' + opts.xUnit : ''}</div>${rows}`, px, c.m.t + 10);
  });
  hit.addEventListener('pointerleave', () => {
    cross.setAttribute('opacity', 0);
    dots.forEach((d) => d.setAttribute('opacity', 0));
    c.hideTip();
  });

  c.legend(series.map((s, i) => ({ label: s.name, color: s.color || SERIES_VARS[i % SERIES_VARS.length] })));
  if (opts.table !== false) {
    const xsAll = [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))].sort((a, b) => a - b);
    const step = Math.max(1, Math.ceil(xsAll.length / 24));
    const rows = xsAll.filter((_, i) => i % step === 0).map((x) => [
      opts.xFmt ? opts.xFmt(x) : fmt(x, 4),
      ...series.map((s) => {
        const p = s.points.reduce((a, b) => (Math.abs(b.x - x) < Math.abs(a.x - x) ? b : a), s.points[0]);
        return fmt(p.y, 4);
      }),
    ]);
    c.table([opts.xLabel || 'x', ...series.map((s) => s.name)], rows);
  }
  c.note(opts.note);
  return c;
}

/* ---------------------------------------------------------------- bar chart */

/**
 * @param items [{ label, value, color?, highlight?, sub? }]
 */
export function barChart(host, opts) {
  const c = new Chart(host, Object.assign({ margin: { t: 26, r: 18, b: 74, l: 62 } }, opts));
  const items = opts.items;
  const vals = items.map((d) => d.value).filter(Number.isFinite);
  const yr = niceTicks(Math.min(0, ...vals), Math.max(...vals) * 1.12, 6);
  const yDom = opts.yDomain || { min: yr.min, max: yr.max };
  c.axes({ x: { min: 0, max: items.length }, y: yDom, yLabel: opts.yLabel, xTicksOverride: [] });

  for (const r of opts.hlines || []) {
    const y = c.sy(r.y);
    el('line', { x1: c.m.l, x2: c.m.l + c.iw, y1: y, y2: y, class: 'ref-line spec' }, c.g);
    if (r.label) refLabel(c.g, c.m.l + c.iw - 4, y - 6, r.label, 'end');
  }

  const bw = c.iw / items.length;
  const pad = Math.min(bw * 0.22, 14);
  const zero = c.sy(Math.max(yDom.min, 0));
  items.forEach((d, i) => {
    const x = c.m.l + i * bw + pad / 2 + 1;      // +1 = 2px surface gap between bars
    const w = bw - pad - 2;
    const y = c.sy(d.value);
    const up = d.value >= 0;
    const hgt = Math.abs(y - zero);
    const color = d.color || (d.highlight ? 'var(--series-3)' : 'var(--series-1)');
    const g = el('g', { class: 'bar-g' }, c.g);
    el('rect', {
      x, y: up ? y : zero, width: Math.max(w, 1), height: Math.max(hgt, 1),
      fill: color, rx: 4, ry: 4,
    }, g);
    // square off the baseline end so only the data end is rounded
    el('rect', { x, y: up ? zero - 4 : zero, width: Math.max(w, 1), height: 4, fill: color }, g);
    el('text', {
      x: x + w / 2, y: up ? y - 7 : zero + hgt + 15, class: 'bar-value',
    }, g).textContent = opts.valueFmt ? opts.valueFmt(d.value) : fmt(d.value, 3);

    const label = el('text', { x: x + w / 2, y: c.m.t + c.ih + 16, class: 'bar-label' }, c.g);
    const words = String(d.label).split(/\s+/);
    let line = '', lines = [];
    for (const wd of words) {
      if ((line + ' ' + wd).trim().length > Math.max(8, Math.floor(w / 5.6))) { lines.push(line.trim()); line = wd; }
      else line = (line + ' ' + wd).trim();
    }
    lines.push(line);
    lines.slice(0, 3).forEach((ln, k) => {
      el('tspan', { x: x + w / 2, dy: k === 0 ? 0 : 11 }, label).textContent = ln;
    });

    g.addEventListener('pointerenter', () => {
      c.showTip(`<div class="tip-head">${d.label}</div><div class="tip-row">${opts.yLabel || 'value'}<b>${opts.valueFmt ? opts.valueFmt(d.value) : fmt(d.value, 4)}</b></div>${d.sub ? `<div class="tip-sub">${d.sub}</div>` : ''}`, x + w / 2, y);
    });
    g.addEventListener('pointerleave', () => c.hideTip());
  });

  if (opts.table !== false) {
    c.table([opts.xLabel || 'Item', opts.yLabel || 'Value'],
      items.map((d) => [d.label, (opts.valueFmt ? opts.valueFmt(d.value) : fmt(d.value, 4))]));
  }
  c.note(opts.note);
  return c;
}

/* --------------------------------------------------------- horizontal bars */

/**
 * Horizontal bar chart - the right form for a profile of named 0..100 scores,
 * where the labels are words and the comparison is between rows.
 * @param items [{ label, value, note?, color?, reference? }]
 */
export function hBarChart(host, opts) {
  const items = opts.items;
  const rowH = opts.rowH || 30;
  const height = items.length * rowH + 46;
  const c = new Chart(host, Object.assign({}, opts, {
    height, margin: { t: 18, r: 66, b: 46, l: opts.labelWidth || 150 },
  }));
  const max = opts.max ?? Math.max(100, ...items.map((d) => d.value));
  c.axes({
    x: { min: 0, max }, y: { min: 0, max: items.length },
    xLabel: opts.xLabel, xFmt: opts.xFmt, yTickCount: 0,
  });
  // the y axis here is categorical, so drop the numeric ticks the scaffold drew
  c.g.querySelectorAll('.tick-y').forEach((n) => n.remove());

  items.forEach((d, i) => {
    const y = c.m.t + i * rowH + 5;
    const bh = rowH - 12;
    const w = Math.max((clampNum(d.value, 0, max) / max) * c.iw, 2);
    const g = el('g', {}, c.g);
    el('rect', { x: c.m.l, y, width: c.iw, height: bh, fill: 'var(--surface-2)', rx: 4 }, g);
    el('rect', { x: c.m.l, y, width: w, height: bh, fill: d.color || 'var(--series-1)', rx: 4 }, g);
    if (w > 8) el('rect', { x: c.m.l, y, width: 4, height: bh, fill: d.color || 'var(--series-1)' }, g);
    el('text', { x: c.m.l - 10, y: y + bh / 2 + 4, class: 'tick', 'text-anchor': 'end' }, g).textContent = d.label;
    // The bar length carries the relative standing; the printed label carries
    // the real quantity, because "5.5 %" is what the engineer needs to read,
    // not "ranked lowest of seven".
    const text = d.display ?? (opts.valueFmt ? opts.valueFmt(d.value) : d.value.toFixed(0));
    const inside = w > c.iw * 0.55;
    el('text', {
      x: inside ? c.m.l + w - 8 : c.m.l + w + 11, y: y + bh / 2 + 4,
      class: 'bar-value', 'text-anchor': inside ? 'end' : 'start',
      fill: inside ? 'var(--surface-1)' : 'var(--text-primary)',
    }, g).textContent = text;
    if (Number.isFinite(d.reference)) {
      const rx = c.m.l + (clampNum(d.reference, 0, max) / max) * c.iw;
      el('line', { x1: rx, x2: rx, y1: y - 2, y2: y + bh + 2, class: 'ref-line spec' }, g);
    }
    if (d.note) {
      g.addEventListener('pointerenter', () => c.showTip(
        `<div class="tip-head">${d.label}</div>${d.display ? `<div class="tip-row">value<b>${d.display}</b></div>` : ''}<div class="tip-row">rank score<b>${d.value.toFixed(0)}/100</b></div><div class="tip-sub">${d.note}</div>`,
        c.m.l + w / 2, y));
      g.addEventListener('pointerleave', () => c.hideTip());
    }
  });
  if (opts.table !== false) {
    c.table([opts.labelHeader || 'Attribute', 'Value', 'Relative score'],
      items.map((d) => [d.label, d.display ?? '-', d.value.toFixed(0)]));
  }
  c.note(opts.note);
  return c;
}

const clampNum = (v, lo, hi) => Math.min(hi, Math.max(lo, Number.isFinite(v) ? v : lo));

/* ------------------------------------------------------------ stacked bars */

export function stackedBar(host, opts) {
  const c = new Chart(host, Object.assign({ margin: { t: 26, r: 18, b: 66, l: 62 } }, opts));
  const { categories, series } = opts;  // series: [{name, values:[]}]
  const totals = categories.map((_, i) => series.reduce((a, s) => a + (s.values[i] || 0), 0));
  const yr = niceTicks(0, Math.max(...totals) * 1.1, 6);
  c.axes({ x: { min: 0, max: categories.length }, y: { min: 0, max: yr.max }, yLabel: opts.yLabel, xTicksOverride: [] });

  const bw = c.iw / categories.length;
  const pad = Math.min(bw * 0.3, 22);
  categories.forEach((cat, i) => {
    let acc = 0;
    const x = c.m.l + i * bw + pad / 2;
    const w = bw - pad;
    series.forEach((s, k) => {
      const v = s.values[i] || 0;
      if (v <= 0) return;
      const y0 = c.sy(acc), y1 = c.sy(acc + v);
      const isTop = k === series.length - 1 || series.slice(k + 1).every((z) => !(z.values[i] > 0));
      const g = el('g', {}, c.g);
      el('rect', {
        x, y: y1, width: w, height: Math.max(y0 - y1 - 2, 1),   // 2px surface gap
        fill: SERIES_VARS[k % SERIES_VARS.length],
        rx: isTop ? 4 : 0, ry: isTop ? 4 : 0,
      }, g);
      g.addEventListener('pointerenter', () => c.showTip(
        `<div class="tip-head">${cat}</div><div class="tip-row"><span class="tip-sw" style="background:${SERIES_VARS[k % SERIES_VARS.length]}"></span>${s.name}<b>${fmt(v, 3)}</b></div>`, x + w / 2, y1));
      g.addEventListener('pointerleave', () => c.hideTip());
      acc += v;
    });
    const label = el('text', { x: x + w / 2, y: c.m.t + c.ih + 16, class: 'bar-label' }, c.g);
    String(cat).split(/\s+/).slice(0, 3).forEach((ln, k) => {
      el('tspan', { x: x + w / 2, dy: k === 0 ? 0 : 11 }, label).textContent = ln;
    });
  });
  c.legend(series.map((s, i) => ({ label: s.name, color: SERIES_VARS[i % SERIES_VARS.length] })));
  if (opts.table !== false) {
    c.table([opts.xLabel || 'Category', ...series.map((s) => s.name)],
      categories.map((cat, i) => [cat, ...series.map((s) => fmt(s.values[i], 3))]));
  }
  c.note(opts.note);
  return c;
}

/* ---------------------------------------------------------------- histogram */

export function histogramChart(host, opts) {
  const c = new Chart(host, opts);
  const bins = opts.bins;
  const yr = niceTicks(0, Math.max(...bins.map((b) => b.n)) * 1.1, 5);
  c.axes({
    x: { min: bins[0].x0, max: bins[bins.length - 1].x1 }, y: { min: 0, max: yr.max },
    xLabel: opts.xLabel, yLabel: opts.yLabel || 'count', xFmt: opts.xFmt,
  });
  for (const b of opts.bands || []) {
    el('rect', { x: c.sx(b.from), y: c.m.t, width: Math.max(c.sx(b.to) - c.sx(b.from), 1), height: c.ih, class: 'band ok' }, c.g);
    if (b.label) el('text', { x: (c.sx(b.from) + c.sx(b.to)) / 2, y: c.m.t + 13, class: 'band-label' }, c.g).textContent = b.label;
  }
  bins.forEach((b) => {
    if (!b.n) return;
    const x = c.sx(b.x0), w = Math.max(c.sx(b.x1) - c.sx(b.x0) - 2, 1);
    const y = c.sy(b.n);
    const g = el('g', {}, c.g);
    el('rect', { x, y, width: w, height: c.sy(0) - y, fill: b.color || 'var(--series-1)', rx: 3, ry: 3 }, g);
    g.addEventListener('pointerenter', () => c.showTip(
      `<div class="tip-head">${opts.xFmt ? opts.xFmt(b.x0) : fmt(b.x0, 5)} - ${opts.xFmt ? opts.xFmt(b.x1) : fmt(b.x1, 5)}</div><div class="tip-row">count<b>${b.n}</b></div>`, x + w / 2, y));
    g.addEventListener('pointerleave', () => c.hideTip());
  });
  for (const r of opts.vlines || []) {
    const x = c.sx(r.x);
    el('line', { x1: x, x2: x, y1: c.m.t, y2: c.m.t + c.ih, class: `ref-line ${r.kind || ''}` }, c.g);
    if (r.label) refLabel(c.g, x, c.m.t + c.ih - 6, r.label, 'middle');
  }
  c.note(opts.note);
  return c;
}

/* -------------------------------------------------------------- polar plot */

/** Radiation-pattern polar plot, dB scale from `floor` to 0 (+peak). */
export function polarChart(host, opts) {
  const size = opts.size || 340;
  host.innerHTML = '';
  host.classList.add('chart-host');
  if (opts.title) {
    const head = h('div', { class: 'chart-head' }, host);
    h('div', { class: 'chart-title', text: opts.title }, head);
    if (opts.subtitle) h('div', { class: 'chart-sub', text: opts.subtitle }, head);
  }
  const wrap = h('div', { class: 'chart-wrap' }, host);
  const svg = el('svg', { viewBox: `0 0 ${size} ${size}`, class: 'chart-svg', role: 'img', 'aria-label': opts.title || 'polar pattern' }, wrap);
  const tip = h('div', { class: 'chart-tip' }, wrap);
  tip.style.display = 'none';
  const cx = size / 2, cy = size / 2, R = size / 2 - 30;
  const floor = opts.floor ?? -40;
  const rOf = (db) => R * Math.max(0, (Math.max(db, floor) - floor) / (0 - floor));
  const pt = (deg, db) => {
    const a = ((deg - 90) * Math.PI) / 180;
    return [cx + rOf(db) * Math.cos(a), cy + rOf(db) * Math.sin(a)];
  };

  for (let db = floor; db <= 0; db += 10) {
    el('circle', { cx, cy, r: rOf(db), class: 'polar-grid' }, svg);
    el('text', { x: cx + 3, y: cy - rOf(db) - 3, class: 'polar-tick' }, svg).textContent = `${db}`;
  }
  for (let a = 0; a < 360; a += 30) {
    const [x, y] = pt(a, 0);
    el('line', { x1: cx, y1: cy, x2: x, y2: y, class: 'polar-grid' }, svg);
    const [lx, ly] = (() => { const r = R + 16, rad = ((a - 90) * Math.PI) / 180; return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)]; })();
    el('text', { x: lx, y: ly + 4, class: 'polar-tick', 'text-anchor': 'middle' }, svg).textContent = `${a > 180 ? a - 360 : a}°`;
  }

  (opts.series || []).forEach((s, i) => {
    const color = s.color || SERIES_VARS[i % SERIES_VARS.length];
    const d = s.points.map((p, j) => `${j ? 'L' : 'M'}${pt(p.deg, p.db).join(',')}`).join('') + 'Z';
    el('path', { d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-dasharray': s.dash || null }, svg);
  });

  const hit = el('circle', { cx, cy, r: R, fill: 'transparent' }, svg);
  const marker = el('circle', { r: 5, fill: 'var(--text-primary)', opacity: 0 }, svg);
  hit.addEventListener('pointermove', (ev) => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * size - cx;
    const py = ((ev.clientY - r.top) / r.height) * size - cy;
    let deg = (Math.atan2(py, px) * 180) / Math.PI + 90;
    if (deg > 180) deg -= 360;
    let rows = '';
    (opts.series || []).forEach((s, i) => {
      const p = s.points.reduce((a, b) => (Math.abs(b.deg - deg) < Math.abs(a.deg - deg) ? b : a), s.points[0]);
      rows += `<div class="tip-row"><span class="tip-sw" style="background:${s.color || SERIES_VARS[i % SERIES_VARS.length]}"></span>${s.name}<b>${p.db.toFixed(1)} dB</b></div>`;
      if (i === 0) {
        const [mx, my] = pt(p.deg, p.db);
        marker.setAttribute('cx', mx); marker.setAttribute('cy', my); marker.setAttribute('opacity', 1);
      }
    });
    tip.innerHTML = `<div class="tip-head">${deg.toFixed(0)}°</div>${rows}`;
    tip.style.display = 'block';
    const rect = wrap.getBoundingClientRect();
    tip.style.left = `${Math.min(ev.clientX - rect.left + 12, rect.width - tip.offsetWidth)}px`;
    tip.style.top = `${ev.clientY - rect.top - 10}px`;
  });
  hit.addEventListener('pointerleave', () => { tip.style.display = 'none'; marker.setAttribute('opacity', 0); });

  if ((opts.series || []).length >= 2) {
    const lg = h('div', { class: 'chart-legend' }, host);
    opts.series.forEach((s, i) => {
      const sp = h('span', { class: 'lg-item' }, lg);
      h('span', { class: 'lg-swatch' }, sp).style.background = s.color || SERIES_VARS[i % SERIES_VARS.length];
      h('span', { text: s.name }, sp);
    });
  }
  if (opts.note) h('p', { class: 'chart-note', text: opts.note }, host);
  return { svg };
}

/* -------------------------------------------------------------- Smith chart */

export function smithChart(host, opts) {
  const size = opts.size || 340;
  host.innerHTML = '';
  host.classList.add('chart-host');
  if (opts.title) {
    const head = h('div', { class: 'chart-head' }, host);
    h('div', { class: 'chart-title', text: opts.title }, head);
    if (opts.subtitle) h('div', { class: 'chart-sub', text: opts.subtitle }, head);
  }
  const wrap = h('div', { class: 'chart-wrap' }, host);
  const svg = el('svg', { viewBox: `0 0 ${size} ${size}`, class: 'chart-svg', role: 'img', 'aria-label': 'Smith chart' }, wrap);
  const tip = h('div', { class: 'chart-tip' }, wrap);
  tip.style.display = 'none';
  const cx = size / 2, cy = size / 2, R = size / 2 - 16;
  const map = (gr, gi) => [cx + gr * R, cy - gi * R];

  el('circle', { cx, cy, r: R, class: 'smith-outline' }, svg);
  el('line', { x1: cx - R, x2: cx + R, y1: cy, y2: cy, class: 'smith-grid' }, svg);
  // constant-resistance circles
  for (const r of [0.2, 0.5, 1, 2, 5]) {
    const cR = R / (1 + r), ccx = cx + (r / (1 + r)) * R;
    el('circle', { cx: ccx, cy, r: cR, class: 'smith-grid' }, svg);
  }
  // constant-reactance arcs (clipped to the unit circle)
  const clipId = `sm${Math.random().toString(36).slice(2)}`;
  const cp = el('clipPath', { id: clipId }, svg);
  el('circle', { cx, cy, r: R }, cp);
  const arcs = el('g', { 'clip-path': `url(#${clipId})` }, svg);
  for (const x of [0.2, 0.5, 1, 2, 5]) {
    for (const s of [1, -1]) {
      el('circle', { cx: cx + R, cy: cy - (s * R) / x, r: R / x, class: 'smith-grid' }, arcs);
    }
  }
  // VSWR circles
  (opts.vswrCircles || [2]).forEach((v, i) => {
    const g = (v - 1) / (v + 1);
    el('circle', { cx, cy, r: g * R, class: 'smith-vswr' }, svg);
    // stagger the labels around the circle so they never stack on one another
    const ang = (-60 - i * 42) * Math.PI / 180;
    el('text', {
      x: cx + g * R * Math.cos(ang), y: cy + g * R * Math.sin(ang) - 4,
      class: 'polar-tick', 'text-anchor': 'middle',
    }, svg).textContent = `VSWR ${v}`;
  });

  (opts.traces || []).forEach((t, i) => {
    const color = t.color || SERIES_VARS[i % SERIES_VARS.length];
    const d = t.points.map((p, j) => `${j ? 'L' : 'M'}${map(p.gr, p.gi).join(',')}`).join('');
    el('path', { d, fill: 'none', stroke: color, 'stroke-width': 2 }, svg);
    const mid = t.points[Math.floor(t.points.length / 2)];
    if (mid) {
      const [mx, my] = map(mid.gr, mid.gi);
      el('circle', { cx: mx, cy: my, r: 5, fill: color, stroke: 'var(--surface-1)', 'stroke-width': 2 }, svg);
    }
    const hit = el('path', { d, fill: 'none', stroke: 'transparent', 'stroke-width': 14 }, svg);
    hit.addEventListener('pointermove', (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * size;
      const py = ((ev.clientY - r.top) / r.height) * size;
      let best = t.points[0], bd = Infinity;
      for (const p of t.points) {
        const [x, y] = map(p.gr, p.gi);
        const dd = (x - px) ** 2 + (y - py) ** 2;
        if (dd < bd) { bd = dd; best = p; }
      }
      tip.innerHTML = `<div class="tip-head">${engFreq(best.f)}</div>
        <div class="tip-row">Z<b>${best.R.toFixed(1)} ${best.X >= 0 ? '+' : '-'} j${Math.abs(best.X).toFixed(1)}</b></div>
        <div class="tip-row">VSWR<b>${best.vswr.toFixed(2)}</b></div>
        <div class="tip-row">S11<b>${best.s11.toFixed(1)} dB</b></div>`;
      tip.style.display = 'block';
      const rect = wrap.getBoundingClientRect();
      tip.style.left = `${Math.min(ev.clientX - rect.left + 12, rect.width - tip.offsetWidth)}px`;
      tip.style.top = `${ev.clientY - rect.top - 10}px`;
    });
    hit.addEventListener('pointerleave', () => { tip.style.display = 'none'; });
  });
  if (opts.note) h('p', { class: 'chart-note', text: opts.note }, host);
  return { svg };
}

/* ------------------------------------------------------------ scatter chart */

export function scatterChart(host, opts) {
  const c = new Chart(host, opts);
  const pts = opts.points;
  const xr = niceTicks(Math.min(...pts.map((p) => p.x)), Math.max(...pts.map((p) => p.x)), 6);
  const yr = niceTicks(Math.min(...pts.map((p) => p.y)), Math.max(...pts.map((p) => p.y)), 6);
  c.axes({ x: opts.xDomain || { min: xr.min, max: xr.max }, y: opts.yDomain || { min: yr.min, max: yr.max },
           xLabel: opts.xLabel, yLabel: opts.yLabel, xFmt: opts.xFmt, yFmt: opts.yFmt });
  for (const r of opts.hlines || []) {
    const y = c.sy(r.y);
    el('line', { x1: c.m.l, x2: c.m.l + c.iw, y1: y, y2: y, class: `ref-line ${r.kind || ''}` }, c.g);
    if (r.label) el('text', { x: c.m.l + c.iw - 4, y: y - 5, class: 'ref-label', 'text-anchor': 'end' }, c.g).textContent = r.label;
  }
  const placed = [];   // label collision avoidance
  pts.forEach((p) => {
    const g = el('g', {}, c.g);
    const px = c.sx(p.x), py = c.sy(p.y);
    el('circle', {
      cx: px, cy: py, r: p.r || 6,
      fill: p.color || SERIES_VARS[0], stroke: 'var(--surface-1)', 'stroke-width': 2,
    }, g);
    if (p.label) {
      const wEst = p.label.length * 5.4 + 12;
      // try right of the point, then left, then above; skip if all collide
      const slots = [[px + 10, py + 4, 'start'], [px - 10, py + 4, 'end'], [px, py - 12, 'middle']];
      for (const [lx, ly, anchor] of slots) {
        const x0 = anchor === 'start' ? lx : anchor === 'end' ? lx - wEst : lx - wEst / 2;
        const box = { x0, x1: x0 + wEst, y0: ly - 9, y1: ly + 4 };
        const hits = placed.some((b) => !(box.x1 < b.x0 || box.x0 > b.x1 || box.y1 < b.y0 || box.y0 > b.y1));
        const inside = box.x0 > c.m.l - 30 && box.x1 < c.m.l + c.iw + 30;
        if (!hits && inside) {
          placed.push(box);
          el('text', { x: lx, y: ly, class: 'direct-label', 'text-anchor': anchor }, c.g).textContent = p.label;
          break;
        }
      }
    }
    g.addEventListener('pointerenter', () => c.showTip(
      `<div class="tip-head">${p.label || ''}</div><div class="tip-row">${opts.xLabel}<b>${fmt(p.x, 4)}</b></div><div class="tip-row">${opts.yLabel}<b>${fmt(p.y, 4)}</b></div>${p.sub ? `<div class="tip-sub">${p.sub}</div>` : ''}`,
      c.sx(p.x), c.sy(p.y)));
    g.addEventListener('pointerleave', () => c.hideTip());
  });
  if (opts.table !== false) {
    c.table([opts.pointLabel || 'Point', opts.xLabel || 'x', opts.yLabel || 'y'],
      pts.map((p) => [p.label || '', fmt(p.x, 4), fmt(p.y, 4)]));
  }
  c.note(opts.note);
  return c;
}

export { Chart };
