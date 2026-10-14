"""
Mesh generation.

Two interchangeable backends
----------------------------
``occ``      OpenCASCADE geometry + gmsh Delaunay/HXT tetrahedralisation.
             Handles arbitrary CSG, imported STEP/IGES and curved surfaces.
``builtin``  Dependency-free structured tetrahedralisation of the model
             bounding box (6 tets per hexahedron) with material classification
             by analytic point membership.  Always available; used for
             regression tests, for CI, and as a fallback.

Both produce the same :class:`~aether.mesh.tetmesh.TetMesh`, so nothing
downstream cares which one ran.

Element sizing follows the same rule HFSS's initial mesh uses: a target of
``lambda_min / N`` per material region, tightened by curvature and by any
user-supplied maximum.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..core.constants import c0
from ..core.logging import get_logger, timed
from .tetmesh import LOCAL_FACES, TetMesh

log = get_logger("mesh.generator")


# --------------------------------------------------------------------------
# sizing
# --------------------------------------------------------------------------


def target_size(design, freq: float) -> Tuple[float, Dict[str, float]]:
    """Global and per-solid target element sizes [m]."""
    cfg = design.config.mesh
    # Bodies with no readable geometry report a degenerate box at the origin;
    # including those stretches the model diagonal to wherever the origin is
    # and skews every size derived from it.
    boxes = []
    for s in design.solids:
        if getattr(s.shape, "_cad_unreadable", ""):
            continue
        try:
            a, b = s.shape.bounds()
        except Exception:
            continue
        if np.all(np.isfinite(a)) and np.all(np.isfinite(b)) \
                and np.all(np.asarray(b) - np.asarray(a) > 0):
            boxes.append((np.asarray(a, float), np.asarray(b, float)))
    if boxes:
        lo = np.min([b[0] for b in boxes], axis=0)
        hi = np.max([b[1] for b in boxes], axis=0)
    else:
        lo, hi = design.bounding_box()
    diag = float(np.linalg.norm(np.asarray(hi) - np.asarray(lo))) or 1.0

    # A body that is not solved inside -- a PEC block, a "do not solve"
    # import -- contributes no unknowns, so its refractive index must not set
    # the element size. A good conductor has |n| in the thousands at RF, and
    # letting it into this minimum is how an initial mesh ends up asking for
    # 80 nm elements across a 60 mm board and never returns.
    solved = [s for s in design.solids
              if s.solve_inside and not s.material.is_pec]

    per: Dict[str, float] = {}
    lam_min = math.inf
    for s in design.solids:
        m = s.material
        n = abs(m.refractive_index(freq))
        n = max(n.real if isinstance(n, complex) else n, 1.0)
        # The wavelength inside a good conductor is microscopic and is not
        # what an initial mesh resolves -- the field there is a skin-depth
        # boundary layer, handled by the impedance condition or by adaptive
        # refinement, not by filling the body with elements. The index used
        # for sizing is capped so one metal region cannot set an element
        # size the whole model then has to live with.
        n = min(n, INDEX_CAP)
        lam = c0 / (freq * n)
        per[s.name] = lam * cfg.lambda_refinement
        if s in solved:
            lam_min = min(lam_min, lam)
    if not np.isfinite(lam_min):
        lam_min = c0 / freq

    h = lam_min * cfg.lambda_refinement
    h = min(h, diag / 3.0)
    if cfg.max_element_size:
        h = min(h, cfg.max_element_size)
        per = {k: min(v, cfg.max_element_size) for k, v in per.items()}

    # An initial mesh must come back. A material with a very large refractive
    # index -- a conductor the model does solve inside, an epsilon typed in
    # the wrong unit -- can ask for an element size that would fill the model
    # with more tetrahedra than the machine has memory for, and gmsh will sit
    # there for hours trying. The request is honoured up to a budget, then
    # coarsened, and the coarsening is said out loud so it is a decision and
    # not a silent difference between what was asked for and what was meshed.
    box = np.maximum(np.asarray(hi) - np.asarray(lo), 0.0)
    volume = float(np.prod(box[box > 0])) if np.any(box > 0) else diag ** 3
    want = _budget_size(volume, h)
    if want > h * 1.0001:
        log.warning("initial mesh size raised from %.4g m to %.4g m: the "
                    "requested size needs more than %d elements for this "
                    "model (check materials and units on the solved bodies)",
                    h, want, ELEMENT_BUDGET)
        h = want
    per = {k: max(v, h / 8.0) for k, v in per.items()}
    hmin = cfg.min_element_size or h / 50.0
    return max(h, hmin), per


#: Ceiling on the initial mesh, in tetrahedra. Adaptive passes refine from
#: there; an initial mesh bigger than this is a mistake, not a fine model.
ELEMENT_BUDGET = 2_000_000

#: Largest refractive index that may set the element size (eps_r ~ 900).
#: Above this the material is a conductor, not a dielectric to resolve.
INDEX_CAP = 30.0


def _budget_size(volume: float, h: float) -> float:
    """The smallest size at or above ``h`` that stays inside the budget."""
    if h <= 0 or volume <= 0:
        return h
    # ~6 tetrahedra per cube of side h, which is the structured-fill count and
    # close enough for a guard.
    est = 6.0 * volume / (h ** 3)
    if est <= ELEMENT_BUDGET:
        return h
    return float((6.0 * volume / ELEMENT_BUDGET) ** (1.0 / 3.0))


# --------------------------------------------------------------------------
# OCC / gmsh backend
# --------------------------------------------------------------------------


def _has_small_sheet(design, h: float) -> bool:
    """True when some sheet's largest extent is below 1.5 element sizes."""
    for sh in getattr(design, "sheets", []):
        try:
            lo, hi = sh.shape.bounds()
            if float(np.max(np.asarray(hi) - np.asarray(lo))) < 1.5 * h:
                return True
        except Exception:                                   # pragma: no cover
            continue
    return False


def generate_occ(design, freq: float, size: Optional[float] = None,
                 write_msh: Optional[str] = None,
                 size_field: Optional[str] = None) -> TetMesh:
    from ..geometry.kernel import Assembly, GmshSession

    h, per = target_size(design, freq)
    if size:
        h = float(size)
        per = {k: min(v, h) for k, v in per.items()}
    cfg = design.config.mesh

    with GmshSession(design.name) as gmsh:
        asm = Assembly().build(gmsh, design.solids, design.sheets)
        if asm.skipped and not asm.solid_volumes:
            first = next(iter(asm.skipped.items()))
            raise RuntimeError(
                "no body in this design can be built, so there is nothing to "
                f"mesh. {len(asm.skipped)} body/bodies were skipped, e.g. "
                f"{first[0]!r}: {first[1]} "
                "Use Modeler > Repair Imported Bodies to point the model at a "
                "STEP export of the same parts.")

        region_names: Dict[int, str] = {}
        for i, (nm, vols) in enumerate(sorted(asm.solid_volumes.items()), start=1):
            if not vols:
                continue
            gmsh.model.addPhysicalGroup(3, vols, i)
            gmsh.model.setPhysicalName(3, i, nm)
            region_names[i] = nm

        sheet_groups: Dict[int, str] = {}
        base = 1000
        for j, (nm, surfs) in enumerate(sorted(asm.sheet_surfaces.items())):
            if not surfs:
                continue
            gmsh.model.addPhysicalGroup(2, surfs, base + j)
            gmsh.model.setPhysicalName(2, base + j, nm)
            sheet_groups[base + j] = nm

        gmsh.option.setNumber("Mesh.MeshSizeMax", h)
        gmsh.model.mesh.setSize(gmsh.model.getEntities(0), h)
        gmsh.option.setNumber("Mesh.MeshSizeMin", cfg.min_element_size or h / 100.0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature",
                              max(int(360.0 / max(cfg.curvature_angle_deg, 1.0)), 0))
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
        gmsh.option.setNumber("Mesh.Algorithm", cfg.algorithm2d)
        gmsh.option.setNumber("Mesh.Algorithm3D", cfg.algorithm3d)
        gmsh.option.setNumber("Mesh.Optimize", 1 if cfg.optimize else 0)
        gmsh.option.setNumber("Mesh.OptimizeNetgen", 0)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)

        # per-volume refinement for high-permittivity regions
        fields = []
        if size_field:
            gmsh.merge(size_field)
            vid = gmsh.model.mesh.field.add("PostView")
            gmsh.model.mesh.field.setNumber(vid, "ViewIndex", 0)
            fields.append(vid)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        for nm, vols in asm.solid_volumes.items():
            hs = per.get(nm)
            if not hs or hs >= h * 0.999 or not vols:
                continue
            fid = gmsh.model.mesh.field.add("Constant")
            gmsh.model.mesh.field.setNumbers(fid, "VolumesList", vols)
            gmsh.model.mesh.field.setNumber(fid, "VIn", hs)
            gmsh.model.mesh.field.setNumber(fid, "VOut", h)
            fields.append(fid)
        # user mesh operations: "these objects / these faces, no element
        # longer than this". They act on the initial mesh, before the adaptive
        # passes get their say.
        for op in getattr(design, "mesh_ops", []):
            if not getattr(op, "enabled", True) or op.max_length <= 0:
                continue
            vols: List[int] = []
            surfs: List[int] = []
            for nm in op.objects:
                vols += list(asm.solid_volumes.get(nm, []))
                # a sheet is a surface entity: handing its tag to the volume
                # list names a 3-D entity that does not exist and aborts gmsh
                surfs += list(getattr(asm, "sheet_surfaces", {}).get(nm, []))
            if op.selector is not None:
                surfs += _surfaces_for(gmsh, op.selector)
            if not vols and not surfs:
                log.warning("mesh operation %r matched nothing", op.name)
                continue
            fid = gmsh.model.mesh.field.add("Constant")
            if vols:
                gmsh.model.mesh.field.setNumbers(fid, "VolumesList", vols)
            if surfs:
                gmsh.model.mesh.field.setNumbers(fid, "SurfacesList", surfs)
            gmsh.model.mesh.field.setNumber(fid, "IncludeBoundary", 1)
            gmsh.model.mesh.field.setNumber(fid, "VIn", float(op.max_length))
            gmsh.model.mesh.field.setNumber(fid, "VOut", h)
            fields.append(fid)
            if surfs:
                # A face refinement includes the face's own rim, and those
                # curves are shared with the neighbouring faces. With gmsh's
                # default "extend size from boundary" that fine size then
                # propagates through the whole body and the refinement stops
                # being local -- the opposite face comes back just as fine.
                gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            log.info("mesh operation %-12s: %d volume(s), %d surface(s) "
                     "at h <= %.4g m", op.name, len(vols), len(surfs),
                     op.max_length)

        if fields:
            mid = gmsh.model.mesh.field.add("Min")
            gmsh.model.mesh.field.setNumbers(mid, "FieldsList", fields)
            gmsh.model.mesh.field.setAsBackgroundMesh(mid)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)

        with timed(log, f"tetrahedral meshing (h={h:.4g} m)"):
            gmsh.model.mesh.generate(3)
            if cfg.optimize:
                if _has_small_sheet(design, h):
                    # Netgen's optimiser segfaults (taking the whole process
                    # with it) on a sheet much smaller than the element size
                    # -- a lumped-port gap, say. gmsh's own optimiser is safe.
                    log.info("small port/sheet geometry: using the default "
                             "mesh optimiser instead of Netgen")
                    gmsh.model.mesh.optimize("", niter=2)
                else:
                    gmsh.model.mesh.optimize("Netgen", niter=2)

        mesh = _harvest(gmsh, region_names, sheet_groups)
        mesh.skipped_bodies = dict(asm.skipped)
        if write_msh:
            gmsh.write(write_msh)
    log.info("mesh: %d nodes / %d tets / %d edges",
             mesh.n_nodes, mesh.n_tets, mesh.n_edges)
    return mesh


def _harvest(gmsh, region_names: Dict[int, str],
             sheet_groups: Dict[int, str]) -> TetMesh:
    ntags, ncoords, _ = gmsh.model.mesh.getNodes()
    ntags = np.asarray(ntags, dtype=np.int64)
    coords = np.asarray(ncoords, dtype=np.float64).reshape(-1, 3)
    order = np.argsort(ntags)
    ntags, coords = ntags[order], coords[order]
    lut = -np.ones(int(ntags.max()) + 1, dtype=np.int64)
    lut[ntags] = np.arange(len(ntags))

    tets: List[np.ndarray] = []
    regions: List[np.ndarray] = []
    for pid, nm in region_names.items():
        ents = gmsh.model.getEntitiesForPhysicalGroup(3, pid)
        for ent in ents:
            etypes, _, enodes = gmsh.model.mesh.getElements(3, int(ent))
            for et, en in zip(etypes, enodes):
                if et != 4:                       # 4 = 4-node tetrahedron
                    continue
                cells = lut[np.asarray(en, dtype=np.int64).reshape(-1, 4)]
                tets.append(cells)
                regions.append(np.full(len(cells), pid, dtype=np.int32))
    if not tets:
        raise RuntimeError("mesher produced no tetrahedra -- check geometry "
                           "(non-manifold or zero-volume solids?)")
    tets_a = np.vstack(tets)
    reg_a = np.concatenate(regions)

    # internal sheet triangles (perfect-E sheets, lumped ports on sheets)
    tris: List[np.ndarray] = []
    tags: List[np.ndarray] = []
    tag_names: Dict[int, str] = {}
    for pid, nm in sheet_groups.items():
        for ent in gmsh.model.getEntitiesForPhysicalGroup(2, pid):
            etypes, _, enodes = gmsh.model.mesh.getElements(2, int(ent))
            for et, en in zip(etypes, enodes):
                if et != 2:                       # 2 = 3-node triangle
                    continue
                t = lut[np.asarray(en, dtype=np.int64).reshape(-1, 3)]
                tris.append(t)
                tags.append(np.full(len(t), pid, dtype=np.int32))
        tag_names[pid] = nm

    surf = np.vstack(tris) if tris else np.zeros((0, 3), dtype=np.int64)
    stag = np.concatenate(tags) if tags else np.zeros(0, dtype=np.int32)

    used = np.unique(tets_a)
    if len(used) < len(coords):                    # drop orphan nodes
        remap = -np.ones(len(coords), dtype=np.int64)
        remap[used] = np.arange(len(used))
        coords = coords[used]
        tets_a = remap[tets_a]
        if len(surf):
            keep = np.all(remap[surf] >= 0, axis=1)
            surf, stag = remap[surf[keep]], stag[keep]

    return TetMesh(coords, tets_a, reg_a, region_names, surf, stag, tag_names)


# --------------------------------------------------------------------------
# built-in structured backend
# --------------------------------------------------------------------------

# Freudenthal 6-tet subdivision of the unit cube (consistent, conforming)
_CUBE_TETS = np.array([
    [0, 1, 3, 7], [0, 1, 7, 5], [0, 5, 7, 4],
    [0, 3, 2, 7], [0, 2, 6, 7], [0, 6, 4, 7],
], dtype=np.int64)


def generate_builtin(design, freq: float, size: Optional[float] = None,
                     n: Optional[Sequence[int]] = None,
                     pad: float = 0.0, size_field: Optional[str] = None
                     ) -> TetMesh:
    """
    Structured tetrahedral mesh of the model bounding box.

    Cells are classified by analytic point membership against the solid list,
    *later solids winning* (same override rule as the OCC assembly).  Cells
    inside no solid and inside no background are discarded.
    """
    from ..geometry.implicit import contains

    lo, hi = design.bounding_box()
    lo = np.asarray(lo, float) - pad
    hi = np.asarray(hi, float) + pad
    span = hi - lo
    h, _ = target_size(design, freq)
    if size:
        h = float(size)
    if n is None:
        n = np.maximum(np.ceil(span / h).astype(int), 1)
    n = np.asarray(n, dtype=int)

    xs = [np.linspace(lo[i], hi[i], n[i] + 1) for i in range(3)]
    X, Y, Z = np.meshgrid(*xs, indexing="ij")
    nodes = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    nx, ny, nz = n + 1

    def nid(i, j, k):
        return (i * ny + j) * nz + k

    I, J, K = np.meshgrid(np.arange(n[0]), np.arange(n[1]), np.arange(n[2]),
                          indexing="ij")
    I, J, K = I.ravel(), J.ravel(), K.ravel()
    corner = np.stack([
        nid(I, J, K), nid(I, J, K + 1), nid(I, J + 1, K), nid(I, J + 1, K + 1),
        nid(I + 1, J, K), nid(I + 1, J, K + 1), nid(I + 1, J + 1, K),
        nid(I + 1, J + 1, K + 1)], axis=1)                     # (C,8)
    tets = corner[:, _CUBE_TETS.ravel()].reshape(-1, 4)

    cent = nodes[tets].mean(axis=1)
    region = np.zeros(len(tets), dtype=np.int32)
    region_names: Dict[int, str] = {}
    for i, sol in enumerate(design.solids, start=1):
        region_names[i] = sol.name
        try:
            m = contains(sol.shape, cent)
        except NotImplementedError as exc:
            raise RuntimeError(f"Builtin mesher cannot classify {sol.name!r}; use the OCC backend") from exc
        region[m] = i
    keep = region > 0
    if not np.any(keep):
        raise RuntimeError("structured mesh: no cell fell inside any solid; "
                           "reduce the element size")
    tets, region = tets[keep], region[keep]

    used = np.unique(tets)
    remap = -np.ones(len(nodes), dtype=np.int64)
    remap[used] = np.arange(len(used))
    mesh = TetMesh(nodes[used], remap[tets], region, region_names)
    log.info("builtin mesh: grid %s -> %d nodes / %d tets",
             tuple(n), mesh.n_nodes, mesh.n_tets)
    return mesh


# --------------------------------------------------------------------------
# dispatch + boundary tagging
# --------------------------------------------------------------------------


def generate(design, freq: float, backend: str = "auto", **kw) -> TetMesh:
    from ..geometry.kernel import available
    from ..geometry.primitives import ImportedShape

    from ..parametric import walk
    needs_occ = any(isinstance(sh, ImportedShape) for s in design.solids+design.sheets for sh in walk(s.shape))
    if backend == "auto":
        backend = "occ" if available() else "builtin"
    if backend == "builtin" and needs_occ:
        raise RuntimeError("imported CAD requires the OCC backend (install gmsh)")
    if backend == "occ":
        mesh = generate_occ(design, freq, **kw)
    elif backend == "builtin":
        mesh = generate_builtin(design, freq, **kw)
    else:
        raise ValueError(f"unknown mesh backend {backend!r}")
    mesh = drop_pec_regions(mesh, design)
    tag_boundaries(mesh, design)
    return mesh


def drop_pec_regions(mesh: TetMesh, design) -> TetMesh:
    """
    Remove elements belonging to PEC solids (and to bodies flagged
    ``solve_inside=False``) from the solution volume.

    The faces exposed by the removal become model boundary faces and pick up
    the default perfect-E condition -- exactly the behaviour of HFSS's
    "do not solve inside" flag, and the reason a metal block never costs any
    unknowns.
    """
    skip = {s.name for s in design.solids
            if s.material.is_pec or not s.solve_inside}
    if not skip:
        return mesh
    drop_ids = [rid for rid, nm in mesh.region_names.items() if nm in skip]
    if not drop_ids:
        return mesh
    keep = ~np.isin(mesh.tet_region, drop_ids)
    if not np.any(keep):
        raise RuntimeError("every element belongs to a PEC / non-solved body")
    tets = mesh.tets[keep]
    reg = mesh.tet_region[keep]
    used = np.unique(tets)
    remap = -np.ones(mesh.n_nodes, dtype=np.int64)
    remap[used] = np.arange(len(used))
    surf, stag = mesh.surf_tris, mesh.surf_tag
    if len(surf):
        ok = np.all(remap[surf] >= 0, axis=1)
        surf, stag = remap[surf[ok]], stag[ok]
    names = {k: v for k, v in mesh.region_names.items() if k not in drop_ids}
    log.info("excluded %d element(s) inside PEC / non-solved bodies (%s)",
             int((~keep).sum()), ", ".join(sorted(skip)))
    out = TetMesh(mesh.nodes[used], remap[tets], reg, names, surf, stag,
                  dict(mesh.tag_names), dict(mesh.skipped_bodies))
    # Nodes shared with a removed conductor: the faces made only of them are
    # the conductor's surface, not the outside of the air region.
    gone = np.zeros(mesh.n_nodes, bool)
    gone[np.unique(mesh.tets[~keep])] = True
    out.conductor_nodes = gone[used]
    return out


def boundary_triangle_data(mesh: TetMesh) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Boundary triangles of the volume mesh with centroids and outward normals."""
    bidx = mesh.boundary_face_index()
    tris = mesh.faces[bidx]
    p = mesh.nodes[tris]
    cen = p.mean(axis=1)
    nrm = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = nrm / np.maximum(ln, 1e-300)
    owner = mesh.face_to_tet()[bidx, 0]
    tc = mesh.centroids()[owner]
    flip = np.einsum("ij,ij->i", nrm, cen - tc) < 0
    nrm[flip] *= -1.0
    mesh.surf_owner_tet = owner
    mesh.surf_face_index = bidx
    cn = getattr(mesh, "conductor_nodes", None)
    mesh.surf_conductor = (cn[tris].all(axis=1) if cn is not None
                           else np.zeros(len(tris), bool))
    return tris, cen, nrm


def internal_sheet_data(mesh: TetMesh):
    """
    Triangles of zero-thickness sheets that lie *inside* the mesh.

    A patch, an iris, a thin ground plane or a resistive film is a surface the
    volume mesh conforms to but never bounds, so it never appears in
    ``boundary_faces``.  Those triangles are collected here from the sheet
    entities the mesher tagged, and are then eligible for boundary conditions
    exactly like outer faces -- which is what makes internal perfect-E sheets
    and impedance films work at all.
    """
    tris = getattr(mesh, "_sheet_tris", None)
    if tris is None or len(tris) == 0:
        return (np.zeros((0, 3), np.int64), np.zeros((0, 3)),
                np.zeros((0, 3)), np.zeros(0, np.int64))
    tris = np.sort(np.asarray(tris, np.int64), axis=1)
    bnd = set(map(tuple, mesh.boundary_faces))
    keep = np.array([tuple(t) not in bnd for t in tris], bool)
    tris = tris[keep]
    if len(tris) == 0:
        return (np.zeros((0, 3), np.int64), np.zeros((0, 3)),
                np.zeros((0, 3)), np.zeros(0, np.int64))
    p = mesh.nodes[tris]
    cen = p.mean(axis=1)
    nrm = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-300)
    from ..fem.ports import face_indices
    fid = face_indices(mesh, tris)
    owner = mesh.face_to_tet()[np.maximum(fid, 0), 0]
    return tris, cen, nrm, owner


def _surfaces_for(gmsh, selector) -> List[int]:
    """
    OCC surfaces a face selector picks out.

    The selector is geometric -- a point, a normal and an extent -- so it is
    applied to each surface's own centre of mass and normal there. That is the
    same test the mesh tagger uses on triangles, which is what keeps a mesh
    operation and a boundary assigned to the same picked face agreeing about
    which face they mean.
    """
    out: List[int] = []
    for dim, tag in gmsh.model.getEntities(2):
        try:
            com = np.asarray(gmsh.model.occ.getCenterOfMass(2, tag), float)
            uv = gmsh.model.getParametrization(2, tag, com.tolist())
            nrm = np.asarray(gmsh.model.getNormal(tag, uv), float)[:3]
        except Exception:                                   # pragma: no cover
            continue
        ln = float(np.linalg.norm(nrm))
        if ln < 1e-300:
            continue
        try:
            hit = bool(np.asarray(selector(com.reshape(1, 3),
                                           (nrm / ln).reshape(1, 3)))[0])
        except Exception:                                   # pragma: no cover
            continue
        if hit:
            out.append(int(tag))
    return out


def tag_boundaries(mesh: TetMesh, design) -> TetMesh:
    """
    Evaluate every boundary/port selector against the mesh surface and store
    the result on the mesh as ``mesh.bc_faces`` / ``mesh.port_faces``.

    Ports win over boundaries; among boundaries, later assignments and higher
    ``priority`` win, with PEC always dominating.
    """
    mesh._sheet_tris = mesh.surf_tris
    tris, cen, nrm = boundary_triangle_data(mesh)
    s_tris, s_cen, s_nrm, s_owner = internal_sheet_data(mesh)
    if len(s_tris):
        tris = np.vstack([tris, s_tris])
        cen = np.vstack([cen, s_cen])
        nrm = np.vstack([nrm, s_nrm])
        mesh.surf_owner_tet = np.concatenate([mesh.surf_owner_tet, s_owner])
        mesh.n_outer_faces = len(tris) - len(s_tris)
        log.info("%d internal sheet triangle(s) available for boundary "
                 "assignment", len(s_tris))
    else:
        mesh.n_outer_faces = len(tris)
    mesh.surf_tris = tris
    mesh.surf_normals = nrm
    mesh.surf_centroids = cen

    n_outer = mesh.n_outer_faces
    outer_mask = np.zeros(len(tris), bool)
    outer_mask[:n_outer] = True
    # "Outer" means the outside of the air region.  The surface of a PEC body
    # that was cut out of the solution volume is a boundary of the mesh too,
    # but a radiation or impedance condition assigned to "all outer faces"
    # must never land on antenna metal.
    conductor = np.zeros(len(tris), bool)
    conductor[:n_outer] = getattr(mesh, "surf_conductor",
                                  np.zeros(n_outer, bool))
    mesh.surf_is_conductor = conductor

    def _eval(sel):
        m = np.asarray(sel(cen, nrm), bool)
        if getattr(sel, "outer_only", False):
            m &= outer_mask & ~conductor
        return m

    port_faces: Dict[str, np.ndarray] = {}
    claimed = np.zeros(len(tris), bool)
    for p in design.ports:
        m = _eval(p.selector)
        if np.any(m & claimed):
            raise ValueError(f"port {p.name!r} overlaps another port on mesh triangles; assign separate port faces")
        port_faces[p.name] = np.nonzero(m)[0]
        claimed |= m

    bc_faces: Dict[str, np.ndarray] = {}
    owner = np.full(len(tris), -1, dtype=np.int64)
    order = sorted(range(len(design.boundaries)),
                   key=lambda i: (design.boundaries[i].priority,
                                  design.boundaries[i].btype == "pec", i))
    for i in order:
        b = design.boundaries[i]
        m = _eval(b.selector) & ~claimed
        owner[m] = i
    for i, b in enumerate(design.boundaries):
        bc_faces[b.name] = np.nonzero(owner == i)[0]

    mesh.port_faces = port_faces
    mesh.bc_faces = bc_faces
    mesh.bc_owner = owner
    unassigned = int(np.sum((owner < 0) & ~claimed & outer_mask))
    if unassigned:
        log.info("%d outer triangles carry no explicit BC "
                 "(the design default applies)", unassigned)
    for name, idx in port_faces.items():
        if len(idx) == 0:
            log.warning("port %r selected 0 triangles -- check its plane/window",
                        name)
        else:
            log.info("port %-12s : %5d triangles", name, len(idx))
    return mesh


__all__ = ["generate", "generate_occ", "generate_builtin", "tag_boundaries",
           "boundary_triangle_data", "target_size"]
