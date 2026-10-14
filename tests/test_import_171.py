"""Import regressions: assembly registration, DXF graphs, project encodings."""
from pathlib import Path
import zipfile
import numpy as np
import pytest
import ezdxf
from aether.gui.api import dispatch, _clean_part_name
from aether.gui.state import Session
from aether.geometry.dxf import read_dxf, outlines
from aether.geometry.primitives import ImportedShape, Sketch
from conftest import needs_occ


def session():
    s=Session();s.new_project('Imports');return s


def drawing(tmp_path,name='drawing.dxf'):
    doc=ezdxf.new();doc.units=4
    return doc,doc.modelspace(),str(tmp_path/name)


def test_step_multibody_registration_without_kernel_dependency(tmp_path,monkeypatch):
    # Exercise the exact GUI branch that raised _clean_part_name NameError.
    # CAD-kernel reading is deliberately mocked; the real case is separate.
    from aether.geometry import brep_io
    p=tmp_path/'Tx_Antenna_ver2.stp';p.write_text('test payload')
    info=dict(format='step',error='',solids=3,surfaces=24,bbox=[[0,0,0],[.02,.03,.004]],
              appliedUnit='mm',declaredUnit='mm',bodyList=[
              {'index':0,'name':'Assembly/기판'},{'index':1,'name':'Assembly/기판'},
              {'index':2,'name':'Open CASCADE STEP translator'}])
    monkeypatch.setattr(brep_io,'probe',lambda *a,**kw:info)
    s=session();r=dispatch(s,'modeler.importCad',{'path':str(p)})
    assert r['ok'] and len(s.design.solids)==3
    assert len({o.name for o in s.design.solids})==3
    assert s.design.solids[0].name=='기판'
    assert [o.shape.body for o in s.design.solids]==[0,1,2]
    dispatch(s,'edit.undo');assert not s.design.solids
    dispatch(s,'edit.redo');assert len(s.design.solids)==3


def test_assembly_labels_are_safe_and_unicode_preserved():
    assert _clean_part_name('Assembly/123 copper')=='P123_copper'
    assert _clean_part_name('Assembly\\패치')=='패치'
    assert _clean_part_name('Open CASCADE STEP translator')==''


@needs_occ
def test_real_step_three_solids_import_render_save(tmp_path):
    from aether.geometry.kernel import GmshSession
    p=tmp_path/'assembly.step'
    with GmshSession('fixture') as g:
        for x in (0,20,40):g.model.occ.addBox(x,0,0,10,10,1)
        g.model.occ.synchronize();g.write(str(p))
    s=session();dispatch(s,'modeler.importCad',{'path':str(p),'unit':'mm','separate':True})
    assert len(s.design.solids)==3
    geometry=dispatch(s,'view.geometry')
    assert len(geometry['objects'])==3
    assert all(o['count']>0 for o in geometry['objects'])
    assert np.allclose(geometry['bbox'],[[0,0,0],[.05,.01,.001]],atol=1e-7)
    output=str(tmp_path/'moved.warpz');dispatch(s,'project.save',{'path':output})
    p.unlink();dispatch(s,'project.open',{'path':output})
    assert len(dispatch(s,'view.geometry')['objects'])==3


def test_individual_lines_join_into_sheet_outline(tmp_path):
    doc,m,path=drawing(tmp_path)
    points=[(0,0),(20,0),(20,10),(0,10)]
    # unordered and reversed edge orientations
    for a,b in [(2,1),(0,3),(1,0),(3,2)]:m.add_line(points[a],points[b])
    doc.saveas(path);result=read_dxf(path)
    assert len(result['entities'])==1 and result['entities'][0].closed
    assert result['entities'][0].area==pytest.approx(200e-6)
    assert result['joinedChains']==1


def test_two_arcs_form_closed_circle(tmp_path):
    doc,m,path=drawing(tmp_path)
    m.add_arc((0,0),5,0,180);m.add_arc((0,0),5,180,360);doc.saveas(path)
    loops=outlines(path)
    assert len(loops)==1
    assert loops[0].area==pytest.approx(np.pi*25e-6,rel=.002)


def test_open_gap_is_not_fabricated_into_a_face(tmp_path):
    doc,m,path=drawing(tmp_path)
    m.add_lwpolyline([(0,0),(10,0),(10,10),(0,10),(0,1)])
    doc.saveas(path);assert not outlines(path)
    s=session();r=dispatch(s,'modeler.importCad',{'path':path})
    assert r['info']['referencePaths']==1 and r['info']['surfaces']==0
    assert not s.design.solids and isinstance(s.design.sheets[0].shape,Sketch)
    g=dispatch(s,'view.geometry')
    assert g['objects'][0]['referenceOnly'] and len(g['objects'][0]['edges'])==8
    assert np.allclose(g['bbox'],[[0,0,0],[.01,.01,0]])


def test_branching_lines_remain_references(tmp_path):
    doc,m,path=drawing(tmp_path)
    for p in [(10,0),(-10,0),(0,10)]:m.add_line((0,0),p)
    doc.saveas(path)
    assert not outlines(path) and len(read_dxf(path)['entities'])==3


def test_reference_sketch_save_reopen_and_transform(tmp_path):
    doc,m,path=drawing(tmp_path);m.add_line((10,20),(30,40));doc.saveas(path)
    s=session();r=dispatch(s,'modeler.importCad',{'path':path,'scale':2})
    dispatch(s,'modeler.transform',{'name':r['name'],'op':'move','params':{'dx':'1mm'}})
    original=dispatch(s,'view.geometry')
    project=str(tmp_path/'sketch.warpz');dispatch(s,'project.save',{'path':project})
    Path(path).unlink();dispatch(s,'project.open',{'path':project})
    restored=dispatch(s,'view.geometry')
    assert np.allclose(original['objects'][0]['edgeVerts'],restored['objects'][0]['edgeVerts'])
    assert np.allclose(restored['bbox'],[[.021,.04,0],[.061,.08,0]])


def test_block_insert_transform_and_unused_block_not_imported(tmp_path):
    doc,m,path=drawing(tmp_path)
    block=doc.blocks.new('Patch');block.add_lwpolyline([(0,0),(10,0),(10,5),(0,5)],close=True)
    unused=doc.blocks.new('Unused');unused.add_circle((1000,1000),100)
    m.add_blockref('Patch',(20,30),dxfattribs={'xscale':2,'yscale':2,'rotation':90})
    doc.saveas(path);loops=outlines(path)
    assert len(loops)==1
    assert np.allclose(loops[0].points.min(axis=0),[.01,.03,0],atol=1e-12)
    assert np.allclose(loops[0].points.max(axis=0),[.02,.05,0],atol=1e-12)


def test_spline_ellipse_and_ocs_elevation(tmp_path):
    doc,m,path=drawing(tmp_path)
    m.add_ellipse((0,0,2),major_axis=(10,0,0),ratio=.5)
    m.add_spline([(0,0),(2,3),(5,2)])
    doc.saveas(path);entities=read_dxf(path)['entities']
    ellipse=next(e for e in entities if e.kind=='ellipse')
    assert ellipse.closed and ellipse.area==pytest.approx(np.pi*50e-6,rel=.002)
    assert np.allclose(ellipse.points[:,2],.002)
    assert any(e.kind=='spline' and not e.closed for e in entities)


def test_utf16_warps_project_is_read(tmp_path):
    s=session();dispatch(s,'modeler.draw',{'name':'Patch','shape':'box'})
    p=tmp_path/'unicode.warp';dispatch(s,'project.save',{'path':str(p)})
    text=p.read_text();p.write_bytes(text.replace('\n','\r\n').encode('utf-16'))
    dispatch(s,'project.open',{'path':str(p)})
    assert s.design.solids[0].name=='Patch'
    assert s.project.warp_tree.encoding=='utf-16'
    assert s.project.warp_tree.newline=='\r\n'


def test_nested_archive_keeps_relative_cad_source(tmp_path):
    s=session();cad=tmp_path/'body.step';cad.write_bytes(b'CAD source fixture')
    s.design.add_solid('Imported',ImportedShape(str(cad)))
    p=tmp_path/'source.warpz';dispatch(s,'project.save',{'path':str(p)})
    nested=tmp_path/'nested.warpz'
    with zipfile.ZipFile(p) as src,zipfile.ZipFile(nested,'w') as dst:
        for member in src.namelist():dst.writestr('ProjectFolder/'+member,src.read(member))
    cad.unlink()
    dispatch(s,'project.open',{'path':str(nested)})
    assert Path(s.design.solids[0].shape.path).read_bytes()==b'CAD source fixture'
    assert 'ProjectFolder' in s.project.warp_tree.source


def test_bad_archive_keeps_current_design(tmp_path):
    s=session();dispatch(s,'modeler.draw',{'name':'Existing'})
    p=tmp_path/'good.warp';dispatch(s,'project.save',{'path':str(p)})
    bad=tmp_path/'bad.warpz'
    with zipfile.ZipFile(bad,'w') as z:
        z.writestr('model.warp',p.read_bytes());z.writestr('../outside.step',b'invalid')
    with pytest.raises(ValueError,match='Unsafe'):dispatch(s,'project.open',{'path':str(bad)})
    assert s.design.solids[0].name=='Existing'


def test_dxf_tilted_circle_has_nonzero_wcs_area(tmp_path):
    doc,m,path=drawing(tmp_path)
    m.add_circle((0,0,0),5,dxfattribs={'extrusion':(1,0,0)})
    doc.saveas(path);loops=outlines(path)
    assert len(loops)==1
    assert loops[0].area==pytest.approx(np.pi*25e-6,rel=.002)
    assert np.ptp(loops[0].points[:,0])<1e-10


@pytest.mark.parametrize('code,scale',[(8,2.54e-8),(9,2.54e-5),(21,1200/3937)])
def test_dxf_insunits_special_units(tmp_path,code,scale):
    doc,m,path=drawing(tmp_path);doc.header['$INSUNITS']=code
    m.add_line((0,0),(1,0));doc.saveas(path)
    assert read_dxf(path)['entities'][0].length==pytest.approx(scale)
