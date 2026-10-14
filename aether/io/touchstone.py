"""
Touchstone (``.sNp`` / ``.ts``) reader and writer -- versions 1.0 and 2.0.

The awkward corners are handled, because they are exactly where other readers
break:

* the **two-port transposition**: a v1 ``.s2p`` file stores
  ``S11 S21 S12 S22`` -- the only size where the order is column-major.  Every
  other port count is row-major.  Getting this wrong silently swaps S12/S21.
* line wrapping: v1 splits each frequency record over several lines
  (conventionally four complex pairs per line) with no continuation marker,
  so records must be reassembled by counting values, not lines.
* all three data formats (``RI``, ``MA``, ``DB``), all frequency units, and
  per-port reference impedances via the v2 ``[Reference]`` keyword.
* ``!`` comments anywhere, including trailing on a data line.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from ..core.logging import get_logger
from ..post.sparam import SParameters

log = get_logger("io.touchstone")

FREQ_UNITS = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9, "thz": 1e12}
_SNP_RE = re.compile(r"\.s(\d+)p$", re.I)


class TouchstoneError(ValueError):
    pass


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------


def read_touchstone(path: str) -> SParameters:
    """Load a Touchstone file into :class:`~aether.post.sparam.SParameters`."""
    with open(path, "r", errors="replace") as fh:
        raw = fh.read()
    return parse_touchstone(raw, path)


def parse_touchstone(text: str, path: str = "") -> SParameters:
    lines = text.splitlines()
    comments: List[str] = []
    unit, param, fmt, r_ref = 1e9, "S", "MA", 50.0
    version = 1.0
    n_port_hint = 0
    m = _SNP_RE.search(path or "")
    if m:
        n_port_hint = int(m.group(1))

    data: List[float] = []
    refs: Optional[List[float]] = None
    in_network = True
    i = 0
    pending_ref = False
    while i < len(lines):
        ln = lines[i]
        i += 1
        if "!" in ln:
            head, _, tail = ln.partition("!")
            if tail.strip():
                comments.append(tail.strip())
            ln = head
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            unit, param, fmt, r_ref = _parse_option(s)
            continue
        if s.startswith("["):
            kw = s.split("]")[0][1:].strip().lower()
            rest = s.split("]", 1)[1].strip()
            if kw == "version":
                version = float(rest or 2.0)
            elif kw == "number of ports":
                n_port_hint = int(float(rest))
            elif kw == "reference":
                refs = [float(x) for x in rest.split()] if rest else []
                pending_ref = not rest
            elif kw == "network data":
                in_network = True
            elif kw in ("end", "noise data", "end information"):
                in_network = kw == "end"
            continue
        if pending_ref:
            try:
                refs = (refs or []) + [float(x) for x in s.split()]
                if n_port_hint and len(refs) >= n_port_hint:
                    pending_ref = False
                continue
            except ValueError:
                pending_ref = False
        if not in_network:
            continue
        try:
            data.extend(float(x) for x in s.split())
        except ValueError:
            continue

    if not data:
        raise TouchstoneError(f"{path}: no numeric network data found")

    n = n_port_hint or _infer_ports(len(data))
    per = 1 + 2 * n * n
    if len(data) % per:
        raise TouchstoneError(
            f"{path}: {len(data)} numbers is not a multiple of "
            f"{per} (1 frequency + {n*n} complex entries for {n} ports)")
    arr = np.asarray(data, float).reshape(-1, per)
    freq = arr[:, 0] * unit
    vals = arr[:, 1:].reshape(len(arr), n * n, 2)
    s = _to_complex(vals, fmt).reshape(len(arr), n, n)
    if n == 2 and version < 2.0:
        s = np.transpose(s, (0, 2, 1))            # v1 .s2p is column-major
    z0 = np.array(refs if refs else [r_ref] * n, float)
    if len(z0) != n:
        z0 = np.full(n, r_ref)
    sp = SParameters(freq, s, np.tile(z0, (len(freq), 1)),
                     [f"P{i+1}" for i in range(n)], comments)
    if param.upper() != "S":
        log.warning("%s carries %s-parameters; converting is left to the "
                    "caller", path, param)
    return sp


def _parse_option(s: str) -> Tuple[float, str, str, float]:
    toks = s[1:].split()
    unit, param, fmt, r = 1e9, "S", "MA", 50.0
    k = 0
    while k < len(toks):
        t = toks[k].lower()
        if t in FREQ_UNITS:
            unit = FREQ_UNITS[t]
        elif t in ("s", "y", "z", "h", "g"):
            param = t.upper()
        elif t in ("ri", "ma", "db"):
            fmt = t.upper()
        elif t == "r" and k + 1 < len(toks):
            r = float(toks[k + 1])
            k += 1
        k += 1
    return unit, param, fmt, r


def _infer_ports(count: int) -> int:
    for n in range(1, 100):
        per = 1 + 2 * n * n
        if count % per == 0:
            return n
    raise TouchstoneError("cannot infer the port count from the data length")


def _to_complex(v: np.ndarray, fmt: str) -> np.ndarray:
    a, b = v[..., 0], v[..., 1]
    f = fmt.upper()
    if f == "RI":
        return a + 1j * b
    if f == "MA":
        return a * np.exp(1j * np.radians(b))
    if f == "DB":
        return (10.0 ** (a / 20.0)) * np.exp(1j * np.radians(b))
    raise TouchstoneError(f"unknown data format {fmt!r}")


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------


def write_touchstone(path: str, sp: SParameters, fmt: str = "RI",
                     unit: str = "GHz", version: float = 1.0,
                     precision: int = 12,
                     comments: Optional[Sequence[str]] = None) -> str:
    """
    Write *sp* to Touchstone.

    ``version=1.0`` produces a classic ``.sNp``; ``version=2.0`` produces a
    ``.ts`` with ``[Reference]``, which is the only way to store per-port or
    complex reference impedances honestly.
    """
    n = sp.n_port
    u = unit.lower()
    if u not in FREQ_UNITS:
        raise TouchstoneError(f"unknown frequency unit {unit!r}")
    scale = FREQ_UNITS[u]
    z0 = sp.z0[0]
    varies = not np.allclose(sp.z0, z0[None, :])
    if varies and version < 2.0:
        log.warning("reference impedance varies with frequency; Touchstone 1.0 "
                    "cannot express that -- writing the first-point value")
    lines: List[str] = []
    lines.append(f"! Touchstone file written by Aether-EM")
    lines.append(f"! {n}-port S-parameters, {sp.n_freq} frequency points")
    for c in (comments or sp.comments):
        lines.append(f"! {c}")
    if version >= 2.0:
        lines.append("[Version] 2.0")
    r_default = float(np.real(z0[0]))
    lines.append(f"# {unit} S {fmt.upper()} R {_g(r_default, 6)}")
    if version >= 2.0:
        lines.append(f"[Number of Ports] {n}")
        lines.append("[Reference] " + " ".join(_g(float(np.real(v)), 6)
                                               for v in z0))
        lines.append("[Network Data]")

    p = f"{{:.{precision}g}}"
    for k in range(sp.n_freq):
        S = sp.s[k]
        if n == 2 and version < 2.0:
            order = [(0, 0), (1, 0), (0, 1), (1, 1)]
        else:
            order = [(i, j) for i in range(n) for j in range(n)]
        vals = []
        for i, j in order:
            vals.extend(_from_complex(S[i, j], fmt))
        row = [p.format(sp.freq[k] / scale)]
        if n <= 2:
            row += [p.format(v) for v in vals]
            lines.append(" ".join(row))
        else:
            # one matrix row per output line (the conventional layout)
            per_line = 2 * n
            first = row + [p.format(v) for v in vals[:per_line]]
            lines.append(" ".join(first))
            for c in range(per_line, len(vals), per_line):
                lines.append(" " * 10 + " ".join(
                    p.format(v) for v in vals[c:c + per_line]))
    if version >= 2.0:
        lines.append("[End]")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    log.info("wrote %s (%d ports, %d points)", path, n, sp.n_freq)
    return path


def _from_complex(z: complex, fmt: str):
    f = fmt.upper()
    if f == "RI":
        return [z.real, z.imag]
    mag = abs(z)
    ang = math.degrees(math.atan2(z.imag, z.real))
    if f == "MA":
        return [mag, ang]
    if f == "DB":
        return [20.0 * math.log10(max(mag, 1e-300)), ang]
    raise TouchstoneError(f"unknown data format {fmt!r}")


def _g(x: float, p: int) -> str:
    return f"{x:.{p}g}"


def default_extension(n_port: int, version: float = 1.0) -> str:
    return ".ts" if version >= 2.0 else f".s{n_port}p"


__all__ = ["read_touchstone", "write_touchstone", "parse_touchstone",
           "TouchstoneError", "default_extension"]
