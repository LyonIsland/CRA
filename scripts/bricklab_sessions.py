"""Own only the Isaac processes started by the BRICKLAB workspace."""
import json
from pathlib import Path
import subprocess
import threading
import time
import uuid
import secrets
from bricklab_paths import ROOT


class LiveSessions:
    def __init__(self,jobs,launcher=subprocess.Popen):
        self.jobs=Path(jobs);self.launcher=launcher;self.lock=threading.RLock()
        self.process=None;self.job_id=None;self.runtime=None;self.sequence=0

    def running(self):return self.process is not None and self.process.poll() is None

    def start(self,job_id):
        with self.lock:
            if self.running():
                if self.job_id==job_id:return self.status(job_id)
                self.stop(self.job_id)
            job=self.jobs/job_id
            task=job/'task/task.json'
            if not task.is_file():raise ValueError('先生成本作品的说明书与任务')
            self.runtime=job/'live'/uuid.uuid4().hex[:12]
            self.runtime.mkdir(parents=True)
            self.job_id=job_id;self.sequence=0
            with (self.runtime/'process.log').open('w',encoding='utf-8') as log:
                self.process=self.launcher([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'scripts/workbench.py'),
                    '--task','camera-only','--camera-mode','live','--camera-task',str(task),
                    '--camera-output',str(self.runtime),'--policy',str(ROOT/'outputs/camera_only/manual-policy.pt'),
                    '--headless','--seed',str(secrets.randbelow(2**31))],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            return self.status(job_id)

    def status(self,job_id):
        with self.lock:
            if job_id!=self.job_id or self.runtime is None:
                return {'mode':'not_started','message':'点击进入机械臂场景，加载本作品的零件。','policy_available':False}
            path=self.runtime/'live.json'
            value=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {
                'mode':'starting','message':'正在启动本作品的 Isaac 机械臂场景…','policy_available':False}
            if self.process.poll() is not None and not value.get('closed'):
                value.update(mode='failed',message='场景进程已退出，请查看本次运行日志。',closed=True)
            value['job_id']=job_id
            return value

    def asset(self,job_id,name):
        if job_id!=self.job_id or self.runtime is None or name not in ('model.json','wrist.jpg'):
            raise FileNotFoundError(name)
        return self.runtime/name

    def command(self,job_id,command):
        from camera_commands import validate_command
        validate_command(command)
        with self.lock:
            if self.job_id!=job_id or not self.running():raise ValueError('先打开本作品的机械臂场景')
            if command['op']=='start_policy' and not (ROOT/'outputs/camera_only/manual-policy.pt').is_file():
                raise ValueError('尚无训练好的说明书策略，请先采集示范并训练。')
            self.sequence+=1
            path=self.runtime/'commands'/f'{self.sequence:09d}.json'
            path.parent.mkdir(exist_ok=True)
            temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps(command,allow_nan=False),encoding='utf-8');temporary.replace(path)
            return {'accepted':True,'sequence':self.sequence}

    def stop(self,job_id):
        with self.lock:
            if job_id!=self.job_id:return {'stopped':True}
            if self.running():
                self.command(job_id,{'op':'shutdown'})
                try:self.process.wait(timeout=25)
                except subprocess.TimeoutExpired:raise ValueError('原机械臂场景正在退出，请稍后再切换作品。')
            return {'stopped':True}
