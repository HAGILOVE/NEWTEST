"""Geometry export with atomic replacement and explicit units."""

from __future__ import annotations
import os
import tempfile
import numpy as np


def export_geometry(design, path, names=None, units="mm"):
    from ..gui.measurement import UNITS

    if units not in UNITS:
        raise ValueError("Unsupported export unit")
    wanted = set(names or [o.name for o in design.solids + design.sheets
                           if not getattr(o.shape,"reference_only",False)])
    objects = [o for o in design.solids + design.sheets if o.name in wanted]
    if not objects or len(objects) != len(wanted):
        raise ValueError("Select existing geometry to export")
    if any(getattr(o.shape,"reference_only",False) for o in objects):
        raise ValueError("Reference sketches have no CAD surface to export. Save the project or export the source DXF instead.")
    path = os.path.abspath(os.path.expanduser(path))
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".stl", ".step", ".stp"):
        raise ValueError("Choose .stl or .step/.stp")
    fd, temp = tempfile.mkstemp(
        prefix=".aether-export-", suffix=ext, dir=os.path.dirname(path)
    )
    os.close(fd)
    try:
        if ext == ".stl":
            from ..gui.tessellate import tessellate_analytic, tessellate_occ
            from .kernel import available
            from .primitives import Box, Cylinder, Sphere, Cone, Torus, Polygon

            with open(temp, "w", encoding="ascii") as stream:
                stream.write("solid Aether_units_" + units + "\n")
                triangles = 0
                for o in objects:
                    # Export must never use the viewport's bounding-box fallback.
                    if available():
                        buf = tessellate_occ(o.shape)
                    elif isinstance(
                        o.shape, (Box, Cylinder, Sphere, Cone, Torus, Polygon)
                    ):
                        buf = tessellate_analytic(o.shape)
                    else:
                        raise RuntimeError(
                            "Surface geometry is unavailable. Install OCC to export this object."
                        )
                    p = (
                        np.asarray(buf["position"], float).reshape(-1, 3, 3)
                        / UNITS[units]
                    )
                    for tri in p:
                        n = np.cross(tri[1] - tri[0], tri[2] - tri[0])
                        length = np.linalg.norm(n)
                        if not length:
                            continue
                        n = n / length
                        stream.write(
                            "facet normal "
                            + " ".join(f"{x:.12g}" for x in n)
                            + "\nouter loop\n"
                        )
                        for v in tri:
                            stream.write(
                                "vertex " + " ".join(f"{x:.12g}" for x in v) + "\n"
                            )
                        stream.write("endloop\nendfacet\n")
                        triangles += 1
                stream.write("endsolid Aether_units_" + units + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            if not triangles:
                raise ValueError("No exportable triangles")
            note = f"STL coordinates in {units}; STL has no standard unit metadata. Surface tessellation, not editable BREP."
        else:
            from .kernel import GmshSession, build_shape

            with GmshSession("export") as gmsh:
                tags = []
                for o in objects:
                    tags.extend(build_shape(o.shape, gmsh))
                gmsh.model.occ.synchronize()
                b = np.array([gmsh.model.getBoundingBox(dim, tag) for dim, tag in tags])
                expected = np.array([b[:, :3].min(axis=0), b[:, 3:].max(axis=0)])
                # STEP default export is millimetres; verify the actual file in SI below.
                gmsh.model.occ.dilate(tags, 0, 0, 0, 1000, 1000, 1000)
                gmsh.model.occ.synchronize()
                gmsh.write(temp)
            from .brep_io import quick_bounds

            actual = np.array(quick_bounds(temp))
            tolerance = max(float(np.ptp(expected, axis=0).max()) * 1e-4, 2e-6)
            if not np.allclose(expected, actual, rtol=1e-4, atol=tolerance):
                raise RuntimeError(
                    "STEP export unit/bounds verification failed; destination was not replaced"
                )
            note = "STEP BREP export; bounds checked after reimport in SI. Materials, ports and parameter history are not CAD geometry."
        os.replace(temp, path)
        return {
            "ok": True,
            "path": path,
            "objects": [o.name for o in objects],
            "note": note,
        }
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
