"""
Release 1.7.9 — what an Warps project brings in, and what it must not.

The project this round was built against imported as 29 solids, 0 boundaries
and a validation report full of PML materials that no solver here can use.
Every test below is one line of that report turned into a rule: the PML
apparatus is dropped, the air region is rebuilt, a setup's basis order is
made legal, and a body that cannot be built no longer stops the mesh.
"""
import numpy as np
import pytest

from conftest import needs_occ

from aether.gui.api import dispatch
from aether.gui.state import Session
from aether.io.warp.translate import read_project

PROJECT = """$begin 'WarpsProject'
\t$begin 'WarpsModel'
\t\tName='D1'
\t\tDesignID=0
\t\t$begin 'ModelSetup'
\t\t\t$begin 'GeometryCore'
\t\t\t\t$begin 'GeometryOperations'
\t\t\t\t\t$begin 'ToplevelParts'
\t\t\t\t\t\t$begin 'GeometryPart'
\t\t\t\t\t\t\t$begin 'Attributes'
\t\t\t\t\t\t\t\tName='Trace'
\t\t\t\t\t\t\t\tMaterialValue='"copper"'
\t\t\t\t\t\t\t$end 'Attributes'
\t\t\t\t\t\t\t$begin 'Operations'
\t\t\t\t\t\t\t\t$begin 'Operation'
\t\t\t\t\t\t\t\t\tOperationType='Box'
\t\t\t\t\t\t\t\t\tParentPartID=11
\t\t\t\t\t\t\t\t\t$begin 'BoxParameters'
\t\t\t\t\t\t\t\t\t\tXPosition='0mm'
\t\t\t\t\t\t\t\t\t\tYPosition='0mm'
\t\t\t\t\t\t\t\t\t\tZPosition='0mm'
\t\t\t\t\t\t\t\t\t\tXSize='20mm'
\t\t\t\t\t\t\t\t\t\tYSize='10mm'
\t\t\t\t\t\t\t\t\t\tZSize='2mm'
\t\t\t\t\t\t\t\t\t$end 'BoxParameters'
\t\t\t\t\t\t\t\t$end 'Operation'
\t\t\t\t\t\t\t$end 'Operations'
\t\t\t\t\t\t$end 'GeometryPart'
\t\t\t\t\t\t$begin 'GeometryPart'
\t\t\t\t\t\t\t$begin 'Attributes'
\t\t\t\t\t\t\t\tName='PML_Region_1'
\t\t\t\t\t\t\t\tMaterialValue='"PMLGroup1_XYZ_5"'
\t\t\t\t\t\t\t$end 'Attributes'
\t\t\t\t\t\t\t$begin 'Operations'
\t\t\t\t\t\t\t\t$begin 'Operation'
\t\t\t\t\t\t\t\t\tOperationType='Box'
\t\t\t\t\t\t\t\t\tParentPartID=77
\t\t\t\t\t\t\t\t\t$begin 'BoxParameters'
\t\t\t\t\t\t\t\t\t\tXPosition='0mm'
\t\t\t\t\t\t\t\t\t\tYPosition='0mm'
\t\t\t\t\t\t\t\t\t\tZPosition='0mm'
\t\t\t\t\t\t\t\t\t\tXSize='99mm'
\t\t\t\t\t\t\t\t\t\tYSize='99mm'
\t\t\t\t\t\t\t\t\t\tZSize='99mm'
\t\t\t\t\t\t\t\t\t$end 'BoxParameters'
\t\t\t\t\t\t\t\t$end 'Operation'
\t\t\t\t\t\t\t$end 'Operations'
\t\t\t\t\t\t$end 'GeometryPart'
\t\t\t\t\t\t$begin 'GeometryPart'
\t\t\t\t\t\t\t$begin 'Attributes'
\t\t\t\t\t\t\t\tName='Region'
\t\t\t\t\t\t\t\tMaterialValue='"vacuum"'
\t\t\t\t\t\t\t\tSolveInside=true
\t\t\t\t\t\t\t$end 'Attributes'
\t\t\t\t\t\t\t$begin 'Operations'
\t\t\t\t\t\t\t\t$begin 'Operation'
\t\t\t\t\t\t\t\t\tOperationType='Region'
\t\t\t\t\t\t\t\t\tParentPartID=90
\t\t\t\t\t\t\t\t\t$begin 'RegionParameters'
\t\t\t\t\t\t\t\t\t\t'+XPaddingType'='Absolute Offset'
\t\t\t\t\t\t\t\t\t\t'+XPadding'='5mm'
\t\t\t\t\t\t\t\t\t\t'-XPaddingType'='Absolute Offset'
\t\t\t\t\t\t\t\t\t\t'-XPadding'='5mm'
\t\t\t\t\t\t\t\t\t\t'+YPaddingType'='Absolute Offset'
\t\t\t\t\t\t\t\t\t\t'+YPadding'='5mm'
\t\t\t\t\t\t\t\t\t\t'-YPaddingType'='Absolute Offset'
\t\t\t\t\t\t\t\t\t\t'-YPadding'='5mm'
\t\t\t\t\t\t\t\t\t\t'+ZPaddingType'='Percentage Offset'
\t\t\t\t\t\t\t\t\t\t'+ZPadding'='100'
\t\t\t\t\t\t\t\t\t\t'-ZPaddingType'='Absolute Offset'
\t\t\t\t\t\t\t\t\t\t'-ZPadding'='5mm'
\t\t\t\t\t\t\t\t\t$end 'RegionParameters'
\t\t\t\t\t\t\t\t$end 'Operation'
\t\t\t\t\t\t\t$end 'Operations'
\t\t\t\t\t\t$end 'GeometryPart'
\t\t\t\t\t$end 'ToplevelParts'
\t\t\t\t$end 'GeometryOperations'
\t\t\t$end 'GeometryCore'
\t\t$end 'ModelSetup'
\t\t$begin 'BoundarySetup'
\t\t\t$begin 'Boundaries'
\t\t\t\t$begin 'PerfE1'
\t\t\t\t\tBoundType='Perfect E'
\t\t\t\t\tObjects(11)
\t\t\t\t$end 'PerfE1'
\t\t\t\t$begin 'PML_radiation1'
\t\t\t\t\tBoundType='Radiation'
\t\t\t\t\tFaces(31177)
\t\t\t\t$end 'PML_radiation1'
\t\t\t\t$begin 'PmlOnPart'
\t\t\t\t\tBoundType='Radiation'
\t\t\t\t\tObjects(77)
\t\t\t\t$end 'PmlOnPart'
\t\t\t$end 'Boundaries'
\t\t$end 'BoundarySetup'
\t\t$begin 'AnalysisSetup'
\t\t\t$begin 'SolveSetups'
\t\t\t\t$begin 'Setup1'
\t\t\t\t\tName='Setup1'
\t\t\t\t\t$begin 'SolveSetupProps'
\t\t\t\t\t\tFrequency='6GHz'
\t\t\t\t\t\tMaximumPasses=8
\t\t\t\t\t\tMaxDeltaS=0.02
\t\t\t\t\t\tBasisOrder=0
\t\t\t\t\t$end 'SolveSetupProps'
\t\t\t\t$end 'Setup1'
\t\t\t$end 'SolveSetups'
\t\t$end 'AnalysisSetup'
\t$end 'WarpsModel'
$end 'WarpsProject'
"""


@pytest.fixture()
def project(tmp_path):
    p = tmp_path / "pml.warp"
    p.write_text(PROJECT)
    return str(p)


@pytest.fixture()
def imported(project):
    proj, reports = read_project(project)
    return proj.designs[0], reports[0]


# ------------------------------------------------------------------ PML
def test_pml_bodies_do_not_become_objects(imported):
    d, r = imported
    assert "PML_Region_1" not in [s.name for s in d.solids]
    assert r.pml_parts == ["PML_Region_1"]


def test_the_pml_material_never_reaches_the_library(imported):
    d, _ = imported
    assert not any(m.lower().startswith("pml") for m in d.materials.names())


def test_nothing_about_pml_is_reported_as_a_problem(imported):
    d, r = imported
    assert not any("PML" in u for u in r.unresolved)
    assert not any("PML" in e for e in d.validate())


def test_a_boundary_attached_only_to_pml_bodies_goes_with_them(imported):
    _, r = imported
    assert set(r.pml_boundaries) == {"PML_radiation1", "PmlOnPart"}


def test_the_open_boundary_the_pml_stood_for_is_put_back(imported):
    """
    Dropping the layer must not quietly close the model: a PML is an open
    boundary, and the equivalent here is radiation on the outer surface.
    """
    d, _ = imported
    rad = [b for b in d.boundaries if b.btype == "radiation"]
    assert [b.name for b in rad] == ["Radiation1"]


def test_the_boundaries_on_real_bodies_are_untouched(imported):
    d, _ = imported
    assert "PerfE1" in [b.name for b in d.boundaries]


# --------------------------------------------------------------- region
def test_the_air_region_is_rebuilt_from_its_padding(imported):
    d, _ = imported
    lo, hi = d.get_solid("Region").shape.bounds()
    # 20 x 10 x 2 mm model, 5 mm padding on five sides, 100 % on +Z
    assert np.allclose(lo, [-5e-3, -5e-3, -5e-3])
    assert np.allclose(hi, [25e-3, 15e-3, 4e-3])


def test_the_region_is_a_solved_vacuum_volume(imported):
    d, _ = imported
    region = d.get_solid("Region")
    assert region.solve_inside and not region.material.is_pec


def test_a_region_with_nothing_to_pad_says_so_instead_of_guessing(tmp_path):
    # the only real body arrives degenerate, which is what an unreadable
    # ACIS/Parasolid attachment looks like from here
    text = PROJECT.replace("XSize='20mm'", "XSize='0mm'") \
                  .replace("YSize='10mm'", "YSize='0mm'") \
                  .replace("ZSize='2mm'", "ZSize='0mm'")
    p = tmp_path / "noregion.warp"
    p.write_text(text)
    _, reports = read_project(str(p))
    assert any("air region" in u for u in reports[0].unresolved)


# ---------------------------------------------------------------- setup
def test_an_warps_mixed_order_setup_imports_as_first_order(imported):
    d, r = imported
    assert d.setups[0].basis_order == 1
    assert any("basis order" in w for w in r.warnings)


def test_the_imported_project_validates_clean_enough_to_solve(imported):
    d, _ = imported
    assert not any("basis order" in e for e in d.validate())


# ----------------------------------------------------------------- mesh
@needs_occ
def test_a_body_that_cannot_be_built_does_not_stop_the_mesh(tmp_path):
    from aether.geometry.primitives import ImportedShape
    from aether.model import Design
    d = Design("D", units="mm")
    d.add_box("Air", (0, 0, 0), (20e-3, 20e-3, 20e-3), "vacuum")
    broken = ImportedShape(str(tmp_path / "nothing.x_b"), name="Bad")
    broken._cad_unreadable = "Parasolid cannot be read"
    d.add_solid("Bad", broken, "copper")
    m = d.generate_mesh(1e9, force=True)
    assert m.n_tets > 0
    assert list(m.skipped_bodies) == ["Bad"]


@needs_occ
def test_the_workspace_says_which_bodies_are_missing_from_the_mesh(tmp_path):
    from aether.geometry.primitives import ImportedShape
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.draw", {"shape": "box", "name": "Air",
                                 "params": {"position": ["0mm", "0mm", "0mm"],
                                            "size": ["20mm", "20mm", "20mm"]}})
    broken = ImportedShape(str(tmp_path / "nothing.x_b"), name="Bad")
    broken._cad_unreadable = "Parasolid cannot be read"
    s.design.add_solid("Bad", broken, "copper")
    out = dispatch(s, "analysis.generateMesh", {})
    assert out["skipped"] == ["Bad"]
    said = " ".join(m["text"] for m in s.messages.since(0))
    assert "no readable geometry" in said and "Bad" in said


@needs_occ
def test_a_metal_body_does_not_drive_the_element_size(tmp_path):
    """
    A good conductor has a refractive index in the thousands. Letting that
    into the sizing rule asked for 80 nm elements on a 60 mm board -- an
    initial mesh that never came back.
    """
    from aether.mesh.generator import target_size
    from aether.model import Design
    d = Design("D", units="mm")
    d.add_box("Air", (0, 0, 0), (60e-3, 60e-3, 10e-3), "vacuum")
    d.add_box("Pad", (1e-3, 1e-3, 0), (5e-3, 5e-3, 35e-6), "copper")
    d.get_solid("Pad").solve_inside = False
    h, _ = target_size(d, 2.4e9)
    assert h > 1e-3


@needs_occ
def test_the_initial_mesh_stays_inside_its_element_budget():
    from aether.mesh.generator import ELEMENT_BUDGET, target_size
    from aether.model import Design
    d = Design("D", units="mm")
    d.add_box("Air", (0, 0, 0), (100e-3, 100e-3, 100e-3), "vacuum")
    d.config.mesh.max_element_size = 1e-5      # 10 um across 100 mm
    h, _ = target_size(d, 1e9)
    assert 6.0 * (0.1 ** 3) / h ** 3 <= ELEMENT_BUDGET * 1.01


# ---------------------------------------------------------------- ports
@needs_occ
def _two_conductors():
    pass


@needs_occ
def test_a_lumped_port_can_be_built_from_a_signal_and_a_ground_pick():
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.draw", {"shape": "box", "name": "SIG",
             "params": {"position": ["0mm", "0mm", "0mm"],
                        "size": ["10mm", "1mm", "0.2mm"]}})
    dispatch(s, "modeler.draw", {"shape": "box", "name": "GND",
             "params": {"position": ["0mm", "2mm", "0mm"],
                        "size": ["10mm", "1mm", "0.2mm"]}})
    g = dispatch(s, "view.geometry", {})

    def face(obj, key):
        o = [x for x in g["objects"] if x["name"] == obj][0]
        return dict(key(o["faces"]), object=obj)

    sig = face("SIG", lambda fs: max(fs, key=lambda f: f["point"][1]))
    gnd = face("GND", lambda fs: min(fs, key=lambda f: f["point"][1]))
    out = dispatch(s, "excitation.assignBetween",
                   {"kind": "lumped", "signal": [sig], "ground": [gnd],
                    "params": {"impedance": 50}})
    assert out["ok"] and out["faces"] > 0
    port = s.design.ports[0]
    # the sheet spans the gap ...
    sheet = [x for x in s.design.sheets if x.name == out["sheet"]][0]
    lo, hi = sheet.shape.bounds()
    assert np.allclose([lo[1], hi[1]], [1e-3, 2e-3])
    # ... and the integration line runs ground -> signal, which fixes the
    # sign of V and therefore of the port impedance
    a, b = port.integration_line
    assert a[1] > b[1]


@needs_occ
def test_a_wave_port_takes_the_picked_face_and_the_reference_orients_it():
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.draw", {"shape": "box", "name": "SIG",
             "params": {"position": ["0mm", "0mm", "0mm"],
                        "size": ["10mm", "1mm", "0.2mm"]}})
    dispatch(s, "modeler.draw", {"shape": "box", "name": "GND",
             "params": {"position": ["0mm", "2mm", "0mm"],
                        "size": ["10mm", "1mm", "0.2mm"]}})
    g = dispatch(s, "view.geometry", {})

    def face(obj, key):
        o = [x for x in g["objects"] if x["name"] == obj][0]
        return dict(key(o["faces"]), object=obj)

    end = face("SIG", lambda fs: min(fs, key=lambda f: f["point"][0]))
    gnd = face("GND", lambda fs: min(fs, key=lambda f: f["point"][1]))
    out = dispatch(s, "excitation.assignBetween",
                   {"kind": "wave", "signal": [end], "ground": [gnd],
                    "params": {"modes": 2}})
    p = s.design.ports[0]
    assert out["faces"] > 0 and p.kind == "wave" and p.num_modes == 2
    assert p.integration_line is not None


def test_a_lumped_port_without_a_ground_pick_is_refused():
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.draw", {"shape": "box", "name": "B",
             "params": {"position": ["0mm", "0mm", "0mm"],
                        "size": ["1mm", "1mm", "1mm"]}})
    with pytest.raises(Exception) as e:
        dispatch(s, "excitation.assignBetween",
                 {"kind": "lumped",
                  "signal": [{"object": "B", "point": ["0mm", "0mm", "0mm"],
                              "normal": [0, 0, 1], "lo": ["0mm"] * 3,
                              "hi": ["1mm"] * 3}]})
    assert "ground" in str(e.value)


# ----------------------------------------------------- empty assignments
@needs_occ
def test_an_assignment_that_lands_on_nothing_says_so():
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.draw", {"shape": "box", "name": "B",
             "params": {"position": ["0mm", "0mm", "0mm"],
                        "size": ["10mm", "10mm", "2mm"]}})
    out = dispatch(s, "boundary.assign",
                   {"type": "pec", "name": "Nowhere",
                    "selector": {"kind": "plane", "axis": "z",
                                 "value": "500mm"}})
    assert out["faces"] == 0
    said = " ".join(m["text"] for m in s.messages.since(0))
    assert "does not touch any face" in said


@needs_occ
def test_an_assignment_that_lands_on_the_model_reports_its_size():
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.draw", {"shape": "box", "name": "B",
             "params": {"position": ["0mm", "0mm", "0mm"],
                        "size": ["10mm", "10mm", "2mm"]}})
    out = dispatch(s, "boundary.assign",
                   {"type": "pec", "selector": {"kind": "bboxface",
                                                "face": "+z"}})
    assert out["faces"] > 0
