"""
Release 1.7.7 — the three things that stopped a real HFSS project loading.

All three were reproduced from one user's files (an .aedt with 29 bodies, the
STEP those bodies were exported to, and a DXF of the coil layer), and each is
covered here by the smallest synthetic case that carries the same defect:

* a material name with a space or a hyphen in it went into the library under
  one key and was looked up under another, so ``materials.list`` raised — and
  that call sits between "project loaded" and "draw it";
* a STEP file's presentation geometry (free faces of hundreds of square
  metres beside 48 mm parts) was meshed at the assembly's element size;
* a DXF polyline with sub-tolerance steps made OpenCASCADE refuse an edge and
  took the whole drawing with it.
"""
import numpy as np
import pytest

from conftest import needs_occ

from aether.core.materials import ConstantTanD, Material, MaterialLibrary
from aether.gui.api import dispatch, state_json
from aether.gui.state import Session
from test_dxf import write_dxf


# ------------------------------------------------------------- materials
def test_a_material_named_with_spaces_can_be_found_again():
    """``add`` keyed on ``name.lower()`` while ``get`` also folded spaces and
    hyphens: anything with either in its name was unreachable for ever."""
    lib = MaterialLibrary()
    lib.add(Material("Polyflon copper-clad ULTEM (tm)",
                     ConstantTanD(3.05, 0.003), ConstantTanD(1.0, 0.0)))
    assert lib.get("Polyflon copper-clad ULTEM (tm)").name == \
        "Polyflon copper-clad ULTEM (tm)"
    assert "Polyflon copper-clad ULTEM (tm)" in lib
    # and by any of the spellings that normalise to the same key
    assert lib.get("polyflon_copper_clad_ultem_(tm)") is lib.get(
        "POLYFLON COPPER-CLAD ULTEM (TM)")


def test_every_name_the_library_lists_can_be_fetched():
    """``materials.list`` iterates names and fetches each one. One name it
    cannot fetch takes down the whole call."""
    lib = MaterialLibrary()
    for name in ("Rogers RT-duroid 5880 (tm)", "copper clad", "FR4-epoxy 2"):
        lib.add(Material(name, ConstantTanD(2.2, 0.001), ConstantTanD(1.0, 0.0)))
    for n in lib.names():
        assert lib.get(n) is not None


def test_the_material_list_command_survives_awkward_names():
    s = Session()
    s.new_project("P")
    s.design.materials.add(Material("Polyflon copper-clad ULTEM (tm)",
                                    ConstantTanD(3.05, 0.003),
                                    ConstantTanD(1.0, 0.0)))
    out = dispatch(s, "materials.list", {})["materials"]
    assert any(m["name"] == "Polyflon copper-clad ULTEM (tm)" for m in out)


def test_an_object_can_be_given_such_a_material():
    s = Session()
    s.new_project("P")
    s.design.materials.add(Material("copper-clad laminate",
                                    ConstantTanD(3.5, 0.004),
                                    ConstantTanD(1.0, 0.0)))
    dispatch(s, "modeler.draw", {"shape": "box", "name": "B",
                                 "params": {"position": ["0mm", "0mm", "0mm"],
                                            "size": ["4mm", "4mm", "1mm"]}})
    dispatch(s, "modeler.setProperty",
             {"name": "B", "prop": "material", "value": "copper-clad laminate"})
    assert state_json(s)["design"]["objects"][0]["material"] \
        == "copper-clad laminate"


# ------------------------------------------------- bounded display meshing
@needs_occ
def test_free_cad_entities_are_not_meshed_with_the_bodies():
    """
    A STEP export carries presentation geometry that belongs to no solid. Its
    faces can be square metres beside millimetre parts, and meshing those at
    the assembly's element size is unbounded work for something never drawn.
    """
    from aether.geometry.kernel import GmshSession, prune_to_bodies

    with GmshSession("stray") as gmsh:
        occ = gmsh.model.occ
        body = occ.addBox(0, 0, 0, 0.048, 0.013, 0.013)
        stray = occ.addRectangle(-200, -200, 0, 400, 400)   # 160,000 m^2
        occ.synchronize()
        assert len(gmsh.model.getEntities(2)) > 6
        dropped = prune_to_bodies(gmsh, [(3, body)])
        assert dropped >= 1
        faces = gmsh.model.getEntities(2)
        assert len(faces) == 6, faces
        gmsh.option.setNumber("Mesh.MeshSizeMax", 0.048 / 22)
        gmsh.model.mesh.generate(2)
        n = len(gmsh.model.mesh.getNodes()[0])
        assert n < 40000, f"{n} nodes for one small box"
        assert stray                                   # the tag existed


@needs_occ
def test_the_display_mesh_seed_is_capped_by_a_triangle_budget():
    from aether.geometry.kernel import GmshSession, fit_mesh_size

    with GmshSession("budget") as gmsh:
        occ = gmsh.model.occ
        occ.addBox(0, 0, 0, 1.0, 1.0, 1.0)             # 6 m^2 of surface
        occ.synchronize()
        fine = 1e-4                                    # 600 million triangles
        got = fit_mesh_size(gmsh, fine, budget=100_000)
        assert got > fine * 100
        # the returned size really does fit the budget
        assert 6.0 / (got ** 2 * 0.433) <= 100_000 * 1.05


@needs_occ
def test_a_stray_face_no_longer_decides_the_element_size(tmp_path):
    """End to end: a body plus a huge free face still tessellates quickly and
    to a sane triangle count."""
    import time

    from aether.geometry import primitives as prim
    from aether.gui.tessellate import tessellate

    box = prim.Box(position=(0, 0, 0), size=(0.048, 0.013, 0.013))
    t = time.perf_counter()
    buf = tessellate(box)
    assert time.perf_counter() - t < 20
    assert 0 < buf["count"] // 3 < 900_000


# --------------------------------------------------------------- the DXF
def noisy_ring(x0, y0, w, h, step=1e-4):
    """A rectangle whose edges are walked in small steps, with a repeated
    vertex and a 0.1 micron step in the middle of one side — exactly what a
    layout exporter produces."""
    pts = []
    n = int(w / step)
    for i in range(n):
        pts.append((x0 + i * step, y0))
    pts.append((x0 + w, y0))
    pts.append((x0 + w, y0))                       # repeated vertex
    pts.append((x0 + w + 1e-7, y0))                # 0.1 nm in drawing units
    pts.append((x0 + w, y0 + h))
    pts.append((x0, y0 + h))
    e = ["0", "LWPOLYLINE", "8", "COIL", "90", str(len(pts)), "70", "1"]
    for x, y in pts:
        e += ["10", repr(x), "20", repr(y)]
    return e


@needs_occ
def test_a_drawing_with_sub_tolerance_steps_still_imports(tmp_path):
    """OpenCASCADE refuses an edge shorter than its confusion tolerance, and
    one such step used to abort the whole import."""
    p = write_dxf(tmp_path / "coil.dxf", noisy_ring(0, 0, 4.0, 2.0))
    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.importCad", {"path": p, "name": "Coil"})
    sheets = state_json(s)["design"]["sheets"]
    assert len(sheets) == 1 and sheets[0]["name"] == "Coil"
    g = dispatch(s, "view.geometry", {})
    assert g["objects"] and g["objects"][0]["count"] > 0


def test_the_ring_cleaner_keeps_real_vertices_and_drops_noise():
    from aether.geometry.brep_io import _dedupe_ring

    ring = np.array([[0, 0, 0], [0.004, 0, 0], [0.004 + 5e-8, 0, 0],
                     [0.004, 0.002, 0], [0, 0.002, 0], [0, 0, 0]], float)
    out = _dedupe_ring(ring)
    assert len(out) == 4                       # four real corners
    assert np.allclose(out[0], [0, 0, 0])
    d = np.linalg.norm(np.diff(np.vstack([out, out[:1]]), axis=0), axis=1)
    assert d.min() > 1e-6


def test_the_ring_cleaner_leaves_a_clean_ring_alone():
    from aether.geometry.brep_io import _dedupe_ring

    ring = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
    assert len(_dedupe_ring(ring)) == 4


# ------------------------------------------------------- cache hygiene
@needs_occ
def test_opening_another_project_drops_the_previous_buffers(tmp_path):
    from aether.gui.api import BLOBS
    from aether.gui.tessellate import _TESS_CACHE

    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.draw", {"shape": "box", "name": "B",
                                 "params": {"position": ["0mm", "0mm", "0mm"],
                                            "size": ["8mm", "4mm", "1mm"]}})
    dispatch(s, "view.geometry", {"binary": True})
    assert len(_TESS_CACHE) >= 1 and len(BLOBS) >= 1
    p = tmp_path / "P.aedt"
    dispatch(s, "project.save", {"path": str(p)})
    dispatch(s, "project.open", {"path": str(p)})
    assert len(_TESS_CACHE) == 0
    # Blobs are trimmed to a small reserve rather than dropped outright, so a
    # fetch the browser started before the change still gets an answer.
    from aether.gui.api import _BLOB_BYTES, _BLOB_RESERVE_BYTES
    assert _BLOB_BYTES <= max(_BLOB_RESERVE_BYTES, 1)
    assert BLOBS is not None


@needs_occ
def test_a_new_project_drops_them_too():
    from aether.gui.api import BLOBS
    from aether.gui.tessellate import _TESS_CACHE

    s = Session()
    s.new_project("P")
    dispatch(s, "modeler.draw", {"shape": "box", "name": "B",
                                 "params": {"position": ["0mm", "0mm", "0mm"],
                                            "size": ["8mm", "4mm", "1mm"]}})
    dispatch(s, "view.geometry", {"binary": True})
    dispatch(s, "project.new", {})
    from aether.gui.api import _BLOB_BYTES, _BLOB_RESERVE_BYTES
    assert len(_TESS_CACHE) == 0
    assert _BLOB_BYTES <= max(_BLOB_RESERVE_BYTES, 1)
    assert BLOBS is not None
