"""Geometry primitives, CSG membership, selectors and meshing."""
import numpy as np
import pytest

from conftest import needs_occ

import aether as ae
from aether.geometry.implicit import contains
from aether.mesh.tetmesh import TetMesh


def test_box_bounds_and_units():
    b = ae.Box((0, 0, 0), ("10mm", "5mm", "1mm"))
    lo, hi = b.bounds()
    assert np.allclose(hi, [0.010, 0.005, 0.001])


def test_transforms_compose_correctly():
    """bounds() is a conservative (never-too-small) analytic estimate."""
    c = ae.Cylinder((0, 0, 0), "1mm", "4mm").rotate("x", "90deg")
    lo, hi = c.bounds()
    # the cylinder now runs along -y; the box must contain it
    assert lo[1] <= -4e-3 + 1e-12 and hi[1] >= 0.0
    assert lo[0] <= -1e-3 + 1e-12 and hi[0] >= 1e-3 - 1e-12
    assert lo[2] <= -1e-3 + 1e-12 and hi[2] >= 1e-3 - 1e-12


def test_csg_membership():
    shape = ae.Box((0, 0, 0), (1, 1, 1)) - ae.Cylinder((.5, .5, -1), .2, 3)
    pts = np.array([[.5, .5, .5], [.1, .1, .5], [2, 0, 0]])
    assert list(contains(shape, pts)) == [False, True, False]


def test_extruded_polygon_membership():
    r = ae.Rectangle((0, 0, 0), (2, 1), "xy").extrude((0, 0, 0.5))
    assert list(contains(r, np.array([[1, .5, .25], [3, .5, .25]]))) == [True, False]


def test_rotated_membership_uses_inverse_transform():
    b = ae.Box((0, 0, 0), (2, 1, 1)).rotate("z", "90deg")
    # after rotation the body occupies x in [-1,0], y in [0,2]
    assert contains(b, np.array([[-0.5, 1.0, 0.5]]))[0]
    assert not contains(b, np.array([[1.5, 0.5, 0.5]]))[0]


def test_tetmesh_topology_and_geometry():
    n = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    m = TetMesh(n, np.array([[0, 1, 2, 3]]))
    assert m.n_edges == 6 and m.n_faces == 4
    assert m.volumes[0] == pytest.approx(1 / 6)
    assert len(m.boundary_faces) == 4
    # grad(lambda) . edge vectors reproduce the Kronecker delta
    g = m.grads[0]
    assert np.allclose(g.sum(axis=0), 0.0, atol=1e-12)
    assert 0 < m.quality()[0] <= 1.0


def test_negative_orientation_is_repaired():
    n = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    m = TetMesh(n, np.array([[0, 1, 3, 2]]))       # inverted
    assert m.volumes[0] > 0


def test_plane_selector_window():
    sel = ae.PlaneSelector("z", 0.0, window=[[0, 1], [0, 1]])
    cen = np.array([[0.5, 0.5, 0.0], [2.0, 0.5, 0.0], [0.5, 0.5, 1.0]])
    nrm = np.array([[0, 0, 1.0]] * 3)
    assert list(sel(cen, nrm)) == [True, False, False]


def test_selector_algebra():
    a = ae.PlaneSelector("z", 0.0)
    b = ae.BoxSelector((0, 0, -1), (1, 1, 1))
    cen = np.array([[0.5, 0.5, 0.0], [5.0, 5.0, 0.0]])
    nrm = np.array([[0, 0, 1.0]] * 2)
    assert list(ae.intersect_sel(a, b)(cen, nrm)) == [True, False]
    assert list(ae.invert_sel(a)(cen, nrm)) == [False, False]


def _guide_design():
    d = ae.Design("g")
    d.add_box("guide", (0, 0, 0), ("22.86mm", "10.16mm", "10mm"), "vacuum")
    d.add_wave_port("p1", axis="z", value=0)
    d.add_wave_port("p2", axis="z", value="10mm")
    d.assign_pec_outer()
    d.add_setup("S", frequency="10GHz")
    return d


def test_builtin_mesher_is_always_available():
    d = _guide_design()
    m = d.generate_mesh(1e10, force=True, backend="builtin", size=0.003)
    assert m.n_tets > 100
    assert m.volumes.sum() == pytest.approx(22.86e-3 * 10.16e-3 * 10e-3, rel=0.2)
    assert len(m.port_faces["p1"]) > 0


@needs_occ
def test_occ_mesher_volume_and_quality():
    d = _guide_design()
    m = d.generate_mesh(1e10, force=True, backend="occ", size=0.004)
    assert m.volumes.sum() == pytest.approx(22.86e-3 * 10.16e-3 * 10e-3, rel=1e-6)
    assert m.quality().min() > 0.01
    assert len(m.port_faces["p1"]) > 5
    assert len(m.bc_faces["OuterPEC"]) > 5


@needs_occ
def test_pec_bodies_are_removed_from_the_solution_volume():
    d = ae.Design("pecbody")
    d.add_box("air", (0, 0, 0), ("10mm", "10mm", "10mm"), "vacuum")
    d.add_box("metal", ("3mm", "3mm", "3mm"), ("4mm", "4mm", "4mm"), "pec")
    d.add_wave_port("p1", axis="z", value=0)
    d.assign_pec_outer()
    d.add_setup("S", frequency="10GHz")
    m = d.generate_mesh(1e10, force=True, backend="occ", size=0.0015)
    assert "metal" not in m.region_names.values()
    expected = (10e-3) ** 3 - (4e-3) ** 3
    assert m.volumes.sum() == pytest.approx(expected, rel=1e-6)


@needs_occ
def test_stl_export_import_round_trip(tmp_path):
    from aether.geometry.brep_io import export_shapes, read_stl
    from aether.geometry.kernel import GmshSession, build_shape
    path = str(tmp_path / "b.stl")
    with GmshSession("stl") as gmsh:
        build_shape(ae.Box((0, 0, 0), (1, 2, 3)), gmsh)
        gmsh.model.occ.synchronize()
        export_shapes(path, gmsh)
    v, t = read_stl(path)
    assert len(t) >= 12
    assert np.allclose(v.min(0), [0, 0, 0], atol=1e-9)
    assert np.allclose(v.max(0), [1, 2, 3], atol=1e-9)


@needs_occ
def test_step_import_recovers_the_solid(tmp_path):
    from aether.geometry.brep_io import export_shapes
    from aether.geometry.kernel import GmshSession, build_shape
    path = str(tmp_path / "b.step")
    with GmshSession("step") as gmsh:
        build_shape(ae.Box((0, 0, 0), ("4mm", "5mm", "6mm")), gmsh)
        gmsh.model.occ.synchronize()
        export_shapes(path, gmsh)
    d = ae.Design("imported")
    d.add_solid("part", ae.import_cad(path), "vacuum")
    d.add_wave_port("p1", axis="z", value=0)
    d.assign_pec_outer()
    d.add_setup("S", frequency="10GHz")
    m = d.generate_mesh(1e10, force=True, backend="occ", size=0.001)
    assert m.volumes.sum() == pytest.approx(4e-3 * 5e-3 * 6e-3, rel=1e-6)
