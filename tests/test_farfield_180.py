"""
Far field and antenna parameters (1.8.0).

Three layers, each against something analytic:

1. the Stratton-Chu transform, fed the exact near field of a Hertzian dipole;
2. the OuterSelector, which must not put a radiation boundary on antenna metal;
3. the whole chain -- FEM solve, saved field, transform, power bookkeeping --
   on a half-wave dipole (D = 1.64 = 2.15 dBi, null on the axis, round in H).
"""
import math

import numpy as np
import pytest

from conftest import needs_occ

import aether as ae
from aether.geometry.select import BoxSelector
from aether.post.farfield import radiation_faces, transform_currents

c0 = ae.c0
ETA = 376.730313668


# ------------------------------------------------------------ the transform
def hertz_fields(p, f, il=0.01):
    k = 2 * math.pi * f / c0
    x, y, z = p.T
    r = np.sqrt(x * x + y * y + z * z)
    th, ph = np.arccos(z / r), np.arctan2(y, x)
    e = np.exp(-1j * k * r)
    er = ETA * il * np.cos(th) / (2 * math.pi * r ** 2) * (1 + 1 / (1j * k * r)) * e
    et = (1j * ETA * k * il * np.sin(th) / (4 * math.pi * r)
          * (1 + 1 / (1j * k * r) - 1 / (k * r) ** 2) * e)
    hp = 1j * k * il * np.sin(th) / (4 * math.pi * r) * (1 + 1 / (1j * k * r)) * e
    rh = np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph),
                   np.cos(th)], 1)
    thh = np.stack([np.cos(th) * np.cos(ph), np.cos(th) * np.sin(ph),
                    -np.sin(th)], 1)
    phh = np.stack([-np.sin(ph), np.cos(ph), 0 * ph], 1)
    return er[:, None] * rh + et[:, None] * thh, hp[:, None] * phh


def cube(a=0.04, n=24):
    g = (np.arange(n) + 0.5) / n * 2 * a - a
    cen, nrm = [], []
    for ax in range(3):
        for sgn in (-1, 1):
            u, v = np.meshgrid(g, g, indexing="ij")
            P = np.zeros((n * n, 3))
            idx = [i for i in range(3) if i != ax]
            P[:, idx[0]], P[:, idx[1]], P[:, ax] = u.ravel(), v.ravel(), sgn * a
            N = np.zeros((n * n, 3))
            N[:, ax] = sgn
            cen.append(P), nrm.append(N)
    cen, nrm = np.vstack(cen), np.vstack(nrm)
    return cen, np.full(len(cen), (2 * a / n) ** 2), nrm


def test_transform_reproduces_a_hertzian_dipole_exactly():
    f, il = 3e9, 0.01
    cen, area, nrm = cube()
    E, H = hertz_fields(cen, f, il)
    ff = transform_currents(cen, area, nrm, E, H, f)
    k = 2 * math.pi * f / c0
    p_exact = ETA * (k * il) ** 2 / (12 * math.pi)
    assert ff.P_radiated == pytest.approx(p_exact, rel=5e-3)
    assert ff.peak_directivity_dbi() == pytest.approx(
        10 * math.log10(1.5), abs=0.02)
    # null along the axis, theta-polarised, round about it
    d = ff.directivity()
    assert d[0].max() < 1e-3 * d.max() and d[-1].max() < 1e-3 * d.max()
    assert d[ff.theta.searchsorted(math.pi / 2)].std() < 1e-3 * d.max()
    assert np.abs(ff.E_phi).max() < 1e-3 * np.abs(ff.E_theta).max()


def test_enclosing_surface_independence():
    """A bigger surface around the same source gives the same pattern."""
    f = 3e9
    out = []
    for a in (0.03, 0.06):
        cen, area, nrm = cube(a, 24)
        E, H = hertz_fields(cen, f)
        out.append(transform_currents(cen, area, nrm, E, H, f).directivity())
    assert np.abs(out[0] - out[1]).max() < 0.03


def test_reversing_the_normal_flips_the_sign_not_the_pattern():
    f = 3e9
    cen, area, nrm = cube()
    E, H = hertz_fields(cen, f)
    a = transform_currents(cen, area, nrm, E, H, f)
    b = transform_currents(cen, area, -nrm, E, H, f)
    assert np.allclose(a.U, b.U)


def test_circular_polarisation_has_unit_axial_ratio():
    from aether.post.farfield import FarField
    th = np.linspace(0, math.pi, 5)
    ph = np.linspace(0, 2 * math.pi, 6, endpoint=False)
    et = np.ones((5, 6), complex)
    ff = FarField(th, ph, et, 1j * et, 1e9)
    assert np.allclose(ff.axial_ratio(), 1.0, atol=1e-6)
    ff2 = FarField(th, ph, et, 0 * et, 1e9)
    assert ff2.axial_ratio().min() > 1e6


# ------------------------------------------------------- the OuterSelector
@needs_occ
def test_radiation_boundary_never_lands_on_antenna_metal():
    d = ae.Design("rod")
    d.add_box("air", (-0.03, -0.03, -0.03), (0.06, 0.06, 0.06), "vacuum")
    d.add_box("rod", (-0.002, -0.002, -0.01), (0.004, 0.004, 0.02), "pec")
    d.assign_radiation("rad")
    d.add_setup("S", frequency="3GHz")
    m = d.generate_mesh(3e9, force=True, size=0.012)
    faces = radiation_faces(d, m)
    assert len(faces) > 0
    cen = m.surf_centroids[faces]
    # every radiation triangle sits on the air box, none on the rod
    assert np.all(np.max(np.abs(cen), axis=1) > 0.029)
    area = 0.5 * np.linalg.norm(np.cross(
        m.nodes[m.surf_tris[faces][:, 1]] - m.nodes[m.surf_tris[faces][:, 0]],
        m.nodes[m.surf_tris[faces][:, 2]] - m.nodes[m.surf_tris[faces][:, 0]]),
        axis=1)
    assert area.sum() == pytest.approx(6 * 0.06 * 0.06, rel=1e-3)


@needs_occ
def test_a_pec_enclosure_still_gets_its_walls():
    """The conductor exclusion must not strip legitimate outer faces."""
    d = ae.Design("c", solution_type="eigenmode")
    d.add_box("c", (0, 0, 0), (0.03, 0.015, 0.02), "vacuum")
    d.assign_pec_outer()
    d.add_setup("E", frequency="10GHz")
    m = d.generate_mesh(1e10, force=True, size=0.006)
    assert len(m.bc_faces["OuterPEC"]) == m.n_outer_faces


# ------------------------------------------------------ the whole chain
def dipole(order=2, r=0.4, hh=0.6, h=0.1):
    f0 = 3e9
    lam = c0 / f0
    gap, w = 2e-3, 2e-3
    arm = (0.47 * lam - gap) / 2
    R, H = r * lam, hh * lam
    d = ae.Design("dipole")
    d.add_box("air", (-R, -R, -H), (2 * R, 2 * R, 2 * H), "vacuum")
    d.add_box("arm_top", (-w / 2, -w / 2, gap / 2), (w, w, arm), "pec")
    d.add_box("arm_bot", (-w / 2, -w / 2, -gap / 2 - arm), (w, w, arm), "pec")
    d.add_sheet("feed", ae.Rectangle((-w / 2, 0, -gap / 2), (w, gap), "xz"))
    d.add_lumped_port("P1", selector=BoxSelector(
        (-w / 2 - 1e-6, -1e-6, -gap / 2 - 1e-6),
        (w / 2 + 1e-6, 1e-6, gap / 2 + 1e-6)), impedance=73,
        direction=(0, 0, 1))
    d.assign_radiation("rad")
    st = d.add_setup("S1", frequency=f0, max_passes=1, basis_order=order)
    st.add_sweep("sw", points=[f0], count=1, save_fields=True)
    d.config.mesh.max_element_size = lam * h
    d.add_mesh_operation("arms", 2.5e-3, objects=["arm_top", "arm_bot"])
    d.add_mesh_operation("gap", 1e-3, objects=["feed"])
    return d


@pytest.fixture(scope="module")
def dipole_solution():
    d = dipole()
    return d.solve(adaptive=False, progress=False, save_fields=True)


@needs_occ
@pytest.mark.slow
def test_half_wave_dipole_directivity_and_pattern(dipole_solution):
    ff = dipole_solution.farfield()
    assert ff.peak_directivity_dbi() == pytest.approx(2.15, abs=0.4)
    th, ph = ff.peak_direction()
    assert abs(th - 90.0) <= 6.0
    d = ff.directivity()
    # E-plane null along the dipole axis
    assert 10 * math.log10(d[0].max() / d.max()) < -15
    # H-plane is round
    ring = d[ff.theta.searchsorted(math.pi / 2)]
    assert 10 * math.log10(ring.max() / ring.min()) < 0.5
    # symmetric about the feed: front-to-back ~ 0 dB
    assert abs(ff.summary()["frontToBackDb"]) < 0.5
    # linear polarisation
    assert ff.summary()["axialRatioAtPeak"] > 30


@needs_occ
@pytest.mark.slow
def test_power_bookkeeping_closes_for_a_lossless_antenna(dipole_solution):
    ff = dipole_solution.farfield()
    assert ff.efficiency == pytest.approx(1.0, abs=1e-9)   # nothing dissipates
    assert ff.P_dissipated == pytest.approx(0.0, abs=1e-9)
    # far-field power and the power the absorbing boundary takes agree: the
    # air region is large enough for the radiation condition
    assert ff.P_boundary / ff.P_radiated == pytest.approx(1.0, abs=0.2)
    assert ff.gain().max() == pytest.approx(ff.directivity().max(), rel=1e-9)


@needs_occ
@pytest.mark.slow
def test_farfield_needs_saved_fields_and_a_radiation_boundary():
    d = dipole()
    sol = d.solve(adaptive=False, progress=False, save_fields=False)
    sol.fields.clear()
    with pytest.raises(RuntimeError, match="save fields"):
        sol.farfield()
    d2 = dipole()
    d2.boundaries.clear()
    sol2 = d2.solve(adaptive=False, progress=False, save_fields=True)
    with pytest.raises(RuntimeError, match="radiation boundary"):
        sol2.farfield()


@needs_occ
@pytest.mark.slow
def test_gui_commands_return_cuts_summary_and_pattern(dipole_solution):
    from aether.gui.api import dispatch
    from aether.gui.state import Session
    s = Session()
    s.new_project("P")
    s.design = dipole()
    s.project.designs[0] = s.design
    s.solution = dipole_solution
    r = dispatch(s, "results.farField", {"cuts": [0, 90]})
    assert len(r["theta"]) == 91 and len(r["cuts"]) == 2
    assert r["summary"]["peakGainDbi"] == pytest.approx(2.15, abs=0.4)
    assert "peakRealizedGainDbi" in r["summary"]
    assert r["summary"]["peakRealizedGainDbi"] <= r["summary"]["peakGainDbi"]
    assert not r["warnings"]
    v = dispatch(s, "view.pattern", {})
    assert len(v["scalar"]) == v["scalar"].__len__() > 0
    lo, hi = v["range"]
    assert hi - lo == pytest.approx(30.0)
