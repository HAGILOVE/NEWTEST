"""Ports made automatically from a marked signal and ground."""
import numpy as np
import pytest

import aether as ae
from aether.gui.state import Session

from conftest import needs_occ

pytestmark = [needs_occ]


def call(s, method, **params):
    from aether.gui.api import dispatch
    return dispatch(s, method, params)


def microstrip(strip_x=(0.0, 30.0)):
    """50 ohm-ish microstrip on a 1.6 mm substrate; the line runs out to the
    model boundary at both ends unless *strip_x* is shortened."""
    d = ae.Design("ms", units="mm")
    d.add_box("air", (0, -10e-3, -0.035e-3), (30e-3, 20e-3, 9.035e-3), "vacuum")
    d.add_box("sub", (0, -10e-3, 0), (30e-3, 20e-3, 1.6e-3), "vacuum")
    d.add_box("gnd", (0, -10e-3, -0.035e-3), (30e-3, 20e-3, 0.035e-3), "pec")
    d.add_box("strip", (strip_x[0] * 1e-3, -1.5e-3, 1.6e-3),
              ((strip_x[1] - strip_x[0]) * 1e-3, 3e-3, 0.035e-3), "pec")
    d.add_setup("S1", frequency="3GHz")
    return d


@pytest.fixture()
def session():
    s = Session()
    s.new_project("P")
    s.project.designs[0] = microstrip()
    s.design = s.project.designs[0]
    return s


SIG = {"kind": "object", "name": "strip"}
GND = {"kind": "object", "name": "gnd"}


def bounds_mm(shape):
    lo, hi = shape.bounds()
    return [round(float(v) * 1e3, 4) for v in list(lo) + list(hi)]


def test_a_lumped_port_bridges_strip_and_ground_at_the_line_end(session):
    r = call(session, "excitation.autoPort", kind="lumped", signal=[SIG], ground=[GND])
    assert r["ok"] and r["kind"] == "lumped" and r["faces"] > 0
    d = session.design
    port = d.get_port(r["name"])
    sheet = next(x for x in d.sheets if x.name == r["sheet"])
    b = bounds_mm(sheet.shape)
    # a vertical sheet across the strip width, from the strip down to the ground
    assert b[0] == b[3]                                    # one X: at the end of the line
    assert b[0] in (0.0, 30.0)
    assert b[1] == pytest.approx(-1.5, abs=1e-3) and b[4] == pytest.approx(1.5, abs=1e-3)
    assert b[2] == pytest.approx(0.0, abs=1e-3) and b[5] == pytest.approx(1.6, abs=1e-3)
    # the field runs from the signal (top) to the ground (below)
    assert port.direction[2] == pytest.approx(-1.0)
    s_pt, g_pt = port.integration_line
    assert s_pt[2] > g_pt[2]
    assert port.impedance == 50


def test_a_wave_port_covers_the_cross_section_and_gets_a_line(session):
    r = call(session, "excitation.autoPort", kind="wave", signal=[SIG], ground=[GND])
    assert r["ok"] and r["kind"] == "wave" and r["faces"] > 0 and r["onBoundary"]
    assert r["plane"] == "x" and r["at"] in (0.0, 0.03)
    port = session.design.get_port(r["name"])
    s_pt, g_pt = port.integration_line
    assert s_pt[2] == pytest.approx(1.6e-3, abs=1e-9) and g_pt[2] == pytest.approx(0.0, abs=1e-9)
    assert s_pt[0] == g_pt[0] == pytest.approx(r["at"])
    win = port.selector.window                             # (y range), (z range)
    assert win[0][0] == pytest.approx(-10e-3) and win[0][1] == pytest.approx(10e-3)   # clipped to the model
    # from the ground conductor up to 8 gaps above the strip (14.4 mm), clipped to the model top (9 mm)
    assert win[1][0] == pytest.approx(-0.035e-3, abs=1e-9) and win[1][1] == pytest.approx(9.0e-3, abs=1e-9)


def test_auto_chooses_wave_at_the_boundary_and_lumped_inside(session):
    assert call(session, "excitation.autoPort", kind="auto", signal=[SIG], ground=[GND])["kind"] == "wave"
    s2 = Session()
    s2.new_project("Q")
    s2.project.designs[0] = microstrip(strip_x=(5.0, 25.0))
    s2.design = s2.project.designs[0]
    assert call(s2, "excitation.autoPort", kind="auto", signal=[SIG], ground=[GND])["kind"] == "lumped"


def test_marks_are_set_shown_and_used_then_cleared(session):
    call(session, "portmarks.set", role="signal", picks=[SIG])
    call(session, "portmarks.set", role="ground", picks=[GND])
    items = call(session, "view.assignments")
    kinds = {i["type"] for i in items["items"]}
    assert {"mark-signal", "mark-ground"} <= kinds
    assert items["marks"] == {"signal": 1, "ground": 1}
    r = call(session, "excitation.autoPort", kind="lumped")        # uses the marks
    assert r["ok"]
    assert call(session, "view.assignments")["marks"] == {"signal": 0, "ground": 0}


def test_marking_an_object_for_the_other_role_moves_it(session):
    call(session, "portmarks.set", role="signal", picks=[SIG])
    call(session, "portmarks.set", role="ground", picks=[SIG])
    assert call(session, "view.assignments")["marks"] == {"signal": 0, "ground": 1}


def test_faces_work_as_picks(session):
    d = session.design
    strip_end = {"kind": "face", "object": "strip", "point": [0.0, 0.0, 1.6175e-3],
                 "normal": [-1, 0, 0], "lo": [0, -1.5e-3, 1.6e-3], "hi": [0, 1.5e-3, 1.635e-3],
                 "planar": True}
    gnd_end = {"kind": "face", "object": "gnd", "point": [0.0, 0.0, -0.0175e-3],
               "normal": [-1, 0, 0], "lo": [0, -10e-3, -0.035e-3], "hi": [0, 10e-3, 0.0],
               "planar": True}
    r = call(session, "excitation.autoPort", kind="auto", signal=[strip_end], ground=[gnd_end])
    assert r["kind"] == "wave" and r["at"] == pytest.approx(0.0, abs=1e-9)


def test_helpful_errors(session):
    with pytest.raises(ValueError, match="mark the signal"):
        call(session, "excitation.autoPort", kind="lumped")
    with pytest.raises(ValueError, match="gap"):
        call(session, "excitation.autoPort", kind="lumped", signal=[GND], ground=[GND])


def test_the_port_is_one_undo_step(session):
    call(session, "excitation.autoPort", kind="lumped", signal=[SIG], ground=[GND])
    assert len(session.design.ports) == 1 and len(session.design.sheets) == 1
    call(session, "edit.undo")
    assert not session.design.ports and not session.design.sheets


def test_a_second_port_on_the_same_line_goes_to_the_other_end(session):
    a = call(session, "excitation.autoPort", kind="wave", signal=[SIG], ground=[GND])
    b = call(session, "excitation.autoPort", kind="wave", signal=[SIG], ground=[GND])
    assert {round(a["at"], 9), round(b["at"], 9)} == {0.0, 0.03}
    assert a["faces"] > 0 and b["faces"] > 0


def test_the_end_can_be_forced(session):
    r = call(session, "excitation.autoPort", kind="lumped", signal=[SIG], ground=[GND], end="max")
    sheet = next(x for x in session.design.sheets if x.name == r["sheet"])
    assert bounds_mm(sheet.shape)[0] == 30.0


@pytest.mark.slow
def test_two_automatic_wave_ports_make_a_working_through_line():
    """The ports are right if the line they define transmits: a smoke test of
    S11 / S21 on a straight microstrip (coarse mesh, so loose limits)."""
    s = Session()
    s.new_project("P")
    s.project.designs[0] = microstrip()
    s.design = s.project.designs[0]
    for _ in range(2):
        call(s, "excitation.autoPort", kind="wave", signal=[SIG], ground=[GND])
    d = s.design
    d.assign_pec_outer("Walls")
    d.config.mesh.max_element_size = 3e-3
    d.setups[0].max_passes = 1
    d.setups[0].add_sweep("f", points=[3e9], count=1)
    sol = d.solve(adaptive=False, progress=False)
    S = sol.sparams.s[0]
    assert abs(S[1, 0]) > 0.7 and abs(S[0, 0]) < 0.6, np.abs(S)
