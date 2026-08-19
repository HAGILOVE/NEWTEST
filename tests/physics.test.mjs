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
import { groundPlaneEffect, groundModeFor, groundResponse, monopoleGround,
         chassisGround, heightAboveGround, discGround } from '../src/core/ground.js';
import { chuQ, harringtonDirectivity, maxFractionalBandwidth } from '../src/core/limits.js';
import { fspl, gaseousAttenuation, rainAttenuation, noiseFloorDbm, linkBudget } from '../src/core/propagation.js';
import { solveThermal, paschenVoltage, frequencyDrift } from '../src/core/thermal.js';
import { monteCarlo } from '../src/core/tolerance.js';
import { recommend, boardCapability } from '../src/core/recommend.js';
import { runDesign, thicknessSweep } from '../src/core/design.js';
import { patternFor, responseVsFrequency, besselJ1 } from '../src/core/patterns.js';

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

/* -------------------------------------------------------------- patterns */

test('Bessel J1 matches reference values', () => {
  close(besselJ1(0), 0, 1e-7);
  close(besselJ1(1), 0.4400505857, 1e-7);
  close(besselJ1(3.831705970), 0, 1e-6, 'first zero');
  close(besselJ1(10), 0.0434727462, 1e-6);
});

test('per-family patterns reproduce textbook beamwidths and sidelobes', () => {
  const cases = [
    // id, params, expected HPBW (E-plane), tolerance, expected first sidelobe, tol
    ['dipole', { D0: 1.64 }, 78, 3, null, null],
    ['loopSmall', { D0: 1.5 }, 90, 4, null, null],
    // uniform linear array of 6 at 0.525 lambda: HPBW ~17 deg, SLL -13.2 dB
    ['collinear', { D0: 12, count: 6 }, 18, 3, -13.2, 2],
    // Pyramidal horn, 100 x 66 mm aperture at 30 mm: E-plane HPBW 51*l/b = 23 deg,
    // H-plane 70*l/a = 21 deg. The ideal uniform line source gives a -13.2 dB
    // first sidelobe; the obliquity factor of an aperture radiating into a half
    // space pushes the modelled value to -14..-16 dB, which is what real horns
    // actually measure.
    ['hornPyramidal', { D0: 50, dims: { 'Aperture a': 100, 'Aperture b': 66 }, lambda0: 0.03, fbDb: 30 }, 23, 3, -14.8, 2.2],
    // 300 mm dish at 30 mm: HPBW = 70*l/D = 7 deg, parabolic taper SLL ~ -24 dB
    ['reflector', { D0: 1000, dims: { 'Dish diameter': 300 }, lambda0: 0.03, fbDb: 32 }, 7, 2, -24, 2.5],
    // 4 x 4 patch array at 0.7 lambda with a cosine taper: SLL around -20 dB
    ['patchArray', { D0: 60, count: 16 }, 22, 4, -21, 4],
  ];
  for (const [id, p, bw, bwTol, sll, sllTol] of cases) {
    const r = patternFor(id, p);
    close(r.meta.hpbwE, bw, bwTol, `${id} HPBW`);
    if (sll !== null) close(r.meta.sllE, sll, sllTol, `${id} first sidelobe`);
    assert.ok(r.E.length === 361 && r.H.length === 361, `${id}: cuts must cover -180..180`);
    close(Math.max(...r.E.map((q) => q.db)), 0, 1e-9, `${id}: peak normalised`);
  }
});

test('every archetype produces a finite, continuous pattern', () => {
  const D = runDesign({
    f: 2.442e9, materialId: 'fr4', stackMode: 'solid', h: 1.6e-3, targetGainDbi: 7,
    pattern: 'directional', polarization: 'linear', bwPct: 3.42, groundM: 0.07,
    feedLossDb: 0.4, powerW: 1, feedType: 'inset',
  });
  for (const c of D.recommendation.candidates) {
    if (c.verdict === 'error') continue;
    const r = patternFor(c.arch.id, {
      D0: Math.pow(10, c.gainDbi / 10) / Math.max(c.efficiency, 1e-3),
      gainDbi: c.gainDbi, count: c.count, lambda0: D.lambda0, dims: c.dims,
      patch: c.patch ? { Le: c.patch.Le, W: c.patch.W, h: D.stack.h } : null,
    });
    for (const [name, cut] of [['E', r.E], ['H', r.H]]) {
      assert.ok(cut.every((q) => Number.isFinite(q.db)), `${c.arch.id} ${name}: NaN in the cut`);
      for (let i = 1; i < cut.length; i++) {
        assert.ok(Math.abs(cut[i].db - cut[i - 1].db) < 30,
          `${c.arch.id} ${name}: ${Math.abs(cut[i].db - cut[i - 1].db).toFixed(0)} dB jump at ${cut[i].deg} deg`);
      }
    }
    assert.ok(r.meta.hpbwE > 0, `${c.arch.id}: zero beamwidth`);
    const resp = responseVsFrequency(c.arch.id, { f0: D.spec.f, bwPct: c.bwPct, gainDbi: c.realizedGainDbi });
    assert.ok(resp.every((q) => Number.isFinite(q.gain) && Number.isFinite(q.vswr) && q.vswr >= 1),
      `${c.arch.id}: bad frequency response`);
  }
});

test('a steered phased array moves, broadens and pulls toward broadside', () => {
  const at = (deg) => {
    const r = patternFor('phasedArray', { D0: 60, count: 16, scanDeg: deg });
    const peak = r.E.reduce((a, b) => (b.db > a.db ? b : a));
    return { peak: peak.deg, bw: r.meta.hpbwE };
  };
  const b0 = at(0), b25 = at(25), b45 = at(45);
  close(b0.peak, 0, 2, 'unscanned beam points at boresight');
  assert.ok(b25.peak > 5 && b45.peak > b25.peak, `beam follows the command: ${b25.peak} then ${b45.peak}`);
  // The element pattern multiplies the array factor, so the realised peak sits
  // a few degrees inside the commanded angle - real beam pulling, not an error.
  assert.ok(b45.peak > 0.7 * 45 && b45.peak <= 45 + 2,
    `pulled toward broadside but still near the command: ${b45.peak} deg for a 45 deg command`);
  // The array factor broadens as 1/cos(theta), but the element pattern
  // attenuates the outer flank more than the inner one, so the realised
  // broadening is less than the textbook 1/cos figure.
  assert.ok(b45.bw > b0.bw, `beam must broaden when scanned: ${b0.bw} -> ${b45.bw}`);
});

/* --------------------------------------------- per-family ground models */

test('every archetype is routed to a ground model that matches its physics', () => {
  const expected = {
    patch: 'plane', patchArray: 'plane', slotCavity: 'plane', dra: 'plane',
    monopole: 'radial', pifa: 'chassis', ifa: 'chassis',
    helixAxial: 'disc', dipole: 'height', yagi: 'height', reflector: 'height',
  };
  for (const [id, mode] of Object.entries(expected)) {
    assert.equal(groundModeFor(id), mode, `${id} should use the ${mode} model`);
  }
});

test('monopole over a circular ground: tilt and gain follow the published curve', () => {
  const lam = 0.1228;
  // Pattern-peak elevation from method-of-moments studies: 45 deg at a = 0.25
  // lambda, 30 at 0.5, 18 at 1, 10 at 2.
  for (const [a, tilt] of [[0.25, 45], [0.5, 30], [1, 18], [2, 10]]) {
    close(monopoleGround({ radius: a * lam, lambda0: lam }).tiltDeg, tilt, 1.5, `tilt at a = ${a} lambda`);
  }
  const big = monopoleGround({ radius: 3 * lam, lambda0: lam });
  close(big.peakGainDbi, 5.15, 0.6, 'large ground approaches the infinite-ground 5.15 dBi');
  // A small counterpoise costs gain and pushes the beam off the horizon
  const small = monopoleGround({ radius: 0.15 * lam, lambda0: lam });
  assert.ok(small.peakGainDbi < big.peakGainDbi, 'small ground loses peak gain');
  assert.ok(small.horizonGainDbi < small.peakGainDbi - 2,
    `a tilted beam must cost gain at the horizon: peak ${small.peakGainDbi.toFixed(2)}, horizon ${small.horizonGainDbi.toFixed(2)}`);
  assert.ok(big.horizonGainDbi > big.peakGainDbi - 0.5, 'a large ground puts the beam back on the horizon');
});

test('chassis-coupled antennas peak at the half-wave chassis resonance', () => {
  const lam = 0.3279;   // 915 MHz
  const at = (x) => chassisGround({ length: x * lam, lambda0: lam, baseGainDbi: 0 });
  const half = at(0.5), quarter = at(0.25), tiny = at(0.08), full = at(1.0);
  assert.ok(half.gainDbi > quarter.gainDbi, 'half-wave chassis beats a quarter-wave one');
  assert.ok(half.gainDbi > tiny.gainDbi + 3, 'a tiny chassis is far worse');
  assert.ok(half.bandwidthFactor > quarter.bandwidthFactor,
    'bandwidth follows the same resonance as gain - that is the point of the model');
  assert.ok(full.gainDbi > at(0.8).gainDbi, 'a weaker second peak exists near one wavelength');
  assert.ok(half.atResonance && !quarter.atResonance);
});

test('two-ray height model reproduces the classic ground-gain figures', () => {
  const lam = 0.1228;
  // A horizontal dipole a quarter wave above a perfect ground gains 6 dB
  const q = heightAboveGround({ height: 0.25 * lam, lambda0: lam, baseGainDbi: 2.15, reflection: 1 });
  close(q.peakGainDbi, 2.15 + 6.02, 0.15, 'lambda/4 high, perfect ground');
  close(q.groundGainDb, 6.02, 0.15, 'ground gain');
  // The first lobe sits at asin(lambda / 4h)
  for (const h of [0.5, 1, 2, 3]) {
    const r = heightAboveGround({ height: h * lam, lambda0: lam, baseGainDbi: 0, reflection: 1 });
    close(r.firstLobeDeg, (Math.asin(0.25 / h) * 180) / Math.PI, 0.6, `first lobe at h = ${h} lambda`);
  }
  // Horizontal polarisation nulls along the surface; vertical does not
  const hp = heightAboveGround({ height: lam, lambda0: lam, baseGainDbi: 0, reflection: 1, lowElevDeg: 0.5 });
  const vp = heightAboveGround({ height: lam, lambda0: lam, baseGainDbi: 0, reflection: 1, vertical: true, lowElevDeg: 0.5 });
  assert.ok(hp.lowElevGainDbi < -15, `horizontal pol must null at the surface: ${hp.lowElevGainDbi.toFixed(1)} dB`);
  close(vp.lowElevGainDbi, 6.02, 0.3, 'vertical pol keeps the full ground gain at the horizon');
});

test('groundResponse produces a usable sweep for every archetype', () => {
  const D = runDesign({
    f: 2.442e9, materialId: 'fr4', stackMode: 'solid', h: 1.6e-3, targetGainDbi: 7,
    pattern: 'directional', polarization: 'linear', bwPct: 3.42, groundM: 0.07,
    feedLossDb: 0.4, powerW: 1, feedType: 'inset',
  });
  for (const c of D.recommendation.candidates) {
    if (c.verdict === 'error') continue;
    const gr = groundResponse(c.arch.id, {
      lambda0: D.lambda0, baseGainDbi: c.gainDbi,
      radiatorDim: Math.max(c.size.w, c.size.l) / 1e3,
      surfaceWaveRatio: c.patch ? c.patch.surfaceWaveRatio : 0,
      currentSize: D.groundM,
    });
    const valid = gr.points.filter((q) => Number.isFinite(q.gainDbi));
    assert.ok(valid.length > 20, `${c.arch.id}: sweep is too short (${valid.length} points)`);
    assert.ok(valid.every((q) => Number.isFinite(q.secondary)), `${c.arch.id}: NaN in the secondary metric`);
    assert.ok(Number.isFinite(gr.recommended.gainDbi) && Number.isFinite(gr.recommended.xMm),
      `${c.arch.id}: no usable recommendation`);
    assert.ok(gr.mechanism.length > 40 && gr.notes.length >= 2, `${c.arch.id}: missing explanation`);
    // the curve has to be smooth enough to plot
    for (let i = 1; i < valid.length; i++) {
      assert.ok(Math.abs(valid[i].gainDbi - valid[i - 1].gainDbi) < 4,
        `${c.arch.id}: ${Math.abs(valid[i].gainDbi - valid[i - 1].gainDbi).toFixed(1)} dB step at ${valid[i].xLambda.toFixed(2)} lambda`);
    }
  }
});

test('a ground plane smaller than the radiator is reported, not silently zeroed', () => {
  const gr = groundResponse('patchArray', {
    lambda0: 0.1228, baseGainDbi: 14, radiatorDim: 0.25, currentSize: 0.07,
  });
  assert.equal(gr.currentFits, false, 'a 70 mm ground cannot hold a 250 mm array');
  assert.equal(gr.current, null, 'no gain figure is offered for a size the model cannot evaluate');
  assert.ok(gr.minimumMm > 250, `minimum reported size should exceed the radiator: ${gr.minimumMm}`);
});

/* ----------------------------------------- rectangular ground plane */

test('a square ground reduces exactly to the previously validated model', () => {
  const lam = 0.1228, dim = 0.0379;
  const legacy = groundPlaneEffect({ lg: 0.070, patchDim: dim, lambda0: lam, swr: 0.09 });
  close(legacy.deltaGdB, -0.280, 0.01, 'legacy single-dimension call is unchanged');
  close(legacy.frontToBackDb, 9.69, 0.05, 'legacy front-to-back is unchanged');
  // and the two planes of a square ground with a square radiator agree
  const sq = groundPlaneEffect({ lgx: 0.070, lgy: 0.070, patchL: dim, patchW: dim, lambda0: lam, swr: 0.09 });
  close(sq.E.deltaGdB, sq.H.deltaGdB, 1e-9, 'square ground, square radiator: both planes identical');
  close(sq.deltaGdB, legacy.deltaGdB, 1e-9, 'and it matches the legacy result exactly');
  close(sq.E.frontToBackDb, sq.H.frontToBackDb, 1e-9);
});

test('each principal plane answers to its own axis', () => {
  const lam = 0.1228, L = 0.0294, W = 0.0379;
  const base = { patchL: L, patchW: W, lambda0: lam, swr: 0.09 };
  // Growing X must move the E-plane and leave the H-plane alone, and vice versa
  const a = groundPlaneEffect({ ...base, lgx: 0.060, lgy: 0.090 });
  const bx = groundPlaneEffect({ ...base, lgx: 0.140, lgy: 0.090 });
  const by = groundPlaneEffect({ ...base, lgx: 0.060, lgy: 0.170 });
  close(a.H.deltaGdB, bx.H.deltaGdB, 1e-9, 'changing X must not touch the H-plane');
  close(a.H.frontToBackDb, bx.H.frontToBackDb, 1e-9, 'nor its front-to-back');
  close(a.E.deltaGdB, by.E.deltaGdB, 1e-9, 'changing Y must not touch the E-plane');
  assert.ok(bx.E.deltaGdB > a.E.deltaGdB, 'a bigger X improves the E-plane');
  assert.ok(by.H.frontToBackDb > a.H.frontToBackDb, 'a bigger Y improves the H-plane front-to-back');
});

test('margins are measured against the right patch dimension', () => {
  const lam = 0.1228, L = 0.0294, W = 0.0379;
  const r = groundPlaneEffect({ lgx: 0.100, lgy: 0.080, patchL: L, patchW: W, lambda0: lam });
  close(r.marginXLambda, ((0.100 - L) / 2) / lam, 1e-9, 'X margin runs past the RADIATING edges (length L)');
  close(r.marginYLambda, ((0.080 - W) / 2) / lam, 1e-9, 'Y margin runs past the side edges (width W)');
  // a radiator larger than its axis clamps the margin at zero rather than going negative
  const tight = groundPlaneEffect({ lgx: 0.020, lgy: 0.080, patchL: L, patchW: W, lambda0: lam });
  assert.equal(tight.marginXLambda, 0, 'a negative margin clamps to zero');
});

test('board orientation matters, and the tool computes by how much', () => {
  const lam = 0.1228, L = 0.0294, W = 0.0379;
  const p = { patchL: L, patchW: W, lambda0: lam, swr: 0.09 };
  const tall = groundPlaneEffect({ ...p, lgx: 0.040, lgy: 0.122 });
  const wide = groundPlaneEffect({ ...p, lgx: 0.122, lgy: 0.040 });
  // Same board outline, antenna turned 90 degrees - and it is NOT the same answer
  assert.ok(Math.abs(tall.deltaGdB - wide.deltaGdB) > 0.5,
    `orientation must change the result: ${tall.deltaGdB.toFixed(2)} vs ${wide.deltaGdB.toFixed(2)} dB`);
  assert.ok(wide.deltaGdB > tall.deltaGdB,
    'the orientation that puts the long axis beyond the radiating edges wins');
  assert.ok(tall.asymmetryDb > 2 && wide.asymmetryDb > 2, 'a 3:1 board is strongly asymmetric');
  // the E-plane of one is the H-plane geometry of the other
  close(wide.E.frontToBackDb, tall.H.frontToBackDb, 1e-9);
});

test('the design run carries X and Y end to end', () => {
  const spec = {
    f: 2.442e9, materialId: 'fr4', stackMode: 'solid', h: 1.6e-3, targetGainDbi: 7,
    pattern: 'directional', polarization: 'linear', bwPct: 3.42,
    feedLossDb: 0.4, powerW: 1, feedType: 'inset',
  };
  const a = runDesign({ ...spec, groundXM: 0.110, groundYM: 0.070 });
  const b = runDesign({ ...spec, groundXM: 0.070, groundYM: 0.110 });
  close(a.groundXM, 0.110, 1e-12);
  close(a.groundYM, 0.070, 1e-12);
  assert.ok(Math.abs(a.realizedGainDbi - b.realizedGainDbi) > 0.1,
    'the two orientations of one board give different realized gain');
  // thermal area must follow the real rectangle, not a square
  const area = 0.110 * 0.070;
  assert.ok(a.thermal.rTotalKperW > 0 && Number.isFinite(a.thermal.rTotalKperW));
  const square = runDesign({ ...spec, groundM: Math.sqrt(area) });
  assert.ok(Math.abs(a.thermal.rTotalKperW - square.thermal.rTotalKperW) / square.thermal.rTotalKperW < 0.05,
    'equal-area boards dissipate about the same, whatever their aspect');
  // a square spec still works through the legacy field
  const legacy = runDesign({ ...spec, groundM: 0.070 });
  close(legacy.groundXM, 0.070, 1e-12);
  close(legacy.groundYM, 0.070, 1e-12);
});

// ---------------------------------------------------------------------------
// What a given board can actually do
// ---------------------------------------------------------------------------

const capSpec = (over = {}) => ({
  f: 2.442e9, material: MATERIAL_BY_ID.fr4, sigma: 5.8e7, h: 1.6e-3,
  pattern: 'directional', polarization: 'linear', bwPct: 3,
  feedLossDb: 0.4, powerW: 1, feedType: 'inset', ...over,
});

test('board capability rises monotonically with board size', () => {
  const edges = [0.03, 0.05, 0.07, 0.12, 0.20, 0.30];
  let prev = -Infinity;
  for (const e of edges) {
    const cap = boardCapability(capSpec({ groundXM: e, groundYM: e }));
    assert.ok(cap && cap.best, `${e * 1e3} mm board must support something`);
    assert.ok(cap.best.gainDbi > prev - 0.01,
      `a bigger board cannot do worse: ${e * 1e3} mm -> ${cap.best.gainDbi.toFixed(1)} dBi after ${prev.toFixed(1)}`);
    prev = cap.best.gainDbi;
  }
});

test('nothing on any board beats the Harrington bound', () => {
  for (const e of [0.02, 0.04, 0.07, 0.15, 0.30, 0.60]) {
    const cap = boardCapability(capSpec({ groundXM: e, groundYM: e }));
    for (const row of cap.perArch) {
      // Each candidate is held to the sphere that encloses IT - board outline
      // plus its own height, which is how a mast legitimately out-gains a
      // board-outline bound without breaking physics.
      assert.ok(row.gainDbi <= row.boundDbi + 1e-6,
        `${row.arch.name} claims ${row.gainDbi.toFixed(1)} dBi on a ${e * 1e3} mm board, `
        + `over its ${row.boundDbi.toFixed(1)} dBi bound`);
      const flat = row.sizeMm.h / 1e3 <= 0.02;
      if (flat) {
        assert.ok(row.gainDbi <= cap.boardCeilingDbi + 1e-6,
          `${row.arch.name} is flat, so the board-outline bound applies to it`);
      }
    }
    if (cap.best) assert.ok(cap.realisableFraction > 0 && cap.realisableFraction <= 1);
  }
});

test('every capability candidate physically fits the board it was found on', () => {
  const bx = 0.09, by = 0.045;
  const cap = boardCapability(capSpec({ groundXM: bx, groundYM: by }));
  assert.ok(cap.perArch.length > 0);
  for (const row of cap.perArch) {
    const w = row.sizeMm.w / 1e3, l = row.sizeMm.l / 1e3;
    const fits = (w <= bx + 1e-9 && l <= by + 1e-9) || (w <= by + 1e-9 && l <= bx + 1e-9);
    assert.ok(fits, `${row.arch.name} is ${row.sizeMm.w.toFixed(1)}x${row.sizeMm.l.toFixed(1)} mm `
      + `on a ${bx * 1e3}x${by * 1e3} mm board`);
    assert.ok(row.footprintUse > 0 && row.footprintUse <= 1.001);
  }
});

test('the ceilings follow the textbook aperture and sphere formulas', () => {
  const f = 5.8e9, lam = C0 / f;
  const bx = 0.100, by = 0.080;
  const cap = boardCapability(capSpec({ f, groundXM: bx, groundYM: by }));
  close(cap.areaM2, bx * by, 1e-12);
  close(cap.areaLambdaSq, (bx * by) / (lam * lam), 1e-9);
  // 4*pi*A*eta / lambda^2 at 65 % aperture efficiency
  const apExpect = 10 * Math.log10((4 * Math.PI * bx * by * 0.65) / (lam * lam));
  close(cap.apertureCeilingDbi, apExpect, 1e-6);
  // Harrington on the enclosing sphere, derated 1 dB for a real radiator
  const ka = (2 * Math.PI / lam) * (Math.hypot(bx, by) / 2);
  const dExpect = 10 * Math.log10((ka * ka + 2 * ka) * 0.8);
  close(cap.harringtonDbi, dExpect, 1e-6);
  close(cap.ceilingDbi, cap.harringtonDbi, 1e-12);
  assert.equal(cap.apertureLimited, true, 'a board several wavelengths across is aperture limited');
});

test('board capability honours the pattern and envelope the user asked for', () => {
  const board = { groundXM: 0.15, groundYM: 0.15 };
  // The headline answer must be an antenna that makes the requested pattern -
  // never a fallback of the wrong kind, however much gain it has.
  for (const pattern of ['directional', 'omni', 'hemispheric']) {
    const cap = boardCapability(capSpec({ ...board, pattern }));
    assert.ok(cap.best.patternMatch >= 0.5,
      `${pattern}: ${cap.best.arch.name} is a ${cap.best.arch.pattern} type`);
  }
  // a height limit must exclude the tall antennas that would otherwise win
  const free = boardCapability(capSpec({ ...board }));
  const flat = boardCapability(capSpec({ ...board, maxDimM: 0.006, lowProfile: true }));
  assert.ok(flat.best.gainDbi <= free.best.gainDbi,
    'a 6 mm envelope cannot beat an unconstrained one');
  for (const row of flat.perArch) {
    assert.ok(row.sizeMm.h / 1e3 <= 0.006 + 1e-9,
      `${row.arch.name} is ${row.sizeMm.h.toFixed(1)} mm tall inside a 6 mm envelope`);
  }
  // The ceiling follows the sphere the user allowed: board outline, plus the
  // height budget when one is set. Height can only enlarge that sphere.
  assert.ok(Number.isFinite(flat.envelopeCeilingDbi));
  assert.ok(flat.envelopeCeilingDbi >= flat.boardCeilingDbi - 1e-9);
  close(flat.ceilingDbi, flat.envelopeCeilingDbi, 1e-12);
  assert.equal(free.envelopeCeilingDbi, null, 'no envelope set, no envelope ceiling');
  close(free.ceilingDbi, free.boardCeilingDbi, 1e-12);
});

test('a model that returns NaN is treated as broken, not as a candidate', () => {
  // sigma missing used to make the array feed-loss model produce NaN, which
  // then poisoned the ranking sort. Both halves are now guarded.
  const cap = boardCapability({ ...capSpec({ groundXM: 0.3, groundYM: 0.3 }), sigma: undefined });
  for (const row of cap.perArch) {
    assert.ok(Number.isFinite(row.gainDbi), `${row.arch.name} produced ${row.gainDbi}`);
  }
  for (let i = 1; i < cap.perArch.length; i++) {
    assert.ok(cap.perArch[i - 1].gainDbi >= cap.perArch[i].gainDbi, 'the ranking is actually sorted');
  }
  // a spec given only a material id still resolves to a real dielectric
  const byId = boardCapability({ ...capSpec({ groundXM: 0.07, groundYM: 0.07 }), material: undefined, materialId: 'fr4' });
  assert.ok(byId.best && Number.isFinite(byId.best.gainDbi));
});

test('board capability needs a board and reports the winner it names', () => {
  assert.equal(boardCapability(capSpec({})), null, 'no board, no answer');
  const cap = boardCapability(capSpec({ groundM: 0.07 }));
  close(cap.boardXM, 0.07, 1e-12);
  close(cap.boardYM, 0.07, 1e-12);
  assert.ok(cap.best.arch && cap.best.arch.name, 'the winner is a named archetype');
  assert.ok(cap.perArch[0].gainDbi >= cap.best.gainDbi,
    'the pattern-matched winner never beats the outright winner');
  assert.ok(cap.bestAnyPattern.gainDbi >= cap.best.gainDbi);
});
