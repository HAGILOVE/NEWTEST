"""Fields and surface current on metals the user chooses."""
import numpy as np
import pytest

from conftest import needs_occ

pytestmark = [needs_occ, pytest.mark.slow]

playwright = pytest.importorskip("playwright.sync_api",
                                 reason="playwright is not installed")
from playwright.sync_api import sync_playwright          # noqa: E402

LAUNCH_ARGS = ["--enable-unsafe-swiftshader"]


def call(s, method, **params):
    from aether.gui.api import dispatch
    return dispatch(s, method, params)


@pytest.fixture(scope="module")
def desktop():
    from aether.gui.server import serve
    srv, _, session = serve(port=8837, open_browser=False, token="",
                            block=False)
    from test_farfield_180 import dipole
    session.new_project("Dipole")
    d = dipole()
    session.project.designs[0] = d
    session.design = d
    session.solution = d.solve(adaptive=False, progress=False, save_fields=True)
    session.solution_serial += 1
    yield "http://127.0.0.1:8837/", session
    try:
        srv.shutdown()
    except Exception:
        pass


def _bbox(buf):
    p = np.asarray(buf["position"], float).reshape(-1, 3)
    return p.min(axis=0), p.max(axis=0)


# --------------------------------------------------------------------- API
def test_current_on_one_arm_stays_on_that_arm(desktop):
    _, s = desktop
    top = call(s, "view.field", quantity="J", where="objects", objects=["arm_top"])
    lo, hi = _bbox(top)
    assert lo[2] > -1e-9                    # nothing on the lower arm (z < 0)
    assert top["on"] == ["arm_top"]
    bot = call(s, "view.field", quantity="J", where="objects", objects=["arm_bot"])
    assert _bbox(bot)[1][2] < 1e-9
    both = call(s, "view.field", quantity="J", where="objects",
                objects=["arm_top", "arm_bot"])
    assert both["count"] >= top["count"] + bot["count"] - 6
    allj = call(s, "view.field", quantity="J", where="surface")
    assert allj["count"] >= both["count"]


def test_fields_can_be_restricted_to_a_metal_too(desktop):
    _, s = desktop
    for q in ("E", "H"):
        r = call(s, "view.field", quantity=q, where="objects", objects=["arm_top"])
        lo, hi = _bbox(r)
        assert r["count"] > 0 and lo[2] > -1e-9 and r["on"] == ["arm_top"]


def test_a_sheet_can_be_chosen_as_a_metal(desktop):
    _, s = desktop
    r = call(s, "view.field", quantity="E", where="objects", objects=["feed"])
    assert r["count"] > 0


def test_a_missing_name_or_an_empty_choice_is_reported(desktop):
    _, s = desktop
    with pytest.raises(Exception):
        call(s, "view.field", quantity="J", where="objects", objects=["nope"])
    with pytest.raises(Exception, match="choose"):
        call(s, "view.field", quantity="J", where="objects", objects=[])


def test_the_design_tells_the_ui_which_objects_are_metals(desktop):
    _, s = desktop
    names = {o["name"]: o["isMetal"] for o in call(s, "view.fieldInfo") and
             __import__("aether.gui.api", fromlist=["_design_json"])._design_json(s)["objects"]}
    assert names["arm_top"] and names["arm_bot"] and not names["air"]


# ----------------------------------------------------------------- browser
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
def tab(desktop, browser):
    url, session = desktop
    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.errs = errs
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    pg.evaluate("async()=>{STATE=await (await fetch('/api/state?token='+"
                "encodeURIComponent(window.AETHER_TOKEN))).json();renderAll();}")
    pg.wait_for_function("()=>STATE.hasSolution===true", timeout=20000)
    yield pg
    pg.close()


def test_the_panel_lists_metals_and_plots_only_the_ticked_ones(tab):
    tab.evaluate("()=>showField(true,{quantity:'J',where:'surface'})")
    tab.wait_for_selector("#fp-w", timeout=30000)
    tab.wait_for_function("()=>!FIELD.busy", timeout=30000)
    tab.select_option("#fp-w", "objects")
    tab.wait_for_selector("#fp-metals", timeout=10000)
    names = tab.locator("#fp-metals .nm").all_inner_texts()
    assert "arm_top" in names and "arm_bot" in names and "air" not in names
    tab.wait_for_function("()=>!FIELD.busy", timeout=30000)
    # untick the lower arm: the plot is redrawn with the upper one only
    tab.locator("#fp-metals label", has_text="arm_bot").locator("input").uncheck()
    tab.wait_for_function("()=>JSON.stringify(FIELD.objects).includes('arm_top')&&"
                          "!JSON.stringify(FIELD.objects).includes('arm_bot')", timeout=10000)
    tab.wait_for_function("()=>!FIELD.busy&&document.querySelector('#fp-note').textContent.includes('on arm_top')",
                          timeout=30000)
    # the model stays visible, faint, behind the plot
    assert tab.evaluate("()=>currentBuffers.length>=1") is True
    assert tab.evaluate("()=>FIELD.modelAlpha<=0.35")
    assert not tab.errs


def test_clicking_a_metal_in_the_tree_shows_its_current(tab):
    tab.evaluate("()=>showField(true,{quantity:'J',where:'objects'})")
    tab.wait_for_selector("#fp-metals", timeout=30000)
    tab.wait_for_function("()=>!FIELD.busy", timeout=30000)
    tab.evaluate("()=>setSelection(['arm_bot'])")
    tab.wait_for_function("()=>JSON.stringify(FIELD.objects)==='[\"arm_bot\"]'", timeout=10000)
    tab.wait_for_function("()=>!FIELD.busy&&document.querySelector('#fp-note').textContent.includes('on arm_bot')",
                          timeout=30000)
    assert tab.locator("#fp-metals label", has_text="arm_top").locator("input").is_checked() is False
    # a non-metal selection leaves the plot alone
    tab.evaluate("()=>setSelection(['air'])")
    tab.wait_for_timeout(500)
    assert tab.evaluate("()=>JSON.stringify(FIELD.objects)") == '["arm_bot"]'
    assert not tab.errs
