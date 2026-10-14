"""World frame, complete outlines, topology recovery and annotation regressions."""
from pathlib import Path
import subprocess, shutil
import numpy as np
import pytest
from aether.io.warp.tree import WarpBlock
from aether.io.warp.values import Call
from aether.io.warp.translate import _box_from_topology
from aether.gui.api import dispatch
from aether.gui.state import Session


def topology_box():
    part=WarpBlock('GeometryPart');ops=part.add_block('Operations');op=ops.add_block('Operation')
    op.add_prop('OperationType','SweepFaceAlongNormalFrom');group=op.add_block('NewFaces')
    import itertools
    for axis in range(3):
        for side in (0,1):
            g=group.add_block('Face').add_block('FaceGeometry');v=g.add_block('FcTolVts')
            spans=[2,3,4];g.add_prop('Area',np.prod([spans[i] for i in range(3) if i!=axis]))
            for pair in itertools.product((0,1),repeat=2):
                p=[];j=0
                for i in range(3):
                    if i==axis:p.append(side*spans[i])
                    else:p.append(pair[j]*spans[i]);j+=1
                v.add_prop('TolVt',Call('TolVt',p+[1e-7]))
    return part


def test_verified_rectangular_topology_in_model_units():
    shape=_box_from_topology(topology_box(),'mm')
    assert shape is not None
    lo,hi=shape.bounds()
    assert np.allclose(lo,[0,0,0]) and np.allclose(hi,[.002,.003,.004])


def test_historical_or_inconsistent_topology_is_rejected():
    p=topology_box();p.block('Operations').add_block('Operation').add_prop('OperationType','MoveFaces')
    assert _box_from_topology(p,'mm') is None
    p=topology_box();p.find('FaceGeometry')[0].prop('Area').set(1000)
    assert _box_from_topology(p,'mm') is None


def test_outline_measure_uses_all_segments_for_gap():
    s=Session();s.new_project('Edges')
    square=[[[0,0,0],[1,0,0]],[[1,0,0],[1,1,0]],[[1,1,0],[0,1,0]],[[0,1,0],[0,0,0]]]
    upper=[[[0,1,2],[1,1,2]]]
    dispatch(s,'modeler.select',{'edges':[dict(a=square[0][0],b=square[0][1],length=4,segments=square),dict(a=upper[0][0],b=upper[0][1],length=1,segments=upper)]})
    r=dispatch(s,'modeler.measure')
    assert r['lengths']==[4,1] and r['distance']==pytest.approx(2)
    assert 'angle' not in r


def test_world_frame_outline_and_annotation_logic():
    node=shutil.which('node')
    if not node:pytest.skip('Node unavailable')
    subprocess.run([node,str(Path(__file__).with_name('viewport_173.cjs'))],check=True)


def test_replace_incomplete_primitive_and_undo(tmp_path,monkeypatch):
    from aether.geometry import brep_io
    from aether.geometry.primitives import ImportedShape,Box
    s=Session();s.new_project('Repair')
    dispatch(s,'modeler.draw',{'shape':'box','name':'Box1','params':{'position':[0,0,0],'size':[1,2,3]}})
    issue="Incomplete history for 'Box1': MoveFaces"
    s.design.import_issues=[issue,'Other unresolved boundary']
    p=tmp_path/'final.step';p.write_text('mock CAD')
    monkeypatch.setattr(brep_io,'inspect',lambda *a,**k:dict(error='',solids=1,surfaces=6,bbox=[[0,0,0],[1,2,3]],appliedUnit='m'))
    dispatch(s,'modeler.replaceCad',{'name':'Box1','path':str(p)})
    assert isinstance(s.design.solids[0].shape,ImportedShape)
    assert s.design.import_issues==['Other unresolved boundary']
    dispatch(s,'edit.undo')
    assert isinstance(s.design.solids[0].shape,Box) and issue in s.design.import_issues


def test_complete_outline_from_cylinder_has_whole_rim():
    import json
    from aether.gui.tessellate import tessellate_analytic
    from aether.geometry.primitives import Cylinder
    t=tessellate_analytic(Cylinder([0,0,0],1,2))
    # Produce the real buffers for the JS component builder, not a hand-made ring.
    node=shutil.which('node')
    if not node:pytest.skip('Node unavailable')
    script="""const fs=require('fs'),vm=require('vm'),assert=require('assert');const c={window:{}};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),c);const t=JSON.parse(fs.readFileSync(0,'utf8'));const g=c.buildEdgeGroups(t.faceEdges,t.edgeVerts);assert(g.length>=2);for(const x of g)assert(Math.abs(x.length-2*Math.PI)<.003);"""
    subprocess.run([node,'-e',script,str(Path(__file__).parents[1]/'aether/gui/static/gl.js')],input=json.dumps(t),text=True,check=True)
