"""Network-parameter algebra: conversions, renormalisation, checks."""
import numpy as np
import pytest

import aether as ae
from aether.post.sparam import SParameters


def series_impedance_network(Z, z0=50.0, f=None):
    """Exact S-matrix of a series impedance between two z0 references."""
    f = np.atleast_1d(f if f is not None else 1e9)
    s11 = Z / (Z + 2 * z0)
    s21 = 2 * z0 / (Z + 2 * z0)
    s = np.tile(np.array([[s11, s21], [s21, s11]]), (len(f), 1, 1))
    return SParameters(f, s, z0)


def test_series_resistor_matches_theory():
    sp = series_impedance_network(50.0)
    assert sp.sij(1, 1)[0] == pytest.approx(1 / 3)
    assert sp.sij(2, 1)[0] == pytest.approx(2 / 3)
    # a pure series element has a singular Z-matrix; Y is the honest one
    y = sp.to_y()[0]
    assert y[0, 0] == pytest.approx(1 / 50.0, rel=1e-9)
    assert y[0, 1] == pytest.approx(-1 / 50.0, rel=1e-9)


def test_s_to_z_to_s_round_trip():
    rng = np.random.default_rng(3)
    f = np.linspace(1e9, 2e9, 4)
    s = 0.3 * (rng.normal(size=(4, 3, 3)) + 1j * rng.normal(size=(4, 3, 3)))
    sp = SParameters(f, s, 50.0)
    back = SParameters.from_z(f, sp.to_z(), 50.0)
    assert np.max(np.abs(back.s - sp.s)) < 1e-10


def test_renormalisation_is_invertible_and_physical():
    sp = series_impedance_network(50.0)
    r = sp.renormalize(75.0)
    assert r.z0[0, 0] == pytest.approx(75.0)
    back = r.renormalize(50.0)
    assert np.max(np.abs(back.s - sp.s)) < 1e-12
    # a series 50 ohm between 75 ohm references
    assert r.sij(1, 1)[0] == pytest.approx(50.0 / (50.0 + 150.0))


def test_matched_load_stays_matched_under_renormalisation():
    f = np.array([1e9])
    s = np.zeros((1, 2, 2), complex)
    s[0, 0, 1] = s[0, 1, 0] = 1.0
    thru = SParameters(f, s, 50.0)
    r = thru.renormalize(50.0)
    assert np.allclose(r.s, thru.s, atol=1e-12)


def test_abcd_of_a_series_impedance():
    sp = series_impedance_network(30.0)
    abcd = sp.to_abcd()[0]
    assert abcd[0, 0] == pytest.approx(1.0, abs=1e-9)
    assert abcd[0, 1] == pytest.approx(30.0, rel=1e-9)
    assert abs(abcd[1, 0]) < 1e-9
    assert abcd[1, 1] == pytest.approx(1.0, abs=1e-9)


def test_deembedding_removes_a_line_phase():
    f = np.array([1e10])
    beta = 2 * np.pi * f[0] / ae.c0
    L = 0.01
    s = np.zeros((1, 2, 2), complex)
    s[0, 0, 1] = s[0, 1, 0] = np.exp(-1j * beta * L)
    sp = SParameters(f, s, 50.0)
    g = np.array([[1j * beta, 1j * beta]])
    out = sp.deembed(g, [L / 2, L / 2])
    assert out.sij(2, 1)[0] == pytest.approx(1.0 + 0j, abs=1e-12)


def test_passivity_and_reciprocity_detection():
    f = np.array([1e9])
    s = np.array([[[0.1, 0.2], [0.2, 0.1]]], complex)
    assert SParameters(f, s, 50.0).is_passive()
    assert SParameters(f, s, 50.0).is_reciprocal()
    bad = np.array([[[1.2, 0.0], [0.0, 0.1]]], complex)
    assert not SParameters(f, bad, 50.0).is_passive()
    nonrec = np.array([[[0.1, 0.9], [0.0, 0.1]]], complex)   # an isolator
    assert not SParameters(f, nonrec, 50.0).is_reciprocal()


def test_vswr_and_group_delay():
    f = np.linspace(1e9, 2e9, 21)
    tau = 1e-9
    s = np.zeros((len(f), 2, 2), complex)
    s[:, 1, 0] = s[:, 0, 1] = np.exp(-1j * 2 * np.pi * f * tau)
    s[:, 0, 0] = s[:, 1, 1] = 1 / 3
    sp = SParameters(f, s, 50.0)
    assert np.allclose(sp.group_delay(2, 1), tau, rtol=1e-6)
    assert sp.vswr(1)[0] == pytest.approx(2.0)


def test_mixed_mode_transform_of_an_ideal_balanced_thru():
    f = np.array([1e9])
    s = np.zeros((1, 4, 4), complex)
    for a, b in ((0, 2), (1, 3)):
        s[0, a, b] = s[0, b, a] = 1.0
    sp = SParameters(f, s, 50.0)
    mm = sp.to_mixed_mode([(1, 2), (3, 4)])
    assert mm.n_port == 4
    assert abs(mm.s[0, 0, 1]) == pytest.approx(1.0, abs=1e-9)   # Sdd21
    assert abs(mm.s[0, 0, 3]) < 1e-9                            # no dd/cc mixing


def test_interpolation_between_points():
    f = np.array([1e9, 2e9])
    s = np.zeros((2, 1, 1), complex)
    s[0, 0, 0], s[1, 0, 0] = 0.0, 1.0
    sp = SParameters(f, s, 50.0)
    assert sp.at(1.5e9)[0, 0] == pytest.approx(0.5)
    assert sp.at(0.5e9)[0, 0] == pytest.approx(0.0)
