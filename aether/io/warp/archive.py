"""``.warpz`` support -- the zipped form of an Warps project."""
from __future__ import annotations

import io
import os
import zipfile
from typing import Tuple

from .lexer import ENCODINGS


def read_warpz(path: str) -> Tuple[str, str, str]:
    """Extract the project text from a ``.warpz`` archive."""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".warp")]
        if not names:
            raise ValueError(f"{path}: archive contains no .warp member")
        names.sort(key=len)
        data = z.read(names[0])
    from .lexer import decode_bytes
    return decode_bytes(data)


def write_warpz(path: str, text: str, encoding: str = "utf-8",
                member: str | None = None, cad_folder: str | None = None) -> str:
    """Write project *text* into a fresh ``.warpz`` archive."""
    member = member or (os.path.splitext(os.path.basename(path))[0] + ".warp")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, text.encode(encoding))
        if cad_folder and os.path.isdir(cad_folder):
            for name in sorted(os.listdir(cad_folder)):
                source = os.path.join(cad_folder, name)
                if os.path.isfile(source):
                    z.write(source, os.path.basename(cad_folder) + "/" + name)
    return path


__all__ = ["read_warpz", "write_warpz"]
