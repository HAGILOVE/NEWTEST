"""
Discrete vs interpolating vs fast frequency sweeps.

The same 81-point X-band sweep three ways: every point solved, a rational
model fitted through adaptively chosen solves, and a reduced basis.  The
accuracy is printed against the discrete answer, with the number of full FEM
solves each one needed.

    python examples/12_sweep_strategies.py
"""
import os
import time

import numpy as np

import aether as ae

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ae.set_log_level("WARNING")
    ref = None
    print(f"{'sweep':>14} {'full solves':>12} {'time [s]':>9} {'max |dS|':>10}")
    for kind in ("discrete", "interpolating", "fast"):
        design, _ = ae.open_warps(os.path.join(HERE, "wr90_waveguide.warp"))
        sw = design.setups[0].sweeps[0]
        sw.kind, sw.spacing, sw.count = kind, "linear", 81
        t0 = time.perf_counter()
        sol = design.solve(progress=False, adaptive=False)
        dt = time.perf_counter() - t0
        s = sol.sparams.s
        ref = s if ref is None else ref
        print(f"{kind:>14} {int(sol.solved.sum()):>12d} {dt:>9.1f} "
              f"{np.abs(s - ref).max():>10.2e}")


if __name__ == "__main__":
    main()
