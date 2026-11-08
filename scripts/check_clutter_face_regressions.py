"""Development regressions from recorded physical fixture trials, not a test success rate."""
import json
from collections import defaultdict
import numpy as np
from PIL import Image
from assembly_agent import ROOT
from kinematics import PiperKinematics
from tabletop import solve_checked,SETTINGS
from wrist_vision import camera_pose,CONFIG
from clutter_face_model import UprightVerifier

CONFIG['resolution']=[640,480]
kin=PiperKinematics(ROOT/'generated/piper_basic.urdf')
pose=camera_pose(kin,solve_checked(kin,SETTINGS['home']))
verifier=UprightVerifier(ROOT/'outputs/clutter_face/upright.pt')
trial=json.loads((ROOT/'outputs/clutter/red-verifier-miss.json').read_text())
orientations=[(0,0),(90,0),(180,0),(-90,0),(0,90),(0,-90)]
counts=defaultdict(int);rows=[]
for entry in trial['evaluation_only_face_checks']:
    color=entry['color'];index=counts[color];counts[color]+=1
    check=entry['check'];actuator=orientations.index(tuple(check['actuator_orientation']))
    filename=ROOT/f'outputs/clutter_face/physical-regression-images/inspect_{trial["seed"]}_{color}_{actuator}_{index}.png'
    up=entry['evaluation_only_normal_world'][2]
    if .85<up<.95 or not filename.exists():continue
    # Approximate the recorded fixed inspection camera by its calibrated home.
    # These are known development failures and must not enter held-out claims.
    result=verifier.predict(np.asarray(Image.open(filename).convert('RGB')),pose,color)
    rows.append({'image':filename.name,'evaluation_only_up_z':up,'expected_upright':up>=.95,**result})
report={'scope':'known physical-trial development regressions; not independent generalization evidence',
    'camera':'nominal encoder-calibrated inspection home approximation',
    'false_upright':sum(r['upright'] and not r['expected_upright'] for r in rows),
    'missed_upright':sum(not r['upright'] and r['expected_upright'] for r in rows),'checks':rows}
(ROOT/'outputs/clutter_face/physical-regressions.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
if report['false_upright'] or report['missed_upright']:raise SystemExit(1)
