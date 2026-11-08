"""Semantic/surrogate guards; these checks are not a physical assembly trial."""
import ast,json
import numpy as np
from types import SimpleNamespace
from assembly_agent import InstructionAgent,ROOT
from concept_connectors import ConceptConnectors,FIXTURE_ORIGIN

obs={'source':'planning_test_fixture','frame':'robot_base','calibration_id':'fixture_test',
    'fixture':{'registered':True,'confidence':1.,'pose':{'position_m':FIXTURE_ORIGIN.tolist(),'yaw_deg':0}},
    'pieces':[{'track_id':'red_test','catalog_id':'3001','studs_xy':[4,2],'color':'red','confidence':.99,
               'xy_sigma_m':.001,'pose':{'position_m':[.2,-.2,.0048],'yaw_deg':0}}]}
evidence={'step_id':'S1','track_id':'red_test','position_error_m':.001,'yaw_error_deg':1,
    'connections':{'fixture':8},'connection_verified':True,'verification_source':'simulated_connector_surrogate'}
physical=InstructionAgent(allow_test_evidence=True);physical.observe(obs)
physical.next_plan({k:True for k in ['visual_pick','oriented_transport','force_limited_insertion','connection_verification','fixture_registration']})
try:physical.confirm(evidence);raise AssertionError('Physical mode accepted surrogate evidence')
except ValueError:pass
concept=InstructionAgent(allow_test_evidence=True,execution_mode='concept');concept.observe(obs)
concept.next_plan({k:True for k in ['visual_pick','concept_transport','concept_connection_model','placement_verification','fixture_registration']})
assert concept.confirm(evidence) and concept.completed==['S1']
part=SimpleNamespace(get_world_pose=lambda:(FIXTURE_ORIGIN+np.array([.012,.004,.0144]),np.array([1.,0,0,0])),get_linear_velocity=lambda:np.zeros(3))
backend=ConceptConnectors(None,{'red':part},None)
assert backend.try_engage('red',False,20) is None
assert backend.try_engage('red',True,2) is None
assert backend.try_engage('red',True,20) is None  # unsupported layer cannot latch
tree=ast.parse((ROOT/'scripts/live_assembly.py').read_text(encoding='utf-8'))
controller=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='StepController')
assert not any(isinstance(n,ast.Attribute) and n.attr in ['get_world_pose','set_world_pose'] for n in ast.walk(controller))
connector=ast.parse((ROOT/'scripts/concept_connectors.py').read_text(encoding='utf-8'))
assert not any(isinstance(n,ast.Attribute) and n.attr=='set_world_pose' for n in ast.walk(connector))
print(json.dumps({'physical_mode_rejects_surrogate':True,'concept_mode_explicit':True,
    'unsupported_or_uncontacted_parts_cannot_connect':True,'no_pose_teleport_in_connector':True,
    'robot_controller_no_object_pose_access':True,'physical_build_tested':False},indent=2))
