# RF Antenna Studio

A physics-based antenna design and trade-study tool for RF, microwave and EMC
engineers. You enter a specification — frequency, dielectric, radiation pattern,
polarisation, target realized gain, size and power — and it returns ranked
antenna candidates with the analysis behind each one: efficiency, bandwidth,
ground-plane behaviour, thermal limits, manufacturing yield and link budget.

Everything is computed from published models. There is no lookup table of
"typical" numbers anywhere in the engine.

```
npm test          # 32 physics regression tests
npm run dev       # serve at http://localhost:8777
npm run build     # -> dist/rf-antenna-studio.html  (one file, works offline)
```

No dependencies, no build step required to develop — `index.html` loads the ES
modules directly. The build script only exists to produce a single portable file.

---

## What it does

**Shows you each antenna, not just its numbers.** Click any candidate and the
Antenna detail tab opens a full picture of that type: a scale drawing generated
from its own synthesised dimensions, its radiation pattern in polar and
rectangular form with measured beamwidth, sidelobe level and front-to-back,
gain and VSWR across the band, and where it stands against every other viable
candidate. Rejected types can be inspected too — the drawing and pattern are
often the fastest way to see *why* a type does not suit the job.

**Recommends antenna types.** 29 archetypes — patch, stacked patch, air-gap
patch, aperture-coupled patch, patch array, series-fed column, SIW slot array,
DRA, monopole, dipole, PIFA, IFA, collinear, biconical, small loop, Yagi-Uda,
printed quasi-Yagi, LPDA, Vivaldi, pyramidal horn, SIW horn, parabolic
reflector, reflectarray, axial helix, QHA, cavity-backed slot, magneto-electric
dipole, dielectric lens and phased array. Each carries its own quantitative
model, so the ranking falls out of computed gain, bandwidth, size, efficiency,
cost and build complexity rather than from an opinion. Rejected candidates say
why they were rejected.

**Checks the specification against physics first.** Chu–McLean bounds the
bandwidth an envelope can support; Harrington bounds the directivity. A request
for 30 dBi from a 50 mm box at 100 MHz is reported as impossible before any
design work starts.

**Runs the substrate trade.** Realized gain, efficiency, bandwidth and patch
size for every candidate stack-up on your actual ground plane, plus efficiency
and bandwidth against substrate thickness for several materials at once, the
permittivity–aperture–directivity relationship, and the surface-wave power that
never leaves the board.

**Sizes the ground plane.** Aperture truncation, λ/2-periodic edge-diffraction
ripple and surface-wave spill-over, with a recommended size and the
front-to-back ratio you get for it.

**Solves the thermal problem.** Conduction through the laminate, spreading in
the ground plane, thermal vias, natural or forced convection and grey-body
radiation to ambient — solved iteratively because convection and radiation both
depend on the surface temperature. Gives hot-spot temperature, maximum
continuous power, thermal time constant, pulsed behaviour, Paschen breakdown
against altitude, peak-power limits and the resonance drift that TCDk and CTE
cause over your operating temperature range.

**Predicts manufacturing yield.** Monte Carlo over Dk, thickness and etch
tolerance at 3σ, propagated through the same resonance model, with a sensitivity
breakdown showing which parameter is eating your frequency budget and a
recommended artwork pre-bias when the median part lands off target.

**Closes the link.** Friis, two-ray and COST-231 Hata; ITU-R P.676 gaseous
absorption and P.838 rain; thermal noise floor, sensitivity, margin, Shannon
capacity, maximum range, Fresnel clearance, radio horizon and MPE distance —
with the regulatory EIRP limit for the band checked automatically.

**Draws it.** Stack-up cross-section and etch plan view generated from the
solved dimensions, so the drawing cannot drift out of step with the numbers,
plus a scale drawing for each of the 29 archetypes — patch stacks, array grids
with their feed trees, Yagi booms, horn flares, dish optics, helix windings,
via fences, lens ray paths.

**Exports.** Printable report, JSON payload and CSV summary.

---

## Validation

The patch engine was checked against published data before any UI was written.

| Check | Reference | Model |
|---|---|---|
| Slot self-conductance G₁ | Balanis Ex. 14.1: 1.57e-3 S | 1.5728e-3 S |
| Mutual conductance G₁₂ | Balanis Ex. 14.1: 6.1683e-4 S | 6.1683e-4 S |
| Edge resistance | Balanis Ex. 14.1: 228.35 Ω | 228.4 Ω |
| Patch W, L synthesis | Balanis Ex. 14.1: 11.86, 9.06 mm | 11.85, 9.02 mm |
| 50 Ω on 1.6 mm FR-4 | ~3.05 mm | 3.05 mm |
| 50 Ω on 0.508 mm RO4003C | Rogers datasheet 1.15 mm | 1.13 mm |
| FR-4 efficiency vs thickness at 2.45 GHz | 6.5 / 14 / 26 / 43 / 54 / 62 % | 6.8 / 14.3 / 26.5 / 41.4 / 53.6 / 60.9 % |
| RO4003C efficiency, 1.52 / 3.05 mm | 82 / 92 % | 82.4 / 91.5 % |
| Realized gain on 70×70 mm ground | −0.6 / 1.6 / 3.2 / 5.1 / 7.7 dBi | −0.4 / 1.6 / 2.8 / 4.7 / 7.3 dBi |
| ITU-R P.676 at 10 / 22 / 60 / 94 / 183 GHz | 0.011 / 0.20 / 15.1 / 0.45 / 29 dB/km | within ±30 % in the windows, exact at the resonances |
| Paschen breakdown, 1.6 mm air at sea level | 5–8 kV | 7.4 kV |
| Half-wave dipole beamwidth | 78° | 78° |
| Small loop beamwidth | 90° | 90° |
| 6-element uniform array, sidelobe | −13.2 dB | −13.9 dB |
| Pyramidal horn, 100 × 66 mm at 30 mm | E 23° / H 21° | E 24° / H 22° |
| 300 mm dish at 30 mm | 7°, sidelobe −24 dB | 8°, −24 dB |
| 4 × 4 array, 0.7 λ, cosine taper | ~22°, −20 dB | 22°, −21 dB |

`npm test` locks all of these in. If a model change moves any of them, the test
fails and the change has to be argued for rather than slipping through.

---

## Models and their limits

| Area | Model | Validity |
|---|---|---|
| Patch resonance & impedance | Cavity / transmission-line model, Balanis ch. 14 | h ≲ 0.06 λ₀, dominant TM₁₀ mode |
| Directivity | Numerical integration of the two-slot far field | any W, h, εr — no thin-substrate assumption |
| Radiation Q | Derived from the physical aperture: Q = 2ωW_E/P_rad | as above |
| Microstrip Z₀, ε_eff | Hammerstad & Jensen 1980 | ±0.2 % for 0.05 < W/h < 20 |
| Dispersion | Kirschning & Jansen 1982 | to ~60 GHz |
| Wideband Dk/Df | Djordjevic–Sarkar causal model | anchored to the datasheet point |
| Conductor loss | Wheeler incremental inductance + Hammerstad or Huray roughness | — |
| Surface wave | Jackson & Alexopoulos thin-substrate asymptotics, coefficient calibrated to published full-wave data | k₀h ≲ 0.3 |
| Finite ground plane | GTD/UTD edge diffraction reduced to closed form, calibrated to Huang 1983 and Kishk & Shafai 1986 | engineering estimate, ±0.5 dB |
| Fundamental limits | Chu 1948, McLean 1996, Harrington 1960, Bode–Fano | exact |
| Radiation patterns | per family: cavity model (patch), ordinary end-fire array factor (Yagi), uniform/cosine rectangular aperture (horn), Airy and parabolic-taper circular aperture (dish, lens), element × array factor with real spacing and taper (arrays), thin-dipole and small-loop closed forms | beamwidth and sidelobe level measured off the computed cut |
| Atmosphere | Line-shape model calibrated to the ITU-R P.676 sea-level curve | ±30 % in the windows, 1–300 GHz |
| Rain | ITU-R P.838-3 k/α coefficients | 1–100 GHz |
| Thermal | Churchill–Chu and McAdams convection, grey-body radiation, lumped conduction | steady state and single-pole transient |
| Breakdown | Paschen, A = 15 cm⁻¹Torr⁻¹, B = 365 V·cm⁻¹Torr⁻¹ (air) | above the Paschen minimum |
| Yield | Monte Carlo, 3σ Dk / thickness / etch | — |

These are analytic models. Use them for architecture decisions, sizing and trade
studies — which design to build and simulate. Validate the chosen candidate in a
full-wave solver and on hardware before release.

---

## Materials

24 substrates with the properties that actually matter for an antenna: Dk, Df,
TCDk, through-thickness and in-plane thermal conductivity, z-axis and x/y CTE,
Tg, maximum operating temperature, density, specific heat, dielectric strength,
moisture absorption, relative cost and the thicknesses that are actually stocked.

Air and foam (Rohacell 51 HF, PP), FR-4 standard and high-Tg, Megtron 6,
I-Tera MT40, RO4003C, RO4350B, RT/duroid 5880 and 5870, RO3003, TLY-5,
CuClad 217, RT/duroid 6010, alumina 96 %, LTCC DuPont 951, polyimide, LCP, bulk
PTFE, ABS and PC radome, borosilicate glass, high-resistivity silicon.

21 service bands from 433 MHz through 5G FR2, 60 GHz WiGig and 77 GHz automotive
radar to D-band, each with its regulatory EIRP limit where one applies.

---

## Repository layout

```
index.html                 entry point (loads ES modules directly)
src/core/
  constants.js             CODATA constants, conductors, skin depth
  materials.js             substrate database + Djordjevic-Sarkar dispersion
  microstrip.js            Z0/eps_eff, synthesis, dispersion, loss, roughness
  patch.js                 cavity model, far field, Q factors, feed synthesis
  ground.js                finite ground plane
  limits.js                Chu, Harrington, Bode-Fano, field regions
  library.js               29 antenna archetypes with quantitative models
  patterns.js              per-family far-field models and frequency response
  recommend.js             candidate scoring and rejection reasons
  propagation.js           path loss, atmosphere, rain, link budget
  thermal.js               heat transfer, breakdown, drift
  tolerance.js             Monte Carlo yield
  bands.js                 regulatory bands
  design.js                orchestrator: spec -> complete design + datasets
src/ui/
  charts.js                dependency-free SVG chart library
  diagrams.js              stack-up, plan view, array layout
  antennaArt.js            scale drawing for each of the 29 archetypes
  panels.js                the ten analysis panels
  app.js                   shell, specification form, routing
src/styles/main.css        design tokens, light and dark
tools/build.mjs            single-file bundler
tests/physics.test.mjs     regression tests
```

## Charting

The SVG chart library is written for this tool and enforces its own rules:
a single y-axis per chart (two measures become two panels, never two scales on
one plot), categorical hues assigned in fixed slot order, a legend whenever
there are two or more series plus selective direct labels, crosshair and tooltip
on every line chart, a data-table view under every chart, and separately-stepped
light and dark palettes validated for colour-vision deficiency rather than
flipped automatically.

## Licence

MIT.
