"""Parametric editing, studies, diagnostics and CAD export commands."""

from __future__ import annotations
import copy
import math
import threading
import time
import numpy as np
from ..parametric import Scope, FIELDS, definition, make_primitive, rebuild
from ..core.constants import to_si


def _object(s, name=""):
    names = [name] if name else list(s.selection)
    if len(names) != 1:
        raise ValueError("Select exactly one object")
    return next(
        (o for o in s.require_design().solids + s.design.sheets if o.name == names[0]),
        None,
    ) or _missing(names[0])


def _missing(name):
    raise ValueError(f"No object named {name}")


def metrics(sp, port=1, threshold=-10.0, freq=None):
    if not 1 <= int(port) <= sp.n_port:
        raise ValueError("Port index out of range")
    f = np.asarray(sp.freq)
    db = sp.db(int(port), int(port))
    idx = int(np.argmin(db))
    threshold = float(threshold)
    if not math.isfinite(threshold) or threshold >= 0:
        raise ValueError("Return-loss threshold must be negative dB")
    bands = []
    start = None
    for k in range(len(f)):
        inside = db[k] <= threshold
        if inside and start is None:
            start = float(f[k])
            if k and db[k - 1] > threshold:
                start = float(
                    f[k - 1]
                    + (f[k] - f[k - 1]) * (threshold - db[k - 1]) / (db[k] - db[k - 1])
                )
        if start is not None and (not inside or k == len(f) - 1):
            end = float(f[k])
            if not inside and k:
                end = float(
                    f[k - 1]
                    + (f[k] - f[k - 1]) * (threshold - db[k - 1]) / (db[k] - db[k - 1])
                )
            bands.append(
                {
                    "start": start,
                    "stop": end,
                    "bandwidth": end - start,
                    "clipped": start == float(f[0]) or end == float(f[-1]),
                }
            )
            start = None
    marker = int(np.argmin(abs(f - float(freq)))) if freq is not None else idx
    z = sp.sij(int(port), int(port))[marker]
    return {
        "minimumDb": float(db[idx]),
        "minimumFrequency": float(f[idx]),
        "thresholdDb": threshold,
        "bands": bands,
        "marker": {
            "frequency": float(f[marker]),
            "db": float(db[marker]),
            "real": float(z.real),
            "imag": float(z.imag),
        },
        "passive": bool(sp.is_passive()),
        "reciprocal": bool(sp.is_reciprocal(1e-4)),
        "note": "Minima and marker use solved samples; threshold crossings use linear interpolation in dB. Sweep-edge bands may be incomplete.",
    }


def _clone(d):
    from ..model import Design

    work = Design(d.name)
    work.restore(d.snapshot())
    return work


def study_worker(s, base, variable, values, setup, backend, adaptive):
    from ..fem.control import checkpoint, SolveCancelled

    try:
        for i, value in enumerate(values):
            checkpoint(s.cancel_event)
            work = _clone(base)
            variables = dict(work.variables)
            variables[variable] = str(value)
            rebuild(work, variables)
            with s._lock:
                s.job.stage = f"case {i+1}/{len(values)}: {variable}={value}"
            sol = work.solve(
                setup=setup or None,
                backend=backend,
                adaptive=adaptive,
                save_fields=False,
                cancel=s.cancel_event,
            )
            summary = metrics(sol.sparams)
            row = {
                "index": i + 1,
                "variable": variable,
                "value": str(value),
                "runtime": sol.runtime,
                "metrics": summary,
                "freq": sol.freqs.tolist(),
                "s11Db": sol.sparams.db(1, 1).tolist(),
                "convergence": sol.convergence,
            }
            with s._lock:
                s.study_results.append(row)
                s.job.freq_done = i + 1
        with s._lock:
            s.job.stage = "complete"
    except Exception as exc:
        with s._lock:
            s.job.error = str(exc)
            s.job.stage = "cancelled" if isinstance(exc, SolveCancelled) else "failed"
        s.messages.add(
            f"Parameter study: {exc}",
            "warning" if isinstance(exc, SolveCancelled) else "error",
            "study",
        )
    finally:
        with s._lock:
            s.job.running = False
            s.job.done = True
            s.job.finished = time.time()


def register(command):
    @command("parameters.list")
    def variables(s, **_):
        d = s.require_design()
        scope = Scope(d.variables)
        rows = []
        for name, expr in d.variables.items():
            try:
                q = scope.variable(name)
                rows.append(
                    {
                        "name": name,
                        "expression": expr,
                        "si": q.value,
                        "dimension": q.dim,
                    }
                )
            except Exception as e:
                rows.append({"name": name, "expression": expr, "error": str(e)})
        return {"rows": rows}

    @command("parameters.set")
    def set_variables(s, variables=None, replace=False, **_):
        if not isinstance(variables, dict):
            raise ValueError("Variables must be a name/expression mapping")
        d = s.require_design()
        new = {} if replace else dict(d.variables)
        new.update(variables)
        return {"ok": True, "rebuilt": rebuild(d, new)}

    @command("modeler.primitiveInfo")
    def primitive_info(s, name="", **_):
        obj = _object(s, name)
        spec = definition(obj.shape, s.design.units)
        return {
            "name": obj.name,
            "definition": spec,
            "fields": FIELDS[spec["kind"]],
            "transforms": len(obj.shape._xform),
        }

    @command("modeler.editPrimitive")
    def primitive_edit(s, name="", params=None, **_):
        obj = _object(s, name)
        spec = definition(obj.shape, s.design.units)
        spec["params"].update(params or {})
        new = make_primitive(
            spec["kind"],
            spec["params"],
            obj.name,
            s.design.variables,
            spec.get("units", s.design.units),
        )
        old = obj.shape
        xform = old._xform
        if hasattr(old, "angle"):
            new.angle = old.angle
        old.__dict__.update(new.__dict__)
        old._xform = xform
        s.design.mesh = None
        return {
            "ok": True,
            "name": obj.name,
            "size": (np.array(old.bounds()[1]) - old.bounds()[0]).tolist(),
        }

    @command("analysis.diagnostics")
    def diagnostics(s, **_):
        from ..diagnostics import report

        return report(s.require_design())

    @command("analysis.controls")
    def controls(s, **_):
        return s.require_design().config.to_dict()

    @command("analysis.setControls")
    def set_controls(
        s, meshSize=None, solver="auto", tolerance=1e-8, convergedPasses=1, **_
    ):
        d = s.require_design()
        if solver not in ("auto", "direct", "iterative"):
            raise ValueError("Unknown solver strategy")
        tolerance = float(tolerance)
        convergedPasses = int(convergedPasses)
        if not math.isfinite(tolerance) or not 1e-14 <= tolerance <= 1e-2:
            raise ValueError("Solver tolerance must be 1e-14 to 1e-2")
        if not 1 <= convergedPasses <= 20:
            raise ValueError("Consecutive converged passes must be 1–20")
        h = (
            Scope(d.variables).length(meshSize, d.units)
            if meshSize not in (None, "")
            else None
        )
        if h is not None and h <= 0:
            raise ValueError("Mesh size must be positive")
        d.config.mesh.max_element_size = h
        d.config.solver.linear_solver = solver
        d.config.solver.tol = tolerance
        d.config.adaptive.min_converged_passes = convergedPasses
        d.mesh = None
        return {"ok": True}

    @command("analysis.cancel")
    def cancel(s, **_):
        if not s.job.running:
            return {"ok": True, "running": False}
        s.cancel_event.set()
        s.messages.add(
            "Cancellation requested; waiting for the current solver stage to finish.",
            "warning",
            "analysis",
        )
        return {"ok": True, "running": True}

    @command("analysis.study")
    def study(
        s, variable="", values=None, setup="", backend="auto", adaptive=False, **_
    ):
        if s.job.running:
            raise ValueError("An analysis or study is already running")
        d = s.require_design()
        if variable not in d.variables:
            raise ValueError("Define the design variable first")
        if not isinstance(values, list) or not 1 <= len(values) <= 50:
            raise ValueError("Enter 1–50 values")
        if backend not in ("auto", "builtin", "occ"):
            raise ValueError("Unknown mesh backend")
        # Reject unused variables: a study of identical geometry is not useful.
        import re
        from ..parametric import walk

        expressions = " ".join(
            str(getattr(sh, "_parametric", {}))
            for o in d.solids + d.sheets
            for sh in walk(o.shape)
        )

        def depends(expr, target, seen=None):
            seen = set(seen or ())
            if re.search(r"\b" + re.escape(target) + r"\b", expr):
                return True
            for key, value in d.variables.items():
                if (
                    key not in seen
                    and re.search(r"\b" + re.escape(key) + r"\b", expr)
                    and depends(str(value), target, seen | {key})
                ):
                    return True
            return False

        if not depends(expressions, variable):
            raise ValueError(
                "Variable is not bound to any primitive; edit a dimension to use it first"
            )
        for value in values:
            check = _clone(d)
            variables = dict(check.variables)
            variables[variable] = str(value)
            rebuild(check, variables)
            errors = check.validate()
            if errors:
                raise ValueError(f"{value}: " + "; ".join(errors))
        d.get_setup(setup or None)
        from .state import SolveJob

        s.study_results = []
        s.study_spec = {
            "variable": variable,
            "values": values,
            "setup": setup,
            "backend": backend,
            "adaptive": bool(adaptive),
        }
        s.cancel_event.clear()
        s.job = SolveJob(
            setup="Parameter study",
            running=True,
            started=time.time(),
            freq_total=len(values),
            stage="starting",
        )
        threading.Thread(
            target=study_worker,
            args=(s, _clone(d), variable, values, setup, backend, bool(adaptive)),
            daemon=True,
        ).start()
        return {"ok": True, "cases": len(values)}

    @command("analysis.studyResults")
    def study_results(s, **_):
        return {
            "spec": s.study_spec,
            "rows": copy.deepcopy(s.study_results),
            "job": s.job.to_json(),
        }

    @command("results.metrics")
    def results_metrics(s, port=1, threshold=-10.0, freq=None, **_):
        if s.solution is None:
            raise ValueError("Analyze the model first")
        return metrics(
            s.solution.sparams,
            port,
            threshold,
            to_si(freq, "frequency") if freq is not None else None,
        )

    @command("modeler.exportCad")
    def export_cad(s, path="", names=None, units="mm", **_):
        if s.job.running:
            raise ValueError("Wait for the running analysis before CAD export")
        from ..geometry.export import export_geometry

        return export_geometry(s.require_design(), path, names, units)

    @command("modeler.airRegion")
    def air_region(s, padding="20mm", name="AirRegion", **_):
        from ..geometry import primitives as prim
        from ..geometry.select import PlaneSelector, OuterSelector
        from .naming import unique_name

        d = s.require_design()
        if not d.solids:
            raise ValueError("Create the physical geometry first")
        blanket = [
            b.name
            for b in d.boundaries
            if isinstance(b.selector, OuterSelector) and b.btype != "radiation"
        ]
        if blanket:
            raise ValueError(
                "An outer-boundary assignment would also cover the new air region: "
                + ", ".join(blanket)
                + ". Replace it with object/face assignments before creating the radiation region."
            )
        gap = Scope(d.variables).length(padding, d.units)
        if gap <= 0:
            raise ValueError("Air padding must be positive")
        lo, hi = d.bounding_box()
        lo = lo - gap
        hi = hi + gap
        shell = prim.Box(lo, hi - lo)
        shell = prim.cut(shell, *[o.shape.copy() for o in d.solids])
        nm = unique_name([o.name for o in d.solids + d.sheets], name)
        d.add_solid(nm, shell, "air")
        d.solids[-1].display_transparency = 0.9
        for i, axis in enumerate("xyz"):
            for side, coord in [("min", lo[i]), ("max", hi[i])]:
                bn = unique_name(
                    [b.name for b in d.boundaries], nm + "_" + axis + "_" + side
                )
                d.assign_boundary(bn, "radiation", PlaneSelector(axis, float(coord)))
        d.mesh = None
        s.selection = [nm]
        return {
            "ok": True,
            "name": nm,
            "note": "Six first-order radiation planes. Recheck clearance after editing the physical geometry; this is not PML.",
        }
