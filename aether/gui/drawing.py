"""DXF import: solved closed faces and visible unsolved reference paths."""
import numpy as np
from ..geometry.dxf import read_dxf
from ..geometry.primitives import ImportedShape, Sketch
from ..geometry.kernel import available
from .naming import unique_name, model_names, suggest_part_from_file


def import_drawing(session, path, name, material, unit, scale):
    d=session.require_design()
    doc=read_dxf(path,unit)
    entities=doc['entities']
    usable=[p for p in entities if len(p.points)>=2]
    if not usable:
        raise ValueError('No supported DXF modelspace geometry found. Check Message Manager and export LINE/ARC/POLYLINE from the source CAD.')
    closed=[p for p in usable if p.closed and len(p.points)>=3 and p.area>0]
    openpaths=[p for p in usable if p not in closed]
    base=unique_name(model_names(d),name) if name else suggest_part_from_file(d,path)
    made=[];kernel=available()
    if closed and kernel:
        shape=ImportedShape(path,name=base,scale_to_m=scale,unit=unit)
        # Do not commit an unreadable face; errors roll the entire import back.
        # The buffer this produces is exactly what the viewport will ask for
        # next, so it is kept rather than discarded and rebuilt.
        from .tessellate import cache_buffer, tessellate_occ
        cache_buffer(shape, tessellate_occ(shape))
        d.add_sheet(base,shape,material);made.append(base)
    elif closed:
        openpaths=usable
        session.messages.add('OCC unavailable: closed DXF outlines are shown as reference paths only. Install the CAD backend to make faces.','warning','import')
    if openpaths:
        paths=[]
        for p in openpaths:
            points=p.points*scale
            if p.closed:points=np.vstack([points,points[0]])
            paths.append(points.tolist())
        nm=unique_name(model_names(d),base+'_Reference' if made else base)
        sh=d.add_sheet(nm,Sketch(paths,nm),material)
        sh.display_color='#ffcc66';made.append(nm)
        session.messages.add(f'{nm}: reference drawing only; open paths have no surface or thickness and are excluded from the EM mesh.','warning','import')
    for warning in doc.get('warnings',[]):session.messages.add(warning,'warning','import')
    allpts=np.vstack([p.points for p in usable])*scale
    info={'format':'dxf','solids':0,'surfaces':len(closed) if kernel else 0,
          'closedOutlines':len(closed),'referencePaths':len(openpaths),'joinedChains':doc.get('joinedChains',0),
          'bbox':[allpts.min(axis=0).tolist(),allpts.max(axis=0).tolist()],
          'appliedUnit':doc['appliedUnit'],'declaredUnit':doc['declaredUnit'],'error':''}
    session.selection=made;session.dirty=True;d.mesh=None
    session.messages.add(f'DXF imported: {len(closed)} closed outline(s), {len(openpaths)} reference path(s), {info["joinedChains"]} joined chain(s), unit {doc["appliedUnit"]}.','info','import')
    return {'ok':True,'name':made[0],'names':made,'info':info}
