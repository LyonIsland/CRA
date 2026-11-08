"""Planner tests using declared test fixtures, NOT physical success trials."""
import copy,json
from pathlib import Path
import numpy as np
from assembly_agent import InstructionAgent,ROOT,validate_recipe

CAPS={name:True for name in ['visual_pick','oriented_transport','force_limited_insertion','connection_verification','fixture_registration']}
out=ROOT/'outputs/assembly';out.mkdir(exist_ok=True)
demo=[]
for seed in range(100):
    agent=InstructionAgent(allow_test_evidence=True);rng=np.random.default_rng(seed)
    pieces=[]
    for i,b in enumerate(agent.recipe['bom']):
        pieces.append({'track_id':f'track_{seed}_{i}','catalog_id':b['catalog_id'],'studs_xy':b['studs_xy'],
            'color':b['color'],'confidence':.99,'xy_sigma_m':.001,'region':'loose',
            'pose':{'position_m':[float(rng.uniform(.15,.36)),float(rng.uniform(-.25,.25)),.0048],
                    'yaw_deg':float(rng.uniform(-180,180))}})
    # Wrong brick shape and a low-confidence duplicate cannot satisfy a step.
    pieces.append({**pieces[0],'track_id':'wrong_shape','catalog_id':'3003','studs_xy':[2,2]})
    pieces.append({**pieces[0],'track_id':'uncertain_duplicate','confidence':.6})
    rng.shuffle(pieces)
    observation={'source':'planning_test_fixture','frame':'robot_base','calibration_id':'test_fixture',
        'fixture':{'registered':True,'confidence':1.,'pose':{'position_m':[.23,.08,0.],'yaw_deg':0}},'pieces':pieces}
    agent.observe(observation)
    overview=agent.conditional_overview()
    assert len(overview['steps'])==6 and all(s['status']=='conditional_plan' for s in overview['steps'])
    assert not agent.completed
    for step in agent.recipe['steps']:
        plan=agent.next_plan(CAPS)
        assert plan['status']=='ready' and plan['selected_part']==step['part']
        assert plan['selected_track_id'] not in ['wrong_shape','uncertain_duplicate']
        before=list(agent.completed)
        evidence={'step_id':step['id'],'track_id':plan['selected_track_id'],'position_error_m':.0005,
            'yaw_error_deg':.5,'connections':{},'connection_verified':False,'verification_source':'planning_test_fixture'}
        assert not agent.confirm(evidence) and agent.completed==before
        evidence.update(connections={c['support_step']:c['stud_count'] for c in step['connections']},connection_verified=True)
        assert agent.confirm(evidence)
        if seed==0:demo.append(plan)
    assert agent.next_plan(CAPS)['status']=='complete'

agent=InstructionAgent(allow_test_evidence=True);agent.observe(observation)
blocked=agent.next_plan({})
assert blocked['status']=='blocked_execution'
try:agent.confirm(evidence);raise AssertionError('Unready executor advanced instruction')
except ValueError:pass
bad=copy.deepcopy(agent.recipe);bad['steps'][1]['anchor_stud']=bad['steps'][0]['anchor_stud']
try:validate_recipe(bad);raise AssertionError('Overlapping recipe accepted')
except ValueError:pass
bad=copy.deepcopy(agent.recipe);bad['steps'][3]['connections'][0]['stud_count']=3
try:validate_recipe(bad);raise AssertionError('Incorrect connection accepted')
except ValueError:pass
bad=copy.deepcopy(agent.recipe);bad['source_position']=[0,0,0]
try:validate_recipe(bad);raise AssertionError('Source coordinates leaked into manual')
except ValueError:pass
agent=InstructionAgent(allow_test_evidence=True)
empty={**observation,'pieces':[]};agent.observe(empty);assert agent.next_plan(CAPS)['status']=='need_piece'
unregistered={**observation,'fixture':{'registered':False}}
agent.observe(unregistered);assert agent.next_plan(CAPS)['status']=='blocked_execution'
try:InstructionAgent().observe(observation);raise AssertionError('Production accepted test fixture')
except ValueError:pass
result={'randomized_layout_planner_trials':100,'all_passed':True,'steps_per_trial':6,
        'no_connection_evidence_no_advance':True,'missing_skill_blocks_execution':True,
        'unregistered_fixture_blocks_execution':True,'production_rejects_test_observations':True,
        'physical_assembly_tested':False,'visual_detection_tested_by_this_script':False,
        'note':'Synthetic observation/connection fixtures test planning logic only; not robot, vision or snap-fit success rates'}
(out/'planner-check.json').write_text(json.dumps(result,indent=2))
(out/'example-plan.json').write_text(json.dumps({'source':'planning_test_fixture','plans':demo},indent=2))
print(json.dumps(result,indent=2))
