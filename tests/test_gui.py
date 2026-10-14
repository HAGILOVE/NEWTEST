"""
Aether Desktop: the command layer, the HTTP server and the tessellator.

These run headless — no browser required. The browser-driven end-to-end test
lives in ``test_gui_browser.py`` and is skipped unless Playwright is present.
"""
import json
import threading
import time
import urllib.error
import urllib.request

import numpy as np
import pytest

from conftest import needs_occ

import aether as ae
from aether.gui.api import COMMANDS, dispatch, state_json
from aether.gui.state import MessageLog, Session
from aether.gui.tessellate import tessellate_analytic


@pytest.fixture()
def sess():
    s = Session()
    s.new_project("TestProject")
    return s


# ------------------------------------------------------------------ state
def test_new_session_has_a_design(sess):
    st = state_json(sess)
    assert st["project"]["name"] == "TestProject"
    assert st["design"]["name"] == "HFSSDesign1"
    assert st["design"]["objects"] == []
    assert st["job"]["running"] is False


def test_message_log_is_incremental():
    m = MessageLog()
    m.add("one"); m.add("two", "warning", "src")
    assert len(m.since(0)) == 2
    first = m.since(0)[0]["id"]
    assert len(m.since(first)) == 1
    assert m.since(first)[0]["severity"] == "warning"


def test_state_is_json_serialisable_even_with_pec(sess):
    """A PEC has infinite conductivity; JSON has no Infinity."""
    from aether.gui.server import _finite
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "Metal",
                                    "material": "pec"})
    payload = {"state": state_json(sess),
               "materials": dispatch(sess, "materials.list", {})}
    json.dumps(_finite(payload), allow_nan=False)          # must not raise


# ---------------------------------------------------------------- modeler
def test_draw_commands_build_the_model(sess):
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "Sub",
        "material": "fr4_epoxy",
        "params": {"position": ["0mm", "0mm", "0mm"],
                   "size": ["20mm", "10mm", "0.8mm"]}})
    dispatch(sess, "modeler.draw", {"shape": "cylinder", "name": "Via",
        "material": "copper",
        "params": {"center": ["5mm", "5mm", "0mm"], "radius": "0.2mm",
                   "height": "0.8mm", "axis": [0, 0, 1]}})
    d = sess.design
    assert [o.name for o in d.solids] == ["Sub", "Via"]
    assert d.get_solid("Sub").material.name == "fr4_epoxy"
    lo, hi = d.bounding_box()
    assert hi[0] == pytest.approx(0.020)


def test_unit_strings_are_honoured_by_the_api(sess):
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "B",
        "params": {"position": [0, 0, 0], "size": ["1in", "25.4mm", "1000mil"]}})
    lo, hi = sess.design.bounding_box()
    assert np.allclose(hi - lo, [0.0254, 0.0254, 0.0254])


def test_boolean_and_delete(sess):
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "A",
        "params": {"size": ["10mm", "10mm", "10mm"]}})
    dispatch(sess, "modeler.draw", {"shape": "sphere", "name": "B",
        "params": {"center": ["5mm", "5mm", "5mm"], "radius": "3mm"}})
    dispatch(sess, "modeler.boolean",
             {"op": "subtract", "blank": "A", "tools": ["B"]})
    assert [o.name for o in sess.design.solids] == ["A"]
    from aether.geometry.implicit import contains
    pts = np.array([[0.005, 0.005, 0.005], [0.001, 0.001, 0.001]])
    assert list(contains(sess.design.solids[0].shape, pts)) == [False, True]
    dispatch(sess, "modeler.delete", {"names": ["A"]})
    assert sess.design.solids == []


def test_transform_command(sess):
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "A",
        "params": {"size": ["10mm", "10mm", "10mm"]}})
    dispatch(sess, "modeler.transform", {"name": "A", "op": "move",
        "params": {"dx": "5mm", "dy": 0, "dz": 0}})
    lo, hi = sess.design.bounding_box()
    assert lo[0] == pytest.approx(0.005)


def test_property_edit_changes_the_material(sess):
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "A"})
    dispatch(sess, "modeler.setProperty",
             {"name": "A", "prop": "material", "value": "copper"})
    assert sess.design.get_solid("A").material.name == "copper"


# --------------------------------------------------- boundaries and ports
def test_selector_kinds_all_resolve(sess):
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "A",
        "params": {"size": ["10mm", "10mm", "10mm"]}})
    specs = [{"kind": "plane", "axis": "z", "value": "0mm"},
             {"kind": "bboxface", "face": "+z"},
             {"kind": "box", "lo": [0, 0, 0], "hi": ["10mm", "10mm", "1mm"]},
             {"kind": "object", "objects": ["A"]},
             {"kind": "outer"}]
    for i, spec in enumerate(specs):
        dispatch(sess, "boundary.assign",
                 {"type": "pec", "name": f"b{i}", "selector": spec})
    assert len(sess.design.boundaries) == len(specs)
    cen = np.array([[0.005, 0.005, 0.0]])
    nrm = np.array([[0.0, 0.0, -1.0]])
    assert sess.design.boundaries[0].selector(cen, nrm)[0]


def test_finite_conductivity_parameters_reach_the_model(sess):
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "A",
        "params": {"size": ["10mm", "10mm", "10mm"]}})
    dispatch(sess, "boundary.assign", {"type": "finite_cond", "name": "Cu",
        "selector": {"kind": "outer"},
        "params": {"material": "copper", "thickness": "35um",
                   "roughness": "1um"}})
    b = sess.design.boundaries[0]
    assert b.params["material"].name == "copper"
    assert b.params["thickness"] == pytest.approx(35e-6)
    zs = b.surface_impedance(1e10)
    assert zs.real > 0 and zs.imag > 0


def test_wave_and_lumped_ports(sess):
    dispatch(sess, "modeler.draw", {"shape": "box", "name": "A",
        "params": {"size": ["10mm", "10mm", "10mm"]}})
    dispatch(sess, "excitation.assign", {"kind": "wave", "name": "p1",
        "selector": {"kind": "plane", "axis": "z", "value": "0mm"},
        "params": {"modes": 2, "deembed": "1mm", "renorm": 50,
                   "line": [["0mm", "0mm", "0mm"], ["0mm", "0mm", "1mm"]]}})
    dispatch(sess, "excitation.assign", {"kind": "lumped", "name": "p2",
        "selector": {"kind": "plane", "axis": "z", "value": "10mm"},
        "params": {"impedance": 75.0, "direction": [0, 1, 0]}})
    p1, p2 = sess.design.ports
    assert p1.num_modes == 2 and p1.deembed == pytest.approx(0.001)
    assert p1.renormalize_z == 50 and p1.integration_line is not None
    assert p2.impedance.real == pytest.approx(75.0)
    assert list(p2.direction) == [0, 1, 0]
    assert sess.design.n_excitations == 3


# -------------------------------------------------------------- analysis
def test_setup_and_sweep_commands(sess):
    dispatch(sess, "analysis.addSetup", {"name": "S1", "frequency": "10GHz",
                                         "maxPasses": 4, "deltaS": 0.01,
                                         "basisOrder": 2})
    dispatch(sess, "analysis.addSweep", {"setup": "S1", "name": "Sw",
        "start": "8GHz", "stop": "12GHz", "count": 41})
    st = sess.design.get_setup("S1")
    assert st.frequency == 1e10 and st.max_passes == 4 and st.basis_order == 2
    assert len(st.sweeps[0].frequencies()) == 41
    dispatch(sess, "analysis.editSetup", {"name": "S1", "frequency": "9GHz"})
    assert sess.design.get_setup("S1").frequency == 9e9


def test_validation_reports_missing_pieces(sess):
    r = dispatch(sess, "analysis.validate")
    assert r["ok"] is False
    assert any("port" in e or "setup" in e for e in r["errors"])
    names = [c["name"] for c in r["checks"]]
    assert "3D Model" in names and "Analysis Setup" in names


@needs_occ
def test_template_projects_load_and_validate():
    for tpl in ("waveguide", "coax", "microstrip"):
        s = Session()
        dispatch(s, "project.template", {"template": tpl})
        assert s.design is not None
        assert s.design.solids and s.design.ports and s.design.setups
        assert dispatch(s, "analysis.validate")["ok"] is True


@needs_occ
def test_mesh_generation_works_off_the_main_thread():
    """
    The GUI meshes from a worker thread; gmsh installs a SIGINT handler on
    initialise and signal handlers can only be set from the main thread, so
    this is the regression guard for that.
    """
    s = Session()
    dispatch(s, "project.template", {"template": "microstrip"})
    out = {}

    def work():
        try:
            out["r"] = dispatch(s, "analysis.generateMesh", {"size": 0.003})
        except Exception as exc:
            out["e"] = str(exc)

    t = threading.Thread(target=work)
    t.start(); t.join(120)
    assert "e" not in out, out.get("e")
    assert out["r"]["tets"] > 20


@needs_occ
def test_full_solve_through_the_api_produces_results():
    s = Session()
    dispatch(s, "project.template", {"template": "microstrip"})
    dispatch(s, "analysis.analyze", {"adaptive": False})
    for _ in range(600):
        if not s.job.running:
            break
        time.sleep(0.2)
    assert not s.job.running and not s.job.error, s.job.error
    assert s.solution is not None

    rep = dispatch(s, "results.report", {"form": "db"})
    assert rep["nPort"] == 2 and rep["passive"] and rep["reciprocal"]
    assert len(rep["traces"]) == 2
    assert min(rep["traces"][1]["y"]) > -0.1        # |S21| ~ 1 on a matched line
    assert max(rep["traces"][0]["y"]) < -25         # S11 well matched

    modes = dispatch(s, "results.portModes", {})
    assert len(modes["rows"]) >= 2

    conv = dispatch(s, "results.convergence", {})
    assert conv["passes"]


@needs_occ
def test_view_buffers_are_renderable():
    s = Session()
    dispatch(s, "project.template", {"template": "waveguide"})
    g = dispatch(s, "view.geometry", {})
    o = g["objects"][0]
    assert o["count"] % 3 == 0 and o["count"] >= 12
    assert len(o["position"]) == o["count"] * 3
    assert len(o["normal"]) == o["count"] * 3
    n = np.asarray(o["normal"]).reshape(-1, 3)
    assert np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-5)
    assert len(g["bbox"]) == 2

    dispatch(s, "analysis.generateMesh", {"size": 0.005})
    m = dispatch(s, "view.mesh", {})
    assert m["stats"]["tets"] > 10
    assert len(m["wire"]["edges"]) % 2 == 0


def test_analytic_tessellation_needs_no_cad_kernel():
    for shape in (ae.Box((0, 0, 0), (1, 2, 3)),
                  ae.Cylinder((0, 0, 0), 1, 4),
                  ae.Sphere((0, 0, 0), 2),
                  ae.Cone((0, 0, 0), 2, 0, 3),
                  ae.Torus((0, 0, 0), 3, 1)):
        b = tessellate_analytic(shape)
        assert b["count"] % 3 == 0 and b["count"] >= 12
        assert len(b["position"]) == b["count"] * 3
        assert np.isfinite(np.asarray(b["position"])).all()


# ---------------------------------------------------------------- console
def test_scripting_console_shares_the_model(sess):
    r = dispatch(sess, "script.run",
                 {"code": "design.add_box('FromScript',(0,0,0),"
                          "('4mm','4mm','4mm'),'copper')"})
    assert r["ok"], r["output"]
    assert sess.design.get_solid("FromScript").material.name == "copper"
    r = dispatch(sess, "script.run", {"code": "len(design.solids)"})
    assert r["output"].strip() == "1"


def test_console_errors_are_returned_not_raised(sess):
    r = dispatch(sess, "script.run", {"code": "1/0"})
    assert r["ok"] is False and "ZeroDivisionError" in r["output"]


# ----------------------------------------------------------------- server
@pytest.fixture()
def server():
    from aether.gui.server import serve
    srv, url, s = serve(port=8791, open_browser=False, token="tkn",
                        block=False)
    time.sleep(0.3)
    yield "http://127.0.0.1:8791", s
    srv.shutdown()


def _post(base, method, params=None, token="tkn"):
    req = urllib.request.Request(
        f"{base}/api/rpc?token={token}",
        data=json.dumps({"method": method, "params": params or {}}).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def test_server_serves_the_page_and_assets(server):
    base, _ = server
    html = urllib.request.urlopen(base + "/").read().decode()
    assert "Aether Desktop" in html and "__AETHER_TOKEN__" not in html
    for asset in ("/app.js", "/gl.js", "/style.css"):
        assert urllib.request.urlopen(base + asset).getcode() == 200


def test_server_rejects_a_bad_token(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "/api/state?token=wrong")
    assert e.value.code == 403


def test_server_rpc_round_trip(server):
    base, s = server
    r = _post(base, "modeler.draw", {"shape": "box", "name": "Blk",
                                     "params": {"size": ["3mm", "3mm", "3mm"]}})
    assert r["ok"] and r["state"]["design"]["objects"][0]["name"] == "Blk"
    assert s.design.get_solid("Blk")


def test_server_reports_command_errors_without_500(server):
    base, _ = server
    r = _post(base, "modeler.boolean", {"op": "subtract", "blank": "nope",
                                        "tools": []})
    assert r["ok"] is False and "nope" in r["error"]
    assert "state" in r                    # the UI still gets fresh state


def test_server_message_endpoint(server):
    base, s = server
    s.messages.add("hello from the test", "info", "pytest")
    j = json.load(urllib.request.urlopen(base + "/api/messages?since=0&token=tkn"))
    assert any("hello from the test" == m["text"] for m in j["messages"])
    assert "job" in j


def test_static_path_traversal_is_blocked(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "/../../etc/passwd")
    assert e.value.code == 404


def test_every_command_is_callable_and_documented():
    assert len(COMMANDS) >= 35
    for name, fn in COMMANDS.items():
        assert callable(fn)
        assert "." in name


@needs_occ
def test_field_overlay_buffer_is_produced():
    """Saving fields must yield a per-triangle |E| map the viewport can colour."""
    s = Session()
    dispatch(s, "project.template", {"template": "microstrip"})
    dispatch(s, "analysis.analyze", {"adaptive": False, "save_fields": True})
    for _ in range(900):
        if not s.job.running:
            break
        time.sleep(0.2)
    assert not s.job.error, s.job.error
    f = dispatch(s, "view.field", {})
    assert f["count"] % 3 == 0 and f["count"] > 30
    assert len(f["scalar"]) == f["count"]
    v = np.asarray(f["scalar"])
    assert v.min() >= 0.0 and v.max() <= 1.0 + 1e-9
    assert f["range"][1] > f["range"][0] > 0
