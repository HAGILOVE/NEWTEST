"""
Curl-conforming (Nedelec) vector basis functions on tetrahedra and triangles.

Order 1  -- Whitney / lowest-order edge elements, 6 DOF per tetrahedron::

    W_ab = lam_a grad(lam_b) - lam_b grad(lam_a)
    curl W_ab = 2 grad(lam_a) x grad(lam_b)

    The degree of freedom is the tangential circulation along the edge,
    ``int_edge E . t dl``, which is exactly what makes the tangential trace
    continuous across faces and the normal component free -- the physics of
    ``n x E`` continuity at a material interface.

Order 2  -- the complete second-kind hierarchical set, 20 DOF per tetrahedron:

    * 6  Whitney edge functions            (as above)
    * 6  edge gradients  grad(lam_a lam_b) (curl-free, spans the gradient part)
    * 8  face functions  lam_i W_jk, lam_j W_ki  for each face (i,j,k)

    The identity ``lam_i W_jk + lam_j W_ki + lam_k W_ij = 0`` is why a face
    contributes two -- not three -- independent functions.  Face node triples
    are ordered by **global** node id so that both tetrahedra sharing a face
    generate identical traces; no orientation signs are needed for the
    gradient and face blocks, only for the Whitney block.

The same construction restricted to a triangle gives the matching port basis
(3 / 8 DOF), which is what keeps the 2-D modal solve consistent with the 3-D
volume discretisation.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np

from ..mesh.tetmesh import LOCAL_EDGES, LOCAL_FACES

# local edges of each local face, as (i,j,k) index triples into the face
TRI_EDGES = np.array([[0, 1], [0, 2], [1, 2]], dtype=np.int64)


def n_dof_per_tet(order: int) -> int:
    return 6 if order == 1 else 20


def n_dof_per_tri(order: int) -> int:
    return 3 if order == 1 else 8


# --------------------------------------------------------------------------
# global DOF layout
# --------------------------------------------------------------------------


class DofMap:
    """
    Global degree-of-freedom numbering for a tetrahedral mesh.

    Layout (order 2)::

        [0 .. E)          Whitney edge functions
        [E .. 2E)         edge gradient functions
        [2E .. 2E + 2F)   two functions per face
    """

    def __init__(self, mesh, order: int = 1):
        self.mesh = mesh
        self.order = int(order)
        self.n_edges = mesh.n_edges
        self.n_faces = mesh.n_faces if order >= 2 else 0
        self.n_dof = self.n_edges if order == 1 else 2 * self.n_edges + 2 * self.n_faces
        self._elem = None
        self._sign = None
        self._face_perm = None

    # ---- element -> global ------------------------------------------------
    @property
    def elem_dofs(self) -> np.ndarray:
        """(M, nb) global DOF index for each local basis function."""
        if self._elem is None:
            self._build()
        return self._elem                          # type: ignore

    @property
    def elem_signs(self) -> np.ndarray:
        """(M, nb) orientation sign (+/-1) for each local basis function."""
        if self._sign is None:
            self._build()
        return self._sign                          # type: ignore

    @property
    def face_perm(self) -> np.ndarray:
        """(M,4,3) local node indices of each local face, sorted by global id."""
        if self._face_perm is None:
            self._build_face_perm()
        return self._face_perm                     # type: ignore

    def _build_face_perm(self):
        m = self.mesh
        nodes = m.tets[:, LOCAL_FACES]             # (M,4,3) global node ids
        order = np.argsort(nodes, axis=2)
        self._face_perm = LOCAL_FACES[None, :, :].repeat(len(m.tets), 0)
        self._face_perm = np.take_along_axis(self._face_perm, order, axis=2)

    def _build(self):
        m = self.mesh
        M = m.n_tets
        te = m.tet_edge                            # (M,6)
        ts = m.tet_edge_sign                       # (M,6)
        if self.order == 1:
            self._elem = te.copy()
            self._sign = ts.copy()
            return
        E, F = self.n_edges, self.n_faces
        tf = m.tet_face                            # (M,4)
        elem = np.empty((M, 20), dtype=np.int64)
        sign = np.ones((M, 20), dtype=np.float64)
        elem[:, 0:6] = te
        sign[:, 0:6] = ts
        elem[:, 6:12] = te + E
        elem[:, 12:20:2] = 2 * E + 2 * tf
        elem[:, 13:20:2] = 2 * E + 2 * tf + 1
        self._elem = elem
        self._sign = sign

    # ---- boundary handling ------------------------------------------------
    def dofs_on_triangles(self, tris: np.ndarray) -> np.ndarray:
        """
        All global DOFs whose basis function has a non-zero tangential trace
        on the given triangles -- i.e. the DOFs a PEC condition constrains.
        """
        m = self.mesh
        if len(tris) == 0:
            return np.zeros(0, dtype=np.int64)
        # edges of those triangles
        e = np.concatenate([tris[:, [0, 1]], tris[:, [0, 2]], tris[:, [1, 2]]])
        lo, hi = e.min(axis=1), e.max(axis=1)
        key = _edge_lookup(m)
        eid = key[lo, hi]
        eid = eid[eid >= 0]
        out = [eid]
        if self.order >= 2:
            out.append(eid + self.n_edges)
            fkey = _face_lookup(m)
            fid = fkey.get_many(np.sort(tris, axis=1))
            fid = fid[fid >= 0]
            out.append(2 * self.n_edges + 2 * fid)
            out.append(2 * self.n_edges + 2 * fid + 1)
        return np.unique(np.concatenate(out))


class _Lookup2:
    def __init__(self, pairs, n):
        from scipy.sparse import coo_matrix
        v = np.arange(len(pairs), dtype=np.int64) + 1
        self.m = coo_matrix((v, (pairs[:, 0], pairs[:, 1])),
                            shape=(n, n)).tocsr()

    def __getitem__(self, idx):
        lo, hi = idx
        return np.asarray(self.m[lo, hi]).ravel().astype(np.int64) - 1


_EDGE_CACHE: dict = {}
_FACE_CACHE: dict = {}


def _edge_lookup(mesh) -> _Lookup2:
    key = id(mesh)
    obj = _EDGE_CACHE.get(key)
    if obj is None or obj[0] is not mesh:
        obj = (mesh, _Lookup2(mesh.edges, mesh.n_nodes))
        _EDGE_CACHE[key] = obj
    return obj[1]


class _FaceLookup:
    def __init__(self, faces: np.ndarray):
        self.map = {tuple(f): i for i, f in enumerate(faces)}

    def get_many(self, tris: np.ndarray) -> np.ndarray:
        return np.array([self.map.get(tuple(t), -1) for t in tris],
                        dtype=np.int64)


def _face_lookup(mesh) -> _FaceLookup:
    key = id(mesh)
    obj = _FACE_CACHE.get(key)
    if obj is None or obj[0] is not mesh:
        obj = (mesh, _FaceLookup(mesh.faces))
        _FACE_CACHE[key] = obj
    return obj[1]


# --------------------------------------------------------------------------
# basis evaluation -- tetrahedra
# --------------------------------------------------------------------------


def tet_basis(order: int, grads: np.ndarray, lam: np.ndarray,
              face_perm: np.ndarray | None = None
              ) -> Tuple[np.ndarray, np.ndarray]:
    """
    Evaluate the vector basis and its curl at one barycentric point.

    Parameters
    ----------
    grads : (M,4,3)  gradients of the barycentric coordinates
    lam   : (4,)     barycentric coordinates of the evaluation point
    face_perm : (M,4,3) globally sorted face node triples (order >= 2 only)

    Returns
    -------
    N     : (M, nb, 3)
    curlN : (M, nb, 3)
    """
    M = grads.shape[0]
    a = LOCAL_EDGES[:, 0]
    b = LOCAL_EDGES[:, 1]
    ga = grads[:, a, :]                     # (M,6,3)
    gb = grads[:, b, :]
    la = lam[a][None, :, None]
    lb = lam[b][None, :, None]

    W = la * gb - lb * ga                   # (M,6,3)
    curlW = 2.0 * np.cross(ga, gb)          # (M,6,3)

    if order == 1:
        return W, curlW

    G = la * gb + lb * ga                   # grad(lam_a lam_b)
    curlG = np.zeros_like(G)

    if face_perm is None:
        raise ValueError("order-2 basis needs face_perm")
    i = face_perm[:, :, 0]                  # (M,4)
    j = face_perm[:, :, 1]
    k = face_perm[:, :, 2]
    gi = np.take_along_axis(grads, i[:, :, None], axis=1)   # (M,4,3)
    gj = np.take_along_axis(grads, j[:, :, None], axis=1)
    gk = np.take_along_axis(grads, k[:, :, None], axis=1)
    li = lam[i][:, :, None]
    lj = lam[j][:, :, None]
    lk = lam[k][:, :, None]

    Wjk = lj * gk - lk * gj
    Wki = lk * gi - li * gk
    F1 = li * Wjk
    F2 = lj * Wki
    cF1 = np.cross(gi, Wjk) + 2.0 * li * np.cross(gj, gk)
    cF2 = np.cross(gj, Wki) + 2.0 * lj * np.cross(gk, gi)

    N = np.empty((M, 20, 3))
    C = np.empty((M, 20, 3))
    N[:, 0:6] = W;  C[:, 0:6] = curlW
    N[:, 6:12] = G; C[:, 6:12] = curlG
    N[:, 12:20:2] = F1; C[:, 12:20:2] = cF1
    N[:, 13:20:2] = F2; C[:, 13:20:2] = cF2
    return N, C


# --------------------------------------------------------------------------
# basis evaluation -- triangles (port / surface integrals)
# --------------------------------------------------------------------------


def tri_basis(order: int, grads2: np.ndarray, lam: np.ndarray
              ) -> Tuple[np.ndarray, np.ndarray]:
    """
    Triangle edge basis (the exact trace of the tetrahedral basis).

    ``grads2`` are the 2-D barycentric gradients (M,3,3) expressed as 3-D
    vectors lying in the triangle plane.  Returns ``(N, curl_z)`` where
    ``curl_z`` is the scalar out-of-plane curl.
    """
    M = grads2.shape[0]
    a = TRI_EDGES[:, 0]
    b = TRI_EDGES[:, 1]
    ga = grads2[:, a, :]
    gb = grads2[:, b, :]
    la = lam[a][None, :, None]
    lb = lam[b][None, :, None]
    W = la * gb - lb * ga
    curlW = 2.0 * np.cross(ga, gb)
    if order == 1:
        return W, curlW
    G = la * gb + lb * ga
    curlG = np.zeros_like(G)
    g0, g1, g2 = grads2[:, 0:1], grads2[:, 1:2], grads2[:, 2:3]
    l0, l1, l2 = lam[0], lam[1], lam[2]
    W12 = l1 * g2 - l2 * g1
    W20 = l2 * g0 - l0 * g2
    F1 = l0 * W12
    F2 = l1 * W20
    cF1 = np.cross(g0, W12) + 2.0 * l0 * np.cross(g1, g2)
    cF2 = np.cross(g1, W20) + 2.0 * l1 * np.cross(g2, g0)
    N = np.concatenate([W, G, F1, F2], axis=1)
    C = np.concatenate([curlW, curlG, cF1, cF2], axis=1)
    return N, C


def tri_nodal(order: int, lam: np.ndarray, grads2: np.ndarray
              ) -> Tuple[np.ndarray, np.ndarray]:
    """
    Scalar Lagrange basis on a triangle: P1 (order 1) or P2 (order 2).

    Returns ``(phi (M,n), grad_phi (M,n,3))``.  P2 node ordering is
    ``[v0, v1, v2, m01, m02, m12]`` matching :data:`TRI_EDGES`.
    """
    M = grads2.shape[0]
    if order == 1:
        phi = np.repeat(lam[None, :], M, axis=0)
        return phi, grads2.copy()
    l = lam
    phi = np.empty((M, 6))
    gph = np.empty((M, 6, 3))
    for i in range(3):
        phi[:, i] = l[i] * (2.0 * l[i] - 1.0)
        gph[:, i] = (4.0 * l[i] - 1.0) * grads2[:, i]
    for e, (i, j) in enumerate(TRI_EDGES):
        phi[:, 3 + e] = 4.0 * l[i] * l[j]
        gph[:, 3 + e] = 4.0 * (l[i] * grads2[:, j] + l[j] * grads2[:, i])
    return phi, gph


def tri_geometry(nodes: np.ndarray, tris: np.ndarray):
    """
    Per-triangle area, in-plane barycentric gradients and unit normal.

    Returns ``(area (M,), grads (M,3,3), normal (M,3))``.
    """
    p = nodes[tris]                       # (M,3,3)
    v1 = p[:, 1] - p[:, 0]
    v2 = p[:, 2] - p[:, 0]
    nrm = np.cross(v1, v2)
    two_a = np.linalg.norm(nrm, axis=1)
    area = 0.5 * two_a
    n = nrm / np.maximum(two_a, 1e-300)[:, None]
    # grad lam_i = (n x e_i) / (2A) with e_i the opposite edge vector
    g0 = np.cross(n, p[:, 2] - p[:, 1])
    g1 = np.cross(n, p[:, 0] - p[:, 2])
    g2 = np.cross(n, p[:, 1] - p[:, 0])
    g = np.stack([g0, g1, g2], axis=1) / np.maximum(two_a, 1e-300)[:, None, None]
    return area, g, n


__all__ = ["DofMap", "tet_basis", "tri_basis", "tri_nodal", "tri_geometry",
           "n_dof_per_tet", "n_dof_per_tri", "TRI_EDGES"]
