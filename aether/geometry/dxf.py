"""
AutoCAD DXF reader.

DXF is where a PCB outline, an antenna trace or a mechanical cut-out usually
starts, and it is a 2-D drawing format: entities on layers, in a drawing unit
that the header states as a code rather than a name. What matters for a
solver is the *outlines* -- closed loops that can become sheets and then, with
one face sweep, solids.

Only what a drawing actually carries is read: LINE, LWPOLYLINE, POLYLINE,
CIRCLE, ARC, SOLID and the POINT entities, on any layer, from any DXF version
in the ASCII (tagged) encoding, which is what every tool exports by default.
Binary DXF and DWG are refused with an explanation rather than a stack trace.

The reader is deliberately self-contained: no third-party DXF library is
needed, so an air-gapped install still reads the drawings.
"""
from __future__ import annotations

import math
import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from ..core.logging import get_logger

log = get_logger("geometry.dxf")

# $INSUNITS: the drawing's unit as a code, which is how DXF states it.
INSUNITS = {0: "", 1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m", 8: "uin",
            9: "mil", 10: "yd", 11: "A", 12: "nm", 13: "um", 14: "dm",
            15: "dam", 16: "hm", 17: "Gm", 21: "usft"}

UNIT_SCALE = {"m": 1.0, "dm": 1e-1, "cm": 1e-2, "mm": 1e-3, "um": 1e-6,
              "nm": 1e-9, "in": 2.54e-2, "ft": 0.3048, "yd": 0.9144,
              "mil": 2.54e-5, "uin": 2.54e-8, "usft": 1200/3937}


class DxfError(RuntimeError):
    pass


class Polyline:
    """One drawn outline, already flattened to points."""

    __slots__ = ("points", "closed", "layer", "kind")

    def __init__(self, points, closed: bool, layer: str = "0",
                 kind: str = "polyline"):
        self.points = np.asarray(points, float)
        self.closed = bool(closed)
        self.layer = layer
        self.kind = kind

    @property
    def length(self) -> float:
        p = self.points
        if len(p) < 2:
            return 0.0
        seg = np.linalg.norm(np.diff(p, axis=0), axis=1).sum()
        if self.closed and len(p) > 2:
            seg += float(np.linalg.norm(p[0] - p[-1]))
        return float(seg)

    @property
    def area(self) -> float:
        """Area magnitude of a planar outline in WCS; zero for open/nonplanar."""
        if not self.closed or len(self.points) < 3:
            return 0.0
        points=self.points-self.points[0]
        normal=np.cross(points,np.roll(points,-1,axis=0)).sum(axis=0)
        norm=float(np.linalg.norm(normal))
        if norm<=1e-30:return 0.0
        if np.max(np.abs(points @ (normal/norm)))>max(1e-9,np.max(np.linalg.norm(points,axis=1))*1e-8):
            return 0.0
        return norm/2

    def __repr__(self):
        return (f"<Polyline {len(self.points)} pts "
                f"{'closed' if self.closed else 'open'} layer={self.layer!r}>")


def _pairs(path: str) -> Iterable[Tuple[int, str]]:
    """Group-code / value pairs, the whole of DXF's syntax."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        while True:
            code = fh.readline()
            if not code:
                return
            value = fh.readline()
            if not value:
                return
            code = code.strip()
            if not code:
                continue
            try:
                yield int(code), value.rstrip("\n").rstrip("\r")
            except ValueError:
                raise DxfError(
                    "this file is not tagged (ASCII) DXF -- binary DXF and "
                    "DWG cannot be read. Save as 'AutoCAD ASCII DXF' and try "
                    "again.")


def _read_ascii_dxf(path: str, unit: Optional[str] = None,
             arc_segments: int = 72) -> dict:
    """
    Read a DXF drawing into flattened outlines, in metres.

    ``unit`` overrides the drawing's own ``$INSUNITS``; a drawing that declares
    nothing is read as millimetres, which is what every mechanical and PCB tool
    exports.
    """
    if not os.path.isfile(path):
        raise DxfError(f"DXF file not found: {path}")

    declared = ""
    entities: List[Polyline] = []
    layers: Dict[str, int] = {}

    section = ""
    header_var = ""
    ent = None                      # current entity accumulator
    verts: List[List[float]] = []   # POLYLINE vertex accumulation
    poly = None

    def flush():
        nonlocal ent, poly, verts
        if ent is not None:
            out = _finish(ent, arc_segments)
            for p in out:
                entities.append(p)
                layers[p.layer] = layers.get(p.layer, 0) + 1
        ent = None

    for code, value in _pairs(path):
        if code == 0:
            kind = value.strip().upper()
            if kind == "SEQEND" and poly is not None:
                poly["verts"] = verts
                ent = poly
                poly, verts = None, []
                flush()
                continue
            if kind == "VERTEX" and poly is not None:
                verts.append([0.0, 0.0, 0.0])
                continue
            flush()
            if kind == "SECTION":
                section = "?"
            elif kind == "ENDSEC":
                section = ""
            elif section == "ENTITIES" and kind == "POLYLINE":
                poly = {"type": "POLYLINE", "layer": "0", "flags": 0,
                        "verts": []}
                verts = []
            elif section == "ENTITIES" and kind in ("LINE", "LWPOLYLINE", "CIRCLE", "ARC", "SOLID",
                          "POINT"):
                ent = {"type": kind, "layer": "0", "pts": [], "bulge": [],
                       "flags": 0}
            continue

        if section == "?" and code == 2:
            section = value.strip().upper()
            continue

        if section == "HEADER":
            if code == 9:
                header_var = value.strip().upper()
            elif header_var == "$INSUNITS" and code == 70:
                declared = INSUNITS.get(int(float(value)), "")
            continue

        if poly is not None and ent is None:
            if code == 8:
                poly["layer"] = value.strip()
            elif code == 70:
                poly["flags"] = int(float(value))
            elif verts:
                if code == 10:
                    verts[-1][0] = float(value)
                elif code == 20:
                    verts[-1][1] = float(value)
                elif code == 30:
                    verts[-1][2] = float(value)
            continue

        if ent is None:
            continue
        if code == 8:
            ent["layer"] = value.strip()
        elif code == 70:
            ent["flags"] = int(float(value))
        elif code == 42:
            # A bulge belongs to the vertex most recently read, and vertices
            # arrive as 10/20 pairs in the code stream.
            nvert = sum(1 for c, _ in ent.get("codes", []) if c == 10)
            ent["bulge"].append((max(nvert - 1, 0), float(value)))
        elif code in (10, 20, 30, 11, 21, 31, 12, 22, 32, 13, 23, 33,
                      40, 50, 51):
            ent.setdefault("codes", []).append((code, float(value)))
    flush()

    use = (unit or "").strip().lower()
    if use in ("", "auto"):
        use = declared or "mm"
    if use not in UNIT_SCALE:
        raise DxfError(f"Unsupported DXF unit: {use}")
    scale = UNIT_SCALE[use]
    for p in entities:
        p.points = p.points * scale

    return {"entities": entities, "declaredUnit": declared,
            "appliedUnit": use, "layers": layers, "scale": scale}


def _finish(ent: dict, arc_segments: int) -> List[Polyline]:
    """Turn one accumulated entity into flattened outlines."""
    kind = ent["type"]
    layer = ent.get("layer", "0")
    codes = ent.get("codes", [])

    if kind == "POLYLINE":
        pts = [v for v in ent.get("verts", [])]
        if len(pts) < 2:
            return []
        return [Polyline(pts, bool(ent.get("flags", 0) & 1), layer, "polyline")]

    def grouped(first: int) -> List[List[float]]:
        """Collect x/y/z triples for a repeating 10/20/30-style group."""
        out: List[List[float]] = []
        for code, val in codes:
            if code == first:
                out.append([val, 0.0, 0.0])
            elif out and code == first + 10:
                out[-1][1] = val
            elif out and code == first + 20:
                out[-1][2] = val
        return out

    def scalar(code: int, default: float = 0.0) -> float:
        for c, v in codes:
            if c == code:
                return v
        return default

    if kind == "LINE":
        a = grouped(10)
        b = grouped(11)
        if not a or not b:
            return []
        return [Polyline([a[0], b[0]], False, layer, "line")]

    if kind == "POINT":
        a = grouped(10)
        return [Polyline(a[:1], False, layer, "point")] if a else []

    if kind == "LWPOLYLINE":
        pts = grouped(10)
        if len(pts) < 2:
            return []
        closed = bool(int(ent.get("flags", 0)) & 1)
        # 42-codes are bulges: an arc between this vertex and the next.
        bulges = dict(ent.get("bulge", []))
        if bulges:
            pts = _apply_bulges(pts, bulges, closed, arc_segments)
        return [Polyline(pts, closed, layer, "lwpolyline")]

    if kind == "CIRCLE":
        c = grouped(10)
        r = scalar(40)
        if not c or r <= 0:
            return []
        return [Polyline(_arc(c[0], r, 0.0, 360.0, arc_segments), True, layer,
                         "circle")]

    if kind == "ARC":
        c = grouped(10)
        r = scalar(40)
        if not c or r <= 0:
            return []
        a0, a1 = scalar(50), scalar(51)
        return [Polyline(_arc(c[0], r, a0, a1, arc_segments), False, layer,
                         "arc")]

    if kind == "SOLID":
        pts = grouped(10) + grouped(11) + grouped(12) + grouped(13)
        pts = [p for p in pts if p]
        if len(pts) < 3:
            return []
        # DXF SOLID lists its fourth and third corners the other way round
        if len(pts) == 4:
            pts = [pts[0], pts[1], pts[3], pts[2]]
        return [Polyline(pts, True, layer, "solid")]

    return []


def _arc(center: Sequence[float], r: float, a0_deg: float, a1_deg: float,
         n: int) -> List[List[float]]:
    a0 = math.radians(a0_deg)
    a1 = math.radians(a1_deg)
    if a1 <= a0:
        a1 += 2 * math.pi
    steps = max(3, int(round(n * (a1 - a0) / (2 * math.pi))))
    return [[center[0] + r * math.cos(a0 + (a1 - a0) * i / steps),
             center[1] + r * math.sin(a0 + (a1 - a0) * i / steps),
             center[2]] for i in range(steps + 1)]


def _apply_bulges(pts, bulges: Dict[int, float], closed: bool,
                  n: int) -> List[List[float]]:
    """Replace bulged segments with their arcs (DXF's way of drawing fillets)."""
    out: List[List[float]] = []
    m = len(pts)
    last = m if closed else m - 1
    for i in range(last):
        a = pts[i]
        b = pts[(i + 1) % m]
        out.append(a)
        g = bulges.get(i, 0.0)
        if abs(g) < 1e-12:
            continue
        # bulge = tan(theta/4); positive is counter-clockwise
        theta = 4.0 * math.atan(g)
        chord = math.hypot(b[0] - a[0], b[1] - a[1])
        if chord < 1e-15 or abs(math.sin(theta / 2)) < 1e-15:
            continue
        r = chord / (2 * math.sin(theta / 2))
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        h = math.sqrt(max(r * r - (chord / 2) ** 2, 0.0)) * (1 if theta > 0 else -1)
        ux, uy = (b[0] - a[0]) / chord, (b[1] - a[1]) / chord
        cx, cy = mx - uy * h, my + ux * h
        a0 = math.atan2(a[1] - cy, a[0] - cx)
        steps = max(2, int(round(abs(theta) / (2 * math.pi) * n)))
        for k in range(1, steps):
            ang = a0 + theta * k / steps
            out.append([cx + abs(r) * math.cos(ang),
                        cy + abs(r) * math.sin(ang), a[2]])
    if not closed:
        out.append(pts[-1])
    return out


def outlines(path: str, unit: Optional[str] = None,
             layer: Optional[str] = None,
             min_area: float = 0.0) -> List[Polyline]:
    """Closed outlines only -- the ones that can become a sheet."""
    doc = read_dxf(path, unit)
    out = []
    for p in doc["entities"]:
        if not p.closed or len(p.points) < 3:
            continue
        if layer and p.layer != layer:
            continue
        if p.area <= min_area:
            continue
        out.append(p)
    return out


def summary(path: str, unit: Optional[str] = None) -> dict:
    """What a DXF holds, for the import dialog."""
    try:
        doc = read_dxf(path, unit)
    except DxfError as exc:
        return {"error": str(exc)}
    ents = doc["entities"]
    closed = [p for p in ents if p.closed and len(p.points) >= 3]
    pts = np.vstack([p.points for p in ents]) if ents else np.zeros((1, 3))
    return {
        "error": "",
        "warnings": doc.get("warnings", []),
        "joinedChains": doc.get("joinedChains", 0),
        "entities": len(ents),
        "closed": len(closed),
        "layers": doc["layers"],
        "declaredUnit": doc["declaredUnit"],
        "appliedUnit": doc["appliedUnit"],
        "bbox": [list(pts.min(0)), list(pts.max(0))],
        "areas": sorted((p.area for p in closed), reverse=True)[:12],
    }


__all__ = ["read_dxf", "outlines", "summary", "Polyline", "DxfError",
           "INSUNITS", "UNIT_SCALE"]


def stitch_entities(entities, tolerance=1e-7):
    """Join unambiguous same-layer endpoint chains; never bridge larger gaps.

    Branching components stay as original open paths. Tolerance is in metres.
    """
    from scipy.spatial import cKDTree
    out, groups = [], {}
    for entity in entities:
        pts = np.asarray(entity.points)
        if len(pts) > 1:
            keep = np.r_[True, np.linalg.norm(np.diff(pts, axis=0), axis=1)>1e-14]
            pts = pts[keep]
        closed = entity.closed or (len(pts)>2 and np.linalg.norm(pts[0]-pts[-1])<=tolerance)
        if closed and len(pts)>2:
            if np.linalg.norm(pts[0]-pts[-1])<=tolerance:pts=pts[:-1]
            out.append(Polyline(pts,True,entity.layer,entity.kind))
        elif len(pts)>=2:
            groups.setdefault(entity.layer,[]).append(Polyline(pts,False,entity.layer,entity.kind))
        else:
            out.append(entity)
    joined = 0
    for layer, paths in groups.items():
        endpoints = np.array([pt for p in paths for pt in (p.points[0],p.points[-1])])
        parent = list(range(len(endpoints)))
        def root(i):
            while parent[i]!=i:
                parent[i]=parent[parent[i]];i=parent[i]
            return i
        for a,b in cKDTree(endpoints).query_pairs(tolerance):
            ra,rb=root(a),root(b)
            if ra!=rb:parent[rb]=ra
        ends=[(root(2*i),root(2*i+1)) for i in range(len(paths))]
        adjacency={}
        for i,(a,b) in enumerate(ends):
            adjacency.setdefault(a,[]).append(i);adjacency.setdefault(b,[]).append(i)
        remaining=set(range(len(paths)))
        while remaining:
            seed=min(remaining);component={seed};stack=[seed]
            while stack:
                e=stack.pop()
                for vertex in ends[e]:
                    for nxt in adjacency[vertex]:
                        if nxt not in component:component.add(nxt);stack.append(nxt)
            remaining-=component
            vertices={v for e in component for v in ends[e]}
            if any(len(adjacency[v])>2 for v in vertices):
                out.extend(paths[e] for e in sorted(component));continue
            tips=[v for v in vertices if len(adjacency[v])==1]
            start=min(tips) if tips else ends[min(component)][0]
            current=start;unused=set(component);points=[]
            while unused:
                e=next((e for e in adjacency[current] if e in unused),None)
                if e is None:break
                unused.remove(e);a,b=ends[e]
                pts=paths[e].points if a==current else paths[e].points[::-1]
                points.extend(pts if not points else pts[1:]);current=b if a==current else a
            closed=current==start and not unused and len(points)>3
            if closed:points=points[:-1]
            out.append(Polyline(points,closed,layer,'joined' if len(component)>1 else paths[seed].kind))
            joined+=int(len(component)>1)
    return out, joined


def _read_ezdxf(path, unit, arc_segments):
    import ezdxf
    from ezdxf.disassemble import recursive_decompose
    from ezdxf.path import make_path
    doc=ezdxf.readfile(path)
    declared=INSUNITS.get(int(doc.header.get('$INSUNITS',0)),'')
    use=(unit or '').strip().lower()
    if use in ('','auto'):use=declared or 'mm'
    if use not in UNIT_SCALE:raise DxfError(f'Unsupported DXF unit: {use}')
    scale=UNIT_SCALE[use];entities=[];ignored={};warnings=[]
    for ent in recursive_decompose(doc.modelspace()):
        kind=ent.dxftype();layer=ent.dxf.get('layer','0')
        if kind not in ('LINE','LWPOLYLINE','POLYLINE','CIRCLE','ARC','ELLIPSE','SPLINE','SOLID','TRACE','3DFACE','POINT'):
            ignored[kind]=ignored.get(kind,0)+1;continue
        if kind=='POINT':
            entities.append(Polyline([tuple(ent.dxf.location)],False,layer,'point'));continue
        try:
            pathobj=make_path(ent,segments=max(1,arc_segments//18))
            # chord tolerance 1 micrometre in the imported model.
            pts=[tuple(p) for p in pathobj.flattening(1e-6/scale,segments=max(4,arc_segments//4))]
            if pts:entities.append(Polyline(pts,pathobj.is_closed,layer,kind.lower()))
        except Exception as exc:
            warnings.append(f'{kind} on layer {layer}: {exc}')
    for ent in entities:ent.points*=scale
    if ignored:warnings.append('Ignored non-geometry/unsupported DXF entities: '+', '.join(f'{k} ({v})' for k,v in sorted(ignored.items())))
    return dict(entities=entities,declaredUnit=declared,appliedUnit=use,scale=scale,warnings=warnings,reader='ezdxf')


def read_dxf(path, unit=None, arc_segments=72):
    """Read modelspace, expand blocks/curves when ezdxf is installed, join paths."""
    if not os.path.isfile(path):raise DxfError(f'DXF file not found: {path}')
    try:
        doc=_read_ezdxf(path,unit,arc_segments)
    except ImportError:
        doc=_read_ascii_dxf(path,unit,arc_segments)
        doc['warnings']=['Basic DXF reader: install ezdxf for INSERT, SPLINE, ELLIPSE and OCS support.']
        doc['reader']='basic'
    except DxfError:
        raise
    except Exception as exc:
        # Minimal/legacy ASCII drawings may omit tables required by ezdxf.
        doc=_read_ascii_dxf(path,unit,arc_segments)
        doc['warnings']=[f'Used basic DXF reader after structured-reader error: {exc}']
        doc['reader']='basic'
    doc['entities'],doc['joinedChains']=stitch_entities(doc['entities'])
    doc['layers']={}
    for ent in doc['entities']:doc['layers'][ent.layer]=doc['layers'].get(ent.layer,0)+1
    return doc
