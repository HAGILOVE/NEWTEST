"""
Sparse linear-algebra backends.

The complex, symmetric (not Hermitian) systems produced by a driven full-wave
FEM are solved either

* **directly**, with a sparse LU that is factorised once and re-used for every
  excitation at that frequency (the usual win: N excitations cost one
  factorisation), or
* **iteratively**, with GMRES/BiCGSTAB preconditioned by an incomplete LU --
  the memory-bounded path for large models.

``auto`` picks direct below :attr:`SolverSettings.direct_threshold_dof`.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from ..core.logging import get_logger

log = get_logger("fem.linalg")


def _pardiso():
    """MKL PARDISO (``pip install pypardiso``) if present and not disabled.

    A 3-D full-wave matrix factorises one to two orders of magnitude faster
    with a multi-threaded nested-dissection solver than with SuperLU, which is
    single-threaded with a weak ordering: 35k unknowns take ~2 s instead of
    minutes. ``AETHER_LINEAR_BACKEND=superlu`` turns it off."""
    if os.environ.get("AETHER_LINEAR_BACKEND", "").lower() == "superlu":
        return None
    try:
        import pypardiso
        return pypardiso
    except Exception:                                   # noqa: BLE001
        return None


class LinearSolver:
    """Factorised operator supporting multiple right-hand sides."""

    def __init__(self, A: sp.spmatrix, settings=None):
        from ..core.config import SolverSettings
        self.s = settings or SolverSettings()
        self.A = A.tocsc()
        self.n = A.shape[0]
        self.mode = self._choose()
        self._lu = None
        self._M = None
        self._pd = None
        self.backend = ""
        self.factor_time = 0.0
        self._prepare()

    def _choose(self) -> str:
        want = self.s.linear_solver
        if want == "auto":
            return "direct" if self.n <= self.s.direct_threshold_dof else "iterative"
        return want

    def _prepare(self):
        t0 = time.perf_counter()
        if self.mode == "direct":
            pd = _pardiso() if self.n >= 3000 else None
            if pd is not None:
                try:
                    # PARDISO is real-valued: solve [[Re,-Im],[Im,Re]] [xr;xi]
                    # = [br;bi], which is exactly the complex system
                    A = self.A.tocsr()
                    R = sp.bmat([[A.real, -A.imag], [A.imag, A.real]],
                                format="csr")
                    ps = pd.PyPardisoSolver()
                    ps.factorize(R)
                    self._pd = (ps, R)
                    self.backend = "pardiso"
                except Exception as exc:                 # noqa: BLE001
                    log.warning("PARDISO unavailable (%s); using SuperLU", exc)
                    self._pd = None
        if self.mode == "direct" and self._pd is None:
            try:
                # The FEM matrix has a symmetric *pattern*, so the column
                # ordering must come from A + A^T. COLAMD orders for A^T A and
                # is far worse here: 38 s vs 0.45 s at 8.7k unknowns, with
                # twice the fill.
                self._lu = spla.splu(self.A,
                                     permc_spec="MMD_AT_PLUS_A",
                                     diag_pivot_thresh=0.1,
                                     options=dict(SymmetricMode=True))
                self.backend = "superlu"
            except (RuntimeError, MemoryError) as exc:
                log.warning("direct factorisation failed (%s); "
                            "falling back to GMRES+ILU", exc)
                self.mode = "iterative"
        if self.mode == "iterative":
            if self.s.preconditioner == "ilu":
                try:
                    ilu = spla.spilu(self.A, drop_tol=self.s.ilu_drop_tol,
                                     fill_factor=self.s.ilu_fill_factor)
                    self._M = spla.LinearOperator(self.A.shape, ilu.solve,
                                                  dtype=self.A.dtype)
                except (RuntimeError, MemoryError) as exc:
                    log.warning("ILU failed (%s); using Jacobi", exc)
                    self._M = _jacobi(self.A)
            elif self.s.preconditioner == "jacobi":
                self._M = _jacobi(self.A)
        self.factor_time = time.perf_counter() - t0
        log.info("linear solver ready [%s%s, n=%d, %.2fs]", self.mode,
                 f"/{self.backend}" if self.backend else "", self.n,
                 self.factor_time)

    # ------------------------------------------------------------------
    def solve(self, b: np.ndarray) -> np.ndarray:
        """Solve for one or many right-hand sides (``b`` shaped (n,) or (n,k))."""
        single = b.ndim == 1
        B = b.reshape(-1, 1) if single else b
        X = np.empty((self.n, B.shape[1]), dtype=complex)
        if self.mode == "direct" and self._pd is not None:
            ps, R = self._pd
            rhs = np.vstack([B.real, B.imag])
            x = np.asarray(ps.solve(R, rhs)).reshape(2 * self.n, -1)
            X = x[:self.n] + 1j * x[self.n:]
        elif self.mode == "direct":
            for j in range(B.shape[1]):
                X[:, j] = self._lu.solve(B[:, j])
        else:
            for j in range(B.shape[1]):
                x, info = _iterative(self.A, B[:, j], self._M, self.s)
                if info != 0:
                    log.warning("iterative solver did not converge "
                                "(info=%d) for RHS %d", info, j)
                X[:, j] = x
        return X[:, 0] if single else X

    def __call__(self, b):
        return self.solve(b)


def _jacobi(A: sp.spmatrix):
    d = A.diagonal()
    d = np.where(np.abs(d) < 1e-300, 1.0, d)
    return spla.LinearOperator(A.shape, lambda x: x / d, dtype=A.dtype)


def _iterative(A, b, M, s):
    kw = dict(rtol=s.tol, maxiter=s.maxiter, M=M)
    try:
        if s.iterative == "bicgstab":
            return spla.bicgstab(A, b, **kw)
        return spla.gmres(A, b, restart=s.restart, **kw)
    except TypeError:                      # older SciPy uses `tol=`
        kw.pop("rtol"); kw["tol"] = s.tol
        if s.iterative == "bicgstab":
            return spla.bicgstab(A, b, **kw)
        return spla.gmres(A, b, restart=s.restart, **kw)


def solve_eigen(A: sp.spmatrix, B: sp.spmatrix, k: int = 6,
                sigma: float = 0.0, tol: float = 0.0):
    """Shift-invert generalised eigenproblem ``A x = lambda B x``."""
    n = A.shape[0]
    k = min(k, max(n - 3, 1))
    vals, vecs = spla.eigs(A.astype(complex), k=k, M=B.astype(complex),
                           sigma=sigma, which="LM", tol=tol)
    order = np.argsort(vals.real)
    return vals[order], vecs[:, order]


__all__ = ["LinearSolver", "solve_eigen"]
