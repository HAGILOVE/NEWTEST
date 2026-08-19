/**
 * Antenna archetype library.
 *
 * Every entry carries a quantitative model so the recommender ranks candidates
 * on computed numbers, not on a lookup table. Gain models come from the
 * standard references:
 *   patch family      - cavity model (patch.js)
 *   Yagi              - Ehrenspeck & Poehler boom-length curve
 *   horn / reflector  - aperture theory with published efficiency factors
 *   helix             - Kraus axial-mode formula
 *   arrays            - element gain + array factor - computed feed loss
 *   small antennas    - Chu/McLean-bounded, with realistic loading efficiency
 */
import { C0, toDB, fromDB, clamp } from './constants.js';
import { solvePatch, patchWidth, compositeEr, stackedBandwidthFactor } from './patch.js';
import { lineLossDbPerM, synthesizeWidth, epsEffStatic } from './microstrip.js';
import { chuQ, maxFractionalBandwidth, harringtonDirectivity, beamwidthFromDirectivity } from './limits.js';

const GHZ = 1e9;

/** Corporate feed-network loss of an N-element planar array [dB]. */
export function arrayFeedLoss(n, ctx, spacingLambda = 0.7) {
  const { f, material, h, sigma, lambda0 } = ctx;
  const w50 = synthesizeWidth(material.er, 50, h);
  const loss = lineLossDbPerM({ er: material.er, df: material.df, w: w50, h, f, sigma });
  const epsEff = epsEffStatic(material.er, w50, h);
  const lambdaG = lambda0 / Math.sqrt(epsEff);
  const side = Math.sqrt(Math.max(n, 1));
  // Mean electrical path from the input port to an element in a corporate tree
  const meanPath = 0.75 * side * spacingLambda * lambdaG + 2 * lambdaG;
  const lineLossDb = loss.total * meanPath;
  const levels = Math.max(Math.ceil(Math.log2(Math.max(n, 1))), 0);
  const junctionLossDb = 0.08 * levels;      // T-junction + bend discontinuities
  const taperLossDb = n >= 8 ? 0.6 : 0.15;   // amplitude taper for sidelobe control
  return {
    total: lineLossDb + junctionLossDb + taperLossDb,
    line: lineLossDb, junction: junctionLossDb, taper: taperLossDb,
    meanPathMm: meanPath * 1e3, levels,
  };
}

/** Helper: build a size record in mm. */
const mm = (w, l, hgt) => ({ w: w * 1e3, l: l * 1e3, h: hgt * 1e3 });

/** Standard patch solution for the current context (cached by the caller). */
function patchOf(ctx, hOverride) {
  const h = hOverride ?? ctx.h;
  return solvePatch({ f: ctx.f, er: ctx.material.er, df: ctx.material.df, h, sigma: ctx.sigma });
}

export const ARCHETYPES = [
  // ======================================================= microstrip family
  {
    id: 'patch', name: 'Rectangular microstrip patch', nameKo: '사각 마이크로스트립 패치',
    category: 'Microstrip', pattern: 'directional', pol: ['linear', 'circular'],
    fRange: [0.3e9, 90e9], profile: 'planar', complexity: 1, cost: 1,
    summary: 'The default low-profile directional element. One etched layer, no assembly, fully described by the cavity model.',
    model(ctx) {
      const s = patchOf(ctx);
      const bw = s.fbw2 * 100;
      return {
        gainDbi: s.gainDbi, efficiency: s.etaSpace, bwPct: bw,
        size: mm(s.W, s.L, ctx.h), patch: s,
        dims: { 'Patch W': s.W * 1e3, 'Patch L': s.L * 1e3, 'Substrate h': ctx.h * 1e3 },
        notes: [
          `TM10 cavity mode, Q_total = ${s.Qt.toFixed(0)} (radiation ${s.Qrad.toFixed(0)}, dielectric ${s.Qd.toFixed(0)}).`,
          `Edge resistance ${s.Rin.toFixed(0)} ohm - use an inset or quarter-wave transformer to reach 50 ohm.`,
        ],
      };
    },
  },
  {
    id: 'patchAir', name: 'Suspended / air-gap patch', nameKo: '공기층 부양 패치',
    category: 'Microstrip', pattern: 'directional', pol: ['linear', 'circular'],
    fRange: [0.3e9, 40e9], profile: 'planar', complexity: 2, cost: 2,
    summary: 'Thin PCB carrier held above the ground by spacers so the field lives in air: near-lossless, wide band, largest footprint.',
    model(ctx) {
      const gap = clamp(0.035 * ctx.lambda0, 1.5e-3, 12e-3);
      const carrier = Math.min(ctx.h, 0.8e-3);
      const comp = compositeEr([
        { h: gap, er: 1.0006, df: 0 },
        { h: carrier, er: ctx.material.er, df: ctx.material.df },
      ]);
      const s = solvePatch({ f: ctx.f, er: comp.er, df: comp.df, h: comp.h, sigma: ctx.sigma });
      return {
        gainDbi: s.gainDbi, efficiency: s.etaSpace, bwPct: s.fbw2 * 100,
        size: mm(s.W, s.L, comp.h), patch: s,
        dims: { 'Patch W': s.W * 1e3, 'Patch L': s.L * 1e3, 'Air gap': gap * 1e3, 'Carrier': carrier * 1e3, 'Total h': comp.h * 1e3 },
        notes: [
          `Composite eps_r = ${comp.er.toFixed(3)}, tan(delta) = ${comp.df.toFixed(5)} over ${(comp.h * 1e3).toFixed(2)} mm.`,
          'Needs M2/M3 nylon spacers or a machined frame; gap tolerance directly sets the resonance.',
        ],
      };
    },
  },
  {
    id: 'patchStacked', name: 'Stacked (parasitic) patch', nameKo: '적층 기생 패치',
    category: 'Microstrip', pattern: 'directional', pol: ['linear', 'circular'],
    fRange: [0.5e9, 80e9], profile: 'planar', complexity: 3, cost: 3,
    summary: 'A parasitic patch above the driven one adds a second resonance: 2.5-3x the bandwidth for ~1 dB more gain.',
    model(ctx) {
      const s = patchOf(ctx, Math.min(ctx.h * 2.2, 0.06 * ctx.lambda0));
      const factor = stackedBandwidthFactor(1);
      return {
        gainDbi: s.gainDbi + 0.9, efficiency: s.etaSpace, bwPct: s.fbw2 * 100 * factor,
        size: mm(s.W * 1.05, s.L * 1.05, ctx.h * 3.2), patch: s,
        dims: { 'Driven W': s.W * 1e3, 'Driven L': s.L * 1e3, 'Parasitic W': s.W * 1.06 * 1e3, 'Parasitic L': s.L * 1.06 * 1e3, 'Layer gap': ctx.h * 2 * 1e3 },
        notes: [
          `Two coupled resonators: VSWR-2 bandwidth multiplied by ~${factor.toFixed(1)}.`,
          'Tune the parasitic 3-6 % larger than the driven patch and set the coupling with the interlayer height.',
        ],
      };
    },
  },
  {
    id: 'patchApertureCoupled', name: 'Aperture-coupled patch', nameKo: '개구 결합 패치',
    category: 'Microstrip', pattern: 'directional', pol: ['linear', 'circular'],
    fRange: [1e9, 90e9], profile: 'planar', complexity: 4, cost: 3,
    summary: 'Feed line on a separate layer couples through a ground slot: no probe inductance, clean pattern, feed network fully shielded from the radiator.',
    model(ctx) {
      const s = patchOf(ctx, Math.min(ctx.h * 1.6, 0.05 * ctx.lambda0));
      return {
        gainDbi: s.gainDbi + 0.3, efficiency: s.etaSpace * 0.97, bwPct: s.fbw2 * 100 * 1.7,
        size: mm(s.W, s.L, ctx.h * 2.4), patch: s,
        dims: { 'Patch W': s.W * 1e3, 'Patch L': s.L * 1e3, 'Slot length': s.W * 0.4 * 1e3, 'Stub length': (s.lambda0 / Math.sqrt(ctx.material.er)) * 0.12 * 1e3 },
        notes: [
          'Slot length ~0.4 x patch width; open stub past the slot tunes out the residual reactance.',
          'Back radiation through the slot is typically -18 to -22 dB; add a reflector layer if F/B matters.',
        ],
      };
    },
  },
  {
    id: 'patchArray', minGainDbi: 8, name: 'Microstrip patch array (corporate feed)', nameKo: '패치 배열 안테나',
    category: 'Microstrip', pattern: 'directional', pol: ['linear', 'circular'],
    fRange: [0.7e9, 90e9], profile: 'planar', complexity: 3, cost: 3,
    summary: 'The standard way to buy gain on a PCB: N elements give 10*log10(N) minus a feed loss that grows with N and with the substrate Df.',
    model(ctx) {
      const s = patchOf(ctx);
      const need = ctx.targetGainDbi ?? s.gainDbi + 6;
      let best = null;
      for (const n of [2, 4, 8, 16, 32, 64, 128, 256]) {
        const fl = arrayFeedLoss(n, ctx);
        const g = s.gainDbi + 10 * Math.log10(n) - fl.total;
        const side = Math.ceil(Math.sqrt(n));
        const spacing = 0.7 * ctx.lambda0;
        const dim = side * spacing;
        const cand = { n, g, fl, dim, side };
        if (!best) best = cand;
        if (g >= need && !best.hit) { best = { ...cand, hit: true }; break; }
        if (g > best.g) best = cand;
        if (ctx.maxDimM && dim > ctx.maxDimM) break;
      }
      const bwPen = 0.85; // feed network narrows the match slightly
      return {
        gainDbi: best.g, efficiency: s.etaSpace * fromDB(-best.fl.total), bwPct: s.fbw2 * 100 * bwPen,
        size: mm(best.dim, best.dim, ctx.h), patch: s, count: best.n,
        dims: { 'Elements': best.n, 'Grid': `${best.side} x ${Math.ceil(best.n / best.side)}`, 'Spacing': 0.7 * ctx.lambda0 * 1e3, 'Array side': best.dim * 1e3 },
        notes: [
          `${best.n} elements, feed loss ${best.fl.total.toFixed(2)} dB (line ${best.fl.line.toFixed(2)}, junctions ${best.fl.junction.toFixed(2)}, taper ${best.fl.taper.toFixed(2)}).`,
          `0.7 lambda spacing keeps the grating lobe out to ${(Math.asin(clamp(1 / 0.7 - 1, -1, 1)) * 180 / Math.PI).toFixed(0)} deg scan.`,
          best.fl.total > 2 ? 'Feed loss dominates - switch to a lower-Df laminate, SIW or a series-fed topology.' : 'Feed loss is acceptable for this element count.',
        ],
      };
    },
  },
  {
    id: 'seriesArray', minGainDbi: 8, name: 'Series-fed patch column', nameKo: '직렬 급전 패치 열',
    category: 'Microstrip', pattern: 'directional', pol: ['linear'],
    fRange: [2e9, 90e9], profile: 'planar', complexity: 3, cost: 2,
    summary: 'Patches strung along one line - minimal feed copper, so it beats a corporate feed on lossy substrates. Beam squints with frequency.',
    model(ctx) {
      const s = patchOf(ctx);
      const n = clamp(Math.round(Math.pow(10, ((ctx.targetGainDbi ?? s.gainDbi + 6) - s.gainDbi) / 10)), 2, 16);
      const fl = arrayFeedLoss(n, ctx, 0.5).total * 0.45;
      const squint = 2.5 * n / 8; // deg per % frequency shift
      return {
        gainDbi: s.gainDbi + 10 * Math.log10(n) - fl, efficiency: s.etaSpace * fromDB(-fl),
        bwPct: Math.min(s.fbw2 * 100, 100 / (n * 1.5)),
        size: mm(s.W * 1.4, n * 0.85 * ctx.lambda0, ctx.h), patch: s, count: n,
        dims: { 'Elements': n, 'Column length': n * 0.85 * ctx.lambda0 * 1e3, 'Element pitch': 0.85 * ctx.lambda0 * 1e3 },
        notes: [
          `${n} series elements, feed loss only ${fl.toFixed(2)} dB.`,
          `Beam squint ~${squint.toFixed(1)} deg per 1 % frequency change - unusable for wideband, ideal for FMCW radar columns.`,
        ],
      };
    },
  },
  {
    id: 'siwSlotArray', minGainDbi: 12, name: 'SIW slot array', nameKo: 'SIW 슬롯 배열',
    category: 'Waveguide', pattern: 'directional', pol: ['linear'],
    fRange: [8e9, 170e9], profile: 'planar', complexity: 4, cost: 4,
    summary: 'Substrate-integrated waveguide replaces the lossy microstrip feed with a via-fenced waveguide: the mmWave answer to feed loss.',
    model(ctx) {
      const s = patchOf(ctx);
      const n = clamp(Math.round(Math.pow(10, ((ctx.targetGainDbi ?? 18) - 5.5) / 10)), 4, 512);
      const fl = 0.25 + 0.12 * Math.log2(Math.max(n, 2)); // SIW loss is ~3x lower than microstrip
      const side = Math.ceil(Math.sqrt(n));
      const dim = side * 0.75 * ctx.lambda0;
      const aWaveguide = C0 / (2 * ctx.f * Math.sqrt(ctx.material.er)) * 1.05;
      return {
        gainDbi: 5.5 + 10 * Math.log10(n) - fl, efficiency: fromDB(-fl) * 0.92,
        bwPct: 8, size: mm(dim, dim, ctx.h), count: n,
        dims: { 'Slots': n, 'SIW width a': aWaveguide * 1e3, 'Via pitch': (0.15 * ctx.lambda0 / Math.sqrt(ctx.material.er)) * 1e3, 'Array side': dim * 1e3 },
        notes: [
          `SIW broad-wall width a = ${(aWaveguide * 1e3).toFixed(2)} mm for the TE10 cutoff at ${(ctx.f / GHZ * 0.8).toFixed(1)} GHz.`,
          'Via pitch must stay under 0.2 lambda_g and via diameter above 0.5 x pitch to stop leakage.',
          `Feed loss ${fl.toFixed(2)} dB versus ${arrayFeedLoss(n, ctx).total.toFixed(2)} dB for a microstrip corporate feed.`,
        ],
      };
    },
    unusedSubstrate: false,
  },
  {
    id: 'dra', name: 'Dielectric resonator antenna (DRA)', nameKo: '유전체 공진기 안테나',
    category: 'Resonator', pattern: 'directional', pol: ['linear', 'circular'],
    fRange: [1e9, 100e9], profile: '3d', complexity: 4, cost: 3,
    summary: 'A block of low-loss ceramic resonating in a HEM mode. No conductor loss at all, so it beats every metal antenna above ~30 GHz.',
    model(ctx) {
      const erD = clamp(ctx.material.er >= 6 ? ctx.material.er : 10, 6, 40);
      // Rectangular DRA, HEM11 mode: a ~ lambda0 / (2*sqrt(er)) with shape factors
      const a = ctx.lambda0 / (2.2 * Math.sqrt(erD));
      const Qr = 0.01007 * Math.pow(erD, 1.3) * 12;   // approximate radiation Q
      const bw = ((2 - 1) / (Qr * Math.sqrt(2))) * 100;
      const eff = 1 / (1 + ctx.material.df * Qr);
      return {
        gainDbi: toDB(5.5 * eff), efficiency: eff, bwPct: clamp(bw, 2, 25),
        size: mm(a * 1.6, a * 1.6, a),
        dims: { 'DR width': a * 1.6 * 1e3, 'DR height': a * 1e3, 'eps_r (DR)': erD },
        notes: [
          `HEM11-delta mode in eps_r = ${erD} ceramic; radiation Q ~ ${Qr.toFixed(0)}.`,
          'Zero conductor loss - efficiency is set only by the ceramic tan(delta) and the feed.',
          'Bonding the block with a repeatable glue-line thickness is the main production risk.',
        ],
      };
    },
  },

  // ============================================================ omni family
  {
    id: 'monopole', name: 'Quarter-wave monopole / whip', nameKo: '1/4파장 모노폴',
    category: 'Wire', pattern: 'omni', pol: ['linear'],
    fRange: [0.03e9, 20e9], profile: '3d', complexity: 1, cost: 1,
    summary: 'The reference omnidirectional element: one quarter-wave conductor over a ground plane. Nothing is cheaper or more broadband per volume.',
    model(ctx) {
      const len = 0.238 * ctx.lambda0;    // 0.25 lambda less the end-effect shortening
      const gndR = ctx.maxDimM ? ctx.maxDimM / 2 : 0.25 * ctx.lambda0;
      const rL = gndR / ctx.lambda0;
      const penalty = -3.4 * Math.exp(-rL / 0.22);
      return {
        gainDbi: 5.15 + penalty, efficiency: 0.95, bwPct: 12,
        size: mm(0.006, 0.006, len),
        dims: { 'Element length': len * 1e3, 'Ground radius': gndR * 1e3, 'Element diameter': 2 },
        notes: [
          `Ideal 5.15 dBi over an infinite ground; ${penalty.toFixed(1)} dB for the ${(rL).toFixed(2)} lambda ground radius here.`,
          'Pattern is a torus - a null straight up. Do not use it if the link can pass overhead.',
        ],
      };
    },
  },
  {
    id: 'dipole', name: 'Half-wave dipole (printed or wire)', nameKo: '반파장 다이폴',
    category: 'Wire', pattern: 'omni', pol: ['linear'],
    fRange: [0.03e9, 60e9], profile: 'planar', complexity: 1, cost: 1,
    summary: 'Ground-plane-independent omnidirectional reference. Printed on a thin substrate it is the cheapest 2 dBi element that exists.',
    model(ctx) {
      const eeff = (ctx.material.er + 1) / 2;
      const len = 0.47 * ctx.lambda0 / Math.sqrt(ctx.material.er > 1.5 ? eeff : 1);
      const eff = 1 / (1 + ctx.material.df * 8);
      return {
        gainDbi: toDB(1.64 * eff), efficiency: eff, bwPct: 16,
        size: mm(len, 0.01, ctx.h),
        dims: { 'Total length': len * 1e3, 'Arm length': len / 2 * 1e3, 'Feed gap': 1 },
        notes: [
          'Needs a balun (or a differential driver) - feeding it with unbalanced coax puts current on the cable shield and wrecks the pattern.',
          `${ctx.material.er > 1.5 ? `Printed on eps_r = ${ctx.material.er.toFixed(2)}, so the arms shorten to ${(len * 1e3).toFixed(1)} mm total.` : 'In free space / on foam the arms stay at the full half-wavelength.'}`,
        ],
      };
    },
  },
  {
    id: 'pifa', name: 'PIFA (planar inverted-F)', nameKo: 'PIFA 평면 역F 안테나',
    category: 'Small', pattern: 'hemispheric', pol: ['linear'],
    fRange: [0.4e9, 12e9], profile: 'planar', complexity: 2, cost: 1,
    summary: 'The mobile-device workhorse: a shorted quarter-wave patch. Half the footprint of a patch, ground-referenced, easy multi-band.',
    model(ctx) {
      const W = patchWidth(ctx.f, ctx.material.er) * 0.55;
      const L = C0 / (4 * ctx.f * Math.sqrt(epsEffStatic(ctx.material.er, W, ctx.h))) * 0.92;
      const height = clamp(0.02 * ctx.lambda0, 2e-3, 10e-3);
      const a = Math.sqrt(W * W + L * L + height * height) / 2;
      const bwMax = maxFractionalBandwidth(a, ctx.lambda0, 0.75, 2) * 100;
      const eff = clamp(0.75 - ctx.material.df * 6, 0.3, 0.92);
      return {
        gainDbi: toDB(2.2 * eff), efficiency: eff, bwPct: clamp(bwMax * 0.55, 1.5, 20),
        size: mm(W, L, height),
        dims: { 'Plate W': W * 1e3, 'Plate L': L * 1e3, 'Height': height * 1e3, 'Short width': W * 0.25 * 1e3 },
        notes: [
          `ka = ${((2 * Math.PI * a) / ctx.lambda0).toFixed(2)}; the Chu bound caps this volume at ${bwMax.toFixed(1)} % bandwidth.`,
          'The chassis is part of the antenna - the ground plane length, not the PIFA, usually sets the low-band bandwidth.',
        ],
      };
    },
  },
  {
    id: 'ifa', name: 'IFA / meandered monopole (chip-antenna class)', nameKo: 'IFA·미앤더 모노폴',
    category: 'Small', pattern: 'hemispheric', pol: ['linear'],
    fRange: [0.4e9, 10e9], profile: 'planar', complexity: 1, cost: 1,
    summary: 'A single etched trace at the board edge. Zero BOM cost, but the efficiency is entirely at the mercy of the ground plane and the enclosure.',
    model(ctx) {
      const trace = 0.24 * ctx.lambda0;
      const a = 0.055 * ctx.lambda0;
      const bwMax = maxFractionalBandwidth(a, ctx.lambda0, 0.6, 2) * 100;
      const eff = clamp(0.62 - ctx.material.df * 8, 0.2, 0.85);
      return {
        gainDbi: toDB(1.9 * eff), efficiency: eff, bwPct: clamp(bwMax * 0.6, 2, 15),
        size: mm(0.12 * ctx.lambda0, 0.035 * ctx.lambda0, ctx.h),
        dims: { 'Trace length': trace * 1e3, 'Keep-out W': 0.12 * ctx.lambda0 * 1e3, 'Keep-out H': 0.035 * ctx.lambda0 * 1e3 },
        notes: [
          'Requires a ground keep-out under the whole element and at least 0.1 lambda of clearance to metal/battery.',
          `Expect ${(eff * 100).toFixed(0)} % efficiency in free space and 10-20 points less once it is inside a plastic housing next to a hand.`,
        ],
      };
    },
  },
  {
    id: 'collinear', minGainDbi: 4, name: 'Collinear omni array (COCO / sleeve stack)', nameKo: '동일선상 옴니 배열',
    category: 'Wire', pattern: 'omni', pol: ['linear'],
    fRange: [0.1e9, 12e9], profile: '3d', complexity: 3, cost: 2,
    summary: 'Stacked in-phase half-wave sections squash the doughnut toward the horizon: the only practical way past ~4 dBi while staying omnidirectional.',
    model(ctx) {
      const need = ctx.targetGainDbi ?? 6;
      const n = clamp(Math.round(Math.pow(10, (need - 2.15 + 0.6) / 10)), 2, 16);
      const loss = 0.15 * n;
      const len = n * 0.5 * ctx.lambda0 * 1.05;
      return {
        gainDbi: 2.15 + 10 * Math.log10(n) - loss, efficiency: fromDB(-loss),
        bwPct: clamp(14 / Math.sqrt(n), 2, 12), size: mm(0.012, 0.012, len), count: n,
        dims: { 'Sections': n, 'Overall length': len * 1e3, 'Section length': 0.5 * ctx.lambda0 * 1.05 * 1e3 },
        notes: [
          `${n} co-phased sections; elevation beamwidth narrows to ~${(51 / n).toFixed(0)} deg, so mounting tilt becomes critical.`,
          'Phasing-line loss and current-balance errors are what limit this in practice, not the array factor.',
        ],
      };
    },
  },
  {
    id: 'biconical', name: 'Biconical / discone', nameKo: '바이코니컬·디스콘',
    category: 'Wire', pattern: 'omni', pol: ['linear'],
    fRange: [0.02e9, 40e9], profile: '3d', complexity: 3, cost: 3,
    summary: 'Decade-plus bandwidth with an omni pattern. The standard EMC and spectrum-monitoring antenna.',
    model(ctx) {
      return {
        gainDbi: 2.0, efficiency: 0.95, bwPct: 160,
        size: mm(0.5 * ctx.lambda0, 0.5 * ctx.lambda0, 0.35 * ctx.lambda0),
        dims: { 'Disc diameter': 0.5 * ctx.lambda0 * 1e3, 'Cone slant': 0.28 * ctx.lambda0 * 1e3, 'Cone angle': 60 },
        notes: [
          'Bandwidth is set by the lowest frequency (cone slant ~ lambda/4 there); the top end is limited only by the feed transition.',
          'Machined or sheet-metal part - not a PCB antenna.',
        ],
      };
    },
    ignoreSubstrate: true,
  },
  {
    id: 'loopSmall', name: 'Small loop / NFC coil', nameKo: '소형 루프 안테나',
    category: 'Small', pattern: 'omni', pol: ['linear'],
    fRange: [0.001e9, 3e9], profile: 'planar', complexity: 1, cost: 1,
    summary: 'Magnetic-field antenna. Immune to nearby dielectric loading, which is why it survives inside metal-rich products - but radiation resistance falls as (circumference/lambda)^4.',
    model(ctx) {
      const r = clamp(0.02 * ctx.lambda0, 2e-3, 0.05);
      const C = 2 * Math.PI * r;
      const Rrad = 20 * Math.pow(Math.PI, 2) * Math.pow(C / ctx.lambda0, 4);
      const Rloss = 0.5; // ohm, typical for a small etched loop with a tuning cap
      const eff = Rrad / (Rrad + Rloss);
      return {
        gainDbi: toDB(1.5 * eff), efficiency: eff, bwPct: clamp(3 * eff, 0.2, 6),
        size: mm(2 * r, 2 * r, ctx.h),
        dims: { 'Loop radius': r * 1e3, 'Circumference/lambda': C / ctx.lambda0, 'R_rad': Rrad },
        notes: [
          `Radiation resistance only ${Rrad.toFixed(3)} ohm against ~${Rloss} ohm of loss - efficiency ${(eff * 100).toFixed(1)} %.`,
          'Use only where the size budget forbids anything else, or below ~100 MHz where everything is electrically small.',
        ],
      };
    },
  },

  // ====================================================== directional / high gain
  {
    id: 'yagi', minGainDbi: 8, name: 'Yagi-Uda array', nameKo: '야기-우다 배열',
    category: 'Wire', pattern: 'directional', pol: ['linear'],
    fRange: [0.05e9, 40e9], profile: '3d', complexity: 2, cost: 2,
    summary: 'Best gain per unit cost of any antenna up to ~16 dBi. One driven element, one reflector, N directors on a boom.',
    model(ctx) {
      const need = ctx.targetGainDbi ?? 12;
      // Ehrenspeck-Poehler: G ~ 10.2 + 6.0*log10(boom/lambda) for optimised designs
      const boomL = clamp(Math.pow(10, (need - 10.2) / 6.0), 0.3, 12);
      const g = 10.2 + 6.0 * Math.log10(boomL);
      const nDir = clamp(Math.round(boomL / 0.3), 1, 30);
      return {
        gainDbi: g, efficiency: 0.93, bwPct: clamp(9 - 0.5 * nDir, 2, 9),
        size: mm(0.5 * ctx.lambda0, boomL * ctx.lambda0, 0.02 * ctx.lambda0), count: nDir + 2,
        dims: { 'Boom length': boomL * ctx.lambda0 * 1e3, 'Directors': nDir, 'Reflector': 0.49 * ctx.lambda0 * 1e3, 'Driven': 0.47 * ctx.lambda0 * 1e3 },
        notes: [
          `${nDir} director${nDir === 1 ? '' : 's'} on a ${boomL.toFixed(2)} lambda boom. Gain follows boom length, not element count - adding elements to a short boom buys almost nothing.`,
          'Element lengths must hold ~0.5 % tolerance; the design is narrowband by construction.',
        ],
      };
    },
    ignoreSubstrate: true,
  },
  {
    id: 'quasiYagi', name: 'Printed quasi-Yagi', nameKo: '인쇄형 준-야기',
    category: 'Microstrip', pattern: 'directional', pol: ['linear'],
    fRange: [1e9, 90e9], profile: 'planar', complexity: 3, cost: 2,
    summary: 'Yagi geometry etched on a board with the ground plane acting as the reflector. End-fire from a flat PCB - ideal for edge-firing radar and Wi-Fi sectors.',
    model(ctx) {
      const need = clamp(ctx.targetGainDbi ?? 8, 5, 13);
      const boomL = clamp(Math.pow(10, (need - 7.4) / 6.0), 0.2, 3);
      const eff = clamp(0.9 - ctx.material.df * 10, 0.35, 0.92);
      return {
        gainDbi: 7.4 + 6.0 * Math.log10(boomL) + toDB(eff), efficiency: eff, bwPct: 22,
        size: mm(0.55 * ctx.lambda0, boomL * ctx.lambda0, ctx.h),
        dims: { 'Board length': boomL * ctx.lambda0 * 1e3, 'Directors': clamp(Math.round(boomL / 0.28), 1, 8), 'Driver length': 0.42 * ctx.lambda0 / Math.sqrt((ctx.material.er + 1) / 2) * 1e3 },
        notes: [
          'Fires along the board edge, so it fits products where a broadside patch cannot point the right way.',
          'Wide bandwidth (~20 %) because the microstrip-to-slotline balun is inherently broadband.',
        ],
      };
    },
  },
  {
    id: 'lpda', minGainDbi: 6, name: 'Log-periodic dipole array (LPDA)', nameKo: '로그 주기 다이폴 배열',
    category: 'Wire', pattern: 'directional', pol: ['linear'],
    fRange: [0.03e9, 40e9], profile: 'planar', complexity: 3, cost: 3,
    summary: 'Constant gain and impedance over a decade. When one antenna must cover 700 MHz to 6 GHz, this is the answer.',
    model(ctx) {
      const tau = 0.9, sigma = 0.16;
      const g = 7.5 + 20 * (tau - 0.85);
      return {
        gainDbi: g, efficiency: 0.9, bwPct: 120,
        size: mm(0.55 * ctx.lambda0, 1.6 * ctx.lambda0, ctx.h),
        dims: { 'tau': tau, 'sigma': sigma, 'Longest element': 0.5 * ctx.lambda0 * 1e3, 'Boom': 1.6 * ctx.lambda0 * 1e3 },
        notes: [
          `tau = ${tau}, sigma = ${sigma} gives ~${g.toFixed(1)} dBi flat across the band; raise tau for more gain and a longer boom.`,
          'Size is set by the LOWEST frequency in the band - a 700 MHz low end means a ~215 mm longest element.',
        ],
      };
    },
    ignoreSubstrate: true,
  },
  {
    id: 'vivaldi', name: 'Vivaldi / tapered slot (TSA)', nameKo: '비발디 테이퍼 슬롯',
    category: 'Aperture', pattern: 'directional', pol: ['linear'],
    fRange: [1e9, 110e9], profile: 'planar', complexity: 3, cost: 2,
    summary: 'Exponentially tapered slot: multi-octave bandwidth, end-fire, and it tiles into wideband phased arrays.',
    model(ctx) {
      const len = 1.5 * ctx.lambda0;
      const eff = clamp(0.88 - ctx.material.df * 12, 0.3, 0.9);
      return {
        gainDbi: 9.0 + toDB(eff), efficiency: eff, bwPct: 130,
        size: mm(0.7 * ctx.lambda0, len, ctx.h),
        dims: { 'Taper length': len * 1e3, 'Aperture width': 0.7 * ctx.lambda0 * 1e3, 'Slot line width': 0.3, 'Opening rate': 0.06 },
        notes: [
          'Low-frequency limit set by the aperture width (~lambda/2), high-frequency limit by the slot-line feed and substrate modes.',
          'Substrate thickness must stay below ~0.03 lambda at the top frequency or the taper radiates into surface waves.',
        ],
      };
    },
  },
  {
    id: 'hornPyramidal', minGainDbi: 11, name: 'Pyramidal horn', nameKo: '피라미드 혼',
    category: 'Aperture', pattern: 'directional', pol: ['linear'],
    fRange: [1e9, 330e9], profile: '3d', complexity: 3, cost: 4,
    summary: 'The metrology standard. Predictable, low-loss, power-handling limited only by breakdown; used as the gain reference in every antenna range.',
    model(ctx) {
      const need = ctx.targetGainDbi ?? 17;
      const apEff = 0.51;
      const area = (fromDB(need) * ctx.lambda0 * ctx.lambda0) / (4 * Math.PI * apEff);
      const a = Math.sqrt(area * 1.5), b = area / a;
      const axial = Math.pow(a, 2) / (3 * ctx.lambda0);
      return {
        gainDbi: need, efficiency: 0.97, bwPct: 40,
        size: mm(a, b, axial),
        dims: { 'Aperture a': a * 1e3, 'Aperture b': b * 1e3, 'Axial length': axial * 1e3, 'Aperture eff.': apEff },
        notes: [
          `Aperture ${(a * 1e3).toFixed(1)} x ${(b * 1e3).toFixed(1)} mm at ${apEff * 100} % efficiency; axial length ${(axial * 1e3).toFixed(0)} mm keeps the phase error under lambda/8.`,
          'Machined aluminium or 3D-printed and plated. No dielectric, so no thermal derating worth mentioning.',
        ],
      };
    },
    ignoreSubstrate: true,
  },
  {
    id: 'hornSiw', minGainDbi: 8, name: 'SIW / substrate-integrated H-plane horn', nameKo: 'SIW 혼 안테나',
    category: 'Aperture', pattern: 'directional', pol: ['linear'],
    fRange: [20e9, 170e9], profile: 'planar', complexity: 4, cost: 4,
    summary: 'A horn built inside the board with via fences. Gives 8-12 dBi end-fire at mmWave with zero assembly.',
    model(ctx) {
      const eff = clamp(0.8 - ctx.material.df * 15, 0.3, 0.85);
      return {
        gainDbi: 10 + toDB(eff), efficiency: eff, bwPct: 25,
        size: mm(1.2 * ctx.lambda0, 1.6 * ctx.lambda0, ctx.h),
        dims: { 'Aperture width': 1.2 * ctx.lambda0 * 1e3, 'Flare length': 1.6 * ctx.lambda0 * 1e3, 'Via pitch': 0.15 * ctx.lambda0 / Math.sqrt(ctx.material.er) * 1e3 },
        notes: [
          'Needs a thick substrate (>0.1 lambda) or the H-plane aperture is too small - usually a bonded multi-core stack.',
          'Add a dielectric lens or a printed transition at the aperture to fix the E-plane pattern.',
        ],
      };
    },
  },
  {
    id: 'reflector', minGainDbi: 18, name: 'Parabolic reflector (prime focus)', nameKo: '파라볼릭 반사판',
    category: 'Aperture', pattern: 'directional', pol: ['linear', 'circular'],
    fRange: [0.3e9, 300e9], profile: '3d', complexity: 4, cost: 4,
    summary: 'The only practical route above ~30 dBi. Gain scales with diameter squared; everything else is feed and surface-tolerance engineering.',
    model(ctx) {
      const need = ctx.targetGainDbi ?? 30;
      const apEff = 0.60;
      const D = (ctx.lambda0 / Math.PI) * Math.sqrt(fromDB(need) / apEff);
      const rmsTol = ctx.lambda0 / 50;
      const beam = 70 * ctx.lambda0 / D;
      return {
        gainDbi: need, efficiency: 0.95, bwPct: 30,
        size: mm(D, D, D * 0.3),
        dims: { 'Dish diameter': D * 1e3, 'f/D': 0.4, 'Focal length': 0.4 * D * 1e3, 'Surface RMS': rmsTol * 1e3, '3 dB beamwidth': beam },
        notes: [
          `${(D * 1e3).toFixed(0)} mm dish at ${apEff * 100} % aperture efficiency; ${beam.toFixed(2)} deg beamwidth means the mount needs ${(beam / 4).toFixed(2)} deg pointing accuracy.`,
          `Surface RMS must stay under lambda/50 = ${(rmsTol * 1e3).toFixed(2)} mm (Ruze loss < 0.3 dB).`,
        ],
      };
    },
    ignoreSubstrate: true,
  },
  {
    id: 'reflectarray', minGainDbi: 20, name: 'Printed reflectarray', nameKo: '리플렉트어레이',
    category: 'Aperture', pattern: 'directional', pol: ['linear', 'circular'],
    fRange: [8e9, 300e9], profile: 'planar', complexity: 5, cost: 4,
    summary: 'A flat PCB that focuses like a dish: phase-shifting patches replace the parabolic surface. Reflector gain without the depth or the feed loss.',
    model(ctx) {
      const need = ctx.targetGainDbi ?? 28;
      const apEff = 0.45;
      const D = (ctx.lambda0 / Math.PI) * Math.sqrt(fromDB(need) / apEff);
      const cells = Math.pow(Math.round(D / (0.5 * ctx.lambda0)), 2);
      return {
        gainDbi: need, efficiency: 0.85, bwPct: 8,
        size: mm(D, D, ctx.h), count: cells,
        dims: { 'Panel side': D * 1e3, 'Unit cells': cells, 'Cell pitch': 0.5 * ctx.lambda0 * 1e3, 'Feed offset': 0.8 * D * 1e3 },
        notes: [
          'No feed-network loss at all - the illumination is through the air - but the spillover and phase-quantisation cost ~1.5 dB of aperture efficiency.',
          'Bandwidth is limited by the differential spatial phase delay across the panel; expect under 10 % for a flat design.',
        ],
      };
    },
  },
  {
    id: 'helixAxial', name: 'Axial-mode helix', nameKo: '축방향 헬릭스',
    category: 'Wire', pattern: 'directional', pol: ['circular'],
    fRange: [0.2e9, 12e9], profile: '3d', complexity: 3, cost: 2,
    summary: 'Naturally circularly polarised over a 1.7:1 band with no polariser. The classic satellite/telemetry uplink antenna.',
    model(ctx) {
      const need = ctx.targetGainDbi ?? 12;
      const Cl = 1.0, Sl = 0.24;   // circumference and pitch in wavelengths
      const n = clamp(Math.round(Math.pow(10, (need - toDB(15 * Cl * Cl * Sl)) / 10)), 3, 40);
      const g = toDB(15 * Cl * Cl * Sl * n);
      return {
        gainDbi: g, efficiency: 0.92, bwPct: 50,
        size: mm(Cl * ctx.lambda0 / Math.PI, Cl * ctx.lambda0 / Math.PI, n * Sl * ctx.lambda0), count: n,
        dims: { 'Turns': n, 'Diameter': (Cl * ctx.lambda0 / Math.PI) * 1e3, 'Pitch': Sl * ctx.lambda0 * 1e3, 'Axial length': n * Sl * ctx.lambda0 * 1e3, 'Ground dia.': 0.8 * ctx.lambda0 * 1e3 },
        notes: [
          `Kraus formula: G = 15*C^2*S*n with C = ${Cl} lambda, S = ${Sl} lambda, n = ${n} turns.`,
          `Axial ratio stays under 1.5 dB across roughly ${(0.75).toFixed(2)}-1.3 x f0. Long and mechanically awkward: ${(n * Sl * ctx.lambda0 * 1e3).toFixed(0)} mm.`,
        ],
      };
    },
    ignoreSubstrate: true,
  },
  {
    id: 'qha', name: 'Quadrifilar helix (QHA)', nameKo: '쿼드리필라 헬릭스',
    category: 'Wire', pattern: 'hemispheric', pol: ['circular'],
    fRange: [0.1e9, 3e9], profile: '3d', complexity: 4, cost: 3,
    summary: 'Cardioid circularly-polarised pattern with no ground plane. The standard GNSS/Iridium/weather-satellite antenna for handhelds and buoys.',
    model(ctx) {
      return {
        gainDbi: 3.5, efficiency: 0.85, bwPct: 12,
        size: mm(0.09 * ctx.lambda0, 0.09 * ctx.lambda0, 0.28 * ctx.lambda0),
        dims: { 'Diameter': 0.09 * ctx.lambda0 * 1e3, 'Length': 0.28 * ctx.lambda0 * 1e3, 'Turns': 0.5, 'Elements': 4 },
        notes: [
          'Wide CP beam down to the horizon with no ground plane - immune to the platform underneath it.',
          'Needs a 4-way 0/90/180/270 deg feed network (or a self-phased bifilar pair) which sets the axial-ratio quality.',
        ],
      };
    },
    ignoreSubstrate: true,
  },
  {
    id: 'slotCavity', name: 'Cavity-backed slot', nameKo: '캐비티 백 슬롯',
    category: 'Aperture', pattern: 'directional', pol: ['linear'],
    fRange: [1e9, 60e9], profile: 'planar', complexity: 4, cost: 3,
    summary: 'A slot with a metal cavity behind it: unidirectional, flush-mountable in a conductive surface, and immune to what is behind the panel.',
    model(ctx) {
      const eff = 0.9;
      return {
        gainDbi: 7.5, efficiency: eff, bwPct: 12,
        size: mm(0.6 * ctx.lambda0, 0.6 * ctx.lambda0, 0.25 * ctx.lambda0),
        dims: { 'Slot length': 0.48 * ctx.lambda0 * 1e3, 'Slot width': 0.05 * ctx.lambda0 * 1e3, 'Cavity depth': 0.25 * ctx.lambda0 * 1e3 },
        notes: [
          'Conformal - the only radiating feature is a slot, so it survives on aircraft skins and machine housings.',
          'Cavity depth ~lambda/4 for the reflection to add in phase; a shallower cavity costs bandwidth, not gain.',
        ],
      };
    },
  },
  {
    id: 'meDipole', name: 'Magneto-electric dipole', nameKo: '자기-전기 다이폴',
    category: 'Aperture', pattern: 'directional', pol: ['linear', 'circular'],
    fRange: [1e9, 60e9], profile: '3d', complexity: 4, cost: 3,
    summary: 'Complementary electric + magnetic dipole gives an unusually symmetric, stable pattern over 40-60 % bandwidth. Standard in modern base-station panels.',
    model(ctx) {
      return {
        gainDbi: 8.2, efficiency: 0.93, bwPct: 50,
        size: mm(0.5 * ctx.lambda0, 0.5 * ctx.lambda0, 0.25 * ctx.lambda0),
        dims: { 'Patch pair': 0.25 * ctx.lambda0 * 1e3, 'Vertical wall': 0.25 * ctx.lambda0 * 1e3, 'Ground': 0.9 * ctx.lambda0 * 1e3 },
        notes: [
          'E- and H-plane beamwidths track each other within a few degrees across the band - that is what makes it a base-station favourite.',
          'Needs a 3D (bent-sheet or multilayer) structure; not a single-layer etch.',
        ],
      };
    },
  },
  {
    id: 'lens', minGainDbi: 16, name: 'Dielectric lens (mmWave)', nameKo: '유전체 렌즈',
    category: 'Aperture', pattern: 'directional', pol: ['linear', 'circular'],
    fRange: [24e9, 300e9], profile: '3d', complexity: 4, cost: 3,
    summary: 'A moulded lens over a patch or SIW feed. At 60-140 GHz this is the cheapest route to 20+ dBi because the feed stays on the PCB.',
    model(ctx) {
      const need = ctx.targetGainDbi ?? 22;
      const apEff = 0.55;
      const D = (ctx.lambda0 / Math.PI) * Math.sqrt(fromDB(need) / apEff);
      const erL = 2.35;
      return {
        gainDbi: need, efficiency: 0.88, bwPct: 35,
        size: mm(D, D, D * 0.6),
        dims: { 'Lens diameter': D * 1e3, 'Lens eps_r': erL, 'Focal length': 0.7 * D * 1e3, 'Thickness': D * 0.35 * 1e3 },
        notes: [
          `Hyperbolic PTFE/PE lens (eps_r ~ ${erL}); add a lambda/4 matching groove or the front face reflects ~4 %.`,
          'Injection-moulded in volume - the lens itself is nearly free once the tool exists.',
        ],
      };
    },
    ignoreSubstrate: true,
  },
  {
    id: 'phasedArray', minGainDbi: 12, name: 'Beam-steering phased array (AiP)', nameKo: '위상 배열·빔 스티어링',
    category: 'Microstrip', pattern: 'steerable', pol: ['linear', 'circular'],
    fRange: [2e9, 170e9], profile: 'planar', complexity: 5, cost: 5,
    summary: 'Per-element phase control for electronic beam steering. Gain like an array, plus a scan angle - at the cost of a beamformer IC per few elements.',
    model(ctx) {
      const s = patchOf(ctx);
      const need = ctx.targetGainDbi ?? 20;
      const n = clamp(Math.pow(2, Math.round(Math.log2(Math.pow(10, (need - s.gainDbi + 1.5) / 10)))), 4, 1024);
      const side = Math.ceil(Math.sqrt(n));
      const scanLoss = 1.5; // cos-law at ~50 deg scan plus quantisation
      return {
        gainDbi: s.gainDbi + 10 * Math.log10(n) - 1.2, efficiency: s.etaSpace * 0.8,
        bwPct: s.fbw2 * 100, size: mm(side * 0.5 * ctx.lambda0, side * 0.5 * ctx.lambda0, ctx.h * 4), count: n,
        dims: { 'Elements': n, 'Grid': `${side} x ${side}`, 'Pitch': 0.5 * ctx.lambda0 * 1e3, 'Beamformer ICs': Math.ceil(n / 4) },
        notes: [
          `0.5 lambda pitch for grating-lobe-free scan to +/-60 deg; scan loss ~${scanLoss} dB at the edge of coverage.`,
          `Needs ${Math.ceil(n / 4)} four-channel beamformer ICs, calibration, and a thermal path for ~${(n * 0.15).toFixed(1)} W of front-end dissipation.`,
        ],
      };
    },
  },
];

export const ARCHETYPE_BY_ID = Object.fromEntries(ARCHETYPES.map((a) => [a.id, a]));

/** Evaluate one archetype in the given context, guarding against model errors. */
export function evaluate(arch, ctx) {
  try {
    const r = arch.model(ctx);
    // A model that produces NaN is broken, not merely pessimistic. Letting it
    // through poisons every sort it lands in, so it is reported as an error.
    if (!Number.isFinite(r.gainDbi) || !Number.isFinite(r.size.w)
        || !Number.isFinite(r.size.l) || !Number.isFinite(r.size.h)) {
      throw new Error('model returned a non-finite gain or size');
    }
    const D0 = fromDB(r.gainDbi) / Math.max(r.efficiency, 1e-3);
    const bw = beamwidthFromDirectivity(D0, arch.pattern === 'omni' ? 4 : 1);
    const maxDim = Math.max(r.size.w, r.size.l, r.size.h) / 1e3;
    return {
      ...r, arch,
      maxDimM: maxDim,
      beamwidth: arch.pattern === 'omni' ? { thetaE: bw.thetaE, thetaH: 360 } : bw,
      harringtonDbi: toDB(harringtonDirectivity(maxDim / 2, ctx.lambda0)),
      chuQ: chuQ((2 * Math.PI * (maxDim / 2)) / ctx.lambda0),
    };
  } catch (e) {
    return { arch, error: String(e && e.message ? e.message : e), gainDbi: -99, efficiency: 0, bwPct: 0, size: { w: 0, l: 0, h: 0 } };
  }
}
