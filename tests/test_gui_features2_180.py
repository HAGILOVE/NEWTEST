"""Ports between two selected metals, lumped RLC, snapping while drawing,
Hide / Show in the context menus, files that open solid."""
import pytest

playwright = pytest.importorskip("playwright.sync_api",
                                 reason="playwright is not installed")
from playwright.sync_api import sync_playwright          # noqa: E402

from conftest import needs_occ                            # noqa: E402
from test_autoport_geom_180 import patch_with_feed        # noqa: E402

pytestmark = [needs_occ, pytest.mark.slow]

LAUNCH_ARGS = ["--enable-unsafe-swiftshader"]


@pytest.fixture(scope="module")
def desktop():
    from aether.gui.server import serve
    srv, _, session = serve(port=8838, open_browser=False, token="", block=False)
    yield "http://127.0.0.1:8838/", session
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


def open_page(desktop, browser, design=None):
    url, session = desktop
    session.new_project("P")
    if design is not None:
        session.project.designs[0] = design
        session.design = design
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
def patch_tab(desktop, browser):
    pg, session = open_page(desktop, browser, patch_with_feed())
    yield pg, session
    pg.close()


def select(pg, *names):
    pg.evaluate("(n)=>rpc('modeler.select',{names:n})", list(names))
    pg.evaluate("async()=>{STATE=await (await fetch('/api/state?token='+encodeURIComponent(window.AETHER_TOKEN))).json();renderAll();}")
    pg.wait_for_timeout(200)


# ----------------------------------------------------- ports between metals
def test_two_selected_metals_open_the_automatic_port_dialog(patch_tab):
    pg, session = patch_tab
    select(pg, "patch", "gnd")
    pg.evaluate("()=>dlgExcitation('lumped')")
    pg.wait_for_selector("#pb-sig", timeout=10000)
    assert pg.input_value("#pb-sig") == "patch" and pg.input_value("#pb-gnd") == "gnd"
    pg.wait_for_function("()=>/3 mm wide/.test(document.querySelector('#pb-info').textContent)", timeout=10000)
    text = pg.inner_text("#pb-info")
    assert "Lumped port" in text and "-30" in text
    # swapping reports the other way round, wave shows its own description
    pg.select_option("#pb-kind", "wave")
    pg.wait_for_function("()=>/Wave port/.test(document.querySelector('#pb-info').textContent)", timeout=10000)
    pg.select_option("#pb-kind", "lumped")
    pg.click("#dialog-ok, .dlg-ok, button:has-text('Assign')")
    pg.wait_for_timeout(800)
    port = session.design.ports[0]
    assert port.kind == "lumped"
    sheet = session.design.sheets[-1]
    lo, hi = sheet.shape.bounds()
    assert hi[0] - lo[0] == pytest.approx(3e-3, abs=1e-9)           # the feed line's width
    assert not pg.errs


def test_lumped_rlc_between_two_metals(patch_tab):
    pg, session = patch_tab
    select(pg, "patch", "gnd")
    pg.evaluate("()=>dlgRlc()")
    pg.wait_for_selector("#rl-R", timeout=10000)
    pg.fill("#rl-R", "75")
    pg.fill("#rl-C", "0.5p")
    pg.click("button:has-text('Assign')")
    pg.wait_for_timeout(800)
    b = session.design.boundaries[-1]
    assert b.btype == "lumped_rlc" and b.params["R"] == 75.0
    assert b.params["C"] == pytest.approx(0.5e-12)
    assert abs(b.params["direction"][2]) == pytest.approx(1.0)
    assert not pg.errs


# ------------------------------------------------------------ hide / show
def test_the_object_menu_hides_and_shows(patch_tab):
    pg, session = patch_tab
    pg.locator("#tree .node:has-text(\"subvacuum\")").first.click(button="right")
    pg.wait_for_selector(".ctx")
    labels = pg.evaluate("()=>[...document.querySelectorAll('.ctx button')].map(b=>b.textContent+(b.disabled?' [off]':''))")
    assert "Hide" in labels and "Show [off]" in labels
    pg.locator(".ctx button", has_text="Hide").first.click()
    pg.wait_for_timeout(600)
    assert pg.evaluate("()=>STATE.design.objects.find(o=>o.name==='sub').visible") is False
    pg.locator("#tree .node:has-text(\"subvacuum\")").first.click(button="right")
    pg.wait_for_selector(".ctx")
    labels = pg.evaluate("()=>[...document.querySelectorAll('.ctx button')].map(b=>b.textContent+(b.disabled?' [off]':''))")
    assert "Show" in labels and "Hide [off]" in labels
    pg.locator(".ctx button", has_text="Show").first.click()
    pg.wait_for_timeout(600)
    assert pg.evaluate("()=>STATE.design.objects.find(o=>o.name==='sub').visible") is True


def test_the_viewport_menu_has_hide_and_show_too(patch_tab):
    pg, _ = patch_tab
    select(pg, "gnd")
    pg.evaluate("()=>viewportContext(null,{clientX:300,clientY:300,preventDefault(){},stopPropagation(){}})")
    pg.wait_for_selector(".ctx")
    labels = pg.evaluate("()=>[...document.querySelectorAll('.ctx button')].map(b=>b.textContent)")
    assert {"Hide", "Show", "Hide Others", "Show All"} <= set(labels)
    pg.locator(".ctx button", has_text="Hide Others").first.click()
    pg.wait_for_timeout(600)
    vis = pg.evaluate("()=>[...STATE.design.objects,...STATE.design.sheets].filter(o=>o.visible!==false).map(o=>o.name)")
    assert vis == ["gnd"]
    pg.evaluate("()=>viewportContext(null,{clientX:300,clientY:300,preventDefault(){},stopPropagation(){}})")
    pg.locator(".ctx button", has_text="Show All").first.click()
    pg.wait_for_timeout(600)
    assert pg.evaluate("()=>[...STATE.design.objects,...STATE.design.sheets].every(o=>o.visible!==false)")


# -------------------------------------------------------- opens solid
def test_a_file_opens_solid_while_air_stays_see_through(desktop, browser, tmp_path):
    from aether.gui.api import dispatch
    url, session = desktop
    session.new_project("P")
    d = patch_with_feed()
    session.project.designs[0] = d
    session.design = d
    d.get_solid("sub").display_transparency = 0.6          # a translucent part
    path = str(tmp_path / "solid.warp")
    dispatch(session, "project.save", {"path": path})
    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    pg.evaluate("p=>openProjectFile(p)", path)
    pg.wait_for_function("()=>VP && VP.objects && VP.objects.length>3", timeout=60000)
    pg.wait_for_timeout(400)
    solid = pg.evaluate("""()=>VP.objects.map(o=>[o.name, o.alpha,
        VP.opaque || (VP.solidParts && o.alpha>=0.2 && !VP.userAlpha.has(o.name))])""")
    by = {n: (a, s) for n, a, s in solid}
    assert by["sub"][1] is True and by["gnd"][1] is True       # parts drawn opaque
    assert by["air"][1] is False                               # the air box stays see-through
    assert pg.evaluate("()=>VP.solidParts") is True
    # a transparency the user sets is respected afterwards
    pg.evaluate("()=>noteUserTransparency(['sub'], 0.5)")
    assert pg.evaluate("()=>VP.userAlpha.has('sub')") is True
    # the toolbar button turns it off again
    pg.evaluate("()=>toggleOpaque()")
    assert pg.evaluate("()=>[VP.opaque, VP.solidParts]") == [False, False]
    assert not errs
    pg.close()


# ------------------------------------------------------------- snapping
def box_design():
    import aether as ae
    d = ae.Design("snap", units="mm")
    d.add_box("b", (0, 0, 0), (23.7e-3, 11.3e-3, 6.1e-3), "pec")
    return d


def screen(pg, point):
    box = pg.locator("#gl").bounding_box()
    q = pg.evaluate("p=>VP.project(p)", point)
    return box["x"] + q["x"], box["y"] + q["y"]


@pytest.mark.parametrize("target,kind", [
    ([23.7e-3, 0.0, 6.1e-3], "vertex"),
    ([11.85e-3, 0.0, 6.1e-3], "edge midpoint"),
    ([11.85e-3, 5.65e-3, 6.1e-3], "face centre"),
])
def test_drawing_snaps_to_vertices_edge_middles_and_face_centres(desktop, browser, target, kind):
    pg, _ = open_page(desktop, browser, box_design())
    pg.evaluate("()=>VP.view('iso')")
    pg.wait_for_timeout(300)
    pg.evaluate("()=>startPointDraw('rectangle')")
    pg.wait_for_selector("#vp-draw.on")
    assert pg.is_checked("#dw-geosnap")
    x, y = screen(pg, target)
    pg.mouse.move(x + 3, y + 2)                       # a few pixels off: it must jump onto the feature
    pg.wait_for_timeout(250)
    p1 = pg.evaluate("()=>DRAW.p1")
    assert p1 == pytest.approx(target, abs=1e-9), (kind, p1)
    assert kind in pg.inner_text("#vp-hint")
    # with the option off the point goes back to the grid / plane
    pg.uncheck("#dw-geosnap")
    pg.mouse.move(x + 3, y + 2)
    pg.wait_for_timeout(250)
    p_off = pg.evaluate("()=>DRAW.p1")
    assert p_off != pytest.approx(target, abs=1e-9)
    assert not pg.errs
    pg.close()


def test_a_snapped_click_starts_the_plane_at_that_point(desktop, browser):
    pg, _ = open_page(desktop, browser, box_design())
    pg.evaluate("()=>VP.view('iso')")
    pg.wait_for_timeout(300)
    pg.evaluate("()=>startPointDraw('rectangle')")
    pg.wait_for_selector("#vp-draw.on")
    x, y = screen(pg, [11.85e-3, 5.65e-3, 6.1e-3])
    pg.mouse.click(x + 2, y + 2)
    pg.wait_for_timeout(250)
    assert pg.evaluate("()=>DRAW.stage") == "p2"
    assert pg.evaluate("()=>DRAW.p1") == pytest.approx([11.85e-3, 5.65e-3, 6.1e-3], abs=1e-9)
    assert pg.evaluate("()=>DRAW.offset") == pytest.approx(6.1e-3, abs=1e-9)   # the top face is now the plane
    pg.close()
