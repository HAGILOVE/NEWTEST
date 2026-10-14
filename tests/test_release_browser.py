"""Run on a machine with Playwright Chromium; no OCC required for basic UI."""
import pytest
pw = pytest.importorskip('playwright.sync_api')

@pytest.fixture(scope='module')
def page():
    from aether.gui.server import serve
    with pw.sync_playwright() as driver:
        try:
            browser=driver.chromium.launch(args=['--enable-unsafe-swiftshader'])
        except Exception as exc:
            pytest.skip('Chromium not available: '+str(exc)[:160])
        server,_,session=serve(port=0,open_browser=False,token='',block=False)
        page=browser.new_page(viewport={'width':1500,'height':950},accept_downloads=True)
        page.goto('http://127.0.0.1:%s/' % server.server_address[1])
        page.wait_for_function('window.__aetherReady === true')
        yield page
        browser.close();server.shutdown();server.server_close()


def test_measure_shortcut_distance_and_csv(page):
    page.keyboard.press('m')
    page.select_option('#dim-mode','distance')
    for i,p in enumerate([[0,0,0],[3,4,0]]):
        for j,v in enumerate(p):page.fill(f'#dim-{i}-{j}',str(v))
    page.click('#dim-calculate')
    page.wait_for_function("document.querySelector('#dim-result').textContent.includes('Distance 5 mm')")
    with page.expect_download() as download:page.get_by_text('Export CSV',exact=True).click()
    assert download.value.suggested_filename=='aether-measurement.csv'
    page.evaluate('closeAllDialogs()')


def test_resize_dialog_changes_geometry(page):
    page.evaluate("async()=>{await rpc('project.new'); await rpc('modeler.draw',{shape:'box',name:'Box',params:{size:['10mm','4mm','2mm']}});await rpc('modeler.select',{names:['Box']});await refreshGeometry(true);await dlgResize();}")
    for i,v in enumerate([20,8,4]):page.fill('#resize-'+str(i),str(v))
    page.get_by_role('button',name='Apply',exact=True).click()
    page.wait_for_function('DIALOG_STACK.length === 0')
    result=page.evaluate("()=>rpc('modeler.measure')")
    assert result['size']==pytest.approx([.02,.008,.004])


def test_cancel_unsaved_new_keeps_project(page):
    """New Project on a dirty model asks first, in the application's own
    dialog (it used to be a browser confirm(), which could only offer discard
    or cancel). Cancelling it must leave the model untouched."""
    # not `newProject()` on its own: evaluate() awaits a returned promise, and
    # this one only settles once the prompt below has been answered.
    page.evaluate('()=>{ newProject(); }')
    page.wait_for_selector('#modal-back.on .dialog', timeout=10000)
    prompt = page.locator('#modal-back > .dialog:not([hidden])')
    assert 'Save changes' in prompt.inner_text()
    assert prompt.locator('.foot button:text-is("Don\'t Save")').count() == 1
    prompt.locator('.foot button:text-is("Cancel")').click()
    page.wait_for_function('DIALOG_STACK.length === 0', timeout=10000)
    assert page.evaluate('STATE.design.objects.length')==1


def test_viewport_measure_can_cancel(page):
    page.evaluate("startMeasurePick('distance')")
    page.keyboard.press('Escape')
    assert page.evaluate('MEASURE_PICK === null')
