"""Units, constants and material models."""
import math

import numpy as np
import pytest

from aether.core.constants import (UnitError, c0, eps0, eta0, k0, mu0,
                                   skin_depth, surface_impedance, to_si,
                                   wavelength)
from aether.core.materials import (LIBRARY, ConstantTanD, Debye,
                                   DjordjevicSarkar, Drude, Material)


def test_si_definitions_are_consistent():
    assert eps0 == pytest.approx(1.0 / (mu0 * c0 ** 2), rel=1e-15)
    assert eta0 == pytest.approx(math.sqrt(mu0 / eps0), rel=1e-15)
    assert eta0 == pytest.approx(376.730313668, rel=1e-9)


@pytest.mark.parametrize("text,expect", [
    ("2.54mm", 2.54e-3), ("1 in", 0.0254), ("100mil", 2.54e-3),
    ("-3.5e-2 m", -0.035), ("1km", 1000.0),
])
def test_length_units(text, expect):
    assert to_si(text) == pytest.approx(expect, rel=1e-12)


def test_frequency_and_angle_units():
    assert to_si("10GHz", "frequency") == 1e10
    assert to_si("90deg", "angle") == pytest.approx(math.pi / 2)
    with pytest.raises(UnitError):
        to_si("5 parsecs")


def test_wavelength_and_wavenumber():
    assert wavelength(1e9) == pytest.approx(0.299792458)
    assert wavelength(1e9, eps_r=4.0) == pytest.approx(0.299792458 / 2)
    assert k0(1e9) == pytest.approx(2 * math.pi / 0.299792458)


def test_copper_skin_depth_and_surface_impedance():
    # textbook value: ~2.09 um at 1 GHz
    assert skin_depth(1e9, 5.8e7) == pytest.approx(2.0898e-6, rel=1e-3)
    zs = surface_impedance(1e9, 5.8e7)
    assert zs.real == pytest.approx(zs.imag)
    assert zs.real == pytest.approx(8.25e-3, rel=1e-2)


def test_conductor_permittivity_dominated_by_conduction():
    cu = LIBRARY.get("copper")
    e = cu.eps_c(1e9)
    assert e.imag < -1e6            # sigma/(w eps0) is enormous
    assert e.real == pytest.approx(1.0)


def test_lossy_dielectric_sign_convention():
    m = LIBRARY.get("fr4_epoxy")
    e = m.eps_c(1e9)
    assert e.real == pytest.approx(4.4)
    assert e.imag < 0                     # e^{+jwt}: loss is negative imag
    assert m.loss_tangent(1e9) == pytest.approx(0.02)


def test_debye_is_causal_and_monotonic():
    m = Material("d", Debye(eps_inf=2.0, poles=((3.0, 1e-10),)))
    lo, hi = m.eps_c(1e6).real, m.eps_c(1e12).real
    assert lo > hi                        # relaxation lowers eps with frequency
    assert m.eps_c(1e9).imag < 0


def test_drude_metal_goes_negative_below_plasma_frequency():
    m = Material("au", Drude(eps_inf=9.0, wp=1.36e16, gamma=1.05e14))
    assert m.eps_c(3e14).real < 0


def test_djordjevic_sarkar_keeps_tan_d_flat():
    m = LIBRARY.get("fr4_djordjevic")
    tds = [m.loss_tangent(f) for f in (1e7, 1e8, 1e9, 1e10)]
    assert max(tds) - min(tds) < 4e-3
    assert m.eps_c(1e7).real > m.eps_c(1e10).real   # causal dispersion


def test_material_library_lookup_is_forgiving():
    assert LIBRARY.get("Rogers RO4003C").eps_c(1e9).real == pytest.approx(3.55)
    assert "copper" in LIBRARY
    with pytest.raises(KeyError):
        LIBRARY.get("unobtainium")
