"""
Eigenmode solver: resonant frequencies, Q and mode fields.

A closed (or weakly open) structure has no ports, so instead of driving it the
source-free operator is solved for its resonances::

    ( S(1/mu) - k^2 T(eps_c) + j k Y_b B ) x = 0 ,       k = 2 pi f / c0

``k`` is complex for a lossy structure; with the ``exp(+j omega t)``
convention a decaying mode has ``Im f > 0`` and ``Q = Re f / (2 Im f)``.

Two practical problems are solved explicitly rather than hoped away:

*The null space.*  Every gradient of a nodal function is curl-free, so the
curl-curl operator has as many zero eigenvalues as the mesh has interior
nodes.  A shift-invert Arnoldi iteration started anywhere near the low end
of the spectrum fills its Krylov space with these.  The operator applied
here is therefore wrapped in the T-orthogonal projector that removes the
discrete gradients, ``P = I - G (G^T T G)^-1 G^T T``; physical modes satisfy
``G^T T x = 0`` and pass through unchanged while the whole null cluster maps
to zero.  No spurious "mode" at ``f = 0`` can come back.

*Frequency-dependent terms.*  Surface impedance / radiation boundaries enter
as ``j k Y B`` and dispersive materials change with ``f``, so the problem is
not a linear pencil in ``k^2``.  The linear pencil (terms frozen at the
frequency of interest) gives the starting point and each mode is then
polished by residual inverse iteration on the *true* operator.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from ..core.constants import c0
from ..core.logging import get_logger, timed
from .adaptive import element_error, remesh_from_error
from .assembly import assemble_regions
from .boundary import BoundaryTerms, expand
from .driver import Solution, _material_maps
from .elements import DofMap
from .fields import FieldSolution

log = get_logger("fem.eigen")


@dataclass
class EigenMode:
    """One resonance of the structure."""
    index: int
    frequency: complex              # Hz; the imaginary part is the loss
    q: float                        # quality factor (inf when lossless)
    residual: float                 # ||F(f) x|| / ||F_ref x|| after polishing
    iterations: int = 0

    @property
    def f(self) -> float:
        return float(self.frequency.real)

    @property
    def converged(self) -> bool:
        return self.residual < 1e-4

    @property
    def damping(self) -> float:
        """Decay rate ``Im(omega)`` [1/s]."""
        return 2.0 * math.pi * float(self.frequency.imag)


# --------------------------------------------------------------------------


def gradient_matrix(mesh, dofmap: DofMap, pec_dofs: np.ndarray) -> sp.csc_matrix:
    """
    Discrete gradient: columns span every curl-free field the basis contains.

    Nodes on a PEC surface are excluded (a tangential field cannot be the
    gradient of a function that is non-zero there), as are PEC edge gradients.
    """
    E = mesh.n_edges
    edges = mesh.edges
    pec_e = pec_dofs[pec_dofs < E]
    on_pec = np.zeros(mesh.n_nodes, bool)
    if len(pec_e):
        on_pec[edges[pec_e].ravel()] = True
    inode = np.nonzero(~on_pec)[0]
    col = -np.ones(mesh.n_nodes, np.int64)
    col[inode] = np.arange(len(inode))
    lo, hi = col[edges[:, 0]], col[edges[:, 1]]
    ee = np.arange(E)
    rows = np.concatenate([ee[lo >= 0], ee[hi >= 0]])
    cols = np.concatenate([lo[lo >= 0], hi[hi >= 0]])
    vals = np.concatenate([-np.ones((lo >= 0).sum()), np.ones((hi >= 0).sum())])
    nc = len(inode)
    if dofmap.order >= 2:
        free = np.ones(E, bool)
        free[pec_e] = False
        fe = np.nonzero(free)[0]
        rows = np.concatenate([rows, E + fe])
        cols = np.concatenate([cols, nc + np.arange(len(fe))])
        vals = np.concatenate([vals, np.ones(len(fe))])
        nc += len(fe)
    return sp.coo_matrix((vals, (rows, cols)),
                         shape=(dofmap.n_dof, nc)).tocsc()


def _bsum(bts: BoundaryTerms, n: int, k0: complex, freq: float):
    return bts.apply(sp.csr_matrix((n, n), dtype=complex), k0, freq)


def _freq_dependent(design, mesh, bts: BoundaryTerms, f: float) -> bool:
    """True when the operator is not a linear pencil in k^2."""
    if bts.matrices:
        return True
    for rid, name in mesh.region_names.items():
        m = next((s.material for s in design.solids if s.name == name), None)
        if m is None:
            continue
        if (abs(m.eps_c(f) - m.eps_c(1.7 * f)) > 1e-9 * abs(m.eps_c(f))
                or abs(m.mu_c(f) - m.mu_c(1.7 * f)) > 1e-9 * abs(m.mu_c(f))):
            return True
    return False


def _f_from_lambda(lam: complex) -> complex:
    k = np.sqrt(complex(lam))
    if k.real < 0:
        k = -k
    return complex(k * c0 / (2.0 * math.pi))


def _q(f: complex) -> float:
    if f.imag <= 1e-12 * max(abs(f.real), 1e-300):
        return float("inf")
    return float(f.real / (2.0 * f.imag))


# --------------------------------------------------------------------------


def _soft_pec_dofs(design, mesh, dm, bts) -> np.ndarray:
    """DOFs under low-loss wall boundaries (surface impedance / finite
    conductivity); to first order these walls are perfect conductors."""
    tris = []
    for b in design.boundaries:
        if b.btype in ("finite_cond", "impedance"):
            idx = mesh.bc_faces.get(b.name, np.zeros(0, np.int64))
            if len(idx):
                tris.append(mesh.surf_tris[idx])
    if not tris:
        return np.zeros(0, np.int64)
    return dm.dofs_on_triangles(np.vstack(tris))


def _linear_modes(design, mesh, dm, ops, bts, n_want, fmin, f_eval,
                  sigma_f, cancel, frozen_walls: bool):
    """
    Lossless-wall pencil + gradient projector.

    Returns ``(lambdas, X_full)``.  With *frozen_walls* the wall boundaries
    are replaced by perfect conductors and every other boundary term is
    dropped (natural condition): a first estimate for the polishing step,
    which owns the real boundary physics.  Without them the pencil is the
    exact operator frozen at *f_eval*.
    """
    from .control import checkpoint
    n = dm.n_dof
    eps, mu = _material_maps(design, mesh, f_eval)
    k_eval = 2.0 * math.pi * f_eval / c0
    S = ops.stiffness(mu)
    T = ops.mass(eps)
    if frozen_walls:
        A1 = S.tocsr()
        pec = np.unique(np.concatenate([bts.pec_dofs,
                                        _soft_pec_dofs(design, mesh, dm, bts)]))
    else:
        A1 = (S + _bsum(bts, n, k_eval, f_eval)).tocsr()
        pec = bts.pec_dofs

    keep = np.ones(n, bool)
    keep[pec] = False
    idx = np.nonzero(keep)[0]
    Ar = A1[idx][:, idx].tocsc()
    Tr = T.tocsr()[idx][:, idx].tocsc()

    G = gradient_matrix(mesh, dm, pec).tocsr()[idx].tocsc()
    keepcols = np.asarray(abs(G).sum(axis=0)).ravel() > 0
    G = G[:, np.nonzero(keepcols)[0]]
    L = (G.T @ Tr @ G).tocsc()
    Llu = spla.splu(L)
    GT = G.T.tocsr()

    def project(v):
        w = Tr @ v
        return v - G @ Llu.solve(GT @ w)

    sigma = (2.0 * math.pi * sigma_f / c0) ** 2
    lu = spla.splu((Ar - sigma * Tr).tocsc())
    nr = Ar.shape[0]
    op = spla.LinearOperator((nr, nr), dtype=complex,
                             matvec=lambda v: project(lu.solve(np.asarray(v).ravel())))
    want = n_want + 6
    for attempt in range(3):
        checkpoint(cancel)
        k = min(want, nr - 2)
        lam, vec = spla.eigs(Ar, k=k, M=Tr, sigma=sigma, which="LM",
                             OPinv=op, tol=1e-11, maxiter=4000)
        f = np.array([_f_from_lambda(l) for l in lam])
        ok = (f.real >= fmin * (1.0 - 1e-6)) & np.isfinite(f.real) & (f.real > 0)
        if ok.sum() >= n_want or k >= nr - 2:
            break
        want *= 2
    lam, vec, f = lam[ok], vec[:, ok], f[ok]
    order = np.argsort(f.real)[:n_want]
    lam, vec = lam[order], vec[:, order]
    X = np.zeros((n, vec.shape[1]), complex)
    X[idx, :] = vec
    return lam, X


def _polish(design, mesh, dm, ops, bts, f0: complex, xfull: np.ndarray,
            cancel, iters: int = 14, tol: float = 1e-10):
    """
    Residual inverse iteration on the full ``F(f) x = 0``.

    ``F`` is factorised once at the starting frequency; each step updates the
    eigenfrequency from the scalar equation ``w^T F(f) x = 0`` (secant) and the
    vector from the residual.  Returns ``(f, x, residual, iterations)``.
    """
    from .control import checkpoint
    n = dm.n_dof
    keep = np.ones(n, bool)
    keep[bts.pec_dofs] = False
    idx = np.nonzero(keep)[0]
    x0 = np.asarray(xfull)[idx].astype(complex)
    eps0, _ = _material_maps(design, mesh, max(float(f0.real), 1.0))
    Tr = ops.mass(eps0).tocsr()[idx][:, idx].tocsc()

    def F(fc: complex):
        k0 = 2.0 * math.pi * fc / c0
        fr = max(float(fc.real), 1.0)
        eps, mu = _material_maps(design, mesh, fr)
        A = ops.operator(k0, eps, mu)
        A = bts.apply(A, k0, fr)
        return A.tocsr()[idx][:, idx].tocsc()

    F0 = F(f0)
    lu = spla.splu(F0)
    w = Tr @ x0
    x = x0.copy()
    f = complex(f0)
    scale = max(float(np.linalg.norm(F0 @ x)), 1e-300)
    res = np.inf
    for it in range(1, iters + 1):
        checkpoint(cancel)
        g = lambda fc: complex(w @ (F(fc) @ x))
        # secant on g(f) = 0, seeded by a small complex step
        fa, fb = f, f * (1.0 + 1e-4)
        ga, gb = g(fa), g(fb)
        for _ in range(8):
            if gb == ga:
                break
            fc = fb - gb * (fb - fa) / (gb - ga)
            fa, ga = fb, gb
            fb, gb = fc, g(fc)
            if abs(fb - fa) < 1e-13 * abs(fb):
                break
        f_new = fb
        r = F(f_new) @ x
        res = float(np.linalg.norm(r)) / scale
        x = x - lu.solve(r)
        nrm = complex(w @ x)
        if abs(nrm) > 0:
            x = x / nrm * complex(w @ x0)
        moved = abs(f_new - f) / abs(f_new)
        f = f_new
        if moved < tol and res < 1e-6:
            break
    nrm = complex(x @ (Tr @ x))
    if abs(nrm) > 0:
        x = x / np.sqrt(nrm)
    xf = np.zeros(n, complex)
    xf[idx] = x
    return f, xf, res, it


# --------------------------------------------------------------------------


def _solve_modes(design, setup, mesh, dm, ops, bts, cancel):
    n_modes = max(int(setup.n_modes), 1)
    fmin = max(float(setup.min_frequency), 0.0)
    lo, hi = mesh.bounding_box()
    diag = float(np.linalg.norm(hi - lo))
    eps_max = 1.0
    for rid, name in mesh.region_names.items():
        m = next((s.material for s in design.solids if s.name == name), None)
        if m is not None and not m.is_pec:
            eps_max = max(eps_max, abs(m.eps_c(1e9) * m.mu_c(1e9)))
    # a frequency safely below every mode of a body of this size
    f_floor = 0.1 * c0 / (2.0 * diag * math.sqrt(eps_max))
    sigma_f = max(fmin * 0.999, f_floor)
    f_eval = max(fmin, 2.5 * f_floor)

    # boundaries with surface terms make the problem nonlinear in k: find
    # lossless-wall modes first, then polish each on the real operator
    f_probe = max(fmin, 2.5 * f_floor)
    dependent = _freq_dependent(design, mesh, bts, f_probe)
    lam, X = _linear_modes(design, mesh, dm, ops, bts, n_modes, fmin, f_eval,
                           sigma_f, cancel, frozen_walls=bool(bts.matrices))
    if len(lam) == 0:
        raise RuntimeError("no resonances found above the minimum frequency; "
                           "lower it or check the boundary conditions")
    f = np.array([_f_from_lambda(l) for l in lam])
    if dependent and not bts.matrices:
        # dispersive materials only: redo the linear solve at the real mode
        lam, X = _linear_modes(design, mesh, dm, ops, bts, n_modes, fmin,
                               float(f[0].real),
                               max(fmin * 0.999, 0.5 * float(f[0].real)),
                               cancel, frozen_walls=False)
        f = np.array([_f_from_lambda(l) for l in lam])
    modes: List[EigenMode] = []
    xs = []
    for j in range(len(f)):
        fj, xj, res, its = complex(f[j]), X[:, j], 0.0, 0
        if dependent:
            fj, xj, res, its = _polish(design, mesh, dm, ops, bts, fj, xj,
                                       cancel)
            if res > 1e-4:
                log.warning("mode %d did not fully converge on the lossy "
                            "operator (residual %.1e)", j + 1, res)
        modes.append(EigenMode(j, fj, _q(fj), res, its))
        xs.append(xj)
    order = np.argsort([m.f for m in modes])
    modes = [EigenMode(i, modes[o].frequency, modes[o].q, modes[o].residual,
                       modes[o].iterations) for i, o in enumerate(order)]
    xs = [xs[o] for o in order]
    return modes, xs


def solve_eigenmode(design, setup: Optional[str] = None, backend: str = "auto",
                    save_fields: bool = True, adaptive: Optional[bool] = None,
                    progress: bool = True, cancel=None) -> Solution:
    """Adaptive eigenmode analysis; returns a :class:`Solution` with ``modes``."""
    from .control import checkpoint
    checkpoint(cancel)
    t0 = time.perf_counter()
    errs = design.validate()
    if errs:
        raise ValueError("model validation failed:\n  - " + "\n  - ".join(errs))
    st = design.get_setup(setup)
    use_adaptive = design.config.adaptive.enabled if adaptive is None else adaptive
    order = st.basis_order
    f_seed = st.frequency
    if design.mesh is not None and not use_adaptive:
        mesh = design.mesh
    else:
        mesh = design.generate_mesh(f_seed, force=True, backend=backend)

    history: List[dict] = []
    prev: Optional[np.ndarray] = None
    converged = 0
    for p in range(1, max(int(st.max_passes), 1) + 1):
        checkpoint(cancel)
        dm = DofMap(mesh, order)
        ops = assemble_regions(mesh, order, dm)
        bts = BoundaryTerms(mesh, dm, design)
        with timed(log, f"eigenmode pass {p} [{mesh.n_tets} tets, {dm.n_dof} DOF]"):
            modes, xs = _solve_modes(design, st, mesh, dm, ops, bts, cancel)
        fr = np.array([m.frequency for m in modes])
        df = None
        if prev is not None and len(prev) == len(fr):
            df = float(np.max(np.abs(fr - prev) / np.abs(fr)))
        history.append({"pass": p, "tets": mesh.n_tets, "dof": dm.n_dof,
                        "delta_s": df, "delta_f": df,
                        "f0": float(fr[0].real)})
        log.info("eigenmode pass %d: %d tets, %d DOF, f1 = %.6f GHz, "
                 "df = %s", p, mesh.n_tets, dm.n_dof, fr[0].real / 1e9,
                 "--" if df is None else f"{df:.5f}")
        prev = fr
        if df is not None and df <= st.delta_f and p >= st.min_passes:
            converged += 1
            if converged >= max(int(st.min_converged), design.config.adaptive.min_converged_passes):
                break
        else:
            converged = 0
        if not use_adaptive or p >= st.max_passes:
            if use_adaptive and p >= st.max_passes:
                log.warning("eigenmode adaptive limit reached (last df = %s)", df)
            break
        # refine where any mode is poorly resolved
        err = np.zeros(mesh.n_tets)
        for m, x in zip(modes, xs):
            fm = max(m.f, 1.0)
            _, mu = _material_maps(design, mesh, fm)
            e = element_error(mesh, dm, x, fm, lambda r: mu.get(r, 1.0 + 0j))
            err = np.maximum(err, e)
        good = [m.f for m in modes if m.f > 0 and m.converged]
        if not good:
            raise RuntimeError("eigenmode refinement stopped: no mode "
                               "converged on this mesh")
        mesh = remesh_from_error(design, mesh, err, max(good), backend, p,
                                 st.refinement)

    sol = Solution(design, mesh, dm, np.array([m.f for m in modes]),
                   convergence=history)
    sol.modes = modes
    sol.solved = np.ones(len(modes), bool)
    if save_fields:
        for m, x in zip(modes, xs):
            fm = max(m.f, 1.0)
            eps, mu = _material_maps(design, mesh, fm)
            sol.fields[(m.f, m.index)] = FieldSolution(
                mesh, dm, x, fm,
                lambda r, e=eps: e.get(r, 1.0 + 0j),
                lambda r, u=mu: u.get(r, 1.0 + 0j))
    sol.runtime = time.perf_counter() - t0
    if progress:
        for m in modes:
            log.info("  mode %d: f = %.6f GHz   Q = %s", m.index + 1,
                     m.f / 1e9, "inf" if math.isinf(m.q) else f"{m.q:.4g}")
    return sol


__all__ = ["EigenMode", "solve_eigenmode", "gradient_matrix"]
