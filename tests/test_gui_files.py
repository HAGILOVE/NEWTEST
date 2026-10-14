"""
File browsing, automatic naming and viewport picking.

These cover the three things a modeller does constantly and must never make
the user think about: finding a file, naming a new object, and clicking on
something to select it.
"""
import os
import time

import numpy as np
import pytest

from conftest import needs_occ

import aether as ae
from aether.gui import files as F
from aether.gui import naming as N
from aether.gui.api import dispatch
from aether.gui.state import Session


@pytest.fixture()
def sess():
    s = Session()
    s.new_project("NamingTest")
    return s


# ============================================================== naming
def test_next_name_fills_the_lowest_gap():
    assert N.next_name([], "Box") == "Box1"
    assert N.next_name(["Box1"], "Box") == "Box2"
    assert N.next_name(["Box1", "Box3"], "Box") == "Box2"
    assert N.next_name(["Box1", "Box2", "Box3"], "Box") == "Box4"


def test_unique_name_advances_a_trailing_number():
    """'Box7' taken becomes 'Box8', never 'Box71'."""
    assert N.unique_name(["Box7"], "Box7") == "Box8"
    assert N.unique_name(["Box7", "Box8"], "Box7") == "Box9"
    assert N.unique_name([], "Antenna") == "Antenna"
    assert N.unique_name(["Antenna"], "Antenna") == "Antenna1"
    assert N.unique_name(["x"], "") == "Object1"


def test_cad_import_names_come_from_the_file():
    assert N.suggest_part_from_file(None, "/x/my part-2.step") == "my_part_2"
    assert N.suggest_part_from_file(None, "/x/3dmodel.stp") == "Part_3dmodel"


def test_drawing_never_requires_a_name(sess):
    """The whole point: press Create repeatedly and get sensible names."""
    for shape in ("box", "box", "cylinder", "cylinder", "sphere", "cone",
                  "torus"):
        dispatch(sess, "modeler.draw", {"shape": shape})
    dispatch(sess, "modeler.draw", {"shape": "rectangle"})
    assert [o.name for o in sess.design.solids] == [
        "Box1", "Box2", "Cylinder1", "Cylinder2", "Sphere1", "Cone1", "Torus1"]
    assert [s.name for s in sess.design.sheets] == ["Rectangle1"]


def test_boundaries_and_ports_are_named_by_type(sess):
    dispatch(sess, "modeler.draw", {"shape": "box"})
    for t in ("pec", "pec", "radiation", "finite_cond", "impedance",
              "lumped_rlc", "symmetry_e"):
        dispatch(sess, "boundary.assign",
                 {"type": t, "params": {"material": "copper"}})
    assert [b.name for b in sess.design.boundaries] == [
        "PerfE1", "PerfE2", "Rad1", "FiniteCond1", "Impedance1", "LumpRLC1",
        "SymmE1"]
    for k in ("wave", "wave", "lumped"):
        dispatch(sess, "excitation.assign",
                 {"kind": k, "selector": {"kind": "plane", "axis": "z"}})
    assert [p.name for p in sess.design.ports] == ["Port1", "Port2", "Lumped1"]


def test_setups_and_sweeps_are_named_per_parent(sess):
    dispatch(sess, "analysis.addSetup", {})
    dispatch(sess, "analysis.addSetup", {})
    for name in ("Setup1", "Setup2"):
        dispatch(sess, "analysis.addSweep", {"setup": name})
        dispatch(sess, "analysis.addSweep", {"setup": name})
    assert [s.name for s in sess.design.setups] == ["Setup1", "Setup2"]
    for st in sess.design.setups:
        assert [w.name for w in st.sweeps] == ["Sweep1", "Sweep2"]


def test_suggest_command_matches_what_creation_would_do(sess):
    for kind, what, expect in (("shape", "box", "Box1"),
                               ("boundary", "radiation", "Rad1"),
                               ("port", "wave", "Port1"),
                               ("setup", "", "Setup1")):
        assert dispatch(sess, "naming.suggest",
                        {"kind": kind, "what": what})["name"] == expect
    dispatch(sess, "modeler.draw", {"shape": "box"})
    assert dispatch(sess, "naming.suggest",
                    {"kind": "shape", "what": "box"})["name"] == "Box2"


def test_explicit_names_are_kept_but_made_unique(sess):
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "Radome"})
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "Radome"})
    assert [o.name for o in sess.design.solids] == ["Radome", "Radome1"]


def test_rename_resolves_collisions_and_keeps_boundaries(sess):
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "A"})
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "B"})
    dispatch(sess, "boundary.assign", {"type": "pec", "name": "OnA",
                                       "selector": {"kind": "object",
                                                    "objects": ["A"]}})
    dispatch(sess, "modeler.setProperty",
             {"name": "A", "prop": "name", "value": "B"})
    names = [o.name for o in sess.design.solids]
    assert names == ["B1", "B"]                 # collision resolved
    # the boundary references the shape object, so it survives the rename
    sel = sess.design.boundaries[0].selector
    assert sel.shape is sess.design.get_solid("B1").shape


def test_names_from_the_console_are_respected_by_the_suggester(sess):
    dispatch(sess, "script.run",
             {"code": "design.add_box('Box1',(0,0,0),('1mm','1mm','1mm'))"})
    assert dispatch(sess, "naming.suggest",
                    {"kind": "shape", "what": "box"})["name"] == "Box2"


# =========================================================== file browsing
def test_listing_a_directory(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.warp").write_text("x")
    (tmp_path / "b.step").write_text("y")
    (tmp_path / ".hidden").write_text("z")
    r = F.list_dir(str(tmp_path))
    assert r["path"] == str(tmp_path)
    assert [d["name"] for d in r["dirs"]] == ["sub"]
    assert {f["name"] for f in r["files"]} == {"a.warp", "b.step"}
    assert not r["error"] and r["writable"]
    assert r["crumbs"][-1]["path"] == str(tmp_path)


def test_extension_filter(tmp_path):
    (tmp_path / "a.warp").write_text("x")
    (tmp_path / "b.step").write_text("y")
    r = F.list_dir(str(tmp_path), [".warp", ".warpz"])
    assert [f["name"] for f in r["files"]] == ["a.warp"]
    r = F.list_dir(str(tmp_path), [])
    assert len(r["files"]) == 2


def test_hidden_files_are_opt_in(tmp_path):
    (tmp_path / ".secret").write_text("z")
    assert not F.list_dir(str(tmp_path))["files"]
    assert F.list_dir(str(tmp_path), None, True)["files"][0]["name"] == ".secret"


def test_missing_directory_falls_back_instead_of_raising(tmp_path):
    r = F.list_dir(str(tmp_path / "does" / "not" / "exist"))
    assert os.path.isdir(r["path"])
    assert not r["error"]


def test_unreadable_directory_reports_instead_of_raising(tmp_path):
    d = tmp_path / "locked"
    d.mkdir()
    os.chmod(d, 0o000)
    try:
        r = F.list_dir(str(d))
        if os.geteuid() != 0:               # root can read anything
            assert r["error"]
        assert r["dirs"] == [] and r["files"] == []
    finally:
        os.chmod(d, 0o755)


def test_breadcrumbs_reach_the_root(tmp_path):
    c = F.breadcrumbs(str(tmp_path))
    assert c[0]["path"] in (os.sep, os.path.splitdrive(str(tmp_path))[0] + os.sep)
    assert c[-1]["path"] == str(tmp_path)


def test_places_are_absolute_and_unique():
    p = F.places()
    assert p and p[0]["name"] == "Home"
    paths = [os.path.normcase(x["path"]) for x in p]
    assert len(paths) == len(set(paths))
    assert all(os.path.isabs(x["path"]) for x in p)


def test_save_path_resolution(tmp_path):
    r = F.resolve_save_path(str(tmp_path), "proj", [".warp"])
    assert r["ok"] and r["path"].endswith("proj.warp") and not r["exists"]
    (tmp_path / "proj.warp").write_text("x")
    assert F.resolve_save_path(str(tmp_path), "proj", [".warp"])["exists"]
    assert F.resolve_save_path(str(tmp_path), "keep.txt", [".warp"])[
        "path"].endswith("keep.txt")
    assert not F.resolve_save_path(str(tmp_path), "")["ok"]
    bad = F.resolve_save_path(str(tmp_path / "nope"), "x", [".warp"])
    assert not bad["ok"] and "does not exist" in bad["error"]


def test_absolute_name_overrides_the_directory(tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    r = F.resolve_save_path(str(tmp_path), str(target / "p.warp"))
    assert r["ok"] and r["path"] == str(target / "p.warp")


def test_filters_cover_every_dialog_we_open():
    for kind in ("project", "cad", "touchstone", "csv", "html", "vtk", "any"):
        f = F.filters(kind)
        assert f and all("label" in x and "ext" in x for x in f)
    assert ".step" in F.filters("cad")[0]["ext"]
    assert ".warp" in F.filters("project")[0]["ext"]


def test_native_dialog_degrades_cleanly_without_a_desktop():
    if F.native_available():
        pytest.skip("a desktop session is present")
    r = F.native_dialog()
    assert r["ok"] is False and "native file dialog" in r["error"]


# --------------------------------------------------------- through the API
def test_browse_command_payload(sess, tmp_path):
    (tmp_path / "p.warp").write_text("x")
    r = dispatch(sess, "files.browse",
                 {"path": str(tmp_path), "kind": "project"})
    assert [f["name"] for f in r["files"]] == ["p.warp"]
    assert r["places"] and r["filters"] and "native" in r
    assert r["crumbs"][-1]["name"] == tmp_path.name


def test_default_dir_prefers_the_open_project(sess, tmp_path):
    sess.project_path = str(tmp_path / "proj.warp")
    assert dispatch(sess, "files.defaultDir")["path"] == str(tmp_path)


def test_resolve_save_command(sess, tmp_path):
    r = dispatch(sess, "files.resolveSave",
                 {"directory": str(tmp_path), "filename": "out",
                  "kind": "touchstone"})
    assert r["ok"] and r["path"].endswith("out.s1p")


def test_native_command_reports_its_own_failure(sess):
    if F.native_available():
        pytest.skip("a desktop session is present")
    r = dispatch(sess, "files.native", {"mode": "open"})
    assert r["ok"] is False
    assert any("Native file dialog" in m["text"]
               for m in sess.messages.since(0))


@needs_occ
def test_save_then_open_through_the_picker_path(tmp_path):
    """Exactly what the dialogs do: resolve a path, save, browse, re-open."""
    s = Session()
    dispatch(s, "project.template", {"template": "waveguide"})
    r = dispatch(s, "files.resolveSave",
                 {"directory": str(tmp_path), "filename": "MyGuide",
                  "kind": "project"})
    assert r["ok"] and r["path"].endswith(".warp")
    dispatch(s, "project.save", {"path": r["path"]})
    listing = dispatch(s, "files.browse",
                       {"path": str(tmp_path), "kind": "project"})
    assert [f["name"] for f in listing["files"]] == ["MyGuide.warp"]
    s2 = Session()
    dispatch(s2, "project.open", {"path": listing["files"][0]["path"]})
    assert s2.design.name == "WR90_Thru"
    assert len(s2.design.ports) == 2


def test_a_path_that_names_a_file_is_reported_as_one(tmp_path):
    """So a full path pasted into the dialog's name box can be accepted in one
    step instead of being turned into a listing of its folder."""
    f = tmp_path / "part.step"
    f.write_text("x")
    r = F.list_dir(str(f), [".step"])
    assert r["isFile"] is True
    assert r["filePath"] == str(f)
    assert r["path"] == str(tmp_path)          # the folder is listed as well
    assert "part.step" in [x["name"] for x in r["files"]]


def test_a_folder_is_not_reported_as_a_file(tmp_path):
    r = F.list_dir(str(tmp_path))
    assert r["isFile"] is False and r["filePath"] == ""
