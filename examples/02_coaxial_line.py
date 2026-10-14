"""
50-ohm air coaxial line: TEM propagation and port impedance extraction.

Demonstrates
  * CSG geometry (outer cylinder minus inner conductor),
  * an integration line, which is what turns a wave port's *wave* impedance
    into the *line* impedance V^2/(2P) that a VNA would measure,
  * de-embedding the reference plane.
"""
import math

import numpy as np

import aether as ae


def main():
    a = 1.0e-3
    b = a * math.exp(50.0 * 2 * math.pi / ae.eta0)     # exactly 50 ohm in air
    L = 20e-3
    print(f"inner radius {a*1e3:.3f} mm, outer {b*1e3:.4f} mm "
          f"-> analytic Z0 = {ae.eta0/(2*math.pi)*math.log(b/a):.3f} ohm")

    d = ae.Design("coax50", units="mm")
    dielectric = (ae.Cylinder((0, 0, 0), b, L)
                  - ae.Cylinder((0, 0, -1e-3), a, L + 2e-3))
    d.add_solid("diel", dielectric, "vacuum")
    d.add_wave_port("p1", axis="z", value=0,
                    integration_line=((a, 0, 0), (b, 0, 0)))
    d.add_wave_port("p2", axis="z", value=L,
                    integration_line=((a, 0, L), (b, 0, L)))

    setup = d.add_setup("Setup1", frequency="10GHz", max_passes=2)
    setup.add_sweep("Sweep", "1GHz", "20GHz", 20)

    d.generate_mesh(10e9, force=True, size=0.0008)
    sol = d.solve(adaptive=False)

    m = sol.port_mode(10e9, 0, 0)
    print(f"\nport mode      : {m.kind}")
    print(f"beta / k0      : {m.beta / (2*math.pi*10e9/ae.c0):.6f}  (1.0 = TEM)")
    print(f"wave impedance : {m.Z_wave.real:.3f} ohm  (eta0 for TEM)")
    print(f"line impedance : {m.Z_pv.real:.3f} ohm  (the 50 ohm we designed)")
    print("\n" + sol.sparams.summary())
    sol.sparams.write_touchstone("coax50.s2p")


if __name__ == "__main__":
    main()
