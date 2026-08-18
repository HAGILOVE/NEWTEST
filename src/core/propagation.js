/**
 * Propagation and link-budget engine.
 *
 *  - Friis / free-space path loss (ITU-R P.525)
 *  - Two-ray ground reflection with a breakpoint
 *  - COST-231 Hata for urban/suburban sub-6 links
 *  - ITU-R P.676 gaseous absorption (O2 + H2O line-by-line simplified fit)
 *  - ITU-R P.838 rain specific attenuation
 *  - Fresnel zones, radio horizon with k-factor
 *  - Thermal-noise floor, receiver sensitivity, Shannon capacity, fade margin
 */
import { C0, KB, T0, toDB, fromDB, clamp } from './constants.js';

/** Free-space path loss [dB]. */
export function fspl(f, d) {
  return 20 * Math.log10(4 * Math.PI * d * f / C0);
}

/**
 * Gaseous absorption: dry air (O2) + water vapour, [dB/km].
 *
 * Line-shape model in the spirit of ITU-R P.676 / Liebe MPM, with the O2
 * 50-70 GHz complex represented by a single super-Lorentzian and the strong
 * H2O lines kept explicit. Calibrated against the P.676 sea-level reference
 * curve (15 degC, 1013.25 hPa, 7.5 g/m^3):
 *   10 GHz 0.011   22.2 GHz 0.20   35 GHz 0.09   60 GHz 15.1
 *   77 GHz 0.28    94 GHz 0.45     118.75 GHz 2.0  183 GHz 29
 * Accurate to roughly +/-30 % in the windows, which is well inside the
 * uncertainty of any real atmosphere.
 *
 * @param f    frequency [Hz]
 * @param T    temperature [degC]
 * @param P    total pressure [hPa]
 * @param rho  water-vapour density [g/m^3]
 */
export function gaseousAttenuation(f, T = 15, P = 1013.25, rho = 7.5) {
  const fG = f / 1e9;
  const rp = P / 1013.25;                 // pressure ratio
  const rt = 288 / (273.15 + T);          // inverse temperature ratio
  const rw = rho / 7.5;

  // --- dry air ------------------------------------------------------------
  // non-resonant Debye term (dominates below ~40 GHz)
  const nonRes = 6.5e-5 * fG * fG / (1 + Math.pow(fG / 45, 2)) * rp * rp * Math.pow(rt, 2.5);
  // O2 60 GHz complex: super-Lorentzian, exponent 4 reproduces the steep skirts
  const superL = (f0, peak, width, expn) => peak / (1 + Math.pow(Math.abs(fG - f0) / width, expn));
  const o60 = superL(60, 15.1, 3.5 * Math.sqrt(rp), 4) * rp * rp * Math.pow(rt, 2);
  const o118 = superL(118.75, 1.9, 1.9 * Math.sqrt(rp), 3) * rp * rp * Math.pow(rt, 2);
  const gO = nonRes + o60 + o118;

  // --- water vapour --------------------------------------------------------
  // exponent 2.5 keeps the near-line shape while suppressing the unphysical
  // far wings a pure Lorentzian would leave in the transmission windows
  const lor = (f0, peak, width) =>
    peak / (1 + Math.pow(Math.abs(fG - f0) / (width * Math.sqrt(rp)), 2.5));
  const continuum = 4.0e-5 * fG * fG * rp * Math.pow(rt, 2.5);
  const gW = rw * (
    lor(22.235, 0.180, 2.8) +
    lor(183.31, 28.0, 4.5) +
    lor(325.15, 38.0, 5.0) +
    continuum
  );

  return { oxygen: gO, water: Math.max(gW, 0), total: gO + Math.max(gW, 0) };
}

/**
 * ITU-R P.838-3 rain specific attenuation gamma_R = k * R^alpha [dB/km].
 * k/alpha interpolated from the recommendation's tabulated coefficients
 * (horizontal polarisation, 1-100 GHz).
 */
const RAIN_TABLE = [
  // f[GHz], kH, aH, kV, aV
  [1, 0.0000259, 0.9691, 0.0000308, 0.8592],
  [2, 0.0000847, 1.0664, 0.0000998, 0.9490],
  [4, 0.0001071, 1.6009, 0.0002461, 1.2476],
  [6, 0.00175, 1.3080, 0.001425, 1.2775],
  [8, 0.004115, 1.3905, 0.003450, 1.3797],
  [10, 0.01217, 1.2571, 0.01129, 1.2156],
  [12, 0.02386, 1.1825, 0.02455, 1.1216],
  [15, 0.04481, 1.1233, 0.05008, 1.0440],
  [20, 0.09164, 1.0568, 0.09611, 0.9847],
  [25, 0.1571, 0.9991, 0.1533, 0.9491],
  [30, 0.2403, 0.9485, 0.2291, 0.9129],
  [40, 0.4274, 0.8761, 0.4001, 0.8433],
  [50, 0.5375, 0.8355, 0.5041, 0.8125],
  [60, 0.6472, 0.8084, 0.6091, 0.7871],
  [70, 0.7171, 0.7871, 0.6797, 0.7658],
  [80, 0.7557, 0.7734, 0.7233, 0.7527],
  [90, 0.7740, 0.7658, 0.7471, 0.7455],
  [100, 0.7816, 0.7628, 0.7584, 0.7436],
];
export function rainAttenuation(f, rainRate = 25, polarization = 'linear', tiltDeg = 45) {
  const fG = clamp(f / 1e9, 1, 100);
  let i = 0;
  while (i < RAIN_TABLE.length - 2 && RAIN_TABLE[i + 1][0] < fG) i++;
  const [f1, kH1, aH1, kV1, aV1] = RAIN_TABLE[i];
  const [f2, kH2, aH2, kV2, aV2] = RAIN_TABLE[i + 1];
  const t = (Math.log(fG) - Math.log(f1)) / (Math.log(f2) - Math.log(f1));
  const lg = (a, b) => Math.exp(Math.log(a) + t * (Math.log(b) - Math.log(a)));
  const kH = lg(kH1, kH2), kV = lg(kV1, kV2);
  const aH = aH1 + t * (aH2 - aH1), aV = aV1 + t * (aV2 - aV1);
  const tau = (polarization === 'circular' ? 45 : tiltDeg) * Math.PI / 180;
  const k = (kH + kV + (kH - kV) * Math.cos(tau) ** 2 * Math.cos(2 * tau)) / 2;
  const a = (kH * aH + kV * aV + (kH * aH - kV * aV) * Math.cos(tau) ** 2 * Math.cos(2 * tau)) / (2 * k);
  return { k, alpha: a, gammaR: k * Math.pow(rainRate, a) };
}

/** Fresnel zone radius [m] at distance d1 from one end of a path of length d. */
export function fresnelRadius(f, d1, d, n = 1) {
  const lam = C0 / f;
  const d2 = d - d1;
  return Math.sqrt((n * lam * d1 * d2) / d);
}

/** Radio horizon [m] for an antenna height h with an effective-earth k-factor. */
export function radioHorizon(h, k = 4 / 3) {
  const Re = 6371e3 * k;
  return Math.sqrt(2 * Re * h);
}

/** Two-ray flat-earth model with the breakpoint distance. */
export function twoRay(f, d, ht, hr, gammaRefl = -1) {
  const lam = C0 / f;
  const dBreak = (4 * Math.PI * ht * hr) / lam;
  if (d < dBreak) return { loss: fspl(f, d), dBreak, region: 'free-space' };
  const loss = 40 * Math.log10(d) - 20 * Math.log10(ht) - 20 * Math.log10(hr);
  void gammaRefl;
  return { loss, dBreak, region: 'two-ray (40 dB/decade)' };
}

/** COST-231 Hata (urban), valid 1.5-2 GHz, extended in practice to 3 GHz. */
export function cost231Hata(f, d, hb = 30, hm = 1.5, env = 'urban') {
  const fM = f / 1e6;
  const dKm = d / 1e3;
  const aHm = env === 'urban'
    ? 3.2 * Math.pow(Math.log10(11.75 * hm), 2) - 4.97
    : (1.1 * Math.log10(fM) - 0.7) * hm - (1.56 * Math.log10(fM) - 0.8);
  const Cm = env === 'urban' ? 3 : 0;
  return 46.3 + 33.9 * Math.log10(fM) - 13.82 * Math.log10(hb) - aHm
       + (44.9 - 6.55 * Math.log10(hb)) * Math.log10(Math.max(dKm, 0.01)) + Cm;
}

/** Thermal noise power [dBm] in a bandwidth B at temperature T. */
export function noiseFloorDbm(B, T = T0) {
  return 10 * Math.log10(KB * T * B * 1e3);
}

/**
 * Complete link budget.
 * @returns everything a reviewer will ask for in a design review.
 */
export function linkBudget(p) {
  const {
    f, distance, ptxDbm, gtxDbi, grxDbi, bandwidth,
    nfDb = 6, requiredSnrDb = 10, cableTxDb = 0.5, cableRxDb = 0.5,
    model = 'fspl', rainRateMmH = 0, humidity = 7.5, tempC = 15,
    ht = 10, hr = 1.5, polarizationLossDb = 0, implementationLossDb = 2,
  } = p;

  const dKm = distance / 1e3;
  const pathBase = model === 'twoRay' ? twoRay(f, distance, ht, hr).loss
    : model === 'hata' ? cost231Hata(f, distance, ht, hr)
    : fspl(f, distance);

  const gas = gaseousAttenuation(f, tempC, 1013.25, humidity);
  const gasDb = gas.total * dKm;
  const rain = rainAttenuation(f, rainRateMmH || 0.001);
  const rainDb = rainRateMmH > 0 ? rain.gammaR * dKm : 0;

  const totalPathDb = pathBase + gasDb + rainDb + polarizationLossDb;
  const eirpDbm = ptxDbm + gtxDbi - cableTxDb;
  const prxDbm = eirpDbm - totalPathDb + grxDbi - cableRxDb;
  const noiseDbm = noiseFloorDbm(bandwidth) + nfDb;
  const snrDb = prxDbm - noiseDbm;
  const sensitivityDbm = noiseDbm + requiredSnrDb + implementationLossDb;
  const marginDb = prxDbm - sensitivityDbm;
  const shannonBps = bandwidth * Math.log2(1 + fromDB(snrDb));

  return {
    eirpDbm, prxDbm, noiseDbm, snrDb, sensitivityDbm, marginDb,
    fsplDb: fspl(f, distance), pathBaseDb: pathBase,
    gasDbPerKm: gas.total, gasDb, rainGammaDbPerKm: rain.gammaR, rainDb,
    totalPathDb, shannonBps,
    fresnel60: fresnelRadius(f, distance / 2, distance) * 0.6,
    fresnelR1: fresnelRadius(f, distance / 2, distance),
    horizonKm: (radioHorizon(ht) + radioHorizon(hr)) / 1e3,
    model,
  };
}

/** Solve for the range at which the margin hits zero. */
export function maxRange(p) {
  let lo = 1, hi = 1e6;
  for (let i = 0; i < 80; i++) {
    const mid = Math.sqrt(lo * hi);
    const m = linkBudget({ ...p, distance: mid }).marginDb;
    if (m > 0) lo = mid; else hi = mid;
  }
  return lo;
}

/** EIRP / power-density limits and human-exposure distance (ICNIRP / FCC MPE). */
export function mpeDistance(eirpDbm, limitWm2 = 10) {
  const eirpW = fromDB(eirpDbm - 30);
  return Math.sqrt(eirpW / (4 * Math.PI * limitWm2));
}

export { toDB, fromDB };
