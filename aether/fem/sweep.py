"""
Frequency-sweep strategies: discrete, interpolating and fast.

``discrete``
    one full solve per requested frequency (the reference answer).

``interpolating``
    full solves at adaptively chosen frequencies only; a common-denominator
    rational function (set-valued AAA, see :mod:`aether.fem.rational`) is fitted
    through them and evaluated on the requested grid.  New frequencies are
    added until an interpolant built *without* the newest sample predicts it to
    within the sweep tolerance -- the same "does the model already know the
    answer here?" test Warps uses.

``fast``
    a reduced-basis (projection) model.  The field solutions at a few
    frequencies span a small subspace; at every other frequency the *full*
    operator is assembled (cheap -- no factorisation) and projected onto that
    subspace, so a point costs a small dense solve instead of a sparse LU.
    The subspace is grown at the frequency whose residual is largest until a
    probe solve there agrees with the reduced model.

Both fall back to ``discrete`` when the grid is too small for them to save
anything, so the choice never costs accuracy on short sweeps.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np

from ..core.logging import get_logger
from .boundary import expand
from .driver import (FieldSolution, PortData, assemble_system,
                     compute_port_data, extract_sparams, solve_frequency)
from .linalg import LinearSolver
from .rational import aaa_fit

log = get_logger("fem.sweep")

MIN_GRID = 7            # below this an adaptive sweep cannot beat discrete


@dataclass
class SweepResult:
    """Per-frequency data of one sweep, in ascending frequency order."""
    freqs: np.ndarray
    S: np.ndarray                      # (nf, n, n) raw power-normalised
    gamma: np.ndarray                  # (nf, n)
    zport: np.ndarray                  # (nf, n)
    solved: np.ndarray                 # (nf,) bool: a real FEM solve exists
    ports: Dict[float, list] = field(default_factory=dict)
    fields: Dict[tuple, object] = field(default_factory=dict)
    info: dict = field(default_factory=dict)


# --------------------------------------------------------------------------


def run_sweep(design, mesh, dofmap, ops, bts, freqs, kind: str = "discrete",
              tol: Optional[float] = None, max_points: Optional[int] = None,
              want_fields: bool = False, cancel=None,
              progress: bool = True) -> SweepResult:
    """Evaluate the S-matrix on *freqs* with the requested strategy."""
    if kind not in ("discrete", "fast", "interpolating"):
        raise ValueError(f"unknown sweep kind {kind!r}")
    freqs = np.unique(np.asarray(freqs, float))
    cfg = design.config.sweep
    tol = cfg.interp_tol if tol is None else float(tol)
    max_points = int(cfg.interp_max_points if max_points is None else max_points)
    t0 = time.perf_counter()
    n_exc = design.n_excitations
    if kind != "discrete" and (len(freqs) < MIN_GRID or n_exc == 0):
        log.info("sweep of %d point(s) is too short for a %s sweep; "
                 "solving every point", len(freqs), kind)
        kind_used = "discrete"
    else:
        kind_used = kind
    if kind_used == "discrete":
        res = _discrete(design, mesh, dofmap, ops, bts, freqs, want_fields,
                        cancel, progress)
    elif kind_used == "interpolating":
        res = _interpolating(design, mesh, dofmap, ops, bts, freqs, tol,
                             max_points, want_fields, cancel, progress)
    else:
        res = _fast(design, mesh, dofmap, ops, bts, freqs, tol, max_points,
                    want_fields, cancel, progress)
    res.info.update(requested=kind, kind=kind_used, points=int(len(freqs)),
                    solved=int(res.solved.sum()),
                    seconds=time.perf_counter() - t0, tolerance=tol)
    return res


def _new(design, freqs) -> SweepResult:
    n = design.n_excitations
    nf = len(freqs)
    return SweepResult(freqs, np.zeros((nf, n, n), complex),
                       np.zeros((nf, n), complex), np.zeros((nf, n), complex),
                       np.zeros(nf, bool))


def _check(cancel):
    from .control import checkpoint
    checkpoint(cancel)


#: Called with ``(result, index)`` after every full solve, so a caller can show
#: the points that exist so far while the rest are still being computed.
POINT_HOOK = None


def _full_solve(res, i, design, mesh, dofmap, ops, bts, f, want_fields):
    S, z0, psols, flds, gam, zport = solve_frequency(
        design, mesh, dofmap, ops, bts, float(f), save_field=want_fields)
    res.S[i], res.gamma[i], res.zport[i] = S, gam, zport
    res.solved[i] = True
    res.ports[float(f)] = psols
    for j, fs in flds.items():
        res.fields[(float(f), j)] = fs
    if POINT_HOOK is not None:
        try:
            POINT_HOOK(res, i)
        except Exception:                                   # noqa: BLE001
            log.debug("partial-result hook failed", exc_info=True)
    return S


def _log_point(f, S, n_exc, tag=""):
    log.info("  f = %10.6f GHz   |S11| = %7.4f  |S21| = %7.4f %s",
             f / 1e9, abs(S[0, 0]), abs(S[min(1, n_exc - 1), 0]), tag)


# --------------------------------------------------------------------------


def _discrete(design, mesh, dofmap, ops, bts, freqs, want_fields, cancel,
              progress) -> SweepResult:
    res = _new(design, freqs)
    n_exc = design.n_excitations
    for i, f in enumerate(freqs):
        _check(cancel)
        S = _full_solve(res, i, design, mesh, dofmap, ops, bts, f, want_fields)
        if progress:
            _log_point(f, S, n_exc)
    return res


# --------------------------------------------------------------------------
# interpolating
# --------------------------------------------------------------------------


def _pack(res: SweepResult, idx) -> np.ndarray:
    """Columns fitted by the interpolant: S entries, gamma^2 and Z_port."""
    idx = np.asarray(idx)
    n = res.S.shape[1]
    return np.concatenate([res.S[idx].reshape(len(idx), n * n),
                           res.gamma[idx] ** 2, res.zport[idx]], axis=1)


def _gamma_from_square(g2: np.ndarray) -> np.ndarray:
    """
    ``gamma`` (``e^{-gamma z}``, so ``Re >= 0`` and ``Im = beta >= 0``) from
    ``gamma^2``.  The principal root is not enough: a propagating mode has
    ``gamma^2 = -beta^2`` on the negative real axis, the root's branch cut, so
    a rounding-level imaginary part of either sign would flip ``beta``.
    """
    g = np.sqrt(np.asarray(g2, complex))
    g = np.where(g.real < 0, -g, g)
    flip = (np.abs(g.real) <= 1e-9 * np.abs(g.imag)) & (g.imag < 0)
    return np.where(flip, -g, g)


def _unpack(res: SweepResult, i, row):
    n = res.S.shape[1]
    res.S[i] = row[:n * n].reshape(n, n)
    res.gamma[i] = _gamma_from_square(row[n * n:n * n + n])
    res.zport[i] = row[n * n + n:]


def _fill_from_fit(res: SweepResult, fit, mask) -> None:
    rows = fit(res.freqs[mask])
    for i, row in zip(np.nonzero(mask)[0], rows):
        _unpack(res, i, row)


def _interpolating(design, mesh, dofmap, ops, bts, freqs, tol, max_points,
                   want_fields, cancel, progress) -> SweepResult:
    res = _new(design, freqs)
    n = len(freqs)
    n_exc = design.n_excitations
    limit = max(min(max_points, n), 5)
    ncols = n_exc * n_exc

    def solve(i, tag=""):
        _check(cancel)
        S = _full_solve(res, i, design, mesh, dofmap, ops, bts, freqs[i],
                        want_fields)
        if progress:
            _log_point(freqs[i], S, n_exc, tag)
        return S

    for i in sorted({0, n // 4, n // 2, (3 * n) // 4, n - 1}):
        solve(i, "[seed]")

    def predict(fit, i):
        return fit(freqs[i:i + 1])[0][:ncols].reshape(n_exc, n_exc)

    err_hist: List[float] = []
    smooth: set = set()          # (a, b) sample-index gaps the model has passed
    rounds = 0
    while True:
        rounds += 1
        done = np.nonzero(res.solved)[0]
        if len(done) >= limit:
            log.warning("interpolating sweep reached its %d-point limit "
                        "before meeting the %.2g tolerance", limit, tol)
            break
        gaps = [(int(a), int(b)) for a, b in zip(done[:-1], done[1:])
                if b - a > 1]
        if not gaps:
            break
        todo = [g for g in gaps if g not in smooth]
        fit = aaa_fit(freqs[done], _pack(res, done), tol=1e-11)
        worst = 0.0
        # 1. probe the midpoint of every gap not yet shown to be smooth: a
        #    model that predicts a sample it has never seen is a model that
        #    already describes that stretch of the band
        for a, b in todo:
            if int(res.solved.sum()) >= limit:
                break
            m = (a + b) // 2
            pred = predict(fit, m)
            e = float(np.max(np.abs(solve(m, "[probe]") - pred)))
            worst = max(worst, e)
            if e <= tol:
                smooth.update({(a, m), (m, b)})
        if todo:
            err_hist.append(worst)
        if worst > tol:
            continue
        # 2. every probe passed: confirm where the model moves fastest before
        #    trusting it across the gaps that were never sampled
        done = np.nonzero(res.solved)[0]
        free = np.nonzero(~res.solved)[0]
        if len(free) == 0:
            break
        fit = aaa_fit(freqs[done], _pack(res, done), tol=1e-11)
        left = np.clip(np.searchsorted(freqs[done], freqs[free]) - 1,
                       0, len(done) - 2)
        var = np.max(np.abs(fit(freqs[done[left + 1]])[:, :ncols]
                            - fit(freqs[done[left]])[:, :ncols]), axis=1)
        bad = 0.0
        for m in free[np.argsort(-var)][:3]:
            if int(res.solved.sum()) >= limit:
                break
            pred = predict(fit, int(m))
            bad = max(bad, float(np.max(np.abs(solve(int(m), "[verify]")
                                               - pred))))
        err_hist.append(bad)
        if bad <= tol:
            break
        smooth.clear()           # the model was wrong somewhere: re-probe all

    done = np.nonzero(res.solved)[0]
    fit = aaa_fit(freqs[done], _pack(res, done), tol=1e-11)
    _fill_from_fit(res, fit, ~res.solved)
    # evaluate the fit on the solved points too: its disagreement with the real
    # solves there is the honest measure of how well the model describes them
    back = fit(freqs[done])[:, :ncols].reshape(len(done), n_exc, n_exc)
    res.info.update(degree=int(fit.degree),
                    fit_residual=float(np.max(np.abs(back - res.S[done]))),
                    last_probe_error=float(err_hist[-1]) if err_hist else 0.0,
                    rounds=rounds)
    return res


# --------------------------------------------------------------------------
# fast (reduced basis)
# --------------------------------------------------------------------------


def _orthonormal_extend(V: Optional[np.ndarray], X: np.ndarray,
                        drop: float = 1e-10) -> np.ndarray:
    """Append the new directions in *X* to the orthonormal basis *V*."""
    if V is not None and V.shape[1]:
        X = X - V @ (V.conj().T @ X)
        X = X - V @ (V.conj().T @ X)               # re-orthogonalise
    U, s, _ = np.linalg.svd(X, full_matrices=False)
    keep = s > drop * max(float(s[0]), 1e-300) if len(s) else s > 0
    U = U[:, keep]
    return U if V is None else np.concatenate([V, U], axis=1)


def _fast(design, mesh, dofmap, ops, bts, freqs, tol, max_points, want_fields,
          cancel, progress) -> SweepResult:
    res = _new(design, freqs)
    n = len(freqs)
    n_exc = design.n_excitations
    limit = max(min(max_points, n), 4)
    pd_cache: Dict[int, PortData] = {}
    keep_idx = {}
    V: Optional[np.ndarray] = None

    def full(i, tag=""):
        """Full solve; returns the reduced-space solution used to grow V."""
        nonlocal V
        _check(cancel)
        Ar, Br, keep, pd = assemble_system(design, mesh, dofmap, ops, bts,
                                           float(freqs[i]), pd_cache.get(i))
        pd_cache[i] = pd
        keep_idx["k"] = keep
        Xr = LinearSolver(Ar, design.config.solver).solve(Br)
        X = expand(Xr, keep, dofmap.n_dof)
        S = extract_sparams(pd, X)
        res.S[i], res.gamma[i], res.zport[i] = S, pd.gammas, pd.zport
        res.solved[i] = True
        res.ports[float(freqs[i])] = pd.port_sols
        if want_fields:
            for j in range(n_exc):
                res.fields[(float(freqs[i]), j)] = FieldSolution(
                    mesh, dofmap, X[:, j], float(freqs[i]), pd.eps_of, pd.mu_of)
        V = _orthonormal_extend(V, Xr)
        if progress:
            _log_point(freqs[i], S, n_exc, tag)
        return S

    for i in sorted({0, n // 2, n - 1}):
        full(i, "[basis]")

    def reduced(i):
        """Reduced solve at index i -> (S, relative residual, pd)."""
        Ar, Br, keep, pd = assemble_system(design, mesh, dofmap, ops, bts,
                                           float(freqs[i]), pd_cache.get(i))
        pd_cache[i] = pd
        AV = Ar @ V
        Ared = V.conj().T @ AV
        y = np.linalg.solve(Ared, V.conj().T @ Br)
        r = Br - AV @ y
        bn = max(float(np.linalg.norm(Br)), 1e-300)
        X = expand(V @ y, keep, dofmap.n_dof)
        return extract_sparams(pd, X), float(np.linalg.norm(r)) / bn, pd, X

    probe_err = []
    hits = 0
    while True:
        free = np.nonzero(~res.solved)[0]
        if len(free) == 0:
            break
        resid = {}
        for i in free:
            _check(cancel)
            S, r, pd, X = reduced(i)
            res.S[i], res.gamma[i], res.zport[i] = S, pd.gammas, pd.zport
            resid[i] = r
        worst = max(resid, key=resid.get)
        if int(res.solved.sum()) >= limit:
            log.warning("fast sweep reached its %d-solve limit "
                        "(worst residual %.2e)", limit, resid[worst])
            break
        S_rom = res.S[worst].copy()
        S_full = full(worst, "[probe]")
        e = float(np.max(np.abs(S_full - S_rom)))
        probe_err.append(e)
        hits = hits + 1 if e <= tol else 0
        if hits >= 2:
            break
    # final pass so every unsolved point comes from the final basis
    for i in np.nonzero(~res.solved)[0]:
        S, r, pd, X = reduced(i)
        res.S[i], res.gamma[i], res.zport[i] = S, pd.gammas, pd.zport
        res.ports[float(freqs[i])] = pd.port_sols
        if want_fields:
            for j in range(n_exc):
                res.fields[(float(freqs[i]), j)] = FieldSolution(
                    mesh, dofmap, X[:, j], float(freqs[i]), pd.eps_of, pd.mu_of)
    res.info.update(basis=int(V.shape[1]),
                    last_probe_error=float(probe_err[-1]) if probe_err else 0.0)
    return res


__all__ = ["SweepResult", "run_sweep"]
