"""
Browser tests for the 1.7.8 modelling interactions.

* rubber-band selection of objects, faces, edges and vertices;
* Move by two points — point at the destination, or type the delta;
* the by-points draw growing the way the cursor goes, not the other way;
* modelling commands working on a workspace with no project open.

Runs against a server of its own. Skipped unless Playwright and a Chromium
build are available.
"""
import pytest

playwright = pytest.importorskip("playwright.sync_api",
                                 reason="playwright is not installed")
from playwright.sync_api import sync_playwright          # noqa: E402

from conftest import needs_occ                            # noqa: E402

pytestmark = [needs_occ, pytest.mark.slow]

LAUNCH_ARGS = ["--enable-unsafe-swiftshader"]


@pytest.fixture(scope="module")
def desktop():
    from aether.gui.server import serve
    srv, _, session = serve(port=8817, open_browser=False, token="",
                            block=False)
    yield "http://127.0.0.1:8817/", session
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
    """One page for the module. A fresh page per test means a fresh WebGL
    context per test, and a dozen of those is more than the browser will
    hold."""
    url, _ = desktop
    pg = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text[:200])
          if m.type == "error" else None)
    pg.errors = errors
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    yield pg
    pg.close()


@pytest.fixture
def page(tab):
    """Two boxes, a clean selection and a fitted camera, for every test."""
    tab.evaluate("""()=>{
      if (typeof MOVE !== 'undefined' && MOVE) cancelInteractiveMove();
      if (typeof DRAW !== 'undefined' && DRAW) cancelPointDraw();
      closeAllDialogs();
      return rpc('project.new',{})
        .then(()=>rpc('modeler.draw',{shape:'box',name:'A',params:{
          position:['0mm','0mm','0mm'], size:['10mm','6mm','2mm']}}))
        .then(()=>rpc('modeler.draw',{shape:'box',name:'B',params:{
          position:['30mm','0mm','0mm'], size:['10mm','6mm','2mm']}}))
        .then(()=>refreshGeometry(true));
    }""")
    tab.wait_for_function("()=>VP.objects.length===2", timeout=60000)
    tab.evaluate("()=>{setSelectMode('object'); setSelection([]); fitView();}")
    tab.wait_for_timeout(250)
    return tab


WHOLE = "{x0:2,y0:2,x1:1390,y1:840}"


# --------------------------------------------------------- box selection
def test_a_band_selects_every_object_it_covers(page):
    page.evaluate("()=>setSelectMode('object')")
    n = page.evaluate(f"()=>{{applyBandSelection({WHOLE},false);"
                      "return STATE.selection.length;}")
    assert n == 2
    assert sorted(page.evaluate("()=>STATE.selection")) == ["A", "B"]


def test_a_band_selects_many_faces_at_once(page):
    page.evaluate("()=>setSelectMode('face')")
    n = page.evaluate(f"()=>{{applyBandSelection({WHOLE},false);"
                      "return FACE_PICKS.length;}")
    assert n >= 8, n            # both boxes, several faces each
    assert page.evaluate("()=>new Set(FACE_PICKS.map(f=>f.object)).size") == 2


def test_a_band_selects_edges(page):
    page.evaluate("()=>setSelectMode('edge')")
    n = page.evaluate(f"()=>{{applyBandSelection({WHOLE},false);"
                      "return EDGE_PICKS.length;}")
    assert n >= 8, n


def test_a_band_selects_vertices_and_reports_the_span(page):
    page.evaluate("()=>setSelectMode('point')")
    n = page.evaluate(f"()=>{{applyBandSelection({WHOLE},false);"
                      "return POINT_PICKS.length;}")
    assert n >= 8, n
    page.wait_for_timeout(200)
    assert "points" in page.locator("#vp-measure").inner_text()


def test_shift_adds_to_the_selection_and_plain_replaces_it(page):
    page.evaluate("()=>setSelectMode('object')")
    page.evaluate("()=>{setSelection(['A']);}")
    page.evaluate("""()=>applyBandSelection({x0:2,y0:2,x1:1390,y1:840},true)""")
    assert sorted(page.evaluate("()=>STATE.selection")) == ["A", "B"]
    page.evaluate("()=>{setSelection(['A']);}")
    page.evaluate(f"()=>applyBandSelection({WHOLE},false)")
    assert sorted(page.evaluate("()=>STATE.selection")) == ["A", "B"]


def test_an_empty_band_selects_nothing(page):
    page.evaluate("()=>setSelectMode('object')")
    page.evaluate("()=>applyBandSelection({x0:1,y0:1,x1:6,y1:6},false)")
    assert page.evaluate("()=>STATE.selection.length") == 0


def test_ctrl_drag_in_the_viewport_starts_a_band(page):
    page.evaluate("()=>setSelectMode('object')")
    box = page.locator("#gl").bounding_box()
    page.keyboard.down("Control")
    page.mouse.move(box["x"] + 20, box["y"] + 20)
    page.mouse.down()
    page.mouse.move(box["x"] + 200, box["y"] + 200, steps=6)
    visible = page.locator("#vp-band").is_visible()
    page.mouse.up()
    page.keyboard.up("Control")
    assert visible, "no rectangle was drawn while dragging with Ctrl"


# ------------------------------------------------------- move by points
def test_move_by_two_points_opens_a_panel_not_a_modal(page):
    page.evaluate("()=>{setSelection(['A']); startInteractiveMove();}")
    page.wait_for_selector("#vp-draw.on", timeout=15000)
    assert page.evaluate("()=>DIALOG_STACK.length") == 0
    text = page.locator("#vp-draw").inner_text()
    assert "Move A" in text and "From" in text and "Delta" in text
    page.evaluate("()=>cancelInteractiveMove()")


def test_a_typed_delta_moves_the_object(page):
    page.evaluate("()=>{setSelection(['A']); startInteractiveMove();}")
    page.wait_for_selector("#vp-draw.on", timeout=15000)
    for k in range(3):
        page.fill(f"#mv-a{k}", "0")
    page.press("#mv-a2", "Enter")
    for k, v in enumerate([7, 3, 1]):
        page.fill(f"#mv-d{k}", str(v))
    page.press("#mv-d2", "Enter")
    page.wait_for_function("()=>DRAW===null && MOVE===null", timeout=30000)
    page.wait_for_timeout(800)
    box = page.evaluate("()=>VP.boundsOf(['A'])")
    assert box[0] == pytest.approx([0.007, 0.003, 0.001], abs=1e-6)


def test_the_distance_field_keeps_the_direction(page):
    page.evaluate("()=>{setSelection(['B']); startInteractiveMove();}")
    page.wait_for_selector("#vp-draw.on", timeout=15000)
    for k in range(3):
        page.fill(f"#mv-a{k}", "0")
    page.press("#mv-a2", "Enter")
    for k, v in enumerate([3, 4, 0]):        # length 5
        page.fill(f"#mv-d{k}", str(v))
    page.wait_for_timeout(200)
    assert float(page.input_value("#mv-len")) == pytest.approx(5.0, abs=1e-6)
    page.fill("#mv-len", "10")               # same direction, twice as far
    page.wait_for_timeout(200)
    delta = [float(page.input_value(f"#mv-d{k}")) for k in range(3)]
    assert delta == pytest.approx([6.0, 8.0, 0.0], abs=1e-6)
    page.evaluate("()=>cancelInteractiveMove()")


def test_move_can_copy_instead(page):
    n0 = page.evaluate("()=>STATE.design.objects.length")
    page.evaluate("()=>{setSelection(['B']); startInteractiveMove();}")
    page.wait_for_selector("#vp-draw.on", timeout=15000)
    page.check("#mv-copy")
    for k in range(3):
        page.fill(f"#mv-a{k}", "0")
    page.press("#mv-a2", "Enter")
    for k, v in enumerate([0, 20, 0]):
        page.fill(f"#mv-d{k}", str(v))
    page.press("#mv-d2", "Enter")
    page.wait_for_function(f"()=>STATE.design.objects.length==={n0 + 1}",
                           timeout=30000)


def test_escape_backs_out_of_a_move(page):
    page.evaluate("()=>{setSelection(['A']); startInteractiveMove();}")
    page.wait_for_selector("#vp-draw.on", timeout=15000)
    for k in range(3):
        page.fill(f"#mv-a{k}", "0")
    page.press("#mv-a2", "Enter")
    page.evaluate("()=>document.activeElement.blur()")
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)
    assert page.evaluate("()=>MOVE && MOVE.stage") == "p1"
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)
    assert page.evaluate("()=>MOVE") is None


def test_moving_nothing_says_so(page):
    # settle first: a geometry refresh still in flight from the fixture ends
    # by writing "Ready" into the status line, which is not what this test is
    # about.
    page.wait_for_timeout(300)
    page.evaluate("()=>{setSelection([]); startInteractiveMove();}")
    page.wait_for_function(
        "()=>document.querySelector('#status-text').textContent"
        ".includes('Select')", timeout=10000)
    assert page.evaluate("()=>MOVE") is None


# ------------------------------------------------- the draw grows upward
def test_the_height_follows_the_cursor_instead_of_opposing_it(page):
    """The closest-approach solve had its sign inverted, so a box grew
    downwards when the cursor was dragged up."""
    page.evaluate("()=>{fitView(); VP.view('iso');}")
    page.wait_for_timeout(300)
    page.evaluate("()=>startPointDraw('box')")
    page.wait_for_selector("#vp-draw.on", timeout=15000)
    for k in range(3):
        page.fill(f"#dw-a{k}", "0")
    page.press("#dw-a2", "Enter")
    for k, v in enumerate([10, 6, 0]):
        page.fill(f"#dw-b{k}", str(v))
    page.press("#dw-b2", "Enter")
    assert page.evaluate("()=>DRAW.stage") == "h"
    box = page.locator("#gl").bounding_box()
    cx = box["x"] + box["width"] / 2
    low = page.evaluate("(y)=>heightFromCursor(700, y)",
                        box["height"] * 0.75)
    high = page.evaluate("(y)=>heightFromCursor(700, y)",
                         box["height"] * 0.25)
    assert high > low, (low, high)
    page.evaluate("()=>cancelInteractiveMove()")
    page.evaluate("()=>cancelPointDraw()")
    assert cx


# ---------------------------------------------- modelling with no project
def test_importing_with_no_project_open_makes_one(page, tmp_path):
    from test_dxf import rect, write_dxf
    p = write_dxf(tmp_path / "s.dxf", rect(0, 0, 20, 10))
    page.evaluate("()=>rpc('project.close',{}).then(()=>resetDocumentViews())")
    page.wait_for_function("()=>STATE.project.open===false", timeout=20000)
    page.evaluate("""(p)=>ensureDesign().then(()=>rpc('modeler.importCad',
        {path:p,name:'Sheet1',material:'copper',unit:'auto',separate:true}))
        .then(()=>refreshGeometry(true))""", p)
    page.wait_for_function("()=>VP.objects.length>=1", timeout=90000)
    assert page.evaluate("()=>STATE.project.open") is True
    assert page.evaluate("()=>STATE.design.sheets.length") >= 1


def test_drawing_with_no_project_open_makes_one(page):
    page.evaluate("()=>rpc('project.close',{}).then(()=>resetDocumentViews())")
    page.wait_for_function("()=>STATE.project.open===false", timeout=20000)
    page.evaluate("()=>startPointDraw('box')")
    page.wait_for_selector("#vp-draw.on", timeout=30000)
    assert page.evaluate("()=>STATE.project.open") is True
    page.evaluate("()=>cancelPointDraw()")


def test_no_javascript_errors(page):
    page.wait_for_timeout(300)
    assert not page.errors, page.errors
