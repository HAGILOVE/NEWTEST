"""
Physical constants and unit handling (CODATA-2018 exact SI definitions).

All internal computation in Aether-EM is performed in **strict SI base units**
(metre, second, kilogram, ampere).  User-facing APIs accept unit-tagged
strings ("2.54mm", "10 GHz") which are converted here exactly once, at the
model boundary.  This is the same discipline Warps enforces with its
"model units" concept, but resolved eagerly instead of lazily so that no
downstream kernel ever has to know about units.
"""
from __future__ import annotations

import math
import re
from typing import Union

# --------------------------------------------------------------------------
# CODATA / SI (2019 redefinition -- c, mu0 no longer exactly 4pi e-7)
# --------------------------------------------------------------------------
c0: float = 299_792_458.0                       # speed of light in vacuum [m/s] (exact)
mu0: float = 1.25663706212e-6                   # vacuum permeability [H/m]
eps0: float = 1.0 / (mu0 * c0 * c0)             # vacuum permittivity [F/m]
eta0: float = math.sqrt(mu0 / eps0)             # free-space wave impedance ~376.730 Ohm
Z0_FREESPACE: float = eta0

e_charge: float = 1.602176634e-19               # elementary charge [C] (exact)
k_B: float = 1.380649e-23                       # Boltzmann [J/K] (exact)
h_planck: float = 6.62607015e-34                # Planck [J s] (exact)
T0_KELVIN: float = 293.15                       # standard ambient temperature

DEG = math.pi / 180.0
RAD = 180.0 / math.pi

# --------------------------------------------------------------------------
# Unit registry
# --------------------------------------------------------------------------
_LENGTH = {
    "m": 1.0, "meter": 1.0, "metre": 1.0,
    "dm": 1e-1, "cm": 1e-2, "mm": 1e-3, "um": 1e-6, "µm": 1e-6, "micron": 1e-6,
    "nm": 1e-9, "pm": 1e-12,
    "km": 1e3,
    "mil": 2.54e-5, "in": 2.54e-2, "inch": 2.54e-2, "ft": 0.3048, "feet": 0.3048,
    "yd": 0.9144, "mi": 1609.344,
}
_FREQ = {
    "hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9, "thz": 1e12, "phz": 1e15,
}
_TIME = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9, "ps": 1e-12, "fs": 1e-15}
_ANGLE = {"rad": 1.0, "deg": DEG, "degree": DEG, "degrees": DEG, "°": DEG}
_RES = {"ohm": 1.0, "kohm": 1e3, "mohm": 1e-3, "megohm": 1e6, "Ω": 1.0}
_COND = {"s/m": 1.0, "siemens/m": 1.0, "ms/m": 1e-3, "ks/m": 1e3, "msiem/m": 1e6}

_REGISTRY = {
    "length": _LENGTH, "frequency": _FREQ, "time": _TIME,
    "angle": _ANGLE, "resistance": _RES, "conductivity": _COND,
}

_NUM_RE = re.compile(
    r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Zµ°Ω/]*)\s*$"
)

Quantity = Union[str, int, float]


class UnitError(ValueError):
    """Raised when a unit-tagged string cannot be resolved."""


def to_si(value: Quantity, kind: str = "length", default_unit: str | None = None) -> float:
    """
    Convert *value* to SI.

    Parameters
    ----------
    value : str | float
        Either a bare number (assumed already SI, or in ``default_unit``)
        or a unit-tagged string such as ``"2.54 mm"`` / ``"10GHz"``.
    kind : str
        One of ``length, frequency, time, angle, resistance, conductivity``.
    default_unit : str, optional
        Unit assumed when *value* carries none.

    Examples
    --------
    >>> to_si("2.54mm")
    0.00254
    >>> round(to_si("10 GHz", "frequency"))
    10000000000
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
        if default_unit:
            return v * _lookup(kind, default_unit)
        return v
    if not isinstance(value, str):
        raise UnitError(f"cannot interpret {value!r} as a {kind} quantity")
    m = _NUM_RE.match(value)
    if not m:
        raise UnitError(f"malformed quantity string {value!r}")
    num, unit = float(m.group(1)), m.group(2)
    if not unit:
        unit = default_unit or _base_unit(kind)
    return num * _lookup(kind, unit)


def _base_unit(kind: str) -> str:
    return {"length": "m", "frequency": "hz", "time": "s",
            "angle": "rad", "resistance": "ohm", "conductivity": "s/m"}[kind]


def _lookup(kind: str, unit: str) -> float:
    try:
        table = _REGISTRY[kind]
    except KeyError as exc:  # pragma: no cover - programmer error
        raise UnitError(f"unknown quantity kind {kind!r}") from exc
    key = unit.strip()
    if key in table:
        return table[key]
    if key.lower() in table:
        return table[key.lower()]
    raise UnitError(f"unknown {kind} unit {unit!r}")


def from_si(value: float, unit: str, kind: str = "length") -> float:
    """Inverse of :func:`to_si` -- express an SI value in *unit*."""
    return value / _lookup(kind, unit)


def wavelength(freq_hz: float, eps_r: float = 1.0, mu_r: float = 1.0) -> float:
    """Wavelength [m] in a medium at *freq_hz*."""
    return c0 / (freq_hz * math.sqrt(eps_r * mu_r))


def k0(freq_hz: float) -> float:
    """Free-space wavenumber [rad/m]."""
    return 2.0 * math.pi * freq_hz / c0


def omega(freq_hz: float) -> float:
    """Angular frequency [rad/s]."""
    return 2.0 * math.pi * freq_hz


def skin_depth(freq_hz: float, sigma: float, mu_r: float = 1.0) -> float:
    """Classical skin depth  delta = sqrt(2/(w mu sigma))  [m]."""
    if sigma <= 0.0:
        return math.inf
    return math.sqrt(2.0 / (omega(freq_hz) * mu0 * mu_r * sigma))


def surface_impedance(freq_hz: float, sigma: float, mu_r: float = 1.0) -> complex:
    """
    Good-conductor surface impedance  Zs = (1+j)/(sigma*delta)  [Ohm/sq].

    This is the Leontovich impedance boundary condition used for finite
    conductivity metals; valid while delta << geometric feature size.
    """
    if sigma <= 0.0:
        return 0.0 + 0.0j
    d = skin_depth(freq_hz, sigma, mu_r)
    rs = 1.0 / (sigma * d)
    return complex(rs, rs)


__all__ = [
    "c0", "mu0", "eps0", "eta0", "Z0_FREESPACE", "e_charge", "k_B", "h_planck",
    "T0_KELVIN", "DEG", "RAD", "UnitError", "Quantity",
    "to_si", "from_si", "wavelength", "k0", "omega", "skin_depth",
    "surface_impedance",
]
