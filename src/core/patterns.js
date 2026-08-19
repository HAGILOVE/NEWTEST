/**
 * Radiation-pattern engine.
 *
 * Every antenna family radiates differently, so a single model cannot draw them
 * all. This module gives each family its own analytic far field:
 *
 *   broadside   cavity model (patch) or cos^2q(theta) fitted to the directivity
 *   endfire     ordinary-endfire array factor (Yagi) or cos^2n(theta/2)
 *   aperture    rectangular horn (uniform E / cosine H) or circular Airy
 *   array       element pattern x array factor with the real element count,
 *               spacing and amplitude taper - so sidelobes and grating lobes
 *               are computed rather than drawn in
 *   omni        thin-dipole pattern, small-loop sin(theta), or a torus
 *   hemispheric cardioid family
 *
 * Cuts are returned with 0 deg at the main beam, which is how antenna
 * datasheets plot them: for a broadside antenna that is the normal to the
 * board, for an endfire antenna the axis, and for an omni antenna the horizon.
 *
 * Every cut also reports the quantities a reviewer asks for - half-power
 * beamwidth, first-sidelobe level and front-to-back ratio - measured off the
 * computed pattern rather than estimated from a formula.
 */
import { toDB, fromDB, clamp, sinc } from './constants.js';
import { besselJ0, patchFieldSq } from './patch.js';

const DEG = Math.PI / 180;

/** Bessel J1 (Abramowitz & Stegun 9.4.4 / 9.4.6). */
export function besselJ1(x) {
  const ax = Math.abs(x);
  let ans;
  if (ax < 8) {
    const y = x * x;
    const a1 = x * (72362614232.0 + y * (-7895059235.0 + y * (242396853.1 +
               y * (-2972611.439 + y * (15704.48260 + y * -30.16036606)))));
    const a2 = 144725228442.0 + y * (2300535178.0 + y * (18583304.74 +
               y * (99447.43394 + y * (376.9991397 + y * 1.0))));
    ans = a1 / a2;
  } else {
    const z = 8 / ax, y = z * z, xx = ax - 2.356194491;
    const p1 = 1 + y * (0.183105e-2 + y * (-0.3516396496e-4 + y * (0.2457520174e-5 + y * -0.240337019e-6)));
    const p2 = 0.04687499995 + y * (-0.2002690873e-3 + y * (0.8449199096e-5 + y * (-0.88228987e-6 + y * 0.105787412e-6)));
    ans = Math.sqrt(0.636619772 / ax) * (Math.cos(xx) * p1 - z * Math.sin(xx) * p2);
    if (x < 0) ans = -ans;
  }
  return ans;
}

/** Normalised circular-aperture factor with a (1-r^2)^p illumination taper. */
function circularAperture(u, p = 0) {
  if (Math.abs(u) < 1e-9) return 1;
  if (p === 0) return (2 * besselJ1(u)) / u;                 // uniform, SLL -17.6 dB
  // p = 1 parabolic taper: 8*J2(u)/u^2, with J2 = 2*J1/u - J0
  const j2 = (2 * besselJ1(u)) / u - besselJ0(u);
  return (8 * j2) / (u * u);
}

/** Uniform rectangular-aperture factor (E-plane of a horn): sinc. */
const uniformAperture = (X) => sinc(X);

/** Cosine-tapered aperture factor (H-plane of a horn): SLL -23 dB. */
function cosineAperture(X) {
  const d = 1 - Math.pow((2 * X) / Math.PI, 2);
  if (Math.abs(d) < 1e-6) return Math.PI / 4;
  return Math.cos(X) / d;
}

/** Uniform / tapered linear array factor, N elements, spacing d (in lambda). */
function arrayFactor(theta, n, dLambda, taper = 'uniform', scanDeg = 0) {
  if (n <= 1) return 1;
  const psi = 2 * Math.PI * dLambda * (Math.sin(theta) - Math.sin(scanDeg * DEG));
  const a = [];
  for (let i = 0; i < n; i++) {
    if (taper === 'cosine') a.push(0.3 + 0.7 * Math.sin((Math.PI * (i + 0.5)) / n));
    else if (taper === 'binomial') a.push(Math.exp(-4 * Math.pow((i + 0.5) / n - 0.5, 2)));
    else a.push(1);
  }
  const norm = a.reduce((x, y) => x + y, 0);
  let re = 0, im = 0;
  for (let i = 0; i < n; i++) {
    const ph = (i - (n - 1) / 2) * psi;
    re += a[i] * Math.cos(ph);
    im += a[i] * Math.sin(ph);
  }
  return Math.sqrt(re * re + im * im) / norm;
}

/** Ordinary end-fire array factor (used for Yagi-class antennas). */
function endfireAF(theta, n, dLambda) {
  if (n <= 1) return 1;
  const beta = -2 * Math.PI * dLambda;
  const psi = 2 * Math.PI * dLambda * Math.cos(theta) + beta;
  const den = n * Math.sin(psi / 2);
  if (Math.abs(den) < 1e-9) return 1;
  return Math.abs(Math.sin((n * psi) / 2) / den);
}

/** Thin half-wave dipole element factor; theta measured from the wire axis. */
function dipoleElement(thetaFromAxis) {
  const s = Math.sin(thetaFromAxis);
  if (Math.abs(s) < 1e-6) return 0;
  return Math.cos((Math.PI / 2) * Math.cos(thetaFromAxis)) / s;
}

/** cos^q broadside element fitted so the pattern integrates to D0. */
function cosQ(theta, q) {
  const c = Math.cos(theta);
  return c <= 0 ? 0 : Math.pow(c, q);
}

/**
 * Build the two principal cuts for an archetype.
 *
 * @param id     archetype id
 * @param p      { D0, gainDbi, count, lambda0, dims, patch, sizeMm, fbDb, scanDeg }
 * @returns { E, H, meta } where E/H are [{deg, db}] with 0 dB at the peak
 */
export function patternFor(id, p) {
  const D0 = Math.max(p.D0 || fromDB(p.gainDbi || 6), 1.05);
  const fb = p.fbDb ?? defaultFrontToBack(id);
  // A true omnidirectional antenna has no "back" to speak of, so it gets no
  // diffraction floor - adding one would flatten the nulls that define it.
  const floor = fb > 0.5 ? fromDB(-fb) : 0;
  const n = p.count || 1;

  let fE, fH, frame, note;

  switch (id) {
    /* ---------------------------------------------------- patch family */
    case 'patch': case 'patchAir': case 'patchStacked': case 'patchApertureCoupled': {
      if (p.patch && p.lambda0) {
        const k0 = (2 * Math.PI) / p.lambda0;
        const { Le, W } = p.patch;
        const hh = p.patch.h || 1e-3;
        const u0 = patchFieldSq(1e-6, 0, k0, Le, W, hh).u;
        // same finite-ground horizon taper the patch panel uses, so both views
        // of the same antenna report the same beamwidth
        const horizon = fromDB(-(0.55 * fb + 1.5));
        const taper = (t) => horizon + (1 - horizon) * Math.pow(Math.cos(Math.min(Math.abs(t), Math.PI / 2)), 2);
        const cut = (phiPos, phiNeg) => (t) =>
          (patchFieldSq(Math.min(Math.abs(t), Math.PI / 2 - 1e-6), t >= 0 ? phiPos : phiNeg, k0, Le, W, hh).u / u0) * taper(t);
        fE = cut(0, Math.PI);
        fH = cut(Math.PI / 2, -Math.PI / 2);
        note = 'Cavity-model two-slot far field with the finite-ground horizon taper.';
      } else {
        const q = clamp((D0 - 2) / 4, 0.5, 8);
        fE = (t) => Math.pow(cosQ(Math.abs(t), q), 2);
        fH = fE;
        note = 'cos^q element fitted to the computed directivity.';
      }
      frame = 'broadside';
      break;
    }
    case 'dra': case 'slotCavity': case 'meDipole': {
      const q = clamp((D0 - 2) / 4, 0.5, 8);
      fE = (t) => Math.pow(cosQ(Math.abs(t), q), 2);
      fH = (t) => Math.pow(cosQ(Math.abs(t), q * 0.85), 2);
      frame = 'broadside';
      note = id === 'meDipole'
        ? 'Complementary electric and magnetic dipoles: the two planes track each other closely.'
        : 'Broadside element fitted to the computed directivity.';
      break;
    }

    /* -------------------------------------------------------- arrays */
    case 'patchArray': case 'phasedArray': case 'siwSlotArray': {
      const side = Math.max(Math.round(Math.sqrt(n)), 1);
      const d = p.spacingLambda ?? (id === 'phasedArray' ? 0.5 : 0.7);
      const taper = n >= 8 ? 'cosine' : 'uniform';
      const qEl = 1.2;
      const scan = id === 'phasedArray' ? (p.scanDeg || 0) : 0;
      fE = (t) => Math.pow(cosQ(Math.abs(t), qEl) * arrayFactor(t, side, d, taper, scan), 2);
      fH = (t) => Math.pow(cosQ(Math.abs(t), qEl) * arrayFactor(t, side, d, taper, 0), 2);
      frame = 'broadside';
      note = `${side} x ${side} elements at ${d} lambda spacing, ${taper} amplitude taper.`;
      break;
    }
    case 'seriesArray': {
      const d = 0.85;
      fE = (t) => Math.pow(cosQ(Math.abs(t), 1.2) * arrayFactor(t, n, d, 'cosine'), 2);
      fH = (t) => Math.pow(cosQ(Math.abs(t), 1.2), 2);
      frame = 'broadside';
      note = `${n} elements in the E-plane, single element across - the column is narrow one way and broad the other.`;
      break;
    }
    case 'collinear': {
      const d = 0.5 * 1.05;
      fE = (t) => {          // elevation: dipole element x vertical array factor
        const fromAxis = Math.PI / 2 - Math.abs(t);
        return Math.pow(dipoleElement(Math.max(fromAxis, 1e-6)) * arrayFactor(t, n, d, 'uniform'), 2);
      };
      fH = () => 1;
      frame = 'omni';
      note = `${n} co-phased half-wave sections squash the doughnut toward the horizon.`;
      break;
    }

    /* ------------------------------------------------------- end-fire */
    case 'yagi': case 'quasiYagi': {
      const nEl = clamp(n, 2, 30);
      const d = clamp((p.boomLambda || 1) / Math.max(nEl - 1, 1), 0.15, 0.4);
      fE = (t) => {
        const af = endfireAF(t, nEl, d);
        const el = Math.abs(dipoleElement(Math.max(Math.abs(Math.PI / 2 - Math.abs(t)) < 1e-6 ? 1e-6 : Math.PI / 2 - Math.abs(t), 1e-6)));
        return Math.pow(af * Math.max(el, 0.05), 2) + floor;
      };
      fH = (t) => Math.pow(endfireAF(t, nEl, d), 2) + floor;
      frame = 'endfire';
      note = `${nEl}-element ordinary end-fire array at ${d.toFixed(2)} lambda spacing - the sidelobes are computed from the array factor.`;
      break;
    }
    case 'lpda': case 'vivaldi': case 'helixAxial': case 'hornSiw': {
      const nn = clamp(D0 - 1, 0.5, 60);
      fE = (t) => Math.pow(Math.cos(Math.abs(t) / 2), 2 * nn) + floor;
      fH = (t) => Math.pow(Math.cos(Math.abs(t) / 2), 2 * nn * 0.9) + floor;
      frame = 'endfire';
      note = 'Travelling-wave end-fire aperture: low sidelobes, beamwidth set by the electrical length.';
      break;
    }

    /* ------------------------------------------------------- apertures */
    case 'hornPyramidal': {
      const a = (p.dims && p.dims['Aperture a']) ? p.dims['Aperture a'] / 1e3 : 0.1;
      const b = (p.dims && p.dims['Aperture b']) ? p.dims['Aperture b'] / 1e3 : 0.07;
      const k0 = (2 * Math.PI) / (p.lambda0 || 0.03);
      // no explicit floor here: sample() fills the rear hemisphere from the
      // mirrored front pattern scaled by the front-to-back ratio
      fE = (t) => Math.pow(uniformAperture((k0 * b / 2) * Math.sin(t)) * (1 + Math.cos(t)) / 2, 2);
      fH = (t) => Math.pow(cosineAperture((k0 * a / 2) * Math.sin(t)) / (Math.PI / 4) * (1 + Math.cos(t)) / 2, 2);
      frame = 'broadside';
      note = 'Uniform E-plane distribution (first sidelobe -13 dB) and cosine H-plane distribution (-23 dB) - the classic horn signature.';
      break;
    }
    case 'reflector': case 'lens': case 'reflectarray': {
      const Dm = (p.dims && (p.dims['Dish diameter'] || p.dims['Lens diameter'] || p.dims['Panel side']))
        ? (p.dims['Dish diameter'] || p.dims['Lens diameter'] || p.dims['Panel side']) / 1e3
        : 0.3;
      const k0 = (2 * Math.PI) / (p.lambda0 || 0.03);
      const taper = id === 'reflector' ? 1 : 0;   // dishes are edge-tapered by the feed
      fE = (t) => Math.pow(circularAperture((k0 * Dm / 2) * Math.sin(t), taper), 2);
      fH = fE;
      frame = 'broadside';
      note = taper
        ? 'Parabolic (-10 dB edge) illumination: first sidelobe near -24 dB.'
        : 'Uniform circular aperture: Airy pattern, first sidelobe -17.6 dB.';
      break;
    }

    /* ----------------------------------------------------------- omni */
    case 'dipole': case 'biconical': {
      fE = (t) => Math.pow(dipoleElement(Math.max(Math.PI / 2 - Math.abs(t), 1e-6)), 2);
      fH = () => 1;
      frame = 'omni';
      note = id === 'biconical'
        ? 'Fat-dipole pattern held over a decade of bandwidth.'
        : 'Thin half-wave dipole: cos((pi/2)cos(theta))/sin(theta).';
      break;
    }
    case 'monopole': {
      const tilt = (p.tiltDeg || 0) * DEG;
      // A finite ground plane does not switch the field off at the horizon: it
      // diffracts, leaving roughly -16 dB below it. Model that as a continuous
      // roll-off so the cut has no step at 0 deg.
      const below = fromDB(-16);
      fE = (t) => {
        const eff = Math.max(Math.PI / 2 - Math.abs(t - tilt), 1e-6);
        const el2 = Math.pow(dipoleElement(eff), 2);
        if (t >= 0) return el2;
        const g = below + (1 - below) * Math.exp(t / (7 * DEG));
        return el2 * g;
      };
      fH = () => 1;
      frame = 'omniHalf';
      note = 'Quarter-wave monopole over a ground plane - a finite ground tilts the peak up off the horizon.';
      break;
    }
    case 'loopSmall': {
      fE = (t) => Math.pow(Math.cos(t), 2);
      fH = () => 1;
      frame = 'omni';
      note = 'Small loop: sin(theta) from the axis, so the doughnut lies in the plane of the loop.';
      break;
    }

    /* ---------------------------------------------------- hemispheric */
    case 'pifa': case 'ifa': {
      const nn = clamp(D0 - 1, 0.2, 3);
      fE = (t) => Math.pow(Math.cos(Math.abs(t) / 2), 2 * nn) * (0.75 + 0.25 * Math.cos(t)) + 0.06;
      fH = (t) => Math.pow(Math.cos(Math.abs(t) / 2), 2 * nn * 0.7) + 0.10;
      frame = 'hemispheric';
      note = 'Broad hemispheric coverage; the chassis carries much of the current, so the real pattern follows the product, not the element.';
      break;
    }
    case 'qha': {
      fE = (t) => Math.pow((1 + Math.cos(t)) / 2, 2);
      fH = fE;
      frame = 'hemispheric';
      note = 'Cardioid: full hemisphere coverage down to the horizon with no ground plane - the GNSS pattern.';
      break;
    }

    default: {
      const q = clamp((D0 - 2) / 4, 0.3, 8);
      fE = (t) => Math.pow(cosQ(Math.abs(t), q), 2);
      fH = fE;
      frame = 'broadside';
      note = 'Generic broadside element fitted to the computed directivity.';
    }
  }

  const d0dBi = toDB(D0);
  const E = sample(fE, frame, floor, false, d0dBi);
  const H = sample(fH, frame, floor, frame === 'omni' || frame === 'omniHalf', d0dBi);
  return {
    E, H, frame, note,
    meta: {
      hpbwE: hpbw(E), hpbwH: hpbw(H),
      sllE: sidelobe(E), sllH: sidelobe(H),
      fbE: frontToBack(E), fbH: frontToBack(H),
      frame,
      axisLabelE: AXIS[frame].E, axisLabelH: AXIS[frame].H,
    },
  };
}

const AXIS = {
  broadside:   { E: 'E-plane (0° = boresight, normal to the board)', H: 'H-plane (0° = boresight)' },
  endfire:     { E: 'E-plane (0° = along the boom / axis)', H: 'H-plane (0° = along the axis)' },
  omni:        { E: 'Elevation (0° = horizon, ±90° = along the axis)', H: 'Azimuth (omnidirectional)' },
  omniHalf:    { E: 'Elevation (0° = horizon, +90° = zenith)', H: 'Azimuth (omnidirectional)' },
  hemispheric: { E: 'Elevation (0° = zenith)', H: 'Elevation, orthogonal cut' },
};

/**
 * Sample a cut over -180..180 deg and normalise the peak to 0 dB.
 *
 * A broadside or hemispheric antenna radiates into a half space, and the
 * cavity/aperture models say nothing about what happens behind it. Rather than
 * leaving a step at the horizon, the front pattern is tapered to a horizon
 * level and the rear hemisphere is built from the mirrored front pattern scaled
 * between that horizon level and the front-to-back ratio. Both pieces meet at
 * exactly the same value at 90 deg, so the cut is continuous by construction.
 *
 * The taper exponent follows the directivity: a broad element (a patch) is
 * shaped strongly by its finite ground, while a directive aperture (a horn, a
 * dish) is already near zero at the horizon and must not have its near-in
 * sidelobes flattened by the taper.
 *
 * Angles are passed through signed, so an asymmetric pattern - a steered array,
 * a tilted monopole - keeps the side it was steered to.
 */
function sample(f, frame, floor, flat = false, d0dBi = 6) {
  const half = frame === 'broadside' || frame === 'hemispheric';
  const horizon = half && floor > 0 ? Math.sqrt(floor) : floor;   // midway in dB
  const q = clamp(20 / Math.max(d0dBi, 1), 0.4, 2);
  const pts = [];
  const raw = [];
  let peak = 0;
  for (let d = -180; d <= 180; d += 1) {
    let v;
    if (flat) {
      v = 1;
    } else if (!half) {
      v = Math.max(f(d * DEG), 0);
    } else if (Math.abs(d) <= 90) {
      const taper = horizon + (1 - horizon) * Math.pow(Math.cos(Math.abs(d) * DEG), q);
      v = Math.max(f(d * DEG), 0) * taper;
    } else {
      // mirror across the horizon, keeping the hemisphere's own side
      const mirrorDeg = Math.sign(d) * (180 - Math.abs(d));
      const c = floor + (horizon - floor) * Math.pow(Math.sin(Math.abs(mirrorDeg) * DEG), 2);
      v = Math.max(f(mirrorDeg * DEG), 0) * c;
    }
    raw.push({ deg: d, v });
    if (v > peak) peak = v;
  }
  for (const r of raw) pts.push({ deg: r.deg, db: clamp(toDB(r.v / peak), -40, 0) });
  return pts;
}

/**
 * Half-power beamwidth measured off the sampled cut.
 * A doughnut pattern peaks at 0 deg AND at +/-180 deg, so among equal maxima
 * the one nearest boresight is the main beam.
 */
function hpbw(cut) {
  const maxDb = Math.max(...cut.map((p) => p.db));
  let iPeak = 0, bestDist = Infinity;
  cut.forEach((p, i) => {
    if (p.db >= maxDb - 0.05 && Math.abs(p.deg) < bestDist) { bestDist = Math.abs(p.deg); iPeak = i; }
  });
  let lo = iPeak, hi = iPeak;
  while (lo > 0 && cut[lo].db > -3) lo--;
  while (hi < cut.length - 1 && cut[hi].db > -3) hi++;
  if (lo === 0 && hi === cut.length - 1) return 360;
  return Math.abs(cut[hi].deg - cut[lo].deg);
}

/** First-sidelobe level: the highest local maximum outside the main lobe. */
function sidelobe(cut) {
  const iPeak = cut.reduce((a, b, i) => (b.db > cut[a].db ? i : a), 0);
  // walk out of the main lobe in both directions until the pattern turns back up
  let best = -60;
  for (const dir of [-1, 1]) {
    let i = iPeak;
    while (i > 0 && i < cut.length - 1) {
      const nxt = i + dir;
      if (nxt <= 0 || nxt >= cut.length - 1) break;
      if (cut[nxt].db > cut[i].db) break;      // reached the first null
      i = nxt;
    }
    for (let j = i; j > 0 && j < cut.length - 1; j += dir) {
      if (cut[j].db > cut[j - 1].db && cut[j].db > cut[j + 1].db) { best = Math.max(best, cut[j].db); break; }
    }
  }
  return best;
}

/** Front-to-back ratio from the cut. */
function frontToBack(cut) {
  const back = cut.find((p) => p.deg === 180);
  return back ? -back.db : 0;
}

/** Sensible default front-to-back ratio when the caller has not computed one. */
function defaultFrontToBack(id) {
  const table = {
    yagi: 18, quasiYagi: 15, lpda: 16, vivaldi: 17, helixAxial: 18,
    hornPyramidal: 30, hornSiw: 18, reflector: 32, lens: 26, reflectarray: 26,
    slotCavity: 22, meDipole: 22, dra: 14, patchArray: 20, phasedArray: 20,
    siwSlotArray: 22, seriesArray: 18, pifa: 6, ifa: 5, qha: 12,
    dipole: 0, monopole: 0, biconical: 0, loopSmall: 0, collinear: 0,
  };
  return table[id] ?? 14;
}

/**
 * Gain and match versus frequency for a candidate.
 * Resonant types roll off with their loaded Q; travelling-wave and aperture
 * types stay flat across their band and fall off at the edges.
 */
export function responseVsFrequency(id, p) {
  const { f0, bwPct, gainDbi } = p;
  const span = clamp((bwPct / 100) * 4, 0.06, 1.6);
  const pts = [];
  const resonant = ['patch', 'patchAir', 'patchStacked', 'patchApertureCoupled', 'patchArray',
                    'seriesArray', 'dra', 'pifa', 'ifa', 'loopSmall', 'slotCavity', 'yagi',
                    'collinear', 'phasedArray', 'siwSlotArray', 'qha'].includes(id);
  const Q = resonant ? 1 / Math.max(bwPct / 100, 1e-3) : 0;
  for (let i = 0; i <= 240; i++) {
    const f = f0 * (1 - span / 2) + f0 * span * (i / 240);
    const x = f / f0 - f0 / f;
    let vswr, gain;
    if (resonant) {
      const g2 = 1 / (1 + Math.pow(2 / (Q * x || 1e-9), 2));       // single resonance
      const gamma = Math.sqrt(clamp(g2, 0, 0.999));
      vswr = (1 + gamma) / (1 - gamma);
      gain = gainDbi + toDB(1 - g2) + 2 * Math.log10(f / f0) * 10 * 0.15;
    } else {
      // flat in band, rolling off outside it
      const edge = Math.abs(f / f0 - 1) / (bwPct / 200);
      const excess = Math.max(edge - 1, 0);
      vswr = 1.3 + 3.5 * excess * excess;
      gain = gainDbi + 20 * Math.log10(f / f0) * 0.25 - 6 * excess * excess;
    }
    pts.push({ f, vswr: clamp(vswr, 1, 20), gain });
  }
  return pts;
}
