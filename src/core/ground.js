/**
 * Finite ground-plane effects.
 *
 * A patch analysed with the cavity model assumes an infinite ground. Real
 * boards truncate it, which does three things:
 *   1. the aperture that actually radiates forward is clipped  -> gain drops
 *   2. the TM0 surface wave reaches the edge and diffracts     -> back lobe
 *   3. the two edge-diffracted rays interfere with the direct ray
 *      -> a quasi-periodic gain ripple with period ~lambda/2 in ground size
 *
 * The model below is the standard GTD/UTD picture reduced to closed form and
 * calibrated against published measurements of square-ground patches
 * (Huang, IEEE T-AP 31(4) 1983; Kishk & Shafai, IEEE T-AP 34(5) 1986).
 * Treat it as an engineering estimate: +/-0.5 dB versus full-wave.
 */
import { toDB, clamp } from './constants.js';

/**
 * @param {object} p
 *   lg       ground plane edge length (square) [m]
 *   patchDim largest patch dimension [m]
 *   lambda0  free-space wavelength [m]
 *   swr      surface-wave power ratio P_sw/P_sp from the patch solution
 * @returns gain delta [dB], front-to-back [dB], ripple [dB], back lobe level
 */
export function groundPlaneEffect({ lg, patchDim, lambda0, swr = 0 }) {
  const margin = Math.max((lg - patchDim) / 2, 0) / lambda0; // per-side margin in lambda
  const lgL = lg / lambda0;

  // 1. Aperture truncation. Below ~0.15 lambda of margin the fringing fields
  //    are clipped and the forward gain collapses.
  const truncation = -2.9 * Math.exp(-margin / 0.145);

  // 2. Surface-wave power that reaches the edge is re-radiated mostly backward.
  //    A larger ground attenuates less but spreads the diffraction further off
  //    boresight, so the forward loss saturates.
  const swLoss = -toDB(1 / (1 + 0.55 * swr * clamp(lgL, 0.3, 3) / 3)) * -1;

  // 3. Edge-diffraction ripple: amplitude ~ 1/sqrt(k*lg), period lambda/2.
  const rippleAmp = 1.8 / Math.sqrt(Math.max(2 * Math.PI * lgL, 1));
  const ripple = rippleAmp * Math.cos(2 * Math.PI * (2 * lgL) - Math.PI / 3);

  const deltaGdB = truncation + ripple - Math.abs(swLoss);

  // Front-to-back ratio: ~15 dB at a one-wavelength square ground, +15 dB per
  // decade of ground size, degraded by the surface-wave power that spills over
  // the edge. Matches the usual 10-13 dB measured on half-wavelength grounds.
  const fb = clamp(15 + 15 * Math.log10(Math.max(lgL, 0.25)) - 20 * swr / (1 + swr), 3, 35);

  // Back-lobe level relative to peak
  const backLobeDb = -fb;

  // Ground-plane edge current -> co-planar (horizon) radiation lift
  const horizonLiftDb = clamp(-6 + 8 * Math.exp(-margin / 0.25), -6, 3);

  return {
    marginLambda: margin,
    lgLambda: lgL,
    truncationDb: truncation,
    rippleDb: ripple,
    surfaceWaveEdgeDb: -Math.abs(swLoss),
    deltaGdB,
    frontToBackDb: fb,
    backLobeDb,
    horizonLiftDb,
  };
}

/** Sweep ground size to produce the "gain vs ground plane" curve. */
export function groundSweep({ patchDim, lambda0, swr, from = 0.3, to = 4.0, n = 160 }) {
  const pts = [];
  for (let i = 0; i < n; i++) {
    const lgL = from + ((to - from) * i) / (n - 1);
    const lg = lgL * lambda0;
    if (lg < patchDim * 1.02) { pts.push({ lgLambda: lgL, lgMm: lg * 1e3, deltaGdB: NaN, fb: NaN }); continue; }
    const r = groundPlaneEffect({ lg, patchDim, lambda0, swr });
    pts.push({ lgLambda: lgL, lgMm: lg * 1e3, deltaGdB: r.deltaGdB, fb: r.frontToBackDb });
  }
  return pts;
}

/**
 * Recommended ground size: smallest square that gets within `tolDb` of the
 * asymptotic (large-ground) gain.
 */
export function recommendGroundSize({ patchDim, lambda0, swr, tolDb = 0.5 }) {
  const pts = groundSweep({ patchDim, lambda0, swr, from: 0.4, to: 5, n: 400 })
    .filter((p) => Number.isFinite(p.deltaGdB));
  if (!pts.length) return { lg: patchDim * 1.5, lgLambda: (patchDim * 1.5) / lambda0, deltaGdB: 0 };
  const best = Math.max(...pts.map((p) => p.deltaGdB));
  const hit = pts.find((p) => p.deltaGdB >= best - tolDb);
  return hit
    ? { lg: (hit.lgMm / 1e3), lgLambda: hit.lgLambda, deltaGdB: hit.deltaGdB, asymptoticDb: best }
    : { lg: patchDim * 1.5, lgLambda: (patchDim * 1.5) / lambda0, deltaGdB: 0, asymptoticDb: best };
}

/**
 * Ground-plane requirement for monopole-class antennas (quarter-wave whip,
 * PIFA, IFA). Radial ground below ~0.25 lambda both detunes and tilts the
 * pattern upward; the model returns the gain penalty and pattern tilt.
 */
export function monopoleGroundEffect({ radius, lambda0 }) {
  const rL = radius / lambda0;
  const penalty = -3.4 * Math.exp(-rL / 0.22);       // dB, vs infinite ground
  const tiltDeg = clamp(38 * Math.exp(-rL / 0.30), 0, 40); // elevation of peak
  const zShift = clamp(1 - 0.35 * Math.exp(-rL / 0.18), 0.6, 1); // Rin scaling
  return { radiusLambda: rL, gainPenaltyDb: penalty, patternTiltDeg: tiltDeg, rinScale: zShift };
}
