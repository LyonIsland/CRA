"""Read only the published instruction images; keep scene setup separate.

No LDraw/recipe parser, page-to-instance map or target poses enter the policy.
This is an application boundary, not an OS sandbox for arbitrary policy code.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image

KIND = 'piper_camera_manual_task'
MAX_PAGES = 64


def task_document(path):
    path = Path(path).resolve()
    task = json.loads(path.read_text(encoding='utf-8'))
    if task.get('schema_version') != '1.0' or task.get('kind') != KIND:
        raise ValueError('Expected a local BRICKLAB camera-only task')
    return path.parent, task


def confined_file(root, name, folder, suffix):
    if not isinstance(name, str) or '\\' in name or ':' in name:
        raise ValueError('Task assets must use relative POSIX paths')
    relative = Path(name)
    target = (root / relative).resolve()
    base = (root / folder).resolve()
    if relative.is_absolute() or not relative.parts or relative.parts[0]!=folder or '..' in relative.parts or root.resolve() not in base.parents or base not in target.parents or target.suffix.lower() != suffix:
        raise ValueError('Task asset is outside its allowed directory')
    if not target.is_file():
        raise ValueError('Missing task asset: ' + name)
    return target


def load_manual(path):
    root, task = task_document(path)
    inputs = task.get('policy_inputs', {})
    if set(inputs) != {'manual', 'page_images', 'sha256'}:
        raise ValueError('Policy task inputs must contain only PDF and page-image references')
    names = inputs['page_images']
    if not isinstance(names, list) or not 1 <= len(names) <= MAX_PAGES or len(set(names)) != len(names):
        raise ValueError('Expected 1 to 64 distinct manual pages; no silent truncation')
    pdf = confined_file(root, inputs['manual'], 'policy', '.pdf')
    assets = [pdf] + [confined_file(root, name, 'policy', '.png') for name in names]
    if set(inputs['sha256']) != {inputs['manual'], *names}:
        raise ValueError('Incomplete instruction integrity manifest')
    for asset, name in zip(assets, [inputs['manual'], *names]):
        if hashlib.sha256(asset.read_bytes()).hexdigest() != inputs['sha256'][name]:
            raise ValueError('Instruction checksum mismatch: ' + name)
    # The model receives image arrays only. PDF metadata and task identifiers
    # are not exposed; all pages are available without oracle step selection.
    pages = []
    for asset in assets[1:]:
        with Image.open(asset) as image:
            pages.append(np.asarray(image.convert('RGB')).copy())
    return pages


def load_scene(path):
    """Environment setup only; never call from policy inference or dataset code."""
    root, task = task_document(path)
    scene = confined_file(root, task['environment']['spec'], 'environment', '.json')
    if hashlib.sha256(scene.read_bytes()).hexdigest() != task['environment']['sha256']:
        raise ValueError('Environment specification checksum mismatch')
    value = json.loads(scene.read_text(encoding='utf-8'))
    if set(value) != {'kind', 'parts', 'baseplate_studs'} or value['kind'] != 'randomized_inventory_v1':
        raise ValueError('Scene setup must be an inventory, with no target or spawn poses')
    if not isinstance(value['parts'], list) or not 1 <= len(value['parts']) <= 64:
        raise ValueError('Local workcell supports 1 to 64 loose parts')
    return value
