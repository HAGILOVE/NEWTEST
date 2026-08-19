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
import { toDB, fromDB, clamp } from './constants.js';

/**
 * @param {object} p
 *   lg       ground plane edge length (square) [m]
 *   patchDim largest patch dimension [m]
 *   lambda0  free-space wavelength [m]
 *   swr      surface-wave power ratio P_sw/P_sp from the patch solution
 * @returns gain delta [dB], front-to-back [dB], ripple [dB], back lobe level
 */
export function groundPlaneEffect(p) {
  // Accepts either a square ground ({lg, patchDim}) or a rectangular one
  // ({lgx, lgy, patchL, patchW}); the square form is the rectangular form with
  // both axes equal.
  const lgx = p.lgx ?? p.lg;                       // ground extent along x (E-plane)
  const lgy = p.lgy ?? p.lg;                       // ground extent along y (H-plane)
  const patchL = p.patchL ?? p.patchDim;           // resonant length, along x
  const patchW = p.patchW ?? p.patchDim;           // radiating width, along y
  const { lambda0, swr = 0 } = p;

  // Per-side copper margin beyond the radiator, in each axis.
  //   x: beyond the RADIATING edges     -> shapes the E-plane
  //   y: beyond the non-radiating edges -> shapes the H-plane
  const mx = Math.max((lgx - patchL) / 2, 0) / lambda0;
  const my = Math.max((lgy - patchW) / 2, 0) / lambda0;
  const lxL = lgx / lambda0;
  const lyL = lgy / lambda0;

  // 1. Aperture truncation: below ~0.15 lambda of margin the fringing fields
  //    are clipped and that plane's forward gain collapses.
  const trunc = (m) => -2.9 * Math.exp(-m / 0.145);
  const truncE = trunc(mx);
  const truncH = trunc(my);

  // 2. Edge-diffraction ripple: amplitude ~ 1/sqrt(k*Lg), period lambda/2 in
  //    that axis. The two axes ripple independently, which is exactly why a
  //    rectangular board does not behave like a square one of the same area.
  const rippleOf = (lL) => (1.8 / Math.sqrt(Math.max(2 * Math.PI * lL, 1)))
    * Math.cos(2 * Math.PI * (2 * lL) - Math.PI / 3);
  const rippleE = rippleOf(lxL);
  const rippleH = rippleOf(lyL);

  // 3. Surface-wave power reaching the rim. The wave that leaves through the
  //    x-edges shows up in the E-plane cut and the wave that leaves through the
  //    y-edges in the H-plane cut, so this is split per axis too - each plane
  //    then depends only on its own two edges, as it physically must.
  const lMean = (lxL + lyL) / 2;
  const swOf = (lL) => -Math.abs(toDB(1 / (1 + 0.55 * swr * clamp(lL, 0.3, 3) / 3)) * -1);
  const swE = swOf(lxL);
  const swH = swOf(lyL);

  // Per-plane gain change (each cut sees its own two edges).
  const deltaE = truncE + rippleE + swE;
  const deltaH = truncH + rippleH + swH;

  // Boresight gain is a property of the whole aperture, not of one cut. The
  // radiating-edge margin dominates, because that is where the fringing fields
  // that actually radiate get clipped, so the axes combine 65/35. With both
  // axes equal this reduces to the single-dimension model the tool was
  // originally validated against.
  const W_E = 0.65, W_H = 0.35;
  const deltaGdB = W_E * deltaE + W_H * deltaH;

  // Front-to-back, per plane: ~15 dB at a one-wavelength ground in that axis,
  // +15 dB per decade, degraded by surface-wave spill-over.
  const fbOf = (lL) => clamp(15 + 15 * Math.log10(Math.max(lL, 0.25)) - 20 * swr / (1 + swr), 3, 35);
  const fbE = fbOf(lxL);
  const fbH = fbOf(lyL);
  // One figure for the whole antenna is the power average of the two cuts.
  const fb = -toDB((fromDB(-fbE) + fromDB(-fbH)) / 2);

  // Ground-plane edge current -> co-planar (horizon) radiation lift
  const horizonLiftDb = clamp(-6 + 8 * Math.exp(-Math.min(mx, my) / 0.25), -6, 3);

  return {
    lgx, lgy, aspect: lgx / lgy,
    marginXLambda: mx, marginYLambda: my,
    lgxLambda: lxL, lgyLambda: lyL,
    E: { truncationDb: truncE, rippleDb: rippleE, deltaGdB: deltaE, frontToBackDb: fbE, marginLambda: mx },
    H: { truncationDb: truncH, rippleDb: rippleH, deltaGdB: deltaH, frontToBackDb: fbH, marginLambda: my },
    asymmetryDb: Math.abs(deltaE - deltaH),
    fbAsymmetryDb: Math.abs(fbE - fbH),
    deltaGdB, frontToBackDb: fb, backLobeDb: -fb,
    surfaceWaveEdgeDb: W_E * swE + W_H * swH, horizonLiftDb,
    // legacy single-axis fields, so existing callers keep working unchanged
    marginLambda: Math.min(mx, my), lgLambda: lMean,
    truncationDb: W_E * truncE + W_H * truncH,
    rippleDb: W_E * rippleE + W_H * rippleH,
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

/* ==========================================================================
 * Per-family ground-plane and platform models.
 *
 * "How big should the ground plane be" has a different answer for every
 * antenna family, because the ground does a different job in each:
 *
 *   plane    the ground is the image plane of a broadside radiator. Its size
 *            sets aperture truncation, edge-diffraction ripple and the path
 *            the surface wave takes to the rim.   (patch family, slots, DRA)
 *   radial   the ground is the other half of the antenna. Its radius sets the
 *            elevation tilt of the pattern and the input impedance.
 *                                                  (monopole, whip)
 *   chassis  the ground plane is the main radiator and the element only feeds
 *            it. Gain and bandwidth peak when the chassis is near its own
 *            half-wave resonance.                  (PIFA, IFA, chip antennas)
 *   disc     a backing disc or cup that suppresses the back lobe; useful
 *            beyond about one wavelength.          (axial helix)
 *   height   the antenna needs no ground of its own, so the question becomes
 *            how high above a reflecting surface it is mounted: the image
 *            interferes with the direct ray and produces lobing.
 *                              (dipole, Yagi, LPDA, horn, dish, biconical...)
 * ========================================================================== */

const GROUND_MODE = {
  patch: 'plane', patchAir: 'plane', patchStacked: 'plane',
  patchApertureCoupled: 'plane', patchArray: 'plane', seriesArray: 'plane',
  phasedArray: 'plane', siwSlotArray: 'plane', slotCavity: 'plane',
  meDipole: 'plane', dra: 'plane', quasiYagi: 'plane', hornSiw: 'plane',
  vivaldi: 'plane', reflectarray: 'plane',
  monopole: 'radial',
  pifa: 'chassis', ifa: 'chassis', loopSmall: 'chassis',
  helixAxial: 'disc', qha: 'disc',
  dipole: 'height', biconical: 'height', collinear: 'height', yagi: 'height',
  lpda: 'height', hornPyramidal: 'height', reflector: 'height', lens: 'height',
};

export function groundModeFor(archId) {
  return GROUND_MODE[archId] || 'plane';
}

/**
 * Monopole / whip over a circular ground plane.
 *
 * Peak gain oscillates about the infinite-ground value of 5.15 dBi with a
 * half-wavelength period in the ground radius (the rim diffraction alternately
 * adds and subtracts), while the pattern maximum tilts up off the horizon as
 * the ground shrinks. The tilt fit  theta = 90/(1 + 4a/lambda)  reproduces the
 * published method-of-moments results: 45 deg at a = 0.25 lambda, 30 deg at
 * 0.5 lambda, 18 deg at 1 lambda, 10 deg at 2 lambda.
 */
export function monopoleGround({ radius, lambda0 }) {
  const a = radius / lambda0;
  const tiltDeg = clamp(90 / (1 + 4 * a), 0, 45);
  const truncation = -2.6 * Math.exp(-a / 0.20);
  const ripple = (0.7 * Math.cos(4 * Math.PI * a - 0.6)) / Math.sqrt(1 + 2 * a);
  const peakGainDbi = 5.15 + truncation + ripple;
  // The pattern is the dipole element tilted to `tiltDeg`, so the level at the
  // horizon is the element evaluated `tiltDeg` away from its own maximum.
  const dip = (fromAxisDeg) => {
    const x = (fromAxisDeg * Math.PI) / 180;
    const sn = Math.sin(x);
    return sn < 1e-6 ? 0 : Math.cos((Math.PI / 2) * Math.cos(x)) / sn;
  };
  const horizonRel = toDB(Math.pow(dip(90 - tiltDeg), 2));
  return {
    radiusLambda: a, tiltDeg,
    peakGainDbi, horizonGainDbi: peakGainDbi + clamp(horizonRel, -20, 0),
    truncationDb: truncation, rippleDb: ripple,
    rinScale: clamp(1 - 0.35 * Math.exp(-a / 0.18), 0.6, 1),
  };
}

/**
 * Chassis-coupled small antenna (PIFA, IFA, chip antenna).
 *
 * The element is an impedance matcher; the chassis is the radiator. Efficiency
 * and bandwidth therefore peak when the chassis is near its own half-wave
 * wavemode resonance and fall away either side, with a weaker second peak near
 * one wavelength.
 * Reference: P. Vainikainen et al., "Resonator-based analysis of the
 * combination of mobile handset antenna and chassis", IEEE T-AP 50(10), 2002.
 */
export function chassisGround({ length, lambda0, baseGainDbi = 0 }) {
  const x = length / lambda0;
  const res = (x0, q) => 1 / (1 + Math.pow(q * (x / x0 - x0 / x), 2));
  const r1 = res(0.5, 1.6);          // fundamental chassis wavemode
  const r2 = res(1.0, 3.0);          // second-order, weaker and narrower
  const tooSmall = -4.5 * Math.exp(-x / 0.12);
  const gainDbi = baseGainDbi + 2.8 * r1 + 0.9 * r2 + tooSmall;
  // bandwidth tracks the same resonance - that is the whole point of the model
  const bwFactor = 0.35 + 1.25 * r1 + 0.4 * r2;
  return {
    lengthLambda: x, gainDbi, bandwidthFactor: bwFactor,
    resonanceStrength: r1, secondMode: r2, sizePenaltyDb: tooSmall,
    atResonance: Math.abs(x - 0.5) < 0.08,
  };
}

/**
 * Backing disc or cup behind an end-fire element (axial helix, QHA).
 * Below about 0.6 lambda diameter the disc stops acting as a reflector and the
 * back lobe rises; past ~1.5 lambda there is nothing left to gain.
 */
export function discGround({ diameter, lambda0, baseGainDbi = 12 }) {
  const d = diameter / lambda0;
  const gainDbi = baseGainDbi - 2.6 * Math.exp(-d / 0.42) + 0.35 * Math.min(d, 1.5);
  const fb = clamp(6 + 16 * Math.log10(Math.max(d, 0.2) / 0.3), 3, 28);
  return { diameterLambda: d, gainDbi, frontToBackDb: fb };
}

/**
 * Height above a reflecting surface, for antennas that carry no ground of
 * their own. The image interferes with the direct ray:
 *   horizontal polarisation  F = 2*sin(k*h*sin(theta))   (image inverted)
 *   vertical polarisation    F = 2*cos(k*h*sin(theta))   (image in phase)
 * so a horizontally polarised antenna has a null along the surface and gains
 * up to 6 dB in the first lobe, while a vertical one keeps the 6 dB at the
 * horizon but lobes above it.
 */
export function heightAboveGround({ height, lambda0, baseGainDbi = 8, vertical = false, reflection = 0.9, lowElevDeg = 2 }) {
  const kh = (2 * Math.PI * height) / lambda0;
  const R = clamp(reflection, 0, 1);
  // |1 + Gamma * exp(-j*psi)|^2 with psi = 2*k*h*sin(theta).
  // Horizontal polarisation sees Gamma = -R (inverted image), vertical +R.
  const gainFactor = (elevDeg) => {
    const psi = 2 * kh * Math.sin((elevDeg * Math.PI) / 180);
    return vertical
      ? 1 + R * R + 2 * R * Math.cos(psi)
      : 1 + R * R - 2 * R * Math.cos(psi);
  };
  // first lobe = the lowest-elevation local maximum, which is what a link near
  // the surface actually uses
  let firstLobeDeg = 90, peak = gainFactor(90);
  let prev = gainFactor(0.1), rising = false;
  for (let e = 0.2; e <= 90; e += 0.1) {
    const v = gainFactor(e);
    if (v > prev) rising = true;
    else if (rising) { firstLobeDeg = e - 0.1; peak = prev; break; }
    prev = v;
  }
  if (firstLobeDeg === 90) peak = gainFactor(90);
  const low = gainFactor(lowElevDeg);
  return {
    heightLambda: height / lambda0,
    peakGainDbi: baseGainDbi + toDB(peak),
    lowElevGainDbi: baseGainDbi + toDB(low),
    lowElevDeg,
    firstLobeDeg,
    lobeCount: Math.max(1, Math.round((2 * kh) / Math.PI)),
    groundGainDb: toDB(peak),
  };
}

/**
 * Unified ground/platform response for any archetype.
 *
 * @param archId
 * @param p  { lambda0, baseGainDbi, radiatorDim (m), surfaceWaveRatio,
 *             currentSize (m), vertical, patchDim }
 * @returns a chart-ready sweep plus the recommendation and the mechanism note
 */
export function groundResponse(archId, p) {
  const mode = groundModeFor(archId);
  const lam = p.lambda0;
  const base = p.baseGainDbi ?? 6;
  const pts = [];
  let recommended = null, mechanism = '', xLabel = '', secondaryLabel = '', notes = [];

  if (mode === 'plane') {
    const dim = p.radiatorDim || 0.4 * lam;
    xLabel = 'ground plane edge length';
    secondaryLabel = 'front-to-back ratio [dB]';
    mechanism = 'The ground plane is the image plane of a broadside radiator. Three effects superimpose: aperture truncation when the fringing fields run out of copper, a half-wavelength-periodic ripple from the two diffracting edges, and surface-wave power spilling over the rim.';
    for (let i = 0; i <= 220; i++) {
      const xL = 0.25 + (4.75 * i) / 220;
      const lg = xL * lam;
      if (lg < dim * 1.02) { pts.push({ xLambda: xL, xMm: lg * 1e3, gainDbi: NaN, secondary: NaN }); continue; }
      const r = groundPlaneEffect({ lg, patchDim: dim, lambda0: lam, swr: p.surfaceWaveRatio || 0 });
      pts.push({ xLambda: xL, xMm: lg * 1e3, gainDbi: base + r.deltaGdB, secondary: r.frontToBackDb, detail: r });
    }
    const rec = recommendGroundSize({ patchDim: dim, lambda0: lam, swr: p.surfaceWaveRatio || 0 });
    recommended = { xLambda: rec.lgLambda, xMm: rec.lg * 1e3, gainDbi: base + rec.deltaGdB,
      reason: `smallest square within 0.5 dB of the large-ground asymptote (${(base + (rec.asymptoticDb ?? 0)).toFixed(2)} dBi)` };
    notes = [
      `Allow at least a quarter-wavelength (${(0.25 * lam * 1e3).toFixed(0)} mm) of ground beyond every radiator edge.`,
      'The ripple is real, not numerical: trimming a ground plane moves measured gain up and down with a half-wavelength period.',
      'Splits, stitching gaps and component keep-outs under the radiator act like a smaller ground plane than the board outline suggests.',
    ];
  } else if (mode === 'radial') {
    xLabel = 'ground plane radius';
    secondaryLabel = 'elevation of the pattern peak [deg]';
    mechanism = 'The ground plane is the other half of the antenna - the image of the rod completes the dipole. Its radius sets how far the pattern peak tilts up off the horizon and how much the rim diffraction adds to or subtracts from the peak gain.';
    for (let i = 0; i <= 220; i++) {
      const xL = 0.05 + (2.95 * i) / 220;
      const r = monopoleGround({ radius: xL * lam, lambda0: lam });
      pts.push({ xLambda: xL, xMm: xL * lam * 1e3, gainDbi: r.peakGainDbi, secondary: r.tiltDeg,
        horizonGainDbi: r.horizonGainDbi, detail: r });
    }
    // Recommend the SMALLEST counterpoise that gets within half a decibel of
    // the large-ground horizon gain - the asymptote itself is metres of metal
    // for a fraction of a dB.
    const usable = pts.filter((q) => q.xLambda >= 0.2);
    const bestHorizon = usable.reduce((a, b) => (b.horizonGainDbi > a.horizonGainDbi ? b : a));
    const enough = usable.find((q) => q.horizonGainDbi >= bestHorizon.horizonGainDbi - 0.5) || bestHorizon;
    recommended = { xLambda: enough.xLambda, xMm: enough.xMm, gainDbi: enough.gainDbi,
      reason: `smallest counterpoise within 0.5 dB of the large-ground horizon gain (${enough.horizonGainDbi.toFixed(2)} dBi, beam ${enough.secondary.toFixed(0)}° above the horizon)` };
    notes = [
      'A radial-wire counterpoise of four to eight quarter-wave radials behaves like a solid disc of similar radius and is far lighter.',
      'Small ground planes also raise the input resistance, so a match tuned on a large plane will not hold on a small one.',
      'The tilt matters more than the gain figure: a peak at 30° elevation means very little energy reaches a receiver on the horizon.',
    ];
  } else if (mode === 'chassis') {
    xLabel = 'chassis (ground plane) length';
    secondaryLabel = 'bandwidth relative to the isolated element';
    mechanism = 'For an electrically small element the chassis is the radiator and the element only couples into it. Gain, efficiency and bandwidth therefore peak when the chassis is near its own half-wave wavemode resonance, with a weaker second peak near one wavelength.';
    for (let i = 0; i <= 220; i++) {
      const xL = 0.05 + (1.45 * i) / 220;
      const r = chassisGround({ length: xL * lam, lambda0: lam, baseGainDbi: base });
      pts.push({ xLambda: xL, xMm: xL * lam * 1e3, gainDbi: r.gainDbi, secondary: r.bandwidthFactor, detail: r });
    }
    const best = pts.reduce((a, b) => (b.gainDbi > a.gainDbi ? b : a));
    recommended = { xLambda: best.xLambda, xMm: best.xMm, gainDbi: best.gainDbi,
      reason: `chassis wavemode resonance - bandwidth is ${best.secondary.toFixed(1)}x the isolated element` };
    notes = [
      'This is why the same antenna performs differently in two products: the chassis changed, not the antenna.',
      'Placing the element at a chassis current maximum (a short edge, a corner) couples into the wavemode; placing it mid-edge does not.',
      'A metal battery, shield can or display within about 0.1 lambda detunes and de-tunes the chassis mode as effectively as changing its length.',
    ];
  } else if (mode === 'disc') {
    xLabel = 'backing disc diameter';
    secondaryLabel = 'front-to-back ratio [dB]';
    mechanism = 'The disc behind an end-fire element is a reflector, not an image plane. Below roughly 0.6 wavelength it stops reflecting cleanly and the back lobe rises; past about 1.5 wavelengths there is nothing further to gain.';
    for (let i = 0; i <= 220; i++) {
      const xL = 0.1 + (2.4 * i) / 220;
      const r = discGround({ diameter: xL * lam, lambda0: lam, baseGainDbi: base });
      pts.push({ xLambda: xL, xMm: xL * lam * 1e3, gainDbi: r.gainDbi, secondary: r.frontToBackDb, detail: r });
    }
    const target = pts.find((q) => q.xLambda >= 0.8) || pts[pts.length - 1];
    recommended = { xLambda: target.xLambda, xMm: target.xMm, gainDbi: target.gainDbi,
      reason: 'about one wavelength: past this the curve is flat and the disc is only mass' };
    notes = [
      'A shallow cup (a rim about a quarter-wavelength deep) beats a flat disc of the same diameter for front-to-back.',
      'The disc also sets the feed impedance of an axial helix; changing it means re-tuning the match.',
    ];
  } else {
    xLabel = 'height above the reflecting surface';
    secondaryLabel = 'elevation of the first lobe [deg]';
    const vertical = !!p.vertical;
    mechanism = vertical
      ? 'This antenna carries no ground plane of its own, so the platform question is mounting height. A vertically polarised antenna sees its image in phase, so the horizon keeps the full 6 dB of ground gain while lobes form above it.'
      : 'This antenna carries no ground plane of its own, so the platform question is mounting height. A horizontally polarised antenna sees an inverted image, which cancels along the surface and reinforces in a lobe whose elevation falls as the antenna is raised.';
    for (let i = 0; i <= 220; i++) {
      const xL = 0.05 + (3.95 * i) / 220;
      const r = heightAboveGround({ height: xL * lam, lambda0: lam, baseGainDbi: base, vertical });
      pts.push({ xLambda: xL, xMm: xL * lam * 1e3, gainDbi: r.peakGainDbi, secondary: r.firstLobeDeg,
        lowElevGainDbi: r.lowElevGainDbi, detail: r });
    }
    const quarter = pts.find((q) => q.xLambda >= 0.25) || pts[0];
    recommended = { xLambda: quarter.xLambda, xMm: quarter.xMm, gainDbi: quarter.gainDbi,
      reason: vertical
        ? 'a quarter wave clears the surface without splitting the elevation pattern'
        : `a quarter wave puts the first lobe at ${quarter.secondary.toFixed(0)}° - raise it further to lower the lobe toward the horizon` };
    notes = [
      'Real ground is not a perfect mirror: soil reflects roughly 0.3-0.7 in amplitude, so the lobing is shallower and the peak gain lower than the ideal 6 dB.',
      vertical
        ? 'Vertical polarisation over ground suffers the Brewster-angle loss at low elevation; the 6 dB figure is optimistic below a few degrees.'
        : 'For a horizontally polarised link near the surface, height is not optional - at low height the direct and reflected rays cancel almost completely.',
      'A metal roof, vehicle skin or test-range floor all count as the reflecting surface.',
    ];
  }

  // Snap the "current size" marker to the nearest point the model can actually
  // evaluate. In plane mode the sweep is undefined below the radiator size, so
  // a ground plane smaller than the antenna itself has no gain figure - that is
  // reported as a fit problem rather than as a number.
  const valid = pts.filter((q) => Number.isFinite(q.gainDbi));
  let cur = null, currentFits = true;
  if (p.currentSize && valid.length) {
    const targetMm = p.currentSize * 1e3;
    cur = valid.reduce((a, b) => (Math.abs(b.xMm - targetMm) < Math.abs(a.xMm - targetMm) ? b : a));
    currentFits = !(mode === 'plane' && targetMm < valid[0].xMm - 1e-6);
    if (!currentFits) cur = null;
  }

  return {
    mode, xLabel, secondaryLabel, points: pts, current: cur, currentFits,
    minimumMm: valid.length ? valid[0].xMm : null,
    recommended, mechanism, notes, lambda0: lam,
  };
}
