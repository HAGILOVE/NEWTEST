"""
Eigenmode solution of a rectangular cavity against closed-form resonances.

    python examples/13_eigenmode_cavity.py

Prints the first resonances of ``cavity_eigenmode.aedt`` (30 x 15 x 20 mm PEC
box) beside f = c/2 sqrt((m/a)^2 + (n/b)^2 + (p/d)^2), and the Q of the
copper-wall version beside Pozar's conductor-loss formula for the TE101 mode.
"""
import itertools
import math
import os

import aether as ae

HERE = os.path.dirname(os.path.abspath(__file__))
A, B, D = 30e-3, 15e-3, 20e-3
c0 = ae.c0


def analytic(n):
    out = []
    for m, k, p in itertools.product(range(4), repeat=3):
        if (m > 0) + (k > 0) + (p > 0) < 2:
            continue
        if (p >= 1 and (m or k)) or (m >= 1 and k >= 1):
            out.append(0.5 * c0 * math.sqrt((m / A) ** 2 + (k / B) ** 2 + (p / D) ** 2))
    return sorted(out)[:n]


def main():
    ae.set_log_level("WARNING")
    d, _ = ae.open_hfss(os.path.join(HERE, "cavity_eigenmode.aedt"))
    sol = d.solve(progress=False)
    print(f"{'mode':>4} {'solver [GHz]':>13} {'analytic [GHz]':>15} {'error':>8}")
    for m, f in zip(sol.modes, analytic(len(sol.modes))):
        print(f"{m.index + 1:>4} {m.f / 1e9:>13.5f} {f / 1e9:>15.5f} "
              f"{100 * (m.f / f - 1):>7.3f}%")

    d2, _ = ae.open_hfss(os.path.join(HERE, "copper_cavity_eigenmode.aedt"))
    m = d2.solve(progress=False).modes[0]
    f0 = analytic(1)[0]
    k = 2 * math.pi * f0 / c0
    mu0, eta, sigma = 4e-7 * math.pi, 376.730313668, 5.8e7
    rs = math.sqrt(2 * math.pi * f0 * mu0 / (2 * sigma))
    qc = ((k * A * D) ** 3 * B * eta / (2 * math.pi ** 2 * rs)
          / (2 * A ** 3 * B + 2 * B * D ** 3 + A ** 3 * D + A * D ** 3))
    print(f"\ncopper cavity TE101: f = {m.f / 1e9:.5f} GHz, Q = {m.q:.0f} "
          f"(Pozar Qc = {qc:.0f}, {100 * (m.q / qc - 1):+.2f} %)")


if __name__ == "__main__":
    main()
