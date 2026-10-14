"""
Near-to-far-field transformation (Stratton-Chu surface equivalence).

Equivalent surface currents on the radiation boundary,

    J_s = n x H ,      M_s = -n x E ,

radiate into free space; the far field follows from the radiation vectors

    N(th,ph) = int_S J_s e^{+j k0 r'.r^} dS
    L(th,ph) = int_S M_s e^{+j k0 r'.r^} dS

    E_th = -j k0 e^{-j k0 r}/(4 pi r) (L_ph + eta0 N_th)
    E_ph = +j k0 e^{-j k0 r}/(4 pi r) (L_th - eta0 N_ph)

Gain, directivity, axial ratio, efficiency and the usual cuts come from those
on the same mesh the fields were solved on.

Power bookkeeping
-----------------
The absolute amplitude of a driven solution depends on how the excitation was
normalised, but every figure of merit is a ratio of two powers that scale
together.  Accepted power is therefore taken from the field itself::

    P_accepted = P_radiated + P_dissipated

``P_radiated`` integrates the far-field intensity, ``P_dissipated`` is the
dielectric loss plus the loss in finite-conductivity / impedance walls.  That
makes ``gain = 4 pi U / P_accepted`` and ``efficiency = P_rad / P_accepted``
independent of port normalisation.  As a check on the *domain* (not the
transform), the power absorbed by the radiation boundary itself is reported
beside the far-field power: if they differ by much, the air box is too small
for a first-order absorbing boundary.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import numpy as np

from ..core.constants import c0, eta0, omega

CHUNK = 192            # far-field directions evaluated per block


# --------------------------------------------------------------------------


@dataclass
class FarField:
    """
    Far field sampled on a (theta, phi) grid, normalised to 1 W accepted.

    ``E_theta`` / ``E_phi`` are ``r * E`` (the ``e^{-jkr}/r`` factor removed)
    in V for 1 W of accepted power; ``U`` is then radiation intensity in W/sr
    per accepted watt.
    """
    theta: np.ndarray                 # (nt,) radians, 0..pi inclusive
    phi: np.ndarray                   # (np_,) radians, [0, 2 pi) periodic
    E_theta: np.ndarray               # (nt, np_) complex
    E_phi: np.ndarray
    freq: float
    P_accepted: float = 1.0
    P_radiated: float = 0.0
    P_dissipated: float = 0.0
    P_boundary: float = 0.0           # absorbed by the radiation boundary
    info: dict = field(default_factory=dict)

    # ---- derived quantities ------------------------------------------
    @property
    def U(self) -> np.ndarray:
        """Radiation intensity [W/sr] for the accepted power it carries."""
        return (np.abs(self.E_theta) ** 2 + np.abs(self.E_phi) ** 2) / (2 * eta0)

    def _weights(self) -> np.ndarray:
        th = self.theta
        dth = np.gradient(th) if len(th) > 1 else np.ones(1)
        w = dth.copy()
        if len(th) > 1:                    # trapezoid ends
            w[0] = (th[1] - th[0]) / 2
            w[-1] = (th[-1] - th[-2]) / 2
        dph = 2 * math.pi / len(self.phi)
        return (np.sin(th) * w)[:, None] * dph * np.ones(len(self.phi))[None, :]

    def radiated_power(self) -> float:
        return float(np.sum(self.U * self._weights()))

    def directivity(self) -> np.ndarray:
        return 4 * math.pi * self.U / max(self.radiated_power(), 1e-300)

    def gain(self) -> np.ndarray:
        """Gain over accepted power (IEEE gain, includes dissipation)."""
        return 4 * math.pi * self.U / max(self.P_accepted, 1e-300)

    def realized_gain(self, mismatch: float = 1.0) -> np.ndarray:
        """Gain scaled by ``1 - |S11|^2`` (impedance mismatch included)."""
        return self.gain() * mismatch

    def component_gain(self, which: str = "theta") -> np.ndarray:
        E = self.E_theta if which == "theta" else self.E_phi
        return 4 * math.pi * (np.abs(E) ** 2 / (2 * eta0)) / max(
            self.P_accepted, 1e-300)

    def peak_directivity_dbi(self) -> float:
        return float(10 * np.log10(max(self.directivity().max(), 1e-300)))

    def peak_gain_dbi(self) -> float:
        return float(10 * np.log10(max(self.gain().max(), 1e-300)))

    def peak_direction(self) -> Tuple[float, float]:
        """(theta_deg, phi_deg) of maximum radiation intensity."""
        k = np.unravel_index(int(np.argmax(self.U)), self.U.shape)
        return float(np.degrees(self.theta[k[0]])), float(np.degrees(self.phi[k[1]]))

    @property
    def efficiency(self) -> float:
        return self.P_radiated / max(self.P_accepted, 1e-300)

    def axial_ratio(self) -> np.ndarray:
        """Polarisation axial ratio (linear, >= 1)."""
        a, b = self.E_theta, self.E_phi
        s0 = np.abs(a) ** 2 + np.abs(b) ** 2
        s1 = np.abs(a) ** 2 - np.abs(b) ** 2
        s2 = 2 * np.real(a * np.conj(b))
        lin = np.sqrt(np.maximum(s1 ** 2 + s2 ** 2, 0.0))
        num = np.sqrt(np.maximum(s0 + lin, 0.0))
        den = np.sqrt(np.maximum(s0 - lin, 1e-300))
        return num / den

    def cut(self, phi_deg: float = 0.0, kind: str = "directivity"):
        """``(theta_deg, dBi)`` along the nearest phi cut."""
        dphi = np.abs((self.phi - math.radians(phi_deg) + math.pi)
                      % (2 * math.pi) - math.pi)
        k = int(np.argmin(dphi))
        arr = {"directivity": self.directivity, "gain": self.gain}[kind]()
        return np.degrees(self.theta), 10 * np.log10(np.maximum(arr[:, k], 1e-300))

    def _wrap_index(self, phi_rad: float) -> int:
        d = np.abs((self.phi - phi_rad + math.pi) % (2 * math.pi) - math.pi)
        return int(np.argmin(d))

    def summary(self) -> Dict[str, float]:
        th, ph = self.peak_direction()
        d = self.directivity()
        it = int(np.argmin(np.abs(self.theta - math.radians(th))))
        ip = self._wrap_index(math.radians(ph))
        ib = int(np.argmin(np.abs(self.theta - (math.pi - math.radians(th)))))
        jb = self._wrap_index(math.radians(ph) + math.pi)
        return {
            "peakDirectivityDbi": self.peak_directivity_dbi(),
            "peakGainDbi": self.peak_gain_dbi(),
            "peakTheta": th, "peakPhi": ph,
            "radiatedPower": self.P_radiated,
            "acceptedPower": self.P_accepted,
            "dissipatedPower": self.P_dissipated,
            "efficiency": self.efficiency,
            "boundaryPower": self.P_boundary,
            "maxIntensity": float(self.U.max()),
            "axialRatioAtPeak": float(self.axial_ratio()[it, ip]),
            "frontToBackDb": float(10 * np.log10(
                max(d[it, ip], 1e-300) / max(d[ib, jb], 1e-300))),
        }


# --------------------------------------------------------------------------


def radiation_faces(design, mesh) -> np.ndarray:
    """Indices into ``mesh.surf_tris`` of every radiation-boundary triangle."""
    idx = [np.asarray(mesh.bc_faces.get(b.name, []), np.int64)
           for b in design.boundaries if b.btype == "radiation"]
    return np.unique(np.concatenate(idx)) if idx else np.zeros(0, np.int64)


def _surface_currents(field_solution, mesh, faces):
    tris = mesh.surf_tris[faces]
    nrm = mesh.surf_normals[faces]
    p = mesh.nodes[tris]
    cen = p.mean(axis=1)
    area = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0],
                                         p[:, 2] - p[:, 0]), axis=1)
    owner = mesh.surf_owner_tet[faces]
    E, H = field_solution.eval_at(owner, cen)
    return cen, area, nrm, E, H


def transform_currents(cen, area, nrm, E, H, freq: float,
                       n_theta: int = 91, n_phi: int = 72,
                       theta=None, phi=None) -> FarField:
    """
    Far field of the equivalent currents ``J = n x H``, ``M = -n x E`` on a
    closed surface given as face centroids / areas / outward normals.

    This is the pure integral (no mesh, no solver); :func:`compute_farfield`
    feeds it the traces of a FEM solution.
    """
    Js = np.cross(nrm, H)
    Ms = -np.cross(nrm, E)
    k0 = 2 * math.pi * freq / c0

    th = np.linspace(0.0, math.pi, n_theta) if theta is None \
        else np.asarray(theta, float)
    ph = np.linspace(0.0, 2 * math.pi, n_phi, endpoint=False) if phi is None \
        else np.asarray(phi, float)
    TH, PH = np.meshgrid(th, ph, indexing="ij")
    st, ct, sp, cp = np.sin(TH), np.cos(TH), np.sin(PH), np.cos(PH)
    rhat = np.stack([st * cp, st * sp, ct], axis=-1).reshape(-1, 3)
    thhat = np.stack([ct * cp, ct * sp, -st], axis=-1).reshape(-1, 3)
    phhat = np.stack([-sp, cp, np.zeros_like(PH)], axis=-1).reshape(-1, 3)

    wJ = area[:, None] * Js
    wM = area[:, None] * Ms
    n_dir = rhat.shape[0]
    Eth = np.empty(n_dir, complex)
    Eph = np.empty(n_dir, complex)
    c = 1j * k0 / (4 * math.pi)
    for s0 in range(0, n_dir, CHUNK):
        sl = slice(s0, min(s0 + CHUNK, n_dir))
        phase = np.exp(1j * k0 * (rhat[sl] @ cen.T))          # (d, M)
        N = phase @ wJ                                         # (d, 3)
        L = phase @ wM
        N_th = np.einsum("da,da->d", N, thhat[sl])
        N_ph = np.einsum("da,da->d", N, phhat[sl])
        L_th = np.einsum("da,da->d", L, thhat[sl])
        L_ph = np.einsum("da,da->d", L, phhat[sl])
        Eth[sl] = -c * (L_ph + eta0 * N_th)
        Eph[sl] = c * (L_th - eta0 * N_ph)
    ff = FarField(th, ph, Eth.reshape(TH.shape), Eph.reshape(TH.shape), freq)
    ff.P_radiated = ff.radiated_power()
    return ff


def compute_farfield(field_solution, mesh, boundary_faces: np.ndarray,
                     n_theta: int = 91, n_phi: int = 72,
                     P_accepted: float = 0.0, theta=None, phi=None
                     ) -> FarField:
    """
    Transform the near field on *boundary_faces* into the far field.

    ``boundary_faces`` are indices into ``mesh.surf_tris`` (the radiation
    boundary).  The returned amplitudes carry the solution's own scaling; use
    :func:`antenna_parameters` for the power-normalised result.
    """
    cen, area, nrm, E, H = _surface_currents(field_solution, mesh,
                                             np.asarray(boundary_faces))
    ff = transform_currents(cen, area, nrm, E, H, field_solution.freq,
                            n_theta, n_phi, theta, phi)
    ff.P_accepted = P_accepted
    return ff


# --------------------------------------------------------------------------


def _wall_loss(design, mesh, dofmap, fs, bts) -> float:
    """Power dissipated in finite-conductivity / impedance walls [W]."""
    total = 0.0
    x = fs.x
    by_name = {b.name: b for b in design.boundaries}
    for name, B in bts.matrices.items():
        b = by_name[name]
        if b.btype not in ("finite_cond", "impedance"):
            continue
        zs = b.surface_impedance(fs.freq)
        if abs(zs) < 1e-30:
            continue
        et2 = float(np.real(np.conj(x) @ (B @ x)))     # int |E_t|^2 dS
        total += 0.5 * (1.0 / zs).real * et2
    return total


def _boundary_absorbed(design, mesh, dofmap, fs, bts) -> float:
    """Power absorbed by the first-order radiation boundary [W]."""
    x = fs.x
    total = 0.0
    for name, B in bts.matrices.items():
        if bts.kinds.get(name) != "radiation":
            continue
        et2 = float(np.real(np.conj(x) @ (B @ x)))
        total += 0.5 * et2 / eta0
    return total


def antenna_parameters(solution, freq: Optional[float] = None,
                       excitation: int = 0, n_theta: int = 91,
                       n_phi: int = 72) -> FarField:
    """
    Power-normalised far field of one excitation of a solved design.

    Requires saved fields (``save_fields=True`` or a sweep with
    ``save_fields``) and at least one radiation boundary.
    """
    from ..fem.boundary import BoundaryTerms

    design, mesh = solution.design, solution.mesh
    if not solution.fields:
        raise RuntimeError("no field data — analyse with 'save fields' enabled")
    faces = radiation_faces(design, mesh)
    if len(faces) == 0:
        raise RuntimeError("the design has no radiation boundary; the far "
                           "field is computed on it. Assign a Radiation "
                           "boundary to the outer faces of the air region.")
    f = float(freq) if freq is not None else float(solution.freqs[-1])
    fs = solution.field(f, int(excitation))
    ff = compute_farfield(fs, mesh, faces, n_theta, n_phi)

    bts = BoundaryTerms(mesh, solution.dofmap, design)
    p_diss = fs.dielectric_loss() + _wall_loss(design, mesh, solution.dofmap,
                                               fs, bts)
    p_bnd = _boundary_absorbed(design, mesh, solution.dofmap, fs, bts)
    p_rad = ff.P_radiated
    p_acc = p_rad + p_diss
    if p_acc <= 0:
        raise RuntimeError("the field carries no radiated or dissipated power")
    scale = 1.0 / math.sqrt(p_acc)
    ff.E_theta = ff.E_theta * scale
    ff.E_phi = ff.E_phi * scale
    ff.P_radiated = p_rad / p_acc
    ff.P_dissipated = p_diss / p_acc
    ff.P_boundary = p_bnd / p_acc
    ff.P_accepted = 1.0
    ff.freq = fs.freq
    ff.info = {"faces": int(len(faces)), "excitation": int(excitation)}
    return ff


__all__ = ["FarField", "compute_farfield", "transform_currents",
           "radiation_faces",
           "antenna_parameters"]
