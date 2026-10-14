"""
Half-wave dipole: input impedance, radiation pattern and gain.

Opens ``dipole_antenna.warp`` (lumped port on a drawn feed sheet, radiation
boundary, 2nd-order elements), solves it and reports what an antenna engineer
asks first: where it resonates, what it presents to a 50 ohm source, and what
it radiates.

    python examples/10_dipole_antenna.py

Expect: resonance near 2.95 GHz with Zin ~ 69 ohm (the textbook half-wave
dipole is 73 ohm), peak directivity ~ 2.2 dBi (theory 2.15 dBi) at theta = 90
deg, and a null along the axis.  Takes about three minutes.
"""
import os

import numpy as np

import aether as ae

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ae.set_log_level("WARNING")
    design, report = ae.open_warps(os.path.join(HERE, "dipole_antenna.warp"))
    sol = design.solve(progress=False, save_fields=True)
    print(sol.summary())

    sp = sol.sparams
    z = 50 * (1 + sp.s[:, 0, 0]) / (1 - sp.s[:, 0, 0])
    k = int(np.argmin(np.abs(z.imag)))
    print(f"\nresonance (Im Zin = 0) : {sp.freq[k] / 1e9:.3f} GHz")
    print(f"Zin at resonance       : {z[k].real:.1f} {z[k].imag:+.1f}j ohm")
    j = int(np.argmin(sp.db(1, 1)))
    print(f"best match             : S11 = {sp.db(1, 1)[j]:.1f} dB "
          f"at {sp.freq[j] / 1e9:.3f} GHz")

    ff = sol.farfield(freq=sol.freqs[np.argmin(np.abs(sol.freqs - 3e9))])
    m = ff.summary()
    print(f"\npeak directivity       : {m['peakDirectivityDbi']:.2f} dBi "
          f"(theory 2.15)")
    print(f"direction of peak      : theta {m['peakTheta']:.0f} deg")
    print(f"radiation efficiency   : {100 * m['efficiency']:.1f} %")
    print(f"front-to-back          : {m['frontToBackDb']:.2f} dB")
    th, e_plane = ff.cut(0.0, "gain")
    print(f"gain on the axis       : {e_plane[0]:.1f} dBi (a dipole has a null there)")

    sol.sparams.write_touchstone(os.path.join(HERE, "dipole_antenna.s1p"))
    print("\nwrote examples/dipole_antenna.s1p")


if __name__ == "__main__":
    main()
