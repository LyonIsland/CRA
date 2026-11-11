"""BRICKLAB -> local manual images and randomized camera-only task.

Run in the separate BRICKLAB tools environment. Never imports Isaac or torch.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sys
from bricklab_paths import upstream


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def prepare(source, output, mode='steps', title=None):
    bridge = upstream()
    from input_adapter import adapt_input
    from prepare import _module
    from scene_plan import _asset
    from usd_scene import asset_geometry
    from manual_renderer import render_manual
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import pypdfium2 as pdfium
    from bricklab_task import KIND, MAX_PAGES, load_manual, load_scene

    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Choose a new output directory; existing tasks are immutable')
    if output == source or output in source.parents:
        raise ValueError('Output cannot contain the source model')
    output.mkdir(parents=True)
    inputs = output/'inputs'
    inputs.mkdir()
    saved = inputs/('source'+source.suffix.lower())
    shutil.copyfile(source, saved)
    adapted = adapt_input(saved, output/'evaluation/adapted', manual_mode=mode)
    # Extract the authored model without invoking the upstream organized-supply
    # planner (its Linux workcell/layout is not the local training environment).
    parser = _module('_piper_bricklab_parser', bridge/'studio_bridge/bridge.py')
    model = Path(adapted['prepare_input'])
    if model.suffix.lower()=='.io':
        previous = sys.modules.get('bridge')
        try:
            sys.modules['bridge'] = parser
            unpacker = _module('_piper_bricklab_unpacker', bridge/'studio_bridge/unpack_io.py')
        finally:
            if previous is None:sys.modules.pop('bridge', None)
            else:sys.modules['bridge'] = previous
        model = output/'evaluation/unpacked.ldr'
        unpacker.unpack_io(Path(adapted['prepare_input']), model)
    gt, validation = parser.extract_model(model, bridge/'catalog.json')
    if not validation['valid']:
        raise ValueError('BRICKLAB model validation failed')
    if len(gt['source']['documents'])!=1:
        raise ValueError('Use a self-contained MPD/LDR or Studio IO')
    parser.write_outputs(output/'evaluation/extracted', gt, validation)
    catalog = json.loads((bridge/'catalog.json').read_text(encoding='utf-8'))
    # Register an installed Windows CJK font, without copying system fonts.
    if 'BricklabCJK' not in pdfmetrics.getRegisteredFontNames():
        for path in [Path('C:/Windows/Fonts/msyh.ttc'), Path('C:/Windows/Fonts/simsun.ttc')]:
            if path.is_file():
                try:
                    pdfmetrics.registerFont(TTFont('BricklabCJK', str(path), subfontIndex=0))
                    break
                except Exception:
                    continue
    rendered = render_manual(gt, output/'evaluation/rendered', mode=mode, title=title or adapted['title'],
                             render_png=False, source_label='BRICKLAB / '+adapted['format'],
                             source_sha256=adapted['input_sha256'], instruction_plan=adapted)
    if not 1 <= rendered['page_count'] <= MAX_PAGES:
        raise ValueError('Manual exceeds the 64-page policy limit; split into explicit tasks')
    policy = output/'policy'
    (policy/'pages').mkdir(parents=True)
    shutil.copyfile(rendered['pdf'], policy/'manual.pdf')
    page_names = []
    with pdfium.PdfDocument(str(policy/'manual.pdf')) as document:
        for index in range(len(document)):
            name = f'policy/pages/page-{index+1:03d}.png'
            page = document[index]
            bitmap = page.render(scale=1.5)
            bitmap.to_pil().convert('RGB').save(output/name)
            bitmap.close()
            page.close()
            page_names.append(name)
    shutil.copyfile(rendered['manifest'], output/'evaluation/manual-page-map.json')
    # This inventory contains ONLY nominal geometry and counts. It intentionally
    # drops colors, instance IDs, assembly ordering and all target/spawn poses.
    counts = Counter(part['part_file'] for part in gt['instances'])
    parts = []
    for part_file, count in sorted(counts.items()):
        asset = _asset(part_file, catalog['parts'][part_file])
        geometry = asset_geometry(asset)
        parts.extend([geometry]*count)
    scene = {'kind': 'randomized_inventory_v1', 'parts': parts,
             'baseplate_studs': [20, 20] if adapted['format']=='web_json' else None}
    spec = output/'environment/inventory.json'
    write_json(spec, scene)
    names = ['policy/manual.pdf', *page_names]
    task = {'schema_version': '1.0', 'kind': KIND, 'title': title or adapted['title'],
            'source_sha256': adapted['input_sha256'], 'manual_mode': mode,
            'policy_inputs': {'manual': names[0], 'page_images': page_names,
                              'sha256': {n: hashlib.sha256((output/n).read_bytes()).hexdigest() for n in names}},
            'environment': {'spec': 'environment/inventory.json', 'sha256': hashlib.sha256(spec.read_bytes()).hexdigest()},
            'evaluation_only': {'page_map': 'evaluation/manual-page-map.json',
                                'model': 'evaluation/extracted/ground-truth.json'},
            'part_count': len(parts), 'robot_execution_validated': False,
            'limitations': ['all loose parts share material; color-specific assembly is not evaluated',
                           'nominal hollow geometry; no verified clutch/interference or real-world calibration',
                           'manual page encoding is not a trained instruction-reading capability']}
    task_path = output/'task.json'
    write_json(task_path, task)
    load_manual(task_path)
    load_scene(task_path)
    # Public downloads contain instruction assets ONLY, never evaluation maps.
    shutil.make_archive(str(output/'policy-inputs'), 'zip', policy)
    return {'task': str(task_path), 'pages': len(page_names), 'parts': len(parts),
            'manual': str(policy/'manual.pdf'), 'robot_execution_validated': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['steps', 'structure', 'lego'], default='steps')
    parser.add_argument('--title')
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output, args.mode, args.title), ensure_ascii=False))
