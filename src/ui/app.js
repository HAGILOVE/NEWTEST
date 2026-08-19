/**
 * Application shell: state, specification form, tab routing.
 */
import { h, engFreq } from './charts.js';
import {
  renderOverview, renderSelected, renderPatch, renderSubstrate, renderGround,
  renderThermal, renderTolerance, renderLink, renderDrawings, renderReport,
} from './panels.js';
import { runDesign, MATERIALS, MATERIAL_BY_ID, CONDUCTORS } from '../core/design.js';
import { BANDS, bandFor, bandFractional } from '../core/bands.js';
import { snapToStock } from '../core/materials.js';

const VERSION = '1.0';

const DEFAULT_SPEC = {
  fGHz: 2.442,
  bandId: 'wifi24',
  materialId: 'fr4',
  stackMode: 'solid',
  hMm: 1.6,
  carrierHMm: 0.8,
  airGapMm: 4.2,
  snapStock: true,
  conductor: 'copper',
  tCuUm: 35,
  roughnessRqUm: 1.0,
  pattern: 'directional',
  polarization: 'linear',
  targetGainDbi: 7,
  bwPct: 3.42,
  groundMm: 70,
  autoGround: false,
  maxDimMm: 120,
  feedType: 'inset',
  feedLossDb: 0.4,
  powerW: 1,
  peakPowerW: 10,
  tAmbC: 25,
  tMinC: -40,
  tMaxC: 85,
  airVelocity: 0,
  emissivity: 0.9,
  altitudeM: 0,
  viaCount: 0,
  lowProfile: false,
  priority: { gain: 1.0, bandwidth: 0.7, size: 0.6, cost: 0.5, simplicity: 0.4 },
};

const TABS = [
  { id: 'overview', label: 'Recommendations', render: renderOverview },
  { id: 'selected', label: 'Antenna detail', render: renderSelected },
  { id: 'patch', label: 'Patch design', render: renderPatch },
  { id: 'substrate', label: 'Substrate trade', render: renderSubstrate },
  { id: 'ground', label: 'Ground plane', render: renderGround },
  { id: 'thermal', label: 'Thermal & power', render: renderThermal },
  { id: 'tolerance', label: 'Tolerance & yield', render: renderTolerance },
  { id: 'link', label: 'Link budget', render: renderLink },
  { id: 'drawings', label: 'Drawings', render: renderDrawings },
  { id: 'report', label: 'Report', render: renderReport },
];

const state = {
  ...structuredClone(DEFAULT_SPEC),
  tab: 'overview',
  selected: null,
  scanDeg: 0,
  showAll: false,
  includeSurfaceWave: true,
  process: 'standard',
  mcSamples: 2500,
  vswrLimit: 2,
  ptxDbm: 20, grxDbi: 2, bwMHz: 20, nfDb: 6, snrDb: 10,
  distanceM: 1000, propModel: 'fspl', rainMmH: 0, humidity: 7.5,
  htM: 10, hrM: 1.5,
  rerender: () => render(),
};

/* ------------------------------------------------------------------ spec */

function toSpec() {
  const mat = MATERIAL_BY_ID[state.materialId];
  return {
    f: state.fGHz * 1e9,
    materialId: state.materialId,
    stackMode: state.stackMode,
    h: state.hMm * 1e-3,
    carrierH: state.carrierHMm * 1e-3,
    airGap: state.airGapMm * 1e-3,
    snapStock: state.snapStock,
    conductor: state.conductor,
    tCu: state.tCuUm * 1e-6,
    roughnessRq: state.roughnessRqUm * 1e-6,
    pattern: state.pattern,
    polarization: state.polarization,
    targetGainDbi: state.targetGainDbi,
    bwPct: state.bwPct,
    groundM: state.autoGround ? null : state.groundMm * 1e-3,
    maxDimM: state.maxDimMm > 0 ? state.maxDimMm * 1e-3 : null,
    feedType: state.feedType,
    feedLossDb: state.feedLossDb,
    powerW: state.powerW,
    peakPowerW: state.peakPowerW,
    tAmbC: state.tAmbC, tMinC: state.tMinC, tMaxC: state.tMaxC,
    airVelocity: state.airVelocity, emissivity: state.emissivity,
    altitudeM: state.altitudeM, viaCount: state.viaCount,
    lowProfile: state.lowProfile,
    priority: state.priority,
    sigma: CONDUCTORS[state.conductor].sigma,
    _material: mat,
  };
}

/* ------------------------------------------------------------------ form */

function field(parent, label, unit, control) {
  const f = h('div', { class: 'field' }, parent);
  h('label', { text: label }, f);
  if (unit) h('span', { class: 'unit', text: unit }, f);
  const wrap = h('div', { style: 'grid-column:1/-1' }, f);
  wrap.appendChild(control);
  return f;
}

function num(key, opts = {}) {
  const i = h('input', { type: 'number', value: String(state[key]), step: opts.step ?? 'any', min: opts.min, max: opts.max });
  i.addEventListener('change', () => {
    const v = parseFloat(i.value);
    if (!Number.isFinite(v)) { i.value = String(state[key]); return; }
    state[key] = opts.clamp ? Math.min(opts.max ?? Infinity, Math.max(opts.min ?? -Infinity, v)) : v;
    i.value = String(state[key]);
    if (opts.after) opts.after();
    render();
  });
  return i;
}

function select(key, options, after) {
  const s = h('select', {});
  for (const o of options) {
    if (o.group) {
      const g = h('optgroup', { label: o.group }, s);
      for (const oo of o.items) h('option', { value: oo.value, text: oo.label, selected: state[key] === oo.value ? 'selected' : null }, g);
    } else {
      h('option', { value: o.value, text: o.label, selected: state[key] === o.value ? 'selected' : null }, s);
    }
  }
  s.value = state[key];
  s.addEventListener('change', () => { state[key] = s.value; if (after) after(); render(); });
  return s;
}

function segmented(key, options, after) {
  const g = h('div', { class: 'seg' });
  for (const o of options) {
    const b = h('button', { text: o.label, type: 'button' }, g);
    b.setAttribute('aria-pressed', String(state[key] === o.value));
    b.addEventListener('click', () => { state[key] = o.value; if (after) after(); render(); });
  }
  return g;
}

function checkbox(key, label, after) {
  const w = h('label', { class: 'row small', style: 'gap:6px;cursor:pointer' });
  const c = h('input', { type: 'checkbox' }, w);
  c.checked = !!state[key];
  h('span', { text: label }, w);
  c.addEventListener('change', () => { state[key] = c.checked; if (after) after(); render(); });
  return w;
}

function buildSidebar(aside) {
  aside.innerHTML = '';

  // On a narrow screen the form stacks above the results, so give the reader a
  // way straight to the output without scrolling the whole specification.
  const jump = h('a', { class: 'jump-results', href: '#panel', text: 'Jump to results ↓' }, aside);
  jump.addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('tabs').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  // --- frequency ---------------------------------------------------------
  const g1 = h('fieldset', { class: 'group' }, aside);
  h('legend', { text: 'Operating frequency' }, g1);
  field(g1, 'Frequency', 'GHz', num('fGHz', { min: 0.03, max: 300, clamp: true, after: () => { state.bandId = (bandFor(state.fGHz * 1e9) || {}).id || 'custom'; } }));
  field(g1, 'Band preset', '', select('bandId', [
    { value: 'custom', label: 'Custom / no preset' },
    ...BANDS.map((b) => ({ value: b.id, label: `${b.name} — ${(b.f0 / 1e9).toFixed(3)} GHz` })),
  ], () => {
    const b = BANDS.find((x) => x.id === state.bandId);
    if (b) { state.fGHz = b.f0 / 1e9; state.bwPct = Math.max(bandFractional(b) * 100, 0.5); }
  }));
  field(g1, 'Required bandwidth (VSWR 2:1)', '%', num('bwPct', { min: 0, max: 200 }));
  const bandNow = bandFor(state.fGHz * 1e9);
  if (bandNow) h('p', { class: 'small muted', text: `λ₀ = ${(299.792458 / state.fGHz).toFixed(1)} mm · ${bandNow.name}${bandNow.eirpDbm !== null ? ` · EIRP limit ${bandNow.eirpDbm} dBm` : ''}`, style: 'margin:2px 0 0' }, g1);

  // --- requirement -------------------------------------------------------
  const g2 = h('fieldset', { class: 'group' }, aside);
  h('legend', { text: 'Performance requirement' }, g2);
  field(g2, 'Target realized gain', 'dBi', num('targetGainDbi', { min: -10, max: 60 }));
  field(g2, 'Radiation pattern', '', segmented('pattern', [
    { value: 'directional', label: 'Directional' },
    { value: 'omni', label: 'Omni' },
    { value: 'hemispheric', label: 'Hemispheric' },
    { value: 'steerable', label: 'Steerable' },
  ]));
  field(g2, 'Polarisation', '', segmented('polarization', [
    { value: 'linear', label: 'Linear' },
    { value: 'circular', label: 'Circular' },
    { value: 'any', label: 'Any' },
  ]));
  field(g2, 'Max envelope dimension', 'mm', num('maxDimMm', { min: 0 }));
  g2.appendChild(checkbox('lowProfile', 'Must be low-profile (no vertical volume)'));

  // --- substrate ---------------------------------------------------------
  const g3 = h('fieldset', { class: 'group' }, aside);
  h('legend', { text: 'Dielectric & stack-up' }, g3);
  const families = [...new Set(MATERIALS.map((m) => m.family))];
  field(g3, 'Material', '', select('materialId', families.map((fam) => ({
    group: fam,
    items: MATERIALS.filter((m) => m.family === fam).map((m) => ({ value: m.id, label: `${m.name} — εr ${m.er}, Df ${m.df}` })),
  })), () => {
    const m = MATERIAL_BY_ID[state.materialId];
    if (m.stock && m.stock.length) state.hMm = snapToStock(m, state.hMm * 1e-3) * 1e3;
  }));
  const mat = MATERIAL_BY_ID[state.materialId];
  h('p', { class: 'small muted', text: mat.notes, style: 'margin:2px 0 8px' }, g3);
  field(g3, 'Stack-up', '', segmented('stackMode', [
    { value: 'solid', label: 'Solid substrate' },
    { value: 'airgap', label: 'Carrier + air gap' },
  ]));
  if (state.stackMode === 'solid') {
    field(g3, 'Substrate thickness', 'mm', num('hMm', { min: 0.02, max: 30 }));
    if (mat.stock && mat.stock.length) {
      const row = h('div', { class: 'row', style: 'margin:-4px 0 8px' }, g3);
      h('span', { class: 'small muted', text: 'Stock:' }, row);
      mat.stock.forEach((s) => {
        const b = h('button', { text: (s * 1e3).toFixed(s * 1e3 < 1 ? 3 : 2), style: 'padding:2px 6px;font-size:11px' }, row);
        if (Math.abs(s * 1e3 - state.hMm) < 1e-4) b.classList.add('primary');
        b.addEventListener('click', () => { state.hMm = s * 1e3; render(); });
      });
    }
  } else {
    field(g3, 'Carrier PCB thickness', 'mm', num('carrierHMm', { min: 0.05, max: 3 }));
    field(g3, 'Air gap', 'mm', num('airGapMm', { min: 0.2, max: 40 }));
  }
  field(g3, 'Conductor', '', select('conductor', Object.entries(CONDUCTORS).map(([k, v]) => ({ value: k, label: `${v.name} — σ ${(v.sigma / 1e7).toFixed(2)}e7 S/m` }))));
  field(g3, 'Copper thickness', 'µm', num('tCuUm', { min: 5, max: 200 }));
  field(g3, 'Surface roughness Rq', 'µm', num('roughnessRqUm', { min: 0.1, max: 8, step: 0.1 }));

  // --- ground / feed -----------------------------------------------------
  const g4 = h('fieldset', { class: 'group' }, aside);
  h('legend', { text: 'Ground plane & feed' }, g4);
  g4.appendChild(checkbox('autoGround', 'Size the ground plane automatically'));
  if (!state.autoGround) field(g4, 'Ground plane (square)', 'mm', num('groundMm', { min: 5, max: 3000 }));
  field(g4, 'Feed type', '', select('feedType', [
    { value: 'inset', label: 'Inset microstrip feed' },
    { value: 'quarterWave', label: 'Quarter-wave transformer' },
    { value: 'probe', label: 'Coaxial probe' },
    { value: 'apertureCoupled', label: 'Aperture (slot) coupled' },
  ]));
  field(g4, 'Feed / connector loss allowance', 'dB', num('feedLossDb', { min: 0, max: 6, step: 0.1 }));

  // --- power / thermal ---------------------------------------------------
  const g5 = h('fieldset', { class: 'group' }, aside);
  h('legend', { text: 'Power & environment' }, g5);
  field(g5, 'Average RF power', 'W', num('powerW', { min: 0.001, max: 5000 }));
  field(g5, 'Peak RF power', 'W', num('peakPowerW', { min: 0.001, max: 100000 }));
  field(g5, 'Ambient temperature', '°C', num('tAmbC', { min: -60, max: 150 }));
  field(g5, 'Operating range min / max', '°C', (() => {
    const w = h('div', { class: 'row' });
    w.appendChild(num('tMinC', { min: -100, max: 50 }));
    w.appendChild(num('tMaxC', { min: 0, max: 300 }));
    return w;
  })());
  field(g5, 'Air velocity', 'm/s', num('airVelocity', { min: 0, max: 30, step: 0.5 }));
  field(g5, 'Surface emissivity', '', num('emissivity', { min: 0.02, max: 1, step: 0.05 }));
  field(g5, 'Altitude', 'm', num('altitudeM', { min: 0, max: 40000, step: 500 }));
  field(g5, 'Thermal vias under the patch', '', num('viaCount', { min: 0, max: 500, step: 1 }));

  // --- priorities --------------------------------------------------------
  const g6 = h('fieldset', { class: 'group' }, aside);
  h('legend', { text: 'Ranking priorities' }, g6);
  for (const [k, label] of [['gain', 'Gain'], ['bandwidth', 'Bandwidth'], ['size', 'Compactness'], ['cost', 'Low cost'], ['simplicity', 'Simple build']]) {
    const row = h('div', { class: 'slider-row' }, g6);
    h('span', { text: label }, row);
    const r = h('input', { type: 'range', min: '0', max: '1.5', step: '0.05', value: String(state.priority[k]) }, row);
    const v = h('span', { class: 'v', text: state.priority[k].toFixed(2) }, row);
    r.addEventListener('input', () => { v.textContent = parseFloat(r.value).toFixed(2); });
    r.addEventListener('change', () => { state.priority[k] = parseFloat(r.value); render(); });
  }

  const reset = h('button', { text: 'Reset to defaults', style: 'width:100%;margin-top:6px' }, aside);
  reset.addEventListener('click', () => { Object.assign(state, structuredClone(DEFAULT_SPEC)); render(); });
}

/* --------------------------------------------------------------- render */

let lastDesign = null;

export function render() {
  const spec = toSpec();
  let D;
  try {
    D = runDesign(spec);
    lastDesign = D;
  } catch (err) {
    console.error(err);
    D = lastDesign;
    if (!D) return;
  }
  if (state.autoGround) state.groundMm = D.groundM * 1e3;

  buildSidebar(document.getElementById('spec'));

  // header stats
  const hs = document.getElementById('hdr-stats');
  hs.innerHTML = '';
  const stat = (k, v, title) => {
    const s = h('span', { class: 'hdr-stat', title: title || '' }, hs);
    s.textContent = k + ' ';
    h('b', { text: v }, s);
  };
  const bestC = D.recommendation.candidates[0];
  stat('λ₀', `${(D.lambda0 * 1e3).toFixed(1)} mm`, 'free-space wavelength at the design frequency');
  stat('best', `${bestC.realizedGainDbi.toFixed(2)} dBi`, `top-ranked candidate: ${bestC.arch.name}`);
  stat('patch on this stack', `${D.realizedGainDbi.toFixed(2)} dBi`,
    'realized gain of a plain rectangular patch on the substrate currently selected in the sidebar');
  stat('η', `${(D.sol.etaSpace * 100).toFixed(0)} %`, 'radiation efficiency of that patch');
  stat('BW', `${(D.sol.fbw2 * 100).toFixed(2)} %`, 'VSWR 2:1 bandwidth of that patch');
  stat('size', `${(D.sol.W * 1e3).toFixed(1)}×${(D.sol.L * 1e3).toFixed(1)} mm`, 'patch dimensions');

  // tabs
  const tabsEl = document.getElementById('tabs');
  tabsEl.innerHTML = '';
  for (const t of TABS) {
    const b = h('button', { text: t.label, role: 'tab' }, tabsEl);
    b.setAttribute('aria-selected', String(state.tab === t.id));
    b.addEventListener('click', () => { state.tab = t.id; render(); window.scrollTo({ top: 0 }); });
  }

  const work = document.getElementById('panel');
  work.innerHTML = '';
  const tab = TABS.find((t) => t.id === state.tab) || TABS[0];
  try {
    tab.render(work, D, state);
  } catch (err) {
    console.error(err);
    const c = h('div', { class: 'callout bad' }, work);
    h('b', { text: 'Panel failed to render' }, c);
    h('pre', { class: 'small', text: String(err && err.stack ? err.stack : err) }, c);
  }
}

/* ----------------------------------------------------------------- boot */

export function boot() {
  const app = document.getElementById('app-root');
  app.innerHTML = `
    <header class="app-bar">
      <div class="brand">
        <h1>RF Antenna Studio</h1>
        <span class="ver">v${VERSION} · analytic design &amp; trade-study engine</span>
      </div>
      <div id="hdr-stats" class="row"></div>
      <span class="spacer"></span>
      <button id="theme-btn" title="Toggle colour theme">Theme</button>
    </header>
    <div class="app">
      <aside class="spec" id="spec"></aside>
      <main class="work">
        <div class="tabs" id="tabs" role="tablist"></div>
        <div id="panel"></div>
      </main>
    </div>`;

  const tb = document.getElementById('theme-btn');
  tb.addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme');
    const next = cur === 'dark' ? 'light' : cur === 'light' ? null : 'dark';
    if (next) document.documentElement.setAttribute('data-theme', next);
    else document.documentElement.removeAttribute('data-theme');
    try { localStorage.setItem('rfas-theme', next || ''); } catch (e) { /* ignore */ }
    render();
  });
  try {
    const saved = localStorage.getItem('rfas-theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
  } catch (e) { /* ignore */ }

  render();
  window.addEventListener('resize', debounce(render, 250));
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export { state, TABS };
