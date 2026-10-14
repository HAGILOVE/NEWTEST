"""
Physics validation against closed-form solutions.

Every number these tests compare against is an analytic result for the
structure, not a stored output of this code.
"""
import math

import numpy as np
import pytest

from conftest import needs_occ

import aether as ae
from aether.core.constants import c0, eta0

A, B = 22.86e-3, 10.16e-3          # WR-90 internal dimensions
pytestmark = needs_occ


def te_cutoff(m, n, a=A, b=B):
    return 0.5 * c0 * math.hypot(m / a, n / b)


def te_beta(f, m=1, n=0, a=A, b=B):
    k0 = 2 * math.pi * f / c0
    kc = math.pi * math.hypot(m / a, n / b)
    return math.sqrt(k0 ** 2 - kc ** 2)


def wr90(length=0.02, order=1, size=0.003, modes=1):
    d = ae.Design("wr90")
    d.config.basis_order = order
    d.add_box("guide", (0, 0, 0), (A, B, length), "vacuum")
    d.add_wave_port("p1", axis="z", value=0, num_modes=modes)
    d.add_wave_port("p2", axis="z", value=length, num_modes=modes)
    d.assign_pec_outer()
    st = d.add_setup("S1", frequency="10GHz", basis_order=order)
    st.add_sweep("Sw", points=["10GHz"], count=1)
    d.generate_mesh(1e10, force=True, size=size)
    return d


# ------------------------------------------------------------------ modes
def test_rectangular_waveguide_modal_solution():
    d = wr90(modes=3, size=0.0035)
    from aether.fem.elements import DofMap
    from aether.fem.ports import solve_port_modes
    m = d.mesh
    dm = DofMap(m, 1)
    tris = m.surf_tris[m.port_faces["p1"]]
    sol = solve_port_modes(m, dm, tris, 1e10, lambda r: 1 + 0j,
                           lambda r: 1 + 0j, n_modes=3, name="p1")
    # TE10 propagation constant and wave impedance
    m1 = sol.modes[0]
    assert m1.kind == "TE" and m1.propagating
    assert m1.beta == pytest.approx(te_beta(1e10), rel=2e-3)
    assert m1.f_cut == pytest.approx(te_cutoff(1, 0), rel=2e-3)
    z_te = eta0 / math.sqrt(1 - (te_cutoff(1, 0) / 1e10) ** 2)
    assert m1.Z_wave.real == pytest.approx(z_te, rel=3e-3)
    # the next two modes are the evanescent TE20 and TE01
    assert sol.modes[1].f_cut == pytest.approx(te_cutoff(2, 0), rel=3e-3)
    assert sol.modes[2].f_cut == pytest.approx(te_cutoff(0, 1), rel=3e-3)
    assert not sol.modes[1].propagating


def test_below_cutoff_the_dominant_mode_is_evanescent():
    d = wr90(size=0.004)
    from aether.fem.elements import DofMap
    from aether.fem.ports import solve_port_modes
    dm = DofMap(d.mesh, 1)
    tris = d.mesh.surf_tris[d.mesh.port_faces["p1"]]
    sol = solve_port_modes(d.mesh, dm, tris, 5e9, lambda r: 1 + 0j,
                           lambda r: 1 + 0j, n_modes=1, name="p1")
    m = sol.modes[0]
    assert not m.propagating
    k0 = 2 * math.pi * 5e9 / c0
    alpha = math.sqrt((math.pi / A) ** 2 - k0 ** 2)
    assert m.alpha == pytest.approx(alpha, rel=1e-2)


# -------------------------------------------------------------- S-matrix
def test_uniform_waveguide_is_matched_and_phase_accurate():
    L = 0.02
    d = wr90(L, order=1, size=0.0025)
    sp = d.solve(adaptive=False).sparams
    assert abs(sp.s[0, 0, 0]) < 5e-3                      # < -46 dB return loss
    assert abs(sp.s[0, 1, 0]) == pytest.approx(1.0, abs=2e-4)
    got = math.degrees(np.angle(sp.s[0, 1, 0]))
    want = math.degrees(np.angle(np.exp(-1j * te_beta(1e10) * L)))
    assert abs((got - want + 180) % 360 - 180) < 0.5


def test_second_order_basis_is_far_more_accurate():
    L = 0.02
    err = {}
    for order in (1, 2):
        d = wr90(L, order=order, size=0.005)
        sp = d.solve(adaptive=False).sparams
        got = math.degrees(np.angle(sp.s[0, 1, 0]))
        want = math.degrees(np.angle(np.exp(-1j * te_beta(1e10) * L)))
        err[order] = abs((got - want + 180) % 360 - 180)
    assert err[2] < err[1] / 5.0


def test_solution_is_reciprocal_and_passive():
    d = wr90(0.015, size=0.003)
    sp = d.solve(adaptive=False).sparams
    assert sp.is_reciprocal(tol=1e-6)
    assert sp.is_passive()


def test_mesh_refinement_reduces_the_error():
    L = 0.02
    want = math.degrees(np.angle(np.exp(-1j * te_beta(1e10) * L)))
    errs = []
    for size in (0.005, 0.003, 0.002):
        d = wr90(L, order=1, size=size)
        sp = d.solve(adaptive=False).sparams
        got = math.degrees(np.angle(sp.s[0, 1, 0]))
        errs.append(abs((got - want + 180) % 360 - 180))
    assert errs[0] > errs[1] > errs[2]


def test_shorted_waveguide_reflects_everything():
    """A guide closed by PEC must give |S11| = 1 with the round-trip phase."""
    L = 0.012
    d = ae.Design("short")
    d.add_box("guide", (0, 0, 0), (A, B, L), "vacuum")
    d.add_wave_port("p1", axis="z", value=0)
    d.assign_pec_outer()
    st = d.add_setup("S1", frequency="10GHz")
    st.add_sweep("Sw", points=["10GHz"], count=1)
    d.generate_mesh(1e10, force=True, size=0.0025)
    sp = d.solve(adaptive=False).sparams
    assert abs(sp.s[0, 0, 0]) == pytest.approx(1.0, abs=2e-3)
    want = math.degrees(np.angle(-np.exp(-2j * te_beta(1e10) * L)))
    got = math.degrees(np.angle(sp.s[0, 0, 0]))
    assert abs((got - want + 180) % 360 - 180) < 2.0


def test_lossy_dielectric_removes_power():
    L = 0.02
    d = ae.Design("lossy")
    lib = d.materials
    lib.define("lossy_air", eps_r=1.0, tan_d=0.02)
    d.add_box("guide", (0, 0, 0), (A, B, L), "lossy_air")
    d.add_wave_port("p1", axis="z", value=0)
    d.add_wave_port("p2", axis="z", value=L)
    d.assign_pec_outer()
    st = d.add_setup("S1", frequency="10GHz")
    st.add_sweep("Sw", points=["10GHz"], count=1)
    d.generate_mesh(1e10, force=True, size=0.003)
    sp = d.solve(adaptive=False).sparams
    out = abs(sp.s[0, 0, 0]) ** 2 + abs(sp.s[0, 1, 0]) ** 2
    assert out < 0.999                       # power is dissipated
    assert sp.is_passive()
    # attenuation of a TE10 mode in a slightly lossy dielectric:
    #   alpha = k0^2 tan_d / (2 beta)
    k0 = 2 * math.pi * 1e10 / c0
    alpha = k0 ** 2 * 0.02 / (2 * te_beta(1e10))
    assert abs(sp.s[0, 1, 0]) == pytest.approx(math.exp(-alpha * L), rel=0.05)


def test_coaxial_line_is_tem_with_the_designed_impedance():
    a = 1e-3
    b = a * math.exp(50.0 * 2 * math.pi / eta0)     # 50 ohm in air
    L = 0.01
    d = ae.Design("coax")
    d.add_solid("diel",
                ae.Cylinder((0, 0, 0), b, L)
                - ae.Cylinder((0, 0, -1e-3), a, L + 2e-3), "vacuum")
    d.add_wave_port("p1", axis="z", value=0,
                    integration_line=((a, 0, 0), (b, 0, 0)))
    d.add_wave_port("p2", axis="z", value=L,
                    integration_line=((a, 0, L), (b, 0, L)))
    st = d.add_setup("S1", frequency="10GHz")
    st.add_sweep("Sw", points=["10GHz"], count=1)
    d.generate_mesh(1e10, force=True, size=0.0008)
    sol = d.solve(adaptive=False)
    m = sol.port_mode(1e10, 0, 0)
    k0 = 2 * math.pi * 1e10 / c0
    assert m.beta == pytest.approx(k0, rel=2e-3)       # TEM: beta = k0
    assert m.f_cut < 1e8                               # no cutoff
    assert m.Z_wave.real == pytest.approx(eta0, rel=1e-3)
    assert m.Z_pv.real == pytest.approx(50.0, rel=0.03)
    sp = sol.sparams
    assert abs(sp.s[0, 0, 0]) < 0.01
    got = math.degrees(np.angle(sp.s[0, 1, 0]))
    want = math.degrees(np.angle(np.exp(-1j * k0 * L)))
    assert abs((got - want + 180) % 360 - 180) < 1.5


def test_adaptive_passes_converge():
    d = ae.Design("wr90")
    d.add_box("guide", (0, 0, 0), (A, B, 0.015), "vacuum")
    d.add_wave_port("p1", axis="z", value=0)
    d.add_wave_port("p2", axis="z", value=0.015)
    d.assign_pec_outer()
    st = d.add_setup("S1", frequency="10GHz", max_passes=4, delta_s=0.02)
    st.add_sweep("Sw", points=["10GHz"], count=1)
    sol = d.solve()
    assert len(sol.convergence) >= 2
    ds = [c["delta_s"] for c in sol.convergence if c["delta_s"] is not None]
    assert ds and ds[-1] <= 0.02                    # met the convergence goal
    assert ds[-1] < ds[0]                           # and it is still improving
    assert sol.convergence[-1]["tets"] > sol.convergence[0]["tets"]


def test_field_solution_energy_balance():
    """Stored electric and magnetic energy must match in a matched guide."""
    d = wr90(0.02, size=0.003)
    sol = d.solve(adaptive=False, save_fields=True)
    fs = sol.field(1e10, 0)
    We, Wm = fs.stored_energy()
    assert We > 0 and Wm > 0
    assert We == pytest.approx(Wm, rel=0.1)


def test_frequency_sweep_tracks_dispersion():
    L = 0.02
    d = wr90(L, size=0.003)
    d.setups[0].sweeps.clear()
    d.setups[0].add_sweep("Sw", "8GHz", "12GHz", 5)
    sp = d.solve(adaptive=False).sparams
    for i, f in enumerate(sp.freq):
        want = math.degrees(np.angle(np.exp(-1j * te_beta(f) * L)))
        got = math.degrees(np.angle(sp.s[i, 1, 0]))
        assert abs((got - want + 180) % 360 - 180) < 1.5
        assert abs(sp.s[i, 1, 0]) == pytest.approx(1.0, abs=1e-3)


def test_lumped_ports_on_a_parallel_plate_line():
    """
    A parallel-plate line has Z0 = eta0 * h / w exactly (TEM, PMC sidewalls).
    Driving it with lumped ports of that impedance must give a perfect match
    and the free-space phase delay.
    """
    h, w, L = 1e-3, 10e-3, 20e-3
    z0 = eta0 * h / w
    d = ae.Design("pplate")
    d.add_box("air", (0, 0, 0), (L, w, h), "vacuum")
    d.assign_boundary("PMC_y0", "pmc", ae.PlaneSelector("y", 0))
    d.assign_boundary("PMC_y1", "pmc", ae.PlaneSelector("y", w))
    d.add_lumped_port("p1", axis="x", value=0, impedance=z0,
                      direction=(0, 0, 1))
    d.add_lumped_port("p2", axis="x", value=L, impedance=z0,
                      direction=(0, 0, 1))
    st = d.add_setup("S1", frequency="5GHz")
    st.add_sweep("Sw", points=["5GHz"], count=1)
    d.generate_mesh(5e9, force=True, size=0.0015)
    sp = d.solve(adaptive=False).sparams
    k0 = 2 * math.pi * 5e9 / c0
    assert abs(sp.s[0, 0, 0]) < 5e-3
    assert abs(sp.s[0, 1, 0]) == pytest.approx(1.0, abs=1e-4)
    got = math.degrees(np.angle(sp.s[0, 1, 0]))
    want = math.degrees(np.angle(np.exp(-1j * k0 * L)))
    assert abs((got - want + 180) % 360 - 180) < 0.5


def test_lumped_port_mismatch_follows_the_reflection_formula():
    """Terminating the same line in 2*Z0 must give the textbook |S11|."""
    h, w, L = 1e-3, 10e-3, 20e-3
    z0 = eta0 * h / w
    d = ae.Design("pplate_mismatch")
    d.add_box("air", (0, 0, 0), (L, w, h), "vacuum")
    d.assign_boundary("PMC_y0", "pmc", ae.PlaneSelector("y", 0))
    d.assign_boundary("PMC_y1", "pmc", ae.PlaneSelector("y", w))
    d.add_lumped_port("p1", axis="x", value=0, impedance=z0,
                      direction=(0, 0, 1))
    d.add_lumped_port("p2", axis="x", value=L, impedance=2 * z0,
                      direction=(0, 0, 1))
    st = d.add_setup("S1", frequency="5GHz")
    st.add_sweep("Sw", points=["5GHz"], count=1)
    d.generate_mesh(5e9, force=True, size=0.0015)
    sp = d.solve(adaptive=False).sparams
    # port 1 sees a z0 line terminated in 2*z0 -> |Gamma| = 1/3
    assert abs(sp.s[0, 0, 0]) == pytest.approx(1 / 3, rel=0.03)
    assert sp.is_passive()


def _iris_guide(gap, size=0.002):
    L = 0.03
    d = ae.Design("iris")
    d.add_box("guide", (0, 0, 0), (A, B, L), "vacuum")
    d.add_sheet("iris", ae.Rectangle((0, 0, L / 2), (A, B), "xy"))
    d.add_wave_port("p1", axis="z", value=0)
    d.add_wave_port("p2", axis="z", value=L)
    d.assign_pec("IrisPEC", ae.union_sel(
        ae.BoxSelector((0, 0, L / 2 - 1e-9), ((A - gap) / 2, B, L / 2 + 1e-9)),
        ae.BoxSelector(((A + gap) / 2, 0, L / 2 - 1e-9), (A, B, L / 2 + 1e-9))))
    d.assign_pec_outer("Walls")
    st = d.add_setup("S", frequency="10GHz")
    st.add_sweep("Sw", points=["10GHz"], count=1)
    d.generate_mesh(1e10, force=True, size=size)
    return d.solve(adaptive=False).sparams


def test_internal_pec_sheet_with_a_slot_behaves_like_an_inductive_iris():
    """
    Narrowing the slot must monotonically increase reflection, and a lossless
    iris must conserve power exactly.  A blanket outer-PEC assignment must not
    leak onto the slot -- that failure mode gives |S21| = 0 for every gap.
    """
    r = []
    for gap in (16e-3, 12e-3, 8e-3):
        sp = _iris_guide(gap)
        s11, s21 = abs(sp.s[0, 0, 0]), abs(sp.s[0, 1, 0])
        assert s11 ** 2 + s21 ** 2 == pytest.approx(1.0, abs=1e-6)
        r.append(s11)
    assert r[0] < r[1] < r[2]
    assert r[0] < 0.5 and r[2] > 0.8


def test_fully_closed_pec_sheet_blocks_transmission():
    sp = _iris_guide(0.0)
    assert abs(sp.s[0, 1, 0]) < 1e-9
    assert abs(sp.s[0, 0, 0]) == pytest.approx(1.0, abs=1e-6)
