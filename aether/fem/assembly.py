"""
Global matrix assembly for the curl-curl (vector Helmholtz) problem.

The discrete operator solved at every frequency is

    A(f) = S(1/mu_r) - k0(f)^2 T(eps_c) + boundary terms

where

    S_ij = int (1/mu_r) (curl N_i) . (curl N_j) dV
    T_ij = int eps_c   N_i . N_j dV

Both are assembled **once per material set** with the material coefficient
factored out per region, so a frequency sweep only rescales and re-sums the
pre-assembled per-region blocks instead of re-touching the mesh.  For a
dispersive model the region coefficient is simply re-evaluated -- still no
re-assembly.  This is what makes a 500-point sweep cheap.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import scipy.sparse as sp

from ..core.logging import get_logger, timed
from .elements import DofMap, n_dof_per_tet, tet_basis
from .quadrature import tet_rule

log = get_logger("fem.assembly")

CHUNK = 20000            # tets per assembly chunk (bounded memory)


class RegionOperators:
    """
    Pre-assembled stiffness/mass blocks, one pair per material region.

    ``S[r]`` carries no material factor (it is assembled with 1/mu_r = 1) and
    ``T[r]`` with eps = 1; the frequency loop forms

        A = sum_r  (1/mu_r(f)) S[r] - k0^2 sum_r eps_c_r(f) T[r]
    """

    def __init__(self, dofmap: DofMap, region_ids: List[int],
                 S: List[sp.csr_matrix], T: List[sp.csr_matrix]):
        self.dofmap = dofmap
        self.region_ids = region_ids
        self.S = S
        self.T = T
        self.n_dof = dofmap.n_dof

    def operator(self, k0: float, eps: Dict[int, complex],
                 mu: Dict[int, complex]) -> sp.csr_matrix:
        A = None
        for r, Sr, Tr in zip(self.region_ids, self.S, self.T):
            c1 = 1.0 / mu.get(r, 1.0 + 0j)
            c2 = -(k0 ** 2) * eps.get(r, 1.0 + 0j)
            blk = Sr * c1 + Tr * c2
            A = blk if A is None else A + blk
        return A.tocsr()

    def mass(self, eps: Dict[int, complex]) -> sp.csr_matrix:
        A = None
        for r, Tr in zip(self.region_ids, self.T):
            blk = Tr * eps.get(r, 1.0 + 0j)
            A = blk if A is None else A + blk
        return A.tocsr()

    def stiffness(self, mu: Dict[int, complex]) -> sp.csr_matrix:
        A = None
        for r, Sr in zip(self.region_ids, self.S):
            blk = Sr * (1.0 / mu.get(r, 1.0 + 0j))
            A = blk if A is None else A + blk
        return A.tocsr()


def assemble_regions(mesh, order: int = 1,
                     dofmap: Optional[DofMap] = None) -> RegionOperators:
    """Assemble per-region curl-curl and mass matrices."""
    dm = dofmap or DofMap(mesh, order)
    nb = n_dof_per_tet(order)
    deg = 2 if order == 1 else 4
    qp, qw = tet_rule(deg)
    grads = mesh.grads
    vols = mesh.volumes
    edofs = dm.elem_dofs
    esign = dm.elem_signs
    fperm = dm.face_perm if order >= 2 else None

    regions = np.unique(mesh.tet_region)
    S_list: List[sp.csr_matrix] = []
    T_list: List[sp.csr_matrix] = []

    with timed(log, f"assembling {len(regions)} region operator(s) "
                    f"[order {order}, {dm.n_dof} DOF]"):
        for r in regions:
            sel = np.nonzero(mesh.tet_region == r)[0]
            Sr, Tr = _assemble_subset(sel, grads, vols, edofs, esign, fperm,
                                      qp, qw, order, nb, dm.n_dof)
            S_list.append(Sr)
            T_list.append(Tr)
    return RegionOperators(dm, [int(r) for r in regions], S_list, T_list)


def _assemble_subset(sel, grads, vols, edofs, esign, fperm, qp, qw,
                     order, nb, n_dof):
    rows_all, cols_all, sv_all, tv_all = [], [], [], []
    for s0 in range(0, len(sel), CHUNK):
        idx = sel[s0:s0 + CHUNK]
        g = grads[idx]
        V = vols[idx]
        fp = fperm[idx] if fperm is not None else None
        Se = np.zeros((len(idx), nb, nb))
        Te = np.zeros((len(idx), nb, nb))
        for q in range(len(qw)):
            N, C = tet_basis(order, g, qp[q], fp)
            w = qw[q] * V
            Se += w[:, None, None] * np.einsum("eia,eja->eij", C, C)
            Te += w[:, None, None] * np.einsum("eia,eja->eij", N, N)
        sg = esign[idx]
        sgn = sg[:, :, None] * sg[:, None, :]
        Se *= sgn
        Te *= sgn
        d = edofs[idx]
        rows = np.repeat(d, nb, axis=1).ravel()
        cols = np.tile(d, (1, nb)).ravel()
        rows_all.append(rows); cols_all.append(cols)
        sv_all.append(Se.ravel()); tv_all.append(Te.ravel())
    rows = np.concatenate(rows_all); cols = np.concatenate(cols_all)
    S = sp.coo_matrix((np.concatenate(sv_all), (rows, cols)),
                      shape=(n_dof, n_dof)).tocsr()
    T = sp.coo_matrix((np.concatenate(tv_all), (rows, cols)),
                      shape=(n_dof, n_dof)).tocsr()
    return S.astype(np.complex128), T.astype(np.complex128)


# --------------------------------------------------------------------------
# surface (boundary) matrices
# --------------------------------------------------------------------------


def assemble_surface_mass(mesh, dofmap: DofMap, tris: np.ndarray,
                          order: Optional[int] = None) -> sp.csr_matrix:
    """
    ``B_ij = int_S (n x N_i) . (n x N_j) dS`` over the given triangles.

    Because the basis is curl-conforming, only the DOFs *belonging to* those
    triangles have a non-zero tangential trace, so the surface matrix is
    assembled directly from the triangle-local basis -- no volume element is
    consulted and the result is exactly the tangential mass matrix.
    """
    from .elements import tri_basis, tri_geometry
    from .quadrature import tri_rule
    order = order or dofmap.order
    n_dof = dofmap.n_dof
    if len(tris) == 0:
        return sp.csr_matrix((n_dof, n_dof), dtype=np.complex128)

    tris = np.sort(np.asarray(tris, dtype=np.int64), axis=1)
    area, g2, nrm = tri_geometry(mesh.nodes, tris)
    dofs, signs = surface_dofs(mesh, dofmap, tris)
    nbt = dofs.shape[1]
    qp, qw = tri_rule(2 if order == 1 else 4)
    Be = np.zeros((len(tris), nbt, nbt))
    for q in range(len(qw)):
        N, _ = tri_basis(order, g2, qp[q])
        w = qw[q] * area
        Be += w[:, None, None] * np.einsum("eia,eja->eij", N, N)
    sgn = signs[:, :, None] * signs[:, None, :]
    Be *= sgn
    rows = np.repeat(dofs, nbt, axis=1).ravel()
    cols = np.tile(dofs, (1, nbt)).ravel()
    return sp.coo_matrix((Be.ravel(), (rows, cols)),
                         shape=(n_dof, n_dof)).tocsr().astype(np.complex128)


def surface_dofs(mesh, dofmap: DofMap, tris: np.ndarray
                 ) -> Tuple[np.ndarray, np.ndarray]:
    """
    Map triangle-local basis functions to global DOFs, with orientation signs.

    Local ordering matches :func:`aether.fem.elements.tri_basis`:
    order 1 -> 3 edges; order 2 -> 3 edges, 3 edge gradients, 2 face functions.
    """
    from .elements import TRI_EDGES, _edge_lookup, _face_lookup
    tris = np.asarray(tris, dtype=np.int64)
    # triangle nodes sorted by global id -> matches the global face convention
    st = np.sort(tris, axis=1)
    ea = st[:, TRI_EDGES[:, 0]]
    eb = st[:, TRI_EDGES[:, 1]]
    lut = _edge_lookup(mesh)
    eid = np.stack([lut[ea[:, k], eb[:, k]] for k in range(3)], axis=1)
    # local edge (i<j in sorted order) always runs low->high -> sign +1,
    # but tri_basis is evaluated on the *sorted* node ordering, so we must
    # supply the geometry in that same order (see assemble_surface_mass).
    n_e = dofmap.n_edges
    if dofmap.order == 1:
        return eid, np.ones_like(eid, dtype=float)
    fl = _face_lookup(mesh)
    fid = fl.get_many(st)
    dofs = np.concatenate([eid, eid + n_e,
                           (2 * n_e + 2 * fid)[:, None],
                           (2 * n_e + 2 * fid + 1)[:, None]], axis=1)
    return dofs, np.ones_like(dofs, dtype=float)


def sorted_triangles(tris: np.ndarray) -> np.ndarray:
    """Node-sorted copy (the canonical orientation used by surface assembly)."""
    return np.sort(np.asarray(tris, dtype=np.int64), axis=1)


__all__ = ["RegionOperators", "assemble_regions", "assemble_surface_mass",
           "surface_dofs", "sorted_triangles"]
