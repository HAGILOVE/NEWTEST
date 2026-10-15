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

    def slab(self, axis: int, at: float, tol: float) -> np.ndarray:
        """The vertices within *tol* of the plane ``axis = at`` (the conductor's
        outline where that plane cuts or ends it)."""
        d = np.abs(self.pts[:, axis] - at)
        sel = self.pts[d <= tol]
        if len(sel):
            return sel
        return self.pts[np.argsort(d)[:8]]

    @property
    def centre(self) -> np.ndarray:
        return 0.5 * (self.lo + self.hi)


# --------------------------------------------------------------------------
# turning picks into geometry
# --------------------------------------------------------------------------


def _subsample(p: np.ndarray, n: int = 200000) -> np.ndarray:
    """Unique vertices (corners matter: they are where a line ends)."""
    if len(p) > 1:
        p = np.unique(np.round(p, 10), axis=0)
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
        kind = pk.get("kind") or ("face" if "point" in pk else "object")
        if kind == "object":
            ent = api._entity(d, pk["name"])
            lo, hi = (np.asarray(v, float) for v in ent.shape.bounds())
            arr = api._assign_arrays(ent.shape)
            p = arr[0].reshape(-1, 3) if arr is not None else np.vstack([lo, hi])
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


def gap_axis(S: Mark, G: Mark, tiny: float = 1e-9) -> Optional[Tuple[int, float]]:
    """The axis along which the two are separated by their bounding boxes, and
    by how much (the *closest* such axis: that is the gap a port bridges)."""
    best = None
    for k in range(3):
        sep = max(G.lo[k] - S.hi[k], S.lo[k] - G.hi[k])
        if sep > tiny and (best is None or sep < best[1]):
            best = (k, float(sep))
    return best


@dataclass
class Gap:
    axis: int              # the direction the port field runs along
    sep: float             # size of the gap
    s_u: float             # where the signal's face toward the ground is
    g_u: float             # where the ground's face toward the signal is
    above: bool            # signal on the +axis side of the ground


def find_gap(S: Mark, G: Mark) -> Optional[Gap]:
    """
    The gap between signal and ground.

    Conductors that sit one above the other (microstrip, patch, parallel
    plates, dipole arms) are separated by their bounding boxes. Conductors that
    are nested -- a coplanar signal inside a ground with a slot, a pin through
    a hole -- have no such separation, so the closest pair of points decides.
    """
    g = gap_axis(S, G)
    if g is not None:
        k, sep = g
        above = bool(S.lo[k] >= G.hi[k])
        return Gap(k, sep, float(S.lo[k] if above else S.hi[k]),
                   float(G.hi[k] if above else G.lo[k]), above)
    from scipy.spatial import cKDTree
    a = S.pts if len(S.pts) <= 8000 else S.pts[np.linspace(0, len(S.pts) - 1, 8000).astype(int)]
    b = G.pts if len(G.pts) <= 8000 else G.pts[np.linspace(0, len(G.pts) - 1, 8000).astype(int)]
    d, idx = cKDTree(b).query(a)
    n = int(np.argmin(d))
    if d[n] <= 1e-9:
        return None                                    # they touch
    sp, gp = a[n], b[idx[n]]
    v = gp - sp
    k = int(np.argmax(np.abs(v)))
    return Gap(k, float(abs(v[k])), float(sp[k]), float(gp[k]), bool(sp[k] > gp[k]))


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


@dataclass
class Feed:
    axis: int              # the line runs along this axis ...
    at: float              # ... and the port plane is here
    internal: bool         # True: no end near the model boundary; centre of the footprint
    centre: float          # middle of the conductor along the axis
    note: str = ""


def feed_end(S: Mark, D_lo, D_hi, exclude: Sequence[int], taken=(), end: str = "") -> Feed:
    """
    Where the signal is fed from: the end of the conductor (outside the gap
    axis) that lies closest to the model's boundary -- the end of a line
    that runs out of the model. A conductor with no end near the boundary
    (a dipole arm in the middle of an air box) is fed at the centre of its
    footprint instead.

    The line direction is *not* taken as the longest side of the bounding
    box: with a patch and its feed in one object that is the wrong axis.
    """
    tol = 1e-7
    span_d = np.maximum(np.asarray(D_hi, float) - np.asarray(D_lo, float), 1e-12)
    cands = []
    for a in range(3):
        if a in exclude:
            continue
        for side, val, dist in (("min", float(S.lo[a]), float(S.lo[a] - D_lo[a])),
                                ("max", float(S.hi[a]), float(D_hi[a] - S.hi[a]))):
            used = any(ax == a and abs(v - val) < tol for ax, v in taken)
            cands.append((dist / span_d[a], a, side, val, used))
    if end in ("min", "max"):
        pool = [c for c in cands if c[2] == end] or cands      # the forced side
    else:
        pool = [c for c in cands if not c[4]] or cands         # a free end first
    frac, a, side, val, used = min(pool, key=lambda c: c[0])
    centre = float(0.5 * (S.lo[a] + S.hi[a]))
    if frac > 0.3 and not end:
        # No end near the boundary (a dipole arm in the middle of the air box):
        # feed through the middle, cutting across the narrower side so that
        # the sheet is as wide as the conductor.
        free = [i for i in range(3) if i not in exclude]
        a = min(free, key=lambda i: S.span[i])
        centre = float(0.5 * (S.lo[a] + S.hi[a]))
        return Feed(a, centre, True, centre,
                    "middle of the conductor (it does not reach the model boundary)")
    return Feed(a, val, False, centre,
                f"{'lower' if side == 'min' else 'upper'} end, {frac * 100:.1f} % of the model from its boundary")


def local_width(S: Mark, axis: int, at: float, across: int, D_lo, D_hi,
                internal: bool = False) -> Tuple[float, float]:
    """
    Width and centre of the conductor across *axis* where the plane
    ``axis = at`` cuts it (or ends it): the corners of its end face, so a
    feed line on a patch is as wide as the *line*, not the patch.
    """
    diag = float(np.linalg.norm(np.asarray(D_hi, float) - np.asarray(D_lo, float))) or 1.0
    tol = min(max(1e-9, 1e-3 * diag), max(0.02 * float(S.span[axis]), 1e-9))
    if internal:
        # inside the conductor: its footprint
        return float(S.span[across]), float(0.5 * (S.lo[across] + S.hi[across]))
    pts = S.slab(axis, at, tol)
    lo, hi = float(pts[:, across].min()), float(pts[:, across].max())
    return hi - lo, 0.5 * (lo + hi)


def _unit(k: int, sign: float) -> np.ndarray:
    u = np.zeros(3)
    u[k] = sign
    return u


# --------------------------------------------------------------------------
# lumped
# --------------------------------------------------------------------------


def plan_lumped(S: Mark, G: Mark, D_lo, D_hi, taken=(), end: str = "") -> dict:
    gp = find_gap(S, G)
    if gp is None:
        raise ValueError(
            "the signal and the ground touch, so there is no gap for a lumped "
            "port to bridge. Leave a gap between them (the port fills it), or "
            "use a wave port.")
    k, sep, s_u, g_u, above = gp.axis, gp.sep, gp.s_u, gp.g_u, gp.above
    if S.face_axis is not None and S.face_axis != k:
        a_l, e, internal, note = S.face_axis, S.face_at, False, "the picked face"
        a_w = next(i for i in range(3) if i not in (k, a_l))
    else:
        f = feed_end(S, D_lo, D_hi, exclude=[k], taken=taken, end=end)
        a_l, e, internal, note = f.axis, f.at, f.internal, f.note
        a_w = next(i for i in range(3) if i not in (k, a_l))
    width, c_w = local_width(S, a_l, e, a_w, D_lo, D_hi, internal)
    # no wider than the ground it lands on
    g_lo, g_hi = float(G.lo[a_w]), float(G.hi[a_w])
    lo_w, hi_w = max(c_w - width / 2, g_lo), min(c_w + width / 2, g_hi)
    if hi_w - lo_w > 1e-12:
        width, c_w = hi_w - lo_w, 0.5 * (hi_w + lo_w)
    if width <= 1e-12:
        # a line-like signal has no width: use the gap so the sheet is not a sliver
        width = max(sep, 1e-6)
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
            "gap": sep, "width": width, "axis": k, "plane_axis": a_l, "plane_at": e,
            "across": a_w, "centre_across": c_w, "note": note,
            "ground_covers": bool(G.lo[a_l] - 1e-9 <= e <= G.hi[a_l] + 1e-9)}


# --------------------------------------------------------------------------
# wave
# --------------------------------------------------------------------------


def plan_wave(S: Mark, G: Mark, D_lo, D_hi, taken=(), end: str = "") -> dict:
    gp = find_gap(S, G)
    gap = (gp.axis, gp.sep) if gp is not None else None
    # the plane the port sits in: across the line, at the end nearest the boundary
    local_c = None
    if S.face_axis is not None:
        a_p, e, internal = S.face_axis, S.face_at, False
    elif G.face_axis is not None:
        a_p, e, internal = G.face_axis, G.face_at, False
    else:
        excl = [gap[0]] if gap else []
        f = feed_end(S, D_lo, D_hi, exclude=excl, taken=taken, end=end)
        a_p, e, internal = f.axis, f.at, f.internal
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
        wid, c_w = local_width(S, a_p, e, w_ax, D_lo, D_hi, internal)
        wid = max(float(wid), 1e-6)
        total_w = max(10.0 * wid, 6.0 * h)
        if up:
            g0, g1 = float(G.lo[g_ax]), float(S.hi[g_ax] + 8.0 * h)
        else:
            g0, g1 = float(S.lo[g_ax] - 8.0 * h), float(G.hi[g_ax])
        win = {g_ax: (g0, g1), w_ax: (c_w - total_w / 2, c_w + total_w / 2)}
        note = (f"open line, signal {wid * 1e3:.3g} mm wide at the port: window {total_w * 1e3:.3g} mm wide "
                f"(10 signal widths) and {(g1 - g0) * 1e3:.3g} mm high (ground + 8 gaps)")
    for i in t:                                    # never outside the model
        win[i] = (max(win[i][0], float(D_lo[i])), min(win[i][1], float(D_hi[i])))
        if win[i][1] <= win[i][0]:
            raise ValueError("the port window falls outside the model; extend the "
                             "air region around the line")
    # the integration line: the closest signal and ground points in that plane
    tol = max(1e-9, 1e-3 * float(np.linalg.norm(np.asarray(D_hi, float) - np.asarray(D_lo, float))))
    sp = S.pts[np.abs(S.pts[:, a_p] - e) <= tol]
    gpts = G.pts[np.abs(G.pts[:, a_p] - e) <= tol]
    if len(sp) and len(gpts):
        dd = np.linalg.norm(sp[:, None, :] - gpts[None, :, :], axis=2) if len(sp) * len(gpts) < 4e6 else None
        if dd is not None:
            i, j = np.unravel_index(int(np.argmin(dd)), dd.shape)
            s_pt, g_pt = sp[i].copy(), gpts[j].copy()
        else:
            s_pt, g_pt = sp[0].copy(), gpts[0].copy()
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
        s_pt[k], g_pt[k] = gp.s_u, gp.g_u
        # ... at the middle of the signal where the plane cuts it
        for i in t:
            if i != k:
                if not enclosed:
                    s_pt[i] = c_w if i == w_ax else s_pt[i]
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
