"""Audit actual heap trials; prefix commissioning and full builds stay separate."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];seed=int(sys.argv[1]) if len(sys.argv)>1 else 5200
r=json.loads((ROOT/f'outputs/clutter/run_{seed}.json').read_text())
scene=r['evaluation_only_scene'];assert scene['part_count']==8
assert scene['down_count']>=1 and scene['side_or_tilted_count']>=1
assert scene['elevated_piece_count']>=1 and scene['overlapping_xy_aabb_pairs']
assert r['trained_face_model_used'] and r['body_pose_writes_after_reset']==0 and not r['grasp_attachment_used']
assert len(r['normalized_colors'])>=1
for e in r['normalization_evidence']:
    assert e['face_decision_source']=='RGB classifier only' and e['evaluation_only_up_z']>.85
    positives=[p for p in e['upright_visual_checks'] if p['upright']]
    assert len(positives)>=2 and all(p['upright_score']>=.98 for p in positives)
for color in r['normalized_colors']:
    metric=r['physics_evaluation'][color]
    assert metric['peak_height_m']>.055 and metric['bilateral_lift_steps']>=5
    proof=next(e for e in r['extraction_evidence'] if e['color']==color)
    assert proof['evaluation_only_settled_up_z']>.98 and not proof['attachment_used']
complete=r['heap_to_assembly_completed']
if complete:
    assert len(r['normalized_colors'])==6 and len(r['completed_steps'])==6
    assert r['joint_count']==9 and r['broken_connections']==[]
    full=json.loads((ROOT/f'outputs/live_assembly/run_{seed}.json').read_text())
    assert all(p['goal_error_m']<.0035 and p['tilt_deg']<6 for p in full['final_parts_evaluation'])
out={'seed':seed,'real_heap_drop':True,'initial_down':scene['down_count'],
    'initial_side_or_tilted':scene['side_or_tilted_count'],'initial_elevated':scene['elevated_piece_count'],
    'physically_extracted_and_normalized':r['normalized_colors'],
    'RGB_face_verification_trained':True,'loose_piece_pose_writes_during_motion':0,
    'brick_grasp_attachments':False,'manual_steps_completed':len(r['completed_steps']),
    'heap_to_assembly_completed':complete,'physical_snapfit_validated':False,
    'scope':'one controlled eight-part heap; not arbitrary dense clutter or hardware validation'}
name='acceptance.json' if complete else 'normalization-prefix.json'
(ROOT/'outputs/clutter'/name).write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
