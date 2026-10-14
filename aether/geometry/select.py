"""
Face selectors -- how boundary conditions and ports find their triangles.

A selector is a callable ``(centroids[N,3], normals[N,3]) -> bool[N]`` applied
to the *boundary triangles* of the generated mesh.  Making selection geometric
(rather than a CAD-tag lookup) keeps boundary assignment identical whether the
mesh came from OpenCASCADE or from the built-in structured mesher, and it
survives remeshing during adaptive passes -- which tag-based selection does
not.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import numpy as np

from ..core.constants import to_si

Selector = Callable[[np.ndarray, np.ndarray], np.ndarray]


@dataclass
class PlaneSelector:
    """
    Triangles whose centroid lies on ``axis = value``.

    Optionally restricted to a rectangular window in the two in-plane
    directions -- this is how a wave port picks out one cross-section of a
    boundary wall.
    """
    axis: str = "z"
    value: float = 0.0
    tol: float = 1e-9
    window: Optional[Sequence[Sequence[float]]] = None   # ((umin,umax),(vmin,vmax))
    normal_tol: float = 1e-3

    def __post_init__(self):
        self.value = to_si(self.value)
        self.tol = to_si(self.tol)
        self._ax = "xyz".index(self.axis.lower())
        if self.window is not None:
            self.window = [[to_si(a), to_si(b)] for a, b in self.window]

    def __call__(self, cen: np.ndarray, nrm: np.ndarray) -> np.ndarray:
        m = np.abs(cen[:, self._ax] - self.value) <= self.tol
        m &= np.abs(np.abs(nrm[:, self._ax]) - 1.0) <= self.normal_tol
        if self.window is not None:
            others = [i for i in range(3) if i != self._ax]
            for k, i in enumerate(others):
                lo, hi = self.window[k]
                m &= (cen[:, i] >= lo - self.tol) & (cen[:, i] <= hi + self.tol)
        return m


@dataclass
class BoxSelector:
    """Triangles whose centroid falls inside an axis-aligned box."""
    lo: Sequence[float] = (0, 0, 0)
    hi: Sequence[float] = (1, 1, 1)
    tol: float = 1e-9

    def __post_init__(self):
        self.lo = np.array([to_si(x) for x in self.lo])
        self.hi = np.array([to_si(x) for x in self.hi])
        self.tol = to_si(self.tol)

    def __call__(self, cen, nrm):
        return np.all((cen >= self.lo - self.tol) & (cen <= self.hi + self.tol), axis=1)


@dataclass
class ShapeSelector:
    """Triangles whose centroid lies on/inside a primitive (analytic test)."""
    shape: object = None
    tol: float = 1e-9

    def __call__(self, cen, nrm):
        from .implicit import contains
        return contains(self.shape, cen, tol=self.tol)


@dataclass
class CylinderSelector:
    center: Sequence[float] = (0, 0, 0)
    axis: Sequence[float] = (0, 0, 1)
    radius: float = 1.0
    height: float = 1.0
    tol: float = 1e-9

    def __post_init__(self):
        self.center = np.array([to_si(x) for x in self.center])
        a = np.array([float(x) for x in self.axis]); self.axis = a / np.linalg.norm(a)
        self.radius, self.height = to_si(self.radius), to_si(self.height)
        self.tol = to_si(self.tol)

    def __call__(self, cen, nrm):
        d = cen - self.center
        t = d @ self.axis
        r = np.linalg.norm(d - np.outer(t, self.axis), axis=1)
        return (t >= -self.tol) & (t <= self.height + self.tol) & \
               (r <= self.radius + self.tol)


@dataclass
class OuterSelector:
    """
    Every triangle on the *outer* boundary of the model (the classic
    radiation box or metal enclosure).

    ``outer_only`` tells the tagger to keep this selector away from internal
    sheets: without it, a blanket "PEC everywhere outside" would also short
    out the slot in an iris or the gap in a patch, since those triangles look
    identical to a purely geometric test.
    """
    exclude: Optional[Selector] = None
    outer_only: bool = True

    def __call__(self, cen, nrm):
        m = np.ones(len(cen), bool)
        if self.exclude is not None:
            m &= ~self.exclude(cen, nrm)
        return m


@dataclass
class BoundingBoxFaceSelector:
    """One face of the model bounding box, e.g. ``face='+z'``."""
    face: str = "+z"
    tol: float = 1e-9
    _bbox: Optional[tuple] = None
    outer_only: bool = True

    def bind(self, lo, hi) -> "BoundingBoxFaceSelector":
        self._bbox = (np.asarray(lo, float), np.asarray(hi, float))
        return self

    def __call__(self, cen, nrm):
        if self._bbox is None:
            lo, hi = cen.min(0), cen.max(0)
        else:
            lo, hi = self._bbox
        sign, ax = self.face[0], "xyz".index(self.face[1].lower())
        val = hi[ax] if sign == "+" else lo[ax]
        span = float(np.max(hi - lo)) or 1.0
        return np.abs(cen[:, ax] - val) <= max(self.tol, 1e-9 * span)


@dataclass
class FaceSelector:
    """
    One picked face of one object.

    A face picked in the viewport has to survive everything that happens
    afterwards -- remeshing on every adaptive pass, a change of mesh size, a
    reopened project -- so the *index* of the face is not what gets stored.
    What is stored is the geometry that identifies it: a reference point on
    the face, its outward normal there, and its extent. A boundary triangle
    belongs to the face when it sits in the same surface and inside that
    extent, which is a test the mesher can apply to any mesh of the same
    model.

    Planar faces (which is nearly everything in an RF model -- patches,
    ground planes, port cross-sections) are matched exactly: same plane, same
    normal direction, inside the outline. A curved face is matched by its
    extent and by the triangle normal pointing away from the face's own axis,
    which is tight enough for a cylinder wall or a fillet and is reported as
    approximate rather than pretended to be exact.
    """
    point: Sequence[float] = (0.0, 0.0, 0.0)
    normal: Sequence[float] = (0.0, 0.0, 1.0)
    lo: Sequence[float] = (0.0, 0.0, 0.0)
    hi: Sequence[float] = (0.0, 0.0, 0.0)
    planar: bool = True
    object: str = ""
    tol: float = 0.0
    outer_only: bool = False

    def __post_init__(self):
        self.point = np.asarray([to_si(x) for x in self.point], float)
        n = np.asarray([float(x) for x in self.normal], float)
        ln = float(np.linalg.norm(n))
        self.normal = n / ln if ln > 1e-300 else np.array([0.0, 0.0, 1.0])
        self.lo = np.asarray([to_si(x) for x in self.lo], float)
        self.hi = np.asarray([to_si(x) for x in self.hi], float)
        span = float(np.max(self.hi - self.lo)) if np.any(self.hi > self.lo) else 1.0
        # Tolerance scales with the face: an absolute one is either useless on
        # a 100 mm ground plane or impossibly tight on a 50 um gap.
        self.tol = to_si(self.tol) if self.tol else max(span * 1e-4, 1e-9)

    def __call__(self, cen: np.ndarray, nrm: np.ndarray) -> np.ndarray:
        d = self.tol
        inside = np.ones(len(cen), bool)
        for i in range(3):
            inside &= (cen[:, i] >= self.lo[i] - d) & (cen[:, i] <= self.hi[i] + d)
        if self.planar:
            off = (cen - self.point) @ self.normal
            inside &= np.abs(off) <= d
            inside &= np.abs(nrm @ self.normal) >= 0.9
        else:
            # Curved: the triangle must face outward from the face's own
            # bounding box centre, which separates a cylinder's wall from the
            # caps that share its extent.
            mid = 0.5 * (self.lo + self.hi)
            radial = cen - mid
            ln = np.linalg.norm(radial, axis=1, keepdims=True)
            radial = radial / np.maximum(ln, 1e-300)
            inside &= np.abs((nrm * radial).sum(1)) >= 0.35
        return inside

    def describe(self) -> str:
        kind = "planar" if self.planar else "curved"
        p = ", ".join(f"{x * 1e3:.3f}" for x in self.point)
        return f"{kind} face of {self.object or '?'} at ({p}) mm"


@dataclass
class Predicate:
    """Wrap an arbitrary user function."""
    func: Callable[[np.ndarray, np.ndarray], np.ndarray] = None

    def __call__(self, cen, nrm):
        return np.asarray(self.func(cen, nrm), bool)


class _Composite:
    """Base of selectors made from other selectors. They are classes, not
    closures, so a project file can write them down and read them back."""
    outer_only = False

    def __init__(self, *sels):
        self.sels = list(sels)


class UnionSelector(_Composite):
    def __call__(self, cen, nrm):
        m = np.zeros(len(cen), bool)
        for s in self.sels:
            m |= s(cen, nrm)
        return m


class IntersectSelector(_Composite):
    def __call__(self, cen, nrm):
        m = np.ones(len(cen), bool)
        for s in self.sels:
            m &= s(cen, nrm)
        return m


class InvertSelector(_Composite):
    def __call__(self, cen, nrm):
        return ~self.sels[0](cen, nrm)


class MultiFaceSelector(UnionSelector):
    """Several picked faces assigned together, as one boundary or one port."""

    def __init__(self, faces):
        super().__init__(*faces)
        self.faces = self.sels


def union_sel(*sels: Selector) -> Selector:
    return UnionSelector(*sels)


def intersect_sel(*sels: Selector) -> Selector:
    return IntersectSelector(*sels)


def invert_sel(sel: Selector) -> Selector:
    return InvertSelector(sel)


__all__ = ["Selector", "PlaneSelector", "BoxSelector", "ShapeSelector",
           "CylinderSelector", "OuterSelector", "BoundingBoxFaceSelector",
           "FaceSelector", "Predicate", "union_sel", "intersect_sel",
           "invert_sel", "UnionSelector", "IntersectSelector",
           "InvertSelector", "MultiFaceSelector"]
