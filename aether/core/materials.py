"""
Material models for full-wave electromagnetics.

A :class:`Material` supplies frequency-dependent complex relative permittivity
and permeability plus a bulk conductivity.  Constitutive evaluation returns

    eps_c(f) = eps_r'(f) - j*eps_r''(f) - j*sigma/(w*eps0)
    mu_c(f)  = mu_r'(f)  - j*mu_r''(f)

using the **e^{+jwt} engineering time convention** (loss => negative imaginary
part), matching Warps/ADS/Touchstone.  Every solver kernel in Aether-EM consumes
only these two complex numbers, so adding a new dispersion law never touches
the FEM code.
"""
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Sequence

from .constants import eps0, mu0, omega, skin_depth, surface_impedance

# --------------------------------------------------------------------------
# Dispersion laws
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Dispersion:
    """Base class -- returns a constant."""

    def eps(self, f: float) -> complex:  # pragma: no cover - overridden
        return 1.0 + 0j


@dataclass(frozen=True)
class ConstantTanD(Dispersion):
    """Constant eps_r with constant loss tangent (Warps default model)."""
    eps_r: float = 1.0
    tan_d: float = 0.0

    def eps(self, f: float) -> complex:
        return complex(self.eps_r, -self.eps_r * self.tan_d)


@dataclass(frozen=True)
class Debye(Dispersion):
    """
    Multi-pole Debye relaxation.

        eps(w) = eps_inf + sum_k  d_eps_k / (1 + j w tau_k)
    """
    eps_inf: float = 1.0
    poles: Sequence[tuple] = ()   # ((d_eps, tau_seconds), ...)

    def eps(self, f: float) -> complex:
        w = omega(f)
        e = complex(self.eps_inf, 0.0)
        for d_eps, tau in self.poles:
            e += d_eps / (1.0 + 1j * w * tau)
        return e


@dataclass(frozen=True)
class Drude(Dispersion):
    """
    Drude free-electron metal (optical/THz regime).

        eps(w) = eps_inf - wp^2 / (w^2 - j*w*gamma)
    """
    eps_inf: float = 1.0
    wp: float = 0.0       # plasma angular frequency [rad/s]
    gamma: float = 0.0    # collision rate [rad/s]

    def eps(self, f: float) -> complex:
        w = omega(f)
        if w == 0.0:
            return complex(self.eps_inf, 0.0)
        return self.eps_inf - self.wp ** 2 / (w * w - 1j * w * self.gamma)


@dataclass(frozen=True)
class Lorentz(Dispersion):
    """
    Multi-pole Lorentz oscillator.

        eps(w) = eps_inf + sum_k  d_eps_k * w0_k^2 / (w0_k^2 + 2j*delta_k*w - w^2)
    """
    eps_inf: float = 1.0
    poles: Sequence[tuple] = ()   # ((d_eps, w0, delta), ...)

    def eps(self, f: float) -> complex:
        w = omega(f)
        e = complex(self.eps_inf, 0.0)
        for d_eps, w0, delta in self.poles:
            e += d_eps * w0 * w0 / (w0 * w0 + 2j * delta * w - w * w)
        return e


@dataclass(frozen=True)
class DjordjevicSarkar(Dispersion):
    """
    Djordjevic-Sarkar wideband causal dielectric (the model Warps applies when
    you tick "Set Frequency Dependency").  Guarantees Kramers-Kronig causality
    for a nominally constant loss tangent over [f1, f2].
    """
    eps_r: float = 4.4          # value at f_ref
    tan_d: float = 0.02         # loss tangent at f_ref
    f_ref: float = 1e9
    f1: float = 1e3
    f2: float = 1e12
    eps_inf: float = 1.0

    def _de(self) -> float:
        # d_eps chosen so tan_d is matched at f_ref
        w1, w2 = omega(self.f1), omega(self.f2)
        wr = omega(self.f_ref)
        L = math.log((w2 ** 2 + wr ** 2) / (w1 ** 2 + wr ** 2))
        if abs(L) < 1e-30:
            return 0.0
        # Im part of the log-model at f_ref  =  d_eps * (pi/2) / ln(w2/w1) approx
        return self.eps_r * self.tan_d * 2.0 * math.log(w2 / w1) / math.pi

    def eps(self, f: float) -> complex:
        w = max(omega(f), 1e-12)
        w1, w2 = omega(self.f1), omega(self.f2)
        de = self._de()
        term = cmath.log((w2 + 1j * w) / (w1 + 1j * w)) / math.log(w2 / w1)
        e = self.eps_inf + de * term
        # renormalise real part to hit eps_r at f_ref
        wr = omega(self.f_ref)
        term_r = (cmath.log((w2 + 1j * wr) / (w1 + 1j * wr)) / math.log(w2 / w1)).real
        shift = self.eps_r - (self.eps_inf + de * term_r)
        return complex(e.real + shift, e.imag)


@dataclass(frozen=True)
class Tabulated(Dispersion):
    """Piecewise-linear interpolation of measured eps_r(f) data."""
    freqs: Sequence[float] = ()
    values: Sequence[complex] = ()

    def eps(self, f: float) -> complex:
        fs, vs = self.freqs, self.values
        if not fs:
            return 1.0 + 0j
        if f <= fs[0]:
            return complex(vs[0])
        if f >= fs[-1]:
            return complex(vs[-1])
        for i in range(len(fs) - 1):
            if fs[i] <= f <= fs[i + 1]:
                t = (f - fs[i]) / (fs[i + 1] - fs[i])
                return complex(vs[i]) * (1 - t) + complex(vs[i + 1]) * t
        return complex(vs[-1])  # pragma: no cover


# --------------------------------------------------------------------------
# Material
# --------------------------------------------------------------------------


@dataclass
class Material:
    """
    A named electromagnetic medium.

    Parameters
    ----------
    name : str
    eps_model : Dispersion
        Relative permittivity law.
    mu_model : Dispersion
        Relative permeability law (real 1.0 for non-magnetic).
    sigma : float
        Bulk electric conductivity [S/m].  Enters as -j*sigma/(w*eps0).
    sigma_m : float
        Magnetic "conductivity" [Ohm/m] for artificial absorbers.
    kind : str
        ``dielectric`` | ``conductor`` | ``pec`` | ``pmc``.
    """
    name: str
    eps_model: Dispersion = field(default_factory=lambda: ConstantTanD(1.0, 0.0))
    mu_model: Dispersion = field(default_factory=lambda: ConstantTanD(1.0, 0.0))
    sigma: float = 0.0
    sigma_m: float = 0.0
    kind: str = "dielectric"
    color: str = "#8899aa"
    transparency: float = 0.6
    mass_density: float = 0.0
    thermal_conductivity: float = 0.0

    # -- constitutive evaluation -------------------------------------------
    def eps_c(self, f: float) -> complex:
        """Complex relative permittivity including bulk conduction loss."""
        e = self.eps_model.eps(f)
        if self.sigma:
            w = omega(max(f, 1e-30))
            e = complex(e.real, e.imag - self.sigma / (w * eps0))
        return e

    def mu_c(self, f: float) -> complex:
        """Complex relative permeability including magnetic loss."""
        m = self.mu_model.eps(f)
        if self.sigma_m:
            w = omega(max(f, 1e-30))
            m = complex(m.real, m.imag - self.sigma_m / (w * mu0))
        return m

    # -- derived quantities -------------------------------------------------
    def refractive_index(self, f: float) -> complex:
        return cmath.sqrt(self.eps_c(f) * self.mu_c(f))

    def wave_impedance(self, f: float) -> complex:
        from .constants import eta0
        return eta0 * cmath.sqrt(self.mu_c(f) / self.eps_c(f))

    def loss_tangent(self, f: float) -> float:
        e = self.eps_c(f)
        return -e.imag / e.real if e.real else 0.0

    def skin_depth(self, f: float) -> float:
        return skin_depth(f, self.sigma, self.mu_c(f).real)

    def surface_impedance(self, f: float) -> complex:
        return surface_impedance(f, self.sigma, self.mu_c(f).real)

    @property
    def is_pec(self) -> bool:
        return self.kind == "pec"

    @property
    def is_conductor(self) -> bool:
        return self.kind in ("conductor", "pec")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Material {self.name!r} kind={self.kind} sigma={self.sigma:g}>"


# --------------------------------------------------------------------------
# Built-in library  (values from standard RF/microwave references)
# --------------------------------------------------------------------------

def _diel(name, er, td=0.0, **kw):
    return Material(name, ConstantTanD(er, td), ConstantTanD(1.0, 0.0), kind="dielectric", **kw)


def _metal(name, sigma, **kw):
    return Material(name, ConstantTanD(1.0, 0.0), ConstantTanD(1.0, 0.0),
                    sigma=sigma, kind="conductor", color="#c0c0c0",
                    transparency=0.0, **kw)


_LIB: Dict[str, Material] = {}


def _reg(m: Material) -> Material:
    _LIB[m.name.lower()] = m
    return m


# vacuum / air
_reg(Material("vacuum", ConstantTanD(1.0, 0.0), ConstantTanD(1.0, 0.0), kind="dielectric",
              color="#dfe8ef", transparency=0.95))
_reg(_diel("air", 1.0006, 0.0, color="#dfe8ef", transparency=0.95))
# PEC / PMC pseudo-materials
_reg(Material("pec", ConstantTanD(1.0, 0.0), ConstantTanD(1.0, 0.0),
              sigma=math.inf, kind="pec", color="#b8b8b8", transparency=0.0))
_reg(Material("pmc", ConstantTanD(1.0, 0.0), ConstantTanD(1.0, 0.0),
              kind="pmc", color="#c8a8a8", transparency=0.0))
# conductors [S/m @ 20 C]
_reg(_metal("copper", 5.8e7, mass_density=8933.0, thermal_conductivity=400.0))
_reg(_metal("annealed_copper", 5.8001e7))
_reg(_metal("silver", 6.3e7))
_reg(_metal("gold", 4.1e7))
_reg(_metal("aluminum", 3.8e7))
_reg(_metal("brass", 1.5e7))
_reg(_metal("nickel", 1.45e7))
_reg(_metal("tin", 8.7e6))
_reg(_metal("solder", 7.0e6))
_reg(_metal("graphite", 7.0e4))
_reg(_metal("steel_stainless", 1.1e6))
_reg(_metal("titanium", 1.82e6))
_reg(_metal("tungsten", 1.82e7))
# common PCB / RF laminates
_reg(_diel("fr4_epoxy", 4.4, 0.02, color="#2f7a3f"))
_reg(_diel("rogers_ro4003c", 3.55, 0.0027, color="#8a5a2b"))
_reg(_diel("rogers_ro4350b", 3.66, 0.0037, color="#8a5a2b"))
_reg(_diel("rogers_rt5880", 2.20, 0.0009, color="#d9d2c4"))
_reg(_diel("rogers_rt6010", 10.2, 0.0023))
_reg(_diel("taconic_tly5", 2.20, 0.0009))
_reg(_diel("isola_i_tera_mt40", 3.45, 0.0031))
_reg(_diel("alumina_96", 9.4, 0.0006, color="#efe7dd"))
_reg(_diel("alumina_99_5", 9.8, 0.0003))
_reg(_diel("sapphire", 9.4, 0.0001))
_reg(_diel("quartz_fused", 3.78, 0.0001))
_reg(_diel("silicon", 11.9, 0.005, color="#4b4b55"))
_reg(_diel("gaas", 12.9, 0.0006))
_reg(_diel("teflon_ptfe", 2.1, 0.0002))
_reg(_diel("polyethylene", 2.25, 0.0004))
_reg(_diel("polyimide", 3.5, 0.008))
_reg(_diel("nylon", 3.0, 0.02))
_reg(_diel("glass_pyrex", 4.82, 0.0054))
_reg(_diel("water_distilled", 81.0, 0.0))
_reg(_diel("mylar", 3.2, 0.005))
_reg(_diel("abs_plastic", 2.9, 0.006))
_reg(_diel("ceramic_bariumtitanate", 1200.0, 0.03))
# ferrite (magnetic)
_reg(Material("ferrite_generic", ConstantTanD(12.0, 0.0), ConstantTanD(100.0, 0.02),
              kind="dielectric", color="#3a3a3a"))
# causal wideband FR-4
_reg(Material("fr4_djordjevic",
              DjordjevicSarkar(eps_r=4.4, tan_d=0.02, f_ref=1e9, f1=1e3, f2=1e12),
              ConstantTanD(1.0, 0.0), kind="dielectric", color="#2f7a3f"))
# Drude gold for optics (wp, gamma in rad/s)
_reg(Material("gold_drude_optical", Drude(eps_inf=9.0, wp=1.36e16, gamma=1.05e14),
              ConstantTanD(1.0, 0.0), kind="dielectric", color="#d4af37"))


class MaterialLibrary:
    """Registry with user-extension support; mirrors the usual material manager."""

    def __init__(self, base: Optional[Dict[str, Material]] = None):
        self._m: Dict[str, Material] = dict(base if base is not None else _LIB)

    @staticmethod
    def key(name: str) -> str:
        """
        The single normalisation every lookup and every insertion uses.

        ``add`` used to key on ``name.lower()`` while ``get`` also folded
        spaces and hyphens to underscores. Any material whose name contained
        either — and an Warps project is full of them, "Polyflon copper-clad
        ULTEM (tm)" among others — went in under one key and was looked up
        under another, so it could never be found again. That made
        ``materials.list`` raise for the whole library, which in turn aborted
        the sequence that opens a project: the model loaded and the viewport
        stayed empty.
        """
        return (str(name).strip().lower()
                .replace(" ", "_").replace("-", "_"))

    def __contains__(self, name: str) -> bool:
        return self.key(name) in self._m

    def __getitem__(self, name: str) -> Material:
        return self.get(name)

    def get(self, name: str) -> Material:
        key = self.key(name)
        if key in self._m:
            return self._m[key]
        raise KeyError(
            f"material {name!r} not found; available: {', '.join(sorted(self._m))[:400]}..."
        )

    def add(self, mat: Material, overwrite: bool = True) -> Material:
        key = self.key(mat.name)
        if key in self._m and not overwrite:
            raise KeyError(f"material {mat.name!r} already defined")
        self._m[key] = mat
        return mat

    def define(self, name: str, eps_r: float = 1.0, tan_d: float = 0.0,
               mu_r: float = 1.0, mu_tan_d: float = 0.0, sigma: float = 0.0,
               **kw) -> Material:
        """Convenience constructor for the common constant-parameter case."""
        return self.add(Material(name, ConstantTanD(eps_r, tan_d),
                                 ConstantTanD(mu_r, mu_tan_d), sigma=sigma, **kw))

    def names(self):
        return sorted(self._m)

    def __len__(self):
        return len(self._m)


LIBRARY = MaterialLibrary()

VACUUM = LIBRARY.get("vacuum")
AIR = LIBRARY.get("air")
PEC = LIBRARY.get("pec")
PMC = LIBRARY.get("pmc")
COPPER = LIBRARY.get("copper")


def resolve(m) -> Material:
    """Accept a Material, a name string, or None -> vacuum."""
    if m is None:
        return VACUUM
    if isinstance(m, Material):
        return m
    return LIBRARY.get(str(m))


__all__ = [
    "Dispersion", "ConstantTanD", "Debye", "Drude", "Lorentz",
    "DjordjevicSarkar", "Tabulated", "Material", "MaterialLibrary",
    "LIBRARY", "VACUUM", "AIR", "PEC", "PMC", "COPPER", "resolve",
]
