"""VTK (.vtu) writer -- opens directly in ParaView / VisIt."""
from __future__ import annotations

import base64
import os
from typing import Dict, Optional

import numpy as np


def write_vtu(path: str, mesh, point_data: Optional[Dict[str, np.ndarray]] = None,
              cell_data: Optional[Dict[str, np.ndarray]] = None) -> str:
    """Write an unstructured tetrahedral grid with optional data arrays."""
    pts = np.asarray(mesh.nodes, float)
    cells = np.asarray(mesh.tets, np.int64)
    n_p, n_c = len(pts), len(cells)
    out = [
        '<?xml version="1.0"?>',
        '<VTKFile type="UnstructuredGrid" version="0.1" byte_order="LittleEndian">',
        "  <UnstructuredGrid>",
        f'    <Piece NumberOfPoints="{n_p}" NumberOfCells="{n_c}">',
        "      <Points>",
        '        <DataArray type="Float64" NumberOfComponents="3" format="ascii">',
        "          " + " ".join(f"{v:.9g}" for v in pts.ravel()),
        "        </DataArray>",
        "      </Points>",
        "      <Cells>",
        '        <DataArray type="Int64" Name="connectivity" format="ascii">',
        "          " + " ".join(str(int(v)) for v in cells.ravel()),
        "        </DataArray>",
        '        <DataArray type="Int64" Name="offsets" format="ascii">',
        "          " + " ".join(str(4 * (i + 1)) for i in range(n_c)),
        "        </DataArray>",
        '        <DataArray type="UInt8" Name="types" format="ascii">',
        "          " + " ".join("10" for _ in range(n_c)),
        "        </DataArray>",
        "      </Cells>",
    ]
    out += _data_block("PointData", point_data)
    out += _data_block("CellData", cell_data)
    out += ["    </Piece>", "  </UnstructuredGrid>", "</VTKFile>"]
    with open(path, "w") as fh:
        fh.write("\n".join(out))
    return path


def _data_block(tag: str, data):
    if not data:
        return []
    out = [f"      <{tag}>"]
    for name, arr in data.items():
        a = np.asarray(arr)
        nc = 1 if a.ndim == 1 else a.shape[1]
        dt = "Int32" if np.issubdtype(a.dtype, np.integer) else "Float64"
        out.append(f'        <DataArray type="{dt}" Name="{name}" '
                   f'NumberOfComponents="{nc}" format="ascii">')
        out.append("          " + " ".join(
            (str(int(v)) if dt == "Int32" else f"{float(v):.9g}")
            for v in a.ravel()))
        out.append("        </DataArray>")
    out.append(f"      </{tag}>")
    return out


__all__ = ["write_vtu"]
