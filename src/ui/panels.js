/**
 * Tab panel renderers. Each takes the container and the current design result.
 */
import { h, el, lineChart, barChart, hBarChart, stackedBar, histogramChart, heatmap, polarChart, smithChart, scatterChart, fmt, engFreq, SERIES_VARS } from './charts.js';
import { stackupDiagram, planView, arrayLayout } from './diagrams.js';
import { antennaDrawing } from './antennaArt.js';
import { patternFor, responseVsFrequency } from '../core/patterns.js';
import {
  thicknessSweep, permittivitySweep, substrateTrade,
  monteCarlo, MATERIALS, MATERIAL_BY_ID, solvePatch, toDB, fromDB, C0, CONDUCTORS,
} from '../core/design.js';
import { groundResponse, groundModeFor, groundPlaneEffect, monopoleGround } from '../core/ground.js';
import { linkBudget, maxRange, gaseousAttenuation, rainAttenuation, fspl, fresnelRadius, mpeDistance, noiseFloorDbm } from '../core/propagation.js';
import { solveThermal, frequencyDrift, paschenVoltage, pulsedRise, traceCurrentLimit, feedCurrent } from '../core/thermal.js';
import { BANDS, bandFractional } from '../core/bands.js';
import { PROCESS_CLASSES, defaultDkTolerance } from '../core/tolerance.js';
import { dispersiveEr } from '../core/materials.js';
import { skinDepth, surfaceResistance } from '../core/constants.js';
import { synthesizeWidth, epsEffStatic, lineLossDbPerM } from '../core/microstrip.js';
import { chuQ, harringtonDirectivity, effectiveAperture } from '../core/limits.js';

/* ------------------------------------------------------------- ui helpers */

export const card = (parent, title, lede) => {
  const c = h('section', { class: 'card' }, parent);
  if (title) h('h2', { text: title }, c);
  if (lede) h('p', { class: 'lede', text: lede }, c);
  return c;
};

export const tile = (parent, k, v, unit, sub, cls = '') => {
  const t = h('div', { class: `tile ${cls}` }, parent);
  h('div', { class: 'k', text: k }, t);
  const vv = h('div', { class: 'v' }, t);
  vv.textContent = v;
  if (unit) h('small', { text: unit }, vv);
  if (sub) h('div', { class: 's', text: sub }, t);
  return t;
};

export const dataTable = (parent, cols, rows) => {
  const wrap = h('div', { class: 'table-scroll' }, parent);
  const t = h('table', { class: 'data' }, wrap);
  const tr = h('tr', {}, h('thead', {}, t));
  cols.forEach((c) => h('th', { text: c }, tr));
  const tb = h('tbody', {}, t);
  rows.forEach((r) => {
    const rr = h('tr', {}, tb);
    r.forEach((cell) => {
      const td = h('td', {}, rr);
      if (cell && typeof cell === 'object' && cell.html) td.innerHTML = cell.html;
      else td.textContent = String(cell);
    });
  });
  return t;
};

export const callout = (parent, kind, title, body) => {
  const c = h('div', { class: `callout ${kind}` }, parent);
  h('span', { class: 'ico', text: kind === 'good' ? '✓' : kind === 'bad' ? '✕' : '!' }, c);
  const d = h('div', {}, c);
  h('b', { text: title }, d);
  if (body) h('div', { class: 'small', text: body, style: 'margin-top:3px' }, d);
  return c;
};

const chartBox = (parent) => h('div', {}, parent);

/** Compact inline numeric/select controls for panel-local parameters. */
export function controlRow(parent, state, controls) {
  const bar = h('div', { class: 'ctrl-row' }, parent);
  for (const c of controls) {
    const w = h('label', { class: 'ctrl' }, bar);
    h('span', { text: c.label }, w);
    if (c.options) {
      const sel = h('select', {}, w);
      c.options.forEach((o) => h('option', { value: o.value, text: o.label, selected: state[c.key] === o.value ? 'selected' : null }, sel));
      sel.value = state[c.key];
      sel.addEventListener('change', () => { state[c.key] = sel.value; state.rerender(); });
    } else {
      const i = h('input', { type: 'number', value: String(state[c.key] ?? c.def), step: c.step ?? 'any', min: c.min, max: c.max }, w);
      i.addEventListener('change', () => {
        const v = parseFloat(i.value);
        if (Number.isFinite(v)) { state[c.key] = v; state.rerender(); }
      });
      if (c.unit) h('span', { class: 'ctrl-unit', text: c.unit }, w);
    }
  }
  return bar;
}
const mm = (x) => `${(x * 1e3).toFixed(2)} mm`;

/* ================================================================ OVERVIEW */

export function renderOverview(root, D, state) {
  const rec = D.recommendation;
  const lim = D.limits;

  // ---- feasibility gate ---------------------------------------------------
  if (!lim.feasible) {
    for (const iss of lim.issues) callout(root, 'bad', 'Specification violates a fundamental limit', iss.message);
  } else if (lim.electricallySmall) {
    callout(root, 'warn', `Electrically small envelope (ka = ${lim.ka.toFixed(2)})`,
      `The Chu-McLean bound caps the VSWR-2 bandwidth at ${(lim.chuBandwidth * 100).toFixed(1)} % for this size at ${engFreq(D.spec.f)}. Efficiency and bandwidth are traded against volume here, not against cleverness.`);
  } else {
    callout(root, 'good', 'Specification is physically achievable',
      `A ${(D.spec.maxDimM ? D.spec.maxDimM * 1e3 : Math.max(D.groundXM, D.groundYM) * 1e3).toFixed(0)} mm envelope supports up to ${lim.harringtonGainDbi.toFixed(1)} dBi (Harrington normal-gain limit) and ${(lim.chuBandwidth * 100).toFixed(0)} % bandwidth at ${engFreq(D.spec.f)}.`);
  }

  // ---- headline tiles -----------------------------------------------------
  const tl = h('div', { class: 'tiles' }, root);
  const best = rec.candidates[0];
  tile(tl, 'Wavelength λ₀', (D.lambda0 * 1e3).toFixed(1), 'mm', `${engFreq(D.spec.f)}${D.band ? ' · ' + D.band.name : ''}`);
  tile(tl, 'Best candidate', best.realizedGainDbi.toFixed(1), 'dBi', best.arch.name,
    best.realizedGainDbi >= D.spec.targetGainDbi ? 'good' : 'warn');
  tile(tl, 'Target gain', D.spec.targetGainDbi.toFixed(1), 'dBi',
    `${(best.realizedGainDbi - D.spec.targetGainDbi >= 0 ? '+' : '')}${(best.realizedGainDbi - D.spec.targetGainDbi).toFixed(1)} dB margin`);
  tile(tl, 'Harrington limit', lim.harringtonGainDbi.toFixed(1), 'dBi', `ka = ${lim.ka.toFixed(2)}`);
  tile(tl, 'Chu max BW', (lim.chuBandwidth * 100).toFixed(1), '%', `VSWR 2:1, η = ${(D.sol.etaSpace * 100).toFixed(0)} %`);
  const viable = rec.candidates.filter((c) => c.verdict !== 'rejected' && c.verdict !== 'error');
  const meetsGain = viable.filter((c) => c.verdict === 'recommended');
  tile(tl, 'Viable candidates', String(viable.length), `/ ${rec.candidates.length}`,
    `${meetsGain.length} meet the gain target · ${rec.candidates.length - viable.length} rejected outright`);

  // ---- ranked candidates --------------------------------------------------
  const c1 = card(root, 'Recommended antenna types',
    'Every archetype is evaluated with the same physics engine under your specification. Ranking combines gain margin, bandwidth, footprint, cost and build complexity using the priority weights in the sidebar.');

  const shown = rec.candidates.filter((c) => c.verdict !== 'error');
  const passing = viable;
  const rejected = shown.filter((c) => c.verdict === 'rejected');

  passing.slice(0, state.showAll ? 99 : 6).forEach((c, i) => renderCandidate(c1, c, i, D, state));

  if (passing.length > 6) {
    const b = h('button', { text: state.showAll ? 'Show fewer' : `Show all ${passing.length} viable candidates` }, c1);
    b.addEventListener('click', () => { state.showAll = !state.showAll; state.rerender(); });
  }

  if (rejected.length) {
    const det = h('details', { class: 'info' }, c1);
    h('summary', { text: `${rejected.length} candidates rejected — reasons` }, det);
    const body = h('div', { class: 'body' }, det);
    dataTable(body, ['Antenna type', 'Realized gain', 'Blocking reason'],
      rejected.map((c) => [c.arch.name, `${c.realizedGainDbi.toFixed(1)} dBi`, c.blockers[0] || '-']));
    h('p', { class: 'chart-note', text: 'A rejected type can still be inspected — pick it from the selector on the Antenna detail tab.' }, body);
  }

  // ---- comparison chart ---------------------------------------------------
  const c2 = card(root, 'Candidate comparison — realized gain against the specification',
    'Bars are the computed realized gain including efficiency, ground-plane truncation and feed loss. The dashed line is your target.');
  barChart(chartBox(c2), {
    height: 320,
    items: passing.slice(0, 9).map((c) => ({
      label: c.arch.name.replace(/ \(.*\)/, ''),
      value: c.realizedGainDbi,
      highlight: c === best,
      color: c.realizedGainDbi >= D.spec.targetGainDbi ? 'var(--series-1)' : 'var(--series-2)',
      sub: `${c.bwPct.toFixed(1)} % BW · ${(c.efficiency * 100).toFixed(0)} % efficient · ${Math.max(c.size.w, c.size.l, c.size.h).toFixed(0)} mm max dim`,
    })),
    yLabel: 'realized gain [dBi]',
    valueFmt: (v) => v.toFixed(1),
    hlines: [{ y: D.spec.targetGainDbi, label: `spec ${D.spec.targetGainDbi.toFixed(1)} dBi` }],
    note: 'Blue clears the target; orange falls short. Hover a bar for bandwidth, efficiency and size; click any candidate card above to open its full detail view.',
  });

  // ---- gain vs size scatter ----------------------------------------------
  const c3 = card(root, 'Gain against footprint',
    'The trade every antenna obeys: gain costs aperture. Points above the target line and left of the envelope line satisfy the specification.');
  scatterChart(chartBox(c3), {
    height: 320,
    points: passing.slice(0, 14).map((c, i) => ({
      x: Math.max(c.size.w, c.size.l, c.size.h),
      y: c.realizedGainDbi,
      label: c.arch.name.split(' ').slice(0, 2).join(' '),
      color: SERIES_VARS[i % 3],
      sub: `${c.arch.category} · complexity ${c.arch.complexity}/5`,
    })),
    xLabel: 'largest dimension [mm]', yLabel: 'realized gain [dBi]',
    hlines: [{ y: D.spec.targetGainDbi, label: 'target', kind: 'spec' }],
    note: 'Only the first three categorical hues are used here: all-pairs colour separation is only validated to three slots.',
  });
}

function renderCandidate(parent, c, i, D, state) {
  const box = h('div', { class: `cand ${i === 0 ? 'top' : ''} ${c.verdict === 'rejected' ? 'rejected' : ''}` }, parent);
  box.setAttribute('role', 'button');
  box.setAttribute('tabindex', '0');
  const open = () => { state.selected = c.arch.id; state.tab = 'selected'; state.rerender(); window.scrollTo({ top: 0 }); };
  box.addEventListener('click', (ev) => { if (!ev.target.closest('details, summary, button, a')) open(); });
  box.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(); } });
  const head = h('div', { class: 'cand-head' }, box);
  h('span', { class: 'rank', text: `#${i + 1}` }, head);
  h('h3', { text: c.arch.name }, head);
  if (c.arch.nameKo) h('span', { class: 'ko', text: c.arch.nameKo }, head);
  h('span', { class: 'spacer' }, head);
  const okGain = c.realizedGainDbi >= D.spec.targetGainDbi;
  h('span', { class: `pill ${okGain ? 'good' : 'warn'}`, text: okGain ? 'meets gain' : 'below gain' }, head);
  h('span', { class: 'pill info', text: c.arch.category }, head);

  h('p', { class: 'summary', text: c.arch.summary }, box);
  const openBtn = h('button', { class: 'cand-open', text: 'View pattern, drawing and response →' }, box);
  openBtn.addEventListener('click', (ev) => { ev.stopPropagation(); open(); });

  const m = h('div', { class: 'cand-metrics' }, box);
  const met = (k, v) => { const s = h('span', {}, m); s.textContent = k + ' '; h('b', { text: v }, s); };
  met('gain', `${c.realizedGainDbi.toFixed(1)} dBi`);
  met('η', `${(c.efficiency * 100).toFixed(0)} %`);
  met('BW', `${c.bwPct.toFixed(1)} %`);
  met('size', `${c.size.w.toFixed(0)}×${c.size.l.toFixed(0)}×${c.size.h.toFixed(1)} mm`);
  if (c.beamwidth && c.arch.pattern !== 'omni') met('HPBW', `${c.beamwidth.thetaE.toFixed(0)}°/${c.beamwidth.thetaH.toFixed(0)}°`);
  met('cost', `${'●'.repeat(c.arch.cost)}${'○'.repeat(5 - c.arch.cost)}`);
  met('build', `${'●'.repeat(c.arch.complexity)}${'○'.repeat(5 - c.arch.complexity)}`);

  const ul = h('ul', {}, box);
  [...(c.notes || []), ...c.reasons.slice(0, 2)].slice(0, 4).forEach((n) => h('li', { text: n }, ul));

  if (c.dims && Object.keys(c.dims).length) {
    const det = h('details', { class: 'info' }, box);
    h('summary', { text: 'Synthesised dimensions' }, det);
    const body = h('div', { class: 'body' }, det);
    dataTable(body, ['Parameter', 'Value'],
      Object.entries(c.dims).map(([k, v]) => [k, typeof v === 'number' ? (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)) : v]));
    if (c.count && c.count > 1 && c.arch.category === 'Microstrip' && c.patch) {
      arrayLayout(h('div', { style: 'margin-top:10px' }, body), c.count, 0.7 * D.lambda0 * 1e3, c.patch.W * 1e3, c.patch.L * 1e3);
    }
  }
}

/* ========================================================= ANTENNA DETAIL */

/**
 * Everything about one selected antenna type on a single screen: what it looks
 * like, how it radiates, how it behaves across the band, and where it sits
 * against the alternatives.
 */
export function renderSelected(root, D, state) {
  const cands = D.recommendation.candidates.filter((c) => c.verdict !== 'error');
  const c = cands.find((x) => x.arch.id === state.selected) || cands[0];
  if (!c) { callout(root, 'warn', 'No candidate to show', 'Adjust the specification in the sidebar.'); return; }
  state.selected = c.arch.id;

  // ---- type selector -----------------------------------------------------
  const bar = h('div', { class: 'ctrl-row' }, root);
  const pick = h('label', { class: 'ctrl' }, bar);
  h('span', { text: 'Antenna type' }, pick);
  const sel = h('select', { style: 'width:auto;min-width:min(250px, 100%)' }, pick);
  for (const group of ['recommended', 'marginal', 'rejected']) {
    const inGroup = cands.filter((x) => x.verdict === group);
    if (!inGroup.length) continue;
    const og = h('optgroup', { label: `${group} (${inGroup.length})` }, sel);
    for (const x of inGroup) {
      h('option', { value: x.arch.id, text: `${x.arch.name} — ${x.realizedGainDbi.toFixed(1)} dBi`,
        selected: x.arch.id === c.arch.id ? 'selected' : null }, og);
    }
  }
  sel.value = c.arch.id;
  sel.addEventListener('change', () => { state.selected = sel.value; state.rerender(); });
  const rank = cands.indexOf(c) + 1;
  h('span', { class: `pill ${c.verdict === 'recommended' ? 'good' : c.verdict === 'rejected' ? 'bad' : 'warn'}`,
    text: c.verdict === 'rejected' ? 'rejected' : `ranked #${rank}` }, bar);
  h('span', { class: 'pill info', text: c.arch.category }, bar);
  h('span', { class: 'pill info', text: c.arch.pol.join(' / ') + ' polarisation' }, bar);

  // ---- pattern + response ------------------------------------------------
  const pat = patternFor(c.arch.id, {
    D0: fromDB(c.gainDbi) / Math.max(c.efficiency, 1e-3),
    gainDbi: c.gainDbi,
    count: c.count,
    lambda0: D.lambda0,
    dims: c.dims,
    patch: c.patch ? { Le: c.patch.Le, W: c.patch.W, h: c.patch.h ?? D.stack.h } : null,
    boomLambda: c.dims && c.dims['Boom length'] ? c.dims['Boom length'] / 1e3 / D.lambda0 : null,
    fbDb: c.groundEffect ? c.groundEffect.frontToBackDb : null,
    scanDeg: state.scanDeg ?? 0,
  });
  const resp = responseVsFrequency(c.arch.id, { f0: D.spec.f, bwPct: c.bwPct, gainDbi: c.realizedGainDbi });

  // ---- headline ----------------------------------------------------------
  const tl = h('div', { class: 'tiles' }, root);
  tile(tl, 'Realized gain', c.realizedGainDbi.toFixed(1), 'dBi',
    `target ${D.spec.targetGainDbi.toFixed(1)} dBi · ${(c.realizedGainDbi - D.spec.targetGainDbi >= 0 ? '+' : '')}${(c.realizedGainDbi - D.spec.targetGainDbi).toFixed(1)} dB`,
    c.realizedGainDbi >= D.spec.targetGainDbi ? 'good' : 'warn');
  tile(tl, 'Efficiency', (c.efficiency * 100).toFixed(0), '%', `${toDB(c.efficiency).toFixed(2)} dB of loss`,
    c.efficiency > 0.8 ? 'good' : c.efficiency > 0.5 ? 'warn' : 'bad');
  tile(tl, 'Bandwidth', c.bwPct.toFixed(1), '%', D.spec.bwPct ? `required ${D.spec.bwPct.toFixed(1)} %` : 'VSWR 2:1',
    !D.spec.bwPct || c.bwPct >= D.spec.bwPct ? 'good' : 'warn');
  tile(tl, 'Beamwidth E / H', `${pat.meta.hpbwE.toFixed(0)}° / ${pat.meta.hpbwH >= 360 ? '360' : pat.meta.hpbwH.toFixed(0)}°`, '',
    pat.frame === 'omni' || pat.frame === 'omniHalf' ? 'elevation / azimuth' : 'half-power');
  tile(tl, 'Sidelobe level', pat.meta.sllE <= -55 ? 'none' : pat.meta.sllE.toFixed(1), pat.meta.sllE <= -55 ? '' : 'dB',
    pat.meta.sllE <= -55 ? 'single-lobe pattern' : 'first sidelobe, E-plane');
  tile(tl, 'Front-to-back', pat.meta.fbE >= 39 ? '> 40' : pat.meta.fbE.toFixed(0), 'dB',
    `envelope ${c.size.w.toFixed(0)} × ${c.size.l.toFixed(0)} × ${c.size.h.toFixed(1)} mm`);

  // ---- drawing + patterns ------------------------------------------------
  const c1 = card(root, 'What it looks like, and how it radiates',
    c.arch.summary);
  antennaDrawing(chartBox(c1), c, D);

  const g1 = h('div', { class: 'grid2' }, c1);
  polarChart(chartBox(g1), {
    size: 360, title: 'Radiation pattern — principal planes',
    subtitle: pat.meta.axisLabelE.replace(/ \(.*/, '') + ' and ' + pat.meta.axisLabelH.replace(/ \(.*/, ''),
    floor: -40,
    series: [
      { name: pat.frame === 'omni' || pat.frame === 'omniHalf' ? 'Elevation' : 'E-plane', points: pat.E },
      { name: pat.frame === 'omni' || pat.frame === 'omniHalf' ? 'Azimuth' : 'H-plane', points: pat.H, color: 'var(--series-2)' },
    ],
    note: `0° is the main beam. ${pat.note}`,
  });
  lineChart(chartBox(g1), {
    height: 320, title: 'Pattern cuts in rectangular form',
    subtitle: 'Easier than a polar plot for reading sidelobe levels and beamwidth',
    series: [
      { name: pat.frame.startsWith('omni') ? 'Elevation' : 'E-plane', points: pat.E.map((p) => ({ x: p.deg, y: p.db })) },
      { name: pat.frame.startsWith('omni') ? 'Azimuth' : 'H-plane', points: pat.H.map((p) => ({ x: p.deg, y: p.db })), color: 'var(--series-2)' },
    ],
    xLabel: pat.meta.axisLabelE, yLabel: 'relative level [dB]',
    xDomain: { min: -180, max: 180 }, yDomain: { min: -40, max: 2 },
    xFmt: (v) => `${v.toFixed(0)}°`,
    hlines: [{ y: -3, label: 'half power (−3 dB)', kind: 'good' }],
    tipFmt: (p) => `${p.y.toFixed(1)} dB`,
    directLabels: false,
    note: `Half-power beamwidth ${pat.meta.hpbwE.toFixed(0)}° in the first plane${pat.meta.sllE > -55 ? `, first sidelobe ${pat.meta.sllE.toFixed(1)} dB` : ''}.`,
  });

  if (c.arch.id === 'phasedArray') {
    const sc = h('div', { class: 'ctrl-row' }, c1);
    const w = h('label', { class: 'ctrl' }, sc);
    h('span', { text: 'Scan angle' }, w);
    const r = h('input', { type: 'range', min: '-60', max: '60', step: '5', value: String(state.scanDeg ?? 0), style: 'width:200px' }, w);
    h('span', { class: 'ctrl-unit', text: `${state.scanDeg ?? 0}°` }, w);
    r.addEventListener('change', () => { state.scanDeg = parseFloat(r.value); state.rerender(); });
    h('span', { class: 'small muted', text: 'Steer the beam and watch the main lobe move, broaden by 1/cos(θ), and the grating lobe approach.' }, sc);
  }

  // ---- frequency response ------------------------------------------------
  const c2 = card(root, 'Behaviour across the band',
    'Gain and match against frequency for this type at the computed bandwidth. Resonant types roll off with their loaded Q; travelling-wave and aperture types stay flat and fall off only at the band edges.');
  const g2 = h('div', { class: 'grid2' }, c2);
  const band = D.spec.bwPct ? [D.spec.f * (1 - D.spec.bwPct / 200), D.spec.f * (1 + D.spec.bwPct / 200)] : null;
  lineChart(chartBox(g2), {
    height: 300, title: 'Realized gain',
    series: [{ name: 'gain', points: resp.map((p) => ({ x: p.f, y: p.gain })) }],
    xLabel: 'frequency [GHz]', yLabel: 'realized gain [dBi]',
    xFmt: (v) => (v / 1e9).toFixed(3),
    hlines: [{ y: D.spec.targetGainDbi, label: `target ${D.spec.targetGainDbi.toFixed(1)} dBi`, kind: 'spec' }],
    bands: band ? [{ from: band[0], to: band[1], label: 'required band' }] : [],
    tipFmt: (p) => `${p.y.toFixed(2)} dBi`, directLabels: false,
  });
  lineChart(chartBox(g2), {
    height: 300, title: 'VSWR',
    series: [{ name: 'VSWR', points: resp.map((p) => ({ x: p.f, y: p.vswr })), color: 'var(--series-2)' }],
    xLabel: 'frequency [GHz]', yLabel: 'VSWR',
    xFmt: (v) => (v / 1e9).toFixed(3),
    yDomain: { min: 1, max: 6 },
    hlines: [{ y: 2, label: 'VSWR 2:1', kind: 'good' }],
    bands: band ? [{ from: band[0], to: band[1], label: 'required band' }] : [],
    tipFmt: (p) => p.y.toFixed(2), directLabels: false,
    note: 'Modelled from the computed bandwidth, not measured — use it to compare types, then confirm the winner in a full-wave solver.',
  });

  // ---- profile against the field ----------------------------------------
  const c3 = card(root, 'How this type scores against the alternatives',
    'Bar length is this type\'s standing against every other viable candidate for this specification; the number on the bar is the actual value. The dashed mark is the best competing candidate. A short bar is a trade, not a fault — the whole point of the comparison is to see what each type gives up.');
  const pool = cands.filter((x) => x.verdict !== 'rejected');
  // Bandwidth and size span two orders of magnitude across the archetype
  // library, so a linear normalisation lets one outlier (a 160 % Vivaldi, a
  // 300 mm dish) crush everything else to zero. Those attributes are scored on
  // a log scale; gain is already logarithmic and cost/complexity are ordinal.
  const norm = (val, arr, invert = false, log = false) => {
    const f = log ? (x) => Math.log10(Math.max(x, 1e-3)) : (x) => x;
    const vals = arr.map(f);
    const lo = Math.min(...vals), hi = Math.max(...vals);
    if (hi - lo < 1e-9) return 100;
    const t = (f(val) - lo) / (hi - lo);
    return 100 * (invert ? 1 - t : t);
  };
  const others = pool.filter((x) => x !== c);
  const attrs = [
    { label: 'Gain', get: (x) => x.realizedGainDbi, display: `${c.realizedGainDbi.toFixed(1)} dBi`,
      note: `target is ${D.spec.targetGainDbi.toFixed(1)} dBi` },
    { label: 'Bandwidth', get: (x) => x.bwPct, log: true, display: `${c.bwPct.toFixed(1)} %`,
      note: D.spec.bwPct ? `requirement is ${D.spec.bwPct.toFixed(1)} %, so this ${c.bwPct >= D.spec.bwPct ? 'passes' : 'falls short'}` : 'at VSWR 2:1' },
    { label: 'Efficiency', get: (x) => x.efficiency, display: `${(c.efficiency * 100).toFixed(0)} %`,
      note: `${toDB(c.efficiency).toFixed(2)} dB of the accepted power is lost` },
    { label: 'Compactness', get: (x) => Math.max(x.size.w, x.size.l, x.size.h), invert: true, log: true,
      display: `${Math.max(c.size.w, c.size.l, c.size.h).toFixed(0)} mm`,
      note: `largest dimension, ${(Math.max(c.size.w, c.size.l, c.size.h) / 1e3 / D.lambda0).toFixed(2)} λ₀` },
    { label: 'Low cost', get: (x) => x.arch.cost, invert: true, display: `${c.arch.cost}/5`,
      note: '1 = etched copper only, 5 = machined or actively beamformed' },
    { label: 'Simple build', get: (x) => x.arch.complexity, invert: true, display: `${c.arch.complexity}/5`,
      note: '1 = one etched layer, 5 = multilayer assembly with calibration' },
  ];
  hBarChart(chartBox(c3), {
    items: attrs.map((a) => {
      const all = pool.map(a.get);
      const mine = norm(a.get(c), all, a.invert, a.log);
      const best = others.length ? Math.max(...others.map((x) => norm(a.get(x), all, a.invert, a.log))) : null;
      return { label: a.label, value: mine, reference: best, note: a.note, display: a.display,
               color: mine >= 80 ? 'var(--series-3)' : mine >= 45 ? 'var(--series-1)' : 'var(--series-2)' };
    }),
    xLabel: `relative standing among the ${pool.length} viable candidates`,
    max: 100,
    note: 'Green leads the field, blue is mid-pack, orange trails it. Bandwidth and size are ranked on a log scale so a single wideband or large-aperture outlier does not flatten the rest.',
  });

  // ---- dimensions and notes ---------------------------------------------
  const c4 = card(root, 'Synthesised dimensions and build notes');
  const g4 = h('div', { class: 'grid2' }, c4);
  const dimRows = Object.entries(c.dims || {}).map(([k, v]) =>
    [k, typeof v === 'number' ? (Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(2)) : v]);
  dimRows.push(['Envelope W × L × H', `${c.size.w.toFixed(1)} × ${c.size.l.toFixed(1)} × ${c.size.h.toFixed(1)} mm`]);
  dimRows.push(['Largest dimension in λ₀', (Math.max(c.size.w, c.size.l, c.size.h) / 1e3 / D.lambda0).toFixed(3)]);
  dataTable(h('div', {}, g4), ['Parameter', 'Value'], dimRows);

  const notes = h('div', {}, g4);
  const ul = h('ul', { class: 'ref-list' }, notes);
  [...(c.notes || []), ...(c.reasons || [])].slice(0, 6).forEach((n) => h('li', { text: n }, ul));
  if (c.blockers && c.blockers.length) {
    const w2 = h('div', { style: 'margin-top:10px' }, notes);
    callout(w2, 'bad', 'Why this type was rejected', c.blockers.join(' '));
  }
  h('p', { class: 'chart-note', text: `Pattern model: ${pat.note}` }, notes);

  if (c.count && c.count > 1 && c.patch) {
    const c5 = card(root, 'Element layout');
    arrayLayout(chartBox(c5), c.count, (c.dims.Spacing ?? c.dims.Pitch ?? 0.7 * D.lambda0 * 1e3),
      c.patch.W * 1e3, c.patch.L * 1e3);
  }
}

/* ====================================================== GROUND & PLATFORM */

/**
 * How the selected antenna's gain moves with the size of its ground plane -
 * or, for the types that carry no ground of their own, with its mounting
 * height above a reflecting surface.
 */
export function renderGroundEffect(root, D, state) {
  const cands = D.recommendation.candidates.filter((c) => c.verdict !== 'error');
  const c = cands.find((x) => x.arch.id === state.selected) || cands[0];
  if (!c) { callout(root, 'warn', 'No candidate selected', 'Pick an antenna on the Recommendations tab.'); return; }
  state.selected = c.arch.id;

  // ---- selector ----------------------------------------------------------
  const bar = h('div', { class: 'ctrl-row' }, root);
  const pick = h('label', { class: 'ctrl' }, bar);
  h('span', { text: 'Antenna type' }, pick);
  const sel = h('select', { style: 'width:auto;min-width:min(250px, 100%)' }, pick);
  for (const x of cands) {
    h('option', { value: x.arch.id, text: `${x.arch.name} — ${x.realizedGainDbi.toFixed(1)} dBi`,
      selected: x.arch.id === c.arch.id ? 'selected' : null }, sel);
  }
  sel.value = c.arch.id;
  sel.addEventListener('change', () => { state.selected = sel.value; state.rerender(); });

  const mode = groundModeFor(c.arch.id);
  const MODE_LABEL = {
    plane: 'Image plane — size sets the gain',
    radial: 'Counterpoise — the other half of the antenna',
    chassis: 'Chassis is the radiator',
    disc: 'Backing reflector',
    height: 'No ground of its own — mounting height instead',
  };
  h('span', { class: 'pill info', text: MODE_LABEL[mode] }, bar);

  const radiatorDim = Math.max(c.size.w, c.size.l) / 1e3;
  const radL = c.size.l / 1e3;    // along x, the resonant length -> E-plane
  const radW = c.size.w / 1e3;    // along y, the radiating width -> H-plane
  const vertical = ['monopole', 'collinear', 'biconical'].includes(c.arch.id);
  // the size currently in play: the design ground for planar types, otherwise
  // a sensible default so the marker has somewhere to sit
  // For a rectangular board the meaningful single number for the square sweep
  // is the equal-area square, not either edge.
  const currentSize = mode === 'plane' ? Math.sqrt(D.groundXM * D.groundYM)
    : mode === 'radial' ? (D.spec.maxDimM ? D.spec.maxDimM / 2 : 0.25 * D.lambda0)
    : mode === 'chassis' ? (D.spec.maxDimM || 0.4 * D.lambda0)
    : mode === 'disc' ? 0.8 * D.lambda0
    : 0.25 * D.lambda0;

  const gr = groundResponse(c.arch.id, {
    lambda0: D.lambda0,
    baseGainDbi: mode === 'plane' ? c.gainDbi - (D.spec.feedLossDb || 0) : c.gainDbi,
    radiatorDim,
    surfaceWaveRatio: c.patch ? c.patch.surfaceWaveRatio : 0,
    currentSize, vertical,
  });
  const valid = gr.points.filter((q) => Number.isFinite(q.gainDbi));
  const best = valid.reduce((a, b) => (b.gainDbi > a.gainDbi ? b : a), valid[0]);

  // In plane mode the rectangular section below owns the headline numbers, so
  // the generic square-ground tiles would only repeat them.
  const unit = mode === 'radial' ? 'radius' : mode === 'disc' ? 'diameter' : mode === 'height' ? 'height' : 'edge';
  if (mode === 'plane') {
    renderRectangularGround(root, D, c, { radL, radW });
  }
  const tl = h('div', { class: 'tiles', style: mode === 'plane' ? 'display:none' : '' }, root);
  tile(tl, `Current ${unit}`, (currentSize * 1e3).toFixed(0), 'mm',
    `${(currentSize / D.lambda0).toFixed(2)} λ₀ at ${engFreq(D.spec.f)}`);
  tile(tl, 'Gain there', gr.current ? gr.current.gainDbi.toFixed(2) : 'n/a', gr.current ? 'dBi' : '',
    gr.current
      ? `${(gr.current.gainDbi - D.spec.targetGainDbi >= 0 ? '+' : '')}${(gr.current.gainDbi - D.spec.targetGainDbi).toFixed(1)} dB against target`
      : `the radiator itself is ${(radiatorDim * 1e3).toFixed(0)} mm — it does not fit`,
    gr.current ? (gr.current.gainDbi >= D.spec.targetGainDbi ? 'good' : 'warn') : 'bad');
  tile(tl, `Recommended ${unit}`, (gr.recommended.xMm).toFixed(0), 'mm',
    `${gr.recommended.xLambda.toFixed(2)} λ₀`);
  tile(tl, 'Gain there', gr.recommended.gainDbi.toFixed(2), 'dBi',
    gr.current ? `${(gr.recommended.gainDbi - gr.current.gainDbi >= 0 ? '+' : '')}${(gr.recommended.gainDbi - gr.current.gainDbi).toFixed(2)} dB versus now` : gr.recommended.reason.slice(0, 60));
  tile(tl, 'Best in the sweep', best.gainDbi.toFixed(2), 'dBi', `at ${best.xMm.toFixed(0)} mm (${best.xLambda.toFixed(2)} λ₀)`);
  const secNow = gr.current ? gr.current.secondary : null;
  tile(tl, gr.secondaryLabel.replace(/ \[.*/, ''), secNow === null || !Number.isFinite(secNow) ? 'n/a' : secNow.toFixed(mode === 'chassis' ? 2 : 0),
    mode === 'radial' || mode === 'height' ? '°' : mode === 'chassis' ? '×' : 'dB', 'at the current size');

  if (mode === 'plane') {
    // handled by the rectangular section
  } else if (!gr.currentFits) {
    callout(root, 'bad',
      `The ${(currentSize * 1e3).toFixed(0)} mm ground plane is smaller than the antenna on it`,
      `This type needs at least ${gr.minimumMm.toFixed(0)} mm just to hold the radiator (${(radiatorDim * 1e3).toFixed(0)} mm across), and ${gr.recommended.xMm.toFixed(0)} mm to reach ${gr.recommended.gainDbi.toFixed(1)} dBi. Raise the ground plane in the sidebar, or pick a type that fits the board you have.`);
  } else if (gr.current && gr.recommended.gainDbi - gr.current.gainDbi > 0.5) {
    callout(root, 'warn', `${(gr.recommended.gainDbi - gr.current.gainDbi).toFixed(1)} dB is being left on the table`,
      `Growing the ${unit} from ${(currentSize * 1e3).toFixed(0)} mm to ${gr.recommended.xMm.toFixed(0)} mm recovers it — ${gr.recommended.reason}.`);
  } else if (gr.current) {
    callout(root, 'good', `The current ${unit} is within ${Math.abs(gr.recommended.gainDbi - gr.current.gainDbi).toFixed(2)} dB of the practical optimum`,
      gr.recommended.reason.charAt(0).toUpperCase() + gr.recommended.reason.slice(1) + '.');
  }

  // ---- the main chart ----------------------------------------------------
  const c1 = card(root,
    mode === 'plane' ? 'Both axes together — the square-ground case' : `Gain against ${gr.xLabel}`,
    mode === 'plane'
      ? 'The diagonal of the map above: X and Y grown together. The marker is the square of the same area as the board actually specified, which is the fair comparison.'
      : gr.mechanism);
  const series = [{ name: mode === 'radial' || mode === 'height' ? 'peak gain' : 'realized gain',
    points: valid.map((q) => ({ x: q.xLambda, y: q.gainDbi })) }];
  if (mode === 'radial') {
    series.push({ name: 'gain toward the horizon', color: 'var(--series-2)',
      points: valid.map((q) => ({ x: q.xLambda, y: q.horizonGainDbi })) });
  }
  if (mode === 'height') {
    series.push({ name: `gain at ${valid[0].detail.lowElevDeg}° elevation`, color: 'var(--series-2)',
      points: valid.map((q) => ({ x: q.xLambda, y: q.lowElevGainDbi })) });
  }
  lineChart(chartBox(c1), {
    height: 360,
    series,
    xLabel: `${gr.xLabel} [λ₀]  ·  1 λ₀ = ${(D.lambda0 * 1e3).toFixed(1)} mm`,
    yLabel: 'gain [dBi]',
    xFmt: (v) => v.toFixed(2),
    vlines: [
      ...(gr.current ? [{ x: gr.current.xLambda, label: mode === 'plane' ? `equal-area square ${(currentSize * 1e3).toFixed(0)} mm` : `current ${(currentSize * 1e3).toFixed(0)} mm`, kind: 'spec' }] : []),
      { x: gr.recommended.xLambda, label: `recommended ${gr.recommended.xMm.toFixed(0)} mm`, kind: 'good' },
    ],
    hlines: [{ y: D.spec.targetGainDbi, label: `target ${D.spec.targetGainDbi.toFixed(1)} dBi` }],
    tipFmt: (p) => `${p.y.toFixed(2)} dBi`,
    directLabels: false,
    note: `Physical scale: the sweep runs from ${valid[0].xMm.toFixed(0)} mm to ${valid[valid.length - 1].xMm.toFixed(0)} mm at ${engFreq(D.spec.f)}.`,
  });

  // ---- secondary effect --------------------------------------------------
  const c2 = card(root, 'What else changes with it',
    mode === 'plane' ? 'Gain is only half the story: the back lobe is what a small ground really costs you.'
    : mode === 'radial' ? 'The peak gain figure hides the important effect — where the beam points.'
    : mode === 'chassis' ? 'Bandwidth follows the same chassis resonance as gain, which is why both improve together.'
    : mode === 'height' ? 'Raising the antenna lowers the first lobe toward the horizon, which is what a terrestrial link needs.'
    : 'The disc is there to suppress the back lobe, so that is the number to watch.');
  lineChart(chartBox(c2), {
    height: 300,
    series: [{ name: gr.secondaryLabel, color: 'var(--series-3)',
      points: valid.filter((q) => Number.isFinite(q.secondary)).map((q) => ({ x: q.xLambda, y: q.secondary })) }],
    xLabel: `${gr.xLabel} [λ₀]`, yLabel: gr.secondaryLabel,
    xFmt: (v) => v.toFixed(2),
    vlines: gr.current ? [{ x: gr.current.xLambda, label: 'current', kind: 'spec' }] : [],
    tipFmt: (p) => p.y.toFixed(2),
    directLabels: false,
  });

  // ---- pattern at three sizes -------------------------------------------
  if (mode === 'plane' || mode === 'radial') {
    const c3 = card(root, 'The same antenna on three different ground planes',
      'Same element, same feed, same frequency — only the ground changes. This is the effect the gain curve is a summary of.');
    const picks = mode === 'plane'
      ? [0.5, gr.current ? gr.current.xLambda : 1.0, 2.5]
      : [0.15, gr.current ? gr.current.xLambda : 0.5, 1.5];
    const colors = ['var(--series-2)', 'var(--series-1)', 'var(--series-3)'];
    const patSeries = picks.map((xL, i) => {
      const opts = {
        D0: fromDB(c.gainDbi) / Math.max(c.efficiency, 1e-3),
        gainDbi: c.gainDbi, count: c.count, lambda0: D.lambda0, dims: c.dims,
        patch: c.patch ? { Le: c.patch.Le, W: c.patch.W, h: D.stack.h } : null,
      };
      if (mode === 'plane') {
        opts.fbDb = groundPlaneEffect({ lg: xL * D.lambda0, patchDim: radiatorDim,
          lambda0: D.lambda0, swr: c.patch ? c.patch.surfaceWaveRatio : 0 }).frontToBackDb;
      } else {
        opts.tiltDeg = monopoleGround({ radius: xL * D.lambda0, lambda0: D.lambda0 }).tiltDeg;
      }
      const pp = patternFor(c.arch.id, opts);
      return { name: `${(xL * D.lambda0 * 1e3).toFixed(0)} mm (${xL.toFixed(2)} λ₀)`, points: pp.E, color: colors[i], meta: pp.meta };
    });
    const g3 = h('div', { class: 'grid2' }, c3);
    polarChart(chartBox(g3), {
      size: 360, title: mode === 'plane' ? 'E-plane pattern' : 'Elevation pattern',
      subtitle: 'normalised to each pattern\'s own peak',
      floor: -40, series: patSeries,
      note: mode === 'plane'
        ? 'A small ground plane does not just cost forward gain — it puts a large fraction of the power behind the antenna.'
        : 'Watch the beam peak lift off the horizon as the counterpoise shrinks.',
    });
    dataTable(h('div', {}, g3), [mode === 'plane' ? 'Ground size' : 'Ground radius', 'Gain', mode === 'plane' ? 'F/B' : 'Peak elevation', 'Beamwidth'],
      picks.map((xL, i) => {
        const q = valid.reduce((a, b) => (Math.abs(b.xLambda - xL) < Math.abs(a.xLambda - xL) ? b : a));
        return [`${(xL * D.lambda0 * 1e3).toFixed(0)} mm (${xL.toFixed(2)} λ₀)`,
          `${q.gainDbi.toFixed(2)} dBi`,
          mode === 'plane' ? `${q.secondary.toFixed(1)} dB` : `${q.secondary.toFixed(0)}°`,
          `${patSeries[i].meta.hpbwE.toFixed(0)}°`];
      }));
  }

  // ---- discrete table ----------------------------------------------------
  const c4 = card(root, 'Sizing table');
  const marks = mode === 'height' ? [0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3]
    : mode === 'chassis' ? [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
    : mode === 'radial' ? [0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2]
    : [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];
  dataTable(c4, [`${gr.xLabel} [λ₀]`, 'in mm', 'Gain [dBi]', 'Δ vs best', gr.secondaryLabel, 'Verdict'],
    marks.map((x) => {
      const q = valid.reduce((a, b) => (Math.abs(b.xLambda - x) < Math.abs(a.xLambda - x) ? b : a), valid[0]);
      const d = q.gainDbi - best.gainDbi;
      return [x.toFixed(2), q.xMm.toFixed(0), q.gainDbi.toFixed(2), `${d.toFixed(2)} dB`,
        Number.isFinite(q.secondary) ? q.secondary.toFixed(mode === 'chassis' ? 2 : 1) : '-',
        d > -0.3 ? 'Fully developed' : d > -1.0 ? 'Acceptable' : d > -2.5 ? 'Degraded' : 'Not usable'];
    }));
  const ul = h('ul', { class: 'ref-list' }, c4);
  gr.notes.forEach((n) => h('li', { text: n }, ul));
}

/**
 * A rectangular ground plane does not behave like a square one of the same
 * area: each principal plane is shaped by the two edges perpendicular to it,
 * so the E-plane answers to the X extent and the H-plane to the Y extent.
 */
function renderRectangularGround(root, D, c, { radL, radW }) {
  const lam = D.lambda0;
  const gx = D.groundXM, gy = D.groundYM;
  const base = c.gainDbi - (D.spec.feedLossDb || 0);
  const g0 = groundPlaneEffect({ lgx: gx, lgy: gy, patchL: radL, patchW: radW,
    lambda0: lam, swr: c.patch ? c.patch.surfaceWaveRatio : 0 });

  const mxMm = ((gx - radL) / 2) * 1e3;
  const myMm = ((gy - radW) / 2) * 1e3;
  const fitsX = mxMm >= 0, fitsY = myMm >= 0;

  const tl = h('div', { class: 'tiles' }, root);
  tile(tl, 'Board', `${(gx * 1e3).toFixed(0)} × ${(gy * 1e3).toFixed(0)}`, 'mm',
    `${(gx / lam).toFixed(2)} × ${(gy / lam).toFixed(2)} λ₀ · aspect ${(gx / gy).toFixed(2)}:1`);
  tile(tl, 'Margin X (E-plane)', fitsX ? mxMm.toFixed(1) : 'does not fit', fitsX ? 'mm' : '',
    fitsX ? `${g0.marginXLambda.toFixed(3)} λ₀ beyond each radiating edge`
          : `the radiator is ${(radL * 1e3).toFixed(1)} mm long — ${Math.abs(mxMm * 2).toFixed(1)} mm too big for this axis`,
    !fitsX ? 'bad' : g0.marginXLambda > 0.15 ? 'good' : g0.marginXLambda > 0.08 ? 'warn' : 'bad');
  tile(tl, 'Margin Y (H-plane)', fitsY ? myMm.toFixed(1) : 'does not fit', fitsY ? 'mm' : '',
    fitsY ? `${g0.marginYLambda.toFixed(3)} λ₀ beyond each side edge`
          : `the radiator is ${(radW * 1e3).toFixed(1)} mm wide — ${Math.abs(myMm * 2).toFixed(1)} mm too big for this axis`,
    !fitsY ? 'bad' : g0.marginYLambda > 0.15 ? 'good' : g0.marginYLambda > 0.08 ? 'warn' : 'bad');
  tile(tl, 'E-plane gain change', g0.E.deltaGdB.toFixed(2), 'dB', `F/B ${g0.E.frontToBackDb.toFixed(1)} dB`);
  tile(tl, 'H-plane gain change', g0.H.deltaGdB.toFixed(2), 'dB', `F/B ${g0.H.frontToBackDb.toFixed(1)} dB`);
  tile(tl, 'E vs H asymmetry', g0.asymmetryDb.toFixed(2), 'dB',
    `F/B differs by ${g0.fbAsymmetryDb.toFixed(1)} dB between the planes`,
    g0.asymmetryDb < 0.5 ? 'good' : g0.asymmetryDb < 1.5 ? 'warn' : 'bad');

  if (!fitsX || !fitsY) {
    callout(root, 'bad',
      `The radiator does not fit on this board in ${!fitsX && !fitsY ? 'either axis' : !fitsX ? 'the X axis' : 'the Y axis'}`,
      `${c.arch.name} is ${(radL * 1e3).toFixed(1)} mm along X and ${(radW * 1e3).toFixed(1)} mm along Y, against a `
      + `${(gx * 1e3).toFixed(0)} × ${(gy * 1e3).toFixed(0)} mm ground plane. The numbers below are computed with the `
      + `margin clamped at zero, so treat them as the best case — a real overhanging patch behaves worse than that.`);
  }

  if (g0.asymmetryDb > 1.0) {
    const worse = g0.E.deltaGdB < g0.H.deltaGdB ? 'E-plane (X axis)' : 'H-plane (Y axis)';
    const better = worse.startsWith('E') ? 'H-plane (Y axis)' : 'E-plane (X axis)';
    const swapped = groundPlaneEffect({ lgx: gy, lgy: gx, patchL: radL, patchW: radW,
      lambda0: lam, swr: c.patch ? c.patch.surfaceWaveRatio : 0 });
    callout(root, 'warn', `The two principal planes differ by ${g0.asymmetryDb.toFixed(1)} dB`,
      `The ${worse} is the starved one. Rotating the antenna 90° on the same board `
      + `(${(gy * 1e3).toFixed(0)} × ${(gx * 1e3).toFixed(0)} mm relative to the patch) would give `
      + `${(base + swapped.deltaGdB).toFixed(2)} dBi instead of ${(base + g0.deltaGdB).toFixed(2)} dBi — `
      + `${swapped.deltaGdB > g0.deltaGdB ? `worth ${(swapped.deltaGdB - g0.deltaGdB).toFixed(2)} dB, so turn it` : 'so the current orientation is the right one'}. `
      + `The ${better} has margin to spare.`);
  }

  // ---- 2-D map ----------------------------------------------------------
  const c1 = card(root, 'Realized gain over the whole board-size space',
    'Every combination of X and Y, with this antenna on it. The circle is the board currently specified; the cross is the best square of the same area. Grey cells are sizes the radiator does not fit on.');
  // 0.3 to 2.0 lambda covers the whole useful design space: below that the
  // radiator does not fit, above it the curve is flat and the board is absurd.
  const n = 52, lo = 0.3, span = 1.7;
  const xs = [], ys = [];
  for (let i = 0; i < n; i++) {
    xs.push(lo + (span * i) / (n - 1));
    ys.push(lo + (span * i) / (n - 1));
  }
  const cells = ys.map((yl) => xs.map((xl) => {
    const lx = xl * lam, ly = yl * lam;
    if (lx < radL * 1.02 || ly < radW * 1.02) return NaN;
    return base + groundPlaneEffect({ lgx: lx, lgy: ly, patchL: radL, patchW: radW,
      lambda0: lam, swr: c.patch ? c.patch.surfaceWaveRatio : 0 }).deltaGdB;
  }));
  const areaSq = Math.sqrt(gx * gy) / lam;
  heatmap(chartBox(c1), {
    square: true, diagonal: true, cells, xs, ys,
    xLabel: 'ground X — along the resonant length [mm]',
    yLabel: 'ground Y — along the width [mm]',
    xFmt: (v) => `${(v * lam * 1e3).toFixed(0)}`,
    yFmt: (v) => `${(v * lam * 1e3).toFixed(0)}`,
    valueLabel: 'realized gain [dBi]', valueFmt: (v) => `${v.toFixed(2)} dBi`,
    markers: [
      { x: gx / lam, y: gy / lam, label: `this board ${(gx * 1e3).toFixed(0)}×${(gy * 1e3).toFixed(0)}` },
      { x: areaSq, y: areaSq, label: 'square of equal area', color: 'var(--series-6)' },
    ],
    note: `Axes are in millimetres at ${engFreq(D.spec.f)}, on equal scales so the dashed diagonal is the square case at 45°. The map is deliberately not symmetric about that diagonal: the X margin sits beyond the radiating edges and the Y margin does not, so the same board turned 90° is a different antenna. The checkerboard is the edge-diffraction ripple in both axes at once — it is physical, not noise.`,
  });

  // ---- the two principal cuts -------------------------------------------
  const c2 = card(root, 'Each axis, taken separately',
    'Sweeping one axis with the other held at its current value. The E-plane responds to X, the H-plane to Y — and the ripple periods are independent, which is why the two curves do not line up.');
  const g2 = h('div', { class: 'grid2' }, c2);
  const sweep = (axis) => {
    const pts = [];
    for (let i = 0; i <= 200; i++) {
      const v = 0.3 + (3.2 * i) / 200;
      const lx = axis === 'x' ? v * lam : gx;
      const ly = axis === 'x' ? gy : v * lam;
      if (lx < radL * 1.02 || ly < radW * 1.02) continue;
      const r = groundPlaneEffect({ lgx: lx, lgy: ly, patchL: radL, patchW: radW,
        lambda0: lam, swr: c.patch ? c.patch.surfaceWaveRatio : 0 });
      pts.push({ v, mm: v * lam * 1e3, gain: base + r.deltaGdB,
        plane: axis === 'x' ? r.E.deltaGdB : r.H.deltaGdB,
        fb: axis === 'x' ? r.E.frontToBackDb : r.H.frontToBackDb });
    }
    return pts;
  };
  const sx = sweep('x'), sy = sweep('y');
  lineChart(chartBox(g2), {
    height: 320, title: 'Sweeping X (E-plane)',
    subtitle: `Y held at ${(gy * 1e3).toFixed(0)} mm`,
    series: [
      { name: 'realized gain', points: sx.map((q) => ({ x: q.mm, y: q.gain })) },
      { name: 'E-plane change', points: sx.map((q) => ({ x: q.mm, y: base + q.plane })), color: 'var(--series-2)', dash: '5 4' },
    ],
    xLabel: 'ground X [mm]', yLabel: 'gain [dBi]',
    vlines: [{ x: gx * 1e3, label: 'current', kind: 'spec' }],
    tipFmt: (p) => `${p.y.toFixed(2)} dBi`, directLabels: false, table: false,
  });
  lineChart(chartBox(g2), {
    height: 320, title: 'Sweeping Y (H-plane)',
    subtitle: `X held at ${(gx * 1e3).toFixed(0)} mm`,
    series: [
      { name: 'realized gain', points: sy.map((q) => ({ x: q.mm, y: q.gain })) },
      { name: 'H-plane change', points: sy.map((q) => ({ x: q.mm, y: base + q.plane })), color: 'var(--series-2)', dash: '5 4' },
    ],
    xLabel: 'ground Y [mm]', yLabel: 'gain [dBi]',
    vlines: [{ x: gy * 1e3, label: 'current', kind: 'spec' }],
    tipFmt: (p) => `${p.y.toFixed(2)} dBi`, directLabels: false, table: false,
  });

  const c3 = card(root, 'Front-to-back, per plane',
    'Back radiation is set by the edges of the plane you are looking at, so a long-and-narrow board has a good F/B one way and a poor one the other.');
  lineChart(chartBox(c3), {
    height: 300,
    series: [
      { name: 'E-plane F/B (follows X)', points: sx.map((q) => ({ x: q.mm, y: q.fb })) },
      { name: 'H-plane F/B (follows Y)', points: sy.map((q) => ({ x: q.mm, y: q.fb })), color: 'var(--series-2)' },
    ],
    xLabel: 'that axis of the ground plane [mm]', yLabel: 'front-to-back [dB]',
    vlines: [{ x: gx * 1e3, label: `X ${(gx * 1e3).toFixed(0)}`, kind: 'spec' },
             { x: gy * 1e3, label: `Y ${(gy * 1e3).toFixed(0)}`, kind: 'good' }],
    tipFmt: (p) => `${p.y.toFixed(1)} dB`, directLabels: false, table: false,
  });

  const c4 = card(root, 'Orientation study — the same board, the antenna turned 90°');
  dataTable(c4, ['Orientation', 'X × Y relative to the patch', 'Realized gain', 'E-plane', 'H-plane', 'F/B E / H', 'Asymmetry'],
    [['As specified', gx, gy], ['Rotated 90°', gy, gx]].map(([name, a, bq]) => {
      const r = groundPlaneEffect({ lgx: a, lgy: bq, patchL: radL, patchW: radW,
        lambda0: lam, swr: c.patch ? c.patch.surfaceWaveRatio : 0 });
      return [name, `${(a * 1e3).toFixed(0)} × ${(bq * 1e3).toFixed(0)} mm`,
        `${(base + r.deltaGdB).toFixed(2)} dBi`, `${r.E.deltaGdB.toFixed(2)} dB`, `${r.H.deltaGdB.toFixed(2)} dB`,
        `${r.E.frontToBackDb.toFixed(1)} / ${r.H.frontToBackDb.toFixed(1)} dB`, `${r.asymmetryDb.toFixed(2)} dB`];
    }));
  h('p', { class: 'chart-note', text: 'On a fixed board outline this is a free change: rotating the patch 90° costs nothing in area and can be worth a decibel.' }, c4);
}

/* =========================================================== PATCH DESIGN */

export function renderPatch(root, D) {
  const s = D.sol, f = D.feed;

  const tl = h('div', { class: 'tiles' }, root);
  tile(tl, 'Patch W × L', `${(s.W * 1e3).toFixed(2)} × ${(s.L * 1e3).toFixed(2)}`, 'mm', `Le = ${(s.Le * 1e3).toFixed(2)} mm incl. fringing`);
  tile(tl, 'Realized gain', D.realizedGainDbi.toFixed(2), 'dBi', `D₀ ${s.D0dBi.toFixed(2)} dBi · η ${(s.etaSpace * 100).toFixed(1)} %`,
    D.realizedGainDbi >= D.spec.targetGainDbi ? 'good' : 'warn');
  tile(tl, 'Efficiency', (s.etaSpace * 100).toFixed(1), '%', `${s.lossBudgetDb.total.toFixed(2)} dB of loss`,
    s.etaSpace > 0.8 ? 'good' : s.etaSpace > 0.5 ? 'warn' : 'bad');
  tile(tl, 'VSWR-2 bandwidth', (s.fbw2 * 100).toFixed(2), '%', `${(s.bw2Hz / 1e6).toFixed(1)} MHz · Q_t ${s.Qt.toFixed(0)}`);
  tile(tl, 'Edge resistance', s.Rin.toFixed(0), 'Ω', `G₁ ${(s.G1 * 1e3).toFixed(3)} mS, G₁₂ ${(s.G12 * 1e3).toFixed(3)} mS`);
  tile(tl, 'Beamwidth E/H', `${D.beamwidth.thetaE.toFixed(0)}° / ${D.beamwidth.thetaH.toFixed(0)}°`, '',
    `F/B ${D.gnd.E.frontToBackDb.toFixed(1)} / ${D.gnd.H.frontToBackDb.toFixed(1)} dB (E / H)`);

  // ---- dimensions + feed --------------------------------------------------
  const c1 = card(root, 'Synthesised geometry', 'Transmission-line/cavity synthesis at the design frequency, then solved back through the full model.');
  const g = h('div', { class: 'grid2' }, c1);
  dataTable(h('div', {}, g), ['Parameter', 'Value', 'Note'], [
    ['Design frequency', engFreq(D.spec.f), D.band ? D.band.name : 'custom'],
    ['Substrate', D.stack.material.name, `εr ${D.stack.material.er.toFixed(3)}, tanδ ${D.stack.material.df.toFixed(5)}`],
    ['Total height h', mm(D.stack.h), `${(D.stack.h / D.lambda0).toFixed(4)} λ₀`],
    ['Effective permittivity', s.epsEff.toFixed(3), 'Hammerstad, includes fringing'],
    ['Patch width W', mm(s.W), `${(s.W / D.lambda0).toFixed(3)} λ₀`],
    ['Patch length L', mm(s.L), `${(s.L / D.lambda0).toFixed(3)} λ₀`],
    ['Fringing extension ΔL', mm(s.dL), 'each radiating edge'],
    ['Effective length Le', mm(s.Le), `${s.LeOverLambda.toFixed(3)} λ₀ — sets the two-slot spacing`],
    ['Ground plane', `${(D.groundXM * 1e3).toFixed(1)} × ${(D.groundYM * 1e3).toFixed(1)} mm`,
      `${(D.groundXM / D.lambda0).toFixed(2)} × ${(D.groundYM / D.lambda0).toFixed(2)} λ₀`],
    ['Ground margin per side', `X ${((D.groundXM - D.sol.L) / 2 * 1e3).toFixed(1)} · Y ${((D.groundYM - D.sol.W) / 2 * 1e3).toFixed(1)} mm`,
      `${D.gnd.marginXLambda.toFixed(3)} / ${D.gnd.marginYLambda.toFixed(3)} λ₀ — X is beyond the radiating edges`],
    ['Far-field distance', `${(D.fieldRegions.farField * 1e3).toFixed(0)} mm`, '2D²/λ criterion — minimum test range'],
  ]);

  const feedRows = [
    ['Feed type', f.type, ''],
    ['50 Ω line width', mm(f.feedLineWidth), `εeff ${f.epsEffFeed.toFixed(3)}`],
    ['Guided wavelength', mm(f.lambdaG), 'on the feed line'],
    ['Feed line loss', `${f.feedLineLossDbPerCm.toFixed(4)} dB/cm`, 'conductor + dielectric'],
  ];
  if (f.insetDepth !== undefined) {
    feedRows.push(['Inset depth y₀', mm(f.insetDepth), `Rin(y₀) = ${s.Rin.toFixed(0)}·cos²(πy₀/L) → 50 Ω`]);
    feedRows.push(['Inset gap', mm(f.insetGap), 'notch each side of the feed']);
  }
  if (f.transformer) {
    feedRows.push(['λ/4 transformer Z', `${f.transformer.z.toFixed(1)} Ω`, `√(50 · ${s.Rin.toFixed(0)})`]);
    feedRows.push(['λ/4 width', mm(f.transformer.w), '']);
    feedRows.push(['λ/4 length', mm(f.transformer.length), '']);
  }
  if (f.probeOffset !== undefined) {
    feedRows.push(['Probe offset from centre', mm(f.probeOffset), '']);
    feedRows.push(['Probe inductance', `${f.probeInductanceNh.toFixed(3)} nH`, `+j${f.probeReactance.toFixed(1)} Ω`]);
  }
  if (f.slotLength !== undefined) {
    feedRows.push(['Coupling slot', `${mm(f.slotLength)} × ${mm(f.slotWidth)}`, '~0.4 × patch width']);
    feedRows.push(['Open stub', mm(f.stubLength), 'tunes out residual reactance']);
  }
  dataTable(h('div', {}, g), ['Feed parameter', 'Value', 'Note'], feedRows);
  if (f.probeNote) h('p', { class: 'chart-note', text: f.probeNote }, c1);

  // ---- S11 / VSWR ---------------------------------------------------------
  const c2 = card(root, 'Impedance response',
    'Parallel-RLC equivalent of the dominant TM₁₀ mode with the loaded Q from the cavity solution. Real hardware lands within a few percent of this once the feed is tuned.');
  const g2 = h('div', { class: 'grid2' }, c2);
  const band = D.spec.bwPct ? [D.spec.f * (1 - D.spec.bwPct / 200), D.spec.f * (1 + D.spec.bwPct / 200)] : null;
  lineChart(chartBox(g2), {
    height: 300,
    series: [{ name: 'S₁₁', points: D.s11.map((p) => ({ x: p.f, y: p.s11 })) }],
    xLabel: 'frequency [GHz]', yLabel: 'S₁₁ [dB]',
    xFmt: (v) => (v / 1e9).toFixed(3),
    yDomain: { min: -40, max: 0 },
    hlines: [{ y: -10, label: 'VSWR 2:1 (−10 dB)', kind: 'good' }],
    bands: band ? [{ from: band[0], to: band[1], label: 'required band' }] : [],
    tipFmt: (p) => `${p.y.toFixed(1)} dB`,
    title: 'Return loss',
  });
  lineChart(chartBox(g2), {
    height: 300,
    series: [
      { name: 'R', points: D.s11.map((p) => ({ x: p.f, y: p.R })) },
      { name: 'X', points: D.s11.map((p) => ({ x: p.f, y: p.X })) },
    ],
    xLabel: 'frequency [GHz]', yLabel: 'impedance [Ω]',
    xFmt: (v) => (v / 1e9).toFixed(3),
    hlines: [{ y: 50, label: '50 Ω' }, { y: 0, label: '' }],
    title: 'Input impedance',
  });

  const g3 = h('div', { class: 'grid2' }, c2);
  smithChart(chartBox(g3), {
    size: 360, title: 'Smith chart (50 Ω)',
    subtitle: `${((D.spec.f * 0.875) / 1e9).toFixed(2)} – ${((D.spec.f * 1.125) / 1e9).toFixed(2)} GHz sweep`,
    vswrCircles: [1.5, 2, 3],
    traces: [{ points: D.s11.map((p) => {
      const gr = ((p.R - 50) * (p.R + 50) + p.X * p.X) / (Math.pow(p.R + 50, 2) + p.X * p.X);
      const gi = (100 * p.X) / (Math.pow(p.R + 50, 2) + p.X * p.X);
      return { gr, gi, f: p.f, R: p.R, X: p.X, vswr: p.vswr, s11: p.s11 };
    }) }],
    note: 'The loop diameter is set by Q_total; a probe feed rotates and lifts it inductively.',
  });
  polarChart(chartBox(g3), {
    size: 360, title: 'Radiation pattern (principal planes)',
    subtitle: `normalised, F/B ${D.gnd.frontToBackDb.toFixed(1)} dB from the finite ground model`,
    floor: -40,
    series: [
      { name: 'E-plane (φ = 0°)', points: D.pattern.E },
      { name: 'H-plane (φ = 90°)', points: D.pattern.H },
    ],
    note: 'Cavity-model two-slot far field over a ground plane; back radiation scaled by the computed front-to-back ratio.',
  });

  // ---- Q / loss budget ----------------------------------------------------
  const c3 = card(root, 'Where the power goes',
    'The loaded Q is the parallel combination of four loss channels. Whichever has the lowest Q dominates the efficiency — that is the one worth engineering.');
  const g4 = h('div', { class: 'grid2' }, c3);
  const chan = [
    { name: 'Radiation (useful)', q: s.Qrad, p: s.etaSpace },
    { name: 'Dielectric', q: s.Qd, p: s.etaDielectric },
    { name: 'Conductor', q: s.Qc, p: s.etaConductor },
    { name: 'Surface wave', q: s.Qsw, p: s.etaSurface },
  ];
  barChart(chartBox(g4), {
    height: 280, title: 'Power split at the port',
    items: chan.map((c, i) => ({ label: c.name, value: c.p * 100, color: i === 0 ? 'var(--series-3)' : SERIES_VARS[i], sub: `Q = ${c.q > 1e8 ? '∞' : c.q.toFixed(0)}` })),
    yLabel: 'share of accepted power [%]',
    valueFmt: (v) => `${v.toFixed(1)}%`,
    note: 'Shares sum to 100 %: the radiated fraction is the radiation efficiency.',
  });
  dataTable(h('div', {}, g4), ['Loss channel', 'Q', 'Share of power', 'Equivalent loss'], [
    ...chan.map((c) => [c.name, c.q > 1e8 ? '∞' : c.q.toFixed(1), `${(c.p * 100).toFixed(2)} %`,
      c.name.startsWith('Radiation') ? `${toDB(c.p).toFixed(2)} dB efficiency` : `${(-toDB(1 - c.p)).toFixed(3)} dB`]),
    ['Loaded Q_total', s.Qt.toFixed(1), '-', `BW = ${(s.fbw2 * 100).toFixed(2)} % at VSWR 2`],
  ]);

  const det = h('details', { class: 'info' }, c3);
  h('summary', { text: 'Model and equations used' }, det);
  const body = h('div', { class: 'body' }, det);
  body.innerHTML = `
    <span class="eq">W = (c/2f)·√(2/(εr+1))              patch width for best efficiency
εeff = (εr+1)/2 + (εr−1)/2·(1+12h/W)^(−1/2)
ΔL/h = 0.412·(εeff+0.3)(W/h+0.264) / ((εeff−0.258)(W/h+0.8))
L = c/(2f√εeff) − 2ΔL
Q_rad = 2π²·εeff·Le / (k₀·h·W·I)     I = ∮|F(θ,φ)|² dΩ  (integrated numerically)
Q_d = 1/tanδ      Q_c = h·√(πfμσ)     Q_sw = Q_rad·P_sp/P_sw
1/Q_t = 1/Q_rad + 1/Q_d + 1/Q_c + 1/Q_sw
η = Q_t/Q_rad     BW(S) = (S−1)/(Q_t·√S)</span>
    <p class="small">The far field is the two-slot cavity model: a y-directed equivalent magnetic
    current over the ground gives E<sub>θ</sub> ∝ F·cosφ and E<sub>φ</sub> ∝ −F·cosθ·sinφ with
    F = sinc(k₀h/2·sinθcosφ)·sinc(k₀W/2·sinθsinφ)·2cos(k₀Le/2·sinθcosφ).
    Directivity comes from integrating that pattern rather than from a closed-form approximation,
    so it stays correct for wide, thick and low-εr patches where the textbook formulas drift.</p>
    <ul class="ref-list">
      <li>C. A. Balanis, <i>Antenna Theory: Analysis and Design</i>, 4th ed., ch. 14</li>
      <li>E. Hammerstad &amp; Ø. Jensen, "Accurate models for microstrip computer-aided design", MTT-S 1980</li>
      <li>D. R. Jackson &amp; N. G. Alexopoulos, "Simple approximate formulas for input resistance, bandwidth and efficiency of a resonant rectangular patch", IEEE T-AP 39(3), 1991</li>
      <li>D. M. Pozar, "Considerations for millimeter wave printed antennas", IEEE T-AP 31(5), 1983</li>
    </ul>`;
}

/* ======================================================== SUBSTRATE TRADE */

export function renderSubstrate(root, D, state) {
  const spec = D.spec;

  // ---- trade bar chart ----------------------------------------------------
  const candidates = state.tradeCandidates || defaultTradeSet(spec);
  const trade = substrateTrade(spec, candidates);

  const c1 = card(root, 'Substrate trade — realized gain on the actual ground plane',
    `Every candidate stack is solved end to end: efficiency from the loss tangent and height, directivity from the aperture the permittivity allows, then ground-plane truncation and ${(spec.feedLossDb || 0).toFixed(1)} dB of feed loss.`);
  barChart(chartBox(c1), {
    height: 350,
    items: trade.map((t) => ({
      label: t.label,
      value: t.realizedGainDbi,
      highlight: t.realizedGainDbi >= spec.targetGainDbi,
      color: t.realizedGainDbi >= spec.targetGainDbi ? 'var(--series-3)' : 'var(--series-1)',
      sub: `η ${(t.efficiency * 100).toFixed(0)} % · BW ${t.bwPct.toFixed(1)} % · patch ${t.widthMm.toFixed(0)}×${t.lengthMm.toFixed(0)} mm`,
    })),
    yLabel: 'realized gain [dBi]',
    valueFmt: (v) => v.toFixed(1),
    hlines: [{ y: spec.targetGainDbi, label: `spec ${spec.targetGainDbi.toFixed(1)} dBi` }],
    note: 'Green clears the specification. Hover for efficiency, bandwidth and the resulting patch size.',
  });
  dataTable(c1, ['Stack', 'εr', 'tanδ', 'h [mm]', 'Patch [mm]', 'η [%]', 'BW [%]', 'Realized gain [dBi]', 'Cost index'],
    trade.map((t) => [t.label, t.er.toFixed(2), t.df.toFixed(4), (t.h * 1e3).toFixed(2),
      `${t.widthMm.toFixed(1)} × ${t.lengthMm.toFixed(1)}`, (t.efficiency * 100).toFixed(1),
      t.bwPct.toFixed(2), t.realizedGainDbi.toFixed(2), t.cost.toFixed(1)]));

  // ---- efficiency vs thickness -------------------------------------------
  const ids = state.sweepMaterials || ['fr4', 'ro4003c', 'rt5880', 'ro6010'];
  const sweeps = thicknessSweep(spec, ids, { includeSurfaceWave: state.includeSurfaceWave !== false });
  const c2 = card(root, 'Why a thin lossy substrate cannot radiate',
    'Radiation Q falls as 1/h while the dielectric Q is fixed at 1/tanδ. Efficiency is the ratio of the two, so on a high-Df laminate you must go thick — and thick then costs you bandwidth to surface waves.');
  const tgl = h('div', { class: 'toolbar' }, c2);
  const swBtn = h('button', { text: state.includeSurfaceWave !== false ? 'Surface-wave loss: included' : 'Surface-wave loss: excluded' }, tgl);
  swBtn.addEventListener('click', () => { state.includeSurfaceWave = !(state.includeSurfaceWave !== false); state.rerender(); });
  h('span', { class: 'small muted', text: 'Excluding it reproduces the classic textbook curve; including it is what hardware actually measures.' }, tgl);

  lineChart(chartBox(c2), {
    height: 340,
    series: sweeps.map((s) => ({
      name: `${s.name} (Df ${s.df.toFixed(4)})`,
      points: s.points.map((p) => ({ x: p.hMm, y: p.etaPct })),
    })),
    xLabel: 'substrate thickness [mm]', yLabel: 'radiation efficiency [%]',
    yDomain: { min: 0, max: 100 },
    vlines: [{ x: D.stack.h * 1e3, label: 'this design', kind: 'spec' }],
    tipFmt: (p) => `${p.y.toFixed(1)} %`,
    note: `At ${engFreq(spec.f)}. Q_d = 1/tanδ is the ceiling each material can never beat: FR-4 tanδ 0.020 → Q_d = 50.`,
  });

  const c2b = card(root, 'Bandwidth bought with thickness',
    'The same thickness that buys efficiency also buys bandwidth — until the surface wave and the probe inductance take over.');
  lineChart(chartBox(c2b), {
    height: 300,
    series: sweeps.map((s) => ({ name: s.name, points: s.points.map((p) => ({ x: p.hMm, y: p.bwPct })) })),
    xLabel: 'substrate thickness [mm]', yLabel: 'VSWR-2 bandwidth [%]',
    vlines: [{ x: D.stack.h * 1e3, label: 'this design', kind: 'spec' }],
    tipFmt: (p) => `${p.y.toFixed(2)} %`,
    note: spec.bwPct ? `Your requirement is ${spec.bwPct.toFixed(1)} %.` : '',
    hlines: spec.bwPct ? [{ y: spec.bwPct, label: `required ${spec.bwPct.toFixed(1)} %`, kind: 'spec' }] : [],
  });

  // ---- permittivity sweep (two panels, never a dual axis) ----------------
  const perm = permittivitySweep(spec, { h: D.stack.h });
  const marks = [
    { er: 1.14, label: 'air gap' },
    { er: 2.2, label: '5880' },
    { er: 3.55, label: 'RO4003C' },
    { er: 4.3, label: 'FR-4' },
    { er: 10.2, label: '6010' },
  ];
  const c3 = card(root, 'Permittivity sets the aperture, and the aperture sets the directivity',
    'Raising εr shrinks the patch by 1/√εeff. A smaller radiating aperture radiates less directively — miniaturisation is paid for in gain, bandwidth and surface-wave loss, every time.');
  const g3 = h('div', { class: 'grid2' }, c3);
  lineChart(chartBox(g3), {
    height: 300, title: 'Slot separation',
    series: [{ name: 'Le/λ₀', points: perm.map((p) => ({ x: p.er, y: p.LeOverLambda })) }],
    xLabel: 'substrate εr', yLabel: 'slot separation Le/λ₀',
    vlines: marks.map((m) => ({ x: m.er, label: m.label })),
    tipFmt: (p) => p.y.toFixed(3),
  });
  lineChart(chartBox(g3), {
    height: 300, title: 'Directivity',
    series: [{ name: 'D₀', points: perm.map((p) => ({ x: p.er, y: p.D0dBi })), color: 'var(--series-2)' }],
    xLabel: 'substrate εr', yLabel: 'directivity D₀ [dBi]',
    vlines: marks.map((m) => ({ x: m.er, label: m.label })),
    tipFmt: (p) => `${p.y.toFixed(2)} dBi`,
    note: 'Two panels rather than one chart with two y-axes: the scales are unrelated and a shared axis would imply a correlation that is not there.',
  });

  // ---- surface wave -------------------------------------------------------
  const c4 = card(root, 'Surface-wave power — the loss that is not heat',
    'Power coupled into the grounded-slab TM₀ mode never leaves the board through the patch. It travels to the board edge and diffracts, showing up as back radiation, ripple and array coupling rather than as gain.');
  lineChart(chartBox(c4), {
    height: 300,
    series: sweeps.map((s) => ({
      name: s.name,
      points: s.points.map((p) => ({ x: p.hOverLambda, y: (p.swr / (1 + p.swr)) * 100 })),
    })),
    xLabel: 'h/λ₀', yLabel: 'power into the surface wave [%]',
    vlines: [{ x: D.stack.h / D.lambda0, label: 'this design', kind: 'spec' }],
    tipFmt: (p) => `${p.y.toFixed(1)} %`,
    note: 'Scales as (k₀h)(εr−1)³ — this is the reason high-Dk mmWave boards go to thin substrates or to SIW.',
  });
}

function defaultTradeSet(spec) {
  const base = [
    { materialId: 'fr4', h: 0.8e-3, stackMode: 'solid', label: 'FR-4 0.8 mm' },
    { materialId: 'fr4', h: 1.6e-3, stackMode: 'solid', label: 'FR-4 1.6 mm' },
    { materialId: 'fr4', h: 3.2e-3, stackMode: 'solid', label: 'FR-4 3.2 mm' },
    { materialId: 'ro4003c', h: 1.524e-3, stackMode: 'solid', label: 'RO4003C 1.52 mm' },
    { materialId: 'ro4003c', h: 3.048e-3, stackMode: 'solid', label: 'RO4003C 3.05 mm' },
    { materialId: 'rt5880', h: 1.575e-3, stackMode: 'solid', label: 'RT5880 1.57 mm' },
    { materialId: 'fr4', stackMode: 'airgap', carrierH: 0.8e-3, airGap: 4.2e-3, label: 'FR-4 carrier + 4.2 mm air' },
    { materialId: 'rohacell51', h: 5e-3, stackMode: 'solid', label: 'Rohacell 5 mm' },
  ];
  return base;
}

/* ============================================================== THERMAL */

export function renderThermal(root, D, state) {
  const spec = D.spec;
  const th = D.thermal;
  const pk = D.peak;

  const tl = h('div', { class: 'tiles' }, root);
  tile(tl, 'Dissipated power', th.pDissipatedW.toFixed(3), 'W', `of ${(spec.powerW ?? 1).toFixed(2)} W in · ${(th.pRadiatedW).toFixed(3)} W radiated`);
  tile(tl, 'Hot-spot temperature', th.tHotC.toFixed(1), '°C', `+${th.riseK.toFixed(1)} K over ${th.tAmbC} °C ambient`,
    th.headroomK > 20 ? 'good' : th.headroomK > 0 ? 'warn' : 'bad');
  tile(tl, 'Thermal resistance', th.rTotalKperW.toFixed(2), 'K/W', `internal ${th.rInternalKperW.toFixed(2)} + surface ${th.rSurfaceKperW.toFixed(2)}`);
  tile(tl, 'Max continuous power', th.pMaxContinuousW.toFixed(2), 'W', `limit ${th.tLimitC.toFixed(0)} °C (Tg − 20 K)`,
    th.safe ? 'good' : 'bad');
  tile(tl, 'Thermal time constant', th.tauSeconds.toFixed(1), 's', `C_th ${th.thermalCapacityJperK.toFixed(1)} J/K`);
  const pkW = pk.pMaxPeakW;
  tile(tl, 'Peak power limit',
    pkW >= 1e6 ? (pkW / 1e6).toFixed(2) : pkW >= 1e3 ? (pkW / 1e3).toFixed(1) : pkW.toFixed(1),
    pkW >= 1e6 ? 'MW' : pkW >= 1e3 ? 'kW' : 'W',
    `Paschen ${pk.paschenVoltage.toFixed(0)} V · edge ${pk.vEdge.toFixed(0)} V`, pk.safe ? 'good' : 'bad');

  if (!th.safe) {
    callout(root, 'bad', `Thermal limit exceeded: ${th.tHotC.toFixed(0)} °C against a ${th.tLimitC.toFixed(0)} °C limit`,
      `Reduce input power below ${th.pMaxContinuousW.toFixed(2)} W, move to a lower-Df laminate, add thermal vias or forced air.`);
  }

  // ---- rise vs power ------------------------------------------------------
  const c1 = card(root, 'Temperature rise against input power',
    'Loss power is (1 − η)·P_accepted. It conducts through the laminate, spreads in the ground plane, then leaves by natural or forced convection plus grey-body radiation. Both surface terms are temperature-dependent, so the curve is not a straight line.');
  const powers = Array.from({ length: 40 }, (_, i) => ((i + 1) / 40) * Math.max(spec.powerW * 3, 5));
  const cases = [
    { name: 'Still air', v: 0 },
    { name: 'Forced 1 m/s', v: 1 },
    { name: 'Forced 3 m/s', v: 3 },
  ];
  lineChart(chartBox(c1), {
    height: 330,
    series: cases.map((cs) => ({
      name: cs.name,
      points: powers.map((p) => ({
        x: p,
        y: solveThermal({
          pInW: p, efficiency: D.sol.etaSpace, mismatchGamma: 0.1,
          areaM2: D.groundXM * D.groundYM, perimeterM: 2 * (D.groundXM + D.groundYM), material: D.stack.material,
          h: D.stack.h, tAmbC: spec.tAmbC ?? 25, airVelocity: cs.v,
          emissivity: spec.emissivity ?? 0.9, altitudeM: spec.altitudeM ?? 0,
          viaCount: spec.viaCount ?? 0,
        }).tHotC,
      })),
    })),
    xLabel: 'RF power into the antenna [W]', yLabel: 'hot-spot temperature [°C]',
    hlines: [{ y: th.tLimitC, label: `laminate limit ${th.tLimitC.toFixed(0)} °C`, kind: 'spec' }],
    vlines: [{ x: spec.powerW ?? 1, label: 'operating point' }],
    tipFmt: (p) => `${p.y.toFixed(1)} °C`,
    note: `Emissivity ${(spec.emissivity ?? 0.9).toFixed(2)} (solder mask ≈ 0.9, bare copper ≈ 0.05 — bare copper roughly halves the radiative path).`,
  });

  // ---- resistance breakdown ----------------------------------------------
  const c2 = card(root, 'Thermal resistance network', 'Where the temperature rise is actually generated. The largest resistance is the one to attack.');
  const g2 = h('div', { class: 'grid2' }, c2);
  barChart(chartBox(g2), {
    height: 280,
    items: [
      { label: 'Substrate conduction', value: th.rConductionKperW },
      { label: 'Ground spreading', value: th.rSpreadKperW },
      { label: 'Thermal vias', value: Number.isFinite(th.rViaKperW) ? th.rViaKperW : 0 },
      { label: 'Surface to air', value: th.rSurfaceKperW },
    ].filter((d) => d.value > 0),
    yLabel: 'thermal resistance [K/W]',
    valueFmt: (v) => v.toFixed(2),
    note: 'Convection and radiation to ambient normally dominate a bare PCB antenna — adding copper rarely helps until you also add area or airflow.',
  });
  dataTable(h('div', {}, g2), ['Quantity', 'Value'], [
    ['Convection coefficient h_c', `${th.hConv.toFixed(2)} W/(m²·K)`],
    ['Radiation coefficient h_r', `${th.hRad.toFixed(2)} W/(m²·K)`],
    ['Radiating/convecting area', `${(D.groundXM * D.groundYM * 2 * 1e4).toFixed(1)} cm² (both faces)`],
    ['Ambient pressure', `${(th.pressurePa / 1000).toFixed(1)} kPa (${(spec.altitudeM ?? 0)} m altitude)`],
    ['Board mass', `${th.massG.toFixed(1)} g`],
    ['Time to 63 % of final rise', `${th.tauSeconds.toFixed(0)} s`],
    ['Feed RMS current at rated power', `${feedCurrent(spec.powerW ?? 1).toFixed(3)} A`],
    ['50 Ω line current capacity (ΔT 20 K)', `${traceCurrentLimit(D.feed.feedLineWidth, spec.tCu ?? 35e-6).currentA.toFixed(2)} A`],
  ]);

  // ---- pulsed -------------------------------------------------------------
  if (spec.pulsed) {
    const pr = pulsedRise(th.riseK, th.tauSeconds, spec.pulseUs * 1e-6, (spec.pulseUs * 1e-6) / (spec.duty / 100));
    const c2b = card(root, 'Pulsed operation');
    dataTable(c2b, ['Quantity', 'Value'], [
      ['Duty cycle', `${(pr.duty * 100).toFixed(2)} %`],
      ['Average temperature rise', `${pr.averageRiseK.toFixed(2)} K`],
      ['Single-pulse adiabatic rise', `${pr.pulseOnlyRiseK.toExponential(2)} K`],
      ['Verdict', pr.averageRiseK < th.tLimitC - th.tAmbC ? 'Average power dominates — thermally safe' : 'Average power exceeds the laminate limit'],
    ]);
  }

  // ---- frequency drift ----------------------------------------------------
  const c3 = card(root, 'Resonance drift over temperature',
    'Dk falls with temperature (TCDk) which pushes the resonance up; the copper expands (CTE) which pulls it down. The net drift eats impedance bandwidth you have already paid for.');
  const temps = Array.from({ length: 61 }, (_, i) => -55 + i * 3);
  lineChart(chartBox(c3), {
    height: 320,
    series: [
      { name: 'Resonant frequency shift', points: temps.map((t) => ({ x: t, y: frequencyDrift(D.stack.baseMaterial, D.spec.f, t - 25).relative * 100 })) },
      { name: 'Half-bandwidth edge (+)', points: temps.map((t) => ({ x: t, y: (D.sol.fbw2 / 2) * 100 })), dash: '5 4', color: 'var(--series-2)' },
      { name: 'Half-bandwidth edge (−)', points: temps.map((t) => ({ x: t, y: -(D.sol.fbw2 / 2) * 100 })), dash: '5 4', color: 'var(--series-2)' },
    ],
    xLabel: 'temperature [°C]', yLabel: 'frequency shift [%]',
    vlines: [{ x: spec.tMinC ?? -40, label: 'T min', kind: 'spec' }, { x: spec.tMaxC ?? 85, label: 'T max', kind: 'spec' }],
    tipFmt: (p) => `${p.y.toFixed(3)} %`,
    note: `${D.stack.baseMaterial.name}: TCDk ${D.stack.baseMaterial.tcdk} ppm/°C, in-plane CTE ${D.stack.baseMaterial.ctexy} ppm/°C.`,
  });
  const dr = D.drift;
  const verdict = dr.bandwidthConsumedPct < 30 ? 'good' : dr.bandwidthConsumedPct < 60 ? 'warn' : 'bad';
  callout(root, verdict,
    `Temperature drift consumes ${dr.bandwidthConsumedPct.toFixed(0)} % of the impedance bandwidth`,
    `Over ${spec.tMinC ?? -40} to ${spec.tMaxC ?? 85} °C the resonance moves ${(dr.totalSpan * 100).toFixed(3)} % against a ${(D.sol.fbw2 * 100).toFixed(2)} % VSWR-2 bandwidth. Usable bandwidth after drift: ${dr.usableBwPct.toFixed(2)} %. ${verdict === 'bad' ? 'Move to a low-TCDk laminate such as RO3003 (13 ppm/°C) or widen the design bandwidth.' : ''}`);

  // ---- breakdown / altitude ----------------------------------------------
  const c4 = card(root, 'Voltage breakdown and altitude',
    'Peak RF voltage appears across the radiating edges. At altitude the air thins and the Paschen minimum drops the breakdown voltage by an order of magnitude — the classic cause of avionics and space antenna arcing.');
  const alts = Array.from({ length: 41 }, (_, i) => i * 750);
  lineChart(chartBox(c4), {
    height: 320,
    series: [
      { name: 'Paschen breakdown across the substrate gap', points: alts.map((a) => ({ x: a / 1000, y: paschenVoltage(D.stack.h, 101325 * Math.pow(1 - 2.25577e-5 * a, 5.25588)) })) },
      { name: 'Patch edge voltage at rated peak power', points: alts.map((a) => ({ x: a / 1000, y: pk.vEdge })), color: 'var(--series-2)', dash: '5 4' },
    ],
    xLabel: 'altitude [km]', yLabel: 'voltage [V]',
    tipFmt: (p) => `${p.y.toFixed(0)} V`,
    note: 'Below the Paschen minimum (very low pressure) breakdown voltage rises again — but multipaction becomes the failure mode instead above ~30 km.',
  });
  dataTable(c4, ['Quantity', 'Value', 'Note'], [
    ['Peak edge voltage', `${pk.vEdge.toFixed(0)} V`, `at ${(spec.peakPowerW ?? spec.powerW ?? 1).toFixed(1)} W peak into ${D.sol.Rin.toFixed(0)} Ω`],
    ['E-field in the laminate', `${pk.eFieldKvPerMm.toFixed(3)} kV/mm`, `strength ${pk.dielectricStrengthKvPerMm} kV/mm`],
    ['Margin to dielectric breakdown', `${pk.marginDielectric.toFixed(0)}×`, pk.marginDielectric > 5 ? 'ample' : 'review'],
    ['Air breakdown (Paschen) at altitude', `${pk.paschenVoltage.toFixed(0)} V`, `${((spec.altitudeM ?? 0) / 1000).toFixed(1)} km, ${(pk.pressurePa / 1000).toFixed(1)} kPa`],
    ['Peak power limit', pk.pMaxPeakW > 1e5 ? '> 100 kW' : `${(pk.pMaxPeakW / 1000).toFixed(2)} kW`, 'lower of dielectric and air limits'],
    ['Multipaction risk', pk.multipactionRisk ? 'YES — vacuum operation' : 'No', 'above ~30 km / in vacuum'],
  ]);
}

/* ============================================================= TOLERANCE */

export function renderTolerance(root, D, state) {
  const spec = D.spec;
  const proc = state.process || 'standard';
  const band = spec.bwPct
    ? [spec.f * (1 - spec.bwPct / 200), spec.f * (1 + spec.bwPct / 200)]
    : [spec.f * 0.995, spec.f * 1.005];
  const mc = monteCarlo({
    f0: spec.f, material: D.stack.material, h: D.stack.h,
    W: D.sol.W, L: D.sol.L, process: proc,
    dkTol: state.dkTol ?? defaultDkTolerance(D.stack.baseMaterial),
    gapTolUm: D.stack.composite ? (state.gapTolUm ?? 100) : 0,
    n: state.mcSamples || 2500, bandHz: band, vswrLimit: state.vswrLimit || 2,
  });

  const tl = h('div', { class: 'tiles' }, root);
  tile(tl, 'Predicted yield', mc.yieldPct.toFixed(1), '%', `VSWR ≤ ${state.vswrLimit || 2} across ${(band[0] / 1e9).toFixed(3)}–${(band[1] / 1e9).toFixed(3)} GHz`,
    mc.yieldPct > 95 ? 'good' : mc.yieldPct > 80 ? 'warn' : 'bad');
  tile(tl, 'Resonance spread (1σ)', (mc.f.sdPpm / 1e4).toFixed(3), '%', `${(mc.f.sd / 1e6).toFixed(2)} MHz`);
  tile(tl, '5th–95th percentile', `${(mc.f.p5 / 1e9).toFixed(4)}–${(mc.f.p95 / 1e9).toFixed(4)}`, 'GHz', `median ${(mc.f.p50 / 1e9).toFixed(4)} GHz`);
  tile(tl, 'Gain spread', `${mc.gain.p5.toFixed(2)}–${mc.gain.p95.toFixed(2)}`, 'dBi', `median ${mc.gain.p50.toFixed(2)} dBi`);
  tile(tl, 'Samples', String(mc.n), '', `${mc.process.name}`);

  controlRow(root, state, [
    { key: 'dkTol', label: 'Dk tolerance (±, 3σ)', step: 0.01, min: 0, def: defaultDkTolerance(D.stack.baseMaterial) },
    { key: 'vswrLimit', label: 'Accept VSWR ≤', step: 0.1, min: 1.1 },
    { key: 'mcSamples', label: 'Samples', step: 500, min: 200, max: 20000 },
    ...(D.stack.composite ? [{ key: 'gapTolUm', label: 'Air-gap tolerance (±, 3σ)', unit: 'µm', step: 10, min: 0, def: 100 }] : []),
  ]);

  const toolbar = h('div', { class: 'toolbar' }, root);
  h('span', { class: 'small muted', text: 'Process class:' }, toolbar);
  Object.entries(PROCESS_CLASSES).forEach(([k, v]) => {
    const b = h('button', { text: v.name }, toolbar);
    if (k === proc) b.classList.add('primary');
    b.addEventListener('click', () => { state.process = k; state.rerender(); });
  });

  if (mc.yieldPct < 90) {
    const bias = spec.f - mc.f.p50;
    callout(root, mc.yieldPct < 60 ? 'bad' : 'warn',
      `Predicted first-pass yield ${mc.yieldPct.toFixed(0)} %`,
      `Dominant contributor: ${dominantContributor(mc, D)}. ` +
      (Math.abs(bias / spec.f) > 1e-4
        ? `The median part lands ${((mc.f.p50 - spec.f) / 1e6).toFixed(2)} MHz off target — pre-bias the artwork by ${(bias / 1e6).toFixed(2)} MHz (${((bias / spec.f) * 100).toFixed(3)} %) to recentre. `
        : '') +
      'Widening the bandwidth (thicker substrate, stacked patch, air gap) is the structural fix; tightening the process is the expensive one.');
  } else {
    callout(root, 'good', `Predicted first-pass yield ${mc.yieldPct.toFixed(1)} %`,
      'The design is not tolerance-critical at this process class.');
  }

  const c1 = card(root, 'Resonant-frequency distribution',
    `${mc.n} Monte Carlo samples with Dk ±${mc.dkTolerance.toFixed(3)}, thickness ±${mc.process.hPct} %, etch ±${mc.process.etchUm} µm (all 3σ).`);
  histogramChart(chartBox(c1), {
    height: 320,
    bins: mc.histogram,
    xLabel: 'resonant frequency [GHz]', yLabel: 'parts',
    xFmt: (v) => (v / 1e9).toFixed(4),
    bands: [{ from: band[0], to: band[1], label: 'required band' }],
    vlines: [{ x: spec.f, label: 'target', kind: 'spec' }],
    note: 'Parts whose resonance falls outside the band still pass if their bandwidth covers it — the yield number applies the VSWR test, not just the centre frequency.',
  });

  const c2 = card(root, 'Sensitivity — what actually moves the resonance',
    'Normalised sensitivity of f₀ to each parameter, then multiplied by that parameter’s real tolerance to give the frequency budget each one consumes.');
  const contrib = [
    { label: 'Dk (εr)', s: mc.sensitivity.dk, tol: mc.dkTolerance, unit: '' },
    { label: 'Substrate thickness', s: mc.sensitivity.thickness, tol: mc.process.hPct / 100, unit: 'rel' },
    { label: 'Patch length (etch)', s: mc.sensitivity.length, tol: (mc.process.etchUm * 1e-6) / D.sol.L, unit: 'rel' },
    { label: 'Patch width (etch)', s: mc.sensitivity.width, tol: (mc.process.etchUm * 1e-6) / D.sol.W, unit: 'rel' },
  ].map((c) => ({ ...c, budget: Math.abs(c.s * c.tol) * 100 }));
  barChart(chartBox(c2), {
    height: 300,
    items: contrib.map((c) => ({ label: c.label, value: c.budget, sub: `sensitivity ${c.s.toFixed(3)}, tolerance ±${(c.tol * (c.unit === 'rel' ? 100 : 1)).toFixed(c.unit === 'rel' ? 1 : 3)}${c.unit === 'rel' ? ' %' : ''}` })),
    yLabel: 'frequency budget consumed [%]',
    valueFmt: (v) => `${v.toFixed(3)}%`,
    hlines: [{ y: (D.sol.fbw2 * 100) / 2, label: 'half the impedance bandwidth' }],
    note: 'Any single contributor approaching half the bandwidth is a first-pass yield problem.',
  });

  const c3 = card(root, 'Yield against process class and bandwidth');
  const classes = Object.keys(PROCESS_CLASSES);
  dataTable(c3, ['Process class', 'Etch tol.', 'Thickness tol.', 'Predicted yield'],
    classes.map((k) => {
      const m = monteCarlo({
        f0: spec.f, material: D.stack.material, h: D.stack.h, W: D.sol.W, L: D.sol.L,
        process: k, dkTol: state.dkTol ?? defaultDkTolerance(D.stack.baseMaterial),
        gapTolUm: D.stack.composite ? (state.gapTolUm ?? 100) : 0,
        n: 900, bandHz: band, vswrLimit: state.vswrLimit || 2,
      });
      return [PROCESS_CLASSES[k].name, `±${PROCESS_CLASSES[k].etchUm} µm`, `±${PROCESS_CLASSES[k].hPct} %`, `${m.yieldPct.toFixed(1)} %`];
    }));
  h('p', { class: 'chart-note', text: 'Dk tolerance is a material property and does not improve with process class — on FR-4 it is usually the binding term, which is the real argument for an RF laminate.' }, c3);
}

function dominantContributor(mc, D) {
  const items = [
    ['laminate Dk tolerance', Math.abs(mc.sensitivity.dk * mc.dkTolerance)],
    ['substrate thickness tolerance', Math.abs(mc.sensitivity.thickness * mc.process.hPct / 100)],
    ['etch tolerance on the patch length', Math.abs(mc.sensitivity.length * (mc.process.etchUm * 1e-6) / D.sol.L)],
  ].sort((a, b) => b[1] - a[1]);
  return items[0][0];
}

/* =========================================================== LINK BUDGET */

export function renderLink(root, D, state) {
  const spec = D.spec;
  const rainRate = state.rainMmH ?? 0;
  const rainRef = rainRate > 0 ? rainRate : 25;

  controlRow(root, state, [
    { key: 'ptxDbm', label: 'Tx power', unit: 'dBm', step: 0.5 },
    { key: 'grxDbi', label: 'Rx antenna gain', unit: 'dBi', step: 0.5 },
    { key: 'distanceM', label: 'Link distance', unit: 'm', step: 10, min: 1 },
    { key: 'bwMHz', label: 'Channel bandwidth', unit: 'MHz', step: 1, min: 0.001 },
    { key: 'nfDb', label: 'Rx noise figure', unit: 'dB', step: 0.5 },
    { key: 'snrDb', label: 'Required SNR', unit: 'dB', step: 1 },
    { key: 'rainMmH', label: 'Rain rate', unit: 'mm/h', step: 5, min: 0 },
    { key: 'humidity', label: 'Water vapour', unit: 'g/m³', step: 0.5, min: 0 },
    { key: 'htM', label: 'Tx height', unit: 'm', step: 1, min: 0.5 },
    { key: 'hrM', label: 'Rx height', unit: 'm', step: 0.5, min: 0.5 },
  ]);
  const lk = {
    f: spec.f, ptxDbm: state.ptxDbm ?? 20, gtxDbi: D.realizedGainDbi,
    grxDbi: state.grxDbi ?? 2, bandwidth: (state.bwMHz ?? 20) * 1e6,
    nfDb: state.nfDb ?? 6, requiredSnrDb: state.snrDb ?? 10,
    model: state.propModel || 'fspl', rainRateMmH: state.rainMmH ?? 0,
    humidity: state.humidity ?? 7.5, tempC: spec.tAmbC ?? 15,
    ht: state.htM ?? 10, hr: state.hrM ?? 1.5,
  };
  const d0 = (state.distanceM ?? 1000);
  const lb = linkBudget({ ...lk, distance: d0 });
  const range = maxRange(lk);

  const tl = h('div', { class: 'tiles' }, root);
  tile(tl, 'EIRP', lb.eirpDbm.toFixed(1), 'dBm', `${(fromDB(lb.eirpDbm - 30) * 1000).toFixed(0)} mW · Tx gain ${D.realizedGainDbi.toFixed(1)} dBi`);
  tile(tl, `Rx power at ${(d0 / 1000).toFixed(2)} km`, lb.prxDbm.toFixed(1), 'dBm', `path ${lb.totalPathDb.toFixed(1)} dB`);
  tile(tl, 'Link margin', lb.marginDb.toFixed(1), 'dB', `sensitivity ${lb.sensitivityDbm.toFixed(1)} dBm`,
    lb.marginDb > 10 ? 'good' : lb.marginDb > 0 ? 'warn' : 'bad');
  tile(tl, 'Max range', range > 1000 ? (range / 1000).toFixed(2) : range.toFixed(0), range > 1000 ? 'km' : 'm', 'margin = 0 dB');
  tile(tl, 'SNR', lb.snrDb.toFixed(1), 'dB', `Shannon ${(lb.shannonBps / 1e6).toFixed(1)} Mb/s in ${(lk.bandwidth / 1e6).toFixed(0)} MHz`);
  tile(tl, '60 % Fresnel radius', lb.fresnel60.toFixed(2), 'm', `at midpoint of a ${(d0 / 1000).toFixed(2)} km path`);

  const c1 = card(root, 'Received power against distance',
    'Free-space plus the atmospheric terms your frequency actually suffers. The curve crosses the sensitivity line at the maximum range.');
  const ds = Array.from({ length: 90 }, (_, i) => Math.pow(10, 0.5 + (i / 89) * 4.2));
  const models = [['fspl', 'Free space (Friis)'], ['twoRay', 'Two-ray ground reflection'], ['hata', 'COST-231 Hata urban']];
  lineChart(chartBox(c1), {
    height: 340, xLog: true,
    series: models.map(([m, name]) => ({
      name, points: ds.map((d) => ({ x: d, y: linkBudget({ ...lk, model: m, distance: d }).prxDbm })),
    })),
    xLabel: 'distance [m]', yLabel: 'received power [dBm]',
    xFmt: (v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(0)),
    hlines: [{ y: lb.sensitivityDbm, label: `sensitivity ${lb.sensitivityDbm.toFixed(0)} dBm`, kind: 'spec' },
             { y: lb.noiseDbm, label: `noise floor ${lb.noiseDbm.toFixed(0)} dBm` }],
    vlines: [{ x: d0, label: 'operating range' }],
    tipFmt: (p) => `${p.y.toFixed(1)} dBm`,
    note: 'Below the two-ray breakpoint the two-ray and free-space curves are identical by construction, so they overlap. COST-231 Hata is only calibrated for 1.5–3 GHz macro-cells; outside that range it is shown for reference, not as a prediction.',
  });

  const c2 = card(root, 'Atmospheric absorption across the spectrum',
    'Oxygen resonates near 60 and 118 GHz, water vapour near 22, 183 and 325 GHz. These are not engineering choices — they decide which bands can carry a long link at all.');
  const fsG = Array.from({ length: 240 }, (_, i) => 1 + i * 1.25);
  lineChart(chartBox(c2), {
    height: 340,
    series: [
      { name: 'Dry air (O₂)', points: fsG.map((g) => ({ x: g, y: gaseousAttenuation(g * 1e9, 15, 1013.25, 0.001).oxygen })) },
      { name: `Water vapour (${(state.humidity ?? 7.5).toFixed(1)} g/m³)`, points: fsG.map((g) => ({ x: g, y: gaseousAttenuation(g * 1e9, 15, 1013.25, state.humidity ?? 7.5).water })) },
      { name: `Rain ${rainRef} mm/h${rainRate > 0 ? '' : ' (reference)'}`, points: fsG.map((g) => ({ x: g, y: rainAttenuation(g * 1e9, rainRef).gammaR })), color: 'var(--series-3)' },
    ],
    xLabel: 'frequency [GHz]', yLabel: 'specific attenuation [dB/km]',
    yDomain: { min: 0, max: 30 },
    vlines: [{ x: spec.f / 1e9, label: 'design frequency', kind: 'spec' }],
    tipFmt: (p) => `${p.y.toFixed(3)} dB/km`,
    xUnit: 'GHz',
    note: `At ${engFreq(spec.f)}: gases ${lb.gasDbPerKm.toFixed(4)} dB/km, rain ${rainAttenuation(spec.f, rainRef).gammaR.toFixed(3)} dB/km at ${rainRef} mm/h. Model follows ITU-R P.676 and P.838.${rainRate > 0 ? '' : ' Rain is set to 0 in the budget below; the curve shows a 25 mm/h reference storm.'}`,
  });

  const c3 = card(root, 'Link budget line by line', 'The table a design review will ask for.');
  dataTable(c3, ['Term', 'Value', 'Note'], [
    ['Transmit power', `${lk.ptxDbm.toFixed(1)} dBm`, `${fromDB(lk.ptxDbm - 30).toFixed(3)} W`],
    ['Transmit cable/connector loss', '−0.5 dB', 'default allowance'],
    ['Transmit antenna gain', `+${D.realizedGainDbi.toFixed(2)} dBi`, 'this design, realized'],
    ['EIRP', `${lb.eirpDbm.toFixed(2)} dBm`, D.band && D.band.eirpDbm !== null
      ? (lb.eirpDbm > D.band.eirpDbm ? `EXCEEDS the ${D.band.eirpDbm} dBm limit for ${D.band.name}` : `within the ${D.band.eirpDbm} dBm limit for ${D.band.name}`)
      : 'no regulatory limit loaded'],
    ['Free-space path loss', `−${lb.fsplDb.toFixed(2)} dB`, `${(d0 / 1000).toFixed(3)} km at ${engFreq(spec.f)}`],
    ['Atmospheric gases', `−${lb.gasDb.toFixed(3)} dB`, `${lb.gasDbPerKm.toFixed(4)} dB/km`],
    ['Rain', `−${lb.rainDb.toFixed(3)} dB`, `${state.rainMmH ?? 0} mm/h`],
    ['Receive antenna gain', `+${lk.grxDbi.toFixed(1)} dBi`, 'assumed'],
    ['Receive cable loss', '−0.5 dB', 'default allowance'],
    ['Received power', `${lb.prxDbm.toFixed(2)} dBm`, ''],
    ['Thermal noise kTB', `${(lb.noiseDbm - lk.nfDb).toFixed(2)} dBm`, `${(lk.bandwidth / 1e6).toFixed(1)} MHz at 290 K`],
    ['Receiver noise figure', `+${lk.nfDb.toFixed(1)} dB`, ''],
    ['Noise floor', `${lb.noiseDbm.toFixed(2)} dBm`, ''],
    ['Required SNR', `${lk.requiredSnrDb.toFixed(1)} dB`, 'plus 2 dB implementation loss'],
    ['Sensitivity', `${lb.sensitivityDbm.toFixed(2)} dBm`, ''],
    ['LINK MARGIN', `${lb.marginDb.toFixed(2)} dB`, lb.marginDb > 10 ? 'comfortable' : lb.marginDb > 0 ? 'thin — no fade allowance' : 'link does not close'],
  ]);

  const c4 = card(root, 'Range, clearance and exposure');
  dataTable(c4, ['Quantity', 'Value', 'Note'], [
    ['Maximum range (0 dB margin)', range > 1000 ? `${(range / 1000).toFixed(3)} km` : `${range.toFixed(1)} m`, 'no fade margin'],
    ['Range with 10 dB fade margin', `${(maxRange({ ...lk, requiredSnrDb: lk.requiredSnrDb + 10 }) / 1000).toFixed(3)} km`, 'recommended for a deployed link'],
    ['1st Fresnel zone radius (midpoint)', `${lb.fresnelR1.toFixed(2)} m`, 'keep 60 % clear of obstacles'],
    ['60 % Fresnel clearance needed', `${lb.fresnel60.toFixed(2)} m`, 'the practical LOS criterion'],
    ['Radio horizon (k = 4/3)', `${lb.horizonKm.toFixed(2)} km`, `Tx ${lk.ht} m, Rx ${lk.hr} m`],
    ['Far-field distance', `${(D.fieldRegions.farField * 1e3).toFixed(0)} mm`, `max(2D²/λ = ${(D.fieldRegions.fraunhofer * 1e3).toFixed(0)} mm, 3λ) — minimum measurement range`],
    ['MPE safe distance (10 W/m²)', `${(mpeDistance(lb.eirpDbm) * 100).toFixed(1)} cm`, 'ICNIRP/FCC general-population'],
  ]);
}

/* ============================================================== DRAWINGS */

export function renderDrawings(root, D) {
  const c1 = card(root, 'Stack-up', 'Generated from the solved design — the drawing cannot go out of step with the numbers.');
  stackupDiagram(chartBox(c1), D);

  const c2 = card(root, 'Etch geometry');
  const g = h('div', { class: 'grid2' }, c2);
  planView(chartBox(g), D);
  const dims = h('div', {}, g);
  dataTable(dims, ['Feature', 'Dimension', 'Tolerance guidance'], [
    ['Patch width W', mm(D.sol.W), '±25 µm standard etch'],
    ['Patch length L', mm(D.sol.L), 'sets the resonance — tightest control here'],
    ['Ground plane X (E-plane)', `${(D.groundXM * 1e3).toFixed(1)} mm`, `margin ${((D.groundXM - D.sol.L) / 2 * 1e3).toFixed(1)} mm per side beyond the radiating edges`],
    ['Ground plane Y (H-plane)', `${(D.groundYM * 1e3).toFixed(1)} mm`, `margin ${((D.groundYM - D.sol.W) / 2 * 1e3).toFixed(1)} mm per side`],
    ['Substrate height', mm(D.stack.h), `±${D.stack.composite ? '0.10 mm (spacer stack)' : '10 % (core)'}`],
    ['50 Ω feed width', mm(D.feed.feedLineWidth), '±25 µm'],
    ...(D.feed.insetDepth !== undefined ? [['Inset depth', mm(D.feed.insetDepth), '±50 µm — trims the match, not the frequency']] : []),
    ...(D.feed.probeOffset !== undefined ? [['Probe offset', mm(D.feed.probeOffset), '±100 µm']] : []),
    ['Copper thickness', `${((D.spec.tCu ?? 35e-6) * 1e6).toFixed(0)} µm`, '1 oz nominal'],
  ]);

  const c3 = card(root, 'Manufacturing and assembly notes');
  const ul = h('ul', { class: 'ref-list' }, c3);
  const notes = [
    `Substrate: ${D.stack.baseMaterial.name} — ${D.stack.baseMaterial.notes}`,
    `Keep the ground plane continuous for at least ${((D.groundXM - D.sol.L) / 2 * 1e3).toFixed(1)} mm beyond the radiating edges (X) and ${((D.groundYM - D.sol.W) / 2 * 1e3).toFixed(1)} mm beyond the side edges (Y); splits, stitching gaps and component keep-outs under the patch all show up as pattern distortion. The X margin is the one that matters most - it sits beyond the edges that actually radiate.`,
    `Surface finish: ENIG adds a nickel layer whose conductivity is 4× worse than copper. On a ${(D.stack.h * 1e3).toFixed(2)} mm stack that is worth roughly ${(0.3 * (0.001 / Math.max(D.stack.h, 1e-4))).toFixed(2)} dB — prefer OSP or immersion silver for the radiating layer.`,
    `Solder mask over the patch raises the effective permittivity slightly and adds loss; specify mask-free (SMD-defined keep-out) over the radiator and note it on the fabrication drawing.`,
    D.stack.composite
      ? `Air gap is set by the spacer stack, not by the PCB: specify ${(D.stack.layers[0].h * 1e3).toFixed(2)} mm nylon spacers with a ±0.05 mm length tolerance and torque-controlled assembly. Gap error translates directly into frequency error.`
      : `Core thickness tolerance is typically ±10 % on FR-4 and ±5 % on RF laminates — this is usually the second-largest yield contributor after Dk.`,
    `Test: measure S₁₁ with the antenna in its final housing. A 2 mm ABS radome 1 mm above this patch will pull the resonance down by roughly ${(1.2 * (2 / (D.stack.h * 1e3 + 2))).toFixed(1)} %.`,
    `Far-field measurement distance must exceed ${(D.fieldRegions.farField * 1e3).toFixed(0)} mm (2D²/λ) — measuring closer under-reads the gain.`,
  ];
  notes.forEach((n) => h('li', { text: n }, ul));
}

/* ================================================================ THEORY */

const THEORY_SECTIONS = [
  ['operating', 'Operating point'],
  ['equations', 'Design equations'],
  ['limits', 'Fundamental limits'],
  ['aperture', 'Aperture, gain & beamwidth'],
  ['materials', 'Substrate data'],
  ['conductors', 'Conductors & skin effect'],
  ['lines', 'Transmission lines'],
  ['bands', 'Bands & regulations'],
  ['atmosphere', 'Atmosphere & propagation'],
  ['conversions', 'Conversions & noise'],
  ['constants', 'Constants & symbols'],
];

/**
 * The physical and theoretical background an antenna designer needs, evaluated
 * at the current operating point rather than printed as a static table - so it
 * doubles as a worked example of the design being carried out.
 */
export function renderTheory(root, D, state) {
  const sec = state.theorySection || 'operating';
  const nav = h('div', { class: 'chip-nav' }, root);
  for (const [id, label] of THEORY_SECTIONS) {
    const b = h('button', { class: 'chip', text: label }, nav);
    b.setAttribute('aria-pressed', String(id === sec));
    b.addEventListener('click', () => { state.theorySection = id; state.rerender(); });
  }
  const f = D.spec.f, lam = D.lambda0;
  const mat = D.stack.material;
  const cu = D.conductor;

  const fn = {
    operating: theoryOperating, equations: theoryEquations, limits: theoryLimits,
    aperture: theoryAperture, materials: theoryMaterials, conductors: theoryConductors,
    lines: theoryLines, bands: theoryBands, atmosphere: theoryAtmosphere,
    conversions: theoryConversions, constants: theoryConstants,
  }[sec] || theoryOperating;
  fn(root, D, state, { f, lam, mat, cu });
}

function theoryOperating(root, D, state, k) {
  const { f, lam, mat, cu } = k;
  const c1 = card(root, 'Operating point',
    'Every quantity below is derived from the frequency and stack-up currently in the sidebar. Change either and this page changes with it.');
  const g = h('div', { class: 'grid2' }, c1);
  const lamG = lam / Math.sqrt(D.sol.epsEff);
  const omega = 2 * Math.PI * f;
  dataTable(h('div', {}, g), ['Quantity', 'Symbol', 'Value'], [
    ['Frequency', 'f', engFreq(f)],
    ['Angular frequency', 'ω = 2πf', `${(omega / 1e9).toFixed(4)} Grad/s`],
    ['Period', 'T = 1/f', `${(1e12 / f).toFixed(2)} ps`],
    ['Free-space wavelength', 'λ₀ = c/f', `${(lam * 1e3).toFixed(3)} mm`],
    ['Free-space wavenumber', 'k₀ = 2π/λ₀', `${((2 * Math.PI) / lam).toFixed(2)} rad/m`],
    ['Quarter wavelength', 'λ₀/4', `${((lam / 4) * 1e3).toFixed(3)} mm`],
    ['Guided wavelength', 'λg = λ₀/√εeff', `${(lamG * 1e3).toFixed(3)} mm`],
    ['Effective permittivity', 'εeff', D.sol.epsEff.toFixed(4)],
    ['Substrate permittivity at f', 'εr(f)', `${mat.er.toFixed(4)} (dispersion applied)`],
    ['Loss tangent at f', 'tanδ(f)', mat.df.toFixed(5)],
    ['Dielectric Q ceiling', 'Q_d = 1/tanδ', mat.df > 0 ? (1 / mat.df).toFixed(1) : '∞'],
    ['Electrical height', 'h/λ₀', (D.stack.h / lam).toFixed(4)],
  ]);
  dataTable(h('div', {}, g), ['Quantity', 'Symbol', 'Value'], [
    ['Conductor', '', cu.name],
    ['Conductivity', 'σ', `${(cu.sigma / 1e7).toFixed(3)} × 10⁷ S/m`],
    ['Skin depth', 'δ = 1/√(πfμσ)', `${(skinDepth(f, cu.sigma) * 1e6).toFixed(3)} µm`],
    ['Copper thickness in skin depths', 't/δ', ((D.spec.tCu ?? 35e-6) / skinDepth(f, cu.sigma)).toFixed(2)],
    ['Surface resistance', 'Rs = √(πfμ/σ)', `${(surfaceResistance(f, cu.sigma) * 1e3).toFixed(2)} mΩ/sq`],
    ['Reactive near-field boundary', '0.62√(D³/λ)', `${(D.fieldRegions.reactiveNearField * 1e3).toFixed(1)} mm`],
    ['Far-field (Fraunhofer)', '2D²/λ', `${(D.fieldRegions.fraunhofer * 1e3).toFixed(1)} mm`],
    ['Far-field criterion in use', 'max(2D²/λ, 3λ)', `${(D.fieldRegions.farField * 1e3).toFixed(1)} mm`],
    ['Free-space impedance', 'η₀ = √(µ₀/ε₀)', '376.730 Ω'],
    ['Substrate wave impedance', 'η₀/√εr', `${(376.730 / Math.sqrt(mat.er)).toFixed(2)} Ω`],
    ['Path loss at 1 m', '20log₁₀(4πd/λ)', `${fspl(f, 1).toFixed(2)} dB`],
    ['Thermal noise in 1 MHz', 'kTB at 290 K', `${noiseFloorDbm(1e6).toFixed(2)} dBm`],
  ]);

  const c2 = card(root, 'Wavelength across the spectrum',
    'The single number that sets every antenna dimension. The marker is the current design frequency.');
  const pts = [];
  for (let i = 0; i <= 200; i++) {
    const fg = Math.pow(10, -1.5 + (i / 200) * 4);   // 30 MHz to 300 GHz
    pts.push({ x: fg, y: (C0 / (fg * 1e9)) * 1e3 });
  }
  lineChart(chartBox(c2), {
    height: 300, xLog: true,
    series: [{ name: 'λ₀', points: pts }],
    xLabel: 'frequency [GHz]', yLabel: 'free-space wavelength [mm]',
    xFmt: (v) => (v >= 1 ? v.toFixed(0) : v.toFixed(2)),
    yFmt: (v) => (v >= 1000 ? `${(v / 1000).toFixed(0)} m` : v.toFixed(0)),
    vlines: [{ x: f / 1e9, label: engFreq(f), kind: 'spec' }],
    tipFmt: (p) => (p.y >= 1000 ? `${(p.y / 1000).toFixed(2)} m` : `${p.y.toFixed(1)} mm`),
    directLabels: false, table: false,
    note: 'A half-wave resonator is λ₀/2 in air and λ₀/(2√εeff) on a substrate — the whole miniaturisation trade in one line.',
  });
}

function theoryEquations(root, D, state, k) {
  const { f, lam, mat } = k;
  const s = D.sol;
  const c1 = card(root, 'The equations, with this design substituted in',
    'Each block shows the governing relation and then the same relation evaluated at the current operating point, so the numbers can be checked by hand.');

  const block = (title, eq, evaluated, why) => {
    const b = h('div', { class: 'eq-block' }, c1);
    h('div', { class: 'eq-title', text: title }, b);
    h('span', { class: 'eq', text: eq }, b);
    h('span', { class: 'eq evaluated', text: evaluated }, b);
    if (why) h('p', { class: 'chart-note', text: why }, b);
  };

  block('Patch width for best efficiency (Balanis 14-6)',
    'W = (c / 2f) · √(2 / (εr + 1))',
    `W = (2.99792e8 / (2 × ${(f / 1e9).toFixed(4)}e9)) × √(2 / (${mat.er.toFixed(3)} + 1)) = ${(s.W * 1e3).toFixed(3)} mm`,
    'Wider radiates better but risks exciting the next mode; this is the standard compromise.');

  // Hammerstad's exponent is -a*b, not the -1/2 of the textbook shorthand;
  // solving for it here keeps the printed arithmetic reproducible by hand.
  const uWH = s.W / D.stack.h;
  const abExp = Math.log((s.epsEff - (mat.er + 1) / 2) / ((mat.er - 1) / 2)) / Math.log(1 + 10 / uWH);
  block('Effective permittivity (Hammerstad & Jensen)',
    'εeff = (εr+1)/2 + ((εr−1)/2) · (1 + 10h/W)^(−a·b)\n   a = f(W/h),  b = f(εr)   [the textbook shorthand uses (1+12h/W)^(−1/2)]',
    `εeff = ${((mat.er + 1) / 2).toFixed(3)} + ${((mat.er - 1) / 2).toFixed(3)} × (1 + 10/${uWH.toFixed(3)})^(−${Math.abs(abExp).toFixed(4)}) = ${s.epsEff.toFixed(4)}`,
    'Part of the field is in air, so the guided wave sees less than the bulk permittivity. The exponent a·b is close to 0.5 for ordinary W/h, which is where the shorthand comes from.');

  block('Fringing extension',
    'ΔL/h = 0.412 · (εeff+0.3)(W/h+0.264) / ((εeff−0.258)(W/h+0.8))',
    `ΔL = ${(s.dL * 1e3).toFixed(4)} mm per radiating edge, so Le = L + 2ΔL = ${(s.Le * 1e3).toFixed(3)} mm`,
    'The patch is electrically longer than it is physically — this is where the radiation comes from.');

  block('Resonant length',
    'L = c / (2f√εeff) − 2ΔL',
    `L = ${(C0 / (2 * f * Math.sqrt(s.epsEff)) * 1e3).toFixed(3)} − 2 × ${(s.dL * 1e3).toFixed(4)} = ${(s.L * 1e3).toFixed(3)} mm`);

  block('Radiation quality factor',
    'Q_rad = 2π²·εeff·Le / (k₀·h·W·I),   I = ∮ |F(θ,φ)|² dΩ',
    `Q_rad = 2π² × ${s.epsEff.toFixed(3)} × ${(s.Le * 1e3).toFixed(2)}e−3 / (${((2 * Math.PI) / lam).toFixed(1)} × ${(D.stack.h * 1e3).toFixed(2)}e−3 × ${(s.W * 1e3).toFixed(2)}e−3 × ${s.patternIntegral.toFixed(3)}) = ${s.Qrad.toFixed(1)}`,
    'Derived from the physical aperture rather than a fitted formula, so it stays correct for thick and low-permittivity substrates.');

  block('Loss channels combine as parallel Qs',
    '1/Q_t = 1/Q_rad + 1/Q_d + 1/Q_c + 1/Q_sw',
    `1/${s.Qt.toFixed(1)} = 1/${s.Qrad.toFixed(1)} + 1/${s.Qd.toFixed(1)} + 1/${s.Qc.toFixed(0)} + 1/${s.Qsw > 1e6 ? '∞' : s.Qsw.toFixed(0)}`,
    'The smallest Q dominates. That is the one worth engineering — everything else is second order.');

  block('Radiation efficiency and bandwidth',
    'η = Q_t / Q_rad          BW(VSWR = S) = (S−1) / (Q_t·√S)',
    `η = ${s.Qt.toFixed(1)} / ${s.Qrad.toFixed(1)} = ${(s.etaSpace * 100).toFixed(1)} %      BW(2:1) = 1/(${s.Qt.toFixed(1)} × 1.414) = ${(s.fbw2 * 100).toFixed(3)} %`,
    'Efficiency and bandwidth are the same trade seen from two sides: both improve with a thicker, lower-loss substrate.');

  block('Edge resistance and inset feed',
    'Rin = 1 / (2(G₁ + G₁₂)),   Rin(y₀) = Rin(0)·cos²(π y₀ / L)',
    `Rin = 1 / (2 × (${(s.G1 * 1e3).toFixed(4)} + ${(s.G12 * 1e3).toFixed(4)}) mS) = ${s.Rin.toFixed(1)} Ω${D.feed.insetDepth !== undefined ? `, so y₀ = ${(D.feed.insetDepth * 1e3).toFixed(3)} mm reaches 50 Ω` : ''}`);

  block('Surface-wave power ratio (thin-substrate asymptotics)',
    'P_sw / P_sp ≈ (3π/8) · k₀h · (εr−1)³ / εr^2.5',
    `= (3π/8) × ${(((2 * Math.PI) / lam) * D.stack.h).toFixed(4)} × (${mat.er.toFixed(2)}−1)³ / ${mat.er.toFixed(2)}^2.5 = ${s.surfaceWaveRatio.toFixed(4)}`,
    'Grows with both thickness and permittivity — the reason high-Dk mmWave boards go thin or go to SIW.');

  block('Free-space path loss (Friis)',
    'FSPL = 20 log₁₀(4πd/λ)',
    `at 1 km: 20 log₁₀(4π × 1000 / ${(lam).toFixed(4)}) = ${fspl(f, 1000).toFixed(2)} dB`);

  block('Chu–McLean lower bound on Q',
    'Q_min = 1/(ka)³ + 1/(ka)          BW(2:1) ≤ 1 / (√2 · Q_min / η)',
    `ka = ${D.limits.ka.toFixed(3)} → Q_min = 1/${Math.pow(D.limits.ka, 3).toFixed(3)} + 1/${D.limits.ka.toFixed(3)} = ${D.limits.chuQ.toFixed(3)}\n`
    + `with η = ${(D.sol.etaSpace * 100).toFixed(1)} %:  BW(2:1) ≤ 1 / (1.414 × ${(D.limits.chuQ / D.sol.etaSpace).toFixed(3)}) = ${(D.limits.chuBandwidth * 100).toFixed(2)} %`,
    'No geometry beats this for a given enclosing sphere. If the spec needs more, the antenna must get bigger or less efficient.');
}

function theoryLimits(root, D, state, k) {
  const { lam } = k;
  const c1 = card(root, 'What physics allows before any design starts',
    'Two bounds decide whether a specification is possible at all. Chu and McLean bound the bandwidth an enclosing sphere can support; Harrington bounds the directivity. Both depend only on size in wavelengths.');

  const kaPts = [];
  for (let i = 0; i <= 200; i++) {
    const ka = 0.15 + (i / 200) * 11.85;
    kaPts.push({ ka, q: chuQ(ka), d: toDB(harringtonDirectivity((ka * lam) / (2 * Math.PI), lam)),
      bw: (1 / (chuQ(ka) * Math.SQRT2)) * 100 });
  }
  const g = h('div', { class: 'grid2' }, c1);
  lineChart(chartBox(g), {
    height: 320, title: 'Minimum radiation Q against electrical size',
    series: [{ name: 'Q_min', points: kaPts.map((p) => ({ x: p.ka, y: p.q })) }],
    xLabel: 'ka  (a = radius of the enclosing sphere)', yLabel: 'minimum radiation Q',
    yDomain: { min: 0, max: 40 },
    vlines: [{ x: D.limits.ka, label: `this design, ka = ${D.limits.ka.toFixed(2)}`, kind: 'spec' },
             { x: 1, label: 'ka = 1: electrically small', kind: '' }],
    tipFmt: (p) => p.y.toFixed(2), directLabels: false, table: false,
    note: 'Q rises as 1/(ka)³ — halving an antenna multiplies its minimum Q roughly eightfold, which is why small antennas are narrowband.',
  });
  lineChart(chartBox(g), {
    height: 320, title: 'Maximum bandwidth and directivity',
    series: [
      { name: 'max VSWR-2 bandwidth [%]', points: kaPts.map((p) => ({ x: p.ka, y: p.bw })) },
      { name: 'Harrington directivity [dBi]', points: kaPts.map((p) => ({ x: p.ka, y: p.d })), color: 'var(--series-2)' },
    ],
    xLabel: 'ka', yLabel: 'per-axis value (see legend)',
    yDomain: { min: 0, max: 40 },
    vlines: [{ x: D.limits.ka, label: 'this design', kind: 'spec' }],
    tipFmt: (p) => p.y.toFixed(2), directLabels: false, table: false,
    note: 'Both curves are plotted against the same ka axis and both are dimensionless-to-dB quantities of similar range; the legend names which is which.',
  });

  const c2 = card(root, 'Where this design sits');
  dataTable(c2, ['Bound', 'Statement', 'Value here', 'Status'], [
    ['Chu–McLean Q', 'Q ≥ 1/(ka)³ + 1/(ka)', `Q_min = ${D.limits.chuQ.toFixed(2)} at ka = ${D.limits.ka.toFixed(3)}`,
      D.sol.Qt >= D.limits.chuQ ? `design Q_t = ${D.sol.Qt.toFixed(1)} — above the bound, as it must be` : 'below the bound — check the inputs'],
    ['Chu bandwidth', 'BW ≤ (S−1)/(Q_min√S)', `${(D.limits.chuBandwidth * 100).toFixed(2)} %`,
      D.spec.bwPct ? (D.spec.bwPct <= D.limits.chuBandwidth * 100 ? `requirement ${D.spec.bwPct.toFixed(1)} % is achievable` : `requirement ${D.spec.bwPct.toFixed(1)} % is IMPOSSIBLE at this size`) : '-'],
    ['Harrington directivity', 'D ≤ (ka)² + 2ka', `${D.limits.harringtonGainDbi.toFixed(2)} dBi at ${(D.sol.etaSpace * 100).toFixed(0)} % efficiency`,
      D.spec.targetGainDbi <= D.limits.harringtonGainDbi ? `target ${D.spec.targetGainDbi.toFixed(1)} dBi is achievable` : 'target exceeds the bound'],
    ['Aperture gain', 'G = 4πAe/λ²', `${D.limits.apertureGainDbi.toFixed(2)} dBi for the full footprint at 80 % aperture efficiency`, 'upper bound for an aperture of this size'],
    ['Bode–Fano', '|Γ|min = exp(−π/(Q·BW))', `${D.bodeFano.returnLossDb.toFixed(1)} dB return loss`, 'best any lossless matching network can do over the required band'],
    ['Wheeler / radiansphere', 'ka = 1 divides small from resonant', `ka = ${D.limits.ka.toFixed(3)}`,
      D.limits.electricallySmall ? 'electrically SMALL — efficiency and bandwidth are size-limited' : 'resonant-sized — normal design rules apply'],
  ]);
  h('p', { class: 'chart-note', text: 'These are not modelling assumptions: they follow from expanding the field outside a sphere in spherical modes. An antenna that appears to beat them is either larger than assumed, lossy, or measured wrongly.' }, c2);
}

function theoryAperture(root, D, state, k) {
  const { lam } = k;
  const c1 = card(root, 'Aperture, gain and beamwidth',
    'For anything larger than a wavelength these three quantities are the same fact stated three ways. The relations below are what lets you size an antenna before choosing its type.');
  const g = h('div', { class: 'grid2' }, c1);
  const pts = [];
  for (let i = 0; i <= 200; i++) {
    const dL = 0.3 + (i / 200) * 29.7;                 // aperture diameter in lambda
    pts.push({ dL, g: toDB(0.6 * Math.pow(Math.PI * dL, 2)), bw: 70 / dL });
  }
  lineChart(chartBox(g), {
    height: 320, title: 'Gain of a circular aperture', xLog: true,
    series: [{ name: 'gain at 60 % aperture efficiency', points: pts.map((p) => ({ x: p.dL, y: p.g })) }],
    xLabel: 'aperture diameter [λ₀]', yLabel: 'gain [dBi]',
    xFmt: (v) => (v >= 1 ? v.toFixed(0) : v.toFixed(1)),
    tipFmt: (p) => `${p.y.toFixed(1)} dBi`, directLabels: false, table: false,
    note: 'Gain rises 6 dB per doubling of diameter. There is no way around it: high gain is aperture.',
  });
  lineChart(chartBox(g), {
    height: 320, title: 'Beamwidth of the same aperture', xLog: true,
    series: [{ name: '3 dB beamwidth', points: pts.map((p) => ({ x: p.dL, y: p.bw })), color: 'var(--series-2)' }],
    xLabel: 'aperture diameter [λ₀]', yLabel: '3 dB beamwidth [deg]',
    xFmt: (v) => (v >= 1 ? v.toFixed(0) : v.toFixed(1)),
    tipFmt: (p) => `${p.y.toFixed(1)}°`, directLabels: false, table: false,
    note: 'Beamwidth ≈ 70λ/D. A 30 dBi antenna has a 2° beam, and a 2° beam needs a mount that can hold 0.5°.',
  });

  const c2 = card(root, 'Relationships worth memorising');
  dataTable(c2, ['Relation', 'Formula', 'At this design'], [
    ['Directivity from beamwidths', 'D₀ ≈ 32400 / (θ_E · θ_H)', `${D.beamwidth.thetaE.toFixed(0)}° × ${D.beamwidth.thetaH.toFixed(0)}° → ${toDB(32400 / (D.beamwidth.thetaE * D.beamwidth.thetaH)).toFixed(1)} dBi`],
    ['Effective aperture', 'Ae = Gλ²/4π', `${(effectiveAperture(D.realizedGainDbi, lam) * 1e4).toFixed(2)} cm²`],
    ['Aperture efficiency', 'ηap = Ae / Aphysical', `${((effectiveAperture(D.realizedGainDbi, lam) / (D.groundXM * D.groundYM)) * 100).toFixed(1)} % of the ${(D.groundXM * 1e3).toFixed(0)} × ${(D.groundYM * 1e3).toFixed(0)} mm footprint`],
    ['Array gain', 'G = G_element + 10log₁₀(N) − feed loss', 'each doubling of elements is +3 dB minus what the feed takes back'],
    ['Element spacing for no grating lobe', 'd/λ < 1/(1 + |sin θ_scan|)', 'broadside: d < λ. ±60° scan: d < 0.54λ'],
    ['Gain–bandwidth of a small antenna', 'G·BW bounded by (ka)³', 'the Chu bound restated — you may trade them, not beat them'],
    ['Polarisation loss', 'PLF = cos²(Δψ)', '30° misalignment costs 1.25 dB; cross-polarised is a total loss'],
    ['Axial ratio to polarisation loss', 'worst case = 20log₁₀((AR₁AR₂+1)/(AR₁+AR₂))', '3 dB AR against a pure circular source ≈ 0.5 dB worst case'],
  ]);
}

function theoryMaterials(root, D, state, k) {
  const { f, mat } = k;
  const c1 = card(root, `Substrate data at ${engFreq(f)}`,
    'Dk and Df are shown at the current operating frequency using the Djordjevic–Sarkar causal dispersion model, not at the datasheet frequency — the difference matters above a few GHz. The row in use is highlighted.');
  const rows = MATERIALS.map((m) => {
    const d = dispersiveEr(m, f);
    return { m, d, isCurrent: D.stack.baseMaterial && m.id === D.stack.baseMaterial.id };
  }).sort((a, b) => a.d.er - b.d.er);
  const t = dataTable(c1, ['Material', 'Family', `εr @ ${(f / 1e9).toFixed(2)} GHz`, `tanδ @ f`, 'Q_d', 'TCDk [ppm/°C]', 'k [W/m·K]', 'CTE z [ppm]', 'Tg [°C]', 'Cost', 'f max'],
    rows.map((r) => [
      r.m.name, r.m.family, r.d.er.toFixed(3), r.d.df.toFixed(5),
      r.d.df > 0 ? (1 / r.d.df).toFixed(0) : '∞',
      r.m.tcdk, r.m.k.toFixed(2), r.m.cte, r.m.tg, `${r.m.cost.toFixed(1)}×`,
      `${(r.m.fMax / 1e9).toFixed(0)} GHz`]));
  [...t.querySelectorAll('tbody tr')].forEach((tr, i) => { if (rows[i].isCurrent) tr.classList.add('row-current'); });

  const c2 = card(root, 'Loss tangent against permittivity',
    'The two properties that decide whether a substrate can radiate. Down and to the left is efficient and physically large; up and to the right is compact and lossy.');
  // Label only the reference points a designer navigates by; everything else
  // is on hover. A label on all 24 points would be unreadable.
  const LANDMARKS = { air: 'air', rt5880: 'RT5880', ro3003: 'RO3003', ro4003c: 'RO4003C',
                      fr4: 'FR-4', ro6010: 'RT6010', alumina96: 'alumina', ltccDp951: 'LTCC' };
  scatterChart(chartBox(c2), {
    height: 340,
    points: rows.map((r) => ({
      x: r.d.er, y: r.d.df * 1000,
      label: r.isCurrent ? `${LANDMARKS[r.m.id] || r.m.name.split(' ')[0]} (in use)` : LANDMARKS[r.m.id],
      color: r.isCurrent ? 'var(--series-2)' : 'var(--series-1)',
      r: r.isCurrent ? 8 : 5,
      sub: `${r.m.name} — ${r.m.family} · cost ${r.m.cost}× · Tg ${r.m.tg} °C`,
    })),
    xLabel: 'relative permittivity εr', yLabel: 'loss tangent × 1000',
    yDomain: { min: 0, max: 22 },
    tipFmt: (p) => p.y.toFixed(2), table: false,
    note: 'The current substrate is the orange point. Only landmark materials are labelled — hover any point for its name, family, cost and Tg.',
  });

  const c3 = card(root, 'How to read this table');
  const ul = h('ul', { class: 'ref-list' }, c3);
  [
    'εr sets the size: linear dimensions scale as 1/√εeff, so εr = 10 makes a patch about 3× smaller in each direction than air.',
    'tanδ sets the ceiling on efficiency: Q_d = 1/tanδ can never be exceeded by the radiation Q, so a thin antenna on a high-Df laminate cannot be efficient at any thickness.',
    'TCDk sets how far the resonance walks over temperature: Δf/f ≈ −½·TCDk·ΔT. RO3003 at 13 ppm/°C holds a 77 GHz radar band that FR-4 at −200 ppm/°C would lose.',
    'Thermal conductivity matters only when the antenna shares a substrate with a power amplifier; alumina at 24 W/m·K is two orders above every laminate here.',
    'z-axis CTE is a plated-through-hole reliability number, not an RF one — but PTFE at 200+ ppm/°C is why those boards need special drilling and no thermal shock.',
    'Cost index is relative to standard FR-4 for the bare laminate; the finished-board ratio is usually smaller because processing dominates at low volume.',
  ].forEach((x) => h('li', { text: x }, ul));
}

function theoryConductors(root, D, state, k) {
  const { f, cu } = k;
  const c1 = card(root, 'Skin effect',
    'Above a few megahertz the current rides on the surface. Everything about conductor loss, plating choice and surface roughness follows from how thin that layer is.');
  const fs = [];
  for (let i = 0; i <= 200; i++) fs.push(Math.pow(10, -2 + (i / 200) * 4.5));   // 10 MHz - 300 GHz
  const metals = ['copper', 'silver', 'aluminium', 'brass', 'enig'];
  lineChart(chartBox(c1), {
    height: 340, xLog: true,
    series: metals.map((mid) => ({
      name: CONDUCTORS[mid].name,
      points: fs.map((g) => ({ x: g, y: skinDepth(g * 1e9, CONDUCTORS[mid].sigma) * 1e6 })),
    })),
    xLabel: 'frequency [GHz]', yLabel: 'skin depth [µm]',
    xFmt: (v) => (v >= 1 ? v.toFixed(0) : v.toFixed(2)),
    yFmt: (v) => v.toFixed(1),
    vlines: [{ x: f / 1e9, label: engFreq(f), kind: 'spec' }],
    hlines: [{ y: (D.spec.tCu ?? 35e-6) * 1e6, label: `copper thickness ${((D.spec.tCu ?? 35e-6) * 1e6).toFixed(0)} µm` }],
    tipFmt: (p) => `${p.y.toFixed(3)} µm`, table: false,
    note: 'Where the copper is thinner than about three skin depths the conductor is not fully used; where it is much thicker, adding more copper buys nothing electrically.',
  });

  const c2 = card(root, 'Conductor properties');
  dataTable(c2, ['Metal', 'σ [S/m]', `δ at ${engFreq(f)}`, 'Rs [mΩ/sq]', 'Relative Rs', 'k [W/m·K]', 'Temp. coeff.'], 
    Object.entries(CONDUCTORS).map(([, m]) => {
      const rs = surfaceResistance(f, m.sigma);
      return [m.name, m.sigma.toExponential(2), `${(skinDepth(f, m.sigma) * 1e6).toFixed(3)} µm`,
        (rs * 1e3).toFixed(2), `${(rs / surfaceResistance(f, CONDUCTORS.copper.sigma)).toFixed(2)}×`,
        m.k, `${(m.alphaR * 1e3).toFixed(2)} ×10⁻³/K`];
    }));
  h('p', { class: 'chart-note', text: 'ENIG puts 3–6 µm of nickel between the copper and the gold. Nickel is roughly four times more resistive than copper AND magnetic, so at microwave frequencies an ENIG finish over a radiating surface costs real efficiency. Use OSP or immersion silver on the antenna layer.' }, c2);

  const c3 = card(root, 'Surface roughness',
    'Rolled foil is smooth; the tooth that bonds cheap foil to laminate is not. Once the roughness approaches the skin depth the current has to follow a longer path.');
  const rq = [];
  for (let i = 0; i <= 150; i++) {
    const ratio = (i / 150) * 5;
    rq.push({ x: ratio, y: 1 + (2 / Math.PI) * Math.atan(1.4 * ratio * ratio) });
  }
  lineChart(chartBox(c3), {
    height: 300,
    series: [{ name: 'Hammerstad correction Kr', points: rq }],
    xLabel: 'RMS roughness / skin depth  (Rq/δ)', yLabel: 'conductor-loss multiplier',
    vlines: [{ x: (D.spec.roughnessRq ?? 1e-6) / skinDepth(f, cu.sigma),
      label: `this design: Rq ${((D.spec.roughnessRq ?? 1e-6) * 1e6).toFixed(1)} µm`, kind: 'spec' }],
    tipFmt: (p) => `${p.y.toFixed(3)}×`, directLabels: false, table: false,
    note: `Typical RMS roughness: standard foil 2 µm, VLP 1 µm, HVLP 0.5 µm, rolled annealed 0.3 µm. Skin depth here is ${(skinDepth(f, cu.sigma) * 1e6).toFixed(2)} µm.`,
  });
}

function theoryLines(root, D, state, k) {
  const { f, mat } = k;
  const c1 = card(root, '50 Ω microstrip width against substrate height',
    'The first number every layout needs. Computed with Hammerstad–Jensen at the current frequency for each candidate laminate.');
  const ids = ['fr4', 'ro4003c', 'rt5880', 'ro3003', 'ro6010'];
  const hs = [];
  for (let i = 1; i <= 120; i++) hs.push((i / 120) * 3.2e-3);
  lineChart(chartBox(c1), {
    height: 340,
    series: ids.map((id) => {
      const m = MATERIAL_BY_ID[id];
      const d = dispersiveEr(m, f);
      return { name: `${m.name} (εr ${d.er.toFixed(2)})`,
        points: hs.map((hh) => ({ x: hh * 1e3, y: synthesizeWidth(d.er, 50, hh) * 1e3 })) };
    }),
    xLabel: 'substrate height h [mm]', yLabel: '50 Ω trace width [mm]',
    vlines: [{ x: D.stack.h * 1e3, label: 'this stack', kind: 'spec' }],
    tipFmt: (p) => `${p.y.toFixed(3)} mm`, table: false,
    note: 'W/h is nearly constant for a given permittivity, so halving the substrate halves the trace width — which is what makes thin high-Dk mmWave boards hard to etch.',
  });

  const c2 = card(root, 'Line loss against frequency',
    'Conductor loss rises as √f, dielectric loss rises linearly with f. Where they cross tells you which one to attack.');
  const w50 = D.feed.feedLineWidth;
  const fsw = [];
  for (let i = 0; i <= 160; i++) fsw.push(Math.pow(10, -1 + (i / 160) * 2.5));
  lineChart(chartBox(c2), {
    height: 320, xLog: true,
    series: [
      { name: 'conductor', points: fsw.map((g) => ({ x: g, y: lineLossDbPerM({ er: mat.er, df: mat.df, w: w50, h: D.stack.h, f: g * 1e9, sigma: k.cu.sigma, rq: D.spec.roughnessRq ?? 1e-6 }).conductor / 100 })) },
      { name: 'dielectric', points: fsw.map((g) => ({ x: g, y: lineLossDbPerM({ er: mat.er, df: mat.df, w: w50, h: D.stack.h, f: g * 1e9, sigma: k.cu.sigma }).dielectric / 100 })), color: 'var(--series-2)' },
      { name: 'total', points: fsw.map((g) => ({ x: g, y: lineLossDbPerM({ er: mat.er, df: mat.df, w: w50, h: D.stack.h, f: g * 1e9, sigma: k.cu.sigma, rq: D.spec.roughnessRq ?? 1e-6 }).total / 100 })), color: 'var(--series-3)' },
    ],
    xLabel: 'frequency [GHz]', yLabel: 'loss [dB/cm]',
    xFmt: (v) => (v >= 1 ? v.toFixed(0) : v.toFixed(1)),
    vlines: [{ x: f / 1e9, label: engFreq(f), kind: 'spec' }],
    tipFmt: (p) => `${p.y.toFixed(4)} dB/cm`, table: false,
    note: `On ${mat.name} with a ${(w50 * 1e3).toFixed(2)} mm line, ${lineLossDbPerM({ er: mat.er, df: mat.df, w: w50, h: D.stack.h, f, sigma: k.cu.sigma }).dielectric > lineLossDbPerM({ er: mat.er, df: mat.df, w: w50, h: D.stack.h, f, sigma: k.cu.sigma, rq: D.spec.roughnessRq ?? 1e-6 }).conductor ? 'dielectric loss dominates — a better laminate helps, more copper does not' : 'conductor loss dominates — smoother foil and wider lines help'}.`,
  });

  const c3 = card(root, 'Line reference at this operating point');
  const zs = [25, 35.4, 50, 70.7, 100];
  dataTable(c3, ['Z₀ [Ω]', 'Width [mm]', 'W/h', 'εeff', 'λg [mm]', 'λg/4 [mm]', 'Loss [dB/cm]', 'Typical use'], 
    zs.map((z) => {
      const w = synthesizeWidth(mat.er, z, D.stack.h);
      const ee = epsEffStatic(mat.er, w, D.stack.h);
      const lg = C0 / (f * Math.sqrt(ee));
      const use = { 25: 'low-Z stubs, wide feeds', 35.4: 'λ/4 between 25 and 50 Ω', 50: 'standard reference',
                    70.7: 'λ/4 between 50 and 100 Ω', 100: 'array branch lines' }[z];
      return [z.toFixed(1), (w * 1e3).toFixed(3), (w / D.stack.h).toFixed(2), ee.toFixed(3),
        (lg * 1e3).toFixed(2), ((lg / 4) * 1e3).toFixed(3),
        (lineLossDbPerM({ er: mat.er, df: mat.df, w, h: D.stack.h, f, sigma: k.cu.sigma }).total / 100).toFixed(4), use];
    }));
  const lim = D.microstripLimits;
  h('p', { class: 'chart-note', text: `Mode limits on this stack: the first higher-order TM surface wave appears at ${(lim.fTM1 / 1e9).toFixed(1)} GHz and transverse resonance of the 50 Ω line at ${(lim.fTransverse / 1e9).toFixed(1)} GHz, so keep microstrip below about ${(lim.fMaxRecommended / 1e9).toFixed(1)} GHz here.` }, c3);
}

function theoryBands(root, D, state, k) {
  const { f } = k;
  const c1 = card(root, 'Service bands',
    'Wavelength, fractional bandwidth and the headline EIRP limit for each band. The fractional bandwidth column is what decides whether one resonant antenna can cover the whole allocation.');
  const cur = D.band;
  const t = dataTable(c1, ['Band', 'Range [GHz]', 'Centre', 'λ₀ [mm]', 'λ₀/2 [mm]', 'Fractional BW', 'EIRP limit', 'Region', 'Note'],
    BANDS.map((b) => {
      const fc = (b.lo + b.hi) / 2;
      return [b.name, `${(b.lo / 1e9).toFixed(3)} – ${(b.hi / 1e9).toFixed(3)}`, engFreq(fc),
        ((C0 / fc) * 1e3).toFixed(1), ((C0 / fc / 2) * 1e3).toFixed(1),
        `${(bandFractional(b) * 100).toFixed(2)} %`,
        b.eirpDbm === null ? '—' : `${b.eirpDbm} dBm`, b.region, b.note];
    }));
  [...t.querySelectorAll('tbody tr')].forEach((tr, i) => { if (cur && BANDS[i].id === cur.id) tr.classList.add('row-current'); });

  const c2 = card(root, 'Bandwidth demanded by each band, against what a patch can give',
    'The dashed line is the VSWR-2 bandwidth of the patch currently configured. Bands above it need a wideband topology — stacked, aperture-coupled, air-gapped, or a different antenna entirely.');
  barChart(chartBox(c2), {
    height: 340,
    items: BANDS.filter((b) => b.hi < 200e9).map((b) => ({
      label: b.name.replace(/ \(.*\)/, '').slice(0, 16),
      value: bandFractional(b) * 100,
      color: bandFractional(b) * 100 <= D.sol.fbw2 * 100 ? 'var(--series-3)' : 'var(--series-1)',
      highlight: cur && b.id === cur.id,
      sub: `${(b.lo / 1e9).toFixed(2)}–${(b.hi / 1e9).toFixed(2)} GHz`,
    })),
    yLabel: 'fractional bandwidth [%]',
    valueFmt: (v) => v.toFixed(1),
    hlines: [{ y: D.sol.fbw2 * 100, label: `this patch: ${(D.sol.fbw2 * 100).toFixed(2)} %` }],
    note: 'Green bands fit inside the current patch bandwidth; blue ones do not.',
  });
}

function theoryAtmosphere(root, D, state, k) {
  const { f } = k;
  const c1 = card(root, 'Atmospheric absorption',
    'Specific attenuation of dry air and water vapour at sea level, following ITU-R P.676. The resonances are not engineering choices — they decide which bands can carry a long link at all.');
  const fsG = [];
  for (let i = 0; i <= 300; i++) fsG.push(1 + i);
  lineChart(chartBox(c1), {
    height: 340,
    series: [
      { name: 'dry air (O₂)', points: fsG.map((g) => ({ x: g, y: gaseousAttenuation(g * 1e9, 15, 1013.25, 0.001).oxygen })) },
      { name: 'water vapour (7.5 g/m³)', points: fsG.map((g) => ({ x: g, y: gaseousAttenuation(g * 1e9, 15, 1013.25, 7.5).water })), color: 'var(--series-2)' },
    ],
    xLabel: 'frequency [GHz]', yLabel: 'specific attenuation [dB/km]',
    yDomain: { min: 0, max: 30 },
    vlines: [{ x: f / 1e9, label: engFreq(f), kind: 'spec' }],
    tipFmt: (p) => `${p.y.toFixed(3)} dB/km`, table: false,
  });

  const c2 = card(root, 'Reference values');
  const marks = [2.45, 5.8, 10, 24, 28, 39, 60, 77, 94, 122, 140, 183];
  dataTable(c2, ['f [GHz]', 'λ₀ [mm]', 'O₂ [dB/km]', 'H₂O [dB/km]', 'Total [dB/km]', 'Rain 25 mm/h [dB/km]', 'Character'],
    marks.map((g) => {
      const a = gaseousAttenuation(g * 1e9);
      const r = rainAttenuation(Math.min(g, 100) * 1e9, 25).gammaR;
      const ch = a.total > 5 ? 'absorption band — short range by physics'
        : a.total > 0.5 ? 'usable, plan the link budget for it'
        : 'atmospheric window';
      return [g.toFixed(0), ((C0 / (g * 1e9)) * 1e3).toFixed(2), a.oxygen.toFixed(3), a.water.toFixed(3),
        a.total.toFixed(3), r.toFixed(2), ch];
    }));

  const c3 = card(root, 'Rain attenuation coefficients (ITU-R P.838-3)',
    'γR = k·R^α with R in mm/h. Rain, not gas, is what closes a Ku- or Ka-band link budget.');
  dataTable(c3, ['f [GHz]', 'k (horizontal)', 'α (horizontal)', '5 mm/h', '25 mm/h', '50 mm/h', '100 mm/h'],
    [4, 10, 15, 20, 30, 40, 60, 80, 100].map((g) => {
      const r = rainAttenuation(g * 1e9, 25);
      return [g, r.k.toFixed(5), r.alpha.toFixed(3),
        ...[5, 25, 50, 100].map((rr) => `${(r.k * Math.pow(rr, r.alpha)).toFixed(2)} dB/km`)];
    }));
}

function theoryConversions(root, D, state, k) {
  const c1 = card(root, 'Match: VSWR, return loss and mismatch loss',
    'Three ways of stating the same reflection. Mismatch loss is the one that matters to a link budget — it is how much of the delivered power never enters the antenna.');
  const g = h('div', { class: 'grid2' }, c1);
  dataTable(h('div', {}, g), ['VSWR', '|Γ|', 'Return loss [dB]', 'Mismatch loss [dB]', 'Power reflected'],
    [1.0, 1.1, 1.2, 1.5, 1.92, 2.0, 2.5, 3.0, 4.0, 5.0, 10].map((v) => {
      const gm = (v - 1) / (v + 1);
      return [v.toFixed(2), gm.toFixed(4), v === 1 ? '∞' : (-20 * Math.log10(gm)).toFixed(2),
        (-10 * Math.log10(1 - gm * gm)).toFixed(3), `${(gm * gm * 100).toFixed(2)} %`];
    }));
  dataTable(h('div', {}, g), ['dB', 'Power ratio', 'Voltage ratio', 'Meaning'],
    [[-20, 'a hundredth'], [-10, 'a tenth'], [-6, 'a quarter'], [-3, 'half'], [-1, '79 %'],
     [0, 'unity'], [1, '1.26×'], [3, 'double'], [6, 'four times'], [10, 'ten times'], [20, 'a hundred times']]
      .map(([d, meaning]) => [d > 0 ? `+${d}` : `${d}`, fromDB(d).toFixed(d === 0 ? 0 : 4),
        Math.pow(10, d / 20).toFixed(4), meaning]));

  const c2 = card(root, 'Power');
  const g2 = h('div', { class: 'grid2' }, c2);
  dataTable(h('div', {}, g2), ['dBm', 'Watts', 'dBW', 'Typical source'],
    [[-100, 'thermal noise floor in 1 MHz + 14 dB NF'], [-80, 'weak received signal'], [-30, '1 µW'],
     [0, '1 mW — reference'], [10, '10 mW, BLE'], [14, '25 mW, EU SRD limit'], [20, '100 mW, Wi-Fi EIRP (EU)'],
     [30, '1 W'], [36, '4 W, US point-to-multipoint EIRP'], [43, '20 W'], [50, '100 W'], [60, '1 kW']]
      .map(([d, note]) => [d, fromDB(d - 30) >= 1 ? `${fromDB(d - 30).toFixed(fromDB(d - 30) >= 10 ? 0 : 2)} W` : `${(fromDB(d - 30) * 1e3).toFixed(3)} mW`,
        (d - 30).toFixed(0), note]));
  dataTable(h('div', {}, g2), ['Bandwidth', 'kTB at 290 K [dBm]', 'With 6 dB NF', 'Sensitivity at 10 dB SNR'],
    [1e3, 1e4, 1e5, 1e6, 1e7, 2e7, 1e8, 1e9].map((b) => [
      b >= 1e6 ? `${(b / 1e6).toFixed(0)} MHz` : `${(b / 1e3).toFixed(0)} kHz`,
      noiseFloorDbm(b).toFixed(2), (noiseFloorDbm(b) + 6).toFixed(2), (noiseFloorDbm(b) + 16).toFixed(2)]));

  const c3 = card(root, 'Field strength and power density',
    'For EMC work and exposure assessment, all referred to the EIRP of the current design.');
  const eirp = 20 + D.realizedGainDbi - 0.5;
  dataTable(c3, ['Distance', 'Power density [W/m²]', 'E field [V/m]', 'H field [A/m]', 'Against the 10 W/m² public limit'],
    [0.05, 0.1, 0.2, 0.5, 1, 3, 10].map((d) => {
      const pd = fromDB(eirp - 30) / (4 * Math.PI * d * d);
      const e = Math.sqrt(pd * 376.73);
      return [`${(d * 100).toFixed(0)} cm`, pd.toExponential(3), e.toFixed(2), (e / 376.73).toFixed(4),
        pd > 10 ? 'EXCEEDS' : `${(pd / 10 * 100).toFixed(2)} % of the limit`];
    }));
  h('p', { class: 'chart-note', text: `Assumes ${(20).toFixed(0)} dBm at the connector and the ${D.realizedGainDbi.toFixed(1)} dBi of this design (EIRP ${eirp.toFixed(1)} dBm), far-field formulas applied at all distances — inside the reactive near field (${(D.fieldRegions.reactiveNearField * 1e3).toFixed(0)} mm) they overestimate.` }, c3);
}

function theoryConstants(root, D, state, k) {
  const c1 = card(root, 'Physical constants', 'CODATA 2018 values, as used throughout the engine.');
  dataTable(c1, ['Constant', 'Symbol', 'Value', 'Unit'], [
    ['Speed of light in vacuum', 'c₀', '299 792 458', 'm/s'],
    ['Vacuum permeability', 'µ₀', '4π × 10⁻⁷ = 1.256 637 × 10⁻⁶', 'H/m'],
    ['Vacuum permittivity', 'ε₀', '8.854 188 × 10⁻¹²', 'F/m'],
    ['Free-space impedance', 'η₀ = µ₀c₀', '376.730 313', 'Ω'],
    ['Boltzmann constant', 'k_B', '1.380 649 × 10⁻²³', 'J/K'],
    ['Stefan–Boltzmann constant', 'σ_SB', '5.670 374 × 10⁻⁸', 'W/(m²·K⁴)'],
    ['Reference noise temperature', 'T₀', '290', 'K'],
    ['Standard atmosphere', 'p₀', '101 325', 'Pa'],
  ]);

  const c2 = card(root, 'Symbols used in this tool');
  dataTable(c2, ['Symbol', 'Quantity', 'Where it appears'], [
    ['λ₀, λg', 'free-space and guided wavelength', 'every dimension'],
    ['k₀', 'free-space wavenumber, 2π/λ₀', 'pattern integrals, Q'],
    ['εr, εeff', 'bulk and effective permittivity', 'substrate, microstrip'],
    ['tanδ, Df', 'loss tangent', 'dielectric loss, Q_d'],
    ['Q_rad, Q_d, Q_c, Q_sw, Q_t', 'radiation, dielectric, conductor, surface-wave and loaded quality factors', 'efficiency and bandwidth'],
    ['η', 'radiation efficiency', 'gain = directivity × efficiency'],
    ['D₀, G', 'directivity and gain', 'pattern and link budget'],
    ['ka', 'electrical size of the enclosing sphere', 'Chu and Harrington bounds'],
    ['Γ, VSWR', 'reflection coefficient and standing-wave ratio', 'match'],
    ['δ, Rs', 'skin depth and surface resistance', 'conductor loss'],
    ['σ', 'conductivity', 'conductor loss, Q_c'],
    ['Rθ', 'thermal resistance [K/W]', 'power handling'],
  ]);

  const c3 = card(root, 'Primary references',
    'Every model in this tool traces to one of these. Where a coefficient has been calibrated rather than derived, the source code says so at the point of use.');
  const ul = h('ul', { class: 'ref-list' }, c3);
  [
    'C. A. Balanis, Antenna Theory: Analysis and Design, 4th ed., Wiley 2016 — cavity and transmission-line patch models, ch. 14.',
    'E. O. Hammerstad and Ø. Jensen, "Accurate models for microstrip computer-aided design", IEEE MTT-S 1980.',
    'M. Kirschning and R. H. Jansen, "Accurate model for effective dielectric constant of microstrip with validity up to millimetre-wave frequencies", Electronics Letters 18(6), 1982.',
    'A. R. Djordjevic et al., "Wideband frequency-domain characterization of FR-4 and time-domain causality", IEEE T-EMC 43(4), 2001.',
    'D. R. Jackson and N. G. Alexopoulos, "Simple approximate formulas for input resistance, bandwidth and efficiency of a resonant rectangular patch", IEEE T-AP 39(3), 1991.',
    'D. M. Pozar, "Considerations for millimeter wave printed antennas", IEEE T-AP 31(5), 1983.',
    'J. Huang, "The finite ground plane effect on the microstrip antenna radiation patterns", IEEE T-AP 31(4), 1983.',
    'A. A. Kishk and L. Shafai, "The effect of various parameters of circular microstrip antennas on their radiation efficiency and the mode excitation", IEEE T-AP 34(8), 1986.',
    'L. J. Chu, "Physical limitations of omni-directional antennas", J. Appl. Phys. 19, 1948; J. S. McLean, IEEE T-AP 44(5), 1996.',
    'R. F. Harrington, "Effect of antenna size on gain, bandwidth and efficiency", J. Res. NBS 64D, 1960.',
    'P. Vainikainen et al., "Resonator-based analysis of the combination of mobile handset antenna and chassis", IEEE T-AP 50(10), 2002.',
    'J. D. Kraus, "The helical antenna", Proc. IRE 37, 1949 — axial-mode gain formula.',
    'H. W. Ehrenspeck and H. Poehler, "A new method for obtaining maximum gain from Yagi antennas", IRE T-AP 7, 1959.',
    'ITU-R P.525 (free space), P.676 (gaseous attenuation), P.838 (rain), P.2001 (wide-range terrestrial).',
    'IPC-2152 (current capacity), IPC-4101 (laminate specification).',
  ].forEach((r) => h('li', { text: r }, ul));
}

/* ================================================================ REPORT */

export function renderReport(root, D, state) {
  const c0 = card(root, 'Design report', 'Everything the engine computed, in one page. Print to PDF or copy the machine-readable payload for your own tooling.');
  const bar = h('div', { class: 'toolbar' }, c0);
  const bPrint = h('button', { class: 'primary', text: 'Print / save as PDF' }, bar);
  bPrint.addEventListener('click', () => window.print());
  const bJson = h('button', { text: 'Copy JSON' }, bar);
  const bCsv = h('button', { text: 'Copy CSV summary' }, bar);

  const payload = buildPayload(D);
  bJson.addEventListener('click', async () => {
    await copy(JSON.stringify(payload, null, 2));
    bJson.textContent = 'Copied';
    setTimeout(() => { bJson.textContent = 'Copy JSON'; }, 1400);
  });
  bCsv.addEventListener('click', async () => {
    const rows = flatten(payload).map(([k, v]) => `${k},${v}`).join('\n');
    await copy(`parameter,value\n${rows}`);
    bCsv.textContent = 'Copied';
    setTimeout(() => { bCsv.textContent = 'Copy CSV summary'; }, 1400);
  });

  const c1 = card(root, 'Specification');
  dataTable(c1, ['Item', 'Value'], [
    ['Frequency', engFreq(D.spec.f)],
    ['Band', D.band ? `${D.band.name} (${(D.band.lo / 1e9).toFixed(3)}–${(D.band.hi / 1e9).toFixed(3)} GHz)` : 'custom'],
    ['Required realized gain', `${D.spec.targetGainDbi.toFixed(1)} dBi`],
    ['Pattern', D.spec.pattern],
    ['Polarisation', D.spec.polarization],
    ['Required bandwidth', D.spec.bwPct ? `${D.spec.bwPct.toFixed(2)} %` : 'not specified'],
    ['Substrate', `${D.stack.material.name}, h = ${(D.stack.h * 1e3).toFixed(3)} mm`],
    ['Ground plane', `${(D.groundXM * 1e3).toFixed(1)} × ${(D.groundYM * 1e3).toFixed(1)} mm (X × Y)`],
    ['Envelope limit', D.spec.maxDimM ? `${(D.spec.maxDimM * 1e3).toFixed(0)} mm` : 'unconstrained'],
    ['Input power', `${(D.spec.powerW ?? 1).toFixed(2)} W`],
    ['Temperature range', `${D.spec.tMinC ?? -40} to ${D.spec.tMaxC ?? 85} °C`],
  ]);

  const c2 = card(root, 'Computed result');
  const best = D.recommendation.candidates[0];
  dataTable(c2, ['Quantity', 'Value', 'Verdict'], [
    ['Recommended type', best.arch.name, best.verdict],
    ['Realized gain (this patch design)', `${D.realizedGainDbi.toFixed(2)} dBi`,
      D.realizedGainDbi >= D.spec.targetGainDbi ? `meets spec (+${(D.realizedGainDbi - D.spec.targetGainDbi).toFixed(2)} dB)` : `${(D.spec.targetGainDbi - D.realizedGainDbi).toFixed(2)} dB short`],
    ['Directivity', `${D.sol.D0dBi.toFixed(2)} dBi`, ''],
    ['Radiation efficiency', `${(D.sol.etaSpace * 100).toFixed(1)} %`, D.sol.etaSpace > 0.8 ? 'good' : D.sol.etaSpace > 0.5 ? 'acceptable' : 'substrate-limited'],
    ['VSWR-2 bandwidth', `${(D.sol.fbw2 * 100).toFixed(2)} % (${(D.sol.bw2Hz / 1e6).toFixed(1)} MHz)`,
      D.spec.bwPct ? (D.sol.fbw2 * 100 >= D.spec.bwPct ? 'covers requirement' : 'insufficient') : ''],
    ['Patch dimensions', `${(D.sol.W * 1e3).toFixed(2)} × ${(D.sol.L * 1e3).toFixed(2)} mm`, ''],
    ['Loaded Q', D.sol.Qt.toFixed(1), ''],
    ['Front-to-back', `${D.gnd.frontToBackDb.toFixed(1)} dB`, `E-plane ${D.gnd.E.frontToBackDb.toFixed(1)} dB, H-plane ${D.gnd.H.frontToBackDb.toFixed(1)} dB`],
    ['Hot-spot temperature', `${D.thermal.tHotC.toFixed(1)} °C`, D.thermal.safe ? 'within laminate limit' : 'EXCEEDS limit'],
    ['Max continuous power', `${D.thermal.pMaxContinuousW.toFixed(2)} W`, ''],
    ['Drift over temperature', `${(D.drift.totalSpan * 100).toFixed(3)} %`, `${D.drift.bandwidthConsumedPct.toFixed(0)} % of bandwidth`],
    ['Harrington gain limit', `${D.limits.harringtonGainDbi.toFixed(1)} dBi`, D.limits.feasible ? 'spec is achievable' : 'SPEC EXCEEDS PHYSICS'],
    ['Chu bandwidth limit', `${(D.limits.chuBandwidth * 100).toFixed(1)} %`, ''],
  ]);

  const c3 = card(root, 'Machine-readable payload');
  const ta = h('textarea', { class: 'export', readonly: 'readonly' }, c3);
  ta.value = JSON.stringify(payload, null, 2);

  const c4 = card(root, 'Methods and references',
    'Every number on this page comes from a published model, not a lookup table. The models and their validity limits:');
  const ul = h('ul', { class: 'ref-list' }, c4);
  [
    'Cavity / transmission-line patch model — Balanis, Antenna Theory 4th ed. ch. 14. Valid for h ≲ 0.06 λ₀ and a single dominant TM₁₀ mode.',
    'Microstrip Z₀ and εeff — Hammerstad & Jensen (1980), ±0.2 % for 0.05 < W/h < 20. Dispersion after Kirschning & Jansen (1982).',
    'Wideband causal Dk/Df — Djordjevic, Biljic, Likar-Smiljanic & Sarkar, IEEE T-EMC 43(4), 2001.',
    'Surface-wave power — thin-substrate asymptotics after Jackson & Alexopoulos, IEEE T-AP 39(3), 1991; coefficient calibrated to published full-wave data.',
    'Finite ground plane — GTD/UTD edge-diffraction picture reduced to closed form, calibrated against Huang (1983) and Kishk & Shafai (1986). Engineering estimate, ±0.5 dB.',
    'Fundamental limits — Chu (1948), McLean (1996) for Q; Harrington (1960) for normal-gain directivity; Bode-Fano for the matching bound.',
    'Atmospheric absorption — line-shape model calibrated to the ITU-R P.676 sea-level reference curve. Rain — ITU-R P.838-3 k/α coefficients.',
    'Thermal — Churchill-Chu and McAdams convection correlations, grey-body radiation, lumped conduction network. Paschen breakdown with A = 15 cm⁻¹Torr⁻¹, B = 365 V·cm⁻¹Torr⁻¹ for air.',
    'Tolerance — Monte Carlo over Dk, thickness and etch at 3σ, propagated through the same resonance model.',
  ].forEach((t) => h('li', { text: t }, ul));
  h('p', { class: 'chart-note', text: 'Analytic models are for architecture decisions, sizing and trade studies. Validate the chosen candidate in a full-wave solver and on hardware before release — this tool tells you which design to build and simulate, not that it will pass qualification.' }, c4);
}

function buildPayload(D) {
  return {
    tool: 'RF Antenna Studio', generated: new Date().toISOString(),
    specification: {
      frequencyHz: D.spec.f, targetGainDbi: D.spec.targetGainDbi,
      pattern: D.spec.pattern, polarization: D.spec.polarization,
      requiredBandwidthPct: D.spec.bwPct, substrate: D.stack.material.name,
      epsilonR: D.stack.material.er, lossTangent: D.stack.material.df,
      substrateHeightM: D.stack.h, groundPlaneXM: D.groundXM, groundPlaneYM: D.groundYM,
      inputPowerW: D.spec.powerW, temperatureRangeC: [D.spec.tMinC, D.spec.tMaxC],
    },
    geometry: {
      patchWidthM: D.sol.W, patchLengthM: D.sol.L, effectiveLengthM: D.sol.Le,
      fringingExtensionM: D.sol.dL, epsilonEff: D.sol.epsEff,
      feed: { type: D.feed.type, lineWidthM: D.feed.feedLineWidth,
              insetDepthM: D.feed.insetDepth, probeOffsetM: D.feed.probeOffset },
    },
    performance: {
      directivityDbi: D.sol.D0dBi, radiationEfficiency: D.sol.etaSpace,
      realizedGainDbi: D.realizedGainDbi, bandwidthVswr2Pct: D.sol.fbw2 * 100,
      bandwidthHz: D.sol.bw2Hz, qTotal: D.sol.Qt, qRadiation: D.sol.Qrad,
      qDielectric: D.sol.Qd, qConductor: D.sol.Qc, qSurfaceWave: D.sol.Qsw,
      edgeResistanceOhm: D.sol.Rin, frontToBackDb: D.gnd.frontToBackDb,
      beamwidthEDeg: D.beamwidth.thetaE, beamwidthHDeg: D.beamwidth.thetaH,
      groundPenaltyDb: D.gnd.deltaGdB,
      groundPenaltyEPlaneDb: D.gnd.E.deltaGdB, groundPenaltyHPlaneDb: D.gnd.H.deltaGdB,
      frontToBackEPlaneDb: D.gnd.E.frontToBackDb, frontToBackHPlaneDb: D.gnd.H.frontToBackDb,
      groundMarginXLambda: D.gnd.marginXLambda, groundMarginYLambda: D.gnd.marginYLambda,
    },
    thermal: {
      dissipatedW: D.thermal.pDissipatedW, hotSpotC: D.thermal.tHotC,
      thermalResistanceKperW: D.thermal.rTotalKperW,
      maxContinuousW: D.thermal.pMaxContinuousW,
      driftPct: D.drift.totalSpan * 100, bandwidthConsumedPct: D.drift.bandwidthConsumedPct,
    },
    limits: {
      harringtonGainDbi: D.limits.harringtonGainDbi,
      chuBandwidthPct: D.limits.chuBandwidth * 100, ka: D.limits.ka,
      feasible: D.limits.feasible,
    },
    recommendations: D.recommendation.candidates.slice(0, 8).map((c) => ({
      type: c.arch.name, verdict: c.verdict, realizedGainDbi: c.realizedGainDbi,
      efficiency: c.efficiency, bandwidthPct: c.bwPct,
      sizeMm: c.size, score: c.score, blockers: c.blockers,
    })),
  };
}

function flatten(obj, prefix = '') {
  const out = [];
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object' && !Array.isArray(v)) out.push(...flatten(v, key));
    else out.push([key, Array.isArray(v) ? JSON.stringify(v).replace(/,/g, ';') : v]);
  }
  return out;
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); }
  catch { const t = document.createElement('textarea'); t.value = text; document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove(); }
}

export { buildPayload };
