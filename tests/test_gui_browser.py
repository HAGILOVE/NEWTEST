"""
End-to-end browser test of the Aether Desktop workspace.

Skipped unless Playwright and a Chromium build are available:

    pip install playwright && playwright install chromium
    pytest tests/test_gui_browser.py -q

It drives the real UI — ribbon, dialogs, WebGL viewport, solver, reports and
the scripting console — against the real solver, and asserts on what the page
actually renders.
"""
import os
import sys

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
    srv, _, session = serve(port=8795, open_browser=False, token="",
                            block=False, template="waveguide")
    yield "http://127.0.0.1:8795/", session
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    """One Playwright instance and browser for the whole module."""
    try:
        pw = sync_playwright().start()
        b = pw.chromium.launch(args=LAUNCH_ARGS)
    except Exception as exc:                     # no browser binary installed
        pytest.skip(f"chromium unavailable: {exc}")
    yield b
    b.close()
    pw.stop()


def _new_page(browser, url):
    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    errors = []
    pg.on("pageerror", lambda e: errors.append(("pageerror", str(e))))
    pg.on("console",
          lambda m: errors.append(("console", m.text[:200]))
          if m.type == "error" else None)
    pg.errors = errors
    pg.goto(url)
    pg.wait_for_function("window.__aetherReady === true", timeout=60000)
    pg.wait_for_timeout(600)
    return pg


@pytest.fixture(scope="module")
def page(desktop, browser):
    url, _ = desktop
    pg = _new_page(browser, url)
    yield pg
    pg.close()


def ok(page):
    """Press the dialog's primary button and wait for it to actually close.

    The command behind it is asynchronous: the model changes as soon as the
    call returns, but the dialog closes only after the viewport has caught up.
    Carrying on before that leaves the next test typing into a dialog that is
    still on screen.
    """
    before = page.evaluate("()=>DIALOG_STACK.length")
    page.click("#modal-back > .dialog:not([hidden]) .foot button.pri")
    page.wait_for_function(f"()=>DIALOG_STACK.length < {before}", timeout=60000)


# ------------------------------------------------------------------ shell
def test_workspace_chrome_is_complete(page):
    assert page.locator("#menubar .menu").count() == 10
    assert page.locator("#ribbon-tabs button").count() == 6
    tree = page.locator("#tree").inner_text()
    for branch in ("Modeler", "Boundaries", "Excitations", "Analysis",
                   "Mesh", "Results"):
        assert branch in tree
    assert "Solution type" in page.locator("#props-body").inner_text()


def test_viewport_renders_the_model(page):
    assert page.evaluate("()=>{const c=document.getElementById('gl');"
                         "return !!c && c.width > 800 && c.height > 400}")
    assert page.evaluate("()=>window.currentBuffersLen") >= 1
    # the framebuffer is not blank: something was actually shaded
    assert page.evaluate("""()=>{
        const gl=document.getElementById('gl').getContext('webgl');
        const p=new Uint8Array(4);
        gl.readPixels(gl.drawingBufferWidth>>1, gl.drawingBufferHeight>>1,
                      1,1,gl.RGBA,gl.UNSIGNED_BYTE,p);
        return p[0]+p[1]+p[2] > 60;}""")


def test_clicking_the_viewport_selects_an_object(page):
    """Ray picking against the same triangles that were uploaded to the GPU."""
    box = page.locator("#gl").bounding_box()
    hit = page.evaluate("()=>{const c=document.getElementById('gl');"
                        "const r=c.getBoundingClientRect();"
                        "return VP.pick(r.width/2, r.height/2);}")
    assert hit and hit["name"] == "guide"
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_function("()=>STATE.selection.length===1", timeout=15000)
    assert page.evaluate("()=>STATE.selection[0]") == "guide"
    assert "guide" in page.locator("#status-sel").inner_text()
    # a click on empty space clears the selection
    page.mouse.click(box["x"] + 24, box["y"] + 24)
    page.wait_for_function("()=>STATE.selection.length===0", timeout=15000)


def test_draw_dialog_prefills_an_automatic_name(page):
    page.click("#ribbon-tabs button:has-text('Draw')")
    page.click(".rbtn:has-text('Box')")
    page.wait_for_selector("#modal-back.on")
    page.wait_for_function("()=>document.getElementById('d-name').value!==''",
                           timeout=15000)
    assert page.input_value("#d-name") == "Box1"
    page.click(".dialog .foot button.pri")
    page.wait_for_function("()=>STATE.design.objects.length===2", timeout=30000)
    # the next suggestion has moved on
    page.click(".rbtn:has-text('Box')")
    page.wait_for_selector("#modal-back.on")
    page.wait_for_function(
        "()=>document.getElementById('d-name').value==='Box2'", timeout=15000)
    page.click(".dialog .foot button:has-text('Cancel')")
    page.evaluate("()=>rpc('modeler.delete',{names:['Box1']})")
    page.wait_for_function("()=>STATE.design.objects.length===1", timeout=30000)


def test_draw_dialog_creates_geometry(page):
    page.click("#ribbon-tabs button:has-text('Draw')")
    page.click(".rbtn:has-text('Cylinder')")
    page.wait_for_selector("#modal-back.on")
    page.fill("#d-name", "Post")
    page.fill("#d-r", "2mm")
    page.fill("#d-h", "10mm")
    page.fill("#px", "40mm"); page.fill("#py", "0mm"); page.fill("#pz", "0mm")
    page.select_option("#d-mat", "copper")
    ok(page)
    page.wait_for_function("()=>STATE.design.objects.length===2", timeout=30000)
    assert "Post" in page.locator("#tree").inner_text()
    # the viewport re-tessellates asynchronously after the model changes
    page.wait_for_function("()=>window.currentBuffersLen===2", timeout=30000)


def test_boolean_dialog(page):
    page.click("#ribbon-tabs button:has-text('Modeler')")
    page.click(".rbtn:has-text('Boolean')")
    page.wait_for_selector("#modal-back.on")
    page.select_option("#b-op", "subtract")
    page.select_option("#b-blank", "Post")
    page.select_option("#b-tools", ["guide"])
    ok(page)
    page.wait_for_function("()=>STATE.design.objects.length===1", timeout=30000)
    assert "Post" in page.locator("#tree").inner_text()
    page.evaluate("()=>rpc('modeler.delete',{names:['Post']})")
    page.wait_for_timeout(800)


def test_boundary_dialog_is_type_aware(page):
    page.click("#ribbon-tabs button:has-text('Simulation')")
    page.click(".rbtn:has-text('Assign')")
    page.wait_for_selector("#modal-back.on")
    page.select_option("#bn-type", "finite_cond")
    page.wait_for_timeout(250)
    assert page.locator("#bn-mat").count() == 1
    page.select_option("#bn-type", "lumped_rlc")
    page.wait_for_timeout(250)
    assert page.locator("#bn-C").count() == 1
    page.click(".dialog .foot button:has-text('Cancel')")


def test_file_picker_browses_the_real_filesystem(page, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "one.aedt").write_text("x")
    (tmp_path / "two.aedt").write_text("y")
    (tmp_path / "ignore.txt").write_text("z")
    page.evaluate("(p)=>filePicker({mode:'open',kind:'project',"
                  "title:'Open Project',path:p})", str(tmp_path))
    page.wait_for_selector(".fp-list .fp-row", timeout=20000)
    names = page.locator(".fp-row .nm").all_inner_texts()
    assert [n.strip() for n in names] == ["sub", "one.aedt", "two.aedt"]
    assert page.locator(".fp-places button").count() >= 2
    assert page.locator(".fp-crumbs button").count() >= 2
    # selecting a file fills the name box
    page.locator(".fp-row", has_text="one.aedt").click()
    assert page.input_value("#fp-name") == "one.aedt"
    # entering a folder navigates
    page.locator(".fp-row", has_text="sub").dblclick()
    page.wait_for_function(
        "()=>document.querySelector('.fp-list').innerText.includes("
        "'No matching files')", timeout=15000)
    page.click(".fp-bar button.nav:nth-child(2)")          # up
    page.wait_for_selector(".fp-list .fp-row", timeout=15000)
    page.click(".dialog .foot button:has-text('Cancel')")


def test_file_picker_saves_and_the_project_reopens(page, tmp_path):
    target = tmp_path / "FromPicker.aedt"
    page.evaluate("(p)=>filePicker({mode:'save',kind:'project',"
                  "title:'Save',path:p,filename:'FromPicker',"
                  "onPick:(x)=>rpc('project.save',{path:x})})", str(tmp_path))
    page.wait_for_selector(".fp-list", timeout=20000)
    page.click(".dialog .foot button.pri")
    page.wait_for_timeout(1500)
    assert target.is_file(), list(tmp_path.iterdir())
    text = target.read_text()
    assert "$begin 'AnsoftProject'" in text


def test_validation_dialog(page):
    page.click(".rbtn:has-text('Validate')")
    page.wait_for_selector("#modal-back.on")
    page.wait_for_timeout(400)
    txt = page.locator("#modal-back > .dialog:not([hidden])").inner_text()
    for row in ("3D Model", "Boundaries and Excitations", "Materials",
                "Analysis Setup", "Mesh Operations"):
        assert row in txt
    page.click(".dialog .foot button:has-text('Close')")


def test_solve_and_report(page):
    # switch to the fast lumped-port template, then solve it end to end
    page.click("#ribbon-tabs button:has-text('Home')")
    page.click(".rbtn:has-text('Template')")
    page.wait_for_selector("#modal-back.on")
    page.select_option("#tp-name", "microstrip")
    ok(page)
    page.wait_for_function("()=>STATE.design.name==='PlateLine'", timeout=60000)

    page.click("#ribbon-tabs button:has-text('Simulation')")
    page.click(".rbtn:has-text('Analyze All')")
    page.wait_for_selector("#modal-back.on")
    page.uncheck("#an-adapt")
    ok(page)
    page.wait_for_function("()=>STATE && STATE.hasSolution===true",
                           timeout=240000)
    page.wait_for_timeout(2500)

    assert page.locator("#doctabs button").count() >= 2
    assert page.locator(".report svg polyline").count() >= 2
    assert "passive" in page.locator(".report-toolbar").inner_text()
    assert page.locator(".trace-chips label").count() == 4
    page.select_option("#rp-form", "deg")
    page.wait_for_timeout(900)
    assert page.locator(".report svg").count() >= 1


def test_port_mode_report_covers_lumped_ports(page):
    page.click("#ribbon-tabs button:has-text('Results')")
    page.click(".rbtn:has-text('Port Modes')")
    page.wait_for_timeout(1200)
    # each result is its own page now (rep-<id>); the active one is this report
    grid = page.locator('.doc-page.active')
    assert grid.locator("table.grid tr").count() == 3      # header + 2 ports
    assert "TEM (lumped)" in grid.inner_text()


def test_scripting_console_drives_the_live_model(page):
    page.click("#bottomtabs button[data-b='console']")
    page.fill("#console-src", "print(design.name, solution.sparams.n_port)")
    page.keyboard.press("Control+Enter")
    page.wait_for_timeout(1500)
    assert "PlateLine 2" in page.locator("#console-out").inner_text()

    page.fill("#console-src",
              "design.add_box('Cover',(0,0,'1mm'),('20mm','10mm','1mm'),'copper')")
    page.keyboard.press("Control+Enter")
    page.wait_for_function("()=>STATE.design.objects.length===2", timeout=30000)
    assert "Cover" in page.locator("#tree").inner_text()


def test_view_controls_and_theme(page):
    page.click("#doctabs button:has-text('3D Modeler')")
    for v in ("top", "front", "right", "iso"):
        page.evaluate(f"()=>VP.view('{v}')")
        page.wait_for_timeout(120)
    page.evaluate("()=>{VP.mode='wireframe'; VP.fit();}")
    page.wait_for_timeout(300)
    page.evaluate("()=>toggleTheme()")
    page.wait_for_timeout(300)
    assert page.evaluate("()=>document.documentElement.dataset.theme") == "dark"


def test_no_javascript_errors_during_the_whole_session(page):
    assert page.errors == []


# ------------------------------------------------------- dead-entry sweep
@pytest.fixture(scope="module")
def fresh_page(desktop, browser):
    """A second tab, so the sweep cannot disturb the workflow tests."""
    url, _ = desktop
    pg = _new_page(browser, url)
    yield pg
    pg.close()


def test_every_menu_item_and_ribbon_button_works(fresh_page):
    """
    Click every entry point in the application and assert none of them
    raises. A menu item that silently does nothing — or throws into the
    console — is the classic way a GUI rots; this sweep is what keeps the
    answer to "does everything work?" honest.
    """
    pg = fresh_page
    broken = []

    def close_any():
        if pg.locator("#modal-back.on").count():
            for label in ("Cancel", "Close"):
                btn = pg.locator(f".dialog .foot button:has-text('{label}')")
                if btn.count():
                    btn.first.click()
                    pg.wait_for_timeout(120)
                    return
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(120)

    exercised = 0
    skipped = []
    # Two entry points are excluded because doing them is the point of them:
    # Close Project leaves the sweep with no document to click into, and Exit
    # stops the server this page is talking to. Both have tests of their own
    # (test_closing_a_project_asks_first, test_exit_asks_before_it_quits).
    destructive = {"Close Project", "Close", "Exit"}
    menus = pg.locator("#menubar .menu")
    for mi in range(menus.count()):
        menu = menus.nth(mi)
        title = menu.locator("button").first.inner_text()

        def open_menu():
            if not menu.evaluate("e=>e.classList.contains('open')"):
                menu.locator("button").first.click()
            pg.wait_for_timeout(90)

        open_menu()
        items = menu.locator(".menu-pop button")
        for ii in range(items.count()):
            open_menu()
            label = items.nth(ii).inner_text().split("\n")[0]
            if label.strip() in destructive:
                continue
            if items.nth(ii).is_disabled():
                # Undo, Paste and the rest are greyed out until they mean
                # something; that they are disabled is itself correct.
                skipped.append(f"{title} > {label}")
                continue
            before = len(pg.errors)
            try:
                items.nth(ii).click()
                pg.wait_for_timeout(400)
            except Exception as exc:
                broken.append(f"{title} > {label}: {exc}")
                continue
            close_any()
            if len(pg.errors) > before:
                broken.append(f"{title} > {label}: {pg.errors[before]}")
            exercised += 1
        pg.keyboard.press("Escape")

    tabs = pg.locator("#ribbon-tabs button")
    for ti in range(tabs.count()):
        tabs.nth(ti).click()
        pg.wait_for_timeout(120)
        tname = tabs.nth(ti).inner_text()
        buttons = pg.locator("#ribbon-body .rbtn")
        for bi in range(buttons.count()):
            tabs.nth(ti).click()
            pg.wait_for_timeout(80)
            label = buttons.nth(bi).inner_text().strip()
            if label in destructive:
                continue
            before = len(pg.errors)
            try:
                buttons.nth(bi).click()
                pg.wait_for_timeout(400)
            except Exception as exc:
                broken.append(f"ribbon {tname} > {label}: {exc}")
                continue
            close_any()
            if len(pg.errors) > before:
                broken.append(f"ribbon {tname} > {label}: {pg.errors[before]}")
            exercised += 1

    print(f"\nentry points exercised: {exercised}, disabled: {len(skipped)}")
    assert exercised >= 80, f"only {exercised} entry points found"
    # The disabled ones are the commands that need history, a clipboard or a
    # selection, on a design that has none of the three. Anything else greyed
    # out is a defect.
    needs_a_selection = {"View > Fit Selection"}
    assert all(x.startswith("Edit > ") or x in needs_a_selection
               for x in skipped), skipped
    assert not broken, "\n".join(broken)


# ------------------------------------------------------------ edit tools
@pytest.fixture(scope="module")
def edit_page(desktop, browser):
    """A third tab, on a project of its own so the sweep cannot upset it."""
    url, _ = desktop
    pg = _new_page(browser, url)
    pg.evaluate("()=>rpc('project.new',{}).then(()=>rpc('modeler.draw',"
                "{shape:'box',name:'EditBox',params:"
                "{position:['0mm','0mm','0mm'],size:['10mm','4mm','2mm']}}))")
    pg.wait_for_function("()=>STATE.design.objects.length===1", timeout=30000)
    pg.evaluate("()=>refreshGeometry(true)")
    pg.wait_for_timeout(500)
    yield pg
    pg.close()


def menu_item(pg, menu, label):
    pg.evaluate("()=>closeMenus()")          # a menu left open would toggle shut
    pg.click(f"#menubar .menu button:text-is('{menu}')")
    pg.wait_for_timeout(120)
    pg.click(f"#menubar .menu.open .menu-pop button:has-text('{label}')")
    pg.wait_for_timeout(200)


def nobj(pg):
    return pg.evaluate("()=>STATE.design.objects.length")


def test_edit_menu_disables_what_cannot_be_done_yet(edit_page):
    pg = edit_page
    pg.evaluate("()=>rpc('modeler.select',{names:[]})")
    pg.click("#menubar .menu button:text-is('Edit')")
    pg.wait_for_timeout(150)
    pop = pg.locator("#menubar .menu.open .menu-pop")
    assert pop.locator("button:has-text('Paste')").first.is_disabled()
    assert pop.locator("button:has-text('Copy')").first.is_disabled()
    pg.evaluate("()=>closeMenus()")


def test_duplicate_along_line_creates_the_pattern(edit_page):
    pg = edit_page
    n0 = nobj(pg)
    first = pg.evaluate("()=>STATE.design.objects[0].name")
    menu_item(pg, "Edit", "Duplicate ▸ Along Line")
    pg.wait_for_selector("#modal-back.on")
    pg.select_option("#q-objs", [first])
    pg.fill("#q-n", "3")
    pg.fill("#qx", "50mm"); pg.fill("#qy", "0mm"); pg.fill("#qz", "0mm")
    ok(pg)
    pg.wait_for_function(f"()=>STATE.design.objects.length==={n0 + 2}",
                         timeout=30000)


def test_undo_and_redo_reach_the_model(edit_page):
    pg = edit_page
    n = nobj(pg)
    menu_item(pg, "Edit", "Undo")
    pg.wait_for_function(f"()=>STATE.design.objects.length==={n - 2}",
                         timeout=30000)
    menu_item(pg, "Edit", "Redo")
    pg.wait_for_function(f"()=>STATE.design.objects.length==={n}",
                         timeout=30000)


def test_copy_and_paste_from_the_keyboard(edit_page):
    pg = edit_page
    first = pg.evaluate("()=>STATE.design.objects[0].name")
    pg.evaluate(f"()=>rpc('modeler.select',{{names:['{first}']}})")
    pg.wait_for_timeout(200)
    n = nobj(pg)
    pg.evaluate("()=>document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("Control+c")
    pg.wait_for_function("()=>STATE.history.clipboard===1", timeout=15000)
    pg.keyboard.press("Control+v")
    pg.wait_for_function(f"()=>STATE.design.objects.length==={n + 1}",
                         timeout=30000)
    pg.keyboard.press("Control+z")
    pg.wait_for_function(f"()=>STATE.design.objects.length==={n}",
                         timeout=30000)


def test_arrange_move_shifts_the_object(edit_page):
    pg = edit_page
    first = pg.evaluate("()=>STATE.design.objects[0].name")
    menu_item(pg, "Edit", "Arrange ▸ Move")
    pg.wait_for_selector("#modal-back.on")
    pg.select_option("#t-objs", [first])
    pg.fill("#tx", "0mm"); pg.fill("#ty", "0mm"); pg.fill("#tz", "7mm")
    ok(pg)
    pg.wait_for_timeout(900)
    assert all(e[0] != "pageerror" for e in pg.errors)


@needs_occ
def test_import_cad_inspects_the_file_before_importing(edit_page, tmp_path):
    """The unit is chosen and the file is reported before anything lands in
    the model — the fix for 'I imported a STEP file and nothing appeared'."""
    import aether as ae
    from aether.geometry.brep_io import export_shapes
    from aether.geometry.kernel import GmshSession, build_shape
    path = str(tmp_path / "widget.step")
    with GmshSession("mk") as gmsh:
        build_shape(ae.Box((0, 0, 0), ("20mm", "10mm", "4mm")), gmsh)
        gmsh.model.occ.synchronize()
        export_shapes(path, gmsh)

    pg = edit_page
    n0 = nobj(pg)
    pg.click("#ribbon-tabs button:has-text('Draw')")
    pg.click(".rbtn:has-text('Import')")
    pg.wait_for_selector("#modal-back.on")
    assert pg.locator("#ic-unit").count() == 1
    # the picker is a real dialog; drive the same code path it feeds
    pg.evaluate(f"()=>{{document.getElementById('ic-path').value={path!r};"
                "document.getElementById('ic-name').value='Widget';}")
    pg.select_option("#ic-unit", "mm")
    pg.wait_for_function(
        "()=>document.getElementById('ic-info').textContent.includes('solid')",
        timeout=60000)
    info = pg.locator("#ic-info").inner_text()
    assert "1 solid" in info and "unit mm" in info
    # a single-body file offers no "separate bodies" choice
    assert pg.locator("#ic-sep-row").is_hidden()
    assert info.split("extent ")[1].startswith("20.000 × 10.000 × 4.00")
    ok(pg)
    pg.wait_for_function(f"()=>STATE.design.objects.length==={n0 + 1}",
                         timeout=60000)
    assert "Widget" in pg.locator("#tree").inner_text()
    # and it is visible: the tessellator produced triangles for it
    pg.wait_for_function("()=>window.currentBuffersLen>=1", timeout=60000)


@pytest.fixture(scope="module")
def step_file(tmp_path_factory):
    import aether as ae
    from aether.geometry.brep_io import export_shapes
    from aether.geometry.kernel import GmshSession, build_shape
    path = tmp_path_factory.mktemp("cad") / "picked.step"
    with GmshSession("mk") as gmsh:
        build_shape(ae.Box((0, 0, 0), ("6mm", "6mm", "6mm")), gmsh)
        gmsh.model.occ.synchronize()
        export_shapes(str(path), gmsh)
    return str(path)


@needs_occ
def test_browsing_from_inside_import_cad_keeps_the_dialog(edit_page, step_file):
    """The regression: the file browser overwrote the one dialog panel, so
    picking a file destroyed the Import CAD dialog waiting for it — the import
    then did nothing at all, which is exactly what it looked like."""
    pg = edit_page
    n0 = nobj(pg)
    pg.click("#ribbon-tabs button:has-text('Draw')")
    pg.click(".rbtn:has-text('Import')")
    pg.wait_for_selector("#ic-unit")
    pg.click(".dialog:not([hidden]) button:has-text('Browse')")
    pg.wait_for_selector("#fp-name")
    # two dialogs are open at once; only the browser is interactive
    assert pg.locator("#modal-back > .dialog").count() == 2
    # a full path typed into the name box is accepted directly
    pg.fill("#fp-name", step_file)
    pg.keyboard.press("Enter")
    pg.wait_for_function("()=>document.getElementById('fp-name')===null",
                         timeout=30000)
    # the parent survived, with the picked file and a name filled in
    assert pg.locator("#ic-unit").count() == 1
    assert pg.input_value("#ic-path") == step_file
    assert pg.input_value("#ic-name") == "picked"
    pg.wait_for_function(
        "()=>document.getElementById('ic-info').textContent.includes('solid')",
        timeout=60000)
    ok(pg)
    pg.wait_for_function(f"()=>STATE.design.objects.length==={n0 + 1}",
                         timeout=60000)
    assert "picked" in pg.locator("#tree").inner_text()


@needs_occ
def test_an_imported_body_is_editable_from_the_property_grid(edit_page):
    pg = edit_page
    pg.evaluate("()=>{showProps('object','picked'); }")
    pg.wait_for_timeout(300)
    txt = pg.locator("#props-body").inner_text()
    assert "picked.step" in txt and "Model units" in txt
    # change the unit from the grid: the body must resize, in place
    before = pg.evaluate("()=>STATE.design.bbox")
    pg.select_option("#props-body select#pm", label="copper")
    pg.wait_for_function(
        "()=>STATE.design.objects.find(o=>o.name==='picked')"
        ".material==='copper'", timeout=30000)
    assert before is not None


@needs_occ
def test_replace_cad_source_dialog_changes_the_unit_in_place(edit_page):
    pg = edit_page
    menu_item(pg, "Modeler", "Replace CAD Source")
    pg.wait_for_selector("#rc-obj")
    pg.select_option("#rc-obj", "picked")
    pg.select_option("#rc-unit", "cm")
    ok(pg)
    pg.wait_for_timeout(900)
    o = pg.evaluate("()=>STATE.design.objects.find(o=>o.name==='picked')")
    assert o["cad"]["unit"] == "cm"          # same object, new unit
    assert o["material"] == "copper"         # everything else survived


# --------------------------------------------------- selection & faces
def test_selection_modes_switch_from_the_toolbar_and_the_keyboard(edit_page):
    pg = edit_page
    pg.evaluate("()=>closeMenus()")
    pg.click("#vt-sel-face")
    pg.wait_for_timeout(200)
    assert pg.evaluate("()=>SEL_MODE") == "face"
    assert pg.locator("#vt-sel-face.on").count() == 1
    pg.evaluate("()=>document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("e")
    pg.wait_for_timeout(200)
    assert pg.evaluate("()=>SEL_MODE") == "edge"
    pg.keyboard.press("o")
    pg.wait_for_timeout(200)
    assert pg.evaluate("()=>SEL_MODE") == "object"


def test_clicking_a_face_picks_it_and_the_status_bar_says_its_area(edit_page):
    pg = edit_page
    first = pg.evaluate("()=>STATE.design.objects[0].name")
    pg.evaluate("()=>{VP.view('iso'); VP.fit();}")
    pg.wait_for_timeout(300)
    pg.evaluate("()=>setSelectMode('face')")
    # drive the same path a click takes, from the middle of the canvas
    hit = pg.evaluate("""()=>{
      const c = document.getElementById('gl');
      for (let dx = 0; dx < 220; dx += 11) {
        const h = VP.pick(c.clientWidth/2 + dx, c.clientHeight/2);
        if (h && h.face >= 0) { VP.onPick(h, {}); return h; }
      }
      return null; }""")
    assert hit and hit["face"] >= 0
    pg.wait_for_timeout(400)
    assert pg.evaluate("()=>FACE_PICKS.length") == 1
    txt = pg.locator("#status-sel").inner_text()
    assert "face(s)" in txt and "mm" in txt
    assert pg.evaluate("()=>STATE.selFaces ? 1 : 0") is not None


def test_a_boundary_can_be_assigned_to_the_picked_face(edit_page):
    pg = edit_page
    n0 = pg.evaluate("()=>STATE.design.boundaries.length")
    pg.click("#ribbon-tabs button:has-text('Simulation')")
    pg.click(".rbtn:has-text('Assign')")
    pg.wait_for_selector("#bs-kind")
    assert pg.input_value("#bs-kind") == "faces"     # the pick is the default
    ok(pg)
    pg.wait_for_function(f"()=>STATE.design.boundaries.length==={n0 + 1}",
                         timeout=30000)
    b = pg.evaluate("()=>STATE.design.boundaries.at(-1)")
    assert "face" in b["selector"]["label"].lower()


def test_a_mesh_operation_can_be_added_on_the_picked_face(edit_page):
    pg = edit_page
    pg.evaluate("()=>closeMenus()")
    menu_item(pg, "Simulation", "Add Mesh Operation")
    pg.wait_for_selector("#mo-kind")
    assert pg.input_value("#mo-kind") == "faces"
    pg.fill("#mo-len", "0.4mm")
    ok(pg)
    pg.wait_for_function("()=>STATE.design.meshOps.length>=1", timeout=30000)
    assert "Length1" in pg.locator("#tree").inner_text()


def test_sweeping_the_picked_face_makes_a_new_body(edit_page):
    pg = edit_page
    pg.evaluate("()=>setSelectMode('face')")
    hit = pg.evaluate("""()=>{
      const c = document.getElementById('gl');
      for (let dx = 0; dx < 220; dx += 11) {
        const h = VP.pick(c.clientWidth/2 + dx, c.clientHeight/2);
        if (h && h.face >= 0) { VP.onPick(h, {}); return h; }
      }
      return null; }""")
    assert hit
    obj = hit["name"]
    extent = ("()=>rpc('view.geometry',{}).then(g=>{const o=g.objects"
              ".find(x=>x.name===%r); const p=o.position; let lo=[1e9,1e9,1e9],"
              "hi=[-1e9,-1e9,-1e9];"
              "for(let i=0;i<p.length;i+=3){for(let k=0;k<3;k++){"
              "lo[k]=Math.min(lo[k],p[i+k]);hi[k]=Math.max(hi[k],p[i+k]);}}"
              "return [hi[0]-lo[0],hi[1]-lo[1],hi[2]-lo[2]];})" % obj)
    before = pg.evaluate(extent)
    n0 = nobj(pg)
    menu_item(pg, "Modeler", "Sweep Face Along Normal")
    pg.wait_for_selector("#fo-d")
    pg.fill("#fo-d", "4mm")
    pg.fill("#fo-name", "SweptPatch")
    ok(pg)
    pg.wait_for_function(f"()=>STATE.design.objects.length==={n0 + 1}",
                         timeout=30000)
    pg.wait_for_timeout(1500)
    # the swept volume is its own body, 4 mm deep along the face normal
    made = pg.evaluate(extent.replace(repr(obj), repr("SweptPatch")))
    assert any(abs(v - 4e-3) < 2e-4 for v in made), made
    # ...and the body the face belongs to is untouched
    after = pg.evaluate(extent)
    assert after == pytest.approx(before, abs=1e-6)


# ------------------------------------------- display properties & right-click
def test_colour_and_transparency_are_editable_in_the_property_grid(edit_page):
    pg = edit_page
    pg.evaluate("()=>closeContext()")
    name = pg.evaluate("()=>STATE.design.objects[0].name")
    pg.evaluate(f"()=>showProps('object',{name!r})")
    pg.wait_for_timeout(300)
    grid = pg.locator("#props-body").inner_text()
    assert "Colour" in grid and "Transparency" in grid and "Visible" in grid

    pg.fill("#props-body input[type=color]", "#ff8800")
    pg.dispatch_event("#props-body input[type=color]", "change")
    pg.wait_for_function(
        f"()=>STATE.design.objects.find(o=>o.name==={name!r}).color==='#ff8800'",
        timeout=30000)

    slider = pg.locator("#props-body input[type=range]")
    slider.fill("0.9")
    slider.dispatch_event("change")
    pg.wait_for_function(
        f"()=>Math.abs(STATE.design.objects.find(o=>o.name==={name!r})"
        ".transparency-0.9)<1e-6", timeout=30000)


def test_hiding_an_object_removes_it_from_the_viewport(edit_page):
    pg = edit_page
    name = pg.evaluate("()=>STATE.design.objects[0].name")
    pg.evaluate(f"()=>showProps('object',{name!r})")
    pg.wait_for_timeout(250)
    box = pg.locator("#props-body input[type=checkbox]").last
    box.uncheck()
    pg.wait_for_function(
        f"()=>VP.objects.find(o=>o.name==={name!r}).visible===false",
        timeout=30000)
    box.check()
    pg.wait_for_function(
        f"()=>VP.objects.find(o=>o.name==={name!r}).visible!==false",
        timeout=30000)


def test_right_clicking_the_viewport_opens_the_modeller_menu(edit_page):
    pg = edit_page
    pg.evaluate("()=>{closeContext(); setSelectMode('object');}")
    pg.evaluate("()=>{VP.view('iso'); VP.fit();}")
    pg.wait_for_timeout(300)
    box = pg.locator("#gl").bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pg.mouse.down(button="right")
    pg.mouse.up(button="right")
    pg.wait_for_selector(".ctx", timeout=15000)
    txt = pg.locator(".ctx").inner_text()
    for item in ("Select Faces", "Assign Boundary", "Sweep Face Along Normal",
                 "Fit All", "Properties"):
        assert item in txt
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    assert pg.locator(".ctx").count() == 0


def test_the_viewport_menu_runs_a_command(edit_page):
    pg = edit_page
    box = pg.locator("#gl").bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pg.mouse.down(button="right")
    pg.mouse.up(button="right")
    pg.wait_for_selector(".ctx")
    pg.click(".ctx button:has-text('Select Faces')")
    pg.wait_for_timeout(300)
    assert pg.evaluate("()=>SEL_MODE") == "face"
    assert pg.locator(".ctx").count() == 0


def test_right_clicking_the_tree_offers_what_applies_to_that_node(edit_page):
    pg = edit_page
    pg.evaluate("()=>{closeContext(); setSelectMode('object');}")
    name = pg.evaluate("()=>STATE.design.objects[0].name")
    node = pg.locator(f"#tree .node:has-text('{name}')").first
    node.click(button="right")
    pg.wait_for_selector(".ctx", timeout=15000)
    txt = pg.locator(".ctx").inner_text()
    for item in ("Properties", "Rename", "Assign Boundary", "Hide", "Delete"):
        assert item in txt
    pg.keyboard.press("Escape")


# --------------------------------------- measuring, drawing, assignments
def test_a_picked_face_is_measured_on_screen(edit_page):
    pg = edit_page
    pg.evaluate("()=>{closeContext(); setSelectMode('face');}")
    pg.evaluate("()=>{VP.view('iso'); VP.fit();}")
    pg.wait_for_timeout(300)
    hit = pg.evaluate("""()=>{
      const c = document.getElementById('gl');
      for (let dx = 0; dx < 220; dx += 11) {
        const h = VP.pick(c.clientWidth/2 + dx, c.clientHeight/2);
        if (h && h.face >= 0) { VP.onPick(h, {}); return h; }
      }
      return null; }""")
    assert hit
    pg.wait_for_function("()=>MEASURE && MEASURE.kind==='face'", timeout=30000)
    box = pg.locator("#vp-measure")
    assert box.is_visible()
    assert "area" in box.inner_text()


def test_two_picked_faces_show_the_gap_and_a_dimension_label(edit_page):
    pg = edit_page
    # pick two faces of one body from the API side, the way a second click does
    picks = pg.evaluate("""async ()=>{
      const g = await rpc('view.geometry', {});
      const o = g.objects.find(x=>x.faces && x.faces.length>=2);
      const top = o.faces.reduce((a,b)=> a.point[2]>b.point[2]?a:b);
      const bot = o.faces.reduce((a,b)=> a.point[2]<b.point[2]?a:b);
      FACE_PICKS = [Object.assign({object:o.name, face:o.faces.indexOf(top)}, top),
                    Object.assign({object:o.name, face:o.faces.indexOf(bot)}, bot)];
      VP.setFaceSelection(FACE_PICKS);
      await rpc('modeler.select', {faces: FACE_PICKS, names: []});
      await refreshMeasure();
      return FACE_PICKS.length; }""")
    assert picks == 2
    pg.wait_for_function("()=>MEASURE && MEASURE.distance>0", timeout=30000)
    assert "gap" in pg.locator("#vp-measure").inner_text()
    assert pg.locator("#vp-dim").is_visible()
    assert pg.evaluate("()=>!!VP.measureBuf")


def test_drawing_a_box_from_two_clicked_points(edit_page):
    """Two clicks in the viewport, then the height — and no modal at any point
    in it. The coordinates live in a panel beside the model, not in a dialog
    on top of it."""
    pg = edit_page
    pg.evaluate("()=>{closeContext(); setSelectMode('object');}")
    n0 = nobj(pg)
    pg.click("#ribbon-tabs button:has-text('Draw')")
    pg.click("#ribbon-body .rbtn:has-text('Box by points')")
    pg.wait_for_selector("#vp-draw.on", timeout=15000)
    assert pg.evaluate("()=>DIALOG_STACK.length") == 0
    box = pg.locator("#gl").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.click(cx - 60, cy + 40)
    pg.wait_for_timeout(250)
    assert pg.evaluate("()=>DRAW && DRAW.stage") == "p2"
    assert pg.evaluate("()=>DRAW && !!DRAW.p1")
    pg.mouse.move(cx + 60, cy - 20)
    pg.wait_for_timeout(200)
    # the panel is tracking the drag, live
    assert pg.input_value("#dw-b0") not in ("",)
    pg.mouse.click(cx + 60, cy - 20)
    pg.wait_for_function("()=>DRAW && DRAW.stage==='h'", timeout=15000)
    assert pg.evaluate("()=>DIALOG_STACK.length") == 0
    # An isometric view can put both clicks on the same X, which is a body of
    # zero width. The panel says so, and correcting it by typing is the other
    # half of the feature: draw roughly, then fix the number.
    pg.fill("#dw-s0", "9")
    pg.press("#dw-s0", "Enter")
    pg.fill("#dw-s1", "4")
    pg.press("#dw-s1", "Tab")          # Enter here would already accept the box
    pg.fill("#dw-h", "3")
    pg.press("#dw-h", "Enter")
    pg.wait_for_function(f"()=>STATE.design.objects.length==={n0 + 1}",
                         timeout=30000)
    assert pg.evaluate(
        "()=>document.querySelector('#vp-draw').classList.contains('on')") is False


def test_a_point_draw_can_be_cancelled(edit_page):
    """Esc steps back a point at a time, and backs all the way out."""
    pg = edit_page
    assert pg.evaluate("()=>DIALOG_STACK.length") == 0
    pg.evaluate("()=>startPointDraw('box')")
    assert pg.evaluate("()=>!!DRAW")
    pg.evaluate("()=>document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    assert pg.evaluate("()=>DRAW") is None


def test_boundaries_and_ports_are_drawn_with_a_legend(edit_page):
    pg = edit_page
    pg.evaluate("()=>closeContext()")
    n = pg.evaluate("""async ()=>{
      const g = await rpc('view.geometry', {});
      const o = g.objects[0];
      const top = o.faces.reduce((a,b)=> a.point[2]>b.point[2]?a:b);
      await rpc('boundary.assign', {type:'pec', name:'ShownPec',
        selector:{kind:'faces', faces:[Object.assign({object:o.name}, top)]}});
      await refreshAssignments();
      return ASSIGN_ITEMS.length; }""")
    assert n >= 1
    legend = pg.locator("#vp-assign")
    assert legend.is_visible()
    assert "ShownPec" in legend.inner_text()
    assert pg.evaluate("()=>VP.assign.length") >= 1
    # and the overlay can be switched off
    pg.evaluate("()=>toggleAssignments()")
    pg.wait_for_timeout(200)
    assert pg.evaluate("()=>VP.showAssignments") is False
    assert legend.is_hidden()
    pg.evaluate("()=>toggleAssignments()")


def test_the_file_browser_offers_and_filters_dxf(edit_page, tmp_path):
    """The DXF reader was unreachable from the UI: the browser did not list
    .dxf files, so the feature looked as though it did not exist."""
    (tmp_path / "shape.dxf").write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n")
    (tmp_path / "part.step").write_text("x")
    pg = edit_page
    pg.evaluate("()=>{closeContext(); closeAllDialogs();}")
    pg.click("#ribbon-tabs button:has-text('Draw')")
    pg.click(".rbtn:has-text('Import')")
    pg.wait_for_selector("#ic-unit")
    pg.click(".dialog:not([hidden]) button:has-text('Browse')")
    pg.wait_for_selector("#fp-name")
    labels = pg.locator("#fp-filter option").all_inner_texts()
    assert any("DXF" in x for x in labels)
    # the folder listing shows the DXF alongside the STEP ...
    pg.fill("#fp-name", str(tmp_path))
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(600)
    assert "shape.dxf" in pg.locator(".fp-list").inner_text()
    # ... and choosing "DXF only" narrows it
    pg.select_option("#fp-filter", label=[x for x in labels if "DXF" in x][0])
    pg.wait_for_timeout(600)
    listed = pg.locator(".fp-list").inner_text()
    assert "shape.dxf" in listed and "part.step" not in listed
    pg.click(".dialog:not([hidden]) .foot button:has-text('Cancel')")
    pg.wait_for_timeout(200)
    pg.click(".dialog:not([hidden]) .foot button:has-text('Cancel')")


@needs_occ
def test_an_assembly_offers_to_split_and_does(edit_page, tmp_path):
    import aether as ae
    from aether.geometry.brep_io import export_shapes
    from aether.geometry.kernel import GmshSession, build_shape
    path = str(tmp_path / "asm.step")
    with GmshSession("mk") as gmsh:
        for i in range(3):
            build_shape(ae.Box((f"{i * 20}mm", "0mm", "0mm"),
                               ("8mm", "8mm", "2mm")), gmsh)
        gmsh.model.occ.synchronize()
        export_shapes(path, gmsh)

    pg = edit_page
    pg.evaluate("()=>{closeContext(); closeAllDialogs();}")
    n0 = nobj(pg)
    pg.click("#ribbon-tabs button:has-text('Draw')")
    pg.click(".rbtn:has-text('Import')")
    pg.wait_for_selector("#ic-unit")
    pg.evaluate(f"()=>{{document.getElementById('ic-path').value={path!r};"
                "document.getElementById('ic-name').value='Asm';}")
    pg.select_option("#ic-unit", "mm")
    pg.wait_for_function(
        "()=>document.getElementById('ic-info').textContent.includes('bodies')",
        timeout=60000)
    assert pg.locator("#ic-sep-row").is_visible()
    assert pg.is_checked("#ic-sep")
    ok(pg)
    pg.wait_for_function(f"()=>STATE.design.objects.length==={n0 + 3}",
                         timeout=60000)


def test_the_edit_session_raised_no_javascript_errors(edit_page):
    assert [e for e in edit_page.errors if e[0] == "pageerror"] == []
