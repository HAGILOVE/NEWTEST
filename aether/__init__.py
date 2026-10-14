"""
Aether-EM -- a 3-D full-wave electromagnetic field solver.

Aether solves Maxwell's equations in the frequency domain with the finite
element method on tetrahedra, using curl-conforming (Nedelec) vector basis
functions -- the same numerical foundation as Ansys HFSS -- and produces
S-parameters, port modes, field distributions and far-field patterns.

Quick start
-----------
>>> import aether as ae
>>> d = ae.Design("wr90", solution_type="driven_modal")
>>> d.add_box("guide", (0, 0, 0), ("22.86mm", "10.16mm", "20mm"), "vacuum")
>>> d.add_wave_port("p1", axis="z", value=0)
>>> d.add_wave_port("p2", axis="z", value="20mm")
>>> d.assign_pec_outer()
>>> setup = d.add_setup("Setup1", frequency="10GHz")
>>> setup.add_sweep("Sweep1", "8GHz", "12GHz", 41)
>>> sol = d.solve()
>>> sol.sparams.write_touchstone("wr90.s2p")

What the physics layer actually solves
--------------------------------------
The double-curl vector wave equation for the electric field,

    curl( (1/mu_r) curl E ) - k0^2 eps_c E = 0 ,

with ``eps_c = eps_r' - j eps_r'' - j sigma/(omega eps0)`` and the
``exp(+j omega t)`` engineering time convention.  Boundary conditions cover
perfect electric/magnetic conductors, Leontovich surface impedance (finite
conductivity with thickness and roughness corrections), first-order radiation,
lumped R-L-C sheets, and modal wave ports whose transverse fields come from a
2-D eigenanalysis of the port cross-section.

HFSS interoperability
---------------------
:mod:`aether.io.aedt` reads and writes the ``.aedt`` / ``.aedtz`` project tree
(raw syntax trees can round-trip without edits), :mod:`aether.io.touchstone` handles ``.sNp``
and ``.ts``, and geometry travels through STEP / IGES / BREP / STL.
"""
from __future__ import annotations

# Verify the interpreter can actually load the scientific stack before any of
# it is imported. A broken or cross-version environment then produces one
# clear diagnosis instead of a nested traceback that blames the wrong module.
from ._preflight import AetherEnvironmentError, environment_error
from .version import __engine__, __release__, __version__

#: ``None`` when the interpreter can load NumPy/SciPy, otherwise the
#: diagnosis. The package stays importable either way so that
#: ``aether doctor`` works precisely when it is needed.
ENV_ERROR = environment_error()

if ENV_ERROR is None:
    # core physics
    from .core import constants
    from .core.config import (AdaptiveSettings, Config, MeshSettings, PortSettings,
                              SolverSettings, SweepSettings)
    from .core.constants import (c0, eps0, eta0, k0, mu0, omega, skin_depth,
                                 to_si, wavelength)
    from .core.logging import configure as set_log_level
    from .core.materials import (LIBRARY, AIR, COPPER, PEC, PMC, VACUUM,
                                 ConstantTanD, Debye, DjordjevicSarkar, Drude,
                                 Lorentz, Material, MaterialLibrary, Tabulated)

    # geometry
    from .geometry.primitives import (Box, Circle, Cone, Cylinder, Extrude,
                                      ImportedShape, Polygon, Rectangle, Revolve,
                                      Sphere, Torus, cut, intersect, union)
    from .geometry.select import (BoundingBoxFaceSelector, BoxSelector,
                                  CylinderSelector, FaceSelector, OuterSelector,
                                  PlaneSelector, Predicate, ShapeSelector,
                                  intersect_sel, invert_sel, union_sel)

    # model
    from .model import (Boundary, Design, FrequencySweep, LumpedPort, Project,
                        Setup, Sheet, Solid, WavePort)

    # mesh / solver
    from .mesh.tetmesh import TetMesh
    from .fem.driver import Solution

    # post-processing
    from .post.sparam import SParameters

    # optimisation (Optimetrics)
    from .optimize import Goal, OptimizationResult, optimize
else:                                    # degraded: only the doctor is usable
    def __getattr__(name):               # PEP 562
        if name.startswith("__"):
            raise AttributeError(name)
        raise ENV_ERROR


def doctor() -> int:
    """Print an environment report (the same one ``aether-doctor`` prints)."""
    from ._preflight import main
    return main()


__all__ = [
    "__version__", "__release__", "__engine__", "AetherEnvironmentError",
    "doctor",
    # config
    "Config", "MeshSettings", "AdaptiveSettings", "SolverSettings",
    "SweepSettings", "PortSettings", "set_log_level",
    # constants
    "constants", "c0", "mu0", "eps0", "eta0", "to_si", "wavelength", "k0",
    "omega", "skin_depth",
    # materials
    "Material", "MaterialLibrary", "LIBRARY", "VACUUM", "AIR", "PEC", "PMC",
    "COPPER", "ConstantTanD", "Debye", "Drude", "Lorentz",
    "DjordjevicSarkar", "Tabulated",
    # geometry
    "Box", "Cylinder", "Sphere", "Cone", "Torus", "Polygon", "Rectangle",
    "Circle", "Extrude", "Revolve", "ImportedShape", "union", "cut",
    "intersect",
    "PlaneSelector", "BoxSelector", "ShapeSelector", "CylinderSelector",
    "FaceSelector",
    "OuterSelector", "BoundingBoxFaceSelector", "Predicate", "union_sel",
    "intersect_sel", "invert_sel",
    # model
    "Design", "Project", "Solid", "Sheet", "Boundary", "WavePort",
    "LumpedPort", "Setup", "FrequencySweep",
    # results
    "TetMesh", "Solution", "SParameters",
    # optimisation
    "optimize", "Goal", "OptimizationResult",
    # helpers
    "open_hfss", "save_hfss", "read_touchstone", "write_touchstone",
    "import_cad",
]


# --------------------------------------------------------------------------
# top-level convenience API
# --------------------------------------------------------------------------


def open_hfss(path: str, design: int | str = 0):
    """
    Open an HFSS ``.aedt`` / ``.aedtz`` project.

    Returns ``(design, report)``; the report lists everything that could not
    be translated, so nothing is lost silently.
    """
    from .io.aedt.translate import read_project
    proj, reports = read_project(path)
    if isinstance(design, str):
        for i, d in enumerate(proj.designs):
            if d.name == design:
                return d, reports[i]
        raise KeyError(f"no design named {design!r} in {path}")
    return proj[design], reports[design]


def open_hfss_project(path: str):
    """Open every design in an HFSS project -> ``(Project, [ImportReport])``."""
    from .io.aedt.translate import read_project
    return read_project(path)


def save_hfss(obj, path: str, mode: str = "auto") -> str:
    """Write a :class:`Design` or :class:`Project` as an ``.aedt`` project."""
    from .io.aedt.writer import write_project
    return write_project(path, obj, mode=mode)


def read_touchstone(path: str) -> SParameters:
    """Read a ``.sNp`` / ``.ts`` file."""
    from .io.touchstone import read_touchstone as _r
    return _r(path)


def write_touchstone(path: str, sp: SParameters, **kw) -> str:
    """Write a ``.sNp`` / ``.ts`` file."""
    from .io.touchstone import write_touchstone as _w
    return _w(path, sp, **kw)


def import_cad(path: str, name: str = "", scale_to_m: float = 1.0,
               healing: bool = True) -> ImportedShape:
    """Reference a STEP / IGES / BREP / STL file as a solid."""
    return ImportedShape(path, name=name or "imported", healing=healing,
                         scale_to_m=scale_to_m)
