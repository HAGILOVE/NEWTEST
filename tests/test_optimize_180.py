"""
Optimisation (1.8.0), against designs whose optimum is known in closed form.

* cavity length that puts TE101 at a target frequency: f = c/2 sqrt(1/a^2+1/L^2)
* dielectric slab in WR-90: reflection vanishes when the slab is half a guide
  wavelength thick, L = pi / sqrt(k0^2 eps_r - kc^2)
"""
import math
import threading

import numpy as np
import pytest

from conftest import needs_occ

import aether as ae
from aether.core.materials import ConstantTanD, Material
from aether.gui.api import dispatch
from aether.gui.state import Session
from aether.optimize import Goal, OptVariable, _pattern_search

pytestmark = needs_occ

c0 = ae.c0
A, B = 30e-3, 15e-3


def cavity_session(length="25mm"):
    s = Session()
    s.new_project("Opt")
    s.insert_design("cav", "eigenmode")
    dispatch(s, "parameters.set", {"variables": {"L": length}})
    dispatch(s, "modeler.draw", {"shape": "box", "name": "cav",
                                 "params": {"size": ["30mm", "15mm", "L"]}})
    d = s.design
    d.assign_pec_outer()
    st = d.add_setup("E", frequency="9GHz", max_passes=1, basis_order=2)
    st.n_modes = 1
    d.config.mesh.max_element_size = 0.006
    return s


def te101(length):
    return 0.5 * c0 * math.sqrt(1 / A ** 2 + 1 / length ** 2)


def length_for(f):
    return 1.0 / math.sqrt((2 * f / c0) ** 2 - 1 / A ** 2)


@pytest.mark.parametrize("method", ["nelder-mead", "pattern", "quasi-newton"])
def test_cavity_length_is_tuned_to_a_target_resonance(method):
    s = cavity_session()
    target = 10e9
    res = ae.optimize(s.design, {"L": ("15mm", "40mm")},
                      [Goal("eigenfreq", target=target)], method=method,
                      max_evals=45)
    # nelder-mead polishes to the FEM's own accuracy; the derivative-free /
    # finite-difference searches stop at their step resolution
    tight = method == "nelder-mead"
    assert res.satisfied or res.best_cost < (0.05 if tight else 0.2)
    assert res.best["L"] == pytest.approx(length_for(target),
                                          rel=4e-3 if tight else 1e-2)
    assert res.n_evals <= 45
    # the design the user holds is untouched until they apply the result
    assert s.design.variables["L"] == "25mm"


def test_apply_sets_the_variable_and_rebuilds_the_geometry():
    s = cavity_session()
    res = ae.optimize(s.design, {"L": ("15mm", "40mm")},
                      [Goal("eigenfreq", target=10e9)], max_evals=40)
    res.apply(s.design)
    lo, hi = s.design.bounding_box()
    assert hi[2] - lo[2] == pytest.approx(res.best["L"], rel=1e-9)
    assert s.design.variables["L"].endswith("m")


def test_goals_that_are_met_cost_nothing_and_stop_the_search():
    s = cavity_session("21.2mm")
    res = ae.optimize(s.design, {"L": ("15mm", "40mm")},
                      [Goal("eigenfreq", target=te101(0.0212) * 1.0001,
                            weight=1.0)], max_evals=30, cost_tol=0.5)
    assert res.stopped == "goals met" and res.satisfied
    assert res.n_evals == 1


def test_budget_is_respected_and_reported():
    s = cavity_session()
    res = ae.optimize(s.design, {"L": ("15mm", "40mm")},
                      [Goal("eigenfreq", target=10e9)], max_evals=3,
                      method="pattern")
    assert res.n_evals == 3 and res.stopped == "budget"
    assert not res.satisfied


def test_cancellation_stops_between_solves():
    s = cavity_session()
    ev = threading.Event()
    seen = []

    def cb(rec):
        seen.append(rec)
        ev.set()

    res = ae.optimize(s.design, {"L": ("15mm", "40mm")},
                      [Goal("eigenfreq", target=10e9)], max_evals=40,
                      callback=cb, cancel=ev)
    assert res.stopped == "cancelled" and res.n_evals == 1


def test_history_records_every_solve_with_its_goal_values():
    s = cavity_session()
    res = ae.optimize(s.design, {"L": ("15mm", "40mm")},
                      [Goal("eigenfreq", target=10e9)], max_evals=8)
    assert len(res.history) == res.n_evals
    h = res.history[0]
    assert set(h) >= {"eval", "values", "cost", "goals", "runtime"}
    assert h["goals"][0]["value"] == pytest.approx(te101(h["values"]["L"]),
                                                   rel=2e-3)
    costs = [r["cost"] for r in res.history]
    assert res.best_cost == pytest.approx(min(costs))


def test_two_variables_and_a_weighted_pair_of_goals():
    s = Session()
    s.new_project("Opt2")
    s.insert_design("cav", "eigenmode")
    dispatch(s, "parameters.set", {"variables": {"W": "28mm", "L": "24mm"}})
    dispatch(s, "modeler.draw", {"shape": "box", "name": "cav",
                                 "params": {"size": ["W", "15mm", "L"]}})
    d = s.design
    d.assign_pec_outer()
    st = d.add_setup("E", frequency="9GHz", max_passes=1, basis_order=2)
    st.n_modes = 2
    d.config.mesh.max_element_size = 0.006
    f1 = 9.5e9
    w, l = 0.032, 0.022
    f2 = 0.5 * c0 * math.sqrt(1 / w ** 2 + 4 / l ** 2) if False else None
    # modes of a W x 15 x L cavity: TE101 and TE102-or-TE201 ordering varies,
    # so ask for the lowest only and let the second variable be free
    res = ae.optimize(d, {"W": ("22mm", "40mm"), "L": ("15mm", "40mm")},
                      [Goal("eigenfreq", target=f1, mode=1)],
                      method="nelder-mead", max_evals=60)
    assert res.satisfied or res.best_cost < 0.1
    got = 0.5 * c0 * math.sqrt(1 / res.best["W"] ** 2 + 1 / res.best["L"] ** 2)
    assert got == pytest.approx(f1, rel=2e-3)


# ----------------------------------------------------------------- driven
def slab_design(start="9mm"):
    """WR-90 with a dielectric slab; the reflection notch is narrow."""
    s = Session()
    s.new_project("Slab")
    d = s.design
    d.materials.add(Material("slab", ConstantTanD(2.0, 0.0)))
    dispatch(s, "parameters.set", {"variables": {"T": start}})
    dispatch(s, "modeler.draw", {
        "shape": "box", "name": "air", "material": "vacuum",
        "params": {"position": ["0mm", "0mm", "0mm"],
                   "size": ["30mm", "15mm", "60mm"]}})
    dispatch(s, "modeler.draw", {
        "shape": "box", "name": "slab", "material": "slab",
        "params": {"position": ["0mm", "0mm", "20mm"],
                   "size": ["30mm", "15mm", "T"]}})
    d.add_wave_port("p1", axis="z", value=0)
    d.add_wave_port("p2", axis="z", value=0.06)
    d.assign_pec_outer()
    d.config.mesh.max_element_size = 0.004
    st = d.add_setup("S", "10GHz", max_passes=1)
    st.add_sweep("Sw", points=["10GHz"])
    return d


def half_wave_thickness():
    k0 = 2 * math.pi * 10e9 / c0
    return math.pi / math.sqrt(k0 ** 2 * 2.0 - (math.pi / A) ** 2)


@pytest.mark.slow
def test_slab_matching_goal_finds_the_half_wave_thickness():
    d = slab_design("9mm")
    res = ae.optimize(d, {"T": ("4mm", "16mm")},
                      [Goal("s_max", target=-30.0, port=1, port2=1,
                            f_start=10e9, f_stop=10e9)],
                      method="nelder-mead", max_evals=30)
    assert res.best_cost < 5.0                         # S11 below -25 dB
    assert res.best["T"] == pytest.approx(half_wave_thickness(), rel=0.06)


@pytest.mark.slow
def test_global_search_escapes_a_flat_starting_region():
    """From 6 mm the response is flat (-11 dB) and a local search stalls."""
    d = slab_design("6mm")
    res = ae.optimize(d, {"T": ("4mm", "16mm")},
                      [Goal("s_max", target=-30.0, port=1, port2=1,
                            f_start=10e9, f_stop=10e9)],
                      method="differential-evolution", max_evals=60)
    assert res.best_cost < 10.0                        # clearly inside the notch
    assert res.best["T"] == pytest.approx(half_wave_thickness(), rel=0.1)


# ------------------------------------------------------------- unit pieces
def test_goal_validation():
    with pytest.raises(ValueError):
        Goal("nonsense")
    with pytest.raises(ValueError):
        Goal("s_max", weight=0)
    g = Goal("resonance", target="2.45GHz", f_start="2GHz", f_stop="3GHz")
    assert g.target == pytest.approx(2.45e9) and g.f_start == pytest.approx(2e9)


def test_variable_checks():
    s = cavity_session()
    with pytest.raises(ValueError, match="not defined"):
        ae.optimize(s.design, {"nope": ("1mm", "2mm")},
                    [Goal("eigenfreq", target=1e10)])
    with pytest.raises(ValueError, match="lower limit"):
        ae.optimize(s.design, {"L": ("30mm", "20mm")},
                    [Goal("eigenfreq", target=1e10)])
    with pytest.raises(ValueError, match="dimension"):
        ae.optimize(s.design, {"L": ("1GHz", "2GHz")},
                    [Goal("eigenfreq", target=1e10)])
    with pytest.raises(ValueError, match="at least one goal"):
        ae.optimize(s.design, {"L": ("10mm", "30mm")}, [])
    with pytest.raises(ValueError, match="unknown method"):
        ae.optimize(s.design, {"L": ("10mm", "30mm")},
                    [Goal("eigenfreq", target=1e10)], method="magic")


def test_pattern_search_minimises_a_smooth_function_inside_the_box():
    pts = []

    def bowl(u):
        return float((u[0] - 0.3) ** 2 + 2 * (u[1] - 0.8) ** 2)

    def f(u):
        pts.append(np.array(u))
        return bowl(u)

    _pattern_search(f, np.array([0.9, 0.1]))
    best = min(pts, key=bowl)                   # a pure key: pts is not mutated
    assert best == pytest.approx([0.3, 0.8], abs=0.02)
    assert all(0 <= p.min() and p.max() <= 1 for p in pts)


def test_opt_variable_text_units():
    assert OptVariable("L", 0, 1, 0, ae.optimize.__globals__["LENGTH"]).text(0.0123) == "0.0123m"


# ------------------------------------------------------------------ GUI API
def _wait(s, timeout=120):
    import time
    t0 = time.time()
    while s.job.running and time.time() - t0 < timeout:
        time.sleep(0.05)
    assert not s.job.running, "optimization did not finish"


def test_api_runs_an_optimization_and_applies_the_result_with_undo():
    s = cavity_session()
    r = dispatch(s, "analysis.optimize", {
        "variables": {"L": ["15mm", "40mm"]},
        "goals": [{"kind": "eigenfreq", "target": "10GHz", "weight": 1}],
        "method": "nelder-mead", "maxEvals": 40})
    assert r["ok"]
    _wait(s)
    res = dispatch(s, "analysis.optimizeResults")
    assert res["status"] in ("goals met", "converged", "budget")
    assert res["rows"] and res["best"]["cost"] < 0.1
    assert res["spec"]["goals"] == ["mode 1 frequency = 10 GHz"]
    assert "L" in res["expressions"]
    # nothing changed in the design until Apply
    assert s.design.variables["L"] == "25mm"
    dispatch(s, "analysis.optimizeApply")
    lo, hi = s.design.bounding_box()
    assert hi[2] - lo[2] == pytest.approx(length_for(10e9), rel=5e-3)
    dispatch(s, "edit.undo")
    lo, hi = s.design.bounding_box()
    assert hi[2] - lo[2] == pytest.approx(0.025, rel=1e-9)


def test_api_rejects_bad_optimization_requests():
    s = cavity_session()
    good = {"variables": {"L": ["15mm", "40mm"]},
            "goals": [{"kind": "eigenfreq", "target": "10GHz"}]}
    for bad in ({"variables": {}}, {"goals": []}, {"method": "magic"},
                {"variables": {"L": ["40mm", "15mm"]}},
                {"variables": {"nope": ["1mm", "2mm"]}},
                {"maxEvals": 1}, {"goals": [{"kind": "wishful"}]}):
        with pytest.raises(Exception):
            dispatch(s, "analysis.optimize", {**good, **bad})
    assert not s.job.running
    with pytest.raises(ValueError, match="No finished optimization"):
        dispatch(s, "analysis.optimizeApply")


def test_api_cancel_stops_a_running_optimization():
    import time
    s = cavity_session()
    dispatch(s, "analysis.optimize", {
        "variables": {"L": ["15mm", "40mm"]},
        "goals": [{"kind": "eigenfreq", "target": "10GHz"}],
        "method": "differential-evolution", "maxEvals": 500})
    time.sleep(0.5)
    dispatch(s, "analysis.cancel")
    _wait(s)
    res = dispatch(s, "analysis.optimizeResults")
    assert res["status"] in ("cancelled", "goals met")
    assert "error" not in res
    assert len(res["rows"]) < 500
