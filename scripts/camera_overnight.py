"""Bounded unattended simulation collection and visual pretraining supervisor.

Owns only its child processes. STOP ends collection/training gracefully, with
bounded child timeouts. Never installs or deploys a production robot policy.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]


def write_json(path,value):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    temp.replace(path)


class Supervisor:
    def __init__(self,args):
        self.args=args;self.out=args.out.resolve();self.out.mkdir(parents=True,exist_ok=False)
        self.started=time.time();self.deadline=self.started+args.hours*3600
        self.status={'started_at':datetime.now(timezone.utc).isoformat(),
            'deadline_utc':datetime.fromtimestamp(self.deadline,timezone.utc).isoformat(),
            'pid':os.getpid(),'stage':'starting','round':0,'training_transitions':0,
            'deployable_policy':False,'physical_success_evaluated':False}
        self.sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (ROOT/'scripts').glob('*.py')}
        self.config=vars(args).copy()
        self.config={k:str(v) if isinstance(v,Path) else v for k,v in self.config.items()}
        write_json(self.out/'config.json',{**self.config,'code_sha256':self.sources})
        self.tasks=json.loads(args.tasks.read_text(encoding='utf-8'))
        if not self.tasks['train'] or not self.tasks['validation']:raise ValueError('Missing task lists')
        self.stage('starting')

    def stage(self,name,**fields):
        self.status.update(stage=name,updated_at=datetime.now(timezone.utc).isoformat(),**fields)
        write_json(self.out/'status.json',self.status)
        print(json.dumps(self.status,ensure_ascii=False),flush=True)

    def stopping(self):return (self.out/'STOP').exists() or time.time()>=self.deadline

    def check_resources(self):
        if shutil.disk_usage(self.out).free<8*1024**3:raise RuntimeError('Training drive below 8 GiB free; stopping')
        if shutil.disk_usage(ROOT).free<3*1024**3:raise RuntimeError('Project drive below 3 GiB free; stopping')
        for name,digest in self.sources.items():
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
                raise RuntimeError('Training source changed during run: '+name)

    def child(self,command,log,*,timeout=1800,stop_file=None,final=False):
        self.check_resources()
        log.parent.mkdir(parents=True,exist_ok=True)
        with log.open('w',encoding='utf-8') as handle:
            process=subprocess.Popen([str(x) for x in command],cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.stage(self.status['stage'],child_pid=process.pid,child_log=str(log))
            started=time.time();last=started;stop_at=None
            try:
                while process.poll() is None:
                    now=time.time()
                    if now-started>timeout:raise TimeoutError('Owned training child timed out')
                    if not final and self.stopping():
                        if stop_file is not None:stop_file.parent.mkdir(parents=True,exist_ok=True);stop_file.touch()
                        if stop_at is None:stop_at=now
                        if now-stop_at>45:raise InterruptedError('Stopped after grace period')
                    if now-last>30:
                        self.stage(self.status['stage'],child_elapsed_seconds=round(now-started));last=now
                    time.sleep(.5)
                if process.returncode:raise RuntimeError(f'Child exit {process.returncode}; see {log}')
            finally:
                if process.poll() is None:
                    # Windows venv launchers create a child interpreter. Terminate
                    # only the still-running process tree owned by this Popen.
                    if os.name=='nt':
                        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW,timeout=20)
                    else:process.terminate()
                    process.wait(timeout=20)
                self.status.pop('child_pid',None)

    def collect(self,split,index,task):
        seed={'train':110000,'validation':210000,'test':310000}[split]+index
        target=self.out/'data'/split/f'episode-{seed}'
        self.stage('collect_'+split,collection_seed=seed)
        self.child([ROOT/'.venv/Scripts/python.exe',ROOT/'scripts/workbench.py',
            '--task','camera-only','--camera-mode','explore','--camera-task',task,
            '--camera-output',target,'--headless','--frames',self.args.frames,'--seed',seed],
            self.out/'logs'/f'{split}-{seed}.log',timeout=600,stop_file=target/'STOP')
        report=json.loads((target/'collection.json').read_text())
        if report['mean_pixel_change']<.03:raise RuntimeError('Camera stream too static; data rejected')
        if split=='train':self.status['training_transitions']+=report['transitions']

    def training(self,label,epochs,lr,resume=None):
        output=self.out/'models'/label
        self.stage('training',candidate=label)
        command=[self.args.python,ROOT/'scripts/pretrain_camera.py','--data',self.out/'data','--out',output,
                 '--epochs',epochs,'--lr',lr,'--require-cuda',
                 '--deadline',self.deadline,'--stop-file',self.out/'STOP']
        for task in self.tasks['train']:command+=['--manual-task',task]
        if resume:command+=['--resume',resume]
        self.child(command,self.out/'logs'/(label+'.log'),timeout=3600)
        report=json.loads((output/'report.json').read_text())
        self.stage('validated',best_metrics=report['best_metrics'],checkpoint=str(output/'best.pt'))
        return output,report

    def run(self):
        selected=None;reports=[]
        if os.name=='nt':
            import ctypes
            # Keep the system awake during the explicitly requested overnight
            # run; do not force the display to stay on or change power settings.
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        try:
            # Held-out test data is collected now, but never read for selection.
            for split,count in [('test',4),('validation',4),('train',6)]:
                tasks=list(dict.fromkeys(self.tasks['train']+self.tasks['validation'])) if split=='test' else self.tasks[split]
                for i in range(count):
                    if self.stopping():raise InterruptedError('Stopped before initial dataset completed')
                    self.collect(split,i,tasks[i%len(tasks)])
            for label,lr in [('initial-3e4',3e-4),('initial-1e4',1e-4)]:
                if self.stopping():break
                folder,report=self.training(label,25,lr)
                reports.append({'model':str(folder),'score':report['best_metrics']['selection_score']})
                selected=Path(min(reports,key=lambda x:x['score'])['model'])
                write_json(self.out/'latest.json',{'checkpoint':str(selected/'best.pt'),
                    'encoder':str(selected/'encoder.pt'),'report':str(selected/'report.json')})
            if not reports:raise InterruptedError('No training completed')
            selected=Path(min(reports,key=lambda x:x['score'])['model'])
            next_episode=6
            for round_id in range(1,self.args.max_rounds+1):
                if self.stopping():break
                self.status['round']=round_id
                for _ in range(2):
                    if self.stopping():break
                    self.collect('train',next_episode,self.tasks['train'][next_episode%len(self.tasks['train'])])
                    next_episode+=1
                if self.stopping():break
                selected,report=self.training(f'round-{round_id:03d}',10,max(1e-5,3e-4/(round_id**.5)),selected/'best.pt')
                write_json(self.out/'latest.json',{'checkpoint':str(selected/'best.pt'),
                    'encoder':str(selected/'encoder.pt'),'report':str(selected/'report.json')})
            self.stage('final_test')
            self.child([self.args.python,ROOT/'scripts/pretrain_camera.py','--data',self.out/'data/test',
                        '--out',self.out/'final-test.json','--test-checkpoint',selected/'best.pt'],
                       self.out/'logs/final-test.log',timeout=300,final=True)
            self.stage('stopped' if (self.out/'STOP').exists() else 'completed',checkpoint=str(selected/'best.pt'))
        except BaseException as error:
            self.stage('stopped' if isinstance(error,InterruptedError) else 'failed',error=str(error))
            (self.out/'error.txt').write_text(traceback.format_exc(),encoding='utf-8')
            raise
        finally:
            if os.name=='nt':ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            if selected:
                write_json(self.out/'latest.json',{'checkpoint':str(selected/'best.pt'),
                    'encoder':str(selected/'encoder.pt'),'report':str(selected/'report.json')})
            write_json(self.out/'summary.json',self.status)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--python',type=Path,default=Path('D:/PiperCameraTraining/venv/Scripts/python.exe'))
    parser.add_argument('--tasks',type=Path,required=True)
    parser.add_argument('--hours',type=float,default=7.)
    parser.add_argument('--frames',type=int,default=512)
    parser.add_argument('--max-rounds',type=int,default=96)
    args=parser.parse_args()
    if not 0<args.hours<=12 or args.frames<32 or args.max_rounds<1:parser.error('Invalid bounded run configuration')
    Supervisor(args).run()
