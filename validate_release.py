"""Reproducible real FEM benchmark; no CAD backend or pytest required.

    python validate_release.py --output validation-local.json

This checks a uniform PEC WR-90 guide against its analytic TE10 response.
It is a narrow verification case, not a general accuracy certification.
"""

import argparse
import json
import math
import platform
import tempfile
from pathlib import Path
import numpy as np
import scipy
import aether as ae
from aether.core.constants import c0
from aether.gui.api import dispatch
from aether.gui.state import Session


def waveguide():
    s = Session()
    s.new_project("Parametric WR90")
    dispatch(
        s,
        "parameters.set",
        {"variables": {"W": "22.86mm", "H": "10.16mm", "L": "20mm"}},
    )
    dispatch(
        s,
        "modeler.draw",
        {"shape": "box", "name": "Guide", "params": {"size": ["W", "H", "L"]}},
    )
    d = s.design
    d.add_wave_port("Port1", axis="z", value=0)
    d.add_wave_port("Port2", axis="z", value="20mm")
    d.assign_pec_outer()
    st = d.add_setup("Setup1", "10GHz")
    st.add_sweep("XBand", points=["10GHz"])
    return s


def run():
    rows = []
    for order, size in [(1, 0.004), (1, 0.0025), (2, 0.005)]:
        s = waveguide()
        d = s.design
        d.setups[0].basis_order = order
        d.config.mesh.max_element_size = size
        sol = d.solve(backend="builtin", adaptive=False, save_fields=False)
        sp = sol.sparams
        beta = math.sqrt((2 * math.pi * 1e10 / c0) ** 2 - (math.pi / 0.02286) ** 2)
        err = float(
            abs(np.degrees(np.angle(sp.s[0, 1, 0] / np.exp(-1j * beta * 0.02))))
        )
        row = dict(
            basisOrder=order,
            meshSizeM=size,
            tetrahedra=len(d.mesh.tets),
            s11Magnitude=float(abs(sp.s[0, 0, 0])),
            s21Magnitude=float(abs(sp.s[0, 1, 0])),
            phaseErrorDegrees=err,
            runtimeSeconds=sol.runtime,
        )
        row["passed"] = bool(
            err < 0.5
            and row["s11Magnitude"] < 0.001
            and abs(row["s21Magnitude"] - 1) < 2e-4
            and sp.is_passive()
            and sp.is_reciprocal(1e-6)
        )
        rows.append(row)
        print(
            "Order %d / h %.2f mm: phase error %.6f deg, %s"
            % (order, size * 1000, err, "PASS" if row["passed"] else "FAIL")
        )
    with tempfile.TemporaryDirectory() as folder:
        s = waveguide()
        path = str(Path(folder) / "roundtrip.warpz")
        dispatch(s, "project.save", {"path": path})
        dispatch(s, "project.open", {"path": path})
        dispatch(s, "parameters.set", {"variables": {"W": "24mm"}})
        dispatch(s, "project.save")
        dispatch(s, "project.open", {"path": path})
        roundtrip = bool(
            np.isclose(s.design.bounding_box()[1][0], 0.024)
            and s.design.variables["W"] == "24mm"
        )
    return dict(
        version=ae.__version__,
        python=platform.python_version(),
        platform=platform.platform(),
        numpy=np.__version__,
        scipy=scipy.__version__,
        case="PEC WR90, vacuum, 20mm long, 10GHz, TE10, builtin mesh, no adaptivity",
        limits="This benchmark does not validate arbitrary CAD, radiation, PML or Warps equivalence.",
        benchmarks=rows,
        parametricSaveReopenPassed=roundtrip,
        passed=all(r["passed"] for r in rows) and roundtrip,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="validation-local.json")
    parser.add_argument(
        "--example", help="Also save a parametric WR90 .warpz project at this path"
    )
    args = parser.parse_args()
    report = run()
    Path(args.output).write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if args.example:
        s = waveguide()
        s.design.config.mesh.max_element_size = 0.004
        s.design.setups[0].sweeps.clear()
        s.design.setups[0].add_sweep("XBand", "8GHz", "12GHz", 9)
        dispatch(s, "project.save", {"path": args.example})
    print("Report:", args.output)
    raise SystemExit(0 if report["passed"] else 1)
