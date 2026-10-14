"""
CAD interchange: STEP / IGES / BREP / STL import and export.

Import goes through OpenCASCADE (via gmsh) which gives real BRep solids --
not a faceted approximation -- so downstream meshing keeps analytic curvature.
STL is handled as a discrete surface and, when watertight, is turned into a
volume so it can still be meshed.

Every importer applies:
  * unit resolution (STEP/IGES carry their own units; a scale override is
    available for files that lie),
  * optional shape healing (sew faces, fix small edges, remove degenerate
    geometry) -- the single biggest cause of "my imported model won't mesh".
"""
from __future__ import annotations

import os
import re
import struct
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..core.logging import get_logger

log = get_logger("geometry.brep_io")

# Units a CAD file may declare, in metres. STEP and IGES carry their own
# unit; STL and OBJ carry none at all and are raw numbers.
UNIT_SCALE = {"m": 1.0, "cm": 1e-2, "mm": 1e-3, "um": 1e-6,
              "in": 2.54e-2, "mil": 2.54e-5, "ft": 0.3048}
UNITLESS = {"stl", "obj"}

STEP_EXT = {".step", ".stp", ".p21"}
IGES_EXT = {".iges", ".igs"}
BREP_EXT = {".brep", ".brp"}
STL_EXT = {".stl"}
OBJ_EXT = {".obj"}
DXF_EXT = {".dxf"}
SAT_EXT = {".sat", ".sab"}          # ACIS -- the usual native solid format
SUPPORTED = STEP_EXT | IGES_EXT | BREP_EXT | STL_EXT | OBJ_EXT | DXF_EXT


class CadImportError(RuntimeError):
    pass


def detect_format(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in STEP_EXT:
        return "step"
    if ext in IGES_EXT:
        return "iges"
    if ext in BREP_EXT:
        return "brep"
    if ext in STL_EXT:
        return "stl"
    if ext in OBJ_EXT:
        return "obj"
    if ext in DXF_EXT:
        return "dxf"
    if ext in SAT_EXT:
        return "sat"
    return "unknown"


# --------------------------------------------------------------------------
# OCC import
# --------------------------------------------------------------------------


def declared_unit(path: str) -> Optional[str]:
    """
    The length unit a STEP or IGES file declares, if it declares one.

    STEP states it as ``SI_UNIT(.MILLI.,.METRE.)`` (or ``CONVERSION_BASED_UNIT``
    for inches); IGES puts a unit name in field 14 of the global section. STL
    and OBJ declare nothing -- they are bare numbers, which is why the importer
    has to be told.
    """
    fmt = detect_format(path)
    if fmt not in ("step", "iges"):
        return None
    try:
        with open(path, "r", errors="replace") as fh:
            head = fh.read(400_000)
    except OSError:                                       # pragma: no cover
        return None
    if fmt == "step":
        m = re.search(r"SI_UNIT\s*\(\s*\.?(\w*)\.?\s*,\s*\.METRE\.", head)
        if m:
            return {"MILLI": "mm", "CENTI": "cm", "MICRO": "um",
                    "": "m", "$": "m"}.get(m.group(1).upper(), "m")
        if re.search(r"CONVERSION_BASED_UNIT\s*\(\s*'INCH'", head, re.I):
            return "in"
        return None
    m = re.search(r"\b(MM|M|IN|INCH|CM|FT|MIL)\b\s*,", head[:2000], re.I)
    if m:
        return {"MM": "mm", "M": "m", "IN": "in", "INCH": "in",
                "CM": "cm", "FT": "ft", "MIL": "mil"}[m.group(1).upper()]
    return None


def import_into_occ(path: str, gmsh, healing="auto",
                    scale_to_m: float = 1.0,
                    unit: Optional[str] = None,
                    body: Optional[int] = None) -> List[Tuple[int, int]]:
    """
    Import *path* into the *current* gmsh OCC model; return dimTags.

    Aether works in metres throughout, but CAD does not: a STEP file from any
    mechanical tool almost always declares millimetres and stores bare numbers
    like ``20.0``. Imported without conversion that 20 mm feature becomes a
    20 **metre** one -- the part is a thousand times too big, the camera fits
    to it, and everything else in the model becomes an invisible speck. So the
    reader is told to deliver metres, and for formats that declare no unit at
    all (STL, OBJ) the caller states which one to assume.
    """
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        raise CadImportError(f"CAD file not found: {path}")
    fmt = detect_format(path)
    occ = gmsh.model.occ

    if fmt == "sat":
        raise CadImportError(
            "ACIS .sat/.sab is a proprietary Spatial format that OpenCASCADE "
            "cannot read. Export the body as STEP AP214 from Warps "
            "(Modeler > Export > .step) and import that instead."
        )

    # Aether is metric internally. OCC could convert a declared unit itself
    # via Geometry.OCCTargetUnit, but that option is honoured only for the
    # first STEP read in a process -- every later import in the same session
    # silently comes back in the file's own numbers. So the reader is left
    # alone (it delivers raw coordinates) and the conversion is done here,
    # where it is the same on the first import and the hundredth.
    explicit = (unit or "").strip().lower()
    if explicit == "auto":
        explicit = ""
    gmsh.option.setString("Geometry.OCCTargetUnit", "")
    if fmt in ("step", "iges"):
        # A STEP file from any mechanical tool stores bare numbers like 20.0
        # and declares what they mean. Read as metres that 20 mm feature
        # becomes a 20 metre one: the camera fits to it and the rest of the
        # model turns into an invisible speck.
        applied = explicit or declared_unit(path) or "mm"
        scale_to_m *= UNIT_SCALE.get(applied, 1e-3)
    elif fmt in ("stl", "obj"):
        # No unit is declared anywhere in these formats; millimetres is what
        # every mechanical CAD exporter writes.
        scale_to_m *= UNIT_SCALE.get(explicit or "mm", 1e-3)
    elif fmt == "dxf":
        pass                     # the DXF reader resolves $INSUNITS itself
    elif fmt == "brep":
        # OCC's own format: unitless, and Aether writes it in metres.
        if explicit:
            scale_to_m *= UNIT_SCALE.get(explicit, 1.0)

    gmsh.option.setNumber("Geometry.OCCImportLabels", 1)

    if fmt in ("step", "iges", "brep"):
        dts = _import_brep(path, gmsh, occ, healing)
    elif fmt == "dxf":
        dts = _import_dxf(path, gmsh, occ, 1.0, unit=explicit or None)
        scale_to_m = 1.0                    # the reader applies it itself
    elif fmt in ("stl", "obj"):
        dts = _import_discrete(path, gmsh)
    else:
        raise CadImportError(
            f"unsupported CAD format {os.path.splitext(path)[1]!r}; "
            f"supported: {sorted(SUPPORTED)}"
        )
    occ.synchronize()

    # Keep only the top-level shapes. importShapes also hands back the faces
    # and edges that belong to the solids, and scaling that whole list asks
    # OCC to transform a body and its own children at once.
    solids = [dt for dt in dts if dt[0] == 3]
    top = solids if solids else [dt for dt in dts if dt[0] == 2] or dts

    if body is not None and body >= 0:
        # One body out of an assembly. The others are removed rather than
        # ignored, so the session holds exactly the object being built and a
        # later face lookup cannot stray into a neighbour.
        top = sorted(top, key=lambda dt: dt[1])
        if body >= len(top):
            raise CadImportError(
                f"{os.path.basename(path)} has {len(top)} bodies; "
                f"body {body} was asked for")
        keep = top[body]
        drop = [dt for dt in top if dt != keep]
        if drop:
            occ.remove(drop, recursive=True)
            occ.synchronize()
        top = [keep]

    if scale_to_m != 1.0:
        occ.dilate(top, 0, 0, 0, scale_to_m, scale_to_m, scale_to_m)
        occ.synchronize()

    log.info("imported %s: %d solid(s), %d surface(s)%s",
             os.path.basename(path), len(solids),
             sum(1 for dt in dts if dt[0] == 2),
             f", scaled x{scale_to_m:g}" if scale_to_m != 1.0 else "")
    return top


def _dedupe_ring(pts: np.ndarray) -> np.ndarray:
    """
    A closed ring with no repeated and no zero-length steps.

    A DXF polyline exported from a layout tool commonly repeats its first
    point at the end, and often carries quantisation noise: steps of a tenth
    of a micron in an outline forty-five millimetres across. OpenCASCADE
    refuses to build an edge shorter than its confusion tolerance — 1e-7 in
    model units, and Aether's model units are metres — so those steps came
    back as "Could not create line" and took the whole import with them.

    The tolerance is the larger of a fraction of the ring's own size and one
    micrometre, which is two hundred times below the smallest real feature in
    a PCB outline and ten times above what OCC will refuse.
    """
    pts = np.asarray(pts, float)
    if len(pts) < 2:
        return pts
    span = float(np.max(pts.max(axis=0) - pts.min(axis=0)))
    tol = max(span * 1e-5, 1e-6)
    keep = [pts[0]]
    for p in pts[1:]:
        if np.linalg.norm(p - keep[-1]) > tol:
            keep.append(p)
    # the ring closes on itself: the last point must not repeat the first
    while len(keep) > 1 and np.linalg.norm(keep[-1] - keep[0]) <= tol:
        keep.pop()
    return np.asarray(keep, float)


def _import_dxf(path: str, gmsh, occ, scale_to_m: float,
                unit: Optional[str] = None) -> List[Tuple[int, int]]:
    """
    Build the closed outlines of a DXF drawing as flat faces.

    A DXF is a drawing, not a model: what it holds is outlines. Each closed one
    becomes a face, and an outline that lies inside another is cut out of it --
    which is what a mounting hole, a slot or a coupling gap in a PCB drawing
    is. From there one face sweep gives the copper its thickness.
    """
    from .dxf import outlines as _outlines

    loops = _outlines(path, unit=unit)
    if not loops:
        raise CadImportError(
            f"{os.path.basename(path)} has no closed outline to build a face "
            "from. DXF holds drawings: a shape has to be a closed polyline, "
            "circle or solid to become geometry.")
    loops.sort(key=lambda p: p.area, reverse=True)

    faces: List[Tuple[int, int, object]] = []
    skipped = 0
    for pl in loops:
        pts = np.asarray(pl.points, float) * float(scale_to_m or 1.0)
        pts = _dedupe_ring(pts)
        if len(pts) < 3:
            skipped += 1
            continue
        try:
            tags = [occ.addPoint(*p) for p in pts]
            lines = [occ.addLine(tags[i], tags[(i + 1) % len(tags)])
                     for i in range(len(tags))]
            loop = occ.addCurveLoop(lines)
            faces.append((occ.addPlaneSurface([loop]), pl.area, pl))
        except Exception as exc:
            # One unusable outline is not a reason to lose the drawing. A
            # DXF exported from a layout tool routinely repeats a vertex or
            # doubles back on itself, and OCC refuses a zero-length edge.
            skipped += 1
            log.warning("DXF outline skipped (%d points): %s", len(pts), exc)
    occ.synchronize()
    if skipped:
        log.warning("%s: %d of %d outline(s) could not be built as faces",
                    os.path.basename(path), skipped, len(loops))
    if not faces:
        raise CadImportError(f"{os.path.basename(path)}: no usable outline")

    # Cut every outline that sits inside a bigger one out of it.
    outer = [f for f in faces]
    made: List[Tuple[int, int]] = []
    used = set()
    for i, (tag, area, pl) in enumerate(outer):
        if i in used:
            continue
        holes = []
        for j, (tag2, area2, pl2) in enumerate(outer):
            if j <= i or j in used:
                continue
            if _inside(pl2, pl):
                holes.append((2, tag2))
                used.add(j)
        if holes:
            res, _ = occ.cut([(2, tag)], holes, removeObject=True,
                             removeTool=True)
            made += [dt for dt in res if dt[0] == 2]
        else:
            made.append((2, tag))
    occ.synchronize()
    log.info("imported %s: %d outline(s) -> %d face(s)",
             os.path.basename(path), len(loops), len(made))
    return made


def _inside(inner, outer) -> bool:
    """Is every point of *inner* inside the *outer* outline (XY, ray cast)?"""
    p3 = np.asarray(inner.points, float)
    q3 = np.asarray(outer.points, float)
    local=q3-q3[0]
    normal=np.cross(local,np.roll(local,-1,axis=0)).sum(axis=0)
    length=np.linalg.norm(normal)
    if length<=1e-30:return False
    normal=normal/length
    if np.max(np.abs((p3-q3[0]) @ normal))>1e-8:return False
    axes=[i for i in range(3) if i!=int(np.argmax(np.abs(normal)))]
    p=p3[:,axes];q=q3[:,axes]
    if len(q) < 3:
        return False
    x, y = p[:, 0], p[:, 1]
    inside = np.zeros(len(p), bool)
    n = len(q)
    for k in range(n):
        x1, y1 = q[k]
        x2, y2 = q[(k + 1) % n]
        cond = ((y1 > y) != (y2 > y))
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (x2 - x1) * (y - y1) / np.where(y2 - y1 == 0, np.nan,
                                                   y2 - y1) + x1
        inside ^= cond & (x < xint)
    return bool(inside.all())


def _set_healing(gmsh, on: bool) -> None:
    for opt in ("OCCFixDegenerated", "OCCFixSmallEdges", "OCCFixSmallFaces",
                "OCCSewFaces", "OCCMakeSolids"):
        gmsh.option.setNumber("Geometry." + opt, 1 if on else 0)


def _ascii_path(path: str):
    """
    A path OpenCASCADE will certainly accept, copying the file if need be.

    OCC takes file names as narrow strings, and on Windows a path holding
    characters outside the system code page -- a Korean folder name, an
    accented part number -- reaches it mangled and the read simply fails.
    Copying to a temporary ASCII name costs one file copy on exactly the files
    that would otherwise not open at all.
    """
    try:
        path.encode("ascii")
        return path, None
    except UnicodeEncodeError:
        import shutil
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            suffix=os.path.splitext(path)[1].lower(), delete=False)
        tmp.close()
        shutil.copy2(path, tmp.name)
        log.info("copied %s to an ASCII path for the CAD kernel",
                 os.path.basename(path))
        return tmp.name, tmp.name


def _import_brep(path: str, gmsh, occ, healing) -> List[Tuple[int, int]]:
    """
    Read a STEP/IGES/BREP file, healing it only if it turns out to need it.

    Healing is not free: "sew faces" welds every body in an assembly into one
    compound and "make solids" then fails on it, so a perfectly good
    three-part STEP came back as fifteen loose faces and no solids at all --
    one lump that could be neither split nor meshed. So the file is read as it
    is first, and healing is applied only when that produced no solid, which
    is the case it was meant for.
    """
    want = str(healing).lower() if not isinstance(healing, bool) else \
        ("always" if healing else "never")
    if want not in ("always", "never"):
        want = "auto"

    read_path, tmp = _ascii_path(path)
    try:
        if want != "always":
            _set_healing(gmsh, False)
            dts = _read_shapes(read_path, path, occ)
            if want == "never" or any(d == 3 for d, _ in dts):
                return dts
            # Nothing solid came out: clear what was read and try again, healed.
            occ.synchronize()
            occ.remove(occ.getEntities(), recursive=True)
            occ.synchronize()
            log.info("%s produced no solid; retrying with shape healing",
                     os.path.basename(path))

        _set_healing(gmsh, True)
        return _read_shapes(read_path, path, occ)
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:                                 # pragma: no cover
                pass


def _read_shapes(read_path: str, shown: str, occ) -> List[Tuple[int, int]]:
    """importShapes, with a failure that says which file and what to try."""
    try:
        return occ.importShapes(read_path, highestDimOnly=False)
    except Exception as exc:
        raise CadImportError(
            f"OpenCASCADE could not read {os.path.basename(shown)}: {exc}. "
            "If it came from another CAD system, re-exporting it as STEP "
            "AP214 usually settles it; a file that is only a mesh should be "
            "saved as STL instead."
        ) from exc


def _import_discrete(path: str, gmsh) -> List[Tuple[int, int]]:
    """Merge a faceted file and promote it to a volume when watertight."""
    gmsh.merge(path)
    gmsh.model.mesh.removeDuplicateNodes()
    gmsh.model.mesh.classifySurfaces(np.pi / 6, True, True, np.pi / 6)
    gmsh.model.mesh.createGeometry()
    surfs = gmsh.model.getEntities(2)
    if not surfs:
        raise CadImportError(f"no surfaces recovered from {path}")
    loop = gmsh.model.geo.addSurfaceLoop([t for _, t in surfs])
    vol = gmsh.model.geo.addVolume([loop])
    gmsh.model.geo.synchronize()
    return [(3, vol)]


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


def _top_level(gmsh):
    """Top-level OCC entities: solids if there are any, else free surfaces."""
    occ = gmsh.model.occ
    return occ.getEntities(3) or occ.getEntities(2) or occ.getEntities(1)


def export_shapes(path: str, gmsh, dim_tags=None) -> str:
    """
    Write current OCC entities to STEP/IGES/BREP/STL by extension.

    The model is held in metres, but OpenCASCADE stamps STEP and IGES with a
    millimetre unit and writes the raw coordinates, so a 20 mm part would be
    written as ``2.0E-02`` under a ``SI_UNIT(.MILLI.,.METRE.)`` header -- a
    file that is internally inconsistent and comes back a thousand times too
    small in any CAD system, this one included.  Scaling to millimetres before
    the write and back afterwards makes the numbers agree with the declared
    unit.  BREP and STL carry no unit and are written as-is (metres for BREP,
    the mesher's own coordinates for STL).
    """
    gmsh.model.occ.synchronize()
    fmt = detect_format(path)
    if fmt == "unknown":
        raise CadImportError(f"cannot infer export format from {path!r}")
    if fmt == "stl":
        gmsh.model.mesh.generate(2)
    scaled = []
    if fmt in ("step", "iges"):
        scaled = _top_level(gmsh)
        if scaled:
            gmsh.model.occ.dilate(scaled, 0, 0, 0, 1e3, 1e3, 1e3)
            gmsh.model.occ.synchronize()
    try:
        gmsh.write(path)
    finally:
        if scaled:
            gmsh.model.occ.dilate(scaled, 0, 0, 0, 1e-3, 1e-3, 1e-3)
            gmsh.model.occ.synchronize()
    log.info("exported geometry -> %s", path)
    return path


# --------------------------------------------------------------------------
# Lightweight STL reader (no CAD kernel needed) + bounds probe
# --------------------------------------------------------------------------


def read_stl(path: str) -> Tuple[np.ndarray, np.ndarray]:
    """Return ``(vertices[N,3], triangles[M,3])`` from a binary or ASCII STL."""
    with open(path, "rb") as fh:
        head = fh.read(84)
        if len(head) < 84:
            raise CadImportError(f"truncated STL: {path}")
        n_tri = struct.unpack("<I", head[80:84])[0]
        rest = fh.read()
    is_binary = len(rest) == n_tri * 50 and n_tri > 0
    if is_binary:
        tris = np.frombuffer(rest, dtype=np.uint8).reshape(n_tri, 50)
        verts = np.frombuffer(tris[:, 12:48].tobytes(),
                              dtype="<f4").reshape(n_tri, 3, 3).astype(float)
    else:
        verts_list = []
        with open(path, "r", errors="ignore") as fh:
            cur = []
            for line in fh:
                s = line.strip().split()
                if s and s[0] == "vertex":
                    cur.append([float(x) for x in s[1:4]])
                    if len(cur) == 3:
                        verts_list.append(cur)
                        cur = []
        if not verts_list:
            raise CadImportError(f"no triangles found in {path}")
        verts = np.asarray(verts_list, float)
    flat = verts.reshape(-1, 3)
    uniq, inv = np.unique(np.round(flat, 12), axis=0, return_inverse=True)
    return uniq, inv.reshape(-1, 3)


# Bounded so a session that browses many files cannot grow without limit.
_BOUNDS_CACHE: "OrderedDict[tuple, Tuple[tuple, tuple]]" = OrderedDict()
_BOUNDS_LIMIT = 4000


def _bounds_put(key, value):
    _BOUNDS_CACHE.pop(key, None)
    _BOUNDS_CACHE[key] = value
    while len(_BOUNDS_CACHE) > _BOUNDS_LIMIT:
        _BOUNDS_CACHE.popitem(last=False)


def _cache_key(path: str, scale_to_m: float, unit: Optional[str]) -> tuple:
    try:
        st = os.stat(path)
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:                                       # pragma: no cover
        stamp = (0, 0)
    return (os.path.abspath(path), stamp, float(scale_to_m), unit or "")


def quick_bounds(path: str, scale_to_m: float = 1.0,
                 unit: Optional[str] = None) -> Tuple[tuple, tuple]:
    """
    Bounding box of a CAD file.

    Cached on (path, mtime, size, scale, unit): the bounding box is consulted
    on every model refresh, and re-reading a 50 MB assembly each time is the
    difference between a workspace that responds and one that appears frozen.
    """
    key = _cache_key(path, scale_to_m, unit)
    hit = _BOUNDS_CACHE.get(key)
    if hit is not None:
        return hit
    fmt = detect_format(path)
    if fmt == "stl":
        v, _ = read_stl(path)
        u = (unit or "").strip().lower()
        sc = scale_to_m * UNIT_SCALE.get(u if u and u != "auto" else "mm", 1e-3)
        out = (tuple(v.min(0) * sc), tuple(v.max(0) * sc))
        _bounds_put(key, out)
        return out
    from .kernel import GmshSession, available
    if not available():
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    with GmshSession("bbox") as gmsh:
        dts = import_into_occ(path, gmsh, scale_to_m=scale_to_m, unit=unit)
        out = tight_bounds(gmsh, dts)
    _bounds_put(key, out)
    return out


def tight_bounds(gmsh, dim_tags) -> Tuple[tuple, tuple]:
    """
    The real extent of what is in the model, not OpenCASCADE's loose box.

    ``getBoundingBox`` builds its answer from the control points of the
    underlying surfaces, and the control polygon of a circle drawn as three
    rational arcs reaches twice the radius. A 10 mm rod therefore reports a
    30 mm box -- the camera frames empty space, the ground grid is drawn for a
    model twice the size, and the automatic mesh seed is derived from a
    diagonal that does not exist. A coarse surface mesh gives points that are
    genuinely on the geometry, so the extent it reports is the real one; the
    CAD box stays as the fallback for geometry too dirty to mesh at all.
    """
    out = tight_bounds_each(gmsh, dim_tags)
    lo = np.min([np.asarray(a) for a, _ in out], axis=0)
    hi = np.max([np.asarray(b) for _, b in out], axis=0)
    return tuple(lo), tuple(hi)


def tight_bounds_each(gmsh, dim_tags, harvest=None,
                      budget: int = 250_000) -> List[Tuple[tuple, tuple]]:
    """
    The real extent of every entity, from a single surface mesh.

    Meshing once and asking each body for its own nodes is what keeps a
    200-part assembly to one pass instead of two hundred.

    ``harvest`` is an optional ``callable(gmsh, dim_tags)`` run while that mesh
    is still in the session. The viewport wants a surface mesh of exactly this
    file, and building a second one is the expensive half of importing a NURBS
    assembly — so the caller is offered the one that already exists. When a
    harvester is given the mesh is generated at display quality, which is
    finer than bounds alone would need.
    """
    from .kernel import fit_mesh_size, prune_to_bodies, steady_size_options

    cad = [np.array(gmsh.model.getBoundingBox(d, t)) for d, t in dim_tags]
    fallback = [(tuple(b[:3]), tuple(b[3:])) for b in cad]
    try:
        allbb = np.array(cad)
        diag = float(np.linalg.norm(allbb[:, 3:].max(0)
                                    - allbb[:, :3].min(0))) or 1.0
        # Only the bodies asked about get meshed. Free presentation faces in
        # a STEP export can be orders of magnitude larger than the parts, and
        # meshing them at the assembly's element size is unbounded work for
        # geometry nobody asked about.
        prune_to_bodies(gmsh, dim_tags)
        if harvest is not None:
            from ..gui.tessellate import display_mesh_options
            h = fit_mesh_size(gmsh, diag / 22.0)
            display_mesh_options(gmsh, h)
        else:
            h = fit_mesh_size(gmsh, diag / 12.0, budget=budget)
            gmsh.option.setNumber("Mesh.MeshSizeMax", h)
            gmsh.option.setNumber("Mesh.MeshSizeMin", h / 33.0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 14)
            steady_size_options(gmsh)
        gmsh.model.mesh.generate(2)
        if harvest is not None:
            try:
                harvest(gmsh, dim_tags)
            except Exception as exc:                        # pragma: no cover
                log.debug("display harvest skipped: %s", exc)
    except Exception as exc:                                # pragma: no cover
        log.debug("tight bounds fell back to the CAD box: %s", exc)
        return fallback

    out: List[Tuple[tuple, tuple]] = []
    for k, (d, t) in enumerate(dim_tags):
        try:
            _, coords, _ = gmsh.model.mesh.getNodes(d, t, includeBoundary=True,
                                                    returnParametricCoord=False)
            pts = np.asarray(coords, float).reshape(-1, 3)
            if len(pts) < 4:
                raise ValueError("too few nodes")
            out.append((tuple(pts.min(0)), tuple(pts.max(0))))
        except Exception:
            out.append(fallback[k])
    return out


def probe(path: str, unit: Optional[str] = None,
          scale_to_m: float = 1.0, harvest=None) -> dict:
    """
    Everything the import needs to know, from **one** read of the file.

    Inspecting and listing the bodies were still two separate reads of the
    file, and — worse — two separate surface meshes, because each of them
    wanted tight extents. On a NURBS assembly that is seconds each, twice,
    before a single body has been added to the model. One session now answers
    both.
    """
    fmt = detect_format(path)
    if fmt == "dxf":
        info = inspect(path, unit)
        info["bodyList"] = []
        return info
    decl = declared_unit(path)
    applied = (unit or "").strip().lower()
    if applied in ("", "auto"):
        applied = decl or ("m" if fmt == "brep" else "mm")
    info = {"format": fmt, "declaredUnit": decl, "appliedUnit": applied,
            "solids": 0, "surfaces": 0, "bodies": 0, "bbox": None,
            "error": "", "bodyList": []}
    try:
        from .kernel import GmshSession, available
        if not available():
            info["error"] = "no CAD kernel"
            return info
        base = _cache_key(path, scale_to_m, unit)
        with GmshSession("probe") as gmsh:
            dts = import_into_occ(path, gmsh, scale_to_m=scale_to_m, unit=unit)
            # Count from the model, not from the returned top-level shapes: a
            # solid's own faces are children and would read as zero surfaces.
            info["solids"] = len(gmsh.model.getEntities(3))
            info["surfaces"] = len(gmsh.model.getEntities(2))
            info["bodies"] = len(dts)
            dts = sorted(dts, key=lambda dt: dt[1])
            meta = []
            for dim, tag in dts:
                try:
                    name = gmsh.model.getEntityName(dim, tag) or ""
                except Exception:                           # pragma: no cover
                    name = ""
                try:
                    mass = float(gmsh.model.occ.getMass(dim, tag))
                except Exception:                           # pragma: no cover
                    mass = 0.0
                meta.append((dim, name, mass))
            boxes = tight_bounds_each(gmsh, dts, harvest=harvest)
            lo = np.min([b[0] for b in boxes], axis=0) if boxes else (0, 0, 0)
            hi = np.max([b[1] for b in boxes], axis=0) if boxes else (0, 0, 0)
            info["bbox"] = [list(map(float, lo)), list(map(float, hi))]
            for i, (blo, bhi) in enumerate(boxes):
                _bounds_put(base + (i,), (blo, bhi))
                dim, name, mass = meta[i]
                info["bodyList"].append({
                    "index": i, "dim": int(dim),
                    "name": name.split("/")[-1],
                    "bbox": [list(blo), list(bhi)],
                    "size": [float(bhi[k] - blo[k]) for k in range(3)],
                    "volume": mass if dim == 3 else 0.0,
                    "area": mass if dim == 2 else 0.0,
                })
    except Exception as exc:
        info["error"] = str(exc)
        info["bodyList"] = []
    return info


def list_bodies(path: str, unit: Optional[str] = None,
                scale_to_m: float = 1.0) -> List[dict]:
    """
    The separate bodies a CAD file holds, in the order they import.

    An assembly is a list of parts, and a model wants them as separate objects
    -- one to make PEC, one to make substrate, one to delete. This is what the
    import dialog offers and what the importer indexes into.
    """
    from .kernel import GmshSession, available
    if not available():
        return []
    out: List[dict] = []
    base = _cache_key(path, scale_to_m, unit)
    with GmshSession("bodies") as gmsh:
        dts = import_into_occ(path, gmsh, scale_to_m=scale_to_m, unit=unit)
        dts = sorted(dts, key=lambda dt: dt[1])
        meta = []
        for dim, tag in dts:
            try:
                name = gmsh.model.getEntityName(dim, tag) or ""
            except Exception:                               # pragma: no cover
                name = ""
            try:
                mass = float(gmsh.model.occ.getMass(dim, tag))
            except Exception:                               # pragma: no cover
                mass = 0.0
            meta.append((dim, name, mass))
        # the bodies' real extents, from one surface mesh, cached for the
        # import that follows
        for i, (lo, hi) in enumerate(tight_bounds_each(gmsh, dts)):
            _bounds_put(base + (i,), (lo, hi))
            dim, name, mass = meta[i]
            out.append({
                "index": i, "dim": int(dim),
                "name": name.split("/")[-1],
                "bbox": [list(lo), list(hi)],
                "size": [float(hi[k] - lo[k]) for k in range(3)],
                "volume": mass if dim == 3 else 0.0,
                "area": mass if dim == 2 else 0.0,
            })
    return out


def body_bounds(path: str, body: int, scale_to_m: float = 1.0,
                unit: Optional[str] = None) -> Tuple[tuple, tuple]:
    """
    Bounding box of one body of a CAD file.

    Every body of a file is measured in **one** import and the whole set is
    cached. Reading a 200-part assembly once per part is what made a large
    import take minutes and hold the file's geometry in memory 200 times over.
    """
    key = _cache_key(path, scale_to_m, unit) + (int(body),)
    hit = _BOUNDS_CACHE.get(key)
    if hit is not None:
        return hit
    from .kernel import GmshSession, available
    if not available():
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    with GmshSession("bbox1") as gmsh:
        dts = sorted(import_into_occ(path, gmsh, scale_to_m=scale_to_m,
                                     unit=unit), key=lambda dt: dt[1])
        base = _cache_key(path, scale_to_m, unit)
        for i, bb in enumerate(tight_bounds_each(gmsh, dts)):
            _bounds_put(base + (i,), bb)
    return _BOUNDS_CACHE.get(key, ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))


def inspect(path: str, unit: Optional[str] = None) -> dict:
    """
    What a CAD file contains, without adding it to a model.

    Used to tell the user what was actually imported -- solid count, extent and
    the unit that was applied -- so a silent scale error cannot go unnoticed.
    """
    fmt = detect_format(path)
    if fmt == "dxf":
        from .dxf import summary as _dxf_summary
        d = _dxf_summary(path, unit)
        if d.get("error"):
            return {"format": "dxf", "declaredUnit": "", "appliedUnit": "",
                    "solids": 0, "surfaces": 0, "bodies": 0, "bbox": None,
                    "error": d["error"]}
        return {"format": "dxf", "declaredUnit": d["declaredUnit"],
                "appliedUnit": d["appliedUnit"], "solids": 0,
                "surfaces": d["closed"], "bodies": d["closed"],
                "entities": d["entities"], "layers": d["layers"],
                "warnings": d.get("warnings", []), "joinedChains": d.get("joinedChains", 0),
                "bbox": d["bbox"], "error": ""}
    decl = declared_unit(path)
    applied = (unit or "").strip().lower()
    if applied in ("", "auto"):
        applied = decl or ("m" if fmt == "brep" else "mm")
    info = {"format": fmt, "declaredUnit": decl, "appliedUnit": applied,
            "solids": 0, "surfaces": 0, "bodies": 0, "bbox": None, "error": ""}
    try:
        from .kernel import GmshSession, available
        if not available():
            info["error"] = "no CAD kernel"
            return info
        with GmshSession("inspect") as gmsh:
            dts = import_into_occ(path, gmsh, unit=unit)
            # Count from the model, not from the returned top-level shapes:
            # a solid's own faces are children and would otherwise read as
            # zero surfaces.
            info["solids"] = len(gmsh.model.getEntities(3))
            info["surfaces"] = len(gmsh.model.getEntities(2))
            info["bodies"] = len(dts)
            lo, hi = tight_bounds(gmsh, dts)
            info["bbox"] = [list(lo), list(hi)]
    except Exception as exc:
        info["error"] = str(exc)
    return info


__all__ = ["import_into_occ", "export_shapes", "read_stl", "quick_bounds",
           "tight_bounds", "tight_bounds_each", "list_bodies", "probe",
           "body_bounds",
           "detect_format", "declared_unit", "inspect", "CadImportError",
           "SUPPORTED", "UNIT_SCALE"]
