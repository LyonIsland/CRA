"""Actual held-brick RGB regression; no simulator motion or success-rate claim."""
import json
import numpy as np
from PIL import Image
from assembly_agent import ROOT
from wrist_vision import CONFIG
from assembly_perception import detect

data=np.load(ROOT/'outputs/clutter/assembly-register-regression.npz');rows=[]
for width in [320,640]:
    rgb=np.asarray(Image.fromarray(data['rgb']).resize((width,width*3//4)))
    CONFIG['resolution']=[width,width*3//4]
    seen=detect(rgb,data['camera_pose'],center_z_m=float(data['center_z_m']),held_color='red')
    target=next(p for p in seen if p['color']=='red');assert target['confidence']>=.85
    assert not detect(np.zeros_like(rgb),data['camera_pose'],center_z_m=float(data['center_z_m']),held_color='red')
    rows.append({'width':width,'position_RGB_m':target['pose']['position_m'],'confidence':target['confidence']})
assert np.linalg.norm(np.array(rows[0]['position_RGB_m'])-rows[1]['position_RGB_m'])<.002
report={'scope':'one actual pre-placement RGB image at two resolutions; not a physical build test',
    'held_red_detected_at_both_resolutions':True,'blank_rejected':True,'results':rows}
(ROOT/'outputs/clutter/assembly-resolution-regression.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
