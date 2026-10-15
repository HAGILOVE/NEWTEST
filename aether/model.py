"""
The user-facing model: :class:`Design` and the objects it owns.

This mirrors the Warps project hierarchy so that a translation layer to and
from ``.warp`` is a data mapping rather than a rewrite::

    Project
      Design (DrivenModal / DrivenTerminal / Eigenmode)
        Modeler   -> Design.solids / Design.sheets
        Boundaries-> Design.boundaries
        Excitations-> Design.ports
        Analysis  -> Design.setups
        Materials -> Design.materials
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from .core.config import Config
from .core.constants import c0, to_si
from .core.logging import get_logger
from .core.materials import LIBRARY, Material, MaterialLibrary, resolve
from .geometry.primitives import (Box, Circle, Cylinder, Polygon, Rectangle,
                                  Shape, Sphere)
from .geometry.select import (BoundingBoxFaceSelector, BoxSelector,
                              OuterSelector, PlaneSelector, Selector,
                              ShapeSelector)

log = get_logger("model")

SolutionType = str      # "driven_modal" | "driven_terminal" | "eigenmode"


# --------------------------------------------------------------------------
# Model entities
# --------------------------------------------------------------------------


@dataclass
class Solid:
    """A 3-D body with a material assignment."""
    name: str
    shape: Shape
    material: Material
    solve_inside: bool = True
    #: per-object display overrides; ``None`` means "use the material's"
    display_color: Optional[str] = None
    display_transparency: Optional[float] = None
    visible: bool = True

    @property
    def is_pec(self) -> bool:
        return self.material.is_pec

    @property
    def color(self) -> str:
        """What the object is actually drawn in."""
        return self.display_color or self.material.color

    @property
    def transparency(self) -> float:
        t = self.display_transparency
        return float(self.material.transparency if t is None else t)


@dataclass
class Sheet:
    """A zero-thickness surface (perfect-E sheet, port plane, lumped element)."""
    name: str
    shape: Shape
    material: Optional[Material] = None
    #: same per-object display overrides a solid has
    display_color: Optional[str] = None
    display_transparency: Optional[float] = None
    visible: bool = True
    solve_inside: bool = False

    @property
    def color(self) -> str:
        return self.display_color or (self.material.color if self.material
                                      else "#d69e2e")

    @property
    def transparency(self) -> float:
        t = self.display_transparency
        if t is not None:
            return float(t)
        return float(self.material.transparency if self.material else 0.25)


@dataclass
class Boundary:
    """
    A boundary condition applied to the triangles chosen by *selector*.

    ``btype`` is one of

    ==================  ==========================================================
    ``pec``             perfect electric conductor, n x E = 0
    ``pmc``             perfect magnetic conductor, n x H = 0 (natural BC)
    ``impedance``       Leontovich  n x (n x E) = -Zs (n x H)
    ``finite_cond``     impedance derived from sigma, thickness, roughness
    ``radiation``       1st-order absorbing boundary (Sommerfeld)
    ``pml``             perfectly matched layer region (see ``PMLRegion``)
    ``symmetry_e``      perfect-E symmetry plane
    ``symmetry_h``      perfect-H symmetry plane
    ``lumped_rlc``      distributed series/parallel R-L-C sheet
    ``master``/``slave``  periodic (Floquet) pair
    ==================  ==========================================================
    """
    name: str
    btype: str
    selector: Selector
    params: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0

    def surface_impedance(self, f: float) -> complex:
        """Resolve the effective sheet impedance [Ohm/sq] at frequency *f*."""
        from .core.constants import surface_impedance as _zs
        p = self.params
        if self.btype == "impedance":
            return complex(p.get("Zs", 0.0))
        if self.btype == "finite_cond":
            mat: Material = p.get("material") or LIBRARY.get("copper")
            zs = mat.surface_impedance(f)
            t = p.get("thickness")
            if t:            # finite thickness correction (coth of gamma*t)
                d = mat.skin_depth(f)
                if d > 0:
                    g = complex(1.0, 1.0) / d
                    zs = zs / np.tanh(g * t)
            rough = p.get("roughness", 0.0)
            if rough:        # Hammerstad-Jensen roughness factor
                d = mat.skin_depth(f)
                k = 1.0 + (2.0 / math.pi) * math.atan(1.4 * (rough / max(d, 1e-30)) ** 2)
                zs = complex(zs.real * k, zs.imag * k)
            return zs
        if self.btype == "lumped_rlc":
            R = p.get("R", 0.0); L = p.get("L", 0.0); C = p.get("C", 0.0)
            w = 2 * math.pi * f
            if p.get("parallel", True):
                y = 0.0 + 0.0j
                if R:
                    y += 1.0 / R
                if L:
                    y += 1.0 / (1j * w * L)
                if C:
                    y += 1j * w * C
                return 1.0 / y if y != 0 else 1e12 + 0j
            z = complex(R, 0.0)
            if L:
                z += 1j * w * L
            if C:
                z += 1.0 / (1j * w * C)
            return z
        return 0.0 + 0.0j


@dataclass
class WavePort:
    """
    Wave port -- a 2-D modal eigen-analysis on a planar cross-section.

    The port plane must lie on the outer boundary of the solution volume
    (Warps rule).  ``num_modes`` transverse modes are solved for and each
    becomes an S-parameter row/column.
    """
    name: str
    selector: Selector
    num_modes: int = 1
    deembed: float = 0.0                       # [m] positive = move plane in
    renormalize_z: Optional[float] = None      # [Ohm]
    integration_line: Optional[Tuple[Sequence[float], Sequence[float]]] = None
    impedance_definition: str = "pi"
    index: int = 0                             # filled by Design

    kind: str = "wave"


@dataclass
class LumpedPort:
    """
    Lumped port -- an internal sheet driven with a uniform field along
    ``direction`` and terminated in ``impedance``.
    """
    name: str
    selector: Selector
    impedance: complex = 50.0
    direction: Sequence[float] = (0.0, 0.0, 1.0)
    integration_line: Optional[Tuple[Sequence[float], Sequence[float]]] = None
    num_modes: int = 1
    index: int = 0
    renormalize_z: Optional[float] = None
    deembed: float = 0.0

    kind: str = "lumped"


Port = Union[WavePort, LumpedPort]


@dataclass
class FrequencySweep:
    """A named sweep inside a setup."""
    name: str = "Sweep1"
    kind: str = "discrete"          # discrete | fast | interpolating
    start: float = 1e9
    stop: float = 10e9
    count: int = 101
    spacing: str = "linear"         # linear | log | single
    points: Optional[Sequence[float]] = None
    save_fields: bool = False
    #: interpolating / fast sweeps: max |dS| the model may be wrong by, and the
    #: most full solves it may spend; ``None`` -> ``Config.sweep`` defaults
    tolerance: Optional[float] = None
    max_points: Optional[int] = None
    #: spacing == "step": the frequency increment [Hz]
    step: Optional[float] = None

    def frequencies(self) -> np.ndarray:
        if self.points is not None:
            return np.asarray([to_si(p, "frequency") for p in self.points], float)
        a, b, n = self.start, self.stop, max(int(self.count), 1)
        if self.spacing == "step":
            # Warps "Linear Step": start, start+step, ... up to and including stop
            st = float(self.step or 0.0)
            if st <= 0:
                raise ValueError("a linear-step sweep needs a positive step")
            k = int(math.floor((b - a) / st + 1e-9)) + 1
            return a + st * np.arange(max(k, 1))
        if self.spacing == "single" or n == 1:
            return np.array([a], float)
        if self.spacing == "log":
            return np.logspace(math.log10(a), math.log10(b), n)
        return np.linspace(a, b, n)


@dataclass
class Setup:
    """Solution setup: adaptive mesh frequency + attached sweeps."""
    name: str = "Setup1"
    frequency: float = 1e9              # adaptive/solution frequency [Hz]
    max_passes: int = 6
    delta_s: float = 0.02
    min_passes: int = 1
    basis_order: int = 1
    sweeps: List[FrequencySweep] = field(default_factory=list)
    #: eigenmode designs: how many modes to find above ``min_frequency`` [Hz]
    #: and the largest relative frequency change between passes that counts
    #: as converged (Warps: "Maximum Delta Frequency Per Pass")
    n_modes: int = 3
    min_frequency: float = 0.0
    delta_f: float = 0.02
    #: consecutive passes that must meet the target (Warps "Minimum Converged
    #: Passes") and the share of tetrahedra refined per pass (default 30 %)
    min_converged: int = 1
    refinement: float = 0.30

    def add_sweep(self, name="Sweep1", start="1GHz", stop="10GHz", count=101,
                  kind="discrete", spacing="linear", points=None,
                  save_fields=False, tolerance=None,
                  max_points=None, step=None) -> FrequencySweep:
        sw = FrequencySweep(name, kind, to_si(start, "frequency"),
                            to_si(stop, "frequency"), count, spacing,
                            points, save_fields, tolerance, max_points,
                            to_si(step, "frequency") if step else None)
        if spacing == "step":
            sw.count = len(sw.frequencies())
        self.sweeps.append(sw)
        return sw


# --------------------------------------------------------------------------
# Design
# --------------------------------------------------------------------------


@dataclass
class MeshOperation:
    """
    A local mesh refinement, the way a modeller states it: *these objects* or
    *these faces*, no element longer than this.

    The solver's own adaptive refinement decides where accuracy is missing,
    but it starts from the initial mesh -- and there are places you already
    know need resolving before the first pass: a thin feed line, the gap of a
    coupled pair, the rim of a patch. That is what a mesh operation is for.
    """
    name: str
    max_length: float = 0.0
    objects: List[str] = field(default_factory=list)
    selector: Optional[Selector] = None
    kind: str = "length"
    enabled: bool = True

    def __post_init__(self):
        self.max_length = to_si(self.max_length)

    def describe(self) -> str:
        where = ", ".join(self.objects) if self.objects else (
            self.selector.describe() if hasattr(self.selector, "describe")
            else "picked faces" if self.selector is not None else "?")
        return f"{self.name}: {where} <= {self.max_length * 1e3:.4g} mm"


class Design:
    """
    A complete simulation model.

    Example
    -------
    >>> d = Design("wr90", solution_type="driven_modal")
    >>> d.add_box("guide", (0,0,0), ("22.86mm","10.16mm","30mm"), "vacuum")
    >>> d.assign_pec_outer(exclude_ports=True)
    >>> d.add_wave_port("p1", axis="z", value=0)
    >>> d.add_wave_port("p2", axis="z", value="30mm")
    >>> s = d.add_setup("Setup1", frequency="10GHz")
    """

    def __init__(self, name: str = "Design1",
                 solution_type: SolutionType = "driven_modal",
                 units: str = "mm", config: Optional[Config] = None,
                 materials: Optional[MaterialLibrary] = None):
        self.name = name
        self.solution_type = solution_type
        self.units = units
        self.config = config or Config()
        self.materials = materials or MaterialLibrary()
        self.solids: List[Solid] = []
        self.sheets: List[Sheet] = []
        self.boundaries: List[Boundary] = []
        self.ports: List[Port] = []
        self.setups: List[Setup] = []
        self.mesh_ops: List[MeshOperation] = []
        #: named relative coordinate systems: ``[{"name": str, "origin": (x, y, z) m}]``.
        #: Offset-only (axes stay parallel to the global ones), like an
        #: "Offset" relative CS: coordinates typed in one are measured from its origin.
        self.coordinate_systems: List[Dict[str, Any]] = []
        #: the coordinate system new coordinates are read in ("" = Global)
        self.working_cs: str = ""
        self.variables: Dict[str, Any] = {}
        self.mesh = None                     # populated by generate_mesh()
        self.notes: Dict[str, Any] = {}
        self._warp_source = None             # round-trip provenance

    # ------------------------------------------------ coordinate systems
    def add_coordinate_system(self, name: str, origin) -> Dict[str, Any]:
        name = str(name).strip()
        if not name or name.lower() == "global":
            raise ValueError("give the coordinate system a name other than 'Global'")
        if any(c["name"] == name for c in self.coordinate_systems):
            raise ValueError(f"a coordinate system named {name!r} already exists")
        o = tuple(float(x) for x in origin)
        if len(o) != 3 or not all(math.isfinite(x) for x in o):
            raise ValueError("a coordinate system origin is three finite numbers")
        cs = {"name": name, "origin": o}
        self.coordinate_systems.append(cs)
        return cs

    def get_coordinate_system(self, name: str) -> Dict[str, Any]:
        for c in self.coordinate_systems:
            if c["name"] == name:
                return c
        raise KeyError(f"no coordinate system named {name!r}")

    def delete_coordinate_system(self, name: str) -> None:
        self.get_coordinate_system(name)
        self.coordinate_systems = [c for c in self.coordinate_systems if c["name"] != name]
        if self.working_cs == name:
            self.working_cs = ""

    def working_origin(self):
        """Origin (metres) of the coordinate system in use; the global one is 0."""
        if self.working_cs:
            try:
                return self.get_coordinate_system(self.working_cs)["origin"]
            except KeyError:
                self.working_cs = ""
        return (0.0, 0.0, 0.0)

    # ----------------------------------------------------------- geometry
    def add_solid(self, name: str, shape: Shape, material="vacuum",
                  solve_inside: bool = True) -> Solid:
        if any(s.name == name for s in self.solids):
            raise ValueError(f"solid {name!r} already exists")
        shape.name = shape.name or name
        s = Solid(name, shape, self.materials.get(material)
                  if isinstance(material, str) else resolve(material),
                  solve_inside)
        self.solids.append(s)
        return s

    def add_box(self, name, position, size, material="vacuum", **kw) -> Solid:
        return self.add_solid(name, Box(position, size, name), material, **kw)

    def add_cylinder(self, name, center, radius, height, material="vacuum",
                     axis=(0, 0, 1), **kw) -> Solid:
        return self.add_solid(name, Cylinder(center, radius, height, axis, name=name),
                              material, **kw)

    def add_sphere(self, name, center, radius, material="vacuum", **kw) -> Solid:
        return self.add_solid(name, Sphere(center, radius, name), material, **kw)

    def add_sheet(self, name: str, shape: Shape, material=None) -> Sheet:
        shape.name = shape.name or name
        sh = Sheet(name, shape, resolve(material) if material else None)
        self.sheets.append(sh)
        return sh

    def get_solid(self, name: str) -> Solid:
        for s in self.solids:
            if s.name == name:
                return s
        raise KeyError(f"no solid named {name!r}")

    def bounding_box(self) -> Tuple[np.ndarray, np.ndarray]:
        if not self.solids:
            return np.zeros(3), np.zeros(3)
        bs = [s.shape.bounds() for s in self.solids]
        lo = np.min([b[0] for b in bs], axis=0)
        hi = np.max([b[1] for b in bs], axis=0)
        return lo, hi

    # --------------------------------------------------------- boundaries
    def assign_boundary(self, name: str, btype: str, selector: Selector,
                        **params) -> Boundary:
        b = Boundary(name, btype, selector, params)
        self.boundaries.append(b)
        return b

    def assign_pec(self, name: str, selector: Selector) -> Boundary:
        return self.assign_boundary(name, "pec", selector)

    def assign_pec_outer(self, name: str = "OuterPEC",
                         exclude_ports: bool = True) -> Boundary:
        """Close the model with PEC everywhere except the port faces."""
        excl = None
        if exclude_ports and self.ports:
            from .geometry.select import union_sel
            excl = union_sel(*[p.selector for p in self.ports])
        return self.assign_boundary(name, "pec", OuterSelector(exclude=excl))

    def assign_radiation(self, name: str = "Rad1",
                         selector: Optional[Selector] = None) -> Boundary:
        return self.assign_boundary(name, "radiation",
                                    selector or OuterSelector())

    def assign_finite_conductivity(self, name: str, selector: Selector,
                                   material="copper", thickness=None,
                                   roughness=0.0) -> Boundary:
        return self.assign_boundary(
            name, "finite_cond", selector,
            material=self.materials.get(material) if isinstance(material, str)
            else resolve(material),
            thickness=to_si(thickness) if thickness else None,
            roughness=to_si(roughness) if roughness else 0.0)

    def assign_impedance(self, name: str, selector: Selector, Zs: complex) -> Boundary:
        return self.assign_boundary(name, "impedance", selector, Zs=complex(Zs))

    def assign_lumped_rlc(self, name: str, selector: Selector, R=0.0, L=0.0,
                          C=0.0, parallel=True, direction=(0, 0, 1)) -> Boundary:
        return self.assign_boundary(name, "lumped_rlc", selector, R=R, L=L, C=C,
                                    parallel=parallel, direction=direction)

    def assign_symmetry(self, name: str, selector: Selector,
                        kind: str = "e") -> Boundary:
        return self.assign_boundary(name, f"symmetry_{kind.lower()}", selector)

    # -------------------------------------------------------------- ports
    def add_wave_port(self, name: str, selector: Optional[Selector] = None,
                      axis: Optional[str] = None, value=0.0, window=None,
                      num_modes: int = 1, deembed=0.0, renormalize_z=None,
                      integration_line=None, tol=1e-9) -> WavePort:
        if selector is None:
            if axis is None:
                raise ValueError("give either a selector or axis+value")
            selector = PlaneSelector(axis, value, tol=tol, window=window)
        p = WavePort(name, selector, num_modes, to_si(deembed),
                     renormalize_z, integration_line, index=len(self.ports))
        self.ports.append(p)
        return p

    def add_lumped_port(self, name: str, selector: Optional[Selector] = None,
                        axis: Optional[str] = None, value=0.0, window=None,
                        impedance=50.0, direction=(0, 0, 1),
                        integration_line=None, tol=1e-9) -> LumpedPort:
        if selector is None:
            if axis is None:
                raise ValueError("give either a selector or axis+value")
            selector = PlaneSelector(axis, value, tol=tol, window=window)
        p = LumpedPort(name, selector, complex(impedance), direction,
                       integration_line, index=len(self.ports))
        self.ports.append(p)
        return p

    def get_port(self, name: str) -> Port:
        for p in self.ports:
            if p.name == name:
                return p
        raise KeyError(f"no port named {name!r}")

    @property
    def n_excitations(self) -> int:
        return sum(getattr(p, "num_modes", 1) for p in self.ports)

    def excitation_names(self) -> List[str]:
        out = []
        for p in self.ports:
            n = getattr(p, "num_modes", 1)
            for m in range(n):
                out.append(f"{p.name}:{m + 1}" if n > 1 else p.name)
        return out

    # ---------------------------------------------------- mesh operations
    def add_mesh_operation(self, name: str = "Length1", max_length="1mm",
                           objects: Optional[Sequence[str]] = None,
                           selector: Optional[Selector] = None,
                           enabled: bool = True) -> MeshOperation:
        """
        Refine the initial mesh on named objects or on a picked face.

        >>> d.add_mesh_operation("Feed", "0.2mm", objects=["feed_line"])
        """
        if any(m.name == name for m in self.mesh_ops):
            raise ValueError(f"mesh operation {name!r} already exists")
        for n in (objects or []):
            if not any(o.name == n for o in self.solids + self.sheets):
                raise KeyError(f"no object named {n!r}")
        op = MeshOperation(name, to_si(max_length), list(objects or []),
                           selector, enabled=enabled)
        if op.max_length <= 0:
            raise ValueError("a mesh operation needs a positive max length")
        if not op.objects and op.selector is None:
            raise ValueError("a mesh operation needs objects or a face selection")
        self.mesh_ops.append(op)
        self.mesh = None
        return op

    def delete_mesh_operation(self, name: str) -> None:
        n = len(self.mesh_ops)
        self.mesh_ops = [m for m in self.mesh_ops if m.name != name]
        if len(self.mesh_ops) == n:
            raise KeyError(f"no mesh operation named {name!r}")
        self.mesh = None

    # ------------------------------------------------------------- setups
    def add_setup(self, name: str = "Setup1", frequency="1GHz",
                  max_passes: Optional[int] = None, delta_s: Optional[float] = None,
                  basis_order: Optional[int] = None) -> Setup:
        s = Setup(name, to_si(frequency, "frequency"),
                  max_passes if max_passes is not None else self.config.adaptive.max_passes,
                  delta_s if delta_s is not None else self.config.adaptive.delta_s,
                  self.config.adaptive.min_passes,
                  basis_order if basis_order is not None else self.config.basis_order)
        self.setups.append(s)
        return s

    def get_setup(self, name: Optional[str] = None) -> Setup:
        if not self.setups:
            raise RuntimeError("no solution setup defined; call add_setup() first")
        if name is None:
            return self.setups[0]
        for s in self.setups:
            if s.name == name:
                return s
        raise KeyError(f"no setup named {name!r}")

    # ------------------------------------------------------- mesh & solve
    def generate_mesh(self, freq: Optional[float] = None, force: bool = False,
                      **kw):
        from .mesh.generator import generate
        if self.mesh is not None and not force:
            return self.mesh
        f = freq if freq is not None else (
            self.setups[0].frequency if self.setups else 1e9)
        self.mesh = generate(self, f, **kw)
        return self.mesh

    def validate(self) -> List[str]:
        """Warps-style pre-flight check.  Returns a list of problems found."""
        errs: List[str] = []
        if not self.solids:
            errs.append("model contains no solids")
        if self.solution_type != "eigenmode" and not self.ports:
            errs.append("driven solution requires at least one port")
        if not self.setups:
            errs.append("no solution setup defined")
        try:
            lo, hi = self.bounding_box()
            if np.any(hi - lo <= 0):
                errs.append(f"degenerate bounding box {lo} .. {hi}")
        except Exception as exc:
            errs.append(f"cannot evaluate model bounds: {exc}")
        names = [s.name for s in self.solids]
        if len(set(names)) != len(names):
            errs.append("duplicate solid names")
        pnames = [p.name for p in self.ports]
        if len(set(pnames)) != len(pnames):
            errs.append("duplicate port names")
        for st in self.setups:
            for sw in st.sweeps:
                try:
                    fr = sw.frequencies()
                    if np.any(fr <= 0):
                        errs.append(f"sweep {sw.name!r} contains non-positive frequency")
                except Exception as exc:
                    errs.append(f"sweep {sw.name!r} is invalid: {exc}")
        from .diagnostics import additional_errors
        errs.extend(additional_errors(self))
        return list(dict.fromkeys(errs))

    def solve(self, setup: Optional[str] = None, sweep: Optional[str] = None,
              **kw):
        from .fem.driver import solve_design
        return solve_design(self, setup=setup, sweep=sweep, **kw)

    # ------------------------------------------------------------ history
    def snapshot(self) -> dict:
        """
        A deep copy of everything an edit can change.

        The mesh and any solution are deliberately excluded: they are derived
        data, they are large, and an edit invalidates them anyway. Because the
        whole model is copied in one ``deepcopy`` call, cross-references
        survive -- a boundary that points at a solid's shape still points at
        the copy of that shape, not the original.
        """
        import copy as _copy
        return _copy.deepcopy({
            "solids": self.solids, "sheets": self.sheets,
            "boundaries": self.boundaries, "ports": self.ports,
            "setups": self.setups, "mesh_ops": self.mesh_ops,
            "variables": self.variables, "import_issues": getattr(self,"import_issues",[]),
            "units": self.units, "solution_type": self.solution_type,
            "config": self.config, "default_boundary": getattr(self, "default_boundary", "pec"),
            "name": self.name, "materials": self.materials,
            "coordinate_systems": self.coordinate_systems,
        })

    def restore(self, snap: dict) -> "Design":
        """Put the model back to a :meth:`snapshot`; derived data is dropped."""
        import copy as _copy
        s = _copy.deepcopy(snap)
        self.solids = s["solids"]
        self.sheets = s["sheets"]
        self.boundaries = s["boundaries"]
        self.ports = s["ports"]
        self.setups = s["setups"]
        self.mesh_ops = s.get("mesh_ops", [])
        self.variables = s["variables"]
        self.import_issues = s.get("import_issues", [])
        self.config = s.get("config", self.config)
        self.default_boundary = s.get("default_boundary", "pec")
        self.units = s["units"]
        self.solution_type = s["solution_type"]
        self.name = s["name"]
        self.materials = s["materials"]
        self.coordinate_systems = s.get("coordinate_systems", [])
        if self.working_cs and not any(c["name"] == self.working_cs
                                       for c in self.coordinate_systems):
            self.working_cs = ""
        for i, p in enumerate(self.ports):
            p.index = i
        self.mesh = None
        return self

    # ---------------------------------------------------------- reporting
    def summary(self) -> str:
        lo, hi = self.bounding_box()
        lines = [
            f"Design {self.name!r}  [{self.solution_type}]  units={self.units}",
            f"  solids     : {len(self.solids)}  "
            f"({', '.join(s.name for s in self.solids[:8])}"
            f"{' ...' if len(self.solids) > 8 else ''})",
            f"  sheets     : {len(self.sheets)}",
            f"  boundaries : {len(self.boundaries)}  "
            f"({', '.join(b.btype for b in self.boundaries[:8])})",
            f"  ports      : {len(self.ports)} -> "
            f"{self.n_excitations} excitation(s)",
            f"  setups     : {', '.join(s.name for s in self.setups) or '-'}",
            f"  bbox       : [{lo[0]:.6g},{lo[1]:.6g},{lo[2]:.6g}] .. "
            f"[{hi[0]:.6g},{hi[1]:.6g},{hi[2]:.6g}] m",
        ]
        if self.mesh is not None:
            lines.append("  " + self.mesh.report().replace("\n", "\n  "))
        return "\n".join(lines)

    def __repr__(self):
        return (f"<Design {self.name!r} solids={len(self.solids)} "
                f"ports={len(self.ports)}>")


class Project:
    """A container of designs -- the unit that maps to one ``.warp`` file."""

    def __init__(self, name: str = "Project1"):
        self.name = name
        self.designs: List[Design] = []
        self.warp_tree = None            # preserved for lossless round-trip

    def add_design(self, design: Design) -> Design:
        self.designs.append(design)
        return design

    def new_design(self, name: str, **kw) -> Design:
        return self.add_design(Design(name, **kw))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self.designs[key]
        for d in self.designs:
            if d.name == key:
                return d
        raise KeyError(key)

    def __len__(self):
        return len(self.designs)

    def __repr__(self):
        return f"<Project {self.name!r} designs={[d.name for d in self.designs]}>"


__all__ = ["Design", "Project", "Solid", "Sheet", "Boundary", "WavePort",
           "LumpedPort", "Port", "Setup", "FrequencySweep"]
