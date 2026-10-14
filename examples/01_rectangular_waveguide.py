"""
WR-90 rectangular waveguide -- the canonical validation case.

Solves a 30 mm length of WR-90 over X-band and compares the computed
propagation constant, cutoff frequency and insertion phase with the
closed-form TE10 results.

    python examples/01_rectangular_waveguide.py
"""
import math

import numpy as np

import aether as ae

A, B, L = "22.86mm", "10.16mm", "30mm"


def main():
    d = ae.Design("wr90_thru", solution_type="driven_modal", units="mm")
    d.add_box("guide", (0, 0, 0), (A, B, L), "vacuum")
    d.add_wave_port("p1", axis="z", value=0, num_modes=1)
    d.add_wave_port("p2", axis="z", value=L, num_modes=1)
    d.assign_pec_outer()                      # metal walls, ports excluded

    setup = d.add_setup("Setup1", frequency="10GHz", max_passes=3,
                        delta_s=0.01)
    setup.add_sweep("XBand", "8.2GHz", "12.4GHz", 22)

    sol = d.solve()
    print(sol.summary())

    a = ae.to_si(A)
    fc = 0.5 * ae.c0 / a
    print(f"\nTE10 cutoff: analytic {fc/1e9:.4f} GHz   "
          f"solver {sol.port_mode(1e10, 0, 0).f_cut/1e9:.4f} GHz")

    print(f"\n{'f [GHz]':>9} {'|S21|':>8} {'phase':>10} {'analytic':>10} "
          f"{'err [deg]':>10}")
    Ls = ae.to_si(L)
    for i, f in enumerate(sol.sparams.freq):
        k0 = 2 * math.pi * f / ae.c0
        beta = math.sqrt(k0 ** 2 - (math.pi / a) ** 2)
        want = math.degrees(np.angle(np.exp(-1j * beta * Ls)))
        got = math.degrees(np.angle(sol.sparams.s[i, 1, 0]))
        print(f"{f/1e9:9.3f} {abs(sol.sparams.s[i,1,0]):8.5f} "
              f"{got:10.3f} {want:10.3f} "
              f"{(got-want+180)%360-180:10.3f}")

    sol.sparams.write_touchstone("wr90_thru.s2p")
    from aether.post.report import html_report
    html_report(sol, "wr90_thru.html")
    print("\nwrote wr90_thru.s2p and wr90_thru.html")


if __name__ == "__main__":
    main()
