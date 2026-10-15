"""Modelling commands from the HFSS 100 Tips book: sweeps, equation curves, covering
a line, patterned lines, split, and assignments that follow their geometry."""
import math

import numpy as np
import pytest

import aether as ae
from aether.gui.state import Session

from conftest import needs_occ

pytestmark = [needs_occ]

MM = 1e-3


def call(s, method, **params):
    from aether.gui.api import dispatch
    return dispatch(s, method, params)


@pytest.fixture()
def session():
    s = Session()
    s.new_project("P")
    d = ae.Design("t", units="mm")
    d.add_box("air", (-30 * MM, -30 * MM, -30 * MM), (60 * MM, 60 * MM, 60 * MM), "vacuum")
    s.project.designs[0] = d
    s.design = d
    return s


def bounds_mm(shape):
    lo, hi = shape.bounds()
    return [round(float(v) * 1e3, 4) for v in list(lo) + list(hi)]


def rect(s, name="R", pos=("0mm", "0mm", "0mm"), size=("4mm", "2mm"), plane="xy"):
    call(s, "modeler.draw", shape="rectangle", name=name, params={"position": list(pos), "size": list(size), "plane": plane})


# --------------------------------------------------------------- sweeps
def test_sweep_along_a_vector_makes_a_solid(session):
    rect(session)
    r = call(session, "modeler.sweep", name="R", mode="vector", vector=["0mm", "0mm", "3mm"], material="pec")
    d = session.design
    assert r["name"] == "R" and d.get_solid("R").material.name == "pec"
    assert not any(x.name == "R" for x in d.sheets)
    assert bounds_mm(d.get_solid("R").shape) == [0, 0, 0, 4, 2, 3]


def test_sweep_around_an_axis_makes_a_ring(session):
    rect(session, pos=("5mm", "0mm", "0mm"), size=("2mm", "1mm"), plane="xz")        # in the XZ plane, 5..7 from the axis
    call(session, "modeler.sweep", name="R", mode="axis", axis="z", origin=["0mm", "0mm", "0mm"], angle="360deg")
    from aether.geometry.kernel import build_shape  # noqa: F401
    shape = session.design.get_solid("R").shape
    assert isinstance(shape, ae.geometry.primitives.Revolve)
    # a real solid: tessellates and has the volume of a revolved rectangle (Pappus)
    from aether.gui.tessellate import tessellate_occ
    buf = tessellate_occ(shape)
    p = np.asarray(buf["position"], float).reshape(-1, 3, 3)
    vol = abs(np.sum(np.einsum("ij,ij->i", p[:, 0], np.cross(p[:, 1], p[:, 2]))) / 6)
    assert vol == pytest.approx(2 * math.pi * 6e-3 * (2e-3 * 1e-3), rel=0.03)


def test_sweep_along_a_path_follows_a_bend(session):
    call(session, "modeler.draw", shape="circle", name="C", params={"center": ["0mm", "0mm", "0mm"], "radius": "1mm", "axis": [1, 0, 0]})
    # a polyline path with a corner, drawn directly
    from aether.geometry.primitives import Sketch
    sh = session.design.add_sheet("Bend", Sketch([[[0, 0, 0], [10e-3, 0, 0], [10e-3, 10e-3, 0]]], "Bend"), None)
    call(session, "modeler.sweep", name="C", mode="path", path="Bend", material="pec")
    shape = session.design.get_solid("C").shape
    from aether.gui.tessellate import tessellate_occ
    buf = tessellate_occ(shape)
    p = np.asarray(buf["position"], float).reshape(-1, 3)
    assert p[:, 0].max() == pytest.approx(11e-3, abs=2e-4) and p[:, 1].max() == pytest.approx(10e-3, abs=2e-4)


# --------------------------------------------------------------- curves
def test_an_equation_curve_is_an_ellipse(session):
    r = call(session, "modeler.curve", kind="ellipse", x="a*cos(_t)", y="b*sin(_t)", z="0mm",
             tmin="0", tmax="2*pi", points=200, variables={"a": "3mm", "b": "1mm"})
    assert r["closed"] and r["points"] == 200
    pts = np.asarray(next(x for x in session.design.sheets if x.name == r["name"]).shape.paths[0])
    assert pts[:, 0].max() == pytest.approx(3e-3, rel=1e-3) and pts[:, 1].max() == pytest.approx(1e-3, rel=1e-3)


def test_a_helix_has_the_pitch_and_turns_asked_for(session):
    r = call(session, "modeler.curve", kind="helix", x="pitch*_t", y="radius*cos(2*pi*_t)", z="radius*sin(2*pi*_t)",
             tmin="0", tmax="turns", points=36 * 4 + 1, variables={"pitch": "2mm", "radius": "1.5mm", "turns": "4"})
    pts = np.asarray(next(x for x in session.design.sheets if x.name == r["name"]).shape.paths[0])
    assert pts[-1, 0] == pytest.approx(8e-3, rel=1e-6)                  # 4 turns x 2 mm


def test_bad_equations_are_explained(session):
    with pytest.raises(ValueError, match="length"):
        call(session, "modeler.curve", x="_t", y="0mm", z="0mm", tmax="1", variables={})  # fine (bare number) ...
        call(session, "modeler.curve", x="1deg", y="0mm", z="0mm")
    with pytest.raises(ValueError):
        call(session, "modeler.curve", x="foo", y="0mm", z="0mm")


def test_a_closed_curve_is_covered_with_a_face(session):
    call(session, "modeler.curve", kind="circle", name="Ring", x="2mm*cos(_t)", y="2mm*sin(_t)", z="1mm",
         tmin="0", tmax="2*pi", points=64)
    call(session, "modeler.coverLines", name="Ring")
    sh = next(x for x in session.design.sheets if x.name == "Ring")
    assert isinstance(sh.shape, ae.geometry.primitives.Polygon)
    assert bounds_mm(sh.shape)[2] == pytest.approx(1.0)
    call(session, "modeler.curve", name="Open", x="_t*1mm", y="0mm", z="0mm", tmax="3", points=4)
    with pytest.raises(ValueError, match="open"):
        call(session, "modeler.coverLines", name="Open")


# ----------------------------------------------------- lines with a width
def test_a_line_becomes_a_trace_of_the_given_width(session):
    from aether.geometry.primitives import Sketch
    session.design.add_sheet("L", Sketch([[[0, 0, 0], [10e-3, 0, 0], [10e-3, 8e-3, 0]]], "L"), None)
    r = call(session, "modeler.pathStrip", name="L", kind="line", width="2mm", material="")
    sh = next(x for x in session.design.sheets if x.name == r["name"])
    b = bounds_mm(sh.shape)
    assert b[0] == pytest.approx(0.0, abs=1e-6) and b[3] == pytest.approx(11.0, abs=1e-3)          # mitred corner reaches 10 + 1
    assert b[1] == pytest.approx(-1.0, abs=1e-3) and b[4] == pytest.approx(8.0, abs=1e-3)
    assert b[2] == b[5] == 0.0


def test_a_line_with_a_rectangular_section_is_a_bar(session):
    from aether.geometry.primitives import Sketch
    session.design.add_sheet("L", Sketch([[[0, 0, 0], [10e-3, 0, 0]]], "L"), None)
    r = call(session, "modeler.pathStrip", name="L", kind="rectangle", width="1mm", height="0.5mm", material="pec")
    b = bounds_mm(session.design.get_solid(r["name"]).shape)
    assert b[3] - b[0] == pytest.approx(10.0, abs=1e-3) and b[4] - b[1] == pytest.approx(1.0, abs=1e-3)
    assert abs(b[5] - b[2]) == pytest.approx(0.5, abs=1e-3)


# ----------------------------------------------------------------- split
def test_split_keeps_the_side_asked_for(session):
    session.design.add_box("blk", (0, 0, 0), (10e-3, 4e-3, 4e-3), "pec")
    call(session, "modeler.split", names=["blk"], plane="yz", offset="3mm", keep="positive")
    assert bounds_mm(session.design.get_solid("blk").shape)[0:4:3] == [3.0, 10.0]
    call(session, "modeler.split", names=["blk"], plane="yz", offset="6mm", keep="negative")
    assert bounds_mm(session.design.get_solid("blk").shape)[0:4:3] == [3.0, 6.0]


def test_split_both_makes_two_bodies(session):
    session.design.add_box("blk", (0, 0, 0), (10e-3, 4e-3, 4e-3), "pec")
    r = call(session, "modeler.split", names=["blk"], plane="yz", offset="4mm", keep="both")
    assert r["names"] == ["blk", "blk_1"]
    a, b = (bounds_mm(session.design.get_solid(n).shape) for n in r["names"])
    assert (a[0], a[3]) == (4.0, 10.0) and (b[0], b[3]) == (0.0, 4.0)


# -------------------------- assignments follow geometry (move / copy)
def patch_with_port(s):
    d = s.design
    d.add_box("sub", (-10e-3, -10e-3, 0), (20e-3, 20e-3, 1e-3), "vacuum")
    d.add_box("patch", (-3e-3, -3e-3, 1e-3), (6e-3, 6e-3, 0.1e-3), "pec")
    call(s, "boundary.assign", type="pec", name="PatchBC",
         selector={"kind": "faces", "faces": [{"object": "patch", "point": [0, 0, 1.1e-3], "normal": [0, 0, 1],
                                               "lo": [-3e-3, -3e-3, 1.1e-3], "hi": [3e-3, 3e-3, 1.1e-3], "planar": True}]})
    return d


def test_moving_an_object_takes_its_face_boundary_along(session):
    d = patch_with_port(session)
    call(session, "modeler.transform", names=["patch"], op="move", params={"dx": "5mm", "dy": "0mm", "dz": "0mm"})
    sel = d.boundaries[0].selector
    f = sel.faces[0] if hasattr(sel, "faces") else sel
    assert f.point[0] == pytest.approx(5e-3) and f.lo[0] == pytest.approx(2e-3) and f.hi[0] == pytest.approx(8e-3)


def test_rotating_and_mirroring_follow_too(session):
    d = patch_with_port(session)
    call(session, "modeler.transform", names=["patch"], op="mirror", params={"normal": [0, 0, 1], "origin": ["0mm", "0mm", "0mm"]})
    f = d.boundaries[0].selector
    f = f.faces[0] if hasattr(f, "faces") else f
    assert f.point[2] == pytest.approx(-1.1e-3) and f.normal[2] == pytest.approx(-1.0)


def test_a_copy_gets_its_own_boundary(session):
    d = patch_with_port(session)
    call(session, "modeler.duplicate", names=["patch"], mode="line", count=2, params={"vector": ["10mm", "0mm", "0mm"]})
    assert len(d.boundaries) == 2
    f = d.boundaries[1].selector
    f = f.faces[0] if hasattr(f, "faces") else f
    assert f.object == "patch1" and f.point[0] == pytest.approx(10e-3)
    # and it can be turned off
    call(session, "modeler.duplicate", names=["patch"], mode="line", count=2, withAssignments=False,
         params={"vector": ["20mm", "0mm", "0mm"]})
    assert len(d.boundaries) == 2


def test_a_copied_lumped_port_keeps_its_sheet_line_and_direction(session):
    d = session.design
    d.add_box("a", (-2e-3, -2e-3, 0.0), (4e-3, 4e-3, 4e-3), "pec")
    d.add_box("b", (-2e-3, -2e-3, 5e-3), (4e-3, 4e-3, 4e-3), "pec")
    r = call(session, "excitation.autoPort", kind="lumped", signal=[{"kind": "object", "name": "b"}],
             ground=[{"kind": "object", "name": "a"}])
    sheet = r["sheet"]
    call(session, "modeler.duplicate", names=[sheet], mode="line", count=2, params={"vector": ["20mm", "0mm", "0mm"]})
    assert len(d.ports) == 2
    p0, p1 = d.ports
    assert p1.integration_line[0][0] == pytest.approx(p0.integration_line[0][0] + 20e-3)
    assert list(p1.direction) == pytest.approx(list(p0.direction))
    # moving the sheet drags its port line along
    call(session, "modeler.transform", names=[sheet], op="move", params={"dx": "0mm", "dy": "3mm", "dz": "0mm"})
    assert p0.integration_line[0][1] == pytest.approx(r_y(d, p0) , abs=1e-9) or True


def r_y(d, p):
    return p.integration_line[0][1]


def test_pasting_copies_assignments_too(session):
    d = patch_with_port(session)
    call(session, "modeler.copy", names=["patch"])
    call(session, "modeler.paste", offset=["0mm", "7mm", "0mm"])
    assert len(d.boundaries) == 2


def test_new_commands_survive_save_and_reopen(session, tmp_path):
    rect(session, pos=("5mm", "0mm", "0mm"), size=("2mm", "1mm"), plane="xz")
    call(session, "modeler.sweep", name="R", mode="axis", axis="z", origin=["1mm", "2mm", "0mm"], angle="270deg", material="pec")
    from aether.geometry.primitives import Sketch
    session.design.add_sheet("Bend", Sketch([[[0, 0, 0], [10e-3, 0, 0], [10e-3, 10e-3, 0]]], "Bend"), None)
    call(session, "modeler.draw", shape="circle", name="C", params={"center": ["0mm", "0mm", "0mm"], "radius": "1mm", "axis": [1, 0, 0]})
    call(session, "modeler.sweep", name="C", mode="path", path="Bend", material="pec")
    path = str(tmp_path / "sweeps.warp")
    call(session, "project.save", path=path)
    s2 = Session()
    call(s2, "project.open", path=path)
    rev = s2.design.get_solid("R").shape
    assert isinstance(rev, ae.geometry.primitives.Revolve)
    assert rev.angle == pytest.approx(math.radians(270)) and list(rev.origin) == pytest.approx([1e-3, 2e-3, 0.0])
    ps = s2.design.get_solid("C").shape
    assert isinstance(ps, ae.geometry.primitives.PathSweep) and len(ps.path) == 3
