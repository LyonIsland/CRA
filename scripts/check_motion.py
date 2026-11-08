"""Compare measured physical TCP motion before/after the damping correction."""
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'

def metrics(path):
    trace=np.load(path)
    transfer=trace[trace[:,1]==4,2:5]
    delta=np.diff(transfer,axis=0)
    return {
        'max_tcp_step_mm':float(np.linalg.norm(delta,axis=1).max()*1000),
        'rms_tcp_second_difference_mm':float(np.sqrt(np.mean(np.sum(np.diff(delta,axis=0)**2,axis=1)))*1000),
        'x_direction_reversals_over_10um':int(((delta[1:,0]*delta[:-1,0]<0)&
            (abs(delta[1:,0])>1e-5)&(abs(delta[:-1,0])>1e-5)).sum()),
    }

old=metrics(OUT/'history/before-damping-fix/learned_demo_trace_1000.npy')
new=metrics(OUT/'policy_evaluation_trace_1000.npy')
results=json.loads((OUT/'policy_evaluation.json').read_text())
assert len(results)==20 and all(r['success'] for r in results)
assert all(r['arm_drive']['damping']==50 for r in results)
assert new['rms_tcp_second_difference_mm']<old['rms_tcp_second_difference_mm']*.2
report={'phase':'transfer','control_interval_s':.02,'before':old,'after':new,
        'new_policy_successes':sum(r['success'] for r in results),
        'new_policy_episodes':len(results),'display_interpolation_delay_ms':80}
(OUT/'motion-check.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
