"""Report component evidence without claiming end-to-end physical assembly."""
import ast,json
from pathlib import Path
import numpy as np
from assembly_agent import ROOT,InstructionAgent

out=ROOT/'outputs/assembly'
planner=json.loads((out/'planner-check.json').read_text())
scan=json.loads((out/'rgb-scan-check.json').read_text())
assert planner['all_passed'] and planner['randomized_layout_planner_trials']==100
expected={'red','blue','green','yellow','orange','purple'}
plans=[]
for trial in scan['trials']:
    assert set(trial['observed_colors'])==expected
    assert trial['visual_tracks']==6 and trial['scene_piece_count']==8 and trial['distractor_count']==2
    assert trial['mean_detection_error_m']<.004
    observation=json.loads((out/f'observation_{trial["seed"]}.json').read_text())
    agent=InstructionAgent();agent.observe(observation);plans.append(agent.next_plan({}))
    assert len(agent.conditional_overview()['steps'])==6 and all(s['selected_track_id'] for s in agent.conditional_overview()['steps'])
    assert not agent.completed
    assert plans[-1]['status']=='blocked_execution'
assert len(plans)>=2 and plans[0]['target_pose']==plans[1]['target_pose']
assert plans[0]['source_pose_observed']!=plans[1]['source_pose_observed']
tree=ast.parse((ROOT/'scripts/assembly_perception.py').read_text(encoding='utf-8'))
assert not any(isinstance(n,ast.Attribute) and n.attr in ['get_world_pose','GetPrimAtPath'] for n in ast.walk(tree))
report={'manual_pdf':str(ROOT/'assets/manuals/step_wall6/manual.pdf'),'manual_pages':8,
    'recipe_steps':6,'planner_fixture_trials':100,'planner_tests_are_not_physical_trials':True,
    'actual_RGB_scanned_layouts':len(scan['trials']),'required_parts_found_each_layout':6,
    'physical_parts_each_layout':8,'distractors_each_layout':2,
    'mean_detection_error_mm_per_layout':[r['mean_detection_error_m']*1000 for r in scan['trials']],
    'no_source_positions_in_manual':True,'perception_simulator_pose_access_audit_passed':True,
    'instruction_conditioned_piece_selection_verified':True,'full_physical_assembly_completed':False,
    'blocked_by':['registered and clamped baseplate','multi-part grasp/orientation skill adapter',
                  'validated snap-fit physics','force-limited insertion and connection verification'],
    'bricksim_reference':'https://github.com/intelligent-control-lab/BrickSim',
    'bricksim_platform_requirement':'x86-64 Linux; not installed or validated in this Windows project'}
prefixes=[r['pick_prefix_test'] for r in scan['trials'] if 'pick_prefix_test' in r]
if prefixes:
    report['S1_pick_prefix_tests']=prefixes
    report['S1_pick_prefix_successes']=sum(r['success'] for r in prefixes)
if (out/'browser-check.json').exists():report['browser']=json.loads((out/'browser-check.json').read_text())
(out/'status.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
