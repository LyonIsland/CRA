"""Audit saved real PhysX concept-build trials, separately from planner tests."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
seeds=[int(s) for s in sys.argv[1:]] or [4200]
trials=[]
for seed in seeds:
    report=json.loads((ROOT/f'outputs/live_assembly/run_{seed}.json').read_text())
    assert report['status']=='complete' and report['concept_build_completed']
    assert report['physical_assembly_completed'] is False
    assert report['completed_steps']==['S1','S2','S3','S4','S5','S6']
    assert report['body_pose_writes_after_reset']==0
    assert report['broken_connections']==[]
    assert report['joint_count']==9
    assert len(report['trace'])==6 and len(report['connectors'])==6
    assert all(not t['grasp_attachment_used'] for t in report['trace'])
    assert all(t['evidence']['verification_source']=='simulated_connector_surrogate' for t in report['trace'])
    final=report['final_parts_evaluation']
    assert len(final)==6
    assert all(p['goal_error_m']<.0035 and p['peak_height_m']>.055 and p['bilateral_lift_steps']>=5 for p in final)
    assert all(p.get('tilt_deg',0)<6 and p.get('speed_m_s',0)<.01 for p in final)
    latched={c['color']:c['engaged_position_m'] for c in report['connectors']}
    import numpy as np
    assert all(np.linalg.norm(np.array(p['position_m'])-latched[p['color']])<.0005 for p in final)
    expected=[{'fixture':8},{'fixture':8},{'fixture':8},{'red':4,'blue':4},{'blue':4,'green':4},{'yellow':4,'orange':4}]
    assert [c['support_colors'] for c in report['connectors']]==expected
    assert all(abs((c['engaged_yaw_deg']+90)%180-90)<=6 for c in report['connectors'])
    if report['random_yaw']:
        colors=['red','blue','green','yellow','orange','purple']
        angles=[report['layout_evaluation'][c]['yaw_deg'] for c in colors]
        assert sum(abs((a+45)%90-45)>5 for a in angles)>=4
        assert len({round(a,1) for a in angles})==6
        assert sum(abs(t['grasp_yaw_from_RGB_deg'])>5 for t in report['trace'])>=4
    trials.append({'seed':seed,'steps':6,'max_final_goal_error_mm':max(p['goal_error_m'] for p in final)*1000,
        'joint_count':report['joint_count'],'random_yaw':report['random_yaw'],
        'source_yaws_deg':angles if report['random_yaw'] else [0.]*6})
result={'physics':'Isaac Sim / PhysX','concept_build_trials':trials,
    'source_pose':'current wrist RGB','manual':'structured recipe paired with illustrated PDF',
    'connection_model':'contact and stud-grid gated fixed-joint approximation',
    'collision_proxy_end_clearance_mm':1.5,
    'no_grasp_attachments':True,'no_body_teleport_after_reset':True,
    'physical_snapfit_validated':False,'real_hardware_validated':False,
    'scope':'Separated upright 2x4 bricks with random planar yaw in the admitted workspace; not stacked clutter or arbitrary PDF understanding'}
(ROOT/'outputs/live_assembly/acceptance.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
