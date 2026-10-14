"""
Aether Desktop: the Edit commands and CAD import.

Two things a modeller is judged on and that used to be broken here: an
imported STEP file has to land at the size the file says it is, and the
edit operations (arrange, clipboard, duplicate, undo) have to change the
model in the way the numbers say they do.  Everything below checks the
resulting *geometry*, not merely that the command returned ok.
"""
import os

import numpy as np
import pytest

from conftest import needs_occ

import aether as ae
from aether.gui.api import dispatch
from aether.gui.state import Session


@pytest.fixture()
def sess():
    s = Session()
    s.new_project("EditTest")
    dispatch(s, "modeler.draw", {"shape": "box", "name": "Box1",
                                 "params": {"position": ["0mm", "0mm", "0mm"],
                                            "size": ["10mm", "4mm", "2mm"]}})
    return s


def bbox(s, name):
    o = s.design.get_solid(name)
    lo, hi = o.shape.bounds()
    return np.array(lo), np.array(hi)


# ------------------------------------------------------------- arranging
def test_move_shifts_the_object_by_the_vector(sess):
    lo0, _ = bbox(sess, "Box1")
    dispatch(sess, "modeler.transform", {"names": ["Box1"], "op": "move",
                                         "params": {"dx": "5mm", "dy": "0mm",
                                                    "dz": "-1mm"}})
    lo1, _ = bbox(sess, "Box1")
    assert np.allclose(lo1 - lo0, [5e-3, 0, -1e-3])


def test_move_without_names_uses_the_selection(sess):
    sess.selection = ["Box1"]
    lo0, _ = bbox(sess, "Box1")
    dispatch(sess, "modeler.transform", {"op": "move",
                                         "params": {"dx": "1mm"}})
    lo1, _ = bbox(sess, "Box1")
    assert np.allclose(lo1 - lo0, [1e-3, 0, 0])


def test_move_with_no_target_at_all_is_refused(sess):
    sess.selection = []
    with pytest.raises(ValueError):
        dispatch(sess, "modeler.transform", {"op": "move",
                                             "params": {"dx": "1mm"}})


def test_rotate_about_z_swaps_the_extents(sess):
    dispatch(sess, "modeler.transform",
             {"names": ["Box1"], "op": "rotate",
              "params": {"axis": "z", "angle": "90deg",
                         "origin": ["0mm", "0mm", "0mm"]}})
    lo, hi = bbox(sess, "Box1")
    assert np.allclose(hi - lo, [4e-3, 10e-3, 2e-3], atol=1e-9)


def test_mirror_reflects_across_the_plane(sess):
    dispatch(sess, "modeler.transform",
             {"names": ["Box1"], "op": "mirror",
              "params": {"normal": [1, 0, 0], "origin": ["0mm", "0mm", "0mm"]}})
    lo, hi = bbox(sess, "Box1")
    assert lo[0] == pytest.approx(-10e-3)
    assert hi[0] == pytest.approx(0.0, abs=1e-12)


def test_transform_applies_to_every_named_object(sess):
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "Box2",
                                    "params": {"position": ["0mm", "0mm", "0mm"],
                                               "size": ["1mm", "1mm", "1mm"]}})
    dispatch(sess, "modeler.transform",
             {"names": ["Box1", "Box2"], "op": "move", "params": {"dz": "3mm"}})
    for n in ("Box1", "Box2"):
        assert bbox(sess, n)[0][2] == pytest.approx(3e-3)


# ------------------------------------------------------------- clipboard
def test_copy_and_paste_makes_an_independent_object(sess):
    dispatch(sess, "modeler.copy", {"names": ["Box1"]})
    r = dispatch(sess, "modeler.paste", {"offset": ["20mm", "0mm", "0mm"]})
    new = r["names"][0]
    assert new != "Box1"
    assert len(sess.design.solids) == 2
    assert bbox(sess, new)[0][0] == pytest.approx(20e-3)
    # the original is untouched
    assert bbox(sess, "Box1")[0][0] == pytest.approx(0.0, abs=1e-12)
    # and the two are not the same object
    dispatch(sess, "modeler.transform",
             {"names": [new], "op": "move", "params": {"dz": "1mm"}})
    assert bbox(sess, "Box1")[0][2] == pytest.approx(0.0, abs=1e-12)


def test_cut_removes_the_original_and_paste_restores_it(sess):
    dispatch(sess, "modeler.copy", {"names": ["Box1"], "cut": True})
    assert sess.design.solids == []
    dispatch(sess, "modeler.paste", {})
    assert len(sess.design.solids) == 1


def test_paste_with_an_empty_clipboard_is_refused(sess):
    with pytest.raises(RuntimeError):
        dispatch(sess, "modeler.paste", {})


def test_copy_keeps_the_material(sess):
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "Cu1",
                                    "material": "copper",
                                    "params": {"size": ["1mm", "1mm", "1mm"]}})
    dispatch(sess, "modeler.copy", {"names": ["Cu1"]})
    new = dispatch(sess, "modeler.paste", {})["names"][0]
    assert sess.design.get_solid(new).material.name == "copper"


# ------------------------------------------------------------- duplicate
def test_duplicate_along_line_steps_by_the_vector(sess):
    r = dispatch(sess, "modeler.duplicate",
                 {"names": ["Box1"], "mode": "line", "count": 4,
                  "params": {"vector": ["20mm", "0mm", "0mm"]}})
    assert len(r["names"]) == 3            # count is the total, original included
    assert len(sess.design.solids) == 4
    xs = sorted(bbox(sess, n)[0][0] for n in ["Box1"] + r["names"])
    assert np.allclose(xs, [0, 20e-3, 40e-3, 60e-3])


def test_duplicate_around_axis_spreads_over_the_full_circle(sess):
    r = dispatch(sess, "modeler.duplicate",
                 {"names": ["Box1"], "mode": "axis", "count": 4,
                  "params": {"axis": "z", "angle": "360deg",
                             "origin": ["0mm", "0mm", "0mm"]}})
    assert len(r["names"]) == 3
    # the 90-degree copy has the 10 mm length along +Y
    lo, hi = bbox(sess, r["names"][0])
    assert np.allclose(hi - lo, [4e-3, 10e-3, 2e-3], atol=1e-9)
    # the 180-degree copy is on the far side of the origin
    assert bbox(sess, r["names"][1])[1][0] == pytest.approx(0.0, abs=1e-9)


def test_duplicate_mirror_makes_exactly_one_copy(sess):
    r = dispatch(sess, "modeler.duplicate",
                 {"names": ["Box1"], "mode": "mirror", "count": 9,
                  "params": {"normal": [1, 0, 0]}})
    assert len(r["names"]) == 1
    assert bbox(sess, r["names"][0])[0][0] == pytest.approx(-10e-3)


@needs_occ
def test_duplicate_with_attach_unites_into_one_object(sess):
    dispatch(sess, "modeler.duplicate",
             {"names": ["Box1"], "mode": "line", "count": 3,
              "params": {"vector": ["10mm", "0mm", "0mm"]}, "attach": True})
    assert [o.name for o in sess.design.solids] == ["Box1"]
    lo, hi = bbox(sess, "Box1")
    assert hi[0] == pytest.approx(30e-3, rel=1e-6)


def test_duplicate_names_do_not_collide(sess):
    r = dispatch(sess, "modeler.duplicate",
                 {"names": ["Box1"], "mode": "line", "count": 5,
                  "params": {"vector": ["1mm", "0mm", "0mm"]}})
    names = [o.name for o in sess.design.solids]
    assert len(set(names)) == len(names) == 5
    assert "Box1" in names and set(r["names"]) <= set(names)


# ----------------------------------------------------------- undo / redo
def test_undo_removes_the_last_object_and_redo_brings_it_back(sess):
    dispatch(sess, "modeler.draw", {"shape": "sphere", "name": "Sphere1",
                                    "params": {"radius": "1mm"}})
    assert len(sess.design.solids) == 2
    assert dispatch(sess, "edit.history", {})["canUndo"] is True
    dispatch(sess, "edit.undo", {})
    assert [o.name for o in sess.design.solids] == ["Box1"]
    dispatch(sess, "edit.redo", {})
    assert [o.name for o in sess.design.solids] == ["Box1", "Sphere1"]


def test_undo_reverses_a_move(sess):
    dispatch(sess, "modeler.transform",
             {"names": ["Box1"], "op": "move", "params": {"dx": "7mm"}})
    assert bbox(sess, "Box1")[0][0] == pytest.approx(7e-3)
    dispatch(sess, "edit.undo", {})
    assert bbox(sess, "Box1")[0][0] == pytest.approx(0.0, abs=1e-12)


def test_undo_reverses_a_delete_including_its_boundary(sess):
    dispatch(sess, "boundary.assign",
             {"name": "Rad1", "type": "radiation",
              "selector": {"kind": "object", "object": "Box1"}})
    assert len(sess.design.boundaries) == 1
    dispatch(sess, "modeler.delete", {"names": ["Box1"]})
    dispatch(sess, "edit.undo", {})
    assert [o.name for o in sess.design.solids] == ["Box1"]
    assert len(sess.design.boundaries) == 1
    # the restored boundary still points at the restored object itself, not
    # at an orphaned copy of it -- the reason undo snapshots the whole design
    # in one deepcopy rather than object by object.
    b = sess.design.boundaries[0]
    assert b.selector.shape is sess.design.get_solid("Box1").shape


def test_a_new_action_clears_the_redo_stack(sess):
    dispatch(sess, "modeler.transform",
             {"names": ["Box1"], "op": "move", "params": {"dx": "1mm"}})
    dispatch(sess, "edit.undo", {})
    assert dispatch(sess, "edit.history", {})["canRedo"] is True
    dispatch(sess, "modeler.transform",
             {"names": ["Box1"], "op": "move", "params": {"dy": "1mm"}})
    assert dispatch(sess, "edit.history", {})["canRedo"] is False


def test_a_failed_command_leaves_no_undo_entry(sess):
    before = dispatch(sess, "edit.history", {})
    with pytest.raises(Exception):
        dispatch(sess, "modeler.transform", {"names": ["Nope"], "op": "move",
                                             "params": {"dx": "1mm"}})
    after = dispatch(sess, "edit.history", {})
    assert after["undo"] == before["undo"]


def test_undo_at_the_bottom_of_the_stack_is_refused_not_silent(sess):
    dispatch(sess, "edit.undo", {})               # undoes the box
    assert dispatch(sess, "edit.history", {})["canUndo"] is False
    with pytest.raises(RuntimeError):
        dispatch(sess, "edit.undo", {})


def test_history_is_reported_in_the_state(sess):
    from aether.gui.api import state_json
    dispatch(sess, "modeler.copy", {"names": ["Box1"]})
    h = state_json(sess)["history"]
    assert h["clipboard"] == 1
    assert set(h) == {"canUndo", "canRedo", "undo", "redo", "clipboard"}


# ----------------------------------------------------------- CAD import
@pytest.fixture()
def step_20mm(tmp_path):
    """A 20 x 10 x 4 mm box written as STEP, declared in millimetres."""
    from aether.geometry.brep_io import export_shapes
    from aether.geometry.kernel import GmshSession, build_shape
    path = str(tmp_path / "part.step")
    with GmshSession("mk") as gmsh:
        build_shape(ae.Box((0, 0, 0), ("20mm", "10mm", "4mm")), gmsh)
        gmsh.model.occ.synchronize()
        export_shapes(path, gmsh)
    return path


@needs_occ
def test_inspect_reports_the_file_before_importing(step_20mm):
    from aether.geometry.brep_io import inspect
    r = inspect(step_20mm)
    assert r["format"] == "step"
    assert r["solids"] == 1 and r["surfaces"] >= 6
    assert not r["error"]
    lo, hi = r["bbox"]
    assert np.allclose(np.array(hi) - np.array(lo), [20e-3, 10e-3, 4e-3],
                       atol=1e-6)


@needs_occ
def test_step_lands_at_the_size_the_file_declares(sess, step_20mm):
    """The regression: read without unit handling this became a 20 m part,
    the camera fitted to it and the rest of the model vanished."""
    dispatch(sess, "modeler.importCad", {"path": step_20mm, "name": "Part"})
    lo, hi = bbox(sess, "Part")
    assert np.allclose(hi - lo, [20e-3, 10e-3, 4e-3], atol=1e-6)


@needs_occ
@pytest.mark.parametrize("unit, mm", [("mm", 20.0), ("cm", 200.0),
                                      ("m", 20000.0), ("in", 508.0)])
def test_an_explicit_unit_overrides_the_declaration(sess, step_20mm, unit, mm):
    dispatch(sess, "modeler.importCad",
             {"path": step_20mm, "name": "P_" + unit, "unit": unit})
    lo, hi = bbox(sess, "P_" + unit)
    assert (hi[0] - lo[0]) * 1e3 == pytest.approx(mm, rel=1e-4)


@needs_occ
def test_import_reports_what_it_read(sess, step_20mm):
    n0 = sess.messages.seq
    dispatch(sess, "modeler.importCad", {"path": step_20mm, "name": "Part"})
    said = " ".join(m["text"] for m in sess.messages.since(n0))
    assert "1 solid" in said and "20.000 x 10.000 x 4.000 mm" in said


def test_importing_a_missing_file_is_refused(sess, tmp_path):
    with pytest.raises(FileNotFoundError):
        dispatch(sess, "modeler.importCad",
                 {"path": str(tmp_path / "nothing.step")})


@needs_occ
def test_importing_an_unreadable_file_is_refused(sess, tmp_path):
    bad = tmp_path / "broken.step"
    bad.write_text("this is not a STEP file\n")
    with pytest.raises(Exception):
        dispatch(sess, "modeler.importCad", {"path": str(bad)})


@needs_occ
def test_reimporting_the_same_file_is_served_from_the_cache(step_20mm):
    import time
    from aether.geometry.brep_io import quick_bounds
    quick_bounds(step_20mm)
    t = time.perf_counter()
    quick_bounds(step_20mm)
    assert time.perf_counter() - t < 0.05


# --------------------------------------------- imported bodies, end to end
@needs_occ
def test_an_imported_body_survives_save_and_reopen(sess, step_20mm, tmp_path):
    """A project that only recorded an absolute path lost the body the moment
    the CAD file moved — and lost it silently, as a part that is simply not
    there. The file now travels with the project."""
    dispatch(sess, "modeler.importCad", {"path": step_20mm, "name": "Part"})
    dispatch(sess, "modeler.transform",
             {"names": ["Part"], "op": "move", "params": {"dz": "3mm"}})
    proj = str(tmp_path / "saved.warp")
    dispatch(sess, "project.save", {"path": proj})
    assert list((tmp_path / "saved.cad").glob("*.step"))

    os.rename(step_20mm, step_20mm + ".moved")     # the original goes away
    s2 = Session()
    dispatch(s2, "project.open", {"path": proj})
    o = s2.design.get_solid("Part")
    lo, hi = o.shape.bounds()
    assert np.allclose(np.array(hi) - np.array(lo), [20e-3, 10e-3, 4e-3],
                       atol=1e-6)
    assert lo[2] == pytest.approx(3e-3, abs=1e-6)   # the move came back too
    assert o.material.name == "vacuum"


@needs_occ
def test_a_reopened_project_keeps_the_import_unit(sess, step_20mm, tmp_path):
    dispatch(sess, "modeler.importCad",
             {"path": step_20mm, "name": "Part", "unit": "in"})
    proj = str(tmp_path / "inches.warp")
    dispatch(sess, "project.save", {"path": proj})
    s2 = Session()
    dispatch(s2, "project.open", {"path": proj})
    sh = s2.design.get_solid("Part").shape
    assert sh.unit == "in"
    lo, hi = sh.bounds()
    assert (hi[0] - lo[0]) * 1e3 == pytest.approx(508.0, rel=1e-4)


@needs_occ
def test_a_missing_cad_source_is_reported_not_dropped(sess, step_20mm, tmp_path):
    dispatch(sess, "modeler.importCad", {"path": step_20mm, "name": "Part"})
    dispatch(sess, "boundary.assign",
             {"name": "PerfE1", "type": "pec",
              "selector": {"kind": "object", "object": "Part"}})
    proj = str(tmp_path / "orphan.warp")
    dispatch(sess, "project.save", {"path": proj})
    import shutil
    shutil.rmtree(tmp_path / "orphan.cad")
    os.rename(step_20mm, step_20mm + ".gone")

    s2 = Session()
    n0 = s2.messages.seq
    dispatch(s2, "project.open", {"path": proj})
    # the model keeps its structure ...
    assert "Part" in [o.name for o in s2.design.solids]
    assert any(b.name == "PerfE1" for b in s2.design.boundaries)
    # ... and says what is wrong instead of pretending
    said = " ".join(m["text"] for m in s2.messages.since(n0))
    assert "not found" in said and "Part" in said


@needs_occ
def test_replace_cad_keeps_everything_but_the_source(sess, step_20mm, tmp_path):
    from aether.geometry.brep_io import export_shapes
    from aether.geometry.kernel import GmshSession, build_shape
    other = str(tmp_path / "rev2.step")
    with GmshSession("mk2") as gmsh:
        build_shape(ae.Box((0, 0, 0), ("30mm", "10mm", "4mm")), gmsh)
        gmsh.model.occ.synchronize()
        export_shapes(other, gmsh)

    dispatch(sess, "modeler.importCad",
             {"path": step_20mm, "name": "Part", "material": "copper"})
    dispatch(sess, "modeler.transform",
             {"names": ["Part"], "op": "move", "params": {"dz": "2mm"}})
    dispatch(sess, "boundary.assign",
             {"name": "PerfE1", "type": "pec",
              "selector": {"kind": "object", "object": "Part"}})
    shape_before = sess.design.get_solid("Part").shape

    dispatch(sess, "modeler.replaceCad", {"name": "Part", "path": other})
    o = sess.design.get_solid("Part")
    assert o.shape is shape_before          # edited in place, not replaced
    assert o.material.name == "copper"
    assert sess.design.boundaries[0].selector.shape is o.shape
    lo, hi = o.shape.bounds()
    assert (hi[0] - lo[0]) == pytest.approx(30e-3, abs=1e-6)
    assert lo[2] == pytest.approx(2e-3, abs=1e-6)     # the transform stayed


@needs_occ
def test_replace_cad_can_correct_the_unit_alone(sess, step_20mm):
    dispatch(sess, "modeler.importCad", {"path": step_20mm, "name": "Part"})
    dispatch(sess, "modeler.replaceCad", {"name": "Part", "unit": "cm"})
    lo, hi = sess.design.get_solid("Part").shape.bounds()
    assert (hi[0] - lo[0]) * 1e3 == pytest.approx(200.0, rel=1e-4)


def test_replace_cad_refuses_a_non_imported_object(sess):
    with pytest.raises(ValueError):
        dispatch(sess, "modeler.replaceCad", {"name": "Box1", "unit": "mm"})


@needs_occ
def test_replace_cad_refuses_a_missing_file(sess, step_20mm, tmp_path):
    dispatch(sess, "modeler.importCad", {"path": step_20mm, "name": "Part"})
    with pytest.raises(FileNotFoundError):
        dispatch(sess, "modeler.replaceCad",
                 {"name": "Part", "path": str(tmp_path / "nope.step")})


@needs_occ
def test_the_state_reports_an_imported_body_provenance(sess, step_20mm):
    from aether.gui.api import state_json
    dispatch(sess, "modeler.importCad", {"path": step_20mm, "name": "Part"})
    o = [x for x in state_json(sess)["design"]["objects"]
         if x["name"] == "Part"][0]
    assert o["cad"]["file"] == os.path.basename(step_20mm)
    assert o["cad"]["exists"] is True
    assert o["cad"]["unit"] == "auto"
