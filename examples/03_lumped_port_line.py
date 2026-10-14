"""
Parallel-plate transmission line driven by lumped ports.

Z0 = eta0 * h / w exactly, so this is a clean check of the lumped-port
formulation: a matched termination gives |S11| ~ 0, and a 2*Z0 termination
gives the textbook |Gamma| = 1/3.
"""
import math

import numpy as np

import aether as ae


def line(z_term):
    h, w, L = 1e-3, 10e-3, 20e-3
    z0 = ae.eta0 * h / w
    d = ae.Design("pplate", units="mm")
    d.add_box("air", (0, 0, 0), (L, w, h), "vacuum")
    # PMC sidewalls keep the mode purely TEM
    d.assign_boundary("PMC_y0", "pmc", ae.PlaneSelector("y", 0))
    d.assign_boundary("PMC_y1", "pmc", ae.PlaneSelector("y", w))
    d.add_lumped_port("p1", axis="x", value=0, impedance=z0,
                      direction=(0, 0, 1))
    d.add_lumped_port("p2", axis="x", value=L, impedance=z_term,
                      direction=(0, 0, 1))
    st = d.add_setup("Setup1", frequency="5GHz")
    st.add_sweep("Sweep", "1GHz", "10GHz", 10)
    d.generate_mesh(5e9, force=True, size=0.0015)
    return z0, d.solve(adaptive=False)


def main():
    z0, sol = line(ae.eta0 * 1e-3 / 10e-3)
    print(f"characteristic impedance : {z0:.3f} ohm")
    print(sol.sparams.summary())
    _, mis = line(2 * z0)
    g = abs(mis.sparams.sij(1, 1)[0])
    print(f"\n2*Z0 termination -> |S11| = {g:.4f}  (theory 0.3333)")


if __name__ == "__main__":
    main()
