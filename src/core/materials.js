/**
 * Substrate / dielectric material database.
 *
 * Fields
 *  id            key
 *  name          display name
 *  family        grouping for the UI
 *  er            relative permittivity at `erRefF` (Hz), out-of-plane (z-axis)
 *  df            loss tangent at `erRefF`
 *  erRefF        frequency at which er/df are quoted [Hz]
 *  tcdk          thermal coefficient of Dk [ppm/degC]
 *  k             through-thickness thermal conductivity [W/(m*K)]
 *  kxy           in-plane thermal conductivity [W/(m*K)]
 *  cte           z-axis CTE [ppm/degC]
 *  ctexy         x/y CTE [ppm/degC]
 *  tg            glass transition / max continuous use temperature [degC]
 *  tmax          absolute max continuous operating temperature [degC]
 *  density       [kg/m^3]
 *  cp            specific heat [J/(kg*K)]
 *  vbd           dielectric strength [kV/mm]
 *  moisture      water absorption [%]
 *  cost          relative cost index (FR4 = 1.0)
 *  stock         typical available core thicknesses [m]
 *  fMax          frequency above which the material is not recommended [Hz]
 *  notes         engineering commentary shown in the UI
 *
 * Sources: manufacturer datasheets (Rogers, Isola, Taconic, DuPont, Panasonic,
 * Arlon, Kyocera), IPC-4101 slash sheets, and standard handbook values for
 * bulk dielectrics. Values are typical, not guaranteed; always confirm against
 * the lot-specific datasheet before release to manufacturing.
 */

export const MATERIALS = [
  // ---------------------------------------------------------------- air / foam
  {
    id: 'air', name: 'Air / vacuum gap', family: 'Air & foam',
    er: 1.0006, df: 0.0000, erRefF: 10e9, tcdk: 0, k: 0.026, kxy: 0.026,
    cte: 0, ctexy: 0, tg: 1000, tmax: 1000, density: 1.2, cp: 1005, vbd: 3.0,
    moisture: 0, cost: 0.1, stock: [1e-3, 2e-3, 3e-3, 4e-3, 5e-3, 6e-3, 8e-3, 10e-3], fMax: 300e9,
    notes: 'Loss-free reference dielectric. Needs a mechanical carrier (thin PCB, spacers or a machined frame). Highest bandwidth and efficiency per unit height, but the largest patch footprint and no conduction path for heat.',
  },
  {
    id: 'rohacell51', name: 'Rohacell 51 HF (PMI foam)', family: 'Air & foam',
    er: 1.065, df: 0.0017, erRefF: 10e9, tcdk: 0, k: 0.031, kxy: 0.031,
    cte: 33, ctexy: 33, tg: 180, tmax: 160, density: 52, cp: 1600, vbd: 2.0,
    moisture: 0.2, cost: 3.0, stock: [1e-3, 2e-3, 3e-3, 5e-3, 8e-3, 10e-3], fMax: 110e9,
    notes: 'Structural foam that behaves almost like air but can be bonded. Standard choice for wideband stacked patches and spaceborne arrays. Check bond-film Dk in the stack-up.',
  },
  {
    id: 'foamPP', name: 'PP foam spacer (generic)', family: 'Air & foam',
    er: 1.15, df: 0.0008, erRefF: 2.4e9, tcdk: 0, k: 0.04, kxy: 0.04,
    cte: 70, ctexy: 70, tg: 100, tmax: 85, density: 90, cp: 1900, vbd: 2.5,
    moisture: 0.05, cost: 0.6, stock: [1e-3, 2e-3, 3e-3, 5e-3], fMax: 20e9,
    notes: 'Low-cost consumer-grade spacer for 2.4/5 GHz WLAN patches. Watch thickness tolerance (typically +/-10 %) which directly modulates resonance.',
  },

  // ---------------------------------------------------------------- FR4 family
  {
    id: 'fr4', name: 'FR-4 (standard, Tg 140)', family: 'FR-4 / glass-epoxy',
    er: 4.30, df: 0.0200, erRefF: 1e9, tcdk: -200, k: 0.30, kxy: 0.60,
    cte: 70, ctexy: 15, tg: 140, tmax: 130, density: 1850, cp: 1100, vbd: 20,
    moisture: 0.15, cost: 1.0, stock: [0.2e-3, 0.4e-3, 0.8e-3, 1.0e-3, 1.6e-3, 2.4e-3, 3.2e-3], fMax: 6e9,
    notes: 'Cheapest and most available laminate. Df ~0.02 caps the radiation efficiency of any thin resonant structure; Dk varies +/-0.2 lot to lot and with glass-weave position. Practical antenna limit around 3 GHz unless it is only a carrier over air.',
  },
  {
    id: 'fr4hi', name: 'FR-4 high-Tg (Tg 170, low-Df)', family: 'FR-4 / glass-epoxy',
    er: 4.20, df: 0.0130, erRefF: 1e9, tcdk: -180, k: 0.35, kxy: 0.70,
    cte: 55, ctexy: 14, tg: 170, tmax: 150, density: 1880, cp: 1100, vbd: 22,
    moisture: 0.12, cost: 1.4, stock: [0.2e-3, 0.4e-3, 0.8e-3, 1.6e-3, 2.4e-3, 3.2e-3], fMax: 8e9,
    notes: 'Phenolic-cured high-Tg FR-4. Roughly 35 % lower Df than standard FR-4 and far better thermal cycling; still not an RF laminate above a few GHz.',
  },
  {
    id: 'megtron6', name: 'Panasonic Megtron 6 (R-5775)', family: 'Low-loss digital',
    er: 3.60, df: 0.0040, erRefF: 12e9, tcdk: -120, k: 0.50, kxy: 0.80,
    cte: 35, ctexy: 12, tg: 185, tmax: 170, density: 1900, cp: 1000, vbd: 25,
    moisture: 0.10, cost: 4.0, stock: [0.1e-3, 0.2e-3, 0.4e-3, 0.8e-3, 1.6e-3], fMax: 40e9,
    notes: 'Low-loss digital laminate. Good compromise when the antenna must share a stack-up with high-speed serial links; processes on standard PCB lines.',
  },
  {
    id: 'iteraMt40', name: 'Isola I-Tera MT40', family: 'Low-loss digital',
    er: 3.45, df: 0.0031, erRefF: 10e9, tcdk: -90, k: 0.45, kxy: 0.75,
    cte: 32, ctexy: 12, tg: 200, tmax: 180, density: 1880, cp: 1000, vbd: 24,
    moisture: 0.08, cost: 4.5, stock: [0.13e-3, 0.25e-3, 0.51e-3, 0.76e-3, 1.52e-3], fMax: 40e9,
    notes: 'Very tight Dk control across the panel, standard FR-4-like processing. Popular for mmWave-adjacent (24 GHz) radar boards that need volume pricing.',
  },

  // ---------------------------------------------------------------- PTFE / RF laminates
  {
    id: 'ro4003c', name: 'Rogers RO4003C', family: 'Hydrocarbon-ceramic',
    er: 3.55, df: 0.0027, erRefF: 10e9, tcdk: 40, k: 0.71, kxy: 0.90,
    cte: 46, ctexy: 11, tg: 280, tmax: 250, density: 1790, cp: 1000, vbd: 31,
    moisture: 0.06, cost: 5.0, stock: [0.203e-3, 0.305e-3, 0.406e-3, 0.508e-3, 0.813e-3, 1.524e-3, 2.03e-3, 3.048e-3], fMax: 40e9,
    notes: 'The industry workhorse RF laminate. FR-4-compatible processing, no PTFE through-hole treatment needed, very stable Dk. Standard 60 mil (1.524 mm) and 120 mil (3.048 mm) cores are stocked worldwide.',
  },
  {
    id: 'ro4350b', name: 'Rogers RO4350B', family: 'Hydrocarbon-ceramic',
    er: 3.66, df: 0.0037, erRefF: 10e9, tcdk: 50, k: 0.69, kxy: 0.88,
    cte: 32, ctexy: 10, tg: 280, tmax: 250, density: 1860, cp: 1000, vbd: 31,
    moisture: 0.06, cost: 5.0, stock: [0.168e-3, 0.254e-3, 0.338e-3, 0.508e-3, 0.762e-3, 1.524e-3], fMax: 40e9,
    notes: 'UL 94 V-0 flame-rated sibling of RO4003C. Slightly higher Df in exchange for flammability compliance - the usual pick for consumer/industrial products needing a UL file.',
  },
  {
    id: 'rt5880', name: 'Rogers RT/duroid 5880', family: 'PTFE / glass',
    er: 2.20, df: 0.0009, erRefF: 10e9, tcdk: -125, k: 0.20, kxy: 0.26,
    cte: 237, ctexy: 31, tg: 300, tmax: 250, density: 2200, cp: 960, vbd: 27,
    moisture: 0.02, cost: 9.0, stock: [0.127e-3, 0.254e-3, 0.381e-3, 0.508e-3, 0.787e-3, 1.575e-3, 3.175e-3], fMax: 77e9,
    notes: 'Lowest-loss general-purpose laminate. Very low Dk gives large radiating apertures and wide bandwidth, but the z-axis CTE of 237 ppm/degC is brutal on plated through-holes and it is mechanically soft.',
  },
  {
    id: 'rt5870', name: 'Rogers RT/duroid 5870', family: 'PTFE / glass',
    er: 2.33, df: 0.0012, erRefF: 10e9, tcdk: -115, k: 0.22, kxy: 0.28,
    cte: 173, ctexy: 22, tg: 300, tmax: 250, density: 2200, cp: 960, vbd: 27,
    moisture: 0.02, cost: 8.5, stock: [0.127e-3, 0.254e-3, 0.381e-3, 0.787e-3, 1.575e-3, 3.175e-3], fMax: 77e9,
    notes: 'Slightly higher Dk than 5880 with better dimensional stability. Common in satcom and radar feed networks.',
  },
  {
    id: 'ro3003', name: 'Rogers RO3003', family: 'PTFE / ceramic',
    er: 3.00, df: 0.0010, erRefF: 10e9, tcdk: 13, k: 0.50, kxy: 0.55,
    cte: 24, ctexy: 17, tg: 300, tmax: 250, density: 2100, cp: 960, vbd: 24,
    moisture: 0.04, cost: 8.0, stock: [0.127e-3, 0.254e-3, 0.508e-3, 0.762e-3, 1.52e-3], fMax: 77e9,
    notes: 'Near-zero Dk drift over temperature (13 ppm/degC) - the default for 77 GHz automotive radar and any design that must hold resonance from -40 to +125 degC.',
  },
  {
    id: 'tly5', name: 'Taconic TLY-5', family: 'PTFE / glass',
    er: 2.20, df: 0.0009, erRefF: 10e9, tcdk: -120, k: 0.22, kxy: 0.26,
    cte: 200, ctexy: 20, tg: 300, tmax: 250, density: 2170, cp: 960, vbd: 26,
    moisture: 0.02, cost: 6.5, stock: [0.127e-3, 0.254e-3, 0.508e-3, 0.787e-3, 1.575e-3], fMax: 60e9,
    notes: 'Cost-effective alternative to RT/duroid 5880 with comparable electrical performance. Widely used for GPS and base-station panels.',
  },
  {
    id: 'cuclad217', name: 'Arlon CuClad 217', family: 'PTFE / glass',
    er: 2.17, df: 0.0009, erRefF: 10e9, tcdk: -160, k: 0.23, kxy: 0.26,
    cte: 190, ctexy: 25, tg: 300, tmax: 250, density: 2170, cp: 960, vbd: 26,
    moisture: 0.02, cost: 7.0, stock: [0.254e-3, 0.508e-3, 0.787e-3, 1.575e-3], fMax: 60e9,
    notes: 'Woven-glass PTFE with low Dk. Good for multilayer stripline feeds behind an antenna layer.',
  },

  // ---------------------------------------------------------------- high-Dk / ceramic
  {
    id: 'ro6010', name: 'Rogers RT/duroid 6010.2LM', family: 'High-Dk ceramic',
    er: 10.20, df: 0.0023, erRefF: 10e9, tcdk: -425, k: 0.86, kxy: 0.95,
    cte: 24, ctexy: 24, tg: 300, tmax: 250, density: 3000, cp: 900, vbd: 23,
    moisture: 0.01, cost: 12.0, stock: [0.254e-3, 0.635e-3, 1.27e-3, 1.905e-3, 2.54e-3], fMax: 20e9,
    notes: 'High-Dk laminate for miniaturisation. Shrinks the patch by ~3.2x in linear dimension versus air, at the cost of narrow bandwidth and severe TM0 surface-wave excitation. Large negative TCDk means notable drift over temperature.',
  },
  {
    id: 'alumina96', name: 'Alumina 96 % (Al2O3)', family: 'High-Dk ceramic',
    er: 9.40, df: 0.0004, erRefF: 10e9, tcdk: 110, k: 24.0, kxy: 24.0,
    cte: 7, ctexy: 7, tg: 1500, tmax: 800, density: 3720, cp: 880, vbd: 15,
    moisture: 0.0, cost: 20.0, stock: [0.254e-3, 0.381e-3, 0.635e-3, 1.0e-3], fMax: 100e9,
    notes: 'Thin-film ceramic substrate. Outstanding thermal conductivity (24 W/mK) makes it the choice when the antenna is co-packaged with a power amplifier. Requires laser machining, not routing.',
  },
  {
    id: 'ltccDp951', name: 'LTCC DuPont 951', family: 'High-Dk ceramic',
    er: 7.80, df: 0.0060, erRefF: 10e9, tcdk: 80, k: 3.0, kxy: 3.0,
    cte: 5.8, ctexy: 5.8, tg: 900, tmax: 400, density: 3100, cp: 800, vbd: 20,
    moisture: 0.0, cost: 18.0, stock: [0.1e-3, 0.2e-3, 0.4e-3, 0.8e-3, 1.2e-3], fMax: 60e9,
    notes: 'Low-temperature co-fired ceramic: buried cavities, integrated passives and hermetic packages. Standard for antenna-in-package and 60 GHz modules.',
  },

  // ---------------------------------------------------------------- flexible / other
  {
    id: 'polyimide', name: 'Polyimide flex (Kapton)', family: 'Flexible',
    er: 3.40, df: 0.0080, erRefF: 1e9, tcdk: -80, k: 0.12, kxy: 0.20,
    cte: 20, ctexy: 20, tg: 360, tmax: 200, density: 1420, cp: 1090, vbd: 240,
    moisture: 1.30, cost: 3.5, stock: [0.025e-3, 0.05e-3, 0.075e-3, 0.1e-3, 0.125e-3], fMax: 20e9,
    notes: 'Thin flexible film for conformal and wearable antennas. Very high moisture uptake shifts Dk with humidity - specify a coverlay and characterise wet.',
  },
  {
    id: 'lcp', name: 'LCP (liquid crystal polymer)', family: 'Flexible',
    er: 3.00, df: 0.0025, erRefF: 10e9, tcdk: -20, k: 0.20, kxy: 0.50,
    cte: 17, ctexy: 17, tg: 315, tmax: 250, density: 1400, cp: 1000, vbd: 100,
    moisture: 0.04, cost: 8.0, stock: [0.025e-3, 0.05e-3, 0.1e-3, 0.2e-3], fMax: 110e9,
    notes: 'Near-hermetic flexible substrate with excellent mmWave loss. The default for flexible 28/60 GHz phased-array tiles and implantable devices.',
  },
  {
    id: 'ptfeBulk', name: 'PTFE (bulk, unreinforced)', family: 'Bulk dielectrics',
    er: 2.10, df: 0.0002, erRefF: 10e9, tcdk: -100, k: 0.25, kxy: 0.25,
    cte: 120, ctexy: 120, tg: 327, tmax: 260, density: 2200, cp: 1000, vbd: 60,
    moisture: 0.01, cost: 4.0, stock: [0.5e-3, 1e-3, 2e-3, 3e-3, 5e-3], fMax: 100e9,
    notes: 'Machinable bulk dielectric for radomes, lenses and coax fills. Cold-flows under load - do not rely on it for a controlled gap.',
  },
  {
    id: 'abs', name: 'ABS (radome / housing)', family: 'Bulk dielectrics',
    er: 2.70, df: 0.0060, erRefF: 2.4e9, tcdk: -300, k: 0.17, kxy: 0.17,
    cte: 80, ctexy: 80, tg: 105, tmax: 85, density: 1050, cp: 1400, vbd: 16,
    moisture: 0.30, cost: 0.3, stock: [1e-3, 1.5e-3, 2e-3, 2.5e-3, 3e-3], fMax: 10e9,
    notes: 'Typical injection-moulded enclosure material. Not a substrate - model it as a radome layer; a 2 mm wall detunes a 2.4 GHz patch by roughly 1-2 %.',
  },
  {
    id: 'pcAbs', name: 'Polycarbonate radome', family: 'Bulk dielectrics',
    er: 2.90, df: 0.0090, erRefF: 2.4e9, tcdk: -250, k: 0.20, kxy: 0.20,
    cte: 68, ctexy: 68, tg: 147, tmax: 115, density: 1200, cp: 1200, vbd: 17,
    moisture: 0.15, cost: 0.5, stock: [1e-3, 2e-3, 3e-3], fMax: 10e9,
    notes: 'UV-stable outdoor radome material. Verify Df at the operating band - filled/flame-retarded grades can exceed Df 0.02.',
  },
  {
    id: 'glassBoro', name: 'Borosilicate glass', family: 'Bulk dielectrics',
    er: 4.60, df: 0.0037, erRefF: 10e9, tcdk: 60, k: 1.20, kxy: 1.20,
    cte: 3.3, ctexy: 3.3, tg: 560, tmax: 450, density: 2230, cp: 830, vbd: 30,
    moisture: 0.0, cost: 6.0, stock: [0.3e-3, 0.5e-3, 0.7e-3, 1.1e-3], fMax: 110e9,
    notes: 'Glass interposers for antenna-on-glass (5G mmWave in display bezels, automotive glazing). Extremely low CTE and smooth surface for fine-line mmWave features.',
  },
  {
    id: 'siliconHR', name: 'High-resistivity silicon', family: 'Semiconductor',
    er: 11.90, df: 0.0050, erRefF: 30e9, tcdk: 100, k: 148, kxy: 148,
    cte: 2.6, ctexy: 2.6, tg: 1400, tmax: 200, density: 2330, cp: 700, vbd: 30,
    moisture: 0.0, cost: 25.0, stock: [0.1e-3, 0.2e-3, 0.3e-3, 0.5e-3], fMax: 300e9,
    notes: 'On-chip / interposer antennas above 100 GHz. Very high Dk drives strong surface-wave loss - normally used with a lens or a micromachined cavity.',
  },
];

export const MATERIAL_BY_ID = Object.fromEntries(MATERIALS.map((m) => [m.id, m]));

/**
 * Djordjevic-Sarkar wideband causal Dk/Df model.
 * Extrapolates a single (er, df) datasheet point to another frequency while
 * preserving Kramers-Kronig causality. m1/m2 bound the relaxation-time spread
 * (1 kHz .. 1 THz) which is the usual choice for PCB laminates.
 * Reference: A.R. Djordjevic et al., IEEE Trans. EMC 43(4), 2001.
 */
export function dispersiveEr(material, f) {
  const { er, df, erRefF } = material;
  if (!df || df < 1e-6) return { er, df: df || 0 };
  const w1 = 2 * Math.PI * 1e3;
  const w2 = 2 * Math.PI * 1e12;
  const w = 2 * Math.PI * f;
  const w0 = 2 * Math.PI * erRefF;
  const L = Math.log(w2 / w1);
  // de = magnitude of the dispersive term fitted so that tan(delta)=df at w0
  const de = (df * er * L) / (Math.PI / 2);
  const term = (om) => {
    const re = (de / (2 * L)) * Math.log((w2 * w2 + om * om) / (w1 * w1 + om * om));
    const im = (de / L) * (Math.atan(w2 / om) - Math.atan(w1 / om));
    return { re, im };
  };
  const t0 = term(w0);
  const einf = er - t0.re; // anchor so that er(w0) matches the datasheet
  const t = term(w);
  const erp = einf + t.re;
  const erpp = t.im;
  return { er: erp, df: erpp / erp };
}

/** Dk shift with temperature using the datasheet TCDk [ppm/degC]. */
export function erAtTemperature(material, tempC, refC = 25) {
  return material.er * (1 + (material.tcdk * 1e-6) * (tempC - refC));
}

/** Nearest stocked core thickness [m]; falls back to the requested value. */
export function snapToStock(material, h) {
  if (!material.stock || !material.stock.length) return h;
  let best = material.stock[0];
  for (const s of material.stock) if (Math.abs(s - h) < Math.abs(best - h)) best = s;
  return best;
}
