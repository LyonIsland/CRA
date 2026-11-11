"""CPU integration checks using real BRICKLAB generation; not robot success."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from bricklab_paths import ROOT, BRICKLAB
from bricklab_prepare import prepare
from bricklab_task import load_manual, load_scene


class BricklabChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        cls.wall=ROOT/'assets/manuals/bricklab_camera_wall/model.json'
        cls.results={}
        for mode in ['steps','structure','lego']:
            cls.results[mode]=prepare(cls.wall,cls.root/mode,mode)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_three_modes_and_instruction_isolation(self):
        for mode,result in self.results.items():
            task=Path(result['task'])
            pages=load_manual(task)
            scene=load_scene(task)
            self.assertEqual(len(pages),result['pages'])
            self.assertEqual(len(scene['parts']),6)
            self.assertFalse(result['robot_execution_validated'])
            self.assertEqual(set(scene),{'kind','parts','baseplate_studs'})
            with zipfile.ZipFile(task.parent/'policy-inputs.zip') as archive:
                files=[n for n in archive.namelist() if not n.endswith('/')]
                self.assertEqual(len(files),len(pages)+1)
                self.assertTrue(all(n=='manual.pdf' or (n.startswith('pages/') and n.endswith('.png')) for n in files))
            # Poison evaluation-only values. Instruction loading is unaffected.
            (task.parent/'evaluation/manual-page-map.json').write_text('invalid evaluation data',encoding='utf-8')
            self.assertEqual(len(load_manual(task)),len(pages))

    def test_integrity_and_path_escape_rejected(self):
        task=Path(self.results['steps']['task'])
        original=json.loads(task.read_text(encoding='utf-8'))
        forged=copy.deepcopy(original)
        forged['policy_inputs']['page_images'][0]='evaluation/hidden.png'
        changed=task.with_name('forged.json')
        changed.write_text(json.dumps(forged),encoding='utf-8')
        with self.assertRaises(ValueError):load_manual(changed)
        forged=copy.deepcopy(original)
        forged['policy_inputs']['sha256']['policy/manual.pdf']='0'*64
        changed.write_text(json.dumps(forged),encoding='utf-8')
        with self.assertRaises(ValueError):load_manual(changed)

    def test_studio_mpd_import(self):
        result=prepare(BRICKLAB/'studio-bridge/examples/mini-gantry.mpd',self.root/'studio','lego')
        self.assertEqual(result['parts'],12)
        self.assertIsNone(load_scene(result['task'])['baseplate_studs'])
        self.assertTrue(load_manual(result['task']))

    def test_local_browser_api_and_private_files(self):
        from bricklab_server import Handler,LocalGateway
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.gateway=LocalGateway(self.root/'jobs')
        server.grasp_reports=self.root/'grasp-report'
        (server.grasp_reports/'evidence/example').mkdir(parents=True)
        (server.grasp_reports/'index.html').write_text('<h1>Grasp evaluation</h1>')
        (server.grasp_reports/'evidence/example/result.json').write_text('{"success":false}')
        (server.grasp_reports/'evidence/example/evaluation-only.json').write_text('{"positions":[]}')
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        prefix=f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(prefix+'/grasp-report/') as response:
                self.assertIn(b'Grasp evaluation',response.read())
            with urllib.request.urlopen(prefix+'/grasp-report/evidence/example/result.json') as response:
                self.assertFalse(json.load(response)['success'])
            for path in ['evidence/example/evaluation-only.json','../status.json','evidence/%2e%2e/index.html']:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(prefix+'/grasp-report/'+path)
                self.assertEqual(error.exception.code,404)
            with urllib.request.urlopen(prefix) as response:
                page=response.read().decode('utf-8')
                self.assertIn('说明书与纯视觉训练任务',page)
            payload={'source':'web','model':json.loads(self.wall.read_text(encoding='utf-8')),'title':'中文说明书接口测试','manual_mode':'steps'}
            request=urllib.request.Request(prefix+'/api/jobs',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request) as response:job=json.load(response)['job_id']
            deadline=time.monotonic()+60
            while True:
                with urllib.request.urlopen(prefix+'/api/jobs/'+job) as response:state=json.load(response)
                if state['status'] in ('prepared','failed'):break
                if time.monotonic()>deadline:self.fail('Local generation timed out')
                time.sleep(.1)
            self.assertEqual(state['status'],'prepared',state)
            for key in ['manual_url','bundle_url','environment_url']:
                with urllib.request.urlopen(prefix+state[key]) as response:self.assertEqual(response.status,200)
            for path in ['task/evaluation/manual-page-map.json','task/environment/inventory.json','task/task.json','inputs/source.json']:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(prefix+'/files/'+job+'/'+path)
                self.assertEqual(error.exception.code,404)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_live_session_reuse_switch_and_command_boundary(self):
        from bricklab_sessions import LiveSessions
        from camera_commands import validate_command
        class Process:
            def __init__(self):self.code=None
            def poll(self):return self.code
            def wait(self,timeout):self.code=0;return 0
        launches=[]
        def launch(args,**options):
            process=Process();launches.append((args,process));return process
        jobs=self.root/'live-session-unit'
        for name in ['first','second']:
            (jobs/name/'task').mkdir(parents=True)
            (jobs/name/'task/task.json').write_text('{}')
        sessions=LiveSessions(jobs,launcher=launch)
        sessions.start('first');first_runtime=sessions.runtime
        sessions.start('first');self.assertEqual(len(launches),1)
        command=sessions.command('first',{'op':'step','action':[0.1]*7})
        self.assertEqual(command['sequence'],1)
        self.assertEqual(json.loads((first_runtime/'commands/000000001.json').read_text())['action'],[.1]*7)
        for bad in [{'op':'step','action':[2]*7},{'op':'step','action':[0]*7,'object_pose':[0,0,0]},{'op':'reset_objects'}]:
            with self.assertRaises(ValueError):validate_command(bad)
        sessions.start('second')
        self.assertEqual(launches[0][1].poll(),0)
        self.assertEqual(json.loads((first_runtime/'commands/000000002.json').read_text()),{'op':'shutdown'})
        self.assertIn(str(jobs/'second/task/task.json'),launches[1][0])
        with self.assertRaises(ValueError):sessions.command('first',{'op':'pause'})
        sessions.stop('second')


if __name__=='__main__':unittest.main()
