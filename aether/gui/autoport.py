"""
Automatic ports from a marked signal and ground.

The user marks the signal conductor(s) and the ground (objects, picked faces or
edges), chooses *Lumped* or *Wave* and a port appears -- no coordinates to type.
What "appears" is what an experienced user would draw by hand:

Lumped port
    A rectangular sheet that bridges the gap between the two conductors, at the
    end of the signal conductor nearest the model boundary (where a line is
    fed), as wide as the signal conductor, with its field running from the
    signal to the ground.

Wave port
    A window in the plane across the signal conductor's end, sized the way HFSS
    recommends: the whole ground cross-section when the ground encloses the
    signal (coax, waveguide), otherwise about ten signal widths wide and eight
    gaps high above the ground, clipped to the model. Its integration line runs
    from the signal to the ground across the gap.

Everything is axis-aligned boxes and planes: the geometry of the structures
these ports are made for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from ..core.constants import c0


@dataclass
class Mark:
    """What a signal or ground selection amounts to geometrically."""
    lo: np.ndarray
    hi: np.ndarray
    pts: np.ndarray                      # sample points on the surface
    face_axis: Optional[int] = None      # planar face: axis of its normal
    face_at: float = 0.0                 # ... and where that plane is
    label: str = ""

    @property
    def span(self) -> np.ndarray:
        return self.hi - self.lo

    @property
    def centre(self) -> np.ndarray:
        return 0.5 * (self.lo + self.hi)


# --------------------------------------------------------------------------
# turning picks into geometry
# --------------------------------------------------------------------------


def _subsample(p: np.ndarray, n: int = 3000) -> np.ndarray:
    return p if len(p) <= n else p[np.linspace(0, len(p) - 1, n).astype(int)]


def marks_from_picks(d, picks: Sequence[dict], role: str) -> Mark:
    """Merge a list of picks (objects, faces, edges) into one :class:`Mark`."""
    from . import api
    if not picks:
        raise ValueError(f"mark the {role} first: select the {role} conductor "
                         "(or a face / edge of it) and choose Mark as "
                         f"{role.capitalize()}")
    los, his, pts, labels = [], [], [], []
    face_axis, face_at = None, 0.0
    for pk in picks:
        kind = pk.get("kind", "object")
        if kind == "object":
            ent = api._entity(d, pk["name"])
            lo, hi = (np.asarray(v, float) for v in ent.shape.bounds())
            arr = api._assign_arrays(ent.shape)
            p = np.vstack([arr[1], arr[0].reshape(-1, 3)]) if arr is not None else np.vstack([lo, hi])
            labels.append(pk["name"])
        elif kind == "face":
            c, n, lo, hi = api._pick_geometry([pk])
            ax = int(np.argmax(np.abs(n)))
            if abs(n[ax]) > 0.99 and len(picks) == 1:
                face_axis, face_at = ax, float(c[ax])
            corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1])
                                for z in (lo[2], hi[2])])
            p = np.vstack([corners, c[None, :]])
            labels.append(f"face of {pk.get('object', '?')}")
        elif kind == "edge":
            a, b = (np.asarray([api.to_si(x) for x in pk[k]], float) for k in ("a", "b"))
            lo, hi = np.minimum(a, b), np.maximum(a, b)
            p = np.linspace(a, b, 9)
            labels.append("edge")
        else:
            raise ValueError(f"cannot use a {kind!r} as a {role}")
        los.append(lo); his.append(hi); pts.append(p)
    return Mark(np.min(los, axis=0), np.max(his, axis=0), _subsample(np.vstack(pts)),
                face_axis, face_at, ", ".join(labels[:3]) + (" …" if len(labels) > 3 else ""))


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------


def gap_axis(S: Mark, G: Mark, tiny: float = 1e-12) -> Optional[Tuple[int, float]]:
    """The axis along which the two are separated, and by how much."""
    best = None
    for k in range(3):
        sep = max(G.lo[k] - S.hi[k], S.lo[k] - G.hi[k])
        if sep > tiny and (best is None or sep > best[1]):
            best = (k, float(sep))
    return best


def taken_planes(d) -> List[Tuple[int, float]]:
    """(axis, coordinate) of the planes that already carry a port, so a second
    port on the same line goes to the other end."""
    out: List[Tuple[int, float]] = []
    for p in d.ports:
        sel = getattr(p, "selector", None)
        if getattr(sel, "_ax", None) is not None and hasattr(sel, "value"):
            out.append((int(sel._ax), float(sel.value)))
        line = getattr(p, "integration_line", None)
        if line:
            a, b = np.asarray(line[0], float), np.asarray(line[1], float)
            for k in range(3):
                if abs(a[k] - b[k]) < 1e-12:
                    out.append((k, float(a[k])))
    return out


def _near_boundary_end(S: Mark, D_lo, D_hi, axis: int, taken=(), end: str = "") -> float:
    """The end of the signal along *axis* that lies closer to the model's outside
    (where a transmission line is fed from) and does not carry a port yet.
    ``end`` = ``min`` / ``max`` forces one."""
    if end in ("min", "max"):
        return float(S.lo[axis] if end == "min" else S.hi[axis])
    d_lo = S.lo[axis] - D_lo[axis]
    d_hi = D_hi[axis] - S.hi[axis]
    ends = [float(S.lo[axis]), float(S.hi[axis])]
    if d_hi < d_lo:
        ends.reverse()
    tol = 1e-7
    for e in ends:
        if not any(a == axis and abs(v - e) < tol for a, v in taken):
            return e
    return ends[0]


def _longitudinal_axis(S: Mark, exclude: Sequence[int]) -> int:
    if S.face_axis is not None and S.face_axis not in exclude:
        return S.face_axis
    cand = [k for k in range(3) if k not in exclude]
    return max(cand, key=lambda k: S.span[k])


def _unit(k: int, sign: float) -> np.ndarray:
    u = np.zeros(3)
    u[k] = sign
    return u


# --------------------------------------------------------------------------
# lumped
# --------------------------------------------------------------------------


def plan_lumped(S: Mark, G: Mark, D_lo, D_hi, taken=(), end: str = "") -> dict:
    gap = gap_axis(S, G)
    if gap is None:
        raise ValueError(
            "the signal and the ground overlap or touch, so there is no gap for "
            "a lumped port to bridge. Leave a gap between them (the port fills "
            "it), or use a wave port.")
    k, sep = gap
    above = S.lo[k] >= G.hi[k]                    # signal on the +k side of the ground
    s_u = float(S.lo[k] if above else S.hi[k])    # signal's face toward the ground
    g_u = float(G.hi[k] if above else G.lo[k])    # ground's face toward the signal
    a_l = _longitudinal_axis(S, exclude=[k])
    a_w = next(i for i in range(3) if i not in (k, a_l))
    e = S.face_at if S.face_axis == a_l else _near_boundary_end(S, D_lo, D_hi, a_l, taken, end)
    width = float(min(S.span[a_w], G.span[a_w]))
    if width <= 1e-12:
        # a line-like signal has no width: use the gap so the sheet is not a sliver
        width = max(sep, 1e-6)
    c_w = float(S.centre[a_w])
    # keep the sheet over the ground
    c_w = float(np.clip(c_w, G.lo[a_w] + width / 2, max(G.hi[a_w] - width / 2, G.lo[a_w] + width / 2)))
    pts = []
    for w, uu in ((c_w - width / 2, s_u), (c_w + width / 2, s_u),
                  (c_w + width / 2, g_u), (c_w - width / 2, g_u)):
        q = np.zeros(3)
        q[a_l], q[a_w], q[k] = e, w, uu
        pts.append(q)
    s_pt = np.zeros(3); g_pt = np.zeros(3)
    s_pt[a_l] = g_pt[a_l] = e
    s_pt[a_w] = g_pt[a_w] = c_w
    s_pt[k], g_pt[k] = s_u, g_u
    return {"corners": pts, "signal": s_pt, "ground": g_pt, "direction": _unit(k, -1.0 if above else 1.0),
            "gap": sep, "width": width, "axis": k, "plane_axis": a_l, "plane_at": e}


# --------------------------------------------------------------------------
# wave
# --------------------------------------------------------------------------


def plan_wave(S: Mark, G: Mark, D_lo, D_hi, taken=(), end: str = "") -> dict:
    gap = gap_axis(S, G)
    # the plane the port sits in: across the line, at the end nearest the boundary
    if S.face_axis is not None:
        a_p, e = S.face_axis, S.face_at
    elif G.face_axis is not None:
        a_p, e = G.face_axis, G.face_at
    else:
        excl = [gap[0]] if gap else []
        a_p = _longitudinal_axis(S, exclude=excl)
        e = _near_boundary_end(S, D_lo, D_hi, a_p, taken, end)
    t = [i for i in range(3) if i != a_p]
    enclosed = all(G.lo[i] < S.lo[i] - 1e-12 and G.hi[i] > S.hi[i] + 1e-12 for i in t)
    if enclosed:
        win = {i: (float(G.lo[i]), float(G.hi[i])) for i in t}
        g_ax = t[0]
        sep = float(min(S.lo[i] - G.lo[i] for i in t))
        note = "the ground encloses the signal: the port covers the whole cross-section"
    else:
        if gap is not None and gap[0] in t:
            g_ax, sep = gap
        else:                                      # side by side along the plane: use the larger offset
            g_ax = max(t, key=lambda i: abs(S.centre[i] - G.centre[i]))
            sep = float(max(abs(S.centre[g_ax] - G.centre[g_ax]) - 0.5 * (S.span[g_ax] + G.span[g_ax]), 1e-6))
        w_ax = next(i for i in t if i != g_ax)
        up = S.centre[g_ax] >= G.centre[g_ax]      # signal on the +g side of the ground
        h = max(sep, 1e-6)
        wid = max(float(S.span[w_ax]), 1e-6)
        total_w = max(10.0 * wid, 6.0 * h)
        c_w = float(S.centre[w_ax])
        if up:
            g0, g1 = float(G.lo[g_ax]), float(S.hi[g_ax] + 8.0 * h)
        else:
            g0, g1 = float(S.lo[g_ax] - 8.0 * h), float(G.hi[g_ax])
        win = {g_ax: (g0, g1), w_ax: (c_w - total_w / 2, c_w + total_w / 2)}
        note = (f"open line: window {total_w * 1e3:.3g} mm wide (10 signal widths) and "
                f"{(g1 - g0) * 1e3:.3g} mm high (ground + 8 gaps)")
    for i in t:                                    # never outside the model
        win[i] = (max(win[i][0], float(D_lo[i])), min(win[i][1], float(D_hi[i])))
        if win[i][1] <= win[i][0]:
            raise ValueError("the port window falls outside the model; extend the "
                             "air region around the line")
    # the integration line: the closest signal and ground points in that plane
    tol = max(1e-9, 1e-3 * float(np.linalg.norm(D_hi - D_lo)))
    sp = S.pts[np.abs(S.pts[:, a_p] - e) <= tol]
    gp = G.pts[np.abs(G.pts[:, a_p] - e) <= tol]
    if len(sp) and len(gp):
        dd = np.linalg.norm(sp[:, None, :] - gp[None, :, :], axis=2) if len(sp) * len(gp) < 4e6 else None
        if dd is not None:
            i, j = np.unravel_index(int(np.argmin(dd)), dd.shape)
            s_pt, g_pt = sp[i].copy(), gp[j].copy()
        else:
            s_pt, g_pt = sp[0].copy(), gp[0].copy()
    else:
        s_pt = S.centre.copy(); g_pt = G.centre.copy()
        if gap is not None:
            k, _ = gap
            above = S.lo[k] >= G.hi[k]
            s_pt[k] = S.lo[k] if above else S.hi[k]
            g_pt[k] = G.hi[k] if above else G.lo[k]
            g_pt[[i for i in range(3) if i != k]] = s_pt[[i for i in range(3) if i != k]]
    if gap is not None and gap[0] in t:
        # snap the line to the conductor faces that look at each other
        k = gap[0]
        above = S.lo[k] >= G.hi[k]
        s_pt[k] = S.lo[k] if above else S.hi[k]
        g_pt[k] = G.hi[k] if above else G.lo[k]
        for i in t:
            if i != k:
                g_pt[i] = s_pt[i]
    s_pt[a_p] = g_pt[a_p] = e
    on_boundary = bool(abs(e - D_lo[a_p]) <= tol or abs(e - D_hi[a_p]) <= tol)
    return {"axis": a_p, "at": float(e), "window": [list(win[i]) for i in t], "signal": s_pt, "ground": g_pt,
            "enclosed": bool(enclosed), "note": note, "on_boundary": on_boundary}


def choose_kind(S: Mark, G: Mark, D_lo, D_hi) -> str:
    """Wave when the line runs out to the model boundary (its end is a port
    plane), lumped when the two conductors sit inside the model."""
    tol = max(1e-9, 1e-3 * float(np.linalg.norm(D_hi - D_lo)))
    for m in (S, G):
        if m.face_axis is not None and (abs(m.face_at - D_lo[m.face_axis]) <= tol
                                        or abs(m.face_at - D_hi[m.face_axis]) <= tol):
            return "wave"
    both = all(any(abs(mm.lo[k] - D_lo[k]) <= tol or abs(mm.hi[k] - D_hi[k]) <= tol for k in range(3))
               for mm in (S, G))
    return "wave" if both else "lumped"


def wavelength_hint(d) -> Optional[float]:
    try:
        f = d.setups[0].frequency
        return c0 / float(f)
    except Exception:                                          # noqa: BLE001
        return None
