"""Sequential frozen-policy physical evaluation; every attempted seed is counted.

This supervisor consumes evaluator outputs only after an episode ends. It never
passes them to the controller or chooses an action/retry from them.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', type=Path, default=ROOT/'outputs/camera_grasp/single-task/task.json')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seeds', type=int, nargs='+', required=True)
    parser.add_argument('--frames', type=int, default=6500)
    parser.add_argument('--timeout', type=float, default=1200)
    parser.add_argument('--negative-open', action='store_true')
    args = parser.parse_args()
    if len(set(args.seeds)) != len(args.seeds):
        parser.error('Seeds must be unique; repeated layouts are not independent tests')
    if not args.task.is_file():parser.error('Prepare a BRICKLAB task first')
    task=json.loads(args.task.read_text(encoding='utf-8'))
    if task.get('part_count')!=1:parser.error('This baseline evaluation requires a single-part task')
    if args.frames<1 or args.timeout<=0:parser.error('Frame and time limits must be positive')
    args.out=args.out.resolve();args.out.mkdir(parents=True,exist_ok=False)
    sources={name:hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest()
             for name in ('camera_grasp_policy.py','camera_grasp_runtime.py','camera_runtime.py','workbench.py')}
    report={'planned_seeds':args.seeds,'sources':sources,'negative_open':args.negative_open,
            'scope':'single upright brick; randomized XY/yaw/material; simulation only',
            'task_title':task.get('title'),'task_source_sha256':task.get('source_sha256'),
            'runs':[],'complete':False}
    write(args.out/'summary.json',report)
    for seed in args.seeds:
        if (args.out/'STOP').exists():break
        for name,digest in sources.items():
            if hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest()!=digest:
                raise RuntimeError('Source changed during frozen evaluation: '+name)
        run=args.out/str(seed)
        command=[sys.executable,str(ROOT/'scripts/workbench.py'),'--task','camera-only',
                 '--camera-mode','grasp','--grasp-flat','--headless','--camera-task',str(args.task.resolve()),
                 '--camera-output',str(run),'--seed',str(seed),'--frames',str(args.frames)]
        if args.negative_open:command.append('--grasp-negative-open')
        with (args.out/f'{seed}.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            started=time.monotonic();stop_at=None;interrupted=False
            while process.poll() is None:
                if (args.out/'STOP').exists() or time.monotonic()-started>args.timeout:
                    interrupted=True
                    run.mkdir(exist_ok=True);(run/'STOP').touch()
                    if stop_at is None:stop_at=time.monotonic()
                    if time.monotonic()-stop_at>30:process.terminate();process.wait(timeout=30)
                time.sleep(1)
        result=run/'result.json'
        item=json.loads(result.read_text(encoding='utf-8')) if result.is_file() else {
            'seed':seed,'success':False,'failure_reason':'Simulator exited without result'}
        item.update(directory=str(seed),process_exit_code=process.returncode)
        if interrupted or process.returncode!=0:
            item.update(success=False,failure_reason='Episode interrupted or process failed')
        if result.is_file() and item.get('policy_sha256')!=sources['camera_grasp_policy.py']:
            raise RuntimeError('Executed policy differs from frozen source')
        report['runs'].append(item)
        report.update(attempted=len(report['runs']),successes=sum(r['success'] for r in report['runs']))
        report['success_rate']=report['successes']/report['attempted']
        report['complete']=len(report['runs'])==len(args.seeds)
        write(args.out/'summary.json',report)
        print(json.dumps({'seed':seed,'success':item['success'],'completed':report['attempted'],
                          'planned':len(args.seeds)},ensure_ascii=False),flush=True)
    print(str(args.out/'summary.json'),flush=True)


if __name__=='__main__':main()
