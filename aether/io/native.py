"""Portable, versioned JSON project archive. Never uses pickle or eval.

Only explicitly supported model classes are decoded. Derived meshes/results
are excluded; imported CAD bytes travel inside the single .aether file.
"""
from __future__ import annotations
import copy
import hashlib
import importlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
import numpy as np

_MODULES = ('aether.model', 'aether.geometry.primitives',
            'aether.geometry.select', 'aether.core.materials', 'aether.core.config')

def _registry():
    result = {}
    for name in _MODULES:
        mod = importlib.import_module(name)
        for key, cls in vars(mod).items():
            if isinstance(cls, type) and cls.__module__ == name:
                result[name + '.' + key] = cls
    return result


def encode(value):
    registry, objects, seen = _registry(), [], {}
    def pack(v):
        if v is None or isinstance(v, (str, bool, int, float)):
            return v
        if isinstance(v, np.generic):
            return pack(v.item())
        if isinstance(v, complex):
            return {'complex': [v.real, v.imag]}
        if isinstance(v, np.ndarray):
            if v.dtype.kind not in 'biufc':
                raise ValueError('unsupported array dtype')
            return {'array': pack(v.tolist()), 'dtype': str(v.dtype)}
        if isinstance(v, (list, tuple)):
            return {'tuple' if isinstance(v, tuple) else 'list': [pack(x) for x in v]}
        if isinstance(v, dict):
            return {'dict': [[pack(k), pack(x)] for k, x in v.items()]}
        key = type(v).__module__ + '.' + type(v).__name__
        if key not in registry:
            raise ValueError('Native save cannot serialize ' + key +
                             '. Replace custom callable selectors with built-in selectors.')
        if id(v) in seen:
            return {'ref': seen[id(v)]}
        idx = len(objects)
        seen[id(v)] = idx
        objects.append(None)
        objects[idx] = {'type': key, 'state': pack(vars(v))}
        return {'ref': idx}
    root = pack(value)
    return {'root': root, 'objects': objects}


def decode(data):
    registry = _registry()
    entries = data['objects']
    if len(entries) > 200000:
        raise ValueError('project object limit exceeded')
    instances = []
    for entry in entries:
        cls = registry.get(entry['type'])
        if cls is None:
            raise ValueError('unsupported model class: ' + entry['type'])
        instances.append(object.__new__(cls))
    def unpack(v):
        if not isinstance(v, dict):
            return v
        if 'ref' in v:
            idx = v['ref']
            if not isinstance(idx, int) or not 0 <= idx < len(instances):
                raise ValueError('invalid model reference')
            return instances[idx]
        if 'complex' in v:
            return complex(*v['complex'])
        if 'array' in v:
            dt = np.dtype(v['dtype'])
            if dt.kind not in 'biufc':
                raise ValueError('unsupported array dtype')
            return np.asarray(unpack(v['array']), dtype=dt)
        if 'list' in v:
            return [unpack(x) for x in v['list']]
        if 'tuple' in v:
            return tuple(unpack(x) for x in v['tuple'])
        if 'dict' in v:
            return {unpack(k): unpack(x) for k, x in v['dict']}
        raise ValueError('invalid native value')
    for obj, entry in zip(instances, entries):
        obj.__dict__.update(unpack(entry['state']))
    return unpack(data['root'])


def _shapes(snapshot):
    from .aedt.writer import _walk_shapes
    from ..geometry.primitives import ImportedShape
    for obj in snapshot['solids'] + snapshot['sheets']:
        for shape in _walk_shapes(obj.shape):
            if isinstance(shape, ImportedShape):
                yield shape


def save_project(path, project, active=''):
    """Stage and atomically replace; any serialization/CAD failure keeps old file."""
    path = os.path.abspath(os.path.expanduser(path))
    snapshots = [d.snapshot() for d in project.designs]
    assets = {}
    for snap in snapshots:
        for shape in _shapes(snap):
            source = Path(shape.path)
            if not source.is_file():
                raise FileNotFoundError('Cannot save missing CAD source: ' + str(source))
            content = source.read_bytes()
            member = 'cad/' + hashlib.sha256(content).hexdigest() + source.suffix.lower()
            assets[member] = content
            shape.path = member
            shape._embedded_rel = ''
    payload = {'format': 'AetherProject', 'version': 1, 'name': project.name,
               'active': active, 'model': encode(snapshots)}
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
    fd, stage = tempfile.mkstemp(prefix='.aether-', suffix='.tmp', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w+b') as stream:
            with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('project.json', raw)
                for member, content in assets.items():
                    z.writestr(member, content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, path)
    finally:
        if os.path.exists(stage):
            os.unlink(stage)
    return path


def load_project(path):
    from ..model import Project
    asset_dir = tempfile.TemporaryDirectory(prefix='aether-cad-')
    try:
        with zipfile.ZipFile(path) as z:
            if sum(x.file_size for x in z.infolist()) > 1024**3:
                raise ValueError('uncompressed project exceeds 1 GiB')
            if z.getinfo('project.json').file_size > 64 * 1024**2:
                raise ValueError('project metadata exceeds 64 MiB')
            data = json.loads(z.read('project.json'))
            if data.get('format') != 'AetherProject' or data.get('version') != 1:
                raise ValueError('unsupported Aether project version')
            snapshots = decode(data['model'])
            project = Project(data['name'])
            for snap in snapshots:
                for shape in _shapes(snap):
                    member = shape.path
                    parts = member.split('/')
                    if len(parts) != 2 or parts[0] != 'cad' or '\\' in member or parts[1] in ('', '.', '..'):
                        raise ValueError('invalid CAD asset path')
                    target = Path(asset_dir.name) / parts[1]
                    content = z.read(member)
                    if hashlib.sha256(content).hexdigest() != parts[1].split('.')[0]:
                        raise ValueError('CAD asset checksum mismatch')
                    target.write_bytes(content)
                    shape.path = str(target)
                project.new_design(snap['name']).restore(snap)
            project._native_assets = asset_dir  # retain files while project is alive
            active = data.get('active', '')
            design = next((d for d in project.designs if d.name == active),
                          project.designs[0] if project.designs else None)
            return project, design
    except Exception:
        asset_dir.cleanup()
        raise
