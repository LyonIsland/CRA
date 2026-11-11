"""Human-only grasp monitoring; this module is never imported by the policy."""
import json
from pathlib import Path


def progress(report_root,experiment_root):
    root=Path(experiment_root).resolve()
    pointer=json.loads((Path(report_root)/'progress-source.json').read_text(encoding='utf-8'))
    batch=(root/pointer['evaluation']).resolve()
    if root not in batch.parents:raise ValueError('Evaluation path escapes experiment root')
    summary=json.loads((batch/'summary.json').read_text(encoding='utf-8'))
    completed={r['seed'] for r in summary['runs']}
    pending=[seed for seed in summary['planned_seeds'] if seed not in completed]
    seed=pending[0] if pending else summary['planned_seeds'][-1]
    if type(seed) is not int:raise ValueError('Invalid evaluation seed')
    run=batch/str(seed);status=run/'status.json'
    status=json.loads(status.read_text(encoding='utf-8')) if status.is_file() else {}
    public={'planned':len(summary['planned_seeds']),'completed':len(summary['runs']),
            'successes':sum(bool(r['success']) for r in summary['runs']),'complete':summary['complete'],
            'seed':seed,'step':status.get('step',0),'phase':status.get('phase','starting')}
    return public,run/'wrist.png'
