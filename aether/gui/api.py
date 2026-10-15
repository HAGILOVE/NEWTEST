"""
Command layer behind the Aether Desktop UI.

Every menu item, dialog and toolbar button in the browser resolves to one
entry in :data:`COMMANDS`. The same commands are what the scripting console
calls, so anything the UI can do is scriptable and anything scripted shows up
in the UI immediately — there is only one model.
"""
from __future__ import annotations

import io
import math
import os
import re
import time
import traceback
from collections import OrderedDict
from typing import Sequence, Any, Callable, Dict, List, Optional

import numpy as np

from ..core.constants import c0, to_si
from ..core.logging import get_logger
from ..core.materials import LIBRARY
from ..geometry import primitives as prim
from ..model import Sheet
from ..geometry.select import (MultiFaceSelector, BoundingBoxFaceSelector, BoxSelector,
                               CylinderSelector, FaceSelector, OuterSelector,
                               PlaneSelector, ShapeSelector, union_sel)
from . import files as filesmod
from . import naming
from .state import Session
from .tessellate import (field_on_surface, mesh_wire, tessellate,
                         tessellate_mesh_surface)

log = get_logger("gui.api")

COMMANDS: Dict[str, Callable] = {}


def command(name: str):
    def deco(fn):
        COMMANDS[name] = fn
        return fn
    return deco


# ==========================================================================
# serialisation of the model into the UI's tree
# ==========================================================================


def _entity(d, name: str):
    """A solid or a sheet by name -- both are objects in the model."""
    for o in d.solids:
        if o.name == name:
            return o
    for sh in d.sheets:
        if sh.name == name:
            return sh
    raise KeyError(f"no object named {name!r}")


def _cad_json(shape) -> dict:
    """The CAD provenance of an imported body, for the property grid."""
    if not isinstance(shape, prim.ImportedShape):
        return {}
    p = shape.path or ""
    return {"cad": {"path": p,
                    "file": os.path.basename(p),
                    "unit": getattr(shape, "unit", "auto"),
                    "scale": float(getattr(shape, "scale_to_m", 1.0)),
                    "healing": bool(getattr(shape, "healing", True)),
                    "unreadable": getattr(shape, "_cad_unreadable", ""),
                    "exists": bool(p) and os.path.isfile(os.path.expanduser(p))}}


def _selector_json(sel) -> dict:
    if isinstance(sel, PlaneSelector):
        return {"kind": "plane", "axis": sel.axis, "value": sel.value,
                "label": f"Plane {sel.axis.upper()} = {sel.value*1e3:.4g} mm"}
    if isinstance(sel, BoxSelector):
        return {"kind": "box", "lo": list(map(float, sel.lo)),
                "hi": list(map(float, sel.hi)), "label": "Box region"}
    if isinstance(sel, CylinderSelector):
        return {"kind": "cylinder", "label": "Cylindrical region"}
    if isinstance(sel, BoundingBoxFaceSelector):
        return {"kind": "bboxface", "face": sel.face,
                "label": f"Bounding-box face {sel.face}"}
    if isinstance(sel, FaceSelector):
        return {"kind": "faces", "object": sel.object,
                "point": [float(x) for x in sel.point],
                "label": f"Picked face of {sel.object}" if sel.object
                         else "Picked face"}
    if isinstance(sel, MultiFaceSelector):
        n = len(sel.faces)
        objs = sorted({f.object for f in sel.faces if f.object})
        return {"kind": "faces", "object": objs[0] if objs else "",
                "count": n,
                "label": f"{n} picked face{'s' if n != 1 else ''}"
                         + (f" on {', '.join(objs[:2])}" if objs else "")}
    if isinstance(sel, ShapeSelector):
        return {"kind": "object", "label": "Object faces"}
    if isinstance(sel, OuterSelector):
        return {"kind": "outer", "label": "All outer faces"}
    return {"kind": "custom", "label": "Custom selection"}


def _design_json(s: Session) -> Optional[dict]:
    d = s.design
    if d is None:
        return None
    lo, hi = d.bounding_box()
    return {
        "name": d.name,
        "solutionType": d.solution_type,
        "units": d.units,
        "bbox": [list(map(float, lo)), list(map(float, hi))],
        "objects": [dict({
            "name": o.name,
            "material": o.material.name,
            "kind": type(o.shape).__name__,
            "solveInside": bool(o.solve_inside),
            "color": o.color,
            "transparency": float(o.transparency),
            "materialColor": o.material.color,
            "materialTransparency": float(o.material.transparency),
            "colorOverridden": o.display_color is not None,
            "transparencyOverridden": o.display_transparency is not None,
            "visible": bool(getattr(o, "visible", True)),
            "isPec": bool(o.material.is_pec),
            "isMetal": bool(o.material.is_conductor),
        }, **_cad_json(o.shape)) for o in d.solids],
        "sheets": [dict({
            "name": sh.name,
            "kind": type(sh.shape).__name__,
            "material": sh.material.name if sh.material else "",
            "color": sh.color,
            "transparency": float(sh.transparency),
            "colorOverridden": sh.display_color is not None,
            "transparencyOverridden": sh.display_transparency is not None,
            "visible": bool(getattr(sh, "visible", True)),
        }, **_cad_json(sh.shape)) for sh in d.sheets],
        "boundaries": [{"name": b.name, "type": b.btype,
                        "selector": _selector_json(b.selector),
                        "params": {k: _plain(v) for k, v in b.params.items()}}
                       for b in d.boundaries],
        "ports": [{
            "name": p.name, "kind": p.kind,
            "modes": int(getattr(p, "num_modes", 1)),
            "impedance": _plain(getattr(p, "impedance", None)),
            "renorm": _plain(getattr(p, "renormalize_z", None)),
            "deembed": float(getattr(p, "deembed", 0.0)),
            "hasLine": getattr(p, "integration_line", None) is not None,
            "direction": [float(x) for x in getattr(p, "direction", (0, 0, 1))]
            if p.kind == "lumped" else None,
            "selector": _selector_json(p.selector),
        } for p in d.ports],
        "coordSystems": [{"name": c["name"], "origin": [float(x) for x in c["origin"]]}
                         for c in d.coordinate_systems],
        "workingCs": d.working_cs,
        "meshOps": [{"name": m.name, "maxLength": float(m.max_length),
                     "objects": list(m.objects), "enabled": bool(m.enabled),
                     "kind": m.kind,
                     "where": (", ".join(m.objects) if m.objects
                               else _selector_json(m.selector).get("label", ""))}
                    for m in getattr(d, "mesh_ops", [])],
        "setups": [{
            "name": st.name, "frequency": st.frequency,
            "maxPasses": st.max_passes, "deltaS": st.delta_s,
            "basisOrder": st.basis_order,
            "nModes": st.n_modes, "minFrequency": st.min_frequency,
            "deltaF": st.delta_f, "minPasses": st.min_passes,
            "minConverged": st.min_converged,
            "refinement": st.refinement * 100.0,
            "sweeps": [{"name": sw.name, "kind": sw.kind,
                        "start": sw.start, "stop": sw.stop,
                        "count": sw.count, "spacing": sw.spacing,
                        "points": int(len(sw.frequencies())),
                        "tolerance": sw.tolerance, "maxPoints": sw.max_points,
                        "step": sw.step, "saveFields": bool(sw.save_fields)}
                       for sw in st.sweeps],
        } for st in d.setups],
        "meshed": d.mesh is not None,
        "meshStats": ({"nodes": d.mesh.n_nodes, "tets": d.mesh.n_tets,
                       "edges": d.mesh.n_edges,
                       "minQuality": float(d.mesh.quality().min())}
                      if d.mesh is not None else None),
        "excitations": d.excitation_names(),
    }


def _plain(v):
    if v is None:
        return None
    if isinstance(v, complex):
        return [v.real, v.imag]
    if isinstance(v, (np.floating, np.integer)):
        return float(v)
    if hasattr(v, "name"):
        return v.name
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def state_json(s: Session) -> dict:
    return {
        "project": {"name": s.project.name, "path": s.project_path,
                    "dirty": bool(s.dirty),
                    "open": bool(getattr(s, "project_open", True)),
                    "designs": [d.name for d in s.project.designs]},
        "design": _design_json(s),
        "selection": list(s.selection),
        "selMode": s.select_mode,
        "selFaces": [dict(f) for f in s.sel_faces],
        "selEdges": [dict(e) for e in s.sel_edges],
        "job": s.job.to_json(),
        "task": s.progress.to_json(),
        "hasSolution": s.solution is not None,
        "solutionPartial": bool(getattr(s.solution, "partial", False)),
        "solutionSerial": int(getattr(s, "solution_serial", 0)),
        "history": {"canUndo": s.can_undo, "canRedo": s.can_redo,
                    "undo": s.undo_label(), "redo": s.redo_label(),
                    "clipboard": len(s.clipboard)},
        "view": dict(s.view),
        "messageSeq": s.messages.seq,
    }


# ==========================================================================
# project
# ==========================================================================


def clear_display_caches() -> None:
    """
    Forget everything cached about the document that is being replaced.

    Display buffers, the arrays the boundary overlays are evaluated against
    and the binary blobs already handed to the browser all belong to one
    model. Carrying them into the next project is how memory grows with every
    file opened in a session — which is what "the second file loads slowly or
    not at all" turns out to be.
    """
    global _BLOB_BYTES
    from .tessellate import clear_cache
    clear_cache()
    _ASSIGN_ARRAYS.clear()
    # Blobs are trimmed rather than dropped. A fetch the browser started
    # before the document changed is still in flight, and answering it with a
    # 404 costs a redraw and writes an error into the console for no reason;
    # the newest entries are exactly the ones still being asked for, so the
    # oldest go first and a small reserve stays.
    while _BLOB_BYTES > _BLOB_RESERVE_BYTES and len(BLOBS) > 1:
        _, dropped = BLOBS.popitem(last=False)
        _BLOB_BYTES -= len(dropped)
    from ..geometry.brep_io import _BOUNDS_CACHE
    _BOUNDS_CACHE.clear()


def _progress_hook(s: Session):
    """Adapt a library-level ``(stage, done, total)`` callback to the session
    progress channel the browser polls."""
    def hook(stage, done=0, total=0):
        s.progress.step(stage=str(stage),
                        done=int(done) if total else None,
                        total=int(total) if total else None)
    return hook


@command("project.new")
def _new(s: Session, name: str = "Project1", **_):
    clear_display_caches()
    s.new_project(name)
    return {"ok": True}


@command("project.importStatus")
def _import_status(s: Session, **_):
    from ..diagnostics import import_errors
    d=s.require_design()
    return {"design":d.name,"errors":import_errors(d),"issues":getattr(d,"import_issues",[]),
            "objects":[{"name":o.name,"missingGeometry":bool(getattr(o.shape,"_cad_unreadable","") or getattr(o.shape,"_cad_missing",False)),
                        "materialIssue":getattr(o,"import_material","")} for o in d.solids+d.sheets]}


@command("project.close")
def _close(s: Session, **_):
    """
    Close the open document.

    Saving is a separate decision and a separate command: the UI asks first and
    calls ``project.save`` itself when the answer is yes, so a close that
    reaches here always means "discard whatever is left".
    """
    s.close_project()
    clear_display_caches()
    return {"ok": True}


@command("project.open")
def _open(s: Session, path: str = "", **_):
    from ..io.warp.translate import read_project
    path = os.path.expanduser(path)
    s.progress.begin(f"Opening {os.path.basename(path) or path}",
                     stage="reading the project file")
    try:
        result = _open_impl(s, path, read_project)
    except Exception as exc:
        s.progress.end(str(exc))
        raise
    s.progress.end()
    return result


def _open_impl(s: Session, path: str, read_project):
    proj, reports = read_project(path, progress=_progress_hook(s))
    clear_display_caches()
    s.progress.step(stage="building the model tree")
    if not len(proj):
        raise ValueError("No supported Warps design found. Open a .warp or .warpz project. Current project was kept.")
    s._undo.clear()
    s._redo.clear()
    s.clipboard = []
    s.clear_picks()
    s.study_results = []; s.study_spec = {}
    s.project = proj
    s.design = proj[0] if len(proj) else None
    s.project_path = path
    s.project_open = True
    if str(proj.warp_tree.root.get("BuildVariant", "")) != "Aether-EM":
        s.messages.add("This project was not written by this program: only the parts it understands were loaded. Use Save As to keep the original; saving rewrites the supported geometry, boundary and setup branches.", "warning", "project")
    s.solution = None
    s.dirty = False
    _restore_results(s, path)
    for r in reports:
        s.messages.add(
            f"Imported design {r.design_name!r}: {len(r.solids)} objects, "
            f"{len(r.boundaries)} boundaries, {len(r.ports)} excitations, "
            f"{len(r.setups)} setups.", "info", "project")
        for u in r.unresolved:
            s.messages.add(u, "warning", "import")
        for w in r.warnings:
            s.messages.add(w, "warning", "import")
    d = s.design
    blocked = [o.name for o in (d.solids if d else [])
               if getattr(o.shape, "_cad_unreadable", "")]
    if blocked:
        s.messages.add(
            f"{len(blocked)} of {len(d.solids)} object(s) have no readable "
            "geometry: the project stores them as native (Parasolid) bodies, "
            "which were written to the project's .cad folder. In Warps use "
            "Modeler > Export > .step, then Modeler > Repair Bodies here to "
            "connect them all from that one file. Affected: "
            f"{', '.join(blocked[:6])}"
            + (" …" if len(blocked) > 6 else ""), "warning", "import")
    dropped = sum(len(r.pml_parts) for r in reports)
    if dropped:
        s.messages.add(
            f"{dropped} PML layer(s) and their materials and boundaries were "
            "left out: a stretched-coordinate absorber is not solved here. "
            "The open boundary they stood for is a Radiation condition on the "
            "outer surface — check the air clearance is at least a quarter "
            "wavelength.", "info", "import")
    return {"ok": True, "unresolved": sum(len(r.unresolved) for r in reports),
            "missingGeometry": blocked}


@command("project.save")
def _save(s: Session, path: str = "", mode: str = "auto",
          withResults: bool = True, **_):
    from ..io.warp.writer import write_project
    p = os.path.expanduser(path or s.project_path)
    if not p:
        raise ValueError("no file name given")
    if not os.path.splitext(p)[1]:
        p += ".warp"
    p = os.path.abspath(p)
    if os.path.splitext(p)[1].lower() not in (".warp", ".warpz"):
        raise ValueError("Save projects as .warp or .warpz")
    write_project(p, s.project, mode=mode)
    s.project_path = p
    s.dirty = False
    s.messages.add(f"Saved project to {p}", "info", "project")
    saved = _save_results(s, p, withResults)
    return {"ok": True, "path": p, "results": saved}


def _save_results(s: Session, path: str, enabled: bool = True) -> str:
    """Keep the finished solution next to the project (``<project>.wres``) so
    reopening the project does not mean solving again; drop a stale file."""
    from ..io import results as resio
    sol = s.solution
    stale = resio.results_path(path)
    if (not enabled or sol is None or sol.design is not s.design
            or getattr(sol, "partial", False)):
        if os.path.isfile(stale):
            try:
                os.remove(stale)
            except OSError:
                pass
        return ""
    try:
        out = resio.save_solution(sol, path, s.design.name)
    except Exception as exc:                                  # noqa: BLE001
        s.messages.add(f"The project was saved, but its results could not be: "
                       f"{exc}", "warning", "project")
        return ""
    s.messages.add(f"Saved solution results to {out} "
                   f"({os.path.getsize(out) / 1e6:.1f} MB). Opening the "
                   "project restores them without solving again.",
                   "info", "project")
    return out


def _restore_results(s: Session, path: str) -> None:
    """After opening a project: bring back the solution saved with it."""
    from ..io import results as resio
    head = resio.peek(path)
    if head is None:
        return
    target = next((d for d in s.project.designs if d.name == head.get("design")),
                  None)
    if target is None:
        return
    sol, why = resio.load_solution(path, target)
    if sol is None:
        s.messages.add(f"Saved results were not restored: {why}.", "warning",
                       "project")
        return
    s.design = target
    target.mesh = sol.mesh
    s.solution = sol
    s.messages.add(
        f"Restored the saved solution of {target.name!r}: "
        f"{len(sol.freqs)} frequency point(s), {len(sol.fields)} field "
        f"solution(s), {sol.mesh.n_tets} tetrahedra. No new analysis needed.",
        "info", "project")


@command("export.threejs")
def _export_threejs(s: Session, path: str = "", results: bool = True,
                    maxFreqs: int = 6, maxExcitations: int = 4, **_):
    """
    Save the open design -- and its solution, when there is one -- as one
    stand-alone HTML file with an embedded three.js viewer.

    The file keeps the complex E / H / Js vectors and the complex far field, so
    the phase, the field component and the frequency are controls of the page
    rather than frames baked in at export time.
    """
    from . import threejs
    d = s.require_design()
    p = os.path.abspath(os.path.expanduser(path or ""))
    if not path:
        raise ValueError("no file name given")
    if os.path.splitext(p)[1].lower() not in (".html", ".htm"):
        p += ".html"
    want = bool(results) and s.solution is not None
    if want and not s.solution.fields:
        s.messages.add("The solution has no saved fields, so the viewer will "
                       "show the model only. Analyse with 'Save fields' "
                       "enabled to export E/H/current/radiation.",
                       "warning", "export")
    s.progress.begin("Exporting 3-D viewer", stage="encoding")
    try:
        info = threejs.export(
            s, p, max_freqs=max(1, int(maxFreqs)),
            max_excitations=max(1, int(maxExcitations)),
            with_results=want,
            progress=lambda t: s.progress.step(detail=t))
    finally:
        s.progress.end()
    s.messages.add(
        f"Exported 3-D viewer to {info['path']} "
        f"({info['bytes'] / 1e6:.1f} MB, {info['objects']} object(s)"
        + (f", results at {info['frequencies']} frequenc"
           f"{'y' if info['frequencies'] == 1 else 'ies'}" if info["results"]
           else ", model only")
        + ("" if info["offline"] else "; three.js loads from a CDN") + ")",
        "info", "export")
    return dict(info, ok=True)


@command("project.insertDesign")
def _insert(s: Session, name: str = "", solutionType: str = "driven_modal", **_):
    s.insert_design(name, solutionType)
    return {"ok": True}


@command("project.setDesign")
def _setdesign(s: Session, name: str = "", **_):
    s.design = s.project[name]
    s.clear_picks()
    s.solution = None
    return {"ok": True}


@command("project.renameDesign")
def _rename_design(s: Session, name: str = "", newName: str = "", **_):
    """Rename a design. The project tree could create and switch designs but
    never rename one, so a design named by an import kept that name forever."""
    target = name or (s.design.name if s.design else "")
    d = s.project[target]
    new = str(newName).strip()
    if not new:
        raise ValueError("give the design a name")
    if new != d.name and any(x.name == new for x in s.project.designs):
        raise ValueError(f"a design named {new!r} already exists")
    old, d.name = d.name, new
    s.dirty = True
    s.messages.add(f"Renamed design {old!r} to {new!r}.", "info", "project")
    return {"ok": True, "name": new}


@command("project.deleteDesign")
def _delete_design(s: Session, name: str = "", **_):
    """Remove a design from the project. The last one cannot go: a project
    with no design has nothing to show and nothing to solve — close the
    project instead."""
    target = name or (s.design.name if s.design else "")
    d = s.project[target]
    if len(s.project.designs) <= 1:
        raise ValueError("a project keeps at least one design — use "
                         "File ▸ Close Project instead")
    s.project.designs = [x for x in s.project.designs if x is not d]
    if s.design is d:
        s.design = s.project.designs[0]
        s.clear_picks()
        s.solution = None
    s._undo.clear()
    s._redo.clear()
    s.dirty = True
    s.messages.add(f"Deleted design {target!r}.", "info", "project")
    return {"ok": True, "design": s.design.name if s.design else ""}


@command("project.template")
def _template(s: Session, template: str = "waveguide", **_):
    """Load one of the starter models, same set the CLI's `new` offers."""
    from ..cli import _p_new
    import argparse
    import contextlib
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(),
                       f"_aether_tpl_{int(time.time()*1000)}.warp")
    with contextlib.redirect_stdout(io.StringIO()):
        _p_new(argparse.Namespace(path=tmp, template=template))
    _open(s, path=tmp)
    s.project_path = ""
    s.project.name = f"{template.capitalize()}Project"
    try:
        os.unlink(tmp)
    except OSError:
        pass
    return {"ok": True}


# ==========================================================================
# modeler
# ==========================================================================


@command("naming.suggest")
def _suggest(s: Session, kind: str = "shape", what: str = "box",
             setup: str = "", **_):
    """
    The name the UI should pre-fill.

    Proposed by the server so the suggestion always reflects the real model,
    including objects created from the scripting console or loaded from a
    project file.
    """
    d = s.design
    if kind == "shape":
        return {"name": naming.suggest_shape(d, what)}
    if kind == "boundary":
        return {"name": naming.suggest_boundary(d, what)}
    if kind == "port":
        return {"name": naming.suggest_port(d, what)}
    if kind == "meshop":
        return {"name": naming.suggest_mesh_op(d)}
    if kind == "setup":
        return {"name": naming.suggest_setup(d)}
    if kind == "sweep":
        st = d.get_setup(setup or None) if d and d.setups else None
        return {"name": naming.suggest_sweep(st)}
    if kind == "design":
        return {"name": naming.suggest_design(s.project)}
    return {"name": naming.next_name([], "Object")}


@command("modeler.draw")
def _draw(s: Session, shape: str = "box", name: str = "", material: str = "vacuum",
          params: Optional[dict] = None, **_):
    d = s.require_design()
    p = params or {}
    nm = (naming.unique_name(naming.model_names(d), name) if name
          else naming.suggest_shape(d, shape))
    from ..parametric import make_primitive
    sh = make_primitive(shape, p, nm, d.variables, d.units)
    if shape in ("rectangle", "circle"):
        d.add_sheet(nm, sh, d.materials.get(material))
    else:
        d.add_solid(nm, sh, material, bool(p.get("solveInside", True)))
    d.mesh = None
    s.dirty = True
    s.selection = [nm]
    s.messages.add(f"Created {shape} {nm!r}.", "info", "modeler")
    return {"ok": True, "name": nm}


@command("modeler.inspectCad")
def _inspect_cad(s: Session, path: str = "", unit: str = "auto", **_):
    """What a CAD file holds, before committing to importing it."""
    from ..geometry.brep_io import inspect as _inspect
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        raise FileNotFoundError(p)
    return _inspect(p, unit=unit)


@command("modeler.listBodies")
def _list_bodies(s: Session, path: str = "", unit: str = "auto", **_):
    """The separate bodies a CAD file holds, before importing it."""
    from ..geometry.brep_io import list_bodies
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        raise FileNotFoundError(p)
    return {"bodies": list_bodies(p, unit=unit)}


def _clean_part_name(label: str) -> str:
    """Normalize STEP assembly labels without rejecting non-Latin names."""
    text = str(label or "").replace("\\", "/").split("/")[-1].strip()
    if not text or "STEP translator" in text or "Open CASCADE" in text:
        return ""
    text = "".join(c if c.isalnum() or c == "_" else "_" for c in text).strip("_")
    if text and text[0].isdigit():
        text = "P" + text
    return text[:60]


@command("modeler.importCad")
def _import_cad(s: Session, path: str = "", name: str = "",
                material: str = "vacuum", scale: float = 1.0,
                unit: str = "auto", separate: bool = True, **_):
    """
    Add a CAD body to the model.

    The unit matters more than anything else here: a STEP file from a
    mechanical tool stores bare numbers and declares millimetres, so imported
    without conversion a 20 mm part becomes a 20 metre one. ``auto`` honours
    the file's declaration (and assumes millimetres for STL/OBJ, which declare
    nothing); an explicit unit overrides it. What actually happened is reported
    afterwards so a silent scale error cannot pass unnoticed.
    """
    from ..geometry.brep_io import probe as _probe
    d = s.require_design()
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        raise FileNotFoundError(p)
    s.progress.begin(f"Importing {os.path.basename(p)}",
                     stage="reading the CAD file")
    try:
        return _import_cad_impl(s, d, p, name, material, scale, unit, separate,
                                _probe)
    except Exception as exc:
        s.progress.end(str(exc))
        raise
    finally:
        if s.progress.active:
            s.progress.end()


def _import_cad_impl(s: Session, d, p, name, material, scale, unit, separate,
                     _probe):
    if not np.isfinite(float(scale)) or float(scale)<=0:
        raise ValueError("Import scale must be finite and positive")
    if p.lower().endswith('.dxf'):
        from .drawing import import_drawing
        s.progress.step(stage="reading the drawing")
        return import_drawing(s,p,name,material,unit,float(scale))
    s.progress.step(stage="inspecting the geometry")

    def _harvest(gmsh, dim_tags):
        # The inspection pass already meshes the file to report each body's
        # extent. That mesh is exactly what the viewport needs, so it is kept
        # rather than thrown away and rebuilt: on a NURBS assembly the second
        # mesh was as expensive as the whole rest of the import.
        from .tessellate import harvest_bodies
        n = harvest_bodies(gmsh, dim_tags, p, float(scale), unit)
        if n:
            log.debug("cached %d display buffer(s) from the import mesh", n)

    info = _probe(p, unit=unit, scale_to_m=float(scale), harvest=_harvest)
    s.progress.step(stage="adding bodies to the model")
    if info.get("error"):
        raise RuntimeError(f"cannot read {os.path.basename(p)}: {info['error']}")
    if not info["solids"] and not info["surfaces"]:
        if info["format"] == "dxf":
            raise RuntimeError(
                f"{os.path.basename(p)} has no closed outline. A DXF is a "
                "drawing: a shape has to be a closed polyline, circle or "
                "solid before it can become geometry.")
        raise RuntimeError(f"{os.path.basename(p)} contains no geometry")
    # A DXF is a drawing: what it yields is flat outlines, which belong in the
    # model as sheets. One face sweep afterwards gives them thickness.
    as_sheet = info["format"] == "dxf" or (
        info["solids"] == 0 and info["surfaces"] > 0)

    base = (naming.unique_name(naming.model_names(d), name) if name
            else naming.suggest_part_from_file(d, p))
    bodies = info.get("bodyList", []) if separate else []
    made: List[str] = []

    if separate and len(bodies) > 1:
        # An assembly is a list of parts, and a model wants them as parts: one
        # to make PEC, one to make substrate, one to delete. Importing it as a
        # single body leaves none of that possible.
        for b in bodies:
            label = _clean_part_name(b.get("name", "")) or f"{base}_{b['index'] + 1}"
            nm = naming.unique_name(naming.model_names(d), label)
            sh = prim.ImportedShape(p, name=nm, scale_to_m=float(scale),
                                    unit=unit, body=b["index"])
            if as_sheet:
                d.add_sheet(nm, sh, material)
            else:
                d.add_solid(nm, sh, material)
            made.append(nm)
    else:
        nm = base
        sh = prim.ImportedShape(p, name=nm, scale_to_m=float(scale), unit=unit)
        if as_sheet:
            d.add_sheet(nm, sh, material)
        else:
            d.add_solid(nm, sh, material)
        made.append(nm)

    d.mesh = None
    s.dirty = True
    s.selection = made
    lo, hi = info["bbox"]
    ext = " x ".join(f"{(hi[k] - lo[k]) * 1e3:.3f}" for k in range(3))
    s.messages.add(
        f"Imported {os.path.basename(p)} as "
        + (f"{len(made)} objects ({', '.join(made[:6])}"
           + (" …" if len(made) > 6 else "") + ")" if len(made) > 1
           else repr(made[0]))
        + f": {info['solids']} solid(s), {info['surfaces']} face(s), "
        f"extent {ext} mm (unit: {info['appliedUnit']}"
        + (f", declared {info['declaredUnit']}" if info["declaredUnit"] else "")
        + ").", "info", "modeler")
    nm = made[0]
    if info["solids"] == 0:
        s.messages.add(
            f"{nm!r} imported as surfaces only — a sheet body cannot enclose a "
            "solution volume. Check that the source model is a closed solid.",
            "warning", "modeler")
    return {"ok": True, "name": nm, "info": info}


@command("modeler.faceOperation")
def _face_op(s: Session, op: str = "sweep", distance: Any = "1mm",
             faces: Optional[List[dict]] = None, name: str = "",
             newName: str = "", **_):
    """
    Sweep or move the picked faces of a body.

    *Sweep face along normal* gives a face thickness; *move faces* drags a face
    in or out, lengthening or trimming the body. Both are recorded on the
    object as an operation over the face, so the distance stays editable and
    the boundaries and ports attached to the body are untouched.
    """
    d = s.require_design()
    picks = list(faces or s.sel_faces)
    if not picks:
        raise ValueError("pick a face first (press F, then click one)")
    if op not in ("sweep", "move"):
        raise ValueError(f"unknown face operation {op!r}")
    objects = sorted({str(f.get("object", "")) for f in picks
                      if f.get("object")})
    target = name or (objects[0] if objects else "")
    if not target:
        raise ValueError("the picked faces do not name an object")
    if len(objects) > 1:
        raise ValueError("pick faces on one object at a time; got "
                         + ", ".join(objects))
    sheet = next((sh for sh in d.sheets if sh.name == target), None)
    if sheet is not None:
        # A sheet swept along its normal becomes a solid -- the step from a
        # DXF outline or an imported surface to something that can be meshed
        # as a volume.
        return _thicken_sheet(s, d, sheet, distance, picks)

    o = d.get_solid(target)
    mine = [f for f in picks if f.get("object") == target]
    curved = [f for f in mine if not f.get("planar", True)]
    if curved:
        raise ValueError(
            "a curved face has no single normal to sweep along; pick a planar "
            "face, or scale the whole body instead")

    dist = to_si(distance)
    if op == "sweep":
        # Warps semantics: sweeping a face along its normal makes a *new* body
        # out of the swept volume and leaves the one the face belongs to
        # alone. That is the whole point of the command -- a face of an
        # existing part becomes an object of its own, with its own material,
        # boundary or port. It used to be built exactly like Move Faces, so
        # the body simply grew and no new object appeared.
        # `name` names the body being operated on; `newName` names the body
        # the sweep creates.
        nm = naming.unique_name(naming.model_names(d),
                                newName or f"{target}_Sweep")
        shape = prim.FaceOperation(o.shape, mine, "sweep", distance, name=nm)
        try:
            tessellate(shape)
        except Exception as exc:
            raise RuntimeError(
                f"the face sweep could not be applied: {exc}") from exc
        d.add_solid(nm, shape, o.material.name if o.material else "vacuum")
        d.mesh = None
        s.dirty = True
        s.sel_faces = []
        s.selection = [nm]
        s.messages.add(
            f"Swept {len(mine)} face(s) of {target!r} by {dist * 1e3:.4g} mm "
            f"into a new object {nm!r}.", "info", "modeler")
        return {"ok": True, "name": nm, "newObject": True, "from": target}

    before = o.shape
    o.shape = prim.FaceOperation(before, mine, op, distance, name=o.name)
    # Build it once, now: an operation that cannot be applied must say so
    # while the dialog is still open, not leave a model that fails to display
    # and fails to mesh.
    try:
        tessellate(o.shape)
    except Exception as exc:
        o.shape = before
        raise RuntimeError(f"the face {op} could not be applied: {exc}") from exc
    d.mesh = None
    s.dirty = True
    s.sel_faces = []
    s.messages.add(
        f"Moved {len(mine)} face(s) of {target!r} by {dist * 1e3:.4g} mm.",
        "info", "modeler")
    return {"ok": True, "name": target}


def _thicken_sheet(s: Session, d, sheet, distance, picks):
    """Sweep a sheet along its normal, turning it into a solid in place."""
    if getattr(sheet.shape,"reference_only",False):
        raise ValueError("An open reference sketch has no face to sweep. Close its outline in the source CAD and reimport.")
    n = None
    for f in picks:
        if f.get("object") == sheet.name and f.get("normal"):
            n = [float(x) for x in f["normal"]]
            break
    if n is None:
        n = [0.0, 0.0, 1.0]
    dist = to_si(distance)
    vec = [x * dist for x in n]
    shape = prim.Extrude(sheet.shape, vec, name=sheet.name)
    material = sheet.material or d.materials.get("copper")
    d.sheets = [x for x in d.sheets if x.name != sheet.name]
    solid = d.add_solid(sheet.name, shape, material)
    try:
        tessellate(solid.shape)
    except Exception as exc:
        d.solids = [x for x in d.solids if x.name != sheet.name]
        d.sheets.append(sheet)
        raise RuntimeError(f"the sheet could not be swept: {exc}") from exc
    d.mesh = None
    s.dirty = True
    s.sel_faces = []
    s.selection = [sheet.name]
    s.messages.add(
        f"Swept sheet {sheet.name!r} by {dist * 1e3:.4g} mm; it is a solid now.",
        "info", "modeler")
    return {"ok": True, "name": sheet.name, "becameSolid": True}


@command("modeler.boolean")
def _boolean(s: Session, op: str = "subtract", blank: str = "",
             tools: Optional[List[str]] = None, keep: bool = False, **_):
    d = s.require_design()
    tools = tools or []
    base = d.get_solid(blank)
    tool_objs = [d.get_solid(t) for t in tools]
    shapes = [t.shape for t in tool_objs]
    if op == "subtract":
        base.shape = prim.cut(base.shape, *shapes)
    elif op == "unite":
        base.shape = prim.union(base.shape, *shapes)
    elif op == "intersect":
        base.shape = prim.intersect(base.shape, *shapes)
    else:
        raise ValueError(f"unknown boolean operation {op!r}")
    base.shape.name = base.name
    if not keep:
        for t in tool_objs:
            d.solids.remove(t)
    d.mesh = None
    s.dirty = True
    s.selection = [blank]
    s.messages.add(f"{op.capitalize()}: {blank} ← {', '.join(tools)}",
                   "info", "modeler")
    return {"ok": True}


AXIS_VEC = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def _entities(d, names: Sequence[str]):
    """Resolve names to solids or sheets, in the order given."""
    by = {o.name: o for o in d.solids}
    by.update({sh.name: sh for sh in d.sheets})
    out = []
    for n in names:
        if n not in by:
            raise KeyError(f"no object named {n!r}")
        out.append(by[n])
    return out


def _apply_transform(shape, op: str, p: dict):
    """One Warps arrange operation on one shape."""
    if op == "move":
        shape.translate(p.get("dx", 0), p.get("dy", 0), p.get("dz", 0))
    elif op == "rotate":
        ax = p.get("axis", "z")
        shape.rotate(AXIS_VEC.get(str(ax).lower(), ax) if isinstance(ax, str)
                     else ax, p.get("angle", "0deg"), p.get("origin", (0, 0, 0)))
    elif op == "scale":
        shape.scale(p.get("sx", 1), p.get("sy"), p.get("sz"),
                    p.get("origin", (0, 0, 0)))
    elif op == "mirror":
        shape.mirror(p.get("normal", (0, 0, 1)), p.get("origin", (0, 0, 0)))
    else:
        raise ValueError(f"unknown transform {op!r}")


@command("modeler.transform")
def _transform(s: Session, name: str = "", names: Optional[List[str]] = None,
               op: str = "move", params: Optional[dict] = None, **_):
    """Arrange ▸ Move / Rotate / Mirror / Scale, on one or many objects."""
    d = s.require_design()
    targets = list(names or ([name] if name else s.selection))
    if not targets:
        raise ValueError("select an object first")
    p = params or {}
    for o in _entities(d, targets):
        _apply_transform(o.shape, op, p)
    d.mesh = None
    s.dirty = True
    s.messages.add(f"{op.capitalize()}: {', '.join(targets)}", "info",
                   "modeler")
    return {"ok": True, "names": targets}


# --------------------------------------------------------------------------
# clipboard and duplication
# --------------------------------------------------------------------------


@command("modeler.resize")
def _resize(s: Session, name: str = "", size=None, anchor: str = "center", **_):
    """Resize a single object's world bounding box, keeping center or minimum."""
    d = s.require_design()
    names = [name] if name else list(s.selection)
    if len(names) != 1:
        raise ValueError("Select exactly one object to resize")
    obj = _entities(d, names)[0]
    if size is None or len(size) != 3:
        raise ValueError("Enter X, Y, Z target dimensions")
    from .measurement import UNITS
    target = np.array([to_si(x) if isinstance(x, str) else float(x) * UNITS[d.units] for x in size])
    if not np.isfinite(target).all() or np.any(target < 0):
        raise ValueError("Dimensions must be finite and non-negative")
    lo, hi = [np.asarray(x, float) for x in obj.shape.bounds()]
    old = hi-lo
    scale = np.ones(3)
    for i in range(3):
        if old[i] <= 1e-15:
            if target[i] > 1e-15:
                raise ValueError("A zero-thickness sheet must be thickened using Sweep Face")
        elif target[i] <= 0:
            raise ValueError("A solid dimension must be positive")
        else:
            scale[i] = target[i]/old[i]
    if anchor not in ("center", "min"):
        raise ValueError("Choose center or min anchor")
    origin = (lo+hi)/2 if anchor == "center" else lo
    obj.shape.scale(*scale, origin=origin)
    d.mesh = None
    return {"ok": True, "size": target.tolist(), "scale": scale.tolist()}


@command("modeler.copy")
def _copy(s: Session, names: Optional[List[str]] = None, cut: bool = False, **_):
    """Copy the selection to the clipboard (Cut also removes it)."""
    d = s.require_design()
    targets = list(names or s.selection)
    if not targets:
        raise ValueError("select an object first")
    import copy as _c
    s.clipboard = [{"shape": _c.deepcopy(o.shape),
                    "material": getattr(o, "material", None),
                    "solve_inside": getattr(o, "solve_inside", True),
                    "sheet": o in d.sheets,
                    "base": o.name}
                   for o in _entities(d, targets)]
    if cut:
        d.solids = [o for o in d.solids if o.name not in targets]
        d.sheets = [o for o in d.sheets if o.name not in targets]
        d.mesh = None
        s.selection = []
    s.messages.add(f"{'Cut' if cut else 'Copied'} {len(s.clipboard)} object(s).",
                   "info", "modeler")
    return {"ok": True, "count": len(s.clipboard)}


@command("modeler.paste")
def _paste(s: Session, offset: Optional[Sequence] = None, **_):
    """Paste the clipboard as new objects, named to avoid collisions."""
    d = s.require_design()
    if not s.clipboard:
        raise RuntimeError("the clipboard is empty")
    import copy as _c
    made = []
    for item in s.clipboard:
        shape = _c.deepcopy(item["shape"])
        if offset:
            shape.translate(*offset)
        nm = naming.unique_name(naming.model_names(d), item["base"])
        shape.name = nm
        if item["sheet"]:
            d.add_sheet(nm, shape, item["material"])
        else:
            d.add_solid(nm, shape, item["material"] or "vacuum",
                        item["solve_inside"])
        made.append(nm)
    d.mesh = None
    s.dirty = True
    s.selection = made
    s.messages.add(f"Pasted {', '.join(made)}.", "info", "modeler")
    return {"ok": True, "names": made}


@command("modeler.duplicate")
def _duplicate(s: Session, names: Optional[List[str]] = None,
               mode: str = "line", count: int = 2,
               params: Optional[dict] = None, attach: bool = False, **_):
    """
    Duplicate ▸ Along Line / Around Axis / Mirror.

    ``count`` is the *total* number of objects including the original, which is
    the convention every modeller uses: 4 copies around a full circle means the
    original plus three more at 90-degree steps.
    """
    d = s.require_design()
    targets = list(names or s.selection)
    if not targets:
        raise ValueError("select an object first")
    p = params or {}
    import copy as _c
    total = max(int(count), 2) if mode != "mirror" else 2
    made: List[str] = []

    for o in _entities(d, targets):
        is_sheet = o in d.sheets
        for k in range(1, total):
            shape = _c.deepcopy(o.shape)
            if mode == "line":
                v = p.get("vector", ("0mm", "0mm", "0mm"))
                shape.translate(*[_scaled(v[i], k) for i in range(3)])
            elif mode == "axis":
                ax = p.get("axis", "z")
                # to_si returns radians; Shape.rotate converts again with a
                # degree default, so the step has to be handed over tagged.
                ang = math.degrees(to_si(p.get("angle", "360deg"),
                                         "angle", "deg"))
                step = ang / total if p.get("fullCircle", True) else ang
                shape.rotate(AXIS_VEC.get(str(ax).lower(), (0, 0, 1))
                             if isinstance(ax, str) else ax,
                             f"{step * k}deg", p.get("origin", (0, 0, 0)))
            elif mode == "mirror":
                shape.mirror(p.get("normal", (0, 0, 1)),
                             p.get("origin", (0, 0, 0)))
            else:
                raise ValueError(f"unknown duplicate mode {mode!r}")
            nm = naming.unique_name(naming.model_names(d), o.name)
            shape.name = nm
            if is_sheet:
                d.add_sheet(nm, shape, getattr(o, "material", None))
            else:
                d.add_solid(nm, shape, o.material, o.solve_inside)
            made.append(nm)

    if attach and made and mode != "mirror":
        base = d.get_solid(targets[0])
        base.shape = prim.union(base.shape, *[d.get_solid(n).shape
                                              for n in made])
        base.shape.name = base.name
        d.solids = [x for x in d.solids if x.name not in made]
        made = []

    d.mesh = None
    s.dirty = True
    s.selection = made or targets
    s.messages.add(
        f"Duplicate {mode}: {len(made)} new object(s)" +
        (f" — {', '.join(made[:6])}{' …' if len(made) > 6 else ''}"
         if made else " (united into the original)"), "info", "modeler")
    return {"ok": True, "names": made}


def _scaled(v, k: int) -> float:
    return to_si(v) * k


# --------------------------------------------------------------------------
# undo / redo
# --------------------------------------------------------------------------


@command("edit.undo")
def _undo(s: Session, **_):
    label = s.undo()
    return {"ok": True, "label": label}


@command("edit.redo")
def _redo(s: Session, **_):
    label = s.redo()
    return {"ok": True, "label": label}


@command("edit.history")
def _history(s: Session, **_):
    return {"canUndo": s.can_undo, "canRedo": s.can_redo,
            "undo": s.undo_label(), "redo": s.redo_label(),
            "clipboard": len(s.clipboard)}


@command("modeler.setProperty")
def _setprop(s: Session, name: str = "", prop: str = "", value: Any = None,
             names: Optional[List[str]] = None, **_):
    """Set one property on one object, or on every object in *names*.

    A multi-object edit is a single command, hence a single undo step; if any
    object refuses the value, none of them change (the dispatcher restores the
    snapshot it took before the command)."""
    if names:
        if prop == "name":
            raise ValueError("objects need distinct names; rename one at a time")
        for nm in names:
            _setprop(s, name=nm, prop=prop, value=value)
        s.messages.add(f"Set {prop} on {len(names)} object(s).", "info",
                       "modeler")
        return {"ok": True, "count": len(names)}
    d = s.require_design()
    o = _entity(d, name)
    if prop == "material":
        o.material = d.materials.get(str(value))
        o.import_material = ""
        d.mesh = None
    elif prop == "solveInside" and isinstance(o, Sheet):
        raise ValueError("a sheet has no inside to solve")
    elif prop == "name":
        new = naming.unique_name(
            [x.name for x in d.solids + d.sheets if x is not o], str(value))
        for mesh_op in d.mesh_ops:
            mesh_op.objects = [new if x == o.name else x for x in mesh_op.objects]
        o.name = new
        o.shape.name = new
        # boundaries and excitations reference the *shape object*, so a rename
        # cannot orphan them; the selection follows the new name
        s.selection = [new]
        s.messages.add(f"Renamed object to {new!r}.", "info", "modeler")
    elif prop == "solveInside":
        o.solve_inside = bool(value)
        d.mesh = None
    elif prop == "color":
        # An empty value clears the override and the material's colour is
        # used again, which is how a per-object colour is undone.
        o.display_color = str(value) or None
    elif prop == "transparency":
        o.display_transparency = None if value in ("", None) \
            else max(0.0, min(1.0, float(value)))
    elif prop == "visible":
        o.visible = bool(value)
    else:
        raise ValueError(f"unknown property {prop!r}")
    s.dirty = True
    return {"ok": True}


def _norm_body_name(n: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(n or "").lower())


@command("modeler.repairBodies")
def _repair_bodies(s: Session, path: str = "", unit: str = "auto",
                   mapping: Optional[dict] = None, apply: bool = False, **_):
    """
    Point every unreadable body at one STEP export, in a single step.

    A project whose parts are ACIS or Parasolid attachments imports
    with its structure intact and its geometry missing -- forty bodies, forty
    *Replace CAD Source* dialogs. What the engineer actually has is one STEP
    export of the same assembly, so the file is read once, its bodies are
    matched to the placeholders by name, and the mapping is offered for
    correction before anything is changed.
    """
    d = s.require_design()
    broken = [o.name for o in d.solids
              if getattr(o.shape, "_cad_unreadable", "")
              or getattr(o.shape, "_cad_missing", False)]
    if not broken:
        return {"ok": True, "broken": [], "bodies": [], "mapping": {},
                "applied": []}
    p = os.path.expanduser(path or "")
    if not p or not os.path.isfile(p):
        raise FileNotFoundError(path or "(no file chosen)")
    from ..geometry.brep_io import probe as _probe
    info = _probe(p, unit=None if unit in ("", "auto") else unit)
    if info.get("error"):
        raise RuntimeError(f"cannot read {os.path.basename(p)}: {info['error']}")
    bodies = [b for b in info.get("bodyList", []) if b.get("dim") == 3]
    if not bodies:
        raise RuntimeError(f"{os.path.basename(p)} contains no solid bodies")

    plan = {k: int(v) for k, v in (mapping or {}).items()
            if str(k) in broken and 0 <= int(v) < len(bodies)}
    if not mapping:
        taken = set()
        by_name = {}
        for b in bodies:
            by_name.setdefault(_norm_body_name(b.get("name")), []).append(b)
        for nm in broken:
            key = _norm_body_name(nm)
            cand = by_name.get(key) or next(
                (v for k, v in by_name.items()
                 if k and (k.startswith(key) or key.startswith(k))), None)
            for b in (cand or []):
                if b["index"] not in taken:
                    plan[nm] = b["index"]
                    taken.add(b["index"])
                    break
    if not apply:
        return {"ok": True, "broken": broken, "bodies": bodies,
                "mapping": plan, "applied": [],
                "file": os.path.basename(p), "unit": info.get("appliedUnit")}

    applied = []
    for nm, idx in plan.items():
        o = d.get_solid(nm)
        sh = prim.ImportedShape(p, name=nm, unit=unit or "auto", body=int(idx))
        try:
            tessellate(sh)
        except Exception as exc:
            s.messages.add(f"{nm}: body {idx} of "
                           f"{os.path.basename(p)} could not be read: {exc}",
                           "warning", "modeler")
            continue
        o.shape = sh
        applied.append(nm)
    d.import_issues = [i for i in getattr(d, "import_issues", [])
                       if not any(f"{nm!r}" in i for nm in applied)]
    d.mesh = None
    s.dirty = True
    clear_display_caches()
    left = [n for n in broken if n not in applied]
    s.messages.add(
        f"Repaired {len(applied)} body/bodies from {os.path.basename(p)}"
        + (f"; {len(left)} still without geometry: "
           + ", ".join(left[:6]) if left else "."),
        "info" if not left else "warning", "modeler")
    return {"ok": True, "broken": broken, "bodies": bodies, "mapping": plan,
            "applied": applied, "remaining": left}


@command("modeler.replaceCad")
def _replace_cad(s: Session, name: str = "", path: str = "",
                 unit: str = "", healing: Optional[bool] = None, **_):
    """
    Point an imported body at a different file, or read it at a different unit.

    Everything else about the object is kept -- its name, its material, its
    place in the tree, the transforms applied to it, and every boundary and
    port that refers to it -- because the shape object is edited in place
    rather than replaced. That is what makes a corrected unit or an updated
    revision of a CAD file a one-step operation instead of a rebuild.
    """
    from ..geometry.brep_io import inspect as _inspect
    d = s.require_design()
    o = d.get_solid(name)
    sh = o.shape
    replacing_primitive = not isinstance(sh, prim.ImportedShape)
    if replacing_primitive:
        if not path:raise ValueError("Choose a final-body STEP/BREP file to replace this geometry")
        sh=prim.ImportedShape(os.path.expanduser(path),unit=unit or "auto")
    new_path = os.path.expanduser(path) if path else sh.path
    if not os.path.isfile(new_path):
        raise FileNotFoundError(new_path)
    # A body that never had readable geometry has an unverified unit; a new
    # file brings its own declaration, so unless the caller says otherwise the
    # unit goes back to Auto rather than carrying a guess over.
    if unit:
        new_unit = unit
    elif path and getattr(sh, "_cad_unreadable", ""):
        new_unit = "auto"
    else:
        new_unit = sh.unit or "auto"
    info = _inspect(new_path, unit=new_unit)
    if info.get("error"):
        raise RuntimeError(f"cannot read {os.path.basename(new_path)}: "
                           f"{info['error']}")
    if not info["solids"] and not info["surfaces"]:
        raise RuntimeError(f"{os.path.basename(new_path)} contains no geometry")
    if replacing_primitive and info.get("solids",0)!=1:
        raise ValueError("Choose a single-solid STEP export matching this object")
    sh.path = new_path
    sh.unit = new_unit
    if healing is not None:
        sh.healing = bool(healing)
    sh._cad_missing = False
    sh._cad_unreadable = ""
    o.shape=sh
    d.import_issues=[issue for issue in getattr(d,"import_issues",[]) if not issue.startswith(f"Incomplete history for {name!r}:")]
    d.mesh = None
    s.dirty = True
    lo, hi = info["bbox"]
    ext = " x ".join(f"{(hi[k] - lo[k]) * 1e3:.3f}" for k in range(3))
    s.messages.add(
        f"{name}: source is now {os.path.basename(new_path)}, unit "
        f"{info['appliedUnit']}, extent {ext} mm.", "info", "modeler")
    return {"ok": True, "info": info}


@command("modeler.delete")
def _delete(s: Session, names: Optional[List[str]] = None, **_):
    d = s.require_design()
    for n in (names or []):
        d.solids = [o for o in d.solids if o.name != n]
        d.sheets = [o for o in d.sheets if o.name != n]
    d.mesh = None
    s.selection = []
    s.dirty = True
    s.messages.add(f"Deleted {', '.join(names or [])}.", "info", "modeler")
    return {"ok": True}


@command("modeler.select")
def _select(s: Session, names: Optional[List[str]] = None,
            faces: Optional[List[dict]] = None,
            edges: Optional[List[dict]] = None,
            mode: str = "", add: bool = False, **_):
    """
    Set the selection: whole objects, picked faces, picked edges, or nothing.

    ``add`` extends the current selection the way Ctrl-click does, so the UI
    and the console reach the same state through the same command.
    """
    if mode:
        if mode not in ("object", "face", "edge", "point"):
            raise ValueError(f"unknown selection mode {mode!r}")
        s.select_mode = mode
    if names is not None:
        s.selection = sorted(set(s.selection) | set(names)) if add else list(names)
    if faces is not None:
        s.sel_faces = (s.sel_faces + list(faces)) if add else list(faces)
    if edges is not None:
        s.sel_edges = (s.sel_edges + list(edges)) if add else list(edges)
    if names is None and faces is None and edges is None and not mode:
        s.clear_picks()
    return {"ok": True, "objects": len(s.selection),
            "faces": len(s.sel_faces), "edges": len(s.sel_edges)}


@command("modeler.selectMode")
def _select_mode(s: Session, mode: str = "object", **_):
    """Object / Face / Edge picking, the way a modeller switches with O F E."""
    if mode not in ("object", "face", "edge", "point"):
        raise ValueError(f"unknown selection mode {mode!r}")
    s.select_mode = mode
    # Picks of another kind would linger invisibly and end up in the next
    # assignment, so switching modes clears them.
    if mode != "face":
        s.sel_faces = []
    if mode != "edge":
        s.sel_edges = []
    return {"ok": True, "mode": mode}


@command("modeler.measure")
def _measure(s: Session, mode: str = "selection", points=None, units: str = "", **_):
    """
    Measure what is picked, the way a modeller does.

    * one edge          -> its length, and its endpoints
    * two edges         -> both lengths and the distance between them
    * one face          -> its area and its extent
    * two faces         -> the gap between them, and whether they are parallel
    * objects           -> overall size, and the gap between two of them

    The distance between two faces is the *minimum* separation, computed
    between the tessellated surfaces -- which is the number that matters for a
    coupling gap or a clearance, and is right whether or not the faces are
    parallel. When they are parallel it also reports the plane-to-plane
    distance, because that is the dimension you would put on a drawing.
    """
    d = s.design
    if mode != "selection":
        from .measurement import measure_points
        return measure_points(mode, points, units or (d.units if d else "mm"))
    out: Dict[str, Any] = {"kind": "", "text": "nothing picked",
                           "units": (d.units if d else "mm")}
    faces, edges, objs = s.sel_faces, s.sel_edges, list(s.selection)

    if len(edges) >= 1:
        lens = [float(e.get("length", 0.0)) for e in edges]
        out["kind"] = "edge"
        out["accuracy"] = "Vertex-bounded edge chain; curved edges are tessellated."
        out["lengths"] = lens
        if len(edges) == 1:
            out["line"] = [edges[0]["a"], edges[0]["b"]]
            out["distance"] = lens[0]
        out["total"] = float(sum(lens))
        if len(edges) >= 2:
            from .measurement import vector_angle
            va = np.asarray(edges[0]["b"]) - np.asarray(edges[0]["a"])
            vb = np.asarray(edges[1]["b"]) - np.asarray(edges[1]["a"])
            if not edges[0].get("segments") and not edges[1].get("segments") and np.linalg.norm(va) > 0 and np.linalg.norm(vb) > 0:
                out["angle"] = vector_angle(va, vb)
            segments=lambda e: [{"a":a,"b":b} for a,b in e.get("segments",[[e["a"],e["b"]]])]
            dist,p1,p2=min((_segment_distance(a,b) for a in segments(edges[0]) for b in segments(edges[1])),key=lambda r:r[0])
            out["distance"] = dist
            out["line"] = [[float(x) for x in p1], [float(x) for x in p2]]
        out["text"] = _fmt_measure(out, d)
        return out

    if len(faces) >= 1:
        areas = [float(f.get("area", 0.0)) for f in faces]
        out["kind"] = "face"
        out["accuracy"] = "Tessellation area; face gap is a sampled estimate, not CAD clearance."
        out["areas"] = areas
        out["total"] = float(sum(areas))
        lo = np.min([np.asarray(f["lo"], float) for f in faces], axis=0)
        hi = np.max([np.asarray(f["hi"], float) for f in faces], axis=0)
        out["size"] = [float(x) for x in (hi - lo)]
        if len(faces) >= 2:
            a, b = faces[0], faces[1]
            dist, p1, p2 = _face_gap(a, b)
            out["distance"] = dist
            out["line"] = [[float(x) for x in p1], [float(x) for x in p2]]
            na = np.asarray(a["normal"], float)
            nb = np.asarray(b["normal"], float)
            parallel = abs(float(na @ nb)) > 0.999
            out["parallel"] = parallel
            if parallel:
                out["planeDistance"] = float(abs(
                    (np.asarray(b["point"], float)
                     - np.asarray(a["point"], float)) @ na))
        out["text"] = _fmt_measure(out, d)
        return out

    if objs and d is not None:
        boxes = []
        for n in objs:
            try:
                boxes.append([np.asarray(x, float)
                              for x in _entity(d, n).shape.bounds()])
            except Exception:
                continue
        if boxes:
            lo = np.min([b[0] for b in boxes], axis=0)
            hi = np.max([b[1] for b in boxes], axis=0)
            out["kind"] = "object"
            out["size"] = [float(x) for x in (hi - lo)]
            out["bbox"] = [[float(x) for x in lo], [float(x) for x in hi]]
            out["objects"] = objs
            out["accuracy"] = "Axis-aligned bounding box; gap is a lower bound, not surface clearance."
            out["bboxVolume"] = float(np.prod(hi - lo))
            out["center"] = ((lo + hi) / 2).tolist()
            out["diagonal"] = float(np.linalg.norm(hi - lo))
            if len(objs) == 1:
                from .measurement import primitive_properties
                out["primitive"] = primitive_properties(_entity(d, objs[0]).shape)
            if len(boxes) >= 2:
                dist, p1, p2 = _box_gap(boxes[0], boxes[1])
                out["distance"] = dist
                out["line"] = [[float(x) for x in p1], [float(x) for x in p2]]
            out["text"] = _fmt_measure(out, d)
    return out


def _closest(a: np.ndarray, b: np.ndarray):
    """(distance, point on a, point on b) for two clouds of sample points."""
    dist = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)
    i, j = np.unravel_index(int(np.argmin(dist)), dist.shape)
    return float(dist[i, j]), a[i], b[j]


def _segment_distance(e1: dict, e2: dict):
    """Exact closest points on the two picked straight segments."""
    from .measurement import segment_distance
    return segment_distance(e1["a"], e1["b"], e2["a"], e2["b"])


def _face_gap(f1: dict, f2: dict):
    """
    Smallest distance between two picked faces.

    Sampled over each face's extent rather than taken between their centres:
    two faces of very different size, or offset from one another, have a gap
    that has nothing to do with the distance between their middles.
    """
    def grid(f):
        lo = np.asarray(f["lo"], float)
        hi = np.asarray(f["hi"], float)
        axes = []
        for k in range(3):
            n = 1 if hi[k] - lo[k] < 1e-12 else 9
            axes.append(np.linspace(lo[k], hi[k], n))
        g = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
        # keep the samples on the face's own plane
        p = np.asarray(f["point"], float)
        n = np.asarray(f["normal"], float)
        if bool(f.get("planar", True)):
            g = g - np.outer((g - p) @ n, n)
        return g

    return _closest(grid(f1), grid(f2))


def _box_gap(b1, b2):
    """Axis-aligned gap between two bounding boxes; 0 when they overlap."""
    lo1, hi1 = b1
    lo2, hi2 = b2
    p1 = np.clip((lo2 + hi2) / 2.0, lo1, hi1)
    p2 = np.clip(p1, lo2, hi2)
    d = np.maximum(np.maximum(lo1 - hi2, lo2 - hi1), 0.0)
    return float(np.linalg.norm(d)), p1, p2


def _fmt_measure(m: dict, d) -> str:
    """One line, in the model's own units."""
    u = (d.units if d else "mm")
    k = {"m": 1.0, "cm": 1e-2, "mm": 1e-3, "um": 1e-6, "mil": 2.54e-5,
         "in": 2.54e-2}.get(u, 1e-3)

    def L(v):
        return f"{v / k:.6g} {u}"

    def A(v):
        return f"{v / (k * k):.6g} {u}²"

    if m["kind"] == "edge":
        parts = ["length " + " + ".join(L(x) for x in m["lengths"])]
        if len(m["lengths"]) > 1:
            parts.append("total " + L(m["total"]))
        if "distance" in m:
            if len(m["lengths"]) > 1:
                parts.append("segment gap " + L(m["distance"]))
        if "angle" in m:
            parts.append(f"angle {m['angle']:.6g}°")
        return ", ".join(parts)
    if m["kind"] == "face":
        parts = ["area " + A(m["total"])]
        parts.append("extent " + " × ".join(L(x) for x in m["size"]))
        if "distance" in m:
            parts.append(("parallel, " if m.get("parallel") else "")
                         + "estimated gap " + L(m["distance"]))
        if "planeDistance" in m:
            parts.append("plane spacing " + L(m["planeDistance"]))
        return ", ".join(parts)
    if m["kind"] == "object":
        parts = ["size " + " × ".join(L(x) for x in m["size"])]
        if "distance" in m:
            parts.append("bounding-box gap " + L(m["distance"]))
        return ", ".join(parts)
    return "nothing picked"


@command("modeler.selectionInfo")
def _selection_info(s: Session, **_):
    """What is picked right now, with the numbers a modeller shows for it."""
    d = s.design
    area = sum(float(f.get("area", 0.0)) for f in s.sel_faces)
    length = sum(float(e.get("length", 0.0)) for e in s.sel_edges)
    out = {"mode": s.select_mode, "objects": list(s.selection),
           "faces": len(s.sel_faces), "edges": len(s.sel_edges),
           "faceArea": area, "edgeLength": length}
    if d is not None and s.selection:
        lo = np.array([np.inf] * 3)
        hi = np.array([-np.inf] * 3)
        for n in s.selection:
            try:
                a, b = _entity(d, n).shape.bounds()
            except Exception:
                continue
            lo = np.minimum(lo, a)
            hi = np.maximum(hi, b)
        if np.all(np.isfinite(lo)):
            out["bbox"] = [list(map(float, lo)), list(map(float, hi))]
    return out


# ==========================================================================
# boundaries and excitations
# ==========================================================================


def _face_selector(f: dict) -> FaceSelector:
    """A picked face, as it comes back from the viewport."""
    return FaceSelector(point=f.get("point", (0, 0, 0)),
                        normal=f.get("normal", (0, 0, 1)),
                        lo=f.get("lo", (0, 0, 0)), hi=f.get("hi", (0, 0, 0)),
                        planar=bool(f.get("planar", True)),
                        object=str(f.get("object", "")))


def _make_selector(d, spec: dict):
    kind = (spec or {}).get("kind", "outer")
    if kind == "plane":
        return PlaneSelector(spec.get("axis", "z"), spec.get("value", 0.0),
                             tol=spec.get("tol", 1e-9),
                             window=spec.get("window"))
    if kind == "box":
        return BoxSelector(spec.get("lo", (0, 0, 0)), spec.get("hi", (1, 1, 1)))
    if kind == "bboxface":
        return BoundingBoxFaceSelector(spec.get("face", "+z"))
    if kind == "object":
        names = spec.get("objects") or ([spec["object"]] if spec.get("object")
                                        else [])
        # solids and sheets alike: a port or boundary is often a drawn face
        shapes = [_entity(d, n).shape for n in names]
        if not shapes:
            raise ValueError("no object selected for this assignment")
        sh = shapes[0] if len(shapes) == 1 else prim.union(*shapes)
        return ShapeSelector(sh, tol=1e-7)
    if kind == "faces":
        picks = spec.get("faces") or []
        if not picks:
            raise ValueError("no face is picked for this assignment")
        sels = [_face_selector(f) for f in picks]
        return sels[0] if len(sels) == 1 else MultiFaceSelector(sels)
    if kind == "outerExceptPorts":
        excl = union_sel(*[p.selector for p in d.ports]) if d.ports else None
        return OuterSelector(exclude=excl)
    return OuterSelector()


@command("boundary.assign")
def _assign_bnd(s: Session, type: str = "pec", name: str = "",
                selector: Optional[dict] = None, params: Optional[dict] = None,
                **_):
    d = s.require_design()
    p = dict(params or {})
    nm = (naming.unique_name([b.name for b in d.boundaries], name) if name
          else naming.suggest_boundary(d, type))
    sel = _make_selector(d, selector or {"kind": "outer"})
    if type == "finite_cond":
        d.assign_finite_conductivity(
            nm, sel, material=p.get("material", "copper"),
            thickness=p.get("thickness"), roughness=p.get("roughness", 0.0))
    elif type == "impedance":
        d.assign_impedance(nm, sel, complex(p.get("R", 0.0), p.get("X", 0.0)))
    elif type == "lumped_rlc":
        d.assign_lumped_rlc(nm, sel, R=_num(p.get("R", 0.0)), L=_num(p.get("L", 0.0)),
                            C=_num(p.get("C", 0.0)),
                            parallel=bool(p.get("parallel", True)),
                            direction=p.get("direction"))
    else:
        d.assign_boundary(nm, type, sel)
    s.dirty = True
    n = _warn_if_empty(s, d, sel, nm, "Boundary")
    s.messages.add(f"Assigned {type} boundary {nm!r}"
                   + (f" — {n} face triangles." if n > 0 else "."),
                   "info", "boundary")
    return {"ok": True, "name": nm, "faces": n}


def _num(v) -> float:
    """A number typed with an engineering suffix (``2.2n``, ``0.5p``, ``1k``)."""
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace("Ω", "").replace("ohm", "").replace("H", "").replace("F", "")
    if not t:
        return 0.0
    mult = {"T": 1e12, "G": 1e9, "M": 1e6, "k": 1e3, "K": 1e3, "m": 1e-3, "u": 1e-6, "µ": 1e-6,
            "n": 1e-9, "p": 1e-12, "f": 1e-15}
    if t[-1] in mult and not t[-1].isdigit():
        return float(t[:-1]) * mult[t[-1]]
    return float(t)


@command("boundary.autoRlc")
def _auto_rlc(s: Session, name: str = "", signal: Optional[list] = None,
              ground: Optional[list] = None, R: Any = 0.0, L: Any = 0.0, C: Any = 0.0,
              parallel: bool = True, end: str = "", preview: bool = False, **_):
    """
    A lumped R / L / C element between two conductors: a sheet that bridges
    the gap (sized from the signal where it ends, like an automatic lumped
    port) carrying a Lumped RLC boundary whose current runs signal -> ground.
    """
    from . import autoport as ap
    d = s.require_design()
    pm = _marks(s)
    S = ap.marks_from_picks(d, signal if signal is not None else pm["signal"], "signal")
    G = ap.marks_from_picks(d, ground if ground is not None else pm["ground"], "ground")
    D_lo, D_hi = (np.asarray(v, float) for v in d.bounding_box())
    plan = ap.plan_lumped(S, G, D_lo, D_hi, [], end)
    text = (f"Lumped RLC: {plan['width'] * 1e3:.4g} mm wide x {plan['gap'] * 1e3:.4g} mm gap "
            f"along {'XYZ'[plan['axis']]} ({plan['note']}).")
    if preview:
        return {"ok": True, "preview": True, "text": text}
    r_, l_, c_ = _num(R), _num(L), _num(C)
    if not (r_ or l_ or c_):
        raise ValueError("enter a resistance, an inductance or a capacitance")
    nm = (naming.unique_name([b.name for b in d.boundaries], name) if name
          else naming.suggest_boundary(d, "lumped_rlc"))
    sheet_name = naming.unique_name([o.name for o in d.solids] + [o.name for o in d.sheets], nm + "_sheet")
    sheet = prim.Polygon([[float(v) for v in q] for q in plan["corners"]], name=sheet_name)
    d.add_sheet(sheet_name, sheet)
    sel = ShapeSelector(sheet, tol=1e-7)
    d.assign_lumped_rlc(nm, sel, R=r_, L=l_, C=c_, parallel=bool(parallel),
                        direction=[float(v) for v in plan["direction"]])
    d.mesh = None
    s.dirty = True
    n = _warn_if_empty(s, d, sel, nm, "Lumped RLC")
    s.messages.add(f"Lumped RLC {nm!r}: " + ", ".join(
        f"{lab} = {v:g}" for lab, v in (("R", r_), ("L", l_), ("C", c_)) if v)
        + (" in parallel" if parallel and sum(bool(v) for v in (r_, l_, c_)) > 1 else
           " in series" if sum(bool(v) for v in (r_, l_, c_)) > 1 else "") + f". {text}",
        "info", "boundary")
    pm["signal"], pm["ground"] = [], []
    return {"ok": True, "name": nm, "sheet": sheet_name, "faces": n, "gap": plan["gap"],
            "width": plan["width"]}


@command("boundary.delete")
def _del_bnd(s: Session, name: str = "", **_):
    d = s.require_design()
    d.boundaries = [b for b in d.boundaries if b.name != name]
    s.dirty = True
    return {"ok": True}


@command("excitation.assign")
def _assign_port(s: Session, kind: str = "wave", name: str = "",
                 selector: Optional[dict] = None, params: Optional[dict] = None,
                 **_):
    d = s.require_design()
    p = dict(params or {})
    nm = (naming.unique_name([p_.name for p_ in d.ports], name) if name
          else naming.suggest_port(d, kind))
    sel = _make_selector(d, selector or {"kind": "plane"})
    line = None
    if p.get("line"):
        a, b = p["line"]
        line = (tuple(to_si(x) for x in a), tuple(to_si(x) for x in b))
    direction = p.get("direction", (0, 0, 1))
    if kind == "lumped" and p.get("ground") and p.get("signal"):
        # polarity as Warps states it: an integration line from the signal
        # conductor to the ground; the port field points along it
        g = np.array([to_si(x) for x in p["ground"]], float)
        sg = np.array([to_si(x) for x in p["signal"]], float)
        v = g - sg
        if float(np.linalg.norm(v)) <= 1e-12:
            raise ValueError("the signal and ground points are the same")
        direction = [float(x) for x in v / np.linalg.norm(v)]
        line = (tuple(float(x) for x in sg), tuple(float(x) for x in g))
    if kind == "wave":
        d.add_wave_port(nm, selector=sel, num_modes=int(p.get("modes", 1)),
                        deembed=p.get("deembed", 0.0),
                        renormalize_z=p.get("renorm"),
                        integration_line=line)
    else:
        d.add_lumped_port(nm, selector=sel,
                          impedance=complex(p.get("impedance", 50.0)),
                          direction=direction,
                          integration_line=line)
    s.dirty = True
    n = _warn_if_empty(s, d, sel, nm, "Port")
    s.messages.add(f"Assigned {kind} port {nm!r}"
                   + (f" — {n} face triangles." if n > 0 else "."),
                   "info", "excitation")
    return {"ok": True, "name": nm, "faces": n}


def _pick_geometry(picks):
    """Centre, normal and extent of a set of picked faces."""
    pts = np.array([[to_si(x) for x in f.get("point", (0, 0, 0))]
                    for f in picks], float)
    nrm = np.array([[float(x) for x in f.get("normal", (0, 0, 1))]
                    for f in picks], float)
    lo = np.array([[to_si(x) for x in f.get("lo", (0, 0, 0))] for f in picks],
                  float).min(axis=0)
    hi = np.array([[to_si(x) for x in f.get("hi", (0, 0, 0))] for f in picks],
                  float).max(axis=0)
    n = nrm.mean(axis=0)
    ln = float(np.linalg.norm(n))
    n = n / ln if ln > 1e-12 else np.array([0.0, 0.0, 1.0])
    return pts.mean(axis=0), n, lo, hi


@command("excitation.assignBetween")
def _assign_port_between(s: Session, kind: str = "lumped", name: str = "",
                         signal: Optional[List[dict]] = None,
                         ground: Optional[List[dict]] = None,
                         params: Optional[dict] = None, **_):
    """
    A port from two mouse picks: the signal conductor and its return.

    This is how a port is actually specified -- "between this pin and that
    ground" -- and it is what the usual pick-two-objects flow means. A lumped
    port needs a sheet bridging the gap, so one is built: a rectangle
    spanning from the signal face to the ground face, no wider than the
    narrower of the two, with the integration line running signal -> ground
    so the sign of V (and therefore of the port impedance) is the one the
    engineer intended. A wave port is assigned to the picked signal face
    itself, and the ground pick only orients its integration line.
    """
    d = s.require_design()
    p = dict(params or {})
    sig = list(signal or [])
    gnd = list(ground or [])
    if not sig:
        raise ValueError("pick the signal conductor's face first")
    nm = (naming.unique_name([x.name for x in d.ports], name) if name
          else naming.suggest_port(d, kind))

    sc, sn, slo, shi = _pick_geometry(sig)
    if kind != "wave":
        # The sheet is sized from the signal where it is fed and put against the
        # ground: see aether.gui.autoport. (Centre-to-centre of two faces only
        # works when they happen to be stacked.)
        return _auto_port(s, kind="lumped", name=name, signal=sig, ground=gnd,
                          impedance=p.get("impedance", 50.0))
    if kind == "wave":
        sel = _make_selector(d, {"kind": "faces", "faces": sig})
        line = None
        if gnd:
            from . import autoport as ap
            try:
                S_ = ap.marks_from_picks(d, sig, "signal")
                G_ = ap.marks_from_picks(d, gnd, "ground")
                D_lo, D_hi = (np.asarray(v, float) for v in d.bounding_box())
                plan = ap.plan_wave(S_, G_, D_lo, D_hi)
                line = (tuple(float(v) for v in plan["signal"]), tuple(float(v) for v in plan["ground"]))
            except Exception:                                     # noqa: BLE001
                gc = _pick_geometry(gnd)[0]
                line = (tuple(sc), tuple(gc))     # signal -> ground
        d.add_wave_port(nm, selector=sel, num_modes=int(p.get("modes", 1)),
                        deembed=p.get("deembed", 0.0),
                        renormalize_z=p.get("renorm"), integration_line=line)
        s.dirty = True
        n = _warn_if_empty(s, d, sel, nm, "Port")
        s.messages.add(
            f"Wave port {nm!r} on {len(sig)} picked face(s)"
            + (" with an integration line from the signal to the ground pick." if line
               else " — pick a ground face too if this is a TEM line."),
            "info", "excitation")
        return {"ok": True, "name": nm, "faces": n}

    if not gnd:
        raise ValueError("a lumped port needs a ground pick as well as a "
                         "signal pick")
    gc, gn, glo, ghi = _pick_geometry(gnd)
    gap = gc - sc
    length = float(np.linalg.norm(gap))
    if length <= 1e-12:
        raise ValueError("the signal and ground picks are at the same point")
    u = gap / length                      # signal -> ground direction

    # The sheet spans the gap along u and the narrower face's width across it.
    # "Across" is whichever axis of the two faces is most perpendicular to u.
    axes = [np.eye(3)[i] for i in range(3)]
    span_s = shi - slo
    span_g = ghi - glo
    best, wide = None, -1.0
    for a in axes:
        if abs(float(np.dot(a, u))) > 0.9:
            continue
        w = min(float(abs(np.dot(span_s, a))), float(abs(np.dot(span_g, a))))
        if w > wide:
            best, wide = a, w
    if best is None or wide <= 0:
        # degenerate picks (an edge-on face, a point) -- fall back to a square
        best = np.cross(u, [0, 0, 1.0])
        if float(np.linalg.norm(best)) < 1e-9:
            best = np.cross(u, [0, 1.0, 0])
        best = best / float(np.linalg.norm(best))
        wide = length
    half = best * (wide / 2.0)
    pts = [sc - half, sc + half, gc + half, gc - half]
    sheet_name = naming.unique_name(
        [o.name for o in d.solids] + [o.name for o in d.sheets], nm + "_sheet")
    sheet = prim.Polygon([[float(v) for v in q] for q in pts], name=sheet_name)
    d.add_sheet(sheet_name, sheet)
    sel = ShapeSelector(sheet, tol=1e-7)
    d.add_lumped_port(nm, selector=sel,
                      impedance=complex(p.get("impedance", 50.0)),
                      direction=[float(v) for v in u],      # signal -> ground
                      integration_line=(tuple(sc), tuple(gc)))
    d.mesh = None
    s.dirty = True
    n = _warn_if_empty(s, d, sel, nm, "Port")
    s.messages.add(
        f"Lumped port {nm!r}: {p.get('impedance', 50.0)} Ω across a "
        f"{wide * 1e3:.3f} x {length * 1e3:.3f} mm sheet {sheet_name!r}, "
        "integration line from signal to ground.", "info", "excitation")
    return {"ok": True, "name": nm, "sheet": sheet_name, "faces": n,
            "gap": length, "width": wide}


def _lumped_ends(d, port):
    """``(signal, ground)`` points of a lumped port, in metres.

    The integration line runs from the signal conductor to the ground, and the
    port's electric field points along it (field from + to -, as usual). A
    port with an explicit line has both ends; one defined only by a field
    direction has them implied: the port face's extent along that direction,
    signal at the low end, ground at the high end."""
    if getattr(port, "integration_line", None):
        a, b = port.integration_line
        return np.asarray(a, float), np.asarray(b, float)
    got = _model_triangles(d)
    if got is None:
        return None
    tris, cent, nrm = got
    try:
        m = np.asarray(port.selector(cent, nrm), bool)
    except Exception:                                         # noqa: BLE001
        return None
    if not m.any():
        return None
    v = tris[m].reshape(-1, 3)
    u = np.asarray(port.direction, float)
    u = u / max(float(np.linalg.norm(u)), 1e-300)
    proj = v @ u
    c = v.mean(axis=0)
    pc = float(c @ u)
    return c + u * (float(proj.min()) - pc), c + u * (float(proj.max()) - pc)


@command("excitation.portGeometry")
def _port_geometry(s: Session, selector: Optional[dict] = None, name: str = "",
                   **_):
    """Where a port face is (centre, extent) and, for a lumped port, which end
    is ground and which is signal. Lengths in metres."""
    d = s.require_design()
    port = None
    if name:
        port = d.get_port(name)
        sel = port.selector
    else:
        sel = _make_selector(d, selector or {"kind": "plane"})
    got = _model_triangles(d)
    if got is None:
        raise ValueError("there is no geometry to take a port from")
    tris, cent, nrm = got
    m = np.asarray(sel(cent, nrm), bool)
    if not m.any():
        raise ValueError("the selection does not touch any face of the model")
    v = tris[m].reshape(-1, 3)
    out = {"center": [float(x) for x in v.mean(axis=0)],
           "lo": [float(x) for x in v.min(axis=0)],
           "hi": [float(x) for x in v.max(axis=0)], "faces": int(m.sum())}
    if port is not None and port.kind == "lumped":
        ends = _lumped_ends(d, port)
        if ends is not None:
            out["signal"] = [float(x) for x in ends[0]]
            out["ground"] = [float(x) for x in ends[1]]
            out["derived"] = getattr(port, "integration_line", None) is None
    return out


@command("excitation.setPolarity")
def _set_polarity(s: Session, name: str = "", ground: Optional[list] = None,
                  signal: Optional[list] = None, flip: bool = False, **_):
    """Set which end of a lumped port is signal and which is ground.

    The integration line runs signal -> ground and the port field points along
    it. ``flip`` swaps the present ends (reverses the sign of the port
    voltage, so S21 between two such ports changes by 180 degrees); otherwise
    give both points."""
    d = s.require_design()
    port = d.get_port(name)
    if port.kind != "lumped":
        raise ValueError("polarity applies to lumped ports; a wave port gets "
                         "its polarity from its integration line")
    if flip:
        ends = _lumped_ends(d, port)
        if ends is None:
            raise ValueError("the port does not touch the model, so its ends "
                             "cannot be found")
        sg, g = ends[1], ends[0]                 # swap: old ground is the signal
    else:
        if not ground or not signal:
            raise ValueError("give the signal and the ground point")
        g = np.array([to_si(x) for x in ground], float)
        sg = np.array([to_si(x) for x in signal], float)
    v = g - sg
    L = float(np.linalg.norm(v))
    if L <= 1e-12:
        raise ValueError("the signal and ground points are the same")
    port.integration_line = (tuple(float(x) for x in sg),
                             tuple(float(x) for x in g))
    port.direction = tuple(float(x) for x in v / L)
    d.mesh = None
    s.dirty = True
    s.messages.add(f"Port {name!r}: field from signal to ground along "
                   f"({port.direction[0]:+.2f}, {port.direction[1]:+.2f}, "
                   f"{port.direction[2]:+.2f}).", "info", "excitation")
    return {"ok": True, "direction": list(port.direction)}


def _marks(s: Session) -> dict:
    """Signal / ground marks of the open design (reset when the design changes)."""
    d = s.design
    pm = getattr(s, "port_marks", None)
    if pm is None or d is None or pm.get("design") != d.name:
        pm = {"design": d.name if d is not None else "", "signal": [], "ground": []}
        s.port_marks = pm
    return pm


@command("portmarks.set")
def _port_marks_set(s: Session, role: str = "signal", picks: Optional[list] = None,
                    mode: str = "replace", **_):
    """Mark objects, faces or edges as the signal or the ground of a port."""
    if role not in ("signal", "ground"):
        raise ValueError("role must be signal or ground")
    s.require_design()
    pm = _marks(s)
    new = [dict(p_) for p_ in (picks or [])]
    if not new:
        raise ValueError("select the conductor (or a face / edge of it) first")
    other = "ground" if role == "signal" else "signal"
    # something cannot be both: moving an object to the other role removes it here
    names = {p_.get("name") for p_ in new if p_.get("kind", "object") == "object"}
    pm[other] = [p_ for p_ in pm[other]
                 if not (p_.get("kind", "object") == "object" and p_.get("name") in names)]
    pm[role] = (pm[role] + new) if mode == "add" else new
    s.messages.add(f"Marked {len(new)} item(s) as {role} "
                   f"({len(pm['signal'])} signal, {len(pm['ground'])} ground).",
                   "info", "excitation")
    return {"ok": True, "signal": len(pm["signal"]), "ground": len(pm["ground"])}


@command("portmarks.clear")
def _port_marks_clear(s: Session, **_):
    pm = _marks(s)
    pm["signal"], pm["ground"] = [], []
    return {"ok": True}


@command("excitation.autoPort")
def _auto_port(s: Session, kind: str = "auto", name: str = "",
               signal: Optional[list] = None, ground: Optional[list] = None,
               impedance: Any = 50.0, modes: int = 1, end: str = "", preview: bool = False, **_):
    """
    A port made from the marked signal and ground: no coordinates.

    ``kind``  ``lumped``, ``wave`` or ``auto`` (wave when the line runs out to
    the model boundary, lumped when the conductors sit inside it).
    """
    from . import autoport as ap
    d = s.require_design()
    pm = _marks(s)
    S = ap.marks_from_picks(d, signal if signal is not None else pm["signal"], "signal")
    G = ap.marks_from_picks(d, ground if ground is not None else pm["ground"], "ground")
    D_lo, D_hi = (np.asarray(v, float) for v in d.bounding_box())
    chosen = kind if kind in ("lumped", "wave") else ap.choose_kind(S, G, D_lo, D_hi)
    nm = naming.suggest_port(d, chosen)
    axname = "XYZ"
    if chosen == "lumped":
        plan = ap.plan_lumped(S, G, D_lo, D_hi, ap.taken_planes(d), end)
        if preview:
            return {"ok": True, "preview": True, "kind": "lumped", "text": (
                f"Lumped port: {plan['width'] * 1e3:.4g} mm wide x {plan['gap'] * 1e3:.4g} mm gap "
                f"along {axname[plan['axis']]} at {axname[plan['plane_axis']]} = {plan['plane_at'] * 1e3:.4g} mm "
                f"({plan['note']}); field from signal to ground.")}
        sheet_name = naming.unique_name([o.name for o in d.solids] + [o.name for o in d.sheets],
                                        nm + "_sheet")
        sheet = prim.Polygon([[float(v) for v in q] for q in plan["corners"]], name=sheet_name)
        d.add_sheet(sheet_name, sheet)
        sel = ShapeSelector(sheet, tol=1e-7)
        d.add_lumped_port(nm, selector=sel, impedance=complex(to_si(impedance) if isinstance(impedance, str)
                                                              else impedance),
                          direction=[float(v) for v in plan["direction"]],
                          integration_line=(tuple(float(v) for v in plan["signal"]),
                                            tuple(float(v) for v in plan["ground"])))
        d.mesh = None
        s.dirty = True
        n = _warn_if_empty(s, d, sel, nm, "Port")
        lam = ap.wavelength_hint(d)
        msg = (f"Lumped port {nm!r}: {plan['gap'] * 1e3:.4g} mm gap along {axname[plan['axis']]}, "
               f"{plan['width'] * 1e3:.4g} mm wide, at {axname[plan['plane_axis']]} = "
               f"{plan['plane_at'] * 1e3:.4g} mm; field from signal to ground.")
        s.messages.add(msg, "info", "excitation")
        if lam and plan["gap"] > lam / 10.0:
            s.messages.add(f"The gap ({plan['gap'] * 1e3:.3g} mm) is more than a tenth of a wavelength "
                           f"({lam * 1e3:.3g} mm): a lumped port is not accurate here; use a wave port.",
                           "warning", "excitation")
        out = {"kind": "lumped", "sheet": sheet_name, "faces": n, "gap": plan["gap"],
               "width": plan["width"]}
    else:
        plan = ap.plan_wave(S, G, D_lo, D_hi, ap.taken_planes(d), end)
        if preview:
            return {"ok": True, "preview": True, "kind": "wave", "text": (
                f"Wave port on the {axname[plan['axis']]} = {plan['at'] * 1e3:.4g} mm plane: {plan['note']}."
                + ("" if plan["on_boundary"] else " (not on the model boundary)"))}
        sel = PlaneSelector(axname[plan["axis"]].lower(), plan["at"], tol=1e-7,
                            window=plan["window"])
        d.add_wave_port(nm, selector=sel, num_modes=int(modes),
                        integration_line=(tuple(float(v) for v in plan["signal"]),
                                          tuple(float(v) for v in plan["ground"])))
        d.mesh = None
        s.dirty = True
        n = _warn_if_empty(s, d, sel, nm, "Port")
        s.messages.add(f"Wave port {nm!r} on the {axname[plan['axis']]} = {plan['at'] * 1e3:.4g} mm "
                       f"plane: {plan['note']}; integration line from signal to ground.",
                       "info", "excitation")
        if not plan["on_boundary"]:
            s.messages.add("The port plane is not on the outer boundary of the model, so it may find "
                           "no face to attach to. Extend the conductors (and the air region) out to "
                           "the boundary, or choose a lumped port.", "warning", "excitation")
        out = {"kind": "wave", "faces": n, "plane": axname[plan["axis"]].lower(),
               "at": plan["at"], "onBoundary": plan["on_boundary"], "note": plan["note"]}
    pm["signal"], pm["ground"] = [], []           # consumed
    return dict(out, ok=True, name=nm)


@command("excitation.delete")
def _del_port(s: Session, name: str = "", **_):
    d = s.require_design()
    d.ports = [p for p in d.ports if p.name != name]
    for i, p in enumerate(d.ports):
        p.index = i
    s.dirty = True
    return {"ok": True}


# ==========================================================================
# analysis
# ==========================================================================


def _apply_setup_options(st, kw) -> None:
    """The Warps solution-setup fields, validated; shared by add and edit."""
    if "frequency" in kw:
        st.frequency = to_si(kw["frequency"], "frequency")
    if "maxPasses" in kw:
        st.max_passes = int(kw["maxPasses"])
    if "minPasses" in kw:
        st.min_passes = int(kw["minPasses"])
    if "minConverged" in kw:
        st.min_converged = int(kw["minConverged"])
    if "deltaS" in kw:
        st.delta_s = float(kw["deltaS"])
    if "refinement" in kw and kw["refinement"] not in (None, ""):
        pct = float(kw["refinement"])
        if not 1.0 <= pct <= 100.0:
            raise ValueError("refinement per pass must be 1..100 %")
        st.refinement = pct / 100.0
    if "basisOrder" in kw:
        st.basis_order = int(kw["basisOrder"])
    if "nModes" in kw and kw["nModes"] not in (None, ""):
        st.n_modes = int(kw["nModes"])
    if "minFrequency" in kw and kw["minFrequency"] not in (None, ""):
        st.min_frequency = to_si(kw["minFrequency"], "frequency")
    if "deltaF" in kw and kw["deltaF"] not in (None, ""):
        st.delta_f = float(kw["deltaF"])
    if not st.min_passes <= st.max_passes:
        raise ValueError("minimum passes cannot exceed maximum passes")
    if st.min_converged < 1:
        raise ValueError("minimum converged passes must be at least 1")


@command("analysis.addSetup")
def _add_setup(s: Session, name: str = "", frequency: Any = "10GHz",
               maxPasses: int = 6, deltaS: float = 0.02,
               basisOrder: int = 1, **kw):
    d = s.require_design()
    nm = (naming.unique_name([x.name for x in d.setups], name) if name
          else naming.suggest_setup(d))
    st = d.add_setup(nm, frequency,
                     max_passes=int(maxPasses), delta_s=float(deltaS),
                     basis_order=int(basisOrder))
    try:
        _apply_setup_options(st, {k: v for k, v in kw.items() if k not in
                                  ("frequency", "maxPasses", "deltaS",
                                   "basisOrder")})
    except Exception:
        d.setups.remove(st)
        raise
    s.dirty = True
    if d.solution_type == "eigenmode":
        s.messages.add(f"Added eigenmode setup {st.name!r}: {st.n_modes} "
                       "mode(s).", "info", "analysis")
    else:
        s.messages.add(f"Added solution setup {st.name!r} at "
                       f"{st.frequency/1e9:g} GHz.", "info", "analysis")
    return {"ok": True, "name": st.name}


@command("analysis.editSetup")
def _edit_setup(s: Session, name: str = "", **kw):
    d = s.require_design()
    st = d.get_setup(name)
    _apply_setup_options(st, kw)
    if "newName" in kw and kw["newName"] and kw["newName"] != st.name:
        st.name = naming.unique_name([x.name for x in d.setups if x is not st],
                                     str(kw["newName"]))
    d.mesh = None
    s.dirty = True
    return {"ok": True, "name": st.name}


def _sweep_args(kind, spacing, tolerance, maxPoints, step):
    if kind not in ("discrete", "interpolating", "fast"):
        raise ValueError(f"unknown sweep type {kind!r}")
    if spacing not in ("linear", "step", "log", "single"):
        raise ValueError(f"unknown frequency setup {spacing!r}")
    tol = float(tolerance) if tolerance not in (None, "") else None
    if tol is not None and not 0 < tol < 1:
        raise ValueError("error tolerance must be between 0 and 1 (|dS|)")
    mp = int(maxPoints) if maxPoints not in (None, "") else None
    if mp is not None and mp < 4:
        raise ValueError("an adaptive sweep needs at least 4 solutions")
    if spacing == "step":
        if step in (None, ""):
            raise ValueError("a linear-step sweep needs a step")
        if to_si(step, "frequency") <= 0:
            raise ValueError("the frequency step must be positive")
    return tol, mp


@command("analysis.addSweep")
def _add_sweep(s: Session, setup: str = "", name: str = "", kind: str = "discrete",
               start: Any = "1GHz", stop: Any = "10GHz", count: int = 101,
               spacing: str = "linear", tolerance: Any = None,
               maxPoints: Any = None, step: Any = None,
               saveFields: bool = False, **_):
    d = s.require_design()
    st = d.get_setup(setup or None)
    swn = (naming.unique_name([x.name for x in st.sweeps], name) if name
           else naming.suggest_sweep(st))
    tol, mp = _sweep_args(kind, spacing, tolerance, maxPoints, step)
    sw = st.add_sweep(swn, start, stop, int(count), kind, spacing,
                      tolerance=tol, max_points=mp, step=step or None,
                      save_fields=bool(saveFields))
    if len(sw.frequencies()) > 20001:
        st.sweeps.remove(sw)
        raise ValueError("maximum 20001 frequency points per sweep")
    s.dirty = True
    s.messages.add(f"Added sweep {sw.name!r}: {sw.start/1e9:g}–"
                   f"{sw.stop/1e9:g} GHz, {len(sw.frequencies())} points.",
                   "info", "analysis")
    return {"ok": True, "name": sw.name}


@command("analysis.editSweep")
def _edit_sweep(s: Session, setup: str = "", name: str = "", kind: str = "discrete",
                start: Any = "1GHz", stop: Any = "10GHz", count: int = 101,
                spacing: str = "linear", tolerance: Any = None,
                maxPoints: Any = None, step: Any = None,
                saveFields: bool = False, **_):
    d = s.require_design()
    st = d.get_setup(setup or None)
    sw = next((x for x in st.sweeps if x.name == name), None)
    if sw is None:
        raise KeyError(f"no sweep named {name!r}")
    tol, mp = _sweep_args(kind, spacing, tolerance, maxPoints, step)
    sw.kind, sw.spacing = kind, spacing
    sw.start, sw.stop = to_si(start, "frequency"), to_si(stop, "frequency")
    sw.count = int(count)
    sw.tolerance, sw.max_points = tol, mp
    sw.step = to_si(step, "frequency") if step else None
    sw.save_fields = bool(saveFields)
    sw.points = None
    if spacing == "step":
        sw.count = len(sw.frequencies())
    d.mesh = None
    s.dirty = True
    return {"ok": True, "name": sw.name}


@command("analysis.deleteSetup")
def _del_setup(s: Session, name: str = "", **_):
    d = s.require_design()
    d.setups = [x for x in d.setups if x.name != name]
    s.dirty = True
    return {"ok": True}


@command("analysis.deleteSweep")
def _del_sweep(s: Session, setup: str = "", name: str = "", **_):
    d = s.require_design()
    st = d.get_setup(setup or None)
    st.sweeps = [x for x in st.sweeps if x.name != name]
    s.dirty = True
    return {"ok": True}


@command("analysis.validate")
def _validate(s: Session, **_):
    d = s.require_design()
    errs = d.validate()
    checks = [
        ("3D Model", bool(d.solids), f"{len(d.solids)} object(s)"),
        ("Boundaries and Excitations", bool(d.ports) or
         d.solution_type == "eigenmode",
         f"{len(d.boundaries)} boundaries, {len(d.ports)} excitations"),
        ("Materials", True, f"{len({o.material.name for o in d.solids})} used"),
        ("Analysis Setup", bool(d.setups),
         f"{len(d.setups)} setup(s), "
         f"{sum(len(x.sweeps) for x in d.setups)} sweep(s)"),
        ("Mesh Operations", True, "default λ-based seeding"),
    ]
    for c in checks:
        s.messages.add(f"Validation — {c[0]}: {'OK' if c[1] else 'FAILED'} "
                       f"({c[2]})", "info" if c[1] else "error", "validation")
    return {"ok": not errs, "errors": errs,
            "checks": [{"name": a, "ok": bool(b), "detail": c}
                       for a, b, c in checks]}


@command("analysis.analyze")
def _analyze(s: Session, setup: str = "", **kw):
    s.start_solve(setup, **{k: v for k, v in kw.items()
                            if k in ("adaptive", "save_fields", "backend")})
    return {"ok": True}


@command("mesh.addOperation")
def _add_mesh_op(s: Session, name: str = "", maxLength: Any = "1mm",
                 objects: Optional[List[str]] = None,
                 selector: Optional[dict] = None, **_):
    """Length-based refinement on objects or on the picked faces."""
    d = s.require_design()
    nm = naming.unique_name([m.name for m in d.mesh_ops],
                            name or "Length1")
    sel = _make_selector(d, selector) if selector else None
    names = list(objects or [])
    if not names and sel is None:
        # A face pick is the more specific statement of intent, so it wins
        # over an object that merely happens to still be selected -- picking
        # a face normally leaves the object selected too.
        if s.sel_faces:
            sel = _make_selector(d, {"kind": "faces", "faces": s.sel_faces})
        else:
            names = list(s.selection)
    op = d.add_mesh_operation(nm, maxLength, names, sel)
    s.dirty = True
    s.messages.add(f"Mesh operation {op.describe()}", "info", "mesh")
    return {"ok": True, "name": nm}


@command("mesh.deleteOperation")
def _del_mesh_op(s: Session, name: str = "", **_):
    d = s.require_design()
    d.delete_mesh_operation(name)
    s.dirty = True
    s.messages.add(f"Deleted mesh operation {name!r}.", "info", "mesh")
    return {"ok": True}


@command("mesh.setOperation")
def _set_mesh_op(s: Session, name: str = "", maxLength: Any = None,
                 enabled: Optional[bool] = None, **_):
    d = s.require_design()
    for m in d.mesh_ops:
        if m.name == name:
            if maxLength is not None:
                m.max_length = to_si(maxLength)
            if enabled is not None:
                m.enabled = bool(enabled)
            d.mesh = None
            s.dirty = True
            return {"ok": True}
    raise KeyError(f"no mesh operation named {name!r}")


@command("analysis.generateMesh")
def _gen_mesh(s: Session, size: Optional[float] = None, **_):
    d = s.require_design()
    if not d.solids and not d.sheets:
        raise RuntimeError("this design has no geometry to mesh — draw or "
                           "import a body first")
    f = d.setups[0].frequency if d.setups else 1e9
    if not d.setups:
        s.messages.add("No solution setup yet; the initial mesh is seeded at "
                       "1 GHz. Add a setup to seed it at the solve frequency.",
                       "warning", "mesh")
    kw = {"size": float(size)} if size else {}
    m = d.generate_mesh(f, force=True, **kw)
    skipped = dict(getattr(m, "skipped_bodies", {}) or {})
    if skipped:
        names = ", ".join(sorted(skipped)[:8]) + \
            (" …" if len(skipped) > 8 else "")
        s.messages.add(
            f"{len(skipped)} body/bodies have no readable geometry and are "
            f"not in the mesh: {names}. Modeler > Repair Imported Bodies "
            "points them at a STEP export of the same parts.",
            "warning", "mesh")
    s.messages.add(f"Initial mesh: {m.n_nodes} nodes, {m.n_tets} tetrahedra, "
                   f"min quality {m.quality().min():.3f}", "info", "mesh")
    return {"ok": True, "nodes": m.n_nodes, "tets": m.n_tets,
            "skipped": sorted(skipped)}


# ==========================================================================
# relative coordinate systems
# ==========================================================================


@command("cs.create")
def _cs_create(s: Session, name: str = "", origin: Any = None,
               setWorking: bool = True, **_):
    """A relative coordinate system whose origin is *origin* (a picked vertex,
    edge mid-point or face centre, or typed). Coordinates entered while it is
    the working system are measured from that origin."""
    d = s.require_design()
    if origin is None or len(origin) != 3:
        raise ValueError("give the origin as three coordinates")
    org = [to_si(x) for x in origin]
    nm = str(name).strip()
    if not nm:
        n = 1
        names = {c["name"] for c in d.coordinate_systems}
        while f"RelativeCS{n}" in names:
            n += 1
        nm = f"RelativeCS{n}"
    d.add_coordinate_system(nm, org)
    if setWorking:
        d.working_cs = nm
    s.dirty = True
    s.messages.add(f"Coordinate system {nm!r} at ({org[0] * 1e3:.4g}, "
                   f"{org[1] * 1e3:.4g}, {org[2] * 1e3:.4g}) mm"
                   + (" is now the working system." if setWorking else "."),
                   "info", "modeler")
    return {"ok": True, "name": nm}


@command("cs.setWorking")
def _cs_set_working(s: Session, name: str = "", **_):
    d = s.require_design()
    nm = "" if str(name).strip().lower() in ("", "global") else str(name)
    if nm:
        d.get_coordinate_system(nm)
    d.working_cs = nm
    return {"ok": True, "name": nm}


@command("cs.delete")
def _cs_delete(s: Session, name: str = "", **_):
    d = s.require_design()
    d.delete_coordinate_system(name)
    s.dirty = True
    return {"ok": True}


@command("cs.rename")
def _cs_rename(s: Session, name: str = "", newName: str = "", **_):
    d = s.require_design()
    c = d.get_coordinate_system(name)
    nn = str(newName).strip()
    if not nn or nn.lower() == "global":
        raise ValueError("give the coordinate system a name other than 'Global'")
    if any(x["name"] == nn for x in d.coordinate_systems if x is not c):
        raise ValueError(f"a coordinate system named {nn!r} already exists")
    c["name"] = nn
    if d.working_cs == name:
        d.working_cs = nn
    s.dirty = True
    return {"ok": True}


# ==========================================================================
# geometry / mesh / field buffers for the viewport
# ==========================================================================


@command("view.geometry")
def _geometry(s: Session, have: Optional[dict] = None, binary: bool = False,
              **_):
    """
    Display buffers for everything in the design.

    Two options exist for the browser, and neither changes the default result
    a script or a test sees:

    ``have``
        ``{object name: shape digest}`` of what the viewport already holds.
        Anything whose digest still matches comes back as
        ``{"name": ..., "unchanged": true}`` plus its display properties, and
        the client keeps the GPU buffers it built last time. Moving one box in
        a twenty-body model used to re-upload — and re-index for picking —
        every other body; now it re-uploads the one that moved.
    ``binary``
        Send ``position``/``normal``/``edgeVerts`` as float32 blobs fetched
        from ``/api/blob`` instead of inlining millions of JSON numbers. The
        JSON text for a mid-sized STEP assembly is an order of magnitude
        larger than the float data it encodes, and parsing it dominated the
        time between "Open" and the first frame.
    """
    d = s.design
    if d is None:
        return {"objects": [], "missing": [], "bbox": None}
    have = have or {}
    entities = [(o, False) for o in d.solids] + [(sh, True) for sh in d.sheets]
    out: List[dict] = []
    missing: List[str] = []
    own_progress = not s.progress.active
    if own_progress and len(entities) > 1:
        s.progress.begin("Building the 3-D view", total=len(entities),
                         stage="tessellating")
    try:
        for i, (obj, is_sheet) in enumerate(entities):
            s.progress.step(detail=obj.name, done=i)
            if getattr(obj.shape, "_cad_unreadable", ""):
                # Known to have no geometry yet: reported once when the project
                # was read, not again on every redraw.
                missing.append(obj.name)
                continue
            props = {"name": obj.name, "color": obj.color,
                     "transparency": float(obj.transparency),
                     "material": (obj.material.name if obj.material
                                  else ("sheet" if is_sheet else "vacuum")),
                     "isSheet": is_sheet,
                     "visible": bool(getattr(obj, "visible", True))}
            digest = _shape_digest(obj.shape)
            if digest and have.get(obj.name) == digest:
                out.append(dict(props, digest=digest, unchanged=True))
                continue
            placeholder = ""
            try:
                buf = tessellate(obj.shape)
            except Exception as exc:
                # A body that cannot be triangulated is still *somewhere*, and
                # drawing nothing at all is what makes an import look like it
                # silently failed. Show its extent as a wire box, say so, and
                # keep it in the report below.
                placeholder = str(exc)
                s.messages.add(f"Cannot display {obj.name!r}: {exc}", "warning",
                               "modeler")
                buf = _extent_box(obj.shape)
                if buf is None:
                    continue
            buf.update(props)
            if placeholder:
                buf["placeholder"] = placeholder
            if digest:
                buf["digest"] = digest
            if binary:
                _to_blobs(s, buf)
            out.append(buf)
    finally:
        if own_progress and len(entities) > 1:
            s.progress.end()
    shown = {item["name"] for item in out}
    boxes = [obj.shape.bounds() for obj, _ in entities if obj.name in shown]
    if boxes:
        lo = np.min([b[0] for b in boxes], axis=0)
        hi = np.max([b[1] for b in boxes], axis=0)
    else:
        lo, hi = d.bounding_box()
    return {"objects": out, "missing": missing,
            "bbox": [list(map(float, lo)), list(map(float, hi))]}


def _extent_box(shape) -> Optional[dict]:
    """The shape's bounding box as a display buffer, for a body that cannot be
    triangulated. Better a box in the right place than an empty viewport."""
    from .tessellate import _pack, _BOX_FACES
    try:
        lo, hi = shape.bounds()
        lo = np.asarray(lo, float)
        hi = np.asarray(hi, float)
        if not np.isfinite(lo).all() or not np.isfinite(hi).all():
            return None
        if float(np.max(hi - lo)) <= 0.0:
            return None
        unit = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                         [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
        return _pack(lo + unit * (hi - lo), _BOX_FACES)
    except Exception:                                       # pragma: no cover
        return None


@command("view.displayReport")
def _display_report(s: Session, **_):
    """
    Why the viewport looks the way it does, object by object.

    "It loaded but nothing is on screen" has several quite different causes —
    no readable geometry, a failed tessellation, a hidden object, a body that
    is entirely transparent because its material is air, or a model whose real
    parts are dwarfed by a PML box. Guessing between them from an empty
    viewport is not reasonable, so this states which one it is.
    """
    d = s.design
    if d is None:
        return {"design": "", "rows": [], "summary": "No project is open."}
    entities = [(o, False) for o in d.solids] + [(sh, True) for sh in d.sheets]
    rows = []
    for obj, is_sheet in entities:
        why = getattr(obj.shape, "_cad_unreadable", "")
        try:
            lo, hi = obj.shape.bounds()
            extent = [float(hi[k] - lo[k]) for k in range(3)]
        except Exception:
            extent = [0.0, 0.0, 0.0]
        state, detail = "displayed", ""
        if why:
            state, detail = "no geometry", why
        elif not bool(getattr(obj, "visible", True)):
            state, detail = "hidden", "Visible is off in Properties"
        else:
            try:
                buf = tessellate(obj.shape)
                if not buf.get("count"):
                    state, detail = "empty", "tessellation produced no triangles"
            except Exception as exc:
                state, detail = "not drawable", str(exc)
        rows.append({
            "name": obj.name, "kind": type(obj.shape).__name__,
            "isSheet": is_sheet,
            "material": obj.material.name if obj.material else "",
            "transparency": float(obj.transparency),
            "visible": bool(getattr(obj, "visible", True)),
            "extent": extent, "state": state, "detail": detail})

    drawn = [r for r in rows if r["state"] == "displayed"]
    faint = [r for r in drawn if r["transparency"] >= 0.8]
    parts = [f"{len(rows)} object(s): {len(drawn)} displayed"]
    for state in ("no geometry", "not drawable", "hidden", "empty"):
        n = sum(1 for r in rows if r["state"] == state)
        if n:
            parts.append(f"{n} {state}")
    summary = ", ".join(parts) + "."
    if drawn and len(faint) == len(drawn):
        summary += (" Every displayed body is 80% or more transparent — that is"
                    " what an air or PML region looks like, and it is why the"
                    " viewport can look empty. View ▸ Solid Display makes them"
                    " opaque.")
    if drawn:
        span = [max(r["extent"]) for r in drawn]
        big, small = max(span), min(s0 for s0 in span if s0 > 0) if any(
            s0 > 0 for s0 in span) else (max(span), 0)
        if small and big / small > 200:
            summary += (f" The largest body is {big / small:.0f}x the smallest,"
                        " so the small parts are sub-pixel until you zoom in.")
    return {"design": d.name, "rows": rows, "summary": summary,
            "faint": [r["name"] for r in faint]}


def _shape_digest(shape) -> str:
    """A short stable id for a shape's geometry, for the viewport's cache."""
    from .tessellate import _cache_key
    try:
        key = _cache_key(shape)
    except Exception:                                       # pragma: no cover
        return ""
    if key is None:
        return ""
    import hashlib
    return hashlib.blake2b(repr(key).encode("utf-8"),
                           digest_size=12).hexdigest()


#: Float arrays handed to the browser out-of-band, keyed by content hash.
#: Bounded: the viewport fetches each blob once, right after the JSON that
#: names it, so only the current model's buffers need to be resident.
BLOBS: "OrderedDict[str, bytes]" = OrderedDict()
#: Blobs already handed to the browser, kept so a redraw of unchanged
#: geometry costs nothing. Cleared whenever the document changes, so this is
#: a ceiling for one model rather than for a session.
BLOB_BUDGET_BYTES = 192 * 1024 * 1024
#: what survives a document change, so replies to in-flight fetches still land
_BLOB_RESERVE_BYTES = 24 * 1024 * 1024
_BLOB_BYTES = 0

_BLOB_FIELDS = (("position", np.float32), ("normal", np.float32),
                ("edgeVerts", np.float32), ("scalar", np.float32),
                ("edges", np.int32), ("faceOf", np.int32))


def _put_blob(data: np.ndarray) -> dict:
    global _BLOB_BYTES
    import hashlib
    raw = np.ascontiguousarray(data).tobytes()
    key = hashlib.blake2b(raw, digest_size=16).hexdigest()
    if key in BLOBS:
        BLOBS.move_to_end(key)
    else:
        BLOBS[key] = raw
        _BLOB_BYTES += len(raw)
        while _BLOB_BYTES > BLOB_BUDGET_BYTES and len(BLOBS) > 1:
            _, dropped = BLOBS.popitem(last=False)
            _BLOB_BYTES -= len(dropped)
    return {"blob": key, "len": int(data.size),
            "type": "f32" if data.dtype == np.float32 else "i32"}


def _to_blobs(s: Session, buf: dict) -> None:
    """Move the big numeric arrays of one display buffer out of the JSON."""
    refs = {}
    for field, dtype in _BLOB_FIELDS:
        vals = buf.get(field)
        if vals is None or len(vals) < 96:
            continue                    # small enough that a round trip costs
        refs[field] = _put_blob(np.asarray(vals, dtype))
        buf[field] = []
    if refs:
        buf["blobs"] = refs


# What each kind of assignment looks like in the viewport. The colours follow
# the convention every EM tool uses closely enough to be read at a glance.
ASSIGN_COLOR = {
    "pec": "#7fb2ff", "pmc": "#c39bff", "radiation": "#ff8a5c",
    "pml": "#ff6f9c", "finite_cond": "#e0a066", "impedance": "#5fd0a0",
    "lumped_rlc": "#8ad46b", "symmetry_e": "#9fb6c8", "symmetry_h": "#9fb6c8",
    "wave": "#ff4fa3", "lumped": "#39c6ff",
}


#: Triangle / centroid / normal arrays per shape digest, for evaluating the
#: geometric selectors that boundaries and ports are made of. Rebuilding these
#: from the display buffer on every redraw was the second full pass over the
#: model's triangles, right after the tessellation itself.
_ASSIGN_ARRAYS: "OrderedDict[str, tuple]" = OrderedDict()
_ASSIGN_LIMIT = 64


def _assign_arrays(shape):
    digest = _shape_digest(shape)
    if digest and digest in _ASSIGN_ARRAYS:
        _ASSIGN_ARRAYS.move_to_end(digest)
        return _ASSIGN_ARRAYS[digest]
    buf = tessellate(shape)
    p = np.asarray(buf.get("position", ()), float).reshape(-1, 3, 3)
    if not len(p):
        return None
    n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    arrays = (p, p.mean(axis=1), n / np.maximum(ln, 1e-300))
    if digest:
        _ASSIGN_ARRAYS[digest] = arrays
        while len(_ASSIGN_ARRAYS) > _ASSIGN_LIMIT:
            _ASSIGN_ARRAYS.popitem(last=False)
    return arrays


def _model_triangles(d):
    """Display triangles of everything with geometry, as (tris, centres, normals)."""
    tris: List[np.ndarray] = []
    cent: List[np.ndarray] = []
    nrm: List[np.ndarray] = []
    for o in list(d.solids) + list(d.sheets):
        if getattr(o.shape, "_cad_unreadable", ""):
            continue
        try:
            arrays = _assign_arrays(o.shape)
        except Exception:
            continue
        if arrays is None:
            continue
        p, c, n = arrays
        tris.append(p)
        cent.append(c)
        nrm.append(n)
    if not tris:
        return None
    return np.vstack(tris), np.vstack(cent), np.vstack(nrm)


def _coverage(d, selector) -> int:
    """
    How many display triangles a selector actually lands on.

    An assignment that matches nothing is the quietest failure in a field
    solver: the boundary is in the tree, the solve runs, and the answer is
    wrong. Counting the faces at assignment time turns that into a warning
    in the message window, next to the assignment that caused it.
    ``-1`` means "cannot tell" -- no geometry to test against.
    """
    got = _model_triangles(d)
    if got is None:
        return -1
    _, cent, nrm = got
    try:
        return int(np.asarray(selector(cent, nrm), bool).sum())
    except Exception:
        return -1


def _warn_if_empty(s: Session, d, selector, nm: str, what: str) -> int:
    n = _coverage(d, selector)
    if n == 0:
        s.messages.add(
            f"{what} {nm!r} does not touch any face of the current model. "
            "Check the selection: picked faces move with the body they were "
            "picked on, and a plane must lie on a real surface.",
            "warning", what.lower())
    return n


@command("view.assignments")
def _view_assignments(s: Session, **_):
    """
    The faces each boundary and port actually covers, ready to draw.

    Assignments used to be invisible: a port was a row in a tree and a line in
    a report, and whether it had landed on the face you meant was something you
    found out from the solve. The selectors are geometric, so they can be
    evaluated against the display triangles directly -- no mesh needed, and
    what is drawn is exactly what the tagger will pick.
    """
    d = s.design
    if d is None:
        return {"items": []}
    pm = _marks(s)
    n_marks = {"signal": len(pm["signal"]), "ground": len(pm["ground"])}

    if not d.ports and not d.boundaries and not (n_marks["signal"] or n_marks["ground"]):
        return {"items": [], "marks": n_marks}

    got = _model_triangles(d)
    if got is None:
        return {"items": []}
    tris, cent, nrm = got

    def pick(selector):
        try:
            m = np.asarray(selector(cent, nrm), bool)
        except Exception:
            return None
        return tris[m] if m.any() else None

    items = []
    for p in d.ports:
        sel = pick(p.selector)
        if sel is None:
            continue
        item = {"name": p.name, "kind": p.kind, "type": p.kind,
                "color": ASSIGN_COLOR.get(p.kind, "#ff4fa3"),
                "count": int(len(sel)),
                "position": np.round(sel.ravel(), 9).tolist(),
                "center": [float(x) for x in sel.reshape(-1, 3).mean(0)]}
        il = getattr(p, "integration_line", None)
        if il:
            item["line"] = [[float(x) for x in il[0]],
                            [float(x) for x in il[1]]]
        elif p.kind == "lumped":
            # no explicit line: show the one the field direction implies, so
            # the polarity of every lumped port is visible as an arrow
            ends = _lumped_ends(d, p)
            if ends is not None:
                item["line"] = [[float(x) for x in ends[0]],
                                [float(x) for x in ends[1]]]
                item["derived"] = True
        items.append(item)
    for b in d.boundaries:
        sel = pick(b.selector)
        if sel is None:
            continue
        items.append({"name": b.name, "kind": "boundary", "type": b.btype,
                      "color": ASSIGN_COLOR.get(b.btype, "#9fb6c8"),
                      "count": int(len(sel)),
                      "position": np.round(sel.ravel(), 9).tolist(),
                      "center": [float(x) for x in sel.reshape(-1, 3).mean(0)]})
    # what is marked as signal / ground, until a port is made from it
    for role, color in (("signal", "#ff5d5d"), ("ground", "#4d8dff")):
        parts, line = [], None
        for pk in pm[role]:
            kind = pk.get("kind", "object")
            try:
                if kind == "object":
                    sel_m = ShapeSelector(_entity(d, pk["name"]).shape, tol=1e-6)
                elif kind == "face":
                    sel_m = FaceSelector(point=pk["point"], normal=pk["normal"],
                                         lo=pk["lo"], hi=pk["hi"],
                                         planar=bool(pk.get("planar", True)),
                                         object=pk.get("object", ""))
                else:
                    line = [[to_si(x) for x in pk["a"]], [to_si(x) for x in pk["b"]]]
                    continue
            except Exception:                                   # noqa: BLE001
                continue
            t = pick(sel_m)
            if t is not None:
                parts.append(t)
        if not parts and line is None:
            continue
        pos = np.vstack(parts) if parts else np.zeros((0, 3, 3))
        item = {"name": f"{role.capitalize()} mark", "kind": "mark", "type": "mark-" + role,
                "color": color, "count": int(len(pos)),
                "position": np.round(pos.ravel(), 9).tolist(),
                "center": ([float(x) for x in pos.reshape(-1, 3).mean(0)] if len(pos)
                           else [float(x) for x in np.mean(line, axis=0)])}
        if line is not None:
            item["line"] = line
        items.append(item)
    return {"items": items, "marks": n_marks}


@command("view.mesh")
def _mesh_view(s: Session, **_):
    d = s.require_design()
    if d.mesh is None:
        raise RuntimeError("no mesh yet — run Analysis ▸ Generate Mesh")
    buf = tessellate_mesh_surface(d.mesh)
    buf["wire"] = mesh_wire(d.mesh)
    buf["stats"] = {"nodes": d.mesh.n_nodes, "tets": d.mesh.n_tets,
                    "edges": d.mesh.n_edges}
    return buf


def _scalar_buffer(patch, scale="linear", floor_db=40.0, ref=None):
    """A viewport buffer coloured by a patch's scalar, plus its colour range."""
    from ..post.fieldview import to_unit_scale
    from .tessellate import _pack
    verts, tris = patch.verts, patch.tris
    tv = verts[tris]
    area2 = np.linalg.norm(np.cross(tv[:, 1] - tv[:, 0], tv[:, 2] - tv[:, 0]),
                           axis=1)
    keep = area2 > max(float(area2.max()) * 1e-12, 1e-300)
    tris = tris[keep]                       # the packer drops these silently
    u, (lo, hi) = to_unit_scale(patch.values, scale, floor_db, ref,
                                getattr(patch, "signed", False))
    buf = _pack(verts, tris)
    buf["scalar"] = np.round(u[tris.reshape(-1)], 5).tolist()
    buf["range"] = [lo, hi]
    return buf


@command("view.fieldInfo")
def _field_info(s: Session, **_):
    """What can be plotted: saved frequencies, excitations/modes, quantities."""
    sol = s.solution
    if sol is None or not sol.fields:
        raise RuntimeError("no field data — analyse with 'save fields' enabled")
    names = ([f"Mode {m.index + 1}  ({m.f / 1e9:.4f} GHz)" for m in sol.modes]
             if sol.modes else sol.design.excitation_names())
    return {"freqs": [float(f) for f in sorted({k[0] for k in sol.fields})],
            "excitations": names, "eigen": bool(sol.modes),
            "bounds": [np.asarray(v).tolist() for v in sol.mesh.bounding_box()],
            "radiation": any(b.btype == "radiation"
                             for b in sol.design.boundaries)}


@command("view.field")
def _field_view(s: Session, freq: Optional[float] = None,
                excitation: int = 0, quantity: str = "E",
                where: str = "surface", objects: Optional[List[str]] = None,
                axis: str = "z", value: Any = 0.0, phase: Any = None,
                scale: str = "linear", floorDb: float = 40.0,
                arrows: int = 0, component: str = "mag", **_):
    """
    A field plot as a viewport surface.

    ``quantity``  E | H | J (surface current)
    ``where``     surface (all boundary faces / all conductors), objects
                  (faces on the named objects) or cut (plane ``axis = value``)
    ``phase``     None for the peak value, or degrees into the RF cycle
    """
    from ..post.fieldview import (QUANTITIES, conductor_faces,
                                  cut_plane_patch, surface_patch)
    if s.solution is None or not s.solution.fields:
        raise RuntimeError("no field data — analyse with 'save fields' enabled")
    if quantity not in QUANTITIES:
        raise ValueError(f"quantity must be one of {', '.join(QUANTITIES)}")
    if scale not in ("linear", "db"):
        raise ValueError("scale must be linear or db")
    from ..post.fieldview import COMPONENTS
    if component not in COMPONENTS:
        raise ValueError(f"component must be one of {', '.join(COMPONENTS)}")
    sol = s.solution
    f = freq if freq is not None else float(sol.freqs[-1])
    fs = sol.field(f, int(excitation))
    ph = None if phase in (None, "") else float(phase)
    if component != "mag":
        scale = "linear"                 # a signed value has no dB
        if ph is None:
            ph = 0.0
    n_arrows = max(0, min(int(arrows), 1500))
    if where == "cut":
        v = to_si(value) if not isinstance(value, (int, float)) else float(value)
        patch = cut_plane_patch(sol, fs, axis, v, quantity, ph, n_arrows,
                                component)
    else:
        faces = None
        on_names = None
        if where == "objects":
            from ..geometry.select import UnionSelector
            names = list(objects or s.selection)
            if not names:
                raise ValueError("choose one or more metals (or select objects "
                                 "in the viewport) to plot on")
            d = sol.design
            mesh = sol.mesh
            sel = UnionSelector(*[ShapeSelector(_entity(d, n).shape, tol=1e-6)
                                  for n in names])
            hit = np.nonzero(np.asarray(sel(mesh.surf_centroids,
                                            mesh.surf_normals), bool))[0]
            if quantity == "J":
                hit = np.intersect1d(hit, conductor_faces(d, mesh))
            if len(hit) == 0:
                raise ValueError(
                    "no solved surface belongs to " + ", ".join(names[:4])
                    + (" …" if len(names) > 4 else "")
                    + (" — surface current exists only on conductors that the "
                       "solution treats as metal" if quantity == "J" else ""))
            faces = hit
            on_names = names
        patch = surface_patch(sol, fs, quantity, faces, ph, n_arrows,
                              component)
    # a peak plot is scaled to its own maximum; an instantaneous one to the
    # peak of the cycle, so the colours stay comparable as the phase moves
    ref = patch.peak if (ph is not None or patch.signed) else None
    buf = _scalar_buffer(patch, scale, floorDb, ref)
    buf["label"] = patch.label
    buf["unit"] = patch.unit if scale == "linear" else "dB re peak"
    buf["peak"] = patch.peak
    buf["arrows"] = np.round(patch.arrows.reshape(-1), 7).tolist()
    buf["freq"] = float(fs.freq)
    buf["on"] = list(on_names) if where != "cut" and on_names else []
    return buf


# ==========================================================================
# results
# ==========================================================================


@command("results.report")
def _report(s: Session, traces: Optional[List[dict]] = None,
            form: str = "db", **_):
    if s.solution is None:
        raise RuntimeError("no solution yet")
    if s.solution.sparams is None:
        raise RuntimeError("an eigenmode solution has no S-parameters; "
                           "open Results > Eigenmode Data")
    sp = s.solution.sparams
    names = sp.port_names
    traces = traces or ([{"i": 1, "j": 1}, {"i": 2, "j": 1}]
        if sp.n_port > 1 else [{"i": 1, "j": 1}])
    out = []
    for t in traces:
        i, j = int(t.get("i", 1)), int(t.get("j", 1))
        if not (1 <= i <= sp.n_port and 1 <= j <= sp.n_port):
            raise ValueError("Trace port indices are 1-based and must exist")
        z = sp.sij(i, j)
        if form == "db":
            y = sp.db(i, j)
        elif form == "mag":
            y = np.abs(z)
        elif form == "deg":
            y = sp.unwrapped_deg(i, j)
        elif form == "vswr":
            y = sp.vswr(i)
        elif form == "groupdelay":
            y = sp.group_delay(i, j) * 1e9
        elif form in ("zre", "zim", "zmag"):
            # input impedance seen at port i: Z = Z0 (1 + S) / (1 - S)
            if i != j:
                raise ValueError("impedance traces need a port with itself: "
                                 "choose S(n,n)")
            zin = sp.z0[:, i - 1] * (1 + z) / (1 - z)
            y = {"zre": zin.real, "zim": zin.imag, "zmag": np.abs(zin)}[form]
        elif form in ("re", "im"):
            y = z.real if form == "re" else z.imag
        elif form == "smith":
            y = sp.db(i, j)                  # the chart is drawn from re / im
        else:
            y = sp.db(i, j)
        out.append({"label": f"S({names[i-1]},{names[j-1]})",
                    "i": i, "j": j,
                    "y": [float(v) for v in y],
                    "re": [float(v) for v in z.real],
                    "im": [float(v) for v in z.imag]})
    return {"freq": [float(f) for f in sp.freq], "traces": out, "form": form,
            "nPort": sp.n_port, "portNames": names,
            "passive": bool(sp.is_passive()),
            "reciprocal": bool(sp.is_reciprocal(1e-4)),
            "z0": [float(v.real) for v in sp.z0[0]]}


@command("results.portModes")
def _port_modes(s: Session, freq: Optional[float] = None, **_):
    """
    Modal data per port.

    Wave ports contribute one row per solved mode. A lumped port has no
    eigenproblem — it drives a prescribed uniform field — so it contributes a
    single row built from its definition, rather than leaving the table
    mysteriously empty.
    """
    if s.solution is None:
        raise RuntimeError("no solution yet")
    sol = s.solution
    f0 = float(freq) if freq is not None else sorted(sol.ports)[0]
    f0 = min(sol.ports, key=lambda f: abs(f - f0))
    by_name = {p.name: p for p in s.design.ports} if s.design else {}
    rows = []
    for ps in sol.ports[f0]:
        if ps.modes:
            for m in ps.modes:
                rows.append({"port": ps.name, "mode": m.index + 1,
                             "type": m.kind, "beta": float(m.beta),
                             "alpha": float(m.alpha), "fc": float(m.f_cut),
                             "zwave": [m.Z_wave.real, m.Z_wave.imag],
                             "zport": [m.Z_port.real, m.Z_port.imag],
                             "propagating": bool(m.propagating)})
            continue
        p = by_name.get(ps.name)
        z = complex(getattr(p, "impedance", 50.0)) if p is not None else 50.0
        rows.append({"port": ps.name, "mode": 1, "type": "TEM (lumped)",
                     "beta": 2 * math.pi * f0 / c0, "alpha": 0.0, "fc": 0.0,
                     "zwave": [z.real, z.imag], "zport": [z.real, z.imag],
                     "propagating": True})
    return {"freq": float(f0), "rows": rows,
            "frequencies": [float(f) for f in sorted(sol.ports)]}


def _farfield_for(s: Session, freq, excitation, theta_step, phi_step):
    """The (cached) power-normalised far field the report and 3-D view share."""
    from ..post.farfield import antenna_parameters
    sol = s.solution
    if sol is None:
        raise RuntimeError("no solution yet")
    if sol.modes:
        raise RuntimeError("far fields belong to driven solutions, not "
                           "eigenmode ones")
    nt = max(int(round(180.0 / max(float(theta_step), 0.5))) + 1, 19)
    npp = max(int(round(360.0 / max(float(phi_step), 1.0))), 12)
    key = (id(sol), None if freq is None else float(freq), int(excitation),
           nt, npp)
    cached = getattr(s, "_ff_cache", None)
    if cached and cached[0] == key:
        return cached[1]
    ff = antenna_parameters(sol, freq, int(excitation), nt, npp)
    s._ff_cache = (key, ff)
    return ff


@command("results.farField")
def _far_field(s: Session, freq: Optional[float] = None, excitation: int = 0,
               cuts: Optional[List[float]] = None, thetaStep: float = 2.0,
               phiStep: float = 5.0, **_):
    """Radiation pattern cuts and antenna parameters of a driven solution."""
    ff = _farfield_for(s, freq, excitation, thetaStep, phiStep)
    sol = s.solution
    cuts = [float(c) for c in (cuts if cuts else [0.0, 90.0])]
    g_tot = ff.gain()
    g_th = ff.component_gain("theta")
    g_ph = ff.component_gain("phi")

    def dB(a):
        return [float(v) for v in 10 * np.log10(np.maximum(a, 1e-30))]

    dirv = ff.directivity()

    def column(c):
        return int(np.argmin(np.abs((ff.phi - math.radians(c) + math.pi)
                                    % (2 * math.pi) - math.pi)))

    def arrays(k):
        return {"total": dB(g_tot[:, k]), "theta": dB(g_th[:, k]),
                "phi_pol": dB(g_ph[:, k]), "directivity": dB(dirv[:, k])}

    out_cuts = []
    for c in cuts:
        k = column(c)
        # the cut is a full great circle: this half-plane and the opposite one
        out_cuts.append(dict(phi=float(np.degrees(ff.phi[k])), **arrays(k),
                             opposite=arrays(column(c + 180.0))))
    summ = ff.summary()
    mismatch = None
    if sol.sparams is not None:
        j = int(excitation)
        try:
            smat = sol.sparams.at(float(ff.freq))
            mismatch = float(1.0 - abs(smat[j, j]) ** 2)
        except Exception:
            mismatch = None
    if mismatch is not None:
        summ["mismatchEfficiency"] = mismatch
        summ["peakRealizedGainDbi"] = float(
            summ["peakGainDbi"] + 10 * math.log10(max(mismatch, 1e-12)))
    warns = []
    if ff.P_radiated > 0:
        ratio = ff.P_boundary / ff.P_radiated
        summ["boundaryToFarFieldPower"] = float(ratio)
        if not 0.7 <= ratio <= 1.4:
            warns.append(
                f"The radiation boundary absorbs {ratio:.2f}x the power the far "
                "field radiates. The air region is probably too small or the "
                "mesh too coarse for a first-order absorbing boundary: keep the "
                "boundary at least a quarter wavelength from the radiator and "
                "refine near it. Directivity is usually still usable; absolute "
                "gain and efficiency are not.")
    return {"theta": [float(v) for v in np.degrees(ff.theta)], "cuts": out_cuts,
            "summary": summ, "freq": float(ff.freq),
            "freqs": [float(f) for f in sorted({k[0] for k in sol.fields})],
            "excitations": sol.design.excitation_names(),
            "excitation": int(excitation), "warnings": warns}


@command("results.antennaSweep")
def _antenna_sweep(s: Session, excitation: int = 0, theta: Any = None,
                   phi: Any = None, component: str = "total",
                   thetaStep: float = 3.0, phiStep: float = 6.0, **_):
    """
    Antenna figures of merit against frequency, one point per saved field.

    ``theta`` / ``phi`` (degrees) pick a fixed direction; without them each
    frequency is evaluated at its own peak. Returned per frequency:

    * ``directivity``   D, dBi (from the pattern alone)
    * ``gain``          total gain, dBi: radiated power over **accepted**
                        power, so it includes ohmic and dielectric loss
    * ``realized``      realized gain, dBi: gain x (1 - |S11|^2), i.e. over
                        the power **available** from the source
    * ``efficiency``    radiation efficiency, %; ``totalEfficiency`` includes
                        the mismatch
    """
    from ..post.farfield import antenna_parameters
    sol = s.solution
    if sol is None:
        raise RuntimeError("no solution yet")
    if sol.modes:
        raise RuntimeError("antenna parameters belong to driven solutions")
    if not sol.fields:
        raise RuntimeError("no field data — analyse with 'save fields' enabled")
    if component not in ("total", "theta", "phi"):
        raise ValueError("component must be total, theta or phi")
    j = int(excitation)
    freqs = sorted({k[0] for k in sol.fields if k[1] == j})
    if not freqs:
        raise ValueError("no saved fields for that excitation")
    nt = max(int(round(180.0 / max(float(thetaStep), 0.5))) + 1, 19)
    npp = max(int(round(360.0 / max(float(phiStep), 1.0))), 12)
    fixed = theta not in (None, "") and phi not in (None, "")
    out = {k: [] for k in ("directivity", "gain", "realized", "efficiency",
                           "totalEfficiency", "mismatch", "s11", "theta", "phi")}

    def db(v):
        return float(10 * math.log10(max(float(v), 1e-30)))

    for f in freqs:
        ff = antenna_parameters(sol, f, j, nt, npp)
        mism = None
        if sol.sparams is not None:
            try:
                smat = sol.sparams.at(float(ff.freq))
                mism = float(1.0 - abs(smat[j, j]) ** 2)
                out["s11"].append(float(20 * math.log10(max(abs(smat[j, j]), 1e-12))))
            except Exception:                                   # noqa: BLE001
                mism = None
        if mism is None:
            out["s11"].append(None)
        D = ff.directivity()
        G = ff.gain() if component == "total" else ff.component_gain(component)
        if fixed:
            it = int(np.argmin(np.abs(ff.theta - math.radians(float(theta)))))
            ip = int(np.argmin(np.abs((ff.phi - math.radians(float(phi)) + math.pi)
                                      % (2 * math.pi) - math.pi)))
            d, g = D[it, ip], G[it, ip]
            th, ph = float(np.degrees(ff.theta[it])), float(np.degrees(ff.phi[ip]))
        else:
            d = D.max()
            k = np.unravel_index(int(np.argmax(G)), G.shape)
            g = G[k]
            th, ph = float(np.degrees(ff.theta[k[0]])), float(np.degrees(ff.phi[k[1]]))
        out["directivity"].append(db(d))
        out["gain"].append(db(g))
        out["realized"].append(db(g * mism) if mism is not None else None)
        out["efficiency"].append(float(100.0 * ff.efficiency))
        out["totalEfficiency"].append(
            float(100.0 * ff.efficiency * mism) if mism is not None else None)
        out["mismatch"].append(None if mism is None else mism)
        out["theta"].append(th)
        out["phi"].append(ph)
    return {"freq": [float(f) for f in freqs], "series": out,
            "excitation": j, "excitations": sol.design.excitation_names(),
            "fixed": bool(fixed), "component": component,
            "theta": None if not fixed else float(theta),
            "phi": None if not fixed else float(phi)}


@command("view.pattern")
def _pattern_view(s: Session, freq: Optional[float] = None,
                  excitation: int = 0, floorDb: float = 30.0,
                  phase: Any = None, **_):
    """
    The 3-D radiation pattern as a surface the viewport can draw.

    Without ``phase`` the radius is gain in dB over a ``floorDb`` range.  With
    ``phase`` (degrees into the RF cycle) it is the *instantaneous* far-field
    magnitude ``|Re(E e^{j phase})|`` relative to its peak, so animating the
    phase shows the radiated field breathing in and out over a cycle.
    """
    ff = _farfield_for(s, freq, excitation, 2.0, 5.0)
    d = s.design
    lo, hi = d.bounding_box()
    scale = 0.42 * float(np.linalg.norm(hi - lo)) or 1.0
    centre = 0.5 * (lo + hi)
    if phase in (None, ""):
        g = ff.gain()
        gdb = 10 * np.log10(np.maximum(g, 1e-30))
        top = float(gdb.max())
        floor = top - float(floorDb)
        rad = np.clip((gdb - floor) / (top - floor), 0.0, 1.0)      # 0..1
        rng, label, unit = [floor, top], "Gain", "dBi"
    else:
        ph = np.exp(1j * math.radians(float(phase)))
        inst = np.sqrt((ff.E_theta * ph).real ** 2 + (ff.E_phi * ph).real ** 2)
        peak = float(np.sqrt(np.abs(ff.E_theta) ** 2
                             + np.abs(ff.E_phi) ** 2).max())
        rad = np.clip(inst / max(peak, 1e-300), 0.0, 1.0)
        rng = [0.0, 1.0]
        label, unit = f"|E far| @ {float(phase):.0f}°", "rel. peak"
    th, ph_ = ff.theta, np.append(ff.phi, ff.phi[0] + 2 * math.pi)
    rad = np.concatenate([rad, rad[:, :1]], axis=1)
    TH, PH = np.meshgrid(th, ph_, indexing="ij")
    R = np.maximum(rad, 0.0) * scale
    pts = np.stack([R * np.sin(TH) * np.cos(PH), R * np.sin(TH) * np.sin(PH),
                    R * np.cos(TH)], axis=-1) + centre
    nt, npp = TH.shape
    idx = np.arange(nt * npp).reshape(nt, npp)
    a, b = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel()
    c, e = idx[1:, :-1].ravel(), idx[1:, 1:].ravel()
    tris = np.concatenate([np.stack([a, b, e], 1), np.stack([a, e, c], 1)])
    from .tessellate import _pack
    verts = pts.reshape(-1, 3)
    # the poles collapse a whole row of triangles to a point; drop them here
    # (the packer would, silently) so the per-corner colours stay aligned
    tv = verts[tris]
    area2 = np.linalg.norm(np.cross(tv[:, 1] - tv[:, 0], tv[:, 2] - tv[:, 0]),
                           axis=1)
    tris = tris[area2 > max(float(area2.max()) * 1e-9, 1e-300)]
    buf = _pack(verts, tris)
    buf["scalar"] = np.round(rad.reshape(-1)[tris.reshape(-1)], 5).tolist()
    buf["range"] = rng
    buf["label"], buf["unit"], buf["freq"] = label, unit, float(ff.freq)
    return buf


@command("results.eigenModes")
def _eigen_modes(s: Session, **_):
    """Resonances of an eigenmode solution (frequency, Q, convergence)."""
    if s.solution is None or not s.solution.modes:
        raise RuntimeError("no eigenmode solution — analyse an eigenmode "
                           "design first")
    rows = []
    for m in s.solution.modes:
        rows.append({"mode": m.index + 1, "freq": m.f,
                     "fimag": float(m.frequency.imag),
                     "q": None if math.isinf(m.q) else float(m.q),
                     "converged": bool(m.converged),
                     "residual": float(m.residual)})
    return {"rows": rows, "passes": s.solution.convergence}


@command("results.convergence")
def _convergence(s: Session, **_):
    if s.solution is None:
        raise RuntimeError("no solution yet")
    return {"passes": s.solution.convergence}


@command("results.export")
def _export(s: Session, path: str = "", format: str = "touchstone", **_):
    if s.solution is None:
        raise RuntimeError("no solution yet")
    sp = s.solution.sparams
    if not str(path).strip():
        raise ValueError("no file name given")
    # Relative names used to land wherever the server process happened to
    # start, which from a browser is an unknowable directory.
    p = os.path.abspath(os.path.expanduser(path))
    if format == "touchstone":
        if not os.path.splitext(p)[1]:
            p += f".s{sp.n_port}p"
        sp.write_touchstone(p)
    elif format == "csv":
        if not os.path.splitext(p)[1]:
            p += ".csv"
        sp.to_csv(p)
    elif format == "html":
        from ..post.report import html_report
        if not os.path.splitext(p)[1]:
            p += ".html"
        html_report(s.solution, p)
    elif format == "vtk":
        if not os.path.splitext(p)[1]:
            p += ".vtu"
        s.solution.field(float(s.solution.freqs[-1]), 0).to_vtk(p)
    else:
        raise ValueError(f"unknown export format {format!r}")
    s.messages.add(f"Exported {format} to {p}", "info", "results")
    return {"ok": True, "path": p}


# ==========================================================================
# materials, view state, scripting
# ==========================================================================


# ==========================================================================
# file browsing (open / save / import / export dialogs)
# ==========================================================================


@command("files.browse")
def _browse(s: Session, path: str = "", kind: str = "any",
            showHidden: bool = False, filter: int = 0, **_):
    """
    One directory listing plus everything the dialog chrome needs.

    ``filter`` indexes the kind's filter list, so choosing "STEP only" in the
    dialog actually narrows the listing -- it used to be decorative.
    """
    all_filters = filesmod.filters(kind)
    try:
        exts = all_filters[max(int(filter), 0)]["ext"]
    except (IndexError, ValueError, TypeError):
        exts = all_filters[0]["ext"] if all_filters else []
    listing = filesmod.list_dir(path, exts, bool(showHidden))
    listing["places"] = filesmod.places()
    listing["filters"] = filesmod.filters(kind)
    listing["native"] = filesmod.native_available()
    return listing


@command("files.defaultDir")
def _default_dir(s: Session, hint: str = "", **_):
    hint = hint or s.project_path or ""
    return {"path": filesmod.default_dir(hint)}


@command("files.resolveSave")
def _resolve_save(s: Session, directory: str = "", filename: str = "",
                  kind: str = "any", **_):
    exts: List[str] = []
    for f in filesmod.filters(kind):
        exts = f["ext"]
        break
    return filesmod.resolve_save_path(directory, filename, exts)


@command("files.native")
def _native(s: Session, mode: str = "open", kind: str = "any",
            title: str = "", path: str = "", filename: str = "", **_):
    """Open the operating system's own file dialog on the machine running the
    solver. Falls back cleanly when there is no desktop session."""
    r = filesmod.native_dialog(mode=mode, kind=kind, title=title,
                               initialdir=path or filesmod.default_dir(
                                   s.project_path),
                               initialfile=filename)
    if not r.get("ok"):
        s.messages.add(f"Native file dialog unavailable: {r.get('error')}",
                       "warning", "files")
    return r


@command("materials.list")
def _materials(s: Session, **_):
    d = s.design
    lib = d.materials if d is not None else LIBRARY
    out = []
    for n in lib.names():
        m = lib.get(n)
        e = m.eps_model.eps(1e9)
        out.append({"name": m.name, "epsR": round(e.real, 6),
                    "tanD": round(-e.imag / e.real, 8) if e.real else 0.0,
                    "muR": round(m.mu_model.eps(1e9).real, 6),
                    "sigma": m.sigma, "kind": m.kind, "color": m.color})
    return {"materials": out}


@command("materials.add")
def _add_material(s: Session, name: str = "", epsR: float = 1.0,
                  tanD: float = 0.0, muR: float = 1.0, sigma: float = 0.0,
                  **_):
    d = s.require_design()
    d.materials.define(name, eps_r=float(epsR), tan_d=float(tanD),
                       mu_r=float(muR), sigma=float(sigma))
    s.messages.add(f"Added material {name!r}.", "info", "materials")
    return {"ok": True}


@command("view.set")
def _view_set(s: Session, **kw):
    s.view.update({k: v for k, v in kw.items()
                   if k in ("mode", "showMesh", "showField")})
    return {"ok": True, "view": dict(s.view)}


@command("script.run")
def _script(s: Session, code: str = "", **_):
    """
    Run Python against the live model — the equivalent of the usual scripting
    console. ``design``, ``project``, ``solution`` and ``aether as ae`` are in
    scope, and anything the script changes appears in the UI immediately
    because it is the same object graph.
    """
    import aether as ae
    buf = io.StringIO()
    env = {"ae": ae, "aether": ae, "np": np, "session": s,
           "project": s.project, "design": s.design, "solution": s.solution,
           "print": lambda *a, **k: print(*a, file=buf, **k)}
    try:
        try:
            val = eval(compile(code, "<console>", "eval"), env)
            if val is not None:
                print(repr(val), file=buf)
        except SyntaxError:
            exec(compile(code, "<console>", "exec"), env)
        s.dirty = True
        return {"ok": True, "output": buf.getvalue()}
    except Exception:
        return {"ok": False, "output": buf.getvalue() + traceback.format_exc()}


@command("app.exit")
def _exit(s: Session, **_):
    """
    Stop the workspace server.

    File ▸ Exit has to actually end the session, not just close a browser tab
    and leave a Python process holding the port. The reply is sent first and
    the shutdown happens a moment later on its own thread, because
    ``shutdown()`` blocks until the serving loop stops and would otherwise
    deadlock the request that asked for it.
    """
    import threading
    srv = getattr(s, "server", None)
    try:
        stop = srv.shutdown                      # a dead weakref raises here
    except (AttributeError, ReferenceError):
        return {"ok": False, "error": "no server attached to this session"}
    s.messages.add("Shutting down.", "info", "desktop")
    threading.Timer(0.35, stop).start()
    return {"ok": True}


@command("messages.since")
def _messages(s: Session, seq: int = 0, **_):
    return {"messages": s.messages.since(int(seq)), "seq": s.messages.seq}


@command("messages.clear")
def _clear(s: Session, **_):
    s.messages.clear()
    return {"ok": True}


# Extended engineering commands are registered without importing the HTTP server.
from .engineering import register as _register_engineering
_register_engineering(command)

#: Commands that change the model. Every one of them records an undo point
#: before it runs, so undo works for anything the UI or a script can do.
MUTATING = {
    "parameters.set": "Edit design variables",
    "modeler.editPrimitive": "Edit primitive dimensions",
    "analysis.setControls": "Edit solver controls",
    "modeler.airRegion": "Create air region",
    "modeler.resize": "Resize object",
    "modeler.draw": "Create object",
    "modeler.importCad": "Import CAD",
    "modeler.replaceCad": "Replace CAD Source",
    "modeler.repairBodies": "Repair Imported Bodies",
    "excitation.assignBetween": "Assign port",
    "mesh.addOperation": "Add Mesh Operation",
    "mesh.deleteOperation": "Delete Mesh Operation",
    "mesh.setOperation": "Edit Mesh Operation",
    "modeler.boolean": "Boolean",
    "modeler.transform": "Transform",
    "modeler.faceOperation": "Face Operation",
    "modeler.setProperty": "Edit property",
    "modeler.delete": "Delete",
    "modeler.paste": "Paste",
    "modeler.duplicate": "Duplicate",
    "boundary.assign": "Assign boundary",
    "boundary.delete": "Delete boundary",
    "excitation.assign": "Assign excitation",
    "excitation.setPolarity": "Set port polarity",
    "excitation.autoPort": "Assign port (auto)",
    "excitation.delete": "Delete excitation",
    "analysis.addSetup": "Add setup",
    "analysis.editSetup": "Edit setup",
    "analysis.addSweep": "Add sweep",
    "analysis.editSweep": "Edit sweep",
    "analysis.editSetup": "Edit setup",
    "analysis.optimizeApply": "Apply optimized variables",
    "analysis.deleteSetup": "Delete setup",
    "analysis.deleteSweep": "Delete sweep",
    "materials.add": "Add material",
    "script.run": "Script",
    "project.renameDesign": "Rename design",
}


def _relink_unchanged(d, live_entities) -> None:
    """
    After a failed command was rolled back, put the *original* objects back
    where nothing about them actually changed.

    ``Design.restore`` works from a deep copy, so a command that failed left
    every body in the design replaced by an equal-but-different object even
    when it never touched them. Anything holding a reference — a caller's
    handle, a cached display buffer keyed by object identity — was silently
    invalidated by an operation that was supposed to be a no-op.
    """
    if not live_entities:
        return
    for attr, olds in (("solids", live_entities[0]), ("sheets", live_entities[1])):
        by_name = {o.name: o for o in olds}
        current = getattr(d, attr, None)
        if current is None:
            continue
        for i, obj in enumerate(current):
            prev = by_name.get(obj.name)
            if prev is None or prev is obj:
                continue
            try:
                same = (prev.shape.to_dict() == obj.shape.to_dict()
                        and getattr(prev, "material", None) is not None
                        and getattr(obj, "material", None) is not None
                        and prev.material.name == obj.material.name
                        and getattr(prev, "visible", True) == getattr(obj, "visible", True)
                        and getattr(prev, "solve_inside", None) == getattr(obj, "solve_inside", None)
                        and prev.display_color == obj.display_color
                        and prev.display_transparency == obj.display_transparency)
            except Exception:                                # pragma: no cover
                same = False
            if same:
                current[i] = prev


def dispatch(s: Session, method: str,
             params: Optional[dict] = None) -> dict:
    fn = COMMANDS.get(method)
    if fn is None:
        raise KeyError(f"unknown command {method!r}")
    # Serialize commands: browser measurement requests and edits may overlap.
    with s._lock:
        label = MUTATING.get(method)
        if method == "modeler.copy" and (params or {}).get("cut"):
            label = "Cut"
        changing = label or method in {"project.new", "project.open",
            "project.template", "project.setDesign", "project.insertDesign",
            "edit.undo", "edit.redo", "analysis.generateMesh"}
        if s.job.running and changing:
            raise RuntimeError("Analysis is running. Wait for it to finish before editing or changing designs.")
        d = s.design
        snap = d.snapshot() if label and d is not None else None
        old_undo, old_redo = list(s._undo), list(s._redo)
        import copy
        old_picks = copy.deepcopy((s.selection, s.sel_faces, s.sel_edges, s.clipboard))
        old_dirty, old_solution = s.dirty, s.solution
        old_mesh = d.mesh if d is not None else None
        live_entities = (list(d.solids), list(d.sheets)) if d is not None else None
        try:
            result = fn(s, **(params or {}))
            if label and isinstance(result, dict) and result.get("ok") is False:
                raise RuntimeError(result.get("output") or result.get("error") or "Edit failed")
            if snap is not None:
                s.study_results = []; s.study_spec = {}
                valid_names = {o.name for o in d.solids + d.sheets}
                kept_ops = []
                for op in d.mesh_ops:
                    op.objects = [name for name in op.objects if name in valid_names]
                    if op.objects or op.selector is not None:
                        kept_ops.append(op)
                    else:
                        s.messages.add(f"Removed mesh operation {op.name!r}: its objects were deleted.", "warning", "modeler")
                d.mesh_ops = kept_ops
                s._undo = (old_undo + [(d.name, label, snap)])[-s.undo_limit:]
                s._redo.clear()
                s.solution = None
                s.dirty = True
                s.sel_faces = []
                s.sel_edges = []
            return result
        except Exception:
            if snap is not None:
                d.restore(snap)
                _relink_unchanged(d, live_entities)
                d.mesh = old_mesh
                s.design = d
                s._undo, s._redo = old_undo, old_redo
                s.selection, s.sel_faces, s.sel_edges, s.clipboard = old_picks
                s.dirty, s.solution = old_dirty, old_solution
            if method == "script.run" and "result" in locals() and result.get("ok") is False:
                return result
            raise



__all__ = ["COMMANDS", "dispatch", "state_json", "MUTATING"]
