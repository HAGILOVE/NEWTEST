"""
File-system browsing for the workspace's open/save dialogs.

The workspace runs on your own machine, so the file dialogs browse your real
disk. Two routes are offered, and both end at the same place:

* the **in-app browser** — a themed dialog served by this module's listing
  API. It always works, looks like the rest of the application, and behaves
  identically on every platform;
* the **native dialog** — the operating system's own picker, opened through
  tkinter in a short-lived subprocess. A GUI toolkit cannot be driven from a
  worker thread on Windows, and a crash inside it must not take the server
  down, so it never runs in-process.

Listing is read-only and every entry is stat-ed defensively: an unreadable
directory or a dangling symlink degrades to a skipped row, never an exception
that empties the dialog.
"""
from __future__ import annotations

import json
import os
import string
import subprocess
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ..core.logging import get_logger

log = get_logger("gui.files")

# Filters offered by each dialog, as (label, [extensions]).
FILTERS: Dict[str, List[Tuple[str, List[str]]]] = {
    "project": [("AEDT project (*.aedt, *.aedtz)", [".aedt", ".aedtz"]),
                ("All files", [])],
    "cad": [("All CAD files", [".step", ".stp", ".iges", ".igs", ".brep",
                               ".brp", ".stl", ".obj", ".dxf"]),
            ("STEP (*.step, *.stp)", [".step", ".stp"]),
            ("IGES (*.iges, *.igs)", [".iges", ".igs"]),
            ("AutoCAD DXF (*.dxf)", [".dxf"]),
            ("BREP (*.brep)", [".brep", ".brp"]),
            ("STL / OBJ", [".stl", ".obj"]),
            ("All files", [])],
    "touchstone": [("Touchstone (*.sNp, *.ts)",
                    [".s1p", ".s2p", ".s3p", ".s4p", ".s5p", ".s6p", ".ts"]),
                   ("All files", [])],
    "csv": [("CSV (*.csv)", [".csv"]), ("All files", [])],
    "html": [("HTML report (*.html)", [".html", ".htm"]), ("All files", [])],
    "vtk": [("VTK unstructured grid (*.vtu)", [".vtu"]), ("All files", [])],
    "cadstep": [("STEP geometry (*.step)", [".step", ".stp"])],
    "cadstl": [("STL surface (*.stl)", [".stl"])],
    "any": [("All files", [])],
}


def filters(kind: str) -> List[dict]:
    return [{"label": lab, "ext": ext}
            for lab, ext in FILTERS.get(kind, FILTERS["any"])]


# --------------------------------------------------------------------------
# places and roots
# --------------------------------------------------------------------------


def drives() -> List[str]:
    """Mounted drive letters on Windows; empty elsewhere."""
    if os.name != "nt":
        return []
    out = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if os.path.exists(root):
            out.append(root)
    return out


def places() -> List[dict]:
    """Shortcuts shown down the left of the dialog."""
    home = os.path.expanduser("~")
    out: List[dict] = [{"name": "Home", "path": home, "kind": "home"}]
    for label in ("Desktop", "Documents", "Downloads"):
        p = os.path.join(home, label)
        if os.path.isdir(p):
            out.append({"name": label, "path": p, "kind": "folder"})
    cwd = os.getcwd()
    if os.path.isdir(cwd):
        out.append({"name": "Working folder", "path": cwd, "kind": "folder"})
    for d in drives():
        out.append({"name": d.rstrip("\\/"), "path": d, "kind": "drive"})
    if os.name != "nt":
        out.append({"name": "Filesystem root", "path": os.sep, "kind": "drive"})
    seen, uniq = set(), []
    for p in out:
        key = os.path.normcase(os.path.abspath(p["path"]))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def default_dir(hint: str = "") -> str:
    """Where a dialog should open when nothing better is known."""
    for cand in (os.path.dirname(hint) if hint else "", os.getcwd(),
                 os.path.expanduser("~")):
        if cand and os.path.isdir(cand):
            return os.path.abspath(cand)
    return os.path.abspath(os.sep)


def breadcrumbs(path: str) -> List[dict]:
    """Clickable path segments, from the root down to *path*."""
    path = os.path.abspath(path)
    parts: List[dict] = []
    head = path
    while True:
        parent = os.path.dirname(head)
        name = os.path.basename(head)
        if not name:
            parts.append({"name": head or os.sep, "path": head or os.sep})
            break
        parts.append({"name": name, "path": head})
        if parent == head:
            break
        head = parent
    return list(reversed(parts))


# --------------------------------------------------------------------------
# listing
# --------------------------------------------------------------------------


def _match(name: str, exts: Sequence[str]) -> bool:
    if not exts:
        return True
    low = name.lower()
    return any(low.endswith(e) for e in exts)


def list_dir(path: str = "", exts: Optional[Sequence[str]] = None,
             show_hidden: bool = False) -> dict:
    """
    One directory's contents, ready for the dialog.

    Never raises for an unreadable directory: the error is reported in the
    payload so the dialog can show it in place and stay usable.
    """
    target = os.path.abspath(os.path.expanduser(path or default_dir()))
    # A path that names a file is reported as such (with its folder listed),
    # so a pasted full path can be accepted in one step instead of being
    # silently turned into a directory listing.
    is_file = os.path.isfile(target)
    file_path = target if is_file else ""
    if not os.path.isdir(target):
        parent = os.path.dirname(target)
        target = parent if os.path.isdir(parent) else default_dir()

    dirs: List[dict] = []
    files: List[dict] = []
    error = ""
    try:
        with os.scandir(target) as it:
            for entry in it:
                name = entry.name
                if not show_hidden and (name.startswith(".")
                                        or _is_hidden(entry)):
                    continue
                try:
                    is_dir = entry.is_dir()
                    st = entry.stat()
                    size, mtime = (0 if is_dir else st.st_size), st.st_mtime
                except OSError:
                    is_dir, size, mtime = False, 0, 0.0
                row = {"name": name, "path": os.path.join(target, name),
                       "dir": bool(is_dir), "size": int(size),
                       "mtime": float(mtime)}
                if is_dir:
                    dirs.append(row)
                elif _match(name, exts or []):
                    files.append(row)
    except PermissionError:
        error = "Permission denied"
    except OSError as exc:
        error = str(exc)

    key = lambda r: r["name"].lower()          # noqa: E731
    parent = os.path.dirname(target)
    return {
        "path": target,
        "parent": parent if parent and parent != target else "",
        "crumbs": breadcrumbs(target),
        "dirs": sorted(dirs, key=key),
        "files": sorted(files, key=key),
        "error": error,
        "isFile": is_file,
        "filePath": file_path,
        "sep": os.sep,
        "writable": os.access(target, os.W_OK),
    }


def _is_hidden(entry) -> bool:
    if os.name != "nt":
        return False
    try:
        import stat
        return bool(entry.stat().st_file_attributes
                    & stat.FILE_ATTRIBUTE_HIDDEN)          # type: ignore[attr-defined]
    except Exception:
        return False


def resolve_save_path(directory: str, filename: str,
                      exts: Optional[Sequence[str]] = None) -> dict:
    """Join and validate a save target, appending the default extension."""
    directory = os.path.abspath(os.path.expanduser(directory or default_dir()))
    name = (filename or "").strip().strip('"')
    if not name:
        return {"ok": False, "error": "Enter a file name."}
    if os.path.isabs(name) or os.sep in name or (os.altsep and os.altsep in name):
        full = os.path.abspath(os.path.join(directory, os.path.expanduser(name)))
        directory = os.path.dirname(full)
        name = os.path.basename(full)
    if not os.path.splitext(name)[1] and exts:
        name += exts[0]
    full = os.path.join(directory, name)
    parent = os.path.dirname(full)
    if os.path.isdir(full):
        return {"ok": False, "error": "The target is a folder, not a file."}
    if not os.path.isdir(parent):
        return {"ok": False, "error": f"Folder does not exist: {parent}"}
    if not os.access(parent, os.W_OK):
        return {"ok": False, "error": f"Folder is not writable: {parent}"}
    return {"ok": True, "path": full, "exists": os.path.isfile(full)}


# --------------------------------------------------------------------------
# native dialogs
# --------------------------------------------------------------------------

_NATIVE_SCRIPT = r"""
import json, sys
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception as exc:
    print(json.dumps({"ok": False, "error": "tkinter unavailable: %s" % exc}))
    raise SystemExit(0)
try:
    cfg = json.loads(sys.argv[1])
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    kw = dict(title=cfg.get("title") or "Select file",
              initialdir=cfg.get("initialdir") or None,
              filetypes=[tuple(f) for f in cfg.get("filetypes") or
                         [("All files", "*.*")]])
    if cfg.get("mode") == "save":
        kw["initialfile"] = cfg.get("initialfile") or ""
        kw["defaultextension"] = cfg.get("defaultextension") or ""
        path = filedialog.asksaveasfilename(**kw)
    else:
        path = filedialog.askopenfilename(**kw)
    root.destroy()
    print(json.dumps({"ok": True, "path": path or ""}))
except Exception as exc:
    print(json.dumps({"ok": False, "error": str(exc)}))
"""


def native_available() -> bool:
    """True when an OS file dialog can plausibly be opened."""
    if os.name != "nt" and not (os.environ.get("DISPLAY")
                                or sys.platform == "darwin"):
        return False
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def _tk_filetypes(kind: str) -> List[List[str]]:
    out = []
    for label, exts in FILTERS.get(kind, FILTERS["any"]):
        pattern = " ".join(f"*{e}" for e in exts) if exts else "*.*"
        out.append([label, pattern])
    return out


def native_dialog(mode: str = "open", kind: str = "any", title: str = "",
                  initialdir: str = "", initialfile: str = "",
                  timeout: float = 300.0) -> dict:
    """
    Open the operating system's own file dialog.

    Runs in a subprocess: a GUI toolkit cannot be started from one of the
    server's worker threads on Windows, and this way a failure inside the
    toolkit cannot take the workspace down with it.
    """
    if not native_available():
        return {"ok": False, "error": "no native file dialog on this system"}
    exts = FILTERS.get(kind, FILTERS["any"])[0][1]
    cfg = {"mode": mode, "title": title, "initialdir": initialdir or default_dir(),
           "initialfile": initialfile, "filetypes": _tk_filetypes(kind),
           "defaultextension": exts[0] if exts else ""}
    try:
        r = subprocess.run([sys.executable, "-c", _NATIVE_SCRIPT,
                            json.dumps(cfg)],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "the file dialog timed out"}
    except Exception as exc:                                # pragma: no cover
        return {"ok": False, "error": str(exc)}
    line = (r.stdout or "").strip().splitlines()
    if not line:
        return {"ok": False, "error": (r.stderr or "no response").strip()[:200]}
    try:
        return json.loads(line[-1])
    except json.JSONDecodeError:
        return {"ok": False, "error": line[-1][:200]}


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"                                    # pragma: no cover


__all__ = ["FILTERS", "filters", "places", "drives", "list_dir",
           "breadcrumbs", "default_dir", "resolve_save_path",
           "native_available", "native_dialog", "human_size"]
