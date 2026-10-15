"""
Analytic point-membership for the primitive/CSG tree.

This is the dependency-free half of the geometry engine.  It lets Aether
classify mesh cells by material and build a usable structured mesh even when
no CAD kernel is installed, and it is also used to sanity-check OCC results.

Transforms are handled by mapping query points through the *inverse* of the
recorded transform stack, so no geometry is ever duplicated.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from .primitives import (Boolean, Box, Circle, Cone, Cylinder, Extrude,
                         ImportedShape, PathSweep, Polygon, Revolve, Shape, Sphere, Torus)


def contains(shape: Shape, pts: np.ndarray, tol: float = 0.0) -> np.ndarray:
    """Boolean mask: which of *pts* (N,3) lie inside *shape*."""
    p = np.atleast_2d(np.asarray(pts, dtype=float))
    for t in reversed(shape._xform):
        p = _inv_xform(p, t)
    return _contains_local(shape, p, tol)


def _inv_xform(pts: np.ndarray, t: dict) -> np.ndarray:
    op = t["op"]
    if op == "translate":
        return pts - np.array(t["d"])
    if op == "rotate":
        from .primitives import _rodrigues
        return _rodrigues(pts, np.array(t["origin"]), np.array(t["axis"]), -t["angle"])
    if op == "scale":
        o = np.array(t["origin"]); s = np.array(t["s"])
        return o + (pts - o) / np.where(np.abs(s) < 1e-300, 1.0, s)
    if op == "mirror":
        o, n = np.array(t["origin"]), np.array(t["n"])
        d = (pts - o) @ n
        return pts - 2.0 * np.outer(d, n)
    return pts


def _contains_local(s: Shape, p: np.ndarray, tol: float) -> np.ndarray:
    if isinstance(s, Box):
        lo = np.minimum(np.array(s.position), np.array(s.position) + np.array(s.size))
        hi = np.maximum(np.array(s.position), np.array(s.position) + np.array(s.size))
        return np.all((p >= lo - tol) & (p <= hi + tol), axis=1)

    if isinstance(s, Sphere):
        d = p - np.array(s.center)
        return (d * d).sum(1) <= (s.radius + tol) ** 2

    if isinstance(s, Cylinder):
        c = np.array(s.center); a = np.array(s.axis)
        d = p - c
        t = d @ a
        radial = d - np.outer(t, a)
        r = np.linalg.norm(radial, axis=1)
        inside = (t >= -tol) & (t <= s.height + tol) & (r <= s.radius + tol)
        if s.angle < 2 * math.pi - 1e-9:
            u, v = _basis(a)
            ang = np.arctan2(radial @ v, radial @ u) % (2 * math.pi)
            inside &= ang <= s.angle + 1e-12
        return inside

    if isinstance(s, Cone):
        c = np.array(s.center); a = np.array(s.axis)
        d = p - c
        t = d @ a
        radial = d - np.outer(t, a)
        r = np.linalg.norm(radial, axis=1)
        frac = np.clip(t / max(s.height, 1e-300), 0.0, 1.0)
        rt = s.r1 + (s.r2 - s.r1) * frac
        return (t >= -tol) & (t <= s.height + tol) & (r <= rt + tol)

    if isinstance(s, Torus):
        c = np.array(s.center); a = np.array(s.axis)
        d = p - c
        z = d @ a
        radial = d - np.outer(z, a)
        rho = np.linalg.norm(radial, axis=1)
        return (rho - s.r_major) ** 2 + z * z <= (s.r_minor + tol) ** 2

    if isinstance(s, Extrude):
        v = np.array(s.vector)
        L = np.linalg.norm(v)
        if L < 1e-300:
            return np.zeros(len(p), bool)
        n = v / L
        # project onto the profile plane
        base = np.array(s.profile.points[0]) if isinstance(s.profile, Polygon) \
            else np.array(getattr(s.profile, "center", (0, 0, 0)))
        t = (p - base) @ n
        proj = p - np.outer(t, n)
        inside = (t >= -tol) & (t <= L + tol)
        inside &= _contains_local(s.profile, proj, tol)
        return inside

    if isinstance(s, Polygon):
        return _in_polygon(s, p, tol)

    if isinstance(s, Circle):
        c = np.array(s.center); a = np.array(s.axis)
        d = p - c
        z = d @ a
        radial = d - np.outer(z, a)
        return (np.abs(z) <= 1e-9 + tol) & (np.linalg.norm(radial, axis=1) <= s.radius + tol)

    if isinstance(s, Boolean):
        res = contains(s.operands[0], p, tol)
        for o in s.operands[1:]:
            m = contains(o, p, tol)
            if s.op == "union":
                res |= m
            elif s.op == "cut":
                res &= ~m
            else:
                res &= m
        return res

    if isinstance(s, Revolve):
        # sample the swept profile: rotate query points back into the profile
        # half-plane and test there (valid for full 360-degree revolutions)
        a = np.array(s.axis); o = np.array(s.origin)
        d = p - o
        z = d @ a
        radial = d - np.outer(z, a)
        rho = np.linalg.norm(radial, axis=1)
        base = np.array(s.profile.points[0]) if isinstance(s.profile, Polygon) \
            else np.array(getattr(s.profile, "center", (0, 0, 0)))
        u, v = _basis(a)
        q = o + np.outer(rho, u) + np.outer(z, a)
        return _contains_local(s.profile, q, tol)

    if isinstance(s, PathSweep):
        raise NotImplementedError("point membership of a swept-along-path body needs the OCC kernel")

    if isinstance(s, ImportedShape):
        raise NotImplementedError(
            "point membership for imported CAD requires the OCC kernel; "
            "install gmsh or mesh with the OCC backend"
        )

    raise TypeError(f"no membership test for {type(s).__name__}")


def _basis(a: np.ndarray):
    a = a / np.linalg.norm(a)
    ref = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(a, ref); u /= np.linalg.norm(u)
    v = np.cross(a, u)
    return u, v


def _in_polygon(poly: Polygon, p: np.ndarray, tol: float) -> np.ndarray:
    pts = np.array(poly.points)
    n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
    nn = np.linalg.norm(n)
    if nn < 1e-300:
        return np.zeros(len(p), bool)
    n = n / nn
    dist = (p - pts[0]) @ n
    on_plane = np.abs(dist) <= 1e-9 + tol
    u = pts[1] - pts[0]; u /= np.linalg.norm(u)
    v = np.cross(n, u)
    P = np.stack([(pts - pts[0]) @ u, (pts - pts[0]) @ v], axis=1)
    Q = np.stack([(p - pts[0]) @ u, (p - pts[0]) @ v], axis=1)
    inside = _winding(P, Q)
    return on_plane & inside


def _winding(poly2d: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Vectorised even-odd ray-crossing test in 2-D."""
    n = len(poly2d)
    inside = np.zeros(len(q), bool)
    for i in range(n):
        x1, y1 = poly2d[i]
        x2, y2 = poly2d[(i + 1) % n]
        cond = ((y1 > q[:, 1]) != (y2 > q[:, 1]))
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (x2 - x1) * (q[:, 1] - y1) / np.where(y2 - y1 == 0, np.nan, y2 - y1) + x1
        crosses = cond & (q[:, 0] < np.nan_to_num(xint, nan=-np.inf))
        inside ^= crosses
    return inside


__all__ = ["contains"]
