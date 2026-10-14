"""
Environment preflight and diagnosis.

This module is imported before anything else in the package and **must not
import numpy, scipy or any other third-party package** — its whole job is to
explain clearly what went wrong when those imports are impossible.

The failure it exists for is the one that produces the least useful error
message in the wild: a console script created by one Python interpreter
picking up another interpreter's ``site-packages``. NumPy's own message in
that case ("you should not try to import numpy from its source directory")
points at the wrong thing entirely, so the user is left staring at a wall of
traceback that names neither the real cause nor the fix.
"""
from __future__ import annotations

import glob
import os
import re
import sys
import sysconfig
from typing import Dict, List, Optional, Tuple

# Minimum versions that actually ship wheels for a given Python.
#   NumPy 2.4.0 was the first release supporting Python 3.14; 2.1 covers 3.13.
#   SciPy 1.16.1 was the first stable release with Python 3.14 binaries.
MIN_FOR_PYTHON = {
    (3, 14): {"numpy": "2.4", "scipy": "1.16.1"},
    (3, 13): {"numpy": "2.1", "scipy": "1.14.1"},
}
BASELINE = {"numpy": "1.24", "scipy": "1.10"}

REQUIRED = ("numpy", "scipy")


class AetherEnvironmentError(ImportError):
    """Raised when the Python environment cannot support Aether-EM."""


# --------------------------------------------------------------------------
# facts about the running interpreter
# --------------------------------------------------------------------------


def _pyver() -> Tuple[int, int]:
    return sys.version_info[:2]


def _ext_tag() -> str:
    """The C-extension ABI tag this interpreter can load, e.g. ``cp314``."""
    tag = sysconfig.get_config_var("EXT_SUFFIX") or ""
    m = re.search(r"cp(\d{2,3})", tag)
    if m:
        return "cp" + m.group(1)
    return "cp%d%d" % _pyver()


_VER_DIR = re.compile(r"python[\\/ ]?(\d)[.\\/]?(\d{1,2})", re.I)


def _version_in_path(path: str) -> Optional[Tuple[int, int]]:
    """Guess the interpreter version a site-packages path belongs to."""
    m = _VER_DIR.search(path.replace("\\", "/"))
    if not m:
        return None
    try:
        return int(m.group(1)), int(m.group(2))
    except ValueError:                                    # pragma: no cover
        return None


def locate(pkg: str) -> Optional[str]:
    """Find *pkg* on ``sys.path`` without importing it."""
    for entry in sys.path:
        if not entry:
            entry = os.getcwd()
        cand = os.path.join(entry, pkg, "__init__.py")
        if os.path.isfile(cand):
            return os.path.dirname(cand)
    return None


def package_version(pkg_dir: str, pkg: str) -> Optional[str]:
    """Read a package's version from its metadata, without importing it."""
    parent = os.path.dirname(pkg_dir)
    for pat in (f"{pkg}-*.dist-info", f"{pkg}-*.egg-info"):
        for info in glob.glob(os.path.join(parent, pat)):
            meta = os.path.join(info, "METADATA")
            if not os.path.isfile(meta):
                meta = os.path.join(info, "PKG-INFO")
            try:
                with open(meta, "r", errors="replace") as fh:
                    for line in fh:
                        if line.startswith("Version:"):
                            return line.split(":", 1)[1].strip()
            except OSError:                               # pragma: no cover
                pass
    v = os.path.join(pkg_dir, "version.py")
    if os.path.isfile(v):
        try:
            with open(v, "r", errors="replace") as fh:
                m = re.search(r'version\s*=\s*["\']([^"\']+)', fh.read())
                if m:
                    return m.group(1)
        except OSError:                                   # pragma: no cover
            pass
    return None


def foreign_extension_tags(pkg_dir: str, limit: int = 400) -> List[str]:
    """ABI tags of the compiled extensions actually present in *pkg_dir*."""
    tags = set()
    n = 0
    for root, _dirs, files in os.walk(pkg_dir):
        for f in files:
            if not f.endswith((".pyd", ".so")):
                continue
            m = re.search(r"\.(cp\d{2,3})[-.]", f)
            if m:
                tags.add(m.group(1))
            n += 1
            if n > limit:
                return sorted(tags)
    return sorted(tags)


def _vtuple(v: str) -> Tuple[int, ...]:
    """Numeric release tuple; pre-release suffixes are ignored ('2.4.0rc1')."""
    out: List[int] = []
    for part in re.split(r"[.\-+_]", str(v)):
        m = re.match(r"\d+", part)
        if not m:
            break
        out.append(int(m.group(0)))
        if m.end() != len(part):
            break                      # '0rc1' -> 0, then stop
    return tuple(out) or (0,)


def _too_old(pkg: str, version: Optional[str]) -> Optional[str]:
    """Return the required minimum if *version* is below it."""
    need = MIN_FOR_PYTHON.get(_pyver(), {}).get(pkg, BASELINE[pkg])
    if version and _vtuple(version) < _vtuple(need):
        return need
    return None


# --------------------------------------------------------------------------
# diagnosis
# --------------------------------------------------------------------------


def probe() -> Dict[str, dict]:
    """Inspect every required package without importing it."""
    me = _pyver()
    tag = _ext_tag()
    out: Dict[str, dict] = {}
    for pkg in REQUIRED:
        d = locate(pkg)
        info = {"path": d, "version": None, "foreign_python": None,
                "ext_tags": [], "abi_mismatch": False, "needs": None,
                "importable": False, "error": None}
        if d:
            info["version"] = package_version(d, pkg)
            v = _version_in_path(d)
            if v and v != me:
                info["foreign_python"] = v
            info["ext_tags"] = foreign_extension_tags(d)
            if info["ext_tags"] and tag not in info["ext_tags"]:
                info["abi_mismatch"] = True
            info["needs"] = _too_old(pkg, info["version"])
        try:
            __import__(pkg)
            info["importable"] = True
        except BaseException as exc:                      # noqa: BLE001
            info["error"] = f"{type(exc).__name__}: {exc}".split("\n")[0][:220]
        out[pkg] = info
    return out


def pythonpath_conflicts() -> List[str]:
    """Entries of PYTHONPATH that belong to a different Python version."""
    me = _pyver()
    bad = []
    for entry in (os.environ.get("PYTHONPATH", "") or "").split(os.pathsep):
        if not entry.strip():
            continue
        v = _version_in_path(entry)
        if v and v != me:
            bad.append(entry)
    return bad


def report(probe_result: Optional[Dict[str, dict]] = None) -> str:
    """A complete, human-readable environment report."""
    p = probe_result if probe_result is not None else probe()
    me = _pyver()
    L: List[str] = []
    add = L.append
    add("Aether-EM environment report")
    add("=" * 60)
    add(f"  Python            : {sys.version.split()[0]}  ({sys.executable})")
    add(f"  Extension ABI tag : {_ext_tag()}")
    add(f"  Virtual env       : "
        f"{'yes — ' + sys.prefix if sys.prefix != sys.base_prefix else 'no (system interpreter)'}")
    pp = os.environ.get("PYTHONPATH", "")
    add(f"  PYTHONPATH        : {pp if pp else '(not set)'}")
    home = os.environ.get("PYTHONHOME", "")
    if home:
        add(f"  PYTHONHOME        : {home}")
    add("")
    for pkg, info in p.items():
        add(f"  {pkg}")
        add(f"    found     : {info['path'] or '(not on sys.path)'}")
        add(f"    version   : {info['version'] or 'unknown'}")
        if info["ext_tags"]:
            add(f"    built for : {', '.join(info['ext_tags'])}")
        add(f"    imports   : {'yes' if info['importable'] else 'NO — ' + str(info['error'])}")
    return "\n".join(L)


def problems(probe_result: Optional[Dict[str, dict]] = None) -> List[dict]:
    """
    Every environment problem found, most-blocking first.

    Each entry is ``{code, detail, fix}`` so callers can render it however
    they like (console script, GUI message manager, test assertion).
    """
    p = probe_result if probe_result is not None else probe()
    me = _pyver()
    mestr = "%d.%d" % me
    out: List[dict] = []

    conflicts = pythonpath_conflicts()
    if conflicts:
        out.append({
            "code": "pythonpath-cross-version",
            "detail": ("PYTHONPATH points at another Python's packages:\n    "
                       + "\n    ".join(conflicts)),
            "fix": ("Clear it for this shell and try again.\n"
                    "    Windows (cmd)        :  set PYTHONPATH=\n"
                    "    Windows (PowerShell) :  $env:PYTHONPATH=''\n"
                    "    macOS / Linux        :  unset PYTHONPATH\n"
                    "  To clear it permanently on Windows, remove PYTHONPATH from\n"
                    "  System Properties > Environment Variables."),
        })

    for pkg, info in p.items():
        if info["importable"]:
            if info["needs"]:
                out.append({
                    "code": f"{pkg}-too-old",
                    "detail": (f"{pkg} {info['version']} is older than the first "
                               f"release supporting Python {mestr} "
                               f"({pkg} {info['needs']})."),
                    "fix": f'  "{sys.executable}" -m pip install -U "{pkg}>={info["needs"]}"',
                })
            continue

        if info["path"] is None:
            out.append({
                "code": f"{pkg}-missing",
                "detail": f"{pkg} is not installed for this interpreter.",
                "fix": f'  "{sys.executable}" -m pip install "{pkg}"',
            })
            continue

        if info["foreign_python"]:
            fv = "%d.%d" % info["foreign_python"]
            out.append({
                "code": f"{pkg}-foreign-interpreter",
                "detail": (f"{pkg} was loaded from a Python {fv} installation "
                           f"while you are running Python {mestr}:\n    "
                           f"{info['path']}\n"
                           f"  Compiled extensions cannot be shared between "
                           f"Python versions, so this can never work."),
                "fix": ("Stop the cross-version leak, then install into THIS "
                        "interpreter:\n"
                        "    set PYTHONPATH=            (see above)\n"
                        f'    "{sys.executable}" -m pip install '
                        f'"{pkg}>={_too_old(pkg, "0") or BASELINE[pkg]}"'),
            })
        elif info["abi_mismatch"]:
            out.append({
                "code": f"{pkg}-abi-mismatch",
                "detail": (f"{pkg} contains extensions built for "
                           f"{', '.join(info['ext_tags'])}, but this "
                           f"interpreter loads {_ext_tag()}."),
                "fix": f'  "{sys.executable}" -m pip install --force-reinstall "{pkg}"',
            })
        else:
            need = _too_old(pkg, info["version"]) or BASELINE[pkg]
            out.append({
                "code": f"{pkg}-broken",
                "detail": (f"{pkg} is present but will not import:\n    "
                           f"{info['error']}"),
                "fix": f'  "{sys.executable}" -m pip install --force-reinstall "{pkg}>={need}"',
            })
    return out


def _alternatives() -> List[str]:
    """Other Python installations on this machine that might be usable."""
    found = []
    if os.name == "nt":
        import subprocess
        try:
            r = subprocess.run(["py", "-0p"], capture_output=True, text=True,
                               timeout=6)
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if line.startswith("-"):
                    found.append(line)
        except Exception:                                 # pragma: no cover
            pass
    return found


def format_failure(probs: List[dict]) -> str:
    """Render the problems as the message a user actually reads."""
    me = "%d.%d" % _pyver()
    L = ["",
         "Aether-EM cannot start: this Python environment is not usable.",
         "=" * 68,
         f"  Running Python {sys.version.split()[0]}",
         f"          from   {sys.executable}",
         ""]
    for i, pr in enumerate(probs, 1):
        L.append(f"  [{i}] {pr['detail']}")
        L.append("")
        L.append("      Fix:")
        for line in pr["fix"].splitlines():
            L.append("      " + line.rstrip())
        L.append("")
    L.append("  Cleanest option — a virtual environment, which cannot pick up")
    L.append("  another interpreter's packages:")
    L.append("")
    if os.name == "nt":
        L.append(f'      "{sys.executable}" -m venv .venv')
        L.append("      .venv\\Scripts\\activate")
        L.append("      set PYTHONPATH=")
        L.append('      pip install -e ".[all]"')
    else:
        L.append(f'      "{sys.executable}" -m venv .venv')
        L.append("      source .venv/bin/activate")
        L.append("      unset PYTHONPATH")
        L.append('      pip install -e ".[all]"')
    alts = _alternatives()
    if alts:
        L.append("")
        L.append("  Python installations found on this machine:")
        for a in alts:
            L.append("      " + a)
    L.append("")
    L.append("  Full details:  aether-doctor")
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------
# entry points
# --------------------------------------------------------------------------


def environment_error() -> Optional["AetherEnvironmentError"]:
    """
    ``None`` when the scientific stack loads; otherwise the diagnosis.

    Returned rather than raised so that :mod:`aether` stays importable in a
    broken environment — which is exactly when ``aether doctor`` has to work.
    Touching any real API then raises this error instead of a nested traceback
    that blames the wrong component.
    """
    if os.environ.get("AETHER_SKIP_PREFLIGHT"):
        return None
    try:
        import numpy  # noqa: F401
        import scipy  # noqa: F401
        return None
    except BaseException as exc:                          # noqa: BLE001
        probs = problems()
        if not probs:
            probs = [{"code": "unknown",
                      "detail": f"the scientific stack failed to import:\n    "
                                f"{type(exc).__name__}: {exc}",
                      "fix": f'  "{sys.executable}" -m pip install '
                             f'--force-reinstall numpy scipy'}]
        return AetherEnvironmentError(format_failure(probs))


def check() -> None:
    """Raise if the environment is unusable (see :func:`environment_error`)."""
    err = environment_error()
    if err is not None:
        raise err


def main(argv: Optional[List[str]] = None) -> int:
    """``aether-doctor`` — print the environment report and any problems."""
    p = probe()
    print(report(p))
    probs = problems(p)
    print()
    if not probs:
        ok = all(i["importable"] for i in p.values())
        print("  No problems found." if ok else
              "  Imports fail for an unknown reason.")
        try:
            import aether
            if getattr(aether, "ENV_ERROR", None) is not None:
                print(str(aether.ENV_ERROR))
                return 1
            print(f"  Aether-EM {aether.__version__} imports cleanly.")
        except Exception as exc:
            print(f"  Aether-EM failed to import: {exc}")
            return 1
        return 0
    print(format_failure(probs))
    return 1


if __name__ == "__main__":                                # pragma: no cover
    sys.exit(main())
