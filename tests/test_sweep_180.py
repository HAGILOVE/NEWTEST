"""
Interpolating and fast frequency sweeps (1.8.0).

Before 1.8.0 these two labels silently ran a full discrete solve per point.
The contract tested here: they spend *fewer* full solves, and what they return
agrees with the discrete reference to within the requested tolerance.
"""
import math

import numpy as np
import pytest

from conftest import needs_occ

import aether as ae
from aether.fem.rational import aaa_fit

A, B = 22.86e-3, 10.16e-3


def test_aaa_reproduces_a_resonant_response_exactly_at_samples():
    f = np.linspace(8e9, 12e9, 401)

    def resp(x):
        den = 1 + 1j * (x - 10e9) / 0.05e9
        return np.stack([(1j * (x - 10e9) / 0.05e9) / den,
                         np.exp(-2j * np.pi * x * 0.15e-9) / den], axis=1)

    idx = np.linspace(0, 400, 17).astype(int)
    fit = aaa_fit(f[idx], resp(f[idx]), tol=1e-10)
    assert np.abs(fit(f[idx]) - resp(f[idx])).max() < 1e-12
    assert np.abs(fit(f) - resp(f)).max() < 1e-9           # between samples too
    assert fit.degree < 16


def test_aaa_rejects_a_single_sample():
    with pytest.raises(ValueError):
        aaa_fit(np.array([1.0]), np.array([[1.0 + 0j]]))


def guide(kind, f0="8GHz", f1="12GHz", n=81, length=0.03, deembed=0.0,
          **sweep_kw):
    d = ae.Design("g")
    d.add_box("g", (0, 0, 0), (A, B, length), "vacuum")
    d.add_wave_port("p1", axis="z", value=0, deembed=deembed)
    d.add_wave_port("p2", axis="z", value=length, deembed=deembed)
    d.assign_pec_outer()
    st = d.add_setup("S1", frequency="10GHz")
    st.add_sweep("Sw", f0, f1, n, kind=kind, **sweep_kw)
    d.generate_mesh(1e10, force=True, size=0.004)
    return d


_REF = {}


def ref(f0="8GHz", f1="12GHz", n=81, **kw):
    """Discrete answer for the same grid (cached: it is the slow part)."""
    key = (f0, f1, n, tuple(sorted(kw.items())))
    if key not in _REF:
        _REF[key] = guide("discrete", f0, f1, n, **kw).solve(
            adaptive=False, progress=False).sparams
    return _REF[key]


@needs_occ
def test_interpolating_sweep_uses_fewer_solves_and_matches():
    sol = guide("interpolating").solve(adaptive=False, progress=False)
    info = sol.sweep_info[0]
    assert info["kind"] == "interpolating"
    assert info["solved"] <= info["points"] * 0.4
    assert sol.solved.sum() == info["solved"]
    err = np.abs(sol.sparams.s - ref().s).max()
    assert err < 5 * ae.Config().sweep.interp_tol
    # the unsampled points are reconstructions, not zeros
    assert np.all(np.abs(sol.sparams.s[~sol.solved]).max(axis=(1, 2)) > 0)


@needs_occ
def test_interpolating_sweep_across_the_cutoff_still_meets_tolerance():
    """The sqrt branch point at cutoff is the hard case for a rational model."""
    kw = dict(f0="5GHz", f1="12GHz", n=161)
    sol = guide("interpolating", **kw).solve(adaptive=False, progress=False)
    info = sol.sweep_info[0]
    assert info["solved"] < info["points"] * 0.5
    assert np.abs(sol.sparams.s - ref(**kw).s).max() < 5e-3


@needs_occ
def test_tighter_tolerance_gives_a_closer_match():
    loose = guide("interpolating", tolerance=1e-1).solve(
        adaptive=False, progress=False)
    tight = guide("interpolating", tolerance=1e-5).solve(
        adaptive=False, progress=False)
    e_loose = np.abs(loose.sparams.s - ref().s).max()
    e_tight = np.abs(tight.sparams.s - ref().s).max()
    assert e_tight <= e_loose
    assert tight.solved.sum() >= loose.solved.sum()
    assert e_tight < 1e-4


@needs_occ
def test_max_points_caps_the_number_of_full_solves():
    sol = guide("interpolating", tolerance=1e-12, max_points=9).solve(
        adaptive=False, progress=False)
    assert sol.solved.sum() <= 9


@needs_occ
def test_fast_sweep_reduced_basis_matches():
    sol = guide("fast").solve(adaptive=False, progress=False)
    info = sol.sweep_info[0]
    assert info["kind"] == "fast"
    assert info["solved"] <= 12 and info["solved"] < info["points"] / 3
    assert np.abs(sol.sparams.s - ref().s).max() < 5e-3
    assert sol.sparams.is_reciprocal(tol=1e-4)
    assert sol.sparams.is_passive(tol=1e-4)


@needs_occ
def test_fast_sweep_can_deliver_fields_at_every_frequency():
    d = guide("fast", n=21)
    d.setups[0].sweeps[0].save_fields = True
    sol = d.solve(adaptive=False, progress=False)
    freqs = {k[0] for k in sol.fields}
    assert len(freqs) == 21


@needs_occ
def test_short_sweeps_fall_back_to_discrete():
    sol = guide("interpolating", n=4).solve(adaptive=False, progress=False)
    info = sol.sweep_info[0]
    assert info["requested"] == "interpolating" and info["kind"] == "discrete"
    assert sol.solved.all()


@needs_occ
def test_deembedding_still_works_through_an_interpolated_sweep():
    ref = guide("discrete", n=21, deembed=0.005).solve(
        adaptive=False, progress=False).sparams
    got = guide("interpolating", n=21, deembed=0.005).solve(
        adaptive=False, progress=False).sparams
    assert np.abs(got.s - ref.s).max() < 5e-3


@needs_occ
def test_discrete_sweep_is_unchanged_and_fully_solved():
    sol = guide("discrete").solve(adaptive=False, progress=False)
    assert sol.solved.all()
    assert np.array_equal(sol.sparams.s, ref().s)
    assert "full solve" not in sol.summary()


@needs_occ
def test_summary_reports_what_an_adaptive_sweep_spent():
    sol = guide("interpolating").solve(adaptive=False, progress=False)
    assert "interpolating ->" in sol.summary()


def test_sweep_kind_is_validated():
    from aether.fem.sweep import run_sweep
    with pytest.raises(ValueError):
        run_sweep(None, None, None, None, None, [1e9, 2e9], kind="bogus")


# ------------------------------------------------------------ GUI / file layer
def _session_with_setup():
    from aether.gui.api import dispatch
    from aether.gui.state import Session
    s = Session()
    s.new_project("P")
    s.design.add_setup("Setup1", "10GHz")
    return s, dispatch


def test_api_adds_an_interpolating_sweep_with_a_tolerance():
    s, dispatch = _session_with_setup()
    dispatch(s, "analysis.addSweep", {"kind": "interpolating", "start": "8GHz",
                                      "stop": "12GHz", "count": 81,
                                      "tolerance": "0.002", "maxPoints": 30})
    sw = s.design.setups[0].sweeps[0]
    assert (sw.kind, sw.tolerance, sw.max_points) == ("interpolating", 0.002, 30)


@pytest.mark.parametrize("bad", [{"tolerance": 5}, {"maxPoints": 2},
                                 {"kind": "turbo"}])
def test_api_rejects_nonsense_sweep_settings(bad):
    s, dispatch = _session_with_setup()
    args = {"kind": "interpolating", "start": "8GHz", "stop": "12GHz",
            "count": 81}
    args.update(bad)
    with pytest.raises(Exception):
        dispatch(s, "analysis.addSweep", args)


def test_aedt_roundtrip_keeps_the_sweep_tolerance(tmp_path):
    d = ae.Design("rt")
    d.add_box("b", (0, 0, 0), (A, B, 0.01), "vacuum")
    d.add_wave_port("p1", axis="z", value=0)
    d.add_wave_port("p2", axis="z", value=0.01)
    st = d.add_setup("S1", "10GHz")
    st.add_sweep("Sw", "8GHz", "12GHz", 41, kind="fast", tolerance=0.004,
                 max_points=25)
    path = str(tmp_path / "rt.aedt")
    ae.save_hfss(d, path, mode="create")
    d2, _ = ae.open_hfss(path)
    sw = d2.setups[0].sweeps[0]
    assert sw.kind == "fast"
    assert sw.tolerance == pytest.approx(0.004)
    assert sw.max_points == 25
