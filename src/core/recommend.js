/**
 * Candidate ranking.
 *
 * Every archetype is evaluated with the real physics models, then scored on
 * how well the computed result meets the specification. Nothing is hard-coded:
 * if a substrate is too lossy for a 64-element array at 28 GHz, the feed-loss
 * model says so and the score falls out of it.
 */
import { toDB, fromDB, clamp } from './constants.js';
import { ARCHETYPES, evaluate } from './library.js';
import { groundPlaneEffect, recommendGroundSize } from './ground.js';
import { feasibility } from './limits.js';

const PATTERN_MATCH = {
  // requested -> archetype pattern -> score 0..1
  directional: { directional: 1.0, steerable: 0.95, hemispheric: 0.45, omni: 0.05, broad: 0.4 },
  omni:        { omni: 1.0, hemispheric: 0.6, broad: 0.7, directional: 0.05, steerable: 0.05 },
  hemispheric: { hemispheric: 1.0, omni: 0.65, directional: 0.6, broad: 0.7, steerable: 0.5 },
  steerable:   { steerable: 1.0, directional: 0.35, omni: 0.05, hemispheric: 0.2, broad: 0.2 },
};

/**
 * @param {object} spec
 *   f              [Hz]
 *   material       material record (or composite)
 *   h              substrate height [m]
 *   sigma          conductor conductivity [S/m]
 *   targetGainDbi  required realized gain
 *   pattern        'directional' | 'omni' | 'hemispheric' | 'steerable'
 *   polarization   'linear' | 'circular' | 'any'
 *   bwPct          required fractional bandwidth [%] (VSWR 2:1)
 *   maxDimM        largest allowed dimension [m] (optional)
 *   groundM        available ground-plane edge [m] (optional)
 *   priority       {gain, size, cost, bandwidth, simplicity} weights 0..1
 */
export function recommend(spec) {
  const lambda0 = 299792458 / spec.f;
  // Types that synthesise their own aperture (horn, reflector, array, ...) must
  // size for the target PLUS the losses that are applied afterwards.
  const ctx = {
    ...spec, lambda0,
    targetGainDbi: spec.targetGainDbi + (spec.feedLossDb || 0) + 0.3,
  };
  const w = {
    gain: 1.0, bandwidth: 0.7, size: 0.6, cost: 0.5, simplicity: 0.4,
    ...(spec.priority || {}),
  };

  const results = ARCHETYPES.map((arch) => {
    const r = evaluate(arch, ctx);
    if (r.error) return { ...r, score: -1, verdict: 'error', reasons: [`Model error: ${r.error}`] };

    const reasons = [];
    const blockers = [];
    let score = 0;
    let weightSum = 0;

    // ---- frequency coverage -------------------------------------------------
    if (spec.f < arch.fRange[0] || spec.f > arch.fRange[1]) {
      blockers.push(`Outside the practical band for this type (${(arch.fRange[0] / 1e9).toFixed(2)} - ${(arch.fRange[1] / 1e9).toFixed(0)} GHz).`);
    }

    // ---- pattern ------------------------------------------------------------
    const pm = (PATTERN_MATCH[spec.pattern] || PATTERN_MATCH.directional)[arch.pattern] ?? 0.2;
    score += pm * 1.4; weightSum += 1.4;
    if (pm < 0.2) blockers.push(`Radiation pattern is ${arch.pattern}, the specification asks for ${spec.pattern}.`);

    // ---- polarisation -------------------------------------------------------
    let polOk = true;
    if (spec.polarization && spec.polarization !== 'any') {
      polOk = arch.pol.includes(spec.polarization);
      if (!polOk) blockers.push(`Cannot produce ${spec.polarization} polarisation without a fundamentally different geometry.`);
    }

    // ---- ground-plane corrected realized gain -------------------------------
    let gain = r.gainDbi;
    let gnd = null;
    if (spec.groundM && (arch.category === 'Microstrip' || arch.id === 'slotCavity')) {
      const patchDim = Math.max(r.size.w, r.size.l) / 1e3;
      gnd = groundPlaneEffect({
        lg: spec.groundM, patchDim, lambda0,
        swr: r.patch ? r.patch.surfaceWaveRatio : 0,
      });
      gain += gnd.deltaGdB;
      if (patchDim > spec.groundM) blockers.push(`The radiator (${patchDim * 1e3 | 0} mm) does not fit on the ${(spec.groundM * 1e3).toFixed(0)} mm ground plane.`);
    }
    gain -= spec.feedLossDb || 0;

    const gainMargin = gain - spec.targetGainDbi;
    const gScore = gainMargin >= 0
      ? clamp(1 - Math.max(gainMargin - 3, 0) / 12, 0.55, 1)   // big overshoot = wasted size
      : clamp(1 + gainMargin / 6, 0, 0.55);
    score += gScore * w.gain * 2.2; weightSum += w.gain * 2.2;
    if (gainMargin < -0.05) {
      reasons.push(`Falls ${Math.abs(gainMargin).toFixed(1)} dB short of the ${spec.targetGainDbi.toFixed(1)} dBi target.`);
      if (gainMargin < -4) blockers.push(`${Math.abs(gainMargin).toFixed(1)} dB short of target - not recoverable by tuning.`);
    } else {
      reasons.push(`Meets the gain target with ${gainMargin.toFixed(1)} dB of margin.`);
    }

    // ---- bandwidth ----------------------------------------------------------
    if (spec.bwPct) {
      const bwMargin = r.bwPct - spec.bwPct;
      const bScore = bwMargin >= 0 ? 1 : clamp(1 + bwMargin / spec.bwPct, 0, 0.6);
      score += bScore * w.bandwidth * 1.5; weightSum += w.bandwidth * 1.5;
      if (bwMargin < 0) {
        reasons.push(`VSWR-2 bandwidth ${r.bwPct.toFixed(1)} % versus the ${spec.bwPct.toFixed(1)} % required.`);
        if (r.bwPct < spec.bwPct * 0.5) blockers.push(`Bandwidth is less than half of what is required (${r.bwPct.toFixed(1)} % vs ${spec.bwPct.toFixed(1)} %).`);
      } else {
        reasons.push(`Bandwidth ${r.bwPct.toFixed(1)} % covers the ${spec.bwPct.toFixed(1)} % requirement.`);
      }
    }

    // ---- size ---------------------------------------------------------------
    const maxDim = Math.max(r.size.w, r.size.l, r.size.h) / 1e3;
    if (spec.maxDimM) {
      const fit = spec.maxDimM / maxDim;
      const sScore = clamp(fit >= 1 ? 1 : fit * fit, 0, 1);
      score += sScore * w.size * 1.3; weightSum += w.size * 1.3;
      if (fit < 1) {
        reasons.push(`Largest dimension ${(maxDim * 1e3).toFixed(0)} mm exceeds the ${(spec.maxDimM * 1e3).toFixed(0)} mm envelope.`);
        if (fit < 0.75) blockers.push(`Does not fit: needs ${(maxDim * 1e3).toFixed(0)} mm against a ${(spec.maxDimM * 1e3).toFixed(0)} mm budget.`);
      }
    } else {
      score += clamp(1 - maxDim / (6 * lambda0), 0.2, 1) * w.size * 0.8;
      weightSum += w.size * 0.8;
    }

    // ---- profile / height ---------------------------------------------------
    if (spec.lowProfile && arch.profile === '3d') {
      reasons.push('Not a low-profile part - needs vertical volume.');
      score -= 0.35;
    }

    // ---- cost & complexity --------------------------------------------------
    score += (1 - (arch.cost - 1) / 4) * w.cost; weightSum += w.cost;
    score += (1 - (arch.complexity - 1) / 4) * w.simplicity; weightSum += w.simplicity;

    // ---- over-engineering ---------------------------------------------------
    // A 24 dBi-class aperture asked to deliver 7 dBi is not "wrong", it is the
    // wrong tool: it costs volume, money and build time for gain nobody asked
    // for. Rank it below the parts that fit the job.
    if (arch.minGainDbi && spec.targetGainDbi < arch.minGainDbi - 0.5) {
      const over = arch.minGainDbi - spec.targetGainDbi;
      reasons.push(`Over-specified for a ${spec.targetGainDbi.toFixed(1)} dBi requirement - this class of antenna only earns its cost above about ${arch.minGainDbi} dBi.`);
      score -= Math.min(over * 0.12, 1.1);
    }

    // ---- substrate sanity ---------------------------------------------------
    if (!arch.ignoreSubstrate && spec.material.fMax && spec.f > spec.material.fMax) {
      reasons.push(`${spec.material.name} is not recommended above ${(spec.material.fMax / 1e9).toFixed(0)} GHz.`);
      score -= 0.5;
    }
    if (!arch.ignoreSubstrate && r.efficiency < 0.35) {
      reasons.push(`Radiation efficiency only ${(r.efficiency * 100).toFixed(0)} % on this substrate - ${toDB(r.efficiency).toFixed(1)} dB is burned as heat.`);
    }

    const norm = weightSum > 0 ? score / weightSum : 0;
    const verdict = blockers.length ? 'rejected' : (gainMargin >= 0 ? 'recommended' : 'marginal');

    return {
      ...r,
      realizedGainDbi: gain,
      gainMargin,
      groundEffect: gnd,
      score: verdict === 'rejected' ? norm * 0.25 : norm,
      rawScore: norm,
      verdict, reasons, blockers,
      patternMatch: pm, polOk,
    };
  });

  results.sort((a, b) => b.score - a.score);

  const lim = feasibility({
    f: spec.f,
    maxDimM: spec.maxDimM || 6 * lambda0,
    targetGainDbi: spec.targetGainDbi,
    fracBw: spec.bwPct ? spec.bwPct / 100 : null,
    efficiency: 0.8,
    circular: spec.polarization === 'circular',
  });

  return { candidates: results, limits: lim, lambda0 };
}

/** Convenience: the best non-rejected candidate. */
export function bestOf(results) {
  return results.candidates.find((c) => c.verdict !== 'rejected' && c.verdict !== 'error') || results.candidates[0];
}

export { recommendGroundSize, fromDB };
