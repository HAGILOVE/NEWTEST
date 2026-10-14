"""
Optimisation: tune a dielectric slab until it stops reflecting.

``slab_matching_parametric.aedt`` has the slab thickness bound to the design
variable ``T``.  A slab in a waveguide reflects nothing at the frequency where
it is half a guide wavelength thick, so the optimiser should land on
T = pi / sqrt(k0^2 eps_r - kc^2) = 11.96 mm for 10 GHz (the coarse first-order
mesh lands within a few percent of it, about 11.7 mm).

    python examples/11_optimize_slab.py

The same thing in the desktop: Tools > Optimization.
"""
import math
import os

import aether as ae

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ae.set_log_level("WARNING")
    design, _ = ae.open_hfss(os.path.join(HERE, "slab_matching_parametric.aedt"))
    k0 = 2 * math.pi * 10e9 / ae.c0
    want = math.pi / math.sqrt(k0 ** 2 * 2.0 - (math.pi / 22.86e-3) ** 2)

    goal = ae.Goal("s_max", target=-30.0, port=1, port2=1,
                   f_start=10e9, f_stop=10e9)
    res = ae.optimize(design, {"T": ("4mm", "16mm")}, [goal],
                      method="nelder-mead", max_evals=30)
    print(res.summary())
    print(f"\nanalytic optimum     : T = {want * 1e3:.3f} mm")
    for h in res.history:
        print(f"  solve {h['eval']:2d}: T = {h['values']['T'] * 1e3:7.3f} mm   "
              f"S11 = {h['goals'][0]['value']:7.2f} dB")


if __name__ == "__main__":
    main()
