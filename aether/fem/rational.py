"""
Rational interpolation of frequency responses (set-valued AAA).

A driven FEM solve is expensive and the quantity it returns -- the S-matrix --
is a smooth, nearly rational function of frequency: a few resonances and a
propagation phase.  An *interpolating sweep* therefore solves at a handful of
frequencies and fits one rational function through all matrix entries at once
(the "set-valued" AAA algorithm of Nakatsukasa-Sete-Trefethen and
Lietaert et al.), sharing the support points and denominator across entries
so that every entry sees the same poles.

The fit is evaluated in barycentric form, which interpolates the support
samples exactly and stays well-conditioned on the real frequency axis.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class RationalFit:
    """Barycentric rational function ``r(x) = sum w_k f_k/(x-z_k) / sum w_k/(x-z_k)``."""
    z: np.ndarray            # support abscissae (m,)
    f: np.ndarray            # support values, normalised columns (m, q)
    w: np.ndarray            # barycentric weights (m,)
    scale: np.ndarray        # per-column scaling that was divided out (q,)
    x0: float                # abscissa normalisation: x = (freq - x0) / dx
    dx: float
    degree: int
    fit_error: float         # max normalised error on the fitted samples

    def __call__(self, freq) -> np.ndarray:
        """Evaluate at physical abscissae *freq*; returns shape (len(freq), q)."""
        x = (np.atleast_1d(np.asarray(freq, float)) - self.x0) / self.dx
        diff = x[:, None] - self.z[None, :]
        hit = np.abs(diff) == 0.0
        diff = np.where(hit, 1.0, diff)
        C = 1.0 / diff
        num = C @ (self.w[:, None] * self.f)
        den = C @ self.w
        out = np.empty_like(num)
        safe = np.abs(den) > 0
        out[safe] = num[safe] / den[safe, None]
        out[~safe] = np.nan
        rows = np.nonzero(hit.any(axis=1))[0]
        for r in rows:                      # exact interpolation at the support
            out[r] = self.f[np.argmax(hit[r])]
        return out * self.scale[None, :]


def aaa_fit(freq: np.ndarray, data: np.ndarray, tol: float = 1e-10,
            max_degree: Optional[int] = None) -> RationalFit:
    """
    Fit a common-denominator rational function to ``data[i, :] = F(freq[i])``.

    Parameters
    ----------
    freq : (M,) real abscissae (need not be sorted, must be distinct)
    data : (M, q) complex samples, one column per scalar quantity
    tol  : stop when the max normalised error on all samples is below this
    """
    freq = np.asarray(freq, float)
    F = np.asarray(data, complex)
    if F.ndim == 1:
        F = F[:, None]
    M, q = F.shape
    if M < 2:
        raise ValueError("need at least two samples to fit")
    x0 = 0.5 * (freq.min() + freq.max())
    dx = 0.5 * (freq.max() - freq.min()) or 1.0
    x = (freq - x0) / dx
    scale = np.max(np.abs(F), axis=0)
    scale = np.where(scale > 0, scale, 1.0)
    Fn = F / scale[None, :]

    mmax = min(M - 1, max_degree if max_degree else M - 1)
    mask = np.ones(M, bool)
    R = np.tile(Fn.mean(axis=0), (M, 1))
    J: list = []
    w = np.ones(1, complex)
    err = np.inf
    for _ in range(mmax + 1):
        res = np.max(np.abs(Fn - R), axis=1)
        res[~mask] = -1.0
        j = int(np.argmax(res))
        J.append(j)
        mask[j] = False
        zs, fs = x[J], Fn[J]
        rem = np.nonzero(mask)[0]
        if len(rem) == 0:
            w = np.ones(len(J), complex) / len(J)
            err = 0.0
            break
        C = 1.0 / (x[rem][:, None] - zs[None, :])
        A = np.concatenate([(Fn[rem, c][:, None] - fs[:, c][None, :]) * C
                            for c in range(q)], axis=0)
        if A.shape[0] < A.shape[1]:
            J.pop(); mask[j] = True
            break
        _, _, Vh = np.linalg.svd(A, full_matrices=False)
        w = np.conj(Vh[-1])
        N = C @ (w[:, None] * fs)
        D = C @ w
        R[rem] = N / D[:, None]
        R[J] = fs
        err = float(np.max(np.abs(Fn[rem] - R[rem])))
        if err <= tol or len(J) > mmax:
            break
    if len(J) != len(w):                       # stopped before a weight solve
        zs, fs = x[J], Fn[J]
        C = 1.0 / (x[mask][:, None] - zs[None, :])
        A = np.concatenate([(Fn[mask, c][:, None] - fs[:, c][None, :]) * C
                            for c in range(q)], axis=0)
        _, _, Vh = np.linalg.svd(A, full_matrices=False)
        w = np.conj(Vh[-1])
    return RationalFit(x[J].copy(), Fn[J].copy(), w, scale, x0, dx,
                       len(J) - 1, err)


__all__ = ["RationalFit", "aaa_fit"]
