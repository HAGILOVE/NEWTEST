/**
 * Physical constants and unit helpers.
 * SI base units throughout the engine (m, Hz, W, K, S/m).
 * CODATA 2018 values.
 */

export const C0 = 299792458;                 // speed of light in vacuum [m/s]
export const MU0 = 4e-7 * Math.PI;           // vacuum permeability [H/m] (classical value)
export const EPS0 = 1 / (MU0 * C0 * C0);     // vacuum permittivity [F/m]
export const ETA0 = MU0 * C0;                // free-space wave impedance ~376.730 [ohm]
export const KB = 1.380649e-23;              // Boltzmann constant [J/K]
export const SIGMA_SB = 5.670374419e-8;      // Stefan-Boltzmann [W/(m^2 K^4)]
export const T0 = 290;                       // IEEE reference noise temperature [K]
export const ZERO_C = 273.15;                // 0 degC in kelvin

/** Bulk conductivity of common antenna metals [S/m] at 20 degC. */
export const CONDUCTORS = {
  copper:      { name: 'Copper (annealed)',   sigma: 5.80e7, alphaR: 3.93e-3, k: 401, rho: 8960, cp: 385 },
  copperEd:    { name: 'Copper (ED foil)',    sigma: 5.60e7, alphaR: 3.93e-3, k: 398, rho: 8940, cp: 385 },
  silver:      { name: 'Silver',              sigma: 6.30e7, alphaR: 3.80e-3, k: 429, rho: 10490, cp: 235 },
  gold:        { name: 'Gold (plated)',       sigma: 4.10e7, alphaR: 3.40e-3, k: 317, rho: 19300, cp: 129 },
  aluminium:   { name: 'Aluminium',           sigma: 3.77e7, alphaR: 3.90e-3, k: 237, rho: 2700, cp: 900 },
  brass:       { name: 'Brass (CuZn37)',      sigma: 1.60e7, alphaR: 1.50e-3, k: 120, rho: 8500, cp: 380 },
  tinLead:     { name: 'HASL (SnPb)',         sigma: 6.90e6, alphaR: 4.20e-3, k: 50,  rho: 8400, cp: 200 },
  enig:        { name: 'ENIG (Ni/Au)',        sigma: 1.45e7, alphaR: 6.00e-3, k: 91,  rho: 8900, cp: 440 },
};

/** Convert linear ratio -> dB (power). */
export const toDB = (x) => 10 * Math.log10(Math.max(x, 1e-300));
/** Convert dB -> linear power ratio. */
export const fromDB = (dB) => Math.pow(10, dB / 10);
/** Free-space wavelength [m] for f in Hz. */
export const lambda0 = (f) => C0 / f;
/** Guided wavelength [m]. */
export const lambdaG = (f, epsEff) => C0 / (f * Math.sqrt(epsEff));
/** Free-space wavenumber [rad/m]. */
export const k0 = (f) => (2 * Math.PI * f) / C0;

export const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
export const lerp = (a, b, t) => a + (b - a) * t;
/** sin(x)/x with the removable singularity handled. */
export const sinc = (x) => (Math.abs(x) < 1e-9 ? 1 - (x * x) / 6 : Math.sin(x) / x);

/** Skin depth [m] for conductivity sigma at frequency f (non-magnetic metal). */
export function skinDepth(f, sigma, mur = 1) {
  return 1 / Math.sqrt(Math.PI * f * MU0 * mur * sigma);
}

/** Surface resistance Rs [ohm/sq]. */
export function surfaceResistance(f, sigma, mur = 1) {
  return Math.sqrt((Math.PI * f * MU0 * mur) / sigma);
}

/** Temperature-corrected conductivity (linear resistivity model). */
export function sigmaAtT(sigma20, alphaR, tempC) {
  return sigma20 / (1 + alphaR * (tempC - 20));
}
