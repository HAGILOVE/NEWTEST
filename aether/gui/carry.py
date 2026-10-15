"""
Assignments that belong to geometry follow it.

A boundary or a port is attached to a *face of an object* (a picked face, a
sheet), not to a place in space. Moving, rotating, mirroring or scaling the
object therefore has to take its assignments along, and copying it should copy
them too (HFSS: "Duplicate boundaries / mesh operations with geometry") --
otherwise a patch that was moved keeps its port where the patch used to be,
which is the kind of thing that makes a model silently wrong.

Everything here works on the transform records a shape keeps (``shape._xform``),
so it applies equally to move, rotate, mirror, scale and to the copies made by
Duplicate and Paste.
"""
from __future__ import annotations

import copy
from typing import List, Optional, Sequence

import numpy as np

from ..geometry.primitives import _apply_xform_points
from ..geometry.select import (FaceSelector, ShapeSelector, UnionSelector,
                               IntersectSelector, InvertSelector, _Composite)


def xf_points(ts: Sequence[dict], pts) -> np.ndarray:
    p = np.atleast_2d(np.asarray(pts, float))
    for t in ts:
        p = _apply_xform_points(p, t)
    return p


def xf_vector(ts: Sequence[dict], at, v) -> np.ndarray:
    """A direction carried through the transforms (a translation leaves it as it is)."""
    a = xf_points(ts, at)[0]
    b = xf_points(ts, np.asarray(at, float) + np.asarray(v, float))[0]
    w = b - a
    n = float(np.linalg.norm(w))
    return w / n if n > 1e-300 else np.asarray(v, float)


def _corners(lo, hi) -> np.ndarray:
    return np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1])
                     for z in (lo[2], hi[2])], float)


# --------------------------------------------------------------------------
# selectors
# --------------------------------------------------------------------------


def refers_to(sel, ent) -> bool:
    """Does this selector pick out (a part of) *ent*?"""
    if isinstance(sel, FaceSelector):
        return sel.object == ent.name
    if isinstance(sel, ShapeSelector):
        return sel.shape is ent.shape
    if isinstance(sel, _Composite):
        return any(refers_to(s, ent) for s in sel.sels)
    return False


def _face_moved(f: FaceSelector, ts, object_name: Optional[str] = None) -> FaceSelector:
    P = xf_points(ts, np.vstack([f.point, _corners(f.lo, f.hi)]))
    C = P[1:]
    return FaceSelector(point=P[0].tolist(), normal=xf_vector(ts, f.point, f.normal).tolist(),
                        lo=C.min(axis=0).tolist(), hi=C.max(axis=0).tolist(),
                        planar=f.planar, object=object_name if object_name is not None else f.object,
                        tol=0, outer_only=f.outer_only)


def follow_in_place(sel, ent, ts) -> None:
    """*ent* was just transformed by *ts*: update the selector's geometry."""
    if isinstance(sel, FaceSelector):
        if sel.object == ent.name:
            n = _face_moved(sel, ts)
            sel.point, sel.normal, sel.lo, sel.hi, sel.tol = n.point, n.normal, n.lo, n.hi, n.tol
    elif isinstance(sel, _Composite):
        for s in sel.sels:
            follow_in_place(s, ent, ts)
    # a ShapeSelector holds the shape itself, which moved with it


def copy_selector(sel, orig, new, ts):
    """The selector for a copy: only the parts that belong to *orig*, re-aimed at *new*."""
    if isinstance(sel, FaceSelector):
        return _face_moved(sel, ts, new.name) if sel.object == orig.name else None
    if isinstance(sel, ShapeSelector):
        return ShapeSelector(new.shape, tol=sel.tol) if sel.shape is orig.shape else None
    if isinstance(sel, _Composite):
        parts = [copy_selector(s, orig, new, ts) for s in sel.sels]
        parts = [p for p in parts if p is not None]
        if not parts:
            return None
        if isinstance(sel, InvertSelector):
            return InvertSelector(parts[0])
        if isinstance(sel, IntersectSelector):
            return IntersectSelector(*parts) if len(parts) == len(sel.sels) else None
        return parts[0] if len(parts) == 1 else UnionSelector(*parts)
    return None


# --------------------------------------------------------------------------
# the design's assignments
# --------------------------------------------------------------------------


def _line_moved(line, ts):
    if not line:
        return line
    a = xf_points(ts, line[0])[0]
    b = xf_points(ts, line[1])[0]
    return (tuple(float(v) for v in a), tuple(float(v) for v in b))


def carry_assignments(d, ent, ts: Sequence[dict]) -> int:
    """*ent* was transformed in place: its boundaries, ports and mesh faces follow."""
    n = 0
    for b in d.boundaries:
        if refers_to(b.selector, ent):
            follow_in_place(b.selector, ent, ts)
            dr = b.params.get("direction")
            if dr is not None:
                at = np.asarray(ent.shape.bounds()[0], float)
                b.params["direction"] = [float(v) for v in xf_vector(ts, at, dr)]
            n += 1
    for p in d.ports:
        if refers_to(p.selector, ent):
            follow_in_place(p.selector, ent, ts)
            line = getattr(p, "integration_line", None)
            if p.kind == "lumped":
                at = np.asarray(line[0] if line else ent.shape.bounds()[0], float)
                p.direction = [float(v) for v in xf_vector(ts, at, p.direction)]
            if line:
                p.integration_line = _line_moved(line, ts)
            n += 1
    for m in d.mesh_ops:
        if m.selector is not None and refers_to(m.selector, ent):
            follow_in_place(m.selector, ent, ts)
    return n


def _direction_of(line, fallback):
    a, b = np.asarray(line[0], float), np.asarray(line[1], float)
    v = b - a
    n = float(np.linalg.norm(v))
    return [float(x) for x in (v / n if n > 1e-12 else np.asarray(fallback, float))]


def _unique(existing: List[str], base: str) -> str:
    if base not in existing:
        return base
    k = 1
    while f"{base}_{k}" in existing:
        k += 1
    return f"{base}_{k}"


def duplicate_assignments(d, orig, new, ts: Sequence[dict]) -> List[str]:
    """
    *new* is a copy of *orig*, made by applying *ts* to it: give it its own
    copies of the boundaries, ports and mesh operations that belonged to *orig*.
    """
    made: List[str] = []
    from ..model import Boundary, LumpedPort, WavePort
    for b in list(d.boundaries):
        sel = copy_selector(b.selector, orig, new, ts)
        if sel is None:
            continue
        params = copy.deepcopy(b.params)
        if params.get("direction") is not None:
            at = np.asarray(orig.shape.bounds()[0], float)
            params["direction"] = [float(v) for v in xf_vector(ts, at, params["direction"])]
        nb = Boundary(_unique([x.name for x in d.boundaries], b.name), b.btype, sel, params,
                      getattr(b, "priority", 0))
        d.boundaries.append(nb)
        made.append(nb.name)
    for p in list(d.ports):
        sel = copy_selector(p.selector, orig, new, ts)
        if sel is None:
            continue
        name = _unique([x.name for x in d.ports], p.name)
        line = _line_moved(p.integration_line, ts) if getattr(p, "integration_line", None) else None
        if p.kind == "lumped":
            direction = _direction_of(line, p.direction) if line else list(
                xf_vector(ts, np.asarray(orig.shape.bounds()[0], float), p.direction))
            d.add_lumped_port(name, selector=sel, impedance=p.impedance, direction=direction,
                              integration_line=line)
        else:
            d.add_wave_port(name, selector=sel, num_modes=p.num_modes, deembed=p.deembed,
                            renormalize_z=p.renormalize_z, integration_line=line)
        made.append(name)
    for m in list(d.mesh_ops):
        if orig.name in (m.objects or []):
            nm = _unique([x.name for x in d.mesh_ops], m.name)
            d.add_mesh_operation(nm, m.max_length, objects=[new.name], enabled=m.enabled)
            made.append(nm)
    return made
