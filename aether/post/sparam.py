"""
Network-parameter container and conversions.

Holds a frequency-indexed S-matrix with a (possibly complex, possibly
frequency-dependent) reference impedance per port, and provides the standard
conversions and checks a microwave engineer expects: S <-> Z <-> Y <-> ABCD,
impedance renormalisation, de-embedding, passivity/reciprocity tests, group
delay, VSWR, and mixed-mode (differential) transformation.
"""
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import numpy as np


@dataclass
class SParameters:
    """S-matrix of shape ``(n_freq, n_port, n_port)``."""
    freq: np.ndarray
    s: np.ndarray
    z0: np.ndarray                    # (n_freq, n_port) complex
    port_names: List[str] = field(default_factory=list)
    comments: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.freq = np.atleast_1d(np.asarray(self.freq, float))
        self.s = np.asarray(self.s, complex)
        if self.s.ndim == 2:
            self.s = self.s[None, :, :]
        n = self.s.shape[1]
        z0 = np.asarray(self.z0, complex)
        if z0.ndim == 0:
            z0 = np.full((len(self.freq), n), z0)
        elif z0.ndim == 1:
            z0 = np.tile(z0, (len(self.freq), 1))
        self.z0 = z0
        if not self.port_names:
            self.port_names = [f"P{i+1}" for i in range(n)]

    # ----------------------------------------------------------- basics
    @property
    def n_port(self) -> int:
        return self.s.shape[1]

    @property
    def n_freq(self) -> int:
        return self.s.shape[0]

    def __getitem__(self, key):
        return self.s[key]

    def sij(self, i: int, j: int) -> np.ndarray:
        """1-based port indexing, like every VNA on earth."""
        return self.s[:, i - 1, j - 1]

    def db(self, i: int, j: int) -> np.ndarray:
        return 20.0 * np.log10(np.maximum(np.abs(self.sij(i, j)), 1e-300))

    def deg(self, i: int, j: int) -> np.ndarray:
        return np.degrees(np.angle(self.sij(i, j)))

    def unwrapped_deg(self, i: int, j: int) -> np.ndarray:
        return np.degrees(np.unwrap(np.angle(self.sij(i, j))))

    def vswr(self, i: int) -> np.ndarray:
        g = np.abs(self.sij(i, i))
        return (1 + g) / np.maximum(1 - g, 1e-300)

    def group_delay(self, i: int, j: int) -> np.ndarray:
        """-d(phase)/d(omega) in seconds."""
        if len(self.freq) < 2:
            raise ValueError("Group delay requires at least two frequency samples")
        if np.any(np.diff(self.freq) <= 0):
            raise ValueError("Group delay requires strictly increasing frequency samples")
        ph = np.unwrap(np.angle(self.sij(i, j)))
        w = 2 * np.pi * self.freq
        return -np.gradient(ph, w)

    # ------------------------------------------------------- conversions
    def to_z(self) -> np.ndarray:
        """Impedance matrix (generalised, complex reference impedances)."""
        n = self.n_port
        I = np.eye(n)
        out = np.empty_like(self.s)
        for k in range(self.n_freq):
            z0 = self.z0[k]
            sq = np.diag(np.sqrt(z0))
            S = self.s[k]
            out[k] = sq @ np.linalg.solve(I - S, I + S) @ sq
        return out

    def to_y(self) -> np.ndarray:
        """
        Admittance matrix, computed **directly** from S.

        Going through Z and inverting fails for common networks -- a series
        element has a singular Z-matrix -- so Y is formed as
        ``Y = sq^-1 (I - S)(I + S)^-1 sq^-1`` instead, which stays
        well-conditioned exactly where the Z route breaks down.
        """
        n = self.n_port
        I = np.eye(n)
        out = np.empty_like(self.s)
        for k in range(self.n_freq):
            isq = np.diag(1.0 / np.sqrt(self.z0[k]))
            S = self.s[k]
            out[k] = isq @ (I - S) @ np.linalg.inv(I + S) @ isq
        return out

    def to_abcd(self) -> np.ndarray:
        """Two-port ABCD from S (requires n_port == 2)."""
        if self.n_port != 2:
            raise ValueError("ABCD is defined for two-ports only")
        out = np.empty((self.n_freq, 2, 2), complex)
        for k in range(self.n_freq):
            S = self.s[k]
            z01, z02 = self.z0[k]
            s11, s12, s21, s22 = S[0, 0], S[0, 1], S[1, 0], S[1, 1]
            z1, z2 = z01, z02
            den = 2 * s21
            out[k, 0, 0] = ((1 + s11) * (1 - s22) + s12 * s21) / den
            out[k, 0, 1] = z2 * ((1 + s11) * (1 + s22) - s12 * s21) / den
            out[k, 1, 0] = ((1 - s11) * (1 - s22) - s12 * s21) / (den * z1)
            out[k, 1, 1] = ((1 - s11) * (1 + s22) + s12 * s21) / den
        return out

    @classmethod
    def from_z(cls, freq, z, z0=50.0, port_names=None) -> "SParameters":
        z = np.asarray(z, complex)
        n = z.shape[1]
        z0a = np.full((len(freq), n), z0, dtype=complex) if np.ndim(z0) == 0 \
            else np.asarray(z0, complex)
        s = np.empty_like(z)
        for k in range(len(freq)):
            sq = np.diag(np.sqrt(z0a[k]))
            isq = np.linalg.inv(sq)
            Zn = isq @ z[k] @ isq
            I = np.eye(n)
            s[k] = np.linalg.solve(Zn + I, Zn - I)
        return cls(freq, s, z0a, port_names or [])

    # ---------------------------------------------------- renormalisation
    def renormalize(self, z_new) -> "SParameters":
        """
        Change the reference impedance (power-wave definition, complex-safe).

            S' = A^-1 (S - G*) (I - G S)^-1 A*
        """
        n = self.n_port
        zn = np.asarray(z_new, complex)
        if zn.ndim == 0:
            zn = np.full((self.n_freq, n), zn)
        elif zn.ndim == 1:
            zn = np.tile(zn, (self.n_freq, 1))
        out = np.empty_like(self.s)
        I = np.eye(n)
        for k in range(self.n_freq):
            z_old, z_new_k = self.z0[k], zn[k]
            g = (z_new_k - z_old) / (z_new_k + z_old)
            G = np.diag(g)
            A = np.diag(np.sqrt(1 - np.abs(g) ** 2)
                        * (1 - g.conjugate()) / np.abs(1 - g))
            S = self.s[k]
            out[k] = np.linalg.inv(A) @ (S - np.conj(G)) \
                @ np.linalg.inv(I - G @ S) @ np.conj(A)
        return SParameters(self.freq, out, zn, list(self.port_names),
                           list(self.comments))

    def deembed(self, gamma: np.ndarray, length: Sequence[float]) -> "SParameters":
        """Shift each port reference plane by ``length[i]`` along ``gamma[:, i]``."""
        g = np.asarray(gamma, complex)
        L = np.asarray(length, float)
        out = self.s.copy()
        for k in range(self.n_freq):
            ph = np.exp(g[k] * L)
            out[k] = np.outer(ph, ph) * self.s[k]
        return SParameters(self.freq, out, self.z0, list(self.port_names),
                           list(self.comments))

    # ------------------------------------------------------------ checks
    def passivity(self) -> np.ndarray:
        """Largest singular value of S at each frequency (<= 1 if passive)."""
        return np.array([np.linalg.svd(self.s[k], compute_uv=False).max()
                         for k in range(self.n_freq)])

    def is_passive(self, tol: float = 1e-6) -> bool:
        return bool(np.all(self.passivity() <= 1.0 + tol))

    def reciprocity_error(self) -> np.ndarray:
        return np.array([np.max(np.abs(self.s[k] - self.s[k].T))
                         for k in range(self.n_freq)])

    def is_reciprocal(self, tol: float = 1e-4) -> bool:
        return bool(np.all(self.reciprocity_error() <= tol))

    def energy_error(self) -> np.ndarray:
        """``1 - sum|S|^2`` per column: the fraction of power not accounted for."""
        return 1.0 - np.sum(np.abs(self.s) ** 2, axis=1)

    # -------------------------------------------------------- mixed mode
    def to_mixed_mode(self, pairs: Sequence[Sequence[int]]) -> "SParameters":
        """
        Single-ended -> differential/common transformation.

        ``pairs`` lists 1-based ``(p, n)`` port pairs; the result is ordered
        ``[dd..., dc..., cd..., cc...]`` in the usual 2N x 2N block layout.
        """
        npair = len(pairs)
        n = self.n_port
        M = np.zeros((2 * npair, n))
        for i, (p, m) in enumerate(pairs):
            M[i, p - 1] = 1 / math.sqrt(2)
            M[i, m - 1] = -1 / math.sqrt(2)
            M[npair + i, p - 1] = 1 / math.sqrt(2)
            M[npair + i, m - 1] = 1 / math.sqrt(2)
        out = np.einsum("ij,kjl,ml->kim", M, self.s, M)
        names = [f"D{i+1}" for i in range(npair)] + [f"C{i+1}" for i in range(npair)]
        z0 = np.tile(self.z0[:, :1], (1, 2 * npair))
        return SParameters(self.freq, out, z0, names, list(self.comments))

    # -------------------------------------------------------------- misc
    def subset(self, ports: Sequence[int]) -> "SParameters":
        idx = [p - 1 for p in ports]
        return SParameters(self.freq, self.s[:, idx][:, :, idx],
                           self.z0[:, idx],
                           [self.port_names[i] for i in idx],
                           list(self.comments))

    def at(self, f: float) -> np.ndarray:
        """Linearly interpolated S-matrix at an arbitrary frequency."""
        if f <= self.freq[0]:
            return self.s[0]
        if f >= self.freq[-1]:
            return self.s[-1]
        i = int(np.searchsorted(self.freq, f)) - 1
        t = (f - self.freq[i]) / (self.freq[i + 1] - self.freq[i])
        return self.s[i] * (1 - t) + self.s[i + 1] * t

    def write_touchstone(self, path: str, **kw) -> str:
        from ..io.touchstone import write_touchstone
        return write_touchstone(path, self, **kw)

    def to_csv(self, path: str) -> str:
        from ..io.csv_io import write_sparam_csv
        return write_sparam_csv(path, self)

    def summary(self) -> str:
        lines = [f"S-parameters: {self.n_port} ports x {self.n_freq} frequencies "
                 f"({self.freq[0]/1e9:.4g} - {self.freq[-1]/1e9:.4g} GHz)"]
        for i in range(1, self.n_port + 1):
            for j in range(1, self.n_port + 1):
                d = self.db(i, j)
                lines.append(f"  S{i}{j}: {d.min():8.3f} .. {d.max():8.3f} dB")
        p = self.passivity()
        lines.append(f"  max singular value = {p.max():.6f} "
                     f"({'passive' if p.max() <= 1 + 1e-6 else 'NOT passive'})")
        return "\n".join(lines)

    def __repr__(self):
        return (f"<SParameters {self.n_port}-port, {self.n_freq} points, "
                f"{self.freq[0]/1e9:.3g}-{self.freq[-1]/1e9:.3g} GHz>")


__all__ = ["SParameters"]
