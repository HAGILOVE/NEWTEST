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
import { feasibility, harringtonDirectivity } from './limits.js';
import { MATERIAL_BY_ID, MATERIALS } from './materials.js';

/**
 * Archetype models read ctx.material. Callers that hand us a materialId
 * instead of a resolved material object must not silently lose every model
 * that touches the dielectric.
 */
function withMaterial(spec) {
  const material = spec.material || MATERIAL_BY_ID[spec.materialId] || MATERIALS[0];
  // Feed-loss models need a conductivity; annealed copper is the default stock.
  const sigma = spec.sigma || 5.8e7;
  return (spec.material && spec.sigma) ? spec : { ...spec, material, sigma };
}

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
export function recommend(rawSpec) {
  const spec = withMaterial(rawSpec);
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
    const GROUND_DEPENDENT = ['Microstrip'].includes(arch.category)
      || ['slotCavity', 'dra', 'meDipole', 'siwSlotArray', 'reflectarray'].includes(arch.id);
    if ((spec.groundXM || spec.groundM) && GROUND_DEPENDENT) {
      const gx = spec.groundXM || spec.groundM;
      const gy = spec.groundYM || spec.groundM;
      // size.l runs with the resonant length (x), size.w with the width (y)
      const dimX = r.size.l / 1e3;
      const dimY = r.size.w / 1e3;
      gnd = groundPlaneEffect({
        lgx: gx, lgy: gy, patchL: dimX, patchW: dimY, lambda0,
        swr: r.patch ? r.patch.surfaceWaveRatio : 0,
      });
      gain += gnd.deltaGdB;
      if (dimX > gx || dimY > gy) {
        blockers.push(`The radiator (${(dimX * 1e3).toFixed(0)} × ${(dimY * 1e3).toFixed(0)} mm) does not fit on the ${(gx * 1e3).toFixed(0)} × ${(gy * 1e3).toFixed(0)} mm ground plane.`);
      }
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

    // ---- does it physically fit on the board? -------------------------------
    // The ground plane / board footprint constrains every antenna, not just the
    // ones that need a ground plane electrically: a Yagi boom, a horn aperture
    // and a dish diameter all have to sit inside the space the user has.
    const boardX = spec.groundXM || spec.groundM;
    const boardY = spec.groundYM || spec.groundM;
    let boardFit = null;
    if (boardX && boardY) {
      const fw = r.size.w / 1e3, fl = r.size.l / 1e3;
      const asIs = fw <= boardX && fl <= boardY;
      const turned = fw <= boardY && fl <= boardX;
      boardFit = {
        fits: asIs || turned,
        needsRotation: !asIs && turned,
        // how much the footprint overruns the board, as a linear ratio
        overrun: Math.max(Math.min(fw / boardX, fw / boardY), Math.min(fl / boardY, fl / boardX)),
        footprintUse: (fw * fl) / (boardX * boardY),
      };
      if (!boardFit.fits) {
        blockers.push(`Footprint ${r.size.w.toFixed(0)} × ${r.size.l.toFixed(0)} mm does not fit the ${(boardX * 1e3).toFixed(0)} × ${(boardY * 1e3).toFixed(0)} mm board in either orientation.`);
      } else {
        // Reward candidates that use the available board well rather than
        // leaving most of it empty - unused board is unused aperture.
        const use = clamp(boardFit.footprintUse, 0, 1);
        score += clamp(0.25 + 0.75 * Math.sqrt(use), 0, 1) * w.size * 0.9;
        weightSum += w.size * 0.9;
        if (boardFit.needsRotation) {
          reasons.push('Fits only if rotated 90° on the board.');
        }
        if (use < 0.12 && arch.pattern === 'directional') {
          reasons.push(`Uses only ${(use * 100).toFixed(0)} % of the board area — there is aperture here going spare.`);
        }
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

/**
 * What this board can do at best.
 *
 * The ranked list answers "which type meets my target". This answers the other
 * question a designer asks first: "given the space I have, how much gain is
 * even on the table, and which style of antenna gets me there?"
 *
 * Two ceilings bound it:
 *   aperture   G = 4*pi*A*eta_ap / lambda^2 for the board area - no antenna
 *              that fits on the board can beat this, whatever its type
 *   Harrington D <= (ka)^2 + 2ka for the enclosing sphere
 * and then each archetype is grown until its footprint stops fitting, which
 * gives the best gain actually reachable with a real geometry.
 *
 * @param spec same shape as recommend(), with groundXM / groundYM set
 */
export function boardCapability(rawSpec) {
  const spec = withMaterial(rawSpec);
  const lambda0 = 299792458 / spec.f;
  const bx = spec.groundXM || spec.groundM;
  const by = spec.groundYM || spec.groundM;
  if (!bx || !by) return null;

  const areaM2 = bx * by;
  // Two different bounds, and they do not apply to the same things.
  //   aperture    a PLANAR aperture filling the board, 65 % efficient. Any
  //               flat, board-filling antenna is held to roughly this.
  //   Harrington  a bound on any current distribution inside the enclosing
  //               sphere. It applies universally - but the sphere has to
  //               enclose the WHOLE antenna. A helix, a dish or a collinear
  //               stack sticks up out of the board plane and is bounded by
  //               the taller sphere, not by the board outline, so each
  //               candidate is checked against its own envelope.
  const apertureEff = 0.65;
  const apertureCeilingDbi = toDB((4 * Math.PI * areaM2 * apertureEff) / (lambda0 * lambda0));
  const sphereBoundDbi = (heightM) =>
    toDB(harringtonDirectivity(Math.hypot(bx, by, heightM || 0) / 2, lambda0) * 0.8);

  // The headline ceiling describes the envelope the user actually constrained:
  // board only, or board plus the height limit if one is set.
  const boardCeilingDbi = sphereBoundDbi(0);
  const envelopeCeilingDbi = spec.maxDimM ? sphereBoundDbi(spec.maxDimM) : null;
  const ceiling = envelopeCeilingDbi ?? boardCeilingDbi;
  // Antennas allowed to leave the board plane can legitimately pass the
  // board-outline figure, so the scan must not stop there.
  const scanMax = (envelopeCeilingDbi ?? boardCeilingDbi + 12) + 4;

  const feedLoss = spec.feedLossDb || 0;

  const perArch = [];
  for (const arch of ARCHETYPES) {
    if (spec.f < arch.fRange[0] || spec.f > arch.fRange[1]) continue;
    if (spec.polarization && spec.polarization !== 'any' && !arch.pol.includes(spec.polarization)) continue;
    const pm = (PATTERN_MATCH[spec.pattern] || PATTERN_MATCH.directional)[arch.pattern] ?? 0.2;
    const GROUND_DEPENDENT = arch.category === 'Microstrip'
      || ['slotCavity', 'dra', 'meDipole', 'siwSlotArray', 'reflectarray'].includes(arch.id);
    const tryTarget = (t) => {
      const r = evaluate(arch, { ...spec, lambda0, targetGainDbi: t + feedLoss + 0.3 });
      if (r.error) return null;
      const fw = r.size.w / 1e3, fl = r.size.l / 1e3, fh = r.size.h / 1e3;
      const fits = (fw <= bx && fl <= by) || (fw <= by && fl <= bx);
      if (!fits) return null;
      // The footprint is already bounded by the board, so the envelope field
      // ("max height / envelope") constrains what stands above it.
      if (spec.maxDimM && fh > spec.maxDimM) return null;
      if (spec.lowProfile && arch.profile === '3d') return null;
      let gain = r.gainDbi;
      if (GROUND_DEPENDENT) {
        gain += groundPlaneEffect({
          lgx: bx, lgy: by, patchL: fl, patchW: fw, lambda0,
          swr: r.patch ? r.patch.surfaceWaveRatio : 0,
        }).deltaGdB;
      }
      gain -= feedLoss;
      // Nothing gets past the bound for the sphere that encloses it. This is
      // the physical sanity check on every model in the library.
      const boundDbi = sphereBoundDbi(fh);
      if (!Number.isFinite(gain) || gain > boundDbi) return null;
      return { gainDbi: gain, boundDbi, sizeMm: r.size, bwPct: r.bwPct,
               efficiency: r.efficiency, count: r.count, footprintUse: (fw * fl) / areaM2 };
    };
    // Coarse scan to find where the footprint stops fitting, then a fine pass
    // over the last usable interval so the answer is not quantised to the step.
    let best = null, lastGood = 0;
    for (let t = 0; t <= scanMax; t += 1.5) {
      const r = tryTarget(t);
      if (!r) break;
      lastGood = t;
      if (!best || r.gainDbi > best.gainDbi) best = r;
    }
    for (let t = lastGood; t <= lastGood + 1.5; t += 0.25) {
      const r = tryTarget(t);
      if (!r) break;
      if (!best || r.gainDbi > best.gainDbi) best = r;
    }
    if (best) perArch.push({ arch, ...best, patternMatch: pm });
  }
  perArch.sort((a, b) => b.gainDbi - a.gainDbi);


  // The headline answer has to be an antenna that produces the pattern the
  // user asked for. Falling back to a mismatched type would report an omni
  // mast as the best a board can do for a directional link.
  const matching = perArch.filter((x) => x.patternMatch >= 0.5);
  const best = matching[0] || null;

  return {
    boardXM: bx, boardYM: by, areaM2,
    areaLambdaSq: areaM2 / (lambda0 * lambda0),
    apertureCeilingDbi, boardCeilingDbi, envelopeCeilingDbi,
    harringtonDbi: boardCeilingDbi, ceilingDbi: ceiling,
    apertureLimited: areaM2 / (lambda0 * lambda0) > 1,
    best,
    // the bound that actually applies to the winner, i.e. for its own height
    bestBoundDbi: best ? best.boundDbi : ceiling,
    bestAnyPattern: perArch[0] || null,
    perArch,
    // how much of the theoretical ceiling a real antenna on this board reaches
    realisableFraction: best ? fromDB(best.gainDbi - best.boundDbi) : 0,
  };
}

/** Convenience: the best non-rejected candidate. */
export function bestOf(results) {
  return results.candidates.find((c) => c.verdict !== 'rejected' && c.verdict !== 'error') || results.candidates[0];
}

export { recommendGroundSize, fromDB };
