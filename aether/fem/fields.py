"""
Field post-processing: reconstruct E and H anywhere from the DOF vector.

The FEM unknown is the vector of tangential circulations; every derived
quantity (E, H, current density, power loss, stored energy, Poynting flux)
is produced here so the rest of the code never has to know the basis.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np

from ..core.constants import c0, eps0, eta0, mu0, omega
from ..mesh.tetmesh import TetMesh
from .elements import DofMap, tet_basis
from .quadrature import tet_rule


class RegionLookup:
    """``region -> complex material value``; a class (not a lambda) so a
    Solution can be pickled between the solver process and the GUI."""

    def __init__(self, table: dict, default: complex = 1.0 + 0j):
        self.table = table
        self.default = default

    def __call__(self, region):
        return self.table.get(region, self.default)


class FieldSolution:
    """A single-frequency electric-field solution on a mesh."""

    def __init__(self, mesh: TetMesh, dofmap: DofMap, x: np.ndarray,
                 freq: float, eps_of_region=None, mu_of_region=None):
        self.mesh = mesh
        self.dofmap = dofmap
        self.x = np.asarray(x, complex)
        self.freq = float(freq)
        self.k0 = 2.0 * math.pi * self.freq / c0
        self.eps_of_region = eps_of_region or RegionLookup({})
        self.mu_of_region = mu_of_region or RegionLookup({})

    # ------------------------------------------------------------------
    def eval_at(self, tets: np.ndarray, points: np.ndarray
                ) -> Tuple[np.ndarray, np.ndarray]:
        """
        ``(E, H)`` at *points*, each evaluated inside its own element *tets*.

        Unlike :meth:`evaluate` there is no cell search -- the caller says
        which element a point belongs to, which is exactly what a surface
        integral over mesh faces knows (the face's owner element).
        """
        dm = self.dofmap
        tets = np.asarray(tets, np.int64)
        pts = np.asarray(points, float)
        g = self.mesh.grads[tets]
        cen = self.mesh.centroids()[tets]
        lam = 0.25 + np.einsum("eia,ea->ei", g, pts - cen)    # linear in x
        fp = dm.face_perm[tets] if dm.order >= 2 else None
        N, C = tet_basis(dm.order, g, lam, fp)
        c = self.x[dm.elem_dofs[tets]] * dm.elem_signs[tets]
        E = np.einsum("eia,ei->ea", N, c)
        cE = np.einsum("eia,ei->ea", C, c)
        mu = np.array([self.mu_of_region(int(r))
                       for r in self.mesh.tet_region[tets]])
        H = -cE / (1j * omega(self.freq) * mu0 * mu[:, None])
        return E, H

    def E_at_centroids(self) -> np.ndarray:
        """(M,3) complex E field at every tetrahedron centroid [V/m]."""
        return self._eval(np.array([0.25, 0.25, 0.25, 0.25]))[0]

    def curlE_at_centroids(self) -> np.ndarray:
        return self._eval(np.array([0.25, 0.25, 0.25, 0.25]))[1]

    def H_at_centroids(self) -> np.ndarray:
        """H = -curl(E) / (j*omega*mu)  [A/m]."""
        _, cE = self._eval(np.array([0.25, 0.25, 0.25, 0.25]))
        mu = np.array([self.mu_of_region(int(r)) for r in self.mesh.tet_region])
        w = omega(self.freq)
        return -cE / (1j * w * mu0 * mu[:, None])

    def _eval(self, lam: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        dm = self.dofmap
        g = self.mesh.grads
        fp = dm.face_perm if dm.order >= 2 else None
        N, C = tet_basis(dm.order, g, lam, fp)
        c = self.x[dm.elem_dofs] * dm.elem_signs
        E = np.einsum("eia,ei->ea", N, c)
        cE = np.einsum("eia,ei->ea", C, c)
        return E, cE

    # ------------------------------------------------------------------
    def evaluate(self, points: np.ndarray) -> np.ndarray:
        """E at arbitrary points (nearest-cell barycentric evaluation)."""
        pts = np.atleast_2d(np.asarray(points, float))
        cen = self.mesh.centroids()
        out = np.zeros((len(pts), 3), complex)
        dm = self.dofmap
        fp = dm.face_perm if dm.order >= 2 else None
        for i, p in enumerate(pts):
            k = int(np.argmin(((cen - p) ** 2).sum(axis=1)))
            lam = _bary_tet(self.mesh.nodes[self.mesh.tets[k]], p)
            N, _ = tet_basis(dm.order, self.mesh.grads[k:k + 1], lam,
                             None if fp is None else fp[k:k + 1])
            c = self.x[dm.elem_dofs[k]] * dm.elem_signs[k]
            out[i] = np.einsum("ia,i->a", N[0], c)
        return out

    # ------------------------------------------------------- energies
    def stored_energy(self) -> Tuple[float, float]:
        """(electric, magnetic) stored energy [J]."""
        qp, qw = tet_rule(2 if self.dofmap.order == 1 else 4)
        V = self.mesh.volumes
        eps = np.array([self.eps_of_region(int(r)) for r in self.mesh.tet_region])
        mu = np.array([self.mu_of_region(int(r)) for r in self.mesh.tet_region])
        We = Wm = 0.0
        dm = self.dofmap
        fp = dm.face_perm if dm.order >= 2 else None
        c = self.x[dm.elem_dofs] * dm.elem_signs
        w_ang = omega(self.freq)
        for q in range(len(qw)):
            N, C = tet_basis(dm.order, self.mesh.grads, qp[q], fp)
            E = np.einsum("eia,ei->ea", N, c)
            cE = np.einsum("eia,ei->ea", C, c)
            H = -cE / (1j * w_ang * mu0 * mu[:, None])
            We += float(np.sum(qw[q] * V * 0.25 * eps0 * eps.real
                               * np.sum(np.abs(E) ** 2, axis=1)))
            Wm += float(np.sum(qw[q] * V * 0.25 * mu0 * mu.real
                               * np.sum(np.abs(H) ** 2, axis=1)))
        return We, Wm

    def dielectric_loss(self) -> float:
        """Volume power loss in lossy dielectrics [W]."""
        qp, qw = tet_rule(2 if self.dofmap.order == 1 else 4)
        V = self.mesh.volumes
        eps = np.array([self.eps_of_region(int(r)) for r in self.mesh.tet_region])
        w_ang = omega(self.freq)
        dm = self.dofmap
        fp = dm.face_perm if dm.order >= 2 else None
        c = self.x[dm.elem_dofs] * dm.elem_signs
        P = 0.0
        for q in range(len(qw)):
            N, _ = tet_basis(dm.order, self.mesh.grads, qp[q], fp)
            E = np.einsum("eia,ei->ea", N, c)
            P += float(np.sum(qw[q] * V * 0.5 * w_ang * eps0
                              * (-eps.imag) * np.sum(np.abs(E) ** 2, axis=1)))
        return P

    # ---------------------------------------------------------- export
    def to_vtk(self, path: str, name: str = "E") -> str:
        from ..io.vtk_io import write_vtu
        E = self.E_at_centroids()
        H = self.H_at_centroids()
        return write_vtu(path, self.mesh,
                         cell_data={f"{name}_real": E.real, f"{name}_imag": E.imag,
                                    f"{name}_mag": np.abs(E),
                                    "H_mag": np.abs(H),
                                    "region": self.mesh.tet_region})


def _bary_tet(p: np.ndarray, x: np.ndarray) -> np.ndarray:
    T = np.stack([p[1] - p[0], p[2] - p[0], p[3] - p[0]], axis=1)
    try:
        u = np.linalg.solve(T, x - p[0])
    except np.linalg.LinAlgError:            # pragma: no cover
        u = np.zeros(3)
    return np.array([1.0 - u.sum(), u[0], u[1], u[2]])


__all__ = ["FieldSolution"]
