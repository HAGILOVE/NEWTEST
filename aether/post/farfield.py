"""
Near-to-far-field transformation (Stratton-Chu surface equivalence).

Equivalent surface currents on the radiation boundary,

    J_s = n x H ,      M_s = -n x E ,

radiate into free space; the far field follows from the radiation vectors

    N(th,ph) = int_S J_s e^{+j k0 r'.r^} dS
    L(th,ph) = int_S M_s e^{+j k0 r'.r^} dS

    E_th = -j k0 e^{-j k0 r}/(4 pi r) (L_ph + eta0 N_th)
    E_ph = +j k0 e^{-j k0 r}/(4 pi r) (L_th - eta0 N_ph)

From those come gain, directivity, axial ratio, radiation efficiency and the
usual cut plots -- computed on the same mesh the fields were solved on, with
no interpolation step in between.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np

from ..core.constants import c0, eta0, mu0, omega


@dataclass
class FarField:
    """Sampled far field on a (theta, phi) grid."""
    theta: np.ndarray                 # (nt,) radians
    phi: np.ndarray                   # (np_,) radians
    E_theta: np.ndarray               # (nt, np_) complex
    E_phi: np.ndarray
    freq: float
    P_accepted: float = 0.0

    # ---- derived quantities ------------------------------------------
    @property
    def U(self) -> np.ndarray:
        """Radiation intensity [W/sr] (r^2 * S)."""
        return (np.abs(self.E_theta) ** 2 + np.abs(self.E_phi) ** 2) / (2 * eta0)

    def radiated_power(self) -> float:
        th, ph = self.theta, self.phi
        w_th = np.gradient(th) if len(th) > 1 else np.array([1.0])
        w_ph = np.gradient(ph) if len(ph) > 1 else np.array([2 * math.pi])
        return float(np.sum(self.U * np.sin(th)[:, None]
                            * w_th[:, None] * w_ph[None, :]))

    def directivity(self) -> np.ndarray:
        P = self.radiated_power()
        return 4 * math.pi * self.U / max(P, 1e-300)

    def gain(self) -> np.ndarray:
        if self.P_accepted <= 0:
            return self.directivity()
        return 4 * math.pi * self.U / self.P_accepted

    def peak_directivity_dbi(self) -> float:
        return float(10 * np.log10(max(self.directivity().max(), 1e-300)))

    def axial_ratio(self) -> np.ndarray:
        """Polarisation axial ratio (linear, >= 1)."""
        a, b = self.E_theta, self.E_phi
        s0 = np.abs(a) ** 2 + np.abs(b) ** 2
        s1 = np.abs(a) ** 2 - np.abs(b) ** 2
        s2 = 2 * np.real(a * np.conj(b))
        s3 = -2 * np.imag(a * np.conj(b))
        lin = np.sqrt(np.maximum(s1 ** 2 + s2 ** 2, 0.0))
        num = np.sqrt(np.maximum(s0 + lin, 0.0))
        den = np.sqrt(np.maximum(s0 - lin, 1e-300))
        return num / den

    def cut(self, phi_deg: float = 0.0):
        """(theta_deg, directivity_dBi) at the nearest phi cut."""
        k = int(np.argmin(np.abs(self.phi - math.radians(phi_deg))))
        d = self.directivity()[:, k]
        return np.degrees(self.theta), 10 * np.log10(np.maximum(d, 1e-300))


def compute_farfield(field_solution, mesh, boundary_faces: np.ndarray,
                     n_theta: int = 91, n_phi: int = 181,
                     P_accepted: float = 0.0) -> FarField:
    """
    Transform the near field on *boundary_faces* into the far field.

    ``boundary_faces`` are indices into ``mesh.surf_tris`` (typically the
    radiation-boundary triangles).
    """
    tris = mesh.surf_tris[boundary_faces]
    nrm = mesh.surf_normals[boundary_faces]
    p = mesh.nodes[tris]
    cen = p.mean(axis=1)
    area = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0],
                                         p[:, 2] - p[:, 0]), axis=1)

    E = field_solution.evaluate(cen)
    Hall = field_solution.H_at_centroids()
    owner = mesh.surf_owner_tet[boundary_faces]
    H = Hall[owner]

    Js = np.cross(nrm, H)
    Ms = -np.cross(nrm, E)

    k0 = 2 * math.pi * field_solution.freq / c0
    th = np.linspace(0.0, math.pi, n_theta)
    ph = np.linspace(0.0, 2 * math.pi, n_phi)
    TH, PH = np.meshgrid(th, ph, indexing="ij")
    r_hat = np.stack([np.sin(TH) * np.cos(PH),
                      np.sin(TH) * np.sin(PH),
                      np.cos(TH)], axis=-1)                # (nt, np, 3)
    th_hat = np.stack([np.cos(TH) * np.cos(PH),
                       np.cos(TH) * np.sin(PH),
                       -np.sin(TH)], axis=-1)
    ph_hat = np.stack([-np.sin(PH), np.cos(PH), np.zeros_like(PH)], axis=-1)

    phase = np.exp(1j * k0 * np.einsum("ijk,mk->ijm", r_hat, cen))  # (nt,np,M)
    w = (area[None, None, :] * phase)
    N = np.einsum("ijm,ma->ija", w, Js)
    L = np.einsum("ijm,ma->ija", w, Ms)

    N_th = np.einsum("ija,ija->ij", N, th_hat)
    N_ph = np.einsum("ija,ija->ij", N, ph_hat)
    L_th = np.einsum("ija,ija->ij", L, th_hat)
    L_ph = np.einsum("ija,ija->ij", L, ph_hat)

    c = 1j * k0 / (4 * math.pi)
    E_th = -c * (L_ph + eta0 * N_th)
    E_ph = c * (L_th - eta0 * N_ph)
    return FarField(th, ph, E_th, E_ph, field_solution.freq, P_accepted)


__all__ = ["FarField", "compute_farfield"]
