"""
Automatic object naming.

Every modeller in this class names new entities for you — you type a name only
when you want a *specific* one. The rule is the familiar one: take the type's
base name and append the lowest positive integer that is still free, so a
fresh project produces ``Box1``, ``Box2``, ``Cylinder1`` and a project that
already contains ``Box1`` and ``Box3`` yields ``Box2``.

Names are proposed by the server rather than the browser so that the
suggestion is always consistent with the real model — including entities
created from the scripting console or loaded from an ``.warp`` file.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Set

# Base names per entity kind. Boundary and excitation bases follow the
# abbreviations an RF engineer expects to read in a project tree.
SHAPE_BASE = {
    "box": "Box", "cylinder": "Cylinder", "sphere": "Sphere",
    "cone": "Cone", "torus": "Torus", "rectangle": "Rectangle",
    "circle": "Circle", "polygon": "Polyline", "imported": "Part",
}
BOUNDARY_BASE = {
    "pec": "PerfE", "pmc": "PerfH", "radiation": "Rad",
    "finite_cond": "FiniteCond", "impedance": "Impedance",
    "lumped_rlc": "LumpRLC", "symmetry_e": "SymmE", "symmetry_h": "SymmH",
    "pml": "PML", "master": "Master", "slave": "Slave",
}
PORT_BASE = {"wave": "Port", "lumped": "Lumped"}

_TRAIL = re.compile(r"^(.*?)(\d+)$")


def next_name(existing: Iterable[str], base: str, start: int = 1) -> str:
    """
    Lowest free ``base<n>``.

    >>> next_name(["Box1", "Box3"], "Box")
    'Box2'
    >>> next_name([], "Box")
    'Box1'
    """
    taken: Set[str] = {str(x) for x in existing}
    n = max(int(start), 1)
    while f"{base}{n}" in taken:
        n += 1
    return f"{base}{n}"


def unique_name(existing: Iterable[str], wanted: str) -> str:
    """
    Make *wanted* unique without surprising the user.

    ``Box7`` that is already taken becomes ``Box8`` -- the trailing number is
    advanced rather than a second one appended, so you never get ``Box71``.
    """
    taken = {str(x) for x in existing}
    w = (wanted or "").strip()
    if not w:
        return next_name(taken, "Object")
    if w not in taken:
        return w
    m = _TRAIL.match(w)
    base, start = (m.group(1), int(m.group(2)) + 1) if m else (w, 1)
    return next_name(taken, base, start)


# --------------------------------------------------------------------------
# model-aware helpers
# --------------------------------------------------------------------------


def model_names(design) -> List[str]:
    """Every name that must stay unique inside the modeller."""
    if design is None:
        return []
    return [o.name for o in design.solids] + [s.name for s in design.sheets]


def suggest_shape(design, shape: str) -> str:
    return next_name(model_names(design), SHAPE_BASE.get(shape, "Object"))


def suggest_boundary(design, btype: str) -> str:
    names = [b.name for b in design.boundaries] if design else []
    return next_name(names, BOUNDARY_BASE.get(btype, "Bnd"))


def suggest_port(design, kind: str) -> str:
    names = [p.name for p in design.ports] if design else []
    return next_name(names, PORT_BASE.get(kind, "Port"))


def suggest_mesh_op(design) -> str:
    """Length1, Length2 ... the way a mesh operation is named."""
    used = [m.name for m in getattr(design, "mesh_ops", [])] if design else []
    return next_name(used, "Length")


def suggest_setup(design) -> str:
    names = [s.name for s in design.setups] if design else []
    return next_name(names, "Setup")


def suggest_sweep(setup) -> str:
    names = [s.name for s in setup.sweeps] if setup else []
    return next_name(names, "Sweep")


def suggest_design(project) -> str:
    names = [d.name for d in project.designs] if project else []
    return next_name(names, "WarpsDesign")


def suggest_part_from_file(design, path: str) -> str:
    """A CAD import is named after its file, cleaned up and made unique."""
    import os
    stem = os.path.splitext(os.path.basename(path))[0] or "Part"
    stem = re.sub(r"[^0-9A-Za-z_]+", "_", stem).strip("_") or "Part"
    if stem[0].isdigit():
        stem = "Part_" + stem
    return unique_name(model_names(design), stem)


__all__ = ["next_name", "unique_name", "model_names", "suggest_shape",
           "suggest_boundary", "suggest_port", "suggest_setup", "suggest_mesh_op",
           "suggest_sweep", "suggest_design", "suggest_part_from_file",
           "SHAPE_BASE", "BOUNDARY_BASE", "PORT_BASE"]
