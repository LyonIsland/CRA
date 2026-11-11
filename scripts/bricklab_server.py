"""Local BRICKLAB UI integrated with camera-only task preparation.

Reuses the upstream editor/protocol, replacing its SSH gateway with local
generation. The HTTP file surface excludes inputs, scene specs and evaluation.
"""
import argparse
import html
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import threading
import uuid
from urllib.parse import unquote, urlsplit
from http.server import ThreadingHTTPServer
from bricklab_paths import ROOT, BRICKLAB, upstream, module

upstream()
base = module('_piper_bricklab_gateway', BRICKLAB/'workbench/server.py')
from bricklab_prepare import write_json
base.write_json=write_json


def local_text(text):
    replacements = {
        'BUILD → MANUAL → SIMULATION': 'BUILD → MANUAL → TRAINING',
        '生成网页说明书与仿真': '完成作品，进入机械臂搭建',
        '生成 Studio 说明书与仿真': '完成作品，进入机械臂搭建',
        '说明书与双臂仿真': '说明书与纯视觉训练任务',
        '生成说明书与仿真': '生成说明书并进入搭建',
        '双 Piper 散件环境': '本机纯视觉训练任务',
        '对应的双 Piper 环境': '对应的纯视觉训练任务',
        '查看此作品 Isaac 仿真': '进入机械臂搭建',
        '查看旧快照 Isaac 仿真': '打开旧快照训练任务',
        '查看旧快照仿真': '打开旧快照训练任务',
        '说明书与仿真': '说明书与训练任务',
        '创建环境': '准备零件',
        '创建双臂环境': '准备训练零件',
        '打开仿真': '查看训练任务',
        '查看仿真环境': '查看训练任务',
        '说明书与环境文件已生成': '说明书与训练任务已生成',
        '说明书与环境来自同一份模型。仿真中提供双臂与散件，机械臂装配策略可在后续接入。':
            '说明书与训练零件来自同一份模型。执行策略仅接收说明书图像与单路相机图像，尚未训练装配能力。',
        '说明书、配色与环境来自上方同一份作品快照。仿真中提供双臂与散件，机械臂装配策略可在后续接入。':
            '说明书与训练零件来自上方同一份作品快照。训练场景统一零件材质，取消颜色身份提示；装配能力仍需训练验证。',
    }
    for old,new in replacements.items():text=text.replace(old,new)
    return text


class LocalGateway(base.Gateway):
    def __init__(self,jobs):
        super().__init__({},jobs)
        self.inspection=None
        self.inspection_lock=threading.Lock()
        self.inspections={}
        from bricklab_sessions import LiveSessions
        self.sessions=LiveSessions(self.jobs)

    def state(self,job_id):
        if not base.ID_RE.fullmatch(job_id):raise FileNotFoundError(job_id)
        with self.lock:
            job=self.jobs/job_id
            state=json.loads((job/'status.json').read_text(encoding='utf-8'))
            request=json.loads((job/'request.json').read_text(encoding='utf-8'))
            state.update({k:request[k] for k in ['source','source_label','title','manual_mode','input_sha256','original_filename'] if k in request})
            summary=job/'model-summary.json'
            if summary.is_file():state['model_summary']=json.loads(summary.read_text(encoding='utf-8'))
            if state['status']=='prepared' and (job/'task/task.json').is_file():
                state['environment_url']='/workspace/'+job_id
            return state

    def update(self,job,status,message,progress,**extra):
        with self.lock:
            state=json.loads((job/'status.json').read_text(encoding='utf-8'))
            state.update(status=status,message=message,progress=progress,**extra)
            write_json(job/'status.json',state)
            return state

    def retry(self,job_id):
        import base64
        self.state(job_id)
        job=self.jobs/job_id
        request=json.loads((job/'request.json').read_text(encoding='utf-8'))
        raw=(job/'inputs'/request['filename']).read_bytes()
        payload={'source':request['source'],'title':request['title'],'manual_mode':request['manual_mode']}
        if payload['source']=='web':payload['model']=json.loads(raw)
        else:payload.update(filename=request['filename'],content_base64=base64.b64encode(raw).decode())
        return self.submit(payload)

    def process(self,job):
        from bricklab_prepare import prepare
        try:
            with self.build_lock:
                request=json.loads((job/'request.json').read_text(encoding='utf-8'))
                self.update(job,'preparing','正在本机读取模型与零件',15)
                self.update(job,'manual','正在生成 PDF、页面图像和训练任务',40)
                result=prepare(job/'inputs'/request['filename'],job/'task',request['manual_mode'],request['title'])
                prefix='/files/'+job.name+'/task/'
                self.update(job,'prepared','本作品已准备就绪，点击“进入机械臂搭建”打开对应场景。',100,
                            manual_url=prefix+'policy/manual.pdf',bundle_url=prefix+'policy-inputs.zip',
                            environment_url='/workspace/'+job.name,page_count=result['pages'],
                            warnings=['训练场景所有零件使用相同材质，颜色不作为零件身份。','检查相机与散件不代表完成抓取或搭建。'])
        except Exception as error:
            (job/'error.txt').write_text(str(error),encoding='utf-8')
            self.update(job,'failed','任务生成未完成；可修正模型后重试。',100,error=str(error))

    def inspect(self,job_id):
        state=self.state(job_id)
        if state['status']!='prepared':raise ValueError('先完成任务生成')
        with self.inspection_lock:
            if self.sessions.running():raise ValueError('机械臂搭建场景正在运行，可在该场景直接查看腕部相机。')
            if self.inspection is not None and self.inspection.poll() is None:
                raise ValueError('相机检查仍在运行，请等待完成')
            job=self.jobs/job_id
            runtime=job/'runtime'/uuid.uuid4().hex[:12]
            runtime.mkdir(parents=True)
            write_json(job/'inspection.json',{'directory':runtime.relative_to(job).as_posix()})
            with (runtime/'inspect.log').open('w',encoding='utf-8') as log:
                self.inspection=subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'scripts/workbench.py'),
                    '--task','camera-only','--camera-mode','inspect','--camera-task',str(job/'task/task.json'),
                    '--camera-output',str(runtime),'--headless','--frames','2','--seed','6000'],
                    cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.inspections[job_id]=self.inspection
            return {'started':True}


class Handler(base.Handler):
    def do_GET(self):
        path=unquote(urlsplit(self.path).path)
        if not self.local_request():return self.reply(403,{'error':'仅允许本机访问'})
        if path=='/api/health':return self.reply(200,{'service':'piper-bricklab-local','ok':True})
        fields=path.split('/')
        try:
            if path in ('/grasp-report/progress','/grasp-report/wrist.png'):
                from grasp_reports import progress
                root=getattr(self.server,'grasp_reports',ROOT/'outputs/camera_grasp/reports/latest')
                value,frame=progress(root,ROOT/'outputs/camera_grasp')
                return self.reply(200,value) if path.endswith('/progress') else self.reply(200,frame.read_bytes(),'image/png')
            if path=='/grasp-report' or path.startswith('/grasp-report/'):
                root=getattr(self.server,'grasp_reports',ROOT/'outputs/camera_grasp/reports/latest').resolve()
                relative=PurePosixPath(path.removeprefix('/grasp-report').lstrip('/') or 'index.html')
                pieces=relative.parts
                allowed=pieces in (('index.html',),('physical-evidence.png',))
                allowed=allowed or (len(pieces)==3 and pieces[0]=='evidence' and
                    pieces[1].replace('-','').replace('_','').isalnum() and
                    pieces[2] in ('result.json','summary.json','final.png','wrist-grasp.mp4'))
                target=(root/str(relative)).resolve()
                if not allowed or root not in target.parents:raise FileNotFoundError()
                mime={'.html':'text/html; charset=utf-8','.png':'image/png',
                      '.json':'application/json','.mp4':'video/mp4'}[target.suffix]
                return self.reply(200,target.read_bytes(),mime)
            if path.startswith('/workspace-assets/'):
                name=fields[-1]
                files={'workspace.js':ROOT/'web/bricklab-workspace.js',
                       'editor-bridge.js':ROOT/'web/bricklab-editor-bridge.js',
                       'three.module.js':ROOT/'web/node_modules/three/build/three.module.js',
                       'OrbitControls.js':ROOT/'web/node_modules/three/examples/jsm/controls/OrbitControls.js'}
                if len(fields)!=3 or name not in files:raise FileNotFoundError()
                return self.reply(200,files[name].read_bytes(),'text/javascript; charset=utf-8')
            if path.startswith('/workspace/'):
                if len(fields) not in (3,4) or not base.ID_RE.fullmatch(fields[2]):raise FileNotFoundError()
                job_id=fields[2];state=self.gateway.state(job_id)
                if len(fields)==4:
                    if fields[3]=='status':return self.reply(200,self.gateway.sessions.status(job_id))
                    name={'model':'model.json','wrist.jpg':'wrist.jpg'}.get(fields[3])
                    if name is None:raise FileNotFoundError()
                    target=self.gateway.sessions.asset(job_id,name)
                    return self.reply(200,target.read_bytes(),'image/jpeg' if name.endswith('.jpg') else 'application/json')
                task=json.loads((self.gateway.jobs/job_id/'task/task.json').read_text(encoding='utf-8'))
                text=(ROOT/'web/bricklab-workspace.html').read_text(encoding='utf-8')
                for key,value in {'TITLE':html.escape(state['title']),'JOB_ID':job_id,'PART_COUNT':str(task['part_count'])}.items():
                    text=text.replace('{{'+key+'}}',value)
                return self.reply(200,text.encode('utf-8'),'text/html; charset=utf-8')
            if path.startswith('/training/'):
                if len(fields) not in (3,4) or not base.ID_RE.fullmatch(fields[2]):raise FileNotFoundError()
                job_id=fields[2]
                state=self.gateway.state(job_id)
                job=self.gateway.jobs/job_id
                if len(fields)==4:
                    pointer=job/'inspection.json'
                    runtime=job/json.loads(pointer.read_text(encoding='utf-8'))['directory'] if pointer.is_file() else job/'runtime/not-started'
                    if fields[3]=='status':
                        report=runtime/'run_6000.json'
                        process=self.gateway.inspections.get(job_id)
                        failed=process is not None and process.poll() not in (None,0)
                        return self.reply(200,{'complete':report.is_file(),'failed':failed,'report':json.loads(report.read_text(encoding='utf-8')) if report.is_file() else None})
                    if fields[3]=='frame.png':
                        frame=runtime/'inspect_6000.png'
                        return self.reply(200,frame.read_bytes(),'image/png')
                    raise FileNotFoundError()
                # The review page displays task instructions, never evaluation.
                task=str(job/'task/task.json')
                collect=f'.\\start-camera-only.ps1 -Task "{task}" -Mode collect -Episode ".\\outputs\\camera_only\\demos\\{job_id}.npz" -Group "{job_id}"'
                text=(ROOT/'web/bricklab-task.html').read_text(encoding='utf-8')
                text=text.replace('{{TITLE}}',html.escape(state['title'])).replace('{{JOB_ID}}',job_id)
                text=text.replace('{{COLLECT_COMMAND}}',html.escape(collect))
                return self.reply(200,text.encode('utf-8'),'text/html; charset=utf-8')
            if path.startswith('/files/'):
                if len(fields)<5 or not base.ID_RE.fullmatch(fields[2]):raise FileNotFoundError()
                allowed=(fields[3:5]==['task','policy'] and (fields[5:]==['manual.pdf'] or
                    (len(fields)==7 and fields[5]=='pages' and fields[6].startswith('page-') and fields[6].endswith('.png'))))
                allowed=allowed or fields[3:]==['task','policy-inputs.zip']
                if not allowed:raise FileNotFoundError()
            if fields[1:2]==['view']:raise FileNotFoundError()
            if not path.startswith(('/api/','/files/')):
                relative=path.lstrip('/') or 'index.html'
                target=(BRICKLAB/'source/dist'/relative).resolve()
                if (BRICKLAB/'source/dist').resolve() not in target.parents or not target.is_file():raise FileNotFoundError()
                if target.suffix in ('.html','.js'):
                    text=local_text(target.read_text(encoding='utf-8'))
                    if target.name=='index.html':text=text.replace('</body>','<script src="/workspace-assets/editor-bridge.js" defer></script></body>')
                    return self.reply(200,text.encode('utf-8'),
                                      'text/html; charset=utf-8' if target.suffix=='.html' else 'text/javascript; charset=utf-8')
            return super().do_GET()
        except (OSError,ValueError,KeyError):return self.reply(404,{'error':'找不到任务或允许访问的文件'})

    def do_POST(self):
        path=urlsplit(self.path).path
        fields=path.split('/')
        if len(fields)==4 and fields[1]=='workspace' and base.ID_RE.fullmatch(fields[2]):
            if not self.local_request():return self.reply(403,{'error':'请求来源无效'})
            try:
                job_id=fields[2];self.gateway.state(job_id)
                if fields[3]=='start':
                    if self.gateway.inspection is not None and self.gateway.inspection.poll() is None:
                        raise ValueError('相机检查仍在运行，请等待检查结束。')
                    return self.reply(202,self.gateway.sessions.start(job_id))
                if fields[3]=='stop':return self.reply(200,self.gateway.sessions.stop(job_id))
                if fields[3]=='command':
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=2048:raise ValueError('Invalid command size')
                    command=json.loads(self.rfile.read(length))
                    return self.reply(202,self.gateway.sessions.command(job_id,command))
                raise FileNotFoundError()
            except (ValueError,FileNotFoundError) as error:return self.reply(409,{'error':str(error)})
        if len(fields)==4 and fields[1]=='training' and fields[3]=='inspect':
            if not self.local_request():return self.reply(403,{'error':'请求来源无效'})
            try:return self.reply(202,self.gateway.inspect(fields[2]))
            except (ValueError,FileNotFoundError) as error:return self.reply(409,{'error':str(error)})
        return super().do_POST()


def serve(port=18110,jobs=ROOT/'outputs/bricklab/jobs'):
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.gateway=LocalGateway(jobs)
    print(f'BRICKLAB training platform: http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    finally:server.server_close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=18110)
    args=parser.parse_args()
    serve(args.port)
