"""
Field plots: what an engineer looks at after a solve.

*  ``E`` and ``H`` magnitude on the model surface or on a cut plane,
*  the **surface current** ``J_s = n x H`` on every conductor,
*  the field at an arbitrary instant of the RF cycle (``Re(V e^{j phase})``),
   so a current can be seen to flow and a standing wave to stand,
*  arrow glyphs showing direction.

Everything returns plain numpy arrays; :mod:`aether.gui.api` turns them into a
viewport buffer.  Values are evaluated *inside the element that owns each
point* (no cell search), then averaged at shared vertices so a surface plot is
smooth rather than faceted.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

QUANTITIES = ("E", "H", "J")
CONDUCTING = ("pec", "finite_cond", "impedance", "symmetry_e")


@dataclass
class FieldPatch:
    """A drawable piece of surface: triangles, a value at every vertex, arrows."""
    verts: np.ndarray                 # (N, 3)
    tris: np.ndarray                  # (K, 3) indices into verts
    values: np.ndarray                # (N,) the plotted scalar (physical units)
    label: str
    unit: str
    arrows: np.ndarray = field(default_factory=lambda: np.zeros((0, 6)))
    peak: float = 0.0                 # peak of the *magnitude* (phase-independent)
    signed: bool = False              # a component: values run -peak .. +peak


# --------------------------------------------------------------------------


COMPONENTS = ("mag", "x", "y", "z")


def _scalar(V: np.ndarray, phase_deg: Optional[float],
            comp: str = "mag") -> np.ndarray:
    """Plotted scalar of complex vectors (n,3): peak magnitude, or the
    instantaneous magnitude at *phase_deg* of the RF cycle; for a Cartesian
    *comp* the **signed** instantaneous component ``Re(V_c e^{j phase})``,
    which is what shows a wave travelling or a charge sloshing."""
    if comp in ("x", "y", "z"):
        ph = np.exp(1j * math.radians(phase_deg or 0.0))
        return (V[:, "xyz".index(comp)] * ph).real
    if phase_deg is None:
        return np.sqrt(np.sum(np.abs(V) ** 2, axis=1))
    ph = np.exp(1j * math.radians(phase_deg))
    return np.linalg.norm((V * ph).real, axis=1)


def _direction(V: np.ndarray, phase_deg: Optional[float]) -> np.ndarray:
    ph = np.exp(1j * math.radians(phase_deg or 0.0))
    R = (V * ph).real
    n = np.linalg.norm(R, axis=1, keepdims=True)
    return R / np.maximum(n, 1e-300)


def conductor_faces(design, mesh) -> np.ndarray:
    """Indices into ``mesh.surf_tris`` of every conducting surface."""
    n = len(mesh.surf_tris)
    mask = np.zeros(n, bool)
    cond = getattr(mesh, "surf_is_conductor", None)
    if cond is not None and len(cond) == n:
        mask |= cond                                    # surface of a PEC body
    for b in design.boundaries:
        if b.btype in CONDUCTING:
            idx = np.asarray(mesh.bc_faces.get(b.name, []), np.int64)
            mask[idx] = True
    # unassigned outer faces default to perfect conductors
    owner = getattr(mesh, "bc_owner", None)
    if owner is not None and len(owner) == n:
        outer = np.zeros(n, bool)
        outer[:getattr(mesh, "n_outer_faces", n)] = True
        free = (owner < 0) & outer
        for idx in mesh.port_faces.values():
            free[np.asarray(idx, np.int64)] = False
        if getattr(design, "default_boundary", "pec") == "pec":
            mask |= free
    for idx in mesh.port_faces.values():
        mask[np.asarray(idx, np.int64)] = False
    return np.nonzero(mask)[0]


def _face_arrays(mesh, faces):
    tris = mesh.surf_tris[faces]
    p = mesh.nodes[tris]
    cen = p.mean(axis=1)
    nrm = mesh.surf_normals[faces]
    owner = mesh.surf_owner_tet[faces]
    return tris, cen, nrm, owner


def _quantity_at(fs, quantity: str, owner, pts, nrm):
    """Complex vectors (n,3) of E, H or the surface current at *pts*."""
    E, H = fs.eval_at(owner, pts)
    if quantity == "E":
        return E
    if quantity == "H":
        return H
    # J_s = n_c x H with n_c pointing from the conductor into the domain, which
    # is the opposite of the mesh's outward (domain -> outside) normal
    return np.cross(-nrm, H)


def surface_patch(solution, fs, quantity: str = "E", faces=None,
                  phase_deg: Optional[float] = None, arrows: int = 0,
                  comp: str = "mag") -> FieldPatch:
    """
    The field on mesh surface triangles *faces* (default: every boundary face,
    or every conductor for the surface current).
    """
    mesh, design = solution.mesh, solution.design
    if faces is None:
        faces = (conductor_faces(design, mesh) if quantity == "J"
                 else np.arange(getattr(mesh, "n_outer_faces",
                                        len(mesh.surf_tris))))
    faces = np.asarray(faces, np.int64)
    if len(faces) == 0:
        raise ValueError("no surface to plot: "
                         + ("the model has no conducting surface"
                            if quantity == "J" else "nothing is selected"))
    tris, cen, nrm, owner = _face_arrays(mesh, faces)
    # evaluate at each triangle's three corners, each inside the owner element
    corner = mesh.nodes[tris]                              # (K,3,3)
    own3 = np.repeat(owner, 3)
    nrm3 = np.repeat(nrm, 3, axis=0)
    V = _quantity_at(fs, quantity, own3, corner.reshape(-1, 3), nrm3)
    val = _scalar(V, phase_deg, comp).reshape(-1, 3)
    # vertex-average over every selected triangle that touches the vertex
    used, inv = np.unique(tris.reshape(-1), return_inverse=True)
    acc = np.zeros(len(used))
    cnt = np.zeros(len(used))
    np.add.at(acc, inv, val.reshape(-1))
    np.add.at(cnt, inv, 1.0)
    vv = acc / np.maximum(cnt, 1.0)
    local = inv.reshape(-1, 3)
    patch = FieldPatch(mesh.nodes[used], local, vv,
                       *_labels(quantity, phase_deg, comp))
    patch.signed = comp in ("x", "y", "z")
    patch.peak = (float(np.abs(V[:, "xyz".index(comp)]).max()) if patch.signed
                  else float(_scalar(V, None).max()))
    if arrows:
        pick = np.linspace(0, len(faces) - 1, min(arrows, len(faces))).astype(int)
        Vc = _quantity_at(fs, quantity, owner[pick], cen[pick], nrm[pick])
        patch.arrows = _glyphs(cen[pick], Vc, phase_deg, nrm[pick], solution,
                               _scalar(Vc, None), patch.peak)
    return patch


def _cut_geometry(mesh, ax: int, value: float):
    """Triangles where the plane ``x[ax] = value`` slices the tetrahedra.

    Returns ``(V, tris, own)``: corner coordinates (3K per K triangles, not
    welded), the (K,3) indices into ``V`` and the owner tetrahedron of each
    triangle."""
    nodes, tets = mesh.nodes, mesh.tets
    d = nodes[tets, ax] - value                             # (M,4)
    pos = d > 0
    npos = pos.sum(axis=1)
    cross = (npos > 0) & (npos < 4) & ~((d == 0).all(axis=1))
    # treat exact-zero as "not positive" consistently
    ids = np.nonzero(cross)[0]
    if len(ids) == 0:
        raise ValueError("the plane does not cut the model; move it inside "
                         f"{nodes[:, ax].min():.4g} .. {nodes[:, ax].max():.4g} m")
    verts: List[np.ndarray] = []
    tri_list: List[np.ndarray] = []
    owner_list: List[np.ndarray] = []
    count = 0

    def cut_point(t, a, b):
        pa, pb = nodes[tets[t, a]], nodes[tets[t, b]]
        da, db = d[t, a], d[t, b]
        s = da / (da - db)
        return pa + s[:, None] * (pb - pa)

    # one positive (or one negative) vertex -> a triangle; two and two -> a quad
    for n_isolated in (1, 3):
        sel = ids[npos[ids] == n_isolated]
        if len(sel) == 0:
            continue
        flag = pos[sel] if n_isolated == 1 else ~pos[sel]
        iso = np.argmax(flag, axis=1)                        # the lone vertex
        others = np.array([[j for j in range(4) if j != i] for i in range(4)])[iso]
        P = [cut_point(sel, iso, others[:, k]) for k in range(3)]
        base = count
        verts.extend(P)
        n = len(sel)
        idx = np.arange(n)
        tri_list.append(np.stack([base + idx, base + n + idx, base + 2 * n + idx], 1))
        owner_list.append(sel)
        count += 3 * n
    sel = ids[npos[ids] == 2]
    if len(sel):
        order = np.argsort(~pos[sel], axis=1, kind="stable")  # positives first
        a, b, c, e = (order[:, 0], order[:, 1], order[:, 2], order[:, 3])
        P = [cut_point(sel, a, c), cut_point(sel, a, e),
             cut_point(sel, b, e), cut_point(sel, b, c)]
        n = len(sel)
        idx = np.arange(n)
        base = count
        verts.extend(P)
        tri_list.append(np.stack([base + idx, base + n + idx, base + 2 * n + idx], 1))
        tri_list.append(np.stack([base + idx, base + 2 * n + idx, base + 3 * n + idx], 1))
        owner_list.extend([sel, sel])
        count += 4 * n
    V = np.vstack(verts)
    tris = np.vstack(tri_list)
    own = np.concatenate(owner_list)
    return V, tris, own


def cut_plane_patch(solution, fs, axis: str, value: float,
                    quantity: str = "E", phase_deg: Optional[float] = None,
                    arrows: int = 0, comp: str = "mag") -> FieldPatch:
    """The field on the plane ``axis = value`` through the volume mesh."""
    if quantity == "J":
        raise ValueError("the surface current lives on conductors, not on a "
                         "cut plane; plot it on the surface instead")
    mesh = solution.mesh
    ax = "xyz".index(axis.lower())
    V, tris, own = _cut_geometry(mesh, ax, value)
    # the value at each triangle corner, evaluated in the element it came from
    Vc, Hc = fs.eval_at(np.repeat(own, 3), V[tris.reshape(-1)])
    F = Vc if quantity == "E" else Hc
    val = _scalar(F, phase_deg, comp)
    patch = FieldPatch(V[tris.reshape(-1)],
                       np.arange(3 * len(tris)).reshape(-1, 3), val,
                       *_labels(quantity, phase_deg, comp))
    patch.signed = comp in ("x", "y", "z")
    patch.peak = (float(np.abs(F[:, "xyz".index(comp)]).max()) if patch.signed
                  else float(_scalar(F, None).max()))
    if arrows:
        cen = V[tris].mean(axis=1)
        pick = np.linspace(0, len(tris) - 1, min(arrows, len(tris))).astype(int)
        Ec, Hh = fs.eval_at(own[pick] if len(own) == len(tris) else
                            np.take(own, pick % len(own)), cen[pick])
        Fv = Ec if quantity == "E" else Hh
        nrm = np.zeros((len(pick), 3))
        nrm[:, ax] = 1.0
        patch.arrows = _glyphs(cen[pick], Fv, phase_deg, nrm, solution,
                               _scalar(Fv, None), patch.peak)
    return patch


def surface_vectors(solution, fs, quantity: str = "E", faces=None,
                    return_faces: bool = False):
    """The complex vector field on boundary / conductor triangles.

    Returns ``(verts, tris, F)``: the vertices used (M,3), local triangle
    indices (K,3) and the complex vector at each vertex (M,3), averaged over
    every selected triangle touching it. A viewer that holds ``F`` can draw any
    phase or Cartesian component itself, without asking the solver again."""
    mesh, design = solution.mesh, solution.design
    if faces is None:
        faces = (conductor_faces(design, mesh) if quantity == "J"
                 else np.arange(getattr(mesh, "n_outer_faces",
                                        len(mesh.surf_tris))))
    faces = np.asarray(faces, np.int64)
    if len(faces) == 0:
        raise ValueError("no surface to plot")
    tris, _, nrm, owner = _face_arrays(mesh, faces)
    corner = mesh.nodes[tris]
    V = _quantity_at(fs, quantity, np.repeat(owner, 3),
                     corner.reshape(-1, 3), np.repeat(nrm, 3, axis=0))
    used, inv = np.unique(tris.reshape(-1), return_inverse=True)
    cnt = np.bincount(inv, minlength=len(used)).astype(float)
    F = np.zeros((len(used), 3), complex)
    for k in range(3):
        F[:, k] = (np.bincount(inv, V[:, k].real, len(used))
                   + 1j * np.bincount(inv, V[:, k].imag, len(used)))
    F /= np.maximum(cnt, 1.0)[:, None]
    if return_faces:
        return mesh.nodes[used], inv.reshape(-1, 3), F, faces
    return mesh.nodes[used], inv.reshape(-1, 3), F


def cut_vectors(solution, fs, axis: str, value: float, quantity: str = "E",
                weld: float = 1e-9):
    """Complex E or H on the plane ``axis = value``, with shared vertices.

    Corners of neighbouring tetrahedra land on the same point; welding them
    makes the data several times smaller and lets a viewer shade smoothly."""
    if quantity == "J":
        raise ValueError("the surface current lives on conductors, not on a "
                         "cut plane")
    mesh = solution.mesh
    ax = "xyz".index(axis.lower())
    V, tris, own = _cut_geometry(mesh, ax, value)
    corner = V[tris.reshape(-1)]
    E, H = fs.eval_at(np.repeat(own, 3), corner)
    F = E if quantity == "E" else H
    lo, hi = mesh.bounding_box()
    q = max(float(np.linalg.norm(np.asarray(hi) - np.asarray(lo))) * weld, 1e-300)
    key = np.round(corner / q).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True,
                              return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    cnt = np.bincount(inv, minlength=len(first)).astype(float)
    G = np.zeros((len(first), 3), complex)
    for k in range(3):
        G[:, k] = (np.bincount(inv, F[:, k].real, len(first))
                   + 1j * np.bincount(inv, F[:, k].imag, len(first)))
    G /= cnt[:, None]
    return corner[first], inv.reshape(-1, 3), G


def _labels(quantity: str, phase_deg, comp: str = "mag") -> Tuple[str, str]:
    name = {"E": "|E|", "H": "|H|", "J": "|Js|"}[quantity]
    if comp in ("x", "y", "z"):
        name = {"E": "E", "H": "H", "J": "Js"}[quantity] + comp
    unit = {"E": "V/m", "H": "A/m", "J": "A/m"}[quantity]
    if phase_deg is not None:
        name = f"{name} @ {phase_deg:.0f}°"
    return name, unit


def _glyphs(points, V, phase_deg, normals, solution, mags, peak) -> np.ndarray:
    """Arrow segments ``[x0,y0,z0,x1,y1,z1]``: a shaft and two barbs each."""
    lo, hi = solution.mesh.bounding_box()
    diag = float(np.linalg.norm(hi - lo))
    L = (0.045 * diag) * (0.25 + 0.75 * mags / max(peak, 1e-300))
    d = _direction(V, phase_deg)
    tip = points + d * L[:, None]
    side = np.cross(normals, d)
    ns = np.linalg.norm(side, axis=1, keepdims=True)
    fallback = np.cross(d, np.array([0.0, 0.0, 1.0]))
    side = np.where(ns > 1e-9, side / np.maximum(ns, 1e-300),
                    fallback / np.maximum(np.linalg.norm(fallback, axis=1,
                                                         keepdims=True), 1e-300))
    back = tip - 0.3 * L[:, None] * d
    barb = 0.14 * L[:, None] * side
    shaft = np.hstack([points, tip])
    b1 = np.hstack([tip, back + barb])
    b2 = np.hstack([tip, back - barb])
    return np.vstack([shaft, b1, b2])


def to_unit_scale(values: np.ndarray, scale: str = "linear",
                  floor_db: float = 40.0, ref: Optional[float] = None,
                  signed: bool = False
                  ) -> Tuple[np.ndarray, Tuple[float, float]]:
    """Map plotted values onto 0..1 for the colour map; returns the range in
    the plotted unit (dB relative to the peak when ``scale == 'db'``).  A signed
    component maps ``-ref .. +ref`` onto 0..1 so zero sits mid-scale."""
    ref = float(np.abs(values).max()) if ref is None else ref
    ref = max(ref, 1e-300)
    if signed:
        return np.clip(0.5 + 0.5 * values / ref, 0.0, 1.0), (-ref, ref)
    if scale == "db":
        db = 20.0 * np.log10(np.maximum(values, 1e-300) / ref)
        lo, hi = -float(floor_db), 0.0
        return np.clip((db - lo) / (hi - lo), 0.0, 1.0), (lo, hi)
    lo = 0.0
    return np.clip(values / ref, 0.0, 1.0), (lo, ref)


__all__ = ["COMPONENTS", "FieldPatch", "surface_patch", "cut_plane_patch", "conductor_faces",
           "surface_vectors", "cut_vectors",
           "to_unit_scale", "QUANTITIES"]


def locate_points(mesh, pts, candidates: int = 24):
    """
    The tetrahedron that contains each point, and whether it was found inside.

    The nearest element centroids are tried in turn (barycentric test); a point
    outside the mesh gets the nearest element and ``inside = False``.
    """
    from scipy.spatial import cKDTree
    pts = np.atleast_2d(np.asarray(pts, float))
    X = np.asarray(mesh.nodes, float)
    T = np.asarray(mesh.tets, np.int64)
    cen = X[T].mean(axis=1)
    k = min(candidates, len(T))
    _, near = cKDTree(cen).query(pts, k=k)
    near = near.reshape(len(pts), -1)
    best = near[:, 0].copy()
    inside = np.zeros(len(pts), bool)
    for c in range(near.shape[1]):
        todo = ~inside
        if not todo.any():
            break
        ti = near[todo, c]
        V = X[T[ti]]                                           # (m,4,3)
        A = np.stack([V[:, 1] - V[:, 0], V[:, 2] - V[:, 0], V[:, 3] - V[:, 0]], axis=2)
        det = np.linalg.det(A)
        ok = np.abs(det) > 1e-300
        lam = np.zeros((len(ti), 3))
        if ok.any():
            lam[ok] = np.einsum("mij,mj->mi", np.linalg.inv(A[ok]), (pts[todo] - V[:, 0])[ok])
        bary = np.column_stack([1.0 - lam.sum(axis=1), lam])
        hit = ok & (bary.min(axis=1) >= -1e-9)
        idx = np.nonzero(todo)[0]
        best[idx[hit]] = ti[hit]
        inside[idx[hit]] = True
    return best, inside
