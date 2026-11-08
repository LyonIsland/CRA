"""Code/data boundary checks, not a heap-to-assembly success rate."""
import ast,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
checked=[]
for name in ['clutter_perception.py','clutter_face_model.py','clutter_extract.py','clutter_normalize.py']:
    tree=ast.parse((ROOT/'scripts'/name).read_text(encoding='utf-8'))
    forbidden={'get_world_pose','set_world_pose','GetPrimAtPath','set_joint_positions'}
    assert not any(isinstance(n,ast.Attribute) and n.attr in forbidden for n in ast.walk(tree)),name
    checked.append(name)
tree=ast.parse((ROOT/'scripts/rotary_regripper.py').read_text(encoding='utf-8'))
runtime=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='RotaryRegripper')
assert not any(isinstance(n,ast.Attribute) and n.attr=='set_world_pose' for n in ast.walk(runtime))
fixture=ROOT/'outputs/clutter/fixture-test.json'
result={'controller_and_RGB_modules_no_body_pose_access':checked,
    'regripper_runtime_commands_fixture_joints_only':True,'physical_heap_to_assembly_tested_by_this_script':False}
if fixture.exists():
    proof=json.loads(fixture.read_text());assert proof['passed'] and proof['bilateral_contact_steps']>100
    assert not proof['brick_attachment_used'] and proof['brick_pose_writes_during_test_motion']==0
    result['separate_fixture_only_physics_test_passed']=True
print(json.dumps(result,indent=2))
