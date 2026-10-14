"""
Drawing on the YZ / ZX planes, typing with Tab, and the new by-points shapes.

The rectangle used to be drawn on XY whatever plane the user meant; the
numbers a user types here must come out in the geometry exactly as typed.
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
    srv, _, session = serve(port=8823, open_browser=False, token="",
                            block=False)
    yield "http://127.0.0.1:8823/", session
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
    url, _ = desktop
    pg = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.errors = errors
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    yield pg
    pg.close()


@pytest.fixture
def page(tab):
    tab.evaluate("()=>{cancelPointDraw(); closeAllDialogs(); return rpc('project.new',{}).then(()=>refreshGeometry(true))}")
    tab.wait_for_timeout(200)
    return tab


def _open(page, kind, plane=None):
    page.evaluate(f"()=>startPointDraw('{kind}')")
    page.wait_for_selector("#vp-draw.on", timeout=10000)
    if plane:
        page.click(f"#dw-pl-{plane}")
        page.wait_for_function(f"()=>DRAW.plane==='{plane}'")


def _type_point(page, prefix, vals):
    for k, v in enumerate(vals):
        page.fill(f"#dw-{prefix}{k}", str(v))


def _size(page, name):
    return page.evaluate("""async (n)=>{
      await rpc('modeler.select',{names:[n]});
      return (await rpc('modeler.measure',{})).size;
    }""", name)


def _bounds(page, name):
    return page.evaluate("""async (n)=>{
      const g = await rpc('view.geometry',{});
      return g.objects.find(o=>o.name===n);
    }""", name)


def test_the_panel_offers_three_work_planes_and_starts_on_xy(page):
    _open(page, "rectangle")
    assert page.evaluate("()=>DRAW.plane") == "xy"
    for k in ("xy", "yz", "zx"):
        assert page.locator(f"#dw-pl-{k}").count() == 1
    page.evaluate("()=>cancelPointDraw()")


@pytest.mark.parametrize("plane,a,b,expect_axes", [
    ("xy", [0, 0, 2], [8, 5, 2], (0, 1)),
    ("yz", [3, 0, 0], [3, 6, 4], (1, 2)),
    ("zx", [0, 7, 0], [4, 7, 9], (0, 2)),
])
def test_a_rectangle_is_drawn_on_the_plane_that_was_chosen(page, plane, a, b,
                                                           expect_axes):
    _open(page, "rectangle", plane)
    page.fill("#dw-name", "R")
    _type_point(page, "a", a)
    page.press("#dw-a0", "Enter")
    _type_point(page, "b", b)
    page.press("#dw-b0", "Enter")
    page.wait_for_function("()=>STATE.design.sheets.some(s=>s.name==='R')",
                           timeout=30000)
    size = _size(page, "R")
    flat = [i for i in range(3) if abs(size[i]) < 1e-9]
    assert flat == [3 - sum(expect_axes)], (plane, size)
    want = {"xy": (0.008, 0.005), "yz": (0.006, 0.004),
            "zx": (0.004, 0.009)}[plane]
    got = [size[i] for i in expect_axes]
    assert got == pytest.approx(list(want), abs=1e-9)
    assert not page.errors


def test_a_box_on_the_yz_plane_grows_along_x(page):
    _open(page, "box", "yz")
    page.fill("#dw-name", "B")
    _type_point(page, "a", [1, 0, 0])
    page.press("#dw-a0", "Enter")
    _type_point(page, "b", [1, 5, 3])
    page.press("#dw-b0", "Enter")
    page.fill("#dw-h", "7")
    page.press("#dw-h", "Enter")
    page.wait_for_function("()=>STATE.design.objects.some(o=>o.name==='B')",
                           timeout=30000)
    assert _size(page, "B") == pytest.approx([0.007, 0.005, 0.003], abs=1e-9)


def test_a_cylinder_axis_follows_the_plane_normal(page):
    _open(page, "cylinder", "zx")
    page.fill("#dw-name", "Cy")
    _type_point(page, "a", [0, 2, 0])
    page.press("#dw-a0", "Enter")
    page.fill("#dw-r", "3")
    page.press("#dw-r", "Enter")
    page.fill("#dw-h", "10")
    page.press("#dw-h", "Enter")
    page.wait_for_function("()=>STATE.design.objects.some(o=>o.name==='Cy')",
                           timeout=30000)
    size = _size(page, "Cy")
    assert size == pytest.approx([0.006, 0.010, 0.006], abs=3e-4)   # axis = Y


def test_circle_sphere_and_cone_by_points(page):
    _open(page, "circle", "yz")
    page.fill("#dw-name", "Disc")
    _type_point(page, "a", [0, 0, 0])
    page.press("#dw-a0", "Enter")
    page.fill("#dw-r", "4")
    page.press("#dw-r", "Enter")
    page.wait_for_function("()=>STATE.design.sheets.some(o=>o.name==='Disc')",
                           timeout=30000)
    size = _size(page, "Disc")
    assert abs(size[0]) < 1e-6 and size[1] == pytest.approx(0.008, abs=3e-4)

    _open(page, "sphere")
    page.fill("#dw-name", "Ball")
    _type_point(page, "a", [20, 0, 0])
    page.press("#dw-a0", "Enter")
    page.fill("#dw-r", "5")
    page.press("#dw-r", "Enter")
    page.wait_for_function("()=>STATE.design.objects.some(o=>o.name==='Ball')",
                           timeout=30000)
    assert _size(page, "Ball") == pytest.approx([0.010] * 3, abs=4e-4)

    _open(page, "cone")
    page.fill("#dw-name", "Cn")
    _type_point(page, "a", [40, 0, 0])
    page.press("#dw-a0", "Enter")
    page.fill("#dw-r", "4")
    page.press("#dw-r", "Enter")
    page.fill("#dw-h", "9")
    page.press("#dw-h", "Enter")
    page.wait_for_function("()=>STATE.design.objects.some(o=>o.name==='Cn')",
                           timeout=30000)
    assert _size(page, "Cn")[2] == pytest.approx(0.009, abs=3e-4)


def test_tab_takes_the_keyboard_and_walks_the_relevant_fields(page):
    _open(page, "rectangle")
    page.evaluate("()=>document.activeElement.blur()")
    page.keyboard.press("Tab")
    assert page.evaluate("()=>DRAW.typing") is True
    assert page.evaluate("()=>document.activeElement.id") == "dw-a0"
    page.keyboard.type("5")
    page.keyboard.press("Tab")
    assert page.evaluate("()=>document.activeElement.id") == "dw-a1"
    page.keyboard.press("Tab")
    assert page.evaluate("()=>document.activeElement.id") == "dw-a2"
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("()=>document.activeElement.id") == "dw-a1"
    page.evaluate("()=>cancelPointDraw()")


def test_while_typing_the_mouse_does_not_overwrite_the_numbers(page):
    _open(page, "rectangle")
    _type_point(page, "a", [1, 2, 0])
    page.press("#dw-a0", "Enter")                       # now waiting on point 2
    page.fill("#dw-s0", "9")
    box = page.locator("#gl").bounding_box()
    page.mouse.move(box["x"] + 200, box["y"] + 200)
    page.mouse.move(box["x"] + 260, box["y"] + 240)
    page.wait_for_timeout(200)
    assert page.evaluate("()=>DRAW.p2[0]-DRAW.p1[0]") == pytest.approx(0.009)
    page.evaluate("()=>cancelPointDraw()")


def test_escape_hands_the_numbers_back_to_the_mouse_before_stepping_back(page):
    _open(page, "rectangle")
    page.keyboard.press("Tab")
    assert page.evaluate("()=>DRAW.typing") is True
    page.keyboard.press("Escape")
    assert page.evaluate("()=>DRAW && DRAW.typing") is False
    assert page.evaluate("()=>DRAW && DRAW.stage") == "p1"
    page.evaluate("()=>cancelPointDraw()")


def test_the_p_key_cycles_the_work_plane(page):
    _open(page, "box")
    page.evaluate("()=>document.activeElement.blur()")
    page.keyboard.press("p")
    assert page.evaluate("()=>DRAW.plane") == "yz"
    page.keyboard.press("p")
    assert page.evaluate("()=>DRAW.plane") == "zx"
    page.keyboard.press("p")
    assert page.evaluate("()=>DRAW.plane") == "xy"
    page.evaluate("()=>cancelPointDraw()")


def test_a_degenerate_size_on_another_plane_names_the_right_axis(page):
    _open(page, "rectangle", "yz")
    _type_point(page, "a", [0, 0, 0])
    page.press("#dw-a0", "Enter")
    _type_point(page, "b", [0, 0, 5])                   # no Y extent
    page.press("#dw-b0", "Enter")
    page.wait_for_timeout(150)
    assert page.locator("#dw-create").is_disabled()
    assert "Y size is zero" in page.locator("#dw-warn").inner_text()
    page.evaluate("()=>cancelPointDraw()")
