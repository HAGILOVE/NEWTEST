/**
 * Fundamental limits on antennas - used to flag physically impossible specs
 * before the user spends a month in a simulator.
 */
import { C0, toDB, clamp } from './constants.js';

/**
 * Chu-Harrington / McLean lower bound on the radiation Q of any antenna that
 * fits inside a sphere of radius a (ka = 2*pi*a/lambda), linear polarisation:
 *      Q_min = 1/(ka)^3 + 1/(ka)
 * Reference: J.S. McLean, IEEE T-AP 44(5), 1996.
 */
export function chuQ(ka, circular = false) {
  const q = 1 / Math.pow(ka, 3) + 1 / ka;
  return circular ? q / 2 : q;
}

/** Maximum VSWR-S fractional bandwidth for an antenna of radius a, efficiency e. */
export function maxFractionalBandwidth(a, lambda, efficiency = 1, vswr = 2, circular = false) {
  const ka = (2 * Math.PI * a) / lambda;
  const q = chuQ(ka, circular) / Math.max(efficiency, 1e-3);
  return (vswr - 1) / (q * Math.sqrt(vswr));
}

/**
 * Harrington's bound on directivity for a source confined to radius a.
 * D_max = (ka)^2 + 2*ka  (normal-gain limit; superdirectivity beyond this is
 * possible in theory but pays with Q, loss sensitivity and tolerance).
 */
export function harringtonDirectivity(a, lambda) {
  const ka = (2 * Math.PI * a) / lambda;
  return ka * ka + 2 * ka;
}

/** Aperture-limited gain: the most any aperture of area A can give. */
export function apertureGain(areaM2, lambda, apertureEfficiency = 1) {
  return toDB((4 * Math.PI * areaM2 * apertureEfficiency) / (lambda * lambda));
}

/**
 * Gain-bandwidth feasibility check for a footprint.
 * Returns a verdict plus the binding constraint.
 */
export function feasibility({ f, maxDimM, targetGainDbi, fracBw, efficiency = 0.8, circular = false }) {
  const lambda = C0 / f;
  const a = maxDimM / 2;                       // enclosing sphere radius
  const dMax = harringtonDirectivity(a, lambda);
  const gMaxDbi = toDB(dMax * efficiency);
  const bwMax = maxFractionalBandwidth(a, lambda, efficiency, 2, circular);
  const apMax = apertureGain(maxDimM * maxDimM, lambda, 0.8);
  const issues = [];
  if (targetGainDbi > gMaxDbi + 0.2) {
    issues.push({
      severity: 'blocking',
      code: 'harrington',
      message: `Requested ${targetGainDbi.toFixed(1)} dBi exceeds the Harrington normal-gain limit of ${gMaxDbi.toFixed(1)} dBi for a ${(maxDimM * 1e3).toFixed(0)} mm envelope at ${(f / 1e9).toFixed(3)} GHz.`,
    });
  }
  if (fracBw && fracBw > bwMax * 1.05) {
    issues.push({
      severity: 'blocking',
      code: 'chu',
      message: `Requested ${(fracBw * 100).toFixed(1)} % bandwidth exceeds the Chu limit of ${(bwMax * 100).toFixed(1)} % for ka = ${((2 * Math.PI * a) / lambda).toFixed(2)}. Enlarge the antenna, accept lower efficiency, or use a multi-resonator/lossy match.`,
    });
  }
  return {
    lambda, ka: (2 * Math.PI * a) / lambda,
    harringtonGainDbi: gMaxDbi,
    apertureGainDbi: apMax,
    chuBandwidth: bwMax,
    chuQ: chuQ((2 * Math.PI * a) / lambda, circular),
    electricallySmall: (2 * Math.PI * a) / lambda < 1,
    issues,
    feasible: issues.every((i) => i.severity !== 'blocking'),
  };
}

/**
 * Bode-Fano bound: best achievable in-band reflection for a single-resonance
 * load matched over a fractional bandwidth.
 *   |Gamma|_min = exp(-pi / (Q * fracBw))
 */
export function bodeFano(Q, fracBw) {
  const g = Math.exp(-Math.PI / Math.max(Q * fracBw, 1e-6));
  return { gamma: g, returnLossDb: -20 * Math.log10(Math.max(g, 1e-9)),
           vswr: (1 + g) / Math.max(1 - g, 1e-9) };
}

/** Rayleigh far-field distance and reactive/radiating boundaries. */
export function fieldRegions(maxDimM, lambda) {
  const D = maxDimM;
  return {
    reactiveNearField: 0.62 * Math.sqrt(Math.pow(D, 3) / lambda),
    fraunhofer: (2 * D * D) / lambda,
    threeLambda: 3 * lambda,
    farField: Math.max((2 * D * D) / lambda, 3 * lambda, 1.6 * lambda),
  };
}

/** Effective aperture from gain. */
export function effectiveAperture(gainDbi, lambda) {
  return (Math.pow(10, gainDbi / 10) * lambda * lambda) / (4 * Math.PI);
}

/** 3 dB beamwidth estimate from directivity (Kraus / Tai-Pereira). */
export function beamwidthFromDirectivity(D0, ratio = 1) {
  // D0 ~ 32400 / (theta_E * theta_H) in degrees; ratio = theta_E/theta_H
  const prod = 32400 / Math.max(D0, 1.01);
  const thH = Math.sqrt(prod / ratio);
  return { thetaE: thH * ratio, thetaH: thH };
}

export { clamp };
