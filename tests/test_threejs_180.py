"""
Save As > three.js 3D viewer (1.8.0).

The exporter writes one HTML page with the model and, for a solved design, the
*complex* E / H / Js vectors and far field. Two layers:

1. the data in the file against the solver's own field views;
2. the page itself in Chromium: it loads from disk, draws, animates, and the
   radiation boundary is hidden until asked for.
"""
import json
import os
import re

import numpy as np
import pytest

from conftest import needs_occ

pytestmark = [needs_occ, pytest.mark.slow]

playwright = pytest.importorskip("playwright.sync_api",
                                 reason="playwright is not installed")
from playwright.sync_api import sync_playwright          # noqa: E402

LAUNCH_ARGS = ["--enable-unsafe-swiftshader"]


@pytest.fixture(scope="module")
def solved():
    from aether.gui.state import Session
    from test_farfield_180 import dipole
    s = Session()
    s.new_project("Dipole")
    d = dipole()
    s.project.designs[0] = d
    s.design = d
    s.solution = d.solve(adaptive=False, progress=False, save_fields=True)
    return s


@pytest.fixture(scope="module")
def page_file(solved, tmp_path_factory):
    from aether.gui import threejs
    path = str(tmp_path_factory.mktemp("viewer") / "dipole.html")
    info = threejs.export(solved, path)
    return path, info


def _scene(path):
    text = open(path, encoding="utf-8").read()
    m = re.search(r"const S = (\{.*?\});\nconst \$ = ", text, re.S)
    assert m, "the scene JSON is not in the page"
    return json.loads(m.group(1).replace("<\\/", "</")), text


# --------------------------------------------------------------- the data
def test_the_page_is_self_contained(page_file):
    path, info = page_file
    scene, text = _scene(path)
    assert info["offline"] and info["results"]
    assert "THREE" in text and "cdn.jsdelivr" not in text
    assert "@@" not in text                       # every template slot filled
    assert len(scene["model"]["objects"]) >= 2
    assert os.path.getsize(path) < 25e6


def test_ports_and_the_radiation_boundary_are_in_the_file(page_file):
    scene, _ = _scene(page_file[0])
    kinds = {(a["kind"], a["type"]) for a in scene["model"]["assign"]}
    assert any(k == "lumped" or t == "lumped" for k, t in kinds)
    assert ("boundary", "radiation") in kinds


def test_results_hold_complex_fields_on_surfaces_and_cut_planes(page_file):
    scene, _ = _scene(page_file[0])
    r = scene["results"]
    e = r["sets"][0]
    assert set(e["surface"]) >= {"E", "H", "J"}
    assert {"Ex", "Ey", "Ez", "Hx", "Hy", "Hz"} <= set(e["cut"])
    assert e["far"] is not None
    import base64
    f = np.frombuffer(base64.b64decode(e["cut"]["Ey"]["f"]), np.float32)
    n = e["cut"]["Ey"]["n"]
    assert f.size == 6 * n
    assert np.abs(f).max() > 0 and np.isfinite(f).all()


def test_stored_peak_is_consistent_with_the_solver_view(solved, page_file):
    """The page animates stored complex vectors; their magnitude must agree
    with what the solver's own plot shows, up to vertex averaging."""
    from aether.post.fieldview import surface_patch
    scene, _ = _scene(page_file[0])
    r = scene["results"]
    e = r["sets"][0]
    fs = solved.solution.field(r["freqs"][0], 0)
    patch = surface_patch(solved.solution, fs, "J")
    stored = e["surface"]["J"]["peak"]
    assert 0.3 * patch.peak < stored <= patch.peak * (1 + 1e-6)


def test_the_far_field_summary_travels_with_the_page(page_file):
    scene, _ = _scene(page_file[0])
    far = scene["results"]["sets"][0]["far"]
    assert far["summary"]["peakDirectivityDbi"] == pytest.approx(2.15, abs=0.8)
    assert far["nt"] > 20 and far["np"] > 12


def test_a_model_only_export_is_small_and_has_no_results(solved, tmp_path):
    from aether.gui import threejs
    p = str(tmp_path / "m.html")
    info = threejs.export(solved, p, with_results=False)
    scene, _ = _scene(p)
    assert scene["results"] is None and not info["results"]


# -------------------------------------------------------------- the browser
@pytest.fixture(scope="module")
def browser():
    try:
        pw = sync_playwright().start()
        b = pw.chromium.launch(args=LAUNCH_ARGS)
    except Exception as exc:
        pytest.skip(f"chromium unavailable: {exc}")
    yield b
    b.close()
    pw.stop()


@pytest.fixture()
def viewer(browser, page_file):
    pg = browser.new_page(viewport={"width": 1300, "height": 800})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.errors = errors
    pg.goto("file://" + page_file[0])
    pg.wait_for_function("()=>!!window.AETHER_VIEWER", timeout=30000)
    yield pg
    pg.close()


def _pixels(pg):
    return pg.evaluate("""()=>{
      const c = document.getElementById('gl'), s = document.createElement('canvas');
      s.width = 160; s.height = 100; const g = s.getContext('2d');
      g.drawImage(c, 0, 0, 160, 100); const d = g.getImageData(0,0,160,100).data;
      let h = 0, nz = new Set();
      for (let i=0;i<d.length;i+=4){ h = (h*31 + d[i] + 3*d[i+1] + 7*d[i+2]) | 0; nz.add(d[i]<<16|d[i+1]<<8|d[i+2]); }
      return {hash: h, colours: nz.size}; }""")


def test_the_page_loads_draws_and_has_no_errors(viewer):
    viewer.wait_for_timeout(600)
    assert not viewer.errors, viewer.errors
    px = _pixels(viewer)
    assert px["colours"] > 15                     # more than a flat background
    assert viewer.evaluate("()=>AETHER_VIEWER.ui.q") == "E"


def test_the_radiation_boundary_is_hidden_until_asked_for(viewer):
    vis = "()=>AETHER_VIEWER.assigns.filter(m=>m.userData.group==='rad').map(m=>m.visible)"
    assert viewer.evaluate(vis) == [False]
    viewer.check("#cRad")
    assert viewer.evaluate(vis) == [True]
    viewer.uncheck("#cRad")
    assert viewer.evaluate(vis) == [False]
    # the ports are drawn by default
    assert any(viewer.evaluate(
        "()=>AETHER_VIEWER.assigns.filter(m=>m.userData.group==='port').map(m=>m.visible)"))


def test_the_field_animates_over_time(viewer):
    viewer.evaluate("()=>AETHER_VIEWER.play(false)")
    viewer.evaluate("()=>{AETHER_VIEWER.ui.phase=0;AETHER_VIEWER.update();}")
    a = _pixels(viewer)["hash"]
    viewer.evaluate("()=>{AETHER_VIEWER.ui.phase=90;AETHER_VIEWER.update();}")
    viewer.wait_for_timeout(200)
    b = _pixels(viewer)["hash"]
    assert a != b
    # and the play button really advances the phase on its own
    viewer.evaluate("()=>AETHER_VIEWER.play(true)")
    p0 = viewer.evaluate("()=>AETHER_VIEWER.ui.phase")
    viewer.wait_for_timeout(700)
    p1 = viewer.evaluate("()=>AETHER_VIEWER.ui.phase")
    assert p0 != p1
    assert not viewer.errors, viewer.errors


def test_quantity_component_and_far_field_switches_work(viewer):
    viewer.evaluate("()=>AETHER_VIEWER.play(false)")
    for q in ("H", "J", "F"):
        viewer.select_option("#qQ", q)
        viewer.wait_for_timeout(250)
        assert viewer.evaluate("()=>AETHER_VIEWER.fieldGroup.visible") is True
        assert _pixels(viewer)["colours"] > 15
    # far field: both pattern modes
    viewer.select_option("#qM", "gain")
    viewer.wait_for_timeout(150)
    assert "dBi" in viewer.locator("#lgU").inner_text()
    viewer.select_option("#qM", "inst")
    assert viewer.locator("#ant tr").count() >= 5          # antenna table
    # a signed component of E on a cut plane
    viewer.select_option("#qQ", "E")
    viewer.select_option("#qC", "z")
    viewer.wait_for_timeout(150)
    assert "Ez" in viewer.locator("#lgT").inner_text()
    viewer.select_option("#qQ", "")
    assert viewer.evaluate("()=>AETHER_VIEWER.fieldGroup.visible") is False
    assert not viewer.errors, viewer.errors


def test_model_only_page_opens_without_a_results_panel(browser, solved, tmp_path):
    from aether.gui import threejs
    p = str(tmp_path / "m.html")
    threejs.export(solved, p, with_results=False)
    pg = browser.new_page(viewport={"width": 1100, "height": 700})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file://" + p)
    pg.wait_for_function("()=>!!window.AETHER_VIEWER", timeout=30000)
    pg.wait_for_timeout(300)
    assert pg.locator("#dRes").is_hidden()
    assert not errs
    pg.close()


# ------------------------------------------------- results on chosen metals
def test_the_page_knows_which_metal_each_surface_triangle_belongs_to(page_file):
    scene, _ = _scene(page_file[0])
    r = scene["results"]
    names = {m["name"] for m in r["metals"]}
    assert {"arm_top", "arm_bot"} <= names and "air" not in names
    import base64
    j = r["sets"][0]["surface"]["J"]
    owner = np.frombuffer(base64.b64decode(j["to"]), np.int16)
    assert len(owner) == len(base64.b64decode(j["i"])) // 12        # one per triangle
    by_idx = {m["idx"]: m["name"] for m in r["metals"]}
    assert {by_idx.get(int(o)) for o in set(owner)} >= {"arm_top", "arm_bot"}


def test_ticking_a_metal_in_the_page_limits_the_plot_to_it(viewer):
    viewer.evaluate("()=>AETHER_VIEWER.play(false)")
    viewer.select_option("#qQ", "J")
    viewer.wait_for_timeout(300)
    assert viewer.locator("#rMetals").is_visible()
    n_all = viewer.evaluate("()=>AETHER_VIEWER.fieldGroup.children[0].geometry.index.count")
    viewer.locator("#metalList label", has_text="arm_bot").locator("input").uncheck()
    viewer.wait_for_timeout(300)
    n_top = viewer.evaluate("()=>AETHER_VIEWER.fieldGroup.children[0].geometry.index.count")
    assert 0 < n_top < n_all
    viewer.click("#mNone")
    viewer.wait_for_timeout(200)
    assert viewer.evaluate("()=>AETHER_VIEWER.fieldGroup.children[0].geometry.index.count") == 0
    viewer.click("#mAll")
    viewer.wait_for_timeout(200)
    assert viewer.evaluate("()=>AETHER_VIEWER.fieldGroup.children[0].geometry.index.count") == n_all
    assert not viewer.errors, viewer.errors
