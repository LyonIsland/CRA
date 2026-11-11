"""Export readable research evidence alongside the full release archives."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--training-root',type=Path,default=Path('D:/PiperCameraTraining'))
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    provenance=[]
    def copy(source,target):
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        provenance.append({'path':target.relative_to(args.out).as_posix(),
                           'source':str(source),'bytes':target.stat().st_size,
                           'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    grasp=ROOT/'outputs/camera_grasp'
    for path in sorted(grasp.rglob('*')):
        if not path.is_file() or 'reports' in path.relative_to(grasp).parts:continue
        if path.suffix in ('.json','.py','.log','.mp4') or path.name in ('0000-start.png','final.png'):
            copy(path,args.out/'evidence/camera_grasp'/path.relative_to(grasp))
    # Training metadata/logs are readable in Git; all images, transitions and
    # checkpoints remain lossless in the camera-training release archive.
    for directory,dirs,names in __import__('os').walk(args.training_root):
        dirs[:]=[d for d in dirs if d not in ('venv','__pycache__')]
        for name in names:
            path=Path(directory)/name
            if path.suffix in ('.json','.log','.txt'):
                copy(path,args.out/'evidence/camera_training'/path.relative_to(args.training_root))
    for source,label in [(grasp/'reports/latest','grasp'),(ROOT/'outputs/camera_only/reports/night-20261111','pretraining')]:
        for path in source.rglob('*'):
            if path.is_file() and path.name!='progress-source.json':copy(path,args.out/'reports'/label/path.relative_to(source))
    static=args.out/'reports/grasp/index.html'
    if static.exists():
        text=static.read_text(encoding='utf-8')
        text=re.sub(r'<script>.*?</script>','',text,flags=re.S)
        text=re.sub(r'<section><h2>当前批次监控</h2>.*?</section>','',text,flags=re.S)
        static.write_text(text,encoding='utf-8')
        for record in provenance:
            if record['path']=='reports/grasp/index.html':
                record.update(sha256=hashlib.sha256(static.read_bytes()).hexdigest(),bytes=static.stat().st_size,
                              transformation='static copy: remove localhost-only live monitor')
    summary=json.loads((grasp/'frozen-eval-v1/summary.json').read_text(encoding='utf-8'))
    for name,digest in summary['sources'].items():
        source=ROOT/'scripts'/name
        if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:raise ValueError('Frozen source changed: '+name)
        copy(source,args.out/'frozen-source'/name)
    runs=[]
    candidates={p.parent for p in grasp.rglob('result.json') if 'reports' not in p.relative_to(grasp).parts}
    candidates|={p.parent for p in grasp.rglob('0000-start.png') if 'reports' not in p.relative_to(grasp).parts}
    for run in sorted(candidates):
        result=run/'result.json';value=json.loads(result.read_text()) if result.is_file() else {}
        name=run.relative_to(grasp).as_posix()
        group=('independent' if name.startswith('frozen-eval-v1/') else 'mechanical_control' if name.startswith('paired-control-')
               else 'online_negative' if name.startswith('negative-') else 'development')
        reason=value.get('failure_reason','')
        trace=run/'trace.json'
        if not reason and trace.is_file():
            events=json.loads(trace.read_text())
            if events:reason=events[-1].get('visual',{}).get('error','')
        runs.append({'run':name,'group':group,'seed':value.get('seed'),'success':value.get('success'),
                     'phase':value.get('controller_result','missing_result'),'steps':value.get('steps'),
                     'peak_lift_mm':1000*max(value.get('peak_lift_m',[0])),
                     'bilateral_hold_seconds':max(value.get('longest_bilateral_hold_seconds',[0])),
                     'stopped':(run/'STOP').exists(),'failure_reason':reason,
                     'policy_sha256':value.get('policy_sha256'),'source_snapshot_available':(run/'policy-source.py').is_file()})
    (args.out/'run-ledger.json').write_text(json.dumps(runs,ensure_ascii=False,indent=2),encoding='utf-8')
    with (args.out/'run-ledger.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(runs[0]));writer.writeheader();writer.writerows(runs)
    (args.out/'evidence-manifest.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'exported_files':len(provenance),'runs':len(runs),'out':str(args.out)}))


if __name__=='__main__':main()
