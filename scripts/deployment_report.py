"""Summarize actual acceptance evidence and limitations."""
import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
report=json.loads((ROOT/'outputs/smoke.json').read_text())
source=json.loads((ROOT/'assets/source.json').read_text())
files=['scripts/workbench.py','scripts/prepare_urdf.py','start.ps1',
       'generated/piper_basic.urdf','outputs/workbench.usda','outputs/workbench.png',
       'scripts/pick_place.py','scripts/kinematics.py','scripts/xr_bridge.py',
       'scripts/train_bc.py','web/app.js','web/index.html','outputs/policy.npz',
       'outputs/demonstrations.npz','outputs/policy_evaluation.json','outputs/xr-software-check.json',
       'scripts/wrist_vision.py','scripts/vision_model.py','scripts/train_vision.py','config/wrist_camera.json',
       'scripts/tabletop.py','scripts/check_tabletop.py','config/tabletop.json',
       'scripts/assembly_agent.py','scripts/assembly_perception.py','scripts/assembly_scene.py',
       'assets/manuals/step_wall6/recipe.json','assets/manuals/step_wall6/manual.pdf']
report['limits']=['smoke-scene check; grasp/place is evaluated separately',
                  'solid-bottom brick; no validated snap-fit','robot self-collision disabled']
result={'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'workspace':str(ROOT),'isaacsim_distribution':importlib.metadata.version('isaacsim'),
        'kit_version':(ROOT/'.venv/Lib/site-packages/isaacsim/VERSION').read_text().strip(),
        'piper_commit':source['commit'],'acceptance':report,
        'main_platform':'Isaac Sim / PhysX',
        'gui_launch_command':'powershell -ExecutionPolicy Bypass -File E:\\PiperIsaac\\start.ps1',
        'quest_pro_connected':False,'bricksim_installed':False,
        'linux_installed_by_this_task':False,
        'capabilities':json.loads((ROOT/'outputs/capabilities.json').read_text()),
        'training':json.loads((ROOT/'outputs/policy.json').read_text()),
        'quest_usb_tools_prepared':(ROOT/'tools/platform-tools/adb.exe').exists(),
        'workshop_url':'http://127.0.0.1:8875/',
        'remaining':['actual Quest Pro display, tracking and performance validation',
                     'real LEGO snap-fit / BrickSim integration and physical calibration',
                     'Vulkan path on the current Windows/driver combination',
                     'real wrist camera calibration, visual domain transfer, human body collision and adaptive collaboration'],
        'sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}}
(ROOT/'deployment-status.json').write_text(json.dumps(result,indent=2))
print(json.dumps({k:result[k] for k in ['workspace','isaacsim_distribution','main_platform','quest_pro_connected']},indent=2))
