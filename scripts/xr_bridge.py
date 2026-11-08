"""Local WebXR client, Isaac Sim authoritative physics, controller ownership."""
import asyncio
import json
from pathlib import Path
import queue
import threading
import time
import uuid
from collections import deque
import numpy as np
from scipy.spatial.transform import Rotation
from pick_place import Task,ROOT

C=np.array([[0.,-1.,0.],[0.,0.,1.],[1.,0.,0.]])
C4=np.eye(4);C4[:3,:3]=C

def export_geometry(stage):
    from pxr import UsdGeom,Usd
    objects=[];prims=[]
    for prim in Usd.PrimRange.Stage(stage,Usd.TraverseInstanceProxies()):
        path=str(prim.GetPath())
        if '/collisions/' in path or not prim.IsA(UsdGeom.Gprim): continue
        image=UsdGeom.Imageable(prim)
        if image.ComputeVisibility()=='invisible' or image.ComputePurpose()=='guide': continue
        if prim.IsA(UsdGeom.Mesh):
            mesh=UsdGeom.Mesh(prim)
            vertices=np.asarray(mesh.GetPointsAttr().Get(),dtype=float)
            counts=mesh.GetFaceVertexCountsAttr().Get(); indices=mesh.GetFaceVertexIndicesAttr().Get()
            faces=[];start=0
            for count in counts:
                for i in range(1,count-1): faces.append([indices[start],indices[start+i],indices[start+i+1]])
                start+=count
        elif prim.IsA(UsdGeom.Cube):
            half=float(UsdGeom.Cube(prim).GetSizeAttr().Get())/2
            vertices=np.array([[x,y,z] for x in [-half,half] for y in [-half,half] for z in [-half,half]])
            faces=[[0,1,3],[0,3,2],[4,6,7],[4,7,5],[0,4,5],[0,5,1],
                   [2,3,7],[2,7,6],[0,2,6],[0,6,4],[1,5,7],[1,7,3]]
        elif prim.IsA(UsdGeom.Cylinder):
            cylinder=UsdGeom.Cylinder(prim); n=20
            radius=float(cylinder.GetRadiusAttr().Get()); half=float(cylinder.GetHeightAttr().Get())/2
            vertices=np.array([[radius*np.cos(i*2*np.pi/n),radius*np.sin(i*2*np.pi/n),z]
                               for z in [-half,half] for i in range(n)]+[[0,0,-half],[0,0,half]])
            faces=[]
            for i in range(n):
                j=(i+1)%n;faces.extend([[i,j,n+j],[i,n+j,n+i],[2*n,j,i],[2*n+1,n+i,n+j]])
        else: continue
        if vertices.size==0: continue
        color=UsdGeom.Gprim(prim).GetDisplayColorAttr().Get()
        color=list(color[0]) if color else [.70,.73,.78]
        objects.append({'id':len(objects),'name':path,'vertices':np.round(vertices@C.T,7).ravel().tolist(),
                        'triangles':np.array(faces,dtype=int)[:,[0,2,1]].ravel().tolist(),'color':color})
        prims.append(prim)
    return {'protocol':1,'units':'metres','objects':objects},prims

class Broker:
    def __init__(self,model,port):
        self.model=model;self.port=port;self.commands=queue.Queue(maxsize=512)
        self.state={};self.lock=threading.Lock();self.ready=threading.Event();self.stop=False
        self.owner=None;self.error=None
        self.camera_jpeg=None;self.camera_seq=0;self.camera_clients=0
        self.camera_started=0.;self.camera_frames=0;self.camera_error=None
        self.camera_times=deque(maxlen=60)
    def start(self):
        self.thread=threading.Thread(target=lambda:asyncio.run(self.serve()),daemon=True)
        self.thread.start()
        if not self.ready.wait(15): raise RuntimeError('Web server startup timed out')
        if self.error: raise RuntimeError(self.error)
    def publish(self,state):
        with self.lock:self.state=state
    async def serve(self):
        from aiohttp import web,WSMsgType
        root=ROOT/'web'
        async def index(request):
            return web.FileResponse(root/'index.html',headers={'Cache-Control':'no-store'})
        async def geometry(request):return web.json_response(self.model)
        async def health(request):
            with self.lock: state=self.state
            return web.json_response({'protocol':1,'physics':'Isaac Sim / PhysX','controller_connected':self.owner is not None,'state':state})
        async def wrist_image(request):
            with self.lock:data=self.camera_jpeg
            if data is None:raise web.HTTPNotFound(text='Wrist camera not active')
            return web.Response(body=data,content_type='image/jpeg',headers={'Cache-Control':'no-store'})
        async def wrist_stream(request):
            response=web.StreamResponse(headers={'Content-Type':'multipart/x-mixed-replace; boundary=frame',
                'Cache-Control':'no-store, no-cache','X-Content-Type-Options':'nosniff'})
            await response.prepare(request)
            with self.lock:self.camera_clients+=1
            previous=-1
            try:
                while not self.stop:
                    with self.lock:data,seq=self.camera_jpeg,self.camera_seq
                    if data is not None and seq!=previous:
                        await response.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+
                            b'\r\nX-Frame-Sequence: '+str(seq).encode()+b'\r\n\r\n'+data+b'\r\n')
                        previous=seq
                    await asyncio.sleep(.005)
            except (ConnectionError,RuntimeError,asyncio.CancelledError):pass
            finally:
                with self.lock:self.camera_clients-=1
            return response
        async def manual(request):return web.FileResponse(ROOT/'assets/manuals/step_wall6/manual.html',headers={'Cache-Control':'no-store'})
        async def manual_pdf(request):return web.FileResponse(ROOT/'assets/manuals/step_wall6/manual.pdf')
        async def assembly_page(request):return web.FileResponse(root/'assembly.html',headers={'Cache-Control':'no-store'})
        async def assembly_observations(request):
            folder=ROOT/'outputs/assembly'
            seeds=sorted(int(p.stem.split('_')[-1]) for p in folder.glob('observation_*.json'))
            return web.json_response(seeds)
        async def assembly_live_status(request):
            with self.lock:state=self.state
            return web.json_response({'available':'assembly_targets' in self.model,
                'state':state.get('assembly'),'agent':state.get('assembly_agent'),
                'overview':state.get('assembly_overview'),'robot_mode':state.get('mode'),
                'physical_assembly_completed':False})
        async def assembly_plan(request):
            origin=request.headers.get('Origin')
            if origin and origin!=f'{request.scheme}://{request.host}':raise web.HTTPForbidden()
            from assembly_agent import InstructionAgent
            from assembly_scene import CAPABILITIES
            try:
                body=await request.json();seed=int(body['seed'])
                path=ROOT/f'outputs/assembly/observation_{seed}.json'
                if not path.exists():raise web.HTTPNotFound()
                observation=json.loads(path.read_text());agent=InstructionAgent();agent.observe(observation)
                prefix_path=ROOT/f'outputs/assembly/prefix_pick_{seed}.json'
                return web.json_response({'observation':observation,'plan':agent.next_plan(CAPABILITIES),
                    'overview':agent.conditional_overview(),
                    'pick_prefix_test':json.loads(prefix_path.read_text()) if prefix_path.exists() else None,
                    'execution':{'available':False,'mode':'planning_snapshots_only',
                        'completed_instruction_steps':0,'total_instruction_steps':len(agent.recipe['steps']),
                        'reason':'No complete instruction-to-robot assembly executor is connected; capability flags describe unimplemented skills, not a user permission switch.',
                        'missing_capabilities':[name for name,available in CAPABILITIES.items() if not available]},
                    'physical_assembly_completed':False})
            except (ValueError,KeyError) as error:raise web.HTTPBadRequest(text=str(error))
        async def assembly_image(request):
            try:seed=int(request.query['seed']);view=int(request.query['view'])
            except (ValueError,KeyError):raise web.HTTPBadRequest()
            if not 0<=view<7:raise web.HTTPBadRequest()
            path=ROOT/f'outputs/assembly/seed_{seed}_view_{view}.png'
            if not path.exists():raise web.HTTPNotFound()
            return web.FileResponse(path)
        async def assembly_prefix_image(request):
            try:seed=int(request.query['seed'])
            except (ValueError,KeyError):raise web.HTTPBadRequest()
            path=ROOT/f'outputs/assembly/prefix_pick_{seed}.png'
            if not path.exists():raise web.HTTPNotFound()
            return web.FileResponse(path)
        async def websocket(request):
            origin=request.headers.get('Origin')
            if origin and origin!=f'{request.scheme}://{request.host}': raise web.HTTPForbidden()
            if self.owner is not None: raise web.HTTPConflict(text='A controller is already connected')
            ws=web.WebSocketResponse(max_msg_size=8192,heartbeat=10)
            await ws.prepare(request)
            client=uuid.uuid4().hex;self.owner=client
            self.commands.put_nowait({'event':'connect','client':client})
            async def push():
                previous=-1
                while not ws.closed:
                    with self.lock: state=self.state
                    if state and state['seq']!=previous:
                        await ws.send_json(state);previous=state['seq']
                    await asyncio.sleep(.02)
            sender=asyncio.create_task(push())
            try:
                async for message in ws:
                    if message.type==WSMsgType.TEXT:
                        try:
                            cmd=json.loads(message.data)
                            if isinstance(cmd,dict) and self.commands.qsize()<500:
                                self.commands.put_nowait({'event':'command','client':client,'command':cmd})
                        except (ValueError,queue.Full):pass
            finally:
                sender.cancel(); self.owner=None
                try:self.commands.put_nowait({'event':'disconnect','client':client})
                except queue.Full:pass
            return ws
        app=web.Application()
        app.router.add_get('/',index);app.router.add_get('/model',geometry)
        app.router.add_get('/health',health);app.router.add_get('/ws',websocket)
        app.router.add_get('/wrist.jpg',wrist_image)
        app.router.add_get('/wrist.mjpeg',wrist_stream)
        app.router.add_get('/manual',manual);app.router.add_get('/manual.pdf',manual_pdf)
        app.router.add_get('/assembly',assembly_page);app.router.add_get('/assembly/api/observations',assembly_observations)
        app.router.add_get('/assembly/api/live',assembly_live_status)
        app.router.add_post('/assembly/api/plan',assembly_plan);app.router.add_get('/assembly/api/image',assembly_image)
        app.router.add_get('/assembly/api/prefix-image',assembly_prefix_image)
        app.router.add_static('/static/',root)
        app.router.add_static('/vendor/',root/'node_modules/three/build')
        runner=web.AppRunner(app,access_log=None)
        try:
            await runner.setup();await web.TCPSite(runner,'127.0.0.1',self.port).start()
            self.ready.set()
            while not self.stop:await asyncio.sleep(.1)
        except Exception as error:
            self.error=str(error);self.ready.set()
        finally:await runner.cleanup()

class XRSession:
    def __init__(self,app,world,robot,brick,stage,seed=1000,wrist_vision=False,tabletop=False):
        self.task=Task(app,world,robot,brick,stage);self.task.reset(seed)
        self.seed=seed;self.mode='ready';self.message='Start robot delivery, then pick up the delivered brick.'
        self.holding=False;self.hand=np.zeros(3);self.hand_rotation=np.eye(3)
        self.offset=np.zeros(3);self.rotation_offset=np.eye(3)
        self.last_hand=0.;self.last_seq=-1;self.client=None;self.result={}
        self.policy=None
        if (ROOT/'outputs/policy.npz').exists():
            from policy import Policy
            self.policy=Policy(ROOT/'outputs/policy.npz')
        from isaacsim.core.prims import RigidPrim
        self.force_view=RigidPrim(prim_paths_expr='/World/Brick',name='human_force')
        self.force_view.initialize(world.physics_sim_view)
        self.events=[]
        self.visual=None;self.sensor=None;self.tabletop=tabletop;self.workspace=[];self.peak=.0048;self.lift_contacts=0
        if tabletop:
            from tabletop import workspace_points,setup,TabletopController,SETTINGS
            from wrist_vision import WristRGB
            self.workspace=workspace_points(self.task.kin)
            setup(self.task,[.22,-.18],SETTINGS['default_goal'])
            self.force_view.initialize(world.physics_sim_view)
            self.sensor=WristRGB(world);self.visual=TabletopController(self.task,self.sensor,self.task.goal)
            self.message='点击开始寻找；可随机摆放或点击可操作区域摆放积木。'
        elif wrist_vision:
            from wrist_vision import WristRGB,VisualController
            self.sensor=WristRGB(world);self.visual=VisualController(self.task,self.sensor)
    def release(self):self.holding=False
    def reset(self):
        if self.tabletop:
            from tabletop import setup,TabletopController
            self.release();setup(self.task,[.22,-.18],self.task.goal)
            self.force_view.initialize(self.task.world.physics_sim_view)
            self.visual=TabletopController(self.task,self.sensor,self.task.goal)
            self.mode='ready';self.result={};self.message='工作台已重置，点击开始寻找。';return
        self.release();self.task.reset(self.seed)
        self.force_view.initialize(self.task.world.physics_sim_view)
        self.mode='ready';self.result={};self.message='Reset. Robot is ready.'
        if self.sensor:
            from wrist_vision import VisualController
            self.visual=VisualController(self.task,self.sensor)
    def event(self,event):
        kind=event.get('event');client=event.get('client')
        if kind=='connect':self.client=client;self.last_seq=-1;return
        if client!=self.client:return
        if kind=='disconnect':
            self.release();self.mode='paused';self.message='Client disconnected. Reconnect and reset.';return
        cmd=event.get('command',{});seq=cmd.get('seq')
        if not isinstance(seq,int) or seq<=self.last_seq:return
        self.last_seq=seq;op=cmd.get('op')
        self.events.append({'wall_time':time.time(),'op':op,'command':cmd})
        if op in ['place','randomize','goal'] and self.tabletop and self.mode!='robot':
            from tabletop import setup,admitted,TabletopController
            if op=='randomize':
                choices=[p for p in self.workspace if np.linalg.norm(np.asarray(p)-self.task.goal[:2])>.07]
                xy=np.array(choices[np.random.default_rng().integers(len(choices))])
            else:
                position=np.asarray(cmd.get('position',[]),dtype=float)
                if position.shape!=(3,) or not np.isfinite(position).all():return
                xy=(C.T@position)[:2]
            if not admitted(self.task.kin,xy):
                self.message='该位置超出当前机械臂可抓取区域，请选择标示区域。';return
            self.release()
            if op=='goal':
                from pxr import UsdGeom,Gf
                self.task.goal=np.r_[xy,.0048]
                UsdGeom.Xformable(self.task.stage.GetPrimAtPath('/World/Goal')).GetOrderedXformOps()[0].Set(Gf.Vec3d(float(xy[0]),float(xy[1]),.0005))
            else:
                setup(self.task,np.r_[xy,.0048],self.task.goal)
                self.force_view.initialize(self.task.world.physics_sim_view)
            self.visual=TabletopController(self.task,self.sensor,self.task.goal)
            self.mode='ready';self.result={};self.message='位置已设置。开始时保留当前积木位置，并用相机重新寻找。'
        elif op=='reset':self.reset()
        elif op=='start' and (self.mode=='ready' or (self.tabletop and self.mode in ['human','paused'])) and not self.holding:
            if self.tabletop:
                from tabletop import TabletopController
                self.visual=TabletopController(self.task,self.sensor,self.task.goal)
                self.peak=.0048;self.lift_contacts=0;self.mode='robot';self.message='开始视觉搜索。';return
            if self.visual:
                try:self.visual.update()
                except RuntimeError as error:
                    self.mode='paused';self.message=str(error);return
            if self.visual or np.linalg.norm(self.task.object-self.task.source)<.005:
                self.mode='robot';self.message='Robot delivering. Human pickup unlocks after retreat.'
            else:self.message='The source brick moved. Reset before starting this baseline.'
        elif op=='pause':
            self.release();self.mode='paused_robot' if self.mode in ['robot','paused_robot'] else 'paused';self.message='Paused.'
        elif op=='resume' and self.mode=='paused_robot':self.mode='robot'
        elif op=='hand':
            p=np.asarray(cmd.get('position',[]),dtype=float)
            if p.shape!=(3,) or not np.isfinite(p).all():return
            p=C.T@p
            if np.any(p<[-.4,-.6,-.02]) or np.any(p>[.8,.6,.6]):return
            self.hand=p;self.last_hand=time.monotonic()
            q=np.asarray(cmd.get('rotation',[0,0,0,1]),dtype=float)
            if q.shape==(4,) and np.isfinite(q).all() and np.linalg.norm(q)>.5:
                self.hand_rotation=C.T@Rotation.from_quat(q).as_matrix()@C
        elif op=='grab' and self.mode in ['ready','human']:
            if time.monotonic()-self.last_hand<.25 and np.linalg.norm(self.hand-self.task.object)<.045:
                self.holding=True;self.mode='human';self.offset=self.task.object-self.hand
                _,q=self.task.brick.get_world_pose()
                self.rotation_offset=self.hand_rotation.T@Rotation.from_quat(np.r_[q[1:],q[0]]).as_matrix()
                self.message='Human holding brick. Release grip to drop.'
            else:self.message='Move the right controller within 4.5 cm of the brick.'
        elif op=='release':self.release();self.message='Human released the brick.'
    def tick(self):
        task=self.task
        if self.mode=='robot':
            if self.tabletop:
                try:
                    self.visual.step()
                except RuntimeError as error:self.visual.fail(str(error))
                self.message=self.visual.message
                pos=task.object;self.peak=max(self.peak,float(pos[2]))
                self.lift_contacts+=int(pos[2]>.04 and self.visual.contacts())
                self.result={'success':False}
                if self.visual.done:
                    success=not self.visual.failed and self.peak>.055 and self.lift_contacts>=5 and np.linalg.norm(pos[:2]-task.goal[:2])<.012 and .002<pos[2]<.012
                    self.result={'success':bool(success)};self.mode='human' if success else 'paused'
                    self.message='已找到并搬运至指定位置，可人工接取。' if success else self.visual.message
                return
            if self.visual:
                try:
                    action=self.visual.action()
                except RuntimeError as error:
                    self.release();self.mode='paused';self.message=str(error);return
            else:action=self.policy(task.observation()) if self.policy else task.expert()
            self.result=task.step(action)
            if task.steps>=sum(__import__('pick_place').DURATIONS):
                self.mode='human' if self.result['success'] else 'paused'
                self.message='Delivery complete. Pick up the brick.' if self.result['success'] else 'Delivery failed. Reset.'
        elif self.mode not in ['paused','paused_robot']:
            if self.holding and time.monotonic()-self.last_hand>.25:
                self.release();self.message='Hand input timed out; grab released.'
            for _ in range(20):
                if self.holding:
                    target=np.clip(self.hand+self.offset,[-.3,-.5,.007],[.7,.5,.5])
                    force=25*(target-task.object)-.15*task.brick.get_linear_velocity()
                    force*=min(1.,.6/(np.linalg.norm(force)+1e-9))
                    _,q=task.brick.get_world_pose();rot=Rotation.from_quat(np.r_[q[1:],q[0]]).as_matrix()
                    error=Rotation.from_matrix((self.hand_rotation@self.rotation_offset)@rot.T).as_rotvec()
                    torque=.0008*error-.00003*task.brick.get_angular_velocity()
                    torque*=min(1.,.002/(np.linalg.norm(torque)+1e-9))
                    self.force_view.apply_forces_and_torques_at_pos(forces=np.array([force],dtype=np.float32),torques=np.array([torque],dtype=np.float32))
                task.world.step(render=False)

def run(app,world,robot,brick,stage,viewport,args):
    from pxr import UsdGeom
    model,prims=export_geometry(stage)
    if args.assembly_live:
        if args.assembly_clutter:
            from clutter_session import ClutterSession
            session=ClutterSession(app,world,robot,brick,stage,args)
        else:
            from live_assembly import LiveAssemblySession
            session=LiveAssemblySession(app,world,robot,brick,stage,args)
    else:session=XRSession(app,world,robot,brick,stage,args.seed,args.wrist_vision,args.tabletop)
    if session.tabletop or args.assembly_live:model['workspace']={'points':session.workspace,'cell_size_m':.027}
    if args.assembly_live:
        from assembly_agent import target_pose
        from concept_connectors import FIXTURE_ORIGIN
        model['assembly_targets']=[{'id':s['id'],'color':s['part']['color'],
            'position':(C@(FIXTURE_ORIGIN+np.array(target_pose(session.agent.recipe,s)['position_m']))).tolist()}
            for s in session.agent.recipe['steps']]
    broker=Broker(model,args.port);broker.start()
    folder=ROOT/'outputs/xr_sessions';folder.mkdir(parents=True,exist_ok=True)
    print(json.dumps({'event':'xr_ready','url':f'http://127.0.0.1:{args.port}',
                      'controller':'instruction_concept_assembly' if args.assembly_live else ('wrist_RGB_search_feedback' if session.tabletop else ('wrist_rgb_plus_BC' if session.visual else ('learned_policy' if session.policy else 'expert'))),
                      'objects':len(prims)}),flush=True)
    start=time.monotonic();seq=0;last_image=None;record_last=0.;record_key=None
    try:
        with (folder/f'{time.strftime("%Y%m%d-%H%M%S")}.jsonl').open('w') as record:
            while app.is_running() and (not args.seconds or time.monotonic()-start<args.seconds):
                frame=time.monotonic()
                frame_perf=time.perf_counter()
                for _ in range(100):
                    try:event=broker.commands.get_nowait()
                    except queue.Empty:break
                    try:session.event(event)
                    except (ValueError,TypeError):pass
                session.tick()
                tick_done=time.perf_counter()
                if session.sensor:
                    with broker.lock:preview_active=broker.camera_clients>0
                    if preview_active and time.monotonic()-session.sensor.last_capture_wall_time>=1/15:
                        try:session.sensor.capture(preview=True);broker.camera_error=None
                        except RuntimeError as error:broker.camera_error=str(error)
                    image_data=session.sensor.last_rgb
                    if image_data is not None and image_data is not last_image:
                        import io
                        from PIL import Image
                        last_image=image_data
                        buffer=io.BytesIO();Image.fromarray(image_data).save(buffer,format='JPEG',quality=80)
                        now=time.monotonic()
                        with broker.lock:
                            broker.camera_jpeg=buffer.getvalue();broker.camera_seq+=1
                            if not broker.camera_started:broker.camera_started=now
                            broker.camera_frames+=1
                            broker.camera_times.append(now)
                            while len(broker.camera_times)>2 and now-broker.camera_times[0]>2:broker.camera_times.popleft()
                preview_done=time.perf_counter()
                if seq%2==0:
                    world.render();cache=UsdGeom.XformCache()
                    matrices=[]
                    for prim in prims:
                        matrix=C4@np.asarray(cache.GetLocalToWorldTransform(prim)).T@C4.T
                        matrices.append(matrix.T.ravel().tolist())
                    state={'protocol':1,'seq':seq,'sim_time':float(world.current_time),
                           'mode':session.mode,'message':session.message,'holding':session.holding,
                           'brick':(C@session.task.object).tolist(),'goal':(C@session.task.goal).tolist(),
                           'matrices':matrices,'success':bool(session.result.get('success',False)),
                           'controller':'instruction_concept_assembly' if args.assembly_live else ('wrist_RGB_search_feedback' if session.tabletop else ('wrist_rgb_plus_BC' if session.visual else ('learned_policy' if session.policy else 'expert'))),
                           'wrist_camera':bool(session.visual),'tabletop':session.tabletop,
                           'task_phase':session.visual.phase if session.tabletop else None}
                    if args.assembly_live:
                        state['assembly_live']=True;state['assembly']=session.snapshot()
                        state['assembly_agent']=session.agent.snapshot()
                        state['assembly_overview']=session.agent.conditional_overview()
                        state['task_phase']=state['assembly']['phase']
                    if session.sensor:
                        from wrist_vision import CONFIG,intrinsics
                        camera_prim=stage.GetPrimAtPath(CONFIG['path'])
                        camera_world=np.asarray(cache.GetLocalToWorldTransform(camera_prim)).T
                        eye=camera_world[:3,3];rotation=camera_world[:3,:3]
                        state['wrist_camera_pose']={'position':(C@eye).tolist(),
                            'target':(C@(eye-rotation[:,2])).tolist(),'up':(C@rotation[:,1]).tolist(),
                            'resolution':CONFIG['resolution'],'K':intrinsics().tolist()}
                    if session.sensor:
                        with broker.lock:
                            times=broker.camera_times
                            camera_fps=(len(times)-1)/max(.001,times[-1]-times[0]) if len(times)>1 else 0.
                            if not broker.camera_clients:camera_fps=0.
                            camera_seq=broker.camera_seq
                        state['camera_preview']={'transport':'MJPEG latest-frame stream','target_fps':15,
                            'fps':camera_fps,'sequence':camera_seq,'capture_ms':session.sensor.last_capture_ms,
                            'preview_physics_time_delta_max':session.sensor.preview_time_delta_max,'error':broker.camera_error}
                        state['camera_preview']['loop_profile_ms']={'tick':(tick_done-frame_perf)*1000,
                            'preview':(preview_done-tick_done)*1000,'scene_sync':(time.perf_counter()-preview_done)*1000}
                    _,orientation=brick.get_world_pose()
                    rotation=Rotation.from_quat(np.r_[orientation[1:],orientation[0]]).as_matrix()
                    state['brick_rotation']=Rotation.from_matrix(C@rotation@C.T).as_quat().tolist()
                    broker.publish(state)
                    # Keep full snapshots at phase/command changes and 1 Hz
                    # during motion (10 s idle). Rendering, physics and socket
                    # publishing keep their original frequency; only disk
                    # recording is sampled to avoid multi-GB idle logs.
                    assembly=state.get('assembly',{})
                    key=(state['mode'],state['task_phase'],assembly.get('status'),
                         assembly.get('active_skill'),assembly.get('current_step'),
                         tuple(assembly.get('completed_steps',[])))
                    now=time.monotonic();interval=1. if session.mode=='robot' else 10.
                    if key!=record_key or session.events or now-record_last>=interval:
                        record.write(json.dumps({'state':state,'events':session.events})+'\n')
                        record_last=now;record_key=key
                    session.events=[]
                seq+=1
                time.sleep(max(0,.02-(time.monotonic()-frame)))
    finally:
        broker.stop=True;broker.thread.join(timeout=3)
