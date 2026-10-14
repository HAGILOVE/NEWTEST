"""
Release 1.7.8 — face operations, and the cost of importing a file.

* Sweep Face Along Normal was built exactly like Move Faces, so it grew the
  body instead of making the new one the command exists to make.
* Importing a CAD file meshed it twice — once to report each body's extent and
  once to draw it — and inspected it with two separate reads on top.
"""
import time

import numpy as np
import pytest

from conftest import needs_occ

from aether.gui.api import dispatch, state_json
from aether.gui.state import Session

pytestmark = needs_occ


@pytest.fixture
def sess():
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.draw",
             {"shape": "box", "name": "Box1",
              "params": {"position": ["0mm", "0mm", "0mm"],
                         "size": ["20mm", "10mm", "4mm"]}})
    return s


def top_face(s, name="Box1"):
    g = dispatch(s, "view.geometry", {})
    o = next(x for x in g["objects"] if x["name"] == name)
    f = max(o["faces"], key=lambda x: x["point"][2])
    return dict(f, object=name)


def zrange(s, name):
    g = dispatch(s, "view.geometry", {})
    o = next(x for x in g["objects"] if x["name"] == name)
    p = np.asarray(o["position"], float).reshape(-1, 3)
    return round(p[:, 2].min(), 9), round(p[:, 2].max(), 9)


# ------------------------------------------------- sweep versus move faces
def test_sweeping_a_face_makes_a_new_object(sess):
    r = dispatch(sess, "modeler.faceOperation",
                 {"op": "sweep", "distance": "3mm", "faces": [top_face(sess)]})
    assert r["newObject"] is True and r["from"] == "Box1"
    names = [o["name"] for o in state_json(sess)["design"]["objects"]]
    assert names == ["Box1", "Box1_Sweep"]


def test_the_swept_body_is_the_swept_volume_only(sess):
    dispatch(sess, "modeler.faceOperation",
             {"op": "sweep", "distance": "3mm", "faces": [top_face(sess)]})
    assert zrange(sess, "Box1") == pytest.approx((0.0, 0.004), abs=1e-9)
    assert zrange(sess, "Box1_Sweep") == pytest.approx((0.004, 0.007), abs=1e-9)


def test_the_body_the_face_belongs_to_is_untouched(sess):
    before = zrange(sess, "Box1")
    dispatch(sess, "modeler.faceOperation",
             {"op": "sweep", "distance": "2mm", "faces": [top_face(sess)]})
    assert zrange(sess, "Box1") == before


def test_the_swept_body_can_be_named(sess):
    dispatch(sess, "modeler.faceOperation",
             {"op": "sweep", "distance": "1mm", "newName": "Patch",
              "faces": [top_face(sess)]})
    assert "Patch" in [o["name"] for o in state_json(sess)["design"]["objects"]]


def test_the_swept_body_inherits_the_material(sess):
    dispatch(sess, "modeler.setProperty",
             {"name": "Box1", "prop": "material", "value": "copper"})
    dispatch(sess, "modeler.faceOperation",
             {"op": "sweep", "distance": "1mm", "faces": [top_face(sess)]})
    made = state_json(sess)["design"]["objects"][1]
    assert made["material"] == "copper"


def test_moving_a_face_still_grows_the_same_body(sess):
    r = dispatch(sess, "modeler.faceOperation",
                 {"op": "move", "distance": "3mm", "faces": [top_face(sess)]})
    assert r.get("newObject") is None
    assert len(state_json(sess)["design"]["objects"]) == 1
    assert zrange(sess, "Box1") == pytest.approx((0.0, 0.007), abs=1e-9)


def test_moving_a_face_inwards_still_trims(sess):
    dispatch(sess, "modeler.faceOperation",
             {"op": "move", "distance": "-1mm", "faces": [top_face(sess)]})
    assert len(state_json(sess)["design"]["objects"]) == 1
    assert zrange(sess, "Box1") == pytest.approx((0.0, 0.003), abs=1e-9)


def test_a_swept_body_can_be_swept_again(sess):
    dispatch(sess, "modeler.faceOperation",
             {"op": "sweep", "distance": "2mm", "faces": [top_face(sess)]})
    f = top_face(sess, "Box1_Sweep")
    dispatch(sess, "modeler.faceOperation",
             {"op": "sweep", "distance": "1mm", "faces": [f]})
    assert len(state_json(sess)["design"]["objects"]) == 3
    assert zrange(sess, "Box1_Sweep_Sweep") == pytest.approx((0.006, 0.007),
                                                             abs=1e-9)


# --------------------------------------------------------- import cost
@needs_occ
def test_inspecting_a_file_reads_and_meshes_it_once(tmp_path):
    """``probe`` used to call ``inspect`` and ``list_bodies``, each of which
    read the file and built its own surface mesh."""
    from aether.geometry import brep_io

    p = _two_body_step(tmp_path)
    reads = {"n": 0}
    real = brep_io.import_into_occ

    def counting(*a, **kw):
        reads["n"] += 1
        return real(*a, **kw)

    brep_io.import_into_occ = counting
    try:
        info = brep_io.probe(p, unit="auto", scale_to_m=1.0)
    finally:
        brep_io.import_into_occ = real
    assert reads["n"] == 1, f"{reads['n']} reads for one probe"
    assert info["solids"] == 2
    assert len(info["bodyList"]) == 2


@needs_occ
def test_the_import_mesh_is_kept_for_the_viewport(tmp_path):
    """The mesh built to measure the bodies is the mesh the viewport wants."""
    import aether.gui.tessellate as T

    p = _two_body_step(tmp_path)
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.importCad", {"path": p, "name": "A"})

    calls = {"n": 0}
    real_occ, real_bodies = T.tessellate_occ, T.tessellate_bodies

    def c1(*a, **kw):
        calls["n"] += 1
        return real_occ(*a, **kw)

    def c2(*a, **kw):
        calls["n"] += 1
        return real_bodies(*a, **kw)

    T.tessellate_occ, T.tessellate_bodies = c1, c2
    try:
        g = dispatch(s, "view.geometry", {})
    finally:
        T.tessellate_occ, T.tessellate_bodies = real_occ, real_bodies
    assert len(g["objects"]) == 2
    assert calls["n"] == 0, "the viewport re-meshed a file it had just meshed"


@needs_occ
def test_a_dxf_is_not_tessellated_twice(tmp_path):
    import aether.gui.tessellate as T
    from test_dxf import rect, write_dxf

    p = write_dxf(tmp_path / "d.dxf", rect(0, 0, 20, 10))
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.importCad", {"path": p, "name": "Sheet1"})
    calls = {"n": 0}
    real = T.tessellate_occ

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    T.tessellate_occ = counting
    try:
        dispatch(s, "view.geometry", {})
    finally:
        T.tessellate_occ = real
    assert calls["n"] == 0


def _two_body_step(tmp_path):
    """A STEP file with two solids, written through the exporter."""
    from aether.geometry.export import export_geometry
    from aether.model import Design

    d = Design("X")
    from aether.geometry import primitives as prim
    d.add_solid("A", prim.Box(position=(0, 0, 0), size=(0.01, 0.01, 0.01)))
    d.add_solid("B", prim.Box(position=(0.02, 0, 0), size=(0.01, 0.01, 0.01)))
    p = str(tmp_path / "two.step")
    export_geometry(d, p)
    return p
