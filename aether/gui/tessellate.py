"""
Solid -> render-ready triangle buffers for the 3-D modeller viewport.

Two paths, same output:

* **OCC path** — the solid is built in OpenCASCADE and surface-meshed, so
  booleans, imported STEP bodies and curved faces are tessellated exactly as
  the solver will see them. What you look at *is* the model that gets meshed.
* **Analytic path** — parametric tessellation of the primitives, used when no
  CAD kernel is installed so the viewport still works.

The buffers are flat lists of floats/ints because they go straight into
WebGL vertex buffers on the other side of the JSON.
"""
from __future__ import annotations

import math
import os
from collections import OrderedDict
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..core.logging import get_logger
from ..geometry.kernel import ModelBuildError
from ..geometry.primitives import (Box, Cone, Cylinder, Polygon, Shape, Sphere,
                                   Torus)

log = get_logger("gui.tessellate")


def _pack(verts: np.ndarray, tris: np.ndarray,
          face_of: Optional[np.ndarray] = None) -> Dict:
    """
    Preserve topology and smooth shading within each geometric face.

    ``face_of`` gives the geometric face each triangle belongs to. It is what
    makes face picking possible: a ray hit is a triangle index, and the face
    index turns that into "the top of the patch" rather than "triangle 412".
    Each face also carries the reference point, normal and extent an assignment
    is later rebuilt from, so a boundary survives a re-tessellation.
    """
    # Degenerate triangles (the poles of a uv-sphere, a cone apex) have no
    # meaningful normal: they draw nothing and would each look like a face of
    # their own. Drop them before anything is derived from the normals.
    tri_v = verts[tris]
    a2 = np.linalg.norm(np.cross(tri_v[:, 1] - tri_v[:, 0],
                                 tri_v[:, 2] - tri_v[:, 0]), axis=1)
    keep = a2 > max(float(a2.max()) * 1e-9, 1e-300) if len(a2) else a2 > 0
    if not keep.all():
        tris = tris[keep]
        if face_of is not None:
            face_of = np.asarray(face_of)[keep]

    v = verts[tris].reshape(-1, 3)
    n = np.cross(v[1::3] - v[0::3], v[2::3] - v[0::3])
    area2 = np.linalg.norm(n, axis=1)
    ln = area2.reshape(-1, 1)
    n = n / np.maximum(ln, 1e-300)
    nrep = np.repeat(n, 3, axis=0)
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    out = {
        # np.round(...).tolist() rather than a Python comprehension: these are
        # millions of numbers on a real import, and the comprehension was a
        # measurable part of "the viewport takes forever to appear".
        "position": np.round(v.ravel(), 9).tolist(),
        "normal": np.round(nrep.ravel(), 6).tolist(),
        "edges": edges.ravel().astype(np.int32).tolist(),
        "edgeVerts": np.round(verts.ravel(), 9).tolist(),
        "count": int(len(v)),
    }
    if face_of is None:
        face_of = _cluster_faces(verts, tris, n)
    # Smooth within each geometric face, never across a box edge or cylinder cap.
    # Use (face, vertex) keys to keep sharp BREP face boundaries intact.
    keys=np.column_stack([np.repeat(face_of,3),tris.ravel()])
    _,inverse=np.unique(keys,axis=0,return_inverse=True)
    weighted=np.repeat(n*area2[:,None],3,axis=0)
    sums=np.zeros((int(inverse.max())+1,3)) if len(inverse) else np.empty((0,3))
    np.add.at(sums,inverse,weighted)
    if len(sums):sums/=np.maximum(np.linalg.norm(sums,axis=1,keepdims=True),1e-300)
    out["normal"]=np.round(sums[inverse],6).ravel().tolist()
    out["faceOf"] = np.asarray(face_of, np.int32).tolist()
    out["faces"] = _face_meta(verts, tris, n, area2 * 0.5, face_of)
    out["faceEdges"] = _face_edges(tris, face_of)
    if out["faceEdges"]:
        boundary_vertices = np.unique(
            np.asarray(out["faceEdges"], np.int64).reshape(-1, 3)[:, :2])
        out["snapPoints"] = verts[boundary_vertices].tolist()
    else:
        out["snapPoints"] = []
    out["snapKind"]="display vertex"
    return out


def _face_meta(verts, tris, tri_n, tri_area, face_of) -> List[Dict]:
    """
    Reference point, normal, extent and area of every face.

    Written as segmented reductions rather than one boolean mask per face: an
    imported STEP body routinely has thousands of faces and hundreds of
    thousands of triangles, and ``face_of == k`` inside a loop over faces is
    quadratic in exactly the case that matters.
    """
    n_face = int(face_of.max()) + 1 if len(face_of) else 0
    faces: List[Dict] = []
    if not n_face:
        return faces

    face_of = np.asarray(face_of, np.int64)
    tri_pts = verts[tris]                                   # (T, 3, 3)
    w = tri_area.astype(float)

    area = np.bincount(face_of, weights=w, minlength=n_face)
    cen = np.stack([np.bincount(face_of, weights=tri_pts[:, :, k].mean(1) * w,
                                minlength=n_face) for k in range(3)], axis=1)
    cen /= np.maximum(area, 1e-300)[:, None]
    nn = np.stack([np.bincount(face_of, weights=tri_n[:, k] * w,
                               minlength=n_face) for k in range(3)], axis=1)
    nl = np.linalg.norm(nn, axis=1, keepdims=True)
    # A face whose weighted normals cancel (a closed tube treated as one face)
    # keeps the normal of one of its triangles rather than a zero vector.
    first = np.zeros(n_face, np.int64)
    first[face_of[::-1]] = np.arange(len(face_of))[::-1]
    nn = np.where(nl > 1e-300, nn / np.maximum(nl, 1e-300), tri_n[first])

    flat = tris.ravel()
    rep = np.repeat(face_of, 3)
    lo = np.stack([_seg_reduce(np.minimum, rep, verts[flat, k], n_face,
                               np.inf) for k in range(3)], axis=1)
    hi = np.stack([_seg_reduce(np.maximum, rep, verts[flat, k], n_face,
                               -np.inf) for k in range(3)], axis=1)
    counts = np.bincount(face_of, minlength=n_face)
    # planar == every triangle normal agrees with the face normal
    dev = np.abs(np.einsum("ij,ij->i", tri_n, nn[face_of]))
    planar = _seg_reduce(np.minimum, face_of, dev, n_face, np.inf) > 0.999

    cen_r = np.round(cen, 9)
    nn_r = np.round(nn, 6)
    lo_r = np.round(lo, 9)
    hi_r = np.round(hi, 9)
    for k in range(n_face):
        if not counts[k]:
            faces.append({"area": 0.0, "point": [0, 0, 0], "normal": [0, 0, 1],
                          "lo": [0, 0, 0], "hi": [0, 0, 0], "planar": True,
                          "tris": 0})
            continue
        faces.append({
            "area": float(area[k]),
            "point": cen_r[k].tolist(),
            "normal": nn_r[k].tolist(),
            "lo": lo_r[k].tolist(),
            "hi": hi_r[k].tolist(),
            "planar": bool(planar[k]),
            "tris": int(counts[k]),
        })
    return faces


def _seg_reduce(ufunc, groups, values, n_groups, initial):
    """``ufunc.at`` style segmented min/max without the Python loop."""
    out = np.full(n_groups, initial, float)
    ufunc.at(out, groups, values)
    out[~np.isfinite(out)] = 0.0
    return out


def _face_edges(tris: np.ndarray, face_of: np.ndarray) -> List[int]:
    """
    The boundary edges of each face, for highlighting a picked face.

    An edge shared by two triangles of the same face is interior; one that is
    not is part of the face's outline. Those outlines are also exactly what an
    edge (line) pick tests against.
    """
    if not len(tris):
        return []
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    owner = np.tile(face_of, 3)
    key = np.sort(e, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0], owner))
    key, owner = key[order], owner[order]
    keep = np.ones(len(key), bool)
    same = (key[1:] == key[:-1]).all(1) & (owner[1:] == owner[:-1])
    keep[:-1] &= ~same
    keep[1:] &= ~same
    triples = np.column_stack([key[keep], owner[keep]]).astype(np.int32)
    return triples.ravel().tolist()


def _cluster_faces(verts, tris, tri_n) -> np.ndarray:
    """
    Group triangles into faces without a CAD kernel.

    Triangles are one face when they are connected and their normals continue
    smoothly into one another; a curved wall stays one face while a sharp edge
    starts a new one, which is what a modeller shows for them too. The CAD
    kernel gives exact faces when it is installed -- this is the fallback.
    """
    ntri = len(tris)
    if not ntri:
        return np.zeros(0, np.int64)
    fast = _cluster_faces_fast(tris, tri_n)
    if fast is not None:
        return fast
    # Adjacency by shared vertex, not shared edge: a cone's side triangles meet
    # only at the apex once the degenerate slivers are gone, and an
    # edge-connected walk would call each of them a separate face. The normal
    # test below is what keeps distinct faces apart.
    vert_map: Dict[int, List[int]] = {}
    for t in range(ntri):
        for x in tris[t]:
            vert_map.setdefault(int(x), []).append(t)
    face = -np.ones(ntri, np.int64)
    cur = 0
    for seed in range(ntri):
        if face[seed] >= 0:
            continue
        stack = [seed]
        face[seed] = cur
        while stack:
            t = stack.pop()
            for x in tris[t]:
                for u in vert_map[int(x)]:
                    if face[u] >= 0:
                        continue
                    # Smoothly continuing (within ~20 degrees) means one
                    # surface: that keeps a tessellated cylinder wall a single
                    # face while a box corner stays two.
                    if float(tri_n[t] @ tri_n[u]) > 0.94:
                        face[u] = cur
                        stack.append(u)
        cur += 1
    return face


#: How many neighbours in a vertex's triangle fan are linked directly. Ordinary
#: manifold vertices carry five or six triangles, so this covers them exactly.
_FAN_BAND = 8


def _cluster_faces_fast(tris: np.ndarray, tri_n: np.ndarray):
    """
    The same clustering as :func:`_cluster_faces`, done with sparse graph
    components instead of a Python flood fill.

    The mesh view of a solved model hands this hundreds of thousands of
    boundary triangles, where the flood fill costs tens of seconds. Two link
    sets reproduce the original connectivity: triangles sharing an edge, and
    consecutive triangles around a shared vertex — the latter is what keeps a
    cone's side one face when its apex triangles meet only at a point.
    Returns ``None`` when SciPy is unavailable, and the caller falls back.
    """
    try:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
    except Exception:                                       # pragma: no cover
        return None
    ntri = len(tris)
    tri_ids = np.arange(ntri, dtype=np.int64)

    # -- links through a shared edge
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    owner = np.tile(tri_ids, 3)
    key = np.sort(e, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, owner = key[order], owner[order]
    same = np.flatnonzero((key[1:] == key[:-1]).all(1))
    ea, eb = owner[same], owner[same + 1]

    # -- links around a shared vertex
    # Every pair within a vertex's fan, up to a fan width of _FAN_BAND. Wider
    # fans (a cone's apex, a cylinder cap's centre) stay connected through the
    # short-range links, and the pairwise normal test below is what decides
    # whether any given link actually joins two triangles into one face.
    vid = tris.ravel()
    vowner = np.repeat(tri_ids, 3)
    vorder = np.lexsort((vowner, vid))
    vid, vowner = vid[vorder], vowner[vorder]
    va_parts, vb_parts = [], []
    for k in range(1, _FAN_BAND + 1):
        if k >= len(vid):
            break
        same_vertex = vid[:-k] == vid[k:]
        if not same_vertex.any():
            break
        va_parts.append(vowner[:-k][same_vertex])
        vb_parts.append(vowner[k:][same_vertex])

    a = np.concatenate([ea] + va_parts) if va_parts else ea
    b = np.concatenate([eb] + vb_parts) if vb_parts else eb
    if not len(a):
        return tri_ids.copy()
    # Smoothly continuing (within ~20 degrees) means one surface.
    smooth = np.einsum("ij,ij->i", tri_n[a], tri_n[b]) > 0.94
    a, b = a[smooth], b[smooth]
    g = coo_matrix((np.ones(len(a) * 2, np.int8),
                    (np.concatenate([a, b]), np.concatenate([b, a]))),
                   shape=(ntri, ntri))
    _, labels = connected_components(g, directed=False)
    # Number faces in order of first appearance, as the flood fill did.
    _, first = np.unique(labels, return_index=True)
    remap = np.empty(labels.max() + 1, np.int64)
    remap[labels[np.sort(first)]] = np.arange(len(first))
    return remap[labels]


# --------------------------------------------------------------------------
# OCC path
# --------------------------------------------------------------------------


def display_mesh_options(gmsh, h: float) -> None:
    """The element-size settings the viewport's meshes are built with."""
    from ..geometry.kernel import steady_size_options
    gmsh.option.setNumber("Mesh.MeshSizeMax", h)
    gmsh.option.setNumber("Mesh.MeshSizeMin", h / 30.0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature",
                          _display_curve_segments())
    steady_size_options(gmsh)


def tessellate_occ(shape: Shape, deflection: Optional[float] = None) -> Dict:
    from ..geometry.kernel import (GmshSession, build_shape, fit_mesh_size,
                                   prune_to_bodies)

    lo, hi = shape.bounds()
    diag = float(np.linalg.norm(np.asarray(hi) - np.asarray(lo))) or 1.0
    h = deflection or diag / 22.0
    with GmshSession("tess") as gmsh:
        dts = build_shape(shape, gmsh)
        gmsh.model.occ.synchronize()
        prune_to_bodies(gmsh, dts)
        if deflection is None:
            h = fit_mesh_size(gmsh, h)
        display_mesh_options(gmsh, h)
        gmsh.model.mesh.generate(2)
        tags, coords, _ = gmsh.model.mesh.getNodes()
        tags = np.asarray(tags, np.int64)
        pts = np.asarray(coords, float).reshape(-1, 3)
        order = np.argsort(tags)
        tags, pts = tags[order], pts[order]
        lut = -np.ones(int(tags.max()) + 1, np.int64)
        lut[tags] = np.arange(len(tags))
        # Per OCC surface, so every triangle knows the CAD face it came from.
        tris, owner = [], []
        for k, (_, tag) in enumerate(gmsh.model.getEntities(2)):
            etypes, _, enodes = gmsh.model.mesh.getElements(2, tag)
            for et, en in zip(etypes, enodes):
                if et != 2:
                    continue
                block = lut[np.asarray(en, np.int64).reshape(-1, 3)]
                tris.append(block)
                owner.append(np.full(len(block), k, np.int64))
        if not tris:
            raise RuntimeError("surface mesher produced no triangles")
        tris = np.vstack(tris)
        owner = np.concatenate(owner)
        # Faces that ended up with no elements would leave holes in the
        # numbering; compact it so face indices are contiguous.
        _, owner = np.unique(owner, return_inverse=True)
        cad_edges=_cad_edges(gmsh,gmsh.model.getEntities(2),pts,lut,[])
    out=_pack(pts,tris,owner);out['cadEdges']=cad_edges
    return out


# --------------------------------------------------------------------------
# analytic path
# --------------------------------------------------------------------------

_BOX_FACES = np.array([
    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
    [0, 1, 5], [0, 5, 4], [2, 3, 7], [2, 7, 6],
    [1, 2, 6], [1, 6, 5], [3, 0, 4], [3, 4, 7]], dtype=np.int64)


def _frame(axis) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    a = np.asarray(axis, float)
    a = a / max(np.linalg.norm(a), 1e-300)
    ref = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(a, ref); u /= np.linalg.norm(u)
    return a, u, np.cross(a, u)


def tessellate_analytic(shape: Shape, n_seg: int = 128) -> Dict:
    from ..geometry.primitives import _apply_xform_points

    if isinstance(shape, Box):
        p = np.asarray(shape.position, float)
        s = np.asarray(shape.size, float)
        v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                      [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
        verts, tris = p + v * s, _BOX_FACES

    elif isinstance(shape, Sphere):
        verts, tris = _uv_sphere(np.asarray(shape.center, float),
                                 shape.radius, n_seg // 2, n_seg)

    elif isinstance(shape, (Cylinder, Cone)):
        a, u, w = _frame(shape.axis)
        c = np.asarray(shape.center, float)
        r1 = shape.radius if isinstance(shape, Cylinder) else shape.r1
        r2 = shape.radius if isinstance(shape, Cylinder) else shape.r2
        sweep = getattr(shape, "angle", 2 * math.pi)
        verts, tris = _tube(c, a, u, w, r1, r2, shape.height, n_seg, sweep)

    elif isinstance(shape, Torus):
        a, u, w = _frame(shape.axis)
        verts, tris = _torus(np.asarray(shape.center, float), a, u, w,
                             shape.r_major, shape.r_minor, n_seg, n_seg // 2)

    elif isinstance(shape, Polygon):
        pts = np.asarray(shape.points, float)
        tris = np.array([[0, i, i + 1] for i in range(1, len(pts) - 1)],
                        dtype=np.int64)
        verts = pts

    else:
        lo, hi = shape.bounds()
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                      [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
        verts, tris = lo + v * (hi - lo), _BOX_FACES
        log.debug("no analytic tessellation for %s; showing its bounding box",
                  type(shape).__name__)

    for t in shape._xform:
        verts = _apply_xform_points(verts, t)
    return _pack(verts, tris)


def _uv_sphere(c, r, nu, nv):
    verts, tris = [], []
    for i in range(nu + 1):
        th = math.pi * i / nu
        for j in range(nv + 1):
            ph = 2 * math.pi * j / nv
            verts.append([c[0] + r * math.sin(th) * math.cos(ph),
                          c[1] + r * math.sin(th) * math.sin(ph),
                          c[2] + r * math.cos(th)])
    for i in range(nu):
        for j in range(nv):
            a = i * (nv + 1) + j
            b = a + nv + 1
            tris += [[a, b, a + 1], [a + 1, b, b + 1]]
    return np.array(verts), np.array(tris, np.int64)


def _tube(c, a, u, w, r1, r2, h, n, sweep):
    verts, tris = [], []
    closed = sweep >= 2 * math.pi - 1e-9
    m = n if closed else n + 1
    for k in range(m):
        t = sweep * (k / n)
        d = math.cos(t) * u + math.sin(t) * w
        verts.append(c + r1 * d)
        verts.append(c + a * h + r2 * d)
    verts.append(c)
    verts.append(c + a * h)
    nb = len(verts) - 2
    for k in range(m if closed else m - 1):
        k2 = (k + 1) % m
        b0, b1 = 2 * k, 2 * k2
        tris += [[b0, b1, b0 + 1], [b0 + 1, b1, b1 + 1],
                 [nb, b1, b0], [nb + 1, b0 + 1, b1 + 1]]
    return np.array(verts), np.array(tris, np.int64)


def _torus(c, a, u, w, R, r, nu, nv):
    verts, tris = [], []
    for i in range(nu):
        t = 2 * math.pi * i / nu
        d = math.cos(t) * u + math.sin(t) * w
        for j in range(nv):
            p = 2 * math.pi * j / nv
            verts.append(c + (R + r * math.cos(p)) * d + r * math.sin(p) * a)
    for i in range(nu):
        for j in range(nv):
            a0 = i * nv + j
            a1 = i * nv + (j + 1) % nv
            b0 = ((i + 1) % nu) * nv + j
            b1 = ((i + 1) % nu) * nv + (j + 1) % nv
            tris += [[a0, b0, a1], [a1, b0, b1]]
    return np.array(verts), np.array(tris, np.int64)


# --------------------------------------------------------------------------


_TESS_CACHE: "OrderedDict[tuple, Dict]" = OrderedDict()
# Bounded by content, not by entry count: a cache of 24 assemblies is far more
# memory than a cache of 24 boxes, and it was the entry count that decided.
# A cached triangle is a Python float list on the way to JSON, which costs
# roughly forty bytes per coordinate, so the budget is deliberately modest —
# and it is emptied outright whenever the open document changes.
_TESS_BUDGET_TRIS = 1_200_000
_TESS_SIZE = 0


def import_cache_key(path, scale_to_m: float, unit: str, body: int,
                     xform=()) -> Optional[tuple]:
    """
    The cache key for one body of one CAD file, computed from the facts alone.

    Written as a free function so the import can fill the cache from the mesh
    it already built, using exactly the key the viewport will later look up.
    Two spellings of the same key are how a cache silently stops working.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (os.path.abspath(path), (st.st_mtime_ns, st.st_size),
            float(scale_to_m), unit or "auto", int(body),
            repr(list(xform)))


def _import_cache_key(shape: Shape):
    """
    Cache key for an imported body: file identity, placement, and *which body*.

    Leaving the body out meant every part of an assembly shared one entry, so
    the whole assembly drew as whichever part was tessellated first.
    """
    from ..geometry.primitives import ImportedShape
    if not isinstance(shape, ImportedShape):
        return None
    return import_cache_key(shape.path, shape.scale_to_m,
                            getattr(shape, "unit", "auto"),
                            int(getattr(shape, "body", -1)), shape._xform)


def cache_buffer(shape: Shape, buf: Dict) -> bool:
    """
    Remember a display buffer that was built for some other reason.

    The DXF import tessellates the shape once to prove the faces can be
    built at all, then used to throw that away and tessellate it again the
    moment the viewport asked. Same file, same mesh, twice.
    """
    key = _cache_key(shape)
    if key is None:
        return False
    _cache_put(key, dict(buf))
    return True


def harvest_bodies(gmsh, dim_tags, path, scale_to_m: float, unit: str) -> int:
    """
    Turn a surface mesh that already exists into display buffers, and cache
    them under the keys the viewport will ask for.

    The import already meshes the file once, to report each body's true
    extent. Meshing it a second time to draw it was pure repetition — and on
    a NURBS assembly the mesh is the expensive half of the whole import.
    """
    made = 0
    try:
        node_table = _node_table(gmsh)
    except Exception:                                       # pragma: no cover
        return 0
    ordered = sorted(dim_tags, key=lambda dt: dt[1])
    for i, (dim, tag) in enumerate(ordered):
        try:
            buf = _harvest_entity(gmsh, dim, tag, (), node_table)
        except Exception:
            continue
        for body in ((i, -1) if len(ordered) == 1 else (i,)):
            key = import_cache_key(path, scale_to_m, unit, body)
            if key is not None:
                _cache_put(key, dict(buf))
                made += 1
    return made


def _shape_fingerprint(shape: Shape):
    """
    A content key for any shape, imported or not.

    Only imported bodies used to be cached, so every primitive, boolean and
    face operation in the model was re-meshed by OpenCASCADE on every single
    redraw — and the viewport is rebuilt after every edit. Moving one box in a
    twelve-object model re-solved the other eleven from scratch. The shape tree
    already serialises itself exactly and completely, so hashing that is a
    faithful key: same geometry in, same triangles out.

    The object's *name* is deliberately excluded — renaming a body does not
    change its geometry — and any imported file inside the tree contributes its
    modification stamp, so editing the source file invalidates the entry.
    """
    from ..geometry.primitives import ImportedShape

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "name"}
        if isinstance(node, (list, tuple)):
            return [strip(v) for v in node]
        if isinstance(node, (np.floating, np.integer)):
            return float(node)
        if isinstance(node, np.ndarray):
            return node.tolist()
        return node

    def files(node: Shape, out: List):
        if isinstance(node, ImportedShape):
            try:
                st = os.stat(node.path)
            except OSError:
                out.append((str(node.path), None))
            else:
                out.append((os.path.abspath(node.path),
                            st.st_mtime_ns, st.st_size))
        for c in node.children():
            files(c, out)

    try:
        import hashlib
        import json
        stamps: List = []
        files(shape, stamps)
        payload = json.dumps([strip(shape.to_dict()), stamps],
                             sort_keys=True, default=repr)
    except Exception:                                       # pragma: no cover
        return None
    return ("shape", type(shape).__name__,
            hashlib.blake2b(payload.encode("utf-8"), digest_size=16).hexdigest())


def _cache_key(shape: Shape):
    """The cache key for a shape: the import key when it has one, else its
    content fingerprint."""
    k = _import_cache_key(shape)
    return k if k is not None else _shape_fingerprint(shape)


def _cache_put(key, buf: Dict) -> None:
    global _TESS_SIZE
    if key is None:
        return
    n = len(buf.get("position", ())) // 9
    old = _TESS_CACHE.pop(key, None)
    if old is not None:
        _TESS_SIZE -= len(old.get("position", ())) // 9
    _TESS_CACHE[key] = buf
    _TESS_SIZE += n
    while _TESS_SIZE > _TESS_BUDGET_TRIS and len(_TESS_CACHE) > 1:
        _, dropped = _TESS_CACHE.popitem(last=False)
        _TESS_SIZE -= len(dropped.get("position", ())) // 9


def clear_cache() -> None:
    """
    Drop every cached display buffer.

    Called when the document changes. The buffers of a project that is no
    longer open are pure ballast, and holding them is how a session that opens
    several large assemblies in a row runs out of memory and starts to crawl.
    """
    global _TESS_SIZE
    _TESS_CACHE.clear()
    _TESS_SIZE = 0


def tessellate_bodies(shape: Shape) -> Optional[Dict]:
    """
    Tessellate every body of an imported file in one pass, and cache them all.

    An assembly is imported once and meshed once; without this each part
    re-read the whole file, which is the difference between a large import
    that appears instantly and one that appears to have hung. Returns the
    buffer for *this* shape's body, or None when the shape is not one body of
    a multi-body file.
    """
    from ..geometry.primitives import ImportedShape
    from ..geometry.brep_io import import_into_occ
    from ..geometry.kernel import GmshSession, fit_mesh_size, prune_to_bodies

    if not isinstance(shape, ImportedShape) or getattr(shape, "body", -1) < 0:
        return None
    key = _import_cache_key(shape)
    if key is None:
        return None

    with GmshSession("tessall") as gmsh:
        dts = sorted(import_into_occ(shape.path, gmsh,
                                     healing=shape.healing,
                                     scale_to_m=shape.scale_to_m,
                                     unit=getattr(shape, "unit", "auto")),
                     key=lambda dt: dt[1])
        if len(dts) <= 1:
            return None
        bb = np.array([gmsh.model.getBoundingBox(d, t) for d, t in dts])
        diag = float(np.linalg.norm(bb[:, 3:].max(0) - bb[:, :3].min(0))) or 1.0
        h = diag / 22.0
        prune_to_bodies(gmsh, dts)
        h = fit_mesh_size(gmsh, h)
        display_mesh_options(gmsh, h)
        gmsh.model.mesh.generate(2)
        node_table = _node_table(gmsh)
        for i, (dim, tag) in enumerate(dts):
            try:
                buf = _harvest_entity(gmsh, dim, tag, shape._xform, node_table)
            except Exception:                               # pragma: no cover
                continue
            _cache_put(key[:4] + (i,) + key[5:], buf)
    return _TESS_CACHE.get(key)


def _harvest_entity(gmsh, dim: int, tag: int, xform, node_table=None) -> Dict:
    """Pull one body's triangles out of an already-generated surface mesh."""
    from ..geometry.primitives import _apply_xform_points

    surfs = ([(2, tag)] if dim == 2
             else gmsh.model.getBoundary([(dim, tag)], combined=False,
                                         oriented=False, recursive=False))
    pts,lut = node_table if node_table is not None else _node_table(gmsh)

    tris, owner = [], []
    for k, (_, st) in enumerate(sorted({(2, abs(int(t))) for d, t in surfs
                                        if d == 2})):
        etypes, _, enodes = gmsh.model.mesh.getElements(2, st)
        for et, en in zip(etypes, enodes):
            if et != 2:
                continue
            block = lut[np.asarray(en, np.int64).reshape(-1, 3)]
            tris.append(block)
            owner.append(np.full(len(block), k, np.int64))
    if not tris:
        raise RuntimeError("no triangles for this body")
    tris = np.vstack(tris)
    owner = np.concatenate(owner)
    _, owner = np.unique(owner, return_inverse=True)
    used = np.unique(tris)
    remap = -np.ones(int(used.max()) + 1, np.int64)
    remap[used] = np.arange(len(used))
    verts = pts[used]
    for t in xform:
        verts = _apply_xform_points(verts, t)
    out=_pack(verts, remap[tris], owner)
    out['cadEdges']=_cad_edges(gmsh,surfs,pts,lut,xform)
    return out


def tessellate(shape: Shape, prefer_occ: bool = True) -> Dict:
    """
    Triangulate one solid for display, OCC first, analytic as fallback.

    Imported bodies are cached. The viewport is rebuilt on every model change,
    and re-reading a large STEP assembly each time is what turns a responsive
    workspace into one that looks frozen.
    """
    from ..geometry.primitives import Sketch, _apply_xform_points
    if isinstance(shape, Sketch):
        vertices=[];edges=[]
        for path in shape.paths:
            points=np.asarray(path,float)
            for transform in shape._xform:
                points=_apply_xform_points(points,transform)
            start=len(vertices)
            vertices.extend(points.tolist())
            for i in range(len(points)-1):edges.extend([start+i,start+i+1])
        return {"position":[],"normal":[],"count":0,"faceOf":[],"faces":[],"faceEdges":[v for i in range(0,len(edges),2) for v in (edges[i],edges[i+1],-1)],
                "snapPoints":vertices,"snapKind":"drawing vertex",
                "edgeVerts":np.asarray(vertices).ravel().tolist(),"edges":edges,"referenceOnly":True}
    key = _cache_key(shape)
    if key is not None:
        hit = _TESS_CACHE.get(key)
        if hit is not None:
            _TESS_CACHE.move_to_end(key)        # keep hot geometry resident
            return dict(hit)
    if _import_cache_key(shape) is not None:
        # One body of a multi-body file: do the whole file at once.
        try:
            whole = tessellate_bodies(shape)
        except ModelBuildError:
            raise
        except Exception as exc:
            log.debug("batch tessellation failed (%s); falling back", exc)
            whole = None
        if whole is not None:
            return dict(whole)
    if prefer_occ:
        try:
            from ..geometry.kernel import available
            if available():
                buf = tessellate_occ(shape)
                _cache_put(key, dict(buf))
                return buf
        except ModelBuildError:
            # The model itself is impossible, not the display: say so instead
            # of drawing a bounding box that looks like a working result.
            raise
        except Exception as exc:
            log.warning("could not tessellate %r (%s); showing its extent "
                        "instead", getattr(shape, "name", "?"), exc)
    buf = tessellate_analytic(shape)
    _cache_put(key, dict(buf))
    return buf


def tessellate_mesh_surface(mesh) -> Dict:
    """Outer surface of a generated tetrahedral mesh (the Mesh view)."""
    tris = mesh.boundary_faces
    return _pack(mesh.nodes, tris)


def mesh_wire(mesh, stride: int = 1) -> Dict:
    """Edge list of the surface mesh, for the wireframe overlay."""
    tris = mesh.boundary_faces[::stride]
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    e = np.unique(np.sort(e, axis=1), axis=0)
    return {"verts": np.round(np.asarray(mesh.nodes).ravel(), 9).tolist(),
            "edges": e.ravel().astype(np.int32).tolist()}


def field_on_surface(field_solution, mesh) -> Dict:
    """|E| sampled on the surface triangles, normalised to [0,1] for colouring."""
    tris = mesh.boundary_faces
    owner = mesh.face_to_tet()[mesh.boundary_face_index(), 0]
    E = field_solution.E_at_centroids()
    mag = np.linalg.norm(np.abs(E[owner]), axis=1)
    lo, hi = float(mag.min()), float(mag.max())
    span = hi - lo or 1.0
    val = np.repeat((mag - lo) / span, 3)
    buf = _pack(mesh.nodes, tris)
    buf["scalar"] = np.round(val, 5).tolist()
    buf["range"] = [lo, hi]
    return buf


__all__ = ["tessellate", "tessellate_occ", "tessellate_analytic",
           "clear_cache", "harvest_bodies", "import_cache_key", "cache_buffer",
           "display_mesh_options",
           "tessellate_mesh_surface", "mesh_wire", "field_on_surface"]


def _display_curve_segments():
    """Display tessellation only; does not change the FEM mesh."""
    try:return max(16,min(128,int(os.environ.get('AETHER_VIEW_CURVE_SEGMENTS','48'))))
    except ValueError:return 48


def _node_table(gmsh):
    ntags, ncoords, _ = gmsh.model.mesh.getNodes()
    ntags = np.asarray(ntags, np.int64)
    pts = np.asarray(ncoords, float).reshape(-1, 3)
    order = np.argsort(ntags)
    ntags, pts = ntags[order], pts[order]
    lut = -np.ones(int(ntags.max()) + 1, np.int64)
    lut[ntags] = np.arange(len(ntags))

    return pts,lut


def _cad_edges(gmsh,surfaces,pts,lut,xform):
    """Keep OCC curve identities instead of merging tangent but distinct edges."""
    from ..geometry.primitives import _apply_xform_points
    curves=set()
    for d,t in surfaces:
        if d==2:
            curves.update(abs(int(tag)) for dim,tag in gmsh.model.getBoundary([(2,abs(int(t)))],combined=False,oriented=False,recursive=False) if dim==1)
    result=[]
    for tag in sorted(curves):
        types,_,nodes=gmsh.model.mesh.getElements(1,tag)
        segments=[]
        for typ,ns in zip(types,nodes):
            if typ!=1:continue
            indices=lut[np.asarray(ns,np.int64).reshape(-1,2)]
            if np.any(indices<0):continue
            values=pts[indices].reshape(-1,3)
            for transform in xform:values=_apply_xform_points(values,transform)
            segments.extend(values.reshape(-1,2,3).tolist())
        if segments:
            result.append(dict(face=-1,cad=True,id=int(tag),segments=segments,
                               length=float(sum(np.linalg.norm(np.asarray(b)-a) for a,b in segments))))
    return result
