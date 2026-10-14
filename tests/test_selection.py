"""
Selection, and everything that hangs off it.

Picking a face is not a UI nicety: it is how a boundary, a port, a mesh
refinement or a face sweep is told *where*. So these tests check the whole
chain — the tessellator giving each triangle a face, the selector rebuilding
that face from geometry, the mesher tagging exactly those triangles, and the
modeller sweeping exactly that face.
"""
import numpy as np
import pytest

from conftest import needs_occ

import aether as ae
from aether.geometry.select import FaceSelector
from aether.gui.api import dispatch, state_json
from aether.gui.state import Session
from aether.gui.tessellate import tessellate, tessellate_analytic

pytestmark = needs_occ


@pytest.fixture()
def sess():
    s = Session()
    s.new_project("SelTest")
    dispatch(s, "modeler.draw", {"shape": "box", "name": "Box1",
                                 "params": {"position": ["0mm", "0mm", "0mm"],
                                            "size": ["20mm", "10mm", "4mm"]}})
    return s


def faces(s, name="Box1"):
    g = dispatch(s, "view.geometry", {})
    o = [x for x in g["objects"] if x["name"] == name][0]
    return [dict(f, object=name) for f in o["faces"]]


def top_face(s, name="Box1"):
    return max(faces(s, name), key=lambda f: f["point"][2])


# ------------------------------------------------------ face identification
def test_a_box_tessellates_into_exactly_six_faces(sess):
    f = faces(sess)
    assert len(f) == 6
    assert sorted(round(x["area"] * 1e6, 3) for x in f) == \
        [40.0, 40.0, 80.0, 80.0, 200.0, 200.0]


def test_every_triangle_belongs_to_a_face(sess):
    g = dispatch(sess, "view.geometry", {})
    o = g["objects"][0]
    assert len(o["faceOf"]) == o["count"] // 3
    assert set(o["faceOf"]) == set(range(len(o["faces"])))


def test_a_curved_face_is_one_face_and_says_it_is_curved():
    t = tessellate(ae.Cylinder((0, 0, 0), "2mm", "6mm"))
    assert len(t["faces"]) == 3                     # wall + two caps
    curved = [f for f in t["faces"] if not f["planar"]]
    assert len(curved) == 1


def test_the_analytic_fallback_finds_the_same_faces():
    """No CAD kernel installed still has to give a usable face pick."""
    for shape, n in ((ae.Box((0, 0, 0), ("2mm", "3mm", "4mm")), 6),
                     (ae.Cylinder((0, 0, 0), "1mm", "5mm"), 3),
                     (ae.Sphere((0, 0, 0), "1mm"), 1)):
        assert len(tessellate_analytic(shape)["faces"]) == n


def test_faces_carry_the_outline_that_highlights_them(sess):
    g = dispatch(sess, "view.geometry", {})
    o = g["objects"][0]
    assert len(o["faceEdges"]) % 3 == 0
    owners = set(o["faceEdges"][2::3])
    assert owners == set(range(6))      # every face has an outline


# -------------------------------------------------------------- selecting
def test_the_session_carries_the_pick(sess):
    t = top_face(sess)
    dispatch(sess, "modeler.selectMode", {"mode": "face"})
    dispatch(sess, "modeler.select", {"faces": [t]})
    st = state_json(sess)
    assert st["selMode"] == "face"
    assert len(st["selFaces"]) == 1
    info = dispatch(sess, "modeler.selectionInfo", {})
    assert info["faces"] == 1
    assert info["faceArea"] == pytest.approx(200e-6)


def test_switching_mode_drops_picks_of_the_other_kind(sess):
    dispatch(sess, "modeler.select", {"faces": [top_face(sess)],
                                      "mode": "face"})
    dispatch(sess, "modeler.selectMode", {"mode": "object"})
    assert state_json(sess)["selFaces"] == []


def test_add_extends_the_selection(sess):
    f = faces(sess)
    dispatch(sess, "modeler.select", {"faces": [f[0]], "mode": "face"})
    dispatch(sess, "modeler.select", {"faces": [f[1]], "add": True})
    assert len(state_json(sess)["selFaces"]) == 2


def test_an_unknown_mode_is_refused(sess):
    with pytest.raises(ValueError):
        dispatch(sess, "modeler.selectMode", {"mode": "vertex"})


# ------------------------------------------- assignments to picked faces
def _tagged_area(mesh, name):
    idx = mesh.bc_faces[name]
    v = mesh.nodes[mesh.surf_tris[idx]]
    return 0.5 * np.linalg.norm(np.cross(v[:, 1] - v[:, 0],
                                         v[:, 2] - v[:, 0]), axis=1).sum()


@pytest.mark.parametrize("which, area", [("top", 200e-6), ("side", 40e-6)])
def test_a_boundary_on_a_picked_face_tags_exactly_that_face(sess, which, area):
    f = faces(sess)
    pick = (max(f, key=lambda x: x["point"][2]) if which == "top"
            else min(f, key=lambda x: x["point"][0]))
    dispatch(sess, "boundary.assign",
             {"type": "pec", "name": "PerfE1",
              "selector": {"kind": "faces", "faces": [pick]}})
    d = sess.design
    d.add_setup("S", frequency="10GHz")
    m = d.generate_mesh(1e10, force=True, size=0.0015)
    assert _tagged_area(m, "PerfE1") == pytest.approx(area, rel=1e-6)


def test_two_picked_faces_assign_as_one_boundary(sess):
    f = faces(sess)
    picks = [max(f, key=lambda x: x["point"][2]),
             min(f, key=lambda x: x["point"][2])]
    dispatch(sess, "boundary.assign",
             {"type": "pec", "name": "PerfE1",
              "selector": {"kind": "faces", "faces": picks}})
    d = sess.design
    d.add_setup("S", frequency="10GHz")
    m = d.generate_mesh(1e10, force=True, size=0.0015)
    assert _tagged_area(m, "PerfE1") == pytest.approx(400e-6, rel=1e-6)


def test_the_boundary_says_what_it_is_attached_to(sess):
    dispatch(sess, "boundary.assign",
             {"type": "pec", "name": "PerfE1",
              "selector": {"kind": "faces", "faces": [top_face(sess)]}})
    st = state_json(sess)
    assert "face" in st["design"]["boundaries"][0]["selector"]["label"].lower()


def test_assigning_with_nothing_picked_is_refused(sess):
    with pytest.raises(ValueError):
        dispatch(sess, "boundary.assign",
                 {"type": "pec", "selector": {"kind": "faces", "faces": []}})


def test_a_face_selector_survives_a_change_of_mesh_size(sess):
    """The reason a pick stores geometry and not a face index."""
    dispatch(sess, "boundary.assign",
             {"type": "pec", "name": "PerfE1",
              "selector": {"kind": "faces", "faces": [top_face(sess)]}})
    d = sess.design
    d.add_setup("S", frequency="10GHz")
    areas = []
    for h in (0.003, 0.0012):
        m = d.generate_mesh(1e10, force=True, size=h)
        areas.append(_tagged_area(m, "PerfE1"))
    assert areas[0] == pytest.approx(200e-6, rel=1e-6)
    assert areas[1] == pytest.approx(200e-6, rel=1e-6)


# ---------------------------------------------------------- mesh operations
def test_a_mesh_operation_on_an_object_refines_it(sess):
    d = sess.design
    d.add_setup("S", frequency="10GHz")
    coarse = d.generate_mesh(1e10, force=True, size=0.004).n_tets
    dispatch(sess, "mesh.addOperation",
             {"name": "Fine", "maxLength": "1mm", "objects": ["Box1"]})
    fine = d.generate_mesh(1e10, force=True, size=0.004).n_tets
    assert fine > coarse * 3


def test_a_mesh_operation_on_a_picked_face_refines_that_face(sess):
    d = sess.design
    d.add_setup("S", frequency="10GHz")
    coarse = d.generate_mesh(1e10, force=True, size=0.004).n_tets
    dispatch(sess, "modeler.select", {"faces": [top_face(sess)], "mode": "face"})
    dispatch(sess, "mesh.addOperation", {"name": "Face1", "maxLength": "1mm"})
    fine = d.generate_mesh(1e10, force=True, size=0.004)
    assert fine.n_tets > coarse
    # and it is local: the picked face carries far more triangles than the
    # opposite one, which nothing asked to refine
    cen = fine.surf_centroids
    on_top = (cen[:, 2] > 3.9e-3).sum()
    on_bottom = (cen[:, 2] < 0.1e-3).sum()
    assert on_top > on_bottom * 3


def test_a_disabled_mesh_operation_does_nothing(sess):
    d = sess.design
    d.add_setup("S", frequency="10GHz")
    base = d.generate_mesh(1e10, force=True, size=0.004).n_tets
    dispatch(sess, "mesh.addOperation",
             {"name": "Fine", "maxLength": "1mm", "objects": ["Box1"]})
    dispatch(sess, "mesh.setOperation", {"name": "Fine", "enabled": False})
    assert d.generate_mesh(1e10, force=True, size=0.004).n_tets == base


def test_mesh_operations_are_named_and_listed(sess):
    dispatch(sess, "mesh.addOperation", {"maxLength": "1mm",
                                         "objects": ["Box1"]})
    dispatch(sess, "mesh.addOperation", {"maxLength": "2mm",
                                         "objects": ["Box1"]})
    ops = state_json(sess)["design"]["meshOps"]
    assert [o["name"] for o in ops] == ["Length1", "Length2"]
    assert ops[0]["where"] == "Box1"


def test_a_mesh_operation_can_be_edited_and_deleted(sess):
    dispatch(sess, "mesh.addOperation", {"name": "Fine", "maxLength": "1mm",
                                         "objects": ["Box1"]})
    dispatch(sess, "mesh.setOperation", {"name": "Fine", "maxLength": "0.5mm"})
    assert sess.design.mesh_ops[0].max_length == pytest.approx(0.5e-3)
    dispatch(sess, "mesh.deleteOperation", {"name": "Fine"})
    assert sess.design.mesh_ops == []


def test_a_mesh_operation_needs_a_target_and_a_length(sess):
    with pytest.raises(Exception):
        sess.design.add_mesh_operation("X", "0mm", objects=["Box1"])
    with pytest.raises(KeyError):
        sess.design.add_mesh_operation("Y", "1mm", objects=["Nope"])


def test_mesh_operations_survive_undo(sess):
    dispatch(sess, "mesh.addOperation", {"name": "Fine", "maxLength": "1mm",
                                         "objects": ["Box1"]})
    dispatch(sess, "modeler.transform", {"names": ["Box1"], "op": "move",
                                         "params": {"dz": "1mm"}})
    dispatch(sess, "edit.undo", {})
    assert [m.name for m in sess.design.mesh_ops] == ["Fine"]


# -------------------------------------------------------- face modelling
def test_sweeping_a_face_along_its_normal_makes_a_new_body(sess):
    """Sweep and Move Faces are two commands, not one. Sweeping turns the
    face into an object of its own and leaves the body it came from alone;
    growing the body is what Move Faces is for."""
    dispatch(sess, "modeler.select", {"faces": [top_face(sess)], "mode": "face"})
    dispatch(sess, "modeler.faceOperation", {"op": "sweep", "distance": "3mm"})
    assert [o.name for o in sess.design.solids] == ["Box1", "Box1_Sweep"]
    lo, hi = sess.design.get_solid("Box1").shape.bounds()
    assert hi[2] == pytest.approx(4e-3, abs=1e-9)      # unchanged
    g = dispatch(sess, "view.geometry", {})
    made = next(x for x in g["objects"] if x["name"] == "Box1_Sweep")
    z = np.asarray(made["position"]).reshape(-1, 3)[:, 2]
    assert z.min() == pytest.approx(4e-3, abs=1e-9)
    assert z.max() == pytest.approx(7e-3, abs=1e-9)
    assert len(made["faces"]) == 6                     # one clean body


def test_moving_a_face_outward_grows_the_body(sess):
    dispatch(sess, "modeler.select", {"faces": [top_face(sess)], "mode": "face"})
    dispatch(sess, "modeler.faceOperation", {"op": "move", "distance": "3mm"})
    assert [o.name for o in sess.design.solids] == ["Box1"]
    lo, hi = sess.design.get_solid("Box1").shape.bounds()
    assert hi[2] == pytest.approx(7e-3, abs=1e-9)
    assert len(faces(sess)) == 6


def test_moving_a_face_inward_trims_the_body(sess):
    dispatch(sess, "modeler.select", {"faces": [top_face(sess)], "mode": "face"})
    dispatch(sess, "modeler.faceOperation", {"op": "move", "distance": "-1mm"})
    g = dispatch(sess, "view.geometry", {})
    pts = np.asarray(g["objects"][0]["position"]).reshape(-1, 3)
    assert pts[:, 2].max() == pytest.approx(3e-3, abs=1e-6)


def test_a_face_operation_keeps_the_object_and_its_boundary(sess):
    dispatch(sess, "boundary.assign",
             {"type": "pec", "name": "PerfE1",
              "selector": {"kind": "object", "object": "Box1"}})
    o_before = sess.design.get_solid("Box1")
    dispatch(sess, "modeler.select", {"faces": [top_face(sess)], "mode": "face"})
    dispatch(sess, "modeler.faceOperation", {"op": "move", "distance": "2mm"})
    assert sess.design.get_solid("Box1") is o_before
    assert len(sess.design.boundaries) == 1


def test_a_face_operation_is_one_undo_step(sess):
    dispatch(sess, "modeler.select", {"faces": [top_face(sess)], "mode": "face"})
    dispatch(sess, "modeler.faceOperation", {"op": "move", "distance": "3mm"})
    dispatch(sess, "edit.undo", {})
    lo, hi = sess.design.get_solid("Box1").shape.bounds()
    assert hi[2] == pytest.approx(4e-3, abs=1e-9)


def test_a_sweep_is_one_undo_step_too(sess):
    dispatch(sess, "modeler.select", {"faces": [top_face(sess)], "mode": "face"})
    dispatch(sess, "modeler.faceOperation", {"op": "sweep", "distance": "3mm"})
    assert len(sess.design.solids) == 2
    dispatch(sess, "edit.undo", {})
    assert [o.name for o in sess.design.solids] == ["Box1"]


def test_a_face_operation_with_no_pick_is_refused(sess):
    with pytest.raises(ValueError):
        dispatch(sess, "modeler.faceOperation", {"op": "sweep",
                                                 "distance": "1mm"})


def test_faces_on_two_objects_at_once_are_refused(sess):
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "Box2",
                                    "params": {"position": ["40mm", "0mm", "0mm"],
                                               "size": ["5mm", "5mm", "5mm"]}})
    picks = [top_face(sess, "Box1"), top_face(sess, "Box2")]
    with pytest.raises(ValueError):
        dispatch(sess, "modeler.faceOperation",
                 {"op": "sweep", "distance": "1mm", "faces": picks})


def test_a_swept_body_can_be_meshed_and_assigned(sess):
    dispatch(sess, "modeler.select", {"faces": [top_face(sess)], "mode": "face"})
    dispatch(sess, "modeler.faceOperation", {"op": "move", "distance": "2mm"})
    dispatch(sess, "boundary.assign",
             {"type": "pec", "name": "PerfE1",
              "selector": {"kind": "faces", "faces": [top_face(sess)]}})
    d = sess.design
    d.add_setup("S", frequency="10GHz")
    m = d.generate_mesh(1e10, force=True, size=0.002)
    assert _tagged_area(m, "PerfE1") == pytest.approx(200e-6, rel=1e-6)


def test_a_face_operation_round_trips_through_a_project_file(sess, tmp_path):
    dispatch(sess, "modeler.select", {"faces": [top_face(sess)], "mode": "face"})
    dispatch(sess, "modeler.faceOperation", {"op": "move", "distance": "3mm"})
    p = str(tmp_path / "swept.aedt")
    dispatch(sess, "project.save", {"path": p})
    s2 = Session()
    dispatch(s2, "project.open", {"path": p})
    sh = s2.design.get_solid("Box1").shape
    assert type(sh).__name__ == "FaceOperation"
    assert sh.distance == pytest.approx(3e-3)
    assert sh.bounds()[1][2] == pytest.approx(7e-3, abs=1e-9)


def test_a_swept_body_round_trips_through_a_project_file(sess, tmp_path):
    dispatch(sess, "modeler.select", {"faces": [top_face(sess)], "mode": "face"})
    dispatch(sess, "modeler.faceOperation", {"op": "sweep", "distance": "3mm"})
    p = str(tmp_path / "sweptnew.aedt")
    dispatch(sess, "project.save", {"path": p})
    s2 = Session()
    dispatch(s2, "project.open", {"path": p})
    assert [o.name for o in s2.design.solids] == ["Box1", "Box1_Sweep"]
    g = dispatch(s2, "view.geometry", {})
    made = next(x for x in g["objects"] if x["name"] == "Box1_Sweep")
    z = np.asarray(made["position"]).reshape(-1, 3)[:, 2]
    assert z.min() == pytest.approx(4e-3, abs=1e-6)
    assert z.max() == pytest.approx(7e-3, abs=1e-6)


# --------------------------------------- face operations on imported bodies
@pytest.fixture()
def step_rod(tmp_path):
    from aether.geometry.brep_io import export_shapes
    from aether.geometry.kernel import GmshSession, build_shape
    path = str(tmp_path / "rod.step")
    with GmshSession("mk") as gmsh:
        build_shape(ae.Cylinder((0, 0, 0), "5mm", "10mm"), gmsh)
        gmsh.model.occ.synchronize()
        export_shapes(path, gmsh)
    return path


def test_an_imported_body_reports_its_true_extent(step_rod):
    """OpenCASCADE's own bounding box is built from surface control points and
    a circle drawn as three arcs reaches twice its radius: a 10 mm rod used to
    report a 30 mm box, and the camera framed mostly empty space."""
    from aether.geometry.brep_io import quick_bounds
    lo, hi = quick_bounds(step_rod)
    assert np.allclose(hi, [5e-3, 5e-3, 10e-3], atol=2e-5)
    assert np.allclose(lo, [-5e-3, -5e-3, 0.0], atol=2e-5)


def test_an_analytic_cylinder_bounds_only_where_it_reaches():
    lo, hi = ae.Cylinder((0, 0, 0), "5mm", "10mm").bounds()
    assert np.allclose(lo, [-5e-3, -5e-3, 0.0])
    assert np.allclose(hi, [5e-3, 5e-3, 10e-3])


def test_a_face_of_an_imported_body_sweeps(sess, step_rod):
    dispatch(sess, "modeler.importCad", {"path": step_rod, "name": "Rod"})
    cap = max(faces(sess, "Rod"), key=lambda f: f["point"][2])
    dispatch(sess, "modeler.select", {"faces": [cap], "mode": "face"})
    dispatch(sess, "modeler.faceOperation", {"op": "sweep", "distance": "2mm"})
    assert [o.name for o in sess.design.solids][-2:] == ["Rod", "Rod_Sweep"]
    g = dispatch(sess, "view.geometry", {})
    made = next(x for x in g["objects"] if x["name"] == "Rod_Sweep")
    p = np.asarray(made["position"]).reshape(-1, 3)
    assert p[:, 2].min() == pytest.approx(10e-3, abs=2e-5)
    assert p[:, 2].max() == pytest.approx(12e-3, abs=2e-5)
    assert p[:, 0].max() == pytest.approx(5e-3, abs=2e-4)   # not widened


def test_sweeping_a_curved_face_is_refused_with_a_reason(sess, step_rod):
    dispatch(sess, "modeler.importCad", {"path": step_rod, "name": "Rod"})
    wall = [f for f in faces(sess, "Rod") if not f["planar"]][0]
    dispatch(sess, "modeler.select", {"faces": [wall], "mode": "face"})
    with pytest.raises(ValueError, match="curved"):
        dispatch(sess, "modeler.faceOperation", {"op": "sweep",
                                                 "distance": "2mm"})
    # and the body is untouched
    assert type(sess.design.get_solid("Rod").shape).__name__ == "ImportedShape"


def test_a_face_operation_that_cannot_build_leaves_the_body_alone(sess):
    bogus = {"object": "Box1", "point": [9.0, 9.0, 9.0], "normal": [0, 0, 1],
             "lo": [9.0, 9.0, 9.0], "hi": [9.0, 9.0, 9.0], "planar": True}
    before = sess.design.get_solid("Box1").shape
    with pytest.raises(Exception):
        dispatch(sess, "modeler.faceOperation",
                 {"op": "sweep", "distance": "1mm", "faces": [bogus]})
    assert sess.design.get_solid("Box1").shape is before


def test_a_face_operation_uses_only_the_faces_of_its_own_body(sess):
    """Two boxes with a face in exactly the same place: sweeping one must not
    deform the other."""
    dispatch(sess, "modeler.draw",
             {"shape": "box", "name": "Box2",
              "params": {"position": ["0mm", "20mm", "0mm"],
                         "size": ["20mm", "10mm", "4mm"]}})
    top1 = top_face(sess, "Box1")
    dispatch(sess, "modeler.select", {"faces": [top1], "mode": "face"})
    dispatch(sess, "modeler.faceOperation", {"op": "move", "distance": "3mm"})
    assert sess.design.get_solid("Box1").shape.bounds()[1][2] == \
        pytest.approx(7e-3, abs=1e-9)
    assert sess.design.get_solid("Box2").shape.bounds()[1][2] == \
        pytest.approx(4e-3, abs=1e-9)


# ------------------------------------------------------ display properties
def test_colour_and_transparency_are_per_object(sess):
    o = [x for x in state_json(sess)["design"]["objects"]
         if x["name"] == "Box1"][0]
    assert o["colorOverridden"] is False
    material_colour = o["color"]

    dispatch(sess, "modeler.setProperty",
             {"name": "Box1", "prop": "color", "value": "#ff8800"})
    dispatch(sess, "modeler.setProperty",
             {"name": "Box1", "prop": "transparency", "value": 0.85})
    o = [x for x in state_json(sess)["design"]["objects"]
         if x["name"] == "Box1"][0]
    assert o["color"] == "#ff8800" and o["transparency"] == pytest.approx(0.85)
    assert o["colorOverridden"] and o["transparencyOverridden"]
    # the viewport is told the same thing
    g = dispatch(sess, "view.geometry", {})
    assert g["objects"][0]["color"] == "#ff8800"


def test_clearing_an_override_returns_to_the_material(sess):
    dispatch(sess, "modeler.setProperty",
             {"name": "Box1", "prop": "color", "value": "#ff8800"})
    mat = [x for x in state_json(sess)["design"]["objects"]
           if x["name"] == "Box1"][0]["materialColor"]
    dispatch(sess, "modeler.setProperty",
             {"name": "Box1", "prop": "color", "value": ""})
    o = [x for x in state_json(sess)["design"]["objects"]
         if x["name"] == "Box1"][0]
    assert o["color"] == mat and o["colorOverridden"] is False


def test_transparency_is_clamped(sess):
    dispatch(sess, "modeler.setProperty",
             {"name": "Box1", "prop": "transparency", "value": 3.0})
    assert sess.design.get_solid("Box1").transparency == 1.0


def test_an_object_can_be_hidden_and_shown(sess):
    dispatch(sess, "modeler.setProperty",
             {"name": "Box1", "prop": "visible", "value": False})
    assert dispatch(sess, "view.geometry", {})["objects"][0]["visible"] is False
    dispatch(sess, "modeler.setProperty",
             {"name": "Box1", "prop": "visible", "value": True})
    assert dispatch(sess, "view.geometry", {})["objects"][0]["visible"] is True


def test_display_settings_survive_undo(sess):
    dispatch(sess, "modeler.setProperty",
             {"name": "Box1", "prop": "color", "value": "#123456"})
    dispatch(sess, "modeler.transform", {"names": ["Box1"], "op": "move",
                                         "params": {"dz": "1mm"}})
    dispatch(sess, "edit.undo", {})
    assert sess.design.get_solid("Box1").display_color == "#123456"


# ------------------------------------------------------- assemblies
@pytest.fixture()
def assembly(tmp_path):
    """Three separate bodies in one STEP file."""
    from aether.geometry.brep_io import export_shapes
    from aether.geometry.kernel import GmshSession, build_shape
    path = str(tmp_path / "asm.step")
    parts = [ae.Box((0, 0, 0), ("10mm", "10mm", "2mm")),
             ae.Box(("0mm", "0mm", "4mm"), ("6mm", "6mm", "2mm")),
             ae.Box(("0mm", "0mm", "8mm"), ("3mm", "3mm", "2mm"))]
    with GmshSession("mk") as gmsh:
        for p in parts:
            build_shape(p, gmsh)
        gmsh.model.occ.synchronize()
        export_shapes(path, gmsh)
    return path


def test_an_assembly_imports_as_separate_parts(sess, assembly):
    """The regression: a multi-body STEP arrived as one lump that could
    neither be split nor picked apart."""
    dispatch(sess, "modeler.importCad", {"path": assembly, "name": "Asm"})
    names = [o.name for o in sess.design.solids if o.name != "Box1"]
    assert len(names) == 3
    sizes = sorted(round((h - l) * 1e3)
                   for n in names
                   for l, h in [(sess.design.get_solid(n).shape.bounds()[0][0],
                                 sess.design.get_solid(n).shape.bounds()[1][0])])
    assert sizes == [3, 6, 10]


def test_an_assembly_can_be_kept_as_one_body(sess, assembly):
    dispatch(sess, "modeler.importCad",
             {"path": assembly, "name": "Whole", "separate": False})
    assert any(o.name == "Whole" for o in sess.design.solids)
    lo, hi = sess.design.get_solid("Whole").shape.bounds()
    assert (hi[2] - lo[2]) == pytest.approx(10e-3, abs=1e-5)


def test_each_imported_part_is_pickable_on_its_own(sess, assembly):
    dispatch(sess, "modeler.importCad", {"path": assembly, "name": "Asm"})
    g = dispatch(sess, "view.geometry", {})
    parts = [o for o in g["objects"] if o["name"] != "Box1"]
    assert len(parts) == 3
    assert all(len(o["faces"]) == 6 for o in parts)
    # and a boundary can go on one face of one part
    top = max((dict(f, object=parts[0]["name"]) for f in parts[0]["faces"]),
              key=lambda f: f["point"][2])
    dispatch(sess, "boundary.assign",
             {"type": "pec", "name": "PerfE1",
              "selector": {"kind": "faces", "faces": [top]}})
    assert len(sess.design.boundaries) == 1


def test_the_bodies_of_a_file_can_be_listed_before_importing(assembly):
    from aether.geometry.brep_io import list_bodies
    bodies = list_bodies(assembly)
    assert len(bodies) == 3
    assert sorted(round(b["size"][0] * 1e3) for b in bodies) == [3, 6, 10]
    assert all(b["volume"] > 0 for b in bodies)


def test_healing_does_not_weld_an_assembly_into_one_shell(assembly):
    """Shape healing sews faces, and sewing an assembly makes one compound
    that then fails to become a solid: three parts came back as loose
    surfaces and no solids at all."""
    from aether.geometry.brep_io import import_into_occ
    from aether.geometry.kernel import GmshSession
    with GmshSession("t") as gmsh:
        dts = import_into_occ(assembly, gmsh)
    assert [d for d, _ in dts] == [3, 3, 3]


# ------------------------------------------------------------ measuring
def test_measuring_one_edge_reports_its_length(sess):
    edge = {"object": "Box1", "a": [0, 0, 0], "b": [0.02, 0, 0],
            "length": 0.02}
    dispatch(sess, "modeler.select", {"edges": [edge], "mode": "edge"})
    m = dispatch(sess, "modeler.measure", {})
    assert m["kind"] == "edge"
    assert m["total"] == pytest.approx(0.02)
    assert "20 mm" in m["text"]


def test_measuring_two_faces_reports_the_gap(sess):
    dispatch(sess, "modeler.draw",
             {"shape": "box", "name": "Box2",
              "params": {"position": ["0mm", "0mm", "7mm"],
                         "size": ["20mm", "10mm", "4mm"]}})
    f1 = top_face(sess, "Box1")                       # z = 4 mm
    f2 = min(faces(sess, "Box2"), key=lambda f: f["point"][2])   # z = 7 mm
    dispatch(sess, "modeler.select", {"faces": [f1, f2], "mode": "face"})
    m = dispatch(sess, "modeler.measure", {})
    assert m["kind"] == "face"
    assert m["parallel"] is True
    assert m["distance"] == pytest.approx(3e-3, abs=1e-6)
    assert m["planeDistance"] == pytest.approx(3e-3, abs=1e-9)
    assert "gap 3 mm" in m["text"]
    # the line it measured, for drawing the dimension
    assert len(m["line"]) == 2


def test_the_gap_of_offset_faces_is_not_the_centre_distance(sess):
    """Two faces that barely overlap have a gap that has nothing to do with
    the distance between their middles."""
    dispatch(sess, "modeler.draw",
             {"shape": "box", "name": "Far",
              "params": {"position": ["100mm", "0mm", "5mm"],
                         "size": ["20mm", "10mm", "2mm"]}})
    f1 = top_face(sess, "Box1")
    f2 = min(faces(sess, "Far"), key=lambda f: f["point"][2])
    dispatch(sess, "modeler.select", {"faces": [f1, f2], "mode": "face"})
    m = dispatch(sess, "modeler.measure", {})
    # nearest corners are 80 mm apart in x and 1 mm in z
    assert m["distance"] == pytest.approx(np.hypot(80e-3, 1e-3), rel=1e-3)


def test_measuring_objects_reports_size_and_separation(sess):
    dispatch(sess, "modeler.draw",
             {"shape": "box", "name": "Box2",
              "params": {"position": ["0mm", "0mm", "9mm"],
                         "size": ["20mm", "10mm", "4mm"]}})
    dispatch(sess, "modeler.select", {"names": ["Box1", "Box2"],
                                      "mode": "object"})
    m = dispatch(sess, "modeler.measure", {})
    assert m["kind"] == "object"
    assert m["size"] == pytest.approx([20e-3, 10e-3, 13e-3])
    assert m["distance"] == pytest.approx(5e-3, abs=1e-9)


def test_measuring_nothing_says_so(sess):
    dispatch(sess, "modeler.select", {"names": [], "faces": [], "edges": []})
    assert dispatch(sess, "modeler.measure", {})["text"] == "nothing picked"


def test_measurements_are_reported_in_the_model_units(sess):
    sess.design.units = "in"
    dispatch(sess, "modeler.select", {"names": ["Box1"], "mode": "object"})
    assert "in" in dispatch(sess, "modeler.measure", {})["text"]


# ----------------------------------------------- assignments in the view
def test_assignments_report_the_faces_they_cover(sess):
    dispatch(sess, "boundary.assign",
             {"type": "pec", "name": "PerfE1",
              "selector": {"kind": "faces", "faces": [top_face(sess)]}})
    dispatch(sess, "excitation.assign",
             {"kind": "wave", "name": "p1",
              "selector": {"kind": "plane", "axis": "z", "value": "0mm"}})
    items = dispatch(sess, "view.assignments", {})["items"]
    names = {i["name"]: i for i in items}
    assert set(names) == {"PerfE1", "p1"}
    assert names["p1"]["kind"] == "wave"
    assert names["PerfE1"]["type"] == "pec"
    # the triangles are real, and they are where the assignment is
    assert names["PerfE1"]["count"] > 0
    assert names["PerfE1"]["center"][2] == pytest.approx(4e-3, abs=1e-6)
    assert len(names["PerfE1"]["position"]) == names["PerfE1"]["count"] * 9


def test_an_assignment_on_nothing_is_not_drawn(sess):
    dispatch(sess, "boundary.assign",
             {"type": "pec", "name": "Nowhere",
              "selector": {"kind": "plane", "axis": "z", "value": "500mm"}})
    items = dispatch(sess, "view.assignments", {})["items"]
    assert [i["name"] for i in items] == []


def test_assignments_need_no_mesh(sess):
    dispatch(sess, "boundary.assign",
             {"type": "radiation", "name": "Rad1",
              "selector": {"kind": "outer"}})
    assert sess.design.mesh is None
    assert dispatch(sess, "view.assignments", {})["items"][0]["name"] == "Rad1"
    assert sess.design.mesh is None
