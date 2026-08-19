/**
 * Tab panel renderers. Each takes the container and the current design result.
 */
import { h, el, lineChart, barChart, hBarChart, stackedBar, histogramChart, polarChart, smithChart, scatterChart, fmt, engFreq, SERIES_VARS } from './charts.js';
import { stackupDiagram, planView, arrayLayout } from './diagrams.js';
import { antennaDrawing } from './antennaArt.js';
import { patternFor, responseVsFrequency } from '../core/patterns.js';
import {
  thicknessSweep, permittivitySweep, substrateTrade, groundSweep, recommendGroundSize,
  monteCarlo, MATERIALS, MATERIAL_BY_ID, solvePatch, toDB, fromDB, C0,
} from '../core/design.js';
import { linkBudget, maxRange, gaseousAttenuation, rainAttenuation, fspl, fresnelRadius, mpeDistance } from '../core/propagation.js';
import { solveThermal, frequencyDrift, paschenVoltage, pulsedRise, traceCurrentLimit, feedCurrent } from '../core/thermal.js';
import { BANDS } from '../core/bands.js';
import { PROCESS_CLASSES, defaultDkTolerance } from '../core/tolerance.js';

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
      `A ${(D.spec.maxDimM ? D.spec.maxDimM * 1e3 : D.groundM * 1e3).toFixed(0)} mm envelope supports up to ${lim.harringtonGainDbi.toFixed(1)} dBi (Harrington normal-gain limit) and ${(lim.chuBandwidth * 100).toFixed(0)} % bandwidth at ${engFreq(D.spec.f)}.`);
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
  const sel = h('select', { style: 'width:auto;min-width:250px' }, pick);
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
  tile(tl, 'Beamwidth E/H', `${D.beamwidth.thetaE.toFixed(0)}° / ${D.beamwidth.thetaH.toFixed(0)}°`, '', `F/B ${D.gnd.frontToBackDb.toFixed(1)} dB`);

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
    ['Ground plane', `${(D.groundM * 1e3).toFixed(1)} mm`, `${(D.groundM / D.lambda0).toFixed(2)} λ₀ square`],
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

/* ========================================================== GROUND PLANE */

export function renderGround(root, D) {
  const patchDim = Math.max(D.sol.W, D.sol.L);
  const sweep = groundSweep({ patchDim, lambda0: D.lambda0, swr: D.sol.surfaceWaveRatio, from: 0.3, to: 4 });
  const rec = recommendGroundSize({ patchDim, lambda0: D.lambda0, swr: D.sol.surfaceWaveRatio });

  const tl = h('div', { class: 'tiles' }, root);
  tile(tl, 'Ground in use', (D.groundM * 1e3).toFixed(0), 'mm', `${D.gnd.lgLambda.toFixed(2)} λ₀ square`);
  tile(tl, 'Gain penalty', D.gnd.deltaGdB.toFixed(2), 'dB', `truncation ${D.gnd.truncationDb.toFixed(2)}, ripple ${D.gnd.rippleDb.toFixed(2)}`,
    D.gnd.deltaGdB > -0.5 ? 'good' : D.gnd.deltaGdB > -1.5 ? 'warn' : 'bad');
  tile(tl, 'Front-to-back', D.gnd.frontToBackDb.toFixed(1), 'dB', 'includes surface-wave spill-over');
  tile(tl, 'Recommended ground', (rec.lg * 1e3).toFixed(0), 'mm', `${rec.lgLambda.toFixed(2)} λ₀ — within 0.5 dB of asymptotic`);
  tile(tl, 'Edge margin', (D.gnd.marginLambda).toFixed(3), 'λ₀', `${((D.groundM - patchDim) / 2 * 1e3).toFixed(1)} mm per side`,
    D.gnd.marginLambda > 0.15 ? 'good' : 'warn');

  const c1 = card(root, 'Gain against ground-plane size',
    'Three effects superimposed: aperture truncation when the fringing fields run out of ground, a λ/2-periodic ripple from the two diffracting edges, and surface-wave power spilling over the rim. The ripple is real — it is why measured gain wobbles as you trim a ground plane.');
  lineChart(chartBox(c1), {
    height: 340,
    series: [{ name: 'Δ gain vs infinite ground', points: sweep.filter((p) => Number.isFinite(p.deltaGdB)).map((p) => ({ x: p.lgLambda, y: p.deltaGdB })) }],
    xLabel: 'ground plane edge length [λ₀]', yLabel: 'gain change [dB]',
    vlines: [{ x: D.gnd.lgLambda, label: 'this design', kind: 'spec' },
             { x: rec.lgLambda, label: 'recommended', kind: 'good' }],
    hlines: [{ y: 0, label: 'infinite ground' }],
    tipFmt: (p) => `${p.y.toFixed(2)} dB`,
    note: `Physical scale: 1 λ₀ = ${(D.lambda0 * 1e3).toFixed(1)} mm at ${engFreq(D.spec.f)}.`,
  });

  const c2 = card(root, 'Front-to-back ratio',
    'Back radiation comes from edge diffraction of both the space wave and the surface wave. Doubling the ground buys roughly 4.5 dB until the surface-wave term saturates it.');
  lineChart(chartBox(c2), {
    height: 300,
    series: [{ name: 'F/B', points: sweep.filter((p) => Number.isFinite(p.fb)).map((p) => ({ x: p.lgLambda, y: p.fb })), color: 'var(--series-2)' }],
    xLabel: 'ground plane edge length [λ₀]', yLabel: 'front-to-back ratio [dB]',
    vlines: [{ x: D.gnd.lgLambda, label: 'this design', kind: 'spec' }],
    tipFmt: (p) => `${p.y.toFixed(1)} dB`,
  });

  const c3 = card(root, 'Ground-plane sizing guidance');
  dataTable(c3, ['Ground size', 'Δ gain', 'F/B', 'Verdict'],
    [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0].map((x) => {
      const p = sweep.reduce((a, b) => (Math.abs(b.lgLambda - x) < Math.abs(a.lgLambda - x) ? b : a));
      const v = p.deltaGdB > -0.3 ? 'Fully developed' : p.deltaGdB > -1.0 ? 'Acceptable' : 'Truncated — gain and pattern degraded';
      return [`${x.toFixed(2)} λ₀ = ${(x * D.lambda0 * 1e3).toFixed(0)} mm`, `${p.deltaGdB.toFixed(2)} dB`, `${p.fb.toFixed(1)} dB`, v];
    }));
  h('p', { class: 'chart-note', text: 'Rule of thumb this model reproduces: allow at least a quarter-wavelength of ground beyond every patch edge, and expect the last 0.5 dB to arrive only past one wavelength square.' }, c3);
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
          areaM2: D.groundM ** 2, perimeterM: 4 * D.groundM, material: D.stack.material,
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
    ['Radiating/convecting area', `${(D.groundM ** 2 * 2 * 1e4).toFixed(1)} cm² (both faces)`],
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
    ['Ground plane', `${(D.groundM * 1e3).toFixed(1)} mm square`, 'unbroken copper, no splits under the patch'],
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
    `Keep the ground plane continuous for at least ${((D.groundM - Math.max(D.sol.W, D.sol.L)) / 2 * 1e3).toFixed(1)} mm beyond every patch edge; splits, stitching gaps and component keep-outs under the patch all show up as pattern distortion.`,
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
    ['Ground plane', `${(D.groundM * 1e3).toFixed(1)} mm square`],
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
    ['Front-to-back', `${D.gnd.frontToBackDb.toFixed(1)} dB`, ''],
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
      substrateHeightM: D.stack.h, groundPlaneM: D.groundM,
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
