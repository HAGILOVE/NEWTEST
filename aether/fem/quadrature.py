"""
Gauss quadrature rules on the reference simplices, in barycentric form.

Weights are normalised to sum to 1, so an integral over a cell is

    I = |cell| * sum_q  w_q * f(lambda_q)

which keeps the assembly code free of Jacobian bookkeeping.  All rules are
standard (Keast for tetrahedra, Dunavant for triangles) and exact to the
stated polynomial degree.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Tuple

import numpy as np


def _perms4(vals):
    """All distinct permutations of a 4-tuple of barycentric values."""
    from itertools import permutations
    return sorted(set(permutations(vals)))


def _perms3(vals):
    from itertools import permutations
    return sorted(set(permutations(vals)))


@lru_cache(maxsize=None)
def tet_rule(degree: int) -> Tuple[np.ndarray, np.ndarray]:
    """Barycentric points (Nq,4) and weights (Nq,) exact to *degree*."""
    if degree <= 1:
        p = np.array([[0.25, 0.25, 0.25, 0.25]])
        w = np.array([1.0])
    elif degree == 2:
        a = 0.5854101966249685
        b = 0.1381966011250105
        p = np.array(_perms4((a, b, b, b)))
        w = np.full(4, 0.25)
    elif degree == 3:
        p = np.vstack([np.full((1, 4), 0.25),
                       np.array(_perms4((0.5, 1 / 6, 1 / 6, 1 / 6)))])
        w = np.array([-0.8] + [0.45] * 4)
    elif degree == 4:
        a2 = 0.7857142857142857
        b2 = 0.0714285714285714
        a3 = 0.1005964238332008
        b3 = 0.3994035761667992
        p = np.vstack([np.full((1, 4), 0.25),
                       np.array(_perms4((a2, b2, b2, b2))),
                       np.array(_perms4((a3, a3, b3, b3)))])
        w = np.array([-0.0131555555555556] + [0.0076222222222222] * 4
                     + [0.0248888888888889] * 6) * 6.0
    else:                                   # degree 5, 15 points (Keast)
        p = [np.full(4, 0.25)]
        w = [0.030283678097089]
        a = 0.0
        for pt in _perms4((0.7272727272727273, 0.0909090909090909,
                           0.0909090909090909, 0.0909090909090909)):
            p.append(np.array(pt)); w.append(0.011645249086029)
        for pt in _perms4((0.0665501535736643, 0.4334498464263357,
                           0.4334498464263357, 0.0665501535736643)):
            p.append(np.array(pt)); w.append(0.010949141561386)
        for pt in _perms4((0.0, 1 / 3, 1 / 3, 1 / 3)):
            p.append(np.array(pt)); w.append(0.006026785714286)
        p = np.array(p); w = np.array(w)
        w = w / w.sum()
    w = np.asarray(w, float)
    return np.ascontiguousarray(p, dtype=float), w / w.sum()


@lru_cache(maxsize=None)
def tri_rule(degree: int) -> Tuple[np.ndarray, np.ndarray]:
    """Barycentric points (Nq,3) and weights (Nq,) on the reference triangle."""
    if degree <= 1:
        p = np.array([[1 / 3, 1 / 3, 1 / 3]])
        w = np.array([1.0])
    elif degree == 2:
        p = np.array([[2 / 3, 1 / 6, 1 / 6], [1 / 6, 2 / 3, 1 / 6],
                      [1 / 6, 1 / 6, 2 / 3]])
        w = np.full(3, 1 / 3)
    elif degree == 3:
        p = np.array([[1 / 3, 1 / 3, 1 / 3], [0.6, 0.2, 0.2],
                      [0.2, 0.6, 0.2], [0.2, 0.2, 0.6]])
        w = np.array([-27 / 48, 25 / 48, 25 / 48, 25 / 48])
    elif degree == 4:
        a, b = 0.108103018168070, 0.445948490915965
        c, d = 0.816847572980459, 0.091576213509771
        p = np.array([[a, b, b], [b, a, b], [b, b, a],
                      [c, d, d], [d, c, d], [d, d, c]])
        w = np.array([0.223381589678011] * 3 + [0.109951743655322] * 3)
    else:
        a, b = 0.059715871789770, 0.470142064105115
        c, d = 0.797426985353087, 0.101286507323456
        p = np.array([[1 / 3, 1 / 3, 1 / 3],
                      [a, b, b], [b, a, b], [b, b, a],
                      [c, d, d], [d, c, d], [d, d, c]])
        w = np.array([0.225] + [0.132394152788506] * 3
                     + [0.125939180544827] * 3)
    w = np.asarray(w, float)
    return np.ascontiguousarray(p, float), w / w.sum()


def line_rule(n: int = 4) -> Tuple[np.ndarray, np.ndarray]:
    """Gauss-Legendre on [0,1]; used for integration lines (voltage)."""
    x, w = np.polynomial.legendre.leggauss(n)
    return 0.5 * (x + 1.0), 0.5 * w


__all__ = ["tet_rule", "tri_rule", "line_rule"]
