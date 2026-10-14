"""
Writing Aether models back out as ``.aedt`` projects.

Two modes, and the difference matters:

``update``  -- you loaded a real HFSS project, changed a few things, and want
               it back.  The original tree is edited *in place*: only the
               statements you touched are re-rendered, everything else keeps
               its exact original bytes.  Nothing HFSS wrote and Aether does
               not model (mesh operations, optimetrics, report definitions,
               field overlays, design settings) can be lost, because it is
               never rewritten.

``create``  -- you built the model in Aether and want an HFSS project.  A
               complete tree is generated from scratch following the AEDT
               layout: AnsoftProject > Desktop / Design > (Materials,
               ModelSetup > ToplevelParts, BoundarySetup, AnalysisSetup).
"""
from __future__ import annotations

import datetime
import math
import os
import shutil
from typing import Any, Dict, List, Optional

import numpy as np

from ...core.constants import from_si
from ...core.logging import get_logger
from ...core.materials import Material
from ...geometry.primitives import (Box, Cone, Cylinder, Polygon, Shape,
                                    Sphere, Torus)
from .tree import AedtBlock, AedtDocument, AedtProp
from .values import Call, Counted

log = get_logger("io.aedt.writer")

AEDT_VERSION = (2024, 2)
AXIS_NAME = {(1, 0, 0): "X", (0, 1, 0): "Y", (0, 0, 1): "Z"}

REV_BTYPE = {
    "pec": "Perfect E", "pmc": "Perfect H", "radiation": "Radiation",
    "finite_cond": "Finite Conductivity", "impedance": "Impedance",
    "lumped_rlc": "Lumped RLC", "symmetry_e": "Symmetry",
    "symmetry_h": "Symmetry", "pml": "Perfectly Matched Layer",
}
REV_SOLUTION = {
    "driven_modal": "HFSS Modal Network",
    "driven_terminal": "HFSS Terminal Network",
    "eigenmode": "HFSS Eigenmode",
}


def _len(v: float, units: str) -> str:
    return f"{from_si(v, units):.12g}{units}"


def _freq(v: float) -> str:
    for unit, scale in (("GHz", 1e9), ("MHz", 1e6), ("kHz", 1e3), ("Hz", 1.0)):
        if abs(v) >= scale:
            return f"{v/scale:.12g}{unit}"
    return f"{v:g}Hz"


# ==========================================================================
# create mode
# ==========================================================================


def build_document(project_name: str, designs: List) -> AedtDocument:
    """Generate a complete AEDT project tree for the given designs."""
    root = AedtBlock("AnsoftProject")
    root.add_prop("FileVersion", Call("FileVersion", [1, 0]))
    root.add_prop("Created", datetime.datetime.now()
                  .strftime("%a %b %d %H:%M:%S %Y"))
    root.add_prop("Product", "ElectronicsDesktop")
    root.add_prop("BuildVariant", "Aether-EM")

    desktop = root.add_block("Desktop")
    desktop.add_prop("Version", Call("Version", list(AEDT_VERSION)))
    desktop.add_prop("InfoAsciiString", f"Written by Aether-EM")

    mats = root.add_block("Materials")
    seen = set()
    for d in designs:
        for material_name in d.materials.names():
            material = d.materials.get(material_name)
            if material.name.lower() in seen:
                continue
            seen.add(material.name.lower())
            _write_material(mats, material, d.setups[0].frequency
                            if d.setups else 1e9)

    for d in designs:
        _write_design(root, d)

    doc = AedtDocument([root, AedtProp(None, "", raw="", blank=True)])
    return doc


def _write_material(parent: AedtBlock, m: Material, f: float) -> AedtBlock:
    b = parent.add_block(m.name)
    b.add_prop("CoordinateSystemType", "Cartesian")
    b.add_prop("BulkOrSurfaceType", 1)
    ph = b.add_block("PhysicsTypes")
    ph.add_prop("set", ["Electromagnetic"])
    eps = m.eps_model.eps(f)      # conduction is written separately
    mu = m.mu_model.eps(f)
    b.add_prop("permittivity", f"{eps.real:.10g}")
    b.add_prop("permeability", f"{mu.real:.10g}")
    if m.sigma:
        b.add_prop("conductivity", f"{m.sigma:.10g}")
    td = (-eps.imag / eps.real) if eps.real else 0.0
    if abs(td) > 0:
        b.add_prop("dielectric_loss_tangent", f"{td:.10g}")
    mtd = (-mu.imag / mu.real) if mu.real else 0.0
    if abs(mtd) > 0:
        b.add_prop("magnetic_loss_tangent", f"{mtd:.10g}")
    if m.mass_density:
        b.add_prop("mass_density", f"{m.mass_density:.10g}")
    if m.thermal_conductivity:
        b.add_prop("thermal_conductivity", f"{m.thermal_conductivity:.10g}")
    b.add_prop("AetherKind", m.kind)
    b.add_prop("AetherColor", m.color)
    b.add_prop("AetherTransparency", float(m.transparency))
    return b


def _write_design(root: AedtBlock, d) -> AedtBlock:
    blk = root.add_block("Design")
    blk.add_prop("DesignType", "HFSS")
    blk.add_prop("Name", d.name)
    blk.add_prop("SolutionType", REV_SOLUTION.get(d.solution_type,
                                                  "HFSS Modal Network"))
    blk.add_prop("DesignVersion", 1)
    import json
    blk.add_prop("AetherConfig", json.dumps(d.config.to_dict()))
    blk.add_prop("AetherImportIssues", json.dumps(getattr(d,"import_issues",[]),ensure_ascii=False))
    blk.add_prop("AetherDefaultBoundary", getattr(d, "default_boundary", "pec"))

    if d.variables:
        var = blk.add_block("Variables")
        for k, v in d.variables.items():
            var.add_prop(str(k), str(v))

    ms = blk.add_block("ModelSetup")
    ms.add_prop("DesignDataId", 1)
    props = ms.add_block("Properties")
    props.add_prop("VersionID", 1)
    geom = ms.add_block("GeometryCore")
    geom.add_prop("BlockVersionID", 3)
    gops = geom.add_block("GeometryOperations")
    gops.add_prop("ModelUnits", d.units)
    parts = gops.add_block("ToplevelParts")
    for i, s in enumerate(d.solids, start=1):
        _write_part(parts, s, d.units, i)
    for i, sh in enumerate(d.sheets, start=len(d.solids) + 1):
        _write_part(parts, sh, d.units, i, sheet=True)

    bs = blk.add_block("BoundarySetup")
    bs.add_prop("MapCoefficients", False)
    for b in d.boundaries:
        _write_boundary(bs, b, d)
    for p in d.ports:
        _write_port(bs, p, d)

    if d.mesh_ops:
        mesh = blk.add_block("AetherMeshOperations")
        for op in d.mesh_ops:
            item = mesh.add_block("Operation")
            item.add_prop("Name", op.name)
            item.add_prop("MaxLength", float(op.max_length))
            item.add_prop("Objects", list(op.objects))
            item.add_prop("Enabled", bool(op.enabled))
            item.add_prop("Kind", op.kind)
            if op.selector is not None:
                write_selector(item, op.selector, d)
    an = blk.add_block("AnalysisSetup")
    ss = an.add_block("SolveSetups")
    for st in d.setups:
        _write_setup(ss, st, eigen=(d.solution_type == "eigenmode"))
    return blk


def _write_part(parent: AedtBlock, solid, units: str, pid: int,
                sheet: bool = False) -> AedtBlock:
    part = parent.add_block("GeometryPart")
    att = part.add_block("Attributes")
    att.add_prop("Name", solid.name)
    att.add_prop("Flags", "" if not sheet else "NonModel#")
    mat = getattr(solid, "material", None)
    att.add_prop("MaterialValue", f'"{mat.name}"' if mat else '"vacuum"')
    att.add_prop("SolveInside", bool(getattr(solid, "solve_inside", True)))
    att.add_prop("PartCoordinateSystem", "Global")
    att.add_prop("Transparency", float(getattr(solid, "transparency", 0.5)))
    att.add_prop("Color", Call("Color",
                               list(_rgb(getattr(solid, "color", None)
                                         or (mat.color if mat else "#808080")))))
    # Per-object display and sheet-ness are Aether's own, and a project has to
    # come back looking like it did: a sheet that reopens as a solid is a
    # different model.
    att.add_prop("AetherIsSheet", bool(sheet))
    if getattr(solid,"import_material",""):
        att.add_prop("AetherUnresolvedMaterial",solid.import_material)
    if getattr(solid, "display_color", None):
        att.add_prop("AetherColor", solid.display_color)
    if getattr(solid, "display_transparency", None) is not None:
        att.add_prop("AetherTransparency", float(solid.display_transparency))
    if not getattr(solid, "visible", True):
        att.add_prop("AetherVisible", False)

    ops = part.add_block("Operations")
    op = ops.add_block("Operation")
    op.add_prop("OperationType", "Create")
    op.add_prop("ID", pid)
    op.add_prop("ParentPartID", pid)
    cmd = op.add_block("GeometryPosition")
    cmd.add_prop("PartID", pid)
    _write_primitive(op, solid.shape, units)
    return part


def _write_primitive(op: AedtBlock, shape: Shape, units: str) -> None:
    from ...geometry.primitives import (Boolean, Extrude, FaceOperation,
                                        ImportedShape, Revolve)
    if getattr(shape, "_parametric", None):
        import json
        op.add_prop("AetherParameters", json.dumps(shape._parametric, ensure_ascii=False))
    from ...geometry.primitives import Sketch
    if isinstance(shape, Sketch):
        import json
        op.add_prop("AetherSketch", json.dumps(shape.paths))
    elif isinstance(shape, Box):
        b = op.add_block("BoxParameters")
        for k, v in zip(("XPosition", "YPosition", "ZPosition"), shape.position):
            b.add_prop(k, _len(v, units))
        for k, v in zip(("XSize", "YSize", "ZSize"), shape.size):
            b.add_prop(k, _len(v, units))
    elif isinstance(shape, Cylinder):
        b = op.add_block("CylinderParameters")
        for k, v in zip(("XCenter", "YCenter", "ZCenter"), shape.center):
            b.add_prop(k, _len(v, units))
        b.add_prop("Radius", _len(shape.radius, units))
        b.add_prop("Height", _len(shape.height, units))
        b.add_prop("WhichAxis", _axis_name(shape.axis))
        b.add_prop("NumSides", "0")
    elif isinstance(shape, Sphere):
        b = op.add_block("SphereParameters")
        for k, v in zip(("XCenter", "YCenter", "ZCenter"), shape.center):
            b.add_prop(k, _len(v, units))
        b.add_prop("Radius", _len(shape.radius, units))
    elif isinstance(shape, Cone):
        b = op.add_block("ConeParameters")
        for k, v in zip(("XCenter", "YCenter", "ZCenter"), shape.center):
            b.add_prop(k, _len(v, units))
        b.add_prop("BottomRadius", _len(shape.r1, units))
        b.add_prop("TopRadius", _len(shape.r2, units))
        b.add_prop("Height", _len(shape.height, units))
        b.add_prop("WhichAxis", _axis_name(shape.axis))
    elif isinstance(shape, Torus):
        b = op.add_block("TorusParameters")
        for k, v in zip(("XCenter", "YCenter", "ZCenter"), shape.center):
            b.add_prop(k, _len(v, units))
        b.add_prop("MajorRadius", _len(shape.r_major, units))
        b.add_prop("MinorRadius", _len(shape.r_minor, units))
        b.add_prop("WhichAxis", _axis_name(shape.axis))
    elif isinstance(shape, Polygon):
        b = op.add_block("PolylineParameters")
        b.add_prop("IsPolylineCovered", True)
        b.add_prop("IsPolylineClosed", True)
        pts = b.add_block("PolylinePoints")
        for p in shape.points:
            pb = pts.add_block("PLPoint")
            for k, v in zip(("X", "Y", "Z"), p):
                pb.add_prop(k, _len(v, units))
    elif isinstance(shape, Boolean):
        # write the operands as sub-commands so nothing is silently dropped
        note = op.add_block("BooleanOperation")
        note.add_prop("BooleanType", shape.op.capitalize())
        for k, sub in enumerate(shape.operands):
            child = note.add_block(f"Operand{k+1}")
            _write_primitive(child, sub, units)
    elif isinstance(shape, FaceOperation):
        # HFSS records these as SweepFaceAlongNormal / MoveFaces operations
        # against its own face ids, which mean nothing outside the session
        # that made them. The faces are written by geometry instead, so the
        # operation replays in Aether and is at least readable elsewhere.
        note = op.add_block("SweepFaceAlongNormalParameters"
                            if shape.op == "sweep" else "MoveFacesParameters")
        note.add_prop("AetherFaceOp", shape.op)
        note.add_prop("SweepDistance", _len(shape.distance, units))
        note.add_prop("NumFaces", len(shape.faces))
        for k, f in enumerate(shape.faces):
            fb = note.add_block(f"Face{k + 1}")
            for key, vals in (("Point", f.get("point", (0, 0, 0))),
                              ("Lo", f.get("lo", (0, 0, 0))),
                              ("Hi", f.get("hi", (0, 0, 0)))):
                for ax, v in zip("XYZ", vals):
                    fb.add_prop(key + ax, _len(v, units))
            for ax, v in zip("XYZ", f.get("normal", (0, 0, 1))):
                fb.add_prop("Normal" + ax, float(v))
            fb.add_prop("Planar", bool(f.get("planar", True)))
            fb.add_prop("Object", str(f.get("object", "")))
        _write_primitive(note.add_block("BaseBody"), shape.base, units)
    elif isinstance(shape, (Extrude, Revolve)):
        note = op.add_block("SweepOperation")
        note.add_prop("SweepType", type(shape).__name__)
        _write_primitive(note.add_block("Profile"), shape.profile, units)
        if isinstance(shape, Extrude):
            for k, v in zip(("XVector", "YVector", "ZVector"), shape.vector):
                note.add_prop(k, _len(v, units))
        else:
            note.add_prop("SweepAngle", f"{math.degrees(shape.angle):.10g}deg")
            note.add_prop("WhichAxis", _axis_name(shape.axis))
    elif isinstance(shape, ImportedShape):
        b = op.add_block("ImportParameters")
        b.add_prop("SourceFile", shape.path)
        b.add_prop("HealGeometry", str(shape.healing))
        # Which body of the file this object is. Without it every part of a
        # re-opened assembly came back as the same body.
        b.add_prop("BodyIndex", int(getattr(shape, "body", -1)))
        # Without these the body comes back at the wrong size, which is worse
        # than not coming back at all.
        b.add_prop("ModelUnits", getattr(shape, "unit", "auto") or "auto")
        b.add_prop("ScaleToM", float(getattr(shape, "scale_to_m", 1.0)))
        rel = getattr(shape, "_embedded_rel", "")
        if rel:
            b.add_prop("EmbeddedFile", rel)
    if shape._xform:
        tb = op.add_block("Transformations")
        for t in shape._xform:
            sub = tb.add_block(t["op"].capitalize())
            for k, v in t.items():
                if k == "op":
                    continue
                sub.add_prop(k, list(v) if isinstance(v, (tuple, list))
                             else float(v))


def _axis_name(axis) -> str:
    a = tuple(round(float(x), 9) for x in axis)
    for k, v in AXIS_NAME.items():
        if a == k:
            return v
    return "Z"


def _rgb(color: str):
    c = (color or "#808080").lstrip("#")
    if len(c) != 6:
        return (128, 128, 128)
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _write_boundary(parent: AedtBlock, b, d) -> AedtBlock:
    blk = parent.add_block(b.name)
    blk.add_prop("BoundType", REV_BTYPE.get(b.btype, "Perfect E"))
    blk.add_prop("Name", b.name)
    objs = _selector_objects(b.selector, d)
    if objs:
        blk.add_prop("Objects", objs)
    write_selector(blk, b.selector, d)
    if b.btype == "finite_cond":
        mat = b.params.get("material")
        if mat is not None:
            blk.add_prop("UseMaterial", True)
            blk.add_prop("Material", mat.name)
        if b.params.get("thickness"):
            blk.add_prop("Thickness", _len(b.params["thickness"], d.units))
        if b.params.get("roughness"):
            blk.add_prop("Roughness", _len(b.params["roughness"], d.units))
    elif b.btype == "impedance":
        z = complex(b.params.get("Zs", 0))
        blk.add_prop("Resistance", f"{z.real:.10g}")
        blk.add_prop("Reactance", f"{z.imag:.10g}")
    elif b.btype == "lumped_rlc":
        blk.add_prop("Resistance", f"{b.params.get('R', 0.0):.10g}")
        blk.add_prop("Inductance", f"{b.params.get('L', 0.0):.10g}")
        blk.add_prop("Capacitance", f"{b.params.get('C', 0.0):.10g}")
    return blk


def _write_port(parent: AedtBlock, p, d) -> AedtBlock:
    blk = parent.add_block(p.name)
    blk.add_prop("Name", p.name)
    blk.add_prop("ExcType", "Wave Port" if p.kind == "wave" else "Lumped Port")
    blk.add_prop("NumModes", int(getattr(p, "num_modes", 1)))
    blk.add_prop("UseIntLine", p.integration_line is not None)
    if p.integration_line is not None:
        il = blk.add_block("IntLine")
        for tag, pt in zip(("Start", "End"), p.integration_line):
            sub = il.add_block(tag)
            for k, v in zip(("X", "Y", "Z"), pt):
                sub.add_prop(k, _len(float(v), d.units))
    if getattr(p, "renormalize_z", None) is not None:
        blk.add_prop("RenormImp", f"{float(p.renormalize_z):.10g}ohm")
    if getattr(p, "deembed", 0.0):
        blk.add_prop("DoDeembed", True)
        blk.add_prop("DeembedDist", _len(float(p.deembed), d.units))
    if p.kind == "lumped":
        blk.add_prop("Impedance", f"{complex(p.impedance).real:.10g}ohm")
        blk.add_prop("Direction", [float(x) for x in p.direction])
    objs = _selector_objects(p.selector, d)
    if objs:
        blk.add_prop("Objects", objs)
    write_selector(blk, p.selector, d)
    return blk


def _selector_objects(sel, d) -> List[str]:
    """Recover object names when the selector is shape-based."""
    from ...geometry.select import ShapeSelector
    if isinstance(sel, ShapeSelector):
        for s in d.solids:
            if s.shape is sel.shape:
                return [s.name]
    return []


def write_selector(parent: AedtBlock, sel, d) -> AedtBlock:
    """
    Persist an Aether face selector as an auxiliary block.

    HFSS identifies boundary faces by kernel ids that mean nothing outside a
    live modeller session.  Aether identifies them geometrically, so the
    selector itself is written into the project under a private block name.
    HFSS ignores blocks it does not know, and Aether reads them back exactly,
    which is what makes an Aether -> .aedt -> Aether round trip lossless even
    though a face id could never survive one.
    """
    from ...geometry.select import (BoundingBoxFaceSelector, BoxSelector,
                                    CylinderSelector, OuterSelector,
                                    PlaneSelector, ShapeSelector)
    b = parent.add_block("AetherSelector")
    if isinstance(sel, PlaneSelector):
        b.add_prop("Kind", "Plane")
        b.add_prop("Axis", sel.axis)
        b.add_prop("Value", float(sel.value))
        b.add_prop("Tol", float(sel.tol))
        if sel.window is not None:
            b.add_prop("Window", [[float(a), float(c)] for a, c in sel.window])
    elif isinstance(sel, BoxSelector):
        b.add_prop("Kind", "Box")
        b.add_prop("Lo", [float(x) for x in sel.lo])
        b.add_prop("Hi", [float(x) for x in sel.hi])
        b.add_prop("Tol", float(sel.tol))
    elif isinstance(sel, CylinderSelector):
        b.add_prop("Kind", "Cylinder")
        b.add_prop("Center", [float(x) for x in sel.center])
        b.add_prop("Axis", [float(x) for x in sel.axis])
        b.add_prop("Radius", float(sel.radius))
        b.add_prop("Height", float(sel.height))
    elif isinstance(sel, BoundingBoxFaceSelector):
        b.add_prop("Kind", "BBoxFace")
        b.add_prop("Face", sel.face)
    elif isinstance(sel, ShapeSelector):
        b.add_prop("Kind", "Shape")
        b.add_prop("Objects", _selector_objects(sel, d))
    else:
        b.add_prop("Kind", "Outer")
    return b


def _write_setup(parent: AedtBlock, st, eigen: bool = False) -> AedtBlock:
    blk = parent.add_block(st.name)
    blk.add_prop("SetupType", "HfssEigen" if eigen else "HfssDriven")
    blk.add_prop("Name", st.name)
    blk.add_prop("IsEnabled", True)
    props = blk.add_block("SolveSetupProps")
    props.add_prop("Frequency", _freq(st.frequency))
    props.add_prop("MaxDeltaS", float(st.delta_s))
    props.add_prop("MaximumPasses", int(st.max_passes))
    props.add_prop("MinimumPasses", int(st.min_passes))
    props.add_prop("MinimumConvergedPasses", int(st.min_converged))
    props.add_prop("PercentRefinement", float(st.refinement) * 100.0)
    props.add_prop("BasisOrder", int(st.basis_order))
    if eigen:
        props.add_prop("NumModes", int(st.n_modes))
        props.add_prop("MinimumFrequency", _freq(st.min_frequency))
        props.add_prop("MaxDeltaFreq", float(st.delta_f) * 100.0)
        props.add_prop("ConvergeOnRealFreq", True)
    for sw in ([] if eigen else st.sweeps):
        s = blk.add_block("Sweep")
        s.add_prop("Name", sw.name)
        s.add_prop("IsEnabled", True)
        s.add_prop("Type", {"discrete": "Discrete", "fast": "Fast",
                            "interpolating": "Interpolating"}[sw.kind])
        if sw.spacing == "single" or sw.count <= 1:
            s.add_prop("RangeType", "SinglePoints")
            s.add_prop("RangeStart", _freq(sw.start))
            s.add_prop("RangeEnd", _freq(sw.start))
            s.add_prop("RangeCount", 1)
        elif sw.spacing == "step":
            s.add_prop("RangeType", "LinearStep")
            s.add_prop("RangeStart", _freq(sw.start))
            s.add_prop("RangeEnd", _freq(sw.stop))
            s.add_prop("RangeStep", _freq(float(sw.step)))
        elif sw.spacing == "log":
            s.add_prop("RangeType", "LogScale")
            s.add_prop("RangeStart", _freq(sw.start))
            s.add_prop("RangeEnd", _freq(sw.stop))
            s.add_prop("RangeSamples", int(sw.count))
        else:
            s.add_prop("RangeType", "LinearCount")
            s.add_prop("RangeStart", _freq(sw.start))
            s.add_prop("RangeEnd", _freq(sw.stop))
            s.add_prop("RangeCount", int(sw.count))
        s.add_prop("SaveFields", bool(sw.save_fields))
        if sw.kind != "discrete":
            if sw.tolerance is not None:
                s.add_prop("InterpTolerance", float(sw.tolerance) * 100.0)
            if sw.max_points is not None:
                s.add_prop("InterpMaxSolns", int(sw.max_points))
        if sw.points is not None:
            s.add_prop("AetherFrequencyPoints", [float(v) for v in sw.frequencies()])
    return blk


# ==========================================================================
# update mode
# ==========================================================================


def update_document(doc: AedtDocument, design) -> AedtDocument:
    """
    Push Aether-side edits back into an existing project tree.

    Only statements whose value actually changed are marked dirty, so the
    written file differs from the original exactly where the model does.
    """
    designs = doc.hfss_designs() or doc.designs()
    target = None
    for b in designs:
        if str(b.get("Name", "")).strip("'") == design.name:
            target = b
            break
    if target is None:
        raise KeyError(f"design {design.name!r} not present in the document")

    for gops in target.find("GeometryOperations"):
        if gops.prop("ModelUnits") is not None:
            gops.set("ModelUnits", design.units)

    for asetup in target.find("AnalysisSetup"):
        for solve in asetup.find("SolveSetups") or [asetup]:
            for s in solve.blocks:
                st = next((x for x in design.setups
                           if x.name == str(s.get("Name", s.name)).strip("'")),
                          None)
                if st is None:
                    continue
                props = s.block("SolveSetupProps") or s
                props.set("Frequency", _freq(st.frequency))
                props.set("MaxDeltaS", float(st.delta_s))
                props.set("MaximumPasses", int(st.max_passes))
    return doc


def cad_sidecar(project_path: str) -> str:
    """The folder a project keeps copies of its imported CAD files in."""
    stem = os.path.splitext(os.path.basename(project_path))[0]
    return os.path.join(os.path.dirname(os.path.abspath(project_path)),
                        stem + ".cad")


def embed_cad(designs, project_path: str) -> List[str]:
    """
    Copy every imported CAD source next to the project being written.

    A project that points at ``C:/tmp/part.step`` stops opening the moment that
    file is moved, cleaned up or sent to somebody else -- and the failure shows
    up as a part that silently is not there. So each source is copied into a
    ``<project>.cad`` folder beside the project file and recorded as a relative
    path; the original absolute path is kept as well and used when the copy is
    missing. Copying is best-effort: an unreadable or already-missing source
    leaves the absolute path as the only route, which is what happened before.
    """
    from ...geometry.primitives import ImportedShape
    out: List[str] = []
    folder = cad_sidecar(project_path)
    for d in designs:
        for holder in list(getattr(d, "solids", [])) + list(getattr(d, "sheets", [])):
            for sh in _walk_shapes(getattr(holder, "shape", None)):
                if not isinstance(sh, ImportedShape):
                    continue
                src = os.path.abspath(os.path.expanduser(sh.path))
                if not os.path.isfile(src):
                    raise FileNotFoundError(f"CAD source is missing: {src}. Replace CAD Source before saving.")
                try:
                    os.makedirs(folder, exist_ok=True)
                    import hashlib
                    with open(src, "rb") as stream:
                        digest = hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()
                    suffix = os.path.splitext(src)[1].lower()
                    dst = os.path.join(folder, digest + suffix)
                    if os.path.abspath(dst) != src:
                        shutil.copy2(src, dst)
                    sh._embedded_rel = os.path.join(
                        os.path.basename(folder), os.path.basename(dst)
                    ).replace(os.sep, "/")
                    out.append(dst)
                except OSError as exc:
                    raise OSError(f"Could not preserve CAD source {src}: {exc}") from exc
    return out


def _walk_shapes(shape):
    """A shape and every operand inside it."""
    from ...geometry.primitives import Boolean, Extrude, Revolve, FaceOperation
    if shape is None:
        return
    yield shape
    if isinstance(shape, Boolean):
        for o in shape.operands:
            yield from _walk_shapes(o)
    elif isinstance(shape, (Extrude, Revolve)):
        yield from _walk_shapes(shape.profile)
    elif isinstance(shape, FaceOperation):
        yield from _walk_shapes(shape.base)


def write_project(path: str, project_or_design, mode: str = "auto") -> str:
    """
    Write a :class:`~aether.model.Project` or :class:`~aether.model.Design`.

    ``mode='update'`` requires that the object was imported from an existing
    project; ``mode='create'`` always regenerates; ``auto`` picks update when
    the provenance is available.
    """
    from ...model import Design, Project
    if isinstance(project_or_design, Design):
        designs = [project_or_design]
        name = project_or_design.name
        src = project_or_design._aedt_source
    else:
        designs = list(project_or_design.designs)
        name = project_or_design.name
        src = project_or_design.aedt_tree
    if mode == "auto":
        mode = "workspace" if src is not None else "create"
    if mode not in ("create", "update", "workspace"):
        raise ValueError("Unknown project write mode")
    embed_cad(designs, path)
    if mode == "workspace":
        # Work on a copy: serialization failure must not mutate source provenance.
        import copy
        doc = copy.deepcopy(src) if src is not None else build_document(name, designs)
        fresh = build_document(name, designs)
        modeled = {"Variables", "ModelSetup", "BoundarySetup", "AnalysisSetup", "AetherMeshOperations"}
        for generated in fresh.hfss_designs():
            target = next((b for b in doc.hfss_designs()
                           if str(b.get("Name", "")) == str(generated.get("Name", ""))), None)
            if target is None:
                doc.root.add(copy.deepcopy(generated))
                continue
            for key in ("DesignType", "Name", "SolutionType", "DesignVersion", "AetherConfig", "AetherDefaultBoundary", "AetherImportIssues"):
                target.set(key, generated.get(key))
            target.children = [b for b in target.children
                               if not (isinstance(b, AedtBlock) and b.name in modeled)]
            for block in generated.blocks:
                if block.name in modeled:
                    target.add(copy.deepcopy(block))
        materials = doc.root.block("Materials")
        new_materials = fresh.root.block("Materials")
        if materials is None:
            doc.root.add(copy.deepcopy(new_materials))
        else:
            for block in new_materials.blocks:
                old = materials.block(block.name)
                if old is not None:
                    materials.remove(old)
                materials.add(copy.deepcopy(block))
        return doc.write(path)
    if mode == "update":
        if src is None:
            raise ValueError("no source document to update; use mode='create'")
        for d in designs:
            update_document(src, d)
        return src.write(path)
    doc = build_document(name, designs)
    return doc.write(path)


__all__ = ["build_document", "update_document", "write_project",
           "embed_cad", "cad_sidecar"]
