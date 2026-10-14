"""
The DXF reader, and what a drawing becomes once it is in the model.

A DXF is where an antenna trace, a PCB outline or a mechanical cut-out
usually starts, and it is a drawing rather than a model: entities on layers,
in a unit stated as a numeric code. These check that the outlines come back
with the right size, that holes end up as holes, and that one face sweep
turns the drawing into copper.
"""
import numpy as np
import pytest

from conftest import needs_occ

from aether.geometry.dxf import DxfError, Polyline, outlines, read_dxf, summary
from aether.gui.api import dispatch, state_json
from aether.gui.state import Session


def write_dxf(path, entities, insunits=4):
    out = []

    def pair(c, v):
        out.append(str(c))
        out.append(str(v))

    pair(0, "SECTION"); pair(2, "HEADER")
    if insunits is not None:
        pair(9, "$INSUNITS"); pair(70, insunits)
    pair(0, "ENDSEC")
    pair(0, "SECTION"); pair(2, "ENTITIES")
    out += entities
    pair(0, "ENDSEC"); pair(0, "EOF")
    path.write_text("\n".join(out) + "\n")
    return str(path)


def rect(x0, y0, w, h, layer="0"):
    e = ["0", "LWPOLYLINE", "8", layer, "90", "4", "70", "1"]
    for x, y in ((x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)):
        e += ["10", str(x), "20", str(y)]
    return e


def circle(x, y, r, layer="0"):
    return ["0", "CIRCLE", "8", layer, "10", str(x), "20", str(y),
            "30", "0", "40", str(r)]


@pytest.fixture()
def drawing(tmp_path):
    """A 20 x 10 mm outline with a 3 mm-radius hole, plus a stray line."""
    ents = rect(0, 0, 20, 10, "OUTLINE") + circle(10, 5, 3, "HOLES") + [
        "0", "LINE", "8", "NOTES", "10", "0", "20", "0", "30", "0",
        "11", "20", "21", "10", "31", "0"]
    return write_dxf(tmp_path / "board.dxf", ents)


# ------------------------------------------------------------- the reader
def test_entities_come_back_at_the_declared_size(drawing):
    doc = read_dxf(drawing)
    assert doc["declaredUnit"] == "mm" and doc["appliedUnit"] == "mm"
    closed = [p for p in doc["entities"] if p.closed]
    assert len(closed) == 2
    outline = max(closed, key=lambda p: p.area)
    assert outline.area == pytest.approx(200e-6, rel=1e-9)
    assert outline.length == pytest.approx(60e-3, rel=1e-9)


def test_a_circle_is_flattened_close_to_its_true_area(drawing):
    hole = min((p for p in read_dxf(drawing)["entities"] if p.closed),
               key=lambda p: p.area)
    assert hole.area == pytest.approx(np.pi * 3e-3 ** 2, rel=3e-3)


def test_layers_are_reported(drawing):
    assert set(summary(drawing)["layers"]) == {"OUTLINE", "HOLES", "NOTES"}


def test_an_open_entity_is_not_an_outline(drawing):
    assert all(p.closed for p in outlines(drawing))
    assert len(outlines(drawing)) == 2


def test_a_drawing_without_a_unit_is_read_as_millimetres(tmp_path):
    p = write_dxf(tmp_path / "nounit.dxf", rect(0, 0, 10, 10), insunits=None)
    doc = read_dxf(p)
    assert doc["appliedUnit"] == "mm"
    assert doc["entities"][0].area == pytest.approx(100e-6)


def test_the_unit_can_be_overridden(tmp_path):
    p = write_dxf(tmp_path / "inch.dxf", rect(0, 0, 1, 1), insunits=1)
    assert read_dxf(p)["appliedUnit"] == "in"
    assert read_dxf(p)["entities"][0].area == pytest.approx(2.54e-2 ** 2)
    assert read_dxf(p, unit="mm")["entities"][0].area == pytest.approx(1e-6)


def test_an_arc_bulge_becomes_an_arc(tmp_path):
    """A bulge is DXF's way of writing a fillet; ignoring it would cut the
    corner straight across."""
    e = ["0", "LWPOLYLINE", "8", "0", "90", "2", "70", "1",
         "10", "0", "20", "0", "42", "1.0",          # half circle
         "10", "10", "20", "0"]
    p = write_dxf(tmp_path / "bulge.dxf", e)
    poly = read_dxf(p)["entities"][0]
    assert len(poly.points) > 10                       # flattened, not a chord
    assert poly.area == pytest.approx(np.pi * 5e-3 ** 2 / 2, rel=5e-3)


def test_a_polyline_entity_is_read(tmp_path):
    e = ["0", "POLYLINE", "8", "0", "70", "1"]
    for x, y in ((0, 0), (4, 0), (4, 4), (0, 4)):
        e += ["0", "VERTEX", "10", str(x), "20", str(y), "30", "0"]
    e += ["0", "SEQEND"]
    p = write_dxf(tmp_path / "poly.dxf", e)
    poly = read_dxf(p)["entities"][0]
    assert poly.closed and poly.area == pytest.approx(16e-6)


def test_a_binary_dxf_is_refused_with_an_explanation(tmp_path):
    p = tmp_path / "binary.dxf"
    p.write_bytes(b"AutoCAD Binary DXF\r\n\x1a\x00\x00\x00\x00\x00")
    with pytest.raises(DxfError, match="ASCII"):
        read_dxf(str(p))


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(DxfError):
        read_dxf(str(tmp_path / "nothing.dxf"))


# ------------------------------------------------------- into the model
@needs_occ
def test_a_drawing_imports_as_a_sheet_with_its_holes_cut(drawing):
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.importCad", {"path": drawing, "name": "Board"})
    st = state_json(s)
    assert [x["name"] for x in st["design"]["sheets"]] == ["Board", "Board_Reference"]
    g = dispatch(s, "view.geometry", {})
    o = g["objects"][0]
    assert o["isSheet"] is True
    # 20 x 10 minus a 3 mm-radius hole
    area = sum(f["area"] for f in o["faces"])
    assert area == pytest.approx(200e-6 - np.pi * 3e-3 ** 2, rel=3e-3)


@needs_occ
def test_sweeping_the_sheet_makes_copper(drawing):
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.importCad", {"path": drawing, "name": "Board"})
    g = dispatch(s, "view.geometry", {})
    face = dict(g["objects"][0]["faces"][0], object="Board")
    dispatch(s, "modeler.select", {"faces": [face], "mode": "face"})
    r = dispatch(s, "modeler.faceOperation",
                 {"op": "sweep", "distance": "0.035mm"})
    assert r["becameSolid"] is True
    assert [o.name for o in s.design.solids] == ["Board"]
    assert len(s.design.sheets) == 1
    assert s.design.sheets[0].shape.reference_only
    lo, hi = s.design.get_solid("Board").shape.bounds()
    assert hi[2] - lo[2] == pytest.approx(35e-6, rel=1e-6)


def test_a_drawing_with_no_closed_outline_loads_as_reference(tmp_path):
    p = write_dxf(tmp_path / "lines.dxf",
                  ["0", "LINE", "8", "0", "10", "0", "20", "0", "30", "0",
                   "11", "5", "21", "5", "31", "0"])
    s = Session()
    s.new_project("P")
    r = dispatch(s, "modeler.importCad", {"path": p, "name": "L"})
    assert r["info"]["referencePaths"] == 1
    assert s.design.sheets[0].shape.reference_only


def test_the_import_dialog_can_describe_a_drawing(drawing):
    from aether.geometry.brep_io import inspect
    info = inspect(drawing)
    assert info["format"] == "dxf" and info["error"] == ""
    assert info["surfaces"] == 2 and info["declaredUnit"] == "mm"
    assert info["entities"] == 3
