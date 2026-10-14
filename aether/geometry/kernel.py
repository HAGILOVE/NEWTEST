"""
OpenCASCADE geometry kernel binding (through the gmsh OCC API).

Responsibilities
----------------
* replay a symbolic :class:`~aether.geometry.primitives.Shape` tree into real
  BRep entities,
* impose **conformal topology** on the whole assembly with an OCC
  ``fragment`` (``imprint``) so that neighbouring solids share faces --
  without this a tetrahedral mesh is non-conforming and the FEM solution is
  garbage at material interfaces,
* keep a stable mapping ``solid name -> OCC volume tags`` and
  ``boundary name -> OCC surface tags`` for the mesher and the boundary-
  condition layer.

The module is import-safe when gmsh is missing; :func:`available` reports it
and callers fall back to the built-in structured mesher.
"""
from __future__ import annotations

import math
import os
import threading
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from ..core.logging import get_logger
from .primitives import (Boolean, Box, Circle, Cone, Cylinder, Extrude,
                         FaceOperation, ImportedShape, Polygon, Revolve, Shape,
                         Sphere, Torus)

log = get_logger("geometry.kernel")

_LOCK = threading.RLock()
_GMSH = None


class ModelBuildError(ValueError):
    """
    A modelling operation that cannot be applied to this model.

    Distinct from "the CAD kernel is missing" or "this file will not read":
    those are reasons to fall back to a rough display, while this one means
    the model itself says something impossible -- a face that is no longer
    there, a sweep that produces nothing -- and must be reported rather than
    quietly replaced by a bounding box.
    """


def available() -> bool:
    """True when the OCC kernel (gmsh) can be imported and initialised."""
    try:
        _get_gmsh()
        return True
    except Exception:            # pragma: no cover - environment dependent
        return False


def _get_gmsh():
    global _GMSH
    if _GMSH is None:
        import gmsh  # noqa: F401  (import cost is deliberate & lazy)
        _GMSH = gmsh
    return _GMSH


def _keep_sigpipe_ignored() -> None:
    """
    Put SIGPIPE back to "ignore" after the CAD kernel has initialised.

    Python ignores SIGPIPE so that a write to a closed socket raises
    ``BrokenPipeError`` instead of killing the process. Initialising gmsh
    resets signal dispositions, and from then on a browser tab closed in the
    middle of a reply takes the whole workspace down with it. Signal handlers
    can only be set from the main thread, so this is best-effort.
    """
    try:
        import signal
        import threading
        if (hasattr(signal, "SIGPIPE")
                and threading.current_thread() is threading.main_thread()):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    except (ImportError, ValueError, OSError):              # pragma: no cover
        pass


class GmshSession:
    """Re-entrant context manager around gmsh's global state."""

    _depth = 0

    def __init__(self, name: str = "aether", verbosity: int = 0):
        self.name, self.verbosity = name, verbosity

    def __enter__(self):
        gmsh = _get_gmsh()
        _LOCK.acquire()
        try:
            if GmshSession._depth == 0:
                # a previous session may have died before finalising; the API
                # is a process-global singleton, so reset it rather than
                # stacking a second initialise on top
                try:
                    if gmsh.isInitialized():
                        gmsh.finalize()
                except Exception:
                    pass
                # interruptible=False: gmsh installs a SIGINT handler on
                # initialise, and signal handlers can only be set from the
                # main thread — meshing from a worker thread (the GUI's
                # solve job, or any HTTP request) fails without this.
                try:
                    gmsh.initialize([], False, interruptible=False)
                except TypeError:                    # older gmsh API
                    gmsh.initialize([], False)
                gmsh.option.setNumber("General.Terminal", 0)
                gmsh.option.setNumber("General.Verbosity", self.verbosity)
                gmsh.model.add(self.name)
                _keep_sigpipe_ignored()
            GmshSession._depth += 1
        except Exception:
            _LOCK.release()
            raise
        return gmsh

    def __exit__(self, *exc):
        gmsh = _get_gmsh()
        GmshSession._depth -= 1
        if GmshSession._depth == 0:
            try:
                gmsh.clear()
            finally:
                gmsh.finalize()
        _LOCK.release()
        return False


# --------------------------------------------------------------------------
# Shape replay
# --------------------------------------------------------------------------

DimTag = Tuple[int, int]


# --------------------------------------------------------------------------
# keeping a display / inspection mesh finite
# --------------------------------------------------------------------------


def display_triangle_budget() -> int:
    """
    How many triangles one surface mesh built for *looking at* may cost.

    Overridable with ``AETHER_VIEW_MAX_TRIS``. This is a display and
    inspection limit only; the FEM mesh is sized by physics and is not
    touched by it.
    """
    try:
        return max(50_000, min(8_000_000,
                               int(os.environ.get("AETHER_VIEW_MAX_TRIS",
                                                  "900000"))))
    except ValueError:
        return 900_000


def prune_to_bodies(gmsh, dim_tags) -> int:
    """
    Drop every entity the given bodies do not use, and say how many went.

    A STEP file carries more than its solids. One exported from Warps through
    Spatial InterOp also carries presentation geometry: free faces of hundreds
    of square metres and free curves tens of metres long, in an assembly whose
    largest body is 48 mm across. ``mesh.generate`` meshes *every* entity in
    the model, so those free faces were triangulated at the assembly's element
    size — a hundred million triangles for geometry that is not part of the
    model and is never drawn. Removing them first is the difference between an
    import that finishes and one that does not.
    """
    dim_tags = [(int(d), int(t)) for d, t in dim_tags]
    keep = set(dim_tags)
    try:
        bnd = gmsh.model.getBoundary(dim_tags, combined=False, oriented=False,
                                     recursive=True)
        keep.update((int(d), abs(int(t))) for d, t in bnd)
    except Exception:                                       # pragma: no cover
        return 0
    strays = [(int(d), int(t)) for dim in (3, 2, 1, 0)
              for d, t in gmsh.model.getEntities(dim)
              if (int(d), int(t)) not in keep]
    if not strays:
        return 0
    try:
        gmsh.model.removeEntities(strays, False)
    except Exception:                                       # pragma: no cover
        return 0
    # Debug, not info: this runs on every tessellation, and a line in the
    # Message Manager on every redraw is noise. What it removes is reported
    # where it matters -- once, when the coarsening below actually bites.
    log.debug("ignored %d CAD entities that belong to no body", len(strays))
    return len(strays)


def fit_mesh_size(gmsh, h: float, budget: Optional[int] = None) -> float:
    """
    Coarsen *h* until the surface mesh it implies fits the triangle budget.

    The area still in the model decides what a given element size costs, so
    the size can be solved for rather than discovered after the fact.
    """
    budget = budget or display_triangle_budget()
    area = 0.0
    for _, tag in gmsh.model.getEntities(2):
        try:
            m = float(gmsh.model.occ.getMass(2, tag))
        except Exception:
            continue
        if math.isfinite(m) and m > 0:
            area += m
    if area <= 0:
        return h
    # an equilateral triangle of side h covers h^2 * sqrt(3) / 4
    need = math.sqrt(area / (budget * 0.433))
    if need > h:
        log.info("mesh seed coarsened %.4g mm -> %.4g mm to stay under "
                 "%d display triangles", h * 1e3, need * 1e3, budget)
        return need
    return h


def steady_size_options(gmsh) -> None:
    """
    Stop one bad face from dragging the whole mesh down to its own scale.

    Sizes propagated from CAD points and from neighbouring boundaries are what
    turn a sliver face in an imported solid into a global refinement.
    """
    for name in ("Mesh.MeshSizeFromPoints",
                 "Mesh.MeshSizeFromParametricPoints",
                 "Mesh.MeshSizeExtendFromBoundary"):
        try:
            gmsh.option.setNumber(name, 0)
        except Exception:                                   # pragma: no cover
            pass


def build_shape(shape: Shape, gmsh) -> List[DimTag]:
    """Replay *shape* into OCC entities and return their ``(dim, tag)`` list."""
    occ = gmsh.model.occ
    tags = _build_node(shape, gmsh, occ)
    for t in shape._xform:
        tags = _apply_xform(tags, t, occ)
    return tags


def _build_node(s: Shape, gmsh, occ) -> List[DimTag]:
    if isinstance(s, Box):
        p, d = s.position, s.size
        return [(3, occ.addBox(p[0], p[1], p[2], d[0], d[1], d[2]))]

    if isinstance(s, Cylinder):
        c, a = s.center, s.axis
        h = s.height
        return [(3, occ.addCylinder(c[0], c[1], c[2], a[0] * h, a[1] * h,
                                    a[2] * h, s.radius, angle=s.angle))]

    if isinstance(s, Sphere):
        c = s.center
        return [(3, occ.addSphere(c[0], c[1], c[2], s.radius))]

    if isinstance(s, Cone):
        c, a, h = s.center, s.axis, s.height
        return [(3, occ.addCone(c[0], c[1], c[2], a[0] * h, a[1] * h, a[2] * h,
                                s.r1, s.r2))]

    if isinstance(s, Torus):
        c = s.center
        t = occ.addTorus(c[0], c[1], c[2], s.r_major, s.r_minor)
        tags = [(3, t)]
        # OCC torus is z-axis aligned; rotate onto requested axis
        return _align_axis(tags, (0, 0, 1), s.axis, c, occ)

    if isinstance(s, Circle):
        c, a = s.center, s.axis
        w = occ.addCircle(c[0], c[1], c[2], s.radius,
                          zAxis=list(a))
        loop = occ.addCurveLoop([w])
        return [(2, occ.addPlaneSurface([loop]))]

    if isinstance(s, Polygon):
        pts = [occ.addPoint(*p) for p in s.points]
        lines = [occ.addLine(pts[i], pts[(i + 1) % len(pts)])
                 for i in range(len(pts))]
        loop = occ.addCurveLoop(lines)
        return [(2, occ.addPlaneSurface([loop]))]

    if isinstance(s, Extrude):
        base = build_shape(s.profile, gmsh)
        out = occ.extrude(base, *s.vector)
        return [dt for dt in out if dt[0] == 3] or [dt for dt in out if dt[0] == 2]

    if isinstance(s, Revolve):
        base = build_shape(s.profile, gmsh)
        o, a = s.origin, s.axis
        out = occ.revolve(base, o[0], o[1], o[2], a[0], a[1], a[2], s.angle)
        return [dt for dt in out if dt[0] == 3] or [dt for dt in out if dt[0] == 2]

    if isinstance(s, ImportedShape):
        from .brep_io import import_into_occ
        b = getattr(s, "body", -1)
        return import_into_occ(s.path, gmsh, healing=s.healing,
                               scale_to_m=s.scale_to_m,
                               unit=getattr(s, "unit", "auto"),
                               body=b if b is not None and b >= 0 else None)

    if isinstance(s, FaceOperation):
        return _build_face_op(s, gmsh, occ)

    if isinstance(s, Boolean):
        first = build_shape(s.operands[0], gmsh)
        rest: List[DimTag] = []
        for o in s.operands[1:]:
            rest += build_shape(o, gmsh)
        if not rest:
            return first
        if s.op == "union":
            out, _ = occ.fuse(first, rest, removeObject=True, removeTool=True)
        elif s.op == "cut":
            out, _ = occ.cut(first, rest, removeObject=True, removeTool=True)
        elif s.op == "intersect":
            out, _ = occ.intersect(first, rest, removeObject=True, removeTool=True)
        else:  # pragma: no cover
            raise ValueError(f"unknown boolean op {s.op!r}")
        return list(out)

    raise TypeError(f"cannot build geometry node of type {type(s).__name__}")


def _align_axis(tags, src, dst, origin, occ):
    src = np.array(src, float); dst = np.array(dst, float)
    src /= np.linalg.norm(src); dst /= np.linalg.norm(dst)
    v = np.cross(src, dst)
    s = np.linalg.norm(v)
    if s < 1e-12:
        if float(src @ dst) > 0:
            return tags
        v = np.array([1.0, 0.0, 0.0]) if abs(src[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        v = np.cross(src, v); v /= np.linalg.norm(v); ang = math.pi
    else:
        ang = math.atan2(s, float(src @ dst)); v /= s
    occ.rotate(tags, origin[0], origin[1], origin[2], v[0], v[1], v[2], ang)
    return tags


def _build_face_op(s: FaceOperation, gmsh, occ) -> List[DimTag]:
    """
    Replay a face operation: locate the picked faces, then sweep or move them.

    The faces are found by geometry, not by tag: OCC renumbers entities on
    every build, so an index recorded when the face was picked would point at
    a different face the next time the model is rebuilt. Matching on the
    face's own centre of mass and normal is stable under everything that does
    not change the face itself.

    The two operations are not the same thing, and used to be built as though
    they were:

    * **Move Faces** drags the face and the body follows it -- the swept
      volume is fused on for a positive distance and cut away for a negative
      one, which is what dragging a face in or out of a solid does.
    * **Sweep Face Along Normal** makes a *new body* out of the swept volume
      and leaves the face's own body exactly as it was. That is what the
      command is for: giving a face of an existing part its own object, so it
      can be assigned its own material, boundary or port.
    """
    base = build_shape(s.base, gmsh)
    occ.synchronize()
    if abs(s.distance) < 1e-15 or not s.faces:
        return base

    curved = [f for f in s.faces if not f.get("planar", True)]
    if curved:
        raise ModelBuildError(
            "sweeping or moving a curved face is not supported: 'along the "
            "normal' has no single direction on a curved surface. Pick a "
            "planar face, or use Modeler > Arrange > Scale on the whole body.")

    targets = _match_faces(gmsh, occ, s.faces, base)
    if not targets:
        raise ModelBuildError(
            f"face operation {s.op!r}: none of the {len(s.faces)} recorded "
            "face(s) could be found on the body -- it has changed shape since "
            "they were picked")

    sweeping = str(s.op) == "sweep"
    made: List[DimTag] = []
    for tag, nrm in targets:
        d = s.distance
        v = [float(x) * abs(d) for x in nrm]
        if d < 0:
            v = [-x for x in v]
        # A sweep works on a copy of the face, so the body it came from is
        # never consumed by the extrusion and can be discarded intact.
        src = occ.copy([(2, tag)]) if sweeping else [(2, tag)]
        out = occ.extrude(src, v[0], v[1], v[2])
        made += [dt for dt in out if dt[0] == 3]
    occ.synchronize()
    if not made:
        raise ModelBuildError(f"face operation {s.op!r} produced no volume")

    if sweeping:
        # The result is the swept volume alone; the base was only ever needed
        # to find the face.
        occ.remove(base, recursive=True)
        occ.synchronize()
        if len(made) > 1:
            res, _ = occ.fuse(made[:1], made[1:], removeObject=True,
                              removeTool=True)
            occ.synchronize()
            made = [dt for dt in res if dt[0] == 3] or res
        return made

    if s.distance > 0:
        res, _ = occ.fuse(base, made, removeObject=True, removeTool=True)
    else:
        res, _ = occ.cut(base, made, removeObject=True, removeTool=True)
    occ.synchronize()
    return [dt for dt in res if dt[0] == 3] or res


def _match_faces(gmsh, occ, refs: Sequence[dict],
                 base: Optional[List[DimTag]] = None) -> List[Tuple[int, tuple]]:
    """
    OCC surfaces matching the recorded face references.

    Only the faces of the body being operated on are considered -- when a whole
    design is built into one session, another object's face can sit exactly
    where the recorded one does, and extruding *that* would quietly deform a
    different part of the model.

    Each reference is matched to the single closest surface whose centre of
    mass sits on it and whose normal agrees, so a body with two identical
    parallel faces cannot pick up both.
    """
    import numpy as _np
    from .select import FaceSelector

    if base:
        own = gmsh.model.getBoundary(base, combined=False, oriented=False,
                                     recursive=False)
        candidates = sorted({abs(int(t)) for d, t in own if d == 2})
    else:
        candidates = [t for _, t in gmsh.model.getEntities(2)]

    surfaces = []
    for tag in candidates:
        try:
            com = _np.asarray(occ.getCenterOfMass(2, tag), float)
            uv = gmsh.model.getParametrization(2, tag, com.tolist())
            nrm = _np.asarray(gmsh.model.getNormal(tag, uv), float)[:3]
        except Exception:                                   # pragma: no cover
            continue
        ln = float(_np.linalg.norm(nrm))
        if ln < 1e-300:
            continue
        surfaces.append((tag, com, nrm / ln))

    out: List[Tuple[int, tuple]] = []
    for ref in refs:
        sel = FaceSelector(point=ref.get("point", (0, 0, 0)),
                           normal=ref.get("normal", (0, 0, 1)),
                           lo=ref.get("lo", (0, 0, 0)),
                           hi=ref.get("hi", (0, 0, 0)),
                           planar=bool(ref.get("planar", True)))
        best, bestd = None, float("inf")
        for tag, com, nrm in surfaces:
            if not bool(_np.asarray(sel(com.reshape(1, 3),
                                        nrm.reshape(1, 3)))[0]):
                continue
            d = float(_np.linalg.norm(com - sel.point))
            if d < bestd:
                bestd, best = d, (tag, tuple(float(x) for x in sel.normal))
        if best is not None and best not in out:
            out.append(best)
    return out


def _apply_xform(tags: List[DimTag], t: dict, occ) -> List[DimTag]:
    op = t["op"]
    if op == "translate":
        occ.translate(tags, *t["d"])
    elif op == "rotate":
        o, a = t["origin"], t["axis"]
        occ.rotate(tags, o[0], o[1], o[2], a[0], a[1], a[2], t["angle"])
    elif op == "scale":
        o, s = t["origin"], t["s"]
        occ.dilate(tags, o[0], o[1], o[2], s[0], s[1], s[2])
    elif op == "mirror":
        n, o = np.array(t["n"]), np.array(t["origin"])
        d = -float(n @ o)
        occ.mirror(tags, n[0], n[1], n[2], d)
    return tags


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


class Assembly:
    """
    Conformal multi-solid assembly.

    ``build()`` replays every solid, then performs a single OCC *fragment*
    so all solids share coincident faces.  Ownership is recovered by
    centre-of-mass containment tests against the pre-fragment bodies, which is
    robust for the disjoint / nested arrangements normal in EM models.
    """

    def __init__(self):
        self.solid_volumes: Dict[str, List[int]] = {}
        self.sheet_surfaces: Dict[str, List[int]] = {}
        self.skipped: Dict[str, str] = {}
        self._built = False

    def build(self, gmsh, solids: Sequence, sheets: Sequence = (),
              strict: bool = False) -> "Assembly":
        """
        Replay every body into one OCC session.

        A body that cannot be built -- an imported file in a format the
        kernel cannot read, a CAD source that has gone missing -- is left
        out and recorded in :attr:`skipped` rather than taking the whole
        assembly down with it. One unreadable part in a forty-part import
        used to mean no mesh at all and a raw ``CadImportError`` on screen;
        now the rest of the model meshes and the caller says exactly which
        bodies are missing and what to do about them. Pass ``strict=True``
        where a partial assembly would be wrong.
        """
        sheets = [s for s in sheets if not getattr(s.shape, "reference_only", False)]
        occ = gmsh.model.occ
        raw: List[Tuple[str, List[DimTag]]] = []
        for sol in solids:
            try:
                dts = build_shape(sol.shape, gmsh)
            except Exception as exc:
                if strict:
                    raise
                self.skipped[sol.name] = str(exc)
                log.warning("body %r left out of the assembly: %s",
                            sol.name, exc)
                occ.synchronize()
                continue
            raw.append((sol.name, [dt for dt in dts if dt[0] == 3]))
        occ.synchronize()

        # remember a probe point + bbox for each body before fragmenting
        probes: Dict[str, List[Tuple[np.ndarray, np.ndarray, np.ndarray]]] = {}
        for name, dts in raw:
            entries = []
            for dim, tag in dts:
                com = np.array(occ.getCenterOfMass(dim, tag))
                bb = np.array(gmsh.model.getBoundingBox(dim, tag))
                entries.append((com, bb[:3], bb[3:]))
            probes[name] = entries

        all_dt = [dt for _, dts in raw for dt in dts]
        sheet_dt: List[DimTag] = []
        kept_sheets = []
        for sh in sheets:
            try:
                dts = build_shape(sh.shape, gmsh)
            except Exception as exc:
                if strict:
                    raise
                self.skipped[sh.name] = str(exc)
                log.warning("sheet %r left out of the assembly: %s", sh.name, exc)
                occ.synchronize()
                continue
            kept_sheets.append(sh)
            sheet_dt += [dt for dt in dts if dt[0] == 2]
        sheets = kept_sheets
        occ.synchronize()

        if len(all_dt) + len(sheet_dt) > 1:
            frag_in = all_dt + sheet_dt
            out, parent_map = occ.fragment(frag_in[:1], frag_in[1:])
            occ.synchronize()
            # parent_map[i] lists children of frag_in[i]
            for idx, (name, dts) in enumerate(_index_parents(raw, frag_in)):
                pass
            self.solid_volumes = _assign_by_parents(raw, frag_in, parent_map)
            self.sheet_surfaces = _assign_sheets(sheets, frag_in, parent_map,
                                                 len(all_dt))
        else:
            occ.synchronize()
            self.solid_volumes = {n: [t for _, t in dts] for n, dts in raw}
            self.sheet_surfaces = {}
            if sheets and sheet_dt:
                self.sheet_surfaces = {sheets[0].name: [t for _, t in sheet_dt]}
        self._built = True
        return self

    # -- queries ------------------------------------------------------------
    def volumes(self) -> List[int]:
        return sorted({t for v in self.solid_volumes.values() for t in v})

    def owner_of_volume(self, tag: int) -> str:
        for name, tags in self.solid_volumes.items():
            if tag in tags:
                return name
        return ""


def _index_parents(raw, frag_in):
    return raw


def _assign_by_parents(raw, frag_in, parent_map) -> Dict[str, List[int]]:
    """
    Map fragment children back to the owning solid.

    ``parent_map[i]`` are the resulting entities produced from ``frag_in[i]``.
    Where a child came from several parents (overlap) the *last declared*
    solid wins -- matching the usual "later object overrides" behaviour.
    """
    pos: Dict[DimTag, int] = {dt: i for i, dt in enumerate(frag_in)}
    owner_of_index: List[str] = [""] * len(frag_in)
    for name, dts in raw:
        for dt in dts:
            if dt in pos:
                owner_of_index[pos[dt]] = name
    out: Dict[str, List[int]] = {name: [] for name, _ in raw}
    claimed: Dict[int, str] = {}
    for i, children in enumerate(parent_map):
        owner = owner_of_index[i] if i < len(owner_of_index) else ""
        if not owner:
            continue
        for dim, tag in children:
            if dim != 3:
                continue
            claimed[tag] = owner            # later parents overwrite
    for tag, owner in claimed.items():
        out.setdefault(owner, []).append(tag)
    return {k: sorted(set(v)) for k, v in out.items() if v}


def _assign_sheets(sheets, frag_in, parent_map, n_solid_dt) -> Dict[str, List[int]]:
    out: Dict[str, List[int]] = {}
    if not sheets:
        return out
    idx = n_solid_dt
    for sh in sheets:
        tags: List[int] = []
        if idx < len(parent_map):
            tags = [t for d, t in parent_map[idx] if d == 2]
        out[sh.name] = sorted(set(tags))
        idx += 1
    return out


__all__ = ["available", "GmshSession", "build_shape", "Assembly", "DimTag"]
