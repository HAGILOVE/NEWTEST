"""Relative coordinate systems: create, work in, save, undo-safe."""
import pytest

import aether as ae
from aether.gui.state import Session
from aether.io.warp.translate import read_project
from aether.io.warp.writer import write_project


def call(s, method, **params):
    from aether.gui.api import dispatch
    return dispatch(s, method, params)


@pytest.fixture()
def session():
    s = Session()
    s.new_project("P")
    return s


def test_a_relative_cs_is_created_from_a_point_and_becomes_the_working_system(session):
    r = call(session, "cs.create", origin=["10mm", "0mm", "1.6mm"])
    assert r["name"] == "RelativeCS1"
    d = session.design
    assert d.working_cs == "RelativeCS1"
    assert d.working_origin() == pytest.approx((0.01, 0.0, 0.0016))
    r2 = call(session, "cs.create", origin=[0.0, 0.0, 0.0], setWorking=False)
    assert r2["name"] == "RelativeCS2" and d.working_cs == "RelativeCS1"


def test_working_cs_can_be_switched_back_to_global(session):
    call(session, "cs.create", origin=["5mm", "5mm", "5mm"])
    call(session, "cs.setWorking", name="Global")
    assert session.design.working_origin() == (0.0, 0.0, 0.0)
    with pytest.raises(KeyError):
        call(session, "cs.setWorking", name="nope")


def test_names_are_checked(session):
    call(session, "cs.create", name="Feed", origin=[0, 0, 0])
    with pytest.raises(ValueError):
        call(session, "cs.create", name="Feed", origin=[1, 0, 0])
    with pytest.raises(ValueError):
        call(session, "cs.create", name="Global", origin=[1, 0, 0])
    call(session, "cs.rename", name="Feed", newName="Patch")
    assert session.design.working_cs == "Patch"
    call(session, "cs.delete", name="Patch")
    assert session.design.working_cs == "" and not session.design.coordinate_systems


def test_the_design_json_lists_them(session):
    from aether.gui.api import _design_json
    call(session, "cs.create", name="A", origin=["1mm", "2mm", "3mm"])
    j = _design_json(session)
    assert j["coordSystems"] == [{"name": "A", "origin": pytest.approx([1e-3, 2e-3, 3e-3])}]
    assert j["workingCs"] == "A"


def test_coordinate_systems_are_saved_and_reopened(session, tmp_path):
    call(session, "cs.create", name="A", origin=["1mm", "2mm", "3mm"])
    call(session, "cs.create", name="B", origin=["4mm", "5mm", "6mm"])
    path = str(tmp_path / "p.warp")
    write_project(path, session.project)
    d2 = read_project(path)[0][0]
    assert [c["name"] for c in d2.coordinate_systems] == ["A", "B"]
    assert d2.get_coordinate_system("B")["origin"] == pytest.approx((4e-3, 5e-3, 6e-3))
    assert d2.working_cs == "B"


def test_an_undo_of_another_edit_keeps_the_coordinate_systems(session):
    call(session, "cs.create", name="A", origin=["1mm", "2mm", "3mm"])
    call(session, "modeler.draw", shape="box", name="b",
         params={"position": ["0mm", "0mm", "0mm"], "size": ["1mm", "1mm", "1mm"]})
    call(session, "edit.undo")
    assert [c["name"] for c in session.design.coordinate_systems] == ["A"]
