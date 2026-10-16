"""Stop / Abort in the browser, and an idle viewport that does not burn CPU."""
import time

import pytest

playwright = pytest.importorskip("playwright.sync_api",
                                 reason="playwright is not installed")
from playwright.sync_api import sync_playwright          # noqa: E402

from conftest import needs_occ                            # noqa: E402

pytestmark = [needs_occ, pytest.mark.slow]


@pytest.fixture(scope="module")
def desktop():
    from aether.gui.server import serve
    srv, _, session = serve(port=8798, open_browser=False, token="",
                            block=False, template="waveguide")
    sw = session.design.setups[0].sweeps
    if sw:
        sw[0].count = 3000
        sw[0].kind = "discrete"
    yield "http://127.0.0.1:8798/", session
    session.request_abort()
    time.sleep(0.5)
    srv.shutdown()


@pytest.fixture(scope="module")
def page(desktop):
    try:
        pw = sync_playwright().start()
        b = pw.chromium.launch(args=["--enable-unsafe-swiftshader"])
    except Exception as exc:
        pytest.skip(f"chromium unavailable: {exc}")
    pg = b.new_page(viewport={"width": 1500, "height": 950})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(desktop[0])
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    yield pg
    pg.close()
    b.close()
    pw.stop()


def start(page, session):
    page.evaluate("selectBottom('progress'); "
                  "rpc('analysis.analyze', {adaptive: false}).then(() => pollJob())")
    page.wait_for_selector("#job-stop", timeout=30000)
    t_end = time.time() + 90                 # a loaded machine starts slowly
    while time.time() < t_end and session.job.partial_points < 2:
        time.sleep(0.1)
    assert session.job.running


def idle(page, session, timeout=60):
    t = time.time() + timeout
    while session.job.running and time.time() < t:
        time.sleep(0.1)
    page.wait_for_function("!STATE.job.running || true")


def test_the_progress_panel_offers_stop_and_abort_while_running(page, desktop):
    _, session = desktop
    start(page, session)
    assert page.locator("#job-abort").is_visible()
    assert page.locator("#job-ctl.on").count() == 1          # status bar too
    assert page.locator("#job-stop-sb").is_visible()
    txt = page.locator("#progress").inner_text()
    assert "Solving" in txt and "Solver" in txt and "isolated" in txt
    page.click("#job-stop")
    page.wait_for_function("document.querySelector('#progress').innerText"
                           ".includes('stopped')", timeout=60000)
    assert session.job.outcome == "stopped"
    assert page.locator("#job-ctl.on").count() == 0          # controls hide
    assert "Results kept" in page.locator("#progress").inner_text()
    assert session.solution is not None and session.solution.partial


def test_abort_from_the_status_bar(page, desktop):
    _, session = desktop
    start(page, session)
    page.click("#job-abort-sb")
    page.wait_for_function("document.querySelector('#progress').innerText"
                           ".includes('aborted')", timeout=30000)
    assert session.job.outcome == "aborted"
    assert not session.job.running


def test_shift_escape_stops_and_menu_entries_exist(page, desktop):
    _, session = desktop
    start(page, session)
    page.keyboard.press("Shift+Escape")
    page.wait_for_function("document.querySelector('#progress').innerText"
                           ".includes('stopped')", timeout=60000)
    assert session.job.outcome == "stopped"
    for label in ("Stop Analysis", "Abort Analysis"):
        assert page.evaluate(
            "l => JSON.stringify(MENUS).includes(l)", label)


def test_an_idle_viewport_renders_far_less_than_every_frame(page):
    n = page.evaluate("""() => new Promise(res => {
        const v = window.VP; let draws = 0; const d = v._draw.bind(v);
        v._draw = () => { draws++; d(); };
        v._hot = 0;
        setTimeout(() => { v._draw = d; res(draws); }, 2000);
    })""")
    assert n < 40, f"{n} draws in 2 s while idle (60 fps would be ~120)"
    # and an interaction brings back full-rate drawing
    m = page.evaluate("""() => new Promise(res => {
        const v = window.VP; let draws = 0; const d = v._draw.bind(v);
        v._draw = () => { draws++; d(); };
        v.wake();
        setTimeout(() => { v._draw = d; res(draws); }, 600);
    })""")
    assert m > 8
    assert not page.errors
