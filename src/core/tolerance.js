/**
 * Manufacturing-tolerance Monte Carlo.
 *
 * A patch that is perfect in the simulator can still ship at 60 % yield. The
 * dominant contributors are, in order:
 *   1. Dk tolerance of the laminate      (FR-4 +/-0.20, RO4003C +/-0.05)
 *   2. core thickness tolerance          (typically +/-10 % on FR-4)
 *   3. etch / registration error         (+/-25 um on a standard process)
 *   4. copper thickness and plating
 * This module propagates them through the real resonance model and reports the
 * frequency distribution, the in-band VSWR and the resulting yield.
 */
import { solvePatch, resonantFrequency, inputImpedance, s11Db } from './patch.js';
import { clamp } from './constants.js';

/** Box-Muller normal deviate. */
function gauss(rng) {
  let u = 0, v = 0;
  while (u === 0) u = rng();
  while (v === 0) v = rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/** Deterministic PRNG so a report is reproducible. */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const PROCESS_CLASSES = {
  standard: { name: 'Standard PCB (IPC class 2)', etchUm: 25, hPct: 10, dkAbs: null, cuUm: 5, regUm: 75 },
  precision: { name: 'Precision RF (IPC class 3)', etchUm: 12, hPct: 5, dkAbs: null, cuUm: 3, regUm: 40 },
  mmwave: { name: 'mmWave / thin-film', etchUm: 5, hPct: 3, dkAbs: null, cuUm: 1.5, regUm: 15 },
};

/** Dk tolerance defaults per material family when the datasheet value is unknown. */
export function defaultDkTolerance(material) {
  if (material.family === 'FR-4 / glass-epoxy') return 0.20;
  if (material.family === 'Low-loss digital') return 0.10;
  if (material.family === 'Hydrocarbon-ceramic') return 0.05;
  if (material.family === 'PTFE / glass' || material.family === 'PTFE / ceramic') return 0.02;
  if (material.family === 'High-Dk ceramic') return 0.25;
  if (material.family === 'Air & foam') return 0.005;
  return 0.08;
}

/**
 * Run the Monte Carlo.
 * @param p
 *   f0        target frequency [Hz]
 *   material  substrate record
 *   h         nominal thickness [m]
 *   W, L      nominal patch dimensions [m]
 *   process   key into PROCESS_CLASSES or a custom object
 *   dkTol     +/- absolute Dk tolerance (3 sigma)
 *   gapTolUm  extra tolerance on an air gap (spacer stack-up), if any
 *   n         number of samples
 *   vswrLimit acceptance threshold
 *   bandHz    required band [f_lo, f_hi] to stay inside vswrLimit
 */
export function monteCarlo(p) {
  const {
    f0, material, h, W, L, sigma = 5.8e7,
    process = 'standard', dkTol = null, gapTolUm = 0,
    n = 4000, vswrLimit = 2.0, bandHz = null, seed = 12345,
  } = p;
  const proc = typeof process === 'string' ? PROCESS_CLASSES[process] : process;
  const dTol = dkTol ?? defaultDkTolerance(material);
  const rng = mulberry32(seed);

  const band = bandHz || [f0 * 0.99, f0 * 1.01];
  const samples = [];
  let pass = 0;
  const nominal = solvePatch({ f: f0, er: material.er, df: material.df, h, W, L, sigma });

  for (let i = 0; i < n; i++) {
    const er = material.er + (dTol / 3) * gauss(rng);
    const hh = Math.max(h * (1 + (proc.hPct / 100 / 3) * gauss(rng)) + (gapTolUm * 1e-6 / 3) * gauss(rng), 1e-5);
    const dW = (proc.etchUm * 1e-6 / 3) * gauss(rng);
    const dL = (proc.etchUm * 1e-6 / 3) * gauss(rng);
    const w = W + dW, l = L + dL;
    const fr = resonantFrequency(l, er, hh, w);
    const sol = solvePatch({ f: fr, er, df: material.df, h: hh, W: w, L: l, sigma });
    // worst VSWR across the required band
    let worst = 1;
    const steps = 9;
    for (let k = 0; k <= steps; k++) {
      const f = band[0] + ((band[1] - band[0]) * k) / steps;
      const z = inputImpedance(f, fr, 50, sol.Qt);
      const s = s11Db(z.R, z.X, 50);
      if (s.vswr > worst) worst = s.vswr;
    }
    const ok = worst <= vswrLimit;
    if (ok) pass++;
    samples.push({ fr, er, h: hh, W: w, L: l, worstVswr: worst, gain: sol.gainDbi, eff: sol.etaSpace, ok });
  }

  const frs = samples.map((s) => s.fr).sort((a, b) => a - b);
  const gains = samples.map((s) => s.gain).sort((a, b) => a - b);
  const q = (arr, x) => arr[clamp(Math.round(x * (arr.length - 1)), 0, arr.length - 1)];
  const mean = frs.reduce((a, b) => a + b, 0) / frs.length;
  const sd = Math.sqrt(frs.reduce((a, b) => a + (b - mean) ** 2, 0) / frs.length);

  // sensitivity: partial derivative of f0 to each parameter (finite difference)
  const base = resonantFrequency(L, material.er, h, W);
  const sens = {
    dk: (resonantFrequency(L, material.er + 0.1, h, W) - base) / base / 0.1,
    thickness: (resonantFrequency(L, material.er, h * 1.1, W) - base) / base / 0.1,
    length: (resonantFrequency(L * 1.01, material.er, h, W) - base) / base / 0.01,
    width: (resonantFrequency(L, material.er, h, W * 1.01) - base) / base / 0.01,
  };

  return {
    n, yieldPct: (pass / n) * 100, nominal,
    process: proc, dkTolerance: dTol,
    f: { mean, sd, sdPpm: (sd / mean) * 1e6, p5: q(frs, 0.05), p50: q(frs, 0.5), p95: q(frs, 0.95),
         min: frs[0], max: frs[frs.length - 1] },
    gain: { p5: q(gains, 0.05), p50: q(gains, 0.5), p95: q(gains, 0.95) },
    sensitivity: sens,
    samples,
    histogram: histogram(frs, 40),
    band,
  };
}

export function histogram(values, bins = 40) {
  const lo = values[0], hi = values[values.length - 1];
  const span = hi - lo || 1;
  const out = Array.from({ length: bins }, (_, i) => ({ x0: lo + (span * i) / bins, x1: lo + (span * (i + 1)) / bins, n: 0 }));
  for (const v of values) {
    const i = clamp(Math.floor(((v - lo) / span) * bins), 0, bins - 1);
    out[i].n++;
  }
  return out;
}

/**
 * How much design margin (frequency offset) recovers a target yield.
 * Returns the recommended nominal-frequency pre-bias.
 */
export function recommendPreBias(mc, targetF0) {
  const shift = targetF0 - mc.f.p50;
  return { shiftHz: shift, shiftPct: (shift / targetF0) * 100 };
}
