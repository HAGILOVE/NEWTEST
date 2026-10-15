"""Relative coordinates in the browser: pick an origin on the model, then type
coordinates from it; mid-point and face-centre snapping."""
import pytest

playwright = pytest.importorskip("playwright.sync_api",
                                 reason="playwright is not installed")
from playwright.sync_api import sync_playwright          # noqa: E402

from conftest import needs_occ                            # noqa: E402

pytestmark = [needs_occ, pytest.mark.slow]

LAUNCH_ARGS = ["--enable-unsafe-swiftshader"]


def call(s, method, **params):
    from aether.gui.api import dispatch
    return dispatch(s, method, params)


@pytest.fixture(scope="module")
def desktop():
    from aether.gui.server import serve
    srv, _, session = serve(port=8839, open_browser=False, token="", block=False)
    session.new_project("CS")
    call(session, "modeler.draw", shape="box", name="base",
         params={"position": ["10mm", "20mm", "5mm"], "size": ["10mm", "10mm", "2mm"]})
    yield "http://127.0.0.1:8839/", session
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


@pytest.fixture(scope="module")
def tab(desktop, browser):
    url, session = desktop
    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.errs = errs
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    pg.wait_for_function("()=>STATE&&STATE.design&&STATE.design.objects.length===1", timeout=30000)
    yield pg
    pg.close()


def bounds(session, name):
    lo, hi = session.design.get_solid(name).shape.bounds()
    return [round(float(x) * 1e3, 6) for x in list(lo) + list(hi)]


def test_the_viewport_offers_edge_midpoints_and_face_centres(tab):
    n = tab.evaluate("()=>[VP.objects[0].snapPoints.length, VP.objects[0].snapMids.length, "
                     "VP.objects[0].snapCenters.length]")
    assert n[0] >= 8 and n[1] == 12 and n[2] == 6            # corners, 12 edges, 6 faces


def test_a_picked_point_becomes_the_origin_of_a_relative_cs(tab, desktop):
    _, s = desktop
    # the snap returns the base's top-face centre (15, 25, 7) mm
    tab.evaluate("""()=>{VP.pickFeature=()=>({name:'base',point:[0.015,0.025,0.007],
                         snapKind:'face centre',vertex:true});}""")
    tab.click("#ribbon-tabs button:has-text('Draw')")
    tab.click("#ribbon-body .rbtn:has-text('Box by points')")
    tab.wait_for_selector("#vp-draw.on", timeout=15000)
    tab.click("#dw-pl-xy")
    tab.select_option("#dw-cs", "__pick__")
    tab.wait_for_selector("#status-cs", timeout=5000)
    box = tab.locator("#gl").bounding_box()
    tab.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    tab.wait_for_function("()=>STATE.design.workingCs==='RelativeCS1'", timeout=15000)
    assert "RelativeCS1" in tab.locator("#status-cs").inner_text()
    assert s.design.working_origin() == pytest.approx((0.015, 0.025, 0.007))
    assert tab.locator("#dw-cs").input_value() == "RelativeCS1"


def test_typed_corner_coordinates_are_measured_from_that_origin(tab, desktop):
    _, s = desktop
    n0 = len(s.design.solids)
    # the draw panel is still open on the XY plane
    tab.click("#dw-pl-xy")
    tab.fill("#dw-name", "rel1")
    for k, v in enumerate(("2", "3", "0")):          # first corner, from the origin
        tab.fill(f"#dw-a{k}", v)
    tab.press("#dw-a0", "Enter")
    for k, v in enumerate(("6", "8", "0")):          # opposite corner
        tab.fill(f"#dw-b{k}", v)
    tab.press("#dw-b0", "Enter")
    tab.fill("#dw-h", "1")
    tab.press("#dw-h", "Enter")
    tab.wait_for_function(f"()=>STATE.design.objects.length==={n0 + 1}", timeout=30000)
    # origin (15,25,7) mm + typed (2,3,0) and (6,8,0); height 1 along +Z
    assert bounds(s, "rel1") == pytest.approx([17, 28, 7, 21, 33, 8], abs=1e-6)


def test_the_numeric_dialog_reads_its_position_from_the_working_cs(tab, desktop):
    _, s = desktop
    n0 = len(s.design.solids)
    tab.evaluate("()=>dlgDraw('box')")
    tab.wait_for_selector("#px", timeout=10000)
    assert "RelativeCS1" in tab.locator(".dialog:not([hidden]) .hint").first.inner_text()
    for sel, v in (("#px", "1mm"), ("#py", "1mm"), ("#pz", "0mm"),
                   ("#sx", "2mm"), ("#sy", "2mm"), ("#sz", "2mm")):
        tab.fill(sel, v)
    tab.click(".dialog:not([hidden]) .foot .pri")
    tab.wait_for_function(f"()=>STATE.design.objects.length==={n0 + 1}", timeout=30000)
    new = s.design.solids[-1].name
    assert bounds(s, new) == pytest.approx([16, 26, 7, 18, 28, 9], abs=1e-6)


def test_switching_back_to_global_shows_global_numbers(tab, desktop):
    tab.evaluate("()=>setWorkingCs('Global')")
    tab.wait_for_function("()=>STATE.design.workingCs===''", timeout=10000)
    assert "Global" in tab.locator("#status-cs").inner_text()
    tab.evaluate("()=>dlgDraw('box')")
    tab.wait_for_selector("#px", timeout=10000)
    assert tab.locator(".dialog:not([hidden]) .hint", has_text="RelativeCS1").count() == 0
    tab.keyboard.press("Escape")
    assert not tab.errs


def test_the_coordinate_systems_appear_in_the_project_tree(tab):
    names = tab.locator("#tree .node .lbl").all_inner_texts()
    assert "Coordinate Systems" in names and "RelativeCS1" in names and "Global" in names
    tab.locator("#tree .node", has_text="RelativeCS1").click()
    tab.wait_for_function("()=>STATE.design.workingCs==='RelativeCS1'", timeout=10000)
    tab.evaluate("()=>setWorkingCs('Global')")
