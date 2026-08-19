/**
 * Rectangular microstrip patch antenna - cavity model with a numerically
 * integrated two-slot far field.
 *
 * Design equations : Balanis, "Antenna Theory", ch. 14 (transmission-line and
 *                    cavity models); Hammerstad for eps_eff.
 * Radiation Q      : derived from the physical two-slot aperture field, i.e.
 *                      Q_rad = 2*w*W_E / P_rad
 *                    which reduces to  Q_rad = 2*pi^2*eps_eff*Le / (k0*h*W*I)
 *                    with I the dimensionless pattern integral computed below.
 * Surface wave     : Jackson & Alexopoulos thin-substrate asymptotics.
 * Conductor Q      : Q_c = h*sqrt(pi*f*mu*sigma)
 * Dielectric Q     : Q_d = 1/tan(delta)
 */
import { C0, EPS0, MU0, ETA0, sinc, toDB, clamp } from './constants.js';
import { epsEffStatic } from './microstrip.js';

/**
 * Patch width for maximum radiation efficiency (Balanis 14-6).
 * Wider patches radiate better but risk exciting the TM02/odd modes.
 */
export function patchWidth(f, er) {
  return (C0 / (2 * f)) * Math.sqrt(2 / (er + 1));
}

/** Fringing-field line extension dL (Hammerstad). */
export function fringeExtension(epsEff, w, h) {
  return 0.412 * h *
    ((epsEff + 0.3) * (w / h + 0.264)) /
    ((epsEff - 0.258) * (w / h + 0.8));
}

/**
 * Resonant physical length for a target frequency, solved self-consistently
 * (eps_eff depends on W, dL depends on eps_eff).
 */
export function patchLength(f, er, h, w) {
  const epsEff = epsEffStatic(er, w, h);
  const dL = fringeExtension(epsEff, w, h);
  const L = C0 / (2 * f * Math.sqrt(epsEff)) - 2 * dL;
  return { L, Le: L + 2 * dL, epsEff, dL };
}

/** Inverse: resonant frequency of a given patch. */
export function resonantFrequency(L, er, h, w) {
  const epsEff = epsEffStatic(er, w, h);
  const dL = fringeExtension(epsEff, w, h);
  return C0 / (2 * (L + 2 * dL) * Math.sqrt(epsEff));
}

/**
 * Normalised far-field pattern of the two-slot cavity model.
 * Geometry: patch in the xy-plane over an (infinite) ground at z = 0,
 * resonant length Le along x, width W along y.
 *
 * A y-directed equivalent magnetic current over a ground plane gives
 *   E_theta ~  F * cos(phi)
 *   E_phi   ~ -F * cos(theta) * sin(phi)
 * with F = sinc(k0*h/2*sin(th)cos(ph)) * sinc(k0*W/2*sin(th)sin(ph))
 *          * 2*cos(k0*Le/2*sin(th)cos(ph))
 * Returns squared magnitude (proportional to radiation intensity U).
 */
export function patchFieldSq(theta, phi, k0v, Le, W, h) {
  const st = Math.sin(theta), ct = Math.cos(theta);
  const cp = Math.cos(phi), sp = Math.sin(phi);
  const X = (k0v * h / 2) * st * cp;
  const Y = (k0v * W / 2) * st * sp;
  const Psi = (k0v * Le / 2) * st * cp;
  const F = sinc(X) * sinc(Y) * 2 * Math.cos(Psi);
  const eTheta = F * cp;
  const ePhi = -F * ct * sp;
  return { u: eTheta * eTheta + ePhi * ePhi, eTheta, ePhi };
}

/**
 * Integrate the pattern over the upper hemisphere.
 * Returns { I, D0, U0 } where I = integral of |F|^2 dOmega (dimensionless),
 * D0 = 4*pi*Umax/Prad and Umax is evaluated at broadside.
 */
export function patternIntegral(f, Le, W, h, nTheta = 180, nPhi = 180) {
  const k0v = (2 * Math.PI * f) / C0;
  let I = 0;
  const dth = (Math.PI / 2) / nTheta;
  const dph = (2 * Math.PI) / nPhi;
  let uMax = 0;
  for (let i = 0; i < nTheta; i++) {
    const th = (i + 0.5) * dth;
    const st = Math.sin(th);
    for (let j = 0; j < nPhi; j++) {
      const ph = (j + 0.5) * dph;
      const { u } = patchFieldSq(th, ph, k0v, Le, W, h);
      I += u * st * dth * dph;
      if (u > uMax) uMax = u;
    }
  }
  const uBroadside = patchFieldSq(1e-6, 0, k0v, Le, W, h).u;
  return { I, D0: (4 * Math.PI * uBroadside) / I, D0max: (4 * Math.PI * uMax) / I, uBroadside };
}

/**
 * TM0 surface-wave power ratio for a grounded slab, thin-substrate asymptotics.
 * P_sw/P_sp grows as (k0*h)*(er-1)^3, i.e. thick + high-Dk substrates dump an
 * increasing share of the power into a wave that never leaves the board (it
 * diffracts off the ground-plane edges as back radiation instead).
 *
 * Coefficient calibrated against published full-wave results
 *   er = 2.20, k0h = 0.126 -> ~3.6 %      er = 10.2, k0h = 0.126 -> ~26 %
 * Scaling after Jackson & Alexopoulos, IEEE T-AP 39(3), 1991.
 */
export function surfaceWaveRatio(er, h, f) {
  if (er <= 1.0005) return 0;
  const k0h = ((2 * Math.PI * f) / C0) * h;
  const r = (3 * Math.PI / 8) * k0h * Math.pow(er - 1, 3) / Math.pow(er, 2.5);
  return clamp(r, 0, 20);
}

/**
 * Full electrical solution of a rectangular patch.
 *
 * @param {object} p
 *   f        design frequency [Hz]
 *   er       substrate relative permittivity (effective, incl. air gaps)
 *   df       loss tangent
 *   h        substrate height [m]
 *   sigma    conductor conductivity [S/m]
 *   W, L     optional explicit dimensions [m] (otherwise synthesised)
 *   tCu      conductor thickness [m]
 */
// The pattern integral is 180x180 samples, so a full solve is not free. The
// same stack-up gets solved repeatedly while sweeping something else (board
// size, target gain), and the answer only depends on these six numbers.
const SOLVE_CACHE = new Map();
const CACHE_LIMIT = 400;

export function solvePatch(p) {
  const { f, er, df, h, sigma = 5.8e7, tCu = 35e-6 } = p;
  const key = `${f}|${er}|${df}|${h}|${sigma}|${tCu}|${p.W || 0}|${p.L || 0}`;
  const hit = SOLVE_CACHE.get(key);
  if (hit) return hit;
  const out = solvePatchUncached(p);
  if (SOLVE_CACHE.size >= CACHE_LIMIT) SOLVE_CACHE.clear();
  SOLVE_CACHE.set(key, out);
  return out;
}

function solvePatchUncached(p) {
  const { f, er, df, h, sigma = 5.8e7, tCu = 35e-6 } = p;
  const W = p.W || patchWidth(f, er);
  const geo = p.L ? { L: p.L, epsEff: epsEffStatic(er, W, h), dL: 0 } : patchLength(f, er, h, W);
  if (p.L) {
    geo.dL = fringeExtension(geo.epsEff, W, h);
    geo.Le = p.L + 2 * geo.dL;
  }
  const { L, Le, epsEff, dL } = geo;
  const k0v = (2 * Math.PI * f) / C0;
  const lam0 = C0 / f;

  const pat = patternIntegral(f, Le, W, h);
  const I = pat.I;
  const D0 = pat.D0;

  // --- Quality factors -----------------------------------------------------
  const Qrad = (2 * Math.PI * Math.PI * epsEff * Le) / (k0v * h * W * I);
  const Qd = df > 1e-9 ? 1 / df : 1e9;
  const Qc = h * Math.sqrt(Math.PI * f * MU0 * sigma);
  const swr = surfaceWaveRatio(er, h, f);
  const Qsw = swr > 1e-9 ? Qrad / swr : 1e9;

  const invQt = 1 / Qrad + 1 / Qd + 1 / Qc + 1 / Qsw;
  const Qt = 1 / invQt;

  // Radiation efficiency into the space wave
  const etaSpace = Qt / Qrad;
  const etaDielectric = Qt / Qd;   // fraction lost in the dielectric
  const etaConductor = Qt / Qc;
  const etaSurface = Qt / Qsw;

  // --- Bandwidth -----------------------------------------------------------
  const bwVswr = (s) => ((s - 1) / (Qt * Math.sqrt(s)));
  const fbw2 = bwVswr(2);          // fractional BW at VSWR 2:1
  const fbw15 = bwVswr(1.5);

  // --- Impedance -----------------------------------------------------------
  // Slot conductance (Balanis 14-12) and mutual conductance between the slots
  const G1 = slotConductance(W, lam0, k0v);
  const G12 = mutualConductance(W, L, lam0, k0v);
  const Rin = 1 / (2 * (G1 + G12));   // edge resistance, odd (antiphase) mode

  // --- Gain ----------------------------------------------------------------
  const gainDbi = toDB(D0 * etaSpace);

  return {
    W, L, Le, dL, epsEff, lambda0: lam0, k0: k0v,
    hOverLambda: h / lam0, WOverLambda: W / lam0, LeOverLambda: Le / lam0,
    D0, D0dBi: toDB(D0), patternIntegral: I,
    Qrad, Qd, Qc, Qsw, Qt,
    etaSpace, etaDielectric, etaConductor, etaSurface,
    surfaceWaveRatio: swr,
    fbw2, fbw15, bw2Hz: fbw2 * f, bw15Hz: fbw15 * f,
    G1, G12, Rin, gainDbi,
    lossBudgetDb: {
      dielectric: -toDB(1 - etaDielectric),
      conductor: -toDB(1 - etaConductor),
      surfaceWave: -toDB(1 - etaSurface),
      total: -toDB(etaSpace),
    },
  };
}

/**
 * Slot self-conductance (Balanis 14-12), integrated numerically:
 *
 *   G1 = I1 / (120*pi^2),
 *   I1 = integral_0^pi [ sin(k0*W/2 * cos(th)) / cos(th) ]^2 * sin^3(th) dth
 *
 * Writing sin(u)/cos(th) = (k0*W/2) * sinc(u) pulls the (k0*W/2)^2 out front,
 * which is the form used here.
 *
 * Verified against Balanis Example 14.1 (f = 10 GHz, er = 2.2, h = 1.588 mm,
 * W = 11.86 mm): G1 = 1.5728e-3 S against the published 1.57e-3 S.
 */
export function slotConductance(W, lam0, k0v) {
  const n = 800;
  let s = 0;
  for (let i = 1; i < n; i++) {
    const th = (i * Math.PI) / n;
    const st = Math.sin(th);
    const arg = (k0v * W / 2) * Math.cos(th);
    s += Math.pow(sinc(arg) * st, 2) * st * (Math.PI / n);
  }
  return (Math.pow((k0v * W) / 2, 2) / (120 * Math.PI * Math.PI)) * s;
}

/**
 * Mutual conductance between the two radiating slots (Balanis 14-18a).
 * The Bessel argument uses the PHYSICAL separation L (the slot spacing), not
 * the fringing-extended electrical length.
 *
 * Verified against Balanis Example 14.1: G12 = 6.1683e-4 S, matching the
 * published value to five significant figures.
 */
export function mutualConductance(W, L, lam0, k0v) {
  const n = 800;
  let s = 0;
  for (let i = 1; i < n; i++) {
    const th = (i * Math.PI) / n;
    const st = Math.sin(th);
    const arg = (k0v * W / 2) * Math.cos(th);
    s += Math.pow(sinc(arg) * st, 2) * besselJ0(k0v * L * st) * st * (Math.PI / n);
  }
  return (Math.pow((k0v * W) / 2, 2) / (120 * Math.PI * Math.PI)) * s;
}

/**
 * Bessel function of the first kind, order 0.
 * Rational approximation from Abramowitz & Stegun 9.4.1 / 9.4.3
 * (as tabulated in Numerical Recipes), |error| < 1e-8.
 */
export function besselJ0(x) {
  const ax = Math.abs(x);
  if (ax < 8) {
    const y = x * x;
    const a1 = 57568490574.0 + y * (-13362590354.0 + y * (651619640.7 +
               y * (-11214424.18 + y * (77392.33017 + y * -184.9052456))));
    const a2 = 57568490411.0 + y * (1029532985.0 + y * (9494680.718 +
               y * (59272.64853 + y * (267.8532712 + y * 1.0))));
    return a1 / a2;
  }
  const z = 8 / ax, y = z * z, xx = ax - 0.785398164;
  const p1 = 1 + y * (-0.1098628627e-2 + y * (0.2734510407e-4 + y * (-0.2073370639e-5 + y * 0.2093887211e-6)));
  const p2 = -0.1562499995e-1 + y * (0.1430488765e-3 + y * (-0.6911147651e-5 + y * (0.7621095161e-6 + y * -0.934935152e-7)));
  return Math.sqrt(0.636619772 / ax) * (Math.cos(xx) * p1 - z * Math.sin(xx) * p2);
}

/**
 * Inset-feed depth for a target input impedance.
 * Rin(y0) = Rin(0) * cos^2(pi*y0/L)   [Balanis 14-20a]
 */
export function insetDepth(Redge, Ztarget, L) {
  const ratio = clamp(Ztarget / Redge, 0, 1);
  return (L / Math.PI) * Math.acos(Math.sqrt(ratio));
}

/** Probe-feed offset from the patch centre for a target impedance. */
export function probeOffset(Redge, Ztarget, L) {
  // Same cos^2 law measured from the radiating edge -> distance from centre
  const y0 = insetDepth(Redge, Ztarget, L);
  return Math.max(0, L / 2 - y0);
}

/**
 * Complex input impedance vs frequency using the parallel-RLC resonator
 * equivalent of the dominant TM10 mode, plus the probe series inductance.
 */
export function inputImpedance(f, f0, R0, Qt, Lprobe = 0) {
  const x = (f / f0) - (f0 / f);
  const denom = 1 + Math.pow(Qt * x, 2);
  const R = R0 / denom;
  const X = (-R0 * Qt * x) / denom + 2 * Math.PI * f * Lprobe;
  return { R, X };
}

/** Reflection coefficient magnitude in dB against a reference impedance. */
export function s11Db(R, X, z0 = 50) {
  const num = Math.pow(R - z0, 2) + X * X;
  const den = Math.pow(R + z0, 2) + X * X;
  const g2 = num / den;
  return { gamma: Math.sqrt(g2), s11: 10 * Math.log10(Math.max(g2, 1e-12)),
           vswr: (1 + Math.sqrt(g2)) / Math.max(1 - Math.sqrt(g2), 1e-9) };
}

/**
 * Effective permittivity of a composite stack (e.g. thin PCB carrier over an
 * air gap). Series capacitance per unit area -> eps_eff = h_tot / sum(h_i/e_i).
 */
export function compositeEr(layers) {
  const hTot = layers.reduce((a, l) => a + l.h, 0);
  const invSum = layers.reduce((a, l) => a + l.h / l.er, 0);
  const erEq = hTot / invSum;
  // Loss tangent weighted by the electric energy stored in each layer
  const num = layers.reduce((a, l) => a + (l.h / l.er) * (l.df || 0), 0);
  const dfEq = num / invSum;
  return { h: hTot, er: erEq, df: dfEq };
}

/** Aperture (stacked / suspended) bandwidth enhancement factor. */
export function stackedBandwidthFactor(hRatio = 1) {
  // Two coupled resonators roughly triple the VSWR-2 bandwidth of a single one
  return 2.6 + 0.4 * clamp(hRatio, 0, 2);
}

export { EPS0, ETA0 };
