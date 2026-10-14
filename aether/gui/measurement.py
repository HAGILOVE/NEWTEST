"""Numerical measurements; inputs in display units, returned geometry in SI."""

from __future__ import annotations
import math
import numpy as np
from ..core.constants import to_si

UNITS = {"m": 1.0, "cm": 0.01, "mm": 0.001, "um": 1e-6, "mil": 2.54e-5, "in": 0.0254}


def vector_angle(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        raise ValueError("Angle requires nonzero segments")
    return math.degrees(math.acos(float(np.clip(a @ b / denom, -1, 1))))


def segment_distance(a, b, c, d):
    """Finite segment minimum, including intersection and degenerate segments.

    A convex quadratic on [0,1]^2 reaches its minimum at its stationary point
    or one of the four boundaries. Test each, without spatial sampling.
    """
    a, b, c, d = [np.asarray(p, float) for p in (a, b, c, d)]
    u, v, w = b - a, d - c, a - c
    aa, bb, cc = float(u @ u), float(u @ v), float(v @ v)
    dd, ee = float(u @ w), float(v @ w)
    pairs = []
    for s in (0.0, 1.0):
        pairs.append((s, float(np.clip((ee + s * bb) / cc, 0, 1)) if cc else 0.0))
    for t in (0.0, 1.0):
        pairs.append((float(np.clip((t * bb - dd) / aa, 0, 1)) if aa else 0.0, t))
    # Cross product avoids catastrophic cancellation for nearly parallel edges.
    det = float(np.cross(u, v) @ np.cross(u, v))
    if det > np.finfo(float).eps * aa * cc:
        s, t = (bb * ee - cc * dd) / det, (aa * ee - bb * dd) / det
        if 0 <= s <= 1 and 0 <= t <= 1:
            pairs.append((s, t))
    candidates = [
        (float(np.linalg.norm(a + s * u - c - t * v)), a + s * u, c + t * v)
        for s, t in pairs
    ]
    return min(candidates, key=lambda p: p[0])


def measure_points(mode, points, units="mm"):
    if units not in UNITS:
        raise ValueError("Unsupported length unit")
    count = {"distance": 2, "angle": 3, "circle": 3}.get(mode)
    if count is None:
        raise ValueError("Choose distance, angle, circle or selection")
    if not isinstance(points, (list, tuple)) or len(points) != count:
        raise ValueError(f"{mode} requires {count} XYZ points")
    rows = []
    for point in points:
        if len(point) != 3:
            raise ValueError("Each point requires X, Y and Z")
        rows.append(
            [
                (
                    to_si(v)
                    if isinstance(v, str)
                    and any(c.isalpha() for c in v.replace("e", "").replace("E", ""))
                    else float(v) * UNITS[units]
                )
                for v in point
            ]
        )
    p = np.asarray(rows, float)
    if not np.isfinite(p).all():
        raise ValueError("Coordinates must be finite")
    k = UNITS[units]

    def L(x):
        return f"{x/k:.9g} {units}"

    out = {
        "kind": mode,
        "units": units,
        "points": p.tolist(),
        "accuracy": "Analytic calculation from the supplied coordinates.",
    }
    if mode == "distance":
        delta = p[1] - p[0]
        out.update(
            distance=float(np.linalg.norm(delta)), delta=delta.tolist(), line=p.tolist()
        )
        out["text"] = (
            "Distance "
            + L(out["distance"])
            + "; ΔX / ΔY / ΔZ: "
            + " / ".join(L(x) for x in delta)
        )
    elif mode == "angle":
        out["angle"] = vector_angle(p[0] - p[1], p[2] - p[1])
        out["text"] = f"Angle ABC (vertex B): {out['angle']:.9g}°"
    else:
        u, v = p[1] - p[0], p[2] - p[0]
        n = np.cross(u, v)
        n2 = float(n @ n)
        if n2 <= 1e-24 * float(u @ u) * float(v @ v) or n2 == 0:
            raise ValueError("Circle requires three distinct, non-collinear points")
        offset = ((u @ u) * np.cross(v, n) + (v @ v) * np.cross(n, u)) / (2 * n2)
        center = p[0] + offset
        radius = float(np.linalg.norm(offset))
        out.update(
            center=center.tolist(),
            radius=radius,
            diameter=2 * radius,
            circumference=2 * math.pi * radius,
            area=math.pi * radius**2,
            line=[center.tolist(), p[0].tolist()],
            distance=radius,
        )
        out["text"] = (
            "Radius "
            + L(radius)
            + "; diameter "
            + L(2 * radius)
            + "; circumference "
            + L(out["circumference"])
        )
    return out


def primitive_properties(shape):
    """Exact volume under affine transforms, plus dimensions when unambiguous.

    No Boolean/imported bounding-box volume is presented as actual volume.
    Radius/diameter are emitted only for similarity transforms (no ellipse).
    """
    from ..geometry import primitives as p

    points = np.vstack([np.zeros(3), np.eye(3)])
    for transform in shape._xform:
        points = p._apply_xform_points(points, transform)
    matrix = (points[1:] - points[0]).T
    determinant = abs(float(np.linalg.det(matrix)))
    scale = float(np.linalg.norm(matrix[:, 0]))
    uniform = np.allclose(
        matrix.T @ matrix,
        np.eye(3) * scale**2,
        rtol=1e-9,
        atol=max(scale**2, 1e-300) * 1e-12,
    )
    result = {}
    volume = None
    if isinstance(shape, p.Box):
        volume = float(np.prod(shape.size))
        edges = matrix * np.asarray(shape.size)[None, :]
        result["area"] = 2 * sum(
            float(np.linalg.norm(np.cross(edges[:, i], edges[:, j])))
            for i, j in [(0, 1), (0, 2), (1, 2)]
        )
    elif isinstance(shape, p.Sphere):
        volume = 4 * np.pi * shape.radius**3 / 3
        if uniform:
            result.update(
                radius=shape.radius * scale,
                diameter=2 * shape.radius * scale,
                area=4 * np.pi * (shape.radius * scale) ** 2,
            )
    elif isinstance(shape, p.Cylinder):
        volume = shape.angle * shape.radius**2 * shape.height / 2
        result["height"] = shape.height * float(np.linalg.norm(matrix @ shape.axis))
        if uniform:
            result.update(
                radius=shape.radius * scale, diameter=2 * shape.radius * scale
            )
    elif isinstance(shape, p.Cone):
        volume = (
            np.pi * shape.height * (shape.r1**2 + shape.r1 * shape.r2 + shape.r2**2) / 3
        )
        result["height"] = shape.height * float(np.linalg.norm(matrix @ shape.axis))
        if uniform:
            result.update(
                baseDiameter=2 * shape.r1 * scale, topDiameter=2 * shape.r2 * scale
            )
    elif isinstance(shape, p.Torus):
        volume = 2 * np.pi**2 * shape.r_major * shape.r_minor**2
        if uniform:
            result.update(
                majorRadius=shape.r_major * scale,
                minorRadius=shape.r_minor * scale,
                outerDiameter=2 * (shape.r_major + shape.r_minor) * scale,
                innerDiameter=2 * (shape.r_major - shape.r_minor) * scale,
            )
    elif isinstance(shape, p.Polygon):
        vertices = np.asarray(shape.points) @ matrix.T
        result["area"] = float(
            np.linalg.norm(
                np.cross(vertices, np.roll(vertices, -1, axis=0)).sum(axis=0)
            )
            / 2
        )
    if volume is not None:
        result["volume"] = float(volume * determinant)
    return result
