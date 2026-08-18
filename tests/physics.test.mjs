/**
 * Physics regression tests.
 *
 * These lock in the values the engine was validated against. If a model change
 * moves any of them, that is a deliberate decision that has to be re-argued -
 * not something that should slip through silently.
 *
 * Run: node --test tests/
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { C0, skinDepth, surfaceResistance } from '../src/core/constants.js';
import { MATERIAL_BY_ID, dispersiveEr } from '../src/core/materials.js';
import { z0Microstrip, synthesizeWidth, epsEffStatic, lineLossDbPerM } from '../src/core/microstrip.js';
import { solvePatch, patchWidth, patchLength, resonantFrequency, compositeEr, besselJ0,
         slotConductance, mutualConductance } from '../src/core/patch.js';
import { groundPlaneEffect } from '../src/core/ground.js';
import { chuQ, harringtonDirectivity, maxFractionalBandwidth } from '../src/core/limits.js';
import { fspl, gaseousAttenuation, rainAttenuation, noiseFloorDbm, linkBudget } from '../src/core/propagation.js';
import { solveThermal, paschenVoltage, frequencyDrift } from '../src/core/thermal.js';
import { monteCarlo } from '../src/core/tolerance.js';
import { recommend } from '../src/core/recommend.js';
import { runDesign, thicknessSweep } from '../src/core/design.js';

const close = (a, b, tol, msg) =>
  assert.ok(Math.abs(a - b) <= tol, `${msg || ''}: got ${a}, expected ${b} ± ${tol}`);

/* ------------------------------------------------------------- constants */

test('skin depth and surface resistance of copper at 1 GHz', () => {
  // delta = 2.06 um, Rs = 8.25 mohm/sq  (standard reference values)
  close(skinDepth(1e9, 5.8e7) * 1e6, 2.09, 0.05, 'skin depth [um]');
  close(surfaceResistance(1e9, 5.8e7) * 1e3, 8.25, 0.15, 'Rs [mohm/sq]');
});

/* ------------------------------------------------------------- materials */

test('Djordjevic-Sarkar dispersion anchors the datasheet point and falls with f', () => {
  const fr4 = MATERIAL_BY_ID.fr4;
  const at1 = dispersiveEr(fr4, 1e9);
  const at10 = dispersiveEr(fr4, 10e9);
  close(at1.er, 4.30, 0.02, 'Dk anchored at the 1 GHz datasheet point');
  assert.ok(at10.er < at1.er, 'Dk must fall with frequency');
  assert.ok(at10.er > 4.0, 'FR-4 Dk should stay above 4.0 at 10 GHz');
});

/* ------------------------------------------------------------ microstrip */

test('50 ohm line widths match published tables', () => {
  // 1.6 mm FR-4 (er 4.3): W50 ~ 3.0-3.1 mm
  close(synthesizeWidth(4.3, 50, 1.6e-3, 35e-6) * 1e3, 3.05, 0.15, 'FR-4 1.6 mm');
  // 0.508 mm RO4003C (er 3.55): W50 ~ 1.15 mm per the Rogers datasheet
  close(synthesizeWidth(3.55, 50, 0.508e-3, 35e-6) * 1e3, 1.15, 0.10, 'RO4003C 0.508 mm');
  // 0.254 mm RT/duroid 5880 (er 2.2): W50 ~ 0.79 mm
  close(synthesizeWidth(2.2, 50, 0.254e-3, 17e-6) * 1e3, 0.79, 0.06, 'RT5880 0.254 mm');
});

test('synthesis and analysis are mutually consistent', () => {
  for (const er of [1.0, 2.2, 3.55, 4.3, 10.2]) {
    for (const z of [25, 50, 75, 100]) {
      const w = synthesizeWidth(er, z, 0.8e-3);
      close(z0Microstrip(er, w, 0.8e-3), z, 0.05, `er=${er} Z0=${z}`);
    }
  }
});

test('microstrip loss on FR-4 at 2.45 GHz is around 0.08 dB/cm', () => {
  const w = synthesizeWidth(4.3, 50, 1.6e-3);
  const l = lineLossDbPerM({ er: 4.3, df: 0.02, w, h: 1.6e-3, f: 2.45e9, sigma: 5.8e7 });
  close(l.total / 100, 0.081, 0.02, 'dB/cm');
  assert.ok(l.dielectric > l.conductor, 'FR-4 loss must be dielectric-dominated');
});

/* ----------------------------------------------------------------- patch */

test('patch synthesis reproduces the classic 2.45 GHz FR-4 example', () => {
  const W = patchWidth(2.45e9, 4.3);
  close(W * 1e3, 37.6, 0.6, 'patch width');
  const { L, epsEff } = patchLength(2.45e9, 4.3, 1.6e-3, W);
  close(L * 1e3, 29.1, 0.6, 'patch length');
  close(epsEff, 3.95, 0.08, 'effective permittivity');
  // round trip
  close(resonantFrequency(L, 4.3, 1.6e-3, W) / 1e9, 2.45, 0.005, 'resonance round trip');
});

test('slot conductances match Balanis Example 14.1', () => {
  // f = 10 GHz, er = 2.2, h = 1.588 mm -> W = 11.86 mm, L = 9.06 mm
  // Published: G1 = 1.57e-3 S, G12 = 6.1683e-4 S, Rin = 228.35 ohm
  const f = 10e9, lam = C0 / f, k0v = (2 * Math.PI) / lam;
  const W = 0.01186, L = 0.00906;
  const G1 = slotConductance(W, lam, k0v);
  const G12 = mutualConductance(W, L, lam, k0v);
  close(G1, 1.5728e-3, 5e-6, 'G1');
  close(G12, 6.1683e-4, 5e-6, 'G12');
  close(1 / (2 * (G1 + G12)), 228.35, 1.0, 'input resistance at the radiating edge');
  // and the synthesis that produces those dimensions
  close(patchWidth(f, 2.2) * 100, 1.186, 0.005, 'synthesised W [cm]');
  close(patchLength(f, 2.2, 0.1588e-2, patchWidth(f, 2.2)).L * 100, 0.906, 0.01, 'synthesised L [cm]');
});

test('Bessel J0 matches reference values', () => {
  close(besselJ0(0), 1, 1e-7);
  close(besselJ0(1), 0.7651976866, 1e-6);
  close(besselJ0(2.404825558), 0, 1e-6, 'first zero');
  close(besselJ0(10), -0.2459357644, 1e-6);
});

test('directivity rises as permittivity falls (aperture argument)', () => {
  const d = (er) => solvePatch({ f: 2.45e9, er, df: 0.001, h: 1.6e-3 }).D0dBi;
  const air = d(1.0006), ro = d(3.55), fr4 = d(4.3), hi = d(10.2);
  assert.ok(air > ro && ro > fr4 && fr4 > hi, `monotonic: ${air} > ${ro} > ${fr4} > ${hi}`);
  close(air, 9.3, 0.7, 'air-substrate patch directivity');
  close(fr4, 6.1, 0.5, 'FR-4 patch directivity');
});

test('radiation efficiency reproduces the validated substrate curve', () => {
  // Reference data (surface wave excluded, which is how the textbook curve is
  // drawn): FR-4 tand 0.020 at 2.45 GHz.
  const etaNoSw = (er, df, h) => {
    const s = solvePatch({ f: 2.45e9, er, df, h });
    const invQ = 1 / s.Qrad + 1 / s.Qd + 1 / s.Qc;
    return ((1 / invQ) / s.Qrad) * 100;
  };
  const expect = [[0.2e-3, 6.5], [0.4e-3, 14], [0.8e-3, 26], [1.6e-3, 43], [2.4e-3, 54], [3.2e-3, 62]];
  for (const [h, pct] of expect) close(etaNoSw(4.3, 0.020, h), pct, 3.0, `FR-4 h=${h * 1e3} mm`);
  close(etaNoSw(3.55, 0.0027, 1.524e-3), 82, 3.0, 'RO4003C 1.52 mm');
  close(etaNoSw(3.55, 0.0027, 3.048e-3), 92, 3.0, 'RO4003C 3.05 mm');
});

test('composite air-gap stack gives a near-unity permittivity and high efficiency', () => {
  const c = compositeEr([{ h: 4.2e-3, er: 1.0006, df: 0 }, { h: 0.8e-3, er: 4.3, df: 0.02 }]);
  close(c.er, 1.14, 0.03, 'composite eps_r');
  close(c.h * 1e3, 5.0, 1e-6, 'total height');
  const s = solvePatch({ f: 2.442e9, er: c.er, df: c.df, h: c.h });
  assert.ok(s.etaSpace > 0.97, `efficiency ${s.etaSpace}`);
  assert.ok(s.fbw2 * 100 > 4, `bandwidth ${s.fbw2 * 100} %`);
});

test('surface-wave power grows with thickness and permittivity', () => {
  const swr = (er, h) => solvePatch({ f: 2.45e9, er, df: 0.001, h }).surfaceWaveRatio;
  assert.ok(swr(4.3, 3.2e-3) > swr(4.3, 0.8e-3), 'grows with h');
  assert.ok(swr(10.2, 1.6e-3) > swr(2.2, 1.6e-3), 'grows with er');
  assert.ok(swr(1.0006, 1.6e-3) < 1e-6, 'essentially no surface wave without a dielectric');
});

test('bandwidth follows the Q relation', () => {
  const s = solvePatch({ f: 2.45e9, er: 4.3, df: 0.02, h: 1.6e-3 });
  close(s.fbw2, (2 - 1) / (s.Qt * Math.SQRT2), 1e-9, 'BW = (S-1)/(Q*sqrt(S))');
});

/* ---------------------------------------------------------- ground plane */

test('finite ground plane penalises small grounds and saturates on large ones', () => {
  const g = (lgL) => groundPlaneEffect({ lg: lgL * 0.1224, patchDim: 0.0376, lambda0: 0.1224, swr: 0.09 });
  assert.ok(g(0.5).deltaGdB < -0.5, 'half-wavelength ground costs gain');
  assert.ok(Math.abs(g(2.0).deltaGdB) < 0.4, 'two-wavelength ground is essentially infinite');
  assert.ok(g(3).frontToBackDb > g(1).frontToBackDb, 'F/B improves with ground size');
  close(g(1).frontToBackDb, 13.3, 2.5, 'F/B at one wavelength');
});

/* ---------------------------------------------------------------- limits */

test('Chu and Harrington bounds', () => {
  close(chuQ(1), 2, 1e-9, 'Q_min at ka = 1');
  close(harringtonDirectivity(1 / (2 * Math.PI), 1), 3, 1e-9, 'D_max = (ka)^2 + 2ka = 3 at ka = 1');
  assert.ok(maxFractionalBandwidth(0.005, 0.1224, 1) < maxFractionalBandwidth(0.05, 0.1224, 1),
    'bigger antennas can be more broadband');
});

/* ----------------------------------------------------------- propagation */

test('free-space path loss matches the closed form', () => {
  close(fspl(2.45e9, 1000), 100.23, 0.05, 'FSPL at 1 km, 2.45 GHz');
  close(fspl(1e9, 1000), 92.45, 0.05, 'FSPL at 1 km, 1 GHz');
});

test('gaseous absorption tracks the ITU-R P.676 reference curve', () => {
  const cases = [[10, 0.011, 0.03], [22.235, 0.20, 0.09], [60, 15.1, 2.0],
                 [94, 0.45, 0.20], [183.31, 29, 4.0]];
  for (const [fG, ref, tol] of cases) {
    close(gaseousAttenuation(fG * 1e9).total, ref, tol, `${fG} GHz`);
  }
  assert.ok(gaseousAttenuation(60e9).oxygen > 10 * gaseousAttenuation(60e9).water,
    'the 60 GHz peak is oxygen, not water');
});

test('rain attenuation follows ITU-R P.838 k*R^alpha', () => {
  close(rainAttenuation(10e9, 25).gammaR, 0.65, 0.15, '10 GHz, 25 mm/h');
  close(rainAttenuation(30e9, 25).gammaR, 4.5, 1.0, '30 GHz, 25 mm/h');
  assert.ok(rainAttenuation(77e9, 25).gammaR > rainAttenuation(10e9, 25).gammaR, 'worse at mmWave');
});

test('noise floor and link budget', () => {
  close(noiseFloorDbm(1e6), -114, 0.2, 'kTB in 1 MHz');
  close(noiseFloorDbm(20e6), -101, 0.2, 'kTB in 20 MHz');
  const lb = linkBudget({ f: 2.45e9, distance: 1000, ptxDbm: 20, gtxDbi: 7, grxDbi: 2,
                          bandwidth: 20e6, nfDb: 6, requiredSnrDb: 10 });
  close(lb.eirpDbm, 26.5, 0.01, 'EIRP');
  close(lb.prxDbm, -72.2, 0.2, 'received power');
  assert.ok(lb.marginDb > 0, 'the reference link closes');
});

/* --------------------------------------------------------------- thermal */

test('Paschen curve for air', () => {
  // ~5-8 kV across 1.6 mm at sea level; collapses at altitude
  const sea = paschenVoltage(1.6e-3, 101325);
  const high = paschenVoltage(1.6e-3, 5475);   // ~20 km
  assert.ok(sea > 4000 && sea < 10000, `sea level ${sea} V`);
  assert.ok(high < sea / 5, `altitude ${high} V should collapse`);
});

test('thermal solution is energy-consistent and monotonic in power', () => {
  const fr4 = MATERIAL_BY_ID.fr4;
  const run = (p) => solveThermal({
    pInW: p, efficiency: 0.41, mismatchGamma: 0.1, areaM2: 0.07 * 0.07,
    perimeterM: 4 * 0.07, material: fr4, h: 1.6e-3, tAmbC: 25, emissivity: 0.9,
  });
  const a = run(1), b = run(10);
  assert.ok(b.tHotC > a.tHotC, 'more power, hotter');
  close(a.pDissipatedW, 1 * 0.99 * 0.59 + 0.003, 0.02, 'dissipated = (1-eta)*P_accepted');
  assert.ok(a.rTotalKperW > 5 && a.rTotalKperW < 30, `Rth ${a.rTotalKperW} K/W plausible for a 49 cm2 board`);
  const forced = solveThermal({
    pInW: 10, efficiency: 0.41, mismatchGamma: 0.1, areaM2: 0.07 * 0.07,
    perimeterM: 4 * 0.07, material: fr4, h: 1.6e-3, tAmbC: 25, emissivity: 0.9, airVelocity: 3,
  });
  assert.ok(forced.tHotC < b.tHotC, 'forced air cools it');
});

test('temperature drift signs are physical', () => {
  const fr4 = MATERIAL_BY_ID.fr4;      // TCDk negative -> f rises with T
  const up = frequencyDrift(fr4, 2.45e9, +60);
  assert.ok(up.relative > 0, 'negative TCDk pushes the resonance up with temperature');
  const ro3003 = MATERIAL_BY_ID.ro3003; // near-zero TCDk -> tiny drift
  assert.ok(Math.abs(frequencyDrift(ro3003, 2.45e9, 60).relative) <
            Math.abs(up.relative) / 3, 'RO3003 drifts far less than FR-4');
});

/* ------------------------------------------------------------- tolerance */

test('Monte Carlo yield reflects the bandwidth-versus-tolerance reality', () => {
  const fr4 = MATERIAL_BY_ID.fr4;
  const s = solvePatch({ f: 2.442e9, er: fr4.er, df: fr4.df, h: 1.6e-3 });
  const wide = monteCarlo({ f0: 2.442e9, material: fr4, h: 1.6e-3, W: s.W, L: s.L,
                            bandHz: [2.4e9, 2.4835e9], n: 600 });
  assert.ok(wide.yieldPct < 20, `solid FR-4 cannot cover the whole ISM band: ${wide.yieldPct} %`);
  const narrow = monteCarlo({ f0: 2.442e9, material: fr4, h: 1.6e-3, W: s.W, L: s.L,
                             bandHz: [2.437e9, 2.447e9], n: 600 });
  assert.ok(narrow.yieldPct > wide.yieldPct, 'a narrower requirement yields better');
  // Dk is the dominant contributor on FR-4
  const dk = Math.abs(wide.sensitivity.dk * wide.dkTolerance);
  const etch = Math.abs(wide.sensitivity.length * (25e-6 / s.L));
  assert.ok(dk > etch, `Dk (${dk}) must dominate etch (${etch}) on FR-4`);
});

/* ----------------------------------------------------------- recommender */

test('recommender picks physically sensible types for three very different specs', () => {
  const fr4 = MATERIAL_BY_ID.fr4;
  const wifi = recommend({ f: 2.442e9, material: fr4, h: 1.6e-3, sigma: 5.8e7,
    targetGainDbi: 7, pattern: 'directional', polarization: 'linear', bwPct: 3.4,
    maxDimM: 0.12, groundM: 0.07, feedLossDb: 0.4 });
  const top = wifi.candidates[0];
  assert.equal(top.verdict, 'recommended');
  assert.ok(top.realizedGainDbi >= 7, `top candidate must meet the target: ${top.realizedGainDbi}`);
  assert.ok(['patchAir', 'patchStacked', 'yagi', 'meDipole'].includes(top.arch.id),
    `unexpected top pick: ${top.arch.id}`);

  const omni = recommend({ f: 0.915e9, material: fr4, h: 1.6e-3, sigma: 5.8e7,
    targetGainDbi: 8, pattern: 'omni', polarization: 'linear', bwPct: 2, feedLossDb: 0.3 });
  assert.equal(omni.candidates[0].arch.pattern, 'omni', 'an omni spec must return an omni antenna');

  const radar = recommend({ f: 77e9, material: MATERIAL_BY_ID.ro3003, h: 0.127e-3, sigma: 5.8e7,
    targetGainDbi: 24, pattern: 'directional', polarization: 'linear', bwPct: 5,
    maxDimM: 0.06, feedLossDb: 0.5 });
  assert.ok(radar.candidates[0].realizedGainDbi >= 23.5, 'must find a 24 dBi solution at 77 GHz');

  // circular polarisation must exclude linear-only geometries
  const cp = recommend({ f: 1.575e9, material: fr4, h: 1.6e-3, sigma: 5.8e7,
    targetGainDbi: 4, pattern: 'hemispheric', polarization: 'circular', bwPct: 2, feedLossDb: 0.3 });
  assert.ok(cp.candidates.filter((c) => c.verdict !== 'rejected').every((c) => c.arch.pol.includes('circular')),
    'no linear-only type may be recommended for a circular spec');
});

test('impossible specifications are flagged, not silently accepted', () => {
  const r = recommend({ f: 0.1e9, material: MATERIAL_BY_ID.fr4, h: 1.6e-3, sigma: 5.8e7,
    targetGainDbi: 30, pattern: 'directional', polarization: 'linear',
    bwPct: 2, maxDimM: 0.05, feedLossDb: 0 });
  assert.equal(r.limits.feasible, false, '30 dBi from a 50 mm box at 100 MHz is impossible');
  assert.ok(r.limits.issues.some((i) => i.code === 'harrington'));
});

/* ------------------------------------------------------- full design run */

test('end-to-end design run reproduces the reference trade study', () => {
  const base = {
    f: 2.442e9, materialId: 'fr4', stackMode: 'solid', targetGainDbi: 7,
    pattern: 'directional', polarization: 'linear', bwPct: 3.42,
    groundM: 0.07, maxDimM: 0.12, feedLossDb: 0.4, powerW: 1, feedType: 'inset',
  };
  // Reference realized gains on a 70 x 70 mm ground at ~2.44 GHz
  const solid16 = runDesign({ ...base, h: 1.6e-3 });
  close(solid16.realizedGainDbi, 1.6, 0.8, 'FR-4 1.6 mm realized gain');

  const solid08 = runDesign({ ...base, h: 0.8e-3 });
  close(solid08.realizedGainDbi, -0.6, 0.9, 'FR-4 0.8 mm realized gain');

  const ro = runDesign({ ...base, materialId: 'ro4003c', h: 3.048e-3 });
  close(ro.realizedGainDbi, 5.1, 0.9, 'RO4003C 3.05 mm realized gain');

  const air = runDesign({ ...base, stackMode: 'airgap', carrierH: 0.8e-3, airGap: 4.2e-3 });
  close(air.realizedGainDbi, 7.7, 0.9, 'FR-4 carrier over air realized gain');
  assert.ok(air.realizedGainDbi > solid16.realizedGainDbi + 4,
    'the air-gap build must beat solid FR-4 by more than 4 dB');
  assert.ok(air.sol.etaSpace > 0.95, 'air-gap efficiency');
});

test('every panel dataset builds without throwing across the frequency range', () => {
  for (const fGHz of [0.433, 0.915, 2.442, 5.8, 24.125, 60, 77]) {
    for (const materialId of ['fr4', 'ro4003c', 'rt5880', 'ro3003', 'air']) {
      const D = runDesign({
        f: fGHz * 1e9, materialId, stackMode: 'solid', h: 0.8e-3,
        targetGainDbi: 8, pattern: 'directional', polarization: 'linear',
        bwPct: 3, groundM: null, maxDimM: null, feedLossDb: 0.4, powerW: 1, feedType: 'inset',
      });
      assert.ok(Number.isFinite(D.realizedGainDbi), `${fGHz} GHz / ${materialId}: gain is NaN`);
      assert.ok(Number.isFinite(D.sol.Qt) && D.sol.Qt > 0, `${fGHz} GHz / ${materialId}: bad Q`);
      assert.ok(D.sol.etaSpace > 0 && D.sol.etaSpace <= 1, `${fGHz} GHz / ${materialId}: efficiency out of range`);
      assert.ok(Number.isFinite(D.thermal.tHotC), `${fGHz} GHz / ${materialId}: thermal NaN`);
      assert.ok(D.s11.every((p) => Number.isFinite(p.s11)), 'S11 sweep has NaN');
      assert.ok(D.pattern.E.every((p) => Number.isFinite(p.db)), 'pattern has NaN');
    }
  }
  const sweeps = thicknessSweep({ f: 2.442e9 }, ['fr4', 'ro4003c', 'rt5880', 'ro6010']);
  assert.equal(sweeps.length, 4);
  assert.ok(sweeps.every((s) => s.points.every((p) => Number.isFinite(p.eta))), 'thickness sweep has NaN');
});

test('radiation pattern is continuous and normalised', () => {
  const D = runDesign({
    f: 2.442e9, materialId: 'fr4', stackMode: 'solid', h: 1.6e-3, targetGainDbi: 7,
    pattern: 'directional', polarization: 'linear', bwPct: 3.42, groundM: 0.07,
    feedLossDb: 0.4, powerW: 1, feedType: 'inset',
  });
  for (const cut of [D.pattern.E, D.pattern.H]) {
    const peak = Math.max(...cut.map((p) => p.db));
    close(peak, 0, 1e-6, 'pattern peak is normalised to 0 dB');
    for (let i = 1; i < cut.length; i++) {
      const jump = Math.abs(cut[i].db - cut[i - 1].db);
      assert.ok(jump < 12, `discontinuity of ${jump.toFixed(1)} dB at ${cut[i].deg} deg`);
    }
  }
  const back = D.pattern.E.find((p) => p.deg === 180).db;
  close(back, -D.gnd.frontToBackDb, 0.5, 'back lobe equals the computed F/B');
});
