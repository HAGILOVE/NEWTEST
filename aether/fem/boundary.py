"""
Boundary-condition application.

Everything except PEC enters the system as a **surface term** added to the
operator; PEC is the only *essential* condition and is imposed by eliminating
the constrained degrees of freedom.

Surface term (impedance / radiation / lumped RLC sheets):

    A += j*k0 * Y~ * int_S (n x N_i).(n x N_j) dS ,   Y~ = eta0 / Zs

``Y~ = 1`` reproduces the first-order Sommerfeld absorbing boundary
(free-space matched), ``Zs`` from :meth:`Boundary.surface_impedance` covers
finite conductivity, roughness, thin-film and lumped R-L-C sheets.
"""
from __future__ import annotations

import cmath
from typing import Dict, List, Tuple

import numpy as np
import scipy.sparse as sp

from ..core.constants import eta0
from ..core.logging import get_logger
from .assembly import assemble_directional_mass, assemble_surface_mass
from .elements import DofMap

log = get_logger("fem.boundary")

ESSENTIAL = ("pec", "symmetry_e")
NATURAL_FREE = ("pmc", "symmetry_h")


class BoundaryTerms:
    """Pre-assembled surface mass matrices, one per boundary condition."""

    def __init__(self, mesh, dofmap: DofMap, design):
        self.mesh = mesh
        self.dofmap = dofmap
        self.design = design
        self.matrices: Dict[str, sp.csr_matrix] = {}
        self.kinds: Dict[str, str] = {}
        self.eta_rel: Dict[str, complex] = {}
        self.sheet_scale: Dict[str, float] = {}       # width / length of lumped RLC sheets
        self.directions: Dict[str, np.ndarray] = {}
        self._pec_dofs = None
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        mesh, dm = self.mesh, self.dofmap
        pec_tris: List[np.ndarray] = []
        claimed = np.zeros(len(mesh.surf_tris), bool)

        for b in self.design.boundaries:
            idx = mesh.bc_faces.get(b.name, np.zeros(0, dtype=np.int64))
            if len(idx) == 0:
                continue
            claimed[idx] = True
            tris = mesh.surf_tris[idx]
            if b.btype in ESSENTIAL:
                pec_tris.append(tris)
            elif b.btype in NATURAL_FREE:
                pass                                   # natural: nothing to do
            elif b.btype == "lumped_rlc":
                # A lumped element conducts along its own direction only, and a
                # sheet of width w and length L around a total impedance Z has
                # the surface impedance Z * w / L.
                d, L, w = sheet_geometry(mesh.nodes, tris, b.params.get("direction"))
                self.matrices[b.name] = assemble_directional_mass(mesh, dm, tris, d)
                self.kinds[b.name] = b.btype
                self.eta_rel[b.name] = _relative_eta(mesh, tris)
                self.sheet_scale[b.name] = w / L
                self.directions[b.name] = d
            else:
                self.matrices[b.name] = assemble_surface_mass(mesh, dm, tris)
                self.kinds[b.name] = b.btype
                self.eta_rel[b.name] = _relative_eta(mesh, tris)

        # unassigned + not a port -> default boundary (Warps: perfect E)
        port_idx = np.concatenate([v for v in mesh.port_faces.values()]) \
            if mesh.port_faces else np.zeros(0, dtype=np.int64)
        free = np.zeros(len(mesh.surf_tris), bool)
        free[:getattr(mesh, "n_outer_faces", len(mesh.surf_tris))] = True
        free[port_idx.astype(np.int64)] = False
        free &= ~claimed
        default = getattr(self.design, "default_boundary", "pec")
        if np.any(free) and default == "pec":
            pec_tris.append(mesh.surf_tris[free])
            log.info("default PEC applied to %d unassigned boundary triangles",
                     int(free.sum()))

        if pec_tris:
            all_pec = np.vstack(pec_tris)
            self._pec_dofs = dm.dofs_on_triangles(all_pec)
        else:
            self._pec_dofs = np.zeros(0, dtype=np.int64)

    # ------------------------------------------------------------------
    @property
    def pec_dofs(self) -> np.ndarray:
        return self._pec_dofs                          # type: ignore

    def apply(self, A: sp.csr_matrix, k0: float, freq: float) -> sp.csr_matrix:
        """Add every non-essential surface term to *A* at frequency *freq*."""
        by_name = {b.name: b for b in self.design.boundaries}
        for name, B in self.matrices.items():
            b = by_name[name]
            if b.btype == "radiation":
                y = 1.0 / self.eta_rel[name]
            else:
                Zs = b.surface_impedance(freq)
                if b.btype == "lumped_rlc":
                    Zs = Zs * self.sheet_scale.get(name, 1.0)
                    if abs(Zs) < 1e-12:                       # a short: very conductive, not "nothing"
                        Zs = 1e-12
                elif abs(Zs) < 1e-30:
                    continue
                y = eta0 / Zs
            A = A + (1j * k0 * y) * B
        return A.tocsr()


def sheet_geometry(nodes, tris, direction=None):
    """
    ``(unit direction, length L, width w)`` of a flat sheet.

    *direction* is the way the current runs; without one it is the sheet's
    shorter in-plane side, which is how a lumped element bridges a gap. L is
    the extent along it and w = area / L.
    """
    tris = np.asarray(tris, np.int64)
    pts = nodes[np.unique(tris)]
    tri = nodes[tris]
    area = 0.5 * float(np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1).sum())
    c = pts - pts.mean(axis=0)
    _, sv, vt = np.linalg.svd(c, full_matrices=False)
    normal = vt[2] if len(sv) > 2 else np.array([0.0, 0.0, 1.0])
    d = None
    if direction is not None and np.linalg.norm(np.asarray(direction, float)) > 1e-12:
        d = np.asarray(direction, float)
        d = d - np.dot(d, normal) * normal                  # in the sheet's plane
        if np.linalg.norm(d) > 1e-9:
            d = d / np.linalg.norm(d)
        else:
            d = None
    if d is None:
        # the axes of the sheet's own outline: principal directions, shorter one
        e1, e2 = vt[0], vt[1]
        ext = [float(np.ptp(pts @ e1)), float(np.ptp(pts @ e2))]
        d = e1 if ext[0] <= ext[1] else e2
        # snap to a coordinate axis when it is (nearly) one
        k = int(np.argmax(np.abs(d)))
        if abs(d[k]) > 0.999:
            d = np.eye(3)[k] * np.sign(d[k])
    L = float(np.ptp(pts @ d)) or 1.0
    return d, L, area / L


def _relative_eta(mesh, tris) -> complex:
    """Relative wave impedance of the medium touching those triangles."""
    return 1.0 + 0.0j


def constrain(A: sp.csr_matrix, b: np.ndarray, fixed: np.ndarray
              ) -> Tuple[sp.csr_matrix, np.ndarray, np.ndarray]:
    """
    Eliminate the essential (PEC) degrees of freedom.

    Returns the reduced system and the index array of the retained DOFs.
    """
    n = A.shape[0]
    keep = np.ones(n, bool)
    if len(fixed):
        keep[fixed] = False
    idx = np.nonzero(keep)[0]
    Ar = A[idx][:, idx].tocsc()
    br = b[idx] if b.ndim == 1 else b[idx, :]
    return Ar, br, idx


def expand(x_reduced: np.ndarray, idx: np.ndarray, n: int) -> np.ndarray:
    """Scatter a reduced solution back to the full DOF vector."""
    if x_reduced.ndim == 1:
        x = np.zeros(n, dtype=complex)
        x[idx] = x_reduced
        return x
    x = np.zeros((n, x_reduced.shape[1]), dtype=complex)
    x[idx, :] = x_reduced
    return x


__all__ = ["BoundaryTerms", "constrain", "expand", "ESSENTIAL"]
