"""
Translation between the ``.warp`` project tree and Aether's :class:`Design`.

What transfers
--------------
======================  ====================================================
model units             ``Design.units``
design variables        evaluated into every geometric expression
materials               name, eps_r, mu_r, tan_d, conductivity
primitives              Box, Cylinder, Sphere, Cone, Torus, Polyline-extrude
                        plus Unite / Subtract / Intersect history
boundaries              Perfect E/H, Radiation, Finite Conductivity,
                        Impedance, Lumped RLC, Symmetry
excitations             Wave Port (modes, de-embed, renormalise),
                        Lumped Port (impedance, direction)
solution setups         adaptive frequency, MaxDeltaS, passes, and all
                        Linear-Count / Linear-Step / Single-point sweeps
======================  ====================================================

What does **not** transfer, and why
-----------------------------------
Warps attaches boundaries to *face ids* produced by its own ACIS kernel.  Those
ids exist only inside the modeller session; the project file stores the number,
not the surface.  A boundary given by ``Objects=[...]`` is therefore
re-attached to the named solid's faces, while one given only by ``Faces=[...]``
is reported as unresolved rather than silently mis-applied.  Every such item is
listed in :class:`ImportReport`, so nothing is lost quietly.
"""
from __future__ import annotations

import contextvars
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ...core.constants import c0, to_si
from ...core.logging import get_logger
from ...core.materials import ConstantTanD, Material, MaterialLibrary
from ...geometry.primitives import (Box, Cone, Cylinder, Polygon, Shape,
                                    Sphere, Torus, cut, intersect, union)
from ...geometry.select import (BoundingBoxFaceSelector, OuterSelector,
                                PlaneSelector, ShapeSelector)
from ...model import Design, Project
from .expr import VariableScope, evaluate
from .tree import WarpBlock, WarpDocument, WarpProp
from .values import Call, Counted

log = get_logger("io.warp.translate")

BTYPE_MAP = {
    "perfect e": "pec",
    "perfecte": "pec",
    "perfect h": "pmc",
    "perfecth": "pmc",
    "radiation": "radiation",
    "finite conductivity": "finite_cond",
    "finitecond": "finite_cond",
    "impedance": "impedance",
    "lumped rlc": "lumped_rlc",
    "lumpedrlc": "lumped_rlc",
    "symmetry": "symmetry_e",
    "perfectly matched layer": "pml",
}

SOLUTION_MAP = {
    "warps modal network": "driven_modal",
    "drivenmodal": "driven_modal",
    "driven modal": "driven_modal",
    "warps terminal network": "driven_terminal",
    "driventerminal": "driven_terminal",
    "driven terminal": "driven_terminal",
    "eigenmode": "eigenmode",
    "warps eigenmode": "eigenmode",
}


@dataclass
class ImportReport:
    """Everything the translator did and could not do."""
    design_name: str = ""
    solids: List[str] = field(default_factory=list)
    boundaries: List[str] = field(default_factory=list)
    ports: List[str] = field(default_factory=list)
    setups: List[str] = field(default_factory=list)
    materials: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # Warps attaches boundaries to numeric part ids, not names
    part_ids: Dict[int, str] = field(default_factory=dict)
    # native (Parasolid) bodies written out of the project's own attachments
    extracted: List[str] = field(default_factory=list)
    # PML layers, materials and boundaries dropped on the way in
    pml_parts: List[str] = field(default_factory=list)
    pml_ids: set = field(default_factory=set)
    pml_boundaries: List[str] = field(default_factory=list)
    pml_radiation: bool = False

    def __str__(self):
        out = [f"Warps import report for design {self.design_name!r}",
               f"  solids     : {len(self.solids)}  {self.solids[:8]}",
               f"  materials  : {len(self.materials)}",
               f"  boundaries : {len(self.boundaries)}",
               f"  ports      : {len(self.ports)}",
               f"  setups     : {len(self.setups)}"]
        if self.unresolved:
            out.append(f"  UNRESOLVED ({len(self.unresolved)}):")
            out += [f"    - {u}" for u in self.unresolved[:20]]
        if self.warnings:
            out.append(f"  warnings ({len(self.warnings)}):")
            out += [f"    - {w}" for w in self.warnings[:20]]
        return "\n".join(out)


# ==========================================================================
# reading
# ==========================================================================


_PML_NAME = re.compile(r"^(pml[_\-]?|pmlgroup)", re.I)


def is_pml_name(name: str) -> bool:
    """
    True for the auto-generated PML apparatus Warps writes around a model.

    Warps builds a perfectly matched layer as *geometry*: a shell of
    ``PML_<region>_1..26`` boxes and wedges, one ``PMLGroup*`` material per
    stretching direction, and a ``PML_radiation*`` boundary on each outer
    face. None of it is the model the engineer drew, none of it survives a
    change to the air region, and Aether does not solve with a stretched-
    coordinate absorber -- so all of it is dropped on import and the
    radiation condition it stood for is put back on the outer surface,
    which is the equivalent open boundary here.
    """
    return bool(_PML_NAME.match(str(name or "").strip("'\" ")))


def collect_variables(doc: WarpDocument, design_blk: WarpBlock) -> VariableScope:
    """Project-level ``$vars`` plus design-local variables."""
    sc = VariableScope()
    for blk in list(doc.find("ProjectVariables")) + list(design_blk.find("Variables")) \
            + list(design_blk.find("LocalVariables")):
        for p in blk.props:
            if p.key:
                sc.set(p.key, p.value)
        for sub in blk.blocks:
            v = sub.get("Value", sub.get("VariableValue"))
            if v is not None:
                sc.set(sub.name, v)
    for blk in design_blk.find("VariableProp"):
        n = blk.get("Name")
        v = blk.get("Value")
        if n:
            sc.set(str(n), v)
    # Warps also writes flat  VariableProp('w', 'UD', '', '5mm')  statements
    for b in [design_blk] + list(design_blk.walk()):
        for p in b.props:
            if isinstance(p.value, Call) and p.value.name == "VariableProp" \
                    and len(p.value.args) >= 4:
                sc.set(str(p.value.args[0]), p.value.args[3])
    return sc


def collect_materials(doc: WarpDocument, lib: MaterialLibrary,
                      report: ImportReport) -> MaterialLibrary:
    """Read ``$begin 'Materials'`` definitions into the library."""
    for mats in doc.find("Materials"):
        for m in mats.blocks:
            if is_pml_name(m.name):
                # A PML group is a coordinate-stretched absorber, not a
                # material: its epsilon is a complex tensor that varies
                # through the layer. Importing it as a constant material
                # would be wrong, and the layer itself is dropped anyway
                # (see :func:`is_pml_name`), so the definition is skipped.
                continue
            try:
                lib.add(_material_from_block(m))
                report.materials.append(m.name)
            except Exception as exc:                    # pragma: no cover
                report.warnings.append(f"material {m.name!r}: {exc}")
    return lib


def _material_from_block(b: WarpBlock) -> Material:
    def num(key, default=0.0):
        v = b.get(key)
        if v is None:
            sub = b.block(key)
            if sub is not None:
                v = sub.get("property_value", sub.get("Magnitude"))
        if v is None:
            return default
        try:
            return float(evaluate(v))
        except Exception:
            try:
                return float(str(v).strip("'"))
            except Exception:
                return default

    eps = num("permittivity", 1.0)
    mu = num("permeability", 1.0)
    td = num("dielectric_loss_tangent", 0.0)
    mtd = num("magnetic_loss_tangent", 0.0)
    sig = num("conductivity", 0.0)
    kind = str(b.get("AetherKind") or
               ("conductor" if sig > 1e4 else "dielectric")).strip("'")
    color = str(b.get("AetherColor") or "#8899aa").strip("'")
    transp = b.get("AetherTransparency")
    return Material(b.name, ConstantTanD(eps, td), ConstantTanD(mu, mtd),
                    sigma=sig, kind=kind, color=color,
                    transparency=float(transp) if transp is not None else 0.6,
                    mass_density=num("mass_density", 0.0),
                    thermal_conductivity=num("thermal_conductivity", 0.0))


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------

_PARAM_BLOCKS = {
    "BoxParameters": "box",
    "CylinderParameters": "cylinder",
    "SphereParameters": "sphere",
    "ConeParameters": "cone",
    "TorusParameters": "torus",
    "PolylineParameters": "polyline",
    "RectangleParameters": "rectangle",
    "CircleParameters": "circle",
}

_AXIS = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}

# The folder the project being read lives in, so an imported body's copy can be
# found next to it. A ContextVar rather than a global: the GUI reads projects
# from worker threads.
_PROJECT_DIR: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "warp_project_dir", default="")
_PROJECT_DOC: "contextvars.ContextVar[Any]" = contextvars.ContextVar(
    "warp_project_doc", default=None)


def _resolve_cad(source: str, embedded: str) -> Tuple[str, bool]:
    """
    Where an imported body's CAD file actually is now.

    The copy kept beside the project wins, because it travels with the project;
    the recorded absolute path is the fallback for projects written before the
    copy existed, or when the sidecar folder was not carried along.
    """
    base = _PROJECT_DIR.get("")
    if embedded and base:
        cand = os.path.normpath(os.path.join(base, embedded))
        if os.path.isfile(cand):
            return cand, True
    if source:
        src = os.path.abspath(os.path.expanduser(source))
        if os.path.isfile(src):
            return src, True
        if base:
            # same file name next to the project, e.g. both were copied along
            cand = os.path.join(base, os.path.basename(src))
            if os.path.isfile(cand):
                return cand, True
    return (source or embedded or ""), False


def _q(blk: WarpBlock, key: str, sc: VariableScope, default=0.0,
       kind: str = "length") -> float:
    v = blk.get(key)
    if v is None:
        return default
    try:
        return evaluate(v, sc, kind)
    except Exception:
        return default


def _shape_from_params(kind: str, blk: WarpBlock, sc: VariableScope,
                       name: str) -> Optional[Shape]:
    if kind == "box":
        pos = (_q(blk, "XPosition", sc), _q(blk, "YPosition", sc),
               _q(blk, "ZPosition", sc))
        size = (_q(blk, "XSize", sc), _q(blk, "YSize", sc), _q(blk, "ZSize", sc))
        return Box(pos, size, name)
    if kind == "cylinder":
        c = (_q(blk, "XCenter", sc), _q(blk, "YCenter", sc), _q(blk, "ZCenter", sc))
        ax = _AXIS.get(str(blk.get("WhichAxis", "Z")).upper(), (0, 0, 1))
        return Cylinder(c, _q(blk, "Radius", sc), _q(blk, "Height", sc),
                        ax, name=name)
    if kind == "sphere":
        c = (_q(blk, "XCenter", sc), _q(blk, "YCenter", sc), _q(blk, "ZCenter", sc))
        return Sphere(c, _q(blk, "Radius", sc), name)
    if kind == "cone":
        c = (_q(blk, "XCenter", sc), _q(blk, "YCenter", sc), _q(blk, "ZCenter", sc))
        ax = _AXIS.get(str(blk.get("WhichAxis", "Z")).upper(), (0, 0, 1))
        return Cone(c, _q(blk, "BottomRadius", sc), _q(blk, "TopRadius", sc),
                    _q(blk, "Height", sc), ax, name)
    if kind == "torus":
        c = (_q(blk, "XCenter", sc), _q(blk, "YCenter", sc), _q(blk, "ZCenter", sc))
        ax = _AXIS.get(str(blk.get("WhichAxis", "Z")).upper(), (0, 0, 1))
        return Torus(c, _q(blk, "MajorRadius", sc), _q(blk, "MinorRadius", sc),
                     ax, name)
    if kind == "rectangle":
        pos = (_q(blk, "XStart", sc), _q(blk, "YStart", sc), _q(blk, "ZStart", sc))
        w = _q(blk, "Width", sc)
        h = _q(blk, "Height", sc)
        ax = str(blk.get("WhichAxis", "Z")).upper()
        plane = {"Z": "xy", "X": "yz", "Y": "xz"}.get(ax, "xy")
        from ...geometry.primitives import Rectangle
        return Rectangle(pos, (w, h), plane, name)
    if kind == "polyline":
        pts = []
        for seg in blk.find("PLPoint"):
            xyz = seg.get("X"), seg.get("Y"), seg.get("Z")
            if all(v is not None for v in xyz):
                pts.append(tuple(evaluate(v, sc) for v in xyz))
        if len(pts) >= 3:
            return Polygon(pts, name)
    return None


def _native_body_shape(part: WarpBlock, name: str,
                       report: ImportReport) -> Optional[Shape]:
    """
    A body Warps stored as a native (Parasolid ``.x_b``) attachment.

    Parasolid is a proprietary kernel format that OpenCASCADE cannot read, so
    the geometry itself cannot be rebuilt here. What can be done is everything
    else: the attachment is written out beside the project, the object is
    created with its name, material and place in the tree, and it is marked as
    needing a readable source. Boundaries, ports and setups that refer to it
    therefore survive the import, and one *Replace CAD Source* against a STEP
    export from Warps completes it -- which beats dropping the part and, with
    it, everything attached to it.
    """
    files = _native_body_files(part)
    if not files:
        return None
    from ...geometry.primitives import ImportedShape
    written = _extract_attachments(files)
    path = written[0] if written else files[0]
    shape = ImportedShape(path, name=name)
    shape._cad_unreadable = (
        "Parasolid (.x_b) is a proprietary format OpenCASCADE cannot read. "
        "In Warps: Modeler > Export > .step, then Modeler > Replace CAD Source.")
    if written:
        report.extracted.extend(written)
    return shape


def _extract_attachments(names: List[str]) -> List[str]:
    """
    Write the named attachments out of the project being read.

    ``AllReferencedFilesForProject`` carries them as length-prefixed binary
    blobs; they are unpacked into the same ``<project>.cad`` folder an imported
    body would be copied into, so the files are where the rest of the software
    already looks for them.
    """
    doc = _PROJECT_DOC.get(None)
    base = _PROJECT_DIR.get("")
    if doc is None or not base:
        return []
    stem = os.path.splitext(os.path.basename(getattr(doc, "source", "") or ""))[0]
    folder = os.path.join(base, (stem or "project") + ".cad")
    wanted = {os.path.basename(n): n for n in names}
    out: List[str] = []
    from .tree import WarpBinary
    for blk in doc.roots:
        if not isinstance(blk, WarpBlock):
            continue
        for sub in blk.walk():
            children = sub.children
            for i, node in enumerate(children):
                if not isinstance(node, WarpBinary):
                    continue
                # the statement before the payload is the attachment's path
                label = ""
                for prev in reversed(children[:i]):
                    if isinstance(prev, WarpProp):
                        label = str(prev.value if prev.key is None
                                    else prev.raw or "").strip()
                        break
                bn = os.path.basename(label.strip("'\""))
                if bn not in wanted:
                    continue
                try:
                    os.makedirs(folder, exist_ok=True)
                    dst = os.path.join(folder, bn)
                    with open(dst, "wb") as fh:
                        fh.write(node.data(getattr(doc, "encoding", "latin-1")))
                    out.append(dst)
                except OSError as exc:                     # pragma: no cover
                    log.warning("could not write attachment %s: %s", bn, exc)
    return out


def _part_ids(part: WarpBlock) -> List[int]:
    """
    The Warps body ids that name this part.

    Boundaries are written as ``Objects(1255)`` -- kernel body ids, not names --
    and the id of a part is the ``ParentPartID`` its operations carry. Reading
    every ``ID`` in the subtree instead would sweep up operation and face ids
    and attach boundaries to the wrong body.
    """
    ids: List[int] = []
    ops = part.block("Operations")
    for op in (ops.all_blocks("Operation") if ops is not None else []):
        v = op.get("ParentPartID")
        try:
            if v is not None and int(v) > 0:
                ids.append(int(v))
        except (TypeError, ValueError):
            continue
    at = part.block("Attributes")
    if at is not None:
        v = at.get("ID")
        try:
            if v is not None and int(v) > 0:
                ids.append(int(v))
        except (TypeError, ValueError):
            pass
    return sorted(set(ids))


def _native_body_files(part: WarpBlock) -> List[str]:
    """The attachment file names a native (Parasolid) body is stored in."""
    out: List[str] = []
    for bb in part.find("BodyBlock"):
        v = bb.get("BodyFileNamesVec")
        items = getattr(v, "items", None) or (v if isinstance(v, list) else [])
        for it in items:
            name = str(it).strip("'\" ")
            if name:
                out.append(name)
    return out


class _ItemGuard:
    """
    Read one boundary, port or setup without letting it take the rest down.

    A project is read for the whole model, and one property somewhere in it
    that cannot be evaluated -- an expression in a unit nobody anticipated, a
    variable that resolves to nothing -- is a reason to skip that one item and
    say so, never a reason to hand back no model at all. That failure mode is
    what "invalid decimal literal" looked like from the outside: a project
    that opened to an empty screen.
    """

    def __init__(self, report: ImportReport, what: str, name: str):
        self.report, self.what, self.name = report, what, name

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            return False
        if isinstance(exc, (KeyboardInterrupt, SystemExit, MemoryError)):
            return False
        self.report.unresolved.append(
            f"{self.what} {self.name!r}: {exc}")
        log.warning("%s %r skipped: %s", self.what, self.name, exc)
        return True                      # swallowed, on purpose


def read_geometry(design_blk: WarpBlock, sc: VariableScope, lib: MaterialLibrary,
                  design: Design, report: ImportReport) -> None:
    """Rebuild solids from the modeller's operation history."""
    # Only the top-level parts are objects in their own right. ``OperandParts``
    # holds the pieces consumed by booleans and sweeps; treating those as
    # objects duplicates geometry that is already inside another body.
    tops = design_blk.find("ToplevelParts")
    parts: List[WarpBlock] = []
    for t in tops:
        parts.extend(t.all_blocks("GeometryPart"))
    if not parts:
        parts = design_blk.find("GeometryPart")
    if not parts:
        parts = design_blk.find("Part")
    # The air region is built from the model's own extent, so it is read
    # after every other body -- there is nothing to pad around until then.
    deferred = [p for p in parts if _region_op(p) is not None]
    parts = [p for p in parts if _region_op(p) is None]
    for part in parts:
        attrs = part.block("Attributes") or part
        name = str(attrs.get("Name", f"Part{len(design.solids)+1}")).strip("'")
        candidates=[str(attrs.get(key,"") or "").strip("'\" ") for key in ("MaterialValue","MaterialName","Material")]
        mat=next((value for value in candidates if value),"")
        solve_inside = bool(attrs.get("SolveInside", True))
        if is_pml_name(name) or is_pml_name(mat):
            # dropped before any geometry work: it is the expensive part of
            # the import and none of it would be kept
            report.pml_parts.append(name)
            report.pml_ids.update(_part_ids(part))
            continue
        try:
            shape = _shape_from_part(part, sc, name, report)
        except Exception as exc:
            report.unresolved.append(f"part {name!r}: {exc}")
            continue
        if shape is None:
            try:
                shape = _box_from_topology(part, design.units)
            except (ValueError,TypeError,OverflowError):
                shape = None
            if shape is not None:
                report.warnings.append(f"part {name!r}: recovered rectangular body from six verified planar topology faces")
        if shape is None:
            shape = _native_body_shape(part, name, report)
        if shape is None:
            report.unresolved.append(
                f"part {name!r}: no supported creation command "
                "(imported/lofted/swept bodies need the STEP export path); operations: " +
                ", ".join(_history_types(part)))
            continue
        history=_history_types(part)
        if len(history)>1 and history[0]!='Create':
            report.unresolved.append(f"Incomplete history for {name!r}: {', '.join(history)}. Displayed geometry needs final-body verification or STEP replacement.")
        unresolved_material = str(attrs.get("AetherUnresolvedMaterial", "") or "")
        try:
            material = lib.get(mat)
        except KeyError:
            unresolved_material = mat or "(unspecified)"
            material = lib.get("vacuum")
            report.warnings.append(
                f"part {name!r}: material {mat!r} unknown; vacuum is a display placeholder. Assign the correct material before solving.")
        try:
            if bool(attrs.get("AetherIsSheet", False)):
                design.add_sheet(name, shape, material)
                obj = design.sheets[-1]
            else:
                design.add_solid(name, shape, material, solve_inside)
                obj = design.solids[-1]
            obj.import_material = unresolved_material
            col = attrs.get("AetherColor")
            if not col and history and history[0]!="Create" and attrs.get("Color"):
                rgb=re.findall(r"\d+",str(attrs.get("Color")))
                if len(rgb)==3:col='#'+''.join(f'{min(255,int(c)):02x}' for c in rgb)
            if col:
                obj.display_color = str(col).strip("'\"")
            tr = attrs.get("AetherTransparency", attrs.get("Transparency") if history and history[0]!="Create" else None)
            if tr is not None:
                obj.display_transparency = float(tr)
            if attrs.get("AetherVisible") is False:
                obj.visible = False
            report.solids.append(name)
            for pid in _part_ids(part):
                report.part_ids[pid] = name
        except ValueError as exc:
            report.warnings.append(str(exc))

    for part in deferred:
        _read_region(part, sc, lib, design, report)


_PADDING = re.compile(r"'([+-])([XYZ])Padding(Type)?'\s*=\s*'?([^'\n]*)'?")


def _region_op(part: WarpBlock) -> Optional[WarpBlock]:
    """The ``Region`` creation operation of an air-region part, if it is one."""
    ops = part.block("Operations")
    for op in (ops.all_blocks("Operation") if ops is not None else []):
        if str(op.get("OperationType", "")).strip("'") == "Region":
            return op
    return None


def _region_padding(op: WarpBlock) -> Dict[str, Tuple[str, str]]:
    """``{'+X': ('Absolute Offset', '30mm'), ...}`` from ``RegionParameters``."""
    out: Dict[str, Tuple[str, str]] = {}
    rp = op.block("RegionParameters")
    if rp is None:
        return out
    kinds: Dict[str, str] = {}
    values: Dict[str, str] = {}
    for pr in rp.props:
        m = _PADDING.search(str(pr.raw or pr.value or ""))
        if not m:
            continue
        key = m.group(1) + m.group(2)
        (kinds if m.group(3) else values)[key] = m.group(4).strip()
    for key, val in values.items():
        out[key] = (kinds.get(key, "Absolute Offset"), val)
    return out


def _read_region(part: WarpBlock, sc: VariableScope, lib: MaterialLibrary,
                 design: Design, report: ImportReport) -> None:
    """
    Rebuild the usual air ``Region`` as a padded box around the model.

    The region is the volume the solver actually fills, so an import that
    loses it produces a model that displays but cannot be meshed -- every
    remaining body is metal, and the solve has nowhere to put a field. Warps
    stores it as "the model bounding box, plus this much padding on each of
    the six sides", which is exactly reproducible here as long as the model
    it padded came in. Faces the user afterwards swept outward by hand are
    added on top when they all moved by the same distance; a mixed set is
    reported rather than guessed at.
    """
    attrs = part.block("Attributes") or part
    name = str(attrs.get("Name", "Region")).strip("'")
    have = [s for s in design.solids
            if not getattr(s.shape, "_cad_unreadable", "")
            and not getattr(s.shape, "_cad_missing", False)]
    boxes = []
    for s in have:
        try:
            lo, hi = s.shape.bounds()
        except Exception:
            continue
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        if np.all(np.isfinite(lo)) and np.all(np.isfinite(hi)) \
                and np.all(hi - lo > 0):
            boxes.append((lo, hi))
    if not boxes:
        report.unresolved.append(
            f"part {name!r}: the air region is defined as padding around the "
            "model, and no body in this design came in with usable geometry "
            "to pad. Replace the unreadable bodies with a STEP export, then "
            "re-create the region with Modeler > Create Air Region.")
        return
    lo = np.min([b[0] for b in boxes], axis=0)
    hi = np.max([b[1] for b in boxes], axis=0)
    span = hi - lo

    op = _region_op(part)
    pads = _region_padding(op) if op is not None else {}
    lo_pad = np.zeros(3)
    hi_pad = np.zeros(3)
    for i, axis in enumerate("XYZ"):
        for sign, arr in (("+", hi_pad), ("-", lo_pad)):
            kind, raw = pads.get(sign + axis, ("Absolute Offset", "0"))
            try:
                v = float(evaluate(raw, sc))
            except Exception:
                try:
                    v = to_si(str(raw))
                except Exception:
                    v = 0.0
            if "percent" in str(kind).lower():
                v = float(span[i]) * v / 100.0
            arr[i] = abs(v)

    # faces the user swept outward afterwards
    lengths = []
    for sw in part.find("SweepFaceAlongNormalToParameters"):
        try:
            lengths.append(abs(float(evaluate(sw.get("LengthOfSweep", 0.0), sc))))
        except Exception:
            continue
    if lengths:
        if len(set(round(v, 12) for v in lengths)) == 1 and len(lengths) >= 6:
            lo_pad += lengths[0]
            hi_pad += lengths[0]
        else:
            report.warnings.append(
                f"part {name!r}: {len(lengths)} region faces were swept by "
                "different distances in Warps; the largest is applied to all "
                "six. Check the air clearance before solving.")
            lo_pad += max(lengths)
            hi_pad += max(lengths)

    rlo = lo - lo_pad
    rhi = hi + hi_pad
    if np.any(rhi - rlo <= 0):
        report.unresolved.append(f"part {name!r}: region padding is degenerate")
        return
    mat = str(attrs.get("MaterialValue", "vacuum") or "vacuum").strip("'\" ")
    try:
        material = lib.get(mat)
    except KeyError:
        material = lib.get("vacuum")
    shape = Box(rlo, rhi - rlo, name)
    try:
        obj = design.add_solid(name, shape, material,
                               bool(attrs.get("SolveInside", True)))
    except ValueError as exc:
        report.warnings.append(str(exc))
        return
    obj.display_transparency = 0.9
    report.solids.append(name)
    for pid in _part_ids(part):
        report.part_ids[pid] = name
    report.warnings.append(
        f"part {name!r}: air region rebuilt from the model extent plus the "
        f"padding recorded in the project ({', '.join(f'{k} {v[1]}' for k, v in sorted(pads.items())) or 'none'})")


def _shape_from_part(part: WarpBlock, sc: VariableScope, name: str,
                     report: ImportReport) -> Optional[Shape]:
    """
    Rebuild one part's solid.

    Two paths, tried in order:

    1. **Aether-written structure** -- ``BooleanOperation`` / ``SweepOperation``
       / ``Transformations`` blocks describe the CSG tree exactly, so an
       Aether -> .warp -> Aether round trip reproduces the geometry rather than
       flattening a subtraction into a union.
    2. **Warps-native history** -- a tolerant recursive scan of the operation
       list for the creation commands and Move/Rotate/Scale transforms that
       map onto Aether primitives.  Anything else is reported.
    """
    ops = part.block("Operations")
    op_blocks = ops.all_blocks("Operation") if ops is not None else []
    for op in op_blocks:
        shape = _shape_from_command(op, sc, name)
        if shape is not None:
            return shape
    shape = _shape_from_command(part, sc, name)
    if shape is not None:
        return shape
    shape = _shape_from_history(part, sc, name, report)
    if shape is not None:
        supported={'box','cylinder','sphere','cone','torus','rectangle','circle','polyline','move','translate','rotate','scale','facecsplaceholder'}
        unsupported=[t for t in _history_types(part) if t.lower() not in supported]
        if unsupported:
            report.unresolved.append(f"Incomplete history for {name!r}: {', '.join(unsupported)}. Displayed primitive is not the final Warps body; replace with STEP.")
    return shape


def _shape_from_command(op: WarpBlock, sc: VariableScope,
                        name: str) -> Optional[Shape]:
    """Read the explicit CSG structure Aether writes (direct children only)."""
    shape: Optional[Shape] = None
    if op.get("AetherSketch"):
        import json
        from ...geometry.primitives import Sketch
        shape = Sketch(json.loads(op.get("AetherSketch")), name=name)

    bo = op.block("BooleanOperation")
    if bo is not None:
        kind = str(bo.get("BooleanType", "Union")).strip("'").lower()
        operands = []
        i = 1
        while True:
            child = bo.block(f"Operand{i}")
            if child is None:
                break
            sub = _shape_from_command(child, sc, name)
            if sub is None:
                return None                 # incomplete -- fall back
            operands.append(sub)
            i += 1
        if len(operands) < 2:
            return None
        if kind == "cut":
            shape = cut(operands[0], *operands[1:])
        elif kind == "intersect":
            shape = intersect(*operands)
        else:
            shape = union(*operands)

    if shape is None:
        sw = op.block("SweepOperation")
        if sw is not None:
            prof_blk = sw.block("Profile")
            profile = _shape_from_command(prof_blk, sc, name) \
                if prof_blk is not None else None
            if profile is None:
                return None
            stype = str(sw.get("SweepType", "Extrude")).strip("'").lower()
            if stype == "extrude":
                from ...geometry.primitives import Extrude
                vec = (_q(sw, "XVector", sc), _q(sw, "YVector", sc),
                       _q(sw, "ZVector", sc))
                shape = Extrude(profile, vec, name=name)
            else:
                from ...geometry.primitives import Revolve
                ax = _AXIS.get(str(sw.get("WhichAxis", "Z")).upper(), (0, 0, 1))
                ang = _q(sw, "SweepAngle", sc, 2 * math.pi, "angle")
                shape = Revolve(profile, ax, (0, 0, 0), ang, name=name)

    if shape is None:
        for bname in ("SweepFaceAlongNormalParameters", "MoveFacesParameters"):
            fb = op.block(bname)
            if fb is None or fb.get("AetherFaceOp") is None:
                continue
            base_blk = fb.block("BaseBody")
            base = _shape_from_command(base_blk, sc, name) \
                if base_blk is not None else None
            if base is None:
                break
            faces = []
            k = 1
            while True:
                f = fb.block(f"Face{k}")
                if f is None:
                    break
                faces.append({
                    "point": [_q(f, "Point" + a, sc) for a in "XYZ"],
                    "lo": [_q(f, "Lo" + a, sc) for a in "XYZ"],
                    "hi": [_q(f, "Hi" + a, sc) for a in "XYZ"],
                    "normal": [float(f.get("Normal" + a, 0.0) or 0.0)
                               for a in "XYZ"],
                    "planar": bool(f.get("Planar", True)),
                    "object": str(f.get("Object", "") or "").strip("'"),
                })
                k += 1
            from ...geometry.primitives import FaceOperation
            shape = FaceOperation(
                base, faces,
                str(fb.get("AetherFaceOp", "sweep")).strip("'"),
                _q(fb, "SweepDistance", sc), name=name)
            break

    if shape is None:
        ip = op.block("ImportParameters")
        if ip is not None:
            from ...geometry.primitives import ImportedShape
            src = str(ip.get("SourceFile", "") or "").strip("'\"")
            emb = str(ip.get("EmbeddedFile", "") or "").strip("'\"")
            path, found = _resolve_cad(src, emb)
            if path:
                unit = str(ip.get("ModelUnits", "auto") or "auto").strip("'\"")
                try:
                    scale = float(ip.get("ScaleToM", 1.0))
                except (TypeError, ValueError):
                    scale = 1.0
                heal = ip.get("HealGeometry", "auto")
                if isinstance(heal, bool):
                    heal = "always" if heal else "never"
                try:
                    body = int(ip.get("BodyIndex", -1))
                except (TypeError, ValueError):
                    body = -1
                shape = ImportedShape(path, name=name,
                                      healing=str(heal).strip("'\"") or "auto",
                                      scale_to_m=scale, unit=unit, body=body)
                shape._cad_missing = not found

    if shape is None:
        for bname, kind in _PARAM_BLOCKS.items():
            pb = op.block(bname)
            if pb is None:
                continue
            s = _shape_from_params(kind, pb, sc, name)
            if s is not None:
                shape = s
                break

    if shape is None:
        return None
    spec = op.get("AetherParameters")
    if spec:
        import json
        from ...parametric import make_primitive
        parsed = json.loads(spec)
        restored = make_primitive(parsed["kind"], parsed["params"], shape.name,
                                  sc.raw, parsed.get("units", "mm"))
        if hasattr(shape, "angle"):
            restored.angle = shape.angle
        shape = restored
    _apply_transform_block(op, shape)
    return shape


def _apply_transform_block(op: WarpBlock, shape: Shape) -> None:
    """Restore the recorded transform stack verbatim."""
    tb = op.block("Transformations")
    if tb is None:
        return
    for sub in tb.blocks:
        kind = sub.name.lower()
        d: Dict[str, Any] = {"op": kind}
        for pr in sub.props:
            if pr.key is None:
                continue
            v = pr.value
            d[pr.key] = tuple(float(x) for x in v) if isinstance(v, list) \
                else float(v)
        shape._xform.append(d)


def _shape_from_history(part: WarpBlock, sc: VariableScope, name: str,
                        report: ImportReport) -> Optional[Shape]:
    """Tolerant scan of an Warps-native modeller history."""
    shape: Optional[Shape] = None
    for opblk in part.find("Operation") or [part]:
        for bname, kind in _PARAM_BLOCKS.items():
            for pb in opblk.find(bname):
                s = _shape_from_params(kind, pb, sc, name)
                if s is None:
                    continue
                shape = s if shape is None else union(shape, s)
        ot = str(opblk.get("OperationType", "") or "").strip("'").lower()
        if shape is None:
            continue
        if ot in ("move", "translate"):
            mv = opblk.block("MoveParameters") or opblk
            shape.translate(_q(mv, "XComponent", sc), _q(mv, "YComponent", sc),
                            _q(mv, "ZComponent", sc))
        elif ot == "rotate":
            rb = opblk.block("RotateParameters") or opblk
            ax = _AXIS.get(str(rb.get("RotateAxis", "Z")).upper(), (0, 0, 1))
            shape.rotate(ax, _q(rb, "RotateAngle", sc, 0.0, "angle"))
        elif ot == "scale":
            sb = opblk.block("ScaleParameters") or opblk
            shape.scale(_q(sb, "ScaleX", sc, 1.0), _q(sb, "ScaleY", sc, 1.0),
                        _q(sb, "ScaleZ", sc, 1.0))
        elif ot in ("subtract", "unite", "intersect"):
            report.warnings.append(
                f"part {name!r}: boolean '{ot}' references other parts by id; "
                "the tool bodies are kept as separate solids")
    if shape is None:
        for bname, kind in _PARAM_BLOCKS.items():
            for pb in part.find(bname):
                s = _shape_from_params(kind, pb, sc, name)
                if s is not None:
                    shape = s if shape is None else union(shape, s)
    return shape


# --------------------------------------------------------------------------
# boundaries, ports, setups
# --------------------------------------------------------------------------


def read_boundaries(design_blk: WarpBlock, sc: VariableScope, design: Design,
                    lib: MaterialLibrary, report: ImportReport) -> None:
    for setup in _boundary_containers(design_blk):
        for b in setup.blocks:
            btype_raw = str(b.get("BoundType", b.get("BoundaryType", ""))
                            or "").strip("'")
            btype = BTYPE_MAP.get(btype_raw.lower())
            name = str(b.get("Name", b.name)).strip("'")
            if btype == "pml" or is_pml_name(name) or _touches_pml(b, report):
                # The layer is gone, so its boundary goes with it. What it
                # meant -- "this face is open" -- is recorded and re-applied
                # to the outer surface once the whole design is read.
                report.pml_boundaries.append(name)
                if btype in ("radiation", "pml"):
                    report.pml_radiation = True
                continue
            if btype is None:
                if b.get("ExcType") is not None:
                    continue
                if "port" in btype_raw.lower():
                    continue          # read as an excitation, not a boundary
                report.unresolved.append(
                    f"boundary {name!r}: unsupported type {btype_raw!r}")
                continue
            with _ItemGuard(report, "boundary", name):
                _read_one_boundary(b, btype, btype_raw, name, sc, design, lib,
                                   report)


def _touches_pml(b: WarpBlock, report: ImportReport) -> bool:
    """True when every body a boundary names was part of the dropped PML."""
    objs = b.get("Objects")
    if objs is None or not report.pml_ids:
        return False
    ids = []
    for o in _as_list(objs):
        try:
            ids.append(int(str(o).strip("'\" ")))
        except ValueError:
            return False
    return bool(ids) and all(i in report.pml_ids for i in ids)


def _read_one_boundary(b, btype, btype_raw, name, sc, design, lib, report):
    sel, note = _selector_for(b, design, report.part_ids)
    if sel is None:
        report.unresolved.append(
            f"boundary {name!r} ({btype_raw}): {note}")
        return
    params: Dict[str, Any] = {}
    if btype == "finite_cond":
        cond = b.get("UseMaterial")
        mname = str(b.get("Material", "copper")).strip("'\" ")
        try:
            params["material"] = lib.get(mname)
        except KeyError:
            params["material"] = lib.get("copper")
        if b.get("Thickness") is not None:
            params["thickness"] = evaluate(b.get("Thickness"), sc)
        if b.get("Roughness") is not None:
            params["roughness"] = evaluate(b.get("Roughness"), sc)
    elif btype == "impedance":
        rs = float(evaluate(b.get("Resistance", 0.0), sc, "resistance"))
        xs = float(evaluate(b.get("Reactance", 0.0), sc, "resistance"))
        params["Zs"] = complex(rs, xs)
    elif btype == "lumped_rlc":
        params.update(
            R=float(evaluate(b.get("Resistance", 0.0), sc, "resistance")),
            L=float(evaluate(b.get("Inductance", 0.0), sc)),
            C=float(evaluate(b.get("Capacitance", 0.0), sc)),
            parallel=bool(b.get("UseResist", True)))
    design.assign_boundary(name, btype, sel, **params)
    report.boundaries.append(f"{name} [{btype}]")


def _selector_from_block(blk: WarpBlock, design: Design):
    """Rebuild an Aether selector written by :func:`writer.write_selector`."""
    from ...geometry.select import (BoundingBoxFaceSelector, BoxSelector,
                                    CylinderSelector, OuterSelector,
                                    PlaneSelector, ShapeSelector)
    kind = str(blk.get("Kind", "Outer")).strip("'")
    if kind == "Plane":
        win = blk.get("Window")
        return PlaneSelector(str(blk.get("Axis", "z")), float(blk.get("Value", 0.0)),
                             tol=float(blk.get("Tol", 1e-9)),
                             window=win if win else None)
    if kind == "Box":
        return BoxSelector(blk.get("Lo", [0, 0, 0]), blk.get("Hi", [1, 1, 1]),
                           float(blk.get("Tol", 1e-9)))
    if kind == "Cylinder":
        return CylinderSelector(blk.get("Center", [0, 0, 0]),
                                blk.get("Axis", [0, 0, 1]),
                                float(blk.get("Radius", 1.0)),
                                float(blk.get("Height", 1.0)))
    if kind == "BBoxFace":
        return BoundingBoxFaceSelector(str(blk.get("Face", "+z")).strip("'"))
    if kind == "Shape":
        names = [str(o).strip("'") for o in (blk.get("Objects") or [])]
        shapes = []
        for n in names:
            try:
                shapes.append(design.get_solid(n).shape)
            except KeyError:
                pass
        if shapes:
            from ...geometry.primitives import union as _u
            return ShapeSelector(shapes[0] if len(shapes) == 1 else _u(*shapes),
                                 tol=1e-7)
    return OuterSelector()


def _as_list(v) -> List[Any]:
    """Flatten the several shapes Warps uses for an object/face list."""
    items = getattr(v, "items", None)
    if items is not None:
        return list(items)
    args = getattr(v, "args", None)
    if args is not None:
        return list(args)
    if isinstance(v, (list, tuple)):
        return list(v)
    return [v]


def _boundary_containers(design_blk: WarpBlock) -> List[WarpBlock]:
    """
    Every block that directly holds boundary or excitation definitions.

    Older projects list them straight under ``BoundarySetup``; the desktop
    writes them one level down, in ``Boundaries``. Reading only the outer
    block finds a project's boundaries in one layout and none at all in the
    other.
    """
    out: List[WarpBlock] = []
    for setup in list(design_blk.find("BoundarySetup")) + \
            list(design_blk.find("Excitations")):
        inner = [c for c in setup.blocks
                 if c.name in ("Boundaries", "Excitations", "Ports")]
        out.extend(inner or [setup])
    return out


def _selector_for(b: WarpBlock, design: Design,
                  part_ids: Optional[Dict[int, str]] = None):
    """Best-effort geometric re-attachment of an Warps boundary."""
    aether = b.block("AetherSelector")
    if aether is not None:
        return _selector_from_block(aether, design), ""
    objs = b.get("Objects")
    if objs is None:
        objs = b.get("Faces")
        if objs is not None:
            return None, ("attached to kernel face ids "
                          f"{_as_list(objs)[:6]}; re-assign it by picking the "
                          "faces in the modeller")
    if objs is None:
        return OuterSelector(), ""
    # Warps writes body ids here, not names; the map is built while the parts
    # are read. A name is still accepted, for projects Aether wrote itself.
    ids = part_ids or {}
    names = []
    for o in _as_list(objs):
        token = str(o).strip("'\" ")
        try:
            names.append(ids.get(int(token), token))
        except ValueError:
            names.append(token)
    shapes = []
    for n in names:
        try:
            shapes.append(design.get_solid(n).shape)
        except KeyError:
            pass
    if not shapes:
        return None, f"objects {names} not found in the model"
    shp = shapes[0] if len(shapes) == 1 else union(*shapes)
    return ShapeSelector(shp, tol=1e-7), ""


def read_excitations(design_blk: WarpBlock, sc: VariableScope, design: Design,
                     report: ImportReport) -> None:
    for setup in _boundary_containers(design_blk):
        for b in setup.blocks:
            etype = str(b.get("ExcType", b.get("BoundType", "")) or "").strip("'")
            low = etype.lower()
            if "wave port" not in low and "lumped port" not in low \
                    and low not in ("waveport", "lumpedport"):
                continue
            name = str(b.get("Name", b.name)).strip("'")
            if is_pml_name(name) or _touches_pml(b, report):
                report.pml_boundaries.append(name)
                continue
            with _ItemGuard(report, "port", name):
                _read_one_port(b, low, etype, name, sc, design, report)


def _read_one_port(b, low, etype, name, sc, design, report):
    sel, note = _selector_for(b, design, report.part_ids)
    if sel is None:
        report.unresolved.append(f"port {name!r}: {note}")
        return
    nmodes = int(b.get("NumModes", 1) or 1)
    deembed = 0.0
    if b.get("DoDeembed"):
        deembed = float(evaluate(b.get("DeembedDist", 0.0), sc))
    renorm = None
    if b.get("RenormImp") is not None:
        try:
            renorm = float(evaluate(b.get("RenormImp"), sc, "resistance"))
        except Exception:
            renorm = None
    if "lumped" in low:
        z = b.get("Impedance")
        try:
            zp = complex(evaluate(z, sc, "resistance")) if z is not None \
                else complex(renorm or 50.0)
        except Exception:
            zp = complex(renorm or 50.0)
        direction = b.get("Direction") or [0.0, 0.0, 1.0]
        il = _integration_line(b, sc)
        design.add_lumped_port(name, selector=sel, impedance=zp,
                               direction=[float(x) for x in direction],
                               integration_line=il)
    else:
        design.add_wave_port(name, selector=sel, num_modes=nmodes,
                             deembed=deembed, renormalize_z=renorm,
                             integration_line=_integration_line(b, sc))
    report.ports.append(f"{name} [{etype}]")


def _integration_line(b: WarpBlock, sc: VariableScope):
    """Recover a port integration line, if one was stored."""
    il = b.block("IntLine")
    if il is None:
        return None
    pts = []
    for tag in ("Start", "End"):
        sub = il.block(tag)
        if sub is None:
            return None
        pts.append(tuple(_q(sub, k, sc) for k in ("X", "Y", "Z")))
    return (pts[0], pts[1])


def read_setups(design_blk: WarpBlock, sc: VariableScope, design: Design,
                report: ImportReport) -> None:
    for asetup in design_blk.find("AnalysisSetup"):
        for solve in (asetup.find("SolveSetups") or [asetup]):
            for s in solve.blocks:
                with _ItemGuard(report, "setup",
                                str(s.get("Name", s.name)).strip("'")):
                    _read_one_setup(s, sc, design, report)
    if not design.setups:
        for s in design_blk.find("SolveSetup"):
            with _ItemGuard(report, "setup",
                            str(s.get("Name", s.name)).strip("'")):
                _read_one_setup(s, sc, design, report)


def _read_one_setup(s: WarpBlock, sc: VariableScope, design: Design,
                    report: ImportReport) -> None:
    props = s.block("SolveSetupProps") or s
    freq = props.get("Frequency", props.get("SolutionFrequency", "1GHz"))
    eigen = (props.get("NumModes") is not None
             or "eigen" in str(s.get("SetupType", "")).lower())
    try:
        f = float(evaluate(freq, sc, "frequency"))
    except Exception:
        f = 1e9
    if eigen and props.get("Frequency") is None:
        # an Warps eigenmode setup has no solution frequency; the minimum
        # frequency is the only frequency scale it carries
        try:
            fmin = float(evaluate(props.get("MinimumFrequency", "0Hz"), sc,
                                  "frequency"))
        except Exception:
            fmin = 0.0
        f = 2.0 * fmin if fmin > 0 else f
    name = str(s.get("Name", s.name)).strip("'")
    st = design.add_setup(name, f,
                          max_passes=int(props.get("MaximumPasses", 6) or 6),
                          delta_s=float(props.get("MaxDeltaS", 0.02) or 0.02))
    st.min_passes = max(1, int(props.get("MinimumPasses", 1) or 1))
    try:
        st.min_converged = max(1, int(props.get("MinimumConvergedPasses", 1) or 1))
        pr = props.get("PercentRefinement")
        if pr is not None:
            st.refinement = min(max(float(pr) / 100.0, 0.01), 1.0)
    except (TypeError, ValueError):
        pass
    # Warps writes 0 for "mixed order" and -1 for "zeroth order"; neither has
    # an Aether equivalent, and both used to import verbatim and then fail
    # validation with "basis order must be 1 or 2" on a setup the user never
    # touched. The nearest supported element order is used instead.
    try:
        order = int(props.get("BasisOrder", 1))
    except (TypeError, ValueError):
        order = 1
    if order not in (1, 2):
        report.warnings.append(
            f"setup {name!r}: basis order {order} (Warps mixed/zeroth order) "
            "has no equivalent here; first-order elements are used")
        order = 1
    st.basis_order = order
    if eigen:
        try:
            st.n_modes = max(1, int(props.get("NumModes", 3) or 3))
            st.min_frequency = float(evaluate(props.get("MinimumFrequency",
                                                        "0Hz"), sc, "frequency"))
            st.delta_f = min(max(float(props.get("MaxDeltaFreq", 2.0)) / 100.0,
                                 1e-4), 0.5)
        except Exception:
            report.warnings.append(
                f"setup {name!r}: eigenmode settings could not be read; "
                "defaults are used")
    report.setups.append(name)
    for sw in s.find("Sweep") + s.find("SweepSetupProps"):
        rtype = str(sw.get("RangeType", "LinearCount") or "").strip("'")
        try:
            a = float(evaluate(sw.get("RangeStart", freq), sc, "frequency"))
            b = float(evaluate(sw.get("RangeEnd", freq), sc, "frequency"))
        except Exception:
            continue
        kind = {"Fast": "fast", "Interpolating": "interpolating"}.get(
            str(sw.get("Type", "Discrete")).strip("'"), "discrete")
        swname = str(sw.get("Name", "Sweep")).strip("'")
        if rtype.lower().startswith("linearstep"):
            step = float(evaluate(sw.get("RangeStep", (b - a) or 1.0), sc,
                                  "frequency"))
            n = int(round((b - a) / step)) + 1 if step else 2
            st.add_sweep(swname, a, b, n, kind, "step" if step else "linear",
                         step=step or None)
        elif rtype.lower().startswith("singlepoint"):
            st.add_sweep(swname, a, a, 1, kind, "single")
        elif rtype.lower().startswith("log"):
            st.add_sweep(swname, a, b, int(sw.get("RangeSamples", 101) or 101),
                         kind, "log")
        else:
            st.add_sweep(swname, a, b,
                         int(sw.get("RangeCount", 101) or 101), kind)
        st.sweeps[-1].save_fields = bool(sw.get("SaveFields", False))
        # Warps stores the interpolating tolerance as a percentage of |S|
        try:
            if sw.get("InterpTolerance") is not None and kind != "discrete":
                st.sweeps[-1].tolerance = min(
                    max(float(sw.get("InterpTolerance")) / 100.0, 1e-6), 0.5)
            if sw.get("InterpMaxSolns") is not None and kind != "discrete":
                st.sweeps[-1].max_points = max(int(sw.get("InterpMaxSolns")), 4)
        except (TypeError, ValueError):
            pass
        points = sw.get("AetherFrequencyPoints")
        if points is not None:
            st.sweeps[-1].points = [float(v) for v in points]


# --------------------------------------------------------------------------


def read_design(doc: WarpDocument, index: int = 0,
                lib: Optional[MaterialLibrary] = None
                ) -> Tuple[Design, ImportReport]:
    """Translate one Warps design out of a parsed project document."""
    designs = doc.warps_designs() or doc.designs()
    if not designs:
        raise ValueError("project contains no design blocks")
    blk = designs[index]
    name = str(blk.get("Name", f"Design{index+1}")).strip("'")
    stype_raw = str(blk.get("SolutionType", blk.get("DesignType", "")) or "")
    stype = SOLUTION_MAP.get(stype_raw.strip("'").lower(), "driven_modal")
    report = ImportReport(design_name=name)

    lib = lib or MaterialLibrary()
    collect_materials(doc, lib, report)
    sc = collect_variables(doc, blk)

    units = "mm"
    for m in blk.find("GeometryOperations") + blk.find("ModelUnits") + blk.find("Editor"):
        u = m.get("ModelUnits") or m.get("Units")
        if u:
            units = str(u).strip("'")
            break

    design = Design(name, stype, units=units, materials=lib)
    design.variables = dict(sc.raw)
    if blk.get("AetherConfig"):
        import json
        from ...core.config import Config
        design.config = Config.from_dict(json.loads(blk.get("AetherConfig")))
    design.default_boundary = str(blk.get("AetherDefaultBoundary", "pec"))
    token = _PROJECT_DIR.set(os.path.dirname(os.path.abspath(doc.source))
                             if getattr(doc, "source", None) else "")
    dtoken = _PROJECT_DOC.set(doc)
    design._warp_source = doc

    try:
        read_geometry(blk, sc, lib, design, report)
        read_boundaries(blk, sc, design, lib, report)
        read_excitations(blk, sc, design, report)
        read_setups(blk, sc, design, report)
        for mesh in blk.find("AetherMeshOperations"):
            for item in mesh.blocks:
                selector = item.block("AetherSelector")
                op = design.add_mesh_operation(str(item.get("Name", "Mesh")),
                    max_length=float(item.get("MaxLength", 0.0)),
                    objects=list(item.get("Objects") or []),
                    selector=_selector_from_block(selector, design) if selector else None,
                    enabled=bool(item.get("Enabled", True)))
                op.kind = str(item.get("Kind", "length"))
    finally:
        _PROJECT_DIR.reset(token)
        _PROJECT_DOC.reset(dtoken)

    if report.pml_parts or report.pml_boundaries:
        report.warnings.append(
            f"dropped {len(report.pml_parts)} PML layer(s) and "
            f"{len(report.pml_boundaries)} PML boundary/boundaries; the "
            "original model is imported without them")
    if report.pml_radiation and not any(b.btype == "radiation"
                                        for b in design.boundaries):
        design.assign_boundary("Radiation1", "radiation", OuterSelector())
        report.boundaries.append("Radiation1 [radiation]")
        report.warnings.append(
            "the PML wrapper was replaced by a Radiation boundary on the "
            "outer surface -- check the air clearance is at least a quarter "
            "wavelength before solving")

    # An imported body whose CAD file is gone is loaded anyway (so the model
    # keeps its structure, its boundaries and its ports) and said out loud --
    # the file can be pointed at again from the modeller.
    for so in design.solids:
        if getattr(so.shape, "_cad_missing", False):
            report.warnings.append(
                f"part {so.name!r}: CAD source "
                f"{os.path.basename(getattr(so.shape, 'path', '') or '?')!r} "
                "not found next to the project or at its recorded path; "
                "use Modeler > Replace CAD source to point at it")

    import json
    previous=json.loads(blk.get("AetherImportIssues", "[]"))
    design.import_issues=list(dict.fromkeys(previous+report.unresolved))
    log.info("imported Warps design %r: %d solids, %d boundaries, %d ports, "
             "%d setups (%d unresolved)", name, len(report.solids),
             len(report.boundaries), len(report.ports), len(report.setups),
             len(report.unresolved))
    return design, report


def read_project(path: str, progress=None) -> Tuple[Project, List[ImportReport]]:
    """
    Load a whole ``.warp`` / ``.warpz`` file.

    ``progress`` is an optional ``callable(stage: str, done: int, total: int)``.
    A large project spends real seconds parsing the Warps tree and unpacking a
    ``.warpz`` archive before a single design appears, and a caller that can
    report that -- the desktop workspace does -- needs to be told where it is.
    """
    def say(stage, done=0, total=0):
        if progress is not None:
            try:
                progress(stage, done, total)
            except Exception:                       # pragma: no cover
                pass

    say("parsing the project file")
    doc = WarpDocument.parse(path)
    if str(path).lower().endswith(".warpz"):
        say("unpacking the archive")
        import zipfile, hashlib, tempfile, shutil
        with open(path, "rb") as stream:
            digest=hashlib.sha256(stream.read()).hexdigest()
        folder=os.path.join(tempfile.gettempdir(),"aether-archives",digest)
        with zipfile.ZipFile(path) as archive:
            projects=sorted([n for n in archive.namelist() if n.lower().endswith(".warp")],key=len)
            if not projects:raise ValueError("Archive contains no Warps project")
            total=0
            for entry in archive.infolist():
                name=entry.filename.replace("\\","/")
                parts=name.split("/")
                if name.startswith("/") or ":" in name or any(p in (".","..") for p in parts):
                    raise ValueError("Unsafe archive member")
                if entry.is_dir():continue
                # Preserve relative CAD references including nested project folders.
                ext=os.path.splitext(name)[1].lower()
                if ext not in (".warp",".step",".stp",".iges",".igs",".brep",".stl",".obj",".dxf",".x_b",".x_t",".sat",".sab"):
                    continue
                total+=entry.file_size
                if total>1024*1024*1024:raise ValueError("CAD archive exceeds 1 GiB unpacked limit")
                dst=os.path.join(folder,*parts);os.makedirs(os.path.dirname(dst),exist_ok=True)
                with archive.open(entry) as src,open(dst,"wb") as out:shutil.copyfileobj(src,out)
        doc.source=os.path.join(folder,*projects[0].replace("\\","/").split("/"))
    proj = Project(os.path.splitext(os.path.basename(path))[0])
    proj.warp_tree = doc
    reports = []
    n = len(doc.warps_designs() or doc.designs())
    for i in range(n):
        say(f"reading design {i + 1} of {n}", i, n)
        d, r = read_design(doc, i)
        proj.add_design(d)
        reports.append(r)
        say(f"read design {d.name!r}", i + 1, n)
    return proj, reports


__all__ = ["read_design", "read_project", "ImportReport", "collect_variables",
           "collect_materials"]


def _history_types(part):
    ops=part.block('Operations')
    return [str(b.get('OperationType')) for b in (ops.children if ops else [])
            if isinstance(b,WarpBlock) and b.get('OperationType')]


def _box_from_topology(part, units):
    """Only reconstruct a final, single-operation axis-aligned rectangular body.

    Never interpret a bounding box of arbitrary or historical topology as a solid.
    Later operations, curved faces, missing corners or area mismatches reject it.
    """
    import itertools
    import numpy as np
    if _history_types(part) != ['SweepFaceAlongNormalFrom']:return None
    groups=part.find('NewFaces')
    if len(groups)!=1:return None
    faces=groups[0].all_blocks('Face')
    if len(faces)!=6:return None
    polygons=[];areas=[]
    for face in faces:
        geometries=face.find('FaceGeometry')
        if len(geometries)!=1:return None
        g=geometries[0];vts=g.block('FcTolVts')
        if vts is None:return None
        pts=[list(p.value.args[:3]) for p in vts.children if getattr(p,'key',None)=='TolVt' and hasattr(p.value,'args')]
        if len(pts)!=4:return None
        a=np.asarray(pts,float)
        if len(np.unique(a,axis=0))!=4:return None
        span=np.ptp(a,axis=0);fixed=np.flatnonzero(span<1e-8)
        if len(fixed)!=1:return None
        expected=float(np.prod(span[span>=1e-8]))
        if not np.isclose(float(g.get('Area',-1)),expected,rtol=1e-7,atol=1e-8):return None
        polygons.append(a);areas.append(expected)
    allpts=np.unique(np.concatenate(polygons),axis=0)
    if len(allpts)!=8:return None
    lo=allpts.min(0);hi=allpts.max(0)
    corners=np.array(list(itertools.product(*zip(lo,hi))))
    if any(np.min(np.linalg.norm(allpts-p,axis=1))>1e-8 for p in corners):return None
    keys={tuple(sorted(map(tuple,a))) for a in polygons}
    if len(keys)!=6:return None
    scale=to_si('1'+units)
    return Box(lo*scale,(hi-lo)*scale)
