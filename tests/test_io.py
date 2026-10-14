"""File interchange: .aedt tree, HFSS model translation, Touchstone, CSV, VTK."""
import os

import numpy as np
import pytest

import aether as ae
from aether.io.aedt.expr import VariableScope, evaluate
from aether.io.aedt.tree import AedtDocument
from aether.io.aedt.translate import read_project
from aether.io.aedt.values import Call, format_statement, parse_statement
from aether.io.aedt.writer import write_project
from aether.io.touchstone import read_touchstone, write_touchstone

SAMPLE = (
    "$begin 'AnsoftProject'\n"
    "\tFileVersion(1, 0)\n"
    "\tCreated='Tue Sep 02 09:11:04 2026'\n"
    "\n"
    "\t$begin 'Desktop'\n"
    "\t\tVersion(2024, 2)\n"
    "\t\tInfoStr='It\\'s fine'\n"
    "\t\tList=[1, 2, 3.5]\n"
    "\t\tWrapped=[\n"
    "\t\t  1, 2,\n"
    "\t\t  3]\n"
    "\t$end 'Desktop'\n"
    "\t$begin 'Design'\n"
    "\t\tDesignType='HFSS'\n"
    "\t\tName='HFSSDesign1'\n"
    "\t\tSolutionType='HFSS Modal Network'\n"
    "\t$end 'Design'\n"
    "$end 'AnsoftProject'\n"
)


# ---------------------------------------------------------------- .aedt tree
def test_aedt_text_round_trip_is_byte_identical():
    doc = AedtDocument.parse_text(SAMPLE)
    assert doc.to_text() == SAMPLE


def test_aedt_parses_values_and_nesting():
    doc = AedtDocument.parse_text(SAMPLE)
    assert doc.root.get("Created").startswith("Tue Sep")
    dk = doc.root.path("Desktop")
    assert dk.get("InfoStr") == "It's fine"          # escaped quote survives
    assert dk.get("List") == [1, 2, 3.5]
    assert dk.get("Wrapped") == [1, 2, 3]            # multi-line value joined
    assert len(doc.hfss_designs()) == 1


def test_editing_only_rewrites_the_edited_statement():
    doc = AedtDocument.parse_text(SAMPLE)
    doc.root.path("Desktop").set("Version", Call("Version", [2025, 1]))
    out = doc.to_text().split("\n")
    src = SAMPLE.split("\n")
    diff = [i for i, (a, b) in enumerate(zip(src, out)) if a != b]
    assert len(diff) == 1
    assert "2025" in out[diff[0]]


def test_end_without_begin_is_rejected_when_strict():
    with pytest.raises(ValueError):
        AedtDocument.parse_text("$end 'Nope'\n", strict=True)


def test_mismatched_block_names_are_rejected_when_strict():
    with pytest.raises(ValueError):
        AedtDocument.parse_text("$begin 'A'\n$end 'B'\n", strict=True)


def test_damage_is_repaired_and_reported_rather_than_fatal():
    """Reading someone else's project file: a block that does not close is a
    reason to note the damage and keep going, not to hand back nothing."""
    doc = AedtDocument.parse_text("$end 'Nope'\n")
    assert doc.issues and "without a matching" in doc.issues[0]

    doc = AedtDocument.parse_text("$begin 'A'\n\tX=1\n$end 'B'\n")
    assert doc.issues
    assert doc.root.get("X") == 1                 # the content still arrives


def test_a_stray_quote_costs_one_line_not_the_file():
    """One unbalanced apostrophe used to swallow every line after it, and the
    parse then died far away with 'unterminated string near offset 0'."""
    text = "$begin 'A'\n\tX=1\n\tY='oops\n\tZ=2\n$end 'A'\n"
    doc = AedtDocument.parse_text(text)
    assert doc.root.get("X") == 1 and doc.root.get("Z") == 2
    assert doc.to_text() == text                 # and it still round-trips


def test_dollar_end_inside_a_string_does_not_close_the_block():
    text = ("$begin 'A'\n\tNote='contains $end nothing'\n$end 'A'\n")
    doc = AedtDocument.parse_text(text)
    assert doc.root.get("Note") == "contains $end nothing"
    assert doc.to_text() == text


def test_statement_parsing_and_formatting():
    assert parse_statement("Key='v'") == ("Key", "v")
    assert parse_statement("N=12") == ("N", 12)
    assert parse_statement("F=1.5e-3") == ("F", 1.5e-3)
    assert parse_statement("B=true") == ("B", True)
    k, v = parse_statement("Version(2024, 2)")
    assert isinstance(v, Call) and v.args == [2024, 2]
    assert format_statement("Key", "v") == "Key='v'"
    assert format_statement("B", False) == "B=false"


def test_aedtz_archive_round_trip(tmp_path):
    p = str(tmp_path / "p.aedtz")
    AedtDocument.parse_text(SAMPLE).write(p)
    doc = AedtDocument.parse(p)
    assert doc.to_text() == SAMPLE


def test_bom_is_preserved_and_not_invented(tmp_path):
    plain = str(tmp_path / "a.aedt")
    with open(plain, "wb") as fh:
        fh.write(SAMPLE.encode("utf-8"))
    doc = AedtDocument.parse(plain)
    out = str(tmp_path / "b.aedt")
    doc.write(out)
    assert open(out, "rb").read() == open(plain, "rb").read()


# ------------------------------------------------------------- expressions
def test_variable_expressions_resolve():
    sc = VariableScope({"$w": "10mm", "h": "$w/2"})
    assert evaluate("2*$w+1mm", sc) == pytest.approx(0.021)
    assert evaluate("h", sc) == pytest.approx(0.005)
    assert evaluate("sqrt(2)*$w", sc) == pytest.approx(0.010 * 2 ** 0.5)
    assert evaluate("10GHz", None, "frequency") == 1e10


def test_expression_rejects_code_execution():
    with pytest.raises(Exception):
        evaluate("__import__('os').system('true')")


def test_circular_variables_are_detected():
    sc = VariableScope({"a": "b", "b": "a"})
    with pytest.raises(ValueError):
        evaluate("a", sc)


# ------------------------------------------------------- model translation
def _demo_design():
    d = ae.Design("HFSSDesign1", units="mm")
    d.add_box("sub", (0, 0, 0), ("20mm", "10mm", "0.8mm"), "fr4_epoxy")
    d.add_box("guide", (0, 0, 0), ("22.86mm", "10.16mm", "20mm"), "vacuum")
    d.add_cylinder("via", ("5mm", "5mm", 0), "0.2mm", "0.8mm", "copper")
    d.add_wave_port("p1", axis="z", value=0, num_modes=2)
    d.add_wave_port("p2", axis="z", value="20mm", deembed="2mm",
                    renormalize_z=50)
    d.assign_pec_outer()
    d.assign_finite_conductivity(
        "Cond1", ae.BoxSelector((0, 0, 0), ("20mm", "10mm", "0.1mm")),
        material="copper", roughness="1um")
    st = d.add_setup("Setup1", frequency="10GHz")
    st.add_sweep("Sweep1", "8GHz", "12GHz", 41)
    return d


def test_design_survives_a_full_aedt_round_trip(tmp_path):
    src = _demo_design()
    p1 = str(tmp_path / "a.aedt")
    write_project(p1, src, mode="create")
    proj, reports = read_project(p1)
    back = proj[0]
    assert not reports[0].unresolved
    assert [s.name for s in back.solids] == [s.name for s in src.solids]
    assert back.units == src.units
    assert back.solution_type == src.solution_type
    lo0, hi0 = src.bounding_box()
    lo1, hi1 = back.bounding_box()
    assert np.allclose(lo0, lo1) and np.allclose(hi0, hi1)
    # ports keep their geometry, mode count, de-embed and renormalisation
    assert [p.name for p in back.ports] == ["p1", "p2"]
    assert back.ports[0].num_modes == 2
    assert back.ports[1].deembed == pytest.approx(0.002)
    assert back.ports[1].renormalize_z == pytest.approx(50.0)
    assert isinstance(back.ports[0].selector, ae.PlaneSelector)
    assert back.ports[1].selector.value == pytest.approx(0.020)
    # materials keep their electrical properties
    assert back.get_solid("sub").material.eps_c(1e9).real == pytest.approx(4.4)
    assert back.get_solid("via").material.sigma == pytest.approx(5.8e7)
    # setup and sweep
    st = back.get_setup("Setup1")
    assert st.frequency == pytest.approx(1e10)
    assert len(st.sweeps) == 1
    f = st.sweeps[0].frequencies()
    assert (len(f), f[0], f[-1]) == (41, 8e9, 12e9)


def test_second_export_is_identical_to_the_first(tmp_path):
    src = _demo_design()
    a, b = str(tmp_path / "a.aedt"), str(tmp_path / "b.aedt")
    write_project(a, src, mode="create")
    back = read_project(a)[0][0]
    write_project(b, back, mode="create")
    la = [l for l in open(a) if "Created=" not in l]
    lb = [l for l in open(b) if "Created=" not in l]
    assert la == lb


def test_generated_project_reparses_byte_identically(tmp_path):
    p = str(tmp_path / "a.aedt")
    write_project(p, _demo_design(), mode="create")
    doc = AedtDocument.parse(p)
    q = str(tmp_path / "b.aedt")
    doc.write(q)
    assert open(p, "rb").read() == open(q, "rb").read()


def test_unresolved_face_ids_are_reported_not_guessed():
    text = SAMPLE.replace(
        "\t\tSolutionType='HFSS Modal Network'\n",
        "\t\tSolutionType='HFSS Modal Network'\n"
        "\t\t$begin 'BoundarySetup'\n"
        "\t\t\t$begin 'rad1'\n"
        "\t\t\t\tBoundType='Radiation'\n"
        "\t\t\t\tFaces=[17, 18]\n"
        "\t\t\t$end 'rad1'\n"
        "\t\t$end 'BoundarySetup'\n")
    doc = AedtDocument.parse_text(text)
    from aether.io.aedt.translate import read_design
    d, rep = read_design(doc)
    assert d.boundaries == []
    assert any("face ids" in u for u in rep.unresolved)


def test_csg_boolean_geometry_survives_the_round_trip(tmp_path):
    """
    A subtraction must come back a subtraction.

    Flattening it into a union is the failure mode that silently turns a coax
    into a filled cylinder -- the model still meshes and still solves, it is
    just a different structure, so this is checked by point membership rather
    than by bounding box.
    """
    import math
    from aether.geometry.implicit import contains
    a, b, L = 1e-3, 2.3023e-3, 20e-3
    d = ae.Design("Coax", units="mm")
    d.add_solid("diel",
                ae.Cylinder((0, 0, 0), b, L)
                - ae.Cylinder((0, 0, -1e-3), a, L + 2e-3), "vacuum")
    d.add_wave_port("p1", axis="z", value=0,
                    integration_line=((a, 0, 0), (b, 0, 0)))
    d.add_setup("Setup1", frequency="10GHz")
    p = str(tmp_path / "coax.aedt")
    write_project(p, d, mode="create")
    back = read_project(p)[0][0]

    pts = np.array([[0.0, 0.0, L / 2],           # inside the inner conductor
                    [(a + b) / 2, 0.0, L / 2],   # in the dielectric annulus
                    [2 * b, 0.0, L / 2]])        # outside entirely
    got = contains(back.solids[0].shape, pts)
    assert list(got) == [False, True, False]
    assert list(got) == list(contains(d.solids[0].shape, pts))
    # the integration line comes back too
    assert back.ports[0].integration_line is not None
    assert np.allclose(back.ports[0].integration_line[1], (b, 0, 0))


def test_transform_stack_survives_the_round_trip(tmp_path):
    from aether.geometry.implicit import contains
    d = ae.Design("Xform", units="mm")
    d.add_solid("blk", ae.Box((0, 0, 0), ("4mm", "2mm", "2mm"))
                .rotate("z", "90deg").translate("1mm", 0, 0), "vacuum")
    d.add_wave_port("p1", axis="z", value=0)
    d.add_setup("Setup1", frequency="10GHz")
    p = str(tmp_path / "x.aedt")
    write_project(p, d, mode="create")
    back = read_project(p)[0][0]
    pts = np.array([[0.0, 0.003, 0.001], [0.003, 0.001, 0.001]])
    assert list(contains(back.solids[0].shape, pts)) == \
        list(contains(d.solids[0].shape, pts))
    assert np.allclose(back.bounding_box()[0], d.bounding_box()[0])
    assert np.allclose(back.bounding_box()[1], d.bounding_box()[1])


def test_lumped_port_impedance_and_direction_survive(tmp_path):
    d = ae.Design("Lumped", units="mm")
    d.add_box("air", (0, 0, 0), ("20mm", "10mm", "1mm"), "vacuum")
    d.assign_boundary("PMC", "pmc", ae.PlaneSelector("y", 0))
    d.add_lumped_port("p1", axis="x", value=0, impedance=37.673,
                      direction=(0, 0, 1))
    d.add_lumped_port("p2", axis="x", value="20mm", impedance=75.0,
                      direction=(0, 1, 0))
    d.add_setup("Setup1", frequency="5GHz")
    p = str(tmp_path / "l.aedt")
    write_project(p, d, mode="create")
    back = read_project(p)[0][0]
    assert [x.kind for x in back.ports] == ["lumped", "lumped"]
    assert back.ports[0].impedance.real == pytest.approx(37.673)
    assert back.ports[1].impedance.real == pytest.approx(75.0)
    assert np.allclose(back.ports[0].direction, (0, 0, 1))
    assert np.allclose(back.ports[1].direction, (0, 1, 0))
    assert [b.btype for b in back.boundaries] == ["pmc"]


# --------------------------------------------------------------- touchstone
@pytest.mark.parametrize("n", [1, 2, 3, 4])
@pytest.mark.parametrize("fmt", ["RI", "MA", "DB"])
@pytest.mark.parametrize("ver", [1.0, 2.0])
def test_touchstone_round_trip(tmp_path, n, fmt, ver):
    rng = np.random.default_rng(n)
    f = np.linspace(1e9, 10e9, 7)
    s = 0.3 * (rng.normal(size=(7, n, n)) + 1j * rng.normal(size=(7, n, n)))
    sp = ae.SParameters(f, s, 50.0)
    ext = ".ts" if ver >= 2 else f".s{n}p"
    p = str(tmp_path / f"x{ext}")
    write_touchstone(p, sp, fmt=fmt, version=ver)
    back = read_touchstone(p)
    assert back.n_port == n
    assert np.allclose(back.freq, f)
    assert np.max(np.abs(back.s - sp.s)) < 1e-9


def test_s2p_column_major_convention(tmp_path):
    """A v1 .s2p stores S11 S21 S12 S22 -- getting this wrong swaps S12/S21."""
    f = np.array([1e9])
    s = np.array([[[0.1 + 0j, 0.2 + 0j], [0.3 + 0j, 0.4 + 0j]]])
    p = str(tmp_path / "t.s2p")
    write_touchstone(p, ae.SParameters(f, s, 50.0), fmt="RI", version=1.0)
    nums = [float(x) for x in
            [l for l in open(p) if not l.startswith(("!", "#"))][0].split()]
    assert nums[1:] == [0.1, 0.0, 0.3, 0.0, 0.2, 0.0, 0.4, 0.0]
    assert np.allclose(read_touchstone(p).s, s)


def test_touchstone_reads_comments_and_ma_format(tmp_path):
    p = str(tmp_path / "m.s2p")
    with open(p, "w") as fh:
        fh.write("! demo\n# GHz S MA R 75\n"
                 "1.0 0.5 90 1.0 0 1.0 0 0.5 -90\n")
    sp = read_touchstone(p)
    assert sp.z0[0, 0] == pytest.approx(75.0)
    assert sp.sij(1, 1)[0] == pytest.approx(0.5j, abs=1e-12)
    assert "demo" in " ".join(sp.comments)


# --------------------------------------------------------------- csv / vtk
def test_csv_export(tmp_path):
    f = np.linspace(1e9, 2e9, 3)
    sp = ae.SParameters(f, np.zeros((3, 2, 2), complex) + 0.5, 50.0)
    p = str(tmp_path / "s.csv")
    sp.to_csv(p)
    from aether.io.csv_io import read_csv_table
    head, data = read_csv_table(p)
    assert data.shape == (3, 9)
    assert head[0].startswith("Freq")


def test_vtk_export(tmp_path):
    from aether.io.vtk_io import write_vtu
    from aether.mesh.tetmesh import TetMesh
    m = TetMesh(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float),
                np.array([[0, 1, 2, 3]]))
    p = str(tmp_path / "m.vtu")
    write_vtu(p, m, cell_data={"region": m.tet_region})
    txt = open(p).read()
    assert "UnstructuredGrid" in txt and "region" in txt
