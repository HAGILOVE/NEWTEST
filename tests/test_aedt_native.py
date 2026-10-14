"""
Reading the .aedt files the HFSS desktop actually writes.

A project saved from the modeller is not the tidy text tree the format
description suggests. It carries Parasolid bodies as length-prefixed binary
blobs inside the block structure, names its design block after the solver,
puts boundaries a level deeper than a scripted project does, and attaches them
to kernel body ids rather than to names. Each of those is enough on its own to
turn "open this project" into a parse error or an empty model, so each has a
test here, built on a file with the same shape as the real thing.
"""
import os

import numpy as np
import pytest

from conftest import needs_occ

from aether.gui.api import dispatch, state_json
from aether.gui.state import Session
from aether.io.aedt.lexer import split_logical
from aether.io.aedt.tree import AedtBinary, AedtDocument
from aether.io.aedt.translate import read_project

# A miniature of the real thing: the desktop's block names, a boundary given
# by body id, a wave port, and two native bodies whose Parasolid payloads
# contain quotes, brackets and a literal "$end" -- the bytes that break a
# line-oriented parser.
BODY_A = b"**PARASOLID !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~\n$end 'x_b' fake\n\x00\x01\x02"
BODY_B = b"\x00\x01binary body two\nwith a newline and 'quotes'\x00"


def _project(bodies=(BODY_A, BODY_B)) -> bytes:
    def blob(name, data):
        return (b"$begin 'x_b'\nDesign_0.setup/NativeGeometryFiles/" + name
                + b"\nBIN" + f"{len(data):012d}".encode() + b"\n" + data
                + b"$end 'x_b'\n")

    text = (
        "$begin 'AnsoftProject'\n"
        "\tCreated='Tue Jul  5 16:17:08 2022'\n"
        "\t$begin 'HFSSModel'\n"
        "\t\tName='HFSSDesign1'\n"
        "\t\tDesignID=0\n"
        "\t\t$begin 'ModelSetup'\n"
        "\t\t\t$begin 'GeometryCore'\n"
        "\t\t\t\t$begin 'GeometryOperations'\n"
        "\t\t\t\t\t$begin 'ToplevelParts'\n"
        "\t\t\t\t\t\t$begin 'GeometryPart'\n"
        "\t\t\t\t\t\t\t$begin 'Attributes'\n"
        "\t\t\t\t\t\t\t\tName='ground_plane'\n"
        "\t\t\t\t\t\t\t\tMaterialValue='\"copper\"'\n"
        "\t\t\t\t\t\t\t\tSolveInside=false\n"
        "\t\t\t\t\t\t\t$end 'Attributes'\n"
        "\t\t\t\t\t\t\t$begin 'Operations'\n"
        "\t\t\t\t\t\t\t\t$begin 'Operation'\n"
        "\t\t\t\t\t\t\t\t\tOperationType='NativeBody'\n"
        "\t\t\t\t\t\t\t\t\tParentPartID=1223\n"
        "\t\t\t\t\t\t\t\t\t$begin 'BodyBlock'\n"
        "\t\t\t\t\t\t\t\t\t\tBodyFileNamesVec[1: '0000006.x_b']\n"
        "\t\t\t\t\t\t\t\t\t$end 'BodyBlock'\n"
        "\t\t\t\t\t\t\t\t$end 'Operation'\n"
        "\t\t\t\t\t\t\t$end 'Operations'\n"
        "\t\t\t\t\t\t$end 'GeometryPart'\n"
        "\t\t\t\t\t\t$begin 'GeometryPart'\n"
        "\t\t\t\t\t\t\t$begin 'Attributes'\n"
        "\t\t\t\t\t\t\t\tName='Box1'\n"
        "\t\t\t\t\t\t\t\tMaterialValue='\"vacuum\"'\n"
        "\t\t\t\t\t\t\t$end 'Attributes'\n"
        "\t\t\t\t\t\t\t$begin 'Operations'\n"
        "\t\t\t\t\t\t\t\t$begin 'Operation'\n"
        "\t\t\t\t\t\t\t\t\tOperationType='Box'\n"
        "\t\t\t\t\t\t\t\t\tParentPartID=1255\n"
        "\t\t\t\t\t\t\t\t\t$begin 'BoxParameters'\n"
        "\t\t\t\t\t\t\t\t\t\tXPosition='0mm'\n"
        "\t\t\t\t\t\t\t\t\t\tYPosition='0mm'\n"
        "\t\t\t\t\t\t\t\t\t\tZPosition='0mm'\n"
        "\t\t\t\t\t\t\t\t\t\tXSize='20mm'\n"
        "\t\t\t\t\t\t\t\t\t\tYSize='10mm'\n"
        "\t\t\t\t\t\t\t\t\t\tZSize='4mm'\n"
        "\t\t\t\t\t\t\t\t\t$end 'BoxParameters'\n"
        "\t\t\t\t\t\t\t\t$end 'Operation'\n"
        "\t\t\t\t\t\t\t$end 'Operations'\n"
        "\t\t\t\t\t\t$end 'GeometryPart'\n"
        "\t\t\t\t\t$end 'ToplevelParts'\n"
        "\t\t\t\t\t$begin 'OperandParts'\n"
        "\t\t\t\t\t\t$begin 'GeometryPart'\n"
        "\t\t\t\t\t\t\t$begin 'Attributes'\n"
        "\t\t\t\t\t\t\t\tName='operand_do_not_import'\n"
        "\t\t\t\t\t\t\t$end 'Attributes'\n"
        "\t\t\t\t\t\t\t$begin 'Operations'\n"
        "\t\t\t\t\t\t\t\t$begin 'Operation'\n"
        "\t\t\t\t\t\t\t\t\tOperationType='Box'\n"
        "\t\t\t\t\t\t\t\t\tParentPartID=999\n"
        "\t\t\t\t\t\t\t\t\t$begin 'BoxParameters'\n"
        "\t\t\t\t\t\t\t\t\t\tXPosition='0mm'\n"
        "\t\t\t\t\t\t\t\t\t\tYPosition='0mm'\n"
        "\t\t\t\t\t\t\t\t\t\tZPosition='0mm'\n"
        "\t\t\t\t\t\t\t\t\t\tXSize='1mm'\n"
        "\t\t\t\t\t\t\t\t\t\tYSize='1mm'\n"
        "\t\t\t\t\t\t\t\t\t\tZSize='1mm'\n"
        "\t\t\t\t\t\t\t\t\t$end 'BoxParameters'\n"
        "\t\t\t\t\t\t\t\t$end 'Operation'\n"
        "\t\t\t\t\t\t\t$end 'Operations'\n"
        "\t\t\t\t\t\t$end 'GeometryPart'\n"
        "\t\t\t\t\t$end 'OperandParts'\n"
        "\t\t\t\t$end 'GeometryOperations'\n"
        "\t\t\t$end 'GeometryCore'\n"
        "\t\t$end 'ModelSetup'\n"
        "\t\t$begin 'BoundarySetup'\n"
        "\t\t\t$begin 'Boundaries'\n"
        "\t\t\t\t$begin 'PerfE1'\n"
        "\t\t\t\t\tBoundType='Perfect E'\n"
        "\t\t\t\t\tObjects(1223)\n"
        "\t\t\t\t$end 'PerfE1'\n"
        "\t\t\t\t$begin 'PML_radiation1'\n"
        "\t\t\t\t\tBoundType='Radiation'\n"
        "\t\t\t\t\tFaces(145)\n"
        "\t\t\t\t$end 'PML_radiation1'\n"
        "\t\t\t\t$begin '2'\n"
        "\t\t\t\t\tBoundType='Wave Port'\n"
        "\t\t\t\t\tNumModes=1\n"
        "\t\t\t\t\tObjects(1255)\n"
        "\t\t\t\t$end '2'\n"
        "\t\t\t$end 'Boundaries'\n"
        "\t\t$end 'BoundarySetup'\n"
        "\t$end 'HFSSModel'\n"
        "$end 'AnsoftProject'\n"
        "$begin 'AllReferencedFilesForProject'\n"
        "$begin 'Design_0.setup/NativeGeometryFiles'\n"
        "NumFiles= 2\n"
    ).encode("latin-1")
    text += blob(b"0000006.x_b", bodies[0])
    text += blob(b"0000007.x_b", bodies[1])
    text += b"$end 'Design_0.setup/NativeGeometryFiles'\n"
    text += b"$end 'AllReferencedFilesForProject'\n"
    return text


@pytest.fixture()
def native(tmp_path):
    p = tmp_path / "patch.aedt"
    p.write_bytes(_project())
    return str(p)


# ------------------------------------------------------------ the lexer
def test_binary_payloads_are_taken_by_length_not_scanned(native):
    text = open(native, encoding="latin-1").read()
    lines = split_logical(text)
    payloads = [l for l in lines if l.kind == "binary"]
    assert len(payloads) == 2
    # the "$end 'x_b'" inside the payload is data, not a statement
    ends = [l for l in lines if l.kind == "end" and l.block_name == "x_b"]
    assert len(ends) == 2


def test_a_desktop_project_parses_at_all(native):
    """The regression: 'unterminated block x_b'."""
    doc = AedtDocument.parse(native)
    assert [getattr(r, "name", "") for r in doc.roots][:2] == \
        ["AnsoftProject", "AllReferencedFilesForProject"]
    assert len(doc.designs()) == 1


def test_the_round_trip_is_byte_exact_binaries_included(native):
    doc = AedtDocument.parse(native)
    assert doc.to_text().encode(doc.encoding) == open(native, "rb").read()


def test_the_payload_bytes_are_kept_verbatim(native):
    doc = AedtDocument.parse(native)
    blobs = [n for b in doc.roots if hasattr(b, "walk")
             for sub in b.walk() for n in sub.children
             if isinstance(n, AedtBinary)]
    assert [b.data("latin-1") for b in blobs] == [BODY_A, BODY_B]


def test_an_edited_project_still_writes_its_binaries(native, tmp_path):
    doc = AedtDocument.parse(native)
    doc.designs()[0].set("Name", "Renamed")
    out = str(tmp_path / "out.aedt")
    doc.write(out)
    again = AedtDocument.parse(out)
    blobs = [n for b in again.roots if hasattr(b, "walk")
             for sub in b.walk() for n in sub.children
             if isinstance(n, AedtBinary)]
    assert [b.data("latin-1") for b in blobs] == [BODY_A, BODY_B]


# ------------------------------------------------------- the translation
def test_the_design_is_found_under_its_solver_specific_name(native):
    proj, reports = read_project(native)
    assert [d.name for d in proj.designs] == ["HFSSDesign1"]


def test_operand_parts_are_not_imported_as_objects(native):
    proj, _ = read_project(native)
    names = [o.name for o in proj.designs[0].solids]
    assert "Box1" in names and "ground_plane" in names
    assert "operand_do_not_import" not in names


def test_a_native_body_becomes_a_part_needing_a_readable_source(native):
    proj, reports = read_project(native)
    o = proj.designs[0].get_solid("ground_plane")
    assert "Parasolid" in o.shape._cad_unreadable
    assert o.material.name == "copper"
    # it still has an extent, so nothing downstream divides by it
    assert o.shape.bounds() == ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


def test_the_embedded_bodies_are_written_out_beside_the_project(native, tmp_path):
    proj, reports = read_project(native)
    folder = tmp_path / "patch.cad"
    assert (folder / "0000006.x_b").read_bytes() == BODY_A
    assert reports[0].extracted


def test_a_boundary_given_by_body_id_finds_its_object(native):
    proj, reports = read_project(native)
    d = proj.designs[0]
    assert "PerfE1" in [b.name for b in d.boundaries]
    assert reports[0].part_ids[1223] == "ground_plane"


def test_a_wave_port_given_by_body_id_is_read_as_an_excitation(native):
    proj, reports = read_project(native)
    d = proj.designs[0]
    assert [p.name for p in d.ports] == ["2"]
    # and it is not also reported as an unsupported boundary type
    assert not any("unsupported type 'Wave Port'" in u
                   for u in reports[0].unresolved)


def test_the_pml_apparatus_is_dropped_and_replaced_by_a_radiation_boundary(native):
    """
    HFSS's PML is geometry plus materials plus per-face boundaries, none of
    which is the model the engineer drew. It is dropped on import and the
    open condition it stood for is put back on the outer surface.
    """
    proj, reports = read_project(native)
    d = proj.designs[0]
    assert "PML_radiation1" in reports[0].pml_boundaries
    assert not any("PML" in u for u in reports[0].unresolved)
    rad = [b for b in d.boundaries if b.btype == "radiation"]
    assert [b.name for b in rad] == ["Radiation1"]


def test_an_analytic_part_still_comes_back_as_real_geometry(native):
    proj, _ = read_project(native)
    lo, hi = proj.designs[0].get_solid("Box1").shape.bounds()
    assert np.allclose(np.array(hi) - np.array(lo), [20e-3, 10e-3, 4e-3])


def test_the_workspace_opens_it(native):
    s = Session()
    s.new_project("P")
    dispatch(s, "project.open", {"path": native})
    st = state_json(s)
    names = [o["name"] for o in st["design"]["objects"]]
    assert "Box1" in names and "ground_plane" in names
    gp = [o for o in st["design"]["objects"] if o["name"] == "ground_plane"][0]
    assert "Parasolid" in gp["cad"]["unreadable"]


@needs_occ
def test_an_unreadable_body_can_be_repointed_at_a_step_file(native, tmp_path):
    """The completion path: export STEP from HFSS, then Replace CAD Source."""
    import aether as ae
    from aether.geometry.brep_io import export_shapes
    from aether.geometry.kernel import GmshSession, build_shape
    step = str(tmp_path / "ground.step")
    with GmshSession("mk") as gmsh:
        build_shape(ae.Box((0, 0, 0), ("30mm", "20mm", "0.5mm")), gmsh)
        gmsh.model.occ.synchronize()
        export_shapes(step, gmsh)

    s = Session()
    s.new_project("P")
    dispatch(s, "project.open", {"path": native})
    dispatch(s, "modeler.replaceCad", {"name": "ground_plane", "path": step})
    sh = s.design.get_solid("ground_plane").shape
    assert sh._cad_unreadable == ""
    lo, hi = sh.bounds()
    assert np.allclose(np.array(hi) - np.array(lo), [30e-3, 20e-3, 0.5e-3],
                       atol=1e-6)


# ------------------------------------------------- hostile property values
HOSTILE = """$begin 'AnsoftProject'
\t$begin 'HFSSModel'
\t\tName='D'
\t\t$begin 'ModelSetup'
\t\t\t$begin 'GeometryCore'
\t\t\t\t$begin 'GeometryOperations'
\t\t\t\t\t$begin 'ToplevelParts'
\t\t\t\t\t\t$begin 'GeometryPart'
\t\t\t\t\t\t\t$begin 'Attributes'
\t\t\t\t\t\t\t\tName='Box1'
\t\t\t\t\t\t\t\tReferenceTemperature='20cel'
\t\t\t\t\t\t\t$end 'Attributes'
\t\t\t\t\t\t\t$begin 'Operations'
\t\t\t\t\t\t\t\t$begin 'Operation'
\t\t\t\t\t\t\t\t\tParentPartID=7
\t\t\t\t\t\t\t\t\t$begin 'BoxParameters'
\t\t\t\t\t\t\t\t\t\tXPosition='0mm'
\t\t\t\t\t\t\t\t\t\tYPosition='0mm'
\t\t\t\t\t\t\t\t\t\tZPosition='0mm'
\t\t\t\t\t\t\t\t\t\tXSize='10mm'
\t\t\t\t\t\t\t\t\t\tYSize='5mm'
\t\t\t\t\t\t\t\t\t\tZSize='2mm'
\t\t\t\t\t\t\t\t\t$end 'BoxParameters'
\t\t\t\t\t\t\t\t$end 'Operation'
\t\t\t\t\t\t\t$end 'Operations'
\t\t\t\t\t\t$end 'GeometryPart'
\t\t\t\t\t$end 'ToplevelParts'
\t\t\t\t$end 'GeometryOperations'
\t\t\t$end 'GeometryCore'
\t\t$end 'ModelSetup'
\t\t$begin 'BoundarySetup'
\t\t\t$begin 'Boundaries'
\t\t\t\t$begin 'Imp1'
\t\t\t\t\tBoundType='Impedance'
\t\t\t\t\tObjects(7)
\t\t\t\t\tResistance='50ohm'
\t\t\t\t\tReactance='3 utter nonsense'
\t\t\t\t$end 'Imp1'
\t\t\t\t$begin 'PerfE1'
\t\t\t\t\tBoundType='Perfect E'
\t\t\t\t\tObjects(7)
\t\t\t\t$end 'PerfE1'
\t\t\t$end 'Boundaries'
\t\t$end 'BoundarySetup'
\t\t$begin 'AnalysisSetup'
\t\t\t$begin 'SolveSetups'
\t\t\t\t$begin 'Setup1'
\t\t\t\t\t$begin 'SolveSetupProps'
\t\t\t\t\t\tFrequency='10GHz'
\t\t\t\t\t\tTemperature='20cel'
\t\t\t\t\t$end 'SolveSetupProps'
\t\t\t\t$end 'Setup1'
\t\t\t$end 'SolveSetups'
\t\t$end 'AnalysisSetup'
\t$end 'HFSSModel'
$end 'AnsoftProject'
"""


def test_a_temperature_value_does_not_abort_the_load(tmp_path):
    """The regression: 'invalid decimal literal' — '20cel' is on every part of
    a desktop-written project, and one unparseable value used to cost the
    entire model."""
    p = tmp_path / "hostile.aedt"
    p.write_text(HOSTILE)
    proj, reports = read_project(str(p))
    d = proj.designs[0]
    assert [o.name for o in d.solids] == ["Box1"]
    assert [s.name for s in d.setups] == ["Setup1"]


def test_one_bad_property_costs_only_its_own_item(tmp_path):
    p = tmp_path / "hostile.aedt"
    p.write_text(HOSTILE)
    proj, reports = read_project(str(p))
    d = proj.designs[0]
    # the impedance boundary has an unreadable reactance and is skipped ...
    assert [b.name for b in d.boundaries] == ["PerfE1"]
    # ... loudly
    assert any("Imp1" in u for u in reports[0].unresolved)


@pytest.mark.parametrize("expr, value", [
    ("20cel", 293.15),            # every part carries this one
    ("10mm", 0.01),
    ("2*3mm", 0.006),
    ("1e-3meter", 1e-3),
    ("3W", 3.0),
    ("100pF", 1e-10),
    ("5nH", 5e-9),
    ("2uohm", 2e-6),
    ("50%", 0.5),
])
def test_expressions_that_used_to_be_syntax_errors(expr, value):
    from aether.io.aedt.expr import evaluate
    assert evaluate(expr) == pytest.approx(value)


def test_an_unreadable_expression_raises_a_typed_error_not_a_syntax_error():
    from aether.io.aedt.expr import ExpressionError, evaluate
    with pytest.raises(ExpressionError):
        evaluate("3 utter nonsense")
    with pytest.raises(ExpressionError):
        evaluate("$missing * 2")


def test_the_workspace_says_why_the_viewport_is_empty(native):
    """A project of native bodies has nothing to draw. That has to be stated
    once, plainly, rather than left as an empty screen."""
    s = Session()
    s.new_project("P")
    n0 = s.messages.seq
    r = dispatch(s, "project.open", {"path": native})
    assert r["missingGeometry"] == ["ground_plane"]
    said = " ".join(m["text"] for m in s.messages.since(n0))
    assert "no readable geometry" in said and "Repair Bodies" in said
    g = dispatch(s, "view.geometry", {})
    assert g["missing"] == ["ground_plane"]
    assert [o["name"] for o in g["objects"]] == ["Box1"]   # the rest still draws


def test_a_body_with_no_geometry_does_not_warn_on_every_redraw(native):
    s = Session()
    s.new_project("P")
    dispatch(s, "project.open", {"path": native})
    n0 = s.messages.seq
    for _ in range(3):
        dispatch(s, "view.geometry", {})
    assert [m for m in s.messages.since(n0)] == []
