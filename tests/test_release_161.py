"""Regressions for data loss, edit atomicity and numerical measurements."""
import os
import shutil
from pathlib import Path
import numpy as np
import pytest
from aether.gui.api import dispatch, COMMANDS
from aether.gui.state import Session
from aether.gui.files import resolve_save_path
from aether.gui.measurement import measure_points, segment_distance
from aether.geometry.primitives import ImportedShape
from aether.io.aedt.writer import write_project, embed_cad
from aether.io.aedt.translate import read_project


def session():
    s=Session(); s.new_project('Test')
    dispatch(s,'modeler.draw',{'shape':'box','name':'Box1','params':{'position':['1mm','2mm','3mm'],'size':['10mm','4mm','2mm']}})
    return s


def test_reopened_model_edit_is_actually_saved(tmp_path):
    s=session(); path=str(tmp_path/'모델.aedt')
    dispatch(s,'project.save',{'path':path})
    dispatch(s,'project.open',{'path':path})
    dispatch(s,'modeler.transform',{'name':'Box1','op':'move','params':{'dx':'5mm'}})
    dispatch(s,'modeler.draw',{'shape':'box','name':'NewBox','params':{'size':['1mm']*3}})
    dispatch(s,'project.save')
    dispatch(s,'project.open',{'path':path})
    assert len(s.design.solids)==2
    assert s.design.get_solid('Box1').shape.bounds()[0][0]==pytest.approx(.006)
    dispatch(s,'modeler.delete',{'names':['Box1']})
    dispatch(s,'project.save')
    dispatch(s,'project.open',{'path':path})
    assert [o.name for o in s.design.solids]==['NewBox']
    assert Path(path+'.bak').is_file()


def test_project_open_resets_cross_project_history(tmp_path):
    s=session(); p=str(tmp_path/'p.aedt');dispatch(s,'project.save',{'path':p})
    s.selection=['Box1'];dispatch(s,'modeler.copy')
    dispatch(s,'project.open',{'path':p})
    assert not s.can_undo and not s.can_redo
    assert not s.clipboard and not s.selection


def test_failed_edit_rolls_back_model_redo_and_dirty(monkeypatch):
    s=session();dispatch(s,'modeler.transform',{'name':'Box1','op':'move','params':{'dx':'1mm'}})
    dispatch(s,'edit.undo');s.dirty=False
    before=s.design.get_solid('Box1').shape.bounds()
    def broken(s,**_):
        s.design.get_solid('Box1').shape.translate('100mm',0,0)
        s.dirty=True
        raise ValueError('failure after mutation')
    monkeypatch.setitem(COMMANDS,'modeler.transform',broken)
    with pytest.raises(ValueError):dispatch(s,'modeler.transform')
    assert np.allclose(before,s.design.get_solid('Box1').shape.bounds())
    assert s.can_redo and not s.dirty


def test_cut_is_undoable_and_invalidates_solution():
    s=session();s.selection=['Box1'];s.dirty=False;s.solution=object()
    dispatch(s,'modeler.copy',{'cut':True})
    assert not s.design.solids and s.dirty and s.solution is None
    dispatch(s,'edit.undo')
    assert len(s.design.solids)==1


def test_resize_keeps_center_and_undo():
    s=session();s.selection=['Box1'];old=np.array(s.design.solids[0].shape.bounds())
    dispatch(s,'modeler.resize',{'size':[20,8,4]})
    now=np.array(s.design.solids[0].shape.bounds())
    assert np.allclose(now.mean(axis=0),old.mean(axis=0))
    assert np.allclose(now[1]-now[0],[.02,.008,.004])
    dispatch(s,'edit.undo');assert np.allclose(old,s.design.solids[0].shape.bounds())


def test_solve_blocks_geometry_mutation():
    s=session();s.job.running=True
    with pytest.raises(RuntimeError,match='Analysis is running'):
        dispatch(s,'modeler.delete',{'names':['Box1']})
    assert len(s.design.solids)==1


@pytest.mark.parametrize('args,expected',[
    (([0,0,0],[1,0,0],[.123,-1,0],[.123,1,0]),0),
    (([0,0,0],[1,0,0],[0,2,0],[1,2,0]),2),
    (([0,0,0],[0,0,0],[1,0,0],[2,0,0]),1),
    (([0,0,0],[1,0,0],[2,1,1],[2,2,1]),np.sqrt(3)),
])
def test_exact_segment_measure(args,expected):
    d,a,b=segment_distance(*args)
    assert d==pytest.approx(expected,abs=1e-12)
    assert np.linalg.norm(a-b)==pytest.approx(d)


@pytest.mark.parametrize('unit,k',[('mm',.001),('in',.0254),('mil',.0000254),('m',1)])
def test_measure_units_and_axis_deltas(unit,k):
    r=measure_points('distance',[[0,0,0],[3,4,0]],unit)
    assert r['distance']==pytest.approx(5*k)
    assert r['delta']==pytest.approx([3*k,4*k,0])


def test_angle_circle_and_invalid_inputs():
    assert measure_points('angle',[[1,0,0],[0,0,0],[0,1,0]])['angle']==pytest.approx(90)
    r=measure_points('circle',[[1,0,0],[0,1,0],[-1,0,0]])
    assert r['radius']==pytest.approx(.001)
    assert r['center']==pytest.approx([0,0,0],abs=1e-12)
    with pytest.raises(ValueError):measure_points('circle',[[0,0,0],[1,0,0],[2,0,0]])
    with pytest.raises(ValueError):measure_points('distance',[[0,0,0],[float('nan'),0,0]])
    assert measure_points('distance',[['0mm',0,0],['1in',0,0]],'mm')['distance']==pytest.approx(.0254)


def test_save_relative_subdirectory(tmp_path):
    (tmp_path/'sub').mkdir()
    assert resolve_save_path(str(tmp_path),'sub/project',['.aedt'])['path']==str(tmp_path/'sub/project.aedt')


def test_save_failure_leaves_previous_file_and_dirty(tmp_path,monkeypatch):
    s=session();p=str(tmp_path/'project.aedt');dispatch(s,'project.save',{'path':p})
    before=Path(p).read_bytes();s.dirty=True
    def fail(*a,**k):raise OSError('simulated replace failure')
    monkeypatch.setattr(os,'replace',fail)
    with pytest.raises(OSError):dispatch(s,'project.save')
    assert Path(p).read_bytes()==before and s.dirty


def test_same_basename_cad_is_preserved_and_archive_portable(tmp_path):
    s=session();s.design.solids=[]
    # Source preservation is independent of CAD backend availability.
    for n,content in [('a',b'first CAD payload'),('b',b'second CAD payload')]:
        folder=tmp_path/n;folder.mkdir();src=folder/'part.step';src.write_bytes(content)
        shape=ImportedShape(str(src),name=n)
        s.design.add_solid(n,shape)
    path=tmp_path/'portable.aedtz'
    write_project(str(path),s.project)
    files=list((tmp_path/'portable.cad').glob('*.step'))
    assert len(files)==2
    assert {f.read_bytes() for f in files}=={b'first CAD payload',b'second CAD payload'}
    moved=tmp_path/'elsewhere';moved.mkdir();dest=moved/'renamed.aedtz';shutil.copy2(path,dest)
    shutil.rmtree(tmp_path/'a');shutil.rmtree(tmp_path/'b');shutil.rmtree(tmp_path/'portable.cad')
    project,_=read_project(str(dest))
    assert {Path(o.shape.path).read_bytes() for o in project[0].solids}=={b'first CAD payload',b'second CAD payload'}


def test_units_mesh_and_full_sweep_settings_roundtrip(tmp_path):
    s=session();s.design.units='in'
    s.design.add_mesh_operation('Fine','0.25mm',objects=['Box1'])
    st=s.design.add_setup('Custom','2.4GHz');st.min_passes=3;st.basis_order=2
    st.add_sweep('Sparse',points=['2GHz','2.4GHz','3GHz'],save_fields=True)
    p=str(tmp_path/'settings.aedt');dispatch(s,'project.save',{'path':p})
    dispatch(s,'project.open',{'path':p})
    assert s.design.units=='in'
    assert s.design.mesh_ops[0].max_length==pytest.approx(.00025)
    st=s.design.setups[0]
    assert st.min_passes==3 and st.basis_order==2
    assert np.allclose(st.sweeps[0].frequencies(),[2e9,2.4e9,3e9])
    assert st.sweeps[0].save_fields


def test_insert_design_after_open_can_save(tmp_path):
    s=session();p=str(tmp_path/'multi.aedt');dispatch(s,'project.save',{'path':p})
    dispatch(s,'project.open',{'path':p})
    dispatch(s,'project.insertDesign',{'name':'Second'})
    dispatch(s,'project.save');dispatch(s,'project.open',{'path':p})
    assert [d.name for d in s.project.designs]==['HFSSDesign1','Second']


def test_empty_import_keeps_existing_project(tmp_path):
    p=tmp_path/'empty.aedt';p.write_text("$begin 'AnsoftProject'\n$end 'AnsoftProject'\n")
    s=session()
    with pytest.raises(ValueError):dispatch(s,'project.open',{'path':str(p)})
    assert s.design.solids[0].name=='Box1' and s.can_undo


def test_rename_and_delete_keep_mesh_references_valid(tmp_path):
    s=session();s.design.add_mesh_operation('Fine','0.2mm',objects=['Box1'])
    dispatch(s,'modeler.setProperty',{'name':'Box1','prop':'name','value':'Renamed'})
    assert s.design.mesh_ops[0].objects==['Renamed']
    dispatch(s,'modeler.delete',{'names':['Renamed']})
    assert not s.design.mesh_ops
    dispatch(s,'edit.undo')
    assert s.design.mesh_ops[0].objects==['Renamed']
    p=str(tmp_path/'renamed.aedt');dispatch(s,'project.save',{'path':p});dispatch(s,'project.open',{'path':p})
    assert s.design.mesh_ops[0].objects==['Renamed']
