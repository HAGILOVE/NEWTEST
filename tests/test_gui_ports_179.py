"""
Browser tests for the 1.7.9 port workflow.

Assigning a port used to mean a dialog asking for a plane and a value --
coordinates the engineer has to look up before they can say the one thing
they already know: this conductor, that ground. These tests drive the pick
flow the way a user does: arm it, click a face, click the return, apply.
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
    srv, _, session = serve(port=8819, open_browser=False, token="",
                            block=False)
    yield "http://127.0.0.1:8819/", session
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
    pg.on("console", lambda m: errors.append(m.text[:200])
          if m.type == "error" else None)
    pg.errors = errors
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    yield pg
    pg.close()


@pytest.fixture
def page(tab):
    """A signal trace and a ground strip with a 1 mm gap between them."""
    tab.evaluate("""()=>{
      if (typeof PORTPICK !== 'undefined' && PORTPICK) cancelPortPick();
      closeAllDialogs();
      return rpc('project.new',{})
        .then(()=>rpc('modeler.draw',{shape:'box',name:'SIG',params:{
          position:['0mm','0mm','0mm'], size:['10mm','1mm','0.2mm']}}))
        .then(()=>rpc('modeler.draw',{shape:'box',name:'GND',params:{
          position:['0mm','2mm','0mm'], size:['10mm','1mm','0.2mm']}}))
        .then(()=>refreshGeometry(true));
    }""")
    tab.wait_for_function("()=>VP.objects.length===2", timeout=60000)
    tab.evaluate("()=>{setSelectMode('object'); setSelection([]); fitView();}")
    tab.wait_for_timeout(250)
    return tab


PICK = """async (spec)=>{
  const g = await rpc('view.geometry',{});
  const o = g.objects.find(x=>x.name===spec.obj);
  const f = o.faces.reduce((a,b)=> (spec.max ? (a.point[spec.k]>b.point[spec.k])
                                             : (a.point[spec.k]<b.point[spec.k])) ? a : b);
  return Object.assign({object:spec.obj}, f);
}"""


def _pick(page, obj, k, want_max):
    return page.evaluate(PICK, {"obj": obj, "k": k, "max": want_max})


def test_arming_the_flow_switches_to_face_picking_and_shows_the_panel(page):
    page.evaluate("()=>startPortPick('lumped')")
    page.wait_for_selector("#vp-draw.on", timeout=20000)
    assert page.evaluate("()=>SEL_MODE") == "face"
    assert "Signal" in page.locator("#vp-draw").inner_text()
    assert "Ground" in page.locator("#vp-draw").inner_text()
    page.evaluate("()=>cancelPortPick()")


def test_the_first_click_is_the_signal_and_the_flow_moves_on_to_ground(page):
    page.evaluate("()=>startPortPick('lumped')")
    page.wait_for_selector("#vp-draw.on", timeout=20000)
    sig = _pick(page, "SIG", 1, True)
    page.evaluate("(f)=>portPickFace(f,false)", sig)
    assert page.evaluate("()=>PORTPICK.signal.length") == 1
    assert page.evaluate("()=>PORTPICK.stage") == "gnd"
    assert "SIG" in page.locator("#pp-signal").inner_text()
    page.evaluate("()=>cancelPortPick()")


def test_apply_is_refused_until_both_picks_are_in(page):
    page.evaluate("()=>startPortPick('lumped')")
    page.wait_for_selector("#vp-draw.on", timeout=20000)
    assert page.locator("#pp-apply").is_disabled()
    page.evaluate("(f)=>portPickFace(f,false)", _pick(page, "SIG", 1, True))
    assert page.locator("#pp-apply").is_disabled()
    page.evaluate("(f)=>portPickFace(f,false)", _pick(page, "GND", 1, False))
    assert not page.locator("#pp-apply").is_disabled()
    page.evaluate("()=>cancelPortPick()")


def test_two_picks_and_apply_make_a_lumped_port_with_its_sheet(page):
    page.evaluate("()=>startPortPick('lumped')")
    page.wait_for_selector("#vp-draw.on", timeout=20000)
    page.evaluate("(f)=>portPickFace(f,false)", _pick(page, "SIG", 1, True))
    page.evaluate("(f)=>portPickFace(f,false)", _pick(page, "GND", 1, False))
    page.fill("#pp-z", "75")
    page.evaluate("()=>commitPortPick()")
    page.wait_for_function("()=>STATE.design.ports.length===1", timeout=30000)
    port = page.evaluate("()=>STATE.design.ports[0]")
    assert port["kind"] == "lumped"
    # the created sheet is a real object in the tree
    page.wait_for_function("()=>STATE.design.sheets.length===1", timeout=30000)
    assert page.evaluate("()=>STATE.design.sheets[0].name").endswith("_sheet")


def test_the_panel_closes_and_the_viewport_goes_back_to_normal(page):
    page.evaluate("()=>startPortPick('wave')")
    page.wait_for_selector("#vp-draw.on", timeout=20000)
    page.evaluate("()=>cancelPortPick()")
    assert not page.locator("#vp-draw").evaluate("e=>e.classList.contains('on')")
    assert page.evaluate("()=>PORTPICK") is None


def test_a_wave_port_needs_only_the_one_pick(page):
    page.evaluate("()=>startPortPick('wave')")
    page.wait_for_selector("#vp-draw.on", timeout=20000)
    page.evaluate("(f)=>portPickFace(f,false)", _pick(page, "SIG", 0, False))
    assert not page.locator("#pp-apply").is_disabled()
    page.evaluate("()=>commitPortPick()")
    page.wait_for_function("()=>STATE.design.ports.length===1", timeout=30000)
    assert page.evaluate("()=>STATE.design.ports[0].kind") == "wave"


def test_the_flow_leaves_no_javascript_errors_behind(page):
    assert [e for e in page.errors if "favicon" not in e] == []
