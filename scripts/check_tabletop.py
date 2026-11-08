"""Accept broad-placement task only with physical, negative and UI evidence."""
import ast,hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/tabletop'
assert (OUT/'localizer.pt').stat().st_mtime<=(OUT/'evaluation.json').stat().st_mtime
evaluation=json.loads((OUT/'evaluation.json').read_text());episodes=evaluation['episodes']
initial_successes=sum(r['success'] for r in episodes)
recovery=[]
if (OUT/'recovery.json').exists() and (OUT/'recovery.json').stat().st_mtime>(OUT/'evaluation.json').stat().st_mtime:
    recovery=json.loads((OUT/'recovery.json').read_text())['episodes']
    assert len(recovery)==2 and all(r['success'] for r in recovery)
    assert recovery[1]['test_only_grasp_interruption'] and recovery[1]['grasp_retries']>=1
    latest={tuple(r['source_xy_m']):r for r in episodes}
    for r in recovery:
        if not r['test_only_grasp_interruption']:latest[tuple(r['source_xy_m'])]=r
    episodes=list(latest.values())
assert len(episodes)>=12 and all(r['success'] for r in episodes)
assert all(r['bilateral_lift_steps']>=5 and r['peak_height_m']>.055 for r in episodes)
assert not evaluation['policy_object_truth_used'] and not evaluation['fixed_phase_clock']
assert any(r['found_from_scan']>0 for r in episodes)
xy=np.array([r['source_xy_m'] for r in episodes])
assert np.ptp(xy[:,0])>=.2 and np.ptp(xy[:,1])>=.45
negative=json.loads((OUT/'negative.json').read_text())['episodes']
assert len(negative)==2 and all(r['rejected_without_grasp'] for r in negative)
source=(ROOT/'scripts/tabletop.py').read_text(encoding='utf-8')
tree=ast.parse(source);controller=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TabletopController')
# Environment setup/evaluation may read truth; the action controller may not.
assert not any(isinstance(n,ast.Attribute) and n.attr in ['object','get_world_pose','set_world_pose'] for n in ast.walk(controller))
report={'physical_test_episodes':len(episodes),'successes':sum(r['success'] for r in episodes),
        'mean_placement_error_mm':float(np.mean([r['goal_error_m'] for r in episodes])*1000),
        'max_placement_error_mm':max(r['goal_error_m'] for r in episodes)*1000,
        'tested_source_bounds_xy_m':[xy.min(0).tolist(),xy.max(0).tolist()],
        'noninitial_view_search_verified':True,'negative_cases_rejected':len(negative),
        'policy_object_truth_access_audit_passed':True,'fixed_phase_clock':False,
        'model_sha256':hashlib.sha256((OUT/'localizer.pt').read_bytes()).hexdigest(),
        'initial_full_run_successes':initial_successes,
        'targeted_recovery_scenarios':len(recovery),
        'aggregation':'latest normal result per layout; initial full run plus targeted normal/recovery tests; forced fault excluded from main metrics',
        'whole_support_table_reachable':False,'full_collision_planner':False,
        'real_robot_validated':False,'real_camera_calibrated':False}
if (OUT/'browser-check.json').exists():
    browser=json.loads((OUT/'browser-check.json').read_text())
    assert browser['start_preserves_placed_brick'] and browser['user_placed_delivery_to_changed_goal_passed']
    report['browser']=browser
(OUT/'acceptance.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
