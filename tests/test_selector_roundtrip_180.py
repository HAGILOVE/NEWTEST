"""Every kind of selection must survive Save and Open.

A face picked in the viewport, several picked faces, and selections combined
with union / intersect / invert used to be written as "all outer faces": the
project reopened without error and with a different model."""
import numpy as np
import pytest

import aether as ae
from aether.geometry.select import (BoxSelector, FaceSelector, OuterSelector,
                                    PlaneSelector, invert_sel, intersect_sel,
                                    union_sel, MultiFaceSelector, Predicate)
from aether.io.warp.translate import read_project
from aether.io.warp.writer import write_project


def roundtrip(d, tmp_path):
    p = str(tmp_path / "x.warp")
    write_project(p, d)
    proj, reports = read_project(p)
    return proj[0], reports


def probe(sel):
    """What a selector picks on a fixed set of triangle centres/normals."""
    rng = np.random.default_rng(3)
    cen = rng.uniform(-1e-2, 3e-2, (400, 3))
    cen[:100, 2] = 5e-3                                   # a plane's worth
    nrm = np.tile([0.0, 0.0, 1.0], (400, 1))
    return np.asarray(sel(cen, nrm), bool)


def design(sel_a, sel_b=None):
    d = ae.Design("t", units="mm")
    d.add_box("b", (0, 0, 0), (0.02, 0.02, 0.01), "vacuum")
    d.assign_pec("A", sel_a)
    if sel_b is not None:
        d.assign_pec("B", sel_b)
    return d


FACE = dict(point=(0.01, 0.01, 0.005), normal=(0, 0, 1), lo=(0, 0, 0.005),
            hi=(0.02, 0.02, 0.005), planar=True, object="b")


def test_a_picked_face_is_stored_by_its_geometry(tmp_path):
    d2, _ = roundtrip(design(FaceSelector(**FACE)), tmp_path)
    got = next(b for b in d2.boundaries if b.name == "A").selector
    assert isinstance(got, FaceSelector) and got.object == "b"
    np.testing.assert_array_equal(probe(got), probe(FaceSelector(**FACE)))
    assert probe(got).sum() > 0


def test_several_picked_faces_stay_several_faces(tmp_path):
    a = FaceSelector(**FACE)
    b = FaceSelector(**dict(FACE, point=(0.01, 0.01, 0.0), lo=(0, 0, 0), hi=(0.02, 0.02, 0)))
    sel = MultiFaceSelector([a, b])
    d2, _ = roundtrip(design(sel), tmp_path)
    got = next(x for x in d2.boundaries if x.name == "A").selector
    assert isinstance(got, MultiFaceSelector) and len(got.faces) == 2
    np.testing.assert_array_equal(probe(got), probe(sel))


@pytest.mark.parametrize("make", [
    lambda: union_sel(BoxSelector((0, 0, 0.004), (0.01, 0.02, 0.006)),
                      BoxSelector((0.015, 0, 0.004), (0.02, 0.02, 0.006))),
    lambda: intersect_sel(BoxSelector((0, 0, 0), (0.03, 0.03, 0.03)),
                          PlaneSelector("z", 0.005)),
    lambda: invert_sel(PlaneSelector("z", 0.005)),
    lambda: union_sel(invert_sel(PlaneSelector("z", 0.005)), FaceSelector(**FACE)),
])
def test_combined_selectors_round_trip(make, tmp_path):
    sel = make()
    d2, _ = roundtrip(design(sel), tmp_path)
    got = next(x for x in d2.boundaries if x.name == "A").selector
    assert not isinstance(got, OuterSelector)
    np.testing.assert_array_equal(probe(got), probe(sel))


def test_a_script_function_selector_is_reported_not_turned_into_outer(tmp_path):
    sel = Predicate(lambda c, n: c[:, 2] > 0)
    p = str(tmp_path / "x.warp")
    write_project(p, design(sel))
    proj, reports = read_project(p)
    assert not any(b.name == "A" for b in proj[0].boundaries)
    assert any("A" in u and "script" in u for r in reports for u in r.unresolved)
