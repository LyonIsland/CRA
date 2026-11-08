"""Acceptance checks for vision results and privileged-input exclusion."""
import hashlib,json
from types import SimpleNamespace
from pathlib import Path
import numpy as np
import torch
from wrist_vision import VisualController
from vision_model import Localizer

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/vision'
evaluation=json.loads((OUT/'evaluation.json').read_text())
episodes=evaluation['episodes']
assert len(episodes)>=8 and all(r['success'] for r in episodes)
assert not evaluation['runtime_object_ground_truth_used']
training=json.loads((OUT/'training.json').read_text())
assert training['device']=='cuda' and training['validation_mean_pixel_error']<1.5
# Encoder/goal observations must be invariant to any simulator object state.
fake=SimpleNamespace(phase=0,steps=1,tcp=np.array([.32,-.07,.08]),target=np.array([.32,-.07,.08]),
    names=[f'joint{i}' for i in range(1,9)],robot=SimpleNamespace(
        get_joint_positions=lambda:np.zeros(8),get_joint_velocities=lambda:np.zeros(8)))
c=VisualController.__new__(VisualController);c.task=fake
c.source=np.array([.32,-.07,.0048]);c.goal=np.array([.32,.08,.0048])
for phase in range(8):
    fake.phase=phase
    fake.object=np.zeros(3);fake.source=np.zeros(3);a=c.observation()
    fake.object=np.full(3,100.);fake.source=np.full(3,100.);b=c.observation()
    assert np.array_equal(a,b) and len(a)==45
torch.set_num_threads(2)
model=Localizer();model.load_state_dict(torch.load(OUT/'localizer.pt',map_location='cpu',weights_only=True));model.eval()
with torch.no_grad():
    blank=[model(torch.full((1,3,120,160),v)).sigmoid().max().item() for v in [0.,.5,1.]]
assert max(blank)<.5
report={'episodes':len(episodes),'successes':sum(r['success'] for r in episodes),
    'initial_visual_error_mean_mm':float(np.mean([r['initial_visual_xy_error_m'] for r in episodes])*1000),
    'placement_error_mean_mm':float(np.mean([r['goal_error_m'] for r in episodes])*1000),
    'placement_error_max_mm':max(r['goal_error_m'] for r in episodes)*1000,
    'validation_pixel_error':training['validation_mean_pixel_error'],
    'all_phases_privileged_input_invariance_passed':True,
    'blank_image_rejection_passed':True,'blank_image_peak_confidences':blank,
    'model_sha256':hashlib.sha256((OUT/'localizer.pt').read_bytes()).hexdigest(),
    'real_rgb_camera_calibrated':False,'real_robot_validated':False}
(OUT/'acceptance.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
