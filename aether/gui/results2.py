"""
Post-processing from the HFSS 100 Tips book: output variables / expression
traces (the inductance of a pad as 1e9*im(Z(1,1))/2/pi/Freq, say) and the
field along a line.
"""
from __future__ import annotations

import ast
import math
from typing import Any, Dict, List, Optional

import numpy as np

from ..core.constants import to_si

_FUNCS = {
    "re": lambda a: np.real(a), "im": lambda a: np.imag(a),
    "abs": lambda a: np.abs(a), "mag": lambda a: np.abs(a),
    "db": lambda a: 20 * np.log10(np.maximum(np.abs(a), 1e-300)),
    "db10": lambda a: 10 * np.log10(np.maximum(np.abs(a), 1e-300)),
    "ang_deg": lambda a: np.degrees(np.angle(a)), "ang_rad": lambda a: np.angle(a),
    "unwrap_deg": lambda a: np.degrees(np.unwrap(np.angle(a))),
    "conj": np.conj, "sqrt": np.sqrt, "exp": np.exp, "ln": np.log, "log10": np.log10,
    "sin": np.sin, "cos": np.cos, "tan": np.tan, "atan": np.arctan,
    "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
}


class ExpressionError(ValueError):
    pass


class Calculator:
    """Evaluate output-variable expressions over a solved design's S / Y / Z data."""

    def __init__(self, sp, variables: Optional[Dict[str, str]] = None):
        self.sp = sp
        self.variables = dict(variables or {})
        self._z = self._y = None
        self._cache: Dict[str, Any] = {}
        self._active: List[str] = []

    # matrices are computed once and only when asked for
    def _mat(self, which):
        if which == "S":
            return self.sp.s
        if which == "Z":
            if self._z is None:
                self._z = self.sp.to_z()
            return self._z
        if self._y is None:
            self._y = self.sp.to_y()
        return self._y

    def evaluate(self, text: str):
        text = str(text).strip()
        if not text or len(text) > 400:
            raise ExpressionError("an expression has 1 to 400 characters")
        try:
            node = ast.parse(text, mode="eval")
        except SyntaxError as e:
            raise ExpressionError(f"cannot read the expression: {text}") from e
        if sum(1 for _ in ast.walk(node)) > 200:
            raise ExpressionError("the expression is too complex")
        return np.asarray(self._node(node.body))

    def _port(self, n):
        if not isinstance(n, ast.Constant) or not isinstance(n.value, int):
            raise ExpressionError("port numbers are whole numbers, as in S(1,2)")
        i = int(n.value)
        if not 1 <= i <= self.sp.n_port:
            raise ExpressionError(f"there is no port {i} (1 to {self.sp.n_port})")
        return i - 1

    def _node(self, n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float, complex)) \
                and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.Name):
            nm = n.id
            if nm == "Freq":
                return np.asarray(self.sp.freq, float)
            if nm == "pi":
                return math.pi
            if nm in ("j", "i"):
                return 1j
            if nm in self.variables:
                if nm in self._active or len(self._active) > 12:
                    raise ExpressionError(f"the variable {nm} refers to itself")
                if nm not in self._cache:
                    self._active.append(nm)
                    try:
                        self._cache[nm] = self.evaluate(self.variables[nm])
                    finally:
                        self._active.pop()
                return self._cache[nm]
            raise ExpressionError(f"unknown name {nm!r} (Freq, pi, j, S(i,j), Y(i,j), Z(i,j), or an output variable)")
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            v = self._node(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp):
            a, b = self._node(n.left), self._node(n.right)
            with np.errstate(all="ignore"):
                if isinstance(n.op, ast.Add):
                    return a + b
                if isinstance(n.op, ast.Sub):
                    return a - b
                if isinstance(n.op, ast.Mult):
                    return a * b
                if isinstance(n.op, ast.Div):
                    return a / b
                if isinstance(n.op, ast.Pow):
                    return np.power(a, b)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and not n.keywords:
            f = n.func.id
            if f in ("S", "Y", "Z") and len(n.args) == 2:
                m = self._mat(f)
                return m[:, self._port(n.args[0]), self._port(n.args[1])]
            if f == "Z0" and len(n.args) == 1:
                return np.asarray(self.sp.z0[:, self._port(n.args[0])])
            if f in _FUNCS and len(n.args) == 1:
                return _FUNCS[f](self._node(n.args[0]))
            if f == "atan2" and len(n.args) == 2:
                return np.arctan2(self._node(n.args[0]), self._node(n.args[1]))
            if f in ("min", "max") and len(n.args) == 2:
                return (np.minimum if f == "min" else np.maximum)(self._node(n.args[0]), self._node(n.args[1]))
        raise ExpressionError("unsupported expression; use + - * / ^ ( ), Freq, S(i,j) Y(i,j) Z(i,j), "
                              "re im abs db ang_deg sqrt exp ln log10 sin cos tan atan")


def register(command) -> None:
    from . import api

    @command("results.variables")
    def _variables(s, **_):
        d = s.require_design()
        return {"variables": [{"name": k, "expression": v} for k, v in d.output_variables.items()]}

    @command("results.setVariables")
    def _set_variables(s, variables: Optional[dict] = None, **_):
        """Output variables: name -> expression, replacing the list."""
        d = s.require_design()
        new: Dict[str, str] = {}
        for k, v in (variables or {}).items():
            k = str(k).strip()
            if not k.replace("_", "a").isalnum() or k[0].isdigit() or k in ("Freq", "pi", "j", "i", "S", "Y", "Z"):
                raise ValueError(f"{k!r} is not a usable variable name")
            new[k] = str(v).strip()
        d.output_variables = new
        s.dirty = True
        return {"ok": True, "count": len(new)}

    @command("results.expression")
    def _expression(s, exprs: Optional[list] = None, **_):
        """Evaluate expressions of the S / Y / Z data against frequency."""
        if s.solution is None or s.solution.sparams is None:
            raise RuntimeError("no S-parameter solution yet")
        sp = s.solution.sparams
        calc = Calculator(sp, getattr(s.design, "output_variables", {}))
        traces = []
        for t in exprs or []:
            text = t.get("expr") or t.get("expression") or ""
            label = t.get("name") or text
            y = calc.evaluate(text)
            if y.ndim == 0:
                y = np.full(len(sp.freq), y)
            y = np.broadcast_to(y, (len(sp.freq),))
            traces.append({"label": label, "expr": text,
                           "y": [float(v) for v in np.real(y)],
                           "im": [float(v) for v in np.imag(y)],
                           "complex": bool(np.iscomplexobj(y) and np.abs(np.imag(y)).max() > 1e-30)})
        if not traces:
            raise ValueError("give at least one expression")
        return {"freq": [float(f) for f in sp.freq], "traces": traces}

    @command("results.fieldOnLine")
    def _field_on_line(s, start=None, end=None, points: int = 101, quantity: str = "E",
                       freq: Optional[float] = None, excitation: int = 0, phase: Any = None, **_):
        """The field along a straight line through the solved volume."""
        from ..post.fieldview import locate_points
        if s.solution is None or not s.solution.fields:
            raise RuntimeError("no field data — analyse with 'save fields' enabled")
        if quantity not in ("E", "H"):
            raise ValueError("a line plot is of E or H (the surface current lives on conductors)")
        if start is None or end is None or len(start) != 3 or len(end) != 3:
            raise ValueError("give the start and the end of the line (X, Y, Z)")
        p0 = np.array([to_si(x) if isinstance(x, str) else float(x) for x in start], float)
        p1 = np.array([to_si(x) if isinstance(x, str) else float(x) for x in end], float)
        L = float(np.linalg.norm(p1 - p0))
        if L <= 0:
            raise ValueError("the two points are the same")
        n = max(2, min(int(points), 5001))
        sol = s.solution
        f = float(freq) if freq is not None else float(sol.freqs[-1])
        fs = sol.field(f, int(excitation))
        t = np.linspace(0.0, 1.0, n)
        P = p0 + np.outer(t, p1 - p0)
        tet, inside = locate_points(sol.mesh, P)
        E, H = fs.eval_at(tet, P)
        F = E if quantity == "E" else H
        F = np.where(inside[:, None], F, 0.0)
        out = {"distance": [float(v) for v in t * L], "points": P.tolist(), "inside": [bool(v) for v in inside],
               "frequency": f, "quantity": quantity, "length": L,
               "mag": [float(v) for v in np.linalg.norm(np.abs(F), axis=1) if True],
               "x": [float(abs(v)) for v in F[:, 0]], "y": [float(abs(v)) for v in F[:, 1]],
               "z": [float(abs(v)) for v in F[:, 2]]}
        # |E| is the vector magnitude of the complex phasor
        out["mag"] = [float(v) for v in np.sqrt(np.sum(np.abs(F) ** 2, axis=1))]
        if phase not in (None, ""):
            ph = np.exp(1j * math.radians(float(phase)))
            out["instant"] = {k: [float(v) for v in np.real(F[:, i] * ph)] for i, k in enumerate("xyz")}
        if not bool(np.all(inside)):
            s.messages.add(f"{int((~inside).sum())} of {n} points on the line are outside the meshed volume "
                           "(shown as zero).", "warning", "results")
        return out
