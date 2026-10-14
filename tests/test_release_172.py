"""Rendering, import safety and point-picking regressions (no CAD dependency)."""
import shutil
import subprocess
from pathlib import Path
import numpy as np
import pytest
import aether as ae
from aether.gui.tessellate import tessellate_analytic, tessellate
from aether.geometry.primitives import Sketch, ImportedShape
from aether.diagnostics import import_errors
from aether.gui.api import dispatch
from aether.gui.state import Session


def test_cylinder_smooth_side_preserves_sharp_caps():
    t=tessellate_analytic(ae.Cylinder((0,0,0),1,3))
    p=np.array(t['position']).reshape(-1,3);n=np.array(t['normal']).reshape(-1,3)
    side=np.abs(n[:,2])<.5
    radial=p[side,:2]/np.linalg.norm(p[side,:2],axis=1)[:,None]
    assert np.min(np.sum(n[side,:2]*radial,axis=1))>.999
    assert np.allclose(np.abs(n[~side,2]),1)
    # Silhouette chord deviation below 0.04% of radius.
    xy=np.unique(p[side,:2],axis=0)
    angles=np.sort(np.arctan2(xy[:,1],xy[:,0]))
    gap=np.max(np.diff(np.r_[angles,angles[0]+2*np.pi]))
    assert 1-np.cos(gap/2)<.0004


def test_box_keeps_sharp_normals():
    t=tessellate_analytic(ae.Box((0,0,0),(1,2,3)))
    n=np.array(t['normal']).reshape(-1,3)
    assert np.all(np.sum(np.abs(n)>.01,axis=1)==1)
    assert len(t['faces'])==6


def test_drawing_exposes_points_and_edges():
    t=tessellate(Sketch([[[0,0,0],[1,2,0],[3,2,0]]]))
    assert len(t['snapPoints'])==3
    assert t['faceEdges']==[0,1,-1,1,2,-1]
    assert t['count']==0


def new_session():
    s=Session();s.new_project('Safety')
    dispatch(s,'modeler.draw',{'shape':'box','name':'Box1','params':{'position':[0,0,0],'size':[1,2,3]}})
    return s


def test_missing_geometry_and_material_block_import():
    s=new_session();o=s.design.solids[0]
    o.shape=ImportedShape('/missing/model.step');o.import_material='unknown alloy'
    errors=import_errors(s.design)
    assert any('CAD source' in e for e in errors)
    assert any('material' in e for e in errors)
    assert dispatch(s,'project.importStatus')['errors']==errors


def test_import_flags_survive_save_reopen_and_material_repair(tmp_path):
    s=new_session();s.design.solids[0].import_material='unknown alloy'
    s.design.import_issues=["part 'LostPart': unsupported creation"]
    p=str(tmp_path/'flags.warpz')
    dispatch(s,'project.save',{'path':p});dispatch(s,'project.open',{'path':p})
    assert any('material' in e for e in import_errors(s.design))
    assert any('LostPart' in e for e in import_errors(s.design))
    dispatch(s,'modeler.setProperty',{'name':'Box1','prop':'material','value':'copper'})
    assert not any('material' in e for e in import_errors(s.design))
    dispatch(s,'modeler.selectMode',{'mode':'point'})


def test_viewport_events_and_snap_logic():
    node=shutil.which('node')
    if not node:pytest.skip('Node needed for isolated viewport logic checks')
    subprocess.run([node,str(Path(__file__).with_name('viewport_172.cjs'))],check=True)
