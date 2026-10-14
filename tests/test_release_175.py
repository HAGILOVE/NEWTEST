"""
Release 1.7.5 — document lifecycle, progress reporting and viewport speed.

Three things the workspace was missing and one it was doing far too slowly:

* a project could not be closed, and nothing ever asked whether unsaved work
  should be saved before it was thrown away;
* opening a project or importing CAD reported nothing at all while it worked;
* every redraw re-tessellated the whole model and re-sent every triangle as
  JSON, so editing a model with a few imported bodies in it crawled.
"""
import json
import os
import time

import numpy as np
import pytest

from aether.gui.api import dispatch, state_json
from aether.gui.state import Progress, Session
from conftest import needs_occ

pytestmark = needs_occ


def box(s, name, pos=("0mm", "0mm", "0mm"), size=("10mm", "5mm", "1mm")):
    dispatch(s, "modeler.draw", {"shape": "box", "name": name,
                                 "params": {"position": list(pos),
                                            "size": list(size)}})


@pytest.fixture
def sess():
    s = Session()
    s.new_project("P")
    return s


# ------------------------------------------------------- closing a project
def test_a_project_can_be_closed_and_leaves_no_document(sess):
    box(sess, "Box1")
    assert state_json(sess)["project"]["open"] is True
    dispatch(sess, "project.close", {})
    st = state_json(sess)
    assert st["project"]["open"] is False
    assert st["design"] is None
    assert st["project"]["designs"] == []
    assert st["project"]["dirty"] is False


def test_closing_drops_everything_scoped_to_the_document(sess):
    box(sess, "Box1")
    dispatch(sess, "modeler.copy", {"names": ["Box1"]})
    dispatch(sess, "project.close", {})
    st = state_json(sess)
    assert st["history"]["canUndo"] is False
    assert st["history"]["canRedo"] is False
    assert st["history"]["clipboard"] == 0
    assert st["selection"] == []
    assert sess.solution is None


def test_the_views_still_answer_with_no_project_open(sess):
    """The UI keeps polling after a close; nothing may raise."""
    dispatch(sess, "project.close", {})
    assert dispatch(sess, "view.geometry", {})["objects"] == []
    assert dispatch(sess, "view.assignments", {})["items"] == []
    assert state_json(sess)["design"] is None


def test_a_new_project_reopens_the_document(sess):
    dispatch(sess, "project.close", {})
    dispatch(sess, "project.new", {"name": "Q"})
    st = state_json(sess)
    assert st["project"]["open"] is True
    assert st["design"]["name"] == "HFSSDesign1"


def test_close_does_not_write_anything(tmp_path, sess):
    """Saving is the caller's decision; close never touches the disk."""
    p = tmp_path / "P.aedt"
    box(sess, "Box1")
    dispatch(sess, "project.save", {"path": str(p)})
    box(sess, "Box2")
    before = p.read_bytes()
    dispatch(sess, "project.close", {})
    assert p.read_bytes() == before


def test_the_dirty_flag_is_what_the_prompt_keys_off(tmp_path, sess):
    assert state_json(sess)["project"]["dirty"] is False
    box(sess, "Box1")
    assert state_json(sess)["project"]["dirty"] is True
    dispatch(sess, "project.save", {"path": str(tmp_path / "P.aedt")})
    assert state_json(sess)["project"]["dirty"] is False


# --------------------------------------------------------------- progress
def test_progress_reports_stage_and_fraction():
    p = Progress()
    assert p.to_json()["active"] is False
    p.begin("Opening X", total=4, stage="parsing")
    j = p.to_json()
    assert j["active"] and j["label"] == "Opening X" and j["fraction"] == 0.0
    p.step(stage="reading design 2 of 4", done=2, detail="Design2")
    j = p.to_json()
    assert j["fraction"] == 0.5 and j["detail"] == "Design2"
    p.end()
    assert p.to_json()["active"] is False


def test_progress_seq_moves_so_the_poller_can_tell_it_changed():
    p = Progress()
    p.begin("x")
    a = p.to_json()["seq"]
    p.step(stage="y")
    assert p.to_json()["seq"] > a


def test_progress_reaches_the_state_payload(sess):
    assert "task" in state_json(sess)
    assert state_json(sess)["task"]["active"] is False


def test_opening_a_project_publishes_its_stages(tmp_path, sess):
    """The stage channel must be written during the read, not only after."""
    p = tmp_path / "P.aedt"
    box(sess, "Box1")
    dispatch(sess, "project.save", {"path": str(p)})

    seen = []
    real = Progress.step

    def spy(self, *a, **kw):
        seen.append(kw.get("stage") or (a[0] if a else ""))
        return real(self, *a, **kw)

    Progress.step = spy
    try:
        dispatch(sess, "project.open", {"path": str(p)})
    finally:
        Progress.step = real
    assert any("design" in str(x) for x in seen), seen
    assert sess.progress.to_json()["active"] is False


def test_a_failed_open_clears_the_progress_channel(tmp_path, sess):
    bad = tmp_path / "nope.aedt"
    bad.write_text("not a project")
    with pytest.raises(Exception):
        dispatch(sess, "project.open", {"path": str(bad)})
    assert sess.progress.to_json()["active"] is False
    assert sess.progress.to_json()["error"]


# ------------------------------------------------- viewport: what changed
def test_geometry_carries_a_digest_per_object(sess):
    box(sess, "Box1")
    o = dispatch(sess, "view.geometry", {})["objects"][0]
    assert o["digest"]
    assert dispatch(sess, "view.geometry", {})["objects"][0]["digest"] == o["digest"]


def test_an_unchanged_body_is_not_resent(sess):
    box(sess, "Box1")
    box(sess, "Box2", pos=("40mm", "0mm", "0mm"))
    first = dispatch(sess, "view.geometry", {})["objects"]
    have = {o["name"]: o["digest"] for o in first}
    again = dispatch(sess, "view.geometry", {"have": have})["objects"]
    assert all(o.get("unchanged") for o in again)
    assert all(not o.get("position") for o in again)
    # display properties still travel, because they are cheap and may change
    assert all("color" in o and "visible" in o for o in again)


def test_moving_one_body_re_sends_only_that_body(sess):
    box(sess, "Box1")
    box(sess, "Box2", pos=("40mm", "0mm", "0mm"))
    have = {o["name"]: o["digest"]
            for o in dispatch(sess, "view.geometry", {})["objects"]}
    dispatch(sess, "modeler.transform",
             {"names": ["Box1"], "op": "move",
              "params": {"dx": "5mm", "dy": "0mm", "dz": "0mm"}})
    objs = {o["name"]: o for o in
            dispatch(sess, "view.geometry", {"have": have})["objects"]}
    assert not objs["Box1"].get("unchanged")
    assert objs["Box2"].get("unchanged") is True


def test_a_colour_change_alone_keeps_the_geometry(sess):
    box(sess, "Box1")
    have = {o["name"]: o["digest"]
            for o in dispatch(sess, "view.geometry", {})["objects"]}
    dispatch(sess, "modeler.setProperty",
             {"name": "Box1", "prop": "color", "value": "#ff0000"})
    o = dispatch(sess, "view.geometry", {"have": have})["objects"][0]
    assert o["unchanged"] is True and o["color"] == "#ff0000"


def test_renaming_a_body_does_not_invalidate_its_triangles(sess):
    """The digest is of the geometry; a name is not geometry."""
    box(sess, "Box1")
    before = dispatch(sess, "view.geometry", {})["objects"][0]["digest"]
    dispatch(sess, "modeler.setProperty",
             {"name": "Box1", "prop": "name", "value": "Patch"})
    after = dispatch(sess, "view.geometry", {})["objects"][0]
    assert after["name"] == "Patch" and after["digest"] == before


def test_the_default_response_is_unchanged_for_scripts(sess):
    """No `have`, no `binary`: exactly the payload every caller had before."""
    box(sess, "Box1")
    o = dispatch(sess, "view.geometry", {})["objects"][0]
    assert len(o["position"]) == o["count"] * 3
    assert "blobs" not in o and "unchanged" not in o


# ------------------------------------------------- viewport: how it travels
def test_binary_mode_moves_the_arrays_out_of_the_json(sess):
    from aether.gui.api import BLOBS
    box(sess, "Box1")
    o = dispatch(sess, "view.geometry", {"binary": True})["objects"][0]
    assert o["position"] == [] and o["blobs"]["position"]["type"] == "f32"
    ref = o["blobs"]["position"]
    raw = BLOBS[ref["blob"]]
    assert len(raw) == ref["len"] * 4
    pts = np.frombuffer(raw, np.float32)
    plain = dispatch(sess, "view.geometry", {})["objects"][0]["position"]
    assert np.allclose(pts, np.asarray(plain, np.float32), atol=1e-9)


def test_binary_mode_is_smaller_on_the_wire(sess):
    box(sess, "Box1")
    plain = json.dumps(dispatch(sess, "view.geometry", {}))
    packed = json.dumps(dispatch(sess, "view.geometry", {"binary": True}))
    assert len(packed) < len(plain) / 4


def test_identical_arrays_share_one_blob(sess):
    box(sess, "Box1")
    box(sess, "Box2")           # same size, so the same local triangles
    objs = dispatch(sess, "view.geometry", {"binary": True})["objects"]
    assert (objs[0]["blobs"]["position"]["blob"]
            == objs[1]["blobs"]["position"]["blob"])


# ------------------------------------------------------------- speed
def test_a_redraw_does_not_re_tessellate(sess):
    box(sess, "Box1", size=("10mm", "5mm", "1mm"))
    dispatch(sess, "view.geometry", {})
    import aether.gui.tessellate as T
    calls = {"n": 0}
    real = T.tessellate_occ

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    T.tessellate_occ = counting
    try:
        for _ in range(5):
            dispatch(sess, "view.geometry", {})
    finally:
        T.tessellate_occ = real
    assert calls["n"] == 0


def test_assignments_reuse_the_display_triangles(sess):
    box(sess, "Box1")
    dispatch(sess, "boundary.assign",
             {"type": "pec", "selector": {"kind": "outer"}})
    dispatch(sess, "view.assignments", {})
    t = time.perf_counter()
    for _ in range(5):
        dispatch(sess, "view.assignments", {})
    assert time.perf_counter() - t < 1.0


def test_face_clustering_agrees_with_the_reference_walk():
    """The vectorised clusterer must produce the same faces as the flood fill
    it replaced — a box has six, a closed cylinder three."""
    import aether.gui.tessellate as T
    from aether.geometry.primitives import Box, Cone, Cylinder, Sphere

    for shape, expected in [(Box(size=(1, 2, 3)), 6),
                            (Cylinder(radius=1, height=2), 3),
                            (Cone(r1=1, r2=0, height=2), 2),
                            (Sphere(radius=1), 1)]:
        fast = T.tessellate_analytic(shape)
        saved, T._cluster_faces_fast = T._cluster_faces_fast, lambda *a: None
        try:
            slow = T.tessellate_analytic(shape)
        finally:
            T._cluster_faces_fast = saved
        assert len(fast["faces"]) == expected
        assert len(slow["faces"]) == len(fast["faces"])
        assert (np.bincount(np.asarray(fast["faceOf"])).tolist()
                == np.bincount(np.asarray(slow["faceOf"])).tolist())


# ---------------------------------------------------------- other repairs
def test_export_refuses_an_empty_path(sess):
    class _Fake:
        sparams = None
    sess.solution = _Fake()
    with pytest.raises(ValueError, match="no file name"):
        dispatch(sess, "results.export", {"path": "", "format": "csv"})


def test_a_failed_edit_leaves_the_original_objects_in_place(sess):
    """A rolled-back command must not silently swap every body for a copy."""
    box(sess, "Box1")
    before = sess.design.get_solid("Box1")
    with pytest.raises(Exception):
        dispatch(sess, "modeler.transform",
                 {"names": ["NoSuchBox"], "op": "move",
                  "params": {"dx": "1mm", "dy": "0mm", "dz": "0mm"}})
    assert sess.design.get_solid("Box1") is before


def test_exit_says_so_when_no_server_is_attached(sess):
    assert dispatch(sess, "app.exit", {})["ok"] is False


