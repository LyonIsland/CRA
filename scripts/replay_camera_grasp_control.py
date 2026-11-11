"""Paired mechanical replay control, NEVER an online RGB policy benchmark.

Replay successful camera-controller commands verbatim, then replay identical arm
commands while opening the fingers during close/lift/hold. No scene poses are
read or used to create either action sequence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--task',type=Path,default=ROOT/'outputs/camera_grasp/single-task/task.json')
    args=parser.parse_args();result=json.loads((args.source/'result.json').read_text(encoding='utf-8'))
    trace_bytes=(args.source/'trace.json').read_bytes();trace=json.loads(trace_bytes)
    if not result['success'] or result['controller_result']!='finished_unverified':
        raise ValueError('Source must be a completed successful online grasp')
    args.out=args.out.resolve();args.out.mkdir(parents=True,exist_ok=False)
    summary={'kind':'paired_mechanical_replay_not_online_evaluation','source_seed':result['seed'],
             'source_policy_sha256':result['policy_sha256'],'source_trace_sha256':hashlib.sha256(trace_bytes).hexdigest(),
             'intervention':'same arm commands; force gripper open in close/lift/hold','runs':{}}
    for variant in ('original','open'):
        plan=[]
        for item in trace:
            if 'action' not in item:continue
            action=list(item['action']);phase=item['phase'].replace('_','-')
            if variant=='open' and item['phase'] in ('close','lift','hold'):action[-1]=1.
            if plan and plan[-1]['action']==action and plan[-1]['label']==phase:
                plan[-1]['repeat']+=1
            else:plan.append({'action':action,'repeat':1,'label':phase})
        plan_file=args.out/(variant+'-plan.json');plan_file.write_text(json.dumps(plan),encoding='utf-8')
        run=args.out/variant
        command=[sys.executable,str(ROOT/'scripts/workbench.py'),'--task','camera-only','--camera-mode','grasp',
                 '--grasp-flat','--headless','--camera-task',str(args.task.resolve()),'--seed',str(result['seed']),
                 '--grasp-plan',str(plan_file),'--camera-output',str(run),'--frames',str(sum(p['repeat'] for p in plan))]
        with (args.out/(variant+'.log')).open('w',encoding='utf-8') as log:
            process=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=1200,
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        outcome=json.loads((run/'result.json').read_text(encoding='utf-8'))
        if process.returncode!=0:raise RuntimeError('Replay simulator process failed')
        # The raw runtime contract lists allowed sensors; clarify which inputs
        # this diagnostic actually consumes in the separate comparison record.
        outcome.update(control_inputs=['recorded_command_sequence'],online_policy_executed=False,
                       intervention_gripper_open=variant=='open')
        summary['runs'][variant]=outcome
        summary['complete']=len(summary['runs'])==2
        (args.out/'comparison.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps({'variant':variant,'success':outcome['success'],'steps':outcome['steps']}),flush=True)
    summary['supports_physical_closure']=summary['runs']['original']['success'] and not summary['runs']['open']['success']
    (args.out/'comparison.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


if __name__=='__main__':main()
