"""
Port modal analysis.

A wave port is a two-dimensional eigenvalue problem posed on a planar
cross-section of the model.  Writing the field as

    E(x,y,z) = [E_t(x,y) + z^ E_z(x,y)] exp(-gamma z)

and substituting into the vector Helmholtz equation gives, after the standard
scaling ``Ez~ = j*beta*E_z`` that removes the propagation constant from the
z-equation, the generalised eigenproblem

    | -A_tt   T_tz | |E_t |          | T_tt  0 | |E_t |
    |   0     A_zz | |Ez~ |  = beta^2| T_zt  0 | |Ez~ |

with

    A_tt = int (1/mu)(curl_t E_t)(curl_t W_t) - k0^2 int eps E_t.W_t
    T_tt = int (1/mu) E_t.W_t
    T_tz = int (1/mu) W_t . grad_t Ez~          (T_zt = T_tz^T)
    A_zz = int (1/mu) grad_t Wz.grad_t Ez~ - k0^2 int eps Wz Ez~

Transverse fields use the *trace of the volume basis* (Whitney / order-2 edge
functions), the longitudinal field uses matching Lagrange elements.  Because
the port basis is literally the restriction of the 3-D basis, the modal
projection ``v_m = int_S W_i . e_m dS`` is exactly the surface mass matrix
applied to the mode vector -- no interpolation error is introduced at the
port plane.

Modes are normalised to ``int_S e_m . e_m dS = 1`` (unconjugated, the
normalisation the weak form's modal expansion requires) and the wave
impedance is recovered from the modal power flow, ``Z = 1/(2P)``.
"""
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import scipy.linalg as sla
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from ..core.constants import c0, eps0, eta0, mu0, omega
from ..core.logging import get_logger
from .elements import (DofMap, TRI_EDGES, tri_basis, tri_geometry, tri_nodal)
from .quadrature import tri_rule

log = get_logger("fem.ports")


@dataclass
class PortMode:
    """One propagating or evanescent modal solution on a port plane."""
    index: int
    gamma: complex                 # propagation constant  (alpha + j beta)
    beta: float
    alpha: float
    k_cut: complex                 # cutoff wavenumber
    f_cut: float                   # cutoff frequency [Hz]
    coeffs: np.ndarray             # transverse coefficients in GLOBAL dof space
    ez_coeffs: np.ndarray          # longitudinal (scaled) coefficients
    Z_wave: complex                # power-normalised wave impedance
    Z_pv: complex = 0.0
    Z_pi: complex = 0.0
    power: complex = 0.0
    kind: str = "unknown"
    propagating: bool = False

    @property
    def Z0(self) -> complex:
        return self.Z_port

    @property
    def Z_port(self) -> complex:
        """
        The impedance used for S-parameter normalisation.

        For a hollow waveguide the wave impedance *is* the port impedance.
        For a TEM or quasi-TEM line (coax, microstrip, stripline, CPW) the
        meaningful number is the line impedance V^2/(2P), which needs a
        voltage path -- so it is used whenever an integration line was given,
        exactly as HFSS does.
        """
        if self.Z_pv != 0:
            return self.Z_pv
        return self.Z_wave


@dataclass
class PortSolution:
    """All modes of one port at one frequency, plus the projection vectors."""
    name: str
    freq: float
    modes: List[PortMode]
    tris: np.ndarray
    dofs: np.ndarray               # global dofs carried by the port surface
    B: sp.csr_matrix               # surface tangential mass matrix (global)
    normal: np.ndarray
    area: float
    n_modes: int = 1

    def v(self, m: int) -> np.ndarray:
        """Projection vector ``v_i = int_S W_i . e_m dS`` in global dof space."""
        return np.asarray(self.B @ self.modes[m].coeffs).ravel()

    def project(self, E: np.ndarray, m: int) -> complex:
        """Modal amplitude ``<E, e_m> = int_S E . e_m dS``."""
        return complex(self.modes[m].coeffs @ (self.B @ E))


# --------------------------------------------------------------------------
# port surface discretisation
# --------------------------------------------------------------------------


class PortSurface:
    """Local 2-D discretisation of one port face."""

    def __init__(self, mesh, dofmap: DofMap, tris: np.ndarray):
        self.mesh = mesh
        self.dofmap = dofmap
        self.order = dofmap.order
        self.tris = np.sort(np.asarray(tris, dtype=np.int64), axis=1)
        self.area_e, self.grads, self.normals = tri_geometry(mesh.nodes, self.tris)
        self.area = float(self.area_e.sum())
        self.normal = self.normals.mean(axis=0)
        self.normal /= max(np.linalg.norm(self.normal), 1e-300)
        self._build_dofs()

    # ---- degrees of freedom ----------------------------------------------
    def _build_dofs(self):
        from .assembly import surface_dofs
        gd, _ = surface_dofs(self.mesh, self.dofmap, self.tris)
        self.global_t = np.unique(gd)
        lut = -np.ones(int(self.global_t.max()) + 1, dtype=np.int64)
        lut[self.global_t] = np.arange(len(self.global_t))
        self.elem_t = lut[gd]                       # (K, nbt) local indices
        self.n_t = len(self.global_t)

        # scalar (longitudinal) dofs
        nodes = np.unique(self.tris)
        nlut = -np.ones(self.mesh.n_nodes, dtype=np.int64)
        nlut[nodes] = np.arange(len(nodes))
        self.nodes = nodes
        if self.order == 1:
            self.elem_z = nlut[self.tris]
            self.n_z = len(nodes)
        else:
            from .elements import _edge_lookup
            lut_e = _edge_lookup(self.mesh)
            ea = self.tris[:, TRI_EDGES[:, 0]]
            eb = self.tris[:, TRI_EDGES[:, 1]]
            eid = np.stack([lut_e[ea[:, k], eb[:, k]] for k in range(3)], axis=1)
            uniq_e = np.unique(eid)
            elut = -np.ones(int(uniq_e.max()) + 1, dtype=np.int64)
            elut[uniq_e] = np.arange(len(uniq_e))
            self.elem_z = np.concatenate([nlut[self.tris],
                                          len(nodes) + elut[eid]], axis=1)
            self.n_z = len(nodes) + len(uniq_e)
            self.port_edges = uniq_e

    # ---- perimeter (PEC contour) -----------------------------------------
    def perimeter(self) -> Tuple[np.ndarray, np.ndarray]:
        """Local transverse and scalar DOFs lying on the port boundary curve."""
        e = np.concatenate([self.tris[:, [0, 1]], self.tris[:, [0, 2]],
                            self.tris[:, [1, 2]]])
        e = np.sort(e, axis=1)
        uniq, cnt = np.unique(e, axis=0, return_counts=True)
        bnd = uniq[cnt == 1]
        if len(bnd) == 0:
            return np.zeros(0, np.int64), np.zeros(0, np.int64)
        from .elements import _edge_lookup, _face_lookup
        lut = _edge_lookup(self.mesh)
        eid = lut[bnd[:, 0], bnd[:, 1]]
        gt = [eid]
        if self.order >= 2:
            gt.append(eid + self.dofmap.n_edges)
        gt = np.unique(np.concatenate(gt))
        local_t = np.nonzero(np.isin(self.global_t, gt))[0].astype(np.int64)
        bnodes = np.unique(bnd)
        local_z = np.nonzero(np.isin(self.nodes, bnodes))[0].astype(np.int64)
        if self.order >= 2:
            emap = {e_: i for i, e_ in enumerate(self.port_edges)}
            extra = [len(self.nodes) + emap[i] for i in eid if i in emap]
            local_z = np.concatenate([local_z, np.array(extra, dtype=np.int64)])
        return local_t, np.unique(local_z)

    # ---- material coefficients -------------------------------------------
    def material_coeffs(self, freq: float, eps_of_region, mu_of_region):
        """(eps, mu) per port triangle, taken from the adjacent tetrahedron."""
        fid = face_indices(self.mesh, self.tris)
        f2t = _face_to_tet_cached(self.mesh)
        tet = np.where(fid >= 0, f2t[np.maximum(fid, 0), 0], 0)
        reg = self.mesh.tet_region[np.maximum(tet, 0)]
        eps = np.array([eps_of_region(int(r)) for r in reg], dtype=complex)
        mu = np.array([mu_of_region(int(r)) for r in reg], dtype=complex)
        return eps, mu


def face_indices(mesh, tris: np.ndarray) -> np.ndarray:
    """Row index into ``mesh.faces`` for each (node-sorted) triangle."""
    cache = getattr(mesh, "_face_index_map", None)
    if cache is None:
        cache = {tuple(f): i for i, f in enumerate(mesh.faces)}
        mesh._face_index_map = cache
    return np.array([cache.get(tuple(t), -1) for t in np.sort(tris, axis=1)],
                    dtype=np.int64)


def _face_to_tet_cached(mesh) -> np.ndarray:
    f2t = getattr(mesh, "_f2t_cache", None)
    if f2t is None:
        f2t = mesh.face_to_tet()
        mesh._f2t_cache = f2t
    return f2t


# --------------------------------------------------------------------------
# eigen solve
# --------------------------------------------------------------------------


def solve_port_modes(mesh, dofmap: DofMap, tris: np.ndarray, freq: float,
                     eps_of_region, mu_of_region, n_modes: int = 1,
                     name: str = "port",
                     integration_line=None) -> PortSolution:
    """Solve the 2-D modal eigenproblem on one port face."""
    from .assembly import assemble_surface_mass

    ps = PortSurface(mesh, dofmap, tris)
    if len(ps.tris) == 0:
        raise ValueError(f"port {name!r} has no triangles")
    k0 = 2.0 * math.pi * freq / c0
    eps_e, mu_e = ps.material_coeffs(freq, eps_of_region, mu_of_region)

    order = ps.order
    qp, qw = tri_rule(2 if order == 1 else 4)
    K = len(ps.tris)
    nbt = ps.elem_t.shape[1]
    nbz = ps.elem_z.shape[1]

    Att = np.zeros((K, nbt, nbt), dtype=complex)
    Ttt = np.zeros((K, nbt, nbt), dtype=complex)
    Ttz = np.zeros((K, nbt, nbz), dtype=complex)
    Azz = np.zeros((K, nbz, nbz), dtype=complex)
    Mtt = np.zeros((K, nbt, nbt), dtype=float)      # plain (unweighted) mass

    inv_mu = 1.0 / mu_e
    for q in range(len(qw)):
        N, C = tri_basis(order, ps.grads, qp[q])
        phi, gphi = tri_nodal(order, qp[q], ps.grads)
        w = qw[q] * ps.area_e
        NN = np.einsum("eia,eja->eij", N, N)
        CC = np.einsum("eia,eja->eij", C, C)
        NG = np.einsum("eia,eja->eij", N, gphi)
        GG = np.einsum("eia,eja->eij", gphi, gphi)
        PP = np.einsum("ei,ej->eij", phi, phi)
        wm = (w * inv_mu)[:, None, None]
        we = (w * eps_e)[:, None, None]
        Att += wm * CC - (k0 ** 2) * we * NN
        Ttt += wm * NN
        Ttz += wm * NG
        Azz += wm * GG - (k0 ** 2) * we * PP
        Mtt += w[:, None, None] * NN

    def _scatter(local, ei, ej, ni, nj):
        rows = np.repeat(ei, local.shape[2], axis=1).ravel()
        cols = np.tile(ej, (1, local.shape[1])).ravel()
        return sp.coo_matrix((local.reshape(-1), (rows, cols)),
                             shape=(ni, nj)).tocsr()

    A_tt = _scatter(Att, ps.elem_t, ps.elem_t, ps.n_t, ps.n_t)
    T_tt = _scatter(Ttt, ps.elem_t, ps.elem_t, ps.n_t, ps.n_t)
    T_tz = _scatter(Ttz, ps.elem_t, ps.elem_z, ps.n_t, ps.n_z)
    A_zz = _scatter(Azz, ps.elem_z, ps.elem_z, ps.n_z, ps.n_z)
    M_tt = _scatter(Mtt.astype(complex), ps.elem_t, ps.elem_t, ps.n_t, ps.n_t)

    # PEC on the port perimeter
    bt, bz = ps.perimeter()
    keep_t = np.setdiff1d(np.arange(ps.n_t), bt)
    keep_z = np.setdiff1d(np.arange(ps.n_z), bz)
    if len(keep_t) == 0:
        raise ValueError(f"port {name!r}: every transverse DOF is on the PEC "
                         "perimeter -- the port face is too coarsely meshed")

    A_tt = A_tt[keep_t][:, keep_t]
    T_tt = T_tt[keep_t][:, keep_t]
    T_tz = T_tz[keep_t][:, keep_z]
    A_zz = A_zz[keep_z][:, keep_z]
    nt, nz = len(keep_t), len(keep_z)

    beta2, vecs = _schur_eig(A_tt, T_tt, T_tz, A_zz, n_modes, k0,
                             eps_e, mu_e)

    modes: List[PortMode] = []
    for i in range(min(n_modes, len(beta2))):
        b2 = beta2[i]
        vec = vecs[:, i]
        ct = np.zeros(ps.n_t, dtype=complex)
        cz = np.zeros(ps.n_z, dtype=complex)
        ct[keep_t] = vec[:nt]
        cz[keep_z] = vec[nt:]
        # normalise  int e_t . e_t dS = 1   (unconjugated)
        nrm = complex(ct @ (M_tt @ ct))
        if abs(nrm) < 1e-300:
            continue
        scale = 1.0 / cmath.sqrt(nrm)
        ct *= scale
        cz *= scale
        pol = _polarity(ps, order, qp, qw, ct, integration_line)
        ct *= pol
        cz *= pol
        beta = cmath.sqrt(b2)
        if beta.real < 0:
            beta = -beta
        # gamma = alpha + j*beta with the e^{-gamma z} convention
        if b2.real > 0 and abs(b2.imag) < abs(b2.real):
            gamma = 1j * beta
        else:
            gamma = cmath.sqrt(-b2)
            if gamma.real < 0:
                gamma = -gamma
        kc2 = (k0 ** 2) * complex(np.mean(eps_e * mu_e)) - b2
        kc = cmath.sqrt(kc2)
        f_cut = float(abs(kc) * c0 / (2 * math.pi
                                      * math.sqrt(abs(np.mean(eps_e * mu_e).real))))
        P = _modal_power(ps, order, qp, qw, ct, cz, beta, freq, mu_e)
        Zw = 1.0 / (2.0 * P) if abs(P) > 1e-300 else 0.0
        kind = _classify(ps, order, qp, qw, ct, cz)
        gd = ps.global_t
        coeffs = np.zeros(dofmap.n_dof, dtype=complex)
        coeffs[gd] = ct
        m = PortMode(index=i, gamma=gamma, beta=float(gamma.imag),
                     alpha=float(gamma.real), k_cut=kc, f_cut=f_cut,
                     coeffs=coeffs, ez_coeffs=cz, Z_wave=Zw, power=P,
                     kind=kind, propagating=bool(gamma.imag > 1e-6 * k0))
        m.Z_pv, m.Z_pi = _line_impedances(ps, order, qp, qw, ct, cz, P,
                                          integration_line, mesh)
        modes.append(m)

    if not modes:
        raise RuntimeError(f"port {name!r}: modal solver returned no usable mode")

    B = assemble_surface_mass(mesh, dofmap, ps.tris)
    sol = PortSolution(name, freq, modes, ps.tris, ps.global_t, B,
                       ps.normal, ps.area, n_modes=len(modes))
    log.info("port %-10s f=%.4f GHz : %s", name, freq / 1e9,
             ", ".join(f"m{m.index+1} {m.kind} beta={m.beta:.4g} "
                       f"fc={m.f_cut/1e9:.4f}GHz Z={m.Z_wave.real:.2f}Ohm"
                       for m in modes))
    return sol


def _schur_eig(A_tt, T_tt, T_tz, A_zz, n_modes, k0, eps_e, mu_e):
    """
    Eliminate the longitudinal block, then solve a regular eigenproblem.

    The raw pencil is singular: the ``Ez~`` columns of the right-hand matrix
    vanish, producing a cloud of infinite eigenvalues that a shift-invert
    Arnoldi iteration happily mistakes for physical modes.  Eliminating
    ``Ez~`` analytically,

        A_zz Ez~ = beta^2 T_zt E_t        =>  Ez~ = beta^2 A_zz^-1 T_zt E_t
        A_tt E_t = -beta^2 (T_tt - T_tz A_zz^-1 T_zt) E_t

    leaves a *regular* pencil of roughly half the size whose whole spectrum is
    physical.  That is both faster and the reason the modal solver stays
    reliable on fine port meshes.
    """
    nt = A_tt.shape[0]
    nz = A_zz.shape[0]
    T_zt = np.asarray(T_tz.todense()).T                 # (nz, nt)
    if nz:
        Azz = A_zz.tocsc()
        try:
            X = spla.spsolve(Azz, T_zt)
        except Exception:                               # pragma: no cover
            X = np.linalg.lstsq(np.asarray(Azz.todense()), T_zt, rcond=None)[0]
        X = np.atleast_2d(np.asarray(X, dtype=complex))
        if X.shape[0] != nz:
            X = X.T
        C = np.asarray(T_tt.todense()) - np.asarray(T_tz.todense()) @ X
    else:                                               # pragma: no cover
        X = np.zeros((0, nt), dtype=complex)
        C = np.asarray(T_tt.todense())

    Ad = np.asarray(A_tt.todense())
    w, u = sla.eig(Ad, -C)
    good = np.isfinite(w)
    w, u = w[good], u[:, good]
    cap = max((k0 ** 2) * max(float(np.real(np.mean(eps_e * mu_e))), 1.0),
              k0 ** 2) * 1e8 + 1e6
    ok = np.abs(w) < cap
    w, u = w[ok], u[:, ok]
    order = np.argsort(-w.real)
    w, u = w[order], u[:, order]
    keep = min(max(n_modes * 3, n_modes + 4), len(w))
    w, u = w[:keep], u[:, :keep]
    v = (X @ u) * w[None, :] if nz else np.zeros((0, u.shape[1]), complex)
    return w, np.vstack([u, v])


def _generalized_eig(A, B, n_modes, k0, eps_e, mu_e):
    """Dense QZ for small ports, shift-invert Arnoldi for large ones."""
    n = A.shape[0]
    n_max = max(int(np.real(np.mean(eps_e * mu_e))), 1)
    target = (k0 ** 2) * n_max
    dense_limit = 900
    if n > dense_limit:
        try:
            sigma = target * 1.02 + 1e-3
            k = min(max(2 * n_modes + 6, 10), n - 3)
            w, v = spla.eigs(A.astype(complex), k=k, M=B.astype(complex),
                             sigma=sigma, which="LM",
                             tol=1e-10, maxiter=2000)
            good = np.isfinite(w)
            w, v = w[good], v[:, good]
            if len(w) >= n_modes:
                cap = max(target, k0 ** 2) * 1e8 + 1e6
                ok = np.abs(w) < cap
                w, v = w[ok], v[:, ok]
                order = np.argsort(-w.real)
                return w[order], v[:, order]
            log.debug("sparse port eigensolver returned too few modes; "
                      "falling back to dense QZ")
        except Exception as exc:                       # pragma: no cover
            log.debug("sparse port eigensolver failed (%s); using dense QZ", exc)
    Ad = np.asarray(A.todense())
    Bd = np.asarray(B.todense())
    w, v = sla.eig(Ad, Bd)
    good = np.isfinite(w)
    w, v = w[good], v[:, good]
    # drop numerical infinities produced by the singular pencil
    cap = max(target, k0 ** 2) * 1e8 + 1e6
    ok = np.abs(w) < cap
    w, v = w[ok], v[:, ok]
    order = np.argsort(-w.real)
    return w[order], v[:, order]


def _modal_power(ps: PortSurface, order, qp, qw, ct, cz, beta, freq, mu_e):
    """P = 0.5 Re int (E_t x H_t*) . n dS for the normalised mode."""
    w_ang = omega(freq)
    P = 0.0 + 0.0j
    b2 = beta * beta
    for q in range(len(qw)):
        N, _ = tri_basis(order, ps.grads, qp[q])
        _, gphi = tri_nodal(order, qp[q], ps.grads)
        Et = np.einsum("eia,ei->ea", N, ct[ps.elem_t])
        gz = np.einsum("eia,ei->ea", gphi, cz[ps.elem_z])
        X = gz - b2 * Et                            # grad(Ez~) - beta^2 E_t
        # H_t = -(1/(w mu beta)) z x X   ->   (E x H*).n = -(1/(w mu beta))^*
        #                                     * (E.X* )
        coef = np.conj(1.0 / (w_ang * mu0 * mu_e * beta))
        integ = np.einsum("ea,ea->e", Et, np.conj(X))
        P += np.sum(qw[q] * ps.area_e * (-coef) * integ)
    return 0.5 * P


def _polarity(ps: "PortSurface", order, qp, qw, ct, line) -> float:
    """
    Deterministic mode polarity.

    An eigenvector is only defined up to a sign, and that sign propagates
    straight into the off-diagonal S-parameters: two ports of the same
    uniform line would otherwise disagree by 180 degrees.  The rule is

    1. if the port has an integration line, orient the mode so that
       ``int_S e . l^ dS > 0`` (the HFSS convention),
    2. otherwise orient the *mean* transverse field so that its dominant
       global Cartesian component is positive,
    3. and if the mean vanishes by symmetry (higher-order modes), use the
       field at the point of maximum magnitude with the same rule.

    The result is reproducible across meshes, frequencies and ports.
    """
    mean = np.zeros(3, dtype=complex)
    peak = np.zeros(3, dtype=complex)
    peak_mag = -1.0
    for q in range(len(qw)):
        N, _ = tri_basis(order, ps.grads, qp[q])
        Et = np.einsum("eia,ei->ea", N, ct[ps.elem_t])
        mean += np.sum((qw[q] * ps.area_e)[:, None] * Et, axis=0)
        mag = np.sum(np.abs(Et) ** 2, axis=1)
        k = int(np.argmax(mag))
        if mag[k] > peak_mag:
            peak_mag = float(mag[k])
            peak = Et[k]
    if line is not None:
        d = np.asarray(line[1], float) - np.asarray(line[0], float)
        n = np.linalg.norm(d)
        if n > 1e-300:
            val = complex(mean @ (d / n))
            if abs(val) > 1e-14 * max(abs(mean).max(), 1e-30):
                return -1.0 if _phase_sign(val) < 0 else 1.0
    ref = mean if np.max(np.abs(mean)) > 1e-9 * max(np.max(np.abs(peak)), 1e-30) \
        else peak
    k = int(np.argmax(np.abs(ref)))
    return -1.0 if _phase_sign(ref[k]) < 0 else 1.0


def _phase_sign(z: complex) -> float:
    """Sign of a complex number under the 'largest real projection' rule."""
    if abs(z.real) >= abs(z.imag):
        return 1.0 if z.real >= 0 else -1.0
    return 1.0 if z.imag >= 0 else -1.0


def _classify(ps, order, qp, qw, ct, cz) -> str:
    """Rough TE / TM / TEM / hybrid classification from the field content."""
    ez = 0.0
    curl = 0.0
    for q in range(len(qw)):
        N, C = tri_basis(order, ps.grads, qp[q])
        phi, _ = tri_nodal(order, qp[q], ps.grads)
        e = np.einsum("ei,ei->e", phi, cz[ps.elem_z])
        cc = np.einsum("eia,ei->ea", C, ct[ps.elem_t])
        ez += float(np.sum(qw[q] * ps.area_e * np.abs(e) ** 2))
        curl += float(np.sum(qw[q] * ps.area_e * np.sum(np.abs(cc) ** 2, axis=1)))
    scale = max(ez, curl, 1e-300)
    has_z = ez / scale > 1e-6
    has_curl = curl / scale > 1e-6
    if has_z and has_curl:
        return "hybrid"
    if has_z:
        return "TM"
    if has_curl:
        return "TE"
    return "TEM"


def _line_impedances(ps, order, qp, qw, ct, cz, P, line, mesh):
    """
    Zpv = |V|^2 / (2 P*)   and   Zpi = 2 P / |I|^2 ,  with I = V / Z_wave.

    Requires a user integration line; without one both are reported as zero and
    the power-normalised wave impedance is used instead.
    """
    if line is None or abs(P) < 1e-300:
        return 0.0 + 0j, 0.0 + 0j
    V = line_voltage(ps, ct, np.asarray(line[0], float),
                     np.asarray(line[1], float))
    Zpv = (V * np.conj(V)) / (2.0 * np.conj(P))
    Zw = 1.0 / (2.0 * P)
    I = V / Zw if abs(Zw) > 1e-300 else 0.0
    Zpi = (2.0 * P) / (I * np.conj(I)) if abs(I) > 1e-300 else 0.0
    return complex(Zpv), complex(Zpi)


def line_voltage(ps: "PortSurface", ct: np.ndarray, p0: np.ndarray,
                 p1: np.ndarray, n_seg: int = 64) -> complex:
    """``V = -int_p0^p1 E . dl`` evaluated on the port surface field."""
    from .quadrature import line_rule
    xs, ws = line_rule(12)
    d = p1 - p0
    L = float(np.linalg.norm(d))
    if L < 1e-300:
        return 0.0 + 0j
    V = 0.0 + 0j
    for t, w in zip(xs, ws):
        pt = p0 + t * d
        E = evaluate_surface_field(ps, ct, pt)
        V += w * complex(np.dot(E, d))
    return -V


def evaluate_surface_field(ps: "PortSurface", ct: np.ndarray,
                           pt: np.ndarray) -> np.ndarray:
    """Evaluate the transverse modal field at one point on the port plane."""
    p = ps.mesh.nodes[ps.tris]
    lam = _barycentric(p, pt)
    inside = np.all(lam >= -1e-9, axis=1)
    idx = int(np.argmax(inside)) if np.any(inside) else \
        int(np.argmax(lam.min(axis=1)))
    l = np.clip(lam[idx], 0.0, 1.0)
    N, _ = tri_basis(ps.order, ps.grads[idx:idx + 1], l)
    return np.einsum("ia,i->a", N[0], ct[ps.elem_t[idx]])


def _barycentric(p: np.ndarray, pt: np.ndarray) -> np.ndarray:
    """Barycentric coordinates of *pt* in every triangle of *p* (K,3,3)."""
    v0 = p[:, 1] - p[:, 0]
    v1 = p[:, 2] - p[:, 0]
    v2 = pt[None, :] - p[:, 0]
    d00 = np.einsum("ij,ij->i", v0, v0)
    d01 = np.einsum("ij,ij->i", v0, v1)
    d11 = np.einsum("ij,ij->i", v1, v1)
    d20 = np.einsum("ij,ij->i", v2, v0)
    d21 = np.einsum("ij,ij->i", v2, v1)
    den = np.maximum(d00 * d11 - d01 * d01, 1e-300)
    b = (d11 * d20 - d01 * d21) / den
    c = (d00 * d21 - d01 * d20) / den
    return np.stack([1.0 - b - c, b, c], axis=1)


__all__ = ["PortMode", "PortSolution", "PortSurface", "solve_port_modes"]
