"""
HFSS design-variable expression evaluator.

Geometry in a real ``.aedt`` file is parametric: ``XSize='$width*2'``.  To
turn that into metres we need to resolve variables (project ``$vars`` and
design-local ones), evaluate the arithmetic, and attach the unit that survives
the expression.

The evaluator is a restricted AST walker -- only literals, names and the
arithmetic operators are allowed, so a malicious or malformed project file
cannot execute code.
"""
from __future__ import annotations

import ast
import math
import operator as op
import re
from typing import Any, Dict, Optional

from ...core.constants import to_si

# Any <number><unit> token, whatever the unit is. Matching only the units we
# knew about left everything else -- temperatures, powers, currents, the
# "20cel" every part in a desktop-written project carries -- as a bare
# "20cel" for Python's parser, which is a SyntaxError ("invalid decimal
# literal") and used to abort the whole project load.
_UNIT_RE = re.compile(
    r"(?<![A-Za-z_0-9.])(\d+\.?\d*(?:[eE][+-]?\d+)?)\s*"
    r"([A-Za-z_°][A-Za-z_0-9/°]*)(?![A-Za-z_0-9])")

_KIND = {
    "mm": "length", "cm": "length", "km": "length", "um": "length",
    "nm": "length", "mil": "length", "in": "length", "ft": "length",
    "m": "length", "meter": "length", "metre": "length",
    "ghz": "frequency", "mhz": "frequency", "khz": "frequency",
    "thz": "frequency", "hz": "frequency",
    "deg": "angle", "rad": "angle",
    "ns": "time", "ps": "time", "us": "time", "ms": "time", "s": "time",
    "ohm": "resistance", "s/m": "conductivity",
}

# Units outside the SI registry that still show up in project files. The value
# is the factor to the natural SI unit of that quantity; temperatures are
# offsets rather than factors and are handled separately.
_EXTRA_SCALE = {
    # power / level
    "w": 1.0, "mw": 1e-3, "kw": 1e3, "uw": 1e-6, "nw": 1e-9,
    "db": 1.0, "dbm": 1.0, "dbi": 1.0, "dbw": 1.0, "np": 1.0,
    # electrical
    "v": 1.0, "mv": 1e-3, "kv": 1e3, "uv": 1e-6,
    "a": 1.0, "ma": 1e-3, "ka": 1e3, "ua": 1e-6, "na": 1e-9,
    "f": 1.0, "mf": 1e-3, "uf": 1e-6, "nf": 1e-9, "pf": 1e-12, "ff": 1e-15,
    "h": 1.0, "mh": 1e-3, "uh": 1e-6, "nh": 1e-9, "ph": 1e-12,
    "uohm": 1e-6, "mohm": 1e-3, "kohm": 1e3, "megohm": 1e6, "gohm": 1e9,
    "siemens": 1.0, "sie": 1.0, "sie/m": 1.0, "mho": 1.0,
    "c": 1.0, "coulomb": 1.0,
    # mechanical / thermal / other
    "kg": 1.0, "g": 1e-3, "mg": 1e-6, "n": 1.0, "pa": 1.0, "kpa": 1e3,
    "j": 1.0, "kj": 1e3, "w/m_k": 1.0, "kg/m^3": 1.0,
    "per_meter": 1.0, "per_mm": 1e3, "1/m": 1.0,
    "min": 60.0, "hour": 3600.0, "sec": 1.0,
}

# Temperatures: (scale, offset) to kelvin.
_TEMPERATURE = {"cel": (1.0, 273.15), "c": (1.0, 273.15),
                "kel": (1.0, 0.0), "k": (1.0, 0.0),
                "fah": (5.0 / 9.0, 255.372222222),
                "f": (5.0 / 9.0, 255.372222222)}


class ExpressionError(ValueError):
    """An HFSS expression that could not be evaluated.

    A dedicated type so a caller can decide per property whether to fall back
    to a default -- which is what reading a project has to do, since one
    unreadable value must never cost the whole model.
    """

_OPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
    ast.Div: op.truediv, ast.Pow: op.pow, ast.Mod: op.mod,
    ast.USub: op.neg, ast.UAdd: op.pos,
}

_FUNCS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin,
    "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "sqrt": math.sqrt, "exp": math.exp, "ln": math.log, "log": math.log10,
    "abs": abs, "pi": lambda: math.pi, "min": min, "max": max,
    "pow": pow, "floor": math.floor, "ceil": math.ceil,
}


class VariableScope:
    """Project + design variables, resolved lazily with cycle detection."""

    def __init__(self, variables: Optional[Dict[str, str]] = None):
        self.raw: Dict[str, str] = dict(variables or {})
        self._cache: Dict[str, float] = {}
        self._active: set = set()

    def set(self, name: str, expr: Any) -> None:
        self.raw[name] = expr
        self._cache.pop(name, None)

    def value(self, name: str) -> float:
        if name in self._cache:
            return self._cache[name]
        if name not in self.raw:
            raise KeyError(f"unknown design variable {name!r}")
        if name in self._active:
            raise ValueError(f"circular variable definition involving {name!r}")
        self._active.add(name)
        try:
            v = evaluate(self.raw[name], self)
        finally:
            self._active.discard(name)
        self._cache[name] = v
        return v

    def __contains__(self, name):
        return name in self.raw

    def __repr__(self):
        return f"<VariableScope {len(self.raw)} variables>"


def evaluate(expr: Any, scope: Optional[VariableScope] = None,
             kind: str = "length") -> float:
    """
    Evaluate an HFSS expression to SI.

    ``"2*$w + 0.5mm"`` -> metres, ``"10GHz"`` -> hertz.
    """
    if isinstance(expr, (int, float)) and not isinstance(expr, bool):
        return float(expr)
    s = str(expr).strip().strip("'\"")
    if not s:
        return 0.0
    try:                                   # fast path: a bare quantity
        return to_si(s, kind)
    except Exception:
        pass
    s, unit_kind = _strip_units(s)
    s = s.replace("$", "V_").replace("%", "*0.01")
    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(
            f"cannot read the expression {str(expr)!r}: {exc.msg}") from exc
    try:
        val = _eval_node(tree.body, scope)
    except ExpressionError:
        raise
    except (KeyError, ValueError, ZeroDivisionError, TypeError,
            OverflowError) as exc:
        raise ExpressionError(
            f"cannot evaluate {str(expr)!r}: {exc}") from exc
    return float(val)


def _strip_units(s: str):
    """Convert every ``<number><unit>`` occurrence into its SI value."""
    kinds = []

    def repl(m):
        num, unit = m.group(1), m.group(2)
        low = unit.lower().lstrip("°")
        k = _KIND.get(low)
        if k is not None:
            kinds.append(k)
            try:
                return repr(to_si(f"{num}{unit}", k))
            except Exception:
                pass
        if low in _TEMPERATURE:
            scale, offset = _TEMPERATURE[low]
            kinds.append("temperature")
            return repr(float(num) * scale + offset)
        if low in _EXTRA_SCALE:
            kinds.append("other")
            return repr(float(num) * _EXTRA_SCALE[low])
        # An unknown unit is still a number with a suffix, not a syntax
        # error: take the number, note that the unit was not understood, and
        # let the caller decide whether that matters.
        kinds.append("unknown")
        _UNKNOWN_UNITS.add(unit)
        return repr(float(num))

    return _UNIT_RE.sub(repl, s), (kinds[0] if kinds else None)


def _eval_node(node, scope):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"unsupported constant {node.value!r}")
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.left, scope),
                                   _eval_node(node.right, scope))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.operand, scope))
    if isinstance(node, ast.Name):
        name = node.id
        if name in _FUNCS and name == "pi":
            return math.pi
        real = name[2:] if name.startswith("V_") else name
        for cand in (real, "$" + real, name):
            if scope is not None and cand in scope:
                return scope.value(cand)
        if name.lower() == "pi":
            return math.pi
        raise KeyError(f"unknown variable {real!r} in expression")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = _FUNCS.get(node.func.id.lower())
        if fn is None:
            raise ValueError(f"unsupported function {node.func.id!r}")
        return fn(*[_eval_node(a, scope) for a in node.args])
    raise ValueError(f"unsupported expression element {type(node).__name__}")


_UNKNOWN_UNITS: set = set()

__all__ = ["VariableScope", "evaluate", "ExpressionError"]
