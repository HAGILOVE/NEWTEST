"""
Browser tests for the 1.7.6 workspace changes.

* every dock edge is a splitter, and the message panel remembers its size;
* drawing by points happens in the viewport with a live coordinate panel
  instead of a modal dialog thrown over the model;
* the viewport says *why* it is blank, per object.

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
    srv, _, session = serve(port=8799, open_browser=False, token="",
                            block=False)
    yield "http://127.0.0.1:8799/", session
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


@pytest.fixture
def page(desktop, browser):
    url, session = desktop
    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text[:200])
          if m.type == "error" else None)
    pg.errors = errors
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    pg.evaluate("()=>rpc('project.new',{})")
    pg.wait_for_function("()=>STATE.design!==null", timeout=20000)
    pg.wait_for_timeout(300)
    yield pg
    pg.close()


# ------------------------------------------------------------ dock sizing
def test_every_dock_edge_has_a_splitter(page):
    for sel in ("#split-left", "#split-props", "#split-bottom"):
        assert page.locator(sel).count() == 1, sel


def test_the_message_dock_can_be_dragged_taller(page):
    before = page.evaluate(
        "()=>document.querySelector('#bottomdock').getBoundingClientRect().height")
    box = page.locator("#split-bottom").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] - 160, steps=8)
    page.mouse.up()
    page.wait_for_timeout(150)
    after = page.evaluate(
        "()=>document.querySelector('#bottomdock').getBoundingClientRect().height")
    assert after > before + 100, (before, after)


def test_the_size_is_remembered_and_resettable(page):
    page.evaluate("()=>{DOCKS.bottom=420; applyDocks(); saveDocks();}")
    stored = page.evaluate("()=>JSON.parse(localStorage.getItem('aether.docks.v1'))")
    assert stored["bottom"] == 420
    page.locator("#split-bottom").dblclick()
    page.wait_for_timeout(120)
    assert page.evaluate("()=>DOCKS.bottom") == 178


def test_the_left_dock_can_be_dragged_wider(page):
    before = page.evaluate(
        "()=>document.querySelector('#leftdock').getBoundingClientRect().width")
    box = page.locator("#split-left").bounding_box()
    page.mouse.move(box["x"] + 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + 140, box["y"] + box["height"] / 2, steps=8)
    page.mouse.up()
    page.wait_for_timeout(150)
    after = page.evaluate(
        "()=>document.querySelector('#leftdock').getBoundingClientRect().width")
    assert after > before + 90, (before, after)


def test_the_panel_collapses_to_its_tabs_and_back(page):
    page.evaluate("()=>{DOCKS.bottom=178; applyDocks();}")
    page.locator("#btn-dock-max").click()
    page.wait_for_timeout(120)
    assert page.evaluate("()=>DOCKS.bottom") > 300
    page.locator("#btn-dock-max").click()
    page.wait_for_timeout(120)
    assert page.evaluate("()=>DOCKS.bottom") == 178


# ---------------------------------------------------- drawing by points
def test_drawing_by_points_opens_a_panel_not_a_modal(page):
    page.evaluate("()=>startPointDraw('box')")
    page.wait_for_selector("#vp-draw.on", timeout=10000)
    # nothing modal: the viewport is still usable
    assert page.locator("#modal-back.on").count() == 0
    assert page.evaluate("()=>DIALOG_STACK.length") == 0
    text = page.locator("#vp-draw").inner_text()
    assert "Box by points" in text
    assert "Cursor" in text and "Corner 1" in text and "Height" in text
    page.evaluate("()=>cancelPointDraw()")


def test_the_panel_follows_the_cursor(page):
    page.evaluate("()=>startPointDraw('box')")
    page.wait_for_selector("#vp-draw.on", timeout=10000)
    box = page.locator("#gl").bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.42, box["y"] + box["height"] * 0.55)
    page.wait_for_timeout(160)
    page.mouse.move(box["x"] + box["width"] * 0.58, box["y"] + box["height"] * 0.45)
    page.wait_for_timeout(200)
    cursor = [page.input_value(f"#dw-c{k}") for k in range(3)]
    assert any(c not in ("", "0") for c in cursor), cursor
    # and the status bar carries the same live readout
    assert "X " in page.locator("#status-xyz").inner_text()
    page.evaluate("()=>cancelPointDraw()")


def test_typed_coordinates_are_as_good_as_clicks(page):
    """The whole point: draw with the mouse OR type the numbers, in the same
    panel, without a modal in the way."""
    page.evaluate("()=>startPointDraw('box')")
    page.wait_for_selector("#vp-draw.on", timeout=10000)
    for k, v in enumerate([0, 0, 0]):
        page.fill(f"#dw-a{k}", str(v))
        page.press(f"#dw-a{k}", "Enter")
    for k, v in enumerate([12, 6, 0]):
        page.fill(f"#dw-b{k}", str(v))
        page.press(f"#dw-b{k}", "Enter")
    page.fill("#dw-h", "3")
    page.fill("#dw-name", "TypedBox")
    page.press("#dw-h", "Enter")
    page.wait_for_function(
        "()=>STATE.design.objects.some(o=>o.name==='TypedBox')", timeout=30000)
    size = page.evaluate("""async ()=>{
      await rpc('modeler.select',{names:['TypedBox']});
      return (await rpc('modeler.measure',{})).size;
    }""")
    assert size == pytest.approx([0.012, 0.006, 0.003], abs=1e-9)
    assert page.evaluate("()=>document.querySelector('#vp-draw').classList"
                         ".contains('on')") is False


def test_the_live_size_readout_tracks_the_drag(page):
    page.evaluate("()=>startPointDraw('rectangle')")
    page.wait_for_selector("#vp-draw.on", timeout=10000)
    for k, v in enumerate([0, 0, 0]):
        page.fill(f"#dw-a{k}", str(v))
    page.press("#dw-a2", "Enter")
    for k, v in enumerate([8, 5, 0]):
        page.fill(f"#dw-b{k}", str(v))
    page.wait_for_timeout(150)
    assert [page.input_value(f"#dw-s{k}") for k in range(3)][:2] == ["8", "5"]
    assert page.evaluate("()=>VP.draft && VP.draft.length >= 5")
    page.evaluate("()=>cancelPointDraw()")


def test_escape_steps_back_one_point_instead_of_starting_over(page):
    page.evaluate("()=>startPointDraw('box')")
    page.wait_for_selector("#vp-draw.on", timeout=10000)
    for k in range(3):
        page.fill(f"#dw-a{k}", "0")
    page.press("#dw-a2", "Enter")
    assert page.evaluate("()=>DRAW.stage") == "p2"
    page.evaluate("()=>document.activeElement.blur()")
    page.keyboard.press("Escape")
    page.wait_for_timeout(120)
    assert page.evaluate("()=>DRAW && DRAW.stage") == "p1"
    page.keyboard.press("Escape")
    page.wait_for_timeout(120)
    assert page.evaluate("()=>DRAW") is None


def test_a_cylinder_by_points_uses_radius_and_height(page):
    page.evaluate("()=>startPointDraw('cylinder')")
    page.wait_for_selector("#vp-draw.on", timeout=10000)
    for k in range(3):
        page.fill(f"#dw-a{k}", "0")
    page.press("#dw-a2", "Enter")
    page.fill("#dw-r", "4")
    page.press("#dw-r", "Enter")
    page.fill("#dw-name", "TypedCyl")
    page.fill("#dw-h", "10")
    page.press("#dw-h", "Enter")
    page.wait_for_function(
        "()=>STATE.design.objects.some(o=>o.name==='TypedCyl')", timeout=30000)
    size = page.evaluate("""async ()=>{
      await rpc('modeler.select',{names:['TypedCyl']});
      return (await rpc('modeler.measure',{})).size;
    }""")
    assert size == pytest.approx([0.008, 0.008, 0.010], abs=2e-4)


def test_a_degenerate_box_says_what_is_wrong(page):
    """A box drawn edge-on to the camera has zero width. The button being
    greyed out with no explanation is not an answer."""
    page.evaluate("()=>startPointDraw('box')")
    page.wait_for_selector("#vp-draw.on", timeout=10000)
    for k in range(3):
        page.fill(f"#dw-a{k}", "0")
    page.press("#dw-a2", "Enter")
    for k, v in enumerate([0, 5, 0]):          # no extent in X
        page.fill(f"#dw-b{k}", str(v))
    page.press("#dw-b2", "Enter")
    page.fill("#dw-h", "2")
    page.wait_for_timeout(200)
    assert page.locator("#dw-create").is_disabled()
    assert "X size is zero" in page.locator("#dw-warn").inner_text()
    page.fill("#dw-s0", "7")                   # fix it by typing
    page.wait_for_timeout(200)
    assert page.locator("#dw-create").is_enabled()
    assert page.locator("#dw-warn").inner_text().strip() == ""
    page.evaluate("()=>cancelPointDraw()")


# ------------------------------------------------------- why it is blank
def test_the_display_report_explains_a_transparent_model(page):
    page.evaluate("""()=>rpc('project.new',{}).then(()=>rpc('modeler.draw',
      {shape:'box',name:'AirBox',params:{position:['0mm','0mm','0mm'],
       size:['50mm','50mm','50mm']}}))""")
    page.wait_for_function("()=>STATE.design.objects.length===1", timeout=30000)
    r = page.evaluate("()=>rpc('view.displayReport',{})")
    assert r["rows"][0]["state"] == "displayed"
    assert "transparent" in r["summary"]
    assert r["faint"] == ["AirBox"]


def test_solid_display_can_be_switched_on(page):
    assert page.evaluate("()=>VP.opaque") is False
    page.evaluate("()=>toggleOpaque()")
    assert page.evaluate("()=>VP.opaque") is True
    assert page.evaluate(
        "()=>document.querySelector('#vt-solid').classList.contains('on')")
    page.evaluate("()=>toggleOpaque()")


def test_the_diagnostics_dialog_lists_every_object(page):
    page.evaluate("""()=>rpc('project.new',{}).then(()=>rpc('modeler.draw',
      {shape:'box',name:'B1',params:{position:['0mm','0mm','0mm'],
       size:['5mm','5mm','5mm']}}))""")
    page.wait_for_function("()=>STATE.design.objects.length===1", timeout=30000)
    page.evaluate("()=>dlgDisplayReport()")
    page.wait_for_selector("#modal-back.on .dialog", timeout=20000)
    text = page.locator("#modal-back > .dialog:not([hidden])").inner_text()
    assert "B1" in text and "displayed" in text
    page.click("#modal-back > .dialog:not([hidden]) .foot button")


def test_fit_selection_frames_a_small_part_inside_a_big_box(page):
    """Fit All frames the radiation box and leaves the patch sub-pixel. Fit
    Selection is the way back to the part you are working on."""
    page.evaluate("""()=>rpc('project.new',{})
      .then(()=>rpc('modeler.draw',{shape:'box',name:'Region',params:{
        position:['0mm','0mm','0mm'], size:['200mm','200mm','200mm']}}))
      .then(()=>rpc('modeler.draw',{shape:'box',name:'Patch',params:{
        position:['100mm','100mm','100mm'], size:['2mm','2mm','0.1mm']}}))""")
    page.wait_for_function("()=>STATE.design.objects.length===2", timeout=60000)
    page.evaluate("()=>refreshGeometry(true)")
    page.wait_for_function("()=>VP.objects.length===2", timeout=60000)
    page.evaluate("()=>fitView()")
    page.wait_for_timeout(120)
    whole = page.evaluate("()=>VP.dist")
    page.evaluate("()=>{setSelection(['Patch']); fitSelection();}")
    page.wait_for_timeout(200)
    near = page.evaluate("()=>VP.dist")
    assert near < whole / 10, (whole, near)
    centre = page.evaluate("()=>VP.center")
    assert centre[0] == pytest.approx(0.101, abs=2e-3)


def test_no_javascript_errors(page):
    page.wait_for_timeout(300)
    assert not page.errors, page.errors
