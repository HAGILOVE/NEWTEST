"""
Stand-alone three.js viewer export.

``File ▸ Save As ▸ three.js 3D viewer (*.html)`` writes one HTML file that
shows the current model and, when a solution is open, its results -- without
Aether, Python or a network connection. The file holds:

* every object's triangles, colour and transparency, the port and boundary
  faces, and the edges;
* for each saved frequency and excitation, the **complex** E, H and surface
  current vectors on the outer surface / conductors and on a cut plane through
  each axis, and the complex far field.

Complex vectors rather than rendered frames, because the phase is then a free
parameter in the viewer: the phase slider, the animation and the choice of
|V| / X / Y / Z component are all arithmetic on the stored numbers
(``Re(V e^{j phase})``), so a field animates smoothly at any speed and the
file is several times smaller than a movie of the same cycle.

three.js (MIT) is embedded from ``aether/gui/vendor`` so the file opens from
disk; if that copy is missing the page falls back to a CDN link.
"""
from __future__ import annotations

import base64
import datetime as _dt
import json
import math
import os
from typing import Any, Dict, List, Optional

import numpy as np

from ..core.logging import get_logger

log = get_logger("gui.threejs")

_HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(_HERE, "vendor")
THREE_VERSION = "0.149.0"
THREE_CDN = f"https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}/build/three.min.js"

_UNIT_M = {"m": 1.0, "dm": 1e-1, "cm": 1e-2, "mm": 1e-3, "um": 1e-6,
           "uM": 1e-6, "in": 0.0254, "mil": 25.4e-6, "nm": 1e-9}


def _b64(a: np.ndarray, dtype) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype).tobytes()).decode("ascii")


def _complex_b64(F: np.ndarray) -> str:
    """(N,3) complex -> float32 [re x, im x, re y, im y, re z, im z] * N."""
    out = np.empty((len(F), 6), np.float32)
    out[:, 0::2] = F.real
    out[:, 1::2] = F.imag
    return _b64(out, np.float32)


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------


def _model(s, k: float) -> Dict[str, Any]:
    """Objects, ports and boundaries, in model units (``k`` = 1 / metres per unit)."""
    from . import api

    g = api._geometry(s)                                    # lists, not blobs
    objects = []
    for o in g["objects"]:
        pos = np.asarray(o.get("position", ()), float)
        if o.get("unchanged") or not len(pos) and not o.get("edgeVerts"):
            continue
        item = {"name": o["name"], "color": o.get("color") or "#b0b0b0",
                "opacity": float(1.0 - o.get("transparency", 0.0)),
                "material": o.get("material", ""), "sheet": bool(o.get("isSheet")),
                "visible": bool(o.get("visible", True)),
                "pos": _b64(pos * k, np.float32),
                "nrm": _b64(np.asarray(o.get("normal", ()), float), np.float32)}
        ev = np.asarray(o.get("edgeVerts", ()), float)
        ed = np.asarray(o.get("edges", ()), np.int64)
        if len(ev) and len(ed):
            item["edgeV"] = _b64(ev * k, np.float32)
            item["edgeI"] = _b64(ed, np.uint32)
        objects.append(item)

    assigns = []
    for a in api._view_assignments(s)["items"]:
        assigns.append({"name": a["name"], "kind": a["kind"], "type": a["type"],
                        "color": a["color"],
                        "pos": _b64(np.asarray(a["position"], float) * k, np.float32),
                        "center": [c * k for c in a["center"]]})
    bb = g.get("bbox")
    bbox = ([[float(c) * k for c in bb[0]], [float(c) * k for c in bb[1]]]
            if bb else [[-1, -1, -1], [1, 1, 1]])
    return {"objects": objects, "assign": assigns, "bbox": bbox}


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------


def _pick(values: List[float], limit: int) -> List[float]:
    if len(values) <= limit:
        return list(values)
    idx = np.unique(np.linspace(0, len(values) - 1, limit).round().astype(int))
    return [values[i] for i in idx]


def _centre(s, sol) -> np.ndarray:
    """Where the cut planes go: the middle of the solid, non-air parts."""
    lo = hi = None
    for o in s.design.solids:
        m = o.material.name if o.material else "vacuum"
        if m in ("vacuum", "air"):
            continue
        a, b = o.shape.bounds()
        lo = np.asarray(a, float) if lo is None else np.minimum(lo, a)
        hi = np.asarray(b, float) if hi is None else np.maximum(hi, b)
    if lo is None:
        a, b = sol.mesh.bounding_box()
        return 0.5 * (np.asarray(a, float) + np.asarray(b, float))
    return 0.5 * (lo + hi)


def _surface_sets(sol, fs, k: float) -> Dict[str, Any]:
    from ..post.fieldview import surface_vectors

    out: Dict[str, Any] = {}
    for q in ("E", "H", "J"):
        try:
            v, t, F = surface_vectors(sol, fs, q)
        except ValueError:
            continue
        out[q] = {"v": _b64(v * k, np.float32), "i": _b64(t.reshape(-1), np.uint32),
                  "f": _complex_b64(F), "n": int(len(v)),
                  "peak": float(np.abs(F).max())}
    return out


def _cut_sets(s, sol, fs, k: float, centre: np.ndarray) -> Dict[str, Any]:
    from ..post.fieldview import cut_vectors

    out: Dict[str, Any] = {}
    for ax, c in zip("xyz", centre):
        for q in ("E", "H"):
            try:
                v, t, F = cut_vectors(sol, fs, ax, float(c), q)
            except ValueError:
                continue
            out[f"{q}{ax}"] = {"v": _b64(v * k, np.float32),
                               "i": _b64(t.reshape(-1), np.uint32),
                               "f": _complex_b64(F), "n": int(len(v)),
                               "at": float(c) * k, "peak": float(np.abs(F).max())}
    return out


def _farfield(s, sol, freq: float, exc: int, k: float) -> Optional[Dict[str, Any]]:
    from . import api

    ff = api._farfield_for(s, freq, exc, 3.0, 6.0)
    lo, hi = s.design.bounding_box()
    scale = 0.42 * float(np.linalg.norm(hi - lo)) or 1.0
    centre = 0.5 * (np.asarray(lo, float) + np.asarray(hi, float))
    g = 10 * np.log10(np.maximum(ff.gain(), 1e-30))
    et = np.stack([ff.E_theta.real, ff.E_theta.imag], axis=-1)
    ep = np.stack([ff.E_phi.real, ff.E_phi.imag], axis=-1)
    summ = {k2: (float(v) if isinstance(v, (int, float, np.floating)) else v)
            for k2, v in ff.summary().items()}
    return {"theta": _b64(ff.theta, np.float32), "phi": _b64(ff.phi, np.float32),
            "nt": int(len(ff.theta)), "np": int(len(ff.phi)),
            "et": _b64(et, np.float32), "ep": _b64(ep, np.float32),
            "gain": _b64(g, np.float32), "scale": scale * k, "centre": (centre * k).tolist(),
            "summary": summ, "freq": float(ff.freq)}


def _sparams(sol, k_unused=None) -> Optional[Dict[str, Any]]:
    sp = getattr(sol, "sparams", None)
    if sp is None:
        return None
    traces = []
    n = sp.n_port
    for i in range(1, n + 1):
        for j in range(1, n + 1):
            if j < i or (n > 3 and i != j and j != 1):
                continue
            traces.append({"label": f"S({sp.port_names[i - 1]},{sp.port_names[j - 1]})",
                           "db": [float(v) for v in sp.db(i, j)]})
    return {"freq": [float(f) for f in sp.freq], "traces": traces[:6]}


def _results(s, k: float, max_freqs: int, max_exc: int,
             progress=None) -> Optional[Dict[str, Any]]:
    sol = s.solution
    if sol is None or not sol.fields or sol.modes:
        return None
    all_f = sorted({key[0] for key in sol.fields})
    freqs = _pick(all_f, max_freqs)
    exc_names = list(sol.design.excitation_names())[:max_exc]
    centre = _centre(s, sol)
    has_rad = any(b.btype == "radiation" for b in sol.design.boundaries)
    sets = []
    total = len(freqs) * len(exc_names)
    n = 0
    for fi, f in enumerate(freqs):
        for ei, nm in enumerate(exc_names):
            n += 1
            if progress:
                progress(f"{n}/{total}  {f / 1e9:.4g} GHz  {nm}")
            try:
                fs = sol.field(f, ei)
            except ValueError:
                continue
            entry = {"fi": fi, "ei": ei, "surface": _surface_sets(sol, fs, k),
                     "cut": _cut_sets(s, sol, fs, k, centre)}
            if has_rad:
                try:
                    entry["far"] = _farfield(s, sol, f, ei, k)
                except Exception as exc:                     # noqa: BLE001
                    log.warning("far field skipped at %g Hz: %s", f, exc)
            sets.append(entry)
    return {"freqs": freqs, "excitations": exc_names, "sets": sets,
            "sparams": _sparams(sol), "cutAt": (centre * k).tolist(),
            "hasRadiation": has_rad}


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------


def build_scene(s, max_freqs: int = 6, max_excitations: int = 4,
                with_results: bool = True, progress=None) -> Dict[str, Any]:
    """Everything the page needs, as plain JSON-able data."""
    d = s.require_design()
    k = 1.0 / _UNIT_M.get(d.units, 1e-3)
    scene: Dict[str, Any] = {
        "title": f"{s.project.name if getattr(s, 'project', None) else ''} / {d.name}".strip(" /"),
        "design": d.name, "units": d.units,
        "generated": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "model": _model(s, k)}
    scene["model"]["solutionType"] = getattr(d, "solution_type", "")
    scene["results"] = _results(s, k, max_freqs, max_excitations, progress) \
        if with_results else None
    return scene


def _read(name: str) -> Optional[str]:
    p = os.path.join(_VENDOR, name)
    if not os.path.isfile(p):
        return None
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


def render_html(scene: Dict[str, Any], embed_three: bool = True) -> str:
    tpl = _read("viewer_template.html")
    if tpl is None:
        raise FileNotFoundError("viewer_template.html is missing from aether/gui/vendor")
    three = _read("three.min.js") if embed_three else None
    if three is not None:
        # a literal "</script" would end the inline block early
        tag = "<script>" + three.replace("</script", "<\\/script") + "</script>"
    else:
        tag = f'<script src="{THREE_CDN}"></script>'
    data = json.dumps(scene, separators=(",", ":")).replace("</", "<\\/")
    title = (scene.get("title") or "Aether EM").replace("<", "&lt;")
    return (tpl.replace("<!--@@TITLE@@-->", title)
               .replace("<!--@@THREE@@-->", tag)
               .replace("/*@@SCENE@@*/null", data))


def export(s, path: str, **kw) -> Dict[str, Any]:
    """Write the viewer for the open design (and its solution) to *path*."""
    if os.path.splitext(path)[1].lower() not in (".html", ".htm"):
        path += ".html"
    scene = build_scene(s, **kw)
    html = render_html(scene)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    res = scene.get("results")
    return {"path": os.path.abspath(path), "bytes": len(html.encode("utf-8")),
            "objects": len(scene["model"]["objects"]),
            "results": bool(res),
            "frequencies": len(res["freqs"]) if res else 0,
            "offline": os.path.isfile(os.path.join(_VENDOR, "three.min.js"))}
