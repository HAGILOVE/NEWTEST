"""
Optional bridge to a real Ansys installation through **PyAEDT**.

Purpose: cross-validation and migration, not a dependency.  When PyAEDT and a
licensed AEDT are present you can

* push an Aether :class:`~aether.model.Design` into a live HFSS session,
* pull an HFSS solution back as :class:`~aether.post.sparam.SParameters`,
* run the same model in both engines and diff the S-parameters.

Nothing else in Aether imports this module, so the package works fine without
Ansys installed.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..core.constants import from_si
from ..core.logging import get_logger

log = get_logger("io.pyaedt")


def available() -> bool:
    """True if PyAEDT can be imported."""
    try:
        import pyaedt  # noqa: F401
        return True
    except Exception:
        return False


def _require():
    try:
        import pyaedt
        return pyaedt
    except Exception as exc:                     # pragma: no cover
        raise RuntimeError(
            "PyAEDT is not available. Install it with `pip install pyaedt` and "
            "make sure a licensed Ansys Electronics Desktop is installed."
        ) from exc


class HfssSession:
    """Context manager around a PyAEDT ``Hfss`` object."""

    def __init__(self, project: Optional[str] = None,
                 design: Optional[str] = None, version: Optional[str] = None,
                 non_graphical: bool = True, new_desktop: bool = False):
        self.kw = dict(project=project, design=design, version=version,
                       non_graphical=non_graphical,
                       new_desktop=new_desktop)
        self.app = None

    def __enter__(self):
        pyaedt = _require()
        kw = {k: v for k, v in self.kw.items() if v is not None}
        try:
            self.app = pyaedt.Hfss(**kw)
        except TypeError:                        # older PyAEDT keyword names
            legacy = dict(projectname=kw.get("project"),
                          designname=kw.get("design"),
                          specified_version=kw.get("version"),
                          non_graphical=kw.get("non_graphical", True),
                          new_desktop_session=kw.get("new_desktop", False))
            self.app = pyaedt.Hfss(**{k: v for k, v in legacy.items()
                                      if v is not None})
        return self.app

    def __exit__(self, *exc):
        if self.app is not None:
            try:
                self.app.release_desktop(close_projects=False,
                                         close_on_exit=False)
            except Exception:                    # pragma: no cover
                pass
        return False


def push_design(design, app, units: Optional[str] = None) -> Dict[str, Any]:
    """Recreate an Aether design inside a live HFSS session."""
    from ..geometry.primitives import Box, Cylinder, Sphere
    units = units or design.units
    app.modeler.model_units = units
    created: Dict[str, Any] = {}

    def L(v):
        return f"{from_si(float(v), units):.12g}{units}"

    for s in design.solids:
        sh = s.shape
        if isinstance(sh, Box):
            obj = app.modeler.create_box([L(x) for x in sh.position],
                                         [L(x) for x in sh.size],
                                         name=s.name,
                                         material=s.material.name)
        elif isinstance(sh, Cylinder):
            axis = "XYZ"[int(np.argmax(np.abs(sh.axis)))]
            obj = app.modeler.create_cylinder(axis,
                                              [L(x) for x in sh.center],
                                              L(sh.radius), L(sh.height),
                                              name=s.name,
                                              material=s.material.name)
        elif isinstance(sh, Sphere):
            obj = app.modeler.create_sphere([L(x) for x in sh.center],
                                            L(sh.radius), name=s.name,
                                            material=s.material.name)
        else:
            log.warning("solid %r (%s) has no direct PyAEDT primitive; "
                        "export it as STEP and import instead",
                        s.name, type(sh).__name__)
            continue
        created[s.name] = obj

    for st in design.setups:
        setup = app.create_setup(st.name)
        setup.props["Frequency"] = f"{st.frequency/1e9:.10g}GHz"
        setup.props["MaximumPasses"] = int(st.max_passes)
        setup.props["MaxDeltaS"] = float(st.delta_s)
        setup.update()
        for sw in st.sweeps:
            app.create_linear_count_sweep(
                setup=st.name, units="GHz",
                start_frequency=sw.start / 1e9, stop_frequency=sw.stop / 1e9,
                num_of_freq_points=int(sw.count), name=sw.name,
                sweep_type={"discrete": "Discrete", "fast": "Fast",
                            "interpolating": "Interpolating"}[sw.kind])
    return created


def pull_sparameters(app, setup: Optional[str] = None,
                     sweep: Optional[str] = None):
    """Read the solved S-matrix out of HFSS into an SParameters object."""
    from ..post.sparam import SParameters
    expr = app.get_traces_for_plot(category="S")
    sol = app.post.get_solution_data(expressions=expr,
                                     setup_sweep_name=(
                                         f"{setup} : {sweep}" if setup and sweep
                                         else None))
    if sol is None:
        raise RuntimeError("HFSS returned no solution data -- is it solved?")
    freq = np.asarray(sol.primary_sweep_values, float) * 1e9
    ports = sorted({p for e in expr for p in _ports_in(e)})
    n = len(ports)
    S = np.zeros((len(freq), n, n), complex)
    for e in expr:
        pr = _ports_in(e)
        if len(pr) != 2:
            continue
        i, j = ports.index(pr[0]), ports.index(pr[1])
        re = np.asarray(sol.data_real(e), float)
        im = np.asarray(sol.data_imag(e), float)
        S[:, i, j] = re + 1j * im
    return SParameters(freq, S, 50.0, ports)


def _ports_in(expr: str) -> List[str]:
    import re
    m = re.search(r"S\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)", expr)
    return [m.group(1).strip(), m.group(2).strip()] if m else []


def compare(design, aether_solution, app=None, tol_db: float = 0.5):
    """Solve in HFSS and report the worst-case dB difference per S entry."""
    with HfssSession() as hfss:
        target = app or hfss
        push_design(design, target)
        target.analyze()
        ref = pull_sparameters(target)
    ours = aether_solution.sparams
    n = min(ours.n_port, ref.n_port)
    out = {}
    for i in range(1, n + 1):
        for j in range(1, n + 1):
            a = ours.db(i, j)
            b = np.interp(ours.freq, ref.freq, ref.db(i, j))
            out[f"S{i}{j}"] = float(np.max(np.abs(a - b)))
    worst = max(out.values()) if out else 0.0
    log.info("HFSS cross-check: worst dB deviation %.3f (%s)", worst,
             "PASS" if worst <= tol_db else "FAIL")
    return out


__all__ = ["available", "HfssSession", "push_design", "pull_sparameters",
           "compare"]
