"""
Eigenmode solver (1.8.0), checked against closed-form cavity results.

Every reference below is analytic: rectangular-cavity resonances, Q = 1/tan(d)
for a uniformly lossy filling, and Pozar's conductor-loss Q of the TE101 mode.
"""
import itertools
import math

import numpy as np
import pytest

from conftest import needs_occ

import aether as ae
from aether.core.materials import ConstantTanD, Material
from aether.geometry.select import OuterSelector

pytestmark = needs_occ

c0 = ae.c0
A, B, D = 30e-3, 15e-3, 20e-3


def cavity_modes(n, er=1.0):
    out = []
    for m, k, p in itertools.product(range(4), range(4), range(4)):
        if (m > 0) + (k > 0) + (p > 0) < 2:
            continue
        te = p >= 1 and (m > 0 or k > 0)
        tm = m >= 1 and k >= 1
        if te or tm:
            out.append(0.5 * c0 / math.sqrt(er)
                       * math.sqrt((m / A) ** 2 + (k / B) ** 2 + (p / D) ** 2))
    return sorted(out)[:n]


def cavity(order=2, size=0.006, material="vacuum", walls=None, n_modes=5,
           fmin=0.0, f0="10GHz"):
    d = ae.Design("cav", solution_type="eigenmode")
    d.add_box("c", (0, 0, 0), (A, B, D), material)
    if walls == "copper":
        d.assign_finite_conductivity("walls", OuterSelector(), "copper")
    else:
        d.assign_pec_outer()
    st = d.add_setup("E", frequency=f0, max_passes=1, basis_order=order)
    st.n_modes = n_modes
    st.min_frequency = fmin
    d.generate_mesh(ae.to_si(f0, "frequency"), force=True, size=size)
    return d


def test_second_order_cavity_matches_the_analytic_resonances():
    sol = cavity(order=2).solve(adaptive=False, progress=False)
    got = [m.f for m in sol.modes]
    want = cavity_modes(5)
    assert len(got) == 5
    for g, w in zip(got, want):
        assert g == pytest.approx(w, rel=2e-3)
    # the fundamental, which has no degenerate partner, is far tighter
    assert got[0] == pytest.approx(want[0], rel=2e-4)


def test_there_is_no_spurious_zero_frequency_mode():
    """The curl-free null space must not leak into the result."""
    for order, size in ((1, 0.005), (2, 0.006)):
        sol = cavity(order=order, size=size).solve(adaptive=False,
                                                   progress=False)
        assert min(m.f for m in sol.modes) > 0.9 * cavity_modes(1)[0]


def test_first_order_cavity_is_reasonable_and_second_order_is_better():
    err = {}
    for order, size in ((1, 0.004), (2, 0.006)):
        sol = cavity(order=order, size=size).solve(adaptive=False,
                                                   progress=False)
        err[order] = abs(sol.modes[0].f / cavity_modes(1)[0] - 1)
    assert err[1] < 5e-3
    assert err[2] < err[1] / 5


def test_a_lossless_cavity_has_infinite_q():
    sol = cavity().solve(adaptive=False, progress=False)
    assert all(math.isinf(m.q) for m in sol.modes)
    assert all(m.converged for m in sol.modes)


def test_dielectric_loss_gives_q_equal_to_one_over_tan_delta():
    mat = Material("lossy", ConstantTanD(2.2, 1e-3))
    d = ae.Design("cav", solution_type="eigenmode")
    d.materials.add(mat)
    d.add_box("c", (0, 0, 0), (A, B, D), "lossy")
    d.assign_pec_outer()
    st = d.add_setup("E", frequency="7GHz", max_passes=1, basis_order=2)
    st.n_modes = 1
    d.generate_mesh(7e9, force=True, size=0.006)
    sol = d.solve(adaptive=False, progress=False)
    m = sol.modes[0]
    assert m.f == pytest.approx(cavity_modes(1, er=2.2)[0], rel=1e-3)
    assert m.q == pytest.approx(1000.0, rel=1e-3)


def test_copper_walls_reproduce_pozars_conductor_q():
    d = cavity(walls="copper", n_modes=1)
    sol = d.solve(adaptive=False, progress=False)
    m = sol.modes[0]
    f0 = cavity_modes(1)[0]
    k = 2 * math.pi * f0 / c0
    mu0, eta, sigma = 4e-7 * math.pi, 376.730313668, 5.8e7
    rs = math.sqrt(2 * math.pi * f0 * mu0 / (2 * sigma))
    qc = ((k * A * D) ** 3 * B * eta / (2 * math.pi ** 2 * rs)
          / (2 * A ** 3 * B + 2 * B * D ** 3 + A ** 3 * D + A * D ** 3))
    assert m.converged
    assert m.f == pytest.approx(f0, rel=2e-4)
    assert m.q == pytest.approx(qc, rel=0.02)         # Pozar eq. 6.46
    assert m.q < 0.5 * 1e9                            # finite, not PEC


def test_minimum_frequency_skips_the_lower_modes():
    modes = cavity_modes(8)
    fmin = 0.5 * (modes[1] + modes[2])
    sol = cavity(fmin=fmin, n_modes=2).solve(adaptive=False, progress=False)
    assert all(m.f > fmin for m in sol.modes)
    assert sol.modes[0].f == pytest.approx(modes[2], rel=2e-3)


def test_fields_are_stored_per_mode_and_satisfy_the_boundary():
    sol = cavity(n_modes=2).solve(adaptive=False, progress=False)
    fs = sol.field(sol.modes[0].f, 0)
    e = fs.E_at_centroids()
    assert np.isfinite(e).all() and np.abs(e).max() > 0
    # TE101 has E along y only
    assert np.abs(e[:, 1]).max() > 5 * np.abs(e[:, 0]).max()


def test_adaptive_passes_refine_toward_the_analytic_frequency():
    d = ae.Design("cav", solution_type="eigenmode")
    d.add_box("c", (0, 0, 0), (A, B, D), "vacuum")
    d.assign_pec_outer()
    st = d.add_setup("E", frequency="10GHz", max_passes=4, basis_order=1)
    st.n_modes = 1
    st.delta_f = 0.001
    d.config.mesh.max_element_size = 0.009
    sol = d.solve(progress=False)
    first, last = sol.convergence[0], sol.convergence[-1]
    assert last["tets"] > first["tets"]
    want = cavity_modes(1)[0]
    assert abs(last["f0"] / want - 1) < abs(first["f0"] / want - 1)
    assert abs(last["f0"] / want - 1) < 3e-3


def test_unreliable_boundaries_are_rejected_up_front():
    d = cavity()
    d.assign_radiation("open")
    errs = d.validate()
    assert any("not supported by the eigenmode solver" in e for e in errs)


def test_summary_lists_the_modes():
    sol = cavity(n_modes=2).solve(adaptive=False, progress=False)
    text = sol.summary()
    assert "mode 1: f =" in text and "mode 2: f =" in text


def test_eigenmode_setup_survives_an_aedt_round_trip(tmp_path):
    d = cavity(n_modes=4, fmin=5e9)
    d.setups[0].delta_f = 0.01
    path = str(tmp_path / "cav.aedt")
    ae.save_hfss(d, path, mode="create")
    d2, _ = ae.open_hfss(path)
    assert d2.solution_type == "eigenmode"
    st = d2.setups[0]
    assert st.n_modes == 4
    assert st.min_frequency == pytest.approx(5e9)
    assert st.delta_f == pytest.approx(0.01)
