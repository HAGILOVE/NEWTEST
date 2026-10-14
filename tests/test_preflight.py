"""
Environment preflight: the diagnosis shown when Python cannot load the stack.

The failure being guarded against is the one with the worst native error
message — a console script created by one interpreter picking up another
interpreter's ``site-packages``. NumPy's own advice in that situation
("you should not try to import numpy from its source directory") is wrong,
so these tests assert that Aether names the real cause and the real fix.
"""
import os
import subprocess
import sys
import textwrap

import pytest

from aether import _preflight as pf
from aether.version import __version__

WIN_312 = os.path.join("C:\\", "Users", "USER", "AppData", "Local",
                       "Programs", "Python", "Python312", "Lib",
                       "site-packages")


# ------------------------------------------------------------- primitives
@pytest.mark.parametrize("path,expect", [
    (WIN_312, (3, 12)),
    ("/usr/lib/python3.9/site-packages", (3, 9)),
    ("/opt/Python3.14/lib", (3, 14)),
    ("C:\\Python314\\Lib\\site-packages", (3, 14)),
    ("/home/me/project/src", None),
])
def test_interpreter_version_is_recovered_from_a_path(path, expect):
    assert pf._version_in_path(path) == expect


def test_extension_tag_matches_the_running_interpreter():
    assert pf._ext_tag() == "cp%d%d" % sys.version_info[:2]


def test_version_comparison_handles_real_release_strings():
    assert pf._vtuple("1.26.4") < pf._vtuple("2.4")
    assert pf._vtuple("2.4.0") < pf._vtuple("2.5.2")
    assert pf._vtuple("1.16.1") > pf._vtuple("1.14.1")
    assert pf._vtuple("2.4.0rc1") == (2, 4, 0)


def test_minimum_versions_track_wheel_availability():
    """NumPy 2.4 / SciPy 1.16.1 were the first releases to ship 3.14 wheels."""
    assert pf.MIN_FOR_PYTHON[(3, 14)]["numpy"] == "2.4"
    assert pf.MIN_FOR_PYTHON[(3, 14)]["scipy"] == "1.16.1"
    assert pf.MIN_FOR_PYTHON[(3, 13)]["numpy"] == "2.1"


def test_healthy_environment_reports_no_problems():
    p = pf.probe()
    assert p["numpy"]["importable"] and p["scipy"]["importable"]
    assert pf.problems(p) == []
    r = pf.report(p)
    assert "numpy" in r and "Extension ABI tag" in r


# ------------------------------------------------- synthetic broken stacks
def _fake_numpy(tmp_path, version="1.26.4", abi="cp312", win_style=True):
    """A site-packages tree that looks like another interpreter's numpy."""
    root = tmp_path / ("Python312" if win_style else "python3.12") / \
        "Lib" / "site-packages"
    pkg = root / "numpy"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        "raise ImportError('No module named "
        "\\'numpy.core._multiarray_umath\\'')\n")
    core = pkg / "core"
    core.mkdir()
    (core / "__init__.py").write_text("")
    (core / f"_multiarray_umath.{abi}-win_amd64.pyd").write_bytes(b"\0")
    info = root / f"numpy-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Name: numpy\nVersion: {version}\n")
    return root


def test_cross_version_numpy_is_identified(tmp_path, monkeypatch):
    root = _fake_numpy(tmp_path)
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.setitem(sys.modules, "numpy", None)
    info = {"path": str(root / "numpy"), "version": "1.26.4",
            "importable": False,
            "error": "ImportError: No module named 'numpy.core._multiarray_umath'",
            "foreign_python": (3, 12), "ext_tags": ["cp312"],
            "abi_mismatch": True, "needs": None}
    probs = pf.problems({"numpy": info, "scipy": dict(info, importable=True,
                                                      foreign_python=None)})
    codes = [p["code"] for p in probs]
    assert "numpy-foreign-interpreter" in codes
    p = probs[codes.index("numpy-foreign-interpreter")]
    assert "Python 3.12" in p["detail"]
    assert "Compiled extensions cannot be shared" in p["detail"]
    assert "pip install" in p["fix"]


def test_pythonpath_cross_version_is_flagged(monkeypatch):
    other = (3, 12) if sys.version_info[:2] != (3, 12) else (3, 11)
    monkeypatch.setenv("PYTHONPATH",
                       f"C:\\Python{other[0]}{other[1]}\\Lib\\site-packages")
    bad = pf.pythonpath_conflicts()
    assert len(bad) == 1
    probs = pf.problems({"numpy": {"path": None, "importable": True,
                                   "version": "2.4", "needs": None,
                                   "foreign_python": None, "ext_tags": [],
                                   "abi_mismatch": False, "error": None},
                         "scipy": {"path": None, "importable": True,
                                   "version": "1.17", "needs": None,
                                   "foreign_python": None, "ext_tags": [],
                                   "abi_mismatch": False, "error": None}})
    assert probs[0]["code"] == "pythonpath-cross-version"
    fix = probs[0]["fix"]
    assert "set PYTHONPATH=" in fix and "unset PYTHONPATH" in fix


def test_pythonpath_of_the_same_version_is_not_flagged(monkeypatch):
    me = "%d.%d" % sys.version_info[:2]
    monkeypatch.setenv("PYTHONPATH", f"/opt/python{me}/site-packages")
    assert pf.pythonpath_conflicts() == []


def test_too_old_for_this_python_is_detected(monkeypatch):
    monkeypatch.setattr(pf, "_pyver", lambda: (3, 14))
    info = {"path": "/x/numpy", "version": "1.26.4", "importable": True,
            "error": None, "foreign_python": None, "ext_tags": [],
            "abi_mismatch": False, "needs": pf._too_old("numpy", "1.26.4")}
    probs = pf.problems({"numpy": info,
                         "scipy": dict(info, version="1.18", needs=None)})
    assert probs[0]["code"] == "numpy-too-old"
    assert "2.4" in probs[0]["detail"] and "3.14" in probs[0]["detail"]


def test_missing_package_is_reported():
    info = {"path": None, "version": None, "importable": False,
            "error": "ModuleNotFoundError", "foreign_python": None,
            "ext_tags": [], "abi_mismatch": False, "needs": None}
    probs = pf.problems({"numpy": info, "scipy": dict(info, importable=True)})
    assert probs[0]["code"] == "numpy-missing"


def test_failure_message_is_actionable():
    probs = [{"code": "x", "detail": "something is wrong",
              "fix": "  do the thing"}]
    msg = pf.format_failure(probs)
    assert "cannot start" in msg
    assert "something is wrong" in msg and "do the thing" in msg
    assert "venv" in msg                       # always offers the clean route
    assert "aether-doctor" in msg
    assert sys.executable in msg               # names the actual interpreter


# ------------------------------------------------------- end-to-end guard
def _broken_env(tmp_path):
    root = _fake_numpy(tmp_path)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env.pop("AETHER_SKIP_PREFLIGHT", None)
    return env


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_package_stays_importable_so_the_doctor_can_run(tmp_path):
    """A broken stack must not make the package unimportable — that is
    precisely when the diagnosis has to be reachable."""
    r = subprocess.run(
        [sys.executable, "-c",
         "import aether; print('ENV_ERROR', aether.ENV_ERROR is not None); "
         "print('VERSION', aether.__version__)"],
        capture_output=True, text=True, env=_broken_env(tmp_path), cwd=REPO)
    assert r.returncode == 0, r.stderr
    assert "ENV_ERROR True" in r.stdout
    assert f"VERSION {__version__}" in r.stdout


def test_touching_the_api_raises_the_diagnosis_not_a_numpy_traceback(tmp_path):
    r = subprocess.run(
        [sys.executable, "-c", "import aether; aether.Design('x')"],
        capture_output=True, text=True, env=_broken_env(tmp_path), cwd=REPO)
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "Aether-EM cannot start" in out
    assert "AetherEnvironmentError" in out
    assert "Python 3.12" in out                       # names the foreign tree
    assert "PYTHONPATH" in out                        # names the mechanism
    assert "aether-doctor" in out
    # numpy's misleading advice must not be the last thing the user reads
    assert out.rindex("Aether-EM cannot start") > out.rfind("source directory")


def test_cli_prints_the_diagnosis_without_a_traceback(tmp_path):
    r = subprocess.run([sys.executable, "-m", "aether.cli", "gui"],
                       capture_output=True, text=True,
                       env=_broken_env(tmp_path), cwd=REPO)
    assert r.returncode == 2
    out = r.stdout + r.stderr
    assert "Aether-EM cannot start" in out
    assert "Traceback" not in out                     # no wall of traceback
    assert "aether-doctor" in out


def test_doctor_runs_and_exits_zero_on_a_healthy_environment():
    r = subprocess.run([sys.executable, "-m", "aether._preflight"],
                       capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(
                           os.path.abspath(__file__))))
    assert r.returncode == 0
    assert "No problems found" in r.stdout
    assert f"Aether-EM {__version__} imports cleanly" in r.stdout


def test_doctor_diagnoses_a_broken_stack_instead_of_crashing(tmp_path):
    r = subprocess.run([sys.executable, "-m", "aether._preflight"],
                       capture_output=True, text=True,
                       env=_broken_env(tmp_path), cwd=REPO)
    assert r.returncode == 1
    assert "numpy" in r.stdout and "1.26.4" in r.stdout
    assert "cannot start" in r.stdout


def test_doctor_subcommand_works_in_a_broken_environment(tmp_path):
    """`aether doctor` must run when `aether gui` cannot."""
    r = subprocess.run([sys.executable, "-m", "aether.cli", "doctor"],
                       capture_output=True, text=True,
                       env=_broken_env(tmp_path), cwd=REPO)
    assert r.returncode == 1
    assert "environment report" in r.stdout
    assert "1.26.4" in r.stdout


def test_preflight_can_be_bypassed_for_debugging(tmp_path):
    env = dict(os.environ)
    env["AETHER_SKIP_PREFLIGHT"] = "1"
    r = subprocess.run([sys.executable, "-c",
                        "from aether._preflight import check; check(); print('ok')"],
                       capture_output=True, text=True, env=env,
                       cwd=os.path.dirname(os.path.dirname(
                           os.path.abspath(__file__))))
    assert r.returncode == 0 and "ok" in r.stdout
