"""
Saving a finished solution next to its project, and getting it back.

``project.aedt`` keeps the model; ``project.aedt.aeres`` keeps what the solver
produced from it -- the mesh, the S-parameters, the port modes and every saved
field. Opening the project afterwards restores the solution, so S-parameter
reports, field plots, animations and the far field are available at once
without solving again.

The file is a compressed ``.npz`` holding plain arrays plus a JSON header (no
pickle, so a results file can never run code when it is opened). It records the
SHA-256 of the project file it belongs to; if the ``.aedt`` has been edited
since, the results no longer describe it and are not loaded.
"""
from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import os
import zipfile
from typing import Any, Dict, List, Optional

import numpy as np
import scipy.sparse as sp

from ..core.logging import get_logger

log = get_logger("io.results")

SUFFIX = ".aeres"
FORMAT = 1


def results_path(project_path: str) -> str:
    return project_path + SUFFIX


def file_digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# encoding
# --------------------------------------------------------------------------


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, complex):
        return {"__c": [o.real, o.imag]}
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"cannot store {type(o).__name__}")


def _cx(z) -> list:
    z = complex(z)
    return [z.real, z.imag]


def _uncx(v) -> complex:
    return complex(v[0], v[1]) if isinstance(v, (list, tuple)) else complex(v)


def _dataclass_scalars(obj) -> Dict[str, Any]:
    """Scalar fields of a dataclass as JSON-able values (complex -> [re, im])."""
    out: Dict[str, Any] = {}
    for f in dataclasses.fields(obj):
        v = getattr(obj, f.name)
        if isinstance(v, np.ndarray) or sp.issparse(v):
            continue
        if isinstance(v, (complex, np.complexfloating)):
            out[f.name] = {"__c": _cx(v)}
        elif isinstance(v, (bool, np.bool_)):
            out[f.name] = bool(v)
        elif isinstance(v, (int, np.integer)):
            out[f.name] = int(v)
        elif isinstance(v, (float, np.floating)):
            out[f.name] = float(v)
        elif isinstance(v, str):
            out[f.name] = v
    return out


def _decode_scalars(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (_uncx(v["__c"]) if isinstance(v, dict) and "__c" in v else v)
            for k, v in d.items()}


def save_solution(solution, project_path: str, design_name: str) -> Optional[str]:
    """Write ``<project>.aeres`` for *solution*; returns its path."""
    arrays: Dict[str, np.ndarray] = {}
    meta: Dict[str, Any] = {"format": FORMAT, "design": design_name,
                            "project_sha256": file_digest(project_path)}

    # ---- mesh
    m = solution.mesh
    mesh_meta: Dict[str, Any] = {"scalars": {}, "dicts": {}, "names": {}}
    for k, v in vars(m).items():
        if k.startswith("_"):
            continue
        if isinstance(v, np.ndarray):
            arrays[f"mesh/{k}"] = v
        elif isinstance(v, dict) and v and all(isinstance(x, np.ndarray)
                                               for x in v.values()):
            keys = list(v)
            mesh_meta["dicts"][k] = keys
            for i, key in enumerate(keys):
                arrays[f"meshd/{k}/{i}"] = v[key]
        elif isinstance(v, dict):
            mesh_meta["names"][k] = {str(a): b for a, b in v.items()}
        elif isinstance(v, (int, float, str, bool, np.integer, np.floating)):
            mesh_meta["scalars"][k] = v
    meta["mesh"] = mesh_meta
    meta["order"] = int(solution.dofmap.order)

    # ---- S-parameters
    sp_ = solution.sparams
    if sp_ is not None:
        arrays["sp/freq"], arrays["sp/s"], arrays["sp/z0"] = sp_.freq, sp_.s, sp_.z0
        meta["sparams"] = {"port_names": list(sp_.port_names),
                           "comments": list(sp_.comments)}
    arrays["freqs"] = np.asarray(solution.freqs, float)
    if solution.solved is not None:
        arrays["solved"] = np.asarray(solution.solved, bool)

    # ---- fields
    keys = list(solution.fields)
    meta["fields"] = [[float(f), int(j)] for f, j in keys]
    for i, key in enumerate(keys):
        arrays[f"fx/{i}"] = np.asarray(solution.fields[key].x, complex)
    if keys:
        meta["field_freq"] = [float(solution.fields[k].freq) for k in keys]

    # ---- ports
    pmeta = []
    for fi, (f, sols) in enumerate(solution.ports.items()):
        entry = {"freq": float(f), "sols": []}
        for si, ps in enumerate(sols):
            base = f"pt/{fi}/{si}"
            arrays[f"{base}/tris"], arrays[f"{base}/dofs"] = ps.tris, ps.dofs
            arrays[f"{base}/normal"] = np.asarray(ps.normal, float)
            B = ps.B.tocsr()
            arrays[f"{base}/Bd"], arrays[f"{base}/Bi"], arrays[f"{base}/Bp"] = \
                B.data, B.indices, B.indptr
            modes = []
            for mi, pm in enumerate(ps.modes):
                arrays[f"{base}/m{mi}/coeffs"] = np.asarray(pm.coeffs)
                arrays[f"{base}/m{mi}/ez"] = np.asarray(pm.ez_coeffs)
                modes.append(_dataclass_scalars(pm))
            entry["sols"].append({"name": ps.name, "freq": float(ps.freq),
                                  "area": float(ps.area), "n_modes": int(ps.n_modes),
                                  "shape": list(B.shape), "modes": modes})
        pmeta.append(entry)
    meta["ports"] = pmeta

    # ---- eigenmodes, convergence, sweep log
    meta["modes"] = [{"index": int(e.index), "frequency": _cx(e.frequency),
                      "q": float(e.q), "residual": float(e.residual),
                      "iterations": int(e.iterations)} for e in solution.modes]
    meta["convergence"] = solution.convergence
    meta["sweep_info"] = solution.sweep_info
    meta["runtime"] = float(solution.runtime)

    path = results_path(project_path)
    tmp = path + ".tmp"
    buf = io.BytesIO()
    np.savez_compressed(buf, meta=np.array(json.dumps(meta, default=_json_default)),
                        **{k.replace("/", "__"): v for k, v in arrays.items()})
    with open(tmp, "wb") as fh:
        fh.write(buf.getvalue())
    os.replace(tmp, path)
    log.info("saved results %s (%.1f MB)", path, os.path.getsize(path) / 1e6)
    return path


# --------------------------------------------------------------------------
# decoding
# --------------------------------------------------------------------------


def peek(project_path: str) -> Optional[dict]:
    """Header of the results file next to a project, or ``None``."""
    path = results_path(project_path)
    if not os.path.isfile(path):
        return None
    try:
        with np.load(path, allow_pickle=False) as z:
            return json.loads(str(z["meta"]))
    except Exception as exc:                                  # noqa: BLE001
        log.warning("unreadable results file %s: %s", path, exc)
        return None


def load_solution(project_path: str, design):
    """
    Rebuild a :class:`~aether.fem.driver.Solution` for *design*.

    Returns ``(solution, reason)``: ``solution`` is ``None`` and ``reason``
    says why when the file is missing, belongs to a different version of the
    project, or is unreadable.
    """
    from ..fem.driver import Solution, _material_maps
    from ..fem.eigen import EigenMode
    from ..fem.elements import DofMap
    from ..fem.fields import FieldSolution
    from ..fem.ports import PortMode, PortSolution
    from ..mesh.tetmesh import TetMesh
    from ..post.sparam import SParameters

    path = results_path(project_path)
    if not os.path.isfile(path):
        return None, "no saved results"
    try:
        z = np.load(path, allow_pickle=False)
        meta = json.loads(str(z["meta"]))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        return None, f"saved results are unreadable ({exc})"
    if meta.get("format") != FORMAT:
        return None, "saved results are from an incompatible version"
    if meta.get("design") != design.name:
        return None, f"saved results belong to design {meta.get('design')!r}"
    if meta.get("project_sha256") != file_digest(project_path):
        return None, ("the project file changed after these results were "
                      "saved, so they no longer describe it")

    def arr(key):
        return z[key.replace("/", "__")]

    try:
        mm = meta["mesh"]
        kw = {}
        extra: Dict[str, Any] = {}
        for k in z.files:
            if k.startswith("mesh__"):
                name = k[len("mesh__"):]
                kw[name] = z[k]
        mesh = TetMesh(nodes=kw.pop("nodes"), tets=kw.pop("tets"),
                       tet_region=kw.pop("tet_region", None),
                       region_names={int(a): b for a, b in
                                     mm["names"].get("region_names", {}).items()},
                       surf_tris=kw.pop("surf_tris", None),
                       surf_tag=kw.pop("surf_tag", None),
                       tag_names={int(a): b for a, b in
                                  mm["names"].get("tag_names", {}).items()},
                       skipped_bodies=dict(mm["names"].get("skipped_bodies", {})))
        for k, v in kw.items():                    # generator-added attributes
            setattr(mesh, k, v)
        for k, v in mm["scalars"].items():
            setattr(mesh, k, v)
        for k, dct in mm["names"].items():          # e.g. empty port_faces
            if k not in ("region_names", "tag_names", "skipped_bodies"):
                setattr(mesh, k, dict(dct))
        for k, keys in mm["dicts"].items():
            setattr(mesh, k, {key: arr(f"meshd/{k}/{i}") for i, key in enumerate(keys)})
        dofmap = DofMap(mesh, int(meta["order"]))

        sparams = None
        if "sparams" in meta:
            sparams = SParameters(arr("sp/freq"), arr("sp/s"), arr("sp/z0"),
                                  list(meta["sparams"]["port_names"]),
                                  list(meta["sparams"]["comments"]))

        ports: Dict[float, list] = {}
        for fi, entry in enumerate(meta["ports"]):
            sols = []
            for si, pe in enumerate(entry["sols"]):
                base = f"pt/{fi}/{si}"
                B = sp.csr_matrix((arr(f"{base}/Bd"), arr(f"{base}/Bi"),
                                   arr(f"{base}/Bp")), shape=tuple(pe["shape"]))
                modes = []
                for mi, ms in enumerate(pe["modes"]):
                    d = _decode_scalars(ms)
                    modes.append(PortMode(coeffs=arr(f"{base}/m{mi}/coeffs"),
                                          ez_coeffs=arr(f"{base}/m{mi}/ez"), **d))
                sols.append(PortSolution(
                    name=pe["name"], freq=pe["freq"], modes=modes,
                    tris=arr(f"{base}/tris"), dofs=arr(f"{base}/dofs"), B=B,
                    normal=arr(f"{base}/normal"), area=pe["area"],
                    n_modes=pe["n_modes"]))
            ports[float(entry["freq"])] = sols

        fields = {}
        maps: Dict[float, tuple] = {}
        for i, (f, j) in enumerate(meta["fields"]):
            ff = float(meta["field_freq"][i])
            if ff not in maps:
                eps, mu = _material_maps(design, mesh, ff)
                maps[ff] = (eps, mu)
            eps, mu = maps[ff]
            fields[(float(f), int(j))] = FieldSolution(
                mesh, dofmap, arr(f"fx/{i}"), ff,
                lambda r, e=eps: e.get(r, 1.0 + 0j),
                lambda r, u=mu: u.get(r, 1.0 + 0j))

        modes = [EigenMode(index=e["index"], frequency=_uncx(e["frequency"]),
                           q=e["q"], residual=e["residual"],
                           iterations=e["iterations"]) for e in meta["modes"]]
        sol = Solution(design=design, mesh=mesh, dofmap=dofmap,
                       freqs=arr("freqs"), sparams=sparams, ports=ports,
                       fields=fields, convergence=meta["convergence"],
                       runtime=meta["runtime"],
                       solved=arr("solved") if "solved" in z.files else None,
                       sweep_info=meta["sweep_info"], modes=modes)
    except Exception as exc:                                  # noqa: BLE001
        log.warning("could not restore results from %s: %s", path, exc)
        return None, f"saved results could not be restored ({exc})"
    finally:
        z.close()
    return sol, ""
