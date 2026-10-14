"""Results in the browser: the list under Results, a full-window plot with
markers and axis control, opacity of the plot and of the model."""
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
    srv, _, session = serve(port=8827, open_browser=False, token="",
                            block=False)
    yield "http://127.0.0.1:8827/", session
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
    from test_sweep_180 import guide
    session.new_project("Guide")
    d = guide("discrete", "9GHz", "11GHz", 9)
    session.project.designs[0] = d
    session.design = d
    session.solution = d.solve(adaptive=False, progress=False, save_fields=True)
    session.solution_serial += 1
    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.errors = errors
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    pg.evaluate("async()=>{STATE=await (await fetch('/api/state?token='+"
                "encodeURIComponent(window.AETHER_TOKEN))).json();renderAll();}")
    pg.wait_for_function("()=>RESULTS.items.length>=3", timeout=20000)
    yield pg
    pg.close()


def labels(pg):
    return pg.locator("#tree .node .lbl").all_inner_texts()


def test_results_are_listed_in_the_project_tree(tab):
    names = labels(tab)
    for want in ("S Parameter Plot 1", "Port Modes 1", "Convergence 1"):
        assert want in names, names
    # field views are listed too (the solution saved its fields)
    tab.wait_for_function("()=>RESULTS.items.some(i=>i.kind==='field')", timeout=20000)
    assert any(n.startswith("E Field") for n in labels(tab))


def test_a_plot_fills_the_window(tab):
    tab.locator("#tree .node", has_text="S Parameter Plot 1").click()
    tab.wait_for_selector(".plot-area svg", timeout=20000)
    tab.wait_for_timeout(300)
    box = tab.locator(".plot-area svg").bounding_box()
    vp = tab.locator("#docs").bounding_box()
    assert box["width"] > 0.8 * vp["width"], (box, vp)
    assert box["height"] > 0.45 * vp["height"], (box, vp)
    assert not tab.errors


def test_markers_read_values_and_difference_to_m1(tab):
    area = tab.locator(".plot-area svg")
    b = area.bounding_box()
    tab.mouse.click(b["x"] + 0.30 * b["width"], b["y"] + 0.5 * b["height"])
    tab.mouse.click(b["x"] + 0.70 * b["width"], b["y"] + 0.5 * b["height"])
    rows = tab.locator(".plot-markers tr")
    tab.wait_for_function("()=>document.querySelectorAll('.plot-markers tr').length>=3")
    assert rows.count() == 3                       # header + m1 + m2
    cells = tab.locator(".plot-markers tr").nth(2).locator("td").all_inner_texts()
    assert cells[0] == "m2"
    assert cells[4] != "—" and float(cells[4]) > 0          # delta X to m1
    tab.get_by_text("Marker ▲ Peak").click()
    assert tab.locator(".plot-markers tr").count() == 4
    tab.get_by_text("Clear markers").click()
    assert tab.locator(".plot-markers tr").count() == 0


def test_axis_range_is_user_controlled(tab):
    box = tab.locator(".plot-tools input[title=y0]")
    box.fill("-80")
    box.dispatch_event("change")
    tab.wait_for_timeout(200)
    assert float(tab.locator(".plot-tools input[title=y0]").input_value()) == -80
    texts = tab.evaluate("()=>[...document.querySelectorAll('.plot-area svg text')]"
                         ".map(t=>t.textContent)")
    assert "-80" in texts
    tab.get_by_role("button", name="Auto").click()
    assert float(tab.locator(".plot-tools input[title=y0]").input_value()) > -80
    # wheel zoom narrows the x range around the cursor
    before = float(tab.locator(".plot-tools input[title=x1]").input_value()) - \
        float(tab.locator(".plot-tools input[title=x0]").input_value())
    b = tab.locator(".plot-area svg").bounding_box()
    tab.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    tab.mouse.wheel(0, -300)
    tab.wait_for_timeout(200)
    after = float(tab.locator(".plot-tools input[title=x1]").input_value()) - \
        float(tab.locator(".plot-tools input[title=x0]").input_value())
    assert after < before


def test_a_new_report_adds_a_second_entry(tab):
    tab.evaluate("()=>openReport('sparam')")
    tab.wait_for_function("()=>RESULTS.items.filter(i=>i.kind==='sparam').length===2")
    assert "S Parameter Plot 2" in labels(tab)
    # each entry keeps its own settings
    tab.select_option(".doc-page.active #rp-form", "mag")
    tab.locator("#tree .node", has_text="S Parameter Plot 1").click()
    tab.wait_for_function("()=>{const e=document.querySelector('.doc-page.active #rp-form');"
                          "return !!e&&e.value==='db';}")


def test_opacity_of_plot_and_model_can_be_set(tab):
    tab.errors.clear()
    tab.evaluate("()=>showField(true,{quantity:'J',where:'surface'})")
    tab.wait_for_selector("#fp-pa", timeout=30000)
    assert tab.locator("#fp-ma").count() == 1            # model behind a current plot
    tab.evaluate("()=>{const r=document.querySelector('#fp-ma');"
                 "r.value='0.3';r.dispatchEvent(new Event('change'));}")
    tab.wait_for_function("()=>FIELD.modelAlpha===0.3", timeout=10000)
    tab.wait_for_function("()=>!FIELD.busy", timeout=30000)
    alphas = tab.evaluate("()=>currentBuffers.length")
    assert alphas >= 1
    assert not tab.errors


# ------------------------------------------------------------- port polarity
@pytest.fixture(scope="module")
def dipole_tab(desktop, browser):
    url, session = desktop
    from test_farfield_180 import dipole
    session.new_project("Dipole")
    d = dipole()
    session.project.designs[0] = d
    session.design = d
    session.solution = None
    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.errs = errs
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    pg.wait_for_function("()=>STATE&&STATE.design&&STATE.design.ports.length===1", timeout=20000)
    yield pg
    pg.close()


def test_port_properties_offer_reverse_and_edit_polarity(dipole_tab):
    pg = dipole_tab
    pg.evaluate("()=>showProps('port','P1')")
    pg.get_by_text("⇄ Reverse polarity").click()
    pg.wait_for_function("()=>STATE.design.ports[0].direction[2]<0", timeout=10000)
    pg.evaluate("()=>dlgPolarity('P1')")
    pg.wait_for_selector("#pgz", timeout=10000)
    num = lambda sel: float(pg.input_value(sel).rstrip("mu"))        # "1mm" -> 1.0
    assert num("#pgz") > 0 > num("#psz")              # reversed: ground is high
    pg.get_by_text("⇄ Swap ground / signal").click()
    assert num("#pgz") < 0 < num("#psz")
    pg.locator(".dialog .foot .pri").click()
    pg.wait_for_function("()=>STATE.design.ports[0].direction[2]>0", timeout=10000)
    assert not pg.errs


def test_assign_lumped_port_dialog_has_ground_signal_fields(dipole_tab):
    pg = dipole_tab
    pg.evaluate("()=>dlgExcitation('lumped')")
    pg.wait_for_selector("#pl-axis", timeout=10000)
    assert pg.locator("#plgz").count() == 1 and pg.locator("#plsz").count() == 1
    pg.select_option("#pl-axis", "custom")
    pg.fill("#plgz", "1mm")
    pg.fill("#plsz", "-1mm")
    pg.get_by_text("⇄ Swap ground / signal").click()
    assert pg.input_value("#plgz") == "-1mm" and pg.input_value("#plsz") == "1mm"
    pg.keyboard.press("Escape")
    assert not pg.errs
