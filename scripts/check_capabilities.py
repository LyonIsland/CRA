"""Check saved, independently generated task and camera acceptance evidence."""
import json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'outputs'
camera=json.loads((out/'smoke.json').read_text())
evaluation=json.loads((out/'policy_evaluation.json').read_text())
negative=json.loads((out/'negative_open.json').read_text())
training=json.loads((out/'policy.json').read_text())
assert camera['sensor_rgb_passed'] and camera['rgb_temporal_mean_absolute_difference']>.05
assert len(evaluation)==20 and all(r['success'] for r in evaluation)
assert all(r['bilateral_lift_frames']>=5 and r['released'] and r['tcp_clear'] for r in evaluation)
assert len(negative)==3 and all(not r['success'] and r['bilateral_lift_frames']==0 for r in negative)
assert training['device']=='cuda'
result={'physics':'Isaac Sim / PhysX','rgb_live_frames_passed':True,
        'training_method':'staged behavior cloning','training_episodes':training['episodes'],
        'test_episodes':len(evaluation),'successes':sum(r['success'] for r in evaluation),
        'mean_goal_error_mm':float(np.mean([r['goal_error_m'] for r in evaluation])*1000),
        'max_goal_error_mm':max(r['goal_error_m'] for r in evaluation)*1000,
        'negative_controls_rejected':len(negative),
        'xy_randomization_m':.012,'yaw_randomization':False,
        'visual_policy_trained':False,'lego_snap_fit_validated':False,'quest_pro_hardware_validated':False}
if (out/'xr-software-check.json').exists():result['xr_software']=json.loads((out/'xr-software-check.json').read_text())
if (out/'vision/evaluation.json').exists():
    result['wrist_vision']=json.loads((out/'vision/evaluation.json').read_text())
    result['wrist_vision_training']=json.loads((out/'vision/training.json').read_text())
    result['state_baseline_note']='20-episode metrics above use privileged state; wrist RGB evaluated separately'
if (out/'tabletop/acceptance.json').exists():
    acceptance=json.loads((out/'tabletop/acceptance.json').read_text())
    result={'physics':'Isaac Sim / PhysX','active_controller':'wrist_RGB_search_feedback',
            'tabletop_search_pick_place':acceptance,'historical_baselines':result,
            'historical_note':'Local BC and local visual baselines predate imported collision-instance fix; not current collision-model validation'}
if (out/'camera-stream-check.json').exists():result['camera_display']=json.loads((out/'camera-stream-check.json').read_text())
if (out/'assembly/status.json').exists():result['instruction_assembly_prototype']=json.loads((out/'assembly/status.json').read_text())
if (out/'live_assembly/acceptance.json').exists():result['instruction_concept_assembly']=json.loads((out/'live_assembly/acceptance.json').read_text())
(out/'capabilities.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
