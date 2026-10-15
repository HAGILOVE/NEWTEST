"""
Modelling commands taken from the HFSS 100 Tips book: sweeping a profile around
an axis / along a vector / along a path, equation-based curves (ellipse,
helix, spiral ...), turning a line into a patterned trace, covering a closed
line with a face, and splitting a body with a coordinate plane.

They all work on named objects, replace or add exactly one thing per call and
are single undo steps like every other modeller command.
"""
from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence

import numpy as np

from ..core.constants import to_si
from ..geometry import primitives as prim
from ..geometry.primitives import Polygon, Sketch
from ..parametric import Quantity, Scope

AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def _metres(v, d) -> float:
    if isinstance(v, str):
        return to_si(v)
    return float(v)                       # a bare number is metres


def _vec3(v, d, what="point") -> List[float]:
    if v is None or len(v) != 3:
        raise ValueError(f"give the {what} as three coordinates (X, Y, Z)")
    return [_metres(x, d) for x in v]


def _entity(d, name):
    for o in list(d.solids) + list(d.sheets):
        if o.name == name:
            return o
    raise KeyError(f"no object named {name!r}")


def _sketch_points(ent) -> np.ndarray:
    sh = ent.shape
    if not isinstance(sh, Sketch):
        raise ValueError(f"{ent.name!r} is not a line (a drawn path or an equation curve)")
    pts = np.asarray(sh.paths[0], float)
    for t in sh._xform:
        pts = prim._apply_xform_points(pts, t)
    return pts


def _plane_basis(pts: np.ndarray):
    """(centroid, u, v, normal) of the plane best fitting the points."""
    c = pts.mean(axis=0)
    _, sv, vt = np.linalg.svd(pts - c, full_matrices=False)
    if len(sv) > 1 and sv[1] > 1e-9 * max(sv[0], 1e-30) and len(sv) > 2 and sv[2] > 1e-6 * max(sv[0], 1e-30):
        raise ValueError("the line is not flat; a pattern needs the line to lie in one plane")
    n = vt[2] if len(vt) > 2 else np.array([0.0, 0.0, 1.0])
    if len(sv) > 1 and sv[1] <= 1e-9 * max(sv[0], 1e-30):           # a straight line: any plane containing it
        a = vt[0]
        ref = np.array([0.0, 0.0, 1.0]) if abs(a[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        n = np.cross(a, np.cross(ref, a))
        n = n / np.linalg.norm(n)
    # prefer a coordinate-aligned normal when it is one
    k = int(np.argmax(np.abs(n)))
    if abs(n[k]) > 0.9999:
        n = np.eye(3)[k] * np.sign(n[k])
    u = pts[-1] - pts[0]
    u = u - np.dot(u, n) * n
    if np.linalg.norm(u) < 1e-12:
        u = vt[0]
    u = u / np.linalg.norm(u)
    v = np.cross(n, u)
    return c, u, v, n


def offset_outline(pts3: np.ndarray, width: float) -> List[List[float]]:
    """The outline of a line of the given width: the line offset both ways with
    mitred corners, as a closed polygon."""
    c, u, v, n = _plane_basis(pts3)
    P = np.column_stack([(pts3 - c) @ u, (pts3 - c) @ v])
    # drop repeated points
    keep = [0]
    for i in range(1, len(P)):
        if np.linalg.norm(P[i] - P[keep[-1]]) > 1e-12:
            keep.append(i)
    P = P[keep]
    if len(P) < 2:
        raise ValueError("the line needs two different points")
    h = width / 2.0
    seg = P[1:] - P[:-1]
    ln = np.linalg.norm(seg, axis=1)
    nrm = np.column_stack([-seg[:, 1], seg[:, 0]]) / ln[:, None]
    left, right = [], []
    for i, p in enumerate(P):
        if i == 0:
            off = nrm[0] * h
        elif i == len(P) - 1:
            off = nrm[-1] * h
        else:
            m = nrm[i - 1] + nrm[i]
            nm = np.linalg.norm(m)
            if nm < 1e-9:
                off = nrm[i] * h
            else:
                m = m / nm
                off = m * (h / max(float(m @ nrm[i]), 0.25))        # mitre, bounded for very sharp corners
        left.append(p + off)
        right.append(p - off)
    poly2 = left + right[::-1]
    return [(c + a * u + b * v).tolist() for a, b in poly2], n


def register(command) -> None:
    from . import api, naming

    # ------------------------------------------------------------- sweep
    @command("modeler.sweep")
    def _sweep(s, name: str = "", mode: str = "vector", axis: Any = "z", origin=None,
               angle: Any = "360deg", vector=None, path: str = "", material: str = "vacuum",
               keep: bool = False, newName: str = "", **_):
        """Draw > Sweep > Around Axis / Along Vector / Along Path of a flat object."""
        d = s.require_design()
        ent = _entity(d, name or (s.selection[0] if s.selection else ""))
        if ent not in d.sheets or isinstance(ent.shape, Sketch):
            raise ValueError("sweep needs a flat object (a drawn rectangle, circle or polygon)")
        profile = ent.shape
        if mode == "vector":
            vec = _vec3(vector, d, "sweep vector")
            if float(np.linalg.norm(vec)) <= 0:
                raise ValueError("the sweep vector is zero")
            new = prim.Extrude(profile, vec, name=ent.name)
            what = "along the vector"
        elif mode == "axis":
            ax = AXES.get(str(axis).lower()) if isinstance(axis, str) else tuple(float(x) for x in axis)
            if ax is None:
                raise ValueError("the sweep axis is X, Y or Z")
            org = _vec3(origin or ["0m", "0m", "0m"], d, "axis point")
            ang = to_si(angle, "angle", "deg") if isinstance(angle, str) else math.radians(float(angle))
            if not 0 < abs(ang) <= 2 * math.pi + 1e-9:
                raise ValueError("the sweep angle must be between 0 and 360 degrees")
            new = prim.Revolve(profile, ax, org, f"{math.degrees(ang):.12g}deg", name=ent.name)
            what = f"around the {axis} axis by {math.degrees(ang):g} degrees"
        elif mode == "path":
            pts = _sketch_points(_entity(d, path))
            new = prim.PathSweep(profile, pts.tolist(), name=ent.name)
            what = f"along {path}"
        else:
            raise ValueError(f"unknown sweep mode {mode!r}")
        nm = ent.name
        if keep:
            nm = naming.unique_name(naming.model_names(d), newName or ent.name + "_Sweep")
            new.name = nm
        else:
            d.sheets = [x for x in d.sheets if x is not ent]
        d.add_solid(nm, new, material or "vacuum")
        d.mesh = None
        s.dirty = True
        s.selection = [nm]
        s.messages.add(f"Swept {ent.name!r} {what}: solid {nm!r}.", "info", "modeler")
        return {"ok": True, "name": nm}

    # ------------------------------------------------------------- curves
    @command("modeler.curve")
    def _curve(s, kind: str = "equation", name: str = "", x: str = "0mm", y: str = "0mm", z: str = "0mm",
               tmin: Any = "0", tmax: Any = "1", points: int = 100, variables: Optional[dict] = None,
               color: str = "#ff6fb5", **_):
        """Draw > Equation Based Curve: x(_t), y(_t), z(_t) over a parameter range."""
        d = s.require_design()
        vs = dict(d.variables or {})
        vs.update({k: str(v) for k, v in (variables or {}).items() if str(v).strip()})
        sc0 = Scope(vs)
        t0 = float(sc0.evaluate(str(tmin)).value)
        t1 = float(sc0.evaluate(str(tmax)).value)
        n = int(round(float(sc0.evaluate(str(points)).value)))
        if not 2 <= n <= 20001:
            raise ValueError("the number of points is 2 to 20001")
        if t1 == t0:
            raise ValueError("the parameter range is empty (start = end)")
        from .measurement import UNITS
        unit = UNITS.get(d.units, 1e-3)
        out = []
        for tv in np.linspace(t0, t1, n):
            sc = Scope(vs)
            sc.cache["t"] = sc.cache["_t"] = Quantity(float(tv))
            row = []
            for ex in (x, y, z):
                q = sc.evaluate(ex)
                if q.dim == (1.0, 0.0, 0.0):
                    row.append(q.value)
                elif q.dim == (0.0, 0.0, 0.0):
                    row.append(q.value * unit)           # a bare number is in model units
                else:
                    raise ValueError(f"{ex!r} is not a length")
            out.append(row)
        pts = np.asarray(out, float)
        if not np.isfinite(pts).all():
            raise ValueError("the equations gave a non-finite value")
        nm = naming.unique_name(naming.model_names(d), name or kind.capitalize() + "Curve")
        sh = d.add_sheet(nm, Sketch([pts.tolist()], nm), None)
        sh.display_color = color
        d.mesh = None
        s.dirty = True
        s.selection = [nm]
        closed = bool(np.linalg.norm(pts[0] - pts[-1]) < 1e-9 * max(1.0, float(np.abs(pts).max())))
        s.messages.add(f"Curve {nm!r}: {n} points" + (", closed" if closed else "") + ".", "info", "modeler")
        return {"ok": True, "name": nm, "points": n, "closed": closed}

    @command("modeler.coverLines")
    def _cover(s, name: str = "", **_):
        """Modeler > Surface > Cover Lines: a closed flat line becomes a face."""
        d = s.require_design()
        ent = _entity(d, name or (s.selection[0] if s.selection else ""))
        pts = _sketch_points(ent)
        if np.linalg.norm(pts[0] - pts[-1]) > 1e-9 * max(1.0, float(np.abs(pts).max())):
            raise ValueError("the line is open: close it (end where it starts) before covering it")
        pts = pts[:-1]
        if len(pts) < 3:
            raise ValueError("a face needs at least three points")
        _plane_basis(np.vstack([pts, pts[:1]]))            # flatness check
        poly = Polygon(pts.tolist(), name=ent.name)
        ent.shape = poly
        ent.display_color = None
        d.mesh = None
        s.dirty = True
        s.messages.add(f"Covered {ent.name!r}: now a face.", "info", "modeler")
        return {"ok": True, "name": ent.name}

    @command("modeler.pathStrip")
    def _strip(s, name: str = "", kind: str = "line", width: Any = "1mm", height: Any = "0mm",
               material: str = "pec", newName: str = "", **_):
        """Draw > Lines with a cross-section: a line becomes a trace of a given width
        (a flat face), a rectangular bar, or a round wire."""
        d = s.require_design()
        ent = _entity(d, name or (s.selection[0] if s.selection else ""))
        pts = _sketch_points(ent)
        w = api.to_si(width) if isinstance(width, str) else float(width)
        h = api.to_si(height) if isinstance(height, str) else float(height)
        if w <= 0:
            raise ValueError("the width must be positive")
        nm = naming.unique_name(naming.model_names(d), newName or ent.name + "_Trace")
        if kind == "circle":
            c, u, v, n = _plane_basis(pts) if len(pts) > 2 else (pts[0], None, None, None)
            a = pts[1] - pts[0]
            a = a / np.linalg.norm(a)
            prof = prim.Circle(pts[0].tolist(), w / 2, a.tolist(), name=nm)
            shape = prim.PathSweep(prof, pts.tolist(), name=nm)
            d.add_solid(nm, shape, material or "pec")
        else:
            outline, n = offset_outline(pts, w)
            flat = Polygon(outline, name=nm)
            if kind == "line" or h == 0:
                d.add_sheet(nm, flat, d.materials.get(material) if material else None)
            elif kind == "rectangle":
                shape = prim.Extrude(flat, (n * h).tolist(), name=nm)
                d.add_solid(nm, shape, material or "pec")
            else:
                raise ValueError(f"unknown cross-section {kind!r}")
        d.mesh = None
        s.dirty = True
        s.selection = [nm]
        s.messages.add(f"{ent.name!r} patterned as a {kind} of width {w * 1e3:.4g} mm: {nm!r}.", "info", "modeler")
        return {"ok": True, "name": nm}

    # -------------------------------------------------------------- split
    @command("modeler.split")
    def _split(s, names: Optional[List[str]] = None, plane: str = "xy", offset: Any = "0mm",
               keep: str = "both", **_):
        """Modeler > Boolean > Split: cut bodies with a coordinate plane."""
        d = s.require_design()
        targets = list(names or s.selection)
        if not targets:
            raise ValueError("select the objects to split")
        ax = {"xy": 2, "yz": 0, "zx": 1, "xz": 1}.get(str(plane).lower())
        if ax is None:
            raise ValueError("the split plane is XY, YZ or ZX")
        at = api.to_si(offset) if isinstance(offset, str) else float(offset)
        if keep not in ("both", "positive", "negative"):
            raise ValueError("keep: both, positive or negative")
        made: List[str] = []
        for nm in targets:
            ent = _entity(d, nm)
            lo, hi = (np.asarray(v, float) for v in ent.shape.bounds())
            pad = 0.1 * float(np.max(hi - lo)) + 1e-4
            if not lo[ax] - 1e-12 < at < hi[ax] + 1e-12:
                s.messages.add(f"{nm}: the plane does not cut it.", "warning", "modeler")
                continue
            sizes = (hi - lo) + 2 * pad
            origin = lo - pad

            def half(side):
                p0, sz = origin.copy(), sizes.copy()
                if side > 0:
                    p0[ax], sz[ax] = at, hi[ax] + pad - at
                else:
                    p0[ax], sz[ax] = lo[ax] - pad, at - (lo[ax] - pad)
                return prim.intersect(ent.shape, prim.Box(p0.tolist(), sz.tolist(), name=nm))

            is_sheet = ent in d.sheets
            if keep == "both":
                pos, neg = half(+1), half(-1)
                pos.name = nm
                ent.shape = pos
                nn = naming.unique_name(naming.model_names(d), nm + "_1")
                neg.name = nn
                if is_sheet:
                    d.add_sheet(nn, neg, getattr(ent, "material", None))
                else:
                    d.add_solid(nn, neg, ent.material, ent.solve_inside)
                made += [nm, nn]
            else:
                new = half(+1 if keep == "positive" else -1)
                new.name = nm
                ent.shape = new
                made.append(nm)
        d.mesh = None
        s.dirty = True
        s.selection = made or targets
        s.messages.add(f"Split {', '.join(targets)} at {plane.upper()} = {at * 1e3:.4g} mm, kept {keep}.",
                       "info", "modeler")
        return {"ok": True, "names": made}

    # ---------------------------------------------------------- move edge
    @command("modeler.moveEdge")
    def _move_edge(s, name: str = "", a=None, b=None, distance: Any = "0mm", **_):
        """
        Modeler > Edge > Move Edges: slide one edge of a flat polygon sideways, in its
        plane. A positive distance moves it outwards, a negative one inwards, and the
        two neighbouring edges are lengthened or shortened to meet it -- so the
        gap between two patterns, or the width of a trace, is a number to change.
        """
        d = s.require_design()
        ent = _entity(d, name or (s.selection[0] if s.selection else ""))
        shape = ent.shape
        if ent not in d.sheets or not isinstance(shape, Polygon):
            raise ValueError("Move Edges works on the edges of a flat polygon or rectangle (a sheet)")
        A = np.asarray(_vec3(a, d, "edge start"), float)
        B = np.asarray(_vec3(b, d, "edge end"), float)
        dist = api.to_si(distance) if isinstance(distance, str) else float(distance)
        P = np.asarray(shape.points, float)
        for t in shape._xform:
            P = prim._apply_xform_points(P, t)
        n = len(P)
        tol = 1e-7 * max(1.0, float(np.abs(P).max())) + 1e-9
        k = None
        for i in range(n):
            p, q = P[i], P[(i + 1) % n]
            if (np.linalg.norm(p - A) < tol and np.linalg.norm(q - B) < tol) or \
                    (np.linalg.norm(p - B) < tol and np.linalg.norm(q - A) < tol):
                k = i
                break
            # an edge that was picked as a stretch of a longer straight side
            e = q - p
            L = float(np.linalg.norm(e))
            if L > 0:
                u = e / L
                da = np.linalg.norm(np.cross(A - p, u)); db = np.linalg.norm(np.cross(B - p, u))
                ta, tb = float((A - p) @ u), float((B - p) @ u)
                if da < tol and db < tol and -tol <= ta <= L + tol and -tol <= tb <= L + tol:
                    k = i
                    break
        if k is None:
            raise ValueError("that edge does not belong to this polygon")
        c, u, v, normal = _plane_basis(P)
        Q = np.column_stack([(P - c) @ u, (P - c) @ v])            # work in the plane
        p, q = Q[k], Q[(k + 1) % n]
        e = q - p
        L = float(np.linalg.norm(e))
        te = e / L
        out = np.array([te[1], -te[0]])
        area2 = sum(Q[i, 0] * Q[(i + 1) % n, 1] - Q[(i + 1) % n, 0] * Q[i, 1] for i in range(n))
        if area2 < 0:                                              # clockwise: the other way is outside
            out = -out
        new_p, new_q = p + out * dist, q + out * dist
        # the two vertices move to where the shifted edge line meets the neighbouring edge lines
        def meet(point, direction, other, other_dir):
            M = np.array([direction, -other_dir]).T
            if abs(np.linalg.det(M)) < 1e-12:
                return point                                       # parallel neighbour: slide only
            ts = np.linalg.solve(M, other - point)
            return point + ts[0] * direction
        prev = Q[(k - 1) % n]
        nxt = Q[(k + 2) % n]
        dprev = Q[k] - prev
        dnext = nxt - Q[(k + 1) % n]
        Q2 = Q.copy()
        Q2[k] = meet(new_p, te, prev, dprev / max(np.linalg.norm(dprev), 1e-300))
        Q2[(k + 1) % n] = meet(new_q, te, Q[(k + 1) % n], dnext / max(np.linalg.norm(dnext), 1e-300))
        W = c + np.outer(Q2[:, 0], u) + np.outer(Q2[:, 1], v)
        ent.shape = Polygon(W.tolist(), name=ent.name)
        # a boundary or a port on this sheet follows the new outline
        for old_sel_owner in list(d.boundaries) + list(d.ports):
            sel = old_sel_owner.selector
            if getattr(sel, "shape", None) is shape:
                sel.shape = ent.shape
        d.mesh = None
        s.dirty = True
        s.messages.add(f"Moved an edge of {ent.name!r} by {dist * 1e3:.4g} mm.", "info", "modeler")
        return {"ok": True, "name": ent.name}
