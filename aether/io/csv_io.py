"""CSV export of network data, port modes and sweeps (Excel-friendly)."""
from __future__ import annotations

import csv
from typing import Optional, Sequence

import numpy as np


def write_sparam_csv(path: str, sp, form: str = "db_deg") -> str:
    """Write S-parameters as one row per frequency."""
    n = sp.n_port
    head = ["Freq[Hz]"]
    for i in range(1, n + 1):
        for j in range(1, n + 1):
            if form == "ri":
                head += [f"re(S{i}{j})", f"im(S{i}{j})"]
            elif form == "mag_deg":
                head += [f"mag(S{i}{j})", f"ang(S{i}{j})[deg]"]
            else:
                head += [f"dB(S{i}{j})", f"ang(S{i}{j})[deg]"]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        for k in range(sp.n_freq):
            row = [f"{sp.freq[k]:.10g}"]
            for i in range(n):
                for j in range(n):
                    z = sp.s[k, i, j]
                    if form == "ri":
                        row += [f"{z.real:.10g}", f"{z.imag:.10g}"]
                    elif form == "mag_deg":
                        row += [f"{abs(z):.10g}",
                                f"{np.degrees(np.angle(z)):.10g}"]
                    else:
                        row += [f"{20*np.log10(max(abs(z),1e-300)):.10g}",
                                f"{np.degrees(np.angle(z)):.10g}"]
            w.writerow(row)
    return path


def read_csv_table(path: str):
    """Read a numeric CSV with a single header row into (header, array)."""
    with open(path, newline="") as fh:
        rows = list(csv.reader(fh))
    head = rows[0]
    data = np.array([[float(x) for x in r] for r in rows[1:] if r], float)
    return head, data


def write_port_modes_csv(path: str, solution) -> str:
    """Per-frequency modal data for every port (beta, cutoff, impedance)."""
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Freq[Hz]", "Port", "Mode", "Type", "beta[rad/m]",
                    "alpha[Np/m]", "fc[Hz]",
                    "Re(Zwave)[ohm]", "Im(Zwave)[ohm]",
                    "Re(Zpv)[ohm]", "Im(Zpv)[ohm]",
                    "Re(Zport)[ohm]", "Im(Zport)[ohm]", "Propagating"])
        for f in sorted(solution.ports):
            for ps in solution.ports[f]:
                for m in ps.modes:
                    w.writerow([f"{f:.10g}", ps.name, m.index + 1, m.kind,
                                f"{m.beta:.10g}", f"{m.alpha:.10g}",
                                f"{m.f_cut:.10g}",
                                f"{m.Z_wave.real:.10g}", f"{m.Z_wave.imag:.10g}",
                                f"{m.Z_pv.real:.10g}", f"{m.Z_pv.imag:.10g}",
                                f"{m.Z_port.real:.10g}", f"{m.Z_port.imag:.10g}",
                                int(m.propagating)])
    return path


__all__ = ["write_sparam_csv", "read_csv_table", "write_port_modes_csv"]
