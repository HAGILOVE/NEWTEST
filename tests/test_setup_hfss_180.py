"""Solution setup and sweep fields as HFSS defines them."""
import numpy as np
import pytest

import aether as ae
from aether.gui.api import dispatch
from aether.gui.state import Session


def session():
    s = Session()
    s.new_project("S")
    return s


def test_linear_step_runs_from_start_to_stop_inclusive():
    st = ae.Design("x").add_setup("S", "10GHz")
    sw = st.add_sweep("L", "8GHz", "12GHz", spacing="step", step="0.5GHz")
    f = sw.frequencies()
    assert sw.count == 9 and f[0] == 8e9 and f[-1] == pytest.approx(12e9)
    assert np.allclose(np.diff(f), 0.5e9)
    # a step that does not divide the span stops at the last whole step
    sw2 = st.add_sweep("M", "1GHz", "2GHz", spacing="step", step="0.3GHz")
    assert sw2.frequencies()[-1] == pytest.approx(1.9e9)


def test_a_zero_step_is_rejected():
    st = ae.Design("x").add_setup("S", "10GHz")
    sw = st.add_sweep("L", "8GHz", "12GHz", count=5)
    sw.spacing, sw.step = "step", 0.0
    with pytest.raises(ValueError):
        sw.frequencies()


def test_setup_carries_the_hfss_adaptive_fields():
    s = session()
    dispatch(s, "analysis.addSetup", {
        "name": "Setup1", "frequency": "2.4GHz", "maxPasses": 12,
        "minPasses": 3, "minConverged": 2, "deltaS": 0.01,
        "refinement": 20, "basisOrder": 2})
    st = s.design.setups[0]
    assert (st.max_passes, st.min_passes, st.min_converged) == (12, 3, 2)
    assert st.refinement == pytest.approx(0.20) and st.basis_order == 2
    j = dispatch(s, "project.state", {}) if False else None


@pytest.mark.parametrize("bad", [{"refinement": 0}, {"refinement": 150},
                                 {"minPasses": 9, "maxPasses": 5},
                                 {"minConverged": 0}])
def test_bad_setup_values_are_refused_and_leave_no_setup_behind(bad):
    s = session()
    args = {"name": "S", "frequency": "1GHz", "maxPasses": 6}
    args.update(bad)
    with pytest.raises(ValueError):
        dispatch(s, "analysis.addSetup", args)
    assert s.design.setups == []


def test_edit_setup_changes_fields_and_renames():
    s = session()
    dispatch(s, "analysis.addSetup", {"name": "A", "frequency": "1GHz"})
    dispatch(s, "analysis.editSetup", {"name": "A", "newName": "B",
                                       "frequency": "5GHz", "maxPasses": 9,
                                       "minConverged": 2, "refinement": 40})
    st = s.design.setups[0]
    assert st.name == "B" and st.frequency == 5e9
    assert st.max_passes == 9 and st.min_converged == 2
    assert st.refinement == pytest.approx(0.4)


def test_sweep_add_and_edit_with_step_and_save_fields():
    s = session()
    dispatch(s, "analysis.addSetup", {"name": "A", "frequency": "10GHz"})
    dispatch(s, "analysis.addSweep", {
        "setup": "A", "name": "W", "kind": "interpolating", "start": "8GHz",
        "stop": "12GHz", "spacing": "step", "step": "0.1GHz",
        "saveFields": True})
    sw = s.design.setups[0].sweeps[0]
    assert sw.count == 41 and sw.save_fields and sw.kind == "interpolating"
    dispatch(s, "analysis.editSweep", {
        "setup": "A", "name": "W", "kind": "discrete", "start": "9GHz",
        "stop": "10GHz", "spacing": "linear", "count": 11})
    sw = s.design.setups[0].sweeps[0]
    assert sw.kind == "discrete" and len(sw.frequencies()) == 11
    assert sw.start == 9e9 and sw.step is None


@pytest.mark.parametrize("bad", [{"spacing": "step"}, {"spacing": "step", "step": "0GHz"},
                                 {"spacing": "weird"}, {"kind": "turbo"},
                                 {"start": "1GHz", "stop": "30GHz", "spacing": "step",
                                  "step": "1kHz"}])
def test_bad_sweeps_are_rejected(bad):
    s = session()
    dispatch(s, "analysis.addSetup", {"name": "A", "frequency": "10GHz"})
    args = {"setup": "A", "start": "8GHz", "stop": "12GHz"}
    args.update(bad)
    with pytest.raises(Exception):
        dispatch(s, "analysis.addSweep", args)
    assert s.design.setups[0].sweeps == []


def test_aedt_round_trip_keeps_step_refinement_and_converged_passes(tmp_path):
    d = ae.Design("rt")
    d.add_box("b", (0, 0, 0), (0.02, 0.01, 0.01), "vacuum")
    d.add_wave_port("p1", axis="z", value=0)
    d.add_wave_port("p2", axis="z", value=0.01)
    st = d.add_setup("S1", "10GHz", max_passes=8)
    st.min_converged, st.refinement = 3, 0.25
    st.add_sweep("Sw", "8GHz", "12GHz", spacing="step", step="0.25GHz")
    path = str(tmp_path / "rt.aedt")
    ae.save_hfss(d, path, mode="create")
    d2, _ = ae.open_hfss(path)
    s2 = d2.setups[0]
    assert s2.min_converged == 3 and s2.refinement == pytest.approx(0.25)
    sw = s2.sweeps[0]
    assert sw.spacing == "step" and sw.step == pytest.approx(0.25e9)
    assert len(sw.frequencies()) == 17
