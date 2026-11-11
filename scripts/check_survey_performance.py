"""Compare optimized fitting to the committed RGB baseline on saved real images."""
import json,time,types,subprocess
from pathlib import Path
import numpy as np
from PIL import Image
from wrist_vision import CONFIG,ROOT
import clutter_perception as current
from survey_schedule import order_viewpoints,route_length

CONFIG['resolution']=[640,480]
legacy=types.ModuleType('legacy_clutter_perception')
source=subprocess.check_output(['git','show','HEAD:scripts/clutter_perception.py'],cwd=ROOT).decode('utf-8')
exec(compile(source,'committed_clutter_perception.py','exec'),legacy.__dict__)
folder=ROOT/'outputs/clutter_human';reports=[]
for name in ['views_1974597852_0.json','views_1974597852_6.json']:
    manifest=json.loads((folder/name).read_text())
    views=[current.observe(np.array(Image.open(folder/v['rgb'])),np.array(v['camera_to_world'])) for v in manifest]
    started=time.perf_counter();before=legacy.reconstruct(views);old_seconds=time.perf_counter()-started
    started=time.perf_counter();after=current.reconstruct(views);new_seconds=time.perf_counter()-started
    assert [p['color'] for p in before]==[p['color'] for p in after]
    differences=[]
    for a,b in zip(before,after):
        delta=float(np.linalg.norm(np.array(a['position_m'])-b['position_m']))
        assert a['face_hypothesis']==b['face_hypothesis'],(name,a['color'],a['face_hypothesis'],b['face_hypothesis'])
        assert delta<.0003,(name,a['color'],delta)
        assert a['safe_candidate']==b['safe_candidate'],(name,a['color'],'candidate changed')
        differences.append(delta)
    reports.append({'manifest':name,'pieces':len(after),'baseline_seconds':old_seconds,'optimized_seconds':new_seconds,
        'speedup':old_seconds/new_seconds,'maximum_position_difference_m':max(differences,default=0.)})
poses=[[.24,-.08,.09],[.30,-.18,.09],[.34,-.10,.09],[.22,-.20,.09],[.28,-.13,.095]]
route,old_distance,new_distance=order_viewpoints([.20,-.04,.11],poses)
assert sorted(map(tuple,route))==sorted(map(tuple,poses)) and new_distance<=old_distance
report={'saved_RGB_regressions':reports,'same_viewpoints':True,'original_route_m':old_distance,'shortened_route_m':new_distance,
    'scope':'offline numerical and route comparison; not new physical success rate'}
(folder/'survey-performance-check.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
