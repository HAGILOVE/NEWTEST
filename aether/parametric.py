"""Dimension-checked expressions and persistent primitive parameter bindings.

This deliberately does not use Python eval or the tolerant Warps importer.
Unknown units and dimensionally inconsistent expressions are errors.
"""

from __future__ import annotations
import ast
import copy
import math
import re
from dataclasses import dataclass
import numpy as np
from .geometry import primitives as prim

D0 = (0.0, 0.0, 0.0)
LENGTH = (1.0, 0.0, 0.0)
FREQ = (0.0, -1.0, 0.0)
ANGLE = (0.0, 0.0, 1.0)
UNITS = {
    k: (v, LENGTH)
    for k, v in {
        "m": 1,
        "cm": 0.01,
        "mm": 0.001,
        "um": 1e-6,
        "nm": 1e-9,
        "mil": 0.0000254,
        "in": 0.0254,
    }.items()
}
UNITS.update(
    {k: (v, FREQ) for k, v in {"Hz": 1, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}.items()}
)
UNITS.update({"deg": (math.pi / 180, ANGLE), "rad": (1.0, ANGLE)})
TOKEN = re.compile(
    r"(?<![\w.])((?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z]+)\b"
)
NAME = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")


@dataclass(frozen=True)
class Quantity:
    value: float
    dim: tuple = D0


class Scope:
    def __init__(self, variables=None):
        self.variables = dict(variables or {})
        self.cache = {}
        self.active = set()

    def variable(self, name):
        if name in self.cache:
            return self.cache[name]
        if name not in self.variables:
            raise ValueError(f"Unknown variable: {name}")
        if name in self.active or len(self.active) > 32:
            raise ValueError(f"Cyclic/deep variable dependency: {name}")
        self.active.add(name)
        try:
            q = self.evaluate(self.variables[name])
        finally:
            self.active.remove(name)
        self.cache[name] = q
        return q

    def evaluate(self, expression):
        if isinstance(expression, bool):
            raise ValueError("Boolean is not a dimension")
        text = str(expression).strip()
        if not text or len(text) > 500:
            raise ValueError("Expression must contain 1–500 characters")

        def unit(m):
            number, suffix = m.groups()
            if suffix not in UNITS:
                raise ValueError(f"Unknown unit: {suffix}")
            return f'q({number},"{suffix}")'

        text = TOKEN.sub(unit, text)
        try:
            node = ast.parse(text, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Invalid expression: {expression}") from e
        if len(list(ast.walk(node))) > 128:
            raise ValueError("Expression is too complex")
        q = self._node(node.body)
        if not math.isfinite(q.value):
            raise ValueError("Expression must evaluate to a finite value")
        return q

    def _node(self, n):
        if (
            isinstance(n, ast.Constant)
            and isinstance(n.value, (int, float))
            and not isinstance(n.value, bool)
        ):
            return Quantity(float(n.value))
        if isinstance(n, ast.Name):
            return Quantity(math.pi) if n.id == "pi" else self.variable(n.id)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            a = self._node(n.operand)
            return Quantity(a.value * (-1 if isinstance(n.op, ast.USub) else 1), a.dim)
        if isinstance(n, ast.BinOp):
            a, b = self._node(n.left), self._node(n.right)
            if isinstance(n.op, (ast.Add, ast.Sub)):
                if a.dim != b.dim:
                    raise ValueError(
                        "Cannot add/subtract quantities with different dimensions"
                    )
                return Quantity(
                    a.value + (1 if isinstance(n.op, ast.Add) else -1) * b.value, a.dim
                )
            if isinstance(n.op, ast.Mult):
                return Quantity(
                    a.value * b.value, tuple(x + y for x, y in zip(a.dim, b.dim))
                )
            if isinstance(n.op, ast.Div):
                return Quantity(
                    a.value / b.value, tuple(x - y for x, y in zip(a.dim, b.dim))
                )
            if isinstance(n.op, ast.Pow):
                if b.dim != D0 or abs(b.value) > 12:
                    raise ValueError(
                        "Power requires a dimensionless exponent between -12 and 12"
                    )
                return Quantity(
                    float(a.value**b.value), tuple(x * b.value for x in a.dim)
                )
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and not n.keywords:
            f = n.func.id
            if (
                f == "q"
                and len(n.args) == 2
                and isinstance(n.args[1], ast.Constant)
                and n.args[1].value in UNITS
            ):
                a = self._node(n.args[0])
                scale, dim = UNITS[n.args[1].value]
                if a.dim != D0:
                    raise ValueError("Invalid unit quantity")
                return Quantity(a.value * scale, dim)
            args = [self._node(x) for x in n.args]
            if f in ("min", "max") and args and all(x.dim == args[0].dim for x in args):
                return Quantity(
                    (min if f == "min" else max)(x.value for x in args), args[0].dim
                )
            if len(args) == 1:
                a = args[0]
                if f == "abs":
                    return Quantity(abs(a.value), a.dim)
                if f == "sqrt":
                    return Quantity(math.sqrt(a.value), tuple(x / 2 for x in a.dim))
                if f in ("sin", "cos", "tan") and a.dim in (D0, ANGLE):
                    return Quantity(getattr(math, f)(a.value))
                if f in ("exp", "ln", "log10", "asin", "acos", "atan", "sinh", "cosh",
                         "tanh", "floor", "ceil") and a.dim == D0:
                    fn = {"ln": math.log}.get(f) or getattr(math, f)
                    try:
                        return Quantity(float(fn(a.value)))
                    except (ValueError, OverflowError) as e:
                        raise ValueError(f"{f}() is not defined at {a.value}") from e
            if f == "atan2" and len(args) == 2 and args[0].dim == args[1].dim:
                return Quantity(math.atan2(args[0].value, args[1].value))
        raise ValueError(
            "Unsupported expression; use arithmetic, variables, sqrt, abs, min/max or sin/cos/tan"
        )

    def length(self, value, units="mm"):
        # Legacy numeric API values are SI; bare text is a display-unit length.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            q = Quantity(float(value), LENGTH)
        else:
            q = self.evaluate(value)
            if q.dim == D0 and re.fullmatch(
                r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", str(value).strip()
            ):
                q = Quantity(q.value * UNITS[units][0], LENGTH)
            if q.dim == D0 and q.value == 0:
                q = Quantity(0.0, LENGTH)
        if q.dim != LENGTH or not math.isfinite(q.value):
            raise ValueError(f"Length required: {value}")
        return q.value


FIELDS = {
    "box": {"position": 3, "size": 3},
    "cylinder": {"center": 3, "radius": 1, "height": 1, "axis": 0},
    "sphere": {"center": 3, "radius": 1},
    "cone": {"center": 3, "r1": 1, "r2": 1, "height": 1, "axis": 0},
    "torus": {"center": 3, "rMajor": 1, "rMinor": 1, "axis": 0},
    "rectangle": {"position": 3, "size": 2, "plane": 0},
    "circle": {"center": 3, "radius": 1, "axis": 0},
}
DEFAULTS = {
    "box": {"position": [0, 0, 0], "size": [0.01, 0.005, 0.001]},
    "cylinder": {
        "center": [0, 0, 0],
        "radius": 0.002,
        "height": 0.01,
        "axis": [0, 0, 1],
    },
    "sphere": {"center": [0, 0, 0], "radius": 0.005},
    "cone": {
        "center": [0, 0, 0],
        "r1": 0.003,
        "r2": 0,
        "height": 0.01,
        "axis": [0, 0, 1],
    },
    "torus": {"center": [0, 0, 0], "rMajor": 0.008, "rMinor": 0.002, "axis": [0, 0, 1]},
    "rectangle": {"position": [0, 0, 0], "size": [0.01, 0.005], "plane": "xy"},
    "circle": {"center": [0, 0, 0], "radius": 0.002, "axis": [0, 0, 1]},
}


def make_primitive(kind, params, name, variables=None, units="mm"):
    if kind not in FIELDS:
        raise ValueError(
            "Primitive editing supports box, cylinder, sphere, cone, torus, rectangle and circle"
        )
    scope = Scope(variables)
    raw = copy.deepcopy(DEFAULTS[kind])
    raw.update(params)
    if any(k not in FIELDS[kind] and k != "solveInside" for k in raw):
        raise ValueError("Unknown primitive parameter")
    values = {}
    for key, n in FIELDS[kind].items():
        v = raw[key]
        if n > 1:
            if not isinstance(v, (list, tuple)) or len(v) != n:
                raise ValueError(f"{key} needs {n} components")
            values[key] = [scope.length(x, units) for x in v]
        elif n == 1:
            values[key] = scope.length(v, units)
        elif key == "axis":
            v = (
                {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}.get(v, v)
                if isinstance(v, str)
                else v
            )
            if len(v) != 3 or not np.isfinite(v).all() or np.linalg.norm(v) == 0:
                raise ValueError("Axis requires a nonzero finite XYZ vector")
            values[key] = v
        elif key == "plane":
            if v not in ("xy", "yz", "xz"):
                raise ValueError("Choose xy, yz or xz plane")
            values[key] = v
    for k in ("size", "radius", "height", "rMajor", "rMinor"):
        if k in values and np.any(np.asarray(values[k]) <= 0):
            raise ValueError(f"{k} must be positive")
    if kind == "cone" and (
        values["r1"] < 0 or values["r2"] < 0 or max(values["r1"], values["r2"]) == 0
    ):
        raise ValueError("Cone radii must be nonnegative and not both zero")
    if kind == "torus" and values["rMinor"] >= values["rMajor"]:
        raise ValueError("Minor radius must be smaller than major radius")
    if kind == "box":
        shape = prim.Box(values["position"], values["size"], name)
    elif kind == "cylinder":
        shape = prim.Cylinder(
            values["center"],
            values["radius"],
            values["height"],
            values["axis"],
            name=name,
        )
    elif kind == "sphere":
        shape = prim.Sphere(values["center"], values["radius"], name)
    elif kind == "cone":
        shape = prim.Cone(
            values["center"],
            values["r1"],
            values["r2"],
            values["height"],
            values["axis"],
            name,
        )
    elif kind == "torus":
        shape = prim.Torus(
            values["center"], values["rMajor"], values["rMinor"], values["axis"], name
        )
    elif kind == "circle":
        shape = prim.Circle(values["center"], values["radius"], values["axis"], name)
    else:
        shape = prim.Rectangle(
            values["position"], values["size"], values["plane"], name
        )
    shape._parametric = {"kind": kind, "params": raw, "units": units}
    return shape


def definition(shape, units="mm"):
    if hasattr(shape, "_parametric"):
        return copy.deepcopy(shape._parametric)
    kind = shape.kind
    if kind not in FIELDS:
        raise ValueError(
            "Select a primitive; Boolean/imported geometry is edited through its history, transforms or CAD source"
        )
    p = shape._params()
    if kind == "rectangle":
        points = np.asarray(shape.points)
        plane = shape.plane
        axes = {"xy": (0, 1), "yz": (1, 2), "xz": (0, 2)}[plane]
        p = {
            "position": points[0].tolist(),
            "size": [
                (points[1] - points[0])[axes[0]],
                (points[3] - points[0])[axes[1]],
            ],
            "plane": plane,
        }
    aliases = {
        "rMajor": "r_major",
        "rMinor": "r_minor",
        "r1": "radius1",
        "r2": "radius2",
    }
    out = {}
    for k, n in FIELDS[kind].items():
        key = k if k in p else aliases.get(k, k)
        v = p[key]
        out[k] = (
            [f"{x:.15g}m" for x in v]
            if n > 1
            else f"{v:.15g}m" if n == 1 else list(v) if isinstance(v, tuple) else v
        )
    return {"kind": kind, "params": out, "units": units}


def walk(shape):
    yield shape
    if isinstance(shape, prim.Boolean):
        for s in shape.operands:
            yield from walk(s)
    elif isinstance(shape, (prim.Extrude, prim.Revolve)):
        yield from walk(shape.profile)
    elif isinstance(shape, prim.FaceOperation):
        yield from walk(shape.base)


def rebuild(design, variables):
    if len(variables) > 128:
        raise ValueError("Maximum 128 design variables")
    if any(not NAME.fullmatch(n) or n in ("pi", "q") for n in variables):
        raise ValueError(
            "Variable names must use letters, digits and underscores; pi/q are reserved"
        )
    scope = Scope(variables)
    for n in variables:
        scope.variable(n)
    pending = []
    seen = set()
    for obj in design.solids + design.sheets:
        for shape in walk(obj.shape):
            if id(shape) in seen:
                continue
            seen.add(id(shape))
            spec = getattr(shape, "_parametric", None)
            if spec:
                pending.append(
                    (
                        shape,
                        make_primitive(
                            spec["kind"],
                            spec["params"],
                            shape.name,
                            variables,
                            spec.get("units", design.units),
                        ),
                    )
                )
    for old, new in pending:
        xform = old._xform
        if isinstance(old, prim.Cylinder):
            new.angle = old.angle
        old.__dict__.update(new.__dict__)
        old._xform = xform
    design.variables = dict(variables)
    design.mesh = None
    return len(pending)
