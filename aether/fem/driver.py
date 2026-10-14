"""
Solution driver: mesh -> assemble -> ports -> solve -> S-parameters.

One :class:`Solution` object carries everything a report needs: the network
parameters, the port modal data (propagation constants, cutoffs, impedances),
optional field solutions, and the adaptive-pass convergence history.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import scipy.sparse as sp

from ..core.constants import c0, eta0
from ..core.logging import get_logger, timed
from ..post.sparam import SParameters
from .assembly import assemble_regions, assemble_surface_mass
from .boundary import BoundaryTerms, constrain, expand
from .elements import DofMap
from .fields import FieldSolution
from .linalg import LinearSolver
from .ports import PortSolution, solve_port_modes

log = get_logger("fem.driver")


@dataclass
class Solution:
    """Everything produced by one solve."""
    design: object
    mesh: object
    dofmap: DofMap
    freqs: np.ndarray
    sparams: Optional[SParameters] = None
    ports: Dict[float, List[PortSolution]] = field(default_factory=dict)
    fields: Dict[Tuple[float, int], FieldSolution] = field(default_factory=dict)
    convergence: List[dict] = field(default_factory=list)
    runtime: float = 0.0

    # -- convenience --------------------------------------------------
    @property
    def S(self) -> SParameters:
        if self.sparams is None:
            raise RuntimeError("this solution carries no S-parameters")
        return self.sparams

    def port_mode(self, freq: float, port: int = 0, mode: int = 0):
        key = min(self.ports, key=lambda f: abs(f - freq))
        return self.ports[key][port].modes[mode]

    def field(self, freq: float, excitation: int = 0) -> FieldSolution:
        key = min((k for k in self.fields if k[1] == excitation),
                  key=lambda k: abs(k[0] - freq))
        return self.fields[key]

    def summary(self) -> str:
        out = [f"Solution for design {self.design.name!r}  "
               f"({len(self.freqs)} frequency point(s), {self.runtime:.2f} s)"]
        if self.convergence:
            out.append("  adaptive passes:")
            for c in self.convergence:
                out.append(f"    pass {c['pass']}: {c['tets']:>7d} tets, "
                           f"{c['dof']:>8d} DOF, dS = "
                           + ("--" if c["delta_s"] is None
                              else f"{c['delta_s']:.5f}"))
        if self.sparams is not None:
            out.append("  " + self.sparams.summary().replace("\n", "\n  "))
        return "\n".join(out)


# --------------------------------------------------------------------------


def _material_maps(design, mesh, freq: float):
    """region id -> complex eps_r / mu_r at *freq*."""
    by_name = {s.name: s.material for s in design.solids}
    eps: Dict[int, complex] = {}
    mu: Dict[int, complex] = {}
    for rid, name in mesh.region_names.items():
        m = by_name.get(name)
        if m is None:
            eps[rid], mu[rid] = 1.0 + 0j, 1.0 + 0j
        else:
            eps[rid], mu[rid] = m.eps_c(freq), m.mu_c(freq)
    return eps, mu


def _lumped_mode(mesh, dofmap, tris, direction) -> Tuple[np.ndarray, sp.csr_matrix,
                                                         float, float]:
    """
    Uniform TEM-like mode for a lumped port.

    Returns ``(coeffs, B, L, w)`` where *coeffs* is the L2 projection of the
    unit vector ``direction`` onto the port surface basis normalised so that
    ``int |e|^2 dS = 1``, *L* the port length along the field direction and
    *w* the transverse width.
    """
    from .assembly import surface_dofs
    from .elements import tri_basis, tri_geometry
    from .quadrature import tri_rule

    tris = np.sort(np.asarray(tris, np.int64), axis=1)
    area_e, g2, nrm = tri_geometry(mesh.nodes, tris)
    d = np.asarray(direction, float)
    d = d / max(np.linalg.norm(d), 1e-300)
    gd, _ = surface_dofs(mesh, dofmap, tris)
    qp, qw = tri_rule(2 if dofmap.order == 1 else 4)
    r = np.zeros(dofmap.n_dof, dtype=complex)
    for q in range(len(qw)):
        N, _ = tri_basis(dofmap.order, g2, qp[q])
        val = (qw[q] * area_e)[:, None] * (N @ d)
        np.add.at(r, gd.ravel(), val.ravel())
    B = assemble_surface_mass(mesh, dofmap, tris)
    dofs = np.unique(gd)
    Bpp = B[dofs][:, dofs].tocsc()
    import scipy.sparse.linalg as spla
    c_loc = spla.spsolve(Bpp, r[dofs])
    c = np.zeros(dofmap.n_dof, dtype=complex)
    c[dofs] = c_loc
    nrm2 = complex(c @ (B @ c))
    if abs(nrm2) > 1e-300:
        c /= np.sqrt(nrm2)
    # geometry: extent along the field direction and the transverse width
    pts = mesh.nodes[np.unique(tris)]
    proj = pts @ d
    L = float(proj.max() - proj.min()) or 1.0
    area = float(area_e.sum())
    w = area / L
    return c, B, L, w


# --------------------------------------------------------------------------


def solve_frequency(design, mesh, dofmap, ops, bts, freq: float,
                    save_field: bool = False,
                    port_cache: Optional[dict] = None):
    """Assemble and solve at one frequency; return (S_raw, z0, ports, fields)."""
    k0 = 2.0 * math.pi * freq / c0
    eps, mu = _material_maps(design, mesh, freq)
    eps_of = lambda r: eps.get(r, 1.0 + 0j)
    mu_of = lambda r: mu.get(r, 1.0 + 0j)

    A = ops.operator(k0, eps, mu)
    A = bts.apply(A, k0, freq)

    port_sols: List[PortSolution] = []
    rhs_cols: List[np.ndarray] = []
    z0_list: List[complex] = []
    zport_list: List[complex] = []
    gammas: List[complex] = []
    proj_vecs: List[np.ndarray] = []

    for p in design.ports:
        idx = mesh.port_faces.get(p.name, np.zeros(0, np.int64))
        tris = mesh.surf_tris[idx]
        if len(tris) == 0:
            raise RuntimeError(f"port {p.name!r} selected no mesh triangles")
        if p.kind == "wave":
            ps = solve_port_modes(mesh, dofmap, tris, freq, eps_of, mu_of,
                                  n_modes=p.num_modes, name=p.name,
                                  integration_line=p.integration_line)
            port_sols.append(ps)
            for m in range(len(ps.modes)):
                md = ps.modes[m]
                v = ps.v(m)
                nz = np.nonzero(np.abs(v) > 0)[0]
                col = sp.csr_matrix((v[nz], (nz, np.zeros(len(nz), int))),
                                    shape=(dofmap.n_dof, 1))
                A = A + md.gamma * (col @ col.T)
                rhs = 2.0 * md.gamma * v
                rhs_cols.append(rhs)
                # The power-wave normalisation must use the *modal wave*
                # impedance: only that one satisfies Z ~ 1/gamma, which is
                # what makes the resulting S-matrix exactly reciprocal for a
                # complex-symmetric operator.  The line impedance (Zpv) is
                # applied afterwards as a proper renormalisation.
                z0_list.append(md.Z_wave)
                zport_list.append(md.Z_port)
                gammas.append(md.gamma)
                proj_vecs.append(v)
        else:                                   # lumped port
            c, B, L, w = _lumped_mode(mesh, dofmap, tris, p.direction)
            Zs = complex(p.impedance) * w / L
            y = eta0 / Zs
            A = A + (1j * k0 * y) * B
            v = np.asarray(B @ c).ravel()
            rhs_cols.append(2.0 * 1j * k0 * y * v)
            z0_list.append(complex(p.impedance))
            zport_list.append(complex(p.impedance))
            gammas.append(1j * k0)
            proj_vecs.append(v)
            ps = PortSolution(p.name, freq, [], np.sort(tris, axis=1),
                              np.zeros(0, np.int64), B,
                              np.array([0.0, 0.0, 1.0]), 0.0, 1)
            port_sols.append(ps)

    n_exc = len(rhs_cols)
    Bmat = np.stack(rhs_cols, axis=1)
    Ar, Br, keep = constrain(A.tocsr(), Bmat, bts.pec_dofs)
    solver = LinearSolver(Ar, design.config.solver)
    Xr = solver.solve(Br)
    X = expand(Xr, keep, dofmap.n_dof)

    P = np.stack(proj_vecs, axis=1)             # (n_dof, n_exc)
    amp = P.T @ X                               # amp[i, j] = <E_j, e_i>
    S = amp.copy()
    S -= np.eye(n_exc)                          # subtract the incident wave
    z0 = np.asarray(z0_list, complex)
    zport = np.asarray(zport_list, complex)
    sq = np.sqrt(z0)
    S = S * (sq[None, :] / sq[:, None])         # power-wave normalisation

    fields = {}
    if save_field:
        for j in range(n_exc):
            fields[j] = FieldSolution(mesh, dofmap, X[:, j], freq,
                                      eps_of, mu_of)
    return S, z0, port_sols, fields, np.asarray(gammas, complex), zport


# --------------------------------------------------------------------------


def solve_design(design, setup: Optional[str] = None,
                 sweep: Optional[str] = None, backend: str = "auto",
                 save_fields: bool = False, adaptive: Optional[bool] = None,
                 progress: bool = True, cancel=None) -> Solution:
    """Run a complete analysis (adaptive passes + frequency sweep)."""
    from .control import checkpoint
    checkpoint(cancel)
    t0 = time.perf_counter()
    errs = design.validate()
    if errs:
        raise ValueError("model validation failed:\n  - " + "\n  - ".join(errs))
    st = design.get_setup(setup)
    use_adaptive = design.config.adaptive.enabled if adaptive is None else adaptive

    from .adaptive import adaptive_solve
    mesh, dofmap, ops, bts, history = adaptive_solve(
        design, st, backend=backend, enabled=use_adaptive, cancel=cancel)

    # frequency list
    if sweep is None:
        sweeps = st.sweeps
    else:
        sweeps = [s for s in st.sweeps if s.name == sweep]
        if not sweeps:
            raise KeyError(f"no sweep named {sweep!r} in setup {st.name!r}")
    freqs = np.unique(np.concatenate([s.frequencies() for s in sweeps])) \
        if sweeps else np.array([st.frequency])

    sol = Solution(design, mesh, dofmap, freqs, convergence=history)
    n_exc = design.n_excitations
    Sall = np.zeros((len(freqs), n_exc, n_exc), complex)
    Z0all = np.zeros((len(freqs), n_exc), complex)
    Gall = np.zeros((len(freqs), n_exc), complex)
    Zportall = np.zeros((len(freqs), n_exc), complex)

    want_fields = save_fields or any(s.save_fields for s in sweeps)
    with timed(log, f"frequency sweep ({len(freqs)} point(s))"):
        for i, f in enumerate(freqs):
            checkpoint(cancel)
            S, z0, psols, flds, gam, zport = solve_frequency(
                design, mesh, dofmap, ops, bts, float(f),
                save_field=want_fields)
            Sall[i] = S
            Z0all[i] = z0
            Gall[i] = gam
            Zportall[i] = zport
            sol.ports[float(f)] = psols
            for j, fs in flds.items():
                sol.fields[(float(f), j)] = fs
            if progress:
                log.info("  f = %10.6f GHz   |S11| = %7.4f  |S21| = %7.4f",
                         f / 1e9, abs(S[0, 0]),
                         abs(S[min(1, n_exc - 1), 0]))

    names = design.excitation_names()
    # The reported reference impedance is the *port* impedance (the line
    # impedance Zpv when an integration line defines one, otherwise the modal
    # wave impedance).  The S-matrix itself is power-normalised against the
    # port's own mode, so it is already referenced to that impedance -- only
    # the sqrt scaling inside solve_frequency uses Z_wave, because that is the
    # quantity satisfying Z ~ 1/gamma that keeps S exactly reciprocal.
    sp_obj = SParameters(freqs, Sall, Zportall, names)

    # de-embedding
    d = []
    for p in design.ports:
        for _ in range(getattr(p, "num_modes", 1)):
            d.append(getattr(p, "deembed", 0.0))
    d = np.asarray(d, float)
    if np.any(d != 0.0):
        sp_obj = sp_obj.deembed(Gall, d)


    # renormalisation
    target = [p.renormalize_z for p in design.ports
              for _ in range(getattr(p, "num_modes", 1))]
    if any(t is not None for t in target):
        zt = np.array([[t if t is not None else Zportall[k, i]
                        for i, t in enumerate(target)]
                       for k in range(len(freqs))], dtype=complex)
        sp_obj = sp_obj.renormalize(zt)

    checkpoint(cancel)
    sol.sparams = sp_obj
    sol.runtime = time.perf_counter() - t0
    log.info("solve complete in %.2f s", sol.runtime)
    return sol


__all__ = ["Solution", "solve_design", "solve_frequency"]
