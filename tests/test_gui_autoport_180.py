"""Signal / ground marks and the automatic port, driven from the GUI."""
import pytest

playwright = pytest.importorskip("playwright.sync_api",
                                 reason="playwright is not installed")
from playwright.sync_api import sync_playwright          # noqa: E402

from conftest import needs_occ                            # noqa: E402
from test_autoport_180 import microstrip                  # noqa: E402

pytestmark = [needs_occ, pytest.mark.slow]

LAUNCH_ARGS = ["--enable-unsafe-swiftshader"]


@pytest.fixture(scope="module")
def desktop():
    from aether.gui.server import serve
    srv, _, session = serve(port=8837, open_browser=False, token="",
                            block=False)
    yield "http://127.0.0.1:8837/", session
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


@pytest.fixture()
def tab(desktop, browser):
    url, session = desktop
    session.new_project("MS")
    session.project.designs[0] = microstrip()
    session.design = session.project.designs[0]
    session.port_marks = None
    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.errs = errs
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    pg.evaluate("async()=>{STATE=await (await fetch('/api/state?token='+"
                "encodeURIComponent(window.AETHER_TOKEN))).json();renderAll();}")
    yield pg, session
    pg.close()


def menu_labels(pg):
    return pg.evaluate("()=>[...document.querySelectorAll('.ctx button')]"
                       ".map(b=>b.textContent+(b.disabled?' [off]':''))")


def right_click_object(pg, name):
    pg.locator("#tree .node", has_text=name).first.click(button="right")
    pg.wait_for_selector(".ctx")


def choose(pg, label):
    pg.locator(".ctx button", has_text=label).first.click()
    pg.wait_for_timeout(500)


def test_the_menu_offers_the_marks_and_the_automatic_ports(tab):
    pg, _ = tab
    right_click_object(pg, "strip")
    labels = menu_labels(pg)
    assert any(l.startswith("Mark as Signal") for l in labels)
    assert any(l.startswith("Mark as Ground") for l in labels)
    # nothing marked yet: the automatic ports are greyed out
    assert all("[off]" in l for l in labels if "(auto" in l)
    assert not pg.errs


def test_mark_signal_and_ground_then_assign_a_lumped_port(tab):
    pg, session = tab
    right_click_object(pg, "strip")
    choose(pg, "Mark as Signal")
    right_click_object(pg, "gnd")
    choose(pg, "Mark as Ground")
    assert pg.evaluate("()=>PORT_MARK_COUNT") == {"signal": 1, "ground": 1}
    # the marks are drawn / listed so the user can see what is set
    pg.wait_for_function("()=>ASSIGN_ITEMS.some(i=>i.kind==='mark')", timeout=10000)
    right_click_object(pg, "air")
    labels = menu_labels(pg)
    assert not any("[off]" in l for l in labels if "(auto" in l)
    choose(pg, "Assign Lumped Port")
    pg.wait_for_function("()=>STATE.design && JSON.stringify(STATE.design).includes('lumped')",
                         timeout=10000)
    d = session.design
    assert len(d.ports) == 1 and d.ports[0].kind == "lumped"
    assert not pg.errs


def test_assign_a_wave_port_with_the_same_marks(tab):
    pg, session = tab
    pg.evaluate("async()=>{await rpc('portmarks.set',{role:'signal',picks:[{kind:'object',name:'strip'}]});"
                "await rpc('portmarks.set',{role:'ground',picks:[{kind:'object',name:'gnd'}]});"
                "await refreshAssignments();}")
    right_click_object(pg, "air")
    choose(pg, "Assign Wave Port  (auto)")
    pg.wait_for_timeout(500)
    ports = session.design.ports
    assert len(ports) == 1 and ports[0].kind == "wave"
    assert not pg.errs


def test_a_missing_ground_is_explained(tab):
    pg, session = tab
    right_click_object(pg, "strip")
    choose(pg, "Mark as Signal")
    assert pg.evaluate("()=>PORT_MARK_COUNT") == {"signal": 1, "ground": 0}
    right_click_object(pg, "air")
    assert all("[off]" in l for l in menu_labels(pg) if "(auto" in l)
    pg.keyboard.press("Escape")
    # and Clear removes the mark again
    right_click_object(pg, "air")
    choose(pg, "Clear Signal")
    assert pg.evaluate("()=>PORT_MARK_COUNT") == {"signal": 0, "ground": 0}


def test_two_selected_objects_give_a_port_in_one_step(tab):
    pg, session = tab
    pg.evaluate("async()=>{await rpc('modeler.select',{names:['strip','gnd']});}")
    pg.wait_for_timeout(300)
    pg.locator("#tree .node", has_text="strip").first.click(button="right")
    pg.wait_for_selector(".ctx")
    labels = menu_labels(pg)
    assert any(l.startswith("Lumped Port between the two") for l in labels), labels
    choose(pg, "Lumped Port between the two")
    pg.wait_for_timeout(500)
    assert len(session.design.ports) == 1 and session.design.ports[0].kind == "lumped"
