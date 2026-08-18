/**
 * Thermal and high-power engine.
 *
 * Antennas fail thermally in three different ways and this module covers all
 * three:
 *   1. average power  -> the dielectric and conductor losses heat the laminate
 *                        until it passes Tg and the Dk (and the resonance)
 *                        walks away, or it delaminates.
 *   2. peak power     -> the edge E-field breaks down the air (Paschen) or the
 *                        dielectric, or multipacts in vacuum.
 *   3. temperature    -> even with no failure, TCDk and CTE detune the antenna.
 *
 * Heat transfer uses a lumped network: conduction through the substrate and
 * the via field, spreading into the ground plane, then natural or forced
 * convection plus grey-body radiation to ambient. The steady state is solved
 * by iteration because both convection and radiation depend on the surface
 * temperature.
 */
import { SIGMA_SB, ZERO_C, clamp, fromDB } from './constants.js';

/** Air properties at film temperature T [K] (1 atm, ideal-gas scaling). */
function airProps(Tfilm, pressurePa = 101325) {
  const rho = (pressurePa / (287.05 * Tfilm));
  const k = 0.0242 * Math.pow(Tfilm / 273.15, 0.83);      // [W/(m K)]
  const mu = 1.716e-5 * Math.pow(Tfilm / 273.15, 1.5) * (273.15 + 110.4) / (Tfilm + 110.4);
  const cp = 1005;
  const nu = mu / rho;
  const Pr = (mu * cp) / k;
  const beta = 1 / Tfilm;
  return { rho, k, mu, nu, Pr, beta, cp };
}

/**
 * Natural-convection coefficient [W/(m^2 K)].
 * Correlations: Churchill-Chu (vertical plate), McAdams (horizontal plate).
 */
export function naturalConvection(dT, area, perimeter, orientation = 'horizontalUp', Tamb = 25, pressurePa = 101325) {
  if (dT <= 0.01) return 0;
  const Ta = Tamb + ZERO_C;
  const Tfilm = Ta + dT / 2;
  const { k, nu, Pr, beta } = airProps(Tfilm, pressurePa);
  const Lc = orientation === 'vertical' ? Math.sqrt(area) : area / Math.max(perimeter, 1e-6);
  const Ra = (9.81 * beta * dT * Math.pow(Lc, 3) * Pr) / (nu * nu);
  let Nu;
  if (orientation === 'vertical') {
    const t = 1 + Math.pow(0.492 / Pr, 9 / 16);
    Nu = Math.pow(0.825 + (0.387 * Math.pow(Ra, 1 / 6)) / Math.pow(t, 8 / 27), 2);
  } else if (orientation === 'horizontalDown') {
    Nu = 0.27 * Math.pow(Math.max(Ra, 1), 0.25);
  } else {
    Nu = Ra < 1e7 ? 0.54 * Math.pow(Math.max(Ra, 1), 0.25) : 0.15 * Math.pow(Ra, 1 / 3);
  }
  return (Nu * k) / Lc;
}

/** Forced-convection coefficient for flow over a flat plate [W/(m^2 K)]. */
export function forcedConvection(velocity, length, Tamb = 25, dT = 20, pressurePa = 101325) {
  if (velocity <= 0) return 0;
  const Tfilm = Tamb + ZERO_C + dT / 2;
  const { k, nu, Pr } = airProps(Tfilm, pressurePa);
  const Re = (velocity * length) / nu;
  const Nu = Re < 5e5
    ? 0.664 * Math.sqrt(Re) * Math.cbrt(Pr)          // laminar
    : (0.037 * Math.pow(Re, 0.8) - 871) * Math.cbrt(Pr); // turbulent
  return (Math.max(Nu, 1) * k) / length;
}

/** Linearised radiation coefficient [W/(m^2 K)]. */
export function radiationCoefficient(Ts, Tamb, emissivity = 0.9) {
  const T1 = Ts + ZERO_C, T2 = Tamb + ZERO_C;
  return emissivity * SIGMA_SB * (T1 * T1 + T2 * T2) * (T1 + T2);
}

/**
 * Steady-state thermal solution of a planar antenna.
 *
 * @param p
 *   pInW          RF power delivered to the antenna port [W]
 *   efficiency    radiation efficiency (0..1) - the rest becomes heat
 *   mismatchGamma |Gamma| at the port (reflected power also heats the feed)
 *   areaM2        radiating/ground area available for heat spreading
 *   perimeterM    perimeter of that area
 *   material      substrate record (k, tg, tmax, density, cp)
 *   h             substrate thickness [m]
 *   tAmbC         ambient temperature [degC]
 *   airVelocity   forced-air speed [m/s], 0 for natural convection
 *   emissivity    surface emissivity (bare copper 0.05, solder mask 0.9)
 *   orientation   'horizontalUp' | 'horizontalDown' | 'vertical'
 *   altitudeM     altitude for the reduced-pressure convection derating
 *   viaCount      thermal vias tying the patch region to the ground plane
 *   viaDiaM       via barrel diameter
 *   heatsink      optional extra conductance [W/K]
 */
export function solveThermal(p) {
  const {
    pInW, efficiency, mismatchGamma = 0, areaM2, perimeterM, material, h,
    tAmbC = 25, airVelocity = 0, emissivity = 0.9, orientation = 'horizontalUp',
    altitudeM = 0, viaCount = 0, viaDiaM = 0.3e-3, viaPlatingM = 25e-6,
    heatsinkWperK = 0, bothSides = true,
  } = p;

  const pressurePa = 101325 * Math.pow(1 - 2.25577e-5 * altitudeM, 5.25588);

  // --- heat generated ------------------------------------------------------
  const pAccepted = pInW * (1 - mismatchGamma * mismatchGamma);
  const pDissipated = pAccepted * (1 - efficiency) + pInW * mismatchGamma * mismatchGamma * 0.3;

  // --- conduction through the substrate to the ground plane ----------------
  const rCond = h / (Math.max(material.k, 1e-4) * areaM2);
  // --- thermal vias in parallel (copper barrels) ---------------------------
  const aVia = Math.PI * viaDiaM * viaPlatingM;
  const rVia = viaCount > 0 ? h / (401 * aVia * viaCount) : Infinity;
  const rSpread = 1 / (2 * Math.max(material.kxy || material.k, 1e-4) * Math.sqrt(areaM2 / Math.PI) * 4);
  const rInternal = 1 / (1 / rCond + 1 / rVia) + rSpread;

  // --- iterate the surface temperature -------------------------------------
  const aSurf = areaM2 * (bothSides ? 2 : 1);
  let Ts = tAmbC + 10;
  let hConv = 0, hRad = 0;
  for (let i = 0; i < 200; i++) {
    const dT = Math.max(Ts - tAmbC, 0);
    hConv = airVelocity > 0
      ? forcedConvection(airVelocity, Math.sqrt(areaM2), tAmbC, dT, pressurePa)
      : naturalConvection(dT, areaM2, perimeterM, orientation, tAmbC, pressurePa);
    hRad = radiationCoefficient(Ts, tAmbC, emissivity);
    const gSurface = (hConv + hRad) * aSurf + heatsinkWperK;
    const rTotal = rInternal + 1 / Math.max(gSurface, 1e-9);
    const TsNew = tAmbC + pDissipated * rTotal;
    Ts = Ts + 0.35 * (TsNew - Ts);
    if (Math.abs(TsNew - Ts) < 1e-5) break;
  }
  const gSurface = (hConv + hRad) * aSurf + heatsinkWperK;
  const rTotal = rInternal + 1 / Math.max(gSurface, 1e-9);
  const tHotC = tAmbC + pDissipated * rTotal;

  // --- transient time constant --------------------------------------------
  const mass = material.density * areaM2 * h;
  const cTh = mass * material.cp;
  const tauS = cTh * rTotal;

  // --- limits --------------------------------------------------------------
  const tLimit = Math.min(material.tg - 20, material.tmax);
  const headroomK = tLimit - tHotC;
  const pMaxW = pDissipated > 1e-9
    ? pInW * ((tLimit - tAmbC) / Math.max(tHotC - tAmbC, 1e-9))
    : Infinity;

  return {
    pDissipatedW: pDissipated, pRadiatedW: pAccepted * efficiency,
    rConductionKperW: rCond, rViaKperW: rVia, rSpreadKperW: rSpread,
    rInternalKperW: rInternal, rSurfaceKperW: 1 / Math.max(gSurface, 1e-9),
    rTotalKperW: rTotal,
    hConv, hRad, pressurePa,
    tHotC, tAmbC, riseK: tHotC - tAmbC,
    tLimitC: tLimit, headroomK, safe: headroomK > 0,
    pMaxContinuousW: pMaxW,
    thermalCapacityJperK: cTh, tauSeconds: tauS,
    massG: mass * 1e3,
  };
}

/** Pulsed / duty-cycle temperature rise using the single-pole thermal model. */
export function pulsedRise(steadyRiseK, tauS, pulseS, periodS) {
  const duty = pulseS / periodS;
  const dcRise = steadyRiseK * duty;
  const pulseRise = steadyRiseK * (1 - Math.exp(-pulseS / tauS));
  return { duty, averageRiseK: dcRise, peakRiseK: dcRise + (pulseRise - dcRise) * (1 - Math.exp(-pulseS / tauS)), pulseOnlyRiseK: pulseRise };
}

/**
 * Paschen breakdown voltage of an air gap [V].
 * V = B*p*d / (ln(A*p*d) - ln(ln(1 + 1/gamma)))
 * A = 15 1/(cm*Torr), B = 365 V/(cm*Torr) for air, gamma = 0.01.
 */
export function paschenVoltage(gapM, pressurePa) {
  const pTorr = pressurePa / 133.322;
  const dCm = gapM * 100;
  const pd = pTorr * dCm;
  if (pd <= 1e-6) return Infinity;
  const A = 15, B = 365, gamma = 0.01;
  const denom = Math.log(A * pd) - Math.log(Math.log(1 + 1 / gamma));
  if (denom <= 0.05) return Infinity;    // left branch of the Paschen curve
  return (B * pd) / denom;
}

/**
 * Peak power handling.
 * The patch edge voltage for a given input power follows from the cavity Q:
 *   V_edge = sqrt(2 * P_acc * R_edge)   with a standing-wave enhancement of Q/2
 * for the field inside the substrate. Compared against both the laminate
 * dielectric strength and the air Paschen limit at the exposed edge.
 */
export function peakPowerLimit(p) {
  const { pPeakW, Redge = 200, h, material, altitudeM = 0, vswr = 1.5, gapAirM = null } = p;
  const pressurePa = 101325 * Math.pow(1 - 2.25577e-5 * altitudeM, 5.25588);
  const vswrFactor = (1 + (vswr - 1) / (vswr + 1));
  const vEdge = Math.sqrt(2 * pPeakW * Redge) * vswrFactor;
  const eField = vEdge / h;                       // V/m in the laminate
  const eBreak = material.vbd * 1e6;              // kV/mm -> V/m
  const vAir = paschenVoltage(gapAirM || h, pressurePa);

  const pMaxDielectric = Math.pow((eBreak * 0.5 * h) / vswrFactor, 2) / (2 * Redge);
  const pMaxAir = Math.pow((vAir * 0.6) / vswrFactor, 2) / (2 * Redge);

  return {
    vEdge, eFieldVperM: eField, eFieldKvPerMm: eField / 1e6,
    dielectricStrengthKvPerMm: material.vbd,
    paschenVoltage: vAir, pressurePa,
    marginDielectric: (eBreak * 0.5) / eField,
    pMaxPeakDielectricW: pMaxDielectric,
    pMaxPeakAirW: pMaxAir,
    pMaxPeakW: Math.min(pMaxDielectric, pMaxAir),
    safe: pPeakW < Math.min(pMaxDielectric, pMaxAir),
    multipactionRisk: altitudeM > 30000,
  };
}

/**
 * Resonance drift with temperature.
 * f0 ~ 1/(L*sqrt(er)), so
 *   df/f = -(1/2)*TCDk*dT - CTE_xy*dT
 * Both terms are usually negative-going in frequency for FR-4 (Dk falls with
 * temperature -> frequency rises; the copper expands -> frequency falls).
 */
export function frequencyDrift(material, f0, dT) {
  const dkTerm = -0.5 * material.tcdk * 1e-6 * dT;
  const cteTerm = -material.ctexy * 1e-6 * dT;
  const rel = dkTerm + cteTerm;
  return {
    relative: rel, deltaFHz: rel * f0, deltaFPpm: rel * 1e6,
    dkContribution: dkTerm * f0, cteContribution: cteTerm * f0,
  };
}

/**
 * How much of the impedance bandwidth the temperature drift eats.
 */
export function driftBudget(material, f0, tMinC, tMaxC, fracBw, refC = 25) {
  const dLow = frequencyDrift(material, f0, tMinC - refC).relative;
  const dHigh = frequencyDrift(material, f0, tMaxC - refC).relative;
  const span = Math.abs(dHigh - dLow);
  return {
    driftLow: dLow, driftHigh: dHigh, totalSpan: span,
    bandwidthConsumedPct: (span / fracBw) * 100,
    usableBwPct: (fracBw - span) * 100,
    ok: span < fracBw * 0.5,
  };
}

/** Conductor current density check for the feed line (IPC-2152 style). */
export function traceCurrentLimit(widthM, thicknessM, dTallowed = 20, external = true) {
  const areaMil2 = widthM * 1e3 / 0.0254 * (thicknessM * 1e3 / 0.0254);
  const k = external ? 0.048 : 0.024;
  const I = k * Math.pow(dTallowed, 0.44) * Math.pow(areaMil2, 0.725);
  return { currentA: I, areaMil2 };
}

/** RMS current in a 50-ohm feed for a given average power. */
export function feedCurrent(pW, z0 = 50) {
  return Math.sqrt(pW / z0);
}

export { clamp, fromDB };
