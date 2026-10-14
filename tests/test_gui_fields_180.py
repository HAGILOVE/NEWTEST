"""Field plots in the browser: E, H, surface current, cut plane, phase."""
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
    srv, _, session = serve(port=8824, open_browser=False, token="",
                            block=False)
    yield "http://127.0.0.1:8824/", session
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
    pg.evaluate("()=>rpc('view.fieldInfo',{})")
    pg.wait_for_function("()=>STATE.hasSolution===true", timeout=15000)
    yield pg
    pg.close()


def _wait_plot(page):
    page.wait_for_function("()=>!FIELD.busy && document.querySelector('#legend.on')",
                           timeout=60000)


def test_the_panel_opens_with_e_field_on_the_surfaces(tab):
    tab.evaluate("()=>showField(true)")
    tab.wait_for_selector("#vp-field", timeout=30000)
    _wait_plot(tab)
    assert "|E|" in tab.locator("#legend-labels").inner_text()
    assert tab.evaluate("()=>fieldOn") is True
    assert not tab.errors


def test_h_field_and_surface_current_are_one_click_away(tab):
    tab.select_option("#fp-q", "H")
    _wait_plot(tab)
    assert "|H|" in tab.locator("#legend-labels").inner_text()
    tab.select_option("#fp-q", "J")
    _wait_plot(tab)
    assert "|Js|" in tab.locator("#legend-labels").inner_text()
    # the model stays visible around a current plot, and the metal is plotted
    assert tab.evaluate("()=>VP.objects.length") > 1
    assert not tab.errors


def test_vector_arrows_appear_and_go_away(tab):
    tab.check("#fp-ar")
    _wait_plot(tab)
    assert tab.evaluate("()=>!!VP.arrowBuf && VP.arrowBuf.n > 100")
    tab.uncheck("#fp-ar")
    _wait_plot(tab)
    assert tab.evaluate("()=>!VP.arrowBuf")


def test_a_cut_plane_has_a_position_and_follows_the_slider(tab):
    tab.select_option("#fp-q", "E")
    tab.select_option("#fp-w", "cut")
    tab.wait_for_selector("#fp-ax", timeout=10000)
    _wait_plot(tab)
    before = tab.evaluate("()=>FIELD.pos")
    tab.evaluate("""()=>{const s=document.querySelector('#vp-field input[type=range]');
      s.value = String(parseFloat(s.value) + (parseFloat(s.max)-parseFloat(s.min))*0.2);
      s.dispatchEvent(new Event('input')); s.dispatchEvent(new Event('change'));}""")
    _wait_plot(tab)
    assert tab.evaluate("()=>FIELD.pos") > before
    assert not tab.errors


def test_phase_changes_the_instantaneous_field(tab):
    tab.select_option("#fp-w", "surface")
    _wait_plot(tab)
    tab.check("#fp-inst")
    _wait_plot(tab)
    a = tab.evaluate("()=>rpc('view.field',{quantity:'J',phase:0}).then(f=>f.scalar.slice(0,400))")
    b = tab.evaluate("()=>rpc('view.field',{quantity:'J',phase:90}).then(f=>f.scalar.slice(0,400))")
    assert a != b


def test_closing_the_panel_restores_the_model(tab):
    tab.evaluate("()=>showField(false)")
    tab.wait_for_function("()=>!document.querySelector('#vp-field')", timeout=10000)
    assert tab.evaluate("()=>fieldOn") is False
    assert tab.locator("#legend.on").count() == 0
    tab.wait_for_function("()=>VP.objects.some(o=>o.name!=='__field__')", timeout=30000)


def test_the_smith_chart_draws_the_reflection_trace(tab):
    tab.evaluate("()=>{reportForm='smith'; return openReport('sparam')}")
    tab.wait_for_selector(".doc-page.active svg polyline", timeout=60000)
    assert tab.locator(".doc-page.active svg circle").count() >= 10   # r and x circles
    assert "GHz" in tab.locator(".doc-page.active svg").inner_text()
    assert not tab.errors
    tab.evaluate("()=>{reportForm='db'}")
