"""
Builds the example projects in this folder.

    python examples/build_examples.py            # write every .aedt
    python examples/build_examples.py --verify   # ... and solve each one

Every example is a complete project: geometry, materials, boundaries, ports,
a solution setup and a sweep, so it opens in the desktop (`aether gui
--project examples/<name>.aedt`), analyses with F9 and shows its results with
nothing else to configure.  See ``examples/README.md`` for what each one is
for and what to look at.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import aether as ae                                          # noqa: E402
from aether.core.materials import ConstantTanD, Material     # noqa: E402
from aether.geometry.select import BoxSelector, OuterSelector, PlaneSelector  # noqa: E402

c0 = ae.c0


# ---------------------------------------------------------------- waveguide
def wr90_waveguide() -> ae.Design:
    """WR-90 through line, X band. The canonical wave-port check."""
    d = ae.Design("wr90_waveguide", units="mm")
    d.add_box("guide", (0, 0, 0), ("22.86mm", "10.16mm", "30mm"), "vacuum")
    d.add_wave_port("Port1", axis="z", value=0)
    d.add_wave_port("Port2", axis="z", value="30mm")
    d.assign_pec_outer("Walls")
    st = d.add_setup("Setup1", frequency="10GHz", max_passes=3, delta_s=0.02)
    st.add_sweep("XBand", "8.2GHz", "12.4GHz", 43, kind="interpolating")
    d.config.mesh.max_element_size = 0.004
    return d


def iris_filter() -> ae.Design:
    """Two inductive irises form a one-pole band-pass filter."""
    A, B, lead, cav, gap = 22.86e-3, 10.16e-3, 12e-3, 20e-3, 11e-3

    def strips(z, tol=1e-9):
        return ae.union_sel(
            BoxSelector((0, 0, z - tol), ((A - gap) / 2, B, z + tol)),
            BoxSelector(((A + gap) / 2, 0, z - tol), (A, B, z + tol)))

    L = 2 * lead + cav
    d = ae.Design("iris_filter", units="mm")
    d.add_box("guide", (0, 0, 0), (A, B, L), "vacuum")
    for i, z in enumerate((lead, lead + cav), 1):
        d.add_sheet(f"Iris{i}", ae.Rectangle((0, 0, z), (A, B), "xy"))
    d.add_wave_port("Port1", axis="z", value=0)
    d.add_wave_port("Port2", axis="z", value=L)
    d.assign_pec("Iris1", strips(lead))
    d.assign_pec("Iris2", strips(lead + cav))
    d.assign_pec_outer("Walls")
    f0 = 0.5 * c0 * math.hypot(1 / A, 1 / cav)
    st = d.add_setup("Setup1", frequency=f0, max_passes=3, delta_s=0.02)
    st.add_sweep("Band", f0 * 0.9, f0 * 1.1, 41, kind="fast")
    d.config.mesh.max_element_size = 0.003
    return d


def coax_line() -> ae.Design:
    """50-ohm air coax: TEM, with an integration line for the line impedance."""
    a = 1.0e-3
    b = a * math.exp(50.0 * 2 * math.pi / ae.eta0)
    L = 20e-3
    d = ae.Design("coax_50ohm", units="mm")
    d.add_solid("Dielectric", ae.Cylinder((0, 0, 0), b, L)
                - ae.Cylinder((0, 0, -1e-3), a, L + 2e-3), "vacuum")
    d.add_wave_port("Port1", axis="z", value=0,
                    integration_line=((a, 0, 0), (b, 0, 0)))
    d.add_wave_port("Port2", axis="z", value=L,
                    integration_line=((a, 0, L), (b, 0, L)))
    st = d.add_setup("Setup1", frequency="10GHz", max_passes=2)
    st.add_sweep("Sweep", "1GHz", "20GHz", 20)
    d.config.mesh.max_element_size = 0.0008
    return d


def parallel_plate_lumped() -> ae.Design:
    """Parallel-plate line fed by lumped ports; Z0 = eta0 h / w exactly."""
    h, w, L = 1e-3, 10e-3, 20e-3
    z0 = ae.eta0 * h / w
    d = ae.Design("parallel_plate_lumped", units="mm")
    d.add_box("Air", (0, 0, 0), (L, w, h), "vacuum")
    d.assign_boundary("PMC_y0", "pmc", PlaneSelector("y", 0))
    d.assign_boundary("PMC_y1", "pmc", PlaneSelector("y", w))
    d.add_lumped_port("Port1", axis="x", value=0, impedance=z0,
                      direction=(0, 0, 1))
    d.add_lumped_port("Port2", axis="x", value=L, impedance=2 * z0,
                      direction=(0, 0, 1))
    st = d.add_setup("Setup1", frequency="5GHz")
    st.add_sweep("Sweep", "1GHz", "10GHz", 10)
    d.config.mesh.max_element_size = 0.0015
    return d


# ---------------------------------------------------------------- eigenmode
def cavity_eigenmode() -> ae.Design:
    """Rectangular PEC cavity: resonant frequencies and fields."""
    d = ae.Design("cavity_eigenmode", solution_type="eigenmode", units="mm")
    d.add_box("Cavity", (0, 0, 0), ("30mm", "15mm", "20mm"), "vacuum")
    d.assign_pec_outer("Walls")
    st = d.add_setup("Eigen1", frequency="10GHz", max_passes=4, basis_order=2)
    st.n_modes, st.min_frequency, st.delta_f = 5, 0.0, 0.01
    d.config.mesh.max_element_size = 0.006
    return d


def lossy_cavity_eigenmode() -> ae.Design:
    """Copper-wall cavity: Q from conductor loss (compare Pozar eq. 6.46)."""
    d = ae.Design("copper_cavity_eigenmode", solution_type="eigenmode",
                  units="mm")
    d.add_box("Cavity", (0, 0, 0), ("30mm", "15mm", "20mm"), "vacuum")
    d.assign_finite_conductivity("CopperWalls", OuterSelector(), "copper")
    st = d.add_setup("Eigen1", frequency="10GHz", max_passes=2, basis_order=2)
    st.n_modes = 2
    d.config.mesh.max_element_size = 0.006
    return d


# ----------------------------------------------------------------- antennas
LAM3 = c0 / 3e9


def dipole_antenna(length_factor: float = 0.43, sweep_kind: str = "interpolating"
                   ) -> ae.Design:
    """
    Centre-fed dipole for 3 GHz: two 2 mm square PEC arms, a 2 mm feed gap
    bridged by a **lumped port** on a drawn sheet, in an air box closed by a
    **radiation** boundary.  Second-order elements.

    The arms are 0.43 wavelengths overall: slightly short of half a wavelength
    because the wire is thick, which puts the resonance at 3.0 GHz with an
    input impedance near 74 ohm.
    """
    f0, lam = 3e9, LAM3
    gap, w = 2e-3, 2e-3
    arm = (length_factor * lam - gap) / 2
    R, H = 0.5 * lam, 0.7 * lam
    d = ae.Design("dipole_antenna", units="mm")
    d.add_box("Air", (-R, -R, -H), (2 * R, 2 * R, 2 * H), "vacuum")
    d.add_box("Arm_Top", (-w / 2, -w / 2, gap / 2), (w, w, arm), "pec")
    d.add_box("Arm_Bottom", (-w / 2, -w / 2, -gap / 2 - arm), (w, w, arm), "pec")
    d.solids[1].display_color = "#b87333"
    d.solids[2].display_color = "#b87333"
    d.solids[0].display_transparency = 0.92
    d.add_sheet("Feed", ae.Rectangle((-w / 2, 0, -gap / 2), (w, gap), "xz"))
    d.sheets[0].display_color = "#d64545"
    d.add_lumped_port("Port1", selector=BoxSelector(
        (-w / 2 - 1e-6, -1e-6, -gap / 2 - 1e-6),
        (w / 2 + 1e-6, 1e-6, gap / 2 + 1e-6)),
        impedance=50, direction=(0, 0, 1))
    d.assign_radiation("Radiation")
    st = d.add_setup("Setup1", frequency=f0, max_passes=2, delta_s=0.03,
                     basis_order=2)
    st.add_sweep("Sweep1", "2.6GHz", "3.4GHz", 17, kind=sweep_kind,
                 save_fields=True)
    d.config.mesh.max_element_size = 0.12 * lam
    d.add_mesh_operation("Arms", 2.5e-3, objects=["Arm_Top", "Arm_Bottom"])
    d.add_mesh_operation("Gap", 1.0e-3, objects=["Feed"])
    return d


def patch_antenna() -> ae.Design:
    """
    2.4 GHz rectangular microstrip patch on 1.6 mm FR-4, probe-style lumped
    port from the ground plane to the patch edge, radiation boundary on the
    air box.  The ground plane is the bottom face of the model.
    """
    f0 = 2.45e9
    lam = c0 / f0
    er, h = 4.4, 1.6e-3
    W, Lp = 37.3e-3, 25.8e-3                    # patch width / length
    sub = 70e-3                                 # substrate (and ground) size
    air_h = 0.30 * lam
    pad = 0.25 * lam
    fr4 = Material("FR4_epoxy", ConstantTanD(er, 0.02))
    d = ae.Design("patch_antenna", units="mm")
    d.materials.add(fr4)
    X = sub / 2 + pad
    d.add_box("Air", (-X, -X, 0), (2 * X, 2 * X, h + air_h), "vacuum")
    d.add_box("Substrate", (-sub / 2, -sub / 2, 0), (sub, sub, h), "FR4_epoxy")
    d.solids[0].display_transparency = 0.93
    d.solids[1].display_color = "#3f9d55"
    d.add_sheet("Patch", ae.Rectangle((-Lp / 2, -W / 2, h), (Lp, W), "xy"))
    d.sheets[0].display_color = "#d4af37"
    d.assign_pec("PatchMetal", BoxSelector(
        (-Lp / 2 - 1e-6, -W / 2 - 1e-6, h - 1e-6),
        (Lp / 2 + 1e-6, W / 2 + 1e-6, h + 1e-6)))
    d.assign_pec("Ground", PlaneSelector("z", 0.0))
    # feed: a vertical sheet from the ground plane to the patch, 2 mm wide,
    # inset 4.5 mm from the radiating edge
    fx, fw = Lp / 2 - 4.5e-3, 2e-3
    d.add_sheet("Feed", ae.Rectangle((fx, -fw / 2, 0), (fw, h), "yz"))
    d.sheets[1].display_color = "#d64545"
    d.add_lumped_port("Port1", selector=BoxSelector(
        (fx - 1e-6, -fw / 2 - 1e-6, -1e-6), (fx + 1e-6, fw / 2 + 1e-6, h + 1e-6)),
        impedance=50, direction=(0, 0, 1))
    d.assign_radiation("Radiation", OuterSelector(exclude=PlaneSelector("z", 0.0)))
    st = d.add_setup("Setup1", frequency=f0, max_passes=3, delta_s=0.03)
    st.add_sweep("Sweep1", "2.2GHz", "2.7GHz", 21, kind="interpolating",
                 save_fields=True)
    d.config.mesh.max_element_size = 0.14 * lam
    d.add_mesh_operation("Substrate_mesh", 4e-3, objects=["Substrate"])
    return d


# ------------------------------------------------------------- optimisation
def slab_matching_parametric() -> ae.Design:
    """
    A dielectric slab in WR-90 with its thickness bound to a design variable
    ``T``.  Tools > Optimization tunes ``T`` to put the reflection notch at
    10 GHz (analytic 11.96 mm; the coarse mesh gives about 11.7 mm);
    Tools > Parameter Study sweeps it.
    """
    from aether.parametric import make_primitive, rebuild
    d = ae.Design("slab_matching", units="mm")
    d.materials.add(Material("Slab_eps2", ConstantTanD(2.0, 0.0)))
    d.variables = {"T": "9mm"}
    d.add_box("Guide", (0, 0, 0), ("22.86mm", "10.16mm", "60mm"), "vacuum")
    shape = make_primitive("box", {"position": ["0mm", "0mm", "20mm"],
                                   "size": ["22.86mm", "10.16mm", "T"]},
                           "Slab", d.variables, "mm")
    d.add_solid("Slab", shape, "Slab_eps2")
    d.solids[1].display_color = "#2b79c2"
    d.add_wave_port("Port1", axis="z", value=0)
    d.add_wave_port("Port2", axis="z", value="60mm")
    d.assign_pec_outer("Walls")
    st = d.add_setup("Setup1", frequency="10GHz", max_passes=1)
    st.add_sweep("Spot", points=["10GHz"], count=1)
    d.config.mesh.max_element_size = 0.004
    return d


EXAMPLES = {
    "wr90_waveguide": wr90_waveguide,
    "iris_filter": iris_filter,
    "coax_line": coax_line,
    "parallel_plate_lumped": parallel_plate_lumped,
    "cavity_eigenmode": cavity_eigenmode,
    "copper_cavity_eigenmode": lossy_cavity_eigenmode,
    "dipole_antenna": dipole_antenna,
    "patch_antenna": patch_antenna,
    "slab_matching_parametric": slab_matching_parametric,
}


def build(name: str, directory: str = HERE) -> str:
    d = EXAMPLES[name]()
    path = os.path.join(directory, name + ".aedt")
    ae.save_hfss(d, path, mode="create")
    return path


def verify(path: str) -> str:
    """Open the saved file the way the GUI does and solve it."""
    d, report = ae.open_hfss(path)
    errs = d.validate()
    if errs:
        return "INVALID: " + "; ".join(errs)
    t0 = time.perf_counter()
    sol = d.solve(progress=False, save_fields=True)
    dt = time.perf_counter() - t0
    if sol.modes:
        text = ", ".join(f"{m.f / 1e9:.4f} GHz (Q={m.q:.4g})" for m in sol.modes[:5])
    else:
        sp = sol.sparams
        k = int(np.argmin(sp.db(1, 1)))
        text = (f"{sp.n_freq} points, min S11 {sp.db(1, 1)[k]:.1f} dB at "
                f"{sp.freq[k] / 1e9:.3f} GHz")
    return f"{text}  [{dt:.0f} s]"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help="examples to build (default: all)")
    ap.add_argument("--verify", action="store_true",
                    help="solve each saved project and print a result line")
    ap.add_argument("--out", default=HERE)
    args = ap.parse_args(argv)
    ae.set_log_level("WARNING")
    names = args.names or list(EXAMPLES)
    for n in names:
        if n not in EXAMPLES:
            ap.error(f"unknown example {n!r}; choose from {', '.join(EXAMPLES)}")
        path = build(n, args.out)
        print(f"wrote {os.path.relpath(path)}")
        if args.verify:
            print(f"   {verify(path)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
