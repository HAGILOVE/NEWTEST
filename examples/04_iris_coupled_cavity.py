"""
Iris-coupled waveguide cavity -- a one-pole bandpass filter.

Two inductive irises (zero-thickness PEC sheets with a centred slot) form the
resonator; the response is the classic single-pole bandpass shape with the
transmission peak at the loaded resonance.

This example exercises the parts of the solver that a straight guide does not:
internal perfect-E sheets, strong evanescent coupling, and a resonance that
only converges once the mesh resolves the slot fields.
"""
import math

import numpy as np

import aether as ae

A, B = 22.86e-3, 10.16e-3          # WR-90
LEAD = 12e-3                       # feed guide either side
CAV = 20e-3                        # cavity length
GAP = 11e-3                        # iris slot width


def iris_strips(z, gap=GAP, tol=1e-9):
    """Selector for the metal part of an iris plate at height *z*."""
    return ae.union_sel(
        ae.BoxSelector((0, 0, z - tol), ((A - gap) / 2, B, z + tol)),
        ae.BoxSelector(((A + gap) / 2, 0, z - tol), (A, B, z + tol)))


def main():
    L = 2 * LEAD + CAV
    d = ae.Design("iris_cavity", units="mm")
    d.add_box("guide", (0, 0, 0), (A, B, L), "vacuum")
    for z in (LEAD, LEAD + CAV):
        d.add_sheet(f"iris_{z*1e3:.0f}", ae.Rectangle((0, 0, z), (A, B), "xy"))
    d.add_wave_port("p1", axis="z", value=0)
    d.add_wave_port("p2", axis="z", value=L)
    d.assign_pec("Iris1", iris_strips(LEAD))
    d.assign_pec("Iris2", iris_strips(LEAD + CAV))
    d.assign_pec_outer("Walls")

    f0 = 0.5 * ae.c0 * math.hypot(1 / A, 1 / CAV)
    print(f"unloaded TE101 estimate: {f0/1e9:.4f} GHz")

    st = d.add_setup("Setup1", frequency=f0)
    st.add_sweep("Sweep", f0 * 0.90, f0 * 1.10, 41)
    d.generate_mesh(f0, force=True, size=0.002)
    sol = d.solve(adaptive=False)

    sp = sol.sparams
    k = int(np.argmax(np.abs(sp.sij(2, 1))))
    peak = sp.freq[k]
    mag = np.abs(sp.sij(2, 1))
    half = mag.max() / math.sqrt(2)
    band = sp.freq[mag >= half]
    bw = band[-1] - band[0] if len(band) > 1 else float("nan")
    print(f"transmission peak      : {peak/1e9:.4f} GHz "
          f"(|S21| = {mag[k]:.4f})")
    print(f"3 dB bandwidth         : {bw/1e6:.1f} MHz "
          f"-> loaded Q = {peak/bw:.1f}")
    print(f"energy check max |1-sum|S|^2| : "
          f"{np.max(np.abs(sp.energy_error())):.2e}")
    print("\n" + sp.summary())
    sp.write_touchstone("iris_cavity.s2p")
    from aether.post.report import html_report
    html_report(sol, "iris_cavity.html")
    print("wrote iris_cavity.s2p and iris_cavity.html")


if __name__ == "__main__":
    main()
