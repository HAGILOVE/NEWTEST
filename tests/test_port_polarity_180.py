"""Ground / signal polarity of lumped ports."""
import numpy as np
import pytest

from conftest import needs_occ

pytestmark = [needs_occ, pytest.mark.slow]


@pytest.fixture()
def session():
    from aether.gui.state import Session
    from test_farfield_180 import dipole
    s = Session()
    s.new_project("Dipole")
    d = dipole()
    s.project.designs[0] = d
    s.design = d
    return s


def call(s, method, **params):
    from aether.gui.api import dispatch
    return dispatch(s, method, params)


def test_every_lumped_port_shows_its_ground_to_signal_arrow(session):
    items = call(session, "view.assignments")["items"]
    port = next(i for i in items if i["name"] == "P1")
    (g, sg), derived = port["line"], port.get("derived")
    assert derived                                       # implied by direction
    assert g[2] < 0 < sg[2]                              # ground low, signal high
    assert g[0] == pytest.approx(sg[0], abs=1e-9)


def test_geometry_command_reports_ends_and_extent(session):
    geo = call(session, "excitation.portGeometry", name="P1")
    assert geo["ground"][2] == pytest.approx(-1e-3, abs=1e-9)
    assert geo["signal"][2] == pytest.approx(1e-3, abs=1e-9)
    assert geo["derived"] is True


def test_reverse_swaps_the_ends_and_flips_the_field_direction(session):
    r = call(session, "excitation.setPolarity", name="P1", flip=True)
    assert r["direction"][2] == pytest.approx(-1.0)
    geo = call(session, "excitation.portGeometry", name="P1")
    assert geo["ground"][2] > geo["signal"][2] and geo["derived"] is False
    call(session, "excitation.setPolarity", name="P1", flip=True)    # and back
    assert session.design.get_port("P1").direction[2] == pytest.approx(1.0)


def test_polarity_edit_is_one_undo_step(session):
    call(session, "excitation.setPolarity", name="P1", flip=True)
    assert session.design.get_port("P1").direction[2] < 0
    call(session, "edit.undo")
    assert session.design.get_port("P1").direction[2] > 0


def test_assign_with_ground_and_signal_points(session):
    d = session.design
    d.ports.clear()
    call(session, "excitation.assign", kind="lumped", name="Q",
         selector={"kind": "box", "lo": ["-1.1mm", "-1e-3mm", "-1.1mm"],
                   "hi": ["1.1mm", "1e-3mm", "1.1mm"]},
         params={"impedance": 50, "ground": ["0mm", "0mm", "1mm"],
                 "signal": ["0mm", "0mm", "-1mm"]})
    p = d.get_port("Q")
    np.testing.assert_allclose(p.direction, [0, 0, -1], atol=1e-12)
    np.testing.assert_allclose(p.integration_line[0], [0, 0, 1e-3], atol=1e-12)
    with pytest.raises(ValueError, match="same"):
        call(session, "excitation.assign", kind="lumped", name="R",
             selector={"kind": "plane"},
             params={"ground": ["0mm"] * 3, "signal": ["0mm"] * 3})


def test_a_reversed_port_is_saved_and_reloaded(session, tmp_path):
    call(session, "excitation.setPolarity", name="P1", flip=True)
    path = str(tmp_path / "p.aedt")
    call(session, "project.save", path=path, withResults=False)
    from aether.gui.state import Session
    s2 = Session()
    call(s2, "project.open", path=path)
    p = s2.design.get_port("P1")
    assert p.direction[2] == pytest.approx(-1.0)
    assert p.integration_line[0][2] > p.integration_line[1][2]


def test_s11_of_a_one_port_does_not_depend_on_polarity(session):
    d = session.design
    a = d.solve(adaptive=False, progress=False).sparams.s[0, 0, 0]
    call(session, "excitation.setPolarity", name="P1", flip=True)
    b = d.solve(adaptive=False, progress=False).sparams.s[0, 0, 0]
    assert abs(a - b) < 1e-6
