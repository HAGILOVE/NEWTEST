"""Lumped RLC sheets: the impedance seen across the gap is the one typed in."""
import math

import numpy as np
import pytest

import aether as ae
from aether.geometry import primitives as prim

from conftest import needs_occ

pytestmark = [needs_occ, pytest.mark.slow]

H, W, LEN = 1e-3, 10e-3, 20e-3
Z0 = ae.eta0 * H / W
F = 5e9


def end_load(**rlc):
    """Parallel-plate line, lumped port at x = 0, the RLC on the face at x = LEN."""
    d = ae.Design("pp", units="mm")
    d.add_box("air", (0, 0, 0), (LEN, W, H), "vacuum")
    d.assign_boundary("PMC_y0", "pmc", ae.PlaneSelector("y", 0))
    d.assign_boundary("PMC_y1", "pmc", ae.PlaneSelector("y", W))
    d.add_lumped_port("p1", axis="x", value=0, impedance=Z0, direction=(0, 0, 1))
    d.assign_lumped_rlc("load", ae.PlaneSelector("x", LEN), **rlc)
    st = d.add_setup("S", frequency="5GHz")
    st.add_sweep("sw", "5GHz", "5GHz", 1)
    d.generate_mesh(F, force=True, size=0.0015)
    return d.solve(adaptive=False).sparams.sij(1, 1)[0]


def gamma(z):
    return (z - Z0) / (z + Z0) * np.exp(-2j * (2 * math.pi * F / ae.c0) * LEN)


def test_a_resistor_equal_to_the_line_impedance_is_a_matched_load():
    assert abs(end_load(R=Z0)) < 0.01


def test_a_resistor_of_twice_z0_reflects_one_third():
    s = end_load(R=2 * Z0)
    assert s == pytest.approx(gamma(2 * Z0), abs=0.01)


def test_a_capacitor_reflects_with_the_phase_of_its_reactance():
    c = 1.0 / (2 * math.pi * F * 50.0)                    # 50 ohm of reactance at 5 GHz
    s = end_load(C=c, parallel=True)
    assert s == pytest.approx(gamma(1.0 / (1j * 2 * math.pi * F * c)), abs=0.02)


def test_series_and_parallel_combinations_follow_their_formulas():
    r, l, c = 60.0, 1.2e-9, 0.4e-12
    w = 2 * math.pi * F
    z_ser = r + 1j * w * l + 1.0 / (1j * w * c)
    z_par = 1.0 / (1.0 / r + 1.0 / (1j * w * l) + 1j * w * c)
    assert end_load(R=r, L=l, C=c, parallel=False) == pytest.approx(gamma(z_ser), abs=0.03)
    assert end_load(R=r, L=l, C=c, parallel=True) == pytest.approx(gamma(z_par), abs=0.03)


def test_the_element_current_runs_along_the_given_direction():
    # across the 10 mm width the element would be 10x longer: the load the line sees changes
    along_z = end_load(R=2 * Z0, direction=(0, 0, 1))
    along_y = end_load(R=2 * Z0, direction=(0, 1, 0))
    assert abs(along_z - gamma(2 * Z0)) < 0.02
    assert abs(along_y - gamma(2 * Z0)) > 0.1


def test_an_interior_sheet_is_a_shunt_element_across_the_line():
    d = ae.Design("shunt", units="mm")
    d.add_box("air", (0, 0, 0), (LEN, W, H), "vacuum")
    d.assign_boundary("PMC_y0", "pmc", ae.PlaneSelector("y", 0))
    d.assign_boundary("PMC_y1", "pmc", ae.PlaneSelector("y", W))
    d.add_lumped_port("p1", axis="x", value=0, impedance=Z0, direction=(0, 0, 1))
    d.add_lumped_port("p2", axis="x", value=LEN, impedance=Z0, direction=(0, 0, 1))
    x = LEN / 2
    sheet = prim.Polygon([[x, 0, 0], [x, W, 0], [x, W, H], [x, 0, H]], name="rsheet")
    d.add_sheet("rsheet", sheet)
    d.assign_lumped_rlc("R1", ae.ShapeSelector(sheet, tol=1e-7), R=Z0)
    st = d.add_setup("S", frequency="5GHz")
    st.add_sweep("sw", "5GHz", "5GHz", 1)
    d.generate_mesh(F, force=True, size=0.0015)
    s = d.solve(adaptive=False).sparams
    # a shunt Z across a matched line: S11 = -y/(2+y), y = Z0/Z
    k = 2 * math.pi * F / ae.c0
    assert s.sij(1, 1)[0] == pytest.approx(-1 / 3 * np.exp(-2j * k * x), abs=0.02)
    assert s.sij(2, 1)[0] == pytest.approx(2 / 3 * np.exp(-1j * k * LEN), abs=0.02)


def test_the_gui_command_builds_a_bridging_resistor_between_two_metals():
    from aether.gui.api import dispatch
    from aether.gui.state import Session
    d = ae.Design("m", units="mm")
    d.add_box("air", (-10e-3, -10e-3, -5e-3), (20e-3, 20e-3, 20e-3), "vacuum")
    d.add_box("a", (-2e-3, -2e-3, 0.0), (4e-3, 4e-3, 4e-3), "pec")
    d.add_box("b", (-2e-3, -2e-3, 5e-3), (4e-3, 4e-3, 4e-3), "pec")
    s = Session()
    s.new_project("P")
    s.project.designs[0] = d
    s.design = d
    r = dispatch(s, "boundary.autoRlc", dict(signal=[{"kind": "object", "name": "a"}],
                                             ground=[{"kind": "object", "name": "b"}],
                                             R=75.0, L=0.0, C=0.0))
    assert r["ok"] and r["faces"] > 0
    b = d.boundaries[-1]
    assert b.btype == "lumped_rlc" and b.params["R"] == 75.0
    assert abs(b.params["direction"][2]) == pytest.approx(1.0)


def test_a_saved_project_keeps_the_element_its_sheet_and_its_direction(tmp_path):
    from aether.gui.api import dispatch
    from aether.gui.state import Session
    d = ae.Design("m", units="mm")
    d.add_box("air", (-10e-3, -10e-3, -5e-3), (20e-3, 20e-3, 20e-3), "vacuum")
    d.add_box("a", (-2e-3, -2e-3, 0.0), (4e-3, 4e-3, 4e-3), "pec")
    d.add_box("b", (-2e-3, -2e-3, 5e-3), (4e-3, 4e-3, 4e-3), "pec")
    s = Session()
    s.new_project("P")
    s.project.designs[0] = d
    s.design = d
    dispatch(s, "boundary.autoRlc", dict(signal=[{"kind": "object", "name": "a"}],
                                         ground=[{"kind": "object", "name": "b"}],
                                         R="75", L="1.5n", C="0.2p", parallel=False))
    path = str(tmp_path / "rlc.warp")
    dispatch(s, "project.save", {"path": path})
    s2 = Session()
    dispatch(s2, "project.open", {"path": path})
    b = s2.design.boundaries[-1]
    assert b.btype == "lumped_rlc"
    assert b.params["R"] == pytest.approx(75.0) and b.params["L"] == pytest.approx(1.5e-9)
    assert b.params["C"] == pytest.approx(0.2e-12) and b.params["parallel"] is False
    assert abs(b.params["direction"][2]) == pytest.approx(1.0)
    assert any(x.name.endswith("_sheet") for x in s2.design.sheets)
