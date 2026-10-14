from pathlib import Path
import shutil,subprocess
import pytest
from aether.gui.tessellate import _node_table,_display_curve_segments,_cad_edges


def test_spatial_pick_and_vertex_edges():
    node=shutil.which('node')
    if not node:pytest.skip('Node unavailable')
    subprocess.run([node,str(Path(__file__).with_name('viewport_174.cjs'))],check=True)


def test_display_quality_limits(monkeypatch):
    for value,expected in [('bad',48),('2',16),('900',128),('32',32)]:
        monkeypatch.setenv('AETHER_VIEW_CURVE_SEGMENTS',value)
        assert _display_curve_segments()==expected


def test_native_tangent_curves_keep_distinct_identities():
    import numpy as np
    from types import SimpleNamespace
    class Mesh:
        def getElements(self,dim,tag):return [1],[],[[1,2] if tag==10 else [2,3]]
    model=SimpleNamespace(mesh=Mesh(),getBoundary=lambda *a,**k:[(1,10),(1,11)])
    g=SimpleNamespace(model=model)
    edges=_cad_edges(g,[(2,1)],np.array([[0,0,0],[1,0,0],[2,0,0]]),np.array([-1,0,1,2]),[])
    assert [e['id'] for e in edges]==[10,11]
    assert [e['length'] for e in edges]==[1,1]
