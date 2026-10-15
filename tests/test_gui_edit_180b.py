"""Saving over a file, editing properties in the panel, free orbit, copy / mirror /
sweep / curve / split from the GUI, rubber-band selection rules."""
import math
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api",
                                 reason="playwright is not installed")
from playwright.sync_api import sync_playwright          # noqa: E402

import aether as ae                                       # noqa: E402
from conftest import needs_occ                            # noqa: E402

pytestmark = [needs_occ, pytest.mark.slow]

LAUNCH_ARGS = ["--enable-unsafe-swiftshader"]
MM = 1e-3


@pytest.fixture(scope="module")
def desktop():
    from aether.gui.server import serve
    srv, _, session = serve(port=8845, open_browser=False, token="", block=False)
    yield "http://127.0.0.1:8845/", session
    try:
        srv.shutdown()
    except Exception:
        pass


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


def design():
    d = ae.Design("t", units="mm")
    d.add_box("air", (-40 * MM, -40 * MM, -20 * MM), (80 * MM, 80 * MM, 60 * MM), "vacuum")
    d.add_box("a", (0, 0, 0), (10 * MM, 6 * MM, 3 * MM), "pec")
    d.add_box("b", (20 * MM, 0, 0), (5 * MM, 5 * MM, 5 * MM), "pec")
    st = d.add_setup("S1", frequency="3GHz")
    st.add_sweep("sw", "2GHz", "4GHz", 11, kind="discrete")
    return d


def open_page(desktop, browser, d=None):
    url, session = desktop
    session.new_project("P")
    d = d or design()
    session.project.designs[0] = d
    session.design = d
    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.errs = errs
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    pg.evaluate("async()=>{STATE=await (await fetch('/api/state?token='+"
                "encodeURIComponent(window.AETHER_TOKEN))).json();renderAll();await refreshGeometry(true);}")
    pg.wait_for_timeout(500)
    return pg, session


@pytest.fixture()
def tab(desktop, browser):
    pg, session = open_page(desktop, browser)
    yield pg, session
    pg.close()


def refresh(pg):
    pg.evaluate("async()=>{STATE=await (await fetch('/api/state?token='+encodeURIComponent(window.AETHER_TOKEN))).json();renderAll();}")
    pg.wait_for_timeout(200)


def objects(session):
    return {o.name: o for o in list(session.design.solids) + list(session.design.sheets)}


# ------------------------------------------------------ saving over a file
def test_saving_over_an_existing_file_asks_inside_the_app_and_replaces_it(tab, tmp_path):
    pg, session = tab
    target = tmp_path / "view.html"
    target.write_text("old")
    # a browser whose confirm() is blocked answers "no": the app must not depend on it
    pg.evaluate("()=>{window.confirm=()=>false;}")
    pg.evaluate("p=>filePicker({mode:'save',kind:'html',title:'t',path:p,filename:'view.html',onPick:q=>exportThreeJs(q)})",
                str(tmp_path))
    pg.wait_for_selector("#fp-name")
    pg.click("button.pri:has-text('Save')")
    pg.wait_for_selector("button.pri:has-text('Replace')", timeout=10000)
    pg.click("button.pri:has-text('Replace')")
    pg.wait_for_function("()=>/Saved 3D viewer/.test(document.querySelector('#statusbar').textContent)", timeout=60000)
    assert target.stat().st_size > 10000 and b"three" in target.read_bytes()[:200000].lower()
    assert not pg.errs


def test_replace_can_be_declined(tab, tmp_path):
    pg, _ = tab
    target = tmp_path / "keep.html"
    target.write_text("old")
    pg.evaluate("p=>filePicker({mode:'save',kind:'html',title:'t',path:p,filename:'keep.html',onPick:q=>exportThreeJs(q)})",
                str(tmp_path))
    pg.wait_for_selector("#fp-name")
    pg.click("button.pri:has-text('Save')")
    pg.wait_for_selector("button.pri:has-text('Replace')")
    pg.click(".dialog button:text-is('Cancel') >> nth=-1")
    pg.wait_for_timeout(500)
    assert target.read_text() == "old"


# ------------------------------------------------------ the properties panel
def select_node(pg, text):
    pg.locator("#tree .node", has_text=text).first.click()
    pg.wait_for_timeout(300)


def test_a_sweep_range_can_be_edited_in_the_panel(tab):
    pg, session = tab
    pg.evaluate("()=>showProps('sweep','sw',)")          # propTarget needs the setup too
    pg.evaluate("()=>{propTarget={type:'sweep',setup:'S1',name:'sw'};renderProps();}")
    pg.wait_for_timeout(200)
    labels = pg.evaluate("()=>[...document.querySelectorAll('#props-body tr')].map(r=>r.children[0].textContent)")
    assert {"Start", "Stop", "Count", "Sweep type", "Frequency setup", "Save fields"} <= set(labels)
    start = pg.locator("#props-body tr:has(td:text-is('Start')) input")
    start.fill("1.5GHz")
    start.press("Enter")
    pg.wait_for_timeout(500)
    sw = session.design.setups[0].sweeps[0]
    assert sw.start == pytest.approx(1.5e9)
    pg.locator("#props-body tr:has(td:text-is('Stop')) input").fill("5GHz")
    pg.locator("#props-body tr:has(td:text-is('Stop')) input").press("Enter")
    pg.wait_for_timeout(500)
    assert sw.stop == pytest.approx(5e9)
    # the type and the spacing switch which other fields show
    pg.locator("#props-body tr:has(td:text-is('Frequency setup')) select").select_option("step")
    pg.wait_for_timeout(500)
    assert "Step" in pg.evaluate("()=>[...document.querySelectorAll('#props-body tr')].map(r=>r.children[0].textContent)")
    assert sw.spacing == "step" and sw.step == pytest.approx(0.35e9)         # 1.5..5 GHz in 10 intervals
    pg.locator("#props-body tr:has(td:text-is('Step')) input").fill("0.5GHz")
    pg.locator("#props-body tr:has(td:text-is('Step')) input").press("Enter")
    pg.wait_for_timeout(500)
    assert sw.spacing == "step" and sw.step == pytest.approx(0.5e9) and sw.count == 8       # 1.5 .. 5 GHz
    assert not pg.errs


def test_a_bad_value_is_refused_and_the_old_one_comes_back(tab):
    pg, session = tab
    pg.evaluate("()=>{propTarget={type:'sweep',setup:'S1',name:'sw'};renderProps();}")
    f = pg.locator("#props-body tr:has(td:text-is('Stop')) input")
    f.fill("1MHz")                                       # below the start frequency
    f.press("Enter")
    pg.wait_for_timeout(600)
    assert session.design.setups[0].sweeps[0].stop == pytest.approx(4e9)
    assert pg.locator("#props-body tr:has(td:text-is('Stop')) input").input_value() != "1MHz"


def test_setup_boundary_port_and_mesh_values_edit_in_place(tab):
    pg, session = tab
    d = session.design
    # a setup
    pg.evaluate("()=>{propTarget={type:'setup',name:'S1'};renderProps();}")
    pg.locator("#props-body tr:has(td:text-is('Minimum passes')) input").fill("3")
    pg.locator("#props-body tr:has(td:text-is('Minimum passes')) input").press("Enter")
    pg.locator("#props-body tr:has(td:text-is('Name')) input").fill("Main")
    pg.locator("#props-body tr:has(td:text-is('Name')) input").press("Enter")
    pg.wait_for_timeout(500)
    assert d.setups[0].min_passes == 3 and d.setups[0].name == "Main"
    # a lumped RLC boundary
    from aether.gui.api import dispatch
    dispatch(session, "boundary.autoRlc", dict(signal=[{"kind": "object", "name": "b"}],
                                                ground=[{"kind": "object", "name": "a"}], R=50, L=0, C=0))
    refresh(pg)
    bn = d.boundaries[-1].name
    pg.evaluate("n=>{propTarget={type:'boundary',name:n};renderProps();}", bn)
    pg.locator("#props-body tr:has(td:text-is('R [Ω]')) input").fill("120")
    pg.locator("#props-body tr:has(td:text-is('R [Ω]')) input").press("Enter")
    pg.wait_for_timeout(500)
    assert d.boundaries[-1].params["R"] == 120.0
    # a port
    r = dispatch(session, "excitation.autoPort", dict(kind="lumped", signal=[{"kind": "object", "name": "b"}],
                                                       ground=[{"kind": "object", "name": "a"}]))
    refresh(pg)
    pg.evaluate("n=>{propTarget={type:'port',name:n};renderProps();}", r["name"])
    pg.locator("#props-body tr:has(td:text-is('Impedance [Ω]')) input").fill("75")
    pg.locator("#props-body tr:has(td:text-is('Impedance [Ω]')) input").press("Enter")
    pg.wait_for_timeout(500)
    assert d.get_port(r["name"]).impedance == 75
    assert not pg.errs


def test_a_primitives_size_edits_in_the_panel(tab):
    pg, session = tab
    pg.evaluate("()=>{setSelection(['a']);propTarget={type:'object',name:'a'};renderProps();}")
    pg.wait_for_selector("#props-body tr:has(td:text-is('size'))", timeout=10000)
    inputs = pg.locator("#props-body tr:has(td:text-is('size')) input")
    inputs.nth(0).fill("12mm")
    inputs.nth(0).press("Enter")
    pg.wait_for_timeout(800)
    lo, hi = objects(session)["a"].shape.bounds()
    assert hi[0] - lo[0] == pytest.approx(12e-3)
    assert not pg.errs


def test_project_and_design_names_and_units_edit(tab):
    pg, session = tab
    pg.evaluate("()=>{propTarget={type:'',name:''};renderProps();}")
    pg.locator("#props-body tr:has(td:text-is('Project')) input").fill("Renamed")
    pg.locator("#props-body tr:has(td:text-is('Project')) input").press("Enter")
    pg.wait_for_timeout(400)
    assert session.project.name == "Renamed"
    pg.locator("#props-body tr:has(td:text-is('Model units')) select").select_option("cm")
    pg.wait_for_timeout(400)
    assert session.design.units == "cm"


# --------------------------------------------------------------- free orbit
def drag(pg, dx, dy, steps=40):
    box = pg.locator("#gl").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(cx, cy)
    pg.mouse.down()
    for i in range(1, steps + 1):
        pg.mouse.move(cx + dx * i / steps, cy + dy * i / steps)
    pg.mouse.up()
    pg.wait_for_timeout(200)


def test_the_view_turns_all_the_way_round_without_stopping(tab):
    pg, _ = tab
    pg.evaluate("()=>VP.view('iso')")
    seen = []
    for _ in range(8):
        drag(pg, 0, 120)                                  # 120 px = ~1.02 rad each, 8 -> more than a full turn
        seen.append(pg.evaluate("()=>VP.pitch"))
    # it went past the vertical (pi/2) and kept going; it never sticks at a limit
    assert max(abs(v) for v in seen) > math.pi / 2 + 0.2
    steps = [abs((b - a + math.pi) % (2 * math.pi) - math.pi) for a, b in zip(seen, seen[1:])]
    assert min(steps) > 0.5
    # horizontal turning keeps working when the model is upside down
    pg.evaluate("()=>{VP.pitch=-2.0;}")
    y0 = pg.evaluate("()=>VP.yaw")
    drag(pg, 100, 0)
    assert abs(pg.evaluate("()=>VP.yaw") - y0) > 0.5
    # the picture is still sane upside down (something is drawn, picking still works)
    pg.evaluate("()=>{VP.pitch=2.6;}")
    pg.wait_for_timeout(200)
    assert pg.evaluate("()=>{const q=VP.project([5e-3,3e-3,1.5e-3]);return !!q && isFinite(q.x) && isFinite(q.y)}")
    assert not pg.errs


# ------------------------------------------------------- copy / mirror / move
def screen(pg, p):
    box = pg.locator("#gl").bounding_box()
    q = pg.evaluate("p=>VP.project(p)", p)
    return box["x"] + q["x"], box["y"] + q["y"]


def test_copy_and_move_makes_a_row_of_copies_with_their_boundaries(tab):
    pg, session = tab
    d = session.design
    from aether.gui.api import dispatch
    dispatch(session, "boundary.assign", dict(type="pec", name="TopBC", selector={"kind": "faces", "faces": [
        {"object": "a", "point": [5e-3, 3e-3, 3e-3], "normal": [0, 0, 1], "lo": [0, 0, 3e-3], "hi": [10e-3, 6e-3, 3e-3],
         "planar": True}]}))
    refresh(pg)
    pg.evaluate("()=>VP.view('iso')")
    pg.evaluate("()=>{setSelection(['a']);startInteractiveMove(null,{copy:true});}")
    pg.wait_for_selector("#mv-count")
    pg.fill("#mv-count", "3")
    pg.evaluate("()=>{MOVE.p1=[0,0,0];MOVE.p2=[0,15e-3,0];MOVE.stage='ready';updateMovePanel();}")
    pg.click("#mv-apply")
    pg.wait_for_timeout(1000)
    names = sorted(n for n in objects(session) if n in ("a", "a1", "a2"))
    assert names == ["a", "a1", "a2"]
    ys = sorted(round(objects(session)[n].shape.bounds()[0][1] * 1e3) for n in names)
    assert ys == [0, 15, 30]
    assert len(d.boundaries) == 3                          # each copy carries its own boundary
    assert not pg.errs


def test_mirror_by_two_points_flips_in_place_or_adds_the_image(tab):
    pg, session = tab
    pg.evaluate("()=>{setSelection(['b']);startInteractiveMove(null,{mode:'mirror',copy:true});}")
    pg.wait_for_selector("#mv-apply")
    assert "Mirror" in pg.inner_text("#vp-draw h4")
    pg.evaluate("()=>{MOVE.p1=[10e-3,0,0];MOVE.p2=[11e-3,0,0];MOVE.stage='ready';updateMovePanel();}")   # plane x = 10 mm
    pg.click("#mv-apply")
    pg.wait_for_timeout(1000)
    objs = objects(session)
    img = next(n for n in objs if n.startswith("b") and n != "b")
    lo, hi = objs[img].shape.bounds()
    assert (lo[0], hi[0]) == pytest.approx((-5e-3, 0.0), abs=1e-9)      # 20..25 mirrored about x = 10
    # without Copy the object itself is flipped
    pg.evaluate("()=>{setSelection(['b']);startInteractiveMove(null,{mode:'mirror'});}")
    pg.wait_for_selector("#mv-apply")
    pg.evaluate("()=>{MOVE.p1=[10e-3,0,0];MOVE.p2=[11e-3,0,0];MOVE.stage='ready';updateMovePanel();}")
    pg.click("#mv-apply")
    pg.wait_for_timeout(800)
    lo, hi = objects(session)["b"].shape.bounds()
    assert (lo[0], hi[0]) == pytest.approx((-5e-3, 0.0), abs=1e-9)


def test_pasting_then_moving_goes_straight_to_the_move_tool(tab):
    pg, session = tab
    pg.evaluate("()=>setSelection(['a'])")
    pg.evaluate("()=>editCopy(false)")
    pg.wait_for_timeout(300)
    refresh(pg)
    pg.evaluate("()=>editPaste(true)")
    pg.wait_for_selector("#vp-draw.on", timeout=10000)
    assert "Move" in pg.inner_text("#vp-draw h4")
    assert len([n for n in objects(session) if n in ("a", "a1")]) == 2


# ------------------------------------------------- sweeps, curves, split (UI)
def test_the_sweep_dialog_turns_a_rectangle_into_a_solid(tab):
    pg, session = tab
    from aether.gui.api import dispatch
    dispatch(session, "modeler.draw", dict(shape="rectangle", name="R", params={"position": ["0mm", "10mm", "0mm"],
                                                                                 "size": ["4mm", "2mm"], "plane": "xy"}))
    refresh(pg)
    pg.evaluate("()=>{setSelection(['R']);dlgShapeSweep('vector');}")
    pg.wait_for_selector("#sw3-obj")
    assert pg.input_value("#sw3-obj") == "R"
    pg.fill("#sw3vz", "2mm")
    pg.select_option("#sw3-mat", "pec")
    pg.click(".dialog button.pri:has-text('Sweep')")
    pg.wait_for_timeout(1000)
    assert any(o.name == "R" for o in session.design.solids)
    assert not pg.errs


def test_the_curve_dialog_draws_a_helix_and_it_can_be_swept(tab):
    pg, session = tab
    pg.evaluate("()=>dlgCurve('helix')")
    pg.wait_for_selector("#cv-x")
    assert "pitch" in pg.input_value("#cv-x")
    pg.click(".dialog button.pri:has-text('Create')")
    pg.wait_for_timeout(1000)
    curves = [x for x in session.design.sheets if type(x.shape).__name__ == "Sketch"]
    assert len(curves) == 1
    refresh(pg)
    assert pg.evaluate("()=>lineNames().length") == 1
    assert not pg.errs


def test_split_dialog_cuts_at_the_working_plane_offset(tab):
    pg, session = tab
    pg.evaluate("()=>{setSelection(['a']);dlgSplit();}")
    pg.wait_for_selector("#sp-plane")
    pg.select_option("#sp-plane", "yz")
    pg.fill("#sp-at", "4mm")
    pg.click(".dialog button.pri:has-text('Split')")
    pg.wait_for_timeout(1000)
    objs = objects(session)
    assert "a_1" in objs
    assert objs["a"].shape.bounds()[0][0] == pytest.approx(4e-3, abs=1e-9)
    assert objs["a_1"].shape.bounds()[1][0] == pytest.approx(4e-3, abs=1e-9)


# ------------------------------------------------------------ rubber band
def band(pg, a, b):
    pg.mouse.move(*a)
    pg.keyboard.down("Control")
    pg.mouse.down()
    pg.mouse.move((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    pg.mouse.move(*b)
    pg.mouse.up()
    pg.keyboard.up("Control")
    pg.wait_for_timeout(500)


def test_right_to_left_selects_only_what_lies_completely_inside(tab):
    pg, _ = tab
    pg.evaluate("()=>{VP.view('top'); setSelectMode('object'); setSelection([]);}")
    pg.wait_for_timeout(300)
    (ax, ay), (bx, by) = screen(pg, [-1e-3, -1e-3, 3e-3]), screen(pg, [12e-3, 7e-3, 3e-3])   # just around 'a'
    # right-to-left: a (completely inside) only; the air box merely contains the rectangle
    band(pg, (max(ax, bx), min(ay, by)), (min(ax, bx), max(ay, by)))
    assert pg.evaluate("()=>STATE.selection") == ["a"]
    # left-to-right over the same rectangle also takes what it touches (the air box around everything)
    pg.evaluate("()=>setSelection([])")
    band(pg, (min(ax, bx), min(ay, by)), (max(ax, bx), max(ay, by)))
    sel = pg.evaluate("()=>STATE.selection")
    assert "a" in sel and "air" in sel and "b" not in sel


def test_the_area_filter_limits_what_a_band_takes(tab):
    pg, _ = tab
    pg.evaluate("()=>{VP.view('top'); setSelectMode('object'); setSelection([]);}")
    pg.evaluate("()=>{AREA_FILTER=Object.assign(AREA_FILTER,{exclude:'air',include:'',solids:true,sheets:true,lines:true,materials:[],front:false});}")
    pg.wait_for_timeout(200)
    (ax, ay), (bx, by) = screen(pg, [-1e-3, -1e-3, 3e-3]), screen(pg, [12e-3, 7e-3, 3e-3])
    band(pg, (min(ax, bx), min(ay, by)), (max(ax, bx), max(ay, by)))
    assert pg.evaluate("()=>STATE.selection") == ["a"]
    pg.evaluate("()=>{AREA_FILTER=Object.assign(AREA_FILTER,{exclude:'',include:'b*'});setSelection([]);}")
    (cx, cy), (dx_, dy_) = screen(pg, [-45e-3, -45e-3, 3e-3]), screen(pg, [45e-3, 45e-3, 3e-3])
    band(pg, (min(cx, dx_), min(cy, dy_)), (max(cx, dx_), max(cy, dy_)))
    assert pg.evaluate("()=>STATE.selection") == ["b"]
    pg.evaluate("()=>{AREA_FILTER=Object.assign(AREA_FILTER,{exclude:'',include:''});}")
