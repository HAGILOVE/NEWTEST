"""Browser test: the radiation-pattern report and the 3-D pattern view."""
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
    srv, _, session = serve(port=8822, open_browser=False, token="",
                            block=False)
    yield "http://127.0.0.1:8822/", session
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
    from test_farfield_180 import dipole
    session.new_project("Dipole")
    d = dipole()
    session.project.designs[0] = d
    session.design = d
    session.solution = d.solve(adaptive=False, progress=False,
                               save_fields=True)
    pg = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.errors = errors
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    yield pg
    pg.close()


def test_the_pattern_report_shows_a_polar_plot_and_the_antenna_table(tab):
    tab.evaluate("()=>rpc('results.farField',{})")          # refreshes STATE
    tab.wait_for_function("()=>STATE.hasSolution===true", timeout=15000)
    tab.evaluate("()=>openReport('farfield')")
    tab.wait_for_selector(".doc-page.active svg", timeout=60000)
    text = tab.locator(".doc-page.active").inner_text()
    assert "Peak directivity" in text and "Radiation efficiency" in text
    assert "Front-to-back ratio" in text
    assert tab.locator(".doc-page.active svg circle").count() >= 4   # grid rings
    assert tab.locator(".doc-page.active svg polyline").count() == 2  # two cuts
    assert not tab.errors


def test_switching_to_a_rectangular_plot(tab):
    tab.select_option("#ff-mode", "rect")
    tab.wait_for_function("()=>document.querySelector('.doc-page.active svg polyline')"
                          "&&!document.querySelector('.doc-page.active svg circle')",
                          timeout=30000)
    assert not tab.errors


def test_the_3d_pattern_is_drawn_in_the_viewport(tab):
    tab.evaluate("()=>{selectPage('modeler'); return showPattern(true,{})}")
    tab.wait_for_function("()=>patternShown()===true&&!FIELD.busy", timeout=60000)
    assert tab.locator("#legend.on").count() == 1
    assert "Gain" in tab.locator("#legend-labels").inner_text()
    assert "dBi" in tab.locator("#legend-labels").inner_text()
    # the pattern is a field-panel quantity now: animation and opacity controls
    assert tab.locator("#fp-pa").count() == 1 and tab.locator("#fp-ma").count() == 1
    tab.evaluate("()=>showPattern(false)")
    tab.wait_for_function("()=>patternShown()===false", timeout=30000)
    assert not tab.errors
