"""
Browser tests for the 1.7.5 document lifecycle and progress display.

These run against a server of their own rather than the shared one in
``test_gui_browser``: closing a project and exiting are exactly the actions
that would pull the floor out from under every other test in that module.

Skipped unless Playwright and a Chromium build are available.
"""
import time

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
    srv, _, session = serve(port=8797, open_browser=False, token="",
                            block=False, template="waveguide")
    yield "http://127.0.0.1:8797/", session, srv
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


@pytest.fixture
def page(desktop, browser):
    url, session, _ = desktop
    pg = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text[:200])
          if m.type == "error" else None)
    pg.errors = errors
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    pg.wait_for_timeout(400)
    yield pg
    pg.close()
    # leave the session with a document for whatever runs next
    session.new_project("Project1")


def menu_item(pg, menu, label):
    pg.evaluate("()=>closeMenus()")
    pg.click(f"#menubar .menu button:text-is('{menu}')")
    pg.wait_for_timeout(120)
    pg.click(f"#menubar .menu.open .menu-pop button:has-text('{label}')")
    pg.wait_for_timeout(250)


def dialog_text(pg):
    return pg.locator("#modal-back > .dialog:not([hidden])").inner_text()


def click_dialog(pg, label):
    # double quotes: one of the labels is "Don't Save"
    pg.click("#modal-back > .dialog:not([hidden]) "
             f'.foot button:text-is("{label}")')
    pg.wait_for_timeout(250)


# ------------------------------------------------------- the save prompt
def test_a_clean_project_closes_without_asking(page):
    page.evaluate("()=>rpc('project.new',{})")
    page.wait_for_function("()=>STATE.project.dirty===false", timeout=20000)
    menu_item(page, "File", "Close Project")
    page.wait_for_function("()=>STATE.project.open===false", timeout=20000)
    assert page.locator("#modal-back.on").count() == 0
    assert "No project" in page.locator("#tree").inner_text()
    assert "No project open" in page.locator("#title-doc").inner_text()


def test_closing_a_project_asks_first(page):
    page.evaluate("()=>rpc('project.new',{}).then(()=>rpc('modeler.draw',"
                  "{shape:'box',name:'Box1',params:{position:['0mm','0mm',"
                  "'0mm'],size:['4mm','4mm','1mm']}}))")
    page.wait_for_function("()=>STATE.project.dirty===true", timeout=20000)
    menu_item(page, "File", "Close Project")
    text = dialog_text(page)
    assert "Save changes" in text
    # all three answers are offered — the old prompt had only two
    for label in ("Cancel", "Don't Save", "Save"):
        assert page.locator("#modal-back > .dialog:not([hidden]) "
                            f".foot button:text-is(\"{label}\")").count() == 1


def test_cancel_leaves_the_project_exactly_as_it_was(page):
    page.evaluate("()=>rpc('project.new',{}).then(()=>rpc('modeler.draw',"
                  "{shape:'box',name:'Box1',params:{position:['0mm','0mm',"
                  "'0mm'],size:['4mm','4mm','1mm']}}))")
    page.wait_for_function("()=>STATE.project.dirty===true", timeout=20000)
    menu_item(page, "File", "Close Project")
    click_dialog(page, "Cancel")
    assert page.evaluate("()=>STATE.project.open") is True
    assert page.evaluate("()=>STATE.design.objects.length") == 1


def test_dont_save_discards_and_closes(page):
    page.evaluate("()=>rpc('project.new',{}).then(()=>rpc('modeler.draw',"
                  "{shape:'box',name:'Box1',params:{position:['0mm','0mm',"
                  "'0mm'],size:['4mm','4mm','1mm']}}))")
    page.wait_for_function("()=>STATE.project.dirty===true", timeout=20000)
    menu_item(page, "File", "Close Project")
    click_dialog(page, "Don't Save")
    page.wait_for_function("()=>STATE.project.open===false", timeout=20000)


def test_save_writes_the_file_and_then_closes(page, tmp_path):
    target = str(tmp_path / "kept.warp")
    page.evaluate("()=>rpc('project.new',{}).then(()=>rpc('modeler.draw',"
                  "{shape:'box',name:'Box1',params:{position:['0mm','0mm',"
                  "'0mm'],size:['4mm','4mm','1mm']}}))")
    page.wait_for_function("()=>STATE.project.dirty===true", timeout=20000)
    # give it a file first, so Save does not have to open the browser
    page.evaluate("p=>rpc('project.save',{path:p})", target)
    page.wait_for_function("()=>STATE.project.dirty===false", timeout=20000)
    page.evaluate("()=>rpc('modeler.draw',{shape:'box',name:'Box2',"
                  "params:{position:['9mm','0mm','0mm'],"
                  "size:['4mm','4mm','1mm']}})")
    page.wait_for_function("()=>STATE.project.dirty===true", timeout=20000)

    menu_item(page, "File", "Close Project")
    click_dialog(page, "Save")
    page.wait_for_function("()=>STATE.project.open===false", timeout=30000)
    from aether.io.warp.translate import read_project
    proj, _ = read_project(target)
    assert {s.name for s in proj[0].solids} == {"Box1", "Box2"}


def test_a_new_project_reopens_the_workspace(page):
    menu_item(page, "File", "Close Project")
    if page.locator("#modal-back.on").count():
        click_dialog(page, "Don't Save")
    page.wait_for_function("()=>STATE.project.open===false", timeout=20000)
    menu_item(page, "File", "New Project")
    page.wait_for_function("()=>STATE.project.open===true", timeout=20000)
    assert page.evaluate("()=>STATE.design.name") == "WarpsDesign1"


def test_exit_asks_before_it_quits(page):
    """Cancel here, because the alternative ends the server this page uses."""
    page.evaluate("()=>rpc('project.new',{})")
    page.wait_for_function("()=>STATE.project.dirty===false", timeout=20000)
    menu_item(page, "File", "Exit")
    assert "Exit" in dialog_text(page)
    click_dialog(page, "Cancel")
    assert page.evaluate("()=>window.__aetherReady") is True


# ------------------------------------------------------------- progress
def test_the_message_channel_carries_the_task(page):
    """The stage is published on the poll endpoint, not on the command's own
    response — that is what lets it update while the command is still
    holding the session lock."""
    task = page.evaluate("""async ()=>{
      const r = await fetch('/api/messages?since=0&token='
        + encodeURIComponent(window.AETHER_TOKEN));
      return (await r.json()).task;
    }""")
    assert task is not None
    assert set(task) >= {"active", "label", "stage", "done", "total",
                         "fraction", "elapsed", "seq"}


def test_the_overlay_names_the_stage_and_then_goes_away(page):
    page.evaluate("""()=>renderTask({active:true, label:'Opening solum.warp',
      stage:'reading design 2 of 5', detail:'Antenna', done:2, total:5,
      fraction:0.4, elapsed:3.5, error:'', seq:1})""")
    page.wait_for_selector("#busy-overlay.on", timeout=10000)
    text = page.locator("#busy-overlay").inner_text()
    assert "Opening solum.warp" in text
    assert "reading design 2 of 5" in text and "2 / 5" in text
    assert "Antenna" in text
    assert page.evaluate(
        "()=>document.querySelector('#busy-overlay .pbar .fill').style.width"
    ) == "40%"
    page.evaluate("""()=>renderTask({active:false, label:'', stage:'',
      detail:'', done:0, total:0, fraction:1, elapsed:4, error:'', seq:2})""")
    page.wait_for_function(
        "()=>!document.querySelector('#busy-overlay.on')", timeout=10000)


def test_a_stage_with_no_total_does_not_invent_a_percentage(page):
    page.evaluate("""()=>renderTask({active:true, label:'Importing part.step',
      stage:'reading the CAD file', detail:'', done:0, total:0, fraction:0,
      elapsed:1, error:'', seq:3})""")
    page.wait_for_selector("#busy-overlay.on", timeout=10000)
    assert page.evaluate("()=>document.querySelector("
                         "'#busy-overlay .pbar .fill')"
                         ".classList.contains('indeterminate')") is True
    page.evaluate("""()=>renderTask({active:false, label:'', stage:'',
      detail:'', done:0, total:0, fraction:1, elapsed:1, error:'', seq:4})""")
    page.wait_for_function(
        "()=>!document.querySelector('#busy-overlay.on')", timeout=10000)


def test_the_overlay_goes_away_when_the_work_does(page):
    page.evaluate("()=>refreshGeometry(true)")
    page.wait_for_function(
        "()=>!document.querySelector('#busy-overlay.on')", timeout=60000)


# ---------------------------------------------------- incremental redraw
def test_only_the_changed_body_is_rebuilt(page):
    pg = page
    pg.evaluate("""()=>rpc('project.new',{}).then(()=>Promise.all([
        rpc('modeler.draw',{shape:'box',name:'A',params:{
            position:['0mm','0mm','0mm'],size:['6mm','4mm','1mm']}}),
      ])).then(()=>rpc('modeler.draw',{shape:'box',name:'B',params:{
            position:['20mm','0mm','0mm'],size:['6mm','4mm','1mm']}}))""")
    pg.wait_for_function("()=>STATE.design.objects.length===2", timeout=30000)
    pg.evaluate("()=>refreshGeometry(true)")
    pg.wait_for_function("()=>VP.objects.length===2", timeout=30000)
    before = pg.evaluate("()=>VP.objects.map(o=>o.digest)")
    assert all(before)

    # the object identity of an untouched body must survive the redraw
    pg.evaluate("()=>{VP.objects.forEach((o,i)=>o.__tag=i);}")
    pg.evaluate("()=>rpc('modeler.transform',{names:['A'],op:'move',"
                "params:{dx:'2mm',dy:'0mm',dz:'0mm'}})"
                ".then(()=>refreshGeometry(false))")
    pg.wait_for_function(
        "()=>VP.objects.length===2 && VP.objects.some(o=>o.__tag===undefined)",
        timeout=30000)
    tags = pg.evaluate("()=>VP.objects.map(o=>({n:o.name,t:o.__tag}))")
    moved = [x for x in tags if x["n"] == "A"][0]
    kept = [x for x in tags if x["n"] == "B"][0]
    assert moved["t"] is None, "the body that moved should have been rebuilt"
    assert kept["t"] is not None, "the body that did not move was rebuilt"


def test_vertex_data_arrives_as_binary(page):
    page.evaluate("()=>rpc('project.new',{}).then(()=>rpc('modeler.draw',"
                  "{shape:'sphere',name:'S',params:{center:['0mm','0mm',"
                  "'0mm'],radius:'5mm'}}))")
    page.wait_for_function("()=>STATE.design.objects.length===1", timeout=30000)
    got = page.evaluate("""async ()=>{
      const g = await rpc('view.geometry',{binary:true});
      return !!(g.objects[0].blobs && g.objects[0].blobs.position);
    }""")
    assert got
    page.evaluate("()=>refreshGeometry(true)")
    page.wait_for_function("()=>VP.objects.length===1", timeout=30000)
    assert page.evaluate("()=>VP.objects[0].cpu.length") > 0


def test_a_model_with_many_bodies_all_reach_the_viewport(page):
    """The binary + digest path has to deliver every body, not most of them:
    a project that opens and then shows nothing is the worst failure this
    code can have."""
    page.evaluate("""async ()=>{
      await rpc('project.new',{});
      for (let i=0;i<24;i++)
        await rpc('modeler.draw',{shape:'box',name:'B'+i,params:{
          position:[(i*12)+'mm','0mm','0mm'], size:['8mm','5mm','2mm']}});
    }""")
    page.wait_for_function("()=>STATE.design.objects.length===24", timeout=90000)
    page.evaluate("()=>refreshGeometry(true)")
    page.wait_for_function("()=>VP.objects.length===24", timeout=90000)
    empty = page.evaluate(
        "()=>VP.objects.filter(o=>!o.cpu || o.cpu.length===0).map(o=>o.name)")
    assert empty == [], empty
    assert page.evaluate("()=>VP.objects.every(o=>o.digest)")
    # and a redraw keeps them all
    page.evaluate("()=>refreshGeometry(false)")
    page.wait_for_timeout(500)
    assert page.evaluate("()=>VP.objects.length") == 24
    assert page.evaluate(
        "()=>VP.objects.filter(o=>!o.cpu || o.cpu.length===0).length") == 0


def test_a_failure_after_the_read_still_leaves_the_model_on_screen(page,
                                                                   tmp_path):
    """
    The read is the only step allowed to abort an open.

    A real project brought in a material whose name the library could not look
    up again; the call that lists materials sits between "loaded" and "draw
    it", and its exception left the workspace holding a complete model and
    showing an empty viewport. Nothing after the read may cost the model.
    """
    target = str(tmp_path / "resilient.warp")
    page.evaluate("""async (p)=>{
      await rpc('project.new',{});
      await rpc('modeler.draw',{shape:'box',name:'Body',params:{
        position:['0mm','0mm','0mm'], size:['9mm','4mm','2mm']}});
      await rpc('project.save',{path:p});
    }""", target)
    page.wait_for_function("()=>STATE.project.dirty===false", timeout=30000)

    page.evaluate("""()=>{ window.__realLoad = window.loadMaterials;
      window.loadMaterials = async () => {
        throw new Error('material lookup blew up'); }; }""")
    try:
        page.evaluate("p=>openProjectFile(p)", target)
        page.wait_for_function("()=>VP.objects.length===1", timeout=120000)
        assert page.evaluate("()=>VP.objects[0].cpu.length") > 0
    finally:
        page.evaluate("()=>{ window.loadMaterials = window.__realLoad; }")


def test_no_javascript_errors_in_any_of_it(page):
    page.wait_for_timeout(300)
    assert not page.errors, page.errors
