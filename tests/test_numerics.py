"""Quadrature exactness and finite-element basis completeness."""
import itertools
from math import factorial

import numpy as np
import pytest

from aether.fem.elements import DofMap, tet_basis, tri_basis, tri_geometry
from aether.fem.quadrature import tet_rule, tri_rule
from aether.mesh.tetmesh import TetMesh

REF = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)


def _exact_simplex(alpha, dim):
    return (factorial(dim) * np.prod([factorial(a) for a in alpha])
            / factorial(dim + sum(alpha)))


@pytest.mark.parametrize("deg", [1, 2, 3, 4, 5])
def test_tet_quadrature_is_exact(deg):
    p, w = tet_rule(deg)
    for a in itertools.product(range(deg + 1), repeat=4):
        if sum(a) != deg:
            continue
        num = float((w * np.prod(p ** np.array(a), axis=1)).sum())
        assert num == pytest.approx(_exact_simplex(a, 3), abs=1e-12)


@pytest.mark.parametrize("deg", [1, 2, 3, 4, 5])
def test_tri_quadrature_is_exact(deg):
    p, w = tri_rule(deg)
    for a in itertools.product(range(deg + 1), repeat=3):
        if sum(a) != deg:
            continue
        num = float((w * np.prod(p ** np.array(a), axis=1)).sum())
        assert num == pytest.approx(_exact_simplex(a, 2), abs=1e-12)


def _ref_mesh():
    return TetMesh(REF.copy(), np.array([[0, 1, 2, 3]]))


def _mass(order, mesh, dm):
    p, w = tet_rule(5)
    M = np.zeros((6 if order == 1 else 20,) * 2)
    fp = dm.face_perm if order >= 2 else None
    for q in range(len(w)):
        N, _ = tet_basis(order, mesh.grads, p[q], fp)
        M += w[q] * mesh.volumes[0] * np.einsum("eia,eja->ij", N, N)
    return M


@pytest.mark.parametrize("order", [1, 2])
def test_mass_matrix_is_positive_definite(order):
    m = _ref_mesh()
    ev = np.linalg.eigvalsh(_mass(order, m, DofMap(m, order)))
    assert ev.min() > 0                # a genuine basis, not a dependent set


def _project(order, mesh, dm, field):
    p, w = tet_rule(5)
    fp = dm.face_perm if order >= 2 else None
    M = _mass(order, mesh, dm)
    b = np.zeros(M.shape[0])
    for q in range(len(w)):
        N, _ = tet_basis(order, mesh.grads, p[q], fp)
        x = (p[q][:, None] * mesh.nodes[mesh.tets[0]]).sum(0)
        b += w[q] * mesh.volumes[0] * (N[0] @ field(x))
    c = np.linalg.solve(M, b)
    res = ref = 0.0
    for q in range(len(w)):
        N, _ = tet_basis(order, mesh.grads, p[q], fp)
        x = (p[q][:, None] * mesh.nodes[mesh.tets[0]]).sum(0)
        f = field(x)
        res += w[q] * mesh.volumes[0] * np.sum((f - c @ N[0]) ** 2)
        ref += w[q] * mesh.volumes[0] * np.sum(f ** 2)
    return np.sqrt(res / ref)


def test_order1_reproduces_constant_fields():
    m = _ref_mesh()
    err = _project(1, m, DofMap(m, 1), lambda x: np.array([1.0, -2.0, 3.0]))
    assert err < 1e-12


def test_order2_reproduces_linear_fields():
    """Second order must contain the complete (P1)^3 space."""
    m = _ref_mesh()
    err = _project(2, m, DofMap(m, 2),
                   lambda x: np.array([x[1], x[2], x[0]]))
    assert err < 1e-11


def test_whitney_circulation_is_the_dof():
    """int_edge W_e . t dl == 1 on its own edge, 0 on the others."""
    m = _ref_mesh()
    nodes = m.nodes[m.tets[0]]
    from aether.mesh.tetmesh import LOCAL_EDGES
    xs, ws = np.polynomial.legendre.leggauss(6)
    xs = 0.5 * (xs + 1); ws = 0.5 * ws
    circ = np.zeros((6, 6))
    for e, (a, b) in enumerate(LOCAL_EDGES):
        d = nodes[b] - nodes[a]
        for t, w in zip(xs, ws):
            lam = np.zeros(4)
            lam[a] = 1 - t
            lam[b] = t
            N, _ = tet_basis(1, m.grads, lam)
            circ[:, e] += w * (N[0] @ d)
    assert np.allclose(circ, np.eye(6), atol=1e-12)


def test_curl_of_gradient_basis_vanishes():
    m = _ref_mesh()
    dm = DofMap(m, 2)
    _, C = tet_basis(2, m.grads, np.array([.3, .2, .4, .1]), dm.face_perm)
    assert np.allclose(C[0, 6:12], 0.0, atol=1e-12)   # grad(l_a l_b) is curl-free


def test_triangle_basis_is_the_trace_of_the_tet_basis():
    """Tangential continuity depends on this identity holding exactly."""
    m = _ref_mesh()
    face = np.array([[1, 2, 3]])
    area, g2, n = tri_geometry(m.nodes, face)
    lam2 = np.array([0.2, 0.5, 0.3])
    N2, _ = tri_basis(1, g2, lam2)
    lam4 = np.array([0.0, 0.2, 0.5, 0.3])
    N3, _ = tet_basis(1, m.grads, lam4)
    # local edges of face (1,2,3) are tet edges 3:(1,2) 4:(1,3) 5:(2,3)
    tang = N3[0][[3, 4, 5]]
    tang = tang - np.outer(tang @ n[0], n[0])
    assert np.allclose(tang, N2[0], atol=1e-12)
