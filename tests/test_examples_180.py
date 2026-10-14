"""
Every shipped example must open, validate, mesh with all its ports and
boundaries landing on faces, and the cheap ones must solve.

The meshing check is the one that matters: an example whose port selected no
triangles used to look fine in the tree and fail only when someone pressed
Analyze.
"""
import os
import sys

import numpy as np
import pytest

from conftest import needs_occ

import aether as ae

HERE = os.path.join(os.path.dirname(__file__), "..", "examples")
sys.path.insert(0, HERE)
from build_examples import EXAMPLES                       # noqa: E402

pytestmark = needs_occ


def path(name):
    return os.path.join(HERE, name + ".warp")


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_the_shipped_file_exists_and_opens_cleanly(name):
    assert os.path.isfile(path(name)), f"run examples/build_examples.py ({name})"
    d, report = ae.open_warps(path(name))
    assert d.validate() == []
    assert not report.unresolved


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_every_port_and_boundary_lands_on_mesh_faces(name):
    d, _ = ae.open_warps(path(name))
    st = d.setups[0]
    f = st.frequency if st.frequency > 0 else 1e9
    m = d.generate_mesh(f, force=True)
    for p in d.ports:
        assert len(m.port_faces[p.name]) > 0, f"{name}: port {p.name} is empty"
    for b in d.boundaries:
        assert len(m.bc_faces.get(b.name, [])) > 0, \
            f"{name}: boundary {b.name} is empty"


@pytest.mark.parametrize("name", ["parallel_plate_lumped", "cavity_eigenmode",
                                  "copper_cavity_eigenmode",
                                  "slab_matching_parametric"])
def test_the_small_examples_solve(name):
    d, _ = ae.open_warps(path(name))
    sol = d.solve(progress=False)
    if sol.modes:
        assert all(m.f > 0 for m in sol.modes)
    else:
        assert np.isfinite(sol.sparams.s).all() and sol.sparams.is_passive(1e-3)


def test_the_cavity_examples_match_their_closed_forms():
    from math import hypot
    d, _ = ae.open_warps(path("cavity_eigenmode"))
    f = d.solve(progress=False).modes[0].f
    want = 0.5 * ae.c0 * hypot(1 / 30e-3, 1 / 20e-3)
    assert f == pytest.approx(want, rel=5e-4)
    d2, _ = ae.open_warps(path("copper_cavity_eigenmode"))
    q = d2.solve(progress=False).modes[0].q
    assert q == pytest.approx(9182, rel=0.02)           # Pozar 6.46


def test_the_dipole_example_is_a_drawn_face_feeding_a_lumped_port():
    d, _ = ae.open_warps(path("dipole_antenna"))
    assert [s.name for s in d.sheets] == ["Feed"]
    assert d.ports[0].kind == "lumped"
    assert any(b.btype == "radiation" for b in d.boundaries)
    assert d.setups[0].basis_order == 2
    assert d.setups[0].sweeps[0].save_fields          # the far field needs them
    # the arms are conductors: the radiation boundary must not wrap them
    m = d.generate_mesh(3e9, force=True)
    from aether.post.farfield import radiation_faces
    cen = m.surf_centroids[radiation_faces(d, m)]
    # every radiation face lies on the outside of the air box (on one of the
    # six bounding planes), none on the antenna metal in the middle
    lo, hi = m.nodes.min(axis=0), m.nodes.max(axis=0)
    tol = 1e-6 * float(np.max(hi - lo))
    on_box = np.any((np.abs(cen - lo) < tol) | (np.abs(cen - hi) < tol), axis=1)
    assert on_box.all()


def test_builder_output_matches_the_shipped_files(tmp_path):
    """The .warp files in the repository are what the builder writes."""
    from build_examples import build
    for name in ("wr90_waveguide", "dipole_antenna", "patch_antenna"):
        out = build(name, str(tmp_path))
        a, _ = ae.open_warps(out)
        b, _ = ae.open_warps(path(name))
        assert [s.name for s in a.solids] == [s.name for s in b.solids]
        assert [p.name for p in a.ports] == [p.name for p in b.ports]
        assert a.setups[0].frequency == b.setups[0].frequency
