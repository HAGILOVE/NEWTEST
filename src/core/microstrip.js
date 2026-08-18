/**
 * Quasi-static and dispersive microstrip models.
 *
 *  - Hammerstad & Jensen (1980) closed-form Z0 / eps_eff, accurate to ~0.2 %
 *  - Wheeler synthesis for W given a target Z0
 *  - Kirschning & Jansen (1982) frequency dispersion of eps_eff and Z0
 *  - Conductor loss with the Hammerstad-Jensen roughness correction and the
 *    Huray "cannonball-stack" model for rough foils
 *  - Dielectric loss from the filling factor
 */
import { C0, ETA0, surfaceResistance, sinc } from './constants.js';

/** Hammerstad-Jensen static effective permittivity. */
export function epsEffStatic(er, w, h, t = 0) {
  let W = w;
  if (t > 0) {
    // Strip-thickness correction (Bahl & Garg)
    const dW = W / h >= 1 / (2 * Math.PI)
      ? (t / Math.PI) * (1 + Math.log((2 * h) / t))
      : (t / Math.PI) * (1 + Math.log((4 * Math.PI * W) / t));
    W = W + dW;
  }
  const u = W / h;
  const a = 1 + (1 / 49) * Math.log((Math.pow(u, 4) + Math.pow(u / 52, 2)) / (Math.pow(u, 4) + 0.432))
          + (1 / 18.7) * Math.log(1 + Math.pow(u / 18.1, 3));
  const b = 0.564 * Math.pow((er - 0.9) / (er + 3), 0.053);
  return (er + 1) / 2 + ((er - 1) / 2) * Math.pow(1 + 10 / u, -a * b);
}

/** Hammerstad-Jensen characteristic impedance [ohm]. */
export function z0Microstrip(er, w, h, t = 0) {
  const u = w / h;
  const fu = 6 + (2 * Math.PI - 6) * Math.exp(-Math.pow(30.666 / u, 0.7528));
  const z01 = (ETA0 / (2 * Math.PI)) * Math.log(fu / u + Math.sqrt(1 + Math.pow(2 / u, 2)));
  const ee = epsEffStatic(er, w, h, t);
  return z01 / Math.sqrt(ee);
}

/**
 * Wheeler/Hammerstad synthesis: strip width for a target Z0.
 * Refined by two Newton iterations on the analysis model.
 */
export function synthesizeWidth(er, z0, h, t = 0) {
  const A = (z0 / 60) * Math.sqrt((er + 1) / 2) + ((er - 1) / (er + 1)) * (0.23 + 0.11 / er);
  const B = (377 * Math.PI) / (2 * z0 * Math.sqrt(er));
  let uA = (8 * Math.exp(A)) / (Math.exp(2 * A) - 2);
  let uB = (2 / Math.PI) * (B - 1 - Math.log(2 * B - 1) + ((er - 1) / (2 * er)) * (Math.log(B - 1) + 0.39 - 0.61 / er));
  let u = uA < 2 ? uA : uB;
  let w = u * h;
  for (let i = 0; i < 40; i++) {
    const z = z0Microstrip(er, w, h, t);
    const err = (z - z0) / z0;
    if (Math.abs(err) < 1e-7) break;
    w *= 1 + err * 0.8; // Z0 decreases with W -> increase W when Z0 too high
  }
  return w;
}

/** Kirschning-Jansen dispersion of eps_eff. f in Hz, dimensions in m. */
export function epsEffDispersive(er, w, h, f, t = 0) {
  const ee0 = epsEffStatic(er, w, h, t);
  const u = w / h;
  const fn = (f * h) / 1e9 / 1e-3 / 1e9; // normalised f*h in GHz*mm -> keep as GHz*mm
  const fGHzmm = (f / 1e9) * (h * 1e3);
  const P1 = 0.27488 + (0.6315 + 0.525 / Math.pow(1 + 0.0157 * fGHzmm, 20)) * u - 0.065683 * Math.exp(-8.7513 * u);
  const P2 = 0.33622 * (1 - Math.exp(-0.03442 * er));
  const P3 = 0.0363 * Math.exp(-4.6 * u) * (1 - Math.exp(-Math.pow(fGHzmm / 3.87, 4.97)));
  const P4 = 1 + 2.751 * (1 - Math.exp(-Math.pow(er / 15.916, 8)));
  const P = P1 * P2 * Math.pow((0.1844 + P3 * P4) * fGHzmm, 1.5763);
  void fn;
  return er - (er - ee0) / (1 + P);
}

/**
 * Conductor attenuation [Np/m] including surface roughness.
 * roughnessModel: 'hammerstad' (default) or 'huray'.
 *  rq  = RMS surface roughness [m] (HVLP ~0.5 um, VLP ~1 um, standard ~2 um)
 */
export function alphaConductor(er, w, h, f, sigma, t = 35e-6, rq = 1e-6, roughnessModel = 'hammerstad') {
  const Rs = surfaceResistance(f, sigma);
  const z0 = z0Microstrip(er, w, h, t);
  // Wheeler incremental-inductance approximation for a wide strip
  const u = w / h;
  const geo = u >= 1
    ? (1 / (w)) * (1 + h / w) // dominant strip + return path
    : (1 / (w)) * (1 + h / w) * (1 + (1 / Math.PI) * Math.log((2 * h) / t));
  let Kr = 1;
  const delta = 1 / Math.sqrt(Math.PI * f * 4e-7 * Math.PI * sigma);
  if (roughnessModel === 'huray') {
    // Cannonball-Huray: Ksr = 1 + (Hex.area ratio) / (1 + delta/(2*rq))^2
    const ratio = 1 + (3 * Math.PI * (rq * rq)) / (Math.pow(0.5 * rq + 0.5 * delta, 2) * 6);
    Kr = Math.min(ratio, 2.5);
  } else {
    Kr = 1 + (2 / Math.PI) * Math.atan(1.4 * Math.pow(rq / delta, 2));
  }
  return (Rs * geo * Kr) / (2 * z0);
}

/** Dielectric attenuation [Np/m] using the filling factor. */
export function alphaDielectric(er, w, h, f, df) {
  const ee = epsEffStatic(er, w, h);
  const lam0 = C0 / f;
  const q = ((ee - 1) / (er - 1)) * (er / ee); // filling factor
  return (Math.PI / lam0) * Math.sqrt(ee) * q * df;
}

/** Total line loss in dB per metre. */
export function lineLossDbPerM(opts) {
  const { er, df, w, h, f, sigma, t = 35e-6, rq = 1e-6, roughnessModel = 'hammerstad' } = opts;
  const ac = alphaConductor(er, w, h, f, sigma, t, rq, roughnessModel);
  const ad = alphaDielectric(er, w, h, f, df);
  return { conductor: ac * 8.686, dielectric: ad * 8.686, total: (ac + ad) * 8.686 };
}

/**
 * Highest usable microstrip frequency on a given substrate.
 * Limits: TM0 surface-wave onset and the lowest transverse-resonance mode.
 * Reference: Edwards & Steer, "Foundations of Interconnect and Microstrip Design".
 */
export function microstripFreqLimits(er, w, h) {
  const fTM1 = C0 / (4 * h * Math.sqrt(er - 1));            // first higher-order TM surface wave
  const fTransverse = C0 / (Math.sqrt(er) * (2 * w + 0.8 * h)); // transverse resonance
  return { fTM1, fTransverse, fMaxRecommended: Math.min(fTM1, fTransverse) };
}

/** Quarter-wave transformer between two real impedances. */
export function quarterWaveTransformer(er, h, f, zIn, zOut) {
  const zT = Math.sqrt(zIn * zOut);
  const w = synthesizeWidth(er, zT, h);
  const ee = epsEffStatic(er, w, h);
  const len = C0 / (4 * f * Math.sqrt(ee));
  return { z: zT, w, length: len, epsEff: ee };
}

/** Coaxial-probe series inductance (Balanis 14.x); L ~ mu0*h/(2pi)*ln(...). */
export function probeReactance(f, h, dProbe, er) {
  const mu0 = 4e-7 * Math.PI;
  const k = (2 * Math.PI * f) / C0 * Math.sqrt(er);
  const L = (mu0 * h) / (2 * Math.PI) * (Math.log(2 / (k * dProbe / 2)) - 0.577);
  return { L: Math.max(L, 0), X: 2 * Math.PI * f * Math.max(L, 0) };
}

/** Coplanar/edge coupling helper: gap needed for a target coupling in dB. */
export function edgeCouplingGap(er, h, couplingDb) {
  const c = Math.pow(10, -Math.abs(couplingDb) / 20);
  // Empirical inversion of the even/odd-mode ratio for microstrip edge couplers
  return h * Math.max(0.05, 0.35 * Math.pow((1 - c) / c, 0.55) / Math.sqrt(er));
}

export { sinc };
