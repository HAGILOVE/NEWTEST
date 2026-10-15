"""Output variables (expressions of S / Y / Z) and the field along a line."""
import math

import numpy as np
import pytest

import aether as ae
from aether.gui.state import Session

from conftest import needs_occ

pytestmark = [needs_occ, pytest.mark.slow]

H, W, LEN = 1e-3, 10e-3, 20e-3
Z0 = ae.eta0 * H / W


@pytest.fixture(scope="module")
def solved():
    d = ae.Design("pp", units="mm")
    d.add_box("air", (0, 0, 0), (LEN, W, H), "vacuum")
    d.assign_boundary("PMC_y0", "pmc", ae.PlaneSelector("y", 0))
    d.assign_boundary("PMC_y1", "pmc", ae.PlaneSelector("y", W))
    d.add_lumped_port("p1", axis="x", value=0, impedance=Z0, direction=(0, 0, 1))
    d.add_lumped_port("p2", axis="x", value=LEN, impedance=Z0, direction=(0, 0, 1))
    st = d.add_setup("S", frequency="5GHz")
    st.add_sweep("sw", "4GHz", "6GHz", 3, kind="discrete", save_fields=True)
    d.generate_mesh(5e9, force=True, size=0.0015)
    s = Session()
    s.new_project("P")
    s.project.designs[0] = d
    s.design = d
    s.solution = d.solve(adaptive=False, progress=False, save_fields=True)
    return s


def call(s, method, **params):
    from aether.gui.api import dispatch
    return dispatch(s, method, params)


def test_an_expression_of_the_impedance_matches_the_direct_value(solved):
    r = call(solved, "results.expression", exprs=[{"name": "L", "expr": "1e9*im(Z(1,1))/2/pi/Freq"},
                                                 {"name": "S21dB", "expr": "db(S(2,1))"},
                                                 {"name": "ratio", "expr": "abs(S(1,1))/abs(S(2,1))+0*Freq"}])
    sp = solved.solution.sparams
    z11 = sp.to_z()[:, 0, 0]
    f = np.asarray(sp.freq)
    assert r["traces"][0]["y"] == pytest.approx(list(1e9 * z11.imag / 2 / math.pi / f), rel=1e-9)
    assert r["traces"][1]["y"] == pytest.approx(list(sp.db(2, 1)), rel=1e-9)
    assert len(r["traces"][2]["y"]) == 3
    assert r["freq"] == pytest.approx(list(f))


def test_output_variables_can_refer_to_each_other_and_are_saved(solved, tmp_path):
    call(solved, "results.setVariables", variables={"Zin": "Z(1,1)", "Lin": "1e9*im(Zin)/2/pi/Freq"})
    r = call(solved, "results.expression", exprs=[{"name": "L", "expr": "Lin"}])
    assert len(r["traces"][0]["y"]) == 3
    path = str(tmp_path / "ov.warp")
    call(solved, "project.save", path=path)
    s2 = Session()
    call(s2, "project.open", path=path)
    assert s2.design.output_variables == {"Zin": "Z(1,1)", "Lin": "1e9*im(Zin)/2/pi/Freq"}
    call(solved, "results.setVariables", variables={})


def test_bad_expressions_are_explained(solved):
    for bad, msg in (("S(3,1)", "no port 3"), ("foo+1", "unknown name"), ("__import__('os')", "unsupported"),
                     ("S(1,1", "cannot read")):
        with pytest.raises(ValueError, match=msg):
            call(solved, "results.expression", exprs=[{"name": "x", "expr": bad}])
    with pytest.raises(ValueError, match="refers to itself"):
        call(solved, "results.setVariables", variables={"a": "b+1", "b": "a+1"})
        call(solved, "results.expression", exprs=[{"name": "x", "expr": "a"}])
    call(solved, "results.setVariables", variables={})


def test_the_field_along_the_line_of_a_matched_tem_line_is_uniform(solved):
    r = call(solved, "results.fieldOnLine", start=["2mm", "5mm", "0.5mm"], end=["18mm", "5mm", "0.5mm"],
             points=41, quantity="E", freq=5e9, excitation=0)
    assert all(r["inside"]) and r["length"] == pytest.approx(16e-3)
    mag = np.array(r["mag"])
    assert mag.min() > 0 and (mag.max() - mag.min()) / mag.mean() < 0.15          # |E| = V/h all the way down a matched line
    z = np.array(r["z"])
    assert (z / mag).min() > 0.95                                               # and it is the vertical component
    assert r["distance"][-1] == pytest.approx(16e-3)


def test_a_point_outside_the_mesh_is_flagged_not_invented(solved):
    r = call(solved, "results.fieldOnLine", start=["2mm", "5mm", "0.5mm"], end=["30mm", "5mm", "0.5mm"], points=15,
             freq=5e9)
    assert not all(r["inside"]) and r["inside"][0]
    assert r["mag"][-1] == 0.0


def test_the_instantaneous_value_follows_the_phase(solved):
    a = call(solved, "results.fieldOnLine", start=["2mm", "5mm", "0.5mm"], end=["18mm", "5mm", "0.5mm"], points=21,
             freq=5e9, phase=0)
    b = call(solved, "results.fieldOnLine", start=["2mm", "5mm", "0.5mm"], end=["18mm", "5mm", "0.5mm"], points=21,
             freq=5e9, phase=90)
    assert max(abs(np.array(a["instant"]["z"]))) <= max(a["mag"]) + 1e-12
    assert a["instant"]["z"] != b["instant"]["z"]
