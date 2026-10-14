"""
Tetrahedral mesh container with the topology a curl-conforming FEM needs.

Beyond nodes and cells this class builds and caches:

* the **unique edge list** and the signed ``tet -> edge`` incidence
  (Nedelec/Whitney degrees of freedom live on edges),
* the unique face list and ``tet -> face`` incidence,
* boundary-face extraction with per-face region tags,
* per-element geometry (volume, barycentric gradients) which is what the
  element matrices are actually assembled from,
* quality metrics used by the adaptive-refinement error indicator.

Local numbering conventions (fixed for the whole code base)::

    edges = (0,1) (0,2) (0,3) (1,2) (1,3) (2,3)
    faces = (1,2,3) (0,2,3) (0,1,3) (0,1,2)     # face i is opposite node i
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..core.logging import get_logger

log = get_logger("mesh.tetmesh")

LOCAL_EDGES = np.array([[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]], dtype=np.int64)
LOCAL_FACES = np.array([[1, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2]], dtype=np.int64)
# which two local edges bound each local face (for face-based DOFs, order 2)
FACE_EDGES = np.array([[3, 4, 5], [1, 2, 5], [0, 2, 4], [0, 1, 3]], dtype=np.int64)


@dataclass
class TetMesh:
    """An unstructured tetrahedral mesh in SI metres."""

    nodes: np.ndarray                      # (N,3) float64
    tets: np.ndarray                       # (M,4) int64
    tet_region: np.ndarray = None          # (M,) int32 -> region id
    region_names: Dict[int, str] = field(default_factory=dict)
    surf_tris: np.ndarray = None           # (K,3) int64 tagged boundary faces
    surf_tag: np.ndarray = None            # (K,) int32
    tag_names: Dict[int, str] = field(default_factory=dict)
    # bodies that could not be built and are therefore not in this mesh
    skipped_bodies: Dict[str, str] = field(default_factory=dict)

    # caches
    _edges: Optional[np.ndarray] = field(default=None, repr=False)
    _tet_edge: Optional[np.ndarray] = field(default=None, repr=False)
    _tet_edge_sign: Optional[np.ndarray] = field(default=None, repr=False)
    _faces: Optional[np.ndarray] = field(default=None, repr=False)
    _tet_face: Optional[np.ndarray] = field(default=None, repr=False)
    _vol: Optional[np.ndarray] = field(default=None, repr=False)
    _grads: Optional[np.ndarray] = field(default=None, repr=False)
    _bnd_faces: Optional[np.ndarray] = field(default=None, repr=False)

    # ---------------------------------------------------------------- setup
    def __post_init__(self):
        self.nodes = np.ascontiguousarray(self.nodes, dtype=np.float64)
        self.tets = np.ascontiguousarray(self.tets, dtype=np.int64)
        if self.tet_region is None:
            self.tet_region = np.zeros(len(self.tets), dtype=np.int32)
        else:
            self.tet_region = np.asarray(self.tet_region, dtype=np.int32)
        if self.surf_tris is None:
            self.surf_tris = np.zeros((0, 3), dtype=np.int64)
        else:
            self.surf_tris = np.ascontiguousarray(self.surf_tris, dtype=np.int64)
        if self.surf_tag is None:
            self.surf_tag = np.zeros(len(self.surf_tris), dtype=np.int32)
        else:
            self.surf_tag = np.asarray(self.surf_tag, dtype=np.int32)
        self._orient()

    def _orient(self) -> None:
        """Force positive orientation (det > 0) so signed volumes are positive."""
        p = self.nodes[self.tets]
        d = np.einsum("ij,ij->i", np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]),
                      p[:, 3] - p[:, 0])
        bad = d < 0
        if np.any(bad):
            self.tets[bad] = self.tets[bad][:, [0, 1, 3, 2]]

    # ------------------------------------------------------------ dimensions
    @property
    def n_nodes(self) -> int:
        return len(self.nodes)

    @property
    def n_tets(self) -> int:
        return len(self.tets)

    @property
    def n_edges(self) -> int:
        return len(self.edges)

    @property
    def n_faces(self) -> int:
        return len(self.faces)

    # ------------------------------------------------------------- topology
    @property
    def edges(self) -> np.ndarray:
        """(E,2) sorted unique node pairs."""
        if self._edges is None:
            self._build_edges()
        return self._edges  # type: ignore

    @property
    def tet_edge(self) -> np.ndarray:
        """(M,6) global edge index of each local edge."""
        if self._tet_edge is None:
            self._build_edges()
        return self._tet_edge  # type: ignore

    @property
    def tet_edge_sign(self) -> np.ndarray:
        """(M,6) +1 if the local edge runs low->high global node id, else -1."""
        if self._tet_edge_sign is None:
            self._build_edges()
        return self._tet_edge_sign  # type: ignore

    def _build_edges(self) -> None:
        e = self.tets[:, LOCAL_EDGES]                    # (M,6,2)
        lo = e.min(axis=2)
        hi = e.max(axis=2)
        sign = np.where(e[:, :, 0] < e[:, :, 1], 1.0, -1.0)
        pairs = np.stack([lo, hi], axis=2).reshape(-1, 2)
        uniq, inv = np.unique(pairs, axis=0, return_inverse=True)
        self._edges = uniq.astype(np.int64)
        self._tet_edge = inv.reshape(-1, 6).astype(np.int64)
        self._tet_edge_sign = sign
        log.debug("mesh topology: %d nodes, %d tets, %d edges",
                  self.n_nodes, self.n_tets, len(uniq))

    @property
    def faces(self) -> np.ndarray:
        if self._faces is None:
            self._build_faces()
        return self._faces  # type: ignore

    @property
    def tet_face(self) -> np.ndarray:
        if self._tet_face is None:
            self._build_faces()
        return self._tet_face  # type: ignore

    def _build_faces(self) -> None:
        f = self.tets[:, LOCAL_FACES]                    # (M,4,3)
        sf = np.sort(f, axis=2).reshape(-1, 3)
        uniq, inv, cnt = np.unique(sf, axis=0, return_inverse=True,
                                   return_counts=True)
        self._faces = uniq.astype(np.int64)
        self._tet_face = inv.reshape(-1, 4).astype(np.int64)
        self._face_count = cnt

    @property
    def boundary_faces(self) -> np.ndarray:
        """(B,3) node ids of faces belonging to exactly one tet."""
        if self._bnd_faces is None:
            self.faces  # ensure built
            self._bnd_faces = self._faces[self._face_count == 1]  # type: ignore
        return self._bnd_faces  # type: ignore

    def boundary_face_index(self) -> np.ndarray:
        """Indices into ``faces`` of the boundary faces."""
        self.faces
        return np.nonzero(self._face_count == 1)[0]

    def face_to_tet(self) -> np.ndarray:
        """(F,2) adjacent tets per face; -1 where absent."""
        F = len(self.faces)
        out = -np.ones((F, 2), dtype=np.int64)
        slot = np.zeros(F, dtype=np.int8)
        tf = self.tet_face
        for loc in range(4):
            idx = tf[:, loc]
            s = slot[idx]
            out[idx, s] = np.arange(self.n_tets)
            slot[idx] = np.minimum(s + 1, 1)
        return out

    # ------------------------------------------------------------- geometry
    @property
    def volumes(self) -> np.ndarray:
        """(M,) signed-positive tetrahedron volumes [m^3]."""
        if self._vol is None:
            self._build_geometry()
        return self._vol  # type: ignore

    @property
    def grads(self) -> np.ndarray:
        """(M,4,3) gradients of the barycentric coordinates [1/m]."""
        if self._grads is None:
            self._build_geometry()
        return self._grads  # type: ignore

    def _build_geometry(self) -> None:
        p = self.nodes[self.tets]                        # (M,4,3)
        v1 = p[:, 1] - p[:, 0]
        v2 = p[:, 2] - p[:, 0]
        v3 = p[:, 3] - p[:, 0]
        det = np.einsum("ij,ij->i", np.cross(v1, v2), v3)
        vol = det / 6.0
        # grad(lambda_i): rows of the inverse Jacobian
        J = np.stack([v1, v2, v3], axis=1)               # (M,3,3)
        Jinv = np.linalg.inv(J)                          # (M,3,3)
        g123 = np.transpose(Jinv, (0, 2, 1))             # (M,3,3) rows = grad l1..l3
        g0 = -g123.sum(axis=1)
        self._grads = np.concatenate([g0[:, None, :], g123], axis=1)
        self._vol = vol

    def centroids(self) -> np.ndarray:
        return self.nodes[self.tets].mean(axis=1)

    def edge_vectors(self) -> np.ndarray:
        e = self.edges
        return self.nodes[e[:, 1]] - self.nodes[e[:, 0]]

    def edge_lengths(self) -> np.ndarray:
        return np.linalg.norm(self.edge_vectors(), axis=1)

    def bounding_box(self) -> Tuple[np.ndarray, np.ndarray]:
        return self.nodes.min(axis=0), self.nodes.max(axis=0)

    # -------------------------------------------------------------- quality
    def quality(self) -> np.ndarray:
        """
        Normalised radius-ratio quality in (0, 1]; 1 = regular tetrahedron.

        q = 3 * r_insphere / r_circumsphere  (a standard, scale-free metric).
        """
        p = self.nodes[self.tets]
        V = np.abs(self.volumes)
        # face areas
        A = np.zeros(len(p))
        for f in LOCAL_FACES:
            a = p[:, f[1]] - p[:, f[0]]
            b = p[:, f[2]] - p[:, f[0]]
            A += 0.5 * np.linalg.norm(np.cross(a, b), axis=1)
        r_in = 3.0 * V / np.maximum(A, 1e-300)
        # circumradius
        a = p[:, 1] - p[:, 0]; b = p[:, 2] - p[:, 0]; cc = p[:, 3] - p[:, 0]
        na = (a * a).sum(1); nb = (b * b).sum(1); nc = (cc * cc).sum(1)
        num = np.linalg.norm(na[:, None] * np.cross(b, cc)
                             + nb[:, None] * np.cross(cc, a)
                             + nc[:, None] * np.cross(a, b), axis=1)
        r_out = num / np.maximum(12.0 * V, 1e-300)
        return np.clip(3.0 * r_in / np.maximum(r_out, 1e-300), 0.0, 1.0)

    def report(self) -> str:
        q = self.quality()
        lo, hi = self.bounding_box()
        L = self.edge_lengths()
        return (
            f"TetMesh: {self.n_nodes} nodes, {self.n_tets} tets, "
            f"{self.n_edges} edges, {len(self.boundary_faces)} boundary faces\n"
            f"  bbox   : [{lo[0]:.4g}, {lo[1]:.4g}, {lo[2]:.4g}] .. "
            f"[{hi[0]:.4g}, {hi[1]:.4g}, {hi[2]:.4g}] m\n"
            f"  edge   : min={L.min():.4g}  mean={L.mean():.4g}  max={L.max():.4g} m\n"
            f"  volume : total={self.volumes.sum():.6g} m^3  "
            f"min_tet={self.volumes.min():.4g}\n"
            f"  quality: min={q.min():.4f}  mean={q.mean():.4f}  "
            f"(<0.02: {int((q < 0.02).sum())} slivers)"
        )

    # ------------------------------------------------------------ selection
    def nodes_on_plane(self, axis: int, value: float, tol: float = 1e-9) -> np.ndarray:
        return np.nonzero(np.abs(self.nodes[:, axis] - value) < tol)[0]

    def faces_with_tag(self, tag: int) -> np.ndarray:
        return self.surf_tris[self.surf_tag == tag]

    def tag_id(self, name: str) -> int:
        for k, v in self.tag_names.items():
            if v == name:
                return k
        raise KeyError(f"no boundary tag named {name!r}; "
                       f"have {sorted(self.tag_names.values())}")

    def region_id(self, name: str) -> int:
        for k, v in self.region_names.items():
            if v == name:
                return k
        raise KeyError(f"no region named {name!r}; "
                       f"have {sorted(self.region_names.values())}")

    def tets_in_region(self, name: str) -> np.ndarray:
        return np.nonzero(self.tet_region == self.region_id(name))[0]

    # ------------------------------------------------------------- subsets
    def submesh_from_faces(self, tris: np.ndarray):
        """
        Extract a 2-D triangular submesh (used for wave-port modal analysis).

        Returns ``(local_nodes, local_tris, node_map)`` where ``node_map`` maps
        local node index -> global node index.
        """
        used = np.unique(tris)
        remap = -np.ones(self.n_nodes, dtype=np.int64)
        remap[used] = np.arange(len(used))
        return self.nodes[used].copy(), remap[tris], used

    def copy(self) -> "TetMesh":
        return TetMesh(self.nodes.copy(), self.tets.copy(),
                       self.tet_region.copy(), dict(self.region_names),
                       self.surf_tris.copy(), self.surf_tag.copy(),
                       dict(self.tag_names))


__all__ = ["TetMesh", "LOCAL_EDGES", "LOCAL_FACES", "FACE_EDGES"]
