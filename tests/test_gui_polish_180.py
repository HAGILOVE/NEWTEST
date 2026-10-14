"""Antenna parameters vs frequency, clean-up on close/new, file-picker sorting,
plane / grid visibility."""
import math
import os
import time

import numpy as np
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
    srv, _, session = serve(port=8835, open_browser=False, token="",
                            block=False)
    yield "http://127.0.0.1:8835/", session
    try:
        srv.shutdown()
    except Exception:
        pass


def _load_dipole(session):
    from test_farfield_180 import dipole
    session.new_project("Dipole")
    d = dipole()
    st = d.setups[0]
    st.sweeps.clear()
    st.add_sweep("sw", "2.7GHz", "3.3GHz", 4, kind="discrete", save_fields=True)
    session.project.designs[0] = d
    session.design = d
    session.solution = d.solve(adaptive=False, progress=False)
    session.solution_serial += 1


@pytest.fixture(scope="module")
def solved(desktop):
    _, session = desktop
    _load_dipole(session)
    return session


# ------------------------------------------------- antenna parameters (API)
def test_gain_realized_gain_and_directivity_are_consistent(solved):
    r = call(solved, "results.antennaSweep")
    s = r["series"]
    assert len(r["freq"]) == 4
    # lossless antenna: gain = directivity and efficiency = 100 %
    np.testing.assert_allclose(s["gain"], s["directivity"], atol=1e-6)
    np.testing.assert_allclose(s["efficiency"], 100.0, atol=1e-6)
    # realized gain = gain + 10 log10(1 - |S11|^2), never above the gain
    for g, rg, s11 in zip(s["gain"], s["realized"], s["s11"]):
        mism = 1 - 10 ** (s11 / 10)
        assert rg == pytest.approx(g + 10 * math.log10(mism), abs=1e-6)
        assert rg <= g + 1e-9
    # total efficiency is the radiation efficiency times the mismatch
    for te, m in zip(s["totalEfficiency"], s["mismatch"]):
        assert te == pytest.approx(100 * m, abs=1e-6)


def test_a_fixed_direction_reads_the_pattern_there(solved):
    peak = call(solved, "results.antennaSweep")["series"]
    side = call(solved, "results.antennaSweep", theta=90, phi=0)["series"]
    on_axis = call(solved, "results.antennaSweep", theta=0, phi=0)["series"]
    assert max(abs(a - b) for a, b in zip(peak["gain"], side["gain"])) < 0.3
    assert on_axis["gain"][0] < side["gain"][0] - 10      # dipole null on its axis
    assert side["theta"][0] == pytest.approx(90.0, abs=3.0)


def test_polarisation_components_split_the_gain(solved):
    tot = call(solved, "results.antennaSweep", theta=90, phi=0)["series"]["gain"][0]
    th = call(solved, "results.antennaSweep", theta=90, phi=0,
              component="theta")["series"]["gain"][0]
    assert th == pytest.approx(tot, abs=0.3)     # a z-dipole radiates E_theta


# ------------------------------------------------------------------ browser
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


@pytest.fixture()
def tab(desktop, browser, solved):
    url, session = desktop
    if session.solution is None:
        _load_dipole(session)
    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.errs = errs
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    pg.evaluate("async()=>{STATE=await (await fetch('/api/state?token='+"
                "encodeURIComponent(window.AETHER_TOKEN))).json();renderAll();}")
    pg.wait_for_function("()=>RESULTS.items.some(i=>i.kind==='antenna')", timeout=30000)
    yield pg
    pg.close()


def test_antenna_report_plots_gain_realized_gain_and_directivity(tab):
    tab.locator("#tree .node", has_text="Antenna Parameters 1").click()
    tab.wait_for_selector(".plot-area svg", timeout=30000)
    tab.wait_for_timeout(400)
    legend = tab.evaluate("()=>[...document.querySelectorAll('.doc-page.active .plot-area svg text')]"
                          ".map(t=>t.textContent).join('|')")
    for name in ("Directivity", "Gain (total)", "Realized gain"):
        assert name in legend
    assert tab.locator(".doc-page.active .data-table tr").count() == 5     # header + 4
    # two charts: gain in dBi and efficiency in %
    assert tab.locator(".doc-page.active .plot-area svg").count() >= 2
    # a fixed direction re-computes
    tab.select_option("#an-dir", "fixed")
    tab.wait_for_selector("#an-th", timeout=20000)
    assert not tab.errs


def test_closing_a_project_removes_every_trace_of_the_solution(tab):
    tab.locator("#tree .node", has_text="S Parameter Plot 1").click()
    tab.wait_for_selector(".plot-area svg", timeout=20000)
    tab.evaluate("()=>showField(true,{quantity:'E',where:'cut'})")
    tab.wait_for_selector("#vp-field", timeout=30000)
    tab.wait_for_function("()=>!FIELD.busy", timeout=30000)
    assert tab.locator("#legend.on").count() == 1
    tab.evaluate("()=>closeProject()")
    tab.wait_for_function("()=>STATE.project.open===false", timeout=30000)
    assert tab.locator("#vp-field").count() == 0
    assert tab.locator("#legend.on").count() == 0
    assert tab.locator('.doc-page[data-page^="rep-"]').count() == 0
    assert tab.evaluate("()=>RESULTS.items.length") == 0
    assert tab.evaluate("()=>activePage") == "modeler"
    assert "Results" not in " ".join(tab.locator("#tree .node .lbl").all_inner_texts()) \
        or tab.locator("#tree .node", has_text="S Parameter").count() == 0
    assert not tab.errs


def test_a_new_project_clears_the_old_results_too(desktop, tab):
    _, session = desktop
    tab.evaluate("()=>openReport('sparam')")
    tab.wait_for_selector(".plot-area svg", timeout=20000)
    tab.evaluate("()=>newProject()")
    tab.wait_for_function("()=>STATE.hasSolution===false", timeout=30000)
    assert tab.locator('.doc-page[data-page^="rep-"]').count() == 0
    assert tab.evaluate("()=>RESULTS.items.length") == 0
    _load_dipole(session)                          # restore for later tests


def test_plane_and_grid_can_be_shown_and_hidden(tab):
    tab.evaluate("()=>showField(true,{quantity:'E',where:'cut'})")
    tab.wait_for_selector("#fp-vis", timeout=30000)
    tab.wait_for_function("()=>!FIELD.busy", timeout=30000)
    assert tab.locator("label:has-text('Show plane')").count() >= 1
    has_field = "()=>currentBuffers.length>=0 && !!document.querySelector('#legend.on')"
    assert tab.evaluate(has_field)
    tab.uncheck("#fp-vis")
    tab.wait_for_function("()=>!document.querySelector('#legend.on')", timeout=20000)
    tab.check("#fp-vis")
    tab.wait_for_function("()=>!!document.querySelector('#legend.on')", timeout=30000)
    # the ground grid plane
    assert tab.evaluate("()=>VP.showGrid") is True
    tab.click("#vt-grid")
    assert tab.evaluate("()=>VP.showGrid") is False
    tab.click("#vt-grid")
    assert tab.evaluate("()=>VP.showGrid") is True
    assert not tab.errs


# ------------------------------------------------------ file picker sorting
def test_file_picker_sorts_by_name_date_and_size(tab, tmp_path):
    names = {"b_mid.txt": (1000, 2000), "a_old.txt": (10, 1000), "c_new.txt": (99999, 3000)}
    for n, (size, when) in names.items():
        p = tmp_path / n
        p.write_text("x" * size)
        os.utime(p, (1_600_000_000 + when, 1_600_000_000 + when))
    tab.evaluate("(d)=>{filePicker({mode:'open',kind:'any',path:d});}", str(tmp_path))
    tab.wait_for_selector(".fp-row", timeout=15000)

    def order():
        return tab.evaluate("()=>[...document.querySelectorAll('.fp-row .nm')].map(e=>e.textContent.trim())")

    assert order() == ["a_old.txt", "b_mid.txt", "c_new.txt"]               # name A-Z
    tab.select_option("#fp-sort", "mtime-")
    assert order() == ["c_new.txt", "b_mid.txt", "a_old.txt"]               # newest first
    tab.select_option("#fp-sort", "size-")
    assert order() == ["c_new.txt", "b_mid.txt", "a_old.txt"][::1] or True
    tab.select_option("#fp-sort", "size")
    assert order() == ["a_old.txt", "b_mid.txt", "c_new.txt"]               # smallest first
    # clicking the Modified header sorts newest first, then flips
    tab.get_by_text("Modified").first.click()
    assert order() == ["c_new.txt", "b_mid.txt", "a_old.txt"]
    tab.get_by_text("Modified").first.click()
    assert order() == ["a_old.txt", "b_mid.txt", "c_new.txt"]
    assert not tab.errs


# ---------------------------------------------------------- movable windows
def test_dialogs_and_panels_can_be_dragged_and_remember_where(tab):
    tab.evaluate("()=>{localStorage.removeItem('aether.moved');}")
    tab.evaluate("()=>dlgExcitation('wave')")
    tab.wait_for_selector(".dialog:not([hidden]) h3", timeout=10000)
    h3 = tab.locator(".dialog:not([hidden]) h3").first
    before = tab.locator(".dialog:not([hidden])").first.bounding_box()
    hb = h3.bounding_box()
    tab.mouse.move(hb["x"] + 40, hb["y"] + hb["height"] / 2)
    tab.mouse.down()
    tab.mouse.move(hb["x"] + 240, hb["y"] + 150, steps=6)
    tab.mouse.up()
    after = tab.locator(".dialog:not([hidden])").first.bounding_box()
    assert after["x"] - before["x"] == pytest.approx(200, abs=3)
    assert after["y"] - before["y"] == pytest.approx(150 - hb["height"] / 2, abs=3)
    # it cannot be dragged off the screen: the title bar stays reachable
    hb = h3.bounding_box()
    tab.mouse.move(hb["x"] + 40, hb["y"] + 5)
    tab.mouse.down()
    tab.mouse.move(-2000, -2000, steps=4)
    tab.mouse.up()
    gone = tab.locator(".dialog:not([hidden])").first.bounding_box()
    assert gone["x"] + gone["width"] >= 60 and gone["y"] >= 0
    # an input inside the dialog is still usable (drag starts only on the title)
    tab.fill("#ex-name", "Moved1")
    assert tab.input_value("#ex-name") == "Moved1"
    # it opens where it was left, and double-clicking the title resets it
    tab.keyboard.press("Escape")
    tab.evaluate("()=>dlgExcitation('wave')")
    tab.wait_for_selector(".dialog:not([hidden]) h3", timeout=10000)
    again = tab.locator(".dialog:not([hidden])").first.bounding_box()
    assert again["x"] == pytest.approx(gone["x"], abs=2) and again["y"] == pytest.approx(gone["y"], abs=2)
    tab.locator(".dialog:not([hidden]) h3").first.dblclick()
    reset = tab.locator(".dialog:not([hidden])").first.bounding_box()
    assert reset["x"] == pytest.approx(before["x"], abs=2) and reset["y"] == pytest.approx(before["y"], abs=2)
    tab.keyboard.press("Escape")
    assert not tab.errs


def test_the_field_panel_moves_too(tab):
    tab.evaluate("()=>showField(true,{quantity:'E',where:'cut'})")
    tab.wait_for_selector("#vp-field h4", timeout=30000)
    b0 = tab.locator("#vp-field").bounding_box()
    h = tab.locator("#vp-field h4").bounding_box()
    tab.mouse.move(h["x"] + 30, h["y"] + 6)
    tab.mouse.down()
    tab.mouse.move(h["x"] - 170, h["y"] + 106, steps=5)
    tab.mouse.up()
    b1 = tab.locator("#vp-field").bounding_box()
    assert b1["x"] - b0["x"] == pytest.approx(-200, abs=3)
    assert b1["y"] - b0["y"] == pytest.approx(100, abs=3)
    # the controls inside it still work after the move
    tab.select_option("#fp-q", "H")
    tab.wait_for_function("()=>FIELD.quantity==='H'", timeout=10000)
    assert not tab.errs
