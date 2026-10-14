"""
Browser tests for the eigenmode workflow (1.8.0): insert an eigenmode design,
draw the cavity, add the eigenmode setup, analyse, read the resonances.
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
    srv, _, session = serve(port=8821, open_browser=False, token="",
                            block=False)
    yield "http://127.0.0.1:8821/", session
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


def _build(tab):
    tab.evaluate("""()=>{
      closeAllDialogs();
      return rpc('project.new',{})
        .then(()=>rpc('project.insertDesign',{solutionType:'eigenmode'}))
        .then(()=>rpc('modeler.draw',{shape:'box',name:'Cavity',params:{
          position:['0mm','0mm','0mm'], size:['30mm','15mm','20mm']}}))
        .then(()=>rpc('boundary.assign',{type:'pec',name:'Walls',
                                          selector:{kind:'outer'}}))
        .then(()=>refreshGeometry(true));
    }""")


def test_eigenmode_design_offers_the_eigenmode_setup_dialog(tab):
    _build(tab)
    tab.wait_for_function("()=>STATE.design && STATE.design.solutionType==='eigenmode'",
                          timeout=30000)
    tab.evaluate("()=>dlgSetup()")
    tab.wait_for_selector("#su-nm", timeout=10000)
    assert tab.locator("#su-fmin").count() == 1
    tab.fill("#su-nm", "2")
    tab.fill("#su-f", "10GHz")
    tab.select_option("#su-bo", "2")
    tab.evaluate("()=>document.querySelector('.dialog .foot .pri').click()")
    tab.wait_for_function("()=>STATE.design.setups.length===1", timeout=30000)
    st = tab.evaluate("()=>STATE.design.setups[0]")
    assert st["nModes"] == 2 and st["basisOrder"] == 2


def test_a_sweep_cannot_be_added_to_an_eigenmode_design(tab):
    tab.evaluate("()=>{closeAllDialogs(); dlgSweep();}")
    tab.wait_for_timeout(300)
    assert tab.locator("#sw-kind").count() == 0


def test_analysis_results_open_as_the_eigenmode_table(tab, desktop):
    _, session = desktop
    d = session.design
    d.config.mesh.max_element_size = 0.006
    sol = d.solve(adaptive=False, progress=False)
    session.solution = sol
    tab.evaluate("()=>rpc('results.eigenModes',{})")      # refreshes STATE
    tab.wait_for_function("()=>STATE.hasSolution===true", timeout=15000)
    tab.evaluate("()=>openReport('sparam')")
    tab.wait_for_selector(".doc-page.active table.grid", timeout=30000)
    text = tab.locator(".doc-page.active").inner_text()
    assert "Frequency [GHz]" in text and "Q" in text
    assert "9.00" in text                      # TE101 of the 30x15x20 mm cavity
    assert "lossless" in text
    assert not tab.errors


def test_a_mode_can_be_shown_as_a_field_overlay(tab):
    tab.evaluate("()=>showField(true,{excitation:0})")
    tab.wait_for_function("()=>fieldOn === true", timeout=30000)
    assert tab.locator("#legend.on").count() == 1
    tab.evaluate("()=>showField(false)")
