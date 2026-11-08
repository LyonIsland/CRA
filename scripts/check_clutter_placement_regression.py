"""Known physical placement failure: evaluate released RGB localization only."""
import json
import numpy as np
from assembly_agent import ROOT
from wrist_vision import CONFIG
from clutter_perception import released_table_piece

CONFIG['resolution']=[640,480]
data=np.load(ROOT/'outputs/clutter/orange-placement-regression.npz')
fit=released_table_piece(data['rgb'],data['camera_pose'],'orange',[.19,-.25])
assert fit is not None
error=float(np.linalg.norm(np.array(fit['position_m'])-data['truth_evaluation_only']))
assert error<.002
assert released_table_piece(np.zeros_like(data['rgb']),data['camera_pose'],'orange',[.19,-.25]) is None
report={'scope':'one recorded physical failure image; localization regression, not a correction-motion success rate',
    'RGB_localization_error_m':error,'blank_image_rejected':True,'fit':fit,'physical_regrasp_tested':False}
(ROOT/'outputs/clutter/placement-regression.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
