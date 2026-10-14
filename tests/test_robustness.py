"""
The failures that cost a whole file, and the ones that cost a whole afternoon.

Reading someone else's project or CAD file is the case where being strict is
wrong: the file is what it is, and a reader that stops at the first thing it
does not recognise hands back nothing at all. These check that damage costs
only the damaged part, that a large assembly is read once rather than once per
body, and that the things that made an import fail outright no longer do.
"""
import os
import time

import numpy as np
import pytest

from conftest import needs_occ

import aether as ae
from aether.gui.api import dispatch, state_json
from aether.gui.state import Session
from aether.io.aedt.tree import AedtDocument
from aether.io.aedt.values import parse_statement


# --------------------------------------------------- one bad line, one loss
def test_an_unparseable_statement_is_kept_verbatim():
    key, val = parse_statement("Bad='unterminated")
    assert key is None and val == "Bad='unterminated"


@pytest.mark.parametrize("stmt", [
    "Odd=['a', 'b",                       # unterminated list of strings
    "Weird='he said 'hello''",            # a quote convention we do not know
    "Trailing=",                          # nothing on the right
])
def test_odd_statements_never_raise(stmt):
    parse_statement(stmt)                 # must not raise


def test_a_stray_quote_does_not_swallow_the_rest_of_the_file():
    """The regression behind 'unterminated string near offset 0': the joiner
    kept looking for the closing quote to the end of the file, so the damage
    was one character and the report pointed thousands of lines away."""
    text = ("$begin 'P'\n\tA=1\n\tOops='no closing quote\n\tB=2\n"
            "\t$begin 'Inner'\n\t\tC=3\n\t$end 'Inner'\n$end 'P'\n")
    doc = AedtDocument.parse_text(text)
    root = doc.root
    assert root.get("A") == 1 and root.get("B") == 2
    assert root.block("Inner") is not None
    assert root.block("Inner").get("C") == 3
    assert doc.to_text() == text          # still byte-exact


def test_a_backslash_continuation_still_joins():
    """The base64 blocks in a real project do continue across lines, with a
    trailing backslash -- that must keep working."""
    text = ("$begin 'P'\n\tBlob='aaaa\\\n\tbbbb'\n$end 'P'\n")
    doc = AedtDocument.parse_text(text)
    assert doc.root.get("Blob") is not None
    assert doc.to_text() == text


def test_a_damaged_project_still_opens_in_the_workspace(tmp_path):
    p = tmp_path / "damaged.aedt"
    p.write_text(
        "$begin 'AnsoftProject'\n"
        "\t$begin 'HFSSModel'\n"
        "\t\tName='D'\n"
        "\t\tJunk='no closing quote\n"
        "\t\t$begin 'ModelSetup'\n"
        "\t\t\t$begin 'GeometryCore'\n"
        "\t\t\t\t$begin 'GeometryOperations'\n"
        "\t\t\t\t\t$begin 'ToplevelParts'\n"
        "\t\t\t\t\t\t$begin 'GeometryPart'\n"
        "\t\t\t\t\t\t\t$begin 'Attributes'\n"
        "\t\t\t\t\t\t\t\tName='Box1'\n"
        "\t\t\t\t\t\t\t$end 'Attributes'\n"
        "\t\t\t\t\t\t\t$begin 'Operations'\n"
        "\t\t\t\t\t\t\t\t$begin 'Operation'\n"
        "\t\t\t\t\t\t\t\t\t$begin 'BoxParameters'\n"
        "\t\t\t\t\t\t\t\t\t\tXPosition='0mm'\n"
        "\t\t\t\t\t\t\t\t\t\tYPosition='0mm'\n"
        "\t\t\t\t\t\t\t\t\t\tZPosition='0mm'\n"
        "\t\t\t\t\t\t\t\t\t\tXSize='8mm'\n"
        "\t\t\t\t\t\t\t\t\t\tYSize='4mm'\n"
        "\t\t\t\t\t\t\t\t\t\tZSize='2mm'\n"
        "\t\t\t\t\t\t\t\t\t$end 'BoxParameters'\n"
        "\t\t\t\t\t\t\t\t$end 'Operation'\n"
        "\t\t\t\t\t\t\t$end 'Operations'\n"
        "\t\t\t\t\t\t$end 'GeometryPart'\n"
        "\t\t\t\t\t$end 'ToplevelParts'\n"
        "\t\t\t\t$end 'GeometryOperations'\n"
        "\t\t\t$end 'GeometryCore'\n"
        "\t\t$end 'ModelSetup'\n"
        "\t$end 'HFSSModel'\n"
        "$end 'AnsoftProject'\n")
    s = Session()
    s.new_project("P")
    dispatch(s, "project.open", {"path": str(p)})
    assert [o.name for o in s.design.solids] == ["Box1"]


def test_an_unterminated_block_is_repaired_and_reported():
    doc = AedtDocument.parse_text("$begin 'A'\n\tX=1\n")
    assert doc.issues and "unterminated" in doc.issues[0]
    assert doc.root.get("X") == 1


# ------------------------------------------------ the file dialog and DXF
def test_the_cad_filter_offers_dxf():
    """The DXF reader was unreachable: the browser's CAD filter did not list
    .dxf, so the files simply were not shown."""
    from aether.gui import files as F
    allcad = F.filters("cad")[0]["ext"]
    assert ".dxf" in allcad
    assert any(".dxf" in f["ext"] and len(f["ext"]) == 1 for f in F.filters("cad"))


def test_choosing_a_format_actually_filters(tmp_path):
    from aether.gui import files as F
    for n in ("a.step", "b.dxf", "c.stl", "d.txt"):
        (tmp_path / n).write_text("x")
    s = Session()
    s.new_project("P")
    labels = [f["label"] for f in F.filters("cad")]
    dxf = labels.index("AutoCAD DXF (*.dxf)")
    r = dispatch(s, "files.browse", {"path": str(tmp_path), "kind": "cad",
                                     "filter": dxf})
    assert [f["name"] for f in r["files"]] == ["b.dxf"]
    r = dispatch(s, "files.browse", {"path": str(tmp_path), "kind": "cad"})
    assert sorted(f["name"] for f in r["files"]) == ["a.step", "b.dxf", "c.stl"]


# --------------------------------------------------------- import behaviour
@pytest.fixture()
def assembly(tmp_path):
    from aether.geometry.brep_io import export_shapes
    from aether.geometry.kernel import GmshSession, build_shape
    path = str(tmp_path / "asm.step")
    with GmshSession("mk") as gmsh:
        for i in range(12):
            build_shape(ae.Box((f"{i * 12}mm", "0mm", "0mm"),
                               ("10mm", f"{4 + i}mm", "2mm")), gmsh)
        gmsh.model.occ.synchronize()
        export_shapes(path, gmsh)
    return path


@needs_occ
def test_each_body_of_an_assembly_draws_as_itself(assembly):
    """The bodies shared one cache entry, so a whole assembly drew as
    whichever part happened to be tessellated first."""
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.importCad", {"path": assembly, "name": "A"})
    g = dispatch(s, "view.geometry", {})
    xs = [round(np.asarray(o["position"]).reshape(-1, 3).mean(0)[0] * 1e3, 1)
          for o in g["objects"]]
    assert len(xs) == 12
    assert len(set(xs)) == 12                       # every part in its place
    ys = [round(float(np.ptp(np.asarray(o["position"]).reshape(-1, 3), axis=0)[1]) * 1e3)
          for o in g["objects"]]
    assert sorted(ys) == list(range(4, 16))         # and its own size


@needs_occ
def test_a_large_assembly_is_read_once_not_once_per_body(assembly):
    """Twelve bodies used to mean twelve full imports for the bounds and
    twelve more for the display; that is what "it hangs" looked like."""
    from aether.geometry import brep_io

    reads = {"n": 0}
    real = brep_io.import_into_occ

    def counting(*a, **k):
        reads["n"] += 1
        return real(*a, **k)

    brep_io.import_into_occ = counting
    try:
        s = Session()
        s.new_project("P")
        dispatch(s, "modeler.importCad", {"path": assembly, "name": "A"})
        dispatch(s, "view.geometry", {})
    finally:
        brep_io.import_into_occ = real
    assert reads["n"] <= 4, f"{reads['n']} imports for a 12-body file"


@needs_occ
def test_the_display_of_an_assembly_is_cached(assembly):
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.importCad", {"path": assembly, "name": "A"})
    dispatch(s, "view.geometry", {})
    t = time.perf_counter()
    dispatch(s, "view.geometry", {})
    assert time.perf_counter() - t < 0.5


@needs_occ
def test_a_file_under_a_non_ascii_path_still_reads(tmp_path):
    """OpenCASCADE takes narrow file names, and on Windows a Korean folder
    name reaches it mangled -- the read then simply fails."""
    from aether.geometry.brep_io import export_shapes, quick_bounds
    from aether.geometry.kernel import GmshSession, build_shape
    folder = tmp_path / "설계 폴더"
    folder.mkdir()
    path = str(folder / "부품.step")
    with GmshSession("mk") as gmsh:
        build_shape(ae.Box((0, 0, 0), ("6mm", "4mm", "2mm")), gmsh)
        gmsh.model.occ.synchronize()
        export_shapes(path, gmsh)
    lo, hi = quick_bounds(path)
    assert np.allclose(np.asarray(hi) - np.asarray(lo), [6e-3, 4e-3, 2e-3],
                       atol=1e-5)


@needs_occ
def test_an_unreadable_step_says_what_to_try(tmp_path):
    p = tmp_path / "broken.step"
    p.write_text("ISO-10303-21;\nHEADER;\nthis is not a step file\n")
    s = Session()
    s.new_project("P")
    with pytest.raises(Exception, match="AP214|could not read|no geometry"):
        dispatch(s, "modeler.importCad", {"path": str(p), "name": "X"})


@needs_occ
def test_the_caches_are_bounded():
    from aether.geometry.brep_io import _BOUNDS_CACHE, _BOUNDS_LIMIT
    from aether.gui.tessellate import _TESS_BUDGET_TRIS, _TESS_CACHE
    assert len(_BOUNDS_CACHE) <= _BOUNDS_LIMIT
    tris = sum(len(v.get("position", ())) // 9 for v in _TESS_CACHE.values())
    assert tris <= _TESS_BUDGET_TRIS * 1.5


# ------------------------------------------- sheets are objects as well
@needs_occ
def test_a_sheet_takes_the_same_properties_as_a_solid(tmp_path):
    from test_dxf import rect, write_dxf
    p = write_dxf(tmp_path / "s.dxf", rect(0, 0, 10, 5))
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.importCad", {"path": p, "name": "Sheet1"})
    dispatch(s, "modeler.setProperty",
             {"name": "Sheet1", "prop": "color", "value": "#ff0000"})
    dispatch(s, "modeler.setProperty",
             {"name": "Sheet1", "prop": "transparency", "value": 0.7})
    sh = state_json(s)["design"]["sheets"][0]
    assert sh["color"] == "#ff0000" and sh["transparency"] == 0.7
    assert dispatch(s, "view.geometry", {})["objects"][0]["color"] == "#ff0000"


@needs_occ
def test_a_sheet_can_be_measured_and_hidden(tmp_path):
    from test_dxf import rect, write_dxf
    p = write_dxf(tmp_path / "s.dxf", rect(0, 0, 10, 5))
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.importCad", {"path": p, "name": "Sheet1"})
    dispatch(s, "modeler.select", {"names": ["Sheet1"], "mode": "object"})
    m = dispatch(s, "modeler.measure", {})
    assert m["kind"] == "object"
    assert m["size"][:2] == pytest.approx([10e-3, 5e-3])
    dispatch(s, "modeler.setProperty",
             {"name": "Sheet1", "prop": "visible", "value": False})
    assert dispatch(s, "view.geometry", {})["objects"][0]["visible"] is False


@needs_occ
def test_a_sheet_stays_a_sheet_through_a_project_file(tmp_path):
    from test_dxf import rect, write_dxf
    p = write_dxf(tmp_path / "s.dxf", rect(0, 0, 10, 5))
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.importCad", {"path": p, "name": "Sheet1"})
    dispatch(s, "modeler.setProperty",
             {"name": "Sheet1", "prop": "color", "value": "#00ff00"})
    proj = str(tmp_path / "p.aedt")
    dispatch(s, "project.save", {"path": proj})
    s2 = Session()
    dispatch(s2, "project.open", {"path": proj})
    assert [x.name for x in s2.design.sheets] == ["Sheet1"]
    assert s2.design.sheets[0].display_color == "#00ff00"


@needs_occ
def test_every_body_of_a_saved_assembly_comes_back_as_itself(assembly, tmp_path):
    """The body index was not written, so a reopened assembly was the same
    part twelve times."""
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.importCad", {"path": assembly, "name": "A"})
    proj = str(tmp_path / "asm.aedt")
    dispatch(s, "project.save", {"path": proj})
    s2 = Session()
    dispatch(s2, "project.open", {"path": proj})
    ys = sorted(round((o.shape.bounds()[1][1] - o.shape.bounds()[0][1]) * 1e3)
                for o in s2.design.solids)
    assert ys == list(range(4, 16))
