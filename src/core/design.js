/**
 * Design orchestrator: one call that turns a specification into a complete,
 * reviewable antenna design plus every dataset the UI plots.
 */
import { C0, CONDUCTORS, toDB, fromDB, clamp } from './constants.js';
import { MATERIALS, MATERIAL_BY_ID, dispersiveEr, snapToStock } from './materials.js';
import {
  solvePatch, compositeEr, patchLength, patchWidth, insetDepth, probeOffset,
  inputImpedance, s11Db, patchFieldSq, resonantFrequency,
} from './patch.js';
import {
  synthesizeWidth, z0Microstrip, epsEffStatic, quarterWaveTransformer,
  lineLossDbPerM, microstripFreqLimits, probeReactance,
} from './microstrip.js';
import { groundPlaneEffect, groundSweep, recommendGroundSize } from './ground.js';
import { recommend } from './recommend.js';
import { feasibility, fieldRegions, beamwidthFromDirectivity, bodeFano } from './limits.js';
import { solveThermal, peakPowerLimit, driftBudget, frequencyDrift } from './thermal.js';
import { monteCarlo } from './tolerance.js';
import { bandFor } from './bands.js';

/**
 * Build the effective substrate for the chosen stack-up.
 * mode: 'solid' | 'airgap' (thin carrier over an air gap)
 */
export function buildStack(spec) {
  const base = MATERIAL_BY_ID[spec.materialId] || MATERIALS[0];
  const disp = dispersiveEr(base, spec.f);
  const material = { ...base, er: disp.er, df: disp.df };
  if (spec.stackMode === 'airgap') {
    const carrierH = spec.carrierH ?? 0.8e-3;
    const gap = spec.airGap ?? 4.2e-3;
    const comp = compositeEr([
      { h: gap, er: 1.0006, df: 0 },
      { h: carrierH, er: material.er, df: material.df },
    ]);
    return {
      material: {
        ...material,
        id: `${material.id}+air`,
        name: `${material.name} carrier over ${(gap * 1e3).toFixed(1)} mm air`,
        er: comp.er, df: comp.df,
        // thermal path is now through the spacers only
        k: 0.05, kxy: material.kxy,
      },
      h: comp.h, layers: [
        { name: 'Air gap', h: gap, er: 1.0006, df: 0 },
        { name: base.name, h: carrierH, er: material.er, df: material.df },
      ],
      composite: comp, baseMaterial: base,
    };
  }
  const h = spec.snapStock ? snapToStock(base, spec.h) : spec.h;
  return {
    material, h,
    layers: [{ name: base.name, h, er: material.er, df: material.df }],
    composite: null, baseMaterial: base,
  };
}

/** Feed-network synthesis for a patch. */
export function synthesizeFeed(spec, sol, stack) {
  const { f } = spec;
  const z0 = spec.z0 ?? 50;
  const cu = CONDUCTORS[spec.conductor || 'copper'];
  const er = stack.material.er;
  const h = stack.h;
  const out = { type: spec.feedType || 'inset', z0 };

  const w50 = synthesizeWidth(er, z0, h);
  const loss = lineLossDbPerM({ er, df: stack.material.df, w: w50, h, f, sigma: cu.sigma, rq: spec.roughnessRq ?? 1e-6 });
  out.feedLineWidth = w50;
  out.feedLineLossDbPerCm = loss.total / 100;
  out.epsEffFeed = epsEffStatic(er, w50, h);
  out.lambdaG = C0 / (f * Math.sqrt(out.epsEffFeed));

  if (out.type === 'inset') {
    const y0 = insetDepth(sol.Rin, z0, sol.L);
    out.insetDepth = y0;
    out.insetGap = clamp(w50 * 0.6, 0.2e-3, 1.5e-3);
    out.notchNote = 'Notch gap sets a small series capacitance; 0.5-1x the feed-line width is the usual starting point.';
  } else if (out.type === 'quarterWave') {
    const qw = quarterWaveTransformer(er, h, f, z0, sol.Rin);
    out.transformer = qw;
  } else if (out.type === 'probe') {
    const off = probeOffset(sol.Rin, z0, sol.L);
    const px = probeReactance(f, h, spec.probeDia ?? 1.3e-3, er);
    out.probeOffset = off;
    out.probeInductanceNh = px.L * 1e9;
    out.probeReactance = px.X;
    out.probeNote = px.X > 15
      ? `Probe adds +j${px.X.toFixed(0)} ohm - compensate with a series capacitive gap or move to an aperture-coupled feed.`
      : `Probe reactance +j${px.X.toFixed(1)} ohm is small enough to absorb in the match.`;
  } else if (out.type === 'apertureCoupled') {
    out.slotLength = sol.W * 0.4;
    out.slotWidth = clamp(sol.W * 0.03, 0.15e-3, 1.2e-3);
    out.stubLength = out.lambdaG * 0.12;
  }
  return out;
}

/** S11 / VSWR / impedance sweep for the chart. */
export function sweepS11(sol, f0, feed, span = 0.25, n = 401) {
  const pts = [];
  const Lp = feed && feed.probeInductanceNh ? feed.probeInductanceNh * 1e-9 : 0;
  const R0 = feed && feed.type === 'inset' ? 50 : (feed && feed.type === 'quarterWave' ? 50 : 50);
  for (let i = 0; i < n; i++) {
    const f = f0 * (1 - span / 2) + ((f0 * span) * i) / (n - 1);
    const z = inputImpedance(f, f0, R0, sol.Qt, Lp);
    const s = s11Db(z.R, z.X, 50);
    pts.push({ f, R: z.R, X: z.X, s11: s.s11, vswr: Math.min(s.vswr, 20), gamma: s.gamma });
  }
  return pts;
}

/**
 * Principal-plane cuts of the patch pattern (E: phi=0, H: phi=90).
 *
 * The cavity model assumes an infinite ground, which would leave a
 * discontinuous step at the horizon and no back radiation at all. A real
 * finite ground plane diffracts the incident space wave and the TM0 surface
 * wave over its rim, which does three things: it lifts the horizon level,
 * fills in the back hemisphere, and rounds the transition. That is applied
 * here as a continuous taper anchored to two computed quantities - the
 * front-to-back ratio and the horizon level implied by it - so the plotted
 * pattern is C0-continuous and matches what a measured range shows.
 */
export function patternCuts(sol, opts = {}) {
  const Le = sol.Le, W = sol.W;
  const f = opts.f;
  const k0v = (2 * Math.PI * f) / C0;
  const h = opts.h || 1e-3;
  const fb = opts.frontToBackDb ?? 15;
  const back = fromDB(-fb);                        // back-lobe level, linear
  const horizon = fromDB(-(0.55 * fb + 1.5));      // level at theta = 90 deg

  const cavity = (theta, phi) => {
    const th = Math.min(Math.max(theta, 0), Math.PI / 2 - 1e-6);
    return patchFieldSq(th, phi, k0v, Le, W, h).u;
  };
  const u0 = cavity(1e-6, 0);

  const cut = (phiPos, phiNeg) => {
    const pts = [];
    for (let d = -180; d <= 180; d += 1) {
      const a = (Math.abs(d) * Math.PI) / 180;
      const phi = d >= 0 ? phiPos : phiNeg;
      let u;
      if (a <= Math.PI / 2) {
        // front hemisphere: cavity pattern tapered to the horizon level
        const taper = horizon + (1 - horizon) * Math.pow(Math.cos(a), 2);
        u = cavity(a, phi) * taper;
      } else {
        // back hemisphere: mirrored shape, blended from horizon to back level
        const mirror = Math.PI - a;
        const c = back + (horizon - back) * Math.pow(Math.sin(mirror), 2);
        u = cavity(mirror, phi) * c;
      }
      pts.push({ deg: d, db: clamp(toDB(u / u0), -40, 5) });
    }
    return pts;
  };

  return { E: cut(0, Math.PI), H: cut(Math.PI / 2, -Math.PI / 2) };
}

/** Efficiency / gain versus substrate thickness, for a set of materials. */
export function thicknessSweep(spec, materialIds, opts = {}) {
  const { f } = spec;
  const includeSurfaceWave = opts.includeSurfaceWave ?? true;
  const out = [];
  for (const id of materialIds) {
    const base = MATERIAL_BY_ID[id];
    if (!base) continue;
    const d = dispersiveEr(base, f);
    const lam = C0 / f;
    const hs = [];
    const hMax = Math.min(0.12 * lam, 8e-3 + 0.02 * lam);
    for (let i = 1; i <= 60; i++) {
      const h = (hMax * i) / 60;
      const s = solvePatch({ f, er: d.er, df: d.df, h, sigma: spec.sigma || 5.8e7 });
      let eta = s.etaSpace;
      if (!includeSurfaceWave) {
        const invQ = 1 / s.Qrad + 1 / s.Qd + 1 / s.Qc;
        eta = (1 / invQ) / s.Qrad;
      }
      hs.push({ h, hMm: h * 1e3, hOverLambda: h / lam, eta, etaPct: eta * 100,
                gain: toDB(s.D0 * eta), bwPct: s.fbw2 * 100, Qrad: s.Qrad, Qt: s.Qt,
                swr: s.surfaceWaveRatio });
    }
    out.push({ id, name: base.name, er: d.er, df: d.df, points: hs, stock: base.stock });
  }
  return out;
}

/** eps_r sweep: aperture size and directivity versus permittivity. */
export function permittivitySweep(spec, opts = {}) {
  const { f } = spec;
  const h = opts.h ?? spec.h;
  const pts = [];
  for (let i = 0; i <= 60; i++) {
    const er = 1 + (11 * i) / 60;
    const s = solvePatch({ f, er, df: 0.001, h, sigma: spec.sigma || 5.8e7 });
    pts.push({ er, LeOverLambda: s.LeOverLambda, WOverLambda: s.WOverLambda, D0dBi: s.D0dBi,
               areaRatio: (s.W * s.Le) / (C0 / f) ** 2 });
  }
  return pts;
}

/** Substrate trade study: realized gain for every candidate material. */
export function substrateTrade(spec, stackCandidates) {
  return stackCandidates.map((c) => {
    const stack = buildStack({ ...spec, ...c });
    const sol = solvePatch({ f: spec.f, er: stack.material.er, df: stack.material.df, h: stack.h, sigma: spec.sigma || 5.8e7 });
    const patchDim = Math.max(sol.W, sol.L);
    const gnd = spec.groundM
      ? groundPlaneEffect({ lg: spec.groundM, patchDim, lambda0: sol.lambda0, swr: sol.surfaceWaveRatio })
      : { deltaGdB: 0, frontToBackDb: 20 };
    const realized = sol.gainDbi + gnd.deltaGdB - (spec.feedLossDb || 0);
    return {
      label: c.label || stack.material.name,
      materialId: c.materialId, h: stack.h, er: stack.material.er, df: stack.material.df,
      sol, gnd, realizedGainDbi: realized, efficiency: sol.etaSpace,
      bwPct: sol.fbw2 * 100, fits: patchDim <= (spec.groundM || Infinity),
      cost: (MATERIAL_BY_ID[c.materialId] || {}).cost ?? 1,
      widthMm: sol.W * 1e3, lengthMm: sol.L * 1e3,
    };
  });
}

/** The full design run used by the UI. */
export function runDesign(spec) {
  const stack = buildStack(spec);
  const lam = C0 / spec.f;
  const cu = CONDUCTORS[spec.conductor || 'copper'];

  const sol = solvePatch({
    f: spec.f, er: stack.material.er, df: stack.material.df,
    h: stack.h, sigma: cu.sigma, tCu: spec.tCu ?? 35e-6,
  });

  const patchDim = Math.max(sol.W, sol.L);
  const groundM = spec.groundM || Math.max(patchDim + lam * 0.5, patchDim * 1.4);
  const gnd = groundPlaneEffect({ lg: groundM, patchDim, lambda0: lam, swr: sol.surfaceWaveRatio });
  const realizedGainDbi = sol.gainDbi + gnd.deltaGdB - (spec.feedLossDb || 0);

  const feed = synthesizeFeed(spec, sol, stack);
  const s11 = sweepS11(sol, spec.f, feed);
  const pattern = patternCuts(sol, { f: spec.f, h: stack.h, frontToBackDb: gnd.frontToBackDb });
  const bw = beamwidthFromDirectivity(sol.D0);

  const rec = recommend({
    f: spec.f, material: stack.material, h: stack.h, sigma: cu.sigma,
    targetGainDbi: spec.targetGainDbi, pattern: spec.pattern,
    polarization: spec.polarization, bwPct: spec.bwPct,
    maxDimM: spec.maxDimM, groundM, feedLossDb: spec.feedLossDb || 0,
    lowProfile: spec.lowProfile, priority: spec.priority,
  });

  const thermal = solveThermal({
    pInW: spec.powerW ?? 1, efficiency: sol.etaSpace,
    mismatchGamma: 0.1, areaM2: groundM * groundM, perimeterM: 4 * groundM,
    material: stack.material, h: stack.h, tAmbC: spec.tAmbC ?? 25,
    airVelocity: spec.airVelocity ?? 0, emissivity: spec.emissivity ?? 0.9,
    altitudeM: spec.altitudeM ?? 0, viaCount: spec.viaCount ?? 0,
    orientation: spec.orientation || 'horizontalUp',
  });
  const peak = peakPowerLimit({
    pPeakW: spec.peakPowerW ?? (spec.powerW ?? 1), Redge: sol.Rin, h: stack.h,
    material: stack.baseMaterial, altitudeM: spec.altitudeM ?? 0, vswr: 1.5,
  });
  const drift = driftBudget(stack.baseMaterial, spec.f, spec.tMinC ?? -40, spec.tMaxC ?? 85, sol.fbw2);

  const lim = feasibility({
    f: spec.f, maxDimM: spec.maxDimM || groundM,
    targetGainDbi: spec.targetGainDbi, fracBw: spec.bwPct ? spec.bwPct / 100 : null,
    efficiency: sol.etaSpace, circular: spec.polarization === 'circular',
  });
  const regions = fieldRegions(patchDim, lam);

  return {
    spec, stack, sol, feed, s11, pattern, groundM, gnd, realizedGainDbi,
    beamwidth: bw, recommendation: rec, thermal, peak, drift, limits: lim,
    fieldRegions: regions, band: bandFor(spec.f), lambda0: lam,
    microstripLimits: microstripFreqLimits(stack.material.er, feed.feedLineWidth, stack.h),
    bodeFano: bodeFano(sol.Qt, spec.bwPct ? spec.bwPct / 100 : sol.fbw2),
    conductor: cu,
  };
}

export {
  solvePatch, groundSweep, recommendGroundSize, monteCarlo, frequencyDrift,
  MATERIALS, MATERIAL_BY_ID, resonantFrequency, patchWidth, patchLength,
  z0Microstrip, synthesizeWidth, toDB, fromDB, clamp, C0, CONDUCTORS,
};
