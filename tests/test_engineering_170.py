"""Engineering workflow regressions, including real builtin FEM solves."""

import math
import threading
import time
from pathlib import Path
import numpy as np
import pytest
import aether as ae
from aether.core.constants import c0
from aether.gui.api import dispatch
from aether.gui.state import Session, SolveJob
from aether.gui.engineering import _clone, study_worker, metrics
from aether.parametric import Scope, make_primitive, rebuild, definition, walk
from aether.post.sparam import SParameters
from aether.fem.control import SolveCancelled
from conftest import needs_occ


def session():
    s = Session()
    s.new_project("Engineering")
    dispatch(
        s,
        "parameters.set",
        {"variables": {"W": "22.86mm", "H": "10.16mm", "L": "20mm"}},
    )
    dispatch(
        s,
        "modeler.draw",
        {"shape": "box", "name": "guide", "params": {"size": ["W", "H", "L"]}},
    )
    d = s.design
    d.add_wave_port("p1", axis="z", value=0)
    d.add_wave_port("p2", axis="z", value=".02m")
    d.assign_pec_outer()
    d.config.mesh.max_element_size = 0.004
    st = d.add_setup("S", "10GHz")
    st.add_sweep("Sw", points=["10GHz"])
    return s


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("2*W+1mm", 0.04672),
        ("sqrt(W*W)", 0.02286),
        ("W*sin(30deg)", 0.01143),
        ("max(W,H)", 0.02286),
        ("1e-3m", 0.001),
        ("1in", 0.0254),
        ("2mil", 0.0000508),
    ],
)
def test_dimension_expressions(expr, expected):
    assert Scope({"W": "22.86mm", "H": "W/2"}).length(expr) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expr",
    [
        "1mm+1GHz",
        "missing",
        "1foobar",
        '__import__("os")',
        "(1).__class__",
        "1/0",
        "1mm**99",
        "nan",
        "True",
    ],
)
def test_expression_rejects_invalid_or_unsafe(expr):
    with pytest.raises((ValueError, ZeroDivisionError)):
        Scope().length(expr)


def test_cycles_and_failed_rebuild_preserve_model():
    s = session()
    old = np.array(s.design.bounding_box())
    variables = dict(s.design.variables)
    with pytest.raises(ValueError):
        dispatch(s, "parameters.set", {"variables": {"W": "H", "H": "W"}})
    assert s.design.variables == variables and np.allclose(s.design.bounding_box(), old)
    with pytest.raises(ValueError):
        dispatch(s, "parameters.set", {"variables": {"W": "-2mm"}})
    assert np.allclose(s.design.bounding_box(), old)


def test_edit_variable_transform_and_undo():
    s = session()
    s.selection = ["guide"]
    dispatch(
        s, "modeler.transform", {"name": "guide", "op": "move", "params": {"dx": "5mm"}}
    )
    dispatch(s, "modeler.editPrimitive", {"params": {"size": ["W/2", "H", "L"]}})
    assert s.design.bounding_box()[1][0] == pytest.approx(0.01643)
    dispatch(s, "parameters.set", {"variables": {"W": "30mm"}})
    assert s.design.bounding_box()[1][0] == pytest.approx(0.02)
    dispatch(s, "edit.undo")
    assert s.design.bounding_box()[1][0] == pytest.approx(0.01643)


@pytest.mark.parametrize("ext", ["warp", "warpz"])
def test_parameters_and_solver_controls_survive_repeated_save(tmp_path, ext):
    s = session()
    path = str(tmp_path / ("변수 모델." + ext))
    dispatch(
        s,
        "analysis.setControls",
        {
            "meshSize": "3mm",
            "solver": "direct",
            "tolerance": 1e-9,
            "convergedPasses": 2,
        },
    )
    for w in ("24mm", "26mm"):
        dispatch(s, "parameters.set", {"variables": {"W": w}})
        dispatch(s, "project.save", {"path": path})
        dispatch(s, "project.open", {"path": path})
        assert s.design.variables["W"] == w
        assert s.design.bounding_box()[1][0] == pytest.approx(Scope().length(w))
        assert s.design.solids[0].shape._parametric["params"]["size"][0] == "W"
        assert s.design.config.mesh.max_element_size == pytest.approx(0.003)
        assert s.design.config.solver.linear_solver == "direct"
        assert s.design.config.solver.tol == pytest.approx(1e-9)
        assert s.design.config.adaptive.min_converged_passes == 2


@pytest.mark.parametrize(
    "kind,params",
    [
        ("box", {"size": ["W", "2mm", "3mm"]}),
        ("sphere", {"radius": "W"}),
        ("cylinder", {"radius": "W", "height": "3mm"}),
        ("cone", {"r1": "W", "r2": "0mm", "height": "3mm"}),
        ("torus", {"rMajor": "W", "rMinor": "1mm"}),
        ("rectangle", {"size": ["W", "2mm"], "plane": "yz"}),
    ],
)
def test_all_parametric_primitives_roundtrip_and_rebuild(tmp_path, kind, params):
    s = Session()
    s.new_project("Primitives")
    dispatch(s, "parameters.set", {"variables": {"W": "5mm"}})
    dispatch(s, "modeler.draw", {"shape": kind, "name": "part", "params": params})
    p = str(tmp_path / "p.warp")
    dispatch(s, "project.save", {"path": p})
    dispatch(s, "project.open", {"path": p})
    dispatch(s, "parameters.set", {"variables": {"W": "8mm"}})
    sh = (s.design.solids + s.design.sheets)[0].shape
    expected = make_primitive(kind, params, "part", {"W": "8mm"})
    assert np.allclose(sh.bounds(), expected.bounds())
    assert definition(sh)["kind"] == kind


def test_boolean_children_rebuild_after_save(tmp_path):
    s = session()
    d = s.design
    d.solids[0].shape = d.solids[0].shape - ae.Box(
        (0.001, 0.001, 0.001), (0.001, 0.001, 0.001)
    )
    p = str(tmp_path / "csg.warp")
    dispatch(s, "project.save", {"path": p})
    dispatch(s, "project.open", {"path": p})
    dispatch(s, "parameters.set", {"variables": {"W": "30mm"}})
    assert s.design.bounding_box()[1][0] == pytest.approx(0.03)
    assert any(
        getattr(sh, "_parametric", None) for sh in walk(s.design.solids[0].shape)
    )


def test_rectangle_definition_uses_actual_plane():
    sh = ae.Rectangle((0.001, 0.002, 0.003), (0.005, 0.006), "xz")
    spec = definition(sh)
    assert np.allclose(
        make_primitive("rectangle", spec["params"], "r").bounds(), sh.bounds()
    )


def test_analytic_bounds_under_rotation_and_scale():
    sh = ae.Sphere((0, 0, 0), 0.003).rotate((0, 0, 1), "45deg")
    assert np.allclose(sh.bounds(), [[-0.003] * 3, [0.003] * 3])
    cone = ae.Cone((0, 0, 0), 0.003, 0, 0.01)
    assert np.allclose(cone.bounds(), [[-0.003, -0.003, 0], [0.003, 0.003, 0.01]])
    torus = ae.Torus((0, 0, 0), 0.01, 0.002)
    assert np.allclose(
        torus.bounds(), [[-0.012, -0.012, -0.002], [0.012, 0.012, 0.002]]
    )
    cyl = ae.Cylinder((0, 0, 0), 0.002, 0.01).rotate((0, 1, 0), "90deg")
    assert np.allclose(
        cyl.bounds(), [[0, -0.002, -0.002], [0.01, 0.002, 0.002]], atol=1e-14
    )


def test_stl_export_units_selection_and_failure_preserves_target(tmp_path):
    s = session()
    p = tmp_path / "geometry.stl"
    dispatch(
        s, "modeler.exportCad", {"path": str(p), "names": ["guide"], "units": "mm"}
    )
    points = np.array(
        [
            [float(x) for x in line.split()[1:]]
            for line in p.read_text().splitlines()
            if line.startswith("vertex ")
        ]
    )
    assert np.allclose(points.min(axis=0), [0, 0, 0])
    assert np.allclose(points.max(axis=0), [22.86, 10.16, 20])
    original = p.read_bytes()
    with pytest.raises(ValueError):
        dispatch(s, "modeler.exportCad", {"path": str(p), "names": ["missing"]})
    assert p.read_bytes() == original


@needs_occ
def test_step_export_reimport_dimensions(tmp_path):
    from aether.geometry.brep_io import quick_bounds

    s = session()
    p = tmp_path / "model.step"
    dispatch(s, "modeler.exportCad", {"path": str(p)})
    assert np.allclose(quick_bounds(str(p)), s.design.bounding_box(), atol=2e-6)


@pytest.mark.parametrize("order,size", [(1, 0.004), (1, 0.0025), (2, 0.005)])
def test_builtin_fem_matches_analytic_wr90(order, size):
    s = session()
    d = s.design
    d.setups[0].basis_order = order
    d.config.mesh.max_element_size = size
    sol = d.solve(adaptive=False, backend="builtin", save_fields=False)
    beta = math.sqrt((2 * math.pi * 1e10 / c0) ** 2 - (math.pi / 0.02286) ** 2)
    phase_error = abs(
        np.degrees(np.angle(sol.sparams.s[0, 1, 0] / np.exp(-1j * beta * 0.02)))
    )
    assert phase_error < 0.5
    assert abs(sol.sparams.s[0, 0, 0]) < 0.001
    assert abs(sol.sparams.s[0, 1, 0]) == pytest.approx(1, abs=2e-4)
    assert sol.sparams.is_passive() and sol.sparams.is_reciprocal(1e-6)


def test_real_parameter_study_preserves_original_and_changes_response():
    s = session()
    before = s.design.snapshot()
    s.solution = object()
    oldsolution = s.solution
    s.job = SolveJob(running=True, freq_total=2)
    study_worker(s, _clone(s.design), "W", ["21mm", "24mm"], "S", "builtin", False)
    assert s.job.stage == "complete", s.job.error
    assert len(s.study_results) == 2 and s.job.freq_done == 2
    assert s.design.variables == before["variables"] and s.solution is oldsolution
    assert s.design.bounding_box()[1][0] == pytest.approx(0.02286)
    assert s.study_results[0]["s11Db"] != s.study_results[1]["s11Db"]
    assert s.design.mesh is None


def test_study_api_and_cancel_validation():
    s = session()
    with pytest.raises(ValueError):
        dispatch(s, "analysis.study", {"variable": "bad", "values": ["1mm"]})
    with pytest.raises(ValueError):
        dispatch(s, "analysis.study", {"variable": "W", "values": ["-1mm"]})
    assert not s.job.running
    dispatch(
        s,
        "analysis.study",
        {"variable": "W", "values": ["21mm"], "setup": "S", "backend": "builtin"},
    )
    deadline = time.monotonic() + 15
    while s.job.running and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not s.job.running and s.job.stage == "complete", s.job.error
    assert len(dispatch(s, "analysis.studyResults")["rows"]) == 1
    s.job.running = True
    dispatch(s, "analysis.cancel")
    assert s.cancel_event.is_set()


def test_cancelled_solve_and_study_never_return_fabricated_results():
    s = session()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(SolveCancelled):
        s.design.solve(backend="builtin", cancel=cancel)
    s.cancel_event.set()
    s.job = SolveJob(running=True)
    study_worker(s, _clone(s.design), "W", ["24mm"], "S", "builtin", False)
    assert s.job.stage == "cancelled" and not s.study_results and not s.job.running


def test_metrics_band_crossings_and_group_delay():
    f = np.array([1, 2, 3, 4, 5]) * 1e9
    db = np.array([-5, -15, -20, -15, -5])
    sp = SParameters(f, (10 ** (db / 20)).reshape(-1, 1, 1).astype(complex), 50)
    r = metrics(sp, threshold=-10, freq=3.1e9)
    assert r["minimumFrequency"] == 3e9 and r["marker"]["frequency"] == 3e9
    assert r["bands"][0]["start"] == pytest.approx(1.5e9)
    assert r["bands"][0]["stop"] == pytest.approx(4.5e9)
    assert not r["bands"][0]["clipped"]
    with pytest.raises(ValueError):
        SParameters(f[:1], sp.s[:1], 50).group_delay(1, 1)


def test_unsupported_physics_blocked_before_solve():
    s = session()
    s.design.solution_type = "driven_terminal"
    r = dispatch(s, "analysis.diagnostics")
    assert not r["ok"] and any("driven_modal" in e for e in r["errors"])
    with pytest.raises(ValueError):
        s.design.solve(backend="builtin")
    s.design.solution_type = "driven_modal"
    s.design.assign_boundary("NotImplemented", "pml", ae.PlaneSelector("x", 0))
    assert any("not implemented" in e for e in s.design.validate())


def test_air_region_size_assignments_and_undo():
    s = session()
    with pytest.raises(ValueError, match="outer-boundary"):
        dispatch(s, "modeler.airRegion", {"padding": "5mm"})
    assert len(s.design.solids) == 1
    s.design.boundaries.clear()
    dispatch(s, "modeler.airRegion", {"padding": "5mm"})
    assert len(s.design.solids) == 2
    assert np.allclose(
        s.design.bounding_box(), [[-0.005] * 3, [0.02786, 0.01516, 0.025]]
    )
    assert len([b for b in s.design.boundaries if b.btype == "radiation"]) == 6
    dispatch(s, "edit.undo")
    assert len(s.design.solids) == 1


def test_primitive_measurement_is_actual_volume_and_handles_ellipsoid():
    from aether.gui.measurement import primitive_properties

    sphere = ae.Sphere((0, 0, 0), 0.002)
    r = primitive_properties(sphere)
    assert r["volume"] == pytest.approx(4 * math.pi * 0.002**3 / 3)
    assert r["diameter"] == pytest.approx(0.004)
    sphere.scale(2, 3, 4)
    r = primitive_properties(sphere)
    assert r["volume"] == pytest.approx(24 * 4 * math.pi * 0.002**3 / 3)
    assert "diameter" not in r
    assert primitive_properties(ae.Box((0, 0, 0), (0.01, 0.02, 0.03)))[
        "area"
    ] == pytest.approx(0.0022)
    assert primitive_properties(ae.Rectangle((0, 0, 0), (0.01, 0.02)))[
        "area"
    ] == pytest.approx(0.0002)
    assert primitive_properties(sphere - ae.Box((0, 0, 0), (0.001,) * 3)) == {}


def test_http_project_edit_save_reopen_and_static_ui(tmp_path):
    import json
    import urllib.request
    from aether.gui.server import DesktopServer

    s = Session()
    s.new_project("HTTP")
    server = DesktopServer(("127.0.0.1", 0), s, "test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:" + str(server.server_address[1])

    def rpc(method, params=None):
        req = urllib.request.Request(
            url + "/api/rpc",
            data=json.dumps({"method": method, "params": params or {}}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Aether-Token": "test-token",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            r = json.load(response)
        assert r["ok"], r
        return r

    try:
        with urllib.request.urlopen(url) as response:
            html = response.read().decode()
        assert "engineering.js" in html and html.index("engineering.js") < html.index(
            "app.js"
        )
        with urllib.request.urlopen(url + "/engineering.js") as response:
            assert "dlgStudyResults" in response.read().decode()
        rpc("parameters.set", {"variables": {"W": "5mm"}})
        rpc(
            "modeler.draw",
            {"shape": "box", "name": "part", "params": {"size": ["W", "2mm", "3mm"]}},
        )
        path = str(tmp_path / "http.warpz")
        rpc("project.save", {"path": path})
        rpc("parameters.set", {"variables": {"W": "8mm"}})
        rpc("project.save")
        rpc("project.open", {"path": path})
        rpc("modeler.select", {"names": ["part"]})
        result = rpc("modeler.measure")["result"]
        assert result["size"] == pytest.approx([0.008, 0.002, 0.003])
        assert result["primitive"]["volume"] == pytest.approx(0.008 * 0.002 * 0.003)
        assert rpc("parameters.list")["result"]["rows"][0]["expression"] == "8mm"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_overlapping_ports_are_rejected():
    s = session()
    s.design.add_wave_port("Duplicate", axis="z", value=0)
    with pytest.raises(ValueError, match="overlaps"):
        s.design.generate_mesh(1e10, backend="builtin")
