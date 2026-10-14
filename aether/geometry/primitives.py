"""
Symbolic 3-D solid modelling.

Design note
-----------
Geometry is stored as a *symbolic operation tree*, never as an opaque handle
from the CAD kernel.  Two things fall out of that choice:

1. The same tree can be replayed into any kernel (OpenCASCADE via gmsh today,
   something else tomorrow) -- see :mod:`aether.geometry.kernel`.
2. The tree can be **serialised losslessly**, which is what lets Aether write
   real HFSS ``.aedt`` primitive commands on export instead of dumping a
   faceted mesh.  A round-tripped project keeps its parametric history.

All lengths are SI metres internally; constructors accept unit strings.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List, Sequence, Tuple

import numpy as np

from ..core.constants import to_si

Vec = Tuple[float, float, float]


def _v(p, default=(0.0, 0.0, 0.0)) -> Vec:
    """Coerce a point/vector; each component may carry a unit string."""
    if p is None:
        return tuple(float(x) for x in default)  # type: ignore
    if isinstance(p, (int, float)):
        return (float(p), float(p), float(p))
    seq = list(p)
    if len(seq) != 3:
        raise ValueError(f"expected a 3-component vector, got {p!r}")
    return tuple(to_si(x) for x in seq)  # type: ignore


def _norm(v: Vec) -> Vec:
    n = math.sqrt(sum(x * x for x in v))
    if n < 1e-300:
        raise ValueError("zero-length direction vector")
    return (v[0] / n, v[1] / n, v[2] / n)


# --------------------------------------------------------------------------
# Base
# --------------------------------------------------------------------------


@dataclass
class Shape:
    """Abstract node of the geometry tree."""
    name: str = ""
    _xform: List[dict] = field(default_factory=list, repr=False)

    # -- CSG operators ------------------------------------------------------
    def __or__(self, other: "Shape") -> "Boolean":
        return Boolean("union", [self, other])

    def __add__(self, other: "Shape") -> "Boolean":
        return Boolean("union", [self, other])

    def __sub__(self, other: "Shape") -> "Boolean":
        return Boolean("cut", [self, other])

    def __and__(self, other: "Shape") -> "Boolean":
        return Boolean("intersect", [self, other])

    # -- transforms (chainable, recorded symbolically) ----------------------
    def translate(self, dx=0.0, dy=0.0, dz=0.0) -> "Shape":
        self._xform.append({"op": "translate", "d": _v((dx, dy, dz))})
        return self

    def rotate(self, axis: str | Sequence[float] = "z", angle="0deg",
               origin=(0, 0, 0)) -> "Shape":
        if isinstance(axis, str):
            axis = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis.lower()]
        self._xform.append({"op": "rotate", "axis": _norm(_v(axis)),
                            "angle": to_si(angle, "angle", "deg"),
                            "origin": _v(origin)})
        return self

    def scale(self, sx=1.0, sy=None, sz=None, origin=(0, 0, 0)) -> "Shape":
        sy = sx if sy is None else sy
        sz = sx if sz is None else sz
        self._xform.append({"op": "scale", "s": (float(sx), float(sy), float(sz)),
                            "origin": _v(origin)})
        return self

    def mirror(self, normal=(0, 0, 1), origin=(0, 0, 0)) -> "Shape":
        self._xform.append({"op": "mirror", "n": _norm(_v(normal)), "origin": _v(origin)})
        return self

    def copy(self) -> "Shape":
        import copy as _c
        return _c.deepcopy(self)

    # -- introspection ------------------------------------------------------
    @property
    def kind(self) -> str:
        return type(self).__name__.lower()

    def children(self) -> List["Shape"]:
        return []

    def to_dict(self) -> Dict[str, Any]:
        d = {"kind": self.kind, "name": self.name, "xform": self._xform}
        d.update(self._params())
        ch = self.children()
        if ch:
            d["children"] = [c.to_dict() for c in ch]
        return d

    def _params(self) -> Dict[str, Any]:
        return {}

    def bounds(self) -> Tuple[Vec, Vec]:
        """Axis-aligned bounding box (analytic estimate, pre-transform aware)."""
        if isinstance(self, (Sphere, Cylinder, Cone, Torus, Polygon)):
            # Evaluate support extents after the full affine transform. Rotating
            # a sphere's old bounding cube must not enlarge the sphere.
            basis = np.vstack([np.zeros(3), np.eye(3)])
            for transform in self._xform:
                basis = _apply_xform_points(basis, transform)
            offset = basis[0]; matrix = (basis[1:] - offset).T
            if isinstance(self, Polygon):
                points = np.asarray(self.points) @ matrix.T + offset
                return tuple(points.min(axis=0)), tuple(points.max(axis=0))
            center = matrix @ np.asarray(self.center) + offset
            rownorm = np.linalg.norm(matrix, axis=1)
            if isinstance(self, Sphere):
                pad = self.radius * rownorm
                return tuple(center-pad), tuple(center+pad)
            axis = np.asarray(self.axis)
            projection = matrix @ axis
            radial = np.sqrt(np.maximum(rownorm**2-projection**2, 0.))
            if isinstance(self, Torus):
                pad = self.r_major*radial + self.r_minor*rownorm
                return tuple(center-pad), tuple(center+pad)
            end = center + self.height*projection
            r1 = self.radius if isinstance(self, Cylinder) else self.r1
            r2 = self.radius if isinstance(self, Cylinder) else self.r2
            return tuple(np.minimum(center-r1*radial,end-r2*radial)), tuple(np.maximum(center+r1*radial,end+r2*radial))
        lo, hi = self._local_bounds()
        pts = np.array([[x, y, z] for x in (lo[0], hi[0])
                        for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        for t in self._xform:
            pts = _apply_xform_points(pts, t)
        return tuple(pts.min(axis=0)), tuple(pts.max(axis=0))  # type: ignore

    def _local_bounds(self) -> Tuple[Vec, Vec]:  # pragma: no cover
        raise NotImplementedError


def _apply_xform_points(pts: np.ndarray, t: dict) -> np.ndarray:
    op = t["op"]
    if op == "translate":
        return pts + np.array(t["d"])
    if op == "rotate":
        return _rodrigues(pts, np.array(t["origin"]), np.array(t["axis"]), t["angle"])
    if op == "scale":
        o = np.array(t["origin"])
        return o + (pts - o) * np.array(t["s"])
    if op == "mirror":
        o, n = np.array(t["origin"]), np.array(t["n"])
        d = (pts - o) @ n
        return pts - 2.0 * np.outer(d, n)
    return pts  # pragma: no cover


def _rodrigues(pts: np.ndarray, origin: np.ndarray, axis: np.ndarray,
               ang: float) -> np.ndarray:
    k = axis / np.linalg.norm(axis)
    p = pts - origin
    c, s = math.cos(ang), math.sin(ang)
    return origin + p * c + np.cross(k, p) * s + np.outer(p @ k, k) * (1 - c)


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------


@dataclass
class Box(Shape):
    """Axis-aligned rectangular block from *position* with size *size*."""
    position: Vec = (0.0, 0.0, 0.0)
    size: Vec = (1.0, 1.0, 1.0)

    def __init__(self, position=(0, 0, 0), size=(1, 1, 1), name: str = ""):
        super().__init__(name=name)
        self.position = _v(position)
        self.size = _v(size)

    @classmethod
    def centered(cls, center=(0, 0, 0), size=(1, 1, 1), name: str = "") -> "Box":
        c, s = _v(center), _v(size)
        return cls(tuple(c[i] - s[i] / 2 for i in range(3)), s, name)

    def _params(self):
        return {"position": self.position, "size": self.size}

    def _local_bounds(self):
        p, s = self.position, self.size
        lo = tuple(min(p[i], p[i] + s[i]) for i in range(3))
        hi = tuple(max(p[i], p[i] + s[i]) for i in range(3))
        return lo, hi  # type: ignore


@dataclass
class Cylinder(Shape):
    """Circular cylinder: base *center*, *axis* direction, *radius*, *height*."""
    center: Vec = (0.0, 0.0, 0.0)
    axis: Vec = (0.0, 0.0, 1.0)
    radius: float = 1.0
    height: float = 1.0
    angle: float = 2 * math.pi

    def __init__(self, center=(0, 0, 0), radius=1.0, height=1.0,
                 axis=(0, 0, 1), angle="360deg", name: str = ""):
        super().__init__(name=name)
        self.center = _v(center)
        self.axis = _norm(_v(axis))
        self.radius = to_si(radius)
        self.height = to_si(height)
        self.angle = to_si(angle, "angle", "deg")

    def _params(self):
        return {"center": self.center, "axis": self.axis, "radius": self.radius,
                "height": self.height, "angle": self.angle}

    def _local_bounds(self):
        c = np.array(self.center)
        u = np.array(self.axis)
        a = u * self.height
        # The radius only widens the box across the axis, not along it: a
        # z-directed rod is not r taller at each end than it really is.
        pad = self.radius * np.sqrt(np.maximum(1.0 - u * u, 0.0))
        lo = np.minimum(c, c + a) - pad
        hi = np.maximum(c, c + a) + pad
        return tuple(lo), tuple(hi)  # type: ignore


@dataclass
class Sphere(Shape):
    center: Vec = (0.0, 0.0, 0.0)
    radius: float = 1.0

    def __init__(self, center=(0, 0, 0), radius=1.0, name: str = ""):
        super().__init__(name=name)
        self.center = _v(center)
        self.radius = to_si(radius)

    def _params(self):
        return {"center": self.center, "radius": self.radius}

    def _local_bounds(self):
        c, r = np.array(self.center), self.radius
        return tuple(c - r), tuple(c + r)  # type: ignore


@dataclass
class Cone(Shape):
    """Truncated cone / frustum."""
    center: Vec = (0.0, 0.0, 0.0)
    axis: Vec = (0.0, 0.0, 1.0)
    r1: float = 1.0
    r2: float = 0.0
    height: float = 1.0

    def __init__(self, center=(0, 0, 0), r1=1.0, r2=0.0, height=1.0,
                 axis=(0, 0, 1), name: str = ""):
        super().__init__(name=name)
        self.center = _v(center)
        self.axis = _norm(_v(axis))
        self.r1, self.r2, self.height = to_si(r1), to_si(r2), to_si(height)

    def _params(self):
        return {"center": self.center, "axis": self.axis, "r1": self.r1,
                "r2": self.r2, "height": self.height}

    def _local_bounds(self):
        c = np.array(self.center); a = np.array(self.axis) * self.height
        r = max(self.r1, self.r2)
        return tuple(np.minimum(c, c + a) - r), tuple(np.maximum(c, c + a) + r)  # type: ignore


@dataclass
class Torus(Shape):
    center: Vec = (0.0, 0.0, 0.0)
    axis: Vec = (0.0, 0.0, 1.0)
    r_major: float = 1.0
    r_minor: float = 0.2

    def __init__(self, center=(0, 0, 0), r_major=1.0, r_minor=0.2,
                 axis=(0, 0, 1), name: str = ""):
        super().__init__(name=name)
        self.center = _v(center)
        self.axis = _norm(_v(axis))
        self.r_major, self.r_minor = to_si(r_major), to_si(r_minor)

    def _params(self):
        return {"center": self.center, "axis": self.axis,
                "r_major": self.r_major, "r_minor": self.r_minor}

    def _local_bounds(self):
        c = np.array(self.center); R = self.r_major + self.r_minor
        return tuple(c - R), tuple(c + R)  # type: ignore


@dataclass
class Polygon(Shape):
    """Planar closed polygon (a sheet).  Points must be coplanar."""
    points: List[Vec] = field(default_factory=list)

    def __init__(self, points, name: str = ""):
        super().__init__(name=name)
        self.points = [_v(p) for p in points]
        if len(self.points) < 3:
            raise ValueError("a polygon needs at least 3 points")

    def _params(self):
        return {"points": self.points}

    def _local_bounds(self):
        a = np.array(self.points)
        return tuple(a.min(axis=0)), tuple(a.max(axis=0))  # type: ignore

    def extrude(self, vector) -> "Extrude":
        return Extrude(self, vector, name=self.name)

    def revolve(self, axis=(0, 0, 1), origin=(0, 0, 0), angle="360deg") -> "Revolve":
        return Revolve(self, axis, origin, angle, name=self.name)


@dataclass
class Rectangle(Polygon):
    """Convenience axis-aligned planar rectangle on a coordinate plane."""

    def __init__(self, position=(0, 0, 0), size=(1, 1), plane: str = "xy",
                 name: str = ""):
        p = _v(position)
        u, v = to_si(size[0]), to_si(size[1])
        plane = plane.lower()
        if plane == "xy":
            pts = [p, (p[0] + u, p[1], p[2]), (p[0] + u, p[1] + v, p[2]),
                   (p[0], p[1] + v, p[2])]
        elif plane == "yz":
            pts = [p, (p[0], p[1] + u, p[2]), (p[0], p[1] + u, p[2] + v),
                   (p[0], p[1], p[2] + v)]
        elif plane in ("xz", "zx"):
            pts = [p, (p[0] + u, p[1], p[2]), (p[0] + u, p[1], p[2] + v),
                   (p[0], p[1], p[2] + v)]
        else:
            raise ValueError(f"unknown plane {plane!r}")
        super().__init__(pts, name=name)
        self.plane = plane


@dataclass
class Circle(Shape):
    """Planar circular sheet."""
    center: Vec = (0.0, 0.0, 0.0)
    axis: Vec = (0.0, 0.0, 1.0)
    radius: float = 1.0

    def __init__(self, center=(0, 0, 0), radius=1.0, axis=(0, 0, 1), name: str = ""):
        super().__init__(name=name)
        self.center = _v(center)
        self.axis = _norm(_v(axis))
        self.radius = to_si(radius)

    def _params(self):
        return {"center": self.center, "axis": self.axis, "radius": self.radius}

    def _local_bounds(self):
        c, r = np.array(self.center), self.radius
        return tuple(c - r), tuple(c + r)  # type: ignore


@dataclass
class Extrude(Shape):
    """Linear sweep of a planar profile."""
    profile: Shape = None       # type: ignore
    vector: Vec = (0.0, 0.0, 1.0)

    def __init__(self, profile: Shape, vector, name: str = ""):
        super().__init__(name=name or profile.name)
        self.profile = profile
        self.vector = _v(vector)

    def children(self):
        return [self.profile]

    def _params(self):
        return {"vector": self.vector}

    def _local_bounds(self):
        lo, hi = self.profile.bounds()
        a = np.array([lo, hi]); v = np.array(self.vector)
        pts = np.vstack([a, a + v])
        return tuple(pts.min(axis=0)), tuple(pts.max(axis=0))  # type: ignore


@dataclass
class Revolve(Shape):
    """Rotational sweep of a planar profile."""
    profile: Shape = None       # type: ignore
    axis: Vec = (0.0, 0.0, 1.0)
    origin: Vec = (0.0, 0.0, 0.0)
    angle: float = 2 * math.pi

    def __init__(self, profile: Shape, axis=(0, 0, 1), origin=(0, 0, 0),
                 angle="360deg", name: str = ""):
        super().__init__(name=name or profile.name)
        self.profile = profile
        self.axis = _norm(_v(axis))
        self.origin = _v(origin)
        self.angle = to_si(angle, "angle", "deg")

    def children(self):
        return [self.profile]

    def _params(self):
        return {"axis": self.axis, "origin": self.origin, "angle": self.angle}

    def _local_bounds(self):
        lo, hi = self.profile.bounds()
        c = np.array(self.origin)
        r = float(np.max(np.abs(np.array([lo, hi]) - c))) + 1e-12
        return tuple(c - r), tuple(c + r)  # type: ignore


@dataclass
class FaceOperation(Shape):
    """
    A modelling operation applied to picked faces of a body.

    This is how a solid grows and moves in a modeller once it exists: pick the
    top of a patch and sweep it 0.2 mm to give it thickness; pick the end of a
    line and move that face 3 mm to lengthen it. Both are recorded here as
    *what was done to which face*, not as a new lump of geometry, so the
    operation replays whenever the model is rebuilt and stays editable
    afterwards -- change the distance and the body follows.

    ``faces`` holds the same reference data a face pick carries (a point on
    the face, its outward normal, and its extent); the face is located again
    at build time by that geometry rather than by an index, which is what
    makes it survive a change to anything else in the model.

    ``op``
        ``sweep``  -- extrude the face along its normal and add the result
        ``move``   -- move the face along its normal, growing or trimming the
                      body (a negative distance cuts into it)
    """
    base: Optional[Shape] = None
    faces: List[dict] = field(default_factory=list)
    op: str = "sweep"
    distance: float = 0.0

    def __init__(self, base: Shape, faces: Sequence[dict], op: str = "sweep",
                 distance=0.0, name: str = ""):
        super().__init__(name=name or getattr(base, "name", ""))
        self.base = base
        self.faces = [dict(f) for f in faces]
        self.op = op
        self.distance = to_si(distance)

    def children(self):
        return [self.base] if self.base is not None else []

    def _params(self):
        return {"op": self.op, "distance": self.distance,
                "faces": len(self.faces)}

    def _local_bounds(self):
        lo, hi = self.base.bounds()
        lo, hi = np.array(lo, float), np.array(hi, float)
        d = abs(float(self.distance))
        for f in self.faces:
            n = np.asarray(f.get("normal", (0, 0, 1)), float)
            ln = float(np.linalg.norm(n))
            if ln < 1e-300:
                continue
            n = n / ln
            grow = n * d
            lo = np.minimum(lo, lo + np.minimum(grow, 0.0))
            hi = np.maximum(hi, hi + np.maximum(grow, 0.0))
        return tuple(lo), tuple(hi)


@dataclass
class Boolean(Shape):
    """CSG node: ``union`` | ``cut`` | ``intersect``."""
    op: str = "union"
    operands: List[Shape] = field(default_factory=list)

    def __init__(self, op: str, operands: Sequence[Shape], name: str = ""):
        super().__init__(name=name or (operands[0].name if operands else ""))
        self.op = op
        self.operands = list(operands)

    def children(self):
        return self.operands

    def _params(self):
        return {"op": self.op}

    def _local_bounds(self):
        bs = [o.bounds() for o in self.operands]
        if self.op == "union":
            lo = np.min([b[0] for b in bs], axis=0)
            hi = np.max([b[1] for b in bs], axis=0)
        elif self.op == "intersect":
            lo = np.max([b[0] for b in bs], axis=0)
            hi = np.min([b[1] for b in bs], axis=0)
        else:                       # cut -> bounded by first operand
            lo, hi = bs[0]
        return tuple(lo), tuple(hi)  # type: ignore


@dataclass
class ImportedShape(Shape):
    """
    A solid loaded from a CAD file (STEP / IGES / BREP / STL).

    ``unit`` says how to interpret the file's numbers. ``"auto"`` honours the
    unit a STEP or IGES file declares and assumes millimetres for STL and OBJ,
    which declare nothing -- the assumption every mechanical CAD tool makes.
    """
    path: str = ""
    healing: str = "auto"
    scale_to_m: float = 1.0
    unit: str = "auto"
    #: which body of the file this object is; -1 means the whole file
    body: int = -1
    #: why this body has no geometry yet, empty when it reads fine
    _cad_unreadable: str = ""

    def __init__(self, path: str, name: str = "", healing="auto",
                 scale_to_m: float = 1.0, unit: str = "auto", body: int = -1):
        super().__init__(name=name)
        self.path, self.healing = path, healing
        self.scale_to_m = float(scale_to_m)
        self.unit = unit or "auto"
        self.body = int(body)
        self._cad_unreadable = ""

    def _params(self):
        return {"path": self.path, "healing": self.healing,
                "scale_to_m": self.scale_to_m, "unit": self.unit,
                "body": self.body}

    def _local_bounds(self):
        from .brep_io import quick_bounds
        # A body whose file is missing or in a format the kernel cannot read
        # must not take the whole model down with it: it reports an empty
        # extent, stays in the tree with everything assigned to it, and says
        # what it needs. ``_cad_unreadable`` carries that reason.
        if getattr(self, "_cad_unreadable", ""):
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        try:
            if self.body >= 0:
                from .brep_io import body_bounds
                return body_bounds(self.path, self.body, self.scale_to_m,
                                   self.unit)
            return quick_bounds(self.path, self.scale_to_m, self.unit)
        except Exception as exc:
            self._cad_unreadable = str(exc)
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)


def union(*shapes: Shape) -> Shape:
    shapes = tuple(s for s in shapes if s is not None)
    if len(shapes) == 1:
        return shapes[0]
    return Boolean("union", shapes)


def cut(base: Shape, *tools: Shape) -> Shape:
    return Boolean("cut", (base,) + tools)


def intersect(*shapes: Shape) -> Shape:
    return Boolean("intersect", shapes)


__all__ = [
    "Shape", "Box", "Cylinder", "Sphere", "Cone", "Torus", "Polygon",
    "Rectangle", "Circle", "Extrude", "Revolve", "Boolean", "ImportedShape",
    "FaceOperation",
    "union", "cut", "intersect", "Vec",
]


class Sketch(Shape):
    """Display-only polyline reference; never a solved sheet or volume."""
    reference_only = True

    def __init__(self, paths, name=''):
        super().__init__(name=name)
        self.paths = [[_v(point) for point in path] for path in paths if len(path)>=2]
        if not self.paths or not np.isfinite([v for path in self.paths for p in path for v in p]).all():
            raise ValueError('Sketch requires finite polyline coordinates')

    def _params(self):
        return {'paths':self.paths}

    def _local_bounds(self):
        points=np.array([p for path in self.paths for p in path])
        return tuple(points.min(axis=0)),tuple(points.max(axis=0))
